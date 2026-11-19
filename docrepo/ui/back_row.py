"""Back on Today, Log progress's one row for Today (release 5.166, the design workspace's
``docs/mods/log-progress-whole-plan.md``, decision 757).

It takes the place of 5.139's Follow up row and 5.155's Today row. Its chips, one picked at a time:
- with the task on Today, **Stays** (it stays on Today) and **Done for today** (off Today as done, under Done today);
- with the task off Today, **None** (nothing comes back by itself);
- for Log, then next…'s next step (decision 761), **Put it on Today** and **None**;
- and always **Back**: Tomorrow, 3 days, 1 week, 2 weeks, 1 month (Later's, ``later.CHOICES``) or **Other…**, a day typed
  as Later's Other… reads it (``later.read_later``): a number of workdays, or a date in words.

A Back day takes the task off Today now and sets its Reminder to that day, which puts it back (decision 415); with a wait
it's the wait's follow-up too (decision 588). The window says what each does on the row's line (``note``); this module
only draws the chips and reads the day.
"""
from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from docrepo import later

#: The chips that aren't a day.
STAYS, DONE, NONE, PUT = "stays", "done", "none", "today"
OTHER = "other"
#: Which of them each mode shows: on Today, off Today, and the next step's.
ON_TODAY, OFF_TODAY, NEXT = "on", "off", "next"
FIRST: dict[str, tuple[tuple[str, str, str], ...]] = {
    ON_TODAY: ((STAYS, "Stays", "It stays on Today"), (DONE, "Done for today", "Off Today as done once this is logged: it's under "
                                                       "Done today, where Back on Today puts it back")),
    OFF_TODAY: ((NONE, "None", "Nothing brings it back by itself"),),
    NEXT: ((PUT, "Put it on Today", "The new task goes on Today now"), (NONE, "None", "Not on Today")),
}
#: Other…'s box.
OTHER_HINT = "Fri, 15 Dec, in 3 weeks, or a number of workdays"


class BackRow(QWidget):
    """The chips and Other…'s box. ``changed`` is sent on every pick and every word typed in Other…."""

    changed = Signal()

    def __init__(self, today: Callable[[], date], workdays: Callable[[], Collection[int]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.today, self.workdays = today, workdays
        # Seven chips on a line in Log progress's width: a little less padding than a chip's own, and no minimum width.
        self.setStyleSheet("QPushButton#today { padding: 3px 7px; min-width: 0px; }")
        self.mode = ON_TODAY
        self.key = STAYS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        first = QHBoxLayout()
        first.setSpacing(4)
        for key, label in ((STAYS, "Stays"), (DONE, "Done for today"), (PUT, "Put it on Today"), (NONE, "None")):
            first.addWidget(self._chip(key, label))
        first.addStretch()
        lay.addLayout(first)
        second = QHBoxLayout()
        second.setSpacing(4)
        back = QLabel("Back", objectName="hint")
        back.setToolTip("Off Today now, and back on it that day: its Reminder")
        second.addWidget(back)
        for key, label in (*later.CHOICES, (OTHER, "Other…")):
            second.addWidget(self._chip(key, label))
        second.addStretch()
        lay.addLayout(second)
        self.other = QLineEdit(objectName="progressOther")
        self.other.setPlaceholderText(OTHER_HINT)
        self.other.textEdited.connect(lambda _t: self.changed.emit())
        self.other.hide()
        lay.addWidget(self.other)
        self.note = QLabel(objectName="hint")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.set_mode(ON_TODAY)

    def _chip(self, key: str, label: str) -> QPushButton:
        b = QPushButton(label, objectName="today")  # the checkable chip of the capture window's Today
        b.setCheckable(True)
        b.setProperty("key", key)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.toggled.connect(lambda on, k=key: self._toggled(k, on))
        self.group.addButton(b)
        self.buttons[key] = b
        return b

    def _toggled(self, key: str, on: bool) -> None:
        if not on:
            return
        self.key = key
        self.other.setVisible(key == OTHER)
        if key == OTHER:
            self.other.setFocus()
        self.changed.emit()

    # ---- what's shown ----
    def set_mode(self, mode: str) -> None:
        """On Today, off Today, or the next step's: the first chips it shows. A pick it no longer shows goes to the first."""
        self.mode = mode
        shown = {k for k, _l, _t in FIRST[mode]}
        for key, _label, tip in (x for m in FIRST.values() for x in m):
            self.buttons[key].setToolTip(tip)
        for key in (STAYS, DONE, PUT, NONE):
            self.buttons[key].setVisible(key in shown)
        if self.key in (STAYS, DONE, PUT, NONE) and self.key not in shown:
            self.pick(FIRST[mode][0][0])

    def pick(self, key: str, other: str = "") -> None:
        """Pick a chip, as a click does, without sending ``changed`` twice; ``other`` is Other…'s words."""
        self.key = key
        self.group.blockSignals(True)
        for k, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(k == key)
            b.blockSignals(False)
        self.group.blockSignals(False)
        self.other.setText(other if key == OTHER else "")
        self.other.setVisible(key == OTHER)

    def first(self) -> str:
        """The mode's first chip: Stays, None, or Put it on Today."""
        return FIRST[self.mode][0][0]

    # ---- what it means ----
    def is_day(self) -> bool:
        return self.key == OTHER or self.key in dict(later.CHOICES)

    def day(self) -> date | None:
        """The day it comes back, for a Back chip; None for the others, or for Other…'s words that aren't a day after today."""
        if self.key == OTHER:
            return later.read_later(self.other.text(), self.today(), self.workdays())
        if self.key in dict(later.CHOICES):
            return later.later_day(self.key, self.today(), self.workdays())
        return None
