"""Emails from the drag's own copy, read without Outlook, and their task's name as a category in Outlook (the knowledge
base's phase 0, decisions 22 to 26; release 5.33). Classic Outlook isn't on the personal computer: the emails are
made-up .msg files (``msg_builder``), the drags made-up OLE data objects, and Outlook a fake."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct  # noqa: E402
from datetime import datetime  # noqa: E402

import pythoncom  # noqa: E402
import pytest  # noqa: E402
import win32clipboard  # noqa: E402
import winerror  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from win32com.server.exception import COMException  # noqa: E402
from win32com.server.util import NewEnum, wrap  # noqa: E402

from docrepo import capacity, captures, db, diagnose, layer0, msg, outlook, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.safe_fs import SafeFS, WriteRefused  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import CaptureDraft, EmailItem, email_rows, save_capture  # noqa: E402
from docrepo.ui import drop_target  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.drop_target import DropRead, Dropped  # noqa: E402
from msg_builder import FakeAttachment, FakeEmail, build  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
INSTALLATION = "T000008"
PICTURE = FakeAttachment("image001.png", b"p" * 20_000, "image001.png@01DC", hidden=True)


def crane_email(**kw) -> bytes:
    return build(FakeEmail(attachments=[FakeAttachment("Lift plan.txt", b"Lift plan, made up"), PICTURE,
                                        FakeAttachment("Re: crane", b"", method=5)], **kw))


# ---- reading a .msg without Outlook ----
def test_a_msg_is_read_without_outlook():
    data = crane_email()
    email = msg.read(data)
    assert (email.subject, email.sender, email.to) == ("Crane booking", "Ann Example", "Owner Example; Sam Example")
    assert email.body == "The crane is booked for Tuesday.\nThe lift plan is at https://example.com/lift-plan."
    assert email.sent == datetime(2026, 10, 7, 9, 15).replace(tzinfo=__import__("datetime").timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    assert email.msg_bytes == data and email.html == "" and email.refused == ()
    # The attached email (method 5) is left out, as Outlook's own route leaves it out.
    assert [(a.name, a.size, a.content_id, a.hidden, a.data[:8]) for a in email.attachments] == [
        ("Lift plan.txt", 18, "", False, b"Lift pla"), ("image001.png", 20_000, "image001.png@01DC", True, b"pppppppp")]
    assert email.text().startswith("From: Ann Example\nSent: ")
    with pytest.raises(msg.MsgError):
        msg.read(b"not a msg at all")
    assert msg.when(0) == "" and not msg.is_msg(b"%PDF")


def test_layer_0_without_an_html_body():
    # Links come from the plain text, where Outlook writes them out; pictures are the hidden attachments with a content ID.
    found = layer0.find(msg.read(crane_email()))
    assert [(p.kind, p.name, p.url) for p in found.parts] == [
        ("attachment", "Lift plan.txt", ""), ("link", "example.com", "https://example.com/lift-plan"), ("picture", "image001.png", "")]
    assert layer0.read_text("See <https://example.com/a>, or https://example.com/b. Mail <mailto:ann@example.com>") == [
        "https://example.com/a", "https://example.com/b", "mailto:ann@example.com"]
    # With an HTML body, it's read as before.
    html = msg.read(crane_email(html='<p><a href="https://example.com/html-link">x</a><img src="cid:image001.png@01DC"></p>'))
    assert [p.url for p in layer0.find(html).parts if p.kind == "link"] == ["https://example.com/html-link"]


# ---- the drag's own copy ----
def descriptor(*files: tuple[str, int | None]) -> bytes:
    out = struct.pack("<I", len(files))
    for name, size in files:
        flags = drop_target.FD_FILESIZE if size is not None else 0
        entry = struct.pack("<I", flags) + b"\0" * 60 + struct.pack("<II", 0, size or 0) + name.encode("utf-16-le").ljust(520, b"\0")
        out += entry
    return out


class FakeDrag:
    """An OLE data object made the way Outlook makes a drag: a list of files, and each file's contents, an email's as a
    storage and an attachment's as a block of memory."""

    _com_interfaces_ = [pythoncom.IID_IDataObject]
    _public_methods_ = ["GetData", "QueryGetData", "EnumFormatEtc", "GetDataHere", "GetCanonicalFormatEtc", "SetData", "DAdvise",
                        "DUnadvise", "EnumDAdvise"]

    def __init__(self, files: list[tuple[str, bytes]], outlook_formats: bool = True) -> None:
        self.files = files
        self.descriptor = win32clipboard.RegisterClipboardFormat("FileGroupDescriptorW")
        self.contents = win32clipboard.RegisterClipboardFormat("FileContents")
        self.others = [win32clipboard.RegisterClipboardFormat("RenPrivateMessages")] if outlook_formats else []

    def GetData(self, fe):  # noqa: N802 - OLE's names
        cf, _td, _aspect, index, tymed = fe
        m = pythoncom.STGMEDIUM()
        if cf == self.descriptor:
            m.set(pythoncom.TYMED_HGLOBAL, descriptor(*((n, len(d)) for n, d in self.files)))
            return m
        if cf == self.contents and 0 <= index < len(self.files):
            name, data = self.files[index]
            if name.endswith(".msg") and tymed & pythoncom.TYMED_ISTORAGE:
                lock = pythoncom.CreateILockBytesOnHGlobal(None, True)
                lock.WriteAt(0, data)
                from win32com import storagecon as sc
                m.set(pythoncom.TYMED_ISTORAGE, pythoncom.StgOpenStorageOnILockBytes(lock, None, sc.STGM_READ | sc.STGM_SHARE_EXCLUSIVE))
            else:
                m.set(pythoncom.TYMED_HGLOBAL, data + b"\0\0\0")  # a block of memory can be longer than the file
            return m
        raise COMException(hresult=winerror.DV_E_FORMATETC)

    def QueryGetData(self, fe):  # noqa: N802
        return winerror.S_OK

    def EnumFormatEtc(self, direction):  # noqa: N802
        cfs = [self.descriptor, self.contents, *self.others]
        return NewEnum([(cf, None, 1, -1, pythoncom.TYMED_HGLOBAL) for cf in cfs], iid=pythoncom.IID_IEnumFORMATETC)


def drag(files, outlook_formats: bool = True):
    return wrap(FakeDrag(files, outlook_formats), pythoncom.IID_IDataObject)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_a_drag_is_copied_into_memory():
    data = crane_email()
    found = drop_target.read(drag([("Crane booking.msg", data), ("Lift plan.txt", b"Lift plan, made up")]))
    assert found.outlook and found.forms == ["storage", "memory"] and found.problems == []
    assert [(x.name, x.email) for x in found.items] == [("Crane booking.msg", True), ("Lift plan.txt", False)]
    assert msg.read(found.items[0].data).subject == "Crane booking"  # the storage, copied whole
    assert found.items[1].data == b"Lift plan, made up"  # the block of memory, cut to the file's size
    assert drop_target.descriptors(descriptor(("a.txt", None))) == [("a.txt", None, False)]
    assert drop_target.can_take(drag([("a.txt", b"x")], outlook_formats=False))


def test_the_drop_target_takes_the_drop_after_it(qapp):
    got, left = [], []
    target = wrap(drop_target.DropTarget(got.append, lambda: left.append(True)), pythoncom.IID_IDropTarget)
    obj = drag([("Crane booking.msg", crane_email())])
    diagnose.DROPS.clear()
    assert target.DragEnter(obj, 0, (10, 10), drop_target.DROPEFFECT_COPY) == drop_target.DROPEFFECT_COPY
    assert target.DragOver(0, (12, 12), drop_target.DROPEFFECT_COPY) == drop_target.DROPEFFECT_COPY
    assert target.Drop(obj, 0, (12, 12), drop_target.DROPEFFECT_COPY) == drop_target.DROPEFFECT_COPY
    assert got == [] and left == [True]  # handled once the drop has finished, never during it
    QApplication.processEvents()
    assert [x.name for x in got[0].items] == ["Crane booking.msg"]
    note = diagnose.DROPS[-1]
    assert note.outlook and note.forms == ("storage",) and note.sizes == (len(crane_email()),)
    report = diagnose.build_report(None, AT, [], check_outlook=lambda: ([], ""), drops=list(diagnose.DROPS))
    assert "## Drops on DocRepo's own drop target" in report and "| yes | storage " in report and "Crane" not in report


# ---- saving ----
@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), Settings(me="P001"))
    yield conn, data_root, fs
    conn.close()


def test_the_msg_and_its_attachments_are_written_as_handed_over(env):
    conn, root, fs = env
    data = crane_email()
    email = msg.read(data)
    r = save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(task=INSTALLATION, files=email_rows(email)), AT)
    c = Model(conn).captures[r.capture_id]
    folder = captures.capture_folder(root, c.id, c.saved)
    assert (folder / "email.msg").read_bytes() == data  # the email exactly as Outlook handed it over
    assert (folder / "attachments" / "Lift plan.txt").read_bytes() == b"Lift plan, made up"
    assert (folder / "attachments" / "image001.png").stat().st_size == 20_000
    md = captures.capture_md_path(root, c).read_text(encoding="utf-8")
    assert "From: Ann Example" in md and "The crane is booked for Tuesday." in md  # the text the guard used to hold back
    assert r.filed_emails == [(email, INSTALLATION)] and r.problems == []
    # Unfiled, an email has no task to be marked with.
    r = save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(files=email_rows(msg.read(data))), AT)
    assert r.filed_emails == []


def test_write_copy_never_overwrites_nor_leaves_its_folders(tmp_path):
    fs = SafeFS([tmp_path / "root"])
    target = fs.write_copy(tmp_path / "root" / "a" / "email.msg", b"one")
    assert target.read_bytes() == b"one"
    with pytest.raises(FileExistsError):
        fs.write_copy(target, b"two")
    with pytest.raises(WriteRefused):
        fs.write_copy(tmp_path / "elsewhere.msg", b"x")
    assert target.read_bytes() == b"one"


# ---- categories in Outlook ----
class FakeItem:
    def __init__(self, categories: str = "") -> None:
        self.Categories = categories
        self.saved = 0

    def Save(self):  # noqa: N802 - Outlook's names
        self.saved += 1


class FakeCategory:
    def __init__(self, name: str, colour: int) -> None:
        self.Name, self.Color = name, colour


class FakeCategories:
    """Outlook's list of categories."""

    def __init__(self, *items: FakeCategory) -> None:
        self.items = list(items)

    @property
    def Count(self):  # noqa: N802 - Outlook's names
        return len(self.items)

    def Item(self, n):  # noqa: N802
        return self.items[n - 1]

    def Add(self, name, colour=0):  # noqa: N802
        self.items.append(FakeCategory(name, colour))

    def Remove(self, name):  # noqa: N802
        self.items = [c for c in self.items if c.Name != name]


class FakeSession:
    def __init__(self, items: dict[str, FakeItem], categories: FakeCategories | None = None) -> None:
        self.items = items
        self.asked: list[tuple] = []
        self.Categories = categories or FakeCategories()

    def GetItemFromID(self, entry_id, store_id=None):  # noqa: N802
        self.asked.append((entry_id, store_id))
        if entry_id not in self.items:
            raise RuntimeError("The item could not be found")
        return self.items[entry_id]


class FakeApp:
    def __init__(self, session: FakeSession) -> None:
        self.Session = session


def test_category_names(env):
    m = Model(env[0])
    assert outlook.category_name(m, INSTALLATION) == "Installation"
    conn = env[0]
    conn.execute("UPDATE tasks SET title = 'Pump trial, phase 2' WHERE id = 'T000019'")
    conn.execute("UPDATE tasks SET title = 'Installation' WHERE id = 'T000018'")  # another open task named the same
    m = Model(conn)
    assert outlook.category_name(m, "T000019") == "Pump trial phase 2"  # commas and semicolons separate categories
    top = m.task(m.parents_of("T000018")[0]).title if m.parents_of("T000018") else "T000018"
    assert outlook.category_name(m, "T000018") == f"Installation ({top})"
    assert outlook.with_category("Red, Installation", "installation", ",") == "Red, Installation"  # already there, in any case
    assert outlook.with_category("Red, Blue", "Installation", ",") == "Red, Blue, Installation"
    assert outlook.with_category("", "Installation", ";") == "Installation"
    assert outlook.with_category("Red; Blue", "Installation", ";") == "Red; Blue; Installation"


def test_dragged_emails_find_their_place_in_outlook():
    a, b = EmailItem("Crane booking", "", "", "", ""), EmailItem("Sling drawing", "", "", "", "")
    assert outlook.match_places([a, b], [("E2", "S", "Sling drawing"), ("E1", "S", "Crane booking")]) == 2
    assert (a.entry_id, b.entry_id) == ("E1", "E2")
    c = EmailItem("Renamed by the file", "", "", "", "")
    assert outlook.match_places([c], [("E3", "S", "Something else")]) == 1 and c.entry_id == "E3"  # one dragged, one selected
    d = EmailItem("Nothing alike", "", "", "", "")
    assert outlook.match_places([d], [("E4", "S", "x"), ("E5", "S", "y")]) == 0 and d.entry_id == ""


def test_filed_emails_are_marked_with_their_task(env, monkeypatch):
    m = Model(env[0])
    marked, other = FakeItem("Red"), FakeItem()
    session = FakeSession({"E1": marked, "E2": other})
    monkeypatch.setattr(outlook, "connect", lambda: (FakeApp(session), "fake"))
    monkeypatch.setattr(outlook, "list_separator", lambda: ",")
    e1 = EmailItem("Crane booking", "", "", "", "", entry_id="E1", store_id="S1")
    e2 = EmailItem("Sling drawing", "", "", "", "", entry_id="E2")
    gone = EmailItem("Moved away", "", "", "", "", entry_id="E9")
    unplaced = EmailItem("Never found", "", "", "", "")
    count, problems = outlook.mark_filed([(e1, INSTALLATION), (e2, "T000012"), (gone, INSTALLATION), (unplaced, INSTALLATION)], m)
    assert count == 2 and (marked.Categories, marked.saved) == ("Red, Installation", 1) and other.Categories == "Rigging plan"
    assert session.asked[0] == ("E1", "S1")
    assert problems[0] == "1 email couldn't be marked in Outlook: DocRepo didn't find it there."
    assert problems[1].startswith("An email wasn't marked in Outlook (RuntimeError")
    count, _ = outlook.mark_filed([(e1, INSTALLATION)], m)  # marked already: nothing changes, nothing is saved
    assert count == 1 and marked.saved == 1


def test_the_test_category_is_put_back():
    mail = FakeItem("Red")
    steps = diagnose.category_steps(mail)
    assert [s.ok for s in steps] == [True, True, True] and mail.Categories == "Red" and mail.saved == 2


# ---- the capture window ----
@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001", outlook_categories=True)
    capacity.rebuild_all(conn, AT.date(), settings)
    prompts.write_defaults(fs, data_root)
    messages: list[tuple[str, str]] = []
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: messages.append((t, m)), now=lambda: AT)
    w = CaptureWindow(ctx)
    w.messages = messages  # type: ignore[attr-defined]
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()
    conn.close()


def test_a_dragged_email_is_filed_and_marked(window, monkeypatch):
    item = FakeItem()
    monkeypatch.setattr(outlook, "selected_places", lambda: [("E1", "S1", "Crane booking")])
    monkeypatch.setattr(outlook, "connect", lambda: (FakeApp(FakeSession({"E1": item})), "fake"))
    monkeypatch.setattr(outlook, "list_separator", lambda: ",")
    window.content.setPlainText("#Installation")
    window.read_items()
    window.take_drop(DropRead([Dropped("Crane booking.msg", crane_email(), email=True), Dropped("Lift plan rev B.txt", b"Rev B, made up")],
                              outlook=True))
    assert [(e.src, e.row.name) for e in window.files] == [
        ("dropped", "Lift plan rev B.txt"), ("outlook", "Crane booking"), ("email", "Lift plan.txt"), ("email", "example.com"),
        ("email", "image001.png")]
    assert window.files[1].row.email.entry_id == "E1"
    window.save()
    assert window.messages[-1][1].endswith("Marked 1 email in Outlook with its task's name.")
    assert item.Categories == "Installation" and item.saved == 1


def test_a_msg_file_from_file_explorer_needs_no_outlook(window, monkeypatch, tmp_path):
    def no_outlook(path):
        raise AssertionError("Outlook isn't asked")

    monkeypatch.setattr(outlook, "open_msg_file", no_outlook)
    path = tmp_path / "Crane booking.msg"
    path.write_bytes(crane_email())
    window.add_paths([str(path)])
    assert window.files[0].row.email.msg_bytes == path.read_bytes() and window.files[0].row.email.sender == "Ann Example"


def test_a_drop_that_cant_be_read_says_so(window):
    window.take_drop(DropRead([Dropped("Broken.msg", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 broken", email=True)], outlook=True,
                              problems=["file 2 couldn't be read (com_error)"]))
    assert window.error.text().startswith("Not all of the drop could be read: file 2 couldn't be read (com_error); Broken.msg: ")
    assert window.files == []


# ---- release 5.33.1: the selected email copied whole, its hotkey, and the category's colour ----
class FakeDraft:
    """A new email Outlook makes for the copy: the selected email is attached to it, never saved or sent."""

    def __init__(self, data: bytes | None) -> None:
        self.data = data
        self.closed: list[int] = []
        self.Attachments = self

    def Add(self, item, kind):  # noqa: N802 - Outlook's names
        assert kind == outlook.OL_EMBEDDED_ITEM
        if self.data is None:
            raise outlook_error()
        return self

    def SaveAsFile(self, path):  # noqa: N802
        open(path, "wb").write(self.data)  # what Outlook does: the attached email as a .msg

    def Close(self, how):  # noqa: N802
        self.closed.append(how)


def outlook_error():
    import pywintypes
    return pywintypes.com_error(-2147467260, "Operation aborted", None, None)


class FakeMailItem:
    Class = outlook.OL_MAIL
    Subject = "Crane booking"
    EntryID = "E1"

    class Parent:
        StoreID = "S1"

    def __getattr__(self, name):  # the guard refuses the rest
        raise outlook_error()


class FakeOutlookApp:
    def __init__(self, data: bytes | None) -> None:
        self.draft = FakeDraft(data)
        self.selection = [FakeMailItem()]
        self.Session = FakeSession({})

    def CreateItem(self, kind):  # noqa: N802
        assert kind == outlook.OL_MAIL_ITEM
        return self.draft

    def ActiveExplorer(self):  # noqa: N802
        return self

    @property
    def Selection(self):  # noqa: N802
        items = self.selection

        class S:
            Count = len(items)

            def Item(self, n):  # noqa: N802
                return items[n - 1]

        return S()


def test_the_selected_email_is_copied_whole_past_the_guard(monkeypatch, tmp_path):
    data = crane_email()
    app = FakeOutlookApp(data)
    monkeypatch.setattr(outlook, "connect", lambda: (app, "fake"))
    scratch = tmp_path / "System" / "outlook-email.msg"
    scratch.parent.mkdir()
    [email] = outlook.selected_emails(scratch)
    assert (email.subject, email.sender, email.refused) == ("Crane booking", "Ann Example", ())
    assert email.body.startswith("The crane is booked") and email.msg_bytes == data
    assert (email.entry_id, email.store_id) == ("E1", "S1") and app.draft.closed == [outlook.OL_DISCARD]  # never saved
    # Where Outlook refuses the copy too, the email is read field by field, as before.
    refusing = FakeOutlookApp(None)
    monkeypatch.setattr(outlook, "connect", lambda: (refusing, "fake"))
    [partial] = outlook.selected_emails(scratch)
    assert partial.subject == "Crane booking" and partial.msg_bytes is None and "Body" in partial.refused
    assert refusing.draft.closed == [outlook.OL_DISCARD]


def test_the_category_goes_on_outlooks_list_in_its_colour(env, monkeypatch):
    m = Model(env[0])
    item = FakeItem()
    session = FakeSession({"E1": item}, FakeCategories(FakeCategory("Rigging plan", 1)))
    monkeypatch.setattr(outlook, "connect", lambda: (FakeApp(session), "fake"))
    monkeypatch.setattr(outlook, "list_separator", lambda: ",")
    e1 = EmailItem("Crane booking", "", "", "", "", entry_id="E1")
    assert outlook.mark_filed([(e1, INSTALLATION)], m, "Teal") == (1, [])
    assert [(c.Name, c.Color) for c in session.Categories.items] == [("Rigging plan", 1), ("Installation", 6)]
    e2 = EmailItem("Sling drawing", "", "", "", "", entry_id="E1")
    outlook.mark_filed([(e2, "T000012")], m, "Teal")
    assert [(c.Name, c.Color) for c in session.Categories.items] == [("Rigging plan", 1), ("Installation", 6)]  # its own colour stays
    session.Categories = FakeCategories()
    outlook.mark_filed([(e1, INSTALLATION)], m, "None")
    assert session.Categories.items == []  # None leaves the list alone
    assert outlook.COLOURS[outlook.colour_number("Dark maroon")] == "Dark maroon" and outlook.colour_number("Pink") == 0


def test_the_test_category_goes_on_the_list_and_off_again():
    mail, categories = FakeItem("Red"), FakeCategories()
    steps = diagnose.category_steps(mail, FakeSession({}, categories), "Teal")
    assert [s.ok for s in steps] == [True, True, True, True, True] and categories.items == [] and mail.Categories == "Red"


def test_the_outlook_hotkey_adds_the_selected_email(window, monkeypatch):
    from docrepo import hotkey
    assert ("outlook_hotkey", "Add the email selected in Outlook") in hotkey.HOTKEYS and hotkey.SUGGESTED["outlook_hotkey"] == "Ctrl+Shift+E"
    asked = []
    monkeypatch.setattr(outlook, "selected_emails", lambda scratch=None: asked.append(scratch) or [msg.read(crane_email())])
    window.hide()
    window.add_selected_email()  # nothing showing: the pinned window opens, with the email
    assert window.pinned and window.pin_window.isVisible() and window.pin_window.status.text().startswith("1 email")
    assert asked[0] is not None and asked[0].name == "outlook-email.msg" and asked[0].parent.name == "System"
    window.add_selected_email()  # again, from Outlook: added to the same capture
    assert sum(e.row.email is not None for e in window.files) == 2
    window.pin_window.hide()
