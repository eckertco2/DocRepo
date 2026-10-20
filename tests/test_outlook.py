"""Reading emails from Outlook, with fake COM objects: classic Outlook isn't on this computer, so the real thing is
tested by hand on the corporate computer (mods log round 1, M0004)."""
from __future__ import annotations

from datetime import datetime

import pytest
import pywintypes

from docrepo import outlook

ABORTED = -2147467260  # 0x80004004, as Outlook's security guard refuses


def com_error(code: int = ABORTED, text: str = "Operation aborted", inner: str | None = None) -> pywintypes.com_error:
    excepinfo = (0, "Microsoft Outlook", inner, None, 0, code) if inner else None
    return pywintypes.com_error(code, text, excepinfo, None)


class Refuses:
    """A property Outlook won't give out."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def __get__(self, obj, owner=None):
        raise self.error


class FakeAttachment:
    def __init__(self, name: str, kind: int = outlook.OL_BY_VALUE) -> None:
        self.FileName, self.Type = name, kind
        self.PropertyAccessor = self

    def GetProperty(self, _name):  # noqa: N802 - Outlook's name
        return False


class FakeAttachments:
    def __init__(self, *items: FakeAttachment) -> None:
        self.items = items
        self.Count = len(items)

    def Item(self, n: int) -> FakeAttachment:  # noqa: N802
        return self.items[n - 1]


class FakeMail:
    Class = outlook.OL_MAIL
    Subject = "Revised guard delivery"
    SenderName = "Calder Supply"
    To = "Me"
    SentOn = datetime(2026, 10, 8, 9, 30)
    Body = "The guards ship Friday.\r\nRegards"
    Attachments = FakeAttachments(FakeAttachment("Guard drawing.pdf"))

    def SaveAs(self, path, kind):  # noqa: N802
        raise AssertionError("not called while reading")


class GuardedMail(FakeMail):
    """The security guard refuses the sender, recipients and body."""

    SenderName = Refuses(com_error())
    To = Refuses(com_error())
    Body = Refuses(com_error())


class FakeSelection:
    def __init__(self, *items) -> None:
        self.items = items
        self.Count = len(items)

    def Item(self, n: int):  # noqa: N802
        return self.items[n - 1]


class FakeOutlook:
    def __init__(self, *items, explorer: bool = True) -> None:
        self.selection = FakeSelection(*items)
        self.explorer = explorer
        self.Version = "16.0.17928.20000"

    def ActiveExplorer(self):  # noqa: N802
        return self if self.explorer else None

    @property
    def Selection(self):  # noqa: N802
        return self.selection


@pytest.fixture(autouse=True)
def no_problems():
    outlook.PROBLEMS.clear()
    yield
    outlook.PROBLEMS.clear()


def test_describe_gives_the_code_in_words_and_no_addresses():
    text = outlook.describe(com_error(inner="Access to mike@example.com was refused."))
    assert text == ("com_error: 0x80004004 (operation aborted (often Outlook's security guard refusing access)); "
                    "Outlook says: Access to <email address> was refused.")
    assert outlook.describe(ValueError("bad value")) == "ValueError: bad value"


def test_an_email_is_read_field_by_field():
    email = outlook.email_from_item(FakeMail())
    assert (email.subject, email.sender, email.sent, email.to, email.body) == (
        "Revised guard delivery", "Calder Supply", "2026-10-08 09:30", "Me", "The guards ship Friday.\nRegards")
    assert [a.name for a in email.attachments] == ["Guard drawing.pdf"] and email.refused == ()


def test_fields_outlook_refuses_are_left_out_not_the_whole_email():
    email = outlook.email_from_item(GuardedMail())
    assert email.subject == "Revised guard delivery" and email.sender == email.to == email.body == ""
    assert email.refused == ("Body", "SenderName", "To")
    assert [p.step for p in outlook.PROBLEMS] == ["reading the email's Body", "reading the email's SenderName", "reading the email's To"]
    assert "0x80004004" in outlook.PROBLEMS[0].detail
    assert outlook.refused_note([email]).startswith("Outlook didn't give DocRepo the email's Body, SenderName, To, so those are left out.")


def test_selected_emails(monkeypatch):
    monkeypatch.setattr(outlook, "connect", lambda: (FakeOutlook(FakeMail()), "GetActiveObject"))
    assert [e.subject for e in outlook.selected_emails()] == ["Revised guard delivery"]


@pytest.mark.parametrize("app, message", [
    (FakeOutlook(), "No email is selected in Outlook."),
    (FakeOutlook(type("Meeting", (), {"Class": 53})()), "The selected item in Outlook isn't an email."),
    (FakeOutlook(FakeMail(), explorer=False), "Outlook's main window isn't open. Open it, select the email, and try again."),
])
def test_selected_emails_says_what_is_wrong(monkeypatch, app, message):
    monkeypatch.setattr(outlook, "connect", lambda: (app, "GetActiveObject"))
    with pytest.raises(outlook.OutlookError, match="^" + message.replace(".", r"\.") + "$"):
        outlook.selected_emails()


def test_a_selection_outlook_refuses_is_an_outlook_error_with_its_code(monkeypatch):
    class Busy(FakeOutlook):
        Selection = Refuses(com_error(-2147418111, "Call was rejected by callee."))  # 0x80010001

    monkeypatch.setattr(outlook, "connect", lambda: (Busy(), "GetActiveObject"))
    with pytest.raises(outlook.OutlookError) as e:
        outlook.selected_emails()
    assert e.value.step == "reading Outlook's selection" and "0x80010001 (call rejected by Outlook" in str(e.value)


def test_connect_joins_outlook_when_getactiveobject_fails(monkeypatch):
    import win32com.client

    joined = FakeOutlook()
    monkeypatch.setattr(win32com.client, "GetActiveObject", lambda name: (_ for _ in ()).throw(com_error(-2147221021, "Operation unavailable")))
    monkeypatch.setattr(win32com.client, "Dispatch", lambda name: joined)
    monkeypatch.setattr(outlook, "outlook_window_open", lambda: True)
    assert outlook.connect() == (joined, "Dispatch")
    assert outlook.PROBLEMS[-1].step == "finding Outlook (GetActiveObject)" and "0x800401E3" in outlook.PROBLEMS[-1].detail


def test_connect_never_starts_outlook(monkeypatch):
    import win32com.client

    monkeypatch.setattr(win32com.client, "GetActiveObject", lambda name: (_ for _ in ()).throw(com_error(-2147221021, "Operation unavailable")))
    monkeypatch.setattr(win32com.client, "Dispatch", lambda name: pytest.fail("Dispatch would start Outlook"))
    monkeypatch.setattr(outlook, "outlook_window_open", lambda: False)
    with pytest.raises(outlook.OutlookError, match="Outlook isn't open"):
        outlook.connect()
