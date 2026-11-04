"""Links that go in, whatever their kind (release 5.66, round 6's item 89, decisions 318, 319 and 321): each row of the
round 6 plan's table of what went wrong, folders kept, links pasted with their names, and the report's note of a link
that wasn't kept. Made-up addresses only."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, diagnose, opener, overview, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages  # noqa: E402
from docrepo.links import FOLDER_TEXT, file_url_path, folder_name, is_folder, link_of_line, read_address  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.save import FileRow, held_text  # noqa: E402
from docrepo.text import is_file_line, plain_text  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow, read_drop  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SP = "https://example.sharepoint.com/:w:/r/sites/Plant/Shared%20Documents/Pump%20spec.docx?d=abc&csf=1&web=1"


# ---- reading an address ----
@pytest.mark.parametrize("typed, kind, value", [
    (SP, "link", SP),
    ("https://example.sharepoint.com/sites/Plant/Shared Documents/Pump spec.docx", "link",
     "https://example.sharepoint.com/sites/Plant/Shared%20Documents/Pump%20spec.docx"),  # SharePoint's Copy path
    ("<https://example.com/page>", "link", "https://example.com/page"),  # Outlook's plain text
    ('"https://example.com/page"', "link", "https://example.com/page"),
    ("www.example.com/page", "link", "https://www.example.com/page"),
    ("https://example.com/page.", "link", "https://example.com/page"),
    ("https://example.com/page),", "link", "https://example.com/page"),
    ("https://example.com/wiki/Pump_(rotary)", "link", "https://example.com/wiki/Pump_(rotary)"),  # its own bracket stays
    ("file:///C:/Docs/Pump%20spec.docx", "path", "C:\\Docs\\Pump spec.docx"),
    ("file://fileserver/share/Pump%20spec.docx", "path", "\\\\fileserver\\share\\Pump spec.docx"),
    ("C:/Docs/Pump spec.docx", "path", "C:\\Docs\\Pump spec.docx"),
    ("\\\\fileserver\\share\\Projects", "path", "\\\\fileserver\\share\\Projects"),
    ("https://example.sharepoint.com/sites/Plant/Notebook.one#Page&section-id={1}\nonenote:https://example.sharepoint.com/sites/Plant/Notebook.one",
     "link", "https://example.sharepoint.com/sites/Plant/Notebook.one#Page&section-id={1}"),  # OneNote's Copy link: the web line
])
def test_what_an_address_is(typed, kind, value):
    a = read_address(typed)
    assert (a.kind, a.value) == (kind, value)


@pytest.mark.parametrize("typed, says", [
    ("mailto:someone@example.com", "That's a mailto: link. DocRepo keeps web links (http or https), files and folders."),
    ("msteams:/l/message/19:abc/123", "That's a msteams: link."),
    ("onenote:https://example.sharepoint.com/a.one", "That's a onenote: link."),
    ("example.com/a", "That isn't a link or a path"),
    ("Line one\nLine two", "That's more than one line."),
    ("https://", "That link has a space or a character a link can't have."),
])
def test_what_isnt_kept_says_why(typed, says):
    a = read_address(typed)
    assert a.kind == "refused" and a.why.startswith(says)


def test_a_content_text_line():
    """In the content text a line is a link only when it's one on its own: a space makes it words."""
    assert link_of_line("<https://example.com/page>") == "https://example.com/page"
    assert link_of_line("www.example.com/page.") == "https://www.example.com/page"
    assert link_of_line("https://example.com is down") is None and link_of_line("See https://example.com") is None
    assert link_of_line("https://example.com/Shared Documents/a.pdf") is None
    assert is_file_line("<https://example.com/page>") and not is_file_line("Call www.example.com tomorrow")
    assert plain_text("Spec:\n<https://example.com/spec.pdf>\nDone.") == "Spec:\nDone."


def test_file_addresses_and_folder_names():
    assert file_url_path("file:///c:/a.pdf") == "c:\\a.pdf" and file_url_path("file:///etc/a") is None
    assert folder_name("C:\\Docs\\Pump files\\") == "Pump files" and folder_name("C:\\") == "C:\\"
    assert folder_name("\\\\fileserver\\share\\Projects\\") == "Projects" and folder_name("\\\\fileserver\\share\\") == "\\\\fileserver\\share\\"
    assert is_folder("C:\\Docs\\") and not is_folder("C:\\Docs\\a.pdf") and not is_folder(None)


def test_a_dragged_link_keeps_its_address_exactly():
    """The bug found on 2026-11-03: Qt's toString() turned %20 back into spaces, so the drop was refused."""
    mime = QMimeData()
    mime.setUrls([QUrl(SP)])
    assert read_drop(mime, links=True) == ("links", [SP])
    mime.setUrls([QUrl("mailto:someone@example.com")])  # it comes through, to say why it isn't kept
    assert read_drop(mime, links=True) == ("links", ["mailto:someone@example.com"])
    assert read_drop(mime) == ("", [])  # the full window's text box types it in, as before


# ---- in the capture window ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w._items_timer.stop()
    w.hide()
    if w.pin_window is not None:
        w.pin_window.hide()
        w.pin_window.deleteLater()
    w.deleteLater()
    conn.close()


def rows(w) -> list[tuple[str, str]]:
    return [(e.row.name, e.row.path) for e in w.files]


def test_dropped_on_the_pinned_window(window):
    window.pin()
    mime = QMimeData()
    mime.setUrls([QUrl(SP)])
    window.dropped(*read_drop(mime, links=True))
    assert rows(window) == [("Pump spec.docx", SP)] and window.pin_window.status.text() == "1 link added"
    mime.setUrls([QUrl("mailto:someone@example.com")])
    window.dropped(*read_drop(mime, links=True))
    assert "That's a mailto: link" in window.pin_window.message.text() and len(window.files) == 1


@pytest.mark.parametrize("typed, name", [
    ("<https://example.com/page>", "example.com"),
    ("www.example.com/plant/Pump%20list.xlsx", "Pump list.xlsx"),
    ("https://example.sharepoint.com/sites/Plant/Shared Documents/Pump spec.docx", "Pump spec.docx"),
])
def test_typed_in_the_landing_row(window, typed, name):
    window.pin()
    pin = window.pin_window
    pin.path.setText(typed)
    pin.add_typed()
    assert [n for n, _ in rows(window)] == [name] and pin.path.text() == ""


def test_a_folder_is_kept(window, tmp_path):
    folder = tmp_path / "Pump files"
    folder.mkdir()
    window.set_task("T000008")
    window.add_paths([str(folder)])
    [entry] = window.files
    assert entry.row.path == str(folder) + "\\" and entry.copy.isHidden() and entry.extract.isHidden()
    assert entry.what == "What's in this folder?" and "reads nothing in it" in entry.note.text()
    assert held_text([entry.row]) == "1 folder"
    window.add_paths([str(folder)])  # once only
    assert len(window.files) == 1
    entry.desc.setText("The pump's drawings.")
    window.save()
    m = Model(window.ctx.conn)
    d = next(d for d in m.documents.values() if d.original == str(folder) + "\\")
    assert (d.name, d.text_status, d.text_note, d.description) == ("Pump files", "none", FOLDER_TEXT, "The pump's drawings.")
    page = Pages(m, NOW.date(), lambda c: "").document_page(d.id)
    assert "Folder " + d.id in page and "a folder: DocRepo keeps where it is, and reads nothing in it" in page
    assert overview.file_type(d.name, d.original) == "folder"
    assert [f.kind for f in m.files_of("T000008") if f.document == d.id] == ["Folder"]


def test_a_folder_opens_in_file_explorer():
    folder = "C:\\Docs\\Pump files\\"
    r = overview.Record("file", "D9", "T1", "2026-10-08 09:00:00", "Pump files", type="folder", path=folder)
    assert opener.plan(r) == opener.Plan("show", folder)


def _paste(box, html: str, text: str) -> None:
    mime = QMimeData()
    mime.setHtml(html)
    mime.setText(text)
    box.insertFromMimeData(mime)


def test_a_link_pasted_with_its_name_on_a_line_of_its_own(window):
    """Copy link in SharePoint, OneDrive or Teams: the clipboard holds the file's name, linked. The address was lost."""
    window.content.setFocus()
    window.content.setPlainText("Spec for the seal:\n")
    window.content.moveCursor(window.content.textCursor().MoveOperation.End)
    _paste(window.content, f'<html><body><!--StartFragment--><a href="{SP}">Pump spec.docx</a><!--EndFragment--></body></html>', SP)
    window._sync_paths()
    assert window.content.toPlainText() == f"Spec for the seal:\n{SP}"
    assert rows(window) == [("Pump spec.docx", SP)]


def test_a_named_link_keeps_its_name_over_the_addresss(window):
    named = "https://example.com/view?id=7"
    window.content.setFocus()
    _paste(window.content, f'<a href="{named}">Seal kit order</a>', named)
    window._sync_paths()
    assert rows(window) == [("Seal kit order", named)]


def test_a_link_inside_pasted_words_keeps_its_address(window):
    window.content.setFocus()
    _paste(window.content, f'<p>See <a href="{SP}">the pump spec</a> before Friday.</p>', "See the pump spec before Friday.")
    assert window.content.toPlainText() == f"See the pump spec <{SP}> before Friday."
    assert window.files == []  # words with an address in them aren't a link on its own line


def test_a_safe_links_address_is_unwrapped_when_pasted(window):
    wrapped = "https://nam01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.com%2Fspec.pdf&data=x"
    window.content.setFocus()
    _paste(window.content, f'<a href="{wrapped}">spec.pdf</a>', wrapped)
    window._sync_paths()
    assert rows(window) == [("spec.pdf", "https://example.com/spec.pdf")]


def test_a_link_pasted_in_the_pinned_window_is_added(window):
    window.pin()
    box = window.pin_window.text
    box.setFocus()
    _paste(box, f'<a href="{SP}">Pump spec.docx</a>', SP)
    assert rows(window) == [("Pump spec.docx", SP)] and box.toPlainText() == ""


def test_a_refused_link_is_noted_by_its_shape_only():
    diagnose.REFUSED_LINKS.clear()
    diagnose.note_refused_link("mailto:someone@example.com")
    diagnose.note_refused_link("<msteams:/l/message/19 abc>\nmore")
    assert [shape for _, shape in diagnose.REFUSED_LINKS] == ["mailto:", "msteams:, with spaces, in angle brackets, 2 lines"]
    assert diagnose.link_shape("www.example .com") == "www., with spaces" and diagnose.link_shape("C:\\a b") == "a drive or share path, with spaces"
    report = diagnose.build_report(None, NOW, [], check_outlook=lambda: ([], ""), drops=[])
    assert "## Links the capture window didn't keep" in report and "- " in report and "someone@example.com" not in report
    diagnose.REFUSED_LINKS.clear()
