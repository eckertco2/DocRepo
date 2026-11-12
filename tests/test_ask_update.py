"""Release 5.125, Ask for an update (the cold-eyes plan's section 4, decisions 481 to 487), without Qt: who it goes to,
its subject and words, "asked Mon" and what ends it, schema 25's T-mail kinds, and ``outlook.ask_t_mail`` with a fake
Outlook (To and Subject filled, shown before the words go in above the signature, tagged by its conversation, never
sent). Every name, address and email here is made up."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from docrepo import ask_update, capacity, captures, conversations, db, outlook, people, tasks
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)
TODAY = AT.date()
RIGGING, INSTALLATION, REACTOR, SEAL = "T000012", "T000008", "T000001", "T000007"
ME, PRIYA, TOM, MIKE, TODD = "P001", "P002", "P003", "P004", "P006"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")


@pytest.fixture
def conn(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c
    c.close()


def task(conn, title: str, **kw) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=AT, created_by="test", **kw)


# ================= the words (decisions 482 to 484) =================
def test_the_rigging_plan_asks_mike_in_the_plans_own_words(conn):
    task(conn, "Lift drawings", parents=[RIGGING])
    ask = ask_update.compose(Model(conn), RIGGING, ME, TODAY)
    assert ask.to == ("mike.ortiz@example.com",) and ask.names == ("Mike Ortiz",) and ask.missing == ()
    assert ask.subject == "Rigging plan: where does it stand?"
    assert ask.words == ("Hi Mike,\n\n"
                         "Where does the rigging plan stand? The last I have (5 Oct): lift study done; drawing the sling arrangement. "
                         "It's due Wed 14 Oct. Still open under it: Lift drawings.\n\n"
                         "Thanks,")
    assert ask_update.who_line(ask) == "To Mike Ortiz."


def test_assignees_then_leads_each_once_never_the_owner(conn):
    t = task(conn, "Crane hire", assignees=[MIKE, ME, PRIYA], leads=[ME, TOM, MIKE])
    ask = ask_update.compose(Model(conn), t, ME, TODAY)
    assert ask.names == ("Mike Ortiz", "Priya Shah", "Tom Becker")
    assert ask.to == ("mike.ortiz@example.com", "priya.shah@example.com", "tom.becker@example.com")
    assert ask.words.startswith("Hi Mike, Priya and Tom,\n\n")
    assert ask_update.who_line(ask) == "To Mike Ortiz, Priya Shah and Tom Becker."


def test_someone_with_no_address_is_named_and_left_out(conn):
    t = task(conn, "Guard rail paint", assignees=[TODD, MIKE])
    ask = ask_update.compose(Model(conn), t, ME, TODAY)
    assert ask.to == ("mike.ortiz@example.com",) and ask.missing == ("Todd",)
    assert ask_update.who_line(ask) == "To Mike Ortiz. Todd has no email address in People."
    people.update_person(conn, MIKE, email=None)
    ask = ask_update.compose(Model(conn), t, ME, TODAY)
    assert ask.to == () and ask.words.startswith("Hi,\n\n")
    assert ask_update.who_line(ask) == "To is empty. Todd and Mike Ortiz have no email address in People."


def test_with_only_the_owner_to_is_empty_and_says_so(conn):
    t = task(conn, "My own checklist", leads=[ME], assignees=[ME])
    ask = ask_update.compose(Model(conn), t, ME, TODAY)
    assert ask.to == () and ask.missing == ()
    assert ask_update.who_line(ask) == "To is empty: nobody but you is on this task."


def test_a_title_that_isnt_a_thing_is_quoted():
    assert ask_update.the_task("Rigging plan") == "the rigging plan"
    assert ask_update.the_task("Line 2 extruder screw replacement") == "the line 2 extruder screw replacement"
    assert ask_update.the_task("P-204A pump overhaul") == "the P-204A pump overhaul"  # a code keeps its capitals
    assert ask_update.the_task("The north tank farm") == "the north tank farm"
    assert ask_update.the_task("Order spare mechanical seal") == "“Order spare mechanical seal”"
    assert ask_update.the_task("Book the alignment contractor") == "“Book the alignment contractor”"
    assert ask_update.the_task("Rails need to be painted red") == "“Rails need to be painted red”"


def test_a_status_goes_mid_sentence_unless_it_starts_with_a_name_or_a_code():
    assert ask_update.in_sentence("Waiting for the crane vendor's quote") == "waiting for the crane vendor's quote"
    assert ask_update.in_sentence("PO raised") == "PO raised"
    assert ask_update.in_sentence("I sent it") == "I sent it"
    assert ask_update.in_sentence("Drafted. Sent for review") == "drafted. Sent for review"


def test_no_status_a_past_due_a_deadline_and_many_subtasks(conn):
    t = task(conn, "Spare parts list", due="2026-10-05", assignees=[MIKE])
    for n in range(7):
        task(conn, f"Part {n + 1}", parents=[t])
    task(conn, "Part 8", parents=[t], state="Closed")
    m = Model(conn)
    words = ask_update.question(m, m.task(t), TODAY)
    assert words == ("Where does the spare parts list stand? I have no status for it yet. It was due Mon 5 Oct. "
                     "Still open under it: Part 1, Part 2, Part 3, Part 4, Part 5 and 2 more.")
    d = task(conn, "Permit pack", deadline="2026-10-20", current_status="Drafted. Waiting on the permit office!")
    words = ask_update.question(Model(conn), Model(conn).task(d), TODAY)
    assert words == ("Where does the permit pack stand? The last I have (8 Oct): drafted. Waiting on the permit office! "
                     "Its deadline is Tue 20 Oct.")


def test_greetings_and_lists():
    assert ask_update.greeting([]) == "Hi,"
    assert ask_update.greeting(["Mike Ortiz"]) == "Hi Mike,"
    assert ask_update.greeting(["Mike Ortiz", "Priya Shah"]) == "Hi Mike and Priya,"
    assert ask_update.listed(["A", "B", "C"]) == "A, B and C"
    assert ask_update.listed(list("ABCDEFG")) == "A, B, C, D, E and 2 more"


# ================= "asked Mon" (decision 485) =================
def ask_kept(conn, task_id: str, opened: str, index: str = "") -> int | None:
    return conversations.record_t_mail(conn, task_id, ask_update.KIND, opened, index, untagged=True)


def test_an_ask_waits_until_a_newer_capture_lands_on_its_task(conn):
    assert ask_update.asked(Model(conn), RIGGING) is None
    ask_kept(conn, RIGGING, "2026-11-09 10:00:00", conversations.new_index(datetime(2026, 11, 9, 10, 0), GUID))
    m = Model(conn)
    assert ask_update.asked(m, RIGGING) == "2026-11-09 10:00:00" and ask_update.asked(m, INSTALLATION) is None
    assert ask_update.asked_text(m, RIGGING, date(2026, 11, 11)) == "asked Mon"
    # A capture on another task, or one saved before the ask, changes nothing.
    captures.add_capture(conn, saved="2026-11-10 09:00:00", source="typed", types=["note"], title="Elsewhere", task=INSTALLATION)
    captures.add_capture(conn, saved="2026-11-09 09:00:00", source="typed", types=["note"], title="Before", task=RIGGING)
    assert ask_update.asked(Model(conn), RIGGING) == "2026-11-09 10:00:00"
    # The ask's own sent copy, once release C captures it, isn't the answer.
    sent = captures.add_capture(conn, saved="2026-11-09 10:05:00", source="outlook_email", types=["note"], title="Sent", task=RIGGING)
    conn.execute("UPDATE t_mails SET capture = ? WHERE kind = 'ask'", (sent,))
    assert ask_update.asked(Model(conn), RIGGING) == "2026-11-09 10:00:00"
    # The reply, captured on the task, ends it.
    captures.add_capture(conn, saved="2026-11-10 08:30:00", source="outlook_email", types=["note"], title="Re: Rigging plan", task=RIGGING)
    assert ask_update.asked(Model(conn), RIGGING) is None


def test_a_capture_filed_to_the_task_later_ends_it_too(conn):
    ask_kept(conn, RIGGING, "2026-11-09 10:00:00")
    unfiled = captures.add_capture(conn, saved="2026-11-08 09:00:00", source="typed", types=["note"], title="Loose note")
    assert ask_update.asked(Model(conn), RIGGING)
    conn.execute("UPDATE captures SET filed_to = ?, filed = ? WHERE id = ?", (RIGGING, "2026-11-10 12:00:00", unfiled))
    assert ask_update.asked(Model(conn), RIGGING) is None


def test_a_discarded_capture_doesnt_end_it(conn):
    ask_kept(conn, RIGGING, "2026-11-09 10:00:00")
    c = captures.add_capture(conn, saved="2026-11-10 09:00:00", source="typed", types=["note"], title="Oops", task=RIGGING)
    conn.execute("UPDATE captures SET discarded = '2026-11-10 09:01:00', discard_reason = 'wrong task' WHERE id = ?", (c,))
    assert ask_update.asked(Model(conn), RIGGING) == "2026-11-09 10:00:00"


def test_the_newest_ask_counts():
    assert ask_update.asked_words("2026-11-11 08:00:00", date(2026, 11, 11)) == "asked today"
    assert ask_update.asked_words("2026-11-10 08:00:00", date(2026, 11, 11)) == "asked Tue"
    assert ask_update.asked_words("2026-11-04 08:00:00", date(2026, 11, 11)) == "asked 4 Nov"
    assert ask_update.asked_words("2025-12-30 08:00:00", date(2026, 1, 9)) == "asked 30 Dec 2025"
    assert ask_update.asked_tip("2026-11-09 10:00:00", date(2026, 11, 11)).startswith("You asked for an update on Mon 9 Nov.")


def test_an_ask_without_an_index_is_kept_for_its_asked_but_a_new_t_mail_isnt(conn):
    assert conversations.record_t_mail(conn, RIGGING, "new", "2026-11-09 10:00:00", "") is None
    kept = ask_kept(conn, RIGGING, "2026-11-09 10:00:00")
    (t,) = Model(conn).t_mails
    assert t.id == kept and (t.kind, t.conversation, t.conversation_index) == ("ask", "", "")
    assert conversations.filings(Model(conn)) == {}  # with no conversation, nothing could find the task by it


# ================= schema 25 =================
def test_t_mails_take_the_four_kinds_and_no_other(conn):
    for kind in ("new", "reply", "ask", "report"):
        conn.execute("INSERT INTO t_mails (task, kind, opened) VALUES (?, ?, '2026-11-11 09:00:00')", (RIGGING, kind))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO t_mails (task, kind, opened) VALUES (?, 'forward', '2026-11-11 09:00:00')", (RIGGING,))
    assert [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE tbl_name = 't_mails' AND type = 'index' ORDER BY name")] == \
        ["t_mails_conversation", "t_mails_task"]


def test_the_version_24_roots_t_mail_comes_through_whole(tmp_path):
    from test_migrations import unzip_root

    root = unzip_root("v24", tmp_path)
    old = sqlite3.connect(root / "System" / "docs.db")
    before = old.execute("SELECT * FROM t_mails").fetchall()
    old.close()
    assert len(before) == 1
    conn = db.connect(SafeFS([root]), root)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert [tuple(r) for r in conn.execute("SELECT * FROM t_mails")] == before
        assert "'ask', 'report'" in conn.execute("SELECT sql FROM sqlite_master WHERE name = 't_mails'").fetchone()[0]
        conn.execute("INSERT INTO t_mails (task, kind, opened) VALUES ('T000012', 'ask', '2026-11-11 09:00:00')")
    finally:
        conn.close()


# ================= ask_t_mail, with a fake Outlook =================
class Doc:
    def __init__(self, item: Item) -> None:
        self.item = item

    def Range(self, start, end):  # noqa: N802 - Word's names
        assert (start, end) == (0, 0)
        return self

    def InsertBefore(self, text):  # noqa: N802
        if self.item.editor_fails:
            raise RuntimeError("no editor")
        self.item.events.append("words")
        self.item.text = text + self.item.text


class Inspector:
    def __init__(self, item: Item) -> None:
        self.WordEditor = Doc(item)  # noqa: N815


class Accessor:
    def __init__(self, item: Item) -> None:
        self.item, self.props = item, {}

    def GetProperty(self, tag):  # noqa: N802
        if tag not in self.props:
            raise RuntimeError("property not found")
        return self.props[tag]

    def SetProperty(self, tag, value):  # noqa: N802
        self.props[tag] = value
        if tag == outlook.PR_CONVERSATION_INDEX:
            self.item.ConversationIndex = bytes(value).hex().upper()

    def StringToBinary(self, text):  # noqa: N802
        return bytes.fromhex(text)


SIGNATURE = "<html><body lang=EN-GB><div class=WordSection1><p class=MsoNormal>&nbsp;</p><p class=MsoNormal>Me<br>Lead engineer</p></div></body></html>"


class Item:
    """A fake new email: ``events`` records what was done to it, in order. Display writes the signature, as Outlook does."""

    def __init__(self, on_save: str = "", editor_fails: bool = False, html_fails: bool = False, plain: bool = False,
                 to_fails: bool = False, display_fails: bool = False) -> None:
        self.ConversationIndex = ""  # noqa: N815
        self.on_save, self.editor_fails, self.html_fails, self.to_fails, self.display_fails = on_save, editor_fails, html_fails, to_fails, display_fails
        self.BodyFormat = outlook.OL_FORMAT_PLAIN if plain else 2  # noqa: N815 - olFormatHTML
        self.events: list[str] = []
        self.text = ""
        self._html, self._body, self._to, self.Subject = "", "", "", ""  # noqa: N815
        self.PropertyAccessor = Accessor(self)  # noqa: N815
        self.closed: list[int] = []

    @property
    def To(self):  # noqa: N802
        raise AssertionError("DocRepo never reads To: Outlook's guard asks about that")

    @To.setter
    def To(self, value):  # noqa: N802
        if self.to_fails:
            raise RuntimeError("refused")
        self.events.append("to")
        self._to = value

    @property
    def GetInspector(self):  # noqa: N802
        return Inspector(self)

    @property
    def HTMLBody(self):  # noqa: N802
        if self.html_fails:
            raise RuntimeError("refused")
        return self._html

    @HTMLBody.setter
    def HTMLBody(self, value):  # noqa: N802
        self.events.append("html")
        self._html = value

    @property
    def Body(self):  # noqa: N802
        return self._body

    @Body.setter
    def Body(self, value):  # noqa: N802
        self.events.append("body")
        self._body = value

    def Display(self):  # noqa: N802
        if self.display_fails:
            raise RuntimeError("no window")
        self.events.append("display")
        self._html, self._body, self.text = SIGNATURE, "\r\nMe\r\nLead engineer", "\rMe\rLead engineer"

    def Save(self):  # noqa: N802
        self.events.append("save")
        if self.on_save:
            self.ConversationIndex = self.on_save

    def Close(self, how):  # noqa: N802
        self.closed.append(how)


class App:
    def __init__(self, item: Item) -> None:
        self.item = item

    def CreateItem(self, kind):  # noqa: N802
        assert kind == outlook.OL_MAIL_ITEM
        return self.item


NOW = datetime(2026, 11, 11, 9, 30)
WORDS = "Hi Mike,\n\nWhere does the rigging plan stand?\n\nThanks,"


@pytest.fixture
def made(monkeypatch):
    holder: dict[str, Item] = {}
    monkeypatch.setattr(outlook, "connect", lambda: (App(holder["item"]), "GetActiveObject"))
    return holder


def test_to_and_subject_are_filled_then_shown_then_the_words_go_above_the_signature(made):
    item = made["item"] = Item(on_save=conversations.new_index(NOW, GUID))
    asked = outlook.ask_t_mail(NOW, ["mike.ortiz@example.com", "priya.shah@example.com"], "Rigging plan: where does it stand?", WORDS)
    assert item.events == ["to", "display", "words", "save"]
    assert item._to == "mike.ortiz@example.com; priya.shah@example.com" and item.Subject == "Rigging plan: where does it stand?"
    assert item.text == "Hi Mike,\r\rWhere does the rigging plan stand?\r\rThanks,\r\rMe\rLead engineer"  # the signature stays, below
    assert asked.to_filled and asked.words == "editor"
    assert asked.opened.how == "saved" and conversations.key(asked.opened.index) == GUID.hex().upper()


def test_without_the_editor_the_words_go_into_the_html_inside_words_section(made):
    item = made["item"] = Item(editor_fails=True)
    asked = outlook.ask_t_mail(NOW, ["mike.ortiz@example.com"], "Rigging plan: where does it stand?", WORDS)
    assert asked.words == "html" and item.events == ["to", "display", "html", "save"]
    assert item._html.startswith("<html><body lang=EN-GB><div class=WordSection1><p class=MsoNormal>Hi Mike,</p><p class=MsoNormal>&nbsp;</p>"
                                 "<p class=MsoNormal>Where does the rigging plan stand?</p>")
    assert item._html.endswith("<p class=MsoNormal>Thanks,</p><p class=MsoNormal>&nbsp;</p><p class=MsoNormal>Me<br>Lead engineer</p></div></body></html>")
    # With no index from Outlook even once saved, DocRepo writes one.
    assert asked.opened.how == "written" and conversations.well_formed(asked.opened.index)


def test_a_plain_text_email_takes_the_words_in_its_text(made):
    item = made["item"] = Item(editor_fails=True, plain=True)
    assert outlook.ask_t_mail(NOW, [], "Rigging plan: where does it stand?", "Hi,\n\nThanks,").words == "text"
    assert item._body == "Hi,\r\n\r\nThanks,\r\n\r\nMe\r\nLead engineer" and "to" not in item.events


def test_words_outlook_wont_take_leave_the_email_open_for_pasting(made):
    item = made["item"] = Item(editor_fails=True, html_fails=True)
    asked = outlook.ask_t_mail(NOW, ["mike.ortiz@example.com"], "Rigging plan: where does it stand?", WORDS)
    assert asked.words == "" and "display" in item.events and item.closed == []


def test_a_refused_to_is_said_and_the_email_still_opens(made):
    item = made["item"] = Item(to_fails=True)
    asked = outlook.ask_t_mail(NOW, ["mike.ortiz@example.com"], "Rigging plan: where does it stand?", WORDS)
    assert not asked.to_filled and item.events[0] == "display" and asked.words == "editor"


def test_an_email_outlook_wont_show_is_closed_unsaved_and_said(made):
    item = made["item"] = Item(display_fails=True)
    with pytest.raises(outlook.OutlookError, match="didn't open the new email"):
        outlook.ask_t_mail(NOW, ["mike.ortiz@example.com"], "Rigging plan: where does it stand?", WORDS)
    assert item.closed == [outlook.OL_DISCARD] and "save" not in item.events


def test_words_first_html_without_words_section_or_body():
    assert outlook.words_first_html("<html><body><p>Sig</p></body></html>", "Hi <all>") == \
        "<html><body><p class=MsoNormal>Hi &lt;all&gt;</p><p>Sig</p></body></html>"
    assert outlook.words_first_html("", "Hi") == "<p class=MsoNormal>Hi</p>"


def test_nothing_here_sends_an_email():
    """DocRepo never sends one (decision 486): no Send in the ask's code either."""
    root = Path(__file__).resolve().parent.parent / "docrepo"
    for name in ("ask_update.py", "outlook.py", "ui/t_mails.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert ".Send(" not in text and ".Send()" not in text, name
