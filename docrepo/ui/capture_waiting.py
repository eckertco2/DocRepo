"""Waiting on a reply in the capture window's State lists (release 5.166, the design workspace's
``docs/mods/log-progress-whole-plan.md``, decision 762).

The owner looked for Waiting on a reply where states are picked. A wait is a mark on In progress, not a state (decision
580), so the choice here is In progress with a wait: New task's and Update's State lists gain **Waiting on a reply**,
after In progress, and picked, a **Waiting on** row shows under it, people chips as Log progress's. Save keeps the task In
progress and starts the wait (``save.CaptureDraft.waiting_on``), its follow-up the Reminder field already there. Edit
task's State stays the four states: it edits the field, and a wait isn't one.

This module holds the choice and the row, so ``CaptureWindow`` only places them.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from docrepo.model import Model

#: The State lists' choice.
WAITING = "Waiting on a reply"
TIP = "In progress, with a wait on someone: who in Waiting on, the follow-up in Reminder"


def add_waiting(combo: QComboBox) -> None:
    """Put Waiting on a reply in a State list, after In progress."""
    at = combo.findText("In progress")
    combo.insertItem(at + 1, WAITING)
    combo.setItemData(at + 1, TIP, Qt.ItemDataRole.ToolTipRole)


def is_waiting(combo: QComboBox) -> bool:
    return combo.currentText() == WAITING


def state_of(combo: QComboBox) -> str:
    """The task's state for the pick: Waiting on a reply is In progress (decision 580)."""
    return "In progress" if is_waiting(combo) else combo.currentText()


class WaitingRow(QWidget):
    """Waiting on: a chip per person, and a box for a name from People (Enter adds it; Backspace in the empty box takes the
    last off). ``people`` are their IDs."""

    changed = Signal()

    def __init__(self, model: Callable[[], Model], me: Callable[[], str | None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model, self.me = model, me
        self.people: list[str] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel("Waiting on", objectName="fieldLabel"))
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        lay.addLayout(self.chips)
        self.box = QLineEdit(objectName="waitingWho")
        self.box.setPlaceholderText("Type a name from People")
        self.box.setAccessibleName("Waiting on")
        self.box.installEventFilter(self)
        lay.addWidget(self.box, 1)
        self.note = QLabel(objectName="hint")
        lay.addWidget(self.note)

    def reset(self) -> None:
        """No one, and the names People has now."""
        self.people = []
        self.box.clear()
        names = [p.name for p in self.model().people.values() if p.status == "active" and p.id != self.me()]
        completer = QCompleter(sorted(names), self.box)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(lambda _t: self.add())
        self.box.setCompleter(completer)
        self.render()

    def add(self) -> bool:
        """The box's words as a person in People: added, or said why not. False when the box was empty."""
        words = self.box.text().strip().casefold()
        if not words:
            return False
        m = self.model()
        found = [p.id for p in m.people.values() if p.status == "active" and (p.name.casefold() == words or words in p.name.casefold())]
        if len(found) != 1:
            self.note.setText("Type a name from People." if not found else "Several match: type more.")
            return True
        if found[0] not in self.people:
            self.people.append(found[0])
        self.box.clear()
        self.render()
        self.changed.emit()
        return True

    def drop(self, person: str) -> None:
        self.people = [p for p in self.people if p != person]
        self.render()
        self.changed.emit()

    def render(self) -> None:
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        m = self.model()
        for p in self.people:
            chip = QPushButton(f"{m.person_name(p)}  ✕", objectName="today")
            chip.setToolTip(f"Not waiting on {m.person_name(p)}")
            chip.clicked.connect(lambda _=False, who=p: self.drop(who))
            self.chips.addWidget(chip)
        self.note.setText("")
        self.box.setPlaceholderText("Add a person" if self.people else "Type a name from People")

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if watched is self.box and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                if self.add():
                    return True
            elif event.key() == Qt.Key.Key_Backspace and not self.box.text() and self.people:
                self.drop(self.people[-1])
                return True
        return super().eventFilter(watched, event)
