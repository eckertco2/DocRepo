"""Emails that find their task (the knowledge base's stage K8, release 5.101, KB decisions 32 to 34): Outlook's
identifiers read from a .msg, kept with each email, and the task a conversation follows; the backfill from saved .msg
files; the move of 5.93's places into ``capture_emails``; the Message-ID in "captured before"; and the report's lines and
try-outs, with a fake Outlook. Every email and ID here is made up."""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from docrepo import capacity, captures, conversations, db, diagnose, msg, outlook
from docrepo.cli import main
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture
from msg_builder import FakeEmail, build

AT = datetime(2026, 10, 8, 9, 0)
SETTINGS = Settings(me="P001")
INSTALLATION, RIGGING, REACTOR = "T000008", "T000012", "T000001"

GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")
OTHER_GUID = bytes.fromhex("11111111222222223333333344444444")


def index(guid: bytes = GUID, replies: int = 0) -> bytes:
    """A conversation index in MS-OXOMSG's layout: 0x01, the time in 5 bytes, the GUID, then 5 bytes a reply."""
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + guid + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def key_of(guid: bytes = GUID) -> str:
    return guid.hex().upper()


# ---- the key ----
def test_the_key_is_the_guid_in_a_well_formed_index():
    assert conversations.key(index()) == key_of()
    assert conversations.key(index(replies=3)) == key_of()  # every reply keeps the header
    assert conversations.key(index().hex().lower()) == key_of()  # Outlook's hex string, in any case
    assert conversations.replies(index(replies=2)) == 2 and conversations.replies(index()) == 0
    assert conversations.within(index(replies=2), index(replies=1)) and not conversations.within(index(replies=1), index(replies=1))
    assert not conversations.within(index(OTHER_GUID, 1), index())


@pytest.mark.parametrize("bad", [b"", b"\x01" * 21, index() + b"\x00", b"\x02" + index()[1:], "not hex", "ABC"])
def test_an_index_of_another_shape_has_no_key(bad):
    assert conversations.key(bad) == "" and conversations.replies(bad) == -1
    assert "no key" in conversations.layout(bad) or conversations.layout(bad) == "none"


def test_the_layout_in_words_never_holds_the_value():
    words = conversations.layout(index(replies=1))
    assert words == "MS-OXOMSG's layout, 27 bytes: the header and 1 reply" and key_of()[:8] not in words


# ---- reading a .msg ----
def test_a_msg_gives_its_identifiers():
    e = msg.read(build(FakeEmail(conversation_index=index(replies=1), conversation_id=GUID, conversation_topic="Crane booking",
                                 tracking=True, message_id="<a1@example.com>", in_reply_to="<a0@example.com>",
                                 refs="<a0@example.com>\r\n <z9@example.com>")))
    assert e.conversation_index == index(replies=1).hex().upper() and conversations.key(e.conversation_index) == key_of()
    assert (e.conversation_id, e.conversation_topic, e.conversation_tracking) == (key_of(), "Crane booking", True)
    assert (e.message_id, e.in_reply_to, e.refs) == ("<a1@example.com>", "<a0@example.com>", "<a0@example.com> <z9@example.com>")


def test_the_headers_come_from_the_transport_headers_when_their_own_are_missing():
    headers = ("Received: from mail.example.com\r\nMessage-ID: <b2@example.com>\r\nIn-Reply-To: <b1@example.com>\r\n"
               "References: <b0@example.com>\r\n\t<b1@example.com>\r\nSubject: Re: crane\r\n\r\n")
    e = msg.read(build(FakeEmail(message_id="<own@example.com>", headers=headers)))
    assert (e.message_id, e.in_reply_to, e.refs) == ("<own@example.com>", "<b1@example.com>", "<b0@example.com> <b1@example.com>")


def test_a_msg_without_them_gives_none():
    e = msg.read(build(FakeEmail()))
    assert (e.conversation_index, e.message_id, e.conversation_tracking) == ("", "", None)


# ---- saving, and the task a conversation follows ----
@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def email(subject: str = "Crane booking", guid: bytes = GUID, replies: int = 0, message_id: str = "<a1@example.com>",
          entry: str = "", sent: datetime = datetime(2026, 10, 7, 9, 15)) -> EmailItem:
    e = msg.read(build(FakeEmail(subject=subject, conversation_index=index(guid, replies), message_id=message_id,
                                 sent=sent.astimezone())))
    e.entry_id, e.store_id = entry, "S1" if entry else ""
    return e


def save_email(env, e: EmailItem, task: str | None, at: datetime = AT) -> str:
    conn, root, fs = env
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="", task=task, files=email_rows(e)[:1]), at)
    assert r.capture_id
    return r.capture_id


def test_a_save_keeps_each_emails_identifiers_and_place(env):
    conn, root, _ = env
    cid = save_email(env, email(replies=1, entry="E1"), RIGGING)
    c = Model(conn).captures[cid]
    assert (c.emails[0].conversation, c.emails[0].conversation_index) == (key_of(), index(replies=1).hex().upper())
    assert (c.emails[0].message_id, c.emails[0].entry_id, c.emails[0].store_id) == ("<a1@example.com>", "E1", "S1")
    assert captures.email_places(conn, cid) == [("E1", "S1")]
    md = captures.capture_md_path(root, c).read_text(encoding="utf-8")
    listed = json.loads(next(line for line in md.splitlines() if line.startswith("emails: "))[len("emails: "):])
    assert listed[0]["conversation"] == key_of() and listed[0]["message_id"] == "<a1@example.com>"


def test_a_conversation_follows_the_task_it_was_last_filed_to(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    m = Model(conn)
    assert conversations.pick(m, [key_of()]).task == RIGGING
    later = save_email(env, email(replies=1, message_id="<a2@example.com>"), INSTALLATION, datetime(2026, 10, 8, 11, 0))
    m = Model(conn)
    p = conversations.pick(m, [key_of()])
    assert p.task == INSTALLATION and p.filing.capture == later and not p.mixed
    assert f"filed to {m.tasks[INSTALLATION].title} on 2026-10-08 ({later})" in conversations.note(m, p)
    assert conversations.pick(m, [key_of(OTHER_GUID)]).task is None  # a conversation never filed


def test_an_unfiled_capture_teaches_nothing_until_its_filed(env):
    conn = env[0]
    cid = save_email(env, email(), None)
    assert conversations.pick(Model(conn), [key_of()]).task is None
    with db.transaction(conn):
        conn.execute("UPDATE captures SET filed_to = ?, filed = ? WHERE id = ?", (REACTOR, "2026-10-09 08:00:00", cid))
    assert conversations.pick(Model(conn), [key_of()]).task == REACTOR  # File to task teaches it too


def test_a_discarded_task_or_capture_is_skipped(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    newer = save_email(env, email(replies=1, message_id="<a2@example.com>"), INSTALLATION, datetime(2026, 10, 8, 11, 0))
    with db.transaction(conn):
        conn.execute("UPDATE captures SET discarded = ? WHERE id = ?", ("2026-10-08 12:00:00", newer))
    assert conversations.pick(Model(conn), [key_of()]).task == RIGGING
    with db.transaction(conn):
        conn.execute("UPDATE captures SET discarded = NULL WHERE id = ?", (newer,))
        conn.execute("UPDATE tasks SET discarded = ? WHERE id = ?", ("2026-10-08 12:00:00", INSTALLATION))
    assert conversations.pick(Model(conn), [key_of()]).task == RIGGING  # the filing before it counts


def test_a_closed_task_still_fills_and_says_so(env):
    conn = env[0]
    save_email(env, email(), RIGGING)
    with db.transaction(conn):
        conn.execute("UPDATE tasks SET state = 'Closed', closed = '2026-10-08 10:00:00' WHERE id = ?", (RIGGING,))
    p = conversations.pick(Model(conn), [key_of()])
    assert p.task == RIGGING and p.closed


def test_conversations_of_different_tasks_fill_nothing(env):
    conn = env[0]
    save_email(env, email(), RIGGING)
    save_email(env, email("Reactor inspection", OTHER_GUID, message_id="<r1@example.com>"), REACTOR)
    p = conversations.pick(Model(conn), [key_of(), key_of(OTHER_GUID)])
    assert p.task is None and set(p.mixed) == {RIGGING, REACTOR}
    assert conversations.pick(Model(conn), [key_of(), key_of()]).task == RIGGING  # two emails of one conversation


def test_a_t_mail_starts_a_conversation_on_its_task(env):
    conn = env[0]
    save_email(env, email(), RIGGING, AT)
    with db.transaction(conn):
        conn.execute("INSERT INTO t_mails (task, kind, opened, conversation, conversation_index) VALUES (?, 'new', ?, ?, ?)",
                     (REACTOR, "2026-10-08 10:00:00", key_of(), index().hex().upper()))
    p = conversations.pick(Model(conn), [key_of()])
    assert p.task == REACTOR and p.filing.t_mail and "started with a T-mail" in conversations.note(Model(conn), p)


def test_captured_before_matches_on_the_message_id_first(env):
    conn = env[0]
    cid = save_email(env, email(message_id="<a1@example.com>"), RIGGING)
    same_minute = datetime(2026, 10, 7, 9, 15).astimezone().strftime("%Y-%m-%d %H:%M")
    hit = captures.captured_before(conn, "Ann Example", "Renamed by someone", same_minute, "<a1@example.com>")
    assert [c for c, _ in hit] == [cid]
    # Another email with the same sender, subject and minute isn't the same email when both have Message-IDs.
    assert captures.captured_before(conn, "Ann Example", "Crane booking", same_minute, "<other@example.com>") == []
    # With no Message-ID, the old match still finds it.
    assert [c for c, _ in captures.captured_before(conn, "Ann Example", "Crane booking", same_minute)] == [cid]


# ---- the backfill ----
def emptied(conn, cid: str) -> None:
    """As an email captured before release 5.101: its row has no identifiers."""
    with db.transaction(conn):
        conn.execute("UPDATE capture_emails SET " + ", ".join(f"{k} = NULL" for k in conversations.IDENTIFIERS) + " WHERE capture = ?", (cid,))  # noqa: S608 - a column or table name of DocRepo's own; values are parameters


def test_the_backfill_reads_each_saved_msg_and_never_changes_one(env):
    conn, root, _ = env
    cid = save_email(env, email(replies=1), RIGGING)
    emptied(conn, cid)
    c = Model(conn).captures[cid]
    path = captures.capture_folder(root, cid, c.saved) / "email.msg"
    before = path.stat().st_mtime_ns, path.read_bytes()
    dry = conversations.backfill(conn, root, dry_run=True)
    assert (dry.filled, dry.made, dry.keyed) == (1, 0, 1) and Model(conn).captures[cid].emails[0].conversation == ""
    done = conversations.backfill(conn, root)
    assert (done.filled, done.keyed) == (1, 1) and Model(conn).captures[cid].emails[0].conversation == key_of()
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before
    assert conversations.backfill(conn, root).filled == 0  # a second run finds nothing to do


def test_the_backfill_makes_the_rows_of_emails_captured_before_5_74(env):
    conn, root, fs = env
    cid = captures.add_capture(conn, saved="2026-09-01 08:00:00", source="outlook_email", types=["note"], title="Crane booking", task=RIGGING)
    folder = captures.capture_folder(root, cid, "2026-09-01 08:00:00")
    folder.mkdir(parents=True)
    (folder / "email.msg").write_bytes(build(FakeEmail(conversation_index=index())))
    (folder / "email 2.msg").write_bytes(build(FakeEmail(subject="Re: crane booking", conversation_index=index(replies=1))))
    found = conversations.backfill(conn, root)
    assert (found.made, found.keyed) == (2, 2)
    emails = Model(conn).captures[cid].emails
    assert [(e.pos, e.file, e.subject) for e in emails] == [(0, "email.msg", "Crane booking"), (1, "email 2.msg", "Re: crane booking")]
    assert conversations.pick(Model(conn), [key_of()]).task == RIGGING


def test_the_email_ids_command_says_what_it_did(tmp_path, capsys):
    root = tmp_path / "DocRepoData"
    assert main(["--data-root", str(root), "init"]) == 0
    fs = SafeFS([root])
    conn = db.connect(fs, root)
    try:
        load_sample(conn)
        cid = save_email((conn, root, fs), email(), RIGGING)
        emptied(conn, cid)
    finally:
        conn.close()
    capsys.readouterr()
    assert main(["--data-root", str(root), "email-ids", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would give 1 email row" in out and "Nothing was recorded (--dry-run)." in out
    assert main(["--data-root", str(root), "email-ids"]) == 0
    assert "Gave 1 email row" in capsys.readouterr().out


# ---- schema 22: 5.93's places move into capture_emails ----
def test_the_places_release_5_93_kept_move_into_capture_emails():
    import sqlite3

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    db._run(conn, db.SCHEMA)
    for step in range(2, 22):
        db._run(conn, db.MIGRATIONS[step])
    conn.execute("PRAGMA user_version = 21")
    cid = captures.add_capture(conn, saved="2026-11-06 08:00:00", source="outlook_email", types=["note"], title="Crane booking")
    for pos in (0, 1):
        conn.execute("INSERT INTO capture_emails (capture, pos, file, subject, sender, sent) VALUES (?, ?, ?, 'Crane', 'Ann', '')",
                     (cid, pos, "email.msg" if pos == 0 else "email 2.msg"))
    db.set_state(conn, "outlook_places:" + cid, json.dumps([["E1", "S1"], ["", ""]]))
    db.set_state(conn, "outlook_places:C999999", "not json")  # a damaged entry doesn't stop the upgrade
    db.set_state(conn, "last_daily", "2026-11-06")
    db._ensure_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert captures.email_places(conn, cid) == [("E1", "S1"), ("", "")]
    assert [r[0] for r in conn.execute("SELECT key FROM app_state ORDER BY key")] == ["last_daily"]
    assert conn.execute("SELECT count(*) FROM t_mails").fetchone()[0] == 0


# ---- the troubleshooting report, with a fake Outlook ----
class FakeAccessor:
    def __init__(self, props: dict[str, object]) -> None:
        self.props = props

    def GetProperty(self, tag):  # noqa: N802 - Outlook's name
        if tag not in self.props:
            raise RuntimeError("property not found")
        return self.props[tag]


class FakeMail:
    def __init__(self, conversation_index: str = "", props: dict[str, object] | None = None, replies: int = 0) -> None:
        self.ConversationIndex = conversation_index  # noqa: N815 - Outlook's names
        self.ConversationID = key_of() if conversation_index else ""  # noqa: N815
        self.ConversationTopic = "Crane booking"  # noqa: N815
        self.PropertyAccessor = FakeAccessor(props or {})  # noqa: N815
        self.closed: list[int] = []

    def ReplyAll(self):  # noqa: N802
        return FakeMail(self.ConversationIndex + "8000000001" if self.ConversationIndex else "")

    def Close(self, how):  # noqa: N802
        self.closed.append(how)


def test_the_field_by_field_route_reads_the_identifiers_and_falls_back_to_the_headers():
    mail = FakeMail(index().hex().upper(), {outlook.PR_INTERNET_MESSAGE_ID: "<m1@example.com>", outlook.PR_CONVERSATION_INDEX_TRACKING: True,
                                            outlook.PR_TRANSPORT_MESSAGE_HEADERS: "In-Reply-To: <m0@example.com>\r\n\r\n"})
    found, how = outlook.item_identifiers(mail)
    assert conversations.key(found["conversation_index"]) == key_of() and found["conversation_tracking"] is True
    assert (found["message_id"], found["in_reply_to"], found["refs"]) == ("<m1@example.com>", "<m0@example.com>", "")
    assert (how["message_id"], how["in_reply_to"], how["refs"]) == ("PropertyAccessor", "transport headers", "none")


def test_the_reports_lines_say_presence_and_the_keys_first_8_characters_only():
    mail = FakeMail(index().hex().upper(), {outlook.PR_INTERNET_MESSAGE_ID: "<m1@mail.example.com>"})
    text = " ".join(f"{s.name}: {s.result}" for s in diagnose.identifier_steps(mail))
    assert f"key {key_of()[:8]}…" in text and key_of() not in text and "example.com" not in text
    assert "the same GUID as the index's key" in text and "Read its Message-ID: PropertyAccessor: yes" in text


class FakeSession:
    def __init__(self, saved: FakeMail) -> None:
        self.saved, self.opened = saved, []

    def OpenSharedItem(self, path):  # noqa: N802
        self.opened.append(path)
        return self.saved


class FakeApp:
    def __init__(self, new: FakeMail, saved: FakeMail) -> None:
        self.new, self.Session = new, FakeSession(saved)  # noqa: N815

    def CreateItem(self, kind):  # noqa: N802
        assert kind == outlook.OL_MAIL_ITEM
        return self.new


def test_the_t_mail_try_outs_close_everything_without_saving(tmp_path):
    new, selected, saved = FakeMail(index(OTHER_GUID).hex().upper()), FakeMail(index(replies=1).hex().upper()), FakeMail(index().hex().upper())
    app = FakeApp(new, saved)
    steps = diagnose.t_mail_steps(app, selected, tmp_path / "email.msg")
    assert [s.ok for s in steps] == [True, True, True]
    assert "in the same conversation" in steps[1].result and "in the same conversation" in steps[2].result
    assert new.closed == [outlook.OL_DISCARD] and saved.closed == [outlook.OL_DISCARD]
    assert app.Session.opened == [str(tmp_path / "email.msg")]
    blank = diagnose.t_mail_steps(FakeApp(FakeMail(), saved), None, None)
    assert not blank[0].ok and "DocRepo would give it one (decision 39)" in blank[0].result
    assert "no saved email to try it on" in blank[-1].result


def test_the_newest_saved_email_is_found_read_only(env):
    root = env[1]
    cid = save_email(env, email(), RIGGING, datetime(2027, 1, 1, 8, 0))
    found = diagnose.newest_saved_email(root)
    assert found is not None and found.name == "email.msg" and cid in str(found)
    assert os.access(found, os.R_OK)
