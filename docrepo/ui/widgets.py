"""Small widgets the capture window is built from: date fields, hours fields, chip pickers and "i" buttons. Also the
browse tool's forms' base, ``FormDialog``."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    QWidgetItem,
)

from docrepo.model import Model
from docrepo.ui.help_text import HELP


SAVE_KEYS = ("Ctrl+Return", "Ctrl+Enter")


class FormDialog(QDialog):
    """A browse tool form. Ctrl+Enter saves it and closes it, as in the capture window (mods log round 2, M0035); Esc,
    Cancel or the window's close button closes it, asking first when something was changed.

    A form overrides ``save`` (check, then ``accept``) and, when its boxes aren't enough to tell, ``snapshot``, and calls
    ``mark_clean`` once it's filled. ``ask_discard`` is replaceable, so tests don't open a message box.
    """

    KEYS_HINT = "Ctrl+Enter saves. Esc closes, asking first if you've changed something."

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        for keys in SAVE_KEYS:
            QShortcut(QKeySequence(keys), self, self.save)
        self._clean: Any = None
        self.ask_discard: Callable[[], bool] = lambda: QMessageBox.question(
            self, self.windowTitle(), "Close without saving your changes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def save(self) -> None:
        self.accept()

    def snapshot(self) -> Any:
        """What's in the form's boxes, to tell whether anything changed since ``mark_clean``."""
        out: list[Any] = []
        for w in self.findChildren(QWidget):
            if isinstance(w, QLineEdit):
                out.append(w.text())
            elif isinstance(w, QPlainTextEdit):
                out.append(w.toPlainText())
            elif isinstance(w, QComboBox):
                out.append(w.currentIndex())
            elif isinstance(w, QAbstractButton) and w.isCheckable():
                out.append(w.isChecked())
        return out

    def mark_clean(self) -> None:
        self._clean = self.snapshot()

    def changed(self) -> bool:
        return self.snapshot() != self._clean

    def reject(self) -> None:
        if self.changed() and not self.ask_discard():
            return
        super().reject()


def set_filled(widget: QWidget, filled: bool) -> None:
    """Mark a field Parse and populate filled; the style sheet highlights it until it's edited."""
    widget.setProperty("filled", filled)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FlowLayout(QLayout):
    """Lays its items out left to right, wrapping onto new lines, like words in a paragraph."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt's name
        self._items.append(item)

    def insert_widget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


class InfoButton(QToolButton):
    """The small "i" button that shows what a field is for."""

    def __init__(self, key: str, note: QLabel) -> None:
        super().__init__()
        self.setText("i")
        self.setObjectName("info")
        self.setCheckable(True)
        self.setToolTip("What is this?")
        self.setAccessibleName("About this field")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        note.setText(HELP.get(key, "").replace("\n\n", "<br><br>"))
        note.setWordWrap(True)
        note.setObjectName("tip")
        note.hide()
        self.toggled.connect(note.setVisible)


def field(label: str, widget: QWidget | None, help_key: str | None = None, sub: str = "") -> QWidget:
    """A labelled field: its label (with an "i" button when there's help), the help note, then the widget."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    row = QHBoxLayout()
    row.setSpacing(6)
    text = QLabel(f"{label} <span style='color:#87919c'>{sub}</span>" if sub else label)
    text.setObjectName("fieldLabel")
    if widget is not None:
        text.setBuddy(widget)
    row.addWidget(text)
    note = QLabel()
    if help_key:
        row.addWidget(InfoButton(help_key, note))
    row.addStretch()
    layout.addLayout(row)
    if help_key:
        layout.addWidget(note)
    if widget is not None:
        layout.addWidget(widget)
    box.setProperty("label", text)
    return box


class DateField(QWidget):
    """A date as YYYY-MM-DD, typed or picked from a calendar. Empty means none."""

    edited = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.line = QLineEdit()
        self.line.setPlaceholderText("YYYY-MM-DD")
        self.line.textEdited.connect(self._typed)
        button = QToolButton()
        button.setText("▾")
        button.setToolTip("Pick a date")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.clicked.connect(self._picked)
        action = QWidgetAction(menu)
        action.setDefaultWidget(self.calendar)
        menu.addAction(action)
        menu.addAction("No date", lambda: self._set_by_user(None))
        menu.aboutToShow.connect(self._sync_calendar)
        button.setMenu(menu)
        self._menu = menu
        layout.addWidget(self.line, 1)
        layout.addWidget(button)

    def value(self) -> str | None:
        return self.line.text().strip() or None

    def is_valid(self) -> bool:
        text = self.line.text().strip()
        if not text:
            return True
        try:
            return len(text) == 10 and bool(date.fromisoformat(text))
        except ValueError:
            return False

    def set_value(self, value: str | None) -> None:
        self.line.setText(value or "")

    def _typed(self) -> None:
        set_filled(self.line, False)
        self.edited.emit()

    def _set_by_user(self, value: str | None) -> None:
        self.set_value(value)
        self._typed()

    def _picked(self, day: QDate) -> None:
        self._menu.close()
        self._set_by_user(day.toString("yyyy-MM-dd"))

    def _sync_calendar(self) -> None:
        if self.is_valid() and self.value():
            self.calendar.setSelectedDate(QDate.fromString(self.value(), "yyyy-MM-dd"))


class HoursField(QLineEdit):
    """Hours: a number such as 6 or 2.5, or empty."""

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("Hours")
        self.textEdited.connect(lambda: set_filled(self, False))

    def value(self) -> float | None:
        text = self.text().strip()
        return float(text) if text else None

    def is_valid(self) -> bool:
        try:
            v = self.value()
            return v is None or v >= 0
        except ValueError:
            return False

    def set_value(self, value: float | str | None) -> None:
        if value is None or value == "":
            self.setText("")
        else:
            number = float(value)
            self.setText(str(int(number)) if number.is_integer() else str(number))


@dataclass(frozen=True)
class Option:
    """A choice in a chip picker. ``value`` is an ID, or a name for something new."""

    value: str
    label: str
    sub: str = ""
    new: bool = False


@dataclass
class Chip:
    value: str
    label: str
    new: bool = False
    filled: bool = False


def label_options(model: Model, text: str, picked: list[str]) -> list[Option]:
    """The labels a label picker suggests for what's typed: active ones not picked yet, by name."""
    q = text.strip().lower()
    return [Option(lb.name, lb.name, ", ".join(lb.keywords)) for lb in model.active_labels()
            if lb.name not in picked and (not q or q in lb.name.lower())][:7]


def people_options(model: Model, me: str | None, text: str, picked: list[str]) -> list[Option]:
    """The people a people picker suggests for what's typed: active ones not picked yet, by name or alias."""
    q = text.strip().lower()
    out = []
    for p in model.active_people():
        names = [p.name, *p.aliases]
        if p.id not in picked and (not q or any(q in n.lower() for n in names)):
            out.append(Option(p.id, p.name + (" (me)" if p.id == me else ""), ", ".join(p.aliases)))
    return out[:7]


class ChipPicker(QWidget):
    """Picks several labels, people or agenda targets: chips for those picked, and a box to search for more.

    ``options(text, picked_values)`` gives the choices for what's typed. With ``create_text`` set, typing
    something that isn't there offers to create it (as "new", made when the capture is saved).
    """

    changed = Signal()

    def __init__(self, options: Callable[[str, list[str]], list[Option]], placeholder: str, create_text: str | None = None) -> None:
        super().__init__()
        self._options = options
        self._create_text = create_text
        self._chips: list[Chip] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.box = QWidget()
        self.box.setObjectName("chips")
        self._flow = FlowLayout(self.box)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrame(False)
        self.edit.setMinimumWidth(max(120, self.edit.fontMetrics().horizontalAdvance(placeholder) + 24))  # the whole hint shows
        self.edit.textEdited.connect(self._suggest)
        self.edit.installEventFilter(self)
        self._flow.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("suggestions")
        self.list.setMaximumHeight(150)
        self.list.hide()
        self.list.itemClicked.connect(self._pick_item)
        layout.addWidget(self.box)
        layout.addWidget(self.list)
        self.box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    # ---- the chips ----
    def chips(self) -> list[Chip]:
        return list(self._chips)

    def values(self) -> list[str]:
        return [c.value for c in self._chips]

    def set_chips(self, chips: list[Chip]) -> None:
        self._chips = list(chips)
        self._render()

    def add(self, chip: Chip) -> None:
        if any(c.value.lower() == chip.value.lower() and c.new == chip.new for c in self._chips):
            return
        for c in self._chips:
            c.filled = False
        self._chips.append(chip)
        self._render()
        self.changed.emit()

    def remove(self, index: int) -> None:
        del self._chips[index]
        for c in self._chips:
            c.filled = False
        self._render()
        self.changed.emit()

    def _render(self) -> None:
        while self._flow.count() > 1:
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for i, chip in enumerate(self._chips):
            button = QToolButton()
            button.setText(f"{chip.label}{'  new' if chip.new else ''}  ×")
            button.setObjectName("chip")
            button.setProperty("filled", chip.filled)
            button.setToolTip(f"Remove {chip.label}")
            button.clicked.connect(lambda _=False, i=i: self.remove(i))
            self._flow.insert_widget(i, button)  # before the search box, which stays last
            button.show()
        self.box.updateGeometry()

    # ---- suggestions ----
    def _suggest(self) -> None:
        text = self.edit.text()
        options = self._options(text, self.values())
        query = text.strip()
        exact = any(o.label.lower() == query.lower() for o in options)
        if self._create_text and query and not exact:
            options.append(Option(query, self._create_text.format(query), "Created when you save", new=True))
        self.list.clear()
        for o in options:
            item = QListWidgetItem(f"{o.label}    {o.sub}" if o.sub else o.label)
            item.setData(Qt.ItemDataRole.UserRole, o)
            self.list.addItem(item)
        if options:
            self.list.setCurrentRow(0)
        self.list.setVisible(bool(options) and self.edit.hasFocus())

    def _pick_item(self, item: QListWidgetItem) -> None:
        option: Option = item.data(Qt.ItemDataRole.UserRole)
        self.edit.clear()
        self.list.hide()
        self.add(Chip(option.value, option.value if option.new else option.label.split("    ")[0], option.new))
        self.edit.setFocus()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if watched is self.edit:
            if event.type() == event.Type.FocusIn:
                self._suggest()
            elif event.type() == event.Type.FocusOut:
                if not self.list.underMouse():
                    self.list.hide()
            elif event.type() == event.Type.KeyPress and isinstance(event, QKeyEvent):
                key = event.key()
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.list.isVisible():
                    row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                    self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if self.list.isVisible() and self.list.currentItem():
                        self._pick_item(self.list.currentItem())
                        return True
                if key == Qt.Key.Key_Escape and self.list.isVisible():
                    self.list.hide()
                    return True
                if key == Qt.Key.Key_Backspace and not self.edit.text() and self._chips:
                    self.remove(len(self._chips) - 1)
                    return True
        return super().eventFilter(watched, event)


class _StayOpenMenu(QMenu):
    """A menu whose tick boxes can be ticked one after another without it closing."""

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        action = self.activeAction()
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and action is not None and action.isCheckable():
            action.trigger()
            return
        super().keyPressEvent(event)


class CheckMenuButton(QPushButton):
    """A filter button whose menu has a tick box for each choice (mods log round 1, M0018). ``chosen`` sends the ticked
    values once the menu closes, so the list behind it is drawn again only then."""

    chosen = Signal(list)

    def __init__(self, noun: str, empty: str, choices: list[tuple[str, str]], picked: list[str]) -> None:
        super().__init__()
        self.noun, self.empty = noun, empty
        self.picks = _StayOpenMenu(self)
        clear = self.picks.addAction(empty)
        clear.triggered.connect(lambda: [a.setChecked(False) for a in self.choices])
        self.picks.addSeparator()
        self.choices = []
        for label, value in choices:
            action = self.picks.addAction(label)
            action.setCheckable(True)
            action.setChecked(value in picked)
            action.setData(value)
            action.toggled.connect(lambda _=False: self._name())
            self.choices.append(action)
        self.setMenu(self.picks)
        self._shown = self.values()
        self.picks.aboutToHide.connect(lambda: QTimer.singleShot(0, self._closed))  # after the action that closed it
        self._name()

    def values(self) -> list[str]:
        return [a.data() for a in self.choices if a.isChecked()]

    def _name(self) -> None:
        names = [a.text() for a in self.choices if a.isChecked()]
        shown = self.empty if not names else ", ".join(names) if len(names) <= 2 else f"{names[0]} and {len(names) - 1} more"
        self.setText(f"{self.noun}: {shown}")
        self.setToolTip(", ".join(names) if len(names) > 2 else "")
        # Room for the text and the menu's arrow: the stylesheet's padding isn't in the button's own size.
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance(self.text()) + 36)

    def _closed(self) -> None:
        if self.values() != self._shown:
            self._shown = self.values()
            self.chosen.emit(self._shown)
