"""The formatted content text box (mods log round 2, M0045, release 5.7).

``RichEdit`` is a QTextEdit with bold, italic, underline, strikethrough, three highlight colours, and bulleted and
numbered lists with levels. ``value()`` gives what to save: the markup (``docrepo.markup``) when anything is formatted,
else the plain text, as before. ``document_markup`` reads any QTextDocument the same way, so pasted HTML keeps only
what DocRepo can keep.

Keys, while typing in it, are OneNote's (mods log round 3, M0055, decisions 55 and 56): Ctrl+B, Ctrl+I, Ctrl+U,
Ctrl+- (strikethrough), Ctrl+Alt+H (highlight), Ctrl+. (bullets), Ctrl+/ (numbers); Ctrl+Up and Ctrl+Down to the paragraph
above or below (with Shift, selecting); Alt+Shift+Up and Alt+Shift+Down move the line, with the list items under it;
Tab and Shift+Tab, or Alt+Shift+Right and Alt+Shift+Left, move a list item in and out; "- ", "* " or "1. " at the start
of a line starts a list; Enter on an empty list item, or Backspace at its start, ends it. Release 5.7's own keys
(Ctrl+Shift+X, H, L and O) still work. A list level is 20 px.

Checklists (release 5.26, the notes page plan's decisions 86 and 91): Ctrl+1 (OneNote's to-do key), the Checklist button, or
"[] " or "[ ] " at a line's start make checklist lines, a list item with a box; again takes the boxes off. A click on a box
ticks it, and a ticked line's words go grey. Enter after a ticked line starts an unticked one. They're kept as ``- [ ]``
and ``- [x]``. The new look draws its own tick box over Qt's.

Headings (release 5.28, mods log round 4), in a box that ``takes_headings``: Ctrl+Alt+1, 2 and 3 make the line a heading,
and Ctrl+Alt+0 text again, as on the notes page, or the format bar's Heading menu; Enter at a heading's end starts a line
of text. They're kept as ``# ``, ``## `` and ``### `` (``docrepo.markup``). In a box that ``folds_here`` (the capture
window's), each heading has an arrow beside it that folds the lines under it, down to the next heading at its level or
above; Alt+Shift+- and Alt+Shift++ fold and unfold the section the caret is in, a folded heading says how many lines it
holds, and the arrow keys pass over a folded section. Folds are only for the draft: everything folded is still saved.
The notes page (``notes_edit``) has its own folding, with captions and tables.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontInfo, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPen, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QTextListFormat)
from PySide6.QtWidgets import QHBoxLayout, QMenu, QTextEdit, QToolButton, QWidget

from docrepo import markup
from docrepo.ui.icons import icon
from docrepo.ui import tokens
from docrepo.ui.look import LOOK

#: The new look's icons on the format bar (decision 4): the highlight, the lists and the checklist.
ICONS = {"mark": "highlight", "ul": "bullets", "ol": "numbers", "check": "checklist"}
MARKER = QTextBlockFormat.MarkerType

#: A list level's indent, in pixels: Qt's default is 40 (mods log round 3, M0055).
INDENT = 20

#: Each format bar button's key, as its tooltip and the Ctrl key tips show it.
KEYS = {"b": "Ctrl+B", "i": "Ctrl+I", "u": "Ctrl+U", "s": "Ctrl+-", "mark": "Ctrl+Alt+H", "ul": "Ctrl+.", "ol": "Ctrl+/", "check": "Ctrl+1",
        "heading": "Ctrl+Alt+1"}

#: A heading block's user state while its section is folded (here and on the notes page).
FOLDED = 1
#: Each heading level's size above the text's, in points (here and on the notes page).
HEADING_SIZES = {1: 3.5, 2: 1.5, 3: 0.5}
#: The room left of the text for the fold arrows, while the box has a heading (release 5.28).
GUTTER = 18

NUMBERED = (QTextListFormat.Style.ListDecimal, QTextListFormat.Style.ListLowerAlpha, QTextListFormat.Style.ListUpperAlpha,
            QTextListFormat.Style.ListLowerRoman, QTextListFormat.Style.ListUpperRoman)
_SOFT_BREAKS = "  "


def highlight_name(colour: QColor) -> str | None:
    """The highlight a background colour stands for: the nearest of the three, or none for white."""
    if colour.alpha() == 0 or (colour.lightness() >= 235 and colour.hslSaturation() < 60):
        return None
    hue = colour.hslHue()
    if 70 <= hue <= 175:
        return "green"
    if hue >= 280 or 0 <= hue < 25:
        return "pink"
    return "yellow"


def _marks(fmt: QTextCharFormat) -> tuple[frozenset[str], str | None]:
    marks = set()
    if fmt.fontWeight() >= QFont.Weight.DemiBold.value:
        marks.add("b")
    if fmt.fontItalic():
        marks.add("i")
    if fmt.fontStrikeOut():
        marks.add("s")
    if fmt.fontUnderline() and not fmt.isAnchor():
        marks.add("u")
    colour = None
    if fmt.background().style() != Qt.BrushStyle.NoBrush:
        colour = highlight_name(fmt.background().color())
        if colour:
            marks.add("mark")
    return frozenset(marks), colour


def png_bytes(image) -> bytes:
    """A pasted picture as PNG (release 5.27): what DocRepo keeps of it."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    if hasattr(image, "toImage"):
        image = image.toImage()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


def block_markup(block, headings: bool = True) -> tuple[str, bool]:
    """One block (a line) as markup, and whether it's formatted: a list item, a heading or any mark. With ``headings``
    off (pasted HTML), a heading's line is read as text, with its marks."""
    level = block.blockFormat().headingLevel()
    if level and headings and block.textList() is None:  # a heading's words, without marks (release 5.28)
        words = " ".join(block.text().replace("￼", "").replace("\xa0", " ").split())
        return (markup.heading_line(words, level), True) if words else ("", False)
    segments = []
    only_break = block.text() in _SOFT_BREAKS and block.text() != ""
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        if frag.isValid():
            text = "" if only_break else frag.text().replace("￼", "")
            for ch in _SOFT_BREAKS + "\xa0":  # and a no-break space is a space
                text = text.replace(ch, " ")
            marks, colour = _marks(frag.charFormat())
            if text:
                segments.append((text, marks, colour))
        it += 1
    # Spaces at a line's end are dropped: pasted HTML leaves them after list items and in "empty" paragraphs.
    while segments and not segments[-1][0].rstrip():
        segments.pop()
    if segments:
        segments[-1] = (segments[-1][0].rstrip(), *segments[-1][1:])
    formatted = any(marks for _, marks, _ in segments)
    line = markup.marks_text([(markup.escape_inline(text), marks, colour) for text, marks, colour in segments])
    lst = block.textList()
    if lst is not None:
        fmt = lst.format()
        marker = block.blockFormat().marker()
        if marker != MARKER.NoMarker:  # a checklist line (release 5.26)
            number = "- [x] " if marker == MARKER.Checked else "- [ ] "
        else:
            number = f"{lst.itemNumber(block) + 1}. " if fmt.style() in NUMBERED else "- "
        return "  " * max(0, fmt.indent() - 1) + number + line, True
    return markup.escape_line_start(line), formatted


def document_markup(doc: QTextDocument, headings: bool = True) -> tuple[str, bool]:
    """The document as markup, and whether anything in it is formatted. A line of text that would read as a heading
    keeps a backslash before it (release 5.28)."""
    lines: list[str] = []
    formatted = False
    block = doc.begin()
    while block.isValid():
        line, marked = block_markup(block, headings)
        if block.textList() is None and not (headings and block.blockFormat().headingLevel()):
            line = markup.escape_heading(line)
        lines.append(line)
        formatted = formatted or marked
        block = block.next()
    return "\n".join(lines), formatted


class _FoldGutter(QWidget):
    """The strip left of a box's text with its headings' fold arrows (release 5.28): a click on one folds or opens it."""

    def __init__(self, edit: RichEdit) -> None:
        super().__init__(edit)
        self.edit = edit
        self.setMouseTracking(True)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for b in self.edit._visible_headings(event.rect().top(), event.rect().bottom()):
            self.edit._paint_arrow(p, b)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        h = self.edit.heading_row_at(int(event.position().y()))
        if event.button() == Qt.MouseButton.LeftButton and h is not None:
            self.edit.toggle_fold(h)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        h = self.edit.heading_row_at(int(event.position().y()))
        hover = h.blockNumber() if h is not None else -1
        self.setCursor(Qt.CursorShape.PointingHandCursor if h is not None else Qt.CursorShape.ArrowCursor)
        if hover != self.edit._hover:
            self.edit._hover = hover
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.edit._hover != -1:
            self.edit._hover = -1
            self.update()
        super().leaveEvent(event)


class RichEdit(QTextEdit):
    """The formatted content text box. ``formatting`` is sent when the cursor's formatting changes, for the toolbar."""

    formatting = Signal()
    #: A picture pasted (a screenshot, a copied image), for the box's window to keep as a file (release 5.27).
    image_pasted = Signal(object)
    #: Whether a pasted picture goes to ``image_pasted`` (the capture window and the notes page); else it's left out.
    takes_pictures = False
    #: Whether its lines can be made headings, with the keys and the format bar's Heading menu (release 5.28).
    takes_headings = False
    #: Whether this box draws and handles its headings' fold arrows itself (the capture window's; the notes page has its own).
    folds_here = False
    #: Whether another box shows the same document (``show_text_of``).
    _shares_text = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setTabChangesFocus(False)
        self.document().setIndentWidth(INDENT)
        self.currentCharFormatChanged.connect(lambda _: self.formatting.emit())
        self.cursorPositionChanged.connect(self.formatting.emit)
        # Handled as keys, not shortcuts, so they win over a window's own (the browse tool's Ctrl+B hides its views).
        bullets, numbers = (lambda: self.toggle_list(False)), (lambda: self.toggle_list(True))
        self._keys: dict[str, Callable[[], None]] = {
            "Ctrl+B": self.toggle_bold, "Ctrl+I": self.toggle_italic, "Ctrl+U": self.toggle_underline,
            "Ctrl+-": self.toggle_strike, "Ctrl+Alt+H": self.toggle_highlight, "Ctrl+.": bullets, "Ctrl+/": numbers,
            "Ctrl+Up": lambda: self.to_paragraph(-1), "Ctrl+Down": lambda: self.to_paragraph(1),
            "Ctrl+Shift+Up": lambda: self.to_paragraph(-1, True), "Ctrl+Shift+Down": lambda: self.to_paragraph(1, True),
            "Alt+Shift+Up": lambda: self.move_lines(-1), "Alt+Shift+Down": lambda: self.move_lines(1),
            "Alt+Shift+Right": lambda: self.indent_item(1), "Alt+Shift+Left": lambda: self.indent_item(-1),
            "Ctrl+1": self.toggle_checklist,  # OneNote's to-do key (release 5.26, decision 86)
            # release 5.7's keys, kept (decision 56)
            "Ctrl+Shift+X": self.toggle_strike, "Ctrl+Shift+H": self.toggle_highlight, "Ctrl+Shift+L": bullets, "Ctrl+Shift+O": numbers}
        if self.takes_headings:  # OneNote's heading keys, as on the notes page (release 5.28)
            self._keys.update({f"Ctrl+Alt+{n}": (lambda n=n: self.set_heading(n)) for n in range(4)})
        self._hover = -1
        self._quiet_fold = False
        if self.folds_here:
            self._keys.update({"Alt+Shift+-": lambda: self.fold_here(True), "Alt+Shift+_": lambda: self.fold_here(True),
                               "Alt+Shift++": lambda: self.fold_here(False), "Alt+Shift+=": lambda: self.fold_here(False)})
            self._gutter = _FoldGutter(self)
            self.verticalScrollBar().valueChanged.connect(self._gutter.update)
            self._heading_timer = QTimer(self)
            self._heading_timer.setSingleShot(True)
            self._heading_timer.setInterval(0)
            self._heading_timer.timeout.connect(self.headings_changed)
            self.document().contentsChange.connect(self._contents_changed)
            self.cursorPositionChanged.connect(self._caret_moved)

    def setDocument(self, document: QTextDocument) -> None:  # noqa: N802 - Qt's name
        super().setDocument(document)
        document.setIndentWidth(INDENT)
        if self.folds_here:  # the pinned window shows the capture window's own text
            document.contentsChange.connect(self._contents_changed)
            self.headings_changed()

    def show_text_of(self, other: RichEdit) -> None:
        """Show another box's own document, as the pinned window's box does the capture window's. A document has one
        width, and any box showing it sets that width when its scroll bar comes or goes, hidden or not (item 75). So the
        box on screen holds it: a hidden box keeps its scroll bar as it is, and a box coming back takes the width."""
        self.setDocument(other.document())
        self._shares_text = other._shares_text = True

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().hideEvent(event)
        if self._shares_text:
            on = self.verticalScrollBar().isVisibleTo(self)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn if on else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().showEvent(event)
        if self._shares_text:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.document().setPageSize(QSizeF(self.viewport().width(), -1))

    def _key_action(self, event) -> Callable[[], None] | None:
        return self._keys.get(QKeySequence(event.keyCombination()).toString())

    def event(self, event) -> bool:  # noqa: D102 - Qt's
        if event.type() == QEvent.Type.ShortcutOverride and self._key_action(event):
            event.accept()  # the key comes to keyPressEvent, not to a shortcut
            return True
        return super().event(event)

    def clear(self) -> None:
        """Empty the box, and start the next text with no formatting."""
        super().clear()
        self.setCurrentCharFormat(QTextCharFormat())

    # ---- the value ----
    def value(self) -> tuple[str, bool]:
        """What to save: (markup, True) when anything is formatted, else (the plain text, False)."""
        text, formatted = document_markup(self.document())
        return (text, True) if formatted else (self.toPlainText().replace(" ", "\n").replace(" ", "\n"), False)

    def plain(self) -> str:
        """The text in words: list items keep their markers ("- item"), marks are dropped."""
        text, formatted = self.value()
        return markup.to_plain(text) if formatted else text

    def set_value(self, text: str, formatted: bool) -> None:
        """Show saved content text: markup when ``formatted``, else plain text."""
        if formatted:
            self.setHtml(markup.to_html(text))
            self.style_headings()
        else:
            self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def remove_line(self, line: str) -> None:
        """Delete the first line (block) whose text is ``line``, in any case, keeping the rest of the formatting."""
        block = self.document().begin()
        while block.isValid():
            if block.text().strip().lower() == line.strip().lower():
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                if block.blockNumber() == 0:  # the first block: take the line break after it instead of before
                    cursor = QTextCursor(block)
                    cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
                    if cursor.position() == block.position():  # the only block
                        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                return
            block = block.next()

    # ---- formatting ----
    def _merge(self, fmt: QTextCharFormat) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    def toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Normal if self.fontWeight() >= QFont.Weight.DemiBold.value else QFont.Weight.Bold)
        self._merge(fmt)

    def toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.fontItalic())
        self._merge(fmt)

    def toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.fontUnderline())
        self._merge(fmt)

    def toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.currentCharFormat().fontStrikeOut())
        self._merge(fmt)

    def current_highlight(self) -> str | None:
        fmt = self.currentCharFormat()
        return highlight_name(fmt.background().color()) if fmt.background().style() != Qt.BrushStyle.NoBrush else None

    def set_highlight(self, name: str | None) -> None:
        """Highlight the selection (or the word) yellow, green or pink, or take the highlight off (None)."""
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(QColor(markup.HIGHLIGHTS[name])) if name else QBrush(Qt.BrushStyle.NoBrush))
        self._merge(fmt)

    def toggle_highlight(self) -> None:
        self.set_highlight(None if self.current_highlight() else "yellow")

    def toggle_list(self, numbered: bool) -> None:
        """Make the line, or the selected lines, a bulleted or numbered list; again takes them out of it."""
        cursor = self.textCursor()
        style = QTextListFormat.Style.ListDecimal if numbered else QTextListFormat.Style.ListDisc
        lst = cursor.currentList()
        if lst is not None and (lst.format().style() in NUMBERED) == numbered:
            self._unlist(cursor)
            return
        if lst is not None:
            fmt = lst.format()
            fmt.setStyle(style)
            lst.setFormat(fmt)
            return
        fmt = QTextListFormat()
        fmt.setStyle(style)
        fmt.setIndent(1)
        cursor.createList(fmt)

    @staticmethod
    def leave_list(block) -> None:
        """Take a line out of its list with no indent of its own: QTextList.remove hands it the list's, and on screen
        a line's indent and its list's add up, though the markup reads only the list's (item 74)."""
        block.textList().remove(block)
        bf = block.blockFormat()
        bf.setIndent(0)
        QTextCursor(block).setBlockFormat(bf)

    def _unlist(self, cursor: QTextCursor) -> None:
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        block = self.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            if block.textList() is not None:
                self.leave_list(block)
            if block.blockFormat().marker() != MARKER.NoMarker:
                self._set_tick(block, None)
            block = block.next()

    def indent_item(self, delta: int) -> bool:
        """Tab or Shift+Tab in a list item: a level in or out, one step of undo. Out of the first level ends the list there."""
        cursor = self.textCursor()
        block = cursor.block()
        lst = block.textList()
        if lst is None:
            return False
        fmt = QTextListFormat(lst.format())
        level = fmt.indent() + delta
        cursor.beginEditBlock()
        if level < 1:
            self._unlist(cursor)
        else:
            # Rejoin a list at that level just above, so numbering carries on; else start one.
            prev = block.previous()
            while prev.isValid() and prev.textList() is not None and prev.textList().format().indent() > level:
                prev = prev.previous()
            target = prev.textList() if prev.isValid() else None
            self.leave_list(block)
            if target is not None and target.format().indent() == level:
                target.add(block)
            else:
                fmt.setIndent(level)
                QTextCursor(block).createList(fmt)
        cursor.endEditBlock()
        return True

    # ---- checklists (release 5.26, decisions 86 and 91) ----
    def _checkable(self, block) -> bool:
        """Whether a line can be a checklist line (the notes page leaves out headings, captions and file lines)."""
        return True

    @staticmethod
    def is_check(block) -> bool:
        return block.textList() is not None and block.blockFormat().marker() != MARKER.NoMarker

    def _set_tick(self, block, done: bool | None) -> None:
        """Tick (True), untick (False) or take the box off (None), greying a ticked line's words (decision 91)."""
        c = QTextCursor(block)
        bf = block.blockFormat()
        bf.setMarker(MARKER.NoMarker if done is None else MARKER.Checked if done else MARKER.Unchecked)
        c.setBlockFormat(bf)
        ranges, it = [], block.begin()
        while not it.atEnd():
            frag = it.fragment()
            ranges.append((frag.position(), frag.length(), QTextCharFormat(frag.charFormat())))
            it += 1
        for pos, length, fmt in ranges:
            if done:
                fmt.setForeground(QColor(markup.TICKED_GREY))
            else:
                fmt.clearForeground()
            r = QTextCursor(self.document())
            r.setPosition(pos)
            r.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            r.setCharFormat(fmt)
        if self.textCursor().block() == block:  # what's typed next on the line matches it
            fmt = self.currentCharFormat()
            if done:
                fmt.setForeground(QColor(markup.TICKED_GREY))
            else:
                fmt.clearForeground()
            self.setCurrentCharFormat(fmt)

    def toggle_tick(self, block) -> None:
        """Tick or untick a checklist line: one step of undo."""
        if not self.is_check(block):
            return
        c = QTextCursor(block)
        c.beginEditBlock()
        self._set_tick(block, block.blockFormat().marker() != MARKER.Checked)
        c.endEditBlock()
        self.formatting.emit()

    def _make_check(self, block) -> None:
        if block.textList() is None:
            prev = block.previous()
            lst = prev.textList() if prev.isValid() and self.is_check(prev) else None
            if lst is not None and lst.format().indent() == 1:
                lst.add(block)
            else:
                fmt = QTextListFormat()
                fmt.setStyle(QTextListFormat.Style.ListDisc)
                fmt.setIndent(1)
                QTextCursor(block).createList(fmt)
        self._set_tick(block, False)

    def toggle_checklist(self) -> None:
        """Ctrl+1 or the Checklist button: the line, or the selected lines, become checklist lines; again takes them out
        (decision 86), back to lines of text."""
        c = self.textCursor()
        start, end = sorted((c.selectionStart(), c.selectionEnd()))
        targets, b = [], self.document().findBlock(start)
        while b.isValid() and b.position() <= end:
            if self._checkable(b):
                targets.append(b)
            b = b.next()
        if not targets:
            return
        c.beginEditBlock()
        if all(self.is_check(t) for t in targets):
            for t in targets:
                self._set_tick(t, None)
                self.leave_list(t)
        else:
            for t in targets:
                if not self.is_check(t):
                    self._make_check(t)
        c.endEditBlock()
        self.formatting.emit()

    # ---- headings (release 5.28, mods log round 4) ----
    def blocks(self):
        b = self.document().begin()
        while b.isValid():
            yield b
            b = b.next()

    def _base_points(self) -> float:
        return QFontInfo(self.font()).pointSizeF() or float(tokens.BODY)

    def style_heading(self, block) -> None:
        """Give a heading its look (a little larger, semi-bold, room above), or a line of text back its own."""
        level = block.blockFormat().headingLevel()
        bf = block.blockFormat()
        if level:
            bf.setTopMargin({1: 10, 2: 8}.get(level, 6) if block.previous().isValid() else 2)
            bf.setBottomMargin(2)
        else:
            bf.clearProperty(QTextFormat.Property.BlockTopMargin)
            bf.clearProperty(QTextFormat.Property.BlockBottomMargin)
        c = QTextCursor(block)
        c.setBlockFormat(bf)
        ranges, it = [], block.begin()
        while not it.atEnd():
            frag = it.fragment()
            ranges.append((frag.position(), frag.length(), QTextCharFormat(frag.charFormat())))
            it += 1
        for pos, length, fmt in ranges:
            fmt.clearProperty(QTextFormat.Property.FontSizeAdjustment)
            if level:
                fmt.setFontPointSize(self._base_points() + HEADING_SIZES.get(level, 0.5))
                fmt.setFontWeight(QFont.Weight.DemiBold)
            else:
                fmt.clearProperty(QTextFormat.Property.FontPointSize)
                fmt.setFontWeight(QFont.Weight.Normal)
            c.setPosition(pos)
            c.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            c.setCharFormat(fmt)
        cf = QTextCharFormat(block.charFormat())  # what's typed into an empty heading
        cf.clearProperty(QTextFormat.Property.FontSizeAdjustment)
        if level:
            cf.setFontPointSize(self._base_points() + HEADING_SIZES.get(level, 0.5))
            cf.setFontWeight(QFont.Weight.DemiBold)
        else:
            cf.clearProperty(QTextFormat.Property.FontPointSize)
            cf.clearProperty(QTextFormat.Property.FontWeight)
        QTextCursor(block).setBlockCharFormat(cf)

    def style_headings(self) -> None:
        """Every heading's look, after the box has been given saved text (Qt's own heading sizes are far larger)."""
        for b in list(self.blocks()):
            if b.blockFormat().headingLevel():
                self.style_heading(b)
        if self.folds_here:
            self.headings_changed()

    def set_heading(self, level: int) -> None:
        """Ctrl+Alt+1, 2 and 3 (OneNote's keys): the line, or each selected line, becomes a heading of that level;
        Ctrl+Alt+0 makes it text again. A list item is left as it is."""
        if not self.takes_headings:
            return
        cursor = self.textCursor()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        doc = self.document()
        targets, b = [], doc.findBlock(start)
        while b.isValid() and b.position() <= end:
            if b.textList() is None:
                targets.append(b)
            b = b.next()
        if not targets:
            return
        cursor.beginEditBlock()
        for b in targets:
            bf = b.blockFormat()
            bf.setHeadingLevel(level)
            QTextCursor(b).setBlockFormat(bf)
            if not level:
                b.setUserState(-1)
            self.style_heading(b)
        cursor.endEditBlock()
        fmt = QTextCharFormat(self.currentCharFormat())
        if level:
            fmt.setFontPointSize(self._base_points() + HEADING_SIZES.get(level, 0.5))
            fmt.setFontWeight(QFont.Weight.DemiBold)
        else:
            fmt.clearProperty(QTextFormat.Property.FontPointSize)
            fmt.setFontWeight(QFont.Weight.Normal)
        self.setCurrentCharFormat(fmt)
        if self.folds_here:
            self.headings_changed()

    def heading_level(self) -> int:
        """The caret's line's heading level, 0 for text."""
        return self.textCursor().block().blockFormat().headingLevel()

    # ---- folding, in a box that folds_here ----
    def _contents_changed(self, *_args) -> None:
        if not self._quiet_fold:
            self._heading_timer.start()

    def headings_changed(self) -> None:
        """After an edit: the strip for the arrows while there's a heading, and the folds shown again. The strip is the
        box's own margin, not the text's, so it never becomes a step of Ctrl+Z."""
        has = any(b.blockFormat().headingLevel() for b in self.blocks())
        if has != self._gutter.isVisible():
            self.setViewportMargins(GUTTER if has else 0, 0, 0, 0)
            self._gutter.setVisible(has)
            self._place_gutter()
        self.refold()

    def _place_gutter(self) -> None:
        cr = self.contentsRect()
        self._gutter.setGeometry(cr.left(), cr.top(), GUTTER, cr.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self.folds_here:
            self._place_gutter()

    def heading_of(self, block):
        """The nearest heading at or above ``block``."""
        b = block
        while b.isValid() and not b.blockFormat().headingLevel():
            b = b.previous()
        return b if b.isValid() else None

    def section_end(self, heading):
        """The last line of a heading's section: up to the next heading at its level or above."""
        level, last, b = heading.blockFormat().headingLevel(), heading, heading.next()
        while b.isValid() and not (b.blockFormat().headingLevel() and b.blockFormat().headingLevel() <= level):
            last, b = b, b.next()
        return last

    def refold(self) -> None:
        """Show and hide lines from the headings' folds: a line is hidden under any folded heading above it at a higher
        level. Only the lines that change are laid out again."""
        lo = hi = hide_level = None
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
            self._quiet_fold = True
            self.document().markContentsDirty(lo, hi - lo)
            self._quiet_fold = False
        if not self.textCursor().block().isVisible():
            self._skip_hidden(-1, False)
        self.viewport().update()
        if self.folds_here:
            self._gutter.update()

    def toggle_fold(self, heading) -> None:
        heading.setUserState(-1 if heading.userState() == FOLDED else FOLDED)
        self.refold()

    def fold_here(self, fold: bool) -> None:
        """Alt+Shift+- and Alt+Shift++, as in OneNote: fold or unfold the section the caret is in."""
        h = self.heading_of(self.textCursor().block())
        if h is not None:
            h.setUserState(FOLDED if fold else -1)
            self.refold()

    def reveal(self, block) -> None:
        """Unfold every heading that hides ``block``."""
        if block.isVisible():
            return
        bound, b = 99, block.previous()
        while b.isValid() and bound > 1:
            level = b.blockFormat().headingLevel()
            if level and level < bound:
                if b.userState() == FOLDED:
                    b.setUserState(-1)
                bound = level
            b = b.previous()
        self.refold()

    def _caret_moved(self) -> None:
        """A caret put inside a folded section by a click, Find or a list's key: the section opens."""
        if not self._quiet_fold and not self.textCursor().block().isVisible():
            self.reveal(self.textCursor().block())

    def _skip_hidden(self, step: int, keep: bool) -> None:
        """After an arrow key, a caret in a folded section goes on past it, as if the section weren't there."""
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
        self._quiet_fold = True
        self.setTextCursor(c)
        self._quiet_fold = False

    def section_lines(self, heading) -> int:
        end, b, n = self.section_end(heading), heading.next(), 0
        while b.isValid() and b.position() <= end.position():
            n += 1
            b = b.next()
        return n

    def heading_row_at(self, y: int):
        """The heading whose line is at height ``y`` (the viewport's, which the strip shares), if any."""
        b = self.cursorForPosition(QPoint(4, y)).block()
        if b.isValid() and b.isVisible() and b.blockFormat().headingLevel():
            r = self.cursorRect(QTextCursor(b))
            if r.top() - 4 <= y <= r.bottom() + 4:
                return b
        return None

    def _visible_headings(self, top: int, bottom: int):
        """The headings shown between heights ``top`` and ``bottom`` of the viewport."""
        layout = self.document().documentLayout()
        b = self.cursorForPosition(QPoint(4, top)).block()
        if b.previous().isValid():
            b = b.previous()
        while b.isValid():
            if b.isVisible():
                if layout.blockBoundingRect(b).top() - self.verticalScrollBar().value() > bottom:
                    return
                if b.blockFormat().headingLevel():
                    yield b
            b = b.next()

    def _paint_pills(self, area) -> None:
        """After a folded heading's words, how many lines it holds."""
        p = None
        for b in self._visible_headings(area.top(), area.bottom()):
            if b.userState() == FOLDED:
                if p is None:
                    p = QPainter(self.viewport())
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                self._paint_pill(p, b)
        if p is not None:
            p.end()

    def _paint_arrow(self, p: QPainter, b) -> None:
        """A heading's arrow, in the strip left of the text: pointing down while open, right while folded."""
        r = self.cursorRect(QTextCursor(b))
        folded, hover = b.userState() == FOLDED, b.blockNumber() == self._hover
        cx, cy, s = GUTTER / 2, r.center().y() + 0.5, 4.0
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
        p.setBrush(QColor("#666666") if LOOK.classic else QColor(tokens.colour("text2" if folded or hover else "scroll")))
        p.drawPath(path)

    def _paint_pill(self, p: QPainter, b) -> None:
        r = self.cursorRect(QTextCursor(b))
        n = self.section_lines(b)
        text = f"{n} line{'s' if n != 1 else ''}"
        small = tokens.ui_font(tokens.CAPTION)
        fm = QFontMetrics(small)
        end = QTextCursor(b)
        end.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        x = self.cursorRect(end).right() + 10  # after the heading's words (its layout may not be laid out yet)
        pill = QRectF(x, r.center().y() - fm.height() / 2 - 1, fm.horizontalAdvance(text) + 12, fm.height() + 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tokens.colour("hover")))
        p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        p.setFont(small)
        p.setPen(QColor(tokens.colour("text2")))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)

    def checkbox_at(self, pos: QPoint):
        """The checklist line whose box is at ``pos``, in the viewport, if any."""
        b = self.cursorForPosition(pos).block()
        if b.isValid() and b.isVisible() and self.is_check(b):
            r = self.cursorRect(QTextCursor(b))
            if r.left() - 22 <= pos.x() < r.left() and r.top() <= pos.y() <= r.bottom():
                return b
        return None

    def checkbox_point(self, block) -> QPoint:
        r = self.cursorRect(QTextCursor(block))
        return QPoint(r.left() - 10, r.center().y())

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton and not self.isReadOnly():
            box = self.checkbox_at(event.position().toPoint())
            if box is not None:
                self.toggle_tick(box)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if not self.isReadOnly():
            on_box = self.checkbox_at(event.position().toPoint()) is not None
            if on_box or self.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if on_box else Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """The new look's tick box over Qt's (a box with an X): an outline, or the accent with a white tick; and in a box
        that folds, a folded heading's count of lines, with its arrow in the strip beside the text."""
        super().paintEvent(event)
        if self.folds_here:
            self._paint_pills(event.rect())
            if self._gutter.isVisible():
                self._gutter.update()
        if LOOK.classic:
            return
        area = event.rect()
        layout = self.document().documentLayout()
        p = None
        b = self.cursorForPosition(QPoint(4, area.top())).block()
        if b.previous().isValid():
            b = b.previous()
        while b.isValid():
            if b.isVisible():
                if layout.blockBoundingRect(b).top() - self.verticalScrollBar().value() > area.bottom():
                    break
                if self.is_check(b):
                    if p is None:
                        p = QPainter(self.viewport())
                        p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    self._paint_box(p, b)
            b = b.next()
        if p is not None:
            p.end()

    def _paint_box(self, p: QPainter, b) -> None:
        r = self.cursorRect(QTextCursor(b))
        # Qt's own box is covered with the page's white: the notes page's box is transparent, so its palette's would show it.
        p.fillRect(QRectF(r.left() - 22, r.top(), 21, r.height()), QColor(tokens.colour("content")))
        side = 13.0
        box = QRectF(r.left() - 7 - side, r.center().y() - side / 2 + 0.5, side, side)
        if b.blockFormat().marker() == MARKER.Checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tokens.colour("accent")))
            p.drawRoundedRect(box, 3, 3)
            tick = QPainterPath()
            tick.moveTo(box.left() + 3.2, box.center().y() + 0.2)
            tick.lineTo(box.left() + 5.6, box.bottom() - 3.4)
            tick.lineTo(box.right() - 3.0, box.top() + 3.6)
            pen = QPen(QColor(tokens.colour("on_accent")), 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(tick)
        else:
            p.setPen(QPen(QColor(tokens.colour("control")), 1))
            p.setBrush(QColor(tokens.colour("content")))
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)

    # ---- moving about (mods log round 3, M0055) ----
    def to_paragraph(self, step: int, select: bool = False) -> None:
        """Ctrl+Up and Ctrl+Down, as in Word and OneNote: to the start of this paragraph, or the one above when already
        there; or to the start of the next one (the end of the text after the last). With Shift, it selects as it goes."""
        cursor = self.textCursor()
        mode = QTextCursor.MoveMode.KeepAnchor if select else QTextCursor.MoveMode.MoveAnchor
        if step < 0:
            if cursor.positionInBlock() == 0:
                cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock, mode)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, mode)
        elif not cursor.movePosition(QTextCursor.MoveOperation.NextBlock, mode):
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, mode)
        self.setTextCursor(cursor)

    @staticmethod
    def _level(block) -> int:
        lst = block.textList()
        return lst.format().indent() if lst is not None else 0

    def _unit(self, first: int, last: int) -> tuple[int, int]:
        """Lines ``first`` to ``last``, with the list items under the last of them (a block, as DocRepo reads it), or a
        folded heading's section with it."""
        doc = self.document()
        end = doc.findBlockByNumber(last)
        if end.blockFormat().headingLevel() and end.userState() == FOLDED:
            return first, self.section_end(end).blockNumber()
        level = self._level(doc.findBlockByNumber(first))
        b = end.next()
        while b.isValid() and self._level(b) > level:
            last, b = b.blockNumber(), b.next()
        return first, last

    def move_lines(self, step: int) -> None:
        """Alt+Shift+Up and Alt+Shift+Down, as in OneNote: move the line (or the selected lines), with the list items
        under it, above the line before it or below the one after it, keeping its formatting. One Ctrl+Z puts it back."""
        doc, cursor = self.document(), self.textCursor()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        first, last_block = doc.findBlock(start).blockNumber(), doc.findBlock(end)
        last = last_block.blockNumber()
        if cursor.hasSelection() and end == last_block.position() and last > first:
            last -= 1  # a selection ending at a line's start leaves that line where it is
        first, last = self._unit(first, last)
        count = doc.blockCount()
        if step < 0:
            if first == 0:
                return
            j = first - 1
            while j > 0 and not doc.findBlockByNumber(j).isVisible():  # a folded section above goes past with its heading
                j -= 1
            while j > 0 and self._level(doc.findBlockByNumber(j)) > self._level(doc.findBlockByNumber(first)):
                j -= 1
            other = (j, first - 1)
        else:
            if last >= count - 1:
                return
            other = self._unit(last + 1, last + 1)
        text, formatted = document_markup(doc)
        lines = text.split("\n") if formatted else [doc.findBlockByNumber(n).text() for n in range(count)]
        if len(lines) != count:
            return
        if step < 0:
            order = [*range(other[0]), *range(first, last + 1), *range(other[0], other[1] + 1), *range(last + 1, count)]
        else:
            order = [*range(first), *range(other[0], other[1] + 1), *range(first, last + 1), *range(other[1] + 1, count)]
        new, new_first = [lines[n] for n in order], order.index(first)
        folded = {n for n in range(count) if doc.findBlockByNumber(n).userState() == FOLDED}
        offset, column = cursor.blockNumber() - first, cursor.positionInBlock()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        edit.select(QTextCursor.SelectionType.Document)
        edit.removeSelectedText()
        edit.setBlockFormat(QTextBlockFormat())
        edit.setCharFormat(QTextCharFormat())
        if formatted:
            edit.insertHtml(markup.to_html("\n".join(new)))
        else:
            edit.insertText("\n".join(new))
        edit.endEditBlock()
        if formatted:
            self.style_headings()
        if folded:  # each folded heading stays folded where it went
            for i, n in enumerate(order):
                doc.findBlockByNumber(i).setUserState(FOLDED if n in folded else -1)
            self.refold()
        block = doc.findBlockByNumber(min(doc.blockCount() - 1, new_first + offset))
        here = QTextCursor(block)
        here.setPosition(block.position() + min(column, block.length() - 1))
        self.setTextCursor(here)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        action = self._key_action(event)
        if action:
            action()
            self.formatting.emit()
            return
        cursor = self.textCursor()
        block = cursor.block()
        key = event.key()
        if self.folds_here and key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right) \
                and not event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._quiet_fold = True  # a folded section is passed over, not opened
            try:
                super().keyPressEvent(event)
            finally:
                self._quiet_fold = False
            self._skip_hidden(1 if key in (Qt.Key.Key_Down, Qt.Key.Key_Right) else -1,
                              bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and block.blockFormat().headingLevel() and cursor.atBlockEnd() \
                and not cursor.hasSelection():
            # Enter at a heading's end starts a line of text under it (release 5.28); a folded heading opens first.
            if block.userState() == FOLDED:
                block.setUserState(-1)
                if self.folds_here:
                    self.refold()
            cursor.beginEditBlock()
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.setCurrentCharFormat(QTextCharFormat())
            return
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and block.textList() is not None:
            self.indent_item(-1 if key == Qt.Key.Key_Backtab or event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() and block.textList() is not None and not block.text():
            self.indent_item(-1)  # Enter on an empty item: up a level, or out of the list
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.is_check(block):
            super().keyPressEvent(event)
            nb = self.textCursor().block()
            if self.is_check(nb):  # the next checklist line starts unticked
                self._set_tick(nb, False)
            return
        if key == Qt.Key.Key_Backspace and block.textList() is not None and cursor.positionInBlock() == 0 and not cursor.hasSelection():
            self._unlist(cursor)
            return
        if key == Qt.Key.Key_Space and block.textList() is None and not event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier:
            before = block.text()[: cursor.positionInBlock()]
            if before in ("[]", "[ ]") and self._checkable(block):  # "[] " or "[ ] " at a line's start starts a checklist
                c = QTextCursor(block)
                c.beginEditBlock()
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(before))
                c.removeSelectedText()
                self._make_check(block)
                c.endEditBlock()
                self.formatting.emit()
                return
            if before in ("-", "*") or re.fullmatch(r"\d+\.", before):  # "- " or "1. " starting a line starts a list
                c = QTextCursor(block)
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(before))
                c.removeSelectedText()
                self.toggle_list(before not in ("-", "*"))
                return
        super().keyPressEvent(event)

    # ---- pasting ----
    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt's name
        """Pasted text keeps bold, italic, underline, strikethrough, highlights and lists, and nothing else (no fonts,
        sizes or colours). Word's and Outlook's lists, which aren't real lists in their HTML, come through as release
        5.1 reads them (``paste.html_to_text``)."""
        from docrepo import diagnose, paste

        if source.hasImage() and not source.text().strip():  # a picture alone: kept as a file, never inside the text
            if self.takes_pictures:
                self.image_pasted.emit(source.imageData())
            return
        if source.hasHtml():
            raw = source.html()
            if paste.has_mso_list(raw):
                text = markup.from_list_lines(paste.html_to_text(raw))
                diagnose.note_drag("paste", list(source.formats()), 0, 0, "a Word or Outlook list, from its HTML")
            else:
                doc = QTextDocument()
                doc.setHtml(raw)
                text, _ = document_markup(doc, headings=False)  # a pasted heading comes in as bold text, as before
                diagnose.note_drag("paste", list(source.formats()), 0, 0, "formatted text, from its HTML")
            self.insert_markup(text.strip("\n"))
        elif source.hasText():
            diagnose.note_drag("paste", list(source.formats()), 0, 0, "text")
            self.insertPlainText(paste.bullets_to_dashes(source.text()))
        else:
            super().insertFromMimeData(source)

    def insert_markup(self, text: str) -> None:
        """Put markup in at the cursor: one plain line goes into the line, anything more as its own lines."""
        cursor = self.textCursor()
        if "\n" not in text and not markup.LIST_LINE.match(text):
            cursor.insertHtml(f'<span style="white-space:pre-wrap">{markup.inline_html(text)}</span>')
        else:
            cursor.insertHtml(markup.to_html(text))
        self.setTextCursor(cursor)



class FormatBar(QWidget):
    """The buttons above a RichEdit, each with its key in its tooltip."""

    def __init__(self, edit: RichEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("formatBar")
        self.edit = edit
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for key, text, tip, action, checkable in (
                ("b", "B", "Bold (Ctrl+B)", edit.toggle_bold, True), ("i", "I", "Italic (Ctrl+I)", edit.toggle_italic, True),
                ("u", "U", "Underline (Ctrl+U)", edit.toggle_underline, True), ("s", "S", "Strikethrough (Ctrl+-)", edit.toggle_strike, True),
                ("mark", "Highlight", "Highlight (Ctrl+Alt+H): yellow, or the arrow for green and pink", edit.toggle_highlight, True),
                ("ul", "• List", "Bulleted list (Ctrl+.), or type “- ”. Tab and Shift+Tab change the level; Alt+Shift+Up and "
                                 "Alt+Shift+Down move a line.", lambda: edit.toggle_list(False), True),
                ("ol", "1. List", "Numbered list (Ctrl+/), or type “1. ”", lambda: edit.toggle_list(True), True),
                ("check", "☐ Checklist", "Checklist (Ctrl+1), or type “[] ” at a line's start; a click on a box ticks it",
                 edit.toggle_checklist, True)):
            b = QToolButton(text=text)
            if not LOOK.classic and key in ICONS:  # the new look: icons for the highlight and the lists, their names in the tooltip
                b.setText("")
                b.setIcon(icon(ICONS[key]))
                b.setAccessibleName(tip.split(" (")[0])
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the cursor stays in the text
            b.clicked.connect(lambda _=False, a=action: (a(), self.sync()))
            f = b.font()
            if key == "b":
                f.setBold(True)
            elif key == "i":
                f.setItalic(True)
            elif key == "u":
                f.setUnderline(True)
            elif key == "s":
                f.setStrikeOut(True)
            b.setFont(f)
            lay.addWidget(b)
            self.buttons[key] = b
        menu = QMenu(self)
        for name in markup.HIGHLIGHTS:
            menu.addAction(name.capitalize(), lambda n=name: (edit.set_highlight(n), self.sync()))
        menu.addAction("No highlight", lambda: (edit.set_highlight(None), self.sync()))
        self.buttons["mark"].setMenu(menu)
        self.buttons["mark"].setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        if edit.takes_headings:  # headings (release 5.28): a menu of the three levels and Text
            b = QToolButton(text="H")
            f = b.font()
            f.setBold(True)
            b.setFont(f)
            b.setToolTip("Heading (Ctrl+Alt+1, 2 or 3; Ctrl+Alt+0 for text). A heading folds what's under it.")
            b.setAccessibleName("Heading")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            heading_menu = QMenu(self)
            for level, name in ((1, "Heading 1"), (2, "Heading 2"), (3, "Heading 3"), (0, "Text")):
                heading_menu.addAction(f"{name}\tCtrl+Alt+{level}", lambda n=level: (edit.set_heading(n), self.sync()))
            b.setMenu(heading_menu)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            lay.insertWidget(0, b)
            self.buttons["heading"] = b
        lay.addStretch()
        edit.formatting.connect(self.sync)
        self.sync()

    def show_on_use(self, frame: QWidget) -> None:
        """The new look (mods log round 3, M0055): the buttons show only while the box has the cursor or the mouse is over
        ``frame``, the box's outline. The bar keeps its room, so the text never moves."""
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self._frame = frame
        self._shown_timer = QTimer(self)
        self._shown_timer.setSingleShot(True)
        self._shown_timer.setInterval(0)
        self._shown_timer.timeout.connect(self._sync_shown)
        frame.installEventFilter(self)
        self.edit.installEventFilter(self)
        self._sync_shown()

    def _sync_shown(self) -> None:
        menu_open = any(b.menu() is not None and b.menu().isVisible() for b in self.buttons.values())
        self.setVisible(self.edit.hasFocus() or self._frame.underMouse() or menu_open)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.Enter, QEvent.Type.Leave):
            self._shown_timer.start()
        return False

    def sync(self) -> None:
        """Show which formatting the cursor is in."""
        e = self.edit
        lst = e.textCursor().currentList()
        states = {"b": e.fontWeight() >= QFont.Weight.DemiBold.value, "i": e.fontItalic(), "u": e.fontUnderline(),
                  "s": e.currentCharFormat().fontStrikeOut(), "mark": e.current_highlight() is not None,
                  "ul": lst is not None and lst.format().style() not in NUMBERED and not e.is_check(e.textCursor().block()),
                  "ol": lst is not None and lst.format().style() in NUMBERED, "check": e.is_check(e.textCursor().block())}
        if "heading" in self.buttons:
            level = e.textCursor().block().blockFormat().headingLevel()
            states["heading"] = bool(level)
            states["b"] = states["b"] and not level  # a heading's own weight isn't bold
        for key, on in states.items():
            self.buttons[key].setChecked(bool(on))
