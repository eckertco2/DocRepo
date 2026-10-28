"""Pictures, files and tables on the notes page, and its frame (release 5.27): the PNG write, the page's new lines,
captures made on the page, their descriptions, the capture window's pasted picture, the editor's tables and the frame."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db, edits, notes_page  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.safe_fs import WriteRefused  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402
from docrepo.ui.rich_edit import png_bytes  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
PAGE = "\n".join(["# Site", "Intro", "- ![Picture 1.png](document:D000031)", "  - The nameplate", "- [File: Pump curve.pdf](document:D000032)",
                  "  - ", "| Part | Qty \\| size |", "|---|---|", "| **Seal** | 2 |", "", notes_page.text_line("| not a table"), "After"])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def picture(colour: str = "#3b78c4", w: int = 300, h: int = 120) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


# ---- the PNG write (decision 127) ----
def test_a_pasted_picture_is_written_as_png_only_and_never_over_another(fs, data_root):
    target = data_root / "Tasks" / "T000012" / "Files" / "Picture.png"
    assert fs.write_picture(target, b"\x89PNG data").read_bytes() == b"\x89PNG data"
    with pytest.raises(FileExistsError):
        fs.write_picture(target, b"other")
    with pytest.raises(WriteRefused):
        fs.write_picture(data_root / "x.exe", b"MZ")
    with pytest.raises(WriteRefused):
        fs.write_picture(data_root.parent / "outside.png", b"x")


# ---- the page's new lines ----
def test_pictures_attachments_and_tables_on_the_page():
    lines = notes_page.lines_of(PAGE)
    assert [(x.kind, x.level, x.ref) for x in lines][2:9] == [("picture", 1, "D000031"), ("text", 0, ""), ("attachment", 1, "D000032"),
                                                              ("text", 0, ""), ("row", 0, ""), ("row", 0, ""), ("row", 0, "")]
    assert lines[10].kind == "text" and lines[10].text == "| not a table"
    assert notes_page.write(lines) == PAGE
    assert notes_page.cells_of("| Part | Qty \\| size |") == ["Part", "Qty | size"] and notes_page.is_separator("|---|:--:|")
    assert notes_page.row_line(["a|b", "c"]) == "| a\\|b | c |"
    assert notes_page.descriptions(PAGE) == {"D000031": "The nameplate", "D000032": ""}
    assert notes_page.document_ids(PAGE) == {"D000031", "D000032"}
    assert "Part Qty | size" in notes_page.words(PAGE) and "---" not in notes_page.words(PAGE)
    md = notes_page.task_md(PAGE, lambda _: None, lambda d: f"Files/{d}.png" if d == "D000031" else None)
    assert "- ![Picture 1.png](Files/D000031.png)" in md and "- File: Pump curve.pdf" in md
    i = md.index("| Part | Qty \\| size |")
    assert md[i - 1] == "" and md[i + 1] == "|---|---|" and md[i + 2] == "| **Seal** | 2 |"  # a table's rows stay together


# ---- captures made on the page ----
@pytest.fixture
def root(sample_root):
    return sample_root


def test_a_pasted_picture_is_a_capture_of_the_page_s_with_its_description(root, qapp):
    conn, data_root, fs = root
    cid, doc, name = edits.add_page_picture(conn, data_root, fs, SETTINGS, "T000012", png_bytes(picture()), AT)
    m = Model(conn)
    c, d = m.captures[cid], m.documents[doc]
    assert name == "Picture 2026-10-08 1410.png" and c.page_made and c.task == "T000012" and c.document_ids == [doc]
    assert Path(d.original) == data_root / "Tasks" / "T000012" / "Files" / name and Path(d.original).read_bytes().startswith(b"\x89PNG")
    assert d.description == f"Rigging plan – Pasted picture – {name}"
    assert notes_page.get(conn, "T000012") == m.pages["T000012"]  # Save added nothing: the page shows it at the caret
    page = notes_page.get(conn, "T000012") + "\n" + notes_page.item_line("picture", name, doc) + "\n  - The sling arrangement"
    edits.save_page(conn, data_root, fs, "T000012", page, AT)
    assert Model(conn).documents[doc].description == "The sling arrangement"  # decision 125
    assert cid in notes_page.on_page(Model(conn), "T000012", page)
    edits.save_page(conn, data_root, fs, "T000012", page.replace("The sling arrangement", ""), AT)
    assert Model(conn).documents[doc].description == f"Rigging plan – Pasted picture – {name}"  # left empty: made up again
    md = (data_root / "Tasks" / "T000012" / "Task.md").read_text(encoding="utf-8")
    assert f"- ![{name}](Files/Picture%202026-10-08%201410.png)" in md
    # A second paste in the same minute gets a name of its own.
    assert edits.add_page_picture(conn, data_root, fs, SETTINGS, "T000012", png_bytes(picture()), AT)[2] == "Picture 2026-10-08 1410 (2).png"


def test_a_dropped_file_is_a_capture_of_the_page_s(root, tmp_path):
    conn, data_root, fs = root
    f = tmp_path / "Lift notes.txt"
    f.write_text("Sling angle 60 degrees", encoding="utf-8")
    cid, doc, name = edits.add_page_file(conn, data_root, fs, SETTINGS, "T000012", str(f), AT)
    m = Model(conn)
    assert m.captures[cid].page_made and m.documents[doc].original == str(f) and name == "Lift notes.txt"
    assert m.documents[doc].description == "Rigging plan – Attached document – Lift notes.txt"
    # Add it again puts its line and description back, as a page-made capture's block has no caption.
    assert edits.add_again(conn, data_root, fs, cid, "T000012", AT).message == f"{cid} is on the page again."
    assert notes_page.get(conn, "T000012").endswith(f"\n- [File: Lift notes.txt](document:{doc})\n  - ")


def test_a_capture_window_picture_reaches_its_capture_s_folder_and_the_page(root, qapp):
    conn, data_root, fs = root
    ctx = AppContext(conn, data_root, fs, SETTINGS, now=lambda: AT)
    cw = CaptureWindow(ctx)
    cw.task = "T000012"
    cw.content.setPlainText("Photo of the lug")
    md = QMimeData()
    md.setImageData(picture("#2e9483"))
    cw.content.insertFromMimeData(md)  # decision 129: a file of the capture's, not inside the text
    assert [e.row.name for e in cw.files] == ["Picture 2026-10-08 1410.png"] and cw.content.toPlainText() == "Photo of the lug"
    from docrepo.save import CaptureDraft, save_capture

    r = save_capture(conn, data_root, fs, SETTINGS, CaptureDraft(content="Photo of the lug", task="T000012", files=[e.row for e in cw.files]), AT)
    m = Model(conn)
    d = m.documents[m.captures[r.capture_id].document_ids[0]]
    assert d.capture == r.capture_id and d.description == "Rigging plan – Pasted picture – Picture 2026-10-08 1410.png"
    saved = edits.source_of(data_root, m, d.id)
    assert saved.parent.name == "attachments" and saved.read_bytes().startswith(b"\x89PNG")
    page = notes_page.get(conn, "T000012")
    assert page.endswith(f"\nPhoto of the lug\n- ![Picture 2026-10-08 1410.png](document:{d.id})\n  - ")
    cw.deleteLater()


# ---- the editor ----
def test_the_editor_keeps_pictures_attachments_and_tables(qapp, tmp_path):
    path = tmp_path / "p.png"
    picture().save(str(path))
    n = NotesEdit()
    n.picture_path = lambda d: path if d == "D000031" else None
    n.resize(700, 600)
    n.show()
    n.set_page(PAGE)
    assert n.page() == PAGE
    kinds = [n.kind(b) for b in n.blocks()]
    assert kinds[:6] == ["heading", "text", "picture", "text", "attachment", "text"] and kinds.count("cell") == 4
    pic = next(b for b in n.blocks() if n.kind(b) == "picture")
    n.setTextCursor(QTextCursor(pic))
    QTest.keyClicks(n, "x")  # typing on a picture goes to its description
    assert "  - The nameplatex" in n.page()  # it carries on the description
    n.undo()
    n.setTextCursor(QTextCursor(pic))
    QTest.keyClick(n, Qt.Key.Key_Backspace)  # the picture goes with its description; its file stays
    assert "Picture 1.png" not in n.page() and "The nameplate" not in n.page()
    n.undo()
    cell = next(b for b in n.blocks() if n.kind(b) == "cell" and b.text() == "2")
    c = QTextCursor(cell)
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    n.setTextCursor(c)
    QTest.keyClick(n, Qt.Key.Key_Tab)  # the last cell: a new row
    QTest.keyClicks(n, "Ring")
    QTest.keyClick(n, Qt.Key.Key_Tab)
    QTest.keyClicks(n, "4")
    assert "| Ring | 4 |" in n.page()


def test_a_table_pasted_from_html_and_one_inserted(qapp):
    n = NotesEdit()
    n.set_page("Before")
    c = QTextCursor(n.document().lastBlock())
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    n.setTextCursor(c)
    md = QMimeData()
    md.setHtml("<p>From the sheet</p><table><tr><td colspan=2><b>Spares</b></td><td>Due</td></tr>"
               "<tr><td>Seal</td><td style='color:red'>2</td><td>Fri</td></tr></table>")
    n.insertFromMimeData(md)
    assert n.page().split("\n") == ["Before", "From the sheet", "| Spares |  | Due |", "|---|---|---|", "| Seal | 2 | Fri |"]
    n.set_page("Plain")
    c = QTextCursor(n.document().begin())
    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    n.setTextCursor(c)
    n.insert_table(2, 3)
    QTest.keyClicks(n, "A")
    assert n.page() == "Plain\n| A |  |  |\n|---|---|---|\n|  |  |  |"


def test_a_table_folds_with_its_section_counted_by_its_rows(qapp):
    n = NotesEdit()
    n.set_page("## H\nIn\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n## Next\nAfter")
    n.toggle_fold(n.document().begin())
    cells = [b for b in n.blocks() if n.kind(b) == "cell"]
    assert cells and not any(b.isVisible() for b in cells) and n.section_summary(n.document().begin()) == "4 lines"
    # Rows added later have their cells' room too, as one step for Ctrl+Z.
    n.toggle_fold(n.document().begin())
    n.setTextCursor(QTextCursor(cells[-1]))
    QTest.keyClick(n, Qt.Key.Key_Tab)
    assert all(b.blockFormat().leftMargin() == 6 for b in n.blocks() if n.kind(b) == "cell")
    assert n.page().split("\n")[2:6] == ["| A | B |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"] and n.page().split("\n")[6] == "|  |  |"
    n.undo()
    assert "|  |  |" not in n.page()


def test_lines_don_t_move_on_a_page_with_a_table_and_it_says_so(qapp):
    n = NotesEdit()
    n.set_page("Before\n| A | B |\n|---|---|\n| 1 | 2 |\nAfter\nLast")
    said = []
    n.message.connect(said.append)
    n.setTextCursor(QTextCursor(n.document().lastBlock()))
    n.move_lines(-1)
    assert n.page() == "Before\n| A | B |\n|---|---|\n| 1 | 2 |\nAfter\nLast" and "table" in said[0]


# ---- on the task page ----
@pytest.fixture
def browse(qapp, sample_root):
    conn, root_, fs = sample_root
    ctx = AppContext(conn, root_, fs, SETTINGS, now=lambda: AT)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def test_a_picture_pasted_on_the_task_page(browse):
    browse.go_task("T000012")
    notes = browse.task_pane.notes
    c = notes.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    notes.setTextCursor(c)
    browse._picture_pasted(picture())
    page = notes_page.get(browse.conn, "T000012")
    m = Model(browse.conn)
    cid = next(c.id for c in m.captures.values() if c.page_made)
    doc = m.captures[cid].document_ids[0]
    assert f"- ![Picture 2026-10-08 1410.png](document:{doc})\n  - " in page
    assert notes.kind(notes.textCursor().block()) == "text" and notes.textCursor().block().text() == ""  # the caret on its description
    assert "On the notes page" in browse.task_pane.bottom.toPlainText()
    pic = next(b for b in notes.blocks() if notes.kind(b) == "picture")
    fmt = next(f for f in (pic.begin().fragment().charFormat(),) if f.isImageFormat()).toImageFormat()
    assert fmt.width() == 300  # its own size, under the page's widest


def test_the_notes_frame_shows_where_you_type(browse):
    browse.go_task("T000012")
    pane = browse.task_pane
    assert pane.card.objectName() == "notesCard" and pane.title.parentWidget().parentWidget() is pane.card
    pane.notes.focus_changed.emit(True)
    assert pane.card.property("typing") is True
    pane.notes.focus_changed.emit(False)
    assert pane.card.property("typing") is False
    assert not pane.format_bar.isHidden() and pane.table_button.menu().actions()[0].text() == "2 columns, 2 rows"


def test_the_schema_has_page_made_captures(data_root, fs):
    conn = db.connect(fs, data_root)
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 11  # 11 brought page_made; later versions keep it
    assert [r[1] for r in conn.execute("PRAGMA table_info(captures)") if r[1] == "page_made"] == ["page_made"]
    conn.close()
