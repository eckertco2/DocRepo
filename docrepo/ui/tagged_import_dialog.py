"""The browse tool's form for importing the tagged labels' glossary from Excel or CSV (release 5.79, decision 371).

Pick the file (and an .xlsx's sheet); each column gets a dropdown for what it fills, proposed from its header; the
preview says what Import would add, change, merge and refuse. Nothing is written until Import, and the file is only
read. ``docrepo/tagged_import.py`` does the work.
"""
from __future__ import annotations

import html
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

from docrepo import tagged_import as ti
from docrepo.excel_import import WorkbookError
from docrepo.ui.context import AppContext
from docrepo.ui.look import LOOK, Help
from docrepo.ui.style import page_css
from docrepo.ui.tokens import C

SHOWN = 8  # each list in the preview shows this many, then "and n more"


def esc(text: object) -> str:
    return html.escape(str(text))


class TaggedImportDialog(QDialog):
    """The import form. After Import, ``outcome`` says what was done."""

    def __init__(self, parent: QWidget | None, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Import tagged labels")
        self.setStyleSheet(f"QDialog {{ background: {C.content}; }} QLabel#error {{ background: {C.critical_bg}; color: {C.critical}; padding: 6px 10px; }}")
        self.resize(820, 680)
        self.path: Path | None = None
        self.rows: list[list[str]] = []
        self.found: ti.Preview | None = None
        self.outcome = ""
        self._filling = False
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.addWidget(Help("The plant's tag list: a tagged label, its description and its aliases in each row, from an .xlsx or a .csv. "
                           "The file is only read. Importing again merges: it adds labels and aliases, and replaces a description that "
                           "differs unless you keep DocRepo's. Nothing is removed."))
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
        grid.addWidget(QLabel("File"), 0, 0)
        grid.addWidget(self.file, 0, 1, 1, 3)
        grid.addWidget(choose, 0, 4)
        grid.addWidget(self.sheet_label, 1, 0)
        grid.addWidget(self.sheet, 1, 1)
        grid.addWidget(QLabel("Headers in row"), 1, 2)
        grid.addWidget(self.header, 1, 3)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addWidget(QLabel("<b>Columns</b>"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Column", "First rows", "Fills"])
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 2)
        self.keep = QCheckBox("Keep DocRepo's descriptions where the file's differ")
        self.keep.toggled.connect(lambda _: self._refresh())
        lay.addWidget(self.keep)
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
        self.import_button = QPushButton("Import", objectName="primary" if LOOK.classic else "")
        self.import_button.setDefault(True)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_now)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self._show_sheet(False)

    def _show_sheet(self, on: bool) -> None:
        self.sheet.setVisible(on)
        self.sheet_label.setVisible(on)

    def _say(self, problem: str) -> None:
        self.error.setText(problem)
        self.error.setVisible(bool(problem))

    # ---- choosing and reading ----
    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose the tag list", "", "Tag lists (*.xlsx *.csv *.txt)")
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        """Read a file into the form (Choose…, and tests)."""
        self.path = path
        self.file.setText(str(path))
        self._filling = True
        self.sheet.clear()
        try:
            sheets = ti.workbook_sheets(path)
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
            self.rows = ti.read_rows(self.path, self.sheet.currentText() or None)
        except WorkbookError as e:
            self._fail(str(e))
            return
        if not self.rows:
            self._fail(f"{self.path.name} has nothing in it.")
            return
        self._filling = True
        self.header.setValue(ti.guess_header(self.rows) + 1)
        self._filling = False
        self._columns_changed()

    def _columns_changed(self) -> None:
        if self._filling or not self.rows:
            return
        row = self.header.value() - 1
        header = self.rows[row] if row < len(self.rows) else []
        fields = ti.propose(self.rows, row)
        self._filling = True
        self.table.setRowCount(len(header))
        for i, name in enumerate(header):
            self.table.setItem(i, 0, QTableWidgetItem(name or f"Column {i + 1}"))
            samples = [r[i] for r in self.rows[row + 1:row + 4] if i < len(r) and r[i]]
            self.table.setItem(i, 1, QTableWidgetItem(" · ".join(samples)))
            box = QComboBox()
            for value, text in ti.FIELDS:
                box.addItem(text, value)
            box.setCurrentIndex(box.findData(fields[i]))
            box.currentIndexChanged.connect(lambda _: self._refresh())
            self.table.setCellWidget(i, 2, box)
        self._filling = False
        self._refresh()

    def fields(self) -> list[str]:
        return [self.table.cellWidget(i, 2).currentData() for i in range(self.table.rowCount())]

    def set_field(self, column: int, value: str) -> None:
        box = self.table.cellWidget(column, 2)
        box.setCurrentIndex(box.findData(value))

    # ---- the preview ----
    def _refresh(self) -> None:
        if self._filling or not self.rows:
            return
        plan = ti.Plan(self.header.value() - 1, self.fields(), self.keep.isChecked())
        self.found = ti.preview(self.ctx.conn, self.rows, plan)
        p = self.found
        if p.error:
            self._fail_preview(p.error)
            return
        self._say("")

        def listed(title: str, xs: list[str]) -> str:
            if not xs:
                return ""
            more = f"<li class='sub'>and {len(xs) - SHOWN} more</li>" if len(xs) > SHOWN else ""
            return f"<p class='sec'>{esc(title)}</p><ul>{''.join(f'<li>{esc(x)}</li>' for x in xs[:SHOWN])}{more}</ul>"

        parts = [f"<p>{esc(p.summary())}. Nothing is removed.</p>"]
        if p.cut:
            parts.append(f"<p class='caution'>Only the first {ti.MAX_ROWS:,} rows are read.</p>")
        if p.added:
            shown = ", ".join(esc(x) for x in p.added[:40]) + (f" <span class='sub'>and {len(p.added) - 40} more</span>" if len(p.added) > 40 else "")
            parts.append(f"<p class='sec'>Added</p><p><span class='tg'>{shown}</span></p>")
        parts.append(listed("Descriptions that differ" + (" (DocRepo's kept)" if self.keep.isChecked() else ""),
                            [f"{a}: “{b}” → “{c}”" for a, b, c in p.changed]))
        parts.append(listed("Aliases added", [f"{a}: {b}" for a, b in p.aliases_added]))
        parts.append(listed("Merged and moved", p.merged))
        parts.append(listed("Refused", p.refused))
        self.preview.setHtml("".join(parts))
        self.import_button.setEnabled(bool(p.added or p.changed or p.aliases_added or p.merged))

    def _fail_preview(self, problem: str) -> None:
        self.preview.clear()
        self.import_button.setEnabled(False)
        self._say(problem)

    def import_now(self) -> None:
        if not self.found or self.found.error or self.path is None:
            return
        self.outcome = ti.run_import(self.ctx.conn, self.found, self.path.name, self.ctx.now())
        self.accept()
