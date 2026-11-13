"""The Today side panel (release 5.43; ``docs/ui-design/wheel-design.md``, section 7, decisions 217 to 223).

The Today view, pinned as a floating strip: a readable list at rest, more on hover, and a task's page on a click. **One list,
not two:** its rows come from what the Today view reads (``views.today_groups``, ``lists.reminders_due``, ``views.today_due_entries``,
``Model.done_on``), and Done, Remove, Edit and the box call the browse tool's own methods, so an item done here is done there.

It never takes the keyboard from the window you're in, except when you click in its box or press its hotkey, so you can tick
something off and carry on typing in Outlook. Answering WM_MOUSEACTIVATE with "don't activate" isn't enough for that: tried with
real clicks, it leaves no window in front at all, and typing goes nowhere. So the window has WS_EX_NOACTIVATE, lifted only while
its box or its hotkey has the keyboard.

Release 5.106 (``docs/mods/today-panel-plan.md`` in the design workspace): its inner edge can be dragged to set its width at
rest, which it remembers (decision 406), and a file, a link or an email dropped on one of its tasks opens the capture window
as an Update on that task, with what was dropped in it (decisions 407 and 408).

Release 5.119 (``docs/mods/rows-and-bullets-plan.md``, decisions 440 to 443, the owner's voice memo of 2026-11-11): a row's
title has its line to itself. Its state, as its icon, and its date, short ("8 d"), are on its second line, at the right,
where Later, Done and Remove show on the pointer; Due in the next 7 days has the short date too.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import time
from collections.abc import Callable
from ctypes import wintypes
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QPainter, QPen
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

from docrepo import db, edits, key_dates, markup, meetings, notes_page, panel_rules, selection, waits
from docrepo.detail import Pages, PageState, esc
from docrepo.model import Model, Task, is_person
from docrepo.panel_rules import OPEN_KEY, REST_WIDTH_KEY, Hover, Monitor, Place, Rect
from docrepo.schedule import is_open
from docrepo.ui import tokens
from docrepo.ui.browse_window import TODAY_MINE_KEY
from docrepo.ui.capture_window import note_drag, read_drop
from docrepo.ui.context import AppContext
from docrepo.ui.drop_target import DropOverlay, DropRead
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.page_view import PageView
from docrepo.ui import today_meetings
from docrepo.ui.tree_view import PRIORITY_EDGES, state_icon
from docrepo.ui.state_menu import UNDO_MS, UndoButton
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.tokens import C
from docrepo.ui.wheel_window import animations_on
from docrepo.views import DueCell, due_cell, project_text, since_text, today_due_entries, today_groups

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.wheels import Wheels

log = logging.getLogger(__name__)

PLACE_KEY = "today_panel_place"
REMINDERS_OPEN_KEY = "today_panel_reminders_open"
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
#: The grip on the inner edge, in pixels (decision 406).
GRIP_WIDTH = 5
#: What the cover says while an email, or a file only a program holds, is dragged over the panel (decision 408).
COVER_EMAIL = "Drop on a task: DocRepo keeps the email whole"
COVER_FILE = "Drop on a task: DocRepo keeps the file as it's handed over"

QSS = """
QWidget#todayPanel {{ background: {content}; border: 1px solid {stroke_strong}; }}
QWidget#tpTop {{ background: {base}; border-bottom: 1px solid {stroke}; }}
QFrame#tpRow {{ background: transparent; border-radius: 4px; }}
QFrame#tpRow:hover {{ background: {hover}; }}
QFrame#tpRow[current="true"] {{ background: {selected}; }}
QFrame#tpRow[drop="true"] {{ background: {selected}; border: 1px solid {accent}; }}
QLabel#tpTitle {{ color: {text}; }}
QLabel#tpSub {{ color: {text2}; font-size: {caption}pt; }}
QLabel#tpDue {{ color: {text2}; font-size: {caption}pt; }}
QLabel#tpGroup {{ color: {text2}; font-size: {caption}pt; font-weight: 600; }}
QLabel#tpDone {{ color: {disabled}; text-decoration: line-through; }}
QToolButton#tpFold {{ border: 0; color: {text2}; font-size: {caption}pt; font-weight: 600; text-align: left; padding: 2px; }}
QPushButton#tpLink {{ border: 0; background: transparent; color: {accent}; padding: 0 3px; min-height: 0; font-size: {caption}pt; }}
QPushButton#tpLink:hover {{ text-decoration: underline; }}
QPushButton#tpState {{ border: 0; border-radius: 4px; background: transparent; color: {text2}; padding: 0 3px; min-height: 0; font-size: {caption}pt; }}
QPushButton#tpState:hover {{ background: {pressed}; }}
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


def edge_of(t: Task | None) -> str:
    """An open task's priority, as the colour of its row's left edge (release 5.81, decision L9), or "" for none."""
    return tokens.colour(PRIORITY_EDGES[t.priority]) if t is not None and is_open(t) and t.priority in PRIORITY_EDGES else ""


class _EdgeFrame(QFrame):
    """A row with its task's priority down its left edge, as the browse window's lists have it."""

    edge = ""
    #: The task a drop on this row goes to (decision 407), and its title; None for a note on Today.
    task_id: str | None = None
    title = ""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        if self.edge:
            p = QPainter(self)
            p.fillRect(0, 2, 3, self.height() - 4, QColor(self.edge))
            p.end()


def due_label(cell: DueCell | None) -> QLabel:
    """A row's date, short (release 5.119, decision 442): "8 d", "Today", "3 d late", red when it's late and caution's
    colour within two days, as the browse tool's Due column, a deadline in Due's place with its red ◆, and the whole
    date in the tooltip ("Due Fri 20 Nov, in 8 d")."""
    label = QLabel(objectName="tpDue")
    if cell is not None:
        fill_due(label, cell)
    return label


def fill_due(label: QLabel, cell: DueCell) -> None:
    """``due_label``'s words, in a label made already: a meeting's minutes move on in place (release 5.127)."""
    label.setTextFormat(Qt.TextFormat.RichText)
    mark = f'<span style="color:{tokens.colour("critical")}">◆</span> ' if cell.deadline else ""
    colour = {"over": "critical", "soon": "caution"}.get(cell.cls)
    style = f' style="color:{tokens.colour(colour)}; font-weight:600"' if colour else ""
    label.setText(f"{mark}<span{style}>{esc(cell.days)}</span>")
    label.setProperty("days", cell.days)
    label.setToolTip(cell.tip)


class _Row(_EdgeFrame):
    """One Today item: a tick box and its title at rest. Widened, a second line under the title: its project, a reminder
    and how long it's been carried at its left; its state's icon and its date at its right, the date giving way to Later,
    Done and Remove while the pointer is on it. The title keeps its line to itself (release 5.119, decisions 440 to
    442). Clicking opens its detail."""

    def __init__(self, panel: TodayPanel, item_id: int, task_id: str | None, title: str, sub: str, due: DueCell | None,
                 state: str = "", edge: str = "") -> None:
        super().__init__(objectName="tpRow")
        self.edge = edge
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
        self.title_label = _Elided(title)
        text.addWidget(self.title_label)
        self.second = QWidget()
        second = QHBoxLayout(self.second)
        second.setContentsMargins(0, 0, 0, 0)
        second.setSpacing(4)
        self.subtitle = _Elided(sub, "tpSub")
        second.addWidget(self.subtitle, 1)
        # The task's state, as its icon (decision 441, as the browse tool's lists have it, decision L7), a button that
        # opens the state menu (release 5.76, round 7's item 101, decision 361), its name in its tooltip.
        self.state_button: QPushButton | None = None
        if task_id and state:
            name, colour = state_icon(state)
            self.state_button = QPushButton(objectName="tpState")
            self.state_button.setIcon(icon(name, tokens.colour(colour), size=14))
            self.state_button.setIconSize(icon_size(14))
            self.state_button.setAccessibleName(state)
            self.state_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.state_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.state_button.setToolTip(f"{state}. Click to change the state.")
            self.state_button.clicked.connect(lambda: panel.state_clicked(self))
            second.addWidget(self.state_button)
        self.due = due_label(due)
        second.addWidget(self.due)
        self.buttons = QWidget()
        bl = QHBoxLayout(self.buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        for label, how in ((("Later", self.later_clicked),) if task_id else ()) + (("Done", self.done_clicked), ("Remove", self.remove_clicked)):
            b = QPushButton(label, objectName="tpLink")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(how)
            bl.addWidget(b)
        second.addWidget(self.buttons)
        self.buttons.hide()
        text.addWidget(self.second)
        lay.addLayout(text, 1)
        self.setMouseTracking(True)

    def done_clicked(self) -> None:
        self.panel.done(self.item_id)

    def later_clicked(self) -> None:
        """Later (release 5.116, decision 417): its menu, under the pointer."""
        self.panel.later(self.task_id, self.item_id)

    def remove_clicked(self) -> None:
        self.panel.remove(self.item_id)

    def set_wide(self, wide: bool) -> None:
        self.due.setVisible(bool(self.due.text()))
        self.second.setVisible(wide and bool(self.subtitle.full or self.due.text() or self.state_button is not None))

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        if self.panel.hover.wide and not self.panel.detail_id():
            self.second.show()
            self.buttons.show()
            self.due.hide()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.buttons.hide()
        self.set_wide(self.panel.hover.wide)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.panel.open_detail(self.item_id)


class _Grip(QWidget):
    """The panel's inner edge at rest (decision 406): drag it to set the width at rest. The pointer on it doesn't widen
    the panel, so it can be dragged narrow."""

    def __init__(self, panel: TodayPanel) -> None:
        super().__init__(panel)
        self.panel = panel
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("Drag to set its width at rest. Right-click the top line to reset it")
        self.setMouseTracking(True)
        self._from: int | None = None
        self._start = 0

    def dragging(self) -> bool:
        return self._from is not None

    def paintEvent(self, event) -> None:  # noqa: N802 - a line on the edge while it's under the pointer
        if self.underMouse() or self.dragging():
            p = QPainter(self)
            x = 0 if self.panel.place_.side == "right" else self.width() - 2
            p.fillRect(x, 0, 2, self.height(), QColor(C.accent))
            p.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.panel.on_grip(True)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        if not self.dragging():
            self.panel.on_grip(False)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._from = event.globalPosition().toPoint().x()
            self._start = self.panel.width()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._from is not None:
            self.panel.size_rest(self._start, event.globalPosition().toPoint().x() - self._from)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._from is not None:
            self._from = None
            self.panel.keep_rest()
            if not self.rect().contains(event.position().toPoint()):
                self.panel.on_grip(False)
            self.update()


class _DropCover(DropOverlay):
    """DocRepo's own drop target over the panel (decision 408), while an email from Outlook, or a file only a program
    holds, is dragged over it. It draws the panel's tasks where they are, marks the one under the pointer, and takes a
    drop only on a task."""

    def __init__(self, panel: TodayPanel) -> None:
        super().__init__(panel, panel.cover_dropped, panel.cover_allows)
        self.panel = panel
        self.email = True

    def cover(self, email: bool = True) -> None:
        self.email = email
        self.panel._cover_target = None
        super().cover(email)

    def uncover(self) -> None:
        super().uncover()
        self.panel.drag_over()

    def paintEvent(self, event) -> None:  # noqa: N802 - drawn here, so the rows show through as targets
        panel = self.panel
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C.info_bg))
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(C.accent))
        top = QRect(8, 0, self.width() - 16, panel.top.height())
        hint = COVER_EMAIL if self.email else COVER_FILE
        p.drawText(top, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(font).elidedText(hint, Qt.TextElideMode.ElideRight, top.width()))
        font.setBold(False)
        p.setFont(font)
        viewport = panel.scroll.viewport()
        p.setClipRect(QRect(viewport.mapTo(panel, QPoint(0, 0)), viewport.size()))
        for w in panel.drop_targets():
            r = QRect(w.mapTo(panel, QPoint(0, 0)), w.size()).adjusted(1, 1, -1, -1)
            hot = w is panel._cover_target
            p.setPen(QPen(QColor(C.accent), 2 if hot else 1, Qt.PenStyle.SolidLine if hot else Qt.PenStyle.DashLine))
            p.setBrush(QColor(tokens.LIGHT["selected" if hot else "content"]))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(tokens.LIGHT["text"]))
            words = r.adjusted(8, 0, -8, 0)
            p.drawText(words, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(font).elidedText(w.title, Qt.TextElideMode.ElideRight, words.width()))
        p.setClipping(False)
        p.setPen(QPen(QColor(C.accent), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        p.end()


class TodayPanel(QWidget):
    """One panel per DocRepo, made the first time it opens."""

    def __init__(self, ctx: AppContext, browse: BrowseWindow, wheels: Wheels) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx, self.browse, self.wheels = ctx, browse, wheels
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("todayPanel")
        self.setStyleSheet(style_sheet() + QSS.format(caption=tokens.CAPTION, **tokens.LIGHT))
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
        self._note_kind = "task"
        self._came_from = 0
        self._drag_from: QPoint | None = None
        self._hidden_for_full_screen = False
        self._menu_open = False
        self.user_open = False
        self._built_for: date | None = None
        self._width_now = settings.rest_width
        self._rest = db.get_state(self.ctx.conn, REST_WIDTH_KEY)  # the width at rest, dragged and kept (decision 406)
        self._dragging = False  # a drag of files, links or an email is over the panel (decision 407)
        self._drop_at: _EdgeFrame | None = None  # the row a drop would go to, marked
        self._cover_target: _EdgeFrame | None = None  # the same, under the cover
        self._grow = QVariantAnimation(self)
        self._grow.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._grow.valueChanged.connect(self._grown)
        self._build()
        self.grip = _Grip(self)
        self.grip.hide()
        self.setAcceptDrops(True)
        self.drop_cover = _DropCover(self)
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
        self.count.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # dragged narrow, the width decides (decision 406)
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
        # Below the list: what a state picked from a row did (release 5.76, decision 363), or Done, Remove or Back on Today
        # (release 5.115, decision 420), with Undo, for ten seconds; then, when it's wide, the box.
        self.note_row = QWidget()
        nl = QHBoxLayout(self.note_row)
        nl.setContentsMargins(6, 2, 6, 2)
        nl.setSpacing(4)
        self.note_label = QLabel(objectName="tpSub")
        self.note_label.setWordWrap(True)
        nl.addWidget(self.note_label)
        self.note_undo = UndoButton()
        self.note_undo.setObjectName("tpLink")
        self.note_undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nl.addWidget(self.note_undo)
        nl.addStretch()  # Undo right after the words, as in the status line
        self._note_timer = QTimer(self, singleShot=True, interval=UNDO_MS, timeout=self.note_row.hide)
        self.note_row.hide()
        outer.addWidget(self.note_row)
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
        self.ctx.keep_state(OPEN_KEY, "1")
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
        self.ctx.keep_state(OPEN_KEY, "0")
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
        self._mark_drop(None)
        self._cover_target = None
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.rows = []
        self.extras = []
        self._add_meeting_line(m)  # first, the next meeting (release 5.127, decision 490)
        groups = today_groups(m, today)
        total = sum(len(items) for _, items in groups)
        self.count.setText(f"Today · {total}")
        for name, items in groups:
            self._add(QLabel(name, objectName="tpGroup"))
            for a in items:
                t = m.tasks.get(a.subject) if a.subject else None
                since = f"since {since_text(a.added, today)} · " if a.added[:10] < today.isoformat() else ""
                where = project_text(m, t.id) if t else ""  # its project (the list rows review, decision L3)
                cell = due_cell(t, today) if t else None
                # The state is a button of its own (release 5.76), not words in the second line; the rest is joined as
                # the list rows review joins quiet words (release 5.78).
                state = "" if t is None or t.discarded else t.state
                reminder = "reminder" if a.added_by == edits.REMINDER else ""  # a reminder put it here (release 5.116, decision 415)
                wait = waits.current(m, t.id) if t else None  # its follow-up, or that it's waiting (release 5.139, decisions 580 and 595)
                if wait is not None:
                    reminder = f"Follow up: {waits.words(m, wait, today)}" if wait.late(today) else waits.words(m, wait, today, row=True)
                row = _Row(self, a.id, t.id if t else None, t.title if t else a.note, " · ".join(x for x in (where, reminder, since.rstrip(" ·")) if x),
                           cell, state, edge_of(t))
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
        fold.setText(label)
        fold.setIcon(icon("chevron-down" if is_open else "chevron-right"))
        fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        fold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fold.clicked.connect(lambda: (self.ctx.keep_state(key, "0" if is_open else "1"), self.refresh()))
        self.extras.append(fold)
        self._add(fold)
        return is_open

    def _add_line(self, text: str, when: DueCell | None, links: list[tuple[str, str, Callable[[], object]]], edge: str = "",
                  task_id: str | None = None) -> _EdgeFrame:
        """A row under a folded heading: its words, its date, each link's name, tooltip and what it does, its task's
        priority as its edge, and its task, where a drop on it goes. Returns the row."""
        line = _EdgeFrame(objectName="tpRow")
        line.edge = edge
        line.task_id, line.title = task_id, text
        lay = QHBoxLayout(line)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)
        lay.addWidget(_Elided(text, "tpSub"), 1)
        if when:  # short, as a Today row's (decision 443)
            lay.addWidget(due_label(when))
        for name, tip, do in links:
            link = QPushButton(name, objectName="tpLink")
            link.setToolTip(tip)
            link.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            link.clicked.connect(lambda _=False, do=do: do())
            lay.addWidget(link)
        self.extras.append(line)
        self._add(line)
        return line

    # ================= the next meeting (release 5.127, the cold-eyes plan's decision 490) =================
    def _add_meeting_line(self, m: Model) -> None:
        """The first line: the meeting under way, else the next one, its subject and its minutes ("in 20 min", "now"), with
        Agenda and Notes once it's linked, or Link…, which opens it on Today in the browse tool. A short quiet line when the
        calendar couldn't be read; nothing when no meeting is left today, or with the switch off."""
        self.meeting_line: _EdgeFrame | None = None
        self.meeting_drawn: tuple = ()
        day, cal = today_meetings.day_of(self.ctx)
        if day is None:
            return
        self.meeting_drawn = self._meeting_state(day, cal)
        x = day.lead
        if x is None:
            if cal.kind:
                self._add(QLabel(f"Meetings: {meetings.PROBLEM_WORDS[cal.kind]}", objectName="tpSub"))
            return
        target = x.target
        if target:
            links = [("Agenda", "Its agenda, in the browse tool", lambda: self._agenda_in_browse(target)),
                     ("Notes", "Meeting notes, for today's meeting", lambda: today_meetings.open_notes(self.browse, x))]
        elif x.appointment.key and not x.appointment.private:
            links = [("Link…", "Link it to a meeting task or a person, on Today in the browse tool", lambda: self._link_in_browse(x))]
        else:
            links = []
        line = self.meeting_line = self._add_line(x.appointment.title, today_meetings.time_cell(x, self._today()), links,
                                                  task_id=target if target and not is_person(target) else None)
        # The first line at rest too, unlike the folded sections' rows: its commands only once it's widened.
        self.extras.remove(line)
        self.extras += line.findChildren(QPushButton, "tpLink")
        mark = QLabel()
        mark.setPixmap(icon("person" if target and is_person(target) else "agenda" if target else "calendar",
                            tokens.colour("accent" if target else "text2"), size=14).pixmap(icon_size(14)))
        mark.setToolTip("The meeting under way, or your next one, from your Outlook calendar")
        line.layout().insertWidget(0, mark)
        line.setToolTip(meetings.context_words(m, x))

    @staticmethod
    def _meeting_state(day: meetings.DayMeetings, cal: meetings.TodayCalendar) -> tuple:
        lead = day.lead
        return (lead.appointment, lead.when, lead.target) if lead else (cal.kind,)

    def _agenda_in_browse(self, target: str) -> None:
        self.browse.show_browse()
        today_meetings.open_agenda(self.browse, target)

    def _link_in_browse(self, x: meetings.Meeting) -> None:
        """Link… from the panel: the browse tool on Today, where Link…'s list takes the keyboard (the panel never does)."""
        self.browse.show_browse(view="today")
        today_meetings.pick_link(self.browse, x)

    def _tick_meeting(self) -> None:
        """Each minute while it's open: the line's minutes move on in place; a new lead, or a read that failed, draws it
        again."""
        day, cal = today_meetings.day_of(self.ctx)
        if day is None:
            if self.meeting_drawn or self.meeting_line is not None:
                self.refresh()
            return
        if self._meeting_state(day, cal) != self.meeting_drawn:
            self.refresh()
            return
        if self.meeting_line is not None and day.lead is not None:
            label = self.meeting_line.findChild(QLabel, "tpDue")
            if label is not None:
                fill_due(label, today_meetings.time_cell(day.lead, self._today()))

    def _add_due_section(self, m: Model, today: date) -> None:
        mine = db.get_state(self.ctx.conn, TODAY_MINE_KEY) == "1"
        entries = today_due_entries(m, today, self.ctx.settings.me, mine)
        if not self._fold(DUE_OPEN_KEY, f"Due in the next 7 days · {len(entries)}"):
            return
        for t in entries:
            is_key_date = isinstance(t, key_dates.Due)
            task = t.task if is_key_date else t
            text = (key_dates.label(t.key_date, today) + " · " + task.title) if is_key_date else task.title
            cell = due_cell(task, today) if not is_key_date else None
            links = [] if is_key_date else [("Add", "Put it on Today", lambda i=task.id: self.browse.add_to_today(i)),
                                            ("Later", "Off this list until a later day, when its reminder puts it on Today",
                                             lambda i=task.id: self.later(i, None))]
            self._add_line(text, cell, links, edge_of(task), task.id)

    def _add_done_section(self, m: Model, today: date) -> None:
        """Done today, each row with Back on Today (release 5.115, decision 420)."""
        done = m.done_on(today)
        if not self._fold(DONE_OPEN_KEY, f"Done today · {len(done)}"):
            return
        for a in done:
            t = m.tasks.get(a.subject) if a.subject else None
            line = QFrame(objectName="tpRow")
            lay = QHBoxLayout(line)
            lay.setContentsMargins(4, 2, 4, 2)
            lay.setSpacing(4)
            lay.addWidget(_Elided(f"{t.title if t else a.note}  ({(a.closed or '')[11:16]})", "tpDone"), 1)
            back = QPushButton("Back on Today", objectName="tpLink")
            back.setToolTip("Put it back on Today, as it was")
            back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            back.clicked.connect(lambda _=False, i=a.id: self.put_back(i))
            lay.addWidget(back)
            self.extras.append(line)
            self._add(line)

    # ================= a row's state (release 5.76, round 7's item 101) =================
    def state_clicked(self, row: _Row) -> None:
        """A row's state: the browse tool's state menu, under it. The panel stays open while the menu is."""
        if row.task_id is None or row.state_button is None:
            return
        b = row.state_button
        self._menu_open = True
        try:
            self.browse.popup_state_menu(row.task_id, b.mapToGlobal(QPoint(0, b.height() + 2)), after=self.refresh, tell=self.tell_state)
        finally:
            self._menu_open = False

    def tell_state(self, text: str, undo: Callable[[], None] | None) -> None:
        """What a pick did, under the list, with Undo for ten seconds (decision 363)."""
        self.note_label.setText(text)
        self.note_row.show()
        self._note_timer.start()
        if undo is not None:
            self.note_undo.offer(undo)
        else:
            self.note_undo.forget()

    # ================= what the buttons do: the browse tool's own methods =================
    def done(self, item_id: int | None) -> None:
        """The tick box, Done or Space: off Today, and on a task the capture window opens as an Update on it, with no question
        (release 5.115, decision 421). What it did is said under the list, with Undo (decision 420)."""
        self._close_item(item_id, "Done")

    def remove(self, item_id: int | None) -> None:
        self._close_item(item_id, "Removed")

    def _close_item(self, item_id: int | None, how: str) -> None:
        if item_id is None:
            return
        self.browse.close_today_item(item_id, how, tell=self.tell_state)
        if self._detail and self._detail[1] == item_id:
            self.close_detail()
        self.refresh()
        self._update_state()

    def later(self, task_id: str | None, item_id: int | None) -> None:
        """Later (release 5.116, decision 417): the browse tool's menu, under the pointer, with what it did said here. The
        panel stays open while the menu is."""
        if not task_id:
            return
        self._menu_open = True
        try:
            self.browse.later_menu(task_id, item_id, QCursor.pos(), tell=self.tell_state)
        finally:
            self._menu_open = False
        self.refresh()
        self._hover_timer.start()

    def put_back(self, item_id: int) -> None:
        """Back on Today, on a row of Done today (decision 420)."""
        self.browse.put_back_today(item_id, tell=self.tell_state)
        self.refresh()

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
            pages = Pages(m, self._today(), self.browse.content_of, self.ctx.settings.me, self.ctx.conn, reference_links=self.ctx.settings.reference_links)
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
        return self.box.hasFocus() or self._menu_open or self._detail is not None or self.isActiveWindow() or self._dragging

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
        return s.detail_width if self._detail else s.hover_width if self.hover.wide else self.rest_width()

    def rest_width(self) -> int:
        """The width at rest: dragged and kept (decision 406), or else the wheels config's."""
        return panel_rules.rest_width(self._rest, self.settings.rest_width, self.settings.hover_width)

    # ================= the width at rest (release 5.106, decision 406) =================
    def on_grip(self, on: bool) -> None:
        """The pointer on the grip counts as off the panel, so it doesn't widen while the edge is dragged."""
        at = QCursor.pos()
        if on:
            self.hover.pointer_out(self.clock())
        elif self.rect().contains(self.mapFromGlobal(at)):
            self.hover.pointer_in(self.clock(), (at.x(), at.y()))
        self._hover_timer.start()

    def size_rest(self, start: int, dx: int) -> None:
        """The inner edge dragged ``dx`` pixels from where it was, at ``start`` wide: the panel follows at once."""
        self._rest = str(panel_rules.dragged_width(self.place_.side, start, dx, self.settings.hover_width))
        self.place_window(animate=False)

    def keep_rest(self) -> None:
        self.ctx.keep_state(REST_WIDTH_KEY, self._rest or "")

    def reset_rest(self) -> None:
        """Back to the wheels config's width at rest."""
        self._rest = None
        self.ctx.keep_state(REST_WIDTH_KEY, "")
        self.place_window()

    def _place_grip(self) -> None:
        """The grip on the inner edge, below the top line, and only at rest."""
        grip = getattr(self, "grip", None)
        if grip is None:
            return
        top = self.top.height()
        x = 0 if self.place_.side == "right" else self.width() - GRIP_WIDTH
        grip.setGeometry(x, top, GRIP_WIDTH, max(0, self.height() - top))
        at_rest = not self.hover.wide and self._detail is None and not self._dragging
        grip.setVisible(at_rest or grip.dragging())
        grip.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._place_grip()
        cover = getattr(self, "drop_cover", None)
        if cover is not None and cover.isVisible():
            cover.setGeometry(self.rect())

    # ================= drops on a task (release 5.106, decisions 407 and 408) =================
    def drop_targets(self) -> list[_EdgeFrame]:
        """The rows a drop can go to: Today's tasks, and the tasks under Reminders and Due in the next 7 days, as shown; and the
        meeting line's task, once it's linked to one (release 5.127)."""
        rows = [*self.rows, *getattr(self, "extras", []), getattr(self, "meeting_line", None)]
        return [w for w in rows if isinstance(w, _EdgeFrame) and w.task_id and w.isVisibleTo(self)]

    def target_at(self, at: QPoint) -> _EdgeFrame | None:
        """The task row under ``at``, a point on the screen, in the list as it shows."""
        if self.stack.currentIndex() != 0:
            return None
        viewport = self.scroll.viewport()
        if not viewport.rect().contains(viewport.mapFromGlobal(at)):
            return None
        return next((w for w in self.drop_targets() if w.rect().contains(w.mapFromGlobal(at))), None)

    def _mark_drop(self, target: _EdgeFrame | None) -> None:
        old, self._drop_at = self._drop_at, target
        if old is target:
            return
        for w, on in ((old, False), (target, True)):
            if w is not None:
                w.setProperty("drop", on)
                w.style().unpolish(w)
                w.style().polish(w)

    def drag_in(self) -> None:
        """A drag came over the panel: it widens and shows its list, so the tasks can be read, until the drag is over."""
        self._dragging = True
        if self._detail:
            self._detail = None
            self.stack.setCurrentIndex(0)
        self.hover.open_wide()
        self._apply_wide()
        self.place_window(animate=False)

    def drag_over(self) -> None:
        """The drag left, or dropped: the panel goes back to hovering's rules."""
        if not self._dragging:
            return
        self._dragging = False
        self._mark_drop(None)
        at = QCursor.pos()
        if self.rect().contains(self.mapFromGlobal(at)):
            self.hover.pointer_in(self.clock(), (at.x(), at.y()))
        else:
            self.hover.pointer_out(self.clock())
        self._update_state()
        self._hover_timer.start()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        kind = note_drag("enter", event.mimeData(), links=True)
        if not kind:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.drag_in()
        if kind in ("outlook", "virtual") and self.drop_cover.available:
            self.drop_cover.cover(email=kind == "outlook")

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        target = self.target_at(self.mapToGlobal(event.position().toPoint())) if read_drop(event.mimeData(), links=True)[0] else None
        self._mark_drop(target)
        if target is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - the cover taking the drag over isn't the drag leaving
        if not self.drop_cover.isVisible():
            self.drag_over()

    def dropEvent(self, event) -> None:  # noqa: N802
        note_drag("drop", event.mimeData(), links=True)
        kind, paths = read_drop(event.mimeData(), links=True)
        target = self.target_at(self.mapToGlobal(event.position().toPoint())) if kind else None
        self.drag_over()
        if target is None or not target.task_id:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        task_id = target.task_id
        QTimer.singleShot(0, lambda: self.drop_on(task_id, kind, paths))  # after the drop, so the program dragging is let go

    def cover_allows(self) -> bool:
        """The cover's question while an email or a file is dragged over it: is the pointer on a task? Kept, for the drop."""
        target = self.target_at(QCursor.pos())
        if target is not self._cover_target:
            self._cover_target = target
            self.drop_cover.update()
        return target is not None

    def cover_dropped(self, found: DropRead) -> None:
        """What the cover took, after the drop, for the task it was dropped on."""
        target, self._cover_target = self._cover_target, None
        if target is not None and target.task_id and (found.items or found.problems):
            self.drop_on(target.task_id, found=found)

    def drop_on(self, task_id: str, kind: str = "", paths: list[str] | None = None, found: DropRead | None = None) -> None:
        """Decision 407: the capture window, opened as an Update on the task, with what was dropped in it, as if it had
        been dropped there. A capture it was holding goes to Drafts first, as any open for a task does."""
        self.browse.drop_on_task(task_id, kind, paths, found)

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
        self.ctx.keep_state(PLACE_KEY, json.dumps(self.place_.to_json()))

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
        for w in (self.note_row, self.box_row):
            if not w.isHidden():
                wanted += w.sizeHint().height()
        return max(120, min(most, wanted))

    def place_window(self, animate: bool = True) -> None:
        """On its side of its monitor, at its height, growing away from the edge."""
        screen = self._screen()
        area = screen.availableGeometry()
        width = self.target_width()
        height = self._wanted_height(area)
        top = min(self.place_.top, max(0, area.height() - height))
        self._to = QRect(panel_rules.edge_x(self.place_.side, _rect(area), width), area.y() + top, width, height)
        if not animate or not self.isVisible() or self.width() == width or self.wheels.config.timing.animation_ms <= 0 or not animations_on():
            self._grow.stop()
            self.setGeometry(self._to)
            self._place_grip()
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
        reset = menu.addAction("Reset the width at rest", self.reset_rest)
        reset.setEnabled(bool(self._rest))
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
        elif key == Qt.Key.Key_F5:  # the calendar read again (release 5.127, decision 493)
            today_meetings.read_again(self.ctx)
            self.refresh()
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
        else:
            self._tick_meeting()


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
