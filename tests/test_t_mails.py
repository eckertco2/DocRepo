"""Release 5.105 (the knowledge base's stage K8: release A's fixes from the corporate computer's first results, and
release B): each email counting on its own (its own capture first, then its conversation, then the email it answers),
a new conversation index in MS-OXOMSG's shape, T-mails kept in ``t_mails``, the newest email of a task, New T-mail and
Reply all with a fake Outlook, and the report's lines that are findings rather than faults. Every email and ID here is
made up."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from docrepo import capacity, conversations, db, diagnose, msg, outlook
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture
from msg_builder import FakeEmail, build

AT = datetime(2026, 10, 8, 9, 0)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, REACTOR = "T000008", "T000012", "T000001"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")
OTHER_GUID = bytes.fromhex("11111111222222223333333344444444")


def index(guid: bytes = GUID, replies: int = 0) -> bytes:
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + guid + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def key_of(guid: bytes = GUID) -> str:
    return guid.hex().upper()


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def email(subject: str = "Crane booking", guid: bytes = GUID, replies: int = 0, message_id: str = "<a1@example.com>",
          in_reply_to: str | None = None, refs: str | None = None, sent: datetime = datetime(2026, 10, 7, 9, 15)) -> EmailItem:
    return msg.read(build(FakeEmail(subject=subject, conversation_index=index(guid, replies), message_id=message_id,
                                    in_reply_to=in_reply_to, refs=refs, sent=sent.astimezone())))


def save_email(env, e: EmailItem, task: str | None, at: datetime = AT) -> str:
    conn, root, fs = env
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="", task=task, files=email_rows(e)[:1]), at)
    assert r.capture_id
    return r.capture_id


# ================= the parts =================
def test_a_new_index_has_ms_oxomsgs_shape_and_a_fresh_key():
    now = datetime(2026, 11, 10, 9, 30, tzinfo=timezone.utc)
    made = conversations.new_index(now)
    assert conversations.well_formed(made) and len(bytes.fromhex(made)) == conversations.HEADER
    assert conversations.replies(made) == 0 and conversations.new_index(now)[12:] != made[12:]  # a new GUID each time
    assert conversations.key(conversations.new_index(now, GUID)) == key_of()
    later = conversations.new_index(datetime(2026, 11, 10, 9, 31, tzinfo=timezone.utc), GUID)
    assert later[2:12] > conversations.new_index(now, GUID)[2:12]  # the time bytes go up
    assert conversations.key(conversations.new_index(datetime(2026, 11, 10, 9, 30))) != ""  # a naive time is local time


def test_message_ids_are_read_from_each_header_shape():
    assert conversations.message_ids("<a@example.com>") == ["<a@example.com>"]
    assert conversations.message_ids(" <a@example.com>\r\n\t<b@example.com> ") == ["<a@example.com>", "<b@example.com>"]
    assert conversations.message_ids("a@example.com") == ["<a@example.com>"]
    assert conversations.message_ids("") == [] and conversations.message_ids("no id here") == []


# ================= the fill, each email on its own =================
def test_two_captured_emails_of_one_conversation_on_two_tasks_fill_nothing(env):
    """The corporate computer's two-task case (2026-11-09): one conversation, an email filed to each of two tasks. By the
    conversation alone both follow its latest filing; each counted with its own capture, they disagree."""
    conn = env[0]
    first, reply = email(), email("Re: crane booking", replies=1, message_id="<a2@example.com>")
    a = save_email(env, first, RIGGING, AT)
    save_email(env, reply, INSTALLATION, datetime(2026, 10, 8, 11, 0))
    m = Model(conn)
    assert conversations.pick(m, [key_of(), key_of()]).task == INSTALLATION  # 5.101's rule, by conversation only
    p = conversations.pick_emails(m, [first, reply])
    assert p.task is None and set(p.mixed) == {RIGGING, INSTALLATION}
    alone = conversations.pick_emails(m, [first])
    assert alone.task == RIGGING and alone.filing.how == "email"
    assert conversations.note(m, alone) == f"This email was filed to {m.tasks[RIGGING].title} on 2026-10-08 ({a}). Pick another task to change it."


def test_an_uncaptured_reply_still_follows_the_conversations_latest_filing(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    save_email(env, email("Re: crane booking", replies=1, message_id="<a2@example.com>"), INSTALLATION, datetime(2026, 10, 8, 11, 0))
    third = email("Re: crane booking", replies=2, message_id="<a3@example.com>")
    p = conversations.pick_emails(Model(conn), [third])
    assert p.task == INSTALLATION and p.filing.how == "conversation"


def test_a_discarded_own_capture_falls_back_to_the_conversation(env):
    conn = env[0]
    first = email()
    a = save_email(env, first, RIGGING, AT)
    save_email(env, email("Re: crane booking", replies=1, message_id="<a2@example.com>"), INSTALLATION, datetime(2026, 10, 8, 11, 0))
    with db.transaction(conn):
        conn.execute("UPDATE captures SET discarded = ? WHERE id = ?", ("2026-10-09 08:00:00", a))
    assert conversations.pick_emails(Model(conn), [first]).task == INSTALLATION


def test_a_reply_with_a_changed_subject_follows_the_email_it_answers(env):
    """Exchange gives a reply whose subject was changed a new conversation index, so its key is unknown; its In-Reply-To
    still names the email it answers."""
    conn = env[0]
    a = save_email(env, email(), RIGGING, AT)
    renamed = email("Crane moved to Thursday", OTHER_GUID, message_id="<b1@example.com>", in_reply_to="<a1@example.com>",
                    refs="<a1@example.com>")
    m = Model(conn)
    p = conversations.pick_emails(m, [renamed])
    assert p.task == RIGGING and p.filing.how == "reply" and p.filing.capture == a
    assert conversations.note(m, p).startswith(f"The email this one answers was filed to {m.tasks[RIGGING].title}")
    # By References alone, from the newest back.
    deeper = email("Crane moved", OTHER_GUID, message_id="<b2@example.com>", refs="<old@example.com> <a1@example.com>")
    assert conversations.pick_emails(m, [deeper]).task == RIGGING
    # Once it's captured, its new conversation follows that task like any other.
    save_email(env, renamed, RIGGING, datetime(2026, 10, 8, 12, 0))
    later = email("Re: Crane moved to Thursday", OTHER_GUID, replies=1, message_id="<b3@example.com>")
    p = conversations.pick_emails(Model(conn), [later])
    assert p.task == RIGGING and p.filing.how == "conversation"


def test_a_known_conversation_wins_over_the_headers(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    save_email(env, email("Reactor inspection", OTHER_GUID, message_id="<r1@example.com>"), REACTOR, AT)
    mixed_up = email("Re: reactor inspection", OTHER_GUID, replies=1, message_id="<r2@example.com>", in_reply_to="<a1@example.com>")
    assert conversations.pick_emails(Model(conn), [mixed_up]).task == REACTOR


def test_an_email_nothing_knows_fills_nothing(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    stranger = email("Hello", OTHER_GUID, message_id="<z1@example.com>", in_reply_to="<nobody@example.com>")
    assert conversations.pick_emails(Model(conn), [stranger]) == conversations.Pick()


# ================= T-mails kept, and the email New T-mail's arrow offers =================
def test_a_t_mail_is_kept_with_its_conversation_and_its_task_follows(env):
    conn = env[0]
    made = conversations.new_index(datetime(2026, 11, 10, 9, 30), GUID)
    tid = conversations.record_t_mail(conn, REACTOR, "new", "2026-11-10 09:30:00", made)
    assert tid is not None
    m = Model(conn)
    t = m.t_mails[-1]
    assert (t.id, t.task, t.kind, t.conversation, t.conversation_index, t.capture) == (tid, REACTOR, "new", key_of(), made, None)
    answer = email("Re: hello", GUID, replies=1, message_id="<c1@example.com>")
    p = conversations.pick_emails(m, [answer])
    assert p.task == REACTOR and "started with a T-mail" in conversations.note(m, p)


def test_a_t_mail_with_no_index_isnt_kept(env):
    conn = env[0]
    assert conversations.record_t_mail(conn, REACTOR, "new", "2026-11-10 09:30:00", "") is None
    assert conn.execute("SELECT count(*) FROM t_mails").fetchone()[0] == 0


def test_a_reply_t_mail_names_the_email_it_answers(env):
    conn = env[0]
    cid = save_email(env, email(), RIGGING, AT)
    whole = index(GUID, 1).hex().upper()
    conversations.record_t_mail(conn, RIGGING, "reply", "2026-11-10 09:30:00", whole, cid, 0)
    t = Model(conn).t_mails[-1]
    assert (t.kind, t.reply_capture, t.reply_pos, t.conversation_index) == ("reply", cid, 0, whole)


def test_the_latest_email_is_the_newest_sent_that_reply_all_can_find(env):
    conn = env[0]
    assert conversations.latest_email(Model(conn), RIGGING) is None  # the sample data captures no email
    older = save_email(env, email(sent=datetime(2026, 10, 5, 8, 0)), RIGGING, datetime(2026, 10, 9, 8, 0))
    newer = save_email(env, email("Re: crane booking", replies=1, message_id="<a2@example.com>", sent=datetime(2026, 10, 30, 8, 0)),
                       RIGGING, datetime(2026, 10, 8, 8, 0))
    m = Model(conn)
    c, e = conversations.latest_email(m, RIGGING)
    assert c.id == newer and e.pos == 0  # by when it was sent, not when it was captured
    with db.transaction(conn):
        conn.execute("UPDATE captures SET discarded = ? WHERE id = ?", ("2026-10-31 08:00:00", newer))
    assert conversations.latest_email(Model(conn), RIGGING)[0].id == older
    with db.transaction(conn):  # an email Reply all can't find, with neither a place nor a .msg, isn't offered
        conn.execute("UPDATE capture_emails SET file = NULL, entry_id = NULL WHERE capture = ?", (older,))
    assert conversations.latest_email(Model(conn), RIGGING) is None


def test_a_replys_task_is_the_one_it_was_clicked_from_when_the_capture_is_on_it(env):
    conn = env[0]
    cid = save_email(env, email(), RIGGING, AT)
    unfiled = save_email(env, email("Loose", OTHER_GUID, message_id="<l1@example.com>"), None)
    m = Model(conn)
    c = m.captures[cid]
    assert conversations.reply_task(m, c) == RIGGING
    assert conversations.reply_task(m, c, RIGGING) == RIGGING and conversations.reply_task(m, c, REACTOR) == RIGGING
    assert conversations.reply_task(m, m.captures[unfiled]) is None


# ================= New T-mail and Reply all, with a fake Outlook =================
class Accessor:
    def __init__(self, owner: Item) -> None:
        self.owner, self.props, self.set = owner, {}, []

    def GetProperty(self, tag):  # noqa: N802 - Outlook's names
        if tag not in self.props:
            raise RuntimeError("property not found")
        return self.props[tag]

    def SetProperty(self, tag, value):  # noqa: N802
        if self.owner.refuse_writes:
            raise RuntimeError("refused")
        self.set.append(tag)
        self.props[tag] = value
        if tag == outlook.PR_CONVERSATION_INDEX:
            self.owner.ConversationIndex = bytes(value).hex().upper()

    def StringToBinary(self, text):  # noqa: N802
        return bytes.fromhex(text)


class Item:
    """A fake Outlook email: ``made`` is its index when it's made, ``on_save`` the one Outlook gives it once saved."""

    def __init__(self, made: str = "", on_save: str = "", refuse_writes: bool = False, display_fails: bool = False) -> None:
        self.ConversationIndex = made  # noqa: N815
        self.on_save, self.refuse_writes, self.display_fails = on_save, refuse_writes, display_fails
        self.PropertyAccessor = Accessor(self)  # noqa: N815
        self.saved = self.displayed = 0
        self.closed: list[int] = []
        self.replies: list[Item] = []

    def Save(self):  # noqa: N802
        self.saved += 1
        if self.on_save:
            self.ConversationIndex = self.on_save

    def Display(self):  # noqa: N802
        if self.display_fails:
            raise RuntimeError("no window")
        self.displayed += 1

    def Close(self, how):  # noqa: N802
        self.closed.append(how)

    def ReplyAll(self):  # noqa: N802
        reply = Item(self.ConversationIndex + "8000000001" if self.ConversationIndex else "")
        self.replies.append(reply)
        return reply


class Session:
    def __init__(self, kept: Item | None = None, shared: Item | None = None) -> None:
        self.kept, self.shared = kept, shared
        self.looked: list[tuple] = []
        self.opened: list[str] = []

    def GetItemFromID(self, *ids):  # noqa: N802
        self.looked.append(ids)
        if self.kept is None:
            raise RuntimeError("not found")
        return self.kept

    def OpenSharedItem(self, path):  # noqa: N802
        self.opened.append(path)
        return self.shared


class App:
    def __init__(self, new: Item | None = None, session: Session | None = None) -> None:
        self.new, self.Session = new, session or Session()  # noqa: N815

    def CreateItem(self, kind):  # noqa: N802
        assert kind == outlook.OL_MAIL_ITEM
        if self.new is None:
            raise RuntimeError("refused")
        return self.new


NOW = datetime(2026, 11, 10, 9, 30)


@pytest.fixture
def outlook_app(monkeypatch):
    holder: dict[str, App] = {}
    monkeypatch.setattr(outlook, "connect", lambda: (holder["app"], "GetActiveObject"))
    return holder


def test_new_t_mail_keeps_the_index_outlook_gives_at_once(outlook_app):
    item = Item(index(GUID).hex().upper())
    outlook_app["app"] = App(item)
    opened = outlook.new_t_mail(NOW)
    assert opened == outlook.Opened(index(GUID).hex().upper(), "made")
    assert (item.saved, item.displayed, item.PropertyAccessor.set) == (0, 1, [])


def test_new_t_mail_saves_to_drafts_when_outlook_gives_none_at_first(outlook_app):
    item = Item("", on_save=index(GUID).hex().upper())
    outlook_app["app"] = App(item)
    opened = outlook.new_t_mail(NOW)
    assert opened.how == "saved" and conversations.key(opened.index) == key_of()
    assert (item.saved, item.displayed, item.PropertyAccessor.set) == (1, 1, [])


def test_new_t_mail_writes_an_index_when_saving_gives_none(outlook_app):
    item = Item("")
    outlook_app["app"] = App(item)
    opened = outlook.new_t_mail(NOW)
    assert opened.how == "written" and conversations.well_formed(opened.index) and conversations.replies(opened.index) == 0
    assert item.PropertyAccessor.set == [outlook.PR_CONVERSATION_INDEX, outlook.PR_CONVERSATION_INDEX_TRACKING]
    assert item.PropertyAccessor.props[outlook.PR_CONVERSATION_INDEX_TRACKING] is True
    assert item.saved == 1 and item.displayed == 1  # the email is never sent: there's no Send to call


def test_new_t_mail_still_opens_when_no_index_can_be_had(outlook_app):
    item = Item("", refuse_writes=True)
    outlook_app["app"] = App(item)
    opened = outlook.new_t_mail(NOW)
    assert opened == outlook.Opened("", "none") and item.displayed == 1


def test_new_t_mail_says_why_when_outlook_refuses(outlook_app):
    outlook_app["app"] = App(None)
    with pytest.raises(outlook.OutlookError, match="didn't make a new email"):
        outlook.new_t_mail(NOW)
    shown = Item("", display_fails=True, refuse_writes=True)
    outlook_app["app"] = App(shown)
    with pytest.raises(outlook.OutlookError, match="didn't open the new email"):
        outlook.new_t_mail(NOW)


def test_reply_all_finds_the_email_by_its_place_first(outlook_app, tmp_path):
    kept = Item(index(GUID).hex().upper())
    session = Session(kept=kept, shared=Item())
    outlook_app["app"] = App(session=session)
    saved = tmp_path / "email.msg"
    saved.write_bytes(b"x")
    opened = outlook.reply_all("E1", "S1", saved)
    assert opened.how == "place" and conversations.within(opened.index, index(GUID).hex().upper())
    assert session.looked == [("E1", "S1")] and session.opened == [] and kept.replies[0].displayed == 1
    assert kept.closed == []  # the original in Outlook is left alone


def test_reply_all_takes_the_saved_msg_when_the_place_fails(outlook_app, tmp_path):
    shared = Item(index(GUID).hex().upper())
    session = Session(kept=None, shared=shared)
    outlook_app["app"] = App(session=session)
    saved = tmp_path / "email.msg"
    saved.write_bytes(b"made-up")
    opened = outlook.reply_all("E1", "", saved)
    assert opened.how == "msg" and session.opened == [str(saved)] and shared.replies[0].displayed == 1
    assert shared.closed == [outlook.OL_DISCARD] and saved.read_bytes() == b"made-up"  # closed without saving: unchanged
    session.looked.clear()
    assert outlook.reply_all("", "", saved).how == "msg" and session.looked == []  # no place kept: straight to the .msg


def test_reply_all_says_so_when_it_has_neither(outlook_app, tmp_path):
    outlook_app["app"] = App(session=Session(kept=None))
    with pytest.raises(outlook.OutlookError, match="couldn't find the email"):
        outlook.reply_all("E1", "S1", tmp_path / "gone.msg")


# ================= the report =================
class Props:
    def __init__(self, props: dict[str, object]) -> None:
        self.props = props

    def GetProperty(self, tag):  # noqa: N802
        return self.props[tag]  # a KeyError for one it hasn't, as Outlook raises


class Mail:
    def __init__(self, props: dict[str, object] | None = None) -> None:
        self.ConversationIndex = index(GUID).hex().upper()  # noqa: N815
        self.ConversationID = key_of()  # noqa: N815
        self.ConversationTopic = "Crane booking"  # noqa: N815
        self.PropertyAccessor = Props(props or {})  # noqa: N815


def test_what_outlook_doesnt_give_is_a_finding_not_a_fault():
    steps = {s.name: s for s in diagnose.identifier_steps(Mail())}
    for name in ("Read its conversation index tracking flag", "Read its Message-ID", "Read its In-Reply-To", "Read its References"):
        assert steps[name].info and "FAILED" not in steps[name].line(), name
    assert steps["Read its conversation index tracking flag"].line() == "not set"
    assert steps["Read its In-Reply-To"].line().startswith("none through Outlook")
    assert steps["Read the email's conversation index (ConversationIndex)"].line().startswith("ok: ")
    got = {s.name: s for s in diagnose.identifier_steps(Mail({outlook.PR_INTERNET_MESSAGE_ID: "<m1@example.com>"}))}
    assert got["Read its Message-ID"].line() == "ok: PropertyAccessor: yes"


def test_the_copys_line_says_which_headers_the_msg_holds():
    whole = email(in_reply_to="<a0@example.com>")
    words = diagnose.copy_words(whole)
    assert "Message-ID yes; In-Reply-To yes; References no" in words and "example.com" not in words


def test_the_written_try_out_reads_the_index_back_and_closes_without_saving():
    item = Item("")
    step = diagnose._written_step(App(item), NOW)
    assert step.ok and "written; Outlook reads back MS-OXOMSG's layout, 22 bytes" in step.result
    assert item.saved == 0 and item.displayed == 0 and item.closed == [outlook.OL_DISCARD]
    refused = Item("", refuse_writes=True)
    step = diagnose._written_step(App(refused), NOW)
    assert not step.ok and refused.closed == [outlook.OL_DISCARD]


def test_a_report_line_is_ok_failed_or_a_finding():
    assert diagnose.Step("a", True, "fine").line() == "ok: fine"
    assert diagnose.Step("a", False, "broke").line() == "FAILED: broke"
    assert diagnose.Step("a", False, "none", info=True).line() == "none"


def test_nothing_here_sends_an_email():
    """DocRepo never sends one (the rules file): no Send in the Outlook or T-mail code."""
    root = Path(__file__).resolve().parent.parent / "docrepo"
    for name in ("outlook.py", "conversations.py", "diagnose.py", "ui/t_mails.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert ".Send(" not in text and ".Send()" not in text, name
