"""The task tile's Qt side (release 5.138, the task tile plan's decisions 563 to 579).

- ``fill_menu``: the one right-click menu every tile has (decision 573).
- ``open_task``: what a tile's double-click and Enter do (572).
- ``TileWidget``: the tile painted as a widget, for the places that are widgets rather than item views: the Today side
  panel (576) and the Priorities board's cards and rows (575).

The browse window's lists paint their tiles in ``tree_view.HtmlDelegate``, and pages write theirs as HTML. What a tile
says is ``docrepo.task_tile``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QMenu, QSizePolicy, QToolTip, QWidget

from docrepo import task_tile
from docrepo.model import PRIORITY_NAMES
from docrepo.ui import tokens
from docrepo.ui.icons import icon, tinted

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: One of a view's own lines on a tile's menu: (label, clicked, tooltip), as a row's actions are.
Own = tuple[str, Callable[[], None], str]
#: A menu's key column: a tab, so the key lines up at the menu's right (``task_menus.key_column`` in the new look).
KEY = "	"

# ---- sizes, shared with the painted rows in tree_view.py ----
STATE = 16          # the state circle
MARK = 14           # a mark's icon
MARK_GAP = 3        # between marks
FLAG = 13           # Urgent's flag and the two-parents mark
TICK_SLOT = 12      # the depth ticks' slot, in a flat list
DAYS_W = 34         # the days number's column
PRIORITY_EDGES = {"critical": "pri_critical", "high": "pri_high", "medium": "pri_medium", "parking": "pri_parking"}
STATE_ICONS = {"Not started": ("state-ns", "text2"), "In progress": ("state-ip", "accent"), "Parked": ("state-pk", "parked"),
               "Closed": ("state-cl", "text2")}


def marks_width(marks: tuple) -> int:
    """The room a tile's marks take: a slot for each kind the view shows."""
    return len(marks) * MARK + max(0, len(marks) - 1) * MARK_GAP if marks else 0


def days_colour(d: task_tile.Days) -> str:
    """The days number's colour token: critical when late, caution when soon, else secondary text."""
    return {"over": "critical", "soon": "caution"}.get(d.kind, "text2")


def paint_ticks(painter: QPainter, x: int, mid: int, n: int) -> None:
    """Depth ticks (decision 570): one thin line a generation, at most ``task_tile.MAX_TICKS``, right-aligned in their slot
    that starts at ``x``, so the state circle after them keeps its place."""
    k = min(n, task_tile.MAX_TICKS)
    if k <= 0:
        return
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    colour = QColor(tokens.colour("control"))
    colour.setAlphaF(0.75)
    painter.setBrush(colour)
    right = x + TICK_SLOT - 2
    for i in range(k):
        painter.drawRoundedRect(right - i * 3 - 1, mid - 6, 1.5, 12, 0.75, 0.75)
    painter.restore()


def paint_marks(painter: QPainter, right: int, mid: int, marks: tuple, scale: float) -> list[tuple[QRect, str]]:
    """A tile's marks, their slots ending at ``right``: each where it's true, an empty slot where it isn't (decision 566).
    Returns each drawn mark's rectangle and tooltip, for hits."""
    out = []
    x = right - marks_width(marks)
    for mk in marks:
        if mk is not None:
            r = QRect(x, mid - MARK // 2, MARK, MARK)
            painter.drawPixmap(r.topLeft(), tinted(mk.icon, tokens.colour(mk.colour), MARK, scale))
            out.append((r, mk.tip))
        x += MARK + MARK_GAP
    return out


# ---- what a double-click opens (decision 572) ----
def open_task(browse: BrowseWindow, task_id: str) -> None:
    """A tile's double-click or Enter: the task's page, with the keyboard in it. In a view with the page beside, that page;
    from anywhere else (the side panel, the Priorities board, the quick summary), the browse window comes forward at the
    task's page in the Task tree, as the board's Open task did."""
    from docrepo.views import TASK_VIEWS

    m = browse.model()
    if task_id not in m.tasks:
        return
    if not browse.isVisible():
        browse.show_browse(task=task_id)
    elif browse.view in TASK_VIEWS:
        browse.select("task", task_id)
    else:
        browse.go_task(task_id)
    sizes = browse.split.sizes()
    if len(sizes) == 3 and sizes[2] < 200:  # the page pane was dragged shut: give it room again
        rest = sizes[1] + sizes[2]
        browse.split.setSizes([sizes[0], rest * 43 // 99, rest - rest * 43 // 99])
    browse.task_pane.setFocus(Qt.FocusReason.OtherFocusReason)
    from docrepo.ui.front import bring_to_front

    bring_to_front(browse)


# ---- the right-click menu (decision 573) ----
def others_on(browse: BrowseWindow, task_id: str) -> bool:
    """Whether someone besides the owner leads or is assigned the task, so Ask for an update has someone to ask."""
    t = browse.model().task(task_id)
    me = browse.ctx.settings.me
    return any(p != me for p in (*t.leads, *t.assignees))


def _copy(browse: BrowseWindow, text: str) -> None:
    QGuiApplication.clipboard().setText(text)
    browse.say(f"Copied: {text}")


def _priority_menu(browse: BrowseWindow, task_id: str, parent: QMenu) -> QMenu:
    """Priority: the four buckets and Not ranked with the board's keys, the current one ticked, then Urgent."""
    from docrepo import bulk, edits

    m = browse.model()
    t = m.task(task_id)
    menu = QMenu("Priority", parent)
    menu.setIcon(icon("priorities"))
    menu.setToolTipsVisible(True)
    picks = [(key, label, str(i + 1)) for i, (key, label) in enumerate(PRIORITY_NAMES.items())] + [("", "Not ranked", "0")]
    for key, label, k in picks:
        a = menu.addAction(f"{label}{KEY}{k}")
        a.setCheckable(True)
        a.setChecked((t.priority or "") == key)
        a.triggered.connect(lambda _=False, key=key: browse._do(
            lambda: edits.set_priority(browse.conn, browse.ctx.data_root, browse.ctx.fs, task_id, key, None, browse._now()), ("task", task_id)))
    menu.addSeparator()
    urgent = menu.addAction(icon("urgent"), "Urgent")
    urgent.setCheckable(True)
    urgent.setChecked(bool(t.urgent))
    urgent.triggered.connect(lambda on: browse._do(
        lambda: edits.bulk_edit(browse.conn, browse.ctx.data_root, browse.ctx.fs, browse.ctx.settings, [task_id],
                                bulk.BulkEdit(fields={"urgent": bool(on)}), browse._now()), ("task", task_id)))
    return menu


def _copy_menu(browse: BrowseWindow, task_id: str, parent: QMenu) -> QMenu:
    t = browse.model().task(task_id)
    menu = QMenu("Copy", parent)
    menu.setIcon(icon("copy"))
    menu.addAction("Title", lambda: _copy(browse, t.title))
    menu.addAction(f"ID ({task_id})", lambda: _copy(browse, task_id))
    menu.addAction("Title and ID", lambda: _copy(browse, f"{t.title} (#{task_id})"))
    return menu


def fill_menu(browse: BrowseWindow, task_id: str, menu: QMenu, own: Iterable[Own] = (), *, anchor: QWidget | None = None,
              after: Callable[[], None] | None = None, tell: Callable[[str, Callable[[], None] | None], None] | None = None,
              ask_first: bool = False, open_it: bool = True, state_pick: Callable[[str, bool], None] | None = None) -> None:
    """A tile's right-click menu, the same on every tile (decision 573), after anything already in ``menu``:

    1. Open, the default (Enter);
    2. the view's ``own`` lines (Today's Done, Later and Remove; an agenda's Discussed; Reminders' Clear), with Ask for an
       update first in Waiting on others (``ask_first``);
    3. State, Add to, Ask for an update (on a task someone else is on);
    4. Note, Update, New task under this one;
    5. Edit (with Quick edit), Priority and Copy.

    Nothing for a gone or discarded task. ``after`` and ``tell`` are a tree move's, and ``state_pick`` a state's, for a
    place outside the browse window that redraws itself (the side panel)."""
    from docrepo import task_commands
    from docrepo.ui import t_mails, task_menus

    m = browse.model()
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        return
    menu.setToolTipsVisible(True)
    if not menu.isEmpty():
        menu.addSeparator()
    if open_it:
        opened = menu.addAction(icon("open"), f"Open{task_menus.key_column()}Enter", lambda: open_task(browse, task_id))
        opened.setToolTip("Its page, with the keyboard in it: a double-click does the same")
        f = QFont(opened.font())
        f.setBold(True)
        opened.setFont(f)
        menu.setDefaultAction(opened)
    own = list(own)
    if own or ask_first:
        menu.addSeparator()
        if ask_first:
            t_mails.add_ask(browse, task_id, menu)
        for label, clicked, tip in own:
            a = menu.addAction(label, clicked)
            a.setToolTip(tip)
    menu.addSeparator()
    if state_pick is not None:
        from docrepo.ui.state_menu import state_menu

        menu.addMenu(state_menu(menu, m, task_id, state_pick))
    else:
        sub = browse.state_menu_for(task_id, menu)
        if sub is not None:
            menu.addMenu(sub)
    menu.addMenu(task_menus.add_to_menu(browse, task_id, menu))
    if not ask_first and others_on(browse, task_id):
        t_mails.add_ask(browse, task_id, menu)
    add_wait_lines(browse, task_id, menu)
    put = task_commands.put_under(m, task_id)
    if put is not None:
        task_menus.fill(menu, [put], lambda e: task_menus.run(browse, task_id, e, anchor, after, tell))
    menu.addSeparator()
    k = task_menus.key_column()
    menu.addAction(icon("note"), f"Note…{k}N", lambda: browse.open_capture(task=task_id, mode="note")).setToolTip("A note on its notes page")
    menu.addAction(icon("update"), f"Update…{k}U", lambda: browse.open_capture(task=task_id, mode="update")).setToolTip(
        "Its state, status, dates and more")
    menu.addAction(icon("add"), f"New task under this one…{k}T", lambda: browse.open_capture(task=task_id, mode="new_task"))
    menu.addSeparator()
    edit = task_menus.edit_menu(browse, task_id, menu, anchor, after, tell)
    actions = edit.actions()
    quick = QAction("Quick edit…", edit)
    quick.setToolTip("Its dates, people and hours, in words")
    quick.triggered.connect(lambda: browse.quick_edit(task_id, QRect(QCursor.pos(), QSize(1, 1))))
    edit.insertAction(actions[1] if len(actions) > 1 else None, quick)
    menu.addMenu(edit)
    menu.addMenu(_priority_menu(browse, task_id, menu))
    menu.addMenu(_copy_menu(browse, task_id, menu))


def add_wait_lines(browse: BrowseWindow, task_id: str, menu: QMenu) -> None:
    """Release 5.139's wait on a tile's menus (the task tile plan's decision 567): Log progress…, and Got it while the task
    waits. On the right-click menu after Ask for an update, and at the end of the circle's menu, under a line, as the owner
    looks for "waiting" where a state is set. Nothing on a closed or discarded task."""
    from docrepo import waits as wait_records

    m = browse.model()
    t = m.tasks.get(task_id)
    if t is None or t.discarded or t.state == "Closed":
        return
    menu.setToolTipsVisible(True)
    logged = menu.addAction(icon("waiting"), "Log progress…", lambda: browse.ctx.log_progress(task_id))
    logged.setToolTip("A line of what you did, who you're waiting on and when to follow up")
    if wait_records.current(m, task_id) is not None:
        got = menu.addAction(icon("state-cl"), "Got it", lambda: browse.got_it(task_id))
        got.setToolTip("The answer came: stop waiting, and take away the follow-up")


def tile_menu(browse: BrowseWindow, task_id: str, parent: QWidget | None, own: Iterable[Own] = (), **options) -> QMenu | None:
    """A tile's right-click menu, made: None for a gone or discarded task."""
    menu = QMenu(parent)
    fill_menu(browse, task_id, menu, own, **options)
    if menu.isEmpty():
        menu.deleteLater()
        return None
    return menu


# ---- a tile's parts as widgets: a Priorities card's (decision 575) ----
class MarksDays(QWidget):
    """A tile's marks and its days, at the end of a Priorities card's facts line, where the card keeps its wrapping title."""

    def __init__(self, tile: task_tile.Tile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tile = tile
        self._hits: list[tuple[QRect, str]] = []
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(marks_width(tile.marks) + (6 if tile.marks else 0) + DAYS_W, 18)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        mid = r.center().y() + 1
        self._hits = []
        if self.tile.days is not None:
            d = self.tile.days
            p.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
            p.setPen(QColor(tokens.colour(days_colour(d))))
            box = QRect(r.right() - DAYS_W, r.top(), DAYS_W, r.height())
            p.drawText(box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, ("◆ " if d.deadline else "") + d.text)
            self._hits.append((box, d.tip))
        if self.tile.marks:
            self._hits += paint_marks(p, r.right() - DAYS_W - 6, mid, self.tile.marks, self.devicePixelRatioF())
        p.end()

    def event(self, e) -> bool:  # noqa: D102 - Qt's
        if e.type() == e.Type.ToolTip:
            for box, tip in self._hits:
                if box.contains(e.pos()):
                    QToolTip.showText(e.globalPos(), tip, self)
                    return True
        return super().event(e)


# ---- a tile as a widget: the Today side panel and the Priorities board ----
class TileWidget(QWidget):
    """A ``task_tile.Tile`` painted on one line (the panel's rows, a Priorities card's title line and the rows inside a
    card). Its circle is a button (``state_clicked``); a double-click sends ``opened``; the right-click is the owner's
    (``contextMenuEvent`` of the place it's in). It paints no background: the place it's in gives the tile's tone."""

    state_clicked = Signal(str, QPoint)
    opened = Signal(str)

    def __init__(self, tile: task_tile.Tile, parent: QWidget | None = None, *, font: QFont | None = None, edge: bool = False,
                 circle: bool = True) -> None:
        super().__init__(parent)
        self.tile = tile
        self.edge = edge
        self.circle = circle
        self._font = font or tokens.ui_font()
        self._hits: list[tuple[QRect, str]] = []
        self._circle_rect = QRect()
        self._lit = False
        self._pressed_circle = False
        #: At rest in the side panel (decision 576): the circle, the title and the days, without depth ticks or marks.
        self.compact = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{tile.title}, {tile.state}")
        self.setToolTip(task_tile.tooltip(tile, PRIORITY_NAMES))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(160, max(24, QFontMetrics(self._font).height() + 8))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(60, self.sizeHint().height())

    def set_tile(self, tile: task_tile.Tile) -> None:
        self.tile = tile
        self.setToolTip(task_tile.tooltip(tile, PRIORITY_NAMES))
        self.update()

    def set_compact(self, on: bool) -> None:
        if on != self.compact:
            self.compact = on
            self.update()

    def circle_rect(self) -> QRect:
        return QRect(self._circle_rect)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        t = self.tile
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self.devicePixelRatioF()
        r = self.rect()
        mid = r.center().y() + 1
        x = 4
        if self.edge and t.priority in PRIORITY_EDGES:
            p.fillRect(0, 2, 3, r.height() - 4, QColor(tokens.colour(PRIORITY_EDGES[t.priority])))
        if t.depth >= 0 and not self.compact:
            paint_ticks(p, x, mid, t.depth)
            x += TICK_SLOT + 2
        self._hits = []
        if self.circle:
            name, colour = STATE_ICONS.get(t.state, STATE_ICONS["Not started"])
            self._circle_rect = QRect(x - 2, mid - STATE // 2 - 2, STATE + 4, STATE + 4)
            if self._lit:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(tokens.colour("pressed")))
                p.drawRoundedRect(self._circle_rect, 4, 4)
            p.drawPixmap(QPoint(x, mid - STATE // 2), tinted(name, tokens.colour(colour), STATE, scale))
            x += STATE + 8
        right = r.right() - 4
        fm = QFontMetrics(self._font)
        small = tokens.ui_font(tokens.CAPTION, semibold=True)
        if t.days is not None:
            p.setFont(small)
            p.setPen(QColor(tokens.colour(days_colour(t.days))))
            text = ("◆ " if t.days.deadline else "") + t.days.text
            box = QRect(right - DAYS_W, r.top(), DAYS_W, r.height())
            p.drawText(box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            self._hits.append((box, t.days.tip))
        right -= DAYS_W + 4
        if t.marks and not self.compact:
            self._hits += paint_marks(p, right, mid, t.marks, scale)
            right -= marks_width(t.marks) + 6
        extras = [(n, tip) for n, tip, on in (("urgent", "Urgent", t.urgent), ("parents", t.parents, bool(t.parents))) if on]
        room = right - x - sum(FLAG + 6 for _ in extras)
        title = task_tile.fit_title(t.title, room, fm.horizontalAdvance, lambda s, w: fm.elidedText(s, Qt.TextElideMode.ElideRight, int(w)))
        f = QFont(self._font)
        f.setStrikeOut(t.closed)
        p.setFont(f)
        p.setPen(QColor(tokens.colour("text2" if t.closed else "text")))
        w = fm.horizontalAdvance(title)
        p.drawText(QRect(x, r.top(), w + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, title)
        x += w + 6
        for name, tip in extras:
            box = QRect(x, mid - FLAG // 2, FLAG, FLAG)
            p.drawPixmap(box.topLeft(), tinted(name, tokens.colour("critical" if name == "urgent" else "text2"), FLAG, scale))
            self._hits.append((box, tip))
            x += FLAG + 6
        p.end()

    def event(self, e) -> bool:  # noqa: D102 - Qt's
        if e.type() == e.Type.ToolTip:
            for box, tip in self._hits:
                if box.contains(e.pos()):
                    QToolTip.showText(e.globalPos(), tip, self)
                    return True
            if self.circle and self._circle_rect.contains(e.pos()):
                QToolTip.showText(e.globalPos(), f"{self.tile.state}. Click to change the state.", self)
                return True
        return super().event(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802 - Qt's name
        lit = self.circle and self._circle_rect.contains(e.position().toPoint())
        if lit != self._lit:
            self._lit = lit
            self.setCursor(Qt.CursorShape.PointingHandCursor) if lit else self.unsetCursor()
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if self._lit:
            self._lit = False
            self.unsetCursor()
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802 - Qt's name
        self._pressed_circle = False
        if e.button() == Qt.MouseButton.LeftButton and self.circle and self._circle_rect.contains(e.position().toPoint()):
            e.accept()
            self._pressed_circle = True
            self.state_clicked.emit(self.tile.task_id, self.mapToGlobal(self._circle_rect.bottomLeft() + QPoint(0, 2)))
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if self._pressed_circle:  # the circle's click is the state menu's alone: the row under it doesn't open too
            self._pressed_circle = False
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if self.circle and self._circle_rect.contains(e.position().toPoint()):
            e.accept()
            return
        e.accept()
        self.opened.emit(self.tile.task_id)
