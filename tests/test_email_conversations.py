"""The task page's Email conversations and a conversation's page (release 5.122; the design workspace's
``docs/mods/email-section-plan.md``, decisions 455 to 463): which emails make a conversation, an email's own words, the
section's rows, the page, and Open in Outlook's Outlook side with a fake Outlook. Every email, name and address here is
made up."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from docrepo import email_conversations as ec, msg, outlook
from docrepo.captures import read_content
from docrepo.config import Settings
from docrepo.detail import PageState, Pages
from docrepo.model import Model
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture
from msg_builder import FakeAttachment, FakeEmail, build

TODAY = date(2026, 10, 8)
SETTINGS = Settings(me="P001")  # the sample's owner, named "Me"
REACTOR, SEAL, INSTALLATION, DRAWINGS, RIGGING, VERIFY = "T000001", "T000007", "T000008", "T000009", "T000012", "T000002"
G1, G2, G3 = "0F1E2D3C4B5A69788796A5B4C3D2E1F0", "11111111222222223333333344444444", "AAAAAAAABBBBBBBBCCCCCCCCDDDDDDDD"


def index(guid: str, replies: int = 0) -> bytes:
    return b"\x01" + bytes.fromhex("D9A1B2C3D4") + bytes.fromhex(guid) + b"".join(bytes([0x80, 0, 0, 0, n]) for n in range(1, replies + 1))


def email(subject: str = "Crane booking", sender: str = "Sam Kowalski", body: str = "The crane is booked for Tuesday.",
          guid: str | None = G1, replies: int = 0, mid: str | None = "<a1@example.com>", irt: str | None = None,
          sent: datetime = datetime(2026, 10, 2, 8, 30), to: str = "Me; Rob Lee", attachments: list | None = None,
          entry: str = "") -> EmailItem:
    e = msg.read(build(FakeEmail(subject=subject, sender=sender, to=to, body=body.replace("\n", "\r\n"), sent=sent.astimezone(),
                                 conversation_index=index(guid, replies) if guid else None, message_id=mid, in_reply_to=irt,
                                 attachments=attachments or [])))
    e.entry_id, e.store_id = entry, "S1" if entry else ""
    return e


@pytest.fixture
def env(sample_root):
    conn, root, fs = sample_root

    def capture(*emails: EmailItem, task: str | None, note: str = "", at: datetime | None = None) -> str:
        files = [row for e in emails for row in email_rows(e)]
        when = at or max(datetime.strptime(e.sent, "%Y-%m-%d %H:%M") for e in emails) + timedelta(minutes=5)
        r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=note, task=task, files=files), when)
        assert r.capture_id, r
        return r.capture_id

    def pages() -> Pages:
        m = Model(conn)
        return Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)

    return conn, root, capture, pages


def text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&#x27;", "'").split())


# ================= what makes a conversation (decision 457) =================
def test_one_key_is_one_conversation_oldest_first(env):
    conn, _root, capture, _pages = env
    capture(email(mid="<a2@example.com>", replies=1, subject="RE: Crane booking", sender="Me", sent=datetime(2026, 10, 3, 9, 0)), task=RIGGING)
    capture(email(), task=RIGGING)
    m = Model(conn)
    cv = ec.find(m, G1)
    assert cv is not None and cv.id == G1 and [e.message_id for e in cv.emails] == ["<a1@example.com>", "<a2@example.com>"]
    assert cv.subject == "Crane booking" and cv.senders() == ["Sam Kowalski", "Me"] and cv.tasks() == [RIGGING]


def test_a_reply_with_a_new_key_joins_the_email_it_answers(env):
    """Exchange gives a reply whose subject was changed a new conversation index (the corporate results of 2026-11-09)."""
    conn, _root, capture, _pages = env
    capture(email(), task=RIGGING)
    capture(email("Crane moved to Thursday", guid=G2, mid="<b1@example.com>", irt="<a1@example.com>", sent=datetime(2026, 10, 7, 16, 20)),
            task=RIGGING)
    capture(email("Lift plan", guid=None, mid="<c1@example.com>", sent=datetime(2026, 10, 8, 7, 0), body="Signed.",
                  irt=None), task=RIGGING)
    m = Model(conn)
    joined = ec.find(m, G2)
    assert joined is ec.find(m, G1) and joined.id == G1 and len(joined.emails) == 2
    alone = [cv for cv in ec.all_of(m) if cv.emails[0].message_id == "<c1@example.com>"]
    assert len(alone) == 1 and len(alone[0].emails) == 1 and "." in alone[0].id  # no key: its capture and position


def test_the_subject_never_joins_two_conversations(env):
    conn, _root, capture, _pages = env
    capture(email(), task=RIGGING)
    capture(email(guid=G2, mid="<z1@example.com>", sent=datetime(2026, 10, 5, 8, 0)), task=RIGGING)  # same subject, another key
    assert len([cv for cv in ec.all_of(Model(conn)) if cv.subject == "Crane booking"]) == 2


def test_an_email_captured_twice_is_listed_once_with_both_tasks(env):
    conn, _root, capture, _pages = env
    first = capture(email(), task=RIGGING)
    second = capture(email(), task=INSTALLATION, at=datetime(2026, 10, 4, 9, 0))
    cv = ec.find(Model(conn), G1)
    assert len(cv.emails) == 1 and cv.emails[0].capture == first and cv.emails[0].also == [(second, 0)]
    assert cv.emails[0].tasks == [RIGGING, INSTALLATION]


def test_discarded_captures_and_tasks_are_left_out(env):
    conn, _root, capture, _pages = env
    cid = capture(email(), task=RIGGING)
    conn.execute("UPDATE captures SET discarded = '2026-10-08 10:00:00' WHERE id = ?", (cid,))
    assert ec.find(Model(conn), G1) is None
    capture(email(mid="<a9@example.com>"), task=RIGGING)
    conn.execute("UPDATE tasks SET discarded = '2026-10-08 10:00:00' WHERE id = ?", (RIGGING,))
    m = Model(conn)
    assert ec.find(m, G1).emails[0].tasks == [] and ec.for_tasks(m, [INSTALLATION, RIGGING]) == []


def test_an_email_capture_without_email_rows_is_one_email(env):
    """Decision 463: the sample's vendor email, captured before release 5.74, has no rows."""
    conn, *_ = env
    cv = next(cv for cv in ec.for_tasks(Model(conn), [REACTOR]) if cv.emails[0].capture == "C000003")
    assert cv.id == "C000003.-1" and cv.subject == "Impeller datasheet rev B" and not cv.emails[0].can_open


def test_a_task_lists_its_own_and_its_subtasks_conversations_newest_first(env):
    conn, _root, capture, _pages = env
    capture(email(), task=RIGGING)
    capture(email("Spare seal", guid=G2, mid="<s1@example.com>", sent=datetime(2026, 10, 6, 10, 0)), task=SEAL)
    capture(email("Walkthrough", guid=G3, mid="<w1@example.com>", sent=datetime(2026, 10, 7, 10, 0)), task=VERIFY)
    m = Model(conn)
    ids = m.scope_ids(REACTOR, "descendants")
    subjects = [cv.subject for cv in ec.for_tasks(m, ids)]
    assert subjects[:2] == ["Spare seal", "Crane booking"] and "Walkthrough" not in subjects
    assert ec.task_in(ec.find(m, G1), ids) == RIGGING


# ================= an email's words (decision 462) =================
@pytest.mark.parametrize("quote", [
    "\n\n________________________________\nFrom: Sam Kowalski\nSent: Friday, 2 October 2026 08:30\nTo: Me\nSubject: Crane booking\n\nOld words",
    "\n\n-----Original Message-----\nFrom: Sam Kowalski\nOld words",
    "\n\nFrom: Sam Kowalski <sam@example.com>\nSent: Friday, 2 October 2026 08:30\nOld words",
    "\n\nOn Fri, 2 Oct 2026 at 08:30, Sam Kowalski <sam@example.com>\nwrote:\n> Old words",
    "\n\n> Old words\n> more old words",
])
def test_own_words_stop_where_the_quoted_emails_start(quote):
    own, quoted = ec.own_words("Thanks, Thursday works.\r\nRob" + quote)
    assert own == "Thanks, Thursday works.\nRob" and "Old words" in quoted


def test_a_forward_with_nothing_added_keeps_it_all():
    body = "-----Original Message-----\nFrom: Sam Kowalski\nThe crane is booked."
    assert ec.own_words(body) == (body, "")


def test_each_email_of_a_capture_finds_its_own_words(env):
    conn, root, capture, _pages = env
    a = email(body="First words.")
    b = email("RE: Crane booking", "Rob Lee", "Second words.\n\n-----Original Message-----\nFirst words.", replies=1,
              mid="<a2@example.com>", sent=datetime(2026, 10, 3, 9, 0), to="Sam Kowalski; Me")
    cid = capture(a, b, task=RIGGING, note="Both crane emails")
    m = Model(conn)
    cv = ec.find(m, G1)
    first, second = (ec.email_text(m, e, read_content(root, m.captures[cid])) for e in cv.emails)
    assert (first.to, first.words, first.note) == ("Me; Rob Lee", "First words.", "Both crane emails")
    assert second.to == "Sam Kowalski; Me" and second.note == "" and ec.own_words(second.words) == ("Second words.", "-----Original Message-----\nFirst words.")


def test_snippets_people_and_subjects():
    assert ec.snippet("Hi Rob,\nThe crane is booked.\n\nSam") == "The crane is booked. Sam"
    assert ec.snippet("x " * 60, 20).endswith("…") and len(ec.snippet("word " * 40, 20)) <= 21
    assert ec.who(["Sam Kowalski", "Me", "Rob Lee"], "Me") == "Sam Kowalski, you and Rob Lee"
    assert ec.who(["A", "B", "C", "D", "E"], None) == "A, B, C and 2 more" and ec.who([], None) == "an unknown sender"
    assert ec.clean_subject("RE: Fw: AW:  Crane   booking") == "Crane booking" and ec.clean_subject("Re[2]: Lift") == "Lift"
    assert ec.to_words("Me; Rob Lee", "me") == "you, Rob Lee"


# ================= the section (decisions 455, 456, 458) =================
def test_the_section_lists_the_conversations_with_new_t_mail(env):
    conn, _root, capture, pages = env
    capture(email(body="Hi Rob,\nThe crane is booked for Tuesday."), task=RIGGING)
    capture(email("RE: Crane booking", "Me", "Thanks, see you Tuesday.", replies=1, mid="<a2@example.com>", sent=datetime(2026, 10, 3, 9, 0)),
            task=RIGGING)
    parts = pages().task_parts(REACTOR, PageState())
    assert parts["emails_short"] == "2 · 3 emails"  # with the sample's vendor email on the project itself
    assert 'href="tmail:T000001"' in parts["emails_summary"] and "New T-mail" in parts["emails_summary"]
    rows = parts["emails"]
    assert f'href="conv:T000001/{G1}"' in rows and 'src="ft:mail"' in rows
    assert "Crane booking 2 ↗ Rigging plan Sam Kowalski and you · Thanks, see you Tuesday. 3 Oct" in text(rows)
    assert "Impeller datasheet rev B Norvane Pumps (vendor) · Please find rev B" in text(rows)  # its sender from its From line (463)
    assert "emails" not in pages().task_parts(VERIFY, PageState())  # no email: no section


def test_the_section_shows_five_then_all(env):
    _conn, _root, capture, pages = env
    for n in range(6):
        capture(email(f"Topic {n}", guid=f"{n:032X}", mid=f"<t{n}@example.com>", sent=datetime(2026, 10, 1 + n, 9, 0)), task=INSTALLATION)
    few = pages().task_parts(INSTALLATION, PageState())["emails"]
    assert few.count('src="ft:mail"') == 5 and 'href="fold:conversations"' in few and "Show all 6 conversations" in text(few)
    every = pages().task_parts(INSTALLATION, PageState(conversations=True))["emails"]
    assert every.count('src="ft:mail"') == 6 and "Show fewer" in text(every)


# ================= the page (decisions 459 to 462) =================
def test_a_conversations_page(env):
    _conn, _root, capture, pages = env
    first = capture(email(body="Hi,\nThe crane is booked for Tuesday.", entry="E1"), task=RIGGING)
    second = capture(email("Crane moved to Thursday", guid=G2, mid="<b1@example.com>", irt="<a1@example.com>", sent=datetime(2026, 10, 7, 16, 20),
                           body="Thursday now.\n\n-----Original Message-----\nThe crane is booked for Tuesday.",
                           attachments=[FakeAttachment("Lift plan rev 2.pdf", b"%PDF-1.4 made up")]), task=RIGGING, note="The new day")
    html = pages().conversation_page(INSTALLATION, G1, PageState())
    words = text(html)
    order = ["‹ Installation", "Crane booking", "Sam Kowalski · 2 emails · 2 Oct to 7 Oct · on Rigging plan",
             "Sam Kowalski to you, Rob Lee", "Fri 2 Oct 08:30", "Hi, The crane is booked for Tuesday.", "Open in Outlook · Reply all · Open capture ↗ Rigging plan",
             "Sam Kowalski to you, Rob Lee Newest Subject: Crane moved to Thursday", "Thursday now.", "Show the quoted emails",
             "Your words with it: The new day", "Lift plan rev 2.pdf"]
    at = [words.find(x) for x in order]
    assert -1 not in at and at == sorted(at), dict(zip(order, at))
    assert "-----Original Message-----" not in words  # folded
    assert {"task:T000008", "task:T000012", f"outlook:{first}:0", f"replyall:{first}:0", f"capture:{second}", f"more:q:{second}:0"} <= set(
        re.findall(r'href="([^"]+)"', html))
    opened = text(pages().conversation_page(INSTALLATION, G1, PageState(expanded={f"q:{second}:0"})))
    assert "-----Original Message----- The crane is booked for Tuesday. Hide the quoted emails" in opened
    assert pages().conversation_page(INSTALLATION, G2, PageState()) == html  # either key names it
    assert "isn't here any more" in pages().conversation_page(INSTALLATION, G3, PageState())


# ================= Open in Outlook's Outlook side (decision 460) =================
class Item:
    def __init__(self, fails: bool = False) -> None:
        self.fails, self.displayed = fails, 0

    def Display(self):  # noqa: N802 - Outlook's name
        if self.fails:
            raise RuntimeError("no window")
        self.displayed += 1


class Session:
    def __init__(self, item: Item | None) -> None:
        self.item, self.looked = item, []

    def GetItemFromID(self, *ids):  # noqa: N802
        self.looked.append(ids)
        if self.item is None:
            raise RuntimeError("not found")
        return self.item


class App:
    def __init__(self, session: Session) -> None:
        self.Session = session  # noqa: N815


def test_show_email_finds_it_by_its_place_and_only_shows_it(monkeypatch):
    item = Item()
    session = Session(item)
    monkeypatch.setattr(outlook, "connect", lambda: (App(session), "GetActiveObject"))
    assert outlook.show_email("E1", "S1") is True and session.looked == [("E1", "S1")] and item.displayed == 1
    assert outlook.show_email("E1", "") is True and session.looked[-1] == ("E1",)


def test_show_email_says_when_it_isnt_there(monkeypatch):
    calls = []
    monkeypatch.setattr(outlook, "connect", lambda: calls.append(1) or (App(Session(None)), "GetActiveObject"))
    assert outlook.show_email("", "") is False and calls == []  # no place kept: Outlook isn't asked
    assert outlook.show_email("E1", "S1") is False
    monkeypatch.setattr(outlook, "connect", lambda: (App(Session(Item(fails=True))), "GetActiveObject"))
    with pytest.raises(outlook.OutlookError, match="didn't show it"):
        outlook.show_email("E1", "S1")
