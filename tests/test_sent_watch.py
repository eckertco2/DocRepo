"""T-mails captured when they're sent (the knowledge base's stage K8, release C, as release 5.123; KB decisions 42 to 45),
with a fake Outlook whose Sent Items gains emails; and, since release 5.141, a new T-mail Outlook wouldn't let DocRepo tag,
known by its draft (the design workspace's docs/mods/email-progress-plan.md, decision 582). Every email and ID here is
made up."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from docrepo import capacity, conversations, db, diagnose, msg, sent_watch
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.outlook import DraftState, SendSeen, SentCopy
from docrepo.sample import load_sample
from msg_builder import FakeEmail, build

AT = datetime(2026, 10, 8, 9, 0)
SETTINGS = Settings(me="P001")
RIGGING, REACTOR = "T000012", "T000001"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")
OTHER = bytes.fromhex("11111111222222223333333344444444")


def index(guid: bytes = GUID, replies: int = 0) -> str:
    raw = b"\x01" + bytes.fromhex("D9A1B2C3D4") + guid + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))
    return raw.hex().upper()


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


class FakeOutlook:
    """The parts of ``docrepo.outlook`` the watcher uses. ``sent`` is Sent Items, newest last; ``copied`` the emails it
    was asked to open."""

    def __init__(self) -> None:
        self.open = True
        self.sent: list[tuple[SentCopy, str]] = []  # (the copy, its subject)
        self.copied: list[str] = []
        self.handler = None
        self.send_handler = None
        self.drafts: dict[str, DraftState] = {}  # a new T-mail's draft, by its EntryID (release 5.141)
        self.looked: list[str] = []  # the drafts looked at
        self.no_send_event = False
        self.marked = 0
        self.fail_sweep = False
        self.problems: list[str] = []

    def outlook_window_open(self) -> bool:
        return self.open

    def connect(self):
        return SimpleNamespace(name="Outlook"), "GetActiveObject"

    def watch_sent(self, app, on_sent):
        self.handler = on_sent
        return object()

    def watch_send(self, app, on_send):
        if self.no_send_event:
            raise OSError("no events")
        self.send_handler = on_send
        return object()

    def draft_state(self, app, entry_id, store_id):
        self.looked.append(entry_id)
        return self.drafts.get(entry_id, DraftState(True))

    def sent_items(self, app):
        return "Sent Items"

    def sent_since(self, folder, since, limit):
        if self.fail_sweep:
            raise OSError("RPC server unavailable")
        return [c for c, _ in reversed(self.sent)][:limit]

    def copy_path(self, fs, root):
        return None

    def copy_sent(self, app, copy, scratch):
        self.copied.append(copy.entry_id)
        subject = next(s for c, s in self.sent if c.entry_id == copy.entry_id)
        e = msg.read(build(FakeEmail(subject=subject, conversation_index=bytes.fromhex(copy.index), message_id=f"<{copy.entry_id}@example.com>",
                                     sent=AT.astimezone())))
        e.entry_id, e.store_id = copy.entry_id, copy.store_id
        return e

    def mark_filed(self, filed, model, colour):
        self.marked += len(filed)
        return len(filed), []

    def record_problem(self, step, error):
        self.problems.append(step)
        return f"{type(error).__name__}"

    # what the owner does in Outlook
    def send(self, idx: str, subject: str, entry: str, sent: datetime = AT) -> SentCopy:
        copy = SentCopy(idx, entry, "S1", subject, sent)
        self.sent.append((copy, subject))
        if self.handler is not None:
            self.handler(copy)
        return copy


def watcher(env, out: FakeOutlook, now: datetime = AT, told: list | None = None, settings: Settings = SETTINGS):
    conn, root, fs = env
    clock = {"now": now}
    told = told if told is not None else []
    w = sent_watch.Watcher(conn, root, fs, settings, lambda: clock["now"], told.append, lambda work: work(), out=out)
    return w, clock, told


def open_t_mail(env, task: str = RIGGING, idx: str | None = None, opened: datetime = AT, kind: str = "new") -> int:
    conn = env[0]
    t = conversations.record_t_mail(conn, task, kind, opened.strftime("%Y-%m-%d %H:%M:%S"), idx or index())
    assert t is not None
    return t


def test_a_sent_t_mail_becomes_one_capture_on_its_task(env):
    conn = env[0]
    out = FakeOutlook()
    tid = open_t_mail(env)
    w, _, told = watcher(env, out)
    assert w.ensure() and w.watching()
    out.send(index(), "Seal delivery", "E1")
    assert len(told) == 1 and told[0].task == RIGGING
    m = Model(conn)
    c = m.captures[told[0].capture]
    assert RIGGING in m.capture_tasks(c) and c.emails and c.emails[0].subject == "Seal delivery"
    assert next(t for t in m.t_mails if t.id == tid).capture == c.id
    assert "Seal delivery" in sent_watch.notice(m, told[0]) and c.id in sent_watch.notice(m, told[0])
    # the sweep, and the event again, see it once more: still one capture
    w.sweep()
    out.handler(out.sent[0][0])
    assert len(told) == 1 and out.copied == ["E1"]
    assert sent_watch.waiting(Model(conn), AT) == []


def test_an_email_that_matches_nothing_is_never_opened(env):
    out = FakeOutlook()
    open_t_mail(env)
    w, _, told = watcher(env, out)
    w.ensure()
    out.send(index(OTHER), "Another conversation", "E2")
    out.send(index(replies=1), "A reply in the same conversation", "E3")  # same key, longer index: not the T-mail itself
    assert told == [] and out.copied == []


def test_a_reply_t_mail_is_matched_by_its_whole_index(env):
    out = FakeOutlook()
    open_t_mail(env, REACTOR, index(OTHER, 2), kind="reply")
    w, _, told = watcher(env, out)
    w.ensure()
    out.send(index(OTHER, 1), "Earlier email", "E4")
    out.send(index(OTHER, 2), "RE: Pump trial", "E5")
    assert [t.task for t in told] == [REACTOR] and out.copied == ["E5"]


def test_the_sweep_finds_a_t_mail_sent_while_docrepo_wasnt_watching(env):
    out = FakeOutlook()
    open_t_mail(env)
    out.send(index(), "Sent while DocRepo was closed", "E6")  # no watch yet: nothing hears it
    w, _, told = watcher(env, out)
    w.tick()  # start-up: joins Outlook and sweeps
    assert len(told) == 1 and w.last_found == 1 and w.last_sweep == AT


def test_outlook_is_left_alone_when_no_t_mail_waits_or_it_is_closed(env):
    out = FakeOutlook()
    w, _, _ = watcher(env, out)
    w.tick()
    assert not w.watching() and out.handler is None
    open_t_mail(env)
    out.open = False
    w.tick()
    assert not w.watching()  # Outlook's window is closed: never started by DocRepo
    out.open = True
    w.tick()
    assert w.watching()


def test_a_t_mail_is_waited_for_14_days(env):
    out = FakeOutlook()
    open_t_mail(env, opened=AT - timedelta(days=15))
    w, _, told = watcher(env, out)
    assert sent_watch.waiting(Model(env[0]), AT) == []
    out.send(index(), "Too late", "E7")
    w.tick()
    assert told == [] and not w.watching()
    open_t_mail(env, idx=index(OTHER), opened=AT - timedelta(days=13))
    assert len(sent_watch.waiting(Model(env[0]), AT)) == 1


def test_a_sweep_that_fails_drops_the_watch_and_joins_again_later(env):
    out = FakeOutlook()
    open_t_mail(env)
    w, clock, told = watcher(env, out)
    w.ensure()
    out.fail_sweep = True
    clock["now"] = AT + timedelta(minutes=6)
    w.tick()
    assert not w.watching() and out.problems
    out.fail_sweep = False
    out.sent.append((SentCopy(index(), "E8", "S1"), "Sent while Outlook restarted"))
    clock["now"] = AT + timedelta(minutes=7)
    w.tick()
    assert w.watching() and len(told) == 1


def test_the_sweep_runs_every_5_minutes_while_a_t_mail_waits(env):
    out = FakeOutlook()
    open_t_mail(env)
    w, clock, _ = watcher(env, out)
    w.tick()
    first = w.last_sweep
    clock["now"] = AT + timedelta(minutes=3)
    w.tick()
    assert w.last_sweep == first
    clock["now"] = AT + timedelta(minutes=5)
    w.tick()
    assert w.last_sweep == AT + timedelta(minutes=5)


def test_mark_filed_emails_marks_the_sent_copy(env):
    out = FakeOutlook()
    open_t_mail(env)
    w, _, told = watcher(env, out, settings=Settings(me="P001", outlook_categories=True))
    w.ensure()
    out.send(index(), "Seal delivery", "E9")
    assert len(told) == 1 and out.marked == 1


def test_a_discarded_task_has_no_waiting_t_mail(env):
    conn = env[0]
    open_t_mail(env)
    with db.transaction(conn):
        conn.execute("UPDATE tasks SET discarded = ? WHERE id = ?", (AT.strftime("%Y-%m-%d %H:%M:%S"), RIGGING))
    assert sent_watch.waiting(Model(conn), AT) == []


# ---- outlook.py's side, with fake COM objects ----
class _Item:
    Class = 43

    def __init__(self, idx: str, entry: str, sent: datetime) -> None:
        self.ConversationIndex, self.EntryID, self.SentOn = idx, entry, sent
        self.Parent = SimpleNamespace(StoreID="S1")

    @property
    def Body(self):  # noqa: N802 - Outlook's name
        raise AssertionError("the sweep must not read an email's body")


class _Items:
    def __init__(self, items: list[_Item]) -> None:
        self.items, self.at = items, 0
        self.sorted = None

    def Sort(self, field, descending):  # noqa: N802
        self.sorted = (field, descending)
        self.items.sort(key=lambda i: i.SentOn, reverse=descending)

    def GetFirst(self):  # noqa: N802
        self.at = 0
        return self.GetNext()

    def GetNext(self):  # noqa: N802
        if self.at >= len(self.items):
            return None
        self.at += 1
        return self.items[self.at - 1]


def test_sent_since_reads_only_the_index_and_place_of_recent_emails():
    from docrepo import outlook

    items = _Items([_Item(index(), "E1", AT + timedelta(minutes=2)), _Item(index(OTHER), "E2", AT - timedelta(days=2)),
                    _Item(index(replies=1), "E3", AT + timedelta(minutes=1))])
    found = outlook.sent_since(SimpleNamespace(Items=items), AT, 400)
    assert items.sorted == ("[SentOn]", True)
    assert [c.entry_id for c in found] == ["E1", "E3"] and (found[0].index, found[0].entry_id, found[0].store_id) == (index(), "E1", "S1")  # E2 is older: the walk stops
    assert len(outlook.sent_since(SimpleNamespace(Items=_Items([_Item(index(), f"E{n}", AT) for n in range(9)])), AT, 4)) == 4


def test_the_event_handler_only_hands_on_the_index_and_place():
    from docrepo import outlook

    heard: list = []
    handler = type("H", (outlook._SentHandler,), {"on_sent": staticmethod(heard.append)})()
    handler.OnItemAdd(_Item(index(), "E1", AT))
    handler.OnItemAdd(SimpleNamespace(Class=26))  # a meeting request: not an email
    assert [(c.index, c.entry_id, c.store_id) for c in heard] == [(index(), "E1", "S1")]


def test_the_report_lists_the_waiting_t_mails_and_the_watch(env, data_root):
    out = FakeOutlook()
    open_t_mail(env, opened=AT - timedelta(hours=3))
    w, _, _ = watcher(env, out)
    lines = w.report()
    assert lines[0].startswith("T-mail 1 (new, on T000012), opened 3 hours ago") and "Watching Sent Items: no" in lines[1]
    assert index()[:8] not in "\n".join(lines)  # the index's layout, never its value
    text = diagnose.build_report(data_root, AT, [], check_outlook=lambda: ([], ""), drops=[], t_mails=lines)
    assert "## T-mails waiting to be sent" in text and "Last sweep: none yet" in text
    assert "Not available from the command line (the running app watches)." in diagnose.build_report(data_root, AT, None, check_outlook=lambda: ([], ""))


def test_a_tick_with_nothing_waiting_builds_no_model(env, monkeypatch):
    """The app ticks every minute: with no T-mail waiting it reads t_mails alone, so it builds no model (and asks Outlook
    nothing). A T-mail opened 15 days ago, or one captured already, isn't waiting."""
    out = FakeOutlook()
    w, clock, _told = watcher(env, out)
    loads: list[int] = []
    init = Model.__init__
    monkeypatch.setattr(Model, "__init__", lambda self, conn: (loads.append(1), init(self, conn))[1])
    w.tick()
    open_t_mail(env, opened=AT - timedelta(days=15))
    w.tick()
    assert loads == [] and out.handler is None
    open_t_mail(env)
    w.tick()
    assert loads and out.handler is not None


# ---- a new T-mail known by its draft (release 5.141, decision 582) ----
NEW = index(OTHER)  # the index Outlook gives the new T-mail when it's sent: a new conversation, no replies


def open_untagged(env, entry: str = "D1", task: str = RIGGING, opened: datetime = AT) -> int:
    """A New T-mail as the corporate computer makes it: Outlook gave it no index and refused DocRepo's, so it's kept with
    no conversation and its draft's place."""
    conn = env[0]
    t = conversations.record_t_mail(conn, task, "new", opened.strftime("%Y-%m-%d %H:%M:%S"), "", untagged=True)
    assert t is not None
    sent_watch.keep_draft(conn, t, entry, "S1")
    return t


def test_a_new_t_mail_is_known_by_its_send_and_captured(env):
    conn = env[0]
    out = FakeOutlook()
    tid = open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Seal drawings")
    w, clock, told = watcher(env, out)
    assert w.ensure() and out.send_handler is not None
    assert [t.id for t in w.waits()] == [tid]
    out.send_handler(SendSeen("D1", "Seal drawings for the trial pump", ""))  # the owner changed the subject, then pressed Send
    d = sent_watch.drafts(conn)[tid]
    assert (d.subject, d.how) == ("Seal drawings for the trial pump", "send") and d.gone
    # A minute later (the owner's delay rule) Outlook files it, with the index it gave it when sending.
    out.drafts.pop("D1")
    out.send(index(OTHER, replies=1), "RE: Seal drawings for the trial pump", "E8", AT + timedelta(minutes=1))  # a reply: not it
    out.send(NEW, "Seal drawings for the trial pump", "E9", AT + timedelta(minutes=1))
    assert len(told) == 1 and told[0].task == RIGGING and out.copied == ["E9"]
    t = next(x for x in Model(conn).t_mails if x.id == tid)
    assert t.capture == told[0].capture and t.conversation == conversations.key(NEW)
    assert sent_watch.drafts(conn) == {}
    # Its replies now find the task, as any T-mail's do.
    answer = msg.read(build(FakeEmail(subject="RE: Seal drawings", conversation_index=bytes.fromhex(index(OTHER, replies=1)),
                                      message_id="<r1@example.com>", sent=AT.astimezone())))
    assert conversations.pick_emails(Model(conn), [answer]).task == RIGGING


def test_without_the_send_event_the_draft_leaving_drafts_is_enough(env):
    conn = env[0]
    out = FakeOutlook()
    out.no_send_event = True
    tid = open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Seal drawings")
    w, clock, told = watcher(env, out)
    assert w.ensure() and w.send_watch is None and "watching Outlook's sends for T-mails (ItemSend)" in out.problems
    assert sent_watch.drafts(conn)[tid].subject == "Seal drawings" and not sent_watch.drafts(conn)[tid].gone
    out.drafts.pop("D1")  # sent while DocRepo looked away
    out.handler = None  # and Sent Items' event missed too
    out.send(NEW, "Seal drawings", "E9", AT + timedelta(minutes=2))
    clock["now"] = AT + timedelta(minutes=1)
    w.tick()  # the draft is gone
    assert sent_watch.drafts(conn)[tid].how == "draft" and told == []
    clock["now"] = AT + timedelta(minutes=6)
    w.tick()  # the sweep
    assert len(told) == 1 and told[0].task == RIGGING
    assert w.report()[0] == "No T-mail is waiting to be sent."


def test_an_index_outlook_gives_the_draft_makes_it_an_ordinary_t_mail(env):
    conn = env[0]
    out = FakeOutlook()
    tid = open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Seal drawings", NEW)
    w, _, told = watcher(env, out)
    w.ensure()
    assert sent_watch.drafts(conn) == {} and next(x for x in Model(conn).t_mails if x.id == tid).conversation_index == NEW
    out.send(NEW, "Seal drawings", "E9")
    assert len(told) == 1


def test_two_sent_emails_with_its_subject_are_left_alone(env):
    out = FakeOutlook()
    tid = open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Weekly numbers")
    w, clock, told = watcher(env, out)
    w.ensure()
    out.send_handler(SendSeen("D1", "Weekly numbers", ""))
    out.drafts.pop("D1")
    out.handler = None  # both filed while DocRepo wasn't listening; the sweep finds two
    out.send(NEW, "Weekly numbers", "E9", AT + timedelta(minutes=1))
    out.send(index(GUID), "Weekly numbers", "E10", AT + timedelta(minutes=2))
    w.sweep()
    assert told == [] and w.unsure == [tid] and out.copied == []
    assert "two sent emails would do" in w.report()[0]


def test_two_new_t_mails_claiming_one_email_are_both_left_alone(env):
    out = FakeOutlook()
    one, two = open_untagged(env, "D1"), open_untagged(env, "D2", task=REACTOR)
    w, _, told = watcher(env, out)
    w.ensure()  # neither draft is found: both gone, with no subject kept
    assert all(d.gone for d in sent_watch.drafts(env[0]).values())
    for t_mail in (one, two):
        sent_watch._save(env[0], t_mail, sent_watch.Draft("D", "S1", "Agenda", AT.strftime("%Y-%m-%d %H:%M:%S"), "draft"))
    out.send(NEW, "Agenda", "E9", AT + timedelta(minutes=1))
    assert told == [] and sorted(w.unsure) == [one, two]


def test_an_email_sent_long_after_isnt_taken_for_it(env):
    out = FakeOutlook()
    open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Seal drawings")
    w, _, told = watcher(env, out)
    w.ensure()
    out.send_handler(SendSeen("D1", "Seal drawings", ""))
    out.send(NEW, "Seal drawings", "E9", AT + timedelta(hours=2))
    out.send(index(GUID), "Seal drawings", "E10", AT - timedelta(minutes=20))  # sent before the send was seen: not it either
    assert told == []


def test_a_draft_no_longer_waiting_is_forgotten(env):
    conn = env[0]
    out = FakeOutlook()
    open_untagged(env, opened=AT - timedelta(days=15))
    w, _, _ = watcher(env, out)
    assert w.waits() == []
    w.watch_drafts()
    assert sent_watch.drafts(conn) == {}


def test_the_report_says_how_a_new_t_mail_will_be_known(env):
    out = FakeOutlook()
    open_untagged(env)
    out.drafts["D1"] = DraftState(False, "Seal drawings")
    w, _, _ = watcher(env, out)
    w.ensure()
    lines = w.report()
    assert lines[0].endswith("known by its draft, still in Drafts") and "Seal drawings" not in "\n".join(lines)
    assert "Watching Outlook's sends, for a new T-mail known by its draft: yes" in lines


def test_draft_state_reads_only_the_subject_and_index():
    from docrepo import outlook

    class Draft:
        Class, Subject, ConversationIndex, Sent, Submitted = 43, "Seal drawings", "", False, False

        @property
        def Body(self):  # noqa: N802 - Outlook's name
            raise AssertionError("the draft watch must not read an email's body")

    class Session:
        def __init__(self, item):
            self.item = item

        def GetItemFromID(self, entry, store=None):  # noqa: N802
            if self.item is None:
                raise outlook_error(0x80020009, 0x8004010F)
            if self.item == "busy":
                raise outlook_error(0x8001010A, 0)
            return self.item

    def outlook_error(code, inner):
        e = Exception(code, "Exception occurred.", (0, "Outlook", "The message you specified cannot be found.", None, 0, inner), None)
        return e

    assert outlook.draft_state(SimpleNamespace(Session=Session(Draft())), "D1", "S1") == DraftState(False, "Seal drawings", "")
    sent = Draft()
    sent.Submitted = True
    assert outlook.draft_state(SimpleNamespace(Session=Session(sent)), "D1", "S1").gone
    assert outlook.draft_state(SimpleNamespace(Session=Session(None)), "D1", "S1") == DraftState(True)
    with pytest.raises(Exception):  # noqa: B017 - Outlook busy is raised, so the draft isn't taken for gone
        outlook.draft_state(SimpleNamespace(Session=Session("busy")), "D1", "S1")


def test_the_send_handler_hands_on_the_entry_subject_and_index_and_never_cancels():
    from docrepo import outlook

    heard: list = []
    handler = type("H", (outlook._SendHandler,), {"on_send": staticmethod(heard.append)})()
    item = _Item("", "D1", AT)
    item.Subject = "Seal drawings"
    assert handler.OnItemSend(item, False) is None  # nothing returned: Cancel is left as it was
    handler.OnItemSend(SimpleNamespace(Class=26), False)  # a meeting request: not an email
    assert heard == [SendSeen("D1", "Seal drawings", "")]


def test_a_new_t_mail_known_by_its_draft_counts_for_the_ticks_quick_look(env):
    """The minute's tick reads t_mails alone first (5.123's fix): an untagged T-mail counts only while its draft is kept."""
    conn = env[0]
    t = conversations.record_t_mail(conn, RIGGING, "new", AT.strftime("%Y-%m-%d %H:%M:%S"), "", untagged=True)
    assert not sent_watch.any_waiting(conn, AT)
    sent_watch.keep_draft(conn, t, "D1", "S1")
    assert sent_watch.any_waiting(conn, AT) and not sent_watch.any_waiting(conn, AT + timedelta(days=15))
    out = FakeOutlook()
    out.drafts["D1"] = DraftState(False, "Seal drawings")
    w, _, _ = watcher(env, out)
    w.tick()
    assert out.handler is not None and out.send_handler is not None and out.looked == ["D1"]
