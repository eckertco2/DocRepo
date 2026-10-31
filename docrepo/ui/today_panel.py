"""The Today side panel (release 5.43; ``docs/ui-design/wheel-design.md``, section 7, decisions 217 to 223).

The Today view, pinned as a floating strip: a readable list at rest, more on hover, and a task's page on a click. **One list,
not two:** its rows come from what the Today view reads (``views.today_groups``, ``views.today_due_entries``, ``Model.done_on``),
and Done, Remove, Edit and the box call the browse tool's own methods, so an item done here is done there.

It never takes the keyboard from the window you're in, except when you click in its box or press its hotkey, so you can tick
something off and carry on typing in Outlook. Answering WM_MOUSEACTIVATE with "don't activate" isn't enough for that: tried with
real clicks, it leaves no window in front at all, and typing goes nowhere. So the window has WS_EX_NOACTIVATE, lifted only while
its box or its hotkey has the keyboard.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import time
from ctypes import wintypes
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QCursor, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import db, key_dates, markup, notes_page, panel_rules, selection
from docrepo.detail import Pages, PageState, esc
from docrepo.model import Model
from docrepo.panel_rules import OPEN_KEY, Hover, Monitor, Place, Rect
from docrepo.ui import tokens
from docrepo.ui.browse_window import TODAY_MINE_KEY
from docrepo.ui.context import AppContext
from docrepo.ui.icons import icon
from docrepo.ui.page_view import PageView
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.task_picker import path_text
from docrepo.ui.wheel_window import animations_on
from docrepo.views import due_cell, since_text, today_due_entries, today_groups

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.wheels import Wheels

log = logging.getLogger(__name__)

PLACE_KEY = "today_panel_place"
DUE_OPEN_KEY = "today_panel_due_open"
DONE_OPEN_KEY = "today_panel_done_open"
HOVER_TICK_MS = 40
FULL_SCREEN_CHECK_MS = 1500
MAX_HEIGHT_SHARE = 0.9
WM_MOUSEACTIVATE, MA_ACTIVATE, MA_NOACTIVATE = 0x0021, 1, 3
GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0, 0x11
#: PowerPoint's slide show window, which isn't in front while Presenter View has the keyboard on another monitor.
SLIDE_SHOW_CLASS = "screenClass"
NEWLINE = chr(10)

QSS = """
QWidget#todayPanel {{ background: {content}; border: 1px solid {stroke_strong}; }}
QWidget#tpTop {{ background: {base}; border-bottom: 1px solid {stroke}; }}
QFrame#tpRow {{ background: transparent; border-radius: 4px; }}
QFrame#tpRow:hover {{ background: {hover}; }}
QFrame#tpRow[current="true"] {{ background: {selected}; }}
QLabel#tpTitle {{ color: {text}; }}
QLabel#tpSub {{ color: {text2}; font-size: 8.5pt; }}
QLabel#tpGroup {{ color: {text2}; font-size: 8.5pt; font-weight: 600; }}
QLabel#tpDone {{ color: {disabled}; text-decoration: line-through; }}
QToolButton#tpFold {{ border: 0; color: {text2}; font-size: 8.5pt; font-weight: 600; text-align: left; padding: 2px; }}
QPushButton#tpLink {{ border: 0; background: transparent; color: {accent}; padding: 0 3px; min-height: 0; font-size: 8.5pt; }}
QPushButton#tpLink:hover {{ text-decoration: underline; }}
"""


class _Elided(QLabel):
    """A line cut off to fit, with all of it in the tooltip."""

    def __init__(self, text: str, name: str = "tpTitle") -> None:
        super().__init__(objectName=name)
        self.full = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.setText(QFontMetrics(self.font()).elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width())))


class _Row(QFrame):
    """One Today item: a tick box and its line at rest; widened, a second line, state and due date, and Done and Remove while
    the pointer is on it. Clicking opens its detail."""

    def __init__(self, panel: TodayPanel, item_id: int, task_id: str | None, title: str, sub: str, due: str) -> None:
        super().__init__(objectName="tpRow")
        self.panel, self.item_id, self.task_id, self.title = panel, item_id, task_id, title
        self.setProperty("current", False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(6)
        self.tick = QCheckBox()
        self.tick.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tick.setToolTip("Done: take it off Today")
        self.tick.clicked.connect(lambda: panel.done(self.item_id))
        lay.addWidget(self.tick, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(_Elided(title))
        self.subtitle = _Elided(sub, "tpSub")
        text.addWidget(self.subtitle)
        lay.addLayout(text, 1)
        self.due = QLabel(due, objectName="tpSub")
        lay.addWidget(self.due)
        self.buttons = QWidget()
        bl = QHBoxLayout(self.buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        for label, how in (("Done", self.done_clicked), ("Remove", self.remove_clicked)):
            b = QPushButton(label, objectName="tpLink")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(how)
            bl.addWidget(b)
        lay.addWidget(self.buttons)
        self.buttons.hide()
        self.setMouseTracking(True)

    def done_clicked(self) -> None:
        self.panel.done(self.item_id)

    def remove_clicked(self) -> None:
        self.panel.remove(self.item_id)

    def set_wide(self, wide: bool) -> None:
        self.subtitle.setVisible(wide and bool(self.subtitle.full))
        self.due.setVisible(wide and bool(self.due.text()))

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        if self.panel.hover.wide and not self.panel.detail_id():
            self.buttons.show()
            self.due.hide()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.buttons.hide()
        self.set_wide(self.panel.hover.wide)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.panel.open_detail(self.item_id)


class TodayPanel(QWidget):
    """One panel per DocRepo, made the first time it opens."""

    def __init__(self, ctx: AppContext, browse: BrowseWindow, wheels: Wheels) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx, self.browse, self.wheels = ctx, browse, wheels
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("todayPanel")
        self.setStyleSheet(style_sheet() + QSS.format(**tokens.LIGHT))
        self.setWindowTitle("Today")
        self.setAccessibleName("Today side panel")
        self.setMouseTracking(True)
        self.clock = lambda: int(time.perf_counter() * 1000)
        settings = self.settings
        self.hover = Hover(settings.hover_ms if settings.hover_ms is not None else windows_hover_ms(), settings.contract_ms, settings.hover)
        self.place_ = self._read_place()
        self.rows: list[_Row] = []
        self.cursor = -1  # the row the keyboard is on
        self._detail: tuple[str, int | None, str | None] | None = None  # ("task" or "note", the Today item, the task)
        self._asked: str | None = None
        self._note_kind = "task"
        self._came_from = 0
        self._drag_from: QPoint | None = None
        self._hidden_for_full_screen = False
        self._menu_open = False
        self.user_open = False
        self._built_for: date | None = None
        self._width_now = settings.rest_width
        self._grow = QVariantAnimation(self)
        self._grow.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._grow.valueChanged.connect(self._grown)
        self._build()
        self._hover_timer = QTimer(self, interval=HOVER_TICK_MS, timeout=self._hover_tick)
        self._full_screen_timer = QTimer(self, interval=FULL_SCREEN_CHECK_MS, timeout=self._check_full_screen)
        self._day_timer = QTimer(self, interval=60_000, timeout=self._new_day)
        ctx.today_changed = self._today_changed
        screens = QGuiApplication.instance()
        screens.screenRemoved.connect(lambda _s: QTimer.singleShot(0, self.place_window))
        screens.screenAdded.connect(lambda _s: QTimer.singleShot(0, self.place_window))
        self.winId()
        self._set_no_activate(True)

    @property
    def settings(self):
        return self.wheels.config.today_panel

    def _monitors(self) -> list[Monitor]:
        return [Monitor(s.name(), s.serialNumber(), s.size().width(), s.size().height()) for s in QGuiApplication.screens()]

    # ================= building =================
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        top = QWidget(objectName="tpTop")
        top.setCursor(Qt.CursorShape.SizeAllCursor)
        top.setToolTip("Drag to move it. It snaps to the nearer side. Right-click for more")
        top.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        top.customContextMenuRequested.connect(self._top_menu)
        top.installEventFilter(self)
        self.top = top
        tl = QHBoxLayout(top)
        tl.setContentsMargins(8, 4, 4, 4)
        self.count = QLabel(objectName="tpGroup")
        tl.addWidget(self.count, 1)
        close = QToolButton()
        close.setIcon(icon("close"))
        close.setToolTip("Close the panel")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setAutoRaise(True)
        close.clicked.connect(lambda: self.action("close"))
        tl.addWidget(close)
        outer.addWidget(top)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        # The list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget = QWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # the panel's width decides, not its rows
        self.list_lay = QVBoxLayout(self.list_widget)
        self.list_lay.setContentsMargins(4, 4, 4, 4)
        self.list_lay.setSpacing(1)
        self.scroll.setWidget(self.list_widget)
        self.stack.addWidget(self.scroll)
        # The detail
        detail = QWidget()
        detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # its buttons mustn't widen the panel at rest
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        bar.setSpacing(4)
        self.detail_buttons = {}
        for key, label, how in (("back", "Back", self.close_detail), ("done", "Done", lambda: self.done(self._detail_item())),
                                ("remove", "Remove", lambda: self.remove(self._detail_item())), ("edit", "Edit", self._edit_detail),
                                ("make", "Make it a task", self._make_task), ("browse", "Open in the browse tool", self._open_detail_in_browse)):
            b = QPushButton(label, objectName="tpLink")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, h=how: h())
            bar.addWidget(b)
            self.detail_buttons[key] = b
        bar.addStretch()
        dl.addLayout(bar)
        self.detail_page = PageView()  # the browse tool's, which draws the small pictures a task page names
        self.detail_page.setOpenLinks(False)
        self.detail_page.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_page.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.detail_page.document().setDefaultStyleSheet(page_css())
        self.detail_page.anchorClicked.connect(lambda _url: self._open_detail_in_browse())
        dl.addWidget(self.detail_page, 1)
        self.stack.addWidget(detail)
        # Below the list when it's wide: the question after Done, and the box
        self.ask_row = QWidget()
        al = QVBoxLayout(self.ask_row)
        al.setContentsMargins(6, 4, 6, 4)
        al.setSpacing(2)
        self.ask_label = QLabel(objectName="tpSub")
        self.ask_label.setWordWrap(True)
        al.addWidget(self.ask_label)
        answers = QHBoxLayout()
        answers.setSpacing(4)
        for label, answer in (("Update…", "update"), ("Close the task…", "close"), ("No", None)):
            b = QPushButton(label, objectName="tpLink")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, a=answer: self.answer(a))
            answers.addWidget(b)
        answers.addStretch()
        al.addLayout(answers)
        self.ask_row.hide()
        outer.addWidget(self.ask_row)
        self.box_row = QWidget()
        bl = QHBoxLayout(self.box_row)
        bl.setContentsMargins(6, 4, 6, 6)
        bl.setSpacing(4)
        self.box = QLineEdit()
        self.box.setPlaceholderText("A quick task")
        self.box.returnPressed.connect(self.add_from_box)
        self.box.installEventFilter(self)
        bl.addWidget(self.box, 1)
        self.kind_button = QPushButton("Task", objectName="tpLink")
        self.kind_button.setToolTip("The box makes a quick task, or a note on Today")
        self.kind_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.kind_button.clicked.connect(self._switch_kind)
        bl.addWidget(self.kind_button)
        self.box_row.hide()
        outer.addWidget(self.box_row)

    # ================= opening and closing =================
    def action(self, do: str) -> None:
        """"toggle", "open" or "close", from a wheel, the tray or the palette. "hotkey", its own hotkey: opens it and closes
        it, and a press while it's open but not active brings the keyboard to it, widened."""
        showing = self.isVisible() or self._hidden_for_full_screen
        if do == "close" or (do == "toggle" and showing):
            self.close_panel()
        elif do == "open" or (do == "toggle" and not showing):
            self.open_panel()
        elif not showing:
            self.open_panel()
        elif self.isActiveWindow():
            self.close_panel()
        else:
            self.take_keyboard()

    def open_panel(self) -> None:
        self.user_open = True
        self._hidden_for_full_screen = False
        db.set_state(self.ctx.conn, OPEN_KEY, "1")
        self.hover.enabled = self.settings.hover
        self.hover.contract_ms = self.settings.contract_ms
        self.hover.hover_ms = self.settings.hover_ms if self.settings.hover_ms is not None else windows_hover_ms()
        self.refresh()
        self.place_window()
        self._apply_capture_rule()
        self.show()
        self.raise_()
        self._full_screen_timer.start()
        self._day_timer.start()

    def close_panel(self) -> None:
        self.user_open = False
        self._hidden_for_full_screen = False
        db.set_state(self.ctx.conn, OPEN_KEY, "0")
        self._full_screen_timer.stop()
        self._day_timer.stop()
        self._hover_timer.stop()
        self.hover.pointer_out(self.clock())
        self.hover.contract()
        self.close_detail()
        self.hide()
        self._give_back()

    def _set_no_activate(self, on: bool) -> None:
        """Whether clicks leave the keyboard where it is. Off only while the box or the hotkey has the keyboard."""
        if os.name != "nt":
            return
        hwnd = wintypes.HWND(int(self.winId()))
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE if on else style & ~WS_EX_NOACTIVATE)

    def take_keyboard(self) -> None:
        """The hotkey while it's open: widened, with the keyboard here, until Esc gives it back."""
        self._came_from = selection.foreground()
        self._set_no_activate(False)
        self.hover.open_wide()
        self._update_state()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        if self.rows and self.cursor < 0:
            self._move_cursor(0)

    def _give_back(self) -> None:
        if self._came_from:
            selection.bring_forward(self._came_from)
            self._came_from = 0

    # ================= the rows: the same as the Today view's =================
    def _model(self) -> Model:
        return self.ctx.model()

    def _today(self) -> date:
        return self.ctx.now().date()

    def _today_changed(self) -> None:
        """The browse tool or the capture window changed Today. Nothing to draw while the panel is closed."""
        if self.user_open:
            self.refresh()

    def refresh(self) -> None:
        """Read what's on Today and draw it again."""
        if self._detail and self._detail[1] is not None and not any(a.id == self._detail[1] for a in self._model().today_items()):
            self._detail = None
            self.stack.setCurrentIndex(0)
        m, today = self._model(), self._today()
        self._built_for = today
        was = self.rows[self.cursor].item_id if 0 <= self.cursor < len(self.rows) else None
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.rows = []
        groups = today_groups(m, today)
        total = sum(len(items) for _, items in groups)
        self.count.setText(f"Today · {total}")
        for name, items in groups:
            self._add(QLabel(name, objectName="tpGroup"))
            for a in items:
                t = m.tasks.get(a.subject) if a.subject else None
                since = f"since {since_text(a.added, today)} · " if a.added[:10] < today.isoformat() else ""
                where = (path_text(m, t.id) or "Top-level task") if t else "A note"
                cell = due_cell(t, today) if t else None
                state = f"{t.state} · " if t else ""
                row = _Row(self, a.id, t.id if t else None, t.title if t else a.note, f"{since}{state}{where}", cell.text if cell else "")
                self.rows.append(row)
                self._add(row)
        if not total:
            self._add(QLabel("Nothing on Today.", objectName="tpSub"))
        self._add_due_section(m, today)
        self._add_done_section(m, today)
        self.list_lay.addStretch()
        self.cursor = next((i for i, r in enumerate(self.rows) if r.item_id == was), -1)
        self._mark_cursor()
        self._apply_wide()
        if self._detail:
            self._draw_detail()
        self.place_window()

    def _add(self, widget: QWidget) -> None:
        """A row in the list, shown at once, so the list's height counts it straight away."""
        self.list_lay.addWidget(widget)
        widget.show()

    def _fold(self, key: str, label: str) -> bool:
        """A folded heading, which remembers whether it's open. Returns whether it's open."""
        is_open = db.get_state(self.ctx.conn, key) == "1"
        fold = QToolButton(objectName="tpFold")
        fold.setText(("▾ " if is_open else "▸ ") + label)
        fold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fold.clicked.connect(lambda: (db.set_state(self.ctx.conn, key, "0" if is_open else "1"), self.refresh()))
        self.extras.append(fold)
        self._add(fold)
        return is_open

    def _add_due_section(self, m: Model, today: date) -> None:
        self.extras = []
        mine = db.get_state(self.ctx.conn, TODAY_MINE_KEY) == "1"
        entries = today_due_entries(m, today, self.ctx.settings.me, mine)
        if not self._fold(DUE_OPEN_KEY, f"Due in the next 7 days · {len(entries)}"):
            return
        for t in entries:
            is_key_date = isinstance(t, key_dates.Due)
            task = t.task if is_key_date else t
            text = (key_dates.label(t.key_date, today) + " · " + task.title) if is_key_date else task.title
            cell = due_cell(task, today) if not is_key_date else None
            line = QFrame(objectName="tpRow")
            lay = QHBoxLayout(line)
            lay.setContentsMargins(4, 2, 4, 2)
            lay.setSpacing(4)
            lay.addWidget(_Elided(text, "tpSub"), 1)
            if cell:
                lay.addWidget(QLabel(cell.text, objectName="tpSub"))
            if not is_key_date:
                add = QPushButton("Add", objectName="tpLink")
                add.setToolTip("Put it on Today")
                add.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                add.clicked.connect(lambda _=False, i=task.id: self.browse.add_to_today(i))
                lay.addWidget(add)
            self.extras.append(line)
            self._add(line)

    def _add_done_section(self, m: Model, today: date) -> None:
        done = m.done_on(today)
        if not self._fold(DONE_OPEN_KEY, f"Done today · {len(done)}"):
            return
        for a in done:
            t = m.tasks.get(a.subject) if a.subject else None
            line = _Elided(f"{t.title if t else a.note}  ({(a.closed or '')[11:16]})", "tpDone")
            self.extras.append(line)
            self._add(line)

    # ================= what the buttons do: the browse tool's own methods =================
    def done(self, item_id: int | None) -> None:
        """Done takes it off Today, and on a task asks "Update the task too?", as the Today view does."""
        if item_id is None:
            return
        item = next((a for a in self._model().today_items() if a.id == item_id), None)
        title = None
        if item is not None and item.subject and item.subject in self._model().tasks:
            title = self._model().tasks[item.subject].title
        self.browse.close_today_item(item_id, "Done")
        self._asked = self.browse.today_ask
        if self._asked and title:
            self.ask_label.setText(f"{title} is done for today. Update the task too?")
            self.ask_row.show()
            self.hover.open_wide()
        if self._detail and self._detail[1] == item_id:
            self.close_detail()
        self.refresh()
        self._update_state()

    def remove(self, item_id: int | None) -> None:
        if item_id is None:
            return
        self.browse.close_today_item(item_id, "Removed")
        if self._detail and self._detail[1] == item_id:
            self.close_detail()
        self.refresh()

    def answer(self, answer: str | None) -> None:
        self.ask_row.hide()
        self._asked = None
        self.browse.answer_today(answer)
        self._update_state()

    def add_from_box(self) -> None:
        text = self.box.text().strip()
        if text and self.browse.add_today_text(self._note_kind, text):
            self.box.clear()
            self.refresh()

    def _switch_kind(self) -> None:
        self._note_kind = "note" if self._note_kind == "task" else "task"
        self.kind_button.setText(self._note_kind.capitalize())
        self.box.setPlaceholderText("A quick task" if self._note_kind == "task" else "A note on Today")

    # ================= the detail =================
    def detail_id(self) -> tuple | None:
        return self._detail

    def _detail_item(self) -> int | None:
        return self._detail[1] if self._detail else None

    def open_detail(self, item_id: int) -> None:
        """A click: the panel widens to show the task's page, to read. A note shows its text."""
        item = next((a for a in self._model().today_items() if a.id == item_id), None)
        if item is None:
            return
        task = item.subject if item.subject in self._model().tasks else None
        self._detail = ("task" if task else "note", item_id, task)
        self._draw_detail()
        self.stack.setCurrentIndex(1)
        self.hover.open_wide()
        self._update_state()

    def _draw_detail(self) -> None:
        kind, item_id, task = self._detail
        m = self._model()
        for key, button in self.detail_buttons.items():
            button.setVisible(key in {"back", "done", "remove", "edit"} or (key == "browse" and kind == "task") or (key == "make" and kind == "note"))
        if kind == "task":
            pages = Pages(m, self._today(), self.browse.content_of, self.ctx.settings.me, self.ctx.conn)
            width = self.settings.detail_width - 28
            middle = notes_html(m.pages.get(task, ""))
            self.detail_page.setHtml(pages.task_page(task, PageState(), width, "top") + middle + pages.task_page(task, PageState(), width, "bottom"))
        else:
            note = next((a.note for a in m.today_items() if a.id == item_id), "")
            self.detail_page.setHtml(f"<p>{esc(note)}</p>")

    def close_detail(self) -> None:
        self._detail = None
        self.stack.setCurrentIndex(0)
        self._update_state()

    def _edit_detail(self) -> None:
        if not self._detail:
            return
        kind, item_id, task = self._detail
        if kind == "task":
            self.browse.show_browse(None, task)
            self.browse.edit_task(task)
        else:
            self.browse.edit_today_note(item_id)
        self.refresh()

    def _make_task(self) -> None:
        if self._detail and self._detail[1] is not None:
            self.browse.make_today_task(self._detail[1])
            self.close_detail()
            self.refresh()

    def _open_detail_in_browse(self) -> None:
        if self._detail and self._detail[2]:
            self.browse.show_browse(None, self._detail[2])

    # ================= hovering =================
    def _holding(self) -> bool:
        """What keeps it wide after the pointer leaves: the box has the cursor, a menu is open, or a detail is showing."""
        return self.box.hasFocus() or self._menu_open or self._detail is not None or self.ask_row.isVisible() or self.isActiveWindow()

    def _hover_ms(self) -> int | None:
        return self.settings.inner_edge_hover_ms if self._on_inner_edge() else None

    def _on_inner_edge(self) -> bool:
        screens = QGuiApplication.screens()
        screen = self._screen()
        rect = _rect(screen.geometry())
        return panel_rules.is_inner_edge(self.place_.side, rect, [_rect(s.geometry()) for s in screens])

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        at = QCursor.pos()
        self.hover.pointer_in(self.clock(), (at.x(), at.y()))
        self._hover_timer.start()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.hover.pointer_out(self.clock())
        self._hover_timer.start()

    def _hover_tick(self) -> None:
        at = QCursor.pos()
        if self.hover.inside:
            self.hover.pointer_moved(self.clock(), (at.x(), at.y()))
        was = self.hover.wide
        self.hover.tick(self.clock(), self._holding(), self._hover_ms())
        if was != self.hover.wide:
            self._update_state()
        if not self.hover.waiting(self._holding()):
            self._hover_timer.stop()

    def _apply_wide(self) -> None:
        wide = self.hover.wide
        for row in self.rows:
            row.set_wide(wide)
        for w in getattr(self, "extras", []):
            w.setVisible(wide)
        self.box_row.setVisible(wide and self._detail is None)

    def target_width(self) -> int:
        s = self.settings
        return s.detail_width if self._detail else s.hover_width if self.hover.wide else s.rest_width

    def _update_state(self) -> None:
        self._apply_wide()
        self.place_window()

    # ================= placing =================
    def _read_place(self) -> Place:
        try:
            return Place.from_json(json.loads(db.get_state(self.ctx.conn, PLACE_KEY) or "null"))
        except ValueError:
            return Place()

    def _save_place(self) -> None:
        db.set_state(self.ctx.conn, PLACE_KEY, json.dumps(self.place_.to_json()))

    def _screen(self):
        screens = QGuiApplication.screens()
        i = panel_rules.find_monitor(self.place_.monitor, self._monitors())
        return screens[i] if i is not None else QGuiApplication.primaryScreen()

    def _wanted_height(self, area: QRect) -> int:
        """Height follows the list, up to most of the monitor; a detail takes all of that."""
        most = int(area.height() * MAX_HEIGHT_SHARE)
        if self._detail:
            return most
        self.list_lay.invalidate()  # rows just hidden or shown count at once
        wanted =self.top.sizeHint().height() + self.list_lay.sizeHint().height() + 12
        for w in (self.ask_row, self.box_row):
            if not w.isHidden():
                wanted += w.sizeHint().height()
        return max(120, min(most, wanted))

    def place_window(self) -> None:
        """On its side of its monitor, at its height, growing away from the edge."""
        screen = self._screen()
        area = screen.availableGeometry()
        width = self.target_width()
        height = self._wanted_height(area)
        top = min(self.place_.top, max(0, area.height() - height))
        self._to = QRect(panel_rules.edge_x(self.place_.side, _rect(area), width), area.y() + top, width, height)
        if not self.isVisible() or self.width() == width or self.wheels.config.timing.animation_ms <= 0 or not animations_on():
            self._grow.stop()
            self.setGeometry(self._to)
            return
        self._grow.stop()
        self._grow.setDuration(min(100, self.wheels.config.timing.animation_ms))
        self._grow.setStartValue(self.width())
        self._grow.setEndValue(width)
        self._grow.start()

    def _grown(self, width: int) -> None:
        to = self._to
        x = to.x() if self.place_.side == "left" else to.x() + to.width() - int(width)
        self.setGeometry(x, to.y(), int(width), to.height())

    # ================= moving =================
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.top:
            t = event.type()
            if t == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._press_at = event.globalPosition().toPoint()
                return True
            if t == event.Type.MouseMove and self._drag_from is not None:
                self.move(event.globalPosition().toPoint() - self._drag_from)
                return True
            if t == event.Type.MouseButtonRelease and self._drag_from is not None:
                moved = (event.globalPosition().toPoint() - self._press_at).manhattanLength() > 4
                self._drag_from = None
                if moved:
                    self.dropped(self.frameGeometry().center())
                else:  # a click on the top line widens it, for those with hover turned off
                    self.hover.open_wide()
                    self._hover_timer.start()
                    self._update_state()
                return True
        elif watched is self.box and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)

    def dropped(self, centre: QPoint) -> None:
        """Released after a drag: it snaps to the nearer side edge of the monitor it's over, and remembers."""
        screen = QGuiApplication.screenAt(centre) or self._screen()
        area = screen.availableGeometry()
        side = panel_rules.snap_side(centre.x(), _rect(screen.geometry()))
        top = max(0, self.frameGeometry().y() - area.y())
        self.place_ = Place(side, top, Monitor(screen.name(), screen.serialNumber(), screen.size().width(), screen.size().height()))
        self._save_place()
        self.place_window()

    def _top_menu(self, at: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Move to next screen", self.move_to_next_screen)
        menu.addAction("Hide", lambda: self.action("close"))
        menu.addSeparator()
        menu.addAction("Open wheels config", self.wheels.open_config)
        self._menu_open = True
        menu.exec(self.top.mapToGlobal(at))
        self._menu_open = False
        self._hover_timer.start()

    def move_to_next_screen(self) -> None:
        screens = QGuiApplication.screens()
        now = screens.index(self._screen()) if self._screen() in screens else 0
        screen = screens[panel_rules.next_monitor(now, len(screens))]
        self.place_ = Place(self.place_.side, self.place_.top, Monitor(screen.name(), screen.serialNumber(), screen.size().width(), screen.size().height()))
        self._save_place()
        self.place_window()

    # ================= the keyboard =================
    def _move_cursor(self, row: int) -> None:
        if self.rows:
            self.cursor = max(0, min(len(self.rows) - 1, row))
            self._mark_cursor()
            self.scroll.ensureWidgetVisible(self.rows[self.cursor])

    def _mark_cursor(self) -> None:
        for i, r in enumerate(self.rows):
            r.setProperty("current", i == self.cursor)
            r.style().unpolish(r)
            r.style().polish(r)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Up and Down move, Enter the detail, Space Done, Delete Remove, Esc back
        key = event.key()
        current = self.rows[self.cursor] if 0 <= self.cursor < len(self.rows) else None
        if key == Qt.Key.Key_Escape:
            if self._detail:
                self.close_detail()
            else:
                self.box.clearFocus()
                self.hover.contract()
                self._update_state()
                self._give_back()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move_cursor(self.cursor + (1 if key == Qt.Key.Key_Down else -1))
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and current is not None:
            self.open_detail(current.item_id)
        elif key == Qt.Key.Key_Space and current is not None:
            self.done(current.item_id)
        elif key == Qt.Key.Key_Delete and current is not None:
            self.remove(current.item_id)
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - losing the keyboard lets it contract again
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow():
            self._set_no_activate(True)
            if not self.underMouse():
                self.hover.pointer_out(self.clock())
            self._hover_timer.start()

    # ================= Windows =================
    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt's name
        """A click on anything but the box leaves the keyboard where it is. A click in the box takes it, and Esc gives it back."""
        if os.name == "nt":
            try:
                msg = wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                return False, 0
            if msg.message == WM_MOUSEACTIVATE:
                if not isinstance(self.childAt(self.mapFromGlobal(QCursor.pos())), QLineEdit):
                    return True, MA_NOACTIVATE
                self._came_from = selection.foreground()
                self._set_no_activate(False)
                return True, MA_ACTIVATE
        return False, 0

    def _apply_capture_rule(self) -> None:
        """Decision 223's setting, off until the owner has checked with IT: it also hides the panel from screenshots and
        compliance recordings."""
        if os.name == "nt":
            ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(int(self.winId())), WDA_EXCLUDEFROMCAPTURE if self.settings.exclude_from_capture else WDA_NONE)

    def _check_full_screen(self) -> None:
        """Windows sends no notice, so while it's showing: a full-screen app or slide show on its monitor hides it, until
        that ends. On that monitor only."""
        if not self.settings.hide_on_full_screen or not self.user_open:
            return
        covered = self.covered_now()
        if covered and self.isVisible():
            self._hidden_for_full_screen = True
            self.hide()
        elif not covered and self._hidden_for_full_screen:
            self._hidden_for_full_screen = False
            self.show()

    def covered_now(self) -> bool:
        monitor = _native_rect(self._screen())
        return any(panel_rules.covers(r, monitor) for r in _full_screen_candidates(int(self.winId())))

    def _new_day(self) -> None:
        if self._built_for != self._today():
            self.refresh()


def notes_html(page: str) -> str:
    """A task's notes page, to read: its headings, its text with its formatting, its captions and its files in words. It's
    edited in the browse tool, one button away."""
    out: list[str] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            out.append(markup.to_html(NEWLINE.join(text)))
            text.clear()

    for line in notes_page.lines_of(page):
        if line.kind == "text":
            text.append(line.text)
            continue
        flush()
        if line.kind == "heading":
            out.append(f"<h4>{esc(line.text)}</h4>")
        elif line.kind == "caption":
            out.append(f'<p class="sub">{esc(line.text)}</p>')
        else:  # a file, a picture, an attachment or a table's row
            out.append(f"<p>{esc(line.text)}</p>")
    flush()
    return f"<h3>Notes</h3>{''.join(out)}" if out else ""


def _rect(r: QRect) -> Rect:
    return Rect(r.x(), r.y(), r.width(), r.height())


def _native_rect(screen) -> Rect:
    """A monitor in Windows' pixels: Qt keeps its top left, and scales its size."""
    g, ratio = screen.geometry(), screen.devicePixelRatio()
    return Rect(g.x(), g.y(), round(g.width() * ratio), round(g.height() * ratio))


def _full_screen_candidates(own: int) -> list[Rect]:
    """The window in front, and a slide show's window if there is one, with what Windows says their places are."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    out = []
    user32.FindWindowW.restype = wintypes.HWND
    for hwnd in (selection.foreground(), int(user32.FindWindowW(SLIDE_SHOW_CLASS, None) or 0)):
        if not hwnd or hwnd == own or selection._class_name(hwnd) in selection.NOT_A_WINDOW or not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            continue
        if user32.IsZoomed(wintypes.HWND(hwnd)):  # maximized, with the taskbar hidden, it fills the monitor but isn't full screen
            continue
        r = wintypes.RECT()
        if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
            out.append(Rect(r.left, r.top, r.right - r.left, r.bottom - r.top))
    return out


def windows_hover_ms() -> int:
    """Windows' own hover time (SPI_GETMOUSEHOVERTIME), 400 ms unless it's been changed."""
    if os.name != "nt":
        return 400
    value = wintypes.UINT(400)
    return value.value if ctypes.windll.user32.SystemParametersInfoW(0x0066, 0, ctypes.byref(value), 0) else 400
