"""Links as files (mods log round 1, M0001): a web or SharePoint link kept as a document that DocRepo only copies."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import edits  # noqa: E402
from docrepo.captures import read_content  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import PageState  # noqa: E402
from docrepo.detail import Pages as DetailPages  # noqa: E402
from docrepo.links import is_link, link_name  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.parse import parse_capture  # noqa: E402
from docrepo.save import CaptureDraft, FileRow, NewTaskFields, save_capture  # noqa: E402
from docrepo.text import plain_text  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
SPEC = "https://example.sharepoint.com/sites/Line1/Shared%20Documents/Seal%20kit%20spec%202026-11-30.pdf"
OFFICE = ("https://example.sharepoint.com/:w:/r/sites/Line1/_layouts/15/Doc.aspx?sourcedoc=%7B1234%7D"
          "&file=Pump%20datasheet.docx&action=default")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def save(sample_root, draft: CaptureDraft):
    conn, root, fs = sample_root
    return save_capture(conn, root, fs, SETTINGS, draft, AT)


def test_what_counts_as_a_link():
    assert is_link(SPEC) and is_link("  HTTP://example.com/a  ") and is_link(OFFICE)
    for text in ("See https://example.com", "https://example.com/a b", "ftp://example.com/a", "C:\\Docs\\a.pdf", "", None):
        assert not is_link(text)


def test_a_links_name():
    assert link_name(SPEC) == "Seal kit spec 2026-11-30.pdf"
    assert link_name(OFFICE) == "Pump datasheet.docx"  # SharePoint's file= names the file, not Doc.aspx
    assert link_name("https://Example.com/wiki/Pumps/") == "example.com"
    assert link_name("https://example.com/pages/Home.aspx?web=1") == "Home.aspx"
    assert len(link_name("https://example.com/" + "a" * 150 + ".pdf")) == 100


def test_link_lines_are_files_not_text():
    content = f"Order the seal kit by Friday.\n{SPEC}"
    assert plain_text(content) == "Order the seal kit by Friday."
    # Parse and populate skips the link's line, so the date in its address isn't read: the result is the sentence's alone.
    found = parse_capture(content, "new_task", date(2026, 10, 8), [], [], ())
    assert found == parse_capture("Order the seal kit by Friday.", "new_task", date(2026, 10, 8), [], [], ())
    assert (found.title, found.deadline) == ("Order the seal kit", date(2026, 10, 9))


def test_saving_a_link(sample_root):
    conn, root, _ = sample_root
    row = FileRow(link_name(SPEC), SPEC, "Vendor's seal kit spec.", save_a_copy=True, extract=True)
    r = save(sample_root, CaptureDraft(content=SPEC, task="T000008", types={"note"}, files=[row]))
    m = Model(conn)
    d = m.documents["D000005"]
    assert (d.name, d.original, d.description, d.text_status) == ("Seal kit spec 2026-11-30.pdf", SPEC, "Vendor's seal kit spec.", "none")
    c = m.captures[r.capture_id]
    # A capture whose only file is a link is typed, and listed by the link's name; nothing is copied or read.
    assert (c.source, c.title, c.documents[0].save_a_copy, c.documents[0].extract) == ("typed", "Seal kit spec 2026-11-30.pdf", False, False)
    assert not (root / "Documents" / "D000005").exists() and not (root / "Tasks" / "T000008" / "Files" / "2026-10-08 Seal kit spec 2026-11-30.pdf").exists()
    assert r.problems == []
    assert f'"original":"{SPEC}"' in (root / "Captures" / "2026" / "10" / r.capture_id / "capture.md").read_text(encoding="utf-8")
    assert [f.kind for f in m.files_of("T000008") if f.document == "D000005"] == ["Link"]
    assert f"- Link: Seal kit spec 2026-11-30.pdf · `{SPEC}` · D000005" in (root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8")
    assert edits.source_of(root, m, "D000005") is None  # never handed to File Explorer
    # The same link again reuses its document; a link differing in case is another document.
    save(sample_root, CaptureDraft(task="T000008", types={"note"}, files=[FileRow("x", SPEC, "Rev B.")]))
    save(sample_root, CaptureDraft(task="T000008", types={"note"}, files=[FileRow("y", SPEC.replace("Line1", "LINE1"), "Other.")]))
    m = Model(conn)
    assert m.documents["D000005"].description == "Rev B." and m.documents["D000006"].original == SPEC.replace("Line1", "LINE1")


def test_a_new_task_with_a_link_keeps_it_out_of_its_description(sample_root):
    r = save(sample_root, CaptureDraft(content=f"Review the pump datasheet.\n{OFFICE}", types={"new_task"},
                                       new_task=NewTaskFields(title="Review the datasheet"), files=[FileRow(link_name(OFFICE), OFFICE, "Datasheet.")]))
    m = Model(sample_root[0])
    assert m.task(r.created_task).description == "Review the pump datasheet."
    assert [(f.kind, f.name) for f in m.files_of(r.created_task)] == [("Link", "Pump datasheet.docx")]


def test_the_pages_offer_copy_link_only(sample_root):
    conn, root, _ = sample_root
    save(sample_root, CaptureDraft(task="T000008", types={"note"}, files=[FileRow(link_name(SPEC), SPEC, "Vendor's seal kit spec.")]))
    m = Model(conn)
    pages = DetailPages(m, AT.date(), lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    files = pages.task_page("T000008", PageState(tab="files"))
    assert 'href="doc:D000005"' in files and 'href="copylink:D000005"' in files and "show:doc:D000005" not in files
    doc = pages.document_page("D000005")
    assert "Link D000005" in doc and SPEC in doc and "never opens or fetches links" in doc and "Saved copies" not in doc


def test_the_capture_window_takes_links(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: AT)
    w = CaptureWindow(ctx)
    w.show_capture(task="T000008")
    try:
        w.content.setPlainText(f"Seal kit spec:\n{SPEC}")
        w._sync_paths()
        [entry] = w.files
        assert (entry.row.name, entry.row.path, entry.src) == ("Seal kit spec 2026-11-30.pdf", SPEC, "pasted")
        assert entry.copy.isHidden() and entry.extract.isHidden() and w.copy_hint.isHidden()
        assert w.focusWidget() is not entry.desc  # typing a link by hand isn't interrupted
        w.content.setPlainText("Seal kit spec:")
        w._sync_paths()
        assert w.files == []
        w.add_link_url("example.com/a")
        assert w.error.text().startswith("That isn't a web link") and w.files == []
        w.add_link_url(OFFICE)
        w.add_link_url(OFFICE)
        assert len(w.files) == 1 and "is already added" in w.error.text()
        w.files[0].desc.setText("Pump datasheet.")
        w.save()
        d = Model(conn).documents["D000005"]
        assert (d.original, d.description) == (OFFICE, "Pump datasheet.")
    finally:
        w.deleteLater()


def test_the_browse_tool_copies_a_link_and_never_shows_it(qapp, sample_root):
    conn, root, fs = sample_root
    save(sample_root, CaptureDraft(task="T000008", types={"note"}, files=[FileRow(link_name(SPEC), SPEC, "Vendor's seal kit spec.")]))
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: AT)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.revealed = []
    w.reveal = lambda path: w.revealed.append(path) or True
    w.show_browse()
    try:
        w.on_link(QUrl("doc:D000005"))
        assert w.sel == ("doc", "D000005")
        assert [b.text() for b in w.actions.findChildren(QPushButton) if b.isVisible()] == ["Copy link"]
        QGuiApplication.clipboard().clear()
        w.on_link(QUrl("copylink:D000005"))
        assert QGuiApplication.clipboard().text() == SPEC and "Copied the link to Seal kit spec" in w.status.text()
        QGuiApplication.clipboard().clear()
        w.reveal_key(("doc", "D000005"))  # double-clicking its row copies it too
        assert QGuiApplication.clipboard().text() == SPEC and w.revealed == []
    finally:
        capture.deleteLater()
        w.deleteLater()
