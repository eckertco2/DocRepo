"""Edit task's Reminder repeats (release 5.117, decision 416): how often a task's reminder comes round, as one of
``repeats``' rules. A form piece of its own, as the repo's rule asks (release 5.95, the review's F11)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QSpinBox, QStackedWidget, QWidget

from docrepo import repeats
from docrepo.dates import WEEKDAYS

#: The kinds, in the list's order: (rule kind, words). The first is none.
KINDS = (("", "Doesn't repeat"), ("week", "Every week on"), ("month", "Every month on day"), ("workday", "Every month on workday"),
         ("days", "Every n days"))


class RepeatField(QWidget):
    """A kind, then what it needs: weekdays, a day of the month, a workday of the month, or a number of days."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.kind = QComboBox()
        self.kind.setAccessibleName("Reminder repeats")
        for key, words in KINDS:
            self.kind.addItem(words, key)
        lay.addWidget(self.kind)
        self.parts = QStackedWidget()
        lay.addWidget(self.parts, 1)
        self.parts.addWidget(QWidget())  # none
        week = QWidget()
        wl = QHBoxLayout(week)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)
        self.weekdays = []
        for name in WEEKDAYS:
            box = QCheckBox(name)
            box.toggled.connect(lambda _=False: self.changed.emit())
            self.weekdays.append(box)
            wl.addWidget(box)
        wl.addStretch()
        self.parts.addWidget(week)
        self.day = QComboBox()
        self.day.setAccessibleName("Day of the month")
        self.workday = QComboBox()
        self.workday.setAccessibleName("Workday of the month")
        for box, top in ((self.day, 31), (self.workday, 23)):
            for n in range(1, top + 1):
                box.addItem(str(n), str(n))
            box.addItem("Last", "last")
            box.currentIndexChanged.connect(lambda _=0: self.changed.emit())
            self.parts.addWidget(box)
        self.every = QSpinBox()
        self.every.setRange(1, 366)
        self.every.setValue(7)
        self.every.setSuffix(" days")
        self.every.setAccessibleName("Every how many days")
        self.every.valueChanged.connect(lambda _=0: self.changed.emit())
        self.parts.addWidget(self.every)
        self.kind.currentIndexChanged.connect(self._kind_changed)

    def _kind_changed(self, index: int) -> None:
        self.parts.setCurrentIndex(index)
        self.changed.emit()

    def set_value(self, rule: str | None) -> None:
        """Show a kept rule, or none."""
        r = repeats.parse(rule) if rule else None
        self.kind.setCurrentIndex(0 if r is None else [k for k, _ in KINDS].index(r.kind))
        if r is None:
            return
        if r.kind == "week":
            for i, box in enumerate(self.weekdays):
                box.setChecked(i in r.weekdays)
        elif r.kind in ("month", "workday"):
            box = self.day if r.kind == "month" else self.workday
            box.setCurrentIndex(box.findData("last" if r.n == repeats.LAST else str(r.n)))
        else:
            self.every.setValue(r.n)

    def value(self) -> str | None:
        """The rule as it's kept, or None: "Doesn't repeat", or Every week with no weekday ticked."""
        kind = self.kind.currentData()
        if not kind:
            return None
        if kind == "week":
            days = [WEEKDAYS[i].lower() for i, box in enumerate(self.weekdays) if box.isChecked()]
            return f"week:{','.join(days)}" if days else None
        if kind in ("month", "workday"):
            return f"{kind}:{(self.day if kind == 'month' else self.workday).currentData()}"
        return f"days:{self.every.value()}"

    def problem(self) -> str | None:
        if self.kind.currentData() == "week" and self.value() is None:
            return "Tick a weekday for Every week on, or pick Doesn't repeat."
        return None
