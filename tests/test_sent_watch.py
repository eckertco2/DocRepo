"""T-mails captured when they're sent (the knowledge base's stage K8, release C, as release 5.123; KB decisions 42 to 45),
with a fake Outlook whose Sent Items gains emails. Every email and ID here is made up."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from docrepo import capacity, conversations, db, diagnose, msg, sent_watch
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.outlook import SentCopy
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
    def send(self, idx: str, subject: str, entry: str) -> SentCopy:
        copy = SentCopy(idx, entry, "S1")
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
    assert [c.entry_id for c in found] == ["E1", "E3"] and found[0] == SentCopy(index(), "E1", "S1")  # E2 is older: the walk stops
    assert len(outlook.sent_since(SimpleNamespace(Items=_Items([_Item(index(), f"E{n}", AT) for n in range(9)])), AT, 4)) == 4


def test_the_event_handler_only_hands_on_the_index_and_place():
    from docrepo import outlook

    heard: list = []
    handler = type("H", (outlook._SentHandler,), {"on_sent": staticmethod(heard.append)})()
    handler.OnItemAdd(_Item(index(), "E1", AT))
    handler.OnItemAdd(SimpleNamespace(Class=26))  # a meeting request: not an email
    assert heard == [SentCopy(index(), "E1", "S1")]


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
