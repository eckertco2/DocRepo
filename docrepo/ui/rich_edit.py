"""The formatted content text box (mods log round 2, M0045, release 5.7).

``RichEdit`` is a QTextEdit with bold, italic, underline, strikethrough, three highlight colours, and bulleted and
numbered lists with levels. ``value()`` gives what to save: the markup (``docrepo.markup``) when anything is formatted,
else the plain text, as before. ``document_markup`` reads any QTextDocument the same way, so pasted HTML keeps only
what DocRepo can keep.

Keys, while typing in it: Ctrl+B, Ctrl+I, Ctrl+U, Ctrl+Shift+X (strikethrough), Ctrl+Shift+H (highlight), Ctrl+Shift+L
(bullets), Ctrl+Shift+O (numbers); Tab and Shift+Tab move a list item in and out; "- " or "1. " at the start of a line
starts a list; Enter on an empty list item, or Backspace at its start, ends it.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor, QTextDocument, QTextListFormat
from PySide6.QtWidgets import QHBoxLayout, QMenu, QTextEdit, QToolButton, QWidget

from docrepo import markup

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


def document_markup(doc: QTextDocument) -> tuple[str, bool]:
    """The document as markup, and whether anything in it is formatted."""
    lines: list[str] = []
    formatted = False
    block = doc.begin()
    while block.isValid():
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
        formatted = formatted or any(marks for _, marks, _ in segments)
        line = markup.marks_text([(markup.escape_inline(text), marks, colour) for text, marks, colour in segments])
        lst = block.textList()
        if lst is not None:
            formatted = True
            fmt = lst.format()
            number = f"{lst.itemNumber(block) + 1}. " if fmt.style() in NUMBERED else "- "
            lines.append("  " * max(0, fmt.indent() - 1) + number + line)
        else:
            lines.append(markup.escape_line_start(line))
        block = block.next()
    return "\n".join(lines), formatted


class RichEdit(QTextEdit):
    """The formatted content text box. ``formatting`` is sent when the cursor's formatting changes, for the toolbar."""

    formatting = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setTabChangesFocus(False)
        self.currentCharFormatChanged.connect(lambda _: self.formatting.emit())
        self.cursorPositionChanged.connect(self.formatting.emit)
        # Handled as keys, not shortcuts, so they win over a window's own (the browse tool's Ctrl+B hides its views).
        self._keys: dict[str, Callable[[], None]] = {
            "Ctrl+B": self.toggle_bold, "Ctrl+I": self.toggle_italic, "Ctrl+U": self.toggle_underline, "Ctrl+Shift+X": self.toggle_strike,
            "Ctrl+Shift+H": self.toggle_highlight, "Ctrl+Shift+L": lambda: self.toggle_list(False), "Ctrl+Shift+O": lambda: self.toggle_list(True)}

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
        if key == Qt.Key.Key_Backspace and block.textList() is not None and cursor.positionInBlock() == 0 and not cursor.hasSelection():
            self._unlist(cursor)
            return
        if key == Qt.Key.Key_Space and block.textList() is None and not event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier:
            before = block.text()[: cursor.positionInBlock()]
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
                ("b", "B", "Bold   Ctrl+B", edit.toggle_bold, True), ("i", "I", "Italic   Ctrl+I", edit.toggle_italic, True),
                ("u", "U", "Underline   Ctrl+U", edit.toggle_underline, True), ("s", "S", "Strikethrough   Ctrl+Shift+X", edit.toggle_strike, True),
                ("mark", "Highlight", "Highlight   Ctrl+Shift+H (yellow; the arrow for others)", edit.toggle_highlight, True),
                ("ul", "• List", "Bulleted list   Ctrl+Shift+L, or type “- ”. Tab and Shift+Tab change the level.", lambda: edit.toggle_list(False), True),
                ("ol", "1. List", "Numbered list   Ctrl+Shift+O, or type “1. ”", lambda: edit.toggle_list(True), True)):
            b = QToolButton(text=text)
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

    def sync(self) -> None:
        """Show which formatting the cursor is in."""
        e = self.edit
        lst = e.textCursor().currentList()
        states = {"b": e.fontWeight() >= QFont.Weight.DemiBold.value, "i": e.fontItalic(), "u": e.fontUnderline(),
                  "s": e.currentCharFormat().fontStrikeOut(), "mark": e.current_highlight() is not None,
                  "ul": lst is not None and lst.format().style() not in NUMBERED, "ol": lst is not None and lst.format().style() in NUMBERED}
        for key, on in states.items():
            self.buttons[key].setChecked(bool(on))
