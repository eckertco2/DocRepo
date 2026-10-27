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
"""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextListFormat)
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
KEYS = {"b": "Ctrl+B", "i": "Ctrl+I", "u": "Ctrl+U", "s": "Ctrl+-", "mark": "Ctrl+Alt+H", "ul": "Ctrl+.", "ol": "Ctrl+/", "check": "Ctrl+1"}

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


def block_markup(block) -> tuple[str, bool]:
    """One block (a line) as markup, and whether it's formatted: a list item, or any mark."""
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


def document_markup(doc: QTextDocument) -> tuple[str, bool]:
    """The document as markup, and whether anything in it is formatted."""
    lines: list[str] = []
    formatted = False
    block = doc.begin()
    while block.isValid():
        line, marked = block_markup(block)
        lines.append(line)
        formatted = formatted or marked
        block = block.next()
    return "\n".join(lines), formatted


class RichEdit(QTextEdit):
    """The formatted content text box. ``formatting`` is sent when the cursor's formatting changes, for the toolbar."""

    formatting = Signal()

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

    def setDocument(self, document: QTextDocument) -> None:  # noqa: N802 - Qt's name
        super().setDocument(document)
        document.setIndentWidth(INDENT)

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

    def _unlist(self, cursor: QTextCursor) -> None:
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        block = self.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            lst = block.textList()
            if lst is not None:
                lst.remove(block)
                c = QTextCursor(block)
                bf = c.blockFormat()
                bf.setIndent(0)
                c.setBlockFormat(bf)
            if block.blockFormat().marker() != MARKER.NoMarker:
                self._set_tick(block, None)
            block = block.next()

    def indent_item(self, delta: int) -> bool:
        """Tab or Shift+Tab in a list item: a level in or out. Out of the first level ends the list there."""
        cursor = self.textCursor()
        block = cursor.block()
        lst = block.textList()
        if lst is None:
            return False
        fmt = QTextListFormat(lst.format())
        level = fmt.indent() + delta
        if level < 1:
            self._unlist(cursor)
            return True
        # Rejoin a list at that level just above, so numbering carries on; else start one.
        prev = block.previous()
        while prev.isValid() and prev.textList() is not None and prev.textList().format().indent() > level:
            prev = prev.previous()
        target = prev.textList() if prev.isValid() else None
        lst.remove(block)
        if target is not None and target.format().indent() == level:
            target.add(block)
        else:
            fmt.setIndent(level)
            QTextCursor(block).createList(fmt)
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
                t.textList().remove(t)
                bf = t.blockFormat()
                bf.setIndent(0)
                QTextCursor(t).setBlockFormat(bf)
        else:
            for t in targets:
                if not self.is_check(t):
                    self._make_check(t)
        c.endEditBlock()
        self.formatting.emit()

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
        """The new look's tick box over Qt's (a box with an X): an outline, or the accent with a white tick."""
        super().paintEvent(event)
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
        """Lines ``first`` to ``last``, with the list items under the last of them (a block, as DocRepo reads it)."""
        doc = self.document()
        level = self._level(doc.findBlockByNumber(first))
        b = doc.findBlockByNumber(last).next()
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
        unit, moved = lines[first:last + 1], lines[other[0]:other[1] + 1]
        if step < 0:
            new, new_first = lines[:other[0]] + unit + moved + lines[last + 1:], other[0]
        else:
            new, new_first = lines[:first] + moved + unit + lines[other[1] + 1:], first + len(moved)
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

        if source.hasHtml():
            raw = source.html()
            if paste.has_mso_list(raw):
                text = markup.from_list_lines(paste.html_to_text(raw))
                diagnose.note_drag("paste", list(source.formats()), 0, 0, "a Word or Outlook list, from its HTML")
            else:
                doc = QTextDocument()
                doc.setHtml(raw)
                text, _ = document_markup(doc)
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
        for key, on in states.items():
            self.buttons[key].setChecked(bool(on))
