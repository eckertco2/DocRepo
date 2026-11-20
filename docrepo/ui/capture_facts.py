"""The capture window's facts as chips (release 5.188, the redesign's decision 861): under the content text, one chip a
field that has a value, each opening its field; the words Parse and populate understood are tinted in the text itself
(``OperatorHighlighter.set_understood``), and the fields sit behind "More fields".

A chip is a view of its field's widget, never a value of its own: a value typed by hand shows as Parse's does, and Save
reads the fields as it always has. With the fields shut, a chip opens its field in a ``FactPopover``, the field's own widget
lent to it and put back where it was when it closes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyleOptionToolButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo.dates import long_date
from docrepo.ui import capture_waiting, tokens
from docrepo.ui.icons import icon
from docrepo.ui.widgets import ChipPicker, DateField, FlowLayout, HoursField

#: How long a chip's value may be before it's cut, as the Understood line cut it.
VALUE_MOST = 40
#: The keys of finds whose source is a sentence or a description: a tint over a whole sentence marks nothing.
UNTINTED = ("title", "status", "deadline_desc")


def understood_phrases(found: list) -> list[tuple[str, str]]:
    """The phrases Parse and populate filled a field from, each with its kind ("person" for Lead and Assignees, else
    "fact"), for the highlighter to tint where they stand in the text. A find that wasn't filled (it has a ``why``), a
    title, a status, a deadline's description and a phrase over two lines give none."""
    out: list[tuple[str, str]] = []
    for _lead, f in found:
        if f.why or f.key in UNTINTED or "\n" in f.source:
            continue
        out.append((f.source.strip(), "person" if f.key in ("leads", "assignees") else "fact"))
    return out


@dataclass(frozen=True)
class Fact:
    """One chip: the field's name in the window (``key``), what it's called and what it holds, the widget to open, and where
    Parse and populate got it."""

    key: str
    label: str
    value: str
    widget: QWidget | None
    tip: str = ""


def _cut(text: str) -> str:
    return text if len(text) <= VALUE_MOST else text[:VALUE_MOST] + "…"


def _value(widget: Any) -> Any:
    """A field's value, as a snapshot compares it."""
    if isinstance(widget, DateField):
        return widget.value()
    if isinstance(widget, HoursField):
        return widget.value()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    if isinstance(widget, QPlainTextEdit):
        return widget.toPlainText().strip()
    if isinstance(widget, ChipPicker):
        return tuple(widget.values())
    if isinstance(widget, capture_waiting.WaitingRow):
        return tuple(widget.people)
    rows = getattr(widget, "rows", None)
    if callable(rows):  # the key dates' editor
        return len(rows())
    return None


def _more_fields(w: Any) -> list[tuple[str, str, QWidget]]:
    """The new task's fields under the old More fields link, in the order the chips list them: (key, label, widget)."""
    fields = [("new.state", "State", w.n_state), ("new.start", "Start", w.n_start), ("new.reminder", "Reminder", w.n_reminder),
              ("new.recurrence", "Recurrence", w.n_recurrence), ("new.duration", "Duration", w.n_duration)]
    fields += [(f"new.ref:{name}", name, box) for name, box in w.n_refs.items()]
    fields += [("new.deadline_desc", "Deadline description", w.n_deadline_desc), ("new.urgent", "Urgent", w.n_urgent),
               ("new.meeting", "Meeting", w.n_meeting), ("new.plant_event", "Plant event", w.n_plant),
               ("new.key_dates", "Key dates", w.n_keydates), ("new.waiting", "Waiting on", w.n_waiting)]
    return fields


def snapshot(w: Any) -> None:
    """Note the new task's More fields as the window leaves them (at the end of ``reset_draft`` and ``prefill``), so a chip
    shows a field only once it differs."""
    w._fact_snapshot = {key: _value(widget) for key, _label, widget in _more_fields(w)}


def _day(value: str | None, today: date) -> str:
    try:
        return long_date(date.fromisoformat(value), today) if value else ""
    except ValueError:
        return value or ""


def _hours(value: float | None) -> str:
    return "" if value is None else f"{value:g} h"


def _people(chips: ChipPicker) -> str:
    return ", ".join(c.label for c in chips.chips())


def _tip(w: Any, prefix: str, key: str, field_name: str = "") -> str:
    """Where Parse and populate got a field's value this time: "from “by Fri 16 Oct”". ``w._understood`` holds each find
    with the block it filled, "new" or "upd"."""
    for block, f in getattr(w, "_understood", []):
        if block != prefix or f.why or f.key != key or (field_name and f.field != field_name):
            continue
        return f"from “{f.source[:80]}”"
    return ""


def _new_facts(w: Any, today: date) -> list[Fact]:
    out: list[Fact] = []
    for key, label, field in (("due", "Due", w.n_due), ("deadline", "Deadline", w.n_deadline)):
        if field.value():
            out.append(Fact(f"new.{key}", label, _day(field.value(), today), field, _tip(w, "new", key)))
    for key, label, chips, hours in (("leads", "Lead", w.n_leads, w.n_lead_hours), ("assignees", "Assignees", w.n_assignees, w.n_asg_hours)):
        if chips.chips():
            words = _people(chips) + (f" · {_hours(hours.value())}" if hours.value() is not None else "")
            out.append(Fact(f"new.{key}", label, _cut(words), chips, _tip(w, "new", key)))
    if w.n_labels.chips():
        out.append(Fact("new.labels", "Label" if len(w.n_labels.chips()) == 1 else "Labels", _cut(_people(w.n_labels)), w.n_labels,
                        _tip(w, "new", "labels")))
    was = getattr(w, "_fact_snapshot", {})
    for key, label, field in _more_fields(w):
        now = _value(field)
        if (now == was[key]) if key in was else not now:  # a field made after the snapshot (a reference field) shows once it has words
            continue
        if isinstance(field, QCheckBox):
            words = "Yes" if now else "No"
        elif isinstance(field, DateField):
            words = _day(now, today)
        elif key == "new.recurrence":
            words = now + (f" until {_day(w.n_repeat.value(), today)}" if w.n_repeat.value() else "")
        elif key == "new.duration":
            words = f"{now} days" if now else ""
        elif key == "new.waiting":
            words = ", ".join(w.ctx.model().person_name(p) for p in now)
        else:
            words = str(now)
        if words == "" and not isinstance(field, QCheckBox):
            words = "none"
        name = key.split(".", 1)[1]
        found_key, found_field = ("refs", name[4:]) if name.startswith("ref:") else (name, "")
        out.append(Fact(key, label, _cut(words), field, _tip(w, "new", found_key, found_field)))
    return out


#: An update's changes: their labels and the window's widgets, by ``update_changes``' keys.
def _update_fields(w: Any) -> dict[str, tuple[str, QWidget | None]]:
    return {"due": ("Due", w.u_due), "deadline": ("Deadline", w.u_deadline), "deadline_desc": ("Deadline description", w.u_deadline_desc),
            "leads": ("Lead", w.u_leads), "assignees": ("Assignees", w.u_assignees), "lead_hours": ("Lead hours", w.u_lead_hours),
            "assignee_hours": ("Assignee hours", w.u_asg_hours), "duration": ("Duration", w.u_duration),
            "calendar_days": ("Runs through weekends", w.u_calendar), "start": ("Start", w.u_start), "reminder": ("Reminder", w.u_reminder),
            "recurrence": ("Recurrence", w.u_recurrence), "repeat_until": ("Repeat until", w.u_repeat), "urgent": ("Urgent", w.u_urgent),
            "meeting": ("Meeting", w.u_meeting), "plant_event": ("Plant event", w.u_plant)}


def _update_facts(w: Any, today: date) -> list[Fact]:
    t = w.ctx.model().tasks.get(w.task) if w.task else None
    if t is None:
        return []
    lead = "Update: " if "new_task" in w.types else ""
    changes = w.update_changes(t)
    fields = _update_fields(w)
    out: list[Fact] = []
    for key, value in changes.items():
        if key in ("state", "current_status", "references"):
            continue
        label, widget = fields.get(key, (key.replace("_", " ").capitalize(), None))
        if isinstance(value, bool):
            words = "Yes" if value else "No"
        elif isinstance(value, str) and widget is not None and isinstance(widget, DateField):
            words = _day(value, today)
        else:
            words = w._short(value)
        out.append(Fact(f"upd.{key}", lead + label, _cut(words), widget, _tip(w, "upd", key)))
    for name, value in changes.get("references", {}).items():
        out.append(Fact(f"upd.ref:{name}", lead + name, _cut(value or "none"), w.u_refs.get(name), _tip(w, "upd", "refs", name)))
    if w.update_key_dates() is not None:
        out.append(Fact("upd.key_dates", lead + "Key dates", f"{len(w.u_keydates.rows())} in all", w.u_keydates))
    return out


def facts(w: Any) -> list[Fact]:
    """The chips for the window as it stands: a new task's fields that have a value (its everyday five, then each field
    under its More fields that isn't as a new capture leaves it), then an update's changes, as its history line lists them."""
    today = w.ctx.now().date()
    out: list[Fact] = []
    if "new_task" in w.types:
        out += _new_facts(w, today)
    if "update" in w.types and w.task:
        out += _update_facts(w, today)
    return out


class FactChip(QToolButton):
    """One fact: its label in the third grey, then its value, 24 px high. ``text()`` is both, for tests and screen readers."""

    def __init__(self, fact: Fact, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fact = fact
        self.setObjectName("fact")
        self.setText(f"{fact.label} {fact.value}")
        self.setAccessibleName(self.text())
        self.setToolTip(f"{fact.label}: {fact.value}" + (f", {fact.tip}" if fact.tip else "") + ". Opens the field.")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        """The style's panel, then the two runs of words: the label grey, the value dark."""
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""
        p = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt, p, self)
        fm = self.fontMetrics()
        inner = self.style().subControlRect(QStyle.ComplexControl.CC_ToolButton, opt, QStyle.SubControl.SC_ToolButton, self)
        text_width = fm.horizontalAdvance(self.text())
        x = inner.left() + max(0, (inner.width() - text_width) // 2)
        label = f"{self.fact.label} "
        p.setPen(tokens.colour("text3"))
        p.drawText(QRect(x, inner.top(), inner.width(), inner.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += fm.horizontalAdvance(label)
        p.setPen(tokens.colour("text"))
        value = fm.elidedText(self.fact.value, Qt.TextElideMode.ElideRight, max(0, inner.right() - x))
        p.drawText(QRect(x, inner.top(), inner.right() - x, inner.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, value)
        p.end()


class FactChips(QWidget):
    """The row of chips: one a fact, then "More fields", which shows and hides the fields' block. Rebuilt only when the
    facts change, as ``refresh`` runs on every change and typing must not rebuild a row of buttons."""

    opened = Signal(object)  # a Fact
    more = Signal(bool)
    rebuilt = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = FlowLayout(self)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self.chips: list[FactChip] = []
        self._shown: list[tuple[str, str, str]] | None = None
        self.more_chip = QToolButton(objectName="factMore")
        self.more_chip.setText("More fields")
        self.more_chip.setIcon(icon("add"))
        self.more_chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_chip.setCheckable(True)
        self.more_chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.more_chip.setToolTip("The new task's or the update's fields: Labels, Lead, Assignees, Due, Deadline and the rest")
        self.more_chip.toggled.connect(self.more.emit)
        self._flow.addWidget(self.more_chip)

    def show_facts(self, items: list[Fact]) -> None:
        """Show these facts, if they differ from the ones showing."""
        shown = [(f.key, f.label, f.value) for f in items]
        if shown == self._shown:
            for chip, f in zip(self.chips, items, strict=True):
                chip.fact = f  # the same words; its widget and tip may be newer
            return
        self._shown = shown
        for chip in self.chips:
            self._flow.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self.chips = []
        for i, f in enumerate(items):
            chip = FactChip(f, self)
            chip.clicked.connect(lambda _=False, c=chip: self.opened.emit(c.fact))
            self._flow.insert_widget(i, chip)
            chip.show()
            self.chips.append(chip)
        self._fit_height()
        self.rebuilt.emit()

    def _fit_height(self) -> None:
        """As tall as the rows the chips take at the width the row has: a box beside Parse and Attach is otherwise asked
        its height for a narrower width, and stands taller than its one row."""
        if self.width() > 0:
            self.setFixedHeight(self._flow.heightForWidth(self.width()))
        self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self._flow.heightForWidth(self.width()) != self.height():
            self._fit_height()

    def chip_for(self, key: str) -> FactChip | None:
        return next((c for c in self.chips if c.fact.key == key), None)

    def set_more(self, on: bool) -> None:
        """Check or uncheck More fields without saying so."""
        self.more_chip.blockSignals(True)
        self.more_chip.setChecked(on)
        self.more_chip.blockSignals(False)


def home_of(widget: QWidget, layout: QLayout) -> tuple[QLayout, tuple[int, ...]] | None:
    """Where ``widget`` sits in ``layout`` or a layout inside it: the layout, and its cell (row, column, rows, columns) in a
    grid, or its index in a row or column."""
    i = layout.indexOf(widget)
    if i >= 0:
        if isinstance(layout, QGridLayout):
            return layout, tuple(layout.getItemPosition(i))
        return layout, (i,)
    for n in range(layout.count()):
        inner = layout.itemAt(n).layout()
        if inner is not None:
            found = home_of(widget, inner)
            if found is not None:
                return found
    return None


def put_back(widget: QWidget, home: tuple[QLayout, tuple[int, ...]]) -> None:
    """Put a widget back in its cell."""
    layout, cell = home
    owner = layout.parentWidget()
    widget.setParent(owner)
    if isinstance(layout, QGridLayout):
        layout.addWidget(widget, *cell)
    elif isinstance(layout, QBoxLayout):
        layout.insertWidget(cell[0], widget)
    widget.show()


class FactPopover(QFrame):
    """A field opened from its chip while the fields are shut: the field's own widget, lent and put back. A child of the
    capture window, not a window of its own, so nothing nests two popups and Windows is asked for nothing. It closes on Esc,
    on Enter in a one-line box, on a press outside it, when the keyboard leaves it, and before anything reads its field's
    block."""

    closed = Signal(str)  # the fact's key

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("factPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.window_ = window
        self.wrapper: QWidget | None = None
        self.home: tuple[QLayout, tuple[int, ...]] | None = None
        self.chip: FactChip | None = None
        self.key = ""
        self.focus_to: QWidget | None = None
        self.hide()

    def event(self, e: QEvent) -> bool:
        """A field that grows (a picker's list of suggestions) grows the popover with it."""
        done = super().event(e)
        if e.type() == QEvent.Type.LayoutRequest and self.wrapper is not None and self.chip is not None:
            self.place()
        return done

    def is_open(self) -> bool:
        return self.wrapper is not None

    def open_for(self, chip: FactChip, wrapper: QWidget, home: tuple[QLayout, tuple[int, ...]], focus: QWidget | None) -> None:
        """Lend ``wrapper`` (a field and its label) to the popover, under ``chip``, and give ``focus`` the keyboard."""
        self.close_it(back=False)
        layout, _cell = home
        layout.removeWidget(wrapper)
        wrapper.setParent(self)
        self.lay.addWidget(wrapper)
        wrapper.show()
        self.wrapper, self.home, self.chip, self.key = wrapper, home, chip, chip.fact.key
        self.place()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        target = focus if focus is not None and focus.isVisibleTo(self) else wrapper
        target.setFocus(Qt.FocusReason.PopupFocusReason)

    def place(self) -> None:
        """At least 240 px wide, at most the window's width less 24; under its chip, or over it when there's no room, and
        inside the window."""
        win = self.window_
        self.adjustSize()
        width = max(240, min(self.sizeHint().width(), win.width() - 24))
        self.resize(width, self.sizeHint().height())
        assert self.chip is not None
        below = self.chip.mapTo(win, QPoint(0, self.chip.height() + 4))
        above = self.chip.mapTo(win, QPoint(0, -4 - self.height()))
        y = below.y() if below.y() + self.height() <= win.height() - 8 or above.y() < 8 else above.y()
        x = max(12, min(below.x(), win.width() - width - 12))
        self.move(x, max(8, y))

    def close_it(self, back: bool = True) -> None:
        """Put the field back where it was and hide; ``back`` gives the keyboard to the chip that opened it."""
        if self.wrapper is None:
            return
        QApplication.instance().removeEventFilter(self)
        wrapper, home, key, chip = self.wrapper, self.home, self.key, self.chip
        self.wrapper = self.home = self.chip = None
        self.key = ""
        self.lay.removeWidget(wrapper)
        assert home is not None
        put_back(wrapper, home)
        self.hide()
        self.closed.emit(key)
        if back and chip is not None:
            self.focus_to = chip
            self.closed_focus()

    def closed_focus(self) -> None:
        """Hand the keyboard back to the chip, or its new self if the row was rebuilt."""
        target = self.focus_to
        self.focus_to = None
        if target is None:
            return
        try:
            row = target.parentWidget()
            fresh = row.chip_for(target.fact.key) if isinstance(row, FactChips) else None
        except RuntimeError:  # the chip went with a rebuild
            fresh = None
        try:
            (fresh or target).setFocus(Qt.FocusReason.PopupFocusReason)
        except RuntimeError:
            pass

    def _inside(self, obj: QObject) -> bool:
        return isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        """While open: Esc, and Enter in a one-line box, close it; a press elsewhere in the window, or the keyboard moving
        out of it, closes it. A list or a menu the field opens is a window of its own, or inside the popover, and is let be."""
        if self.wrapper is None or not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind == QEvent.Type.KeyPress and self._inside(watched):
            key = event.key()
            if key == Qt.Key.Key_Escape:
                if isinstance(watched, QLineEdit) and _in_chip_picker(watched) and _suggesting(watched):
                    return False  # the picker's list closes first
                self.close_it()
                return True
            if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and isinstance(watched, QLineEdit) and not _in_chip_picker(watched)):
                self.close_it()
                return True
        elif kind == QEvent.Type.MouseButtonPress:
            if watched.window() is self.window_ and not self._inside(watched) and not _in_chip(watched, self.chip):
                self.close_it(back=False)
        elif kind == QEvent.Type.FocusIn and watched.window() is self.window_ and not self._inside(watched):
            if not _in_chip(watched, self.chip):
                self.close_it(back=False)
        return False


def _in_chip_picker(widget: QWidget) -> bool:
    w: QWidget | None = widget
    while w is not None:
        if isinstance(w, ChipPicker):
            return True
        w = w.parentWidget()
    return False


def _suggesting(widget: QWidget) -> bool:
    w: QWidget | None = widget
    while w is not None and not isinstance(w, ChipPicker):
        w = w.parentWidget()
    return isinstance(w, ChipPicker) and w.list.isVisible()


def _in_chip(widget: QWidget, chip: QWidget | None) -> bool:
    return chip is not None and (widget is chip or chip.isAncestorOf(widget))


#: For ``CaptureWindow``: the wrapper of a field (its label and box) under one of the window's blocks.
def wrapper_of(widget: QWidget, blocks: tuple[QWidget, ...]) -> QWidget | None:
    w: QWidget | None = widget
    while w is not None and w.parentWidget() is not None:
        if w.parentWidget() in blocks:
            return w
        w = w.parentWidget()
    return None


def chain_focus(before: QWidget, chips: list[QWidget], after: QWidget) -> None:
    """``before``, each chip, then ``after``, in the window's Tab order."""
    last = before
    for chip in chips:
        QWidget.setTabOrder(last, chip)
        last = chip
    QWidget.setTabOrder(last, after)



class KeyedButton(QPushButton):
    """A button that shows its key at its right end, such as Save's "Ctrl Enter" (release 5.188): a label laid over the
    button, which lets the mouse through; the style sheet's right padding (``keyed``) makes its room."""

    def __init__(self, text: str, key: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("keyed", True)
        self.key_label = QLabel(key, self)
        self.key_label.setObjectName("saveKey")
        self.key_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.key_label.adjustSize()
        hint = self.key_label.sizeHint()
        self.key_label.setGeometry(self.width() - hint.width() - 10, (self.height() - hint.height()) // 2, hint.width(), hint.height())
