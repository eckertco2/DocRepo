"""The mods log panel: notes about changes the owner wants in DocRepo itself. It sits over the capture window,
whose draft stays as it was."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
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
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        row.addWidget(save)
        copy = QPushButton("Copy log")
        copy.clicked.connect(self.copy_log)
        row.addWidget(copy)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel("For changes to DocRepo. Leave out names and work details, since this log may be copied off this computer. "
                      "Ctrl+Enter saves; Esc goes back to the capture.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
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
            meta.addWidget(QLabel(f"<span style='color:#5a6571'>{e.id} · {e.at} · {e.area}</span>"))
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

    def save(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            self.text.setFocus()
            self.ctx.notify("Mods log", "Type the change you want first.")
            return
        entry = mods.add_entry(self.ctx.fs, self.ctx.data_root, self.area.currentText(), text, self.ctx.now())
        self.text.clear()
        self.refresh()
        self.text.setFocus()
        self.ctx.notify("Mods log", f"Saved {entry.id} to Mods\\mods-log.md.")

    def mark_done(self, mod_id: str) -> None:
        mods.mark_done(self.ctx.fs, self.ctx.data_root, mod_id, self.ctx.now().date())
        self.refresh()
        self.ctx.notify("Mods log", f"{mod_id} is marked done.")

    def copy_log(self) -> None:
        text = mods.log_text(self.ctx.data_root)
        QGuiApplication.clipboard().setText(text)
        self.ctx.notify("Mods log", f"Mods log copied ({len(text)} characters).")
