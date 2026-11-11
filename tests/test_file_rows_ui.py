"""Release 5.114, the file rows review (decisions 427 to 434): files and search results drawn one way in every list, with
less on each row. Driven offscreen over the sample data; ``test_file_rows.py`` has the parts with no Qt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QColor, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit, file_name_end  # noqa: E402
from docrepo.ui.page_view import picture  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1440, 900)
    yield w
    capture.deleteLater()
    w.deleteLater()


def rows(tree) -> list:
    out = []
    for i in range(tree.topLevelItemCount()):
        stack = [tree.topLevelItem(i)]
        while stack:
            item = stack.pop(0)
            out.append(item)
            stack[:0] = [item.child(j) for j in range(item.childCount())]
    return out


def headers(tree) -> list[str]:
    return [tree.headerItem().text(i) for i in range(tree.columnCount())]


def test_documents_have_their_type_colour_and_the_day_they_came(browse):
    """Decisions 427 and 428: no Status column (every document said Current) and no Checked day (every one said the same)."""
    browse.set_view("docs")
    assert headers(browse.tree) == ["Document", "Added"]
    item = next(x for x in rows(browse.tree) if x.data(0, KEY_ROLE) == ("doc", "D000001"))
    line = item.data(0, LINE_ROLE)
    assert (line.icon, line.icon_colour, line.icon_tip, line.chips) == ("type-pdf", "type_pdf", "PDF", ())
    assert line.second.startswith("Vendor datasheet") and "10 Sep" in item.data(1, HTML_ROLE)


def test_search_results_are_file_rows_with_a_day_at_the_end(browse):
    """Decisions 427 to 430: the type's icon, where it is then the words that matched, a short day, plural headings with counts."""
    browse.search_box.setText("datasheet")
    browse._run_search()
    tree = browse.tree
    assert headers(tree) == ["Result", "When"] and "result" in browse.pane_title.text()
    heads = [x.data(0, HTML_ROLE) for x in rows(tree) if x.data(0, KEY_ROLE) is None]
    assert any("<b>Documents</b>" in h and ">&nbsp;" in h for h in heads)
    doc = next(x for x in rows(tree) if x.data(0, KEY_ROLE) == ("doc", "D000001"))
    line = doc.data(0, LINE_ROLE)
    assert line.icon == "type-pdf" and line.icon_colour == "type_pdf" and line.context == ""
    assert line.second.startswith("Reactor impeller upgrade · ") and "10 Sep" in doc.data(1, HTML_ROLE)
    capture = next((x for x in rows(tree) if x.data(0, KEY_ROLE) and x.data(0, KEY_ROLE)[0] == "capture"), None)
    if capture is not None:
        assert "2026-" not in capture.data(0, LINE_ROLE).second and capture.data(1, HTML_ROLE).count(" ") >= 1  # no ISO stamps


def test_a_capture_s_file_row_is_two_lines(ctx, tmp_path):
    """Decision 434: the type's mark rather than the word "File", nothing said for a file that stays where it is, and the
    description with its two choices on one line."""
    path = tmp_path / "Pump curve rev C.pdf"
    path.write_bytes(b"%PDF-1.4")
    w = CaptureWindow(ctx)
    try:
        w.show_capture(mode="note", content="A file to keep")
        w.add_paths([str(path)])
        e = w.files[-1]
        assert e.note.text() == ""
        frame = e.widget.findChild(type(e.widget), "fileRow") or e.desc.parentWidget()
        words = [lb.text() for lb in frame.findChildren(type(e.note))]
        assert not any(t.startswith(("File", "<span")) for t in words) and any("Pump curve rev C.pdf" in t for t in words)
        assert any(lb.accessibleName() == "File" for lb in frame.findChildren(type(e.note)))
        e.widget.show()
        QApplication.processEvents()
        assert abs(e.desc.geometry().center().y() - e.copy.geometry().center().y()) <= 4  # one line
    finally:
        w.deleteLater()


def test_a_notes_file_line_reads_as_its_name():
    """Decision 434: "File:" and the description in secondary text, the name in the link's blue; the page keeps its words."""
    assert file_name_end("File: Pump spec.docx, the vendor's sheet", 6) == len("File: Pump spec.docx")
    assert file_name_end("File: Team site, the project's site", 6) == len("File: Team site")
    assert file_name_end("File: Notes", 6) == len("File: Notes")
    notes = NotesEdit()
    line = "[File: Pump spec.docx, the vendor's datasheet](document:D000012)"
    notes.set_page(line)
    block = notes.document().begin()
    grey, blue = QColor(tokens.colour("text2")), QColor(tokens.colour("accent"))

    def colour_at(i: int) -> QColor:
        c = QTextCursor(block)
        c.setPosition(block.position() + i + 1)
        return c.charFormat().foreground().color()

    assert colour_at(1) == grey and colour_at(10) == blue and colour_at(25) == grey
    assert notes.page().strip() == line  # its words, as the page holds them
    notes.deleteLater()


def test_the_files_group_draws_each_type_s_mark(qapp):
    from PySide6.QtCore import QUrl

    image = picture(QUrl("ft:pdf"), 1.0)
    assert image is not None and image.width() == 16 and picture(QUrl("ft:../x"), 1.0) is None
