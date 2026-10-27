"""A task's notes page, edited in place on its task page (release 5.25; the notes page plan, decisions 95 to 120).

``NotesEdit`` is the capture window's ``RichEdit`` (decision 117: Qt's own text box, no new package) holding one page
(``docrepo.notes_page``): DocRepo's formatting and lists, headings of any text at three levels that fold, captions
that start each capture's block, and file lines. It's as tall as its text: the task page's one scroll holds it, with
the facts above and the history below (``task_pane``).

- **Headings** (decision 118): Ctrl+Alt+1, 2 and 3, OneNote's keys, make the line a heading; Ctrl+Alt+0 makes it text
  again. Alt+Shift+D adds today's date as a heading at the caret (decision 110). Each heading folds, from the arrow
  beside it, or Alt+Shift+- and Alt+Shift++ for the section the caret is in. A folded heading says how many captures
  (or lines) it holds, and the arrow keys pass over its section. Which headings are folded is kept for each task.
- **Captions** (decisions 109 and 120): a click opens the capture. Typing on one goes to the line below; Backspace or
  Delete on one removes it, and its capture is then no longer on the page. Enter on a heading or a caption starts a
  line of text under it, and Backspace and Delete never join a line to one.
- **File lines** open the document.
- **Copy and paste** inside the page keep whole lines as they are (headings, captions, lists); a line's words go in at
  the caret. Text from elsewhere comes in as ``RichEdit`` takes it.
- **Moving lines** (Alt+Shift+Up and Down) moves a line with the list items under it, or a folded heading with its
  section, keeping what each line is.
- **Saving** happens a moment after typing stops, and when the page loses the caret (``changed``).
- **Pictures, files and tables** (release 5.27, decisions 124 to 128): a picture pasted (``image_pasted``) or a file
  dropped (``files_dropped``) becomes a capture of the page's, which the browse window makes; ``insert_item`` then puts
  its picture or file line at the caret, with an empty list item under it for its description. A picture shows at its
  own size up to the page's width, from ``picture_path``. A table pasted from Excel, Word, Outlook or a web page stays a
  table (one line of text a cell, merged cells split); Tab and Shift+Tab go between cells, Tab in the last adds a row,
  Enter goes down a row, and right-click adds or removes rows and columns. ``insert_table`` makes one.
- **Checklists** (release 5.26): ``RichEdit``'s, on lines of text. The Checklist summary (``checklist_summary``) shows the
  page's checklist lines again, each row the line itself: ``checklist_blocks``, ``set_line_from``, ``remove_line``,
  ``add_check_item`` and ``go_to_block`` are what it uses.
"""
from __future__ import annotations

from datetime import date

from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat, QTextImageFormat, QTextLength, QTextListFormat, QTextTable,
                           QTextTableFormat)
from PySide6.QtWidgets import QSizePolicy, QTextEdit, QWidget

from docrepo import markup, notes_page
from docrepo.notes_page import Line
from docrepo.ui import tokens
from docrepo.ui.look import LOOK
from docrepo.ui.rich_edit import MARKER, NUMBERED, RichEdit, block_markup

FOLDED = 1  # a heading block's user state while its section is folded
LEFT = 28   # the gutter beside the page, where the fold arrows go
PAGE_MIME = "application/x-docrepo-notes-page"
PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
SAVE_AFTER_MS = 800
#: Each heading level's size above the body's, in points.
HEADING_SIZES = {1: 3.5, 2: 1.5, 3: 0.5}
#: The widest a picture shows on the page, in pixels (release 5.27).
PICTURE_WIDTH = 560


def _grey() -> QColor:
    return QColor(tokens.colour("text2"))


class NotesEdit(RichEdit):
    """The notes page's editor. ``changed`` carries the page to save; ``open_ref`` a capture's or document's ID."""

    changed = Signal(str)
    open_ref = Signal(str)
    message = Signal(str)
    folds_changed = Signal()
    files_dropped = Signal(list)  # local files dropped on the page (release 5.27)
    focus_changed = Signal(bool)  # the frame round the notes shows where you're typing (decision 130)
    takes_pictures = True
    #: A document's file, for its picture: set by the browse window.
    picture_path = None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notesPage")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.viewport().setMouseTracking(True)
        self.setPlaceholderText("Notes for this task. Captures saved on it are added here; type anywhere.")
        self.saved_body = ""     # the page as docs.db holds it, as far as this editor knows
        self.day_headings = False
        self.on_page_key = None  # the pane's Page Up and Page Down: this box is as tall as its text
        self._quiet = self._moving = False
        self._hover = -1
        self._clip = None
        self._clip_lines = False
        self._clip_first = None  # the first copied line's format and list, which Qt's fragment loses
        self._clip_token = 0
        self._blocks = 0
        doc = self.document()
        doc.documentLayout().documentSizeChanged.connect(lambda _: self._fit())
        doc.contentsChange.connect(self._contents_change)
        self.cursorPositionChanged.connect(self._cursor_moved)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_AFTER_MS)
        self._save_timer.timeout.connect(self.save_now)
        self._restructure = QTimer(self)
        self._restructure.setSingleShot(True)
        self._restructure.setInterval(0)
        self._restructure.timeout.connect(self.refold)
        self._keys.update({
            "Alt+Shift+D": self.add_today_heading,
            "Ctrl+Alt+1": lambda: self.set_heading(1), "Ctrl+Alt+2": lambda: self.set_heading(2),
            "Ctrl+Alt+3": lambda: self.set_heading(3), "Ctrl+Alt+0": lambda: self.set_heading(0),
            "Alt+Shift+-": lambda: self.fold_here(True), "Alt+Shift+_": lambda: self.fold_here(True),
            "Alt+Shift++": lambda: self.fold_here(False), "Alt+Shift+=": lambda: self.fold_here(False),
        })

    # ---- what a block is ----
    def blocks(self):
        b = self.document().begin()
        while b.isValid():
            yield b
            b = b.next()

    @staticmethod
    def ref_of(block) -> tuple[str, str] | None:
        """A caption's or file line's ("capture" or "document", ID): a line that starts with its link."""
        it = block.begin()
        if it.atEnd():
            return None
        href = it.fragment().charFormat().anchorHref()
        scheme, _, ref = href.partition(":")
        return (scheme, ref) if scheme in ("capture", "document") and ref else None

    def kind(self, block) -> str:
        """"heading", "caption", "file", "picture", "attachment", "cell" (in a table) or "text"."""
        if block.blockFormat().headingLevel():
            return "heading"
        if QTextCursor(block).currentTable() is not None:
            return "cell"
        it = block.begin()
        while not it.atEnd():
            if it.fragment().charFormat().isImageFormat():
                return "picture"
            it += 1
        ref = self.ref_of(block)
        if ref:
            return "caption" if ref[0] == "capture" else "attachment" if block.textList() is not None else "file"
        return "text"

    def heading_of(self, block):
        """The nearest heading at or above ``block``."""
        b = block
        while b.isValid() and not b.blockFormat().headingLevel():
            b = b.previous()
        return b if b.isValid() else None

    def section_end(self, heading):
        level, last, b = heading.blockFormat().headingLevel(), heading, heading.next()
        while b.isValid() and not (b.blockFormat().headingLevel() and b.blockFormat().headingLevel() <= level):
            last, b = b, b.next()
        return last

    # ---- formats ----
    def _block_format(self, kind: str, level: int = 0) -> QTextBlockFormat:
        f = QTextBlockFormat()
        if kind == "heading":
            f.setHeadingLevel(level)
            f.setTopMargin({1: 16, 2: 10}.get(level, 8))
            f.setBottomMargin(4)
            f.setLineHeight(115, PROPORTIONAL)
        elif kind == "caption":
            f.setTopMargin(10)
            f.setLineHeight(115, PROPORTIONAL)
        elif kind == "picture":  # a picture's line is as tall as the picture (release 5.27)
            f.setTopMargin(4)
            f.setBottomMargin(4)
            f.setLineHeight(100, PROPORTIONAL)
        else:
            f.setBottomMargin(2)
            f.setLineHeight(130, PROPORTIONAL)
        return f

    def _char_format(self, kind: str, level: int = 0, href: str = "") -> QTextCharFormat:
        f = QTextCharFormat()
        if kind == "heading":
            f.setFontPointSize(tokens.BODY + HEADING_SIZES.get(level, 0.5))
            f.setFontWeight(QFont.Weight.DemiBold)
        elif kind in ("caption", "file"):
            f.setAnchor(True)
            f.setAnchorHref(href)
            if kind == "caption":
                f.setFontPointSize(tokens.CAPTION)
                f.setForeground(_grey())
            else:
                f.setForeground(QColor(tokens.colour("accent")))
        return f

    def style_block(self, block) -> None:
        """Give ``block`` its kind's spacing and look, keeping its words and their bold, italic and the like."""
        kind, bf = self.kind(block), block.blockFormat()
        new = self._block_format(kind, bf.headingLevel())
        for prop in (QTextFormat.Property.BlockTopMargin, QTextFormat.Property.BlockBottomMargin,
                     QTextFormat.Property.LineHeight, QTextFormat.Property.LineHeightType):
            if new.hasProperty(prop):
                bf.setProperty(prop, new.property(prop))
            else:
                bf.clearProperty(prop)
        if block == self.document().begin():
            bf.setTopMargin(2)
        c = QTextCursor(block)
        c.setBlockFormat(bf)
        if kind != "text":
            ref = self.ref_of(block)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            c.mergeCharFormat(self._char_format(kind, bf.headingLevel(), f"{ref[0]}:{ref[1]}" if ref else ""))

    # ---- the page in and out ----
    def _put(self, c: QTextCursor, line: Line, new_block: bool) -> None:
        """Write one page line at ``c``: into a new block after c's, or into c's own (empty) block."""
        if line.kind == "text":
            m = markup.LIST_LINE.match(line.text)
            bf, cf = self._block_format("text"), QTextCharFormat()
            if new_block:
                c.insertBlock(bf, cf)
            else:
                c.setBlockFormat(bf)
                c.setBlockCharFormat(cf)
            rest, done = line.text, None
            if m:
                self._join_list(c, len(m.group(1)) // 2 + 1, bool(m.group(3)))
                rest = line.text[m.end():]
                check = None if m.group(3) else markup.CHECK.match(rest)
                if check:  # a checklist line (release 5.26)
                    done = check.group(1) in "xX"
                    rest = rest[check.end():]
                    bf2 = c.blockFormat()
                    bf2.setMarker(MARKER.Checked if done else MARKER.Unchecked)
                    c.setBlockFormat(bf2)
            for text, marks, colour in markup._segments(rest):
                f = QTextCharFormat()
                if done:
                    f.setForeground(QColor(markup.TICKED_GREY))
                if "b" in marks:
                    f.setFontWeight(QFont.Weight.Bold)
                if "i" in marks:
                    f.setFontItalic(True)
                if "s" in marks:
                    f.setFontStrikeOut(True)
                if "u" in marks:
                    f.setFontUnderline(True)
                if "mark" in marks:
                    f.setBackground(QBrush(QColor(markup.HIGHLIGHTS.get(colour or "yellow", markup.HIGHLIGHTS["yellow"]))))
                c.insertText(text, f)
            return
        if line.kind in ("picture", "attachment"):
            bf, cf = self._block_format("text"), self._char_format("file", 0, f"document:{line.ref}")
            if new_block:
                c.insertBlock(bf, QTextCharFormat())
            else:
                c.setBlockFormat(bf)
                c.setBlockCharFormat(QTextCharFormat())
            self._join_list(c, line.level, False)
            if line.kind == "picture":
                c.insertImage(self._image_format(line.text, line.ref))
            else:
                c.insertText(line.text, cf)
            c.setCharFormat(QTextCharFormat())
            return
        href = f"{'capture' if line.kind == 'caption' else 'document'}:{line.ref}" if line.kind != "heading" else ""
        bf, cf = self._block_format(line.kind, line.level), self._char_format(line.kind, line.level, href)
        if new_block:
            c.insertBlock(bf, cf)
        else:
            c.setBlockFormat(bf)
            c.setBlockCharFormat(cf)
        c.insertText(line.text, cf)
        if line.kind != "heading":
            c.setCharFormat(QTextCharFormat())  # what's typed after a link isn't part of it

    @staticmethod
    def _join_list(c: QTextCursor, level: int, numbered: bool) -> None:
        """Make c's block a list item at ``level``, in the list just above at that level and kind if there is one."""
        style = QTextListFormat.Style.ListDecimal if numbered else QTextListFormat.Style.ListDisc
        prev = c.block().previous()
        while prev.isValid() and prev.textList() is not None and prev.textList().format().indent() > level:
            prev = prev.previous()
        lst = prev.textList() if prev.isValid() else None
        if lst is not None and lst.format().indent() == level and (lst.format().style() in NUMBERED) == numbered:
            lst.add(c.block())
        else:
            lf = QTextListFormat()
            lf.setStyle(style)
            lf.setIndent(level)
            c.createList(lf)

    def _write_lines(self, c: QTextCursor, lines: list[Line], fresh: bool) -> None:
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.kind == "row":  # a table: its rows, the separator line not among them
                rows = []
                while i < len(lines) and lines[i].kind == "row":
                    if not notes_page.is_separator(lines[i].text):
                        rows.append(notes_page.cells_of(lines[i].text))
                    i += 1
                if rows:
                    self._put_table(c, rows, fresh)
                    fresh = True  # the empty line Qt keeps after a table takes the next line
                continue
            self._put(c, line, not fresh)
            fresh = False
            i += 1

    # ---- tables (release 5.27, decision 128) ----
    def _table_format(self) -> QTextTableFormat:
        f = QTextTableFormat()
        # Qt's ordinary grid, which every cell gets, rows added later too. Qt 6 collapses borders unless told not to, and a
        # collapsed border needs each cell's own.
        f.setBorderCollapse(False)
        f.setBorder(1)
        f.setBorderBrush(QBrush(QColor(tokens.colour("stroke_strong"))))
        f.setBorderStyle(QTextTableFormat.BorderStyle.BorderStyle_Solid)
        # A cell's room is its lines' margins (_pad_cells), not the table's padding: a folded section's lines take no
        # room, so its table folds to its borders, which paintEvent covers.
        f.setCellPadding(0)
        f.setCellSpacing(0)
        f.setHeaderRowCount(1)
        f.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        f.setTopMargin(4)
        f.setBottomMargin(6)
        return f

    def _put_table(self, c: QTextCursor, rows: list[list[str]], fresh: bool) -> QTextTable:
        """A table from its rows' cells (markup), after c's line, or in its place when that's an empty line."""
        columns = max(len(r) for r in rows)
        # Qt puts a table after the caret's line and an empty line after the table, so an empty line in its place goes.
        here = c.block()
        if fresh and not here.text() and here.previous().isValid():
            prev = here.previous()
            r = QTextCursor(self.document())
            r.setPosition(prev.position() + prev.length() - 1)
            r.setPosition(here.position() + here.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            r.removeSelectedText()
            c.setPosition(prev.position() + prev.length() - 1)
        elif not fresh:
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        table = c.insertTable(len(rows), columns, self._table_format())
        for r, cells in enumerate(rows):
            for col in range(columns):
                cell = table.cellAt(r, col)
                if r == 0:
                    cf = cell.format()
                    cf.setBackground(QColor(tokens.colour("base")))
                    cell.setFormat(cf)
                cc = cell.firstCursorPosition()
                for text, marks, colour in markup._segments(cells[col] if col < len(cells) else ""):
                    cc.insertText(text, self._marked(marks, colour, bold=r == 0))
        self._pad_cells(table)
        after = table.lastCursorPosition()
        after.movePosition(QTextCursor.MoveOperation.NextBlock)
        if after.block().textList() is not None:  # the line after a table is plain, whatever the line before it was
            after.block().textList().remove(after.block())
        bf = self._block_format("text")
        after.setBlockFormat(bf)
        after.setBlockCharFormat(QTextCharFormat())
        c.setPosition(after.position())
        return table

    @staticmethod
    def _pad_cells(table: QTextTable) -> None:
        """Give every line in the table's cells its room (rows and columns added later too), in the edit going on."""
        pad = QTextBlockFormat()
        pad.setLeftMargin(6)
        pad.setRightMargin(6)
        pad.setTopMargin(4)
        pad.setBottomMargin(4)
        for r in range(table.rows()):
            for col in range(table.columns()):
                cell = table.cellAt(r, col)
                b, last = cell.firstCursorPosition().block(), cell.lastCursorPosition().block()
                while b.isValid():
                    if b.blockFormat().leftMargin() != 6:
                        QTextCursor(b).mergeBlockFormat(pad)
                    if b == last:
                        break
                    b = b.next()

    def _change_table(self, table: QTextTable, change) -> None:
        """Rows or columns added or taken away, their cells given their room, as one step for Ctrl+Z."""
        c = self.textCursor()
        c.beginEditBlock()
        change()
        self._pad_cells(table)
        c.endEditBlock()

    @staticmethod
    def _marked(marks, colour, bold: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        if "b" in marks or bold:
            f.setFontWeight(QFont.Weight.Bold if "b" in marks else QFont.Weight.DemiBold)
        if "i" in marks:
            f.setFontItalic(True)
        if "s" in marks:
            f.setFontStrikeOut(True)
        if "u" in marks:
            f.setFontUnderline(True)
        if "mark" in marks:
            f.setBackground(QBrush(QColor(markup.HIGHLIGHTS.get(colour or "yellow", markup.HIGHLIGHTS["yellow"]))))
        return f

    @staticmethod
    def table_lines(table: QTextTable) -> list[str]:
        """A table as the page keeps it: Markdown's rows, its first row the header, a cell's lines joined."""
        rows = []
        for r in range(table.rows()):
            cells = []
            for col in range(table.columns()):
                cell = table.cellAt(r, col)
                if cell.row() != r or cell.column() != col:  # a merged cell's other places: split, and empty
                    cells.append("")
                    continue
                b, last = cell.firstCursorPosition().block(), cell.lastCursorPosition().block()
                parts = []
                while b.isValid():
                    words, _ = block_markup(b)
                    if b == cell.firstCursorPosition().block() and table.format().headerRowCount() and r == 0:
                        words = words.replace("**", "") if words.startswith("**") and words.endswith("**") else words
                    if words.strip():
                        parts.append(words.strip())
                    if b == last:
                        break
                    b = b.next()
                cells.append(" ".join(parts))
            rows.append(cells)
        out = [notes_page.row_line(rows[0]), notes_page.separator_line(table.columns())] if rows else []
        return out + [notes_page.row_line(r) for r in rows[1:]]

    def insert_table(self, rows: int, columns: int) -> None:
        """A table of ``rows`` (the header row among them) by ``columns``, after the caret's line, the caret in its
        first cell (the Table button)."""
        c = self.textCursor()
        b = c.block()
        fresh = not b.text() and self.kind(b) == "text" and b.textList() is None
        c.beginEditBlock()
        table = self._put_table(c, [[""] * columns for _ in range(rows)], fresh)
        c.endEditBlock()
        self.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
        self._restructure.start()

    def _table_key(self, event) -> bool:
        """Tab, Shift+Tab and Enter in a table: the next or previous cell, a new row after the last, or the cell below."""
        c = self.textCursor()
        table = c.currentTable()
        if table is None or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        key = event.key()
        cell = table.cellAt(c)
        r, col = cell.row(), cell.column()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            back = key == Qt.Key.Key_Backtab or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            n = r * table.columns() + col + (-1 if back else 1)
            if n < 0:
                return True
            if n >= table.rows() * table.columns():
                self._change_table(table, lambda: table.appendRows(1))
            self.setTextCursor(table.cellAt(n // table.columns(), n % table.columns()).firstCursorPosition())
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if r + 1 >= table.rows():
                self._change_table(table, lambda: table.appendRows(1))
            self.setTextCursor(table.cellAt(r + 1, col).firstCursorPosition())
            return True
        return False

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Right-click in a table adds or removes its rows and columns; elsewhere, the usual menu."""
        c = self.cursorForPosition(event.pos())
        table = c.currentTable()
        menu = self.createStandardContextMenu(event.pos())
        if table is not None:
            cell = table.cellAt(c)
            r, col = cell.row(), cell.column()
            menu.addSeparator()
            for text, act in (("Insert row above", lambda: table.insertRows(r, 1)), ("Insert row below", lambda: table.insertRows(r + 1, 1)),
                              ("Insert column left", lambda: table.insertColumns(col, 1)),
                              ("Insert column right", lambda: table.insertColumns(col + 1, 1))):
                menu.addAction(text, lambda act=act: self._change_table(table, act))
            menu.addSeparator()
            menu.addAction("Delete row", lambda: table.removeRows(r, 1) if table.rows() > 1 else None)
            menu.addAction("Delete column", lambda: table.removeColumns(col, 1) if table.columns() > 1 else None)
        self._menu = menu  # kept, so tests can reach it
        menu.popup(event.globalPos())

    # ---- pictures and files put on the page (release 5.27, decisions 124 to 126) ----
    def _image_format(self, name: str, document_id: str) -> QTextImageFormat:
        f = QTextImageFormat()
        f.setName(f"docimg:{document_id}")
        f.setToolTip(name)
        f.setAnchor(True)
        f.setAnchorHref(f"document:{document_id}")
        image = self._picture(document_id)
        if image is not None and not image.isNull():
            w = min(image.width(), PICTURE_WIDTH)
            f.setWidth(w)
            f.setHeight(image.height() * w / max(1, image.width()))
        else:
            f.setWidth(160)
            f.setHeight(24)
        return f

    def _picture(self, document_id: str) -> QImage | None:
        path = self.picture_path(document_id) if self.picture_path else None
        if path is None or not Path(path).is_file():
            return None
        image = QImage(str(path))
        return None if image.isNull() else image

    def loadResource(self, kind: int, url: QUrl):  # noqa: N802 - Qt's name
        if url.scheme() == "docimg":
            image = self._picture(url.path())
            if image is None:  # the file's gone: a grey box with its name, as the page still holds it
                image = QImage(160, 24, QImage.Format.Format_ARGB32)
                image.fill(QColor(tokens.colour("hover")))
            return image
        return super().loadResource(kind, url)

    def insert_item(self, kind: str, text: str, document_id: str) -> None:
        """A picture or a file put on the page, at the caret's line, with an empty list item under it for its
        description, the caret there (decisions 124 to 126)."""
        c = self.textCursor()
        c.clearSelection()
        b = c.block()
        fresh = not b.text() and self.kind(b) == "text" and b.textList() is None
        c.beginEditBlock()
        if not fresh:
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self._put(c, Line(kind, text, 1, document_id), not fresh)
        self.style_block(c.block())
        self._put(c, Line("text", "  - "), True)
        self.style_block(c.block())
        c.endEditBlock()
        self.setTextCursor(c)
        self.setFocus()
        self._restructure.start()

    def set_page(self, body: str, folds: list[str] = (), day_headings: bool = False) -> None:
        """Show a page, as docs.db holds it, with the headings in ``folds`` folded. Undo starts afresh."""
        self._save_timer.stop()
        doc = self.document()
        self._quiet = True
        doc.setUndoRedoEnabled(False)
        doc.clear()
        frame = doc.rootFrame().frameFormat()
        frame.setLeftMargin(LEFT)
        doc.rootFrame().setFrameFormat(frame)
        lines = notes_page.lines_of(body)
        if lines:
            c = QTextCursor(doc)
            self._write_lines(c, lines, True)
        for b in list(self.blocks()):
            self.style_block(b)
        wanted = set(folds)
        for b in self.blocks():
            if b.blockFormat().headingLevel() and self.fold_key(b) in wanted:
                b.setUserState(FOLDED)
        doc.setUndoRedoEnabled(True)
        doc.setModified(False)
        self._quiet = False
        self.saved_body, self.day_headings = body, day_headings
        self._blocks = doc.blockCount()
        self.refold()

    def page(self) -> str:
        """The page as docs.db keeps it."""
        out = self._lines_out()
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out)

    def _lines_out(self) -> list[str]:
        out, done_tables = [], set()
        for b in self.blocks():
            kind = self.kind(b)
            if kind == "cell":
                table = QTextCursor(b).currentTable()
                if id(table) not in done_tables and table is not None:
                    done_tables.add(id(table))
                    out += self.table_lines(table)
                continue
            if kind in ("picture", "attachment"):
                level = b.textList().format().indent() if b.textList() is not None else 1
                ref = self.ref_of(b) or ("document", self._image_ref(b))
                text = self._image_name(b) if kind == "picture" else " ".join(b.text().split())
                out.append(notes_page.item_line(kind, text, ref[1], level))
                continue
            if kind == "heading":
                out.append(notes_page.heading_line(" ".join(b.text().split()), b.blockFormat().headingLevel()))
            elif kind in ("caption", "file"):
                ref = self.ref_of(b)
                text = " ".join(b.text().split())
                out.append(notes_page.caption_line(text, ref[1]) if kind == "caption" else notes_page.file_line(text, ref[1]))
            else:
                out.append(notes_page.text_line(block_markup(b)[0]))
        return out

    @staticmethod
    def _image_ref(block) -> str:
        it = block.begin()
        while not it.atEnd():
            f = it.fragment().charFormat()
            if f.isImageFormat():
                return f.toImageFormat().name().removeprefix("docimg:")
            it += 1
        return ""

    @staticmethod
    def _image_name(block) -> str:
        it = block.begin()
        while not it.atEnd():
            f = it.fragment().charFormat()
            if f.isImageFormat():
                return f.toolTip() or f.toImageFormat().name().removeprefix("docimg:")
            it += 1
        return ""

    @property
    def dirty(self) -> bool:
        return self._save_timer.isActive()

    def save_now(self) -> None:
        """Save what's typed, if anything changed: ``changed`` carries it to docs.db."""
        self._save_timer.stop()
        body = self.page()
        if body != self.saved_body:
            self.saved_body = body
            self.changed.emit(body)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.save_now()  # before the capture window, say, adds to the page
        self.focus_changed.emit(False)
        super().focusOutEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.focus_changed.emit(True)
        super().focusInEvent(event)

    def _contents_change(self, _pos: int, removed: int, added: int) -> None:
        if self._quiet:
            return
        self._save_timer.start()
        if removed or self.document().blockCount() != self._blocks:
            self._blocks = self.document().blockCount()
            self._restructure.start()

    def _fit(self) -> None:
        h = int(self.document().size().height()) + (self.height() - self.viewport().height())
        if h != self.height():
            self.setFixedHeight(max(h, 64))

    # ---- checklists (release 5.26) ----
    def _checkable(self, block) -> bool:
        return self.kind(block) == "text"

    def checklist_blocks(self) -> list[tuple[object, str]]:
        """Every checklist line on the page, in page order, with the heading it sits under ("" for none)."""
        out, heading = [], ""
        for b in self.blocks():
            if b.blockFormat().headingLevel():
                heading = " ".join(b.text().split())
            elif self.is_check(b):
                out.append((b, heading))
        return out

    def set_line_from(self, block, source) -> None:
        """A checklist line's words from the summary's row (``source``, a block of its own document): one change, in
        the page's undo, keeping the line's box and greying its words if it's ticked."""
        done = block.blockFormat().marker() == MARKER.Checked
        c = QTextCursor(block)
        c.beginEditBlock()
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()
        it = source.begin()
        while not it.atEnd():
            fmt = QTextCharFormat(it.fragment().charFormat())
            if done:
                fmt.setForeground(QColor(markup.TICKED_GREY))
            else:
                fmt.clearForeground()
            c.insertText(it.fragment().text(), fmt)
            it += 1
        c.endEditBlock()

    def remove_line(self, block) -> None:
        """Take a line off the page, with its line break: the summary's Remove. Ctrl+Z puts it back."""
        doc, prev = self.document(), block.previous()
        c = QTextCursor(doc)
        c.beginEditBlock()
        if prev.isValid():
            c.setPosition(prev.position() + prev.length() - 1)
            c.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        elif block.next().isValid():
            c.setPosition(block.position())
            c.setPosition(block.next().position(), QTextCursor.MoveMode.KeepAnchor)
        else:
            c.setPosition(block.position())
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()
        if not prev.isValid() and not block.next().isValid():
            self._set_tick(self.document().begin(), None)
        c.endEditBlock()
        self._restructure.start()

    def add_check_item(self, text: str):
        """The summary's Add item (decision 123): a new checklist line at the end of the page, under today's heading when
        the task uses day headings. Returns its block."""
        doc = self.document()
        c = QTextCursor(doc)
        c.beginEditBlock()
        last = doc.lastBlock()
        while last.previous().isValid() and not last.text() and self.kind(last) == "text" and not self.is_check(last) \
                and last.textList() is None and not last.previous().text() and self.kind(last.previous()) == "text":
            last = last.previous()
        c.setPosition(last.position() + last.length() - 1)
        fresh = doc.isEmpty() or (not last.text() and self.kind(last) == "text" and last.textList() is None)
        title = notes_page.day_title(date.today())
        if self.day_headings and not any(self.kind(b) == "heading" and b.text().strip() == title for b in self.blocks()):
            self._put(c, Line("heading", title, 1), not fresh)
            self.style_block(c.block())
            fresh = False
        self._put(c, Line("text", "- [ ] " + markup.escape_inline(" ".join(text.split()))), not fresh)
        self.style_block(c.block())
        c.endEditBlock()
        self._restructure.start()
        return c.block()

    def go_to_block(self, block) -> None:
        """The summary's Go to: the line on the page, unfolding what hides it, with the caret at its end."""
        self.reveal(block)
        c = QTextCursor(block)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setFocus()
        self.setTextCursor(c)

    # ---- folding ----
    @staticmethod
    def fold_key(block) -> str:
        return f"{block.blockFormat().headingLevel()}:{' '.join(block.text().split())}"

    def folds(self) -> list[str]:
        return [self.fold_key(b) for b in self.blocks() if b.blockFormat().headingLevel() and b.userState() == FOLDED]

    def refold(self) -> None:
        """Show and hide blocks from the headings' folds: a block is hidden under any folded heading above it at a
        higher level. Only the blocks that change are laid out again."""
        doc = self.document()
        lo, hi, hide_level = None, None, None
        for b in self.blocks():
            level = b.blockFormat().headingLevel()
            if hide_level is not None and level and level <= hide_level:
                hide_level = None
            visible = hide_level is None
            if b.isVisible() != visible:
                b.setVisible(visible)
                lo = b.position() if lo is None else lo
                hi = b.position() + b.length()
            if visible and level and b.userState() == FOLDED:
                hide_level = level
        if lo is not None:
            self._quiet = True
            doc.markContentsDirty(lo, hi - lo)
            self._quiet = False
        c = self.textCursor()
        if not c.block().isVisible():  # the caret was folded away: to the end of the line above that shows
            b = c.block()
            while b.isValid() and not b.isVisible():
                b = b.previous()
            if b.isValid():
                c.setPosition(b.position() + b.length() - 1)
                self._moving = True
                self.setTextCursor(c)
                self._moving = False
        self._fit()
        self.viewport().update()

    def toggle_fold(self, heading) -> None:
        heading.setUserState(-1 if heading.userState() == FOLDED else FOLDED)
        self.refold()
        self.folds_changed.emit()

    def fold_here(self, fold: bool) -> None:
        """Alt+Shift+- and Alt+Shift++, as in OneNote: fold or unfold the section the caret is in."""
        h = self.heading_of(self.textCursor().block())
        if h is not None:
            h.setUserState(FOLDED if fold else -1)
            self.refold()
            self.folds_changed.emit()

    def fold_all(self, fold: bool) -> None:
        for b in self.blocks():
            if b.blockFormat().headingLevel():
                b.setUserState(FOLDED if fold else -1)
        self.refold()
        self.folds_changed.emit()

    def reveal(self, block) -> bool:
        """Unfold every heading that hides ``block``. Says whether any did."""
        if block.isVisible():
            return False
        bound, b = 99, block.previous()
        while b.isValid() and bound > 1:
            level = b.blockFormat().headingLevel()
            if level and level < bound:
                if b.userState() == FOLDED:
                    b.setUserState(-1)
                bound = level
            b = b.previous()
        self.refold()
        self.folds_changed.emit()
        return True

    def caption_block(self, capture_id: str):
        return next((b for b in self.blocks() if self.ref_of(b) == ("capture", capture_id)), None)

    def go_to(self, capture_id: str) -> bool:
        """Put the caret on a capture's caption, unfolding what hides it (the Captures tab's On the notes page)."""
        b = self.caption_block(capture_id)
        if b is None:
            return False
        self.reveal(b)
        c = QTextCursor(b)
        c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.setFocus()
        self.setTextCursor(c)
        return True

    def section_summary(self, heading) -> str:
        end, b, captures, lines = self.section_end(heading), heading.next(), 0, 0
        while b.isValid() and b.position() <= end.position():
            captures += self.kind(b) == "caption"
            table = QTextCursor(b).currentTable()
            if table is None:
                lines += 1
            else:  # a table is as many lines as it has rows
                cell = table.cellAt(b.position())
                lines += cell.column() == 0 and b == cell.firstCursorPosition().block()
            b = b.next()
        if captures:
            return f"{captures} capture{'s' if captures != 1 else ''}"
        return f"{lines} line{'s' if lines != 1 else ''}"

    def _cursor_moved(self) -> None:
        if not (self._moving or self._quiet) and not self.textCursor().block().isVisible():
            self.reveal(self.textCursor().block())

    # ---- headings ----
    def add_today_heading(self) -> None:
        """Alt+Shift+D (decision 110): today's heading at the caret. With day headings on, the day's captures go under it."""
        title = notes_page.day_title(date.today())
        existing = next((b for b in self.blocks() if self.kind(b) == "heading" and b.text().strip() == title), None)
        if existing is not None:
            self.reveal(existing)
            c = QTextCursor(existing)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self.setTextCursor(c)
            self.message.emit(f"{title} is already on the page, so the caret went to it.")
            return
        c = self.textCursor()
        b = c.block()
        c.beginEditBlock()
        if not b.text() and self.kind(b) == "text" and b.textList() is None:
            self._put(c, Line("heading", title, 1), False)
        else:
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self._put(c, Line("heading", title, 1), True)
        self.style_block(c.block())
        self._put(c, Line("text", ""), True)
        self.style_block(c.block())
        c.endEditBlock()
        self.setTextCursor(c)
        self._restructure.start()

    def set_heading(self, level: int) -> None:
        """Ctrl+Alt+1, 2 and 3 (OneNote's keys, decision 118): the line becomes a heading of that level, which folds;
        Ctrl+Alt+0 makes it text again. A caption, a file line and a list item are left as they are."""
        c = self.textCursor()
        b = c.block()
        if self.kind(b) in ("caption", "file") or b.textList() is not None:
            return
        c.beginEditBlock()
        bf = b.blockFormat()
        bf.setHeadingLevel(level)
        QTextCursor(b).setBlockFormat(bf)
        if not level:
            ranges, it = [], b.begin()
            while not it.atEnd():
                ranges.append((it.fragment().position(), it.fragment().length(), QTextCharFormat(it.fragment().charFormat())))
                it += 1
            r = QTextCursor(b)
            for pos, length, fmt in ranges:
                fmt.clearProperty(QTextFormat.Property.FontPointSize)
                fmt.setFontWeight(QFont.Weight.Normal)
                r.setPosition(pos)
                r.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
                r.setCharFormat(fmt)
            b.setUserState(-1)
        self.style_block(b)
        c.endEditBlock()
        self._restructure.start()

    # ---- moving lines, keeping what each line is ----
    def move_lines(self, step: int) -> None:
        """Alt+Shift+Up and Alt+Shift+Down, as in OneNote: move the line (or the selected lines) with the list items
        under it, or a folded heading with its section, past the line or unit next to it. One Ctrl+Z puts it back."""
        doc, cursor = self.document(), self.textCursor()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        first, last_block = doc.findBlock(start).blockNumber(), doc.findBlock(end)
        last = last_block.blockNumber()
        if cursor.hasSelection() and end == last_block.position() and last > first:
            last -= 1
        first, last = self._unit(first, last)
        count = doc.blockCount()
        if step < 0:
            if first == 0:
                return
            j = first - 1
            while j > 0 and not doc.findBlockByNumber(j).isVisible():
                j -= 1
            j = self._unit_start(j)
            other = (j, first - 1)
        else:
            if last >= count - 1:
                return
            other = self._unit(last + 1, last + 1)
        lines = notes_page.lines_of(self.page_all())
        if len(lines) != count:
            self.message.emit("Lines don't move on a page with a table yet. Cut and paste them instead.")
            return
        folded = {n for n in range(count) if doc.findBlockByNumber(n).userState() == FOLDED}
        unit, moved = list(range(first, last + 1)), list(range(other[0], other[1] + 1))
        order = (list(range(other[0])) + unit + moved + list(range(last + 1, count)) if step < 0
                 else list(range(first)) + moved + unit + list(range(other[1] + 1, count)))
        offset, column = cursor.blockNumber() - first, cursor.positionInBlock()
        new_first = order.index(first)
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        edit.select(QTextCursor.SelectionType.Document)
        edit.removeSelectedText()
        edit.setBlockFormat(QTextBlockFormat())
        edit.setCharFormat(QTextCharFormat())
        self._write_lines(edit, [lines[n] for n in order], True)
        for b in list(self.blocks()):
            self.style_block(b)
        edit.endEditBlock()
        for i, n in enumerate(order):
            doc.findBlockByNumber(i).setUserState(FOLDED if n in folded else -1)
        self.refold()
        block = doc.findBlockByNumber(min(doc.blockCount() - 1, new_first + offset))
        here = QTextCursor(block)
        here.setPosition(block.position() + min(column, block.length() - 1))
        self.setTextCursor(here)

    def _unit(self, first: int, last: int) -> tuple[int, int]:
        """Lines ``first`` to ``last``, with the list items under the last of them, or a folded heading's section."""
        doc = self.document()
        b = doc.findBlockByNumber(last)
        if b.blockFormat().headingLevel() and b.userState() == FOLDED:
            return first, self.section_end(b).blockNumber()
        return super()._unit(first, last)

    def _unit_start(self, n: int) -> int:
        """The first line of the unit that ends at line ``n``: a folded heading whose section it's in, or itself."""
        b = self.document().findBlockByNumber(n)
        if b.isVisible():
            return n
        h = b
        while h.isValid() and not (h.isVisible() and h.blockFormat().headingLevel()):
            h = h.previous()
        return h.blockNumber() if h.isValid() else n

    def page_all(self) -> str:
        """The page, every line kept, empty ones at its end too: what moving lines works on. (A table makes the
        lines and the blocks differ in number, so lines don't move on a page with one.)"""
        return "\n".join(self._lines_out())

    # ---- keys ----
    NAV = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1, Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}

    def _skip_hidden(self, step: int, keep: bool) -> None:
        """After a move, a caret in a folded section goes on past it, as if the section weren't there."""
        c = self.textCursor()
        b = c.block()
        if b.isVisible():
            return
        while b.isValid() and not b.isVisible():
            b = b.next() if step > 0 else b.previous()
        if not b.isValid():
            b = self.document().lastBlock() if step > 0 else self.document().begin()
            while b.isValid() and not b.isVisible():
                b = b.previous() if step > 0 else b.next()
        if not b.isValid():
            return
        pos = b.position() if step > 0 and b.position() > c.position() else b.position() + b.length() - 1
        c.setPosition(pos, QTextCursor.MoveMode.KeepAnchor if keep else QTextCursor.MoveMode.MoveAnchor)
        self._moving = True
        self.setTextCursor(c)
        self._moving = False

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        key, mods = event.key(), event.modifiers()
        combo = self._key_action(event)
        c = self.textCursor()
        b = c.block()
        kind = self.kind(b)
        if kind == "cell" and self._table_key(event):
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and self.on_page_key is not None:
            self.on_page_key(-1 if key == Qt.Key.Key_PageUp else 1, bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return
        moving = key in self.NAV and not mods & Qt.KeyboardModifier.AltModifier
        if moving or (combo is not None and key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and mods & Qt.KeyboardModifier.ControlModifier
                      and not mods & Qt.KeyboardModifier.AltModifier):
            self._moving = True
            try:
                super().keyPressEvent(event)
            finally:
                self._moving = False
            self._skip_hidden(self.NAV.get(key, 1), bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return
        if combo is not None:
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and kind in ("picture", "attachment"):
            self._to_description(b)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and kind not in ("text", "cell"):
            # Enter on a heading, a caption or a file line never splits it: a new line of text under it.
            if b.userState() == FOLDED:
                b.setUserState(-1)
                self.refold()
            c.beginEditBlock()
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self._put(c, Line("text", ""), True)
            self.style_block(c.block())
            c.endEditBlock()
            self.setTextCursor(c)
            return
        if kind in ("caption", "file", "picture", "attachment") and not c.hasSelection() and key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._remove_line(b)
            return
        if key == Qt.Key.Key_Backspace and not c.hasSelection() and c.positionInBlock() == 0 and b.previous().isValid() \
                and self.kind(b.previous()) not in ("text", "cell") and b.textList() is None and kind != "cell":
            if not b.text():
                c.select(QTextCursor.SelectionType.BlockUnderCursor)
                c.removeSelectedText()
            elif kind == "text":
                self.message.emit("Backspace here would join this line to the heading or caption above, so it does nothing.")
            else:
                super().keyPressEvent(event)
            return
        if key == Qt.Key.Key_Delete and not c.hasSelection() and c.atBlockEnd() and b.next().isValid() \
                and self.kind(b.next()) not in ("text", "cell") and kind != "cell":
            self.message.emit("Delete here would join the heading or caption below to this line, so it does nothing.")
            return
        if kind in ("picture", "attachment") and event.text() and event.text().isprintable() and not mods & Qt.KeyboardModifier.ControlModifier:
            self._to_description(b)  # typing on a picture or a file goes to its description
        elif kind in ("caption", "file") and event.text() and event.text().isprintable() and not mods & Qt.KeyboardModifier.ControlModifier:
            # Typing on a caption goes to the line below it: the caption stays the capture's (decision 109).
            nxt = b.next()
            if nxt.isValid() and self.kind(nxt) == "text" and nxt.isVisible():
                c = QTextCursor(nxt)
            else:
                c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self._put(c, Line("text", ""), True)
                self.style_block(c.block())
            self.setTextCursor(c)
            self.setCurrentCharFormat(QTextCharFormat())
        super().keyPressEvent(event)

    def _description_of(self, block):
        """The list item under a picture or attachment, a level in: its description, if it has one."""
        nxt = block.next()
        level = block.textList().format().indent() if block.textList() is not None else 1
        if nxt.isValid() and nxt.textList() is not None and nxt.textList().format().indent() == level + 1 and self.kind(nxt) == "text":
            return nxt
        return None

    def _to_description(self, block) -> None:
        """The caret to a picture's or attachment's description, made if it has none."""
        d = self._description_of(block)
        c = QTextCursor(block)
        if d is None:
            level = block.textList().format().indent() if block.textList() is not None else 1
            c.beginEditBlock()
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self._put(c, Line("text", "  " * level + "- "), True)
            self.style_block(c.block())
            c.endEditBlock()
        else:
            c = QTextCursor(d)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setTextCursor(c)
        self.setCurrentCharFormat(QTextCharFormat())

    def _remove_line(self, block) -> None:
        """A caption or file line goes with the line break before it, so the line below keeps its own format. A picture
        or attachment goes with its description; its file and capture stay (decision 125)."""
        if self.kind(block) in ("picture", "attachment"):
            d = self._description_of(block)
            c = QTextCursor(self.document())
            c.beginEditBlock()
            if d is not None:
                self.remove_line(d)
            self.remove_line(block)
            c.endEditBlock()
            self.message.emit("Taken off the page. Its file and its capture stay, and Captures says it's not on the page. "
                              "Ctrl+Z puts it back.")
            return
        ref, prev = self.ref_of(block), block.previous()
        c = QTextCursor(self.document())
        c.beginEditBlock()
        if prev.isValid():
            c.setPosition(prev.position() + prev.length() - 1)
            c.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
        elif block.next().isValid():  # the first line: it goes with the line break after it; the next line keeps its format
            c.setPosition(block.position())
            c.setPosition(block.next().position(), QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
        else:
            c.setPosition(block.position())
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
            c.setBlockCharFormat(QTextCharFormat())
            self.style_block(c.block())
        c.endEditBlock()
        self.setTextCursor(c)
        if ref and ref[0] == "capture":
            self.message.emit(f"Caption removed: the text under it is no longer tied to {ref[1]}, and Captures says so. Ctrl+Z puts it back.")
        self._restructure.start()

    # ---- copy and paste: inside the page, lines stay what they are ----
    def createMimeDataFromSelection(self):  # noqa: N802 - Qt's name
        mime = super().createMimeDataFromSelection()
        c = self.textCursor()
        doc, start, end = self.document(), c.selectionStart(), c.selectionEnd()

        def at_edge(pos: int) -> bool:
            b = doc.findBlock(pos)
            return pos in (b.position(), b.position() + b.length() - 1)

        self._clip_token += 1
        self._clip = c.selection()
        self._clip_lines = doc.findBlock(start) != doc.findBlock(end) and at_edge(start) and at_edge(end)
        first = doc.findBlock(start)
        lst = first.textList()
        self._clip_first = (QTextBlockFormat(first.blockFormat()),
                            (lst.format().indent(), lst.format().style() in NUMBERED) if lst is not None else None)
        mime.setData(PAGE_MIME, QByteArray(str(self._clip_token).encode()))
        return mime

    def _paste_html_tables(self, html: str) -> None:
        """Pasted HTML with tables: each table as a table of the page's (one line of text a cell, merged cells split, no
        colours or widths), and the rest as lines of DocRepo's markup, in after the caret's line."""
        tmp = QTextDocument()
        tmp.setHtml(html)
        lines: list[Line] = []
        it = tmp.rootFrame().begin()
        while not it.atEnd():
            frame, b = it.currentFrame(), it.currentBlock()
            if frame is not None and isinstance(frame, QTextTable):
                lines += [Line("row", x) for x in self.table_lines(frame)]
            elif b.isValid():
                words, _ = block_markup(b)
                if words.strip():
                    lines.append(Line("text", words))
            it += 1
        if not lines:
            return
        c = self.textCursor()
        c.clearSelection()
        here = c.block()
        fresh = not here.text() and self.kind(here) == "text" and here.textList() is None
        c.beginEditBlock()
        self._write_lines(c, lines, fresh)
        c.endEditBlock()
        for b in list(self.blocks()):
            if self.kind(b) != "cell":
                self.style_block(b)
        self.setTextCursor(c)
        self._restructure.start()

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802 - Qt's name
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt's name
        # Read as data, not hasFormat: Qt's own copy lists only its own formats, as the clipboard hands it back here.
        ours = self._clip is not None and bytes(source.data(PAGE_MIME)).decode(errors="ignore") == str(self._clip_token)
        if not ours:
            files = [u.toLocalFile() for u in source.urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()] if source.hasUrls() else []
            if files:  # files dropped on the page: captures of the page's (decision 126)
                self.files_dropped.emit(files)
                return
            if source.hasHtml() and "<table" in source.html().lower():  # a table from Excel, Word or a web page (128)
                self._paste_html_tables(source.html())
                return
            super().insertFromMimeData(source)
            return
        tmp = QTextDocument()
        QTextCursor(tmp).insertFragment(self._clip)
        if tmp.rootFrame().childFrames():  # a table among what's pasted: Qt's own paste keeps it
            self.textCursor().insertFragment(self._clip)
            self._restructure.start()
            return
        rows = []
        b = tmp.begin()
        while b.isValid():
            rows.append(b)
            b = b.next()
        c = self.textCursor()
        if not self._clip_lines:
            # A line's words (Qt starts a whole line's words with a line break, to carry its format): in at the caret.
            c.beginEditBlock()
            c.removeSelectedText()
            for row in rows:
                it = row.begin()
                while not it.atEnd():
                    fmt = QTextCharFormat(it.fragment().charFormat())
                    fmt.setAnchor(False)
                    fmt.clearProperty(QTextFormat.Property.AnchorHref)
                    c.insertText(it.fragment().text(), fmt)
                    it += 1
            c.endEditBlock()
            self.setTextCursor(c)
            return
        first_kept = True
        if len(rows) > 1 and not rows[0].text():
            rows, first_kept = rows[1:], False
        if len(rows) > 1 and not rows[-1].text():
            rows = rows[:-1]
        c.clearSelection()
        here = c.block()
        fresh = not here.text() and self.kind(here) == "text" and here.textList() is None
        c.beginEditBlock()
        if not fresh:
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        for i, row in enumerate(rows):
            # A fragment's first line comes back without its format (a heading as plain text), so it's the copied one's.
            own = i == 0 and first_kept and self._clip_first is not None
            bf = QTextBlockFormat(self._clip_first[0] if own else row.blockFormat())
            bf.clearProperty(QTextFormat.Property.ObjectIndex)
            if i or not fresh:
                c.insertBlock(bf, QTextCharFormat())
            else:
                c.setBlockFormat(bf)
            listed = self._clip_first[1] if own else (
                (row.textList().format().indent(), row.textList().format().style() in NUMBERED) if row.textList() is not None else None)
            if listed is not None:
                self._join_list(c, *listed)
            it = row.begin()
            while not it.atEnd():
                c.insertText(it.fragment().text(), it.fragment().charFormat())
                it += 1
            self.style_block(c.block())
        c.endEditBlock()
        self.setTextCursor(c)
        self._restructure.start()

    # ---- the mouse: fold arrows, captions and file lines ----
    def _row(self, block) -> QRect:
        return self.cursorRect(QTextCursor(block))

    def heading_row_at(self, pos: QPoint):
        b = self.cursorForPosition(QPoint(LEFT + 4, pos.y())).block()
        if b.isValid() and b.isVisible() and b.blockFormat().headingLevel():
            r = self._row(b)
            if r.top() - 4 <= pos.y() <= r.bottom() + 4:
                return b
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            h = self.heading_row_at(pos) if pos.x() < LEFT else None
            if h is not None:
                self.toggle_fold(h)
                return
            scheme, _, ref = self.anchorAt(pos).partition(":")
            if scheme in ("capture", "document") and ref and not event.modifiers():
                self.open_ref.emit(ref)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        pos = event.position().toPoint()
        row = self.heading_row_at(pos)
        hover = row.blockNumber() if row is not None else -1
        if hover != self._hover:
            self._hover = hover
            self.viewport().update()
        scheme = self.anchorAt(pos).partition(":")[0]
        hand = (row is not None and pos.x() < LEFT) or scheme in ("capture", "document") or self.checkbox_at(pos) is not None
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hand else Qt.CursorShape.IBeamCursor)
        QTextEdit.mouseMoveEvent(self, event)  # the cursor's shape is set here, for the arrows and links too

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        area = event.rect()
        p = QPainter(self.viewport())
        self._cover_folded_tables(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = tokens.ui_font(tokens.CAPTION)
        layout = self.document().documentLayout()
        b = self.cursorForPosition(QPoint(LEFT + 4, area.top())).block()
        if b.previous().isValid():
            b = b.previous()
        while b.isValid():
            if b.isVisible():
                if layout.blockBoundingRect(b).top() > area.bottom():
                    break
                if b.blockFormat().headingLevel():
                    self._paint_heading(p, b, small)
            b = b.next()
        p.end()

    def _cover_folded_tables(self, p: QPainter) -> None:
        """A table in a folded section keeps its borders (Qt lays out a table whose lines are hidden), so they're covered."""
        layout, dy = self.document().documentLayout(), self.verticalScrollBar().value()
        for frame in self.document().rootFrame().childFrames():
            first = frame.firstCursorPosition().block() if isinstance(frame, QTextTable) else None
            if first is None or first.isVisible():
                continue
            # The gap between the lines that show above and below it: the table's leftovers are all in there.
            above, below = first.previous(), frame.lastCursorPosition().block().next()
            while above.isValid() and not above.isVisible():
                above = above.previous()
            while below.isValid() and not below.isVisible():
                below = below.next()
            top = layout.blockBoundingRect(above).bottom() if above.isValid() else 0
            bottom = layout.blockBoundingRect(below).top() if below.isValid() else self.document().size().height()
            if bottom > top:
                p.fillRect(QRectF(0, top - dy, self.viewport().width(), bottom - top),
                           QColor(tokens.colour("content")) if not LOOK.classic else QColor("#ffffff"))

    def _paint_heading(self, p: QPainter, b, small: QFont) -> None:
        r = self._row(b)
        folded, hover = b.userState() == FOLDED, b.blockNumber() == self._hover
        cx, cy, s = LEFT / 2, r.center().y() + 0.5, 4.5
        path = QPainterPath()
        if folded:
            path.moveTo(cx - s / 2, cy - s)
            path.lineTo(cx + s * 0.75, cy)
            path.lineTo(cx - s / 2, cy + s)
        else:
            path.moveTo(cx - s, cy - s / 2)
            path.lineTo(cx + s, cy - s / 2)
            path.lineTo(cx, cy + s * 0.75)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tokens.colour("text2" if folded or hover else "scroll")) if not LOOK.classic else QColor("#666666"))
        p.drawPath(path)
        if folded:
            line = b.layout().lineAt(0)
            text = self.section_summary(b)
            fm = QFontMetrics(small)
            x = r.left() + line.naturalTextWidth() + 12
            pill = QRectF(x, r.center().y() - fm.height() / 2 - 1, fm.horizontalAdvance(text) + 14, fm.height() + 2)
            p.setBrush(QColor(tokens.colour("hover")))
            p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            p.setFont(small)
            p.setPen(_grey())
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
