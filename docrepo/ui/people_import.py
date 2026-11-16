"""Import people… (release 5.151, the design workspace's ``docs/mods/people-import-plan.md``, decisions 658 to 662): the
People view's button and the command palette's line open this window.

Choose a ``.csv`` or an ``.xlsx`` (and an ``.xlsx``'s sheet, when it has several): the window says which columns it reads
and which it leaves alone, then lists each row as New, Update (with what changes), Same or a Problem, each New and Update
ticked. Import adds and updates the ticked ones in one transaction, and the status line counts them. The file is only
read; ``docrepo/people_import.py`` does the work.

A module of its own (release 5.95, the review's F11): the window, and a function of the browse window that opens it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import edits
from docrepo import people_import as pi
from docrepo.excel_import import WorkbookError
from docrepo.model import Model
from docrepo.people import PeopleError
from docrepo.ui.context import AppContext
from docrepo.ui.look import Help
from docrepo.ui.tokens import C

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: What the command is called, on the People view and in the command palette.
NAME = "Import people…"
#: Each kind's colour in the list: words in a colour that reads on white, never colour alone (the kind is its word).
KIND_COLOURS = {pi.NEW: "success", pi.UPDATE: "accent", pi.SAME: "text2", pi.PROBLEM: "critical"}
#: The list's columns: the tick, the kind, the file's row, the name, and what the line does.
TICK, KIND, ROW, NAME_COLUMN, WHAT = range(5)


class _Wrapped(QStyledItemDelegate):
    """The What changes column's height: its text wrapped to the column's width, so a long update reads whole. A tree view
    wraps the words it paints, but sizes each row for one line."""

    def __init__(self, view: QTreeWidget) -> None:
        super().__init__(view)
        self.view = view

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        width = self.view.header().sectionSize(WHAT) - 12  # less the text's margins
        if index.column() != WHAT or width <= 0:
            return size
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fm = opt.fontMetrics
        text = fm.boundingRect(QRect(0, 0, width, 100_000), int(Qt.TextFlag.TextWordWrap), opt.text)
        return QSize(size.width(), max(size.height(), text.height() + size.height() - fm.height()))


class PeopleImportDialog(QDialog):
    """The import window. After Import, ``outcome`` is the status line's words."""

    def __init__(self, parent: QWidget | None, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Import people")
        self.setStyleSheet(f"QDialog {{ background: {C.content}; }} QLabel#error {{ background: {C.critical_bg}; color: {C.critical}; "
                           f"padding: 6px 10px; }} QLabel#caution {{ color: {C.caution}; }} QLabel#sub {{ color: {C.text2}; }}")
        self.resize(860, 600)
        self.path: Path | None = None
        self.found: pi.Preview | None = None
        self.outcome = ""
        self._filling = False
        self._build()

    # ---- building ----
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.addWidget(Help("A list of people from a .csv or an .xlsx file whose first row names its columns: Name, and Email, Role, "
                           "Group and Aliases (split by semicolons) when it has them. Someone already here is found by email, then by "
                           "name. The file is only read, and nothing changes until Import: nobody is removed or retired, and no field "
                           "is cleared."))
        self._build_file(lay)
        self.columns = QLabel(objectName="sub")
        self.columns.setWordWrap(True)
        self.columns.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.columns)
        self.cut = QLabel(f"Only the first {pi.MAX_ROWS:,} rows under the header are read.", objectName="caution")
        self.cut.hide()
        lay.addWidget(self.cut)
        self._build_lines(lay)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        lay.addWidget(self.error)
        self._build_buttons(lay)

    def _build_file(self, lay: QVBoxLayout) -> None:
        grid = QGridLayout()
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.file.setPlaceholderText("No file chosen")
        self.file.setAccessibleName("The file")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        self.sheet = QComboBox()
        self.sheet.setAccessibleName("Sheet")
        self.sheet.currentIndexChanged.connect(lambda _: self._read())
        self.sheet_label = QLabel("Sheet")
        grid.addWidget(QLabel("File"), 0, 0)
        grid.addWidget(self.file, 0, 1)
        grid.addWidget(choose, 0, 2)
        grid.addWidget(self.sheet_label, 1, 0)
        grid.addWidget(self.sheet, 1, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self._show_sheet(False)

    def _build_lines(self, lay: QVBoxLayout) -> None:
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.summary)
        self.lines = QTreeWidget()
        self.lines.setAccessibleName("The file's rows")
        self.lines.setRootIsDecorated(False)
        # A long change wraps rather than being cut off; the tick has a column of its own, so the kinds line up.
        self.lines.setWordWrap(True)
        self.lines.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lines.setHeaderLabels(["", "", "Row", "Name", "What changes"])
        self.lines.setItemDelegate(_Wrapped(self.lines))
        h = self.lines.header()
        h.setStretchLastSection(True)
        for i in (TICK, KIND, ROW, NAME_COLUMN):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.sectionResized.connect(lambda *_: self.lines.scheduleDelayedItemsLayout())  # rows sized again to the column's width
        self.lines.itemChanged.connect(lambda item, column: self._ticked(item) if column == TICK else None)
        lay.addWidget(self.lines, 1)

    def _build_buttons(self, lay: QVBoxLayout) -> None:
        buttons = QHBoxLayout()
        self.ticked_words = QLabel(objectName="sub")
        buttons.addWidget(self.ticked_words)
        buttons.addStretch()
        self.import_button = QPushButton("Import", objectName="primary")
        self.import_button.setDefault(True)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_now)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        lay.addLayout(buttons)

    def _show_sheet(self, on: bool) -> None:
        self.sheet.setVisible(on)
        self.sheet_label.setVisible(on)

    def _say(self, problem: str) -> None:
        self.error.setText(problem)
        self.error.setVisible(bool(problem))

    # ---- choosing and reading ----
    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the list of people", "", pi.FILE_FILTER)
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        """Read a file into the window (Choose…, and tests)."""
        self.path = path
        self.file.setText(str(path))
        self._filling = True
        self.sheet.clear()
        try:
            names = pi.sheets(path)
        except WorkbookError as e:
            self._filling = False
            self._fail(str(e))
            return
        self.sheet.addItems(names)
        self._show_sheet(len(names) > 1)  # one sheet: nothing to pick
        self._filling = False
        self._read()

    def _fail(self, problem: str) -> None:
        self.found = None
        self.lines.clear()
        self.columns.clear()
        self.summary.clear()
        self.ticked_words.clear()
        self.cut.hide()
        self.import_button.setEnabled(False)
        self._say(problem)

    def _read(self) -> None:
        if self._filling or self.path is None:
            return
        try:
            table = pi.read_file(self.path, self.sheet.currentText() or None)
            if not table.rows:
                raise WorkbookError(f"{self.path.name} has nothing in it.")
            self.found = pi.preview(Model(self.ctx.conn), table)
        except WorkbookError as e:
            self._fail(str(e))
            return
        self._say("")
        self._show()

    # ---- the lines ----
    def _show(self) -> None:
        p = self.found
        if p is None:
            return
        self.columns.setText(p.columns_words())
        self.cut.setVisible(p.cut)
        self.summary.setText(p.summary() if p.lines else "No rows under the header.")
        self._filling = True
        self.lines.clear()
        for line in p.lines:
            item = QTreeWidgetItem(["", line.kind_word(), str(line.row), line.name or "(no name)", line.words()])
            item.setData(TICK, Qt.ItemDataRole.UserRole, line.row)
            item.setForeground(KIND, QBrush(QColor(getattr(C, KIND_COLOURS[line.kind]))))
            item.setTextAlignment(ROW, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if line.kind in (pi.SAME, pi.PROBLEM):
                item.setForeground(WHAT, QBrush(QColor(C.critical if line.kind == pi.PROBLEM else C.text2)))
            item.setToolTip(WHAT, line.words())
            if line.can_tick:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(TICK, Qt.CheckState.Checked if line.ticked else Qt.CheckState.Unchecked)
            else:  # Same and Problem lines have no tick box (a tree's item can be ticked by default)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.lines.addTopLevelItem(item)
        self._filling = False
        self._count()

    def _ticked(self, item: QTreeWidgetItem) -> None:
        if self._filling or self.found is None:
            return
        line = self.line_of(item)
        if line is not None and line.can_tick:
            line.ticked = item.checkState(TICK) == Qt.CheckState.Checked
        self._count()

    def _count(self) -> None:
        n = len(self.found.ticked) if self.found else 0
        self.ticked_words.setText(f"{n} ticked to add or update" if self.found and self.found.lines else "")
        self.import_button.setEnabled(n > 0)

    def line_of(self, item: QTreeWidgetItem) -> pi.Line | None:
        row = item.data(TICK, Qt.ItemDataRole.UserRole)
        return next((x for x in self.found.lines if x.row == row), None) if self.found else None

    def item_of(self, row: int) -> QTreeWidgetItem | None:
        """The list's line for the file's row ``row`` (tests)."""
        for i in range(self.lines.topLevelItemCount()):
            item = self.lines.topLevelItem(i)
            if item.data(TICK, Qt.ItemDataRole.UserRole) == row:
                return item
        return None

    def set_ticked(self, row: int, on: bool) -> None:
        """Tick or untick the line for row ``row``, as a click does."""
        item = self.item_of(row)
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(TICK, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    # ---- importing ----
    def import_now(self) -> None:
        """Import the ticked lines, keep the outcome and close. A change refused says why and leaves the window open."""
        if not self.found or not self.found.ticked:
            return
        try:
            self.outcome = pi.run_import(self.ctx.conn, self.found, self.ctx.now())
        except (PeopleError, sqlite3.Error) as e:
            self._say(f"Nothing was imported: {e}")
            return
        self.accept()


def run(browse: BrowseWindow) -> None:
    """Import people… from the People view or the palette: the window, then the pages and the People view, with the
    status line's counts ("12 people added, 3 updated, 2 left out.")."""
    dialog = PeopleImportDialog(browse, browse.ctx)
    if not (browse.run_dialog(dialog) and dialog.outcome):
        return
    out = edits.Outcome(dialog.outcome)
    edits.write_all_pages(browse.conn, browse.ctx.data_root, browse.ctx.fs, browse.ctx.now(), out.problems)
    browse.refresh(render=False)
    if browse.view != "people":
        browse.set_view("people")
    else:
        browse.render_all()
    browse.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))

