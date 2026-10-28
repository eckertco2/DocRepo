"""Quick edit (mods log round 4, M0067, item 55, decisions 138, 139, 143 and 145; release 5.30).

A small window for planning one task, opened by double-clicking it on the timeline, about the pinned capture window's
size, on top of other windows, beside the bar; its top line moves it. From the top:

- the task's title, Open task and ✕, and its path;
- a one-line box Parse and populate reads as you type ("3 hours a week, Tom leads, Mike to help, due 20 Nov"), with a
  chip for each thing it read: a click on one leaves its field as it was, and again fills it;
- Start, Due and Deadline, the deadline's description and Repeats, and the line naming a plant event they fall in;
- the lead and the assignees, each with their hours, and the total;
- Plant event, a line for a problem, and Save.

Fields the box filled are tinted, as Parse and populate's are in the capture window, until they're changed by hand.
Ctrl+Enter saves, through ``edits.edit_task``, as Edit task does: status log lines as "Browse tool", no capture. Esc (or
✕) closes, asking once first when something changed. What's typed in the box is never kept. ``docrepo.planning`` has the
rules; this module only draws them.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import edits, planning
from docrepo.db import RECURRENCES
from docrepo.model import Model
from docrepo.ui import tokens
from docrepo.ui.context import AppContext
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.look import LOOK, tip
from docrepo.ui.style import style_sheet
from docrepo.ui.task_picker import path_text
from docrepo.ui.task_forms import KeyDatesEditor, key_date_rows
from docrepo.ui.widgets import DateField, FlowLayout, HoursField, set_filled

#: Its width (decision 145: about the pinned capture window's size, a little larger for the chips and the during line).
WIDTH = 352
#: The top line's height: dragging it, outside its buttons, moves the window.
HEAD = 32
NO_REPEAT = "Doesn't repeat"


def _extra_style() -> str:
    """Its own rules, beside the look's style sheet: the frame, the top line and the chips' states."""
    if LOOK.classic:
        return """
QWidget#quickEdit { background: #ffffff; border: 1px solid #b8c1cb; }
QWidget#qeHead { background: #f4f6f8; border-bottom: 1px solid #d6dce3; }
QLabel#qeTitle { font-weight: 600; color: #1a1f25; }
QLabel#qeKind { color: #5a6571; }
QToolButton#chip[off="true"] { color: #5a6571; background: #ffffff; text-decoration: line-through; }
QToolButton#chip[why="true"] { color: #5a6571; background: #ffffff; border-style: dashed; }
"""
    c = tokens.colour
    return f"""
QWidget#quickEdit {{ background: {c("content")}; border: 1px solid {c("stroke_strong")}; }}
QWidget#qeHead {{ background: {c("base")}; border-bottom: 1px solid {c("stroke")}; }}
QLabel#qeKind {{ color: {c("text2")}; font-size: {tokens.CAPTION}pt; }}
QLabel#qeTitle {{ font-weight: 600; color: {c("text")}; }}
QLabel#qeField {{ color: {c("text2")}; font-size: {tokens.CAPTION}pt; }}
QWidget#quickEdit QLineEdit {{ min-height: 0; padding: 2px 6px; }}
QWidget#quickEdit QComboBox {{ min-height: 0; padding: 1px 6px; }}
QToolButton#chip[off="true"] {{ color: {c("text2")}; background: {c("content")}; text-decoration: line-through; }}
QToolButton#chip[why="true"] {{ color: {c("text2")}; background: {c("content")}; border-style: dashed; }}
"""


class PeopleRow(QWidget):
    """The lead or the assignees: a chip for each (a click takes them off) and a small + with a menu of the others."""

    changed = Signal()

    def __init__(self, model: Model, role: str) -> None:
        super().__init__()
        self.model = model
        self.role = role
        self.ids: list[str] = []
        self._flow = FlowLayout(self, spacing=3)
        self.add_button = QToolButton(objectName="chip")
        self.add_button.setText("+")
        self.add_button.setAccessibleName("Add a lead" if role == "leads" else "Add an assignee")
        self.add_button.setToolTip(self.add_button.accessibleName())
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.add_menu = QMenu(self.add_button)
        self.add_button.setMenu(self.add_menu)
        self._flow.addWidget(self.add_button)

    def set_ids(self, ids: list[str], filled: bool) -> None:
        self.ids = list(ids)
        while self._flow.count() > 1:
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().hide()  # gone at once, not left showing until Qt deletes it
                item.widget().deleteLater()
        for i, p in enumerate(self.ids):
            b = QToolButton(objectName="chip")
            b.setText(f"{self.model.person_name(p)}  ×")
            b.setProperty("filled", filled)
            b.setToolTip(f"Take {self.model.person_name(p)} off")
            b.clicked.connect(lambda _=False, p=p: self._removed(p))
            self._flow.insert_widget(i, b)
            b.show()
        self.add_menu.clear()
        for person in self.model.active_people():
            if person.id not in self.ids:
                self.add_menu.addAction(person.name, lambda p=person.id: self._added(p))
        self.updateGeometry()

    def _added(self, p: str) -> None:
        self.ids.append(p)
        self.changed.emit()

    def _removed(self, p: str) -> None:
        self.ids = [x for x in self.ids if x != p]
        self.changed.emit()


class QuickEdit(QWidget):
    """Quick edit for one task. ``saved`` sends its ID after a save; ``open_task`` asks for its task page."""

    saved = Signal(str)
    open_task = Signal(str)

    def __init__(self, ctx: AppContext, task_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx = ctx
        self.task_id = task_id
        self.model = ctx.model()
        self.task = self.model.task(task_id)
        self.people = ctx.parse_people(self.model)
        self.base = planning.values_of(self.task, key_date_rows(self.model, task_id))  # the fields without the box
        self.orig = self.base.copy()
        self.off: set[str] = set()  # the fields the box doesn't fill: unticked, or changed by hand
        self.reading = planning.Reading()
        self.warned = False
        self._drag_from = None
        self._setting = False
        self.setObjectName("quickEdit")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(f"Quick edit: {self.task.title}")
        self.setStyleSheet(style_sheet() + _extra_style())
        self.setFixedWidth(WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # ---- the top line: what it is, the title, Open task, ✕ ----
        head = QWidget(objectName="qeHead")
        head.setFixedHeight(HEAD)
        head.setCursor(Qt.CursorShape.SizeAllCursor)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 0, 4, 0)
        hl.setSpacing(6)
        hl.addWidget(QLabel("Quick edit", objectName="qeKind"))
        self.title = QLabel(objectName="qeTitle")
        self.title.setToolTip(self.task.title)
        hl.addWidget(self.title, 1)
        open_button = QPushButton("Open task", objectName="link")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._open)
        hl.addWidget(open_button)
        close = QToolButton(objectName="iconButton")
        close.setIcon(icon("close"))
        close.setIconSize(icon_size(16))
        close.setFixedSize(24, 24)
        close.setAccessibleName("Close")
        tip(close, "Close; asks first when something changed", "Esc")
        close.clicked.connect(self.escape)
        hl.addWidget(close)
        outer.addWidget(head)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(6)
        outer.addWidget(body)
        self.path = QLabel(objectName="hint")
        lay.addWidget(self.path)
        # ---- the box, and what it read ----
        self.box = QLineEdit()
        self.box.setPlaceholderText("Type to fill: 3 hours a week, Tom leads, Mike to help, due 20 Nov")
        self.box.setAccessibleName("Type to fill the fields")
        self.box.setToolTip("Read as you type, as Parse and populate reads a capture: dates, how often it repeats, hours "
                            "(a rate becomes a total over Start to Due), the lead and the assignees, and \"plant event\". "
                            "What it reads fills the fields below. It isn't kept.")
        self.box.textEdited.connect(lambda _: self._changed_by_user(None))
        lay.addWidget(self.box)
        self.chips = QWidget()
        self._chip_flow = FlowLayout(self.chips, spacing=3)
        lay.addWidget(self.chips)
        # ---- the dates ----
        # Two to a row, so a date shows whole in words: Start and Due, then Deadline and Repeats.
        dates = QGridLayout()
        dates.setHorizontalSpacing(6)
        dates.setVerticalSpacing(1)
        self.dates: dict[str, DateField] = {}
        for i, key in enumerate(("start", "due", "deadline")):
            row_at, col = 2 * (i // 2), i % 2
            dates.addWidget(QLabel(planning.NAMES[key], objectName="qeField"), row_at, col)
            f = DateField()
            f.setMaximumWidth(16777215)
            f.line.setAccessibleName(planning.NAMES[key])
            f.edited.connect(lambda key=key: self._field_edited(key))
            dates.addWidget(f, row_at + 1, col)
            self.dates[key] = f
        dates.addWidget(QLabel("Repeats", objectName="qeField"), 2, 1)
        self.repeat = QComboBox()
        self.repeat.setAccessibleName("Repeats")
        self.repeat.addItems([NO_REPEAT, *RECURRENCES])
        self.repeat.activated.connect(lambda _: self._field_edited("recurrence"))
        dates.addWidget(self.repeat, 3, 1)
        dates.setColumnStretch(0, 1)
        dates.setColumnStretch(1, 1)
        lay.addLayout(dates)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Deadline description, such as Boiler restart")
        self.desc.setAccessibleName("Deadline description")
        self.desc.textEdited.connect(lambda _: self._field_edited("deadline_desc"))
        lay.addWidget(self.desc)
        self.during = QLabel(objectName="hint")
        self.during.setWordWrap(True)
        lay.addWidget(self.during)
        # ---- its key dates (release 5.31, the key dates plan): the same rows as Edit task's, compact ----
        self.key_dates = KeyDatesEditor(self.base.key_dates, compact=True)
        self.key_dates.add_button.setText("+ Key date")
        self.key_dates.empty.hide()
        self.key_dates.changed.connect(self._key_dates_edited)
        lay.addWidget(self.key_dates)
        # ---- the people and their hours ----
        who = QGridLayout()
        who.setHorizontalSpacing(4)
        who.setVerticalSpacing(4)
        self.rows: dict[str, PeopleRow] = {}
        self.hours: dict[str, HoursField] = {}
        for r, (key, hkey, label, unit) in enumerate((("leads", "lead_hours", "Lead", "h"), ("assignees", "assignee_hours", "Assignees", "h each"))):
            who.addWidget(QLabel(label, objectName="qeField"), r, 0, Qt.AlignmentFlag.AlignTop)
            people_row = PeopleRow(self.model, key)
            people_row.changed.connect(lambda key=key: self._field_edited(key))
            who.addWidget(people_row, r, 1)
            h = HoursField()
            h.setPlaceholderText("")
            h.setFixedWidth(66)  # room for "26.5" beside the filled field's wand
            h.setAccessibleName(planning.NAMES[hkey])
            h.textEdited.connect(lambda _, hkey=hkey: self._field_edited(hkey))
            who.addWidget(h, r, 2, Qt.AlignmentFlag.AlignTop)
            who.addWidget(QLabel(unit, objectName="qeField"), r, 3, Qt.AlignmentFlag.AlignTop)
            self.rows[key], self.hours[hkey] = people_row, h
        who.setColumnStretch(1, 1)
        lay.addLayout(who)
        self.total = QLabel(objectName="hint")
        lay.addWidget(self.total)
        # ---- Plant event, a problem, Save ----
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.plant_event = QCheckBox("⚑ Plant event")
        self.plant_event.setToolTip("An outage or turnaround: a band down the whole timeline, and its own lane at the top")
        self.plant_event.clicked.connect(lambda _: self._field_edited("plant_event"))
        foot.addWidget(self.plant_event)
        self.message = QLabel(objectName="error")
        self.message.setWordWrap(True)
        self.message.hide()
        foot.addWidget(self.message, 1)
        foot.addStretch()
        self.save_button = QPushButton("Save", objectName="primary")
        tip(self.save_button, "Save the changes to the task, with a line for each in its status log", "Ctrl+Enter")
        self.save_button.clicked.connect(self.save)
        foot.addWidget(self.save_button)
        lay.addLayout(foot)
        for keys, handler in (("Ctrl+Return", self.save), ("Ctrl+Enter", self.save), ("Esc", self.escape)):
            QShortcut(QKeySequence(keys), self, handler, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._refresh()

    # ---- what it shows ----
    def values(self) -> planning.Values:
        """The fields as they stand: the box's values over the rest."""
        return planning.shown(self.base, self.reading)

    def changed(self) -> bool:
        return self.values() != self.orig or any(not h.is_valid() for h in self.hours.values())

    def _refresh(self, skip: str | None = None) -> None:
        """Read the box again (its rates depend on the dates) and draw every field but ``skip``, the one being typed in."""
        self.reading = planning.read(self.box.text(), self.base, self.task, self.people, self.ctx.now().date(),
                                     self.ctx.settings.event_words, self.off)
        self._draw(skip)

    def _draw(self, skip: str | None) -> None:
        self._setting = True
        v, filled = self.values(), set(self.reading.fills)
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(self.task.title, Qt.TextElideMode.ElideRight, WIDTH - 190))
        path = path_text(self.model, self.task_id) or "A top-level task"
        self.path.setText(self.path.fontMetrics().elidedText(path, Qt.TextElideMode.ElideMiddle, WIDTH - 24))
        self.path.setToolTip(path)
        for key, f in self.dates.items():
            if key != skip and (f.value() or "") != getattr(v, key):
                f.set_value(getattr(v, key) or None)
            set_filled(f.line, key in filled)
        if skip != "deadline_desc" and self.desc.text() != v.deadline_desc:
            self.desc.setText(v.deadline_desc)
        set_filled(self.desc, "deadline_desc" in filled)
        self.repeat.setCurrentIndex(self.repeat.findText(v.recurrence) if v.recurrence else 0)
        set_filled(self.repeat, "recurrence" in filled)
        for key, people_row in self.rows.items():
            people_row.set_ids(getattr(v, key), key in filled)
        for key, h in self.hours.items():
            if key != skip:
                h.set_value(getattr(v, key))
            set_filled(h, key in filled)
        self.plant_event.setChecked(v.plant_event)
        set_filled(self.plant_event, "plant_event" in filled)
        self._draw_chips()
        during = planning.during(self.model, v, self.ctx.now().date(), self.task_id)
        self.during.setText(f"⚑ {during}" if during else "")
        self.during.setVisible(bool(during))
        self.total.setText(planning.total_text(v, self.task))
        self._setting = False
        self._fit()

    def _fit(self) -> None:
        """As tall as what it holds: its rows of chips wrap, so its height follows its width."""
        lay = self.layout()
        lay.activate()
        self.setFixedHeight(lay.totalHeightForWidth(WIDTH) if lay.hasHeightForWidth() else lay.totalSizeHint().height())

    def _draw_chips(self) -> None:
        while self._chip_flow.count():
            item = self._chip_flow.takeAt(0)
            if item and item.widget():
                item.widget().hide()  # gone at once, not left showing until Qt deletes it
                item.widget().deleteLater()
        for chip in self.reading.chips:
            b = QToolButton(objectName="chip")
            b.setText(chip.text() + ("" if chip.why else "  ↺" if chip.off else "  ×"))
            b.setToolTip(chip.tip())
            b.setProperty("filled", not chip.off and not chip.why)
            b.setProperty("off", chip.off)
            b.setProperty("why", bool(chip.why))
            b.setAccessibleName(("Fill " if chip.off else "Don't fill ") + chip.field if not chip.why else chip.text())
            if chip.why:
                b.setEnabled(False)
            else:
                b.clicked.connect(lambda _=False, key=chip.key: self.toggle(key))
            self._chip_flow.addWidget(b)
            b.show()
        self.chips.setVisible(bool(self.reading.chips))

    # ---- changes ----
    def _changed_by_user(self, skip: str | None) -> None:
        self.warned = False
        self.message.setText("")
        self.message.hide()
        self._refresh(skip)

    def _field_edited(self, key: str) -> None:
        """A field changed by hand: it keeps what was put in it, and the box no longer fills it."""
        if self._setting:
            return
        if key in self.dates:
            setattr(self.base, key, self.dates[key].value() or "")
        elif key == "deadline_desc":
            self.base.deadline_desc = self.desc.text()
        elif key == "recurrence":
            self.base.recurrence = "" if self.repeat.currentIndex() == 0 else self.repeat.currentText()
        elif key in self.rows:
            setattr(self.base, key, list(self.rows[key].ids))
        elif key in self.hours:
            h = self.hours[key]
            if not h.is_valid():
                self.off.add(key)
                return  # kept as typed; Save says what's wrong
            setattr(self.base, key, h.value())
        elif key == "plant_event":
            self.base.plant_event = self.plant_event.isChecked()
        self.off.add(key)
        self._changed_by_user(key if key not in self.rows else None)

    def _key_dates_edited(self) -> None:
        """A key date added, changed, moved or taken off: kept as it stands; Save says what's wrong with one."""
        if self._setting:
            return
        self.key_dates.empty.hide()  # the window keeps its room: Edit task's sentence about key dates isn't shown here
        self.base.key_dates = self.key_dates.rows()
        self._changed_by_user(None)

    def toggle(self, key: str) -> None:
        """A chip's click: its field no longer filled by the box, or filled again."""
        if key in self.off:
            self.off.discard(key)
        else:
            self.off.add(key)
        self._changed_by_user(None)

    # ---- saving and closing ----
    def save(self) -> None:
        """Ctrl+Enter: the changed fields saved as Edit task saves them, each a line in the status log."""
        for key, h in self.hours.items():
            if not h.is_valid():
                return self._say(f"{planning.NAMES[key]} isn't a number of hours.")
        v = self.values()
        problem = planning.problem(v) or self.key_dates.problem()
        if problem:
            return self._say(problem)
        if v == self.orig:
            self.ctx.notify("Quick edit", f"{self.task.title}: nothing changed.")
            self.hide()
            return None
        try:
            out = edits.edit_task(self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, self.task_id, self.ctx.now(),
                                  **planning.edit_values(v))
        except ValueError as e:
            return self._say(str(e))
        self.ctx.notify("Quick edit", f"{self.task.title}: {out.message}" + (" " + " ".join(out.problems) if out.problems else ""))
        self.hide()
        self.saved.emit(self.task_id)
        return None

    def _say(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self._fit()

    def escape(self) -> None:
        """Esc or ✕: closes, asking once first when something changed."""
        if self.changed() and not self.warned:
            self.warned = True
            self._say("You've changed something. Esc again closes without saving.")
            return
        self.hide()

    def _open(self) -> None:
        self.hide()
        self.open_task.emit(self.task_id)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name: Alt+F4 asks as Esc does
        if self.changed() and not self.warned:
            event.ignore()
            self.escape()
            return
        super().closeEvent(event)

    # ---- placing and moving ----
    def show_near(self, rect: QRect) -> None:
        """Show it beside ``rect`` (a bar, in global coordinates): to its right when it fits, else its left, kept on the
        screen; the box has the caret."""
        self._fit()
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = rect.right() + 10 if rect.right() + 10 + w <= area.right() - 8 else rect.left() - w - 10
        x = max(area.left() + 8, min(x, area.right() - w - 8))
        y = max(area.top() + 8, min(rect.top() - 40, area.bottom() - h - 8))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.box.setFocus()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < HEAD:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)
