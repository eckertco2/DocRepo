"""The browse tool's form for the one-time import of the project list from Excel.

Pick the workbook and sheet; each column gets a dropdown for what it fills,
proposed from its header, and a State column's values each get the state they
become. The preview below shows what Import will create. Nothing is written
until Import, and the workbook is only read. ``docrepo/excel_import.py`` does the work.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from docrepo import excel_import as xi
from docrepo.db import STATES
from docrepo.ui.style import page_css
from docrepo.model import Model
from docrepo.ui.context import AppContext

PREVIEW_ROWS = 15


def esc(text: object) -> str:
    return html.escape(str(text))


class ImportDialog(QDialog):
    """The import form. After Import, ``outcome`` says what was done."""

    def __init__(self, parent: QWidget | None, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Import projects from Excel")
        self.setStyleSheet("QDialog { background: #ffffff; } QLabel#hint { color: #5a6571; } "
                           "QLabel#error { background: #fbe3e1; color: #b0261e; padding: 6px 10px; } "
                           "QPushButton#primary { background: #1d5e98; color: #ffffff; border: 1px solid #1d5e98; padding: 4px 14px; }"
                           "QPushButton#primary:disabled { background: #b8c1cb; border-color: #b8c1cb; }")
        self.resize(1100, 820)
        self.path: Path | None = None
        self.rows: list[list[object]] = []
        self.plan: xi.Plan | None = None
        self.found: xi.Preview | None = None
        self.outcome = ""
        self._filling = False
        self._build()
        self._show_last_import()

    # ---- the form ----
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        intro = QLabel("A one-time import of your project list: each row becomes a top-level task, imported from the Excel tracker. "
                       "The workbook is only read, never changed. Check what each column fills, then Import.", objectName="hint")
        intro.setWordWrap(True)  # kept in view: it says what the import does before you do it
        lay.addWidget(intro)
        self.last = QLabel(objectName="hint")
        self.last.setWordWrap(True)
        lay.addWidget(self.last)
        grid = QGridLayout()
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.file.setPlaceholderText("No workbook chosen")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        self.sheet = QComboBox()
        self.sheet.currentIndexChanged.connect(lambda _: self._load_sheet())
        self.header = QSpinBox()
        self.header.setRange(1, 30)
        self.header.valueChanged.connect(lambda _: self._columns_changed())
        self.default_state = QComboBox()
        self.default_state.addItems(list(STATES))
        self.default_state.setCurrentText("In progress")
        self.default_state.currentIndexChanged.connect(lambda _: self._refresh_preview())
        grid.addWidget(QLabel("Workbook"), 0, 0)
        grid.addWidget(self.file, 0, 1, 1, 3)
        grid.addWidget(choose, 0, 4)
        grid.addWidget(QLabel("Sheet"), 1, 0)
        grid.addWidget(self.sheet, 1, 1)
        grid.addWidget(QLabel("Headers in row"), 1, 2)
        grid.addWidget(self.header, 1, 3)
        grid.addWidget(QLabel("Without a State column, tasks start as"), 2, 0, 1, 2)
        grid.addWidget(self.default_state, 2, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        lay.addWidget(QLabel("<b>Columns</b>"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Column", "Examples", "Fills", "Label"])
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 160)
        lay.addWidget(self.table, 3)
        self.states_label = QLabel("<b>State values</b> <span style='color:#5a6571'>what each value in the State column becomes</span>")
        lay.addWidget(self.states_label)
        self.states = QTableWidget(0, 3)
        self.states.setHorizontalHeaderLabels(["Value", "Rows", "Becomes"])
        self.states.verticalHeader().setVisible(False)
        self.states.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.states.setMaximumHeight(160)
        lay.addWidget(self.states)
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
        self.import_button = QPushButton("Import", objectName="primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_now)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self._show_states([])
        self.preview.setHtml('<p class="note">Choose the workbook that holds your project list.</p>')

    def _show_last_import(self) -> None:
        last = xi.last_import(self.ctx.conn)
        if last:
            when = datetime.fromisoformat(last["at"])
            self.last.setText(f"<b>Already imported:</b> {last.get('tasks', 0)} tasks on {when:%d %b %Y} from {esc(last.get('file') or 'a workbook')}. "
                              "Importing again skips any row whose title is already an imported task.")
        self.last.setVisible(bool(last))

    def _fail(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    # ---- choosing the workbook and sheet ----
    def _choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "The workbook with your project list", "", "Excel workbooks (*.xlsx *.xlsm);;All files (*)")
        if name:
            self.set_workbook(Path(name))

    def set_workbook(self, path: Path) -> None:
        self._fail("")
        try:
            sheets = xi.sheet_names(path)
        except xi.WorkbookError as e:
            self._fail(str(e))
            return
        self.path = path
        self.file.setText(str(path))
        self._filling = True
        self.sheet.clear()
        self.sheet.addItems(sheets)
        best = next((s for s in sheets if "project" in s.lower()), sheets[0] if sheets else "")
        self.sheet.setCurrentText(best)
        self._filling = False
        self._load_sheet()

    def _load_sheet(self) -> None:
        if self._filling or not self.path or not self.sheet.currentText():
            return
        try:
            self.rows = xi.read_sheet(self.path, self.sheet.currentText())
        except xi.WorkbookError as e:
            self._fail(str(e))
            return
        self._filling = True
        self.header.setValue(xi.guess_header_row(self.rows) + 1)
        self._filling = False
        self._columns_changed()

    # ---- the mapping ----
    def _columns_changed(self) -> None:
        """Propose the mapping again, for the sheet and header row now chosen."""
        if self._filling or not self.rows:
            return
        columns = xi.propose(self.rows, self.header.value() - 1)
        self.plan = xi.Plan(columns, self.header.value() - 1)
        self._filling = True
        self.table.setRowCount(len(columns))
        for r, c in enumerate(columns):
            self.table.setItem(r, 0, _item(c.header))
            self.table.setItem(r, 1, _item(" · ".join(s if len(s) <= 50 else s[:50] + "…" for s in c.samples)))
            fills = QComboBox()
            for key, label in xi.FIELDS:
                fills.addItem(label, key)
            fills.setCurrentIndex(max(0, fills.findData(c.field)))
            fills.currentIndexChanged.connect(lambda _=0, row=r: self._field_changed(row))
            self.table.setCellWidget(r, 2, fills)
            label = QLineEdit(c.label)
            label.setPlaceholderText("Label name")
            label.setEnabled(c.field == "label")
            label.textEdited.connect(lambda _=None, row=r: self._label_changed(row))
            self.table.setCellWidget(r, 3, label)
        self.table.resizeRowsToContents()
        self._filling = False
        self._refresh_states()
        self._refresh_preview()

    def set_field(self, header: str, key: str, label: str = "") -> None:
        """Set what a column fills, as choosing it in its dropdown does (and the label, for a yes or no column)."""
        row = next(i for i, c in enumerate(self.plan.columns) if c.header == header)
        combo: QComboBox = self.table.cellWidget(row, 2)
        combo.setCurrentIndex(combo.findData(key))
        if label:
            edit: QLineEdit = self.table.cellWidget(row, 3)
            edit.setText(label)
            self._label_changed(row)

    def _field_changed(self, row: int) -> None:
        if self._filling or self.plan is None:
            return
        combo: QComboBox = self.table.cellWidget(row, 2)
        column = self.plan.columns[row]
        column.field = combo.currentData()
        edit: QLineEdit = self.table.cellWidget(row, 3)
        edit.setEnabled(column.field == "label")
        if column.field == "label" and not edit.text():
            edit.setText(column.header)
            column.label = column.header
        self._refresh_states()
        self._refresh_preview()

    def _label_changed(self, row: int) -> None:
        if self.plan is None:
            return
        self.plan.columns[row].label = self.table.cellWidget(row, 3).text()
        self._refresh_preview()

    def _refresh_states(self) -> None:
        values = xi.state_values(self.rows, self.plan.header_row, self.plan.column_for("state")) if self.plan else []
        self.plan.state_map = {v: s for v, _, s in values}
        self._show_states(values)

    def _show_states(self, values: list[tuple[str, int, str]]) -> None:
        self.states.setRowCount(len(values))
        for r, (value, count, state) in enumerate(values):
            self.states.setItem(r, 0, _item(value))
            self.states.setItem(r, 1, _item(str(count)))
            becomes = QComboBox()
            becomes.addItems(list(STATES))
            becomes.setCurrentText(state)
            becomes.currentTextChanged.connect(lambda s, v=value: self._state_changed(v, s))
            self.states.setCellWidget(r, 2, becomes)
        self.states_label.setVisible(bool(values))
        self.states.setVisible(bool(values))

    def _state_changed(self, value: str, state: str) -> None:
        self.plan.state_map[value] = state
        self._refresh_preview()

    # ---- the preview ----
    def _refresh_preview(self) -> None:
        if self._filling or self.plan is None:
            return
        self.plan.default_state = self.default_state.currentText()
        self._fail("")
        try:
            self.found = xi.preview(self.rows, self.plan, Model(self.ctx.conn), self.ctx.now().date())
        except xi.WorkbookError as e:
            self.found = None
            self.import_button.setEnabled(False)
            self.preview.setHtml(f'<p class="note">{esc(e)}</p>')
            return
        f = self.found
        rows = f.to_import
        skipped = [r for r in f.rows if r.skip]
        problems = [(r.line, p) for r in f.rows for p in r.problems]
        out = [f"<p><b>{len(rows)} task{'s' if len(rows) != 1 else ''}</b> to import"
               + (f", {len(skipped)} row{'s' if len(skipped) != 1 else ''} skipped" if skipped else "") + "."
               + (f" New people: {esc(', '.join(f.new_people))}." if f.new_people else "")
               + (f" New labels: {esc(', '.join(f.new_labels))}." if f.new_labels else "") + "</p>"]
        cells = "".join(
            f"<tr><td>{r.line}</td><td>{esc(r.title)}</td><td>{esc(r.fields.get('state', ''))}</td><td>{esc(r.fields.get('due', ''))}</td>"
            f"<td>{esc(', '.join(r.leads))}</td><td>{esc(', '.join(r.assignees))}</td><td>{esc(', '.join(r.labels))}</td></tr>"
            for r in rows[:PREVIEW_ROWS])
        out.append('<table cellspacing="0" cellpadding="3"><tr><th align="left">Row</th><th align="left">Title</th><th align="left">State</th>'
                   '<th align="left">Due</th><th align="left">Lead</th><th align="left">Assignees</th><th align="left">Labels</th></tr>'
                   f"{cells}</table>")
        if len(rows) > PREVIEW_ROWS:
            out.append(f'<p class="note">and {len(rows) - PREVIEW_ROWS} more.</p>')
        if problems:
            out.append("<p><b>To check</b></p>" + "".join(f'<p class="note">Row {line}: {esc(p)}</p>' for line, p in problems[:40]))
        if skipped:
            out.append("<p><b>Skipped</b></p>" + "".join(f'<p class="note">Row {r.line}, {esc(r.title)}: {esc(r.skip)}</p>' for r in skipped[:40]))
        self.preview.setHtml("".join(out))
        self.import_button.setEnabled(bool(rows))

    # ---- importing ----
    def import_now(self) -> None:
        if not self.found or not self.found.to_import:
            return
        try:
            self.outcome = xi.run_import(self.ctx.conn, self.ctx.settings, self.ctx.data_root, self.ctx.fs, self.found, self.ctx.now(),
                                         self.path.name if self.path else "")
        except Exception as e:  # noqa: BLE001 - nothing was written: the import is one transaction
            self._fail(f"Nothing was imported: {e}")
            return
        self.accept()


def _item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
