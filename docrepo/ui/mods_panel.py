"""The mods log panel: notes about changes the owner wants in DocRepo itself. It sits over the capture window,
whose draft stays as it was. An open entry can be edited, to add to it rather than start another (mods log round 2,
M0047)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from docrepo import mods
from docrepo.ui.context import AppContext


class ModsPanel(QWidget):
    back = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.editing: str | None = None  # the entry being edited, if any
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Mods log</b>  <span style='color:#5a6571'>Changes you want in DocRepo itself</span>"))
        top.addStretch()
        back = QPushButton("Back to the capture")
        back.clicked.connect(self.back.emit)
        top.addWidget(back)
        layout.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("What should change in DocRepo?")
        self.text.setFixedHeight(80)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(QLabel("Area"))
        self.area = QComboBox()
        self.area.addItems(list(mods.AREAS))
        row.addWidget(self.area)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancel edit")
        self.cancel_button.clicked.connect(self.cancel_edit)
        row.addWidget(self.cancel_button)
        copy = QPushButton("Copy log")
        copy.clicked.connect(self.copy_log)
        row.addWidget(copy)
        row.addStretch()
        layout.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self._sync()
        heading = QLabel("Open entries, newest first")
        heading.setObjectName("fieldLabel")
        layout.addWidget(heading)
        self.entries = QWidget()
        self.entries_layout = QVBoxLayout(self.entries)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.entries)
        layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        while self.entries_layout.count():
            item = self.entries_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        open_entries = [e for e in mods.read_log(self.ctx.data_root) if not e.done]
        for e in reversed(open_entries):
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 4, 0, 4)
            meta = QHBoxLayout()
            edited = f" · edited {e.edited}" if e.edited else ""
            meta.addWidget(QLabel(f"<span style='color:#5a6571'>{e.id} · {e.at} · {e.area}{edited}</span>"))
            edit = QPushButton("Edit")
            edit.setObjectName("link")
            edit.setToolTip("Put this entry back in the box above, to add to it or change it")
            edit.clicked.connect(lambda _=False, entry=e: self.start_edit(entry))
            meta.addWidget(edit)
            done = QPushButton("Mark done")
            done.setObjectName("link")
            done.clicked.connect(lambda _=False, i=e.id: self.mark_done(i))
            meta.addWidget(done)
            meta.addStretch()
            box_layout.addLayout(meta)
            note = QLabel(e.text)
            note.setWordWrap(True)
            box_layout.addWidget(note)
            self.entries_layout.addWidget(box)
        if not open_entries:
            self.entries_layout.addWidget(QLabel("<span style='color:#5a6571'>No open entries.</span>"))
        self.entries_layout.addStretch()

    def _sync(self) -> None:
        """Say whether the box makes a new entry or edits one."""
        self.save_button.setText(f"Save {self.editing}" if self.editing else "Save")
        self.cancel_button.setVisible(bool(self.editing))
        self.hint.setText(
            f"Editing {self.editing}: Save replaces its note and marks it edited today. Esc or Cancel edit leaves it as it was."
            if self.editing else "For changes to DocRepo. Leave out names and work details, since this log may be copied off this "
            "computer. Ctrl+Enter saves; Esc goes back to the capture.")

    def start_edit(self, entry: mods.ModEntry) -> None:
        """Put an open entry back in the box, with its area, to add to it or change it."""
        self.editing = entry.id
        self.text.setPlainText(entry.text)
        self.area.setCurrentText(entry.area)
        self._sync()
        self.text.setFocus()
        self.text.moveCursor(QTextCursor.MoveOperation.End)

    def cancel_edit(self) -> None:
        self.editing = None
        self.text.clear()
        self._sync()
        self.text.setFocus()

    def save(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            self.text.setFocus()
            self.ctx.notify("Mods log", "Type the change you want first.")
            return
        if self.editing:
            entry = mods.edit_entry(self.ctx.fs, self.ctx.data_root, self.editing, self.area.currentText(), text, self.ctx.now().date())
            message = f"{entry.id} is updated in Mods\\mods-log.md."
            self.editing = None
            self._sync()
        else:
            entry = mods.add_entry(self.ctx.fs, self.ctx.data_root, self.area.currentText(), text, self.ctx.now())
            message = f"Saved {entry.id} to Mods\\mods-log.md."
        self.text.clear()
        self.refresh()
        self.text.setFocus()
        self.ctx.notify("Mods log", message)

    def mark_done(self, mod_id: str) -> None:
        mods.mark_done(self.ctx.fs, self.ctx.data_root, mod_id, self.ctx.now().date())
        if self.editing == mod_id:
            self.cancel_edit()
        self.refresh()
        self.ctx.notify("Mods log", f"{mod_id} is marked done.")

    def copy_log(self) -> None:
        text = mods.log_text(self.ctx.data_root)
        QGuiApplication.clipboard().setText(text)
        self.ctx.notify("Mods log", f"Mods log copied ({len(text)} characters).")
