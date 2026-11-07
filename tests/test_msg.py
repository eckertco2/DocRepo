"""Reading an Outlook .msg without Outlook (``docrepo.msg``, release 5.33; a test of its own in release 5.102): an email
forwarding another, with two attached files and the forwarded email attached as an item, built by ``msg_builder``. No
Qt, so it's in the fast run."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from docrepo import msg
from msg_builder import EMBEDDED_MESSAGE, FakeAttachment, FakeEmail, build

ORIGINAL = FakeEmail(subject="Crane booking", sender="Ann Example", to="Owner Example",
                     body="The crane is booked for Tuesday.", sent=datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc),
                     attachments=[FakeAttachment("Crane certificate.pdf", b"%PDF-1.7 certificate")],
                     message_id="<ann.1@example.com>")


def forward() -> FakeEmail:
    """Sam forwards Ann's email to the owner: its words below his, two files of his own, and Ann's email as an item."""
    return FakeEmail(
        subject="FW: Crane booking", sender="Sam Example", to="Owner Example",
        body="See below, and the lift plan attached.\r\n\r\n-----Original Message-----\r\nFrom: Ann Example\r\n"
             "Sent: Tuesday, October 6, 2026 2:00 PM\r\nSubject: Crane booking\r\n\r\nThe crane is booked for Tuesday.",
        sent=datetime(2026, 10, 7, 9, 15, tzinfo=timezone.utc),
        attachments=[FakeAttachment("Lift plan.docx", b"PK\x03\x04 lift plan"),
                     FakeAttachment("Site map.png", b"\x89PNG map", content_id="map@01DC"),
                     FakeAttachment("Crane booking", b"", method=EMBEDDED_MESSAGE, email=ORIGINAL)],
        headers="Message-ID: <sam.2@example.com>\r\nIn-Reply-To: <ann.1@example.com>\r\nReferences: <ann.1@example.com>\r\n",
    )


def local(moment: datetime) -> str:
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def test_a_forward_with_two_files_and_the_forwarded_email():
    data = build(forward())
    email = msg.read(data)
    assert (email.subject, email.sender, email.to) == ("FW: Crane booking", "Sam Example", "Owner Example")
    assert email.sent == local(datetime(2026, 10, 7, 9, 15, tzinfo=timezone.utc))
    assert email.body.startswith("See below, and the lift plan attached.\n\n-----Original Message-----\nFrom: Ann Example\n")
    assert email.body.endswith("The crane is booked for Tuesday.") and "\r" not in email.body
    assert email.msg_bytes == data and email.html == ""
    # The two files, each with its bytes; the forwarded email, attached as an item, is left out, and so is its own file.
    assert [(a.name, a.size, a.content_id, a.data) for a in email.attachments] == [
        ("Lift plan.docx", 14, "", b"PK\x03\x04 lift plan"), ("Site map.png", 8, "map@01DC", b"\x89PNG map")]
    assert "Crane certificate.pdf" not in [a.name for a in email.attachments]
    # Its identifiers come from its transport headers, as it has no properties of their own for them.
    assert (email.message_id, email.in_reply_to, email.refs) == ("<sam.2@example.com>", "<ann.1@example.com>", "<ann.1@example.com>")


def test_the_forwarded_email_is_a_msg_of_its_own():
    """Read on its own, the email that was forwarded is whole: the reader takes it as Outlook would save it."""
    email = msg.read(build(ORIGINAL))
    assert (email.subject, email.sender, email.message_id) == ("Crane booking", "Ann Example", "<ann.1@example.com>")
    assert [a.name for a in email.attachments] == ["Crane certificate.pdf"]


def test_what_isnt_a_msg_is_refused():
    with pytest.raises(msg.MsgError, match="isn't an Outlook .msg"):
        msg.read(b"%PDF-1.7 not an email")
    with pytest.raises(msg.MsgError, match="couldn't be read"):
        msg.read(msg.SIGNATURE + b"\0" * 600)  # a compound file's start, then nothing a storage can be read from
    assert msg.is_msg(build(ORIGINAL)) and not msg.is_msg(b"")


def test_times_and_headers():
    assert msg.when(None) == msg.when(0) == msg.when(-5) == ""
    assert msg.when(10**30) == ""  # past any date
    assert msg.header_ids("") == ("", "", "")
    assert msg.header_ids("Message-ID:\r\n <a.1@example.com>\r\nSubject: x\r\n") == ("<a.1@example.com>", "", "")
