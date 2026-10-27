"""The Checklist summary (release 5.26; the notes page plan's decisions 121 to 123, and 88 as redone).

Every checklist line on a task's notes page, shown again at the top of its notes, under Description and Current status,
and in Edit task. It isn't a copy: each row is bound to its line on the page (a ``QTextBlock`` of the ``NotesEdit``), so
ticking, rewording (keeping bold and the like) or removing it in either place changes the one line at once, as a step of
the page's undo, and the page saves as it does when typed in.

- Rows are in page order, under the heading each line sits under, with the count ("3 of 8 done").
- Done lines hide behind "Show 9 done" (decision 122); on the page they stay where they are, grey (91).
- **Add item** puts a new line at the end of the page, under today's heading when the task uses day headings (123).
- **Go to** on a row shows its line on the page; **Remove** takes it off the page.
- The summary folds to its heading, and whether it's folded is kept for each task (``folded``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.notes_edit import NotesEdit
from docrepo.ui.rich_edit import MARKER, RichEdit


class LineEdit(RichEdit):
    """A row's words: a one-line box with the capture window's formatting keys. Enter finishes; it never adds a line."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("checkText")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(lambda _: self._fit())
        del self._keys["Ctrl+1"]  # a row is a checklist line already
        for k in ("Ctrl+.", "Ctrl+/", "Ctrl+Shift+L", "Ctrl+Shift+O"):
            self._keys.pop(k, None)

    def _fit(self) -> None:
        h = int(self.document().size().height()) + (self.height() - self.viewport().height())
        if h != self.height():
            self.setFixedHeight(max(h, 20))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clearFocus()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt's name
        self.insertPlainText(" ".join(source.text().split()))  # one line


class Row(QWidget):
    """One checklist line: its box, its words, and Go to and Remove on hover."""

    def __init__(self, summary: ChecklistSummary, block) -> None:
        super().__init__()
        self.setObjectName("checkRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.summary, self.block = summary, block
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4 + 16 * max(0, block.textList().format().indent() - 1), 0, 2, 0)
        lay.setSpacing(4)
        self.box = QCheckBox()
        self.box.setToolTip("Tick it here or on the page")
        self.box.toggled.connect(self._ticked)
        self.text = LineEdit()
        self.text.textChanged.connect(self._typed)
        self._loading = False
        self.go = QToolButton(objectName="rowAction")
        self.go.setIcon(icon("open"))
        self.go.setToolTip("Go to it on the page")
        self.go.clicked.connect(lambda: summary.notes.go_to_block(self.block))
        self.remove = QToolButton(objectName="rowAction")
        self.remove.setIcon(icon("close"))
        self.remove.setToolTip("Remove it from the page (Ctrl+Z on the page puts it back)")
        self.remove.clicked.connect(lambda: summary.remove(self))
        for b in (self.go, self.remove):
            b.setAutoRaise(True)
            policy = b.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            b.setSizePolicy(policy)
            b.hide()
        lay.addWidget(self.box, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.go, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.remove, 0, Qt.AlignmentFlag.AlignTop)
        self.load()

    def load(self) -> None:
        """The row from its line on the page, unless it's being typed in."""
        if self.text.hasFocus():
            return
        self._loading = True
        done = self.block.blockFormat().marker() == MARKER.Checked
        self.box.blockSignals(True)
        self.box.setChecked(done)
        self.box.blockSignals(False)
        doc = self.text.document()
        if _words(doc.begin()) != _words(self.block):
            doc.clear()
            c = QTextCursor(doc)
            it = self.block.begin()
            while not it.atEnd():
                c.insertText(it.fragment().text(), QTextCharFormat(it.fragment().charFormat()))
                it += 1
        self._loading = False

    def _typed(self) -> None:
        if not self._loading and self.block.isValid():
            self.summary._writing = True
            self.summary.notes.set_line_from(self.block, self.text.document().begin())
            self.summary._writing = False

    def _ticked(self, on: bool) -> None:
        if self.block.isValid() and (self.block.blockFormat().marker() == MARKER.Checked) != on:
            self.summary.notes.toggle_tick(self.block)
            self.load()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.go.show()
        self.remove.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.go.hide()
        self.remove.hide()
        super().leaveEvent(event)


def _words(block) -> list[tuple[str, int, bool, bool, bool, bool]]:
    """A line's words with their marks, to tell whether a row needs loading again (its grey aside)."""
    out, it = [], block.begin()
    while not it.atEnd():
        f = it.fragment().charFormat()
        out.append((it.fragment().text(), f.fontWeight(), f.fontItalic(), f.fontUnderline(), f.fontStrikeOut(),
                    f.background().style() != Qt.BrushStyle.NoBrush))
        it += 1
    return out


class ChecklistSummary(QWidget):
    """The page's checklist lines, bound to them. ``folded`` says the summary folded or opened (by its arrow)."""

    folded = Signal(bool)

    def __init__(self, notes: NotesEdit, foldable: bool = True) -> None:
        super().__init__()
        self.setObjectName("checklistSummary")
        self.notes = notes
        self.show_done = False
        self.is_folded = False
        self._writing = False
        self._rows: list[Row] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.arrow = QToolButton(objectName="checkFold")
        self.arrow.setAutoRaise(True)
        self.arrow.clicked.connect(lambda: self.set_folded(not self.is_folded, emit=True))
        self.arrow.setVisible(foldable)
        self.title = QLabel("Checklist", font=tokens.ui_font(tokens.BODY, semibold=True))
        self.title.setVisible(foldable)  # in Edit task, its section's heading says it
        self.count = QLabel(objectName="checkCount")
        self.done_button = QPushButton(objectName="link")
        self.done_button.setFlat(True)
        self.done_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_button.clicked.connect(self.toggle_done)
        head.addWidget(self.arrow)
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch()
        head.addWidget(self.done_button)
        lay.addLayout(head)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        lay.addWidget(self.body)
        self.add = QLineEdit(objectName="addItem")
        self.add.setPlaceholderText("Add item: a checklist line at the end of the page")
        self.add.returnPressed.connect(self.add_item)
        lay.addWidget(self.add)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.refresh)
        notes.document().contentsChange.connect(self._page_changed)
        self.set_folded(False)

    def _page_changed(self, *_args) -> None:
        if not self._writing:
            self._timer.start()

    def set_folded(self, folded: bool, emit: bool = False) -> None:
        self.is_folded = folded
        self.arrow.setText("▸" if folded else "▾")
        self.arrow.setToolTip("Show the checklist" if folded else "Fold the checklist")
        self.body.setVisible(not folded)
        self.add.setVisible(not folded)
        self.refresh()
        if emit:
            self.folded.emit(folded)

    def toggle_done(self) -> None:
        self.show_done = not self.show_done
        self.refresh()

    def refresh(self) -> None:
        """The rows from the page: each row loaded again, and rebuilt when lines come or go (not while one's typed in)."""
        items = self.notes.checklist_blocks()
        done = sum(1 for b, _ in items if b.blockFormat().marker() == MARKER.Checked)
        total = len(items)
        self.count.setText(f"{done} of {total} done" if total else "None yet: Ctrl+1 on the page, or Add item")
        self.done_button.setText(("Hide done" if self.show_done else f"Show {done} done") if done else "")
        self.done_button.setVisible(bool(done) and not self.is_folded)
        shown = [(b, h) for b, h in items if self.show_done or b.blockFormat().marker() != MARKER.Checked]
        same = [r.block for r in self._rows] == [b for b, _ in shown]
        if same:
            for r in self._rows:
                r.load()
            return
        if any(r.text.hasFocus() for r in self._rows):
            self._timer.start()  # after the typing
            return
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        heading = None
        for b, h in shown:
            if h != heading:
                heading = h
                if h:
                    label = QLabel(h, objectName="checkHeading")
                    label.setFont(tokens.ui_font(tokens.CAPTION))
                    self.rows.addWidget(label)
            row = Row(self, b)
            self._rows.append(row)
            self.rows.addWidget(row)

    def add_item(self) -> None:
        text = self.add.text().strip()
        if not text:
            return
        self.notes.add_check_item(text)
        self.add.clear()
        self.refresh()

    def remove(self, row: Row) -> None:
        if row.block.isValid():
            self.notes.remove_line(row.block)
        self.refresh()

    def row_for(self, block) -> Row | None:
        return next((r for r in self._rows if r.block == block), None)
