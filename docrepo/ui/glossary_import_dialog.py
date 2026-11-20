"""The browse tool's form for importing a glossary from Excel or CSV, or importing one again (release 5.171; the design
workspace's ``docs/mods/glossaries-plan.md``, decisions 804 and 805).

Pick the file (and an .xlsx's sheet) and the header row (guessed); every column is kept, named as its header. Give it a
name (the file's, to start) and, optionally, the column that holds tags (guessed). With a tag column, **Add these to the
tag list too** runs the tag list's own import on it and the column chosen as each tag's description. The preview says
what would be kept, and for Import again what's added, gone and changed. Nothing is written until Import, and the file is
only read. ``docrepo/glossary_import.py`` and ``docrepo/glossaries.py`` do the work.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from docrepo import glossaries
from docrepo import glossary_import as gi
from docrepo import tagged_import as ti
from docrepo.excel_import import WorkbookError
from docrepo.markup import esc
from docrepo.ui.context import AppContext
from docrepo.ui.look import Help
from docrepo.ui.style import page_css
from docrepo.ui.tokens import C


class GlossaryImportDialog(QDialog):
    """The import form; with ``against``, Import again for that glossary. After Import, ``outcome`` says what was done,
    ``glossary_id`` is the glossary's, and ``tags_changed`` says whether the tag list was imported too."""

    def __init__(self, parent: QWidget | None, ctx: AppContext, against: glossaries.Glossary | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.against = against
        self.setWindowTitle(f"Import {against.name} again" if against else "Import a glossary")
        self.setStyleSheet(f"QDialog {{ background: {C.content}; }} QLabel#error {{ background: {C.critical_bg}; color: {C.critical}; padding: 6px 10px; }}")
        self.resize(860, 700)
        self.path: Path | None = None
        self.rows: list[list[str]] = []
        self.found: gi.Preview | None = None
        self.tags_found: ti.Preview | None = None
        self.outcome = ""
        self.glossary_id: int | None = against.id if against else None
        self.tags_changed = False
        self._filling = False
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.addWidget(Help("A table from an .xlsx or a .csv, kept whole: every column, named as its header, each row as the sheet "
                           "has it, up to 100,000 rows. The file is only read. "
                           + ("Importing again replaces this glossary's rows with the file's." if self.against else
                              "A tag column is optional: it ties the glossary to the tag list.")))
        grid = QGridLayout()
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.file.setPlaceholderText("No file chosen")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        self.sheet = QComboBox()
        self.sheet.currentIndexChanged.connect(lambda _: self._read())
        self.sheet_label = QLabel("Sheet")
        self.header = QSpinBox()
        self.header.setRange(1, 30)
        self.header.valueChanged.connect(lambda _: self._columns_changed())
        self.name = QLineEdit(self.against.name if self.against else "")
        self.name.setPlaceholderText("Such as Equipment")
        self.name.setMaxLength(glossaries.NAME_MAX)
        self.name.setReadOnly(self.against is not None)
        self.name.textChanged.connect(lambda _: self._refresh())
        self.tag = QComboBox()
        self.tag.currentIndexChanged.connect(lambda _: self._tag_changed())
        grid.addWidget(QLabel("File"), 0, 0)
        grid.addWidget(self.file, 0, 1, 1, 3)
        grid.addWidget(choose, 0, 4)
        grid.addWidget(self.sheet_label, 1, 0)
        grid.addWidget(self.sheet, 1, 1)
        grid.addWidget(QLabel("Headers in row"), 1, 2)
        grid.addWidget(self.header, 1, 3)
        grid.addWidget(QLabel("Name"), 2, 0)
        grid.addWidget(self.name, 2, 1)
        grid.addWidget(QLabel("Tag column"), 2, 2)
        grid.addWidget(self.tag, 2, 3)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addWidget(QLabel("<b>Columns</b> <span style='font-weight:400'>· every one is kept</span>"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Column", "First rows"])
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 2)
        tags = QHBoxLayout()
        self.to_tags = QCheckBox("Add these to the tag list too")
        self.to_tags.setToolTip("Run the tag list's own import on the tag column and a description column, so the tags are found in every text")
        self.to_tags.toggled.connect(lambda _: self._refresh())
        self.description = QComboBox()
        self.description.setToolTip("The column each tag's description comes from")
        self.description.currentIndexChanged.connect(lambda _: self._refresh())
        self.description_label = QLabel("Description from")
        tags.addWidget(self.to_tags)
        tags.addSpacing(12)
        tags.addWidget(self.description_label)
        tags.addWidget(self.description, 1)
        lay.addLayout(tags)
        lay.addWidget(QLabel("<b>Preview</b>"))
        self.preview = QTextBrowser()
        self.preview.document().setDefaultStyleSheet(page_css())
        lay.addWidget(self.preview, 3)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.import_button = QPushButton("Import")
        self.import_button.setDefault(True)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_now)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self._show_sheet(False)
        self._show_tags(False)

    def _show_sheet(self, on: bool) -> None:
        self.sheet.setVisible(on)
        self.sheet_label.setVisible(on)

    def _show_tags(self, on: bool) -> None:
        self.to_tags.setEnabled(on)
        if not on:
            self.to_tags.setChecked(False)
        self.description.setEnabled(on and self.to_tags.isChecked())
        self.description_label.setEnabled(on)

    def _say(self, problem: str) -> None:
        self.error.setText(problem)
        self.error.setVisible(bool(problem))

    # ---- choosing and reading ----
    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the sheet", "", "Sheets (*.xlsx *.csv *.txt)")
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        """Read a file into the form (Choose…, and tests)."""
        self.path = path
        self.file.setText(str(path))
        if self.against is None and not self.name.text().strip():
            self.name.setText(path.stem)
        self._filling = True
        self.sheet.clear()
        try:
            sheets = gi.workbook_sheets(path)
        except WorkbookError as e:
            self._filling = False
            self._fail(str(e))
            return
        self.sheet.addItems(sheets)
        self._show_sheet(bool(sheets))
        self._filling = False
        self._read()

    def _fail(self, problem: str) -> None:
        self.rows, self.found = [], None
        self.table.setRowCount(0)
        self.preview.clear()
        self.import_button.setEnabled(False)
        self._say(problem)

    def _read(self) -> None:
        if self._filling or self.path is None:
            return
        try:
            self.rows = gi.read_rows(self.path, self.sheet.currentText() or None)
        except WorkbookError as e:
            self._fail(str(e))
            return
        if not self.rows:
            self._fail(f"{self.path.name} has nothing in it.")
            return
        self._filling = True
        self.header.setValue(gi.guess_header(self.rows) + 1)
        self._filling = False
        self._columns_changed()

    def _columns_changed(self) -> None:
        if self._filling or not self.rows:
            return
        row = self.header.value() - 1
        columns = gi.columns_of(self.rows, row)
        guess = gi.guess_tag_column(self.rows, row)
        self._filling = True
        self.table.setRowCount(len(columns))
        for i, name in enumerate(columns):
            self.table.setItem(i, 0, QTableWidgetItem(name))
            samples = [r[i] for r in self.rows[row + 1:row + 4] if i < len(r) and r[i]]
            self.table.setItem(i, 1, QTableWidgetItem(" · ".join(samples)))
        self.tag.clear()
        self.tag.addItem("None", None)
        for i, name in enumerate(columns):
            self.tag.addItem(name, i)
        self.tag.setCurrentIndex(max(0, self.tag.findData(guess)) if guess is not None else 0)
        self._filling = False
        self._tag_changed()

    def _tag_changed(self) -> None:
        if self._filling or not self.rows:
            return
        tag = self.tag.currentData()
        self._filling = True
        self.description.clear()
        columns = gi.columns_of(self.rows, self.header.value() - 1)
        self.description.addItem("None", None)
        for i, name in enumerate(columns):
            if i != tag:
                self.description.addItem(name, i)
        guess = gi.guess_description(gi.Preview("", columns, tag)) if tag is not None else None
        self.description.setCurrentIndex(max(0, self.description.findData(guess)) if guess is not None else 0)
        self._filling = False
        self._show_tags(tag is not None)
        self._refresh()

    def set_tag_column(self, column: int | None) -> None:
        """Make this column the tag column (tests)."""
        self.tag.setCurrentIndex(max(0, self.tag.findData(column)) if column is not None else 0)

    # ---- the preview ----
    def _refresh(self) -> None:
        if self._filling or not self.rows:
            return
        self.description.setEnabled(self.to_tags.isEnabled() and self.to_tags.isChecked())
        p = self.found = gi.preview(self.ctx.conn, self.rows, self.header.value() - 1, self.name.text(), self.tag.currentData(), self.against)
        self.tags_found = None
        if p.error:
            self.preview.setHtml(f"<p>{esc(p.summary())}</p>" if p.rows else "")
            self.import_button.setEnabled(False)
            self._say(p.error)
            return
        self._say("")
        if self.to_tags.isChecked() and p.tag_column is not None:
            self.tags_found = ti.preview(self.ctx.conn, gi.tag_rows(p), gi.tag_plan(p, self.description.currentData()))
        parts = [f"<p>{esc(p.summary().rstrip('.'))}.</p>"]
        if self.against is not None:
            parts.append(f"<p class='sub'>Importing again replaces the {self.against.rows:,} rows of {esc(self.against.name)} "
                         "with these. The backups and dump keep the old ones.</p>")
        head = "".join(f"<th align='left'>{esc(c)}</th>" for c in p.columns)
        body = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in r) + "</tr>" for r in p.rows[:5])
        parts.append(f"<p class='sec'>First rows</p><table cellspacing='0' cellpadding='3'><tr>{head}</tr>{body}</table>")
        if self.tags_found is not None:
            t = self.tags_found
            parts.append("<p class='sec'>The tag list</p>" + (f"<p class='caution'>{esc(t.error)}</p>" if t.error else
                                                              f"<p>{esc(t.summary())}. Nothing is removed from it.</p>"))
        self.preview.setHtml("".join(parts))
        self.import_button.setEnabled(bool(p.rows))

    def import_now(self) -> None:
        """Import what the preview shows, keep the outcome and close."""
        p = self.found
        if p is None or p.error or self.path is None:
            return
        now = self.ctx.now()
        try:
            if self.against is None:
                self.glossary_id = glossaries.create(self.ctx.conn, p.name, p.columns, p.tag_column, p.rows, self.path.name, now)
                said = f"Imported {p.name} from {self.path.name}: {len(p.rows):,} rows in {len(p.columns)} columns."
            else:
                glossaries.replace_rows(self.ctx.conn, self.against.id, p.columns, p.tag_column, p.rows, self.path.name, now)
                said = f"Imported {self.against.name} again from {self.path.name}: {p.changes.words() if p.changes else ''}."
        except glossaries.GlossaryError as e:
            self._say(str(e))
            return
        if self.tags_found is not None and not self.tags_found.error:
            told = ti.run_import(self.ctx.conn, self.tags_found, self.path.name, now)
            said += " The tag list: " + told.removeprefix(f"Imported {self.path.name}: ")
            self.tags_changed = True
        self.outcome = said
        self.accept()
