"""The browse tool's Priorities board (mods log round 2, M0029, M0030; release 5.23, decisions 23 and 74 to 78).

The open tasks as cards, in a column per bucket, Not ranked first. Drag a card to another column, or up and down in its
own (Not ranked sorts itself, so a card dropped there just leaves its bucket). Or with the keys written on each column's
header: 1 to 4 put the selected card at the end of that bucket and 0 takes it out, Alt+Up and Alt+Down move it within its
bucket, the arrow keys move between cards, and Enter opens the task. Double-clicking a card opens Edit task. The board
only says what was asked for (``moved``, ``nudged``); the browse window makes the change and draws the board again.
Like the timeline, it takes the middle and right panes together. ``docrepo/priorities.py`` has the rules.

Show (release 5.137, decisions 550 to 554) picks Work, Parents or All. In Parents a parent's card holds the subtasks
folded into it: its opener (or Space) lists them as rows, and a row is picked, ranked, dragged and opened as a card is.
A parent's card shows its subtasks' buckets as small squares (``Pips``), in Parents and All.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from docrepo import priorities, task_tile
from docrepo.detail import esc
from docrepo.model import Model, Task
from docrepo.stories import clip
from docrepo.ui import tokens
from docrepo.ui.icons import icon, tinted
from docrepo.ui import task_tile as tile_ui
from docrepo.ui.look import LOOK, Help, KeyBadge
from docrepo.ui.widgets import CheckMenuButton, ElidedLabel, FlowLayout, label_filter, people_filter
from docrepo.views import due_cell, find_text, path_text

#: A column's least width: the board scrolls across in a narrower window, so it never sets the window's least width (release 5.58).
COLUMN_MIN = 216
#: A dragged card carries its task's ID.
MIME = "application/x-docrepo-task"
#: A state's chip colours, as the pages draw them.
STATE_COLOURS = {"In progress": ("accent", "info_bg"), "Not started": ("text2", "hover"), "Parked": ("parked", "parked_bg"), "Closed": ("text2", "hover")}
#: A parent's card's opener, closed and open (release 5.137): the icons' chevrons, the one arrow family.
CLOSED, OPENED = "chevron-right", "chevron-down"


def _chip(text: str, fg: str, bg: str, bold: bool = False) -> str:
    """A chip for a label: its colours inline, since a label doesn't have the pages' style sheet."""
    weight = " font-weight:600;" if bold else ""
    return f'<span style="color:{tokens.colour(fg)}; background-color:{tokens.colour(bg)};{weight}">&nbsp;{esc(text)}&nbsp;</span>'


def _urgent() -> str:
    return _chip("Urgent", "critical", "critical_bg", True)


NOTE = ("Click a card, or a subtask inside one, to see it here. Drag cards between columns, or use the keys on the column "
        "headers: 1 to 4 and 0 move the selected card, Alt+Up and Alt+Down move it within its column, the arrow keys move "
        "between cards, Space opens a parent's card in Parents, and Enter opens the task.")


class _Picked:
    """What a click, a drag, a right-click and a double-click do on a card or on a row inside one: the same for both."""

    view: "PrioritiesView"
    task_id: str
    _press: QPoint | None

    def circle_at(self, pos: QPoint) -> QRect | None:
        """The state circle's rectangle when ``pos`` is on it, in this widget's own coordinates; None elsewhere."""
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            circle = self.circle_at(event.position().toPoint())
            if circle is not None:  # the state circle (release 5.138, decision 564): its menu, under it
                event.accept()
                self.view.state_clicked.emit(self.task_id, self.mapToGlobal(circle.bottomLeft() + QPoint(0, 2)))
                return
            self._press = event.position().toPoint()
            self.view.pick(self.task_id)
        event.accept()  # a row's press stays with the row, so its card doesn't take the pick

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name: the card's menu, with its State submenu (release 5.76)
        event.accept()
        self.view.card_menu.emit(self.task_id, event.globalPos())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)  # type: ignore[arg-type]
        mime = QMimeData()
        mime.setData(MIME, QByteArray(self.task_id.encode("ascii")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())  # type: ignore[attr-defined]
        drag.setHotSpot(event.position().toPoint())
        self.view.dragging = self.task_id
        drag.exec(Qt.DropAction.MoveAction)
        self.view.dragging = None

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - opens its page (release 5.138, decision 572): Edit task is E
        event.accept()
        if self.circle_at(event.position().toPoint()) is None:
            self.view.open_task.emit(self.task_id)


class Pips(QWidget):
    """Subtasks as small squares in their buckets' colours, Critical first and Not ranked as a hollow square (release
    5.137, decision 554). Its tooltip names each with its bucket. A click goes through to the card."""

    SIZE, GAP, MOST = 8, 3, 16

    def __init__(self, m: Model, ids: list[str]) -> None:
        super().__init__(objectName="prPips")
        self.buckets = [m.task(x).priority or "" for x in ids]
        n = min(len(ids), self.MOST)
        more = 14 if len(ids) > self.MOST else 0
        self.setFixedSize(max(n * (self.SIZE + self.GAP) - self.GAP, 0) + more, self.SIZE + 4)
        self.setToolTip("<br>".join(f"{esc(m.task(x).title)}: {priorities.name(m.task(x).priority)}" for x in ids))
        self.setAccessibleName(", ".join(priorities.name(b) for b in self.buckets))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - self.SIZE) / 2
        for i, bucket in enumerate(self.buckets[:self.MOST]):
            box = QRectF(i * (self.SIZE + self.GAP) + 0.75, top + 0.75, self.SIZE - 1.5, self.SIZE - 1.5)
            if bucket:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(tokens.colour(f"pri_{bucket}")))
            else:
                p.setPen(QPen(QColor(tokens.colour("control")), 1.25))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 2, 2)
        if len(self.buckets) > self.MOST:
            p.setPen(QColor(tokens.colour("text2")))
            p.drawText(QRectF(self.MOST * (self.SIZE + self.GAP), 0, 14, self.height()), Qt.AlignmentFlag.AlignCenter, "+")
        p.end()


class Card(_Picked, QFrame):
    """A task's card: its title, its path, and a line of facts (Urgent, the due date, its people), with its top-level
    task's colour down its left edge. A parent's card adds a line for its subtasks, and in Parents the rows of those
    inside it (``rows_box``), opened and closed by its ``opener``."""

    def __init__(self, view: "PrioritiesView", t: Task, colour: str, facts: str, path: str, selected: bool,
                 tile: task_tile.Tile | None = None) -> None:
        super().__init__(objectName="prCard")
        self.view, self.task_id, self.colour = view, t.id, colour
        self.setProperty("sel", selected)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName(f"{t.title}, {priorities.name(t.priority)}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 8, 10, 8)
        self.lay.setSpacing(2)
        # A task tile's parts on a card (release 5.138, the task tile plan's decision 575): the state's circle before the
        # title, which still wraps, and the marks and days at the end of the facts line.
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.circle = QLabel(objectName="prCircle")
        name, colour_key = tile_ui.STATE_ICONS.get(t.state, tile_ui.STATE_ICONS["Not started"])
        self.circle.setPixmap(tinted(name, tokens.colour(colour_key), tile_ui.STATE, self.devicePixelRatioF()))
        self.circle.setFixedSize(tile_ui.STATE + 4, tile_ui.STATE + 4)
        self.circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.circle.setToolTip(f"{t.state}. Click to change the state.")
        top.addWidget(self.circle, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel(esc(t.title), objectName="prTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        self.lay.addLayout(top)
        if path:
            self.lay.addWidget(ElidedLabel(path, objectName="fieldLabel"))
        if facts or tile is not None:
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            f = QLabel(facts)
            f.setWordWrap(True)
            f.setTextFormat(Qt.TextFormat.RichText)
            line.addWidget(f, 1)
            if tile is not None and (tile.days is not None or any(tile.marks)):
                line.addWidget(tile_ui.MarksDays(tile), 0, Qt.AlignmentFlag.AlignVCenter)
            self.lay.addLayout(line)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.opener: QPushButton | None = None
        self.rows_box: QWidget | None = None
        self._press: QPoint | None = None
        self.installEventFilter(view)

    def circle_at(self, pos: QPoint) -> QRect | None:
        r = self.circle.geometry()
        return r if r.adjusted(-2, -2, 2, 2).contains(pos) else None

    def add(self, w: QWidget) -> None:
        """A line of its own under the facts. Its words let a click through to the card, as the card's own do."""
        self.lay.addWidget(w)
        for label in w.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(0, 1, 3, self.height() - 2, QColor(self.colour))
        p.end()


class Row(_Picked, QFrame):
    """A subtask inside its parent's card, in Parents (release 5.137, decisions 552 and 553): its bucket's square, its
    title (Urgent first) and its due date. It's picked, ranked, dragged, opened and edited as a card is."""

    def __init__(self, view: "PrioritiesView", m: Model, t: Task, today: date, selected: bool) -> None:
        super().__init__(objectName="prRow")
        self.view, self.task_id = view, t.id
        #: The parent whose card it's inside.
        self.holder = ""
        self.setProperty("sel", selected)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName(f"{t.title}, {priorities.name(t.priority)}, inside its parent's card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lay.addWidget(Pips(m, [t.id]), 0, Qt.AlignmentFlag.AlignVCenter)
        # A task tile (release 5.138, the task tile plan's decision 575), its pip in its edge's place: the circle, the title
        # cut to fit, the flag, the marks and the days.
        self.tile = tile_ui.TileWidget(task_tile.tile(m, t.id, today, task_tile.marks(m, today)), font=tokens.ui_font(tokens.CAPTION + 0.5))
        self.tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.tile, 1)
        self.setToolTip(f"{t.title}: {priorities.name(t.priority)}")
        for w in self.findChildren(QWidget):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._press: QPoint | None = None
        self.installEventFilter(view)

    def circle_at(self, pos: QPoint) -> QRect | None:
        r = self.tile.circle_rect().translated(self.tile.pos())
        return r if r.contains(pos) else None


class Column(QFrame):
    """A bucket's column: its key, name and count, then its cards. A card dropped on it goes where the line shows, before
    the card under the pointer's middle, or at the end; Not ranked has no order, so there's no line."""

    def __init__(self, view: "PrioritiesView", col: priorities.Column) -> None:
        super().__init__(objectName="prCol")
        self.view, self.key = view, col.key
        self.setAcceptDrops(True)
        self.setMinimumWidth(COLUMN_MIN)
        self.setAccessibleName(col.name)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        moves = f"Press {col.digit} to move the selected card {'out of its bucket' if not col.key else 'here'}"
        key = KeyBadge(col.digit)  # with Show hints; the Alt overlay and the tooltip have it otherwise (decision 7)
        key.setToolTip(moves)
        head.addWidget(key)
        name = QLabel(f"<b>{esc(col.name)}</b>")
        name.setToolTip(moves)
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(QLabel(str(len(col.ids)), objectName="count"))
        lay.addLayout(head)
        if not col.key:
            lay.addWidget(Help("Sorted for you: urgent first, then the soonest due."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="prCards")
        self.cards_layout = QVBoxLayout(body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards: list[Card] = []
        for task_id in col.ids:
            card = view.make_card(task_id)
            self.cards.append(card)
            self.cards_layout.addWidget(card)
        if not col.ids:
            empty = QLabel("Drop a card here", objectName="fieldLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(empty)
        self.cards_layout.addStretch(1)
        self.line = QFrame(objectName="prDrop")
        self.line.setFixedHeight(3)
        self.line.hide()
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

    def _spot(self, y_in_column: int) -> Card | None:
        """The card a drop at this height lands before: the first whose middle is below the pointer."""
        for card in self.cards:
            if card.task_id == self.view.dragging:
                continue
            middle = card.mapTo(self, QPoint(0, card.height() // 2)).y()
            if y_in_column < middle:
                return card
        return None

    def _show_line(self, before: Card | None) -> None:
        self.cards_layout.removeWidget(self.line)
        if not self.key:
            self.line.hide()
            return
        at = self.cards_layout.indexOf(before) if before is not None else len(self.cards)
        self.cards_layout.insertWidget(at, self.line)
        self.line.show()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            self.setProperty("over", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            self._show_line(self._spot(event.position().toPoint().y()))
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._end_drag()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(MIME):
            return
        task_id = bytes(event.mimeData().data(MIME).data()).decode("ascii")
        before = self._spot(event.position().toPoint().y()) if self.key else None
        self._end_drag()
        event.acceptProposedAction()
        self.view.drop(task_id, self.key, before.task_id if before else None)

    def _end_drag(self) -> None:
        self.line.hide()
        self.setProperty("over", False)
        self.style().unpolish(self)
        self.style().polish(self)


class PrioritiesView(QWidget):
    """The Priorities view: its filters, the card for the selected task with the buckets as buttons, and the board.
    ``picked`` sends the task a click selects, ``open_task`` one to open, ``edit_task`` one to edit, ``moved`` a task with
    the bucket it goes to ("" for Not ranked) and the task it goes before (or None, the end), and ``nudged`` a task and a
    step (-1 up, +1 down) with the IDs shown in its column."""

    picked = Signal(str)
    open_task = Signal(str)
    edit_task = Signal(str)
    moved = Signal(str, str, object)
    nudged = Signal(str, int, list)
    #: A card's right-click menu, at a point on the screen: Open, Edit and its State submenu (release 5.76, decision 361).
    card_menu = Signal(str, QPoint)
    #: A card's or a row's state circle was clicked (release 5.138, decision 564): the task, and where its menu goes.
    state_clicked = Signal(str, QPoint)

    def __init__(self) -> None:
        super().__init__()
        self.model: Model | None = None
        self.today = date.today()
        self.me: str | None = None
        self.sel: str | None = None
        self.people: list[str] = []
        self.labels: list[str] = []
        self.due = "any"
        self.routine = False
        #: Show (release 5.137, decision 550): "work", "parents" or "all". It starts on All, the board as it was, and is
        #: kept while DocRepo runs, as the filters are.
        self.show_what = "all"
        #: The parents' cards opened in Parents, kept while DocRepo runs (decision 552).
        self.opened: set[str] = set()
        self.dragging: str | None = None
        self.columns: list[priorities.Column] = []
        #: In Parents: each card's folded subtasks that the filters show, and the cards shown only for those.
        self.folds: dict[str, list[str]] = {}
        self.context: set[str] = set()
        #: Each parent card's squares (decision 554).
        self.pips: dict[str, list[str]] = {}
        self.cards: dict[str, Card] = {}
        #: The rows inside the cards, by their task: a subtask with two parents on the board is a row in each.
        self.rows: dict[str, list[Row]] = {}
        self._shown: set[str] = set()
        #: Show's three buttons, by key (``priorities.SHOWS``).
        self.show_buttons: dict[str, QPushButton] = {}
        self._colours: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(8)
        self.title = QLabel(objectName="paneTitle")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.title)
        lay.addWidget(Help("Open tasks by priority. Rank them by dragging, or with the keys on each column. A move to another column "
                           "goes into the task's status log. Urgent stays a flag of its own; parked, closed and routine tasks aren't here."))
        self.controls = QWidget()
        self.controls_layout = FlowLayout(self.controls, spacing=8)
        lay.addWidget(self.controls)
        # Find on the board (release 5.24): Ctrl+F, as Find in this view elsewhere; it narrows the cards as you type, and
        # Esc clears it.
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find on the board")
        self.find_box.setAccessibleName("Find in this view")
        self.find_box.setToolTip("Find in this view: a card stays when its task holds every word. Esc clears it. (Ctrl+F)")
        self.find_box.textChanged.connect(lambda _: self.model is not None and self.render(self.model, self.today, self.sel, self.me))
        self.find_box.installEventFilter(self)
        fb.addWidget(self.find_box, 1)
        self.find_count = QLabel(objectName="paneNote")
        fb.addWidget(self.find_count)
        self.find_bar.hide()
        lay.addWidget(self.find_bar)
        self.strip = QFrame(objectName="fileRow")
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)
        self.strip_text = QLabel()
        self.strip_text.setWordWrap(True)
        self.strip_text.setTextFormat(Qt.TextFormat.RichText)
        sl.addWidget(self.strip_text)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.buckets = QWidget(objectName="typeStrip")
        self.buckets.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        bl = QHBoxLayout(self.buckets)
        bl.setContentsMargins(2, 2, 2, 2)
        bl.setSpacing(2)
        self.bucket_group = QButtonGroup(self)
        self.bucket_group.setExclusive(True)
        self.bucket_buttons: dict[str, QPushButton] = {}
        for key, label, digit in priorities.COLUMNS:
            b = QPushButton(f"{digit}  {label}" if LOOK.show_help else label, objectName="subtle")
            b.setCheckable(True)
            b.setToolTip(f"{label} ({digit})")
            b.clicked.connect(lambda _=False, k=key: self.sel and self.moved.emit(self.sel, k, None))
            self.bucket_group.addButton(b)
            self.bucket_buttons[key] = b
            bl.addWidget(b)
        row.addWidget(self.buckets)
        row.addStretch(1)
        self.open_button = QPushButton("Open task", objectName="primary" if LOOK.classic else "")
        self.open_button.clicked.connect(lambda: self.sel and self.open_task.emit(self.sel))
        self.edit_button = QPushButton("Edit")
        self.edit_button.setToolTip("Edit task (E)")
        self.edit_button.clicked.connect(lambda: self.sel and self.edit_task.emit(self.sel))
        row.addWidget(self.open_button)
        row.addWidget(self.edit_button)
        sl.addLayout(row)
        lay.addWidget(self.strip)
        self.board = QWidget()
        self.board_layout = QHBoxLayout(self.board)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setSpacing(8)
        board_scroll = QScrollArea()
        board_scroll.setWidgetResizable(True)
        board_scroll.setFrameShape(QFrame.Shape.NoFrame)
        board_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        board_scroll.setWidget(self.board)
        lay.addWidget(board_scroll, 1)

    # ---- drawing ----
    def render(self, model: Model, today: date, sel: str | None, me: str | None = None) -> None:
        """Draw the board again from the model, keeping its filters, and the focus on the selected card if it had it."""
        had_focus = isinstance(QApplication.focusWidget(), (Card, Row))  # not while typing in Find
        self.model, self.today, self.me = model, today, me
        tops = [t.id for t in model.top_level() if not t.discarded]
        self._colours = {}
        for t in model.tasks.values():
            top = model.chains_of(t.id)[0][0]
            self._colours[t.id] = tokens.group_colour(tops.index(top)) if top in tops else tokens.group_colour(-1)
        f = priorities.BoardFilter(tuple(self.people), tuple(self.labels), self.due, self.routine, self.show_what)
        words = self.find_box.text().lower().split() if not self.find_bar.isHidden() else []

        def found(x: str) -> bool:  # every word in the task's ID, title, description, status, labels, people or path
            return all(w in find_text(model, x) + " " + path_text(model, x).lower() for w in words)

        # Find goes through the board's own rules, so a subtask it finds brings its folded parent's card (release 5.136)
        self.columns = priorities.columns(model, today, f, found if words else None)
        self.folds = {x: kept for c in self.columns for x, kept in c.folds.items()}
        self.context = set().union(*(c.context for c in self.columns))
        self.pips = {x: ids for c in self.columns for x, ids in c.pips.items()}
        if words:  # the tasks found, on their own cards or folded into one
            hits = sum(len(c.ids) for c in self.columns) - len(self.context) + sum(len(v) for v in self.folds.values())
            self.find_count.setText(f"{hits} match{'es' if hits != 1 else ''}" if hits else "Nothing on the board matches")
        else:
            self.find_count.clear()
        shown = {x for c in self.columns for x in c.ids}
        self._shown = shown
        inside = {x for v in self.folds.values() for x in v}
        if sel in inside and sel not in shown and not any(sel in self.folds.get(x, []) for x in self.opened):
            sel = next(x for x, v in self.folds.items() if sel in v)  # a row in a closed card: its card is picked
        self.sel = sel if sel in shown or sel in inside else None
        self._controls()
        n, unranked = len(shown), len(self.columns[0].ids)
        self.title.setText(f'Priorities&nbsp;&nbsp;<span style="color:{tokens.colour("text2")}; font-size:{tokens.CAPTION}pt; font-weight:400">'
                           f'{n} open task{"" if n == 1 else "s"}{f", {unranked} not ranked" if unranked else ""}</span>')
        self._strip()
        while self.board_layout.count():
            w = self.board_layout.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.cards, self.rows = {}, {}
        for col in self.columns:
            self.board_layout.addWidget(Column(self, col), 1)
        held = self._widget(self.sel)
        if had_focus and held is not None:
            held.setFocus(Qt.FocusReason.OtherFocusReason)

    def _widget(self, task_id: str | None) -> QWidget | None:
        """The selected task's card, or its first row in an open card."""
        if not task_id:
            return None
        if task_id in self.cards:
            return self.cards[task_id]
        return next((r for r in self.rows.get(task_id, []) if r.holder in self.opened), None)

    def _family(self, card: Card, t: Task) -> None:
        """A parent's card's line for its subtasks (release 5.137, decisions 552 and 554). In Parents: its opener, how many
        are inside and how many have cards of their own, and the squares; opened, the rows of those inside. In All: how
        many open subtasks it has, and their squares."""
        m = self.model
        assert m is not None
        kids = priorities.open_subtasks(m, t.id)
        if not kids or self.show_what == "work":
            return
        line = QWidget(objectName="prFamily")
        hl = QHBoxLayout(line)
        hl.setContentsMargins(0, 2, 0, 0)
        hl.setSpacing(6)
        squares = self.pips.get(t.id, [])
        if self.show_what == "parents":
            inside = self.folds.get(t.id, [])
            own = [c for c in kids if c in self._shown]
            words = [f"{len(inside)} subtask{'' if len(inside) == 1 else 's'}"] if inside else []
            if own:
                words.append(f"{len(own)} with a card of {'its' if len(own) == 1 else 'their'} own")
            if inside:
                opened = t.id in self.opened
                card.opener = QPushButton(objectName="prOpener")
                card.opener.setIcon(icon(OPENED if opened else CLOSED))
                card.opener.setFixedSize(20, 18)
                card.opener.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                card.opener.setCursor(Qt.CursorShape.PointingHandCursor)
                card.opener.setToolTip("Show the subtasks inside (Space)")
                card.opener.setAccessibleName(f"Show the subtasks inside {t.title}")
                card.opener.clicked.connect(lambda _=False, x=t.id: self.toggle(x))
                hl.addWidget(card.opener)
        else:
            n = len(squares)
            words = [f"{n} open subtask{'' if n == 1 else 's'}" if n == len(kids) else f"{n} of {len(kids)} open subtasks" if n
                     else f"{len(kids)} open subtask{'' if len(kids) == 1 else 's'}"]
        if not words:
            return
        said = QLabel(f'<span style="color:{tokens.colour("text2")}">{esc(" · ".join(words))}</span>')
        said.setWordWrap(True)  # a narrow column wraps it, rather than the card running past the column's edge
        said.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hl.addWidget(said, 1)
        if squares:
            hl.addWidget(Pips(m, squares), 0, Qt.AlignmentFlag.AlignVCenter)
        card.add(line)
        if self.show_what == "parents" and self.folds.get(t.id):
            box = QFrame(objectName="prRows")
            vl = QVBoxLayout(box)
            vl.setContentsMargins(0, 4, 0, 0)
            vl.setSpacing(1)
            for c in self.folds[t.id]:
                row = Row(self, m, m.task(c), self.today, c == self.sel)
                row.holder = t.id
                self.rows.setdefault(c, []).append(row)
                vl.addWidget(row)
            box.setVisible(t.id in self.opened)
            card.rows_box = box
            card.lay.addWidget(box)

    def toggle(self, task_id: str) -> None:
        """Open or close a parent's card in Parents, in place (decision 552). Closed on its selected row, the card is picked."""
        card = self.cards.get(task_id)
        if card is None or card.rows_box is None or card.opener is None:
            return
        opened = task_id not in self.opened
        (self.opened.add if opened else self.opened.discard)(task_id)
        card.rows_box.setVisible(opened)
        card.opener.setIcon(icon(OPENED if opened else CLOSED))
        card.opener.setToolTip("Hide the subtasks inside (Space)" if opened else "Show the subtasks inside (Space)")
        if not opened and self.sel in self.folds.get(task_id, []):
            self.focus_card(task_id)

    def make_card(self, task_id: str) -> Card:
        m = self.model
        assert m is not None
        t = m.task(task_id)
        bits = []
        tile = task_tile.tile(m, t.id, self.today, task_tile.marks(m, self.today))
        if t.urgent:  # Urgent's flag, as on every tile (release 5.138, decision 569); the days are the tile's, at the line's end
            bits.append(f'<span style="color:{tokens.colour("critical")}; font-weight:600">⚑</span>')
        who = ", ".join("Me" if p == self.me else m.person_name(p).split()[0] for p in dict.fromkeys((*t.leads, *t.assignees)))
        if who:
            bits.append(f'<span style="color:{tokens.colour("text2")}">{esc(who)}</span>')
        card = Card(self, t, self._colours.get(t.id, tokens.group_colour(-1)), " &nbsp;".join(bits), path_text(m, t.id), t.id == self.sel, tile)
        self._family(card, t)
        if task_id in self.context:  # shown only for the subtasks folded into it: dimmed, as the task tree's parents are
            card.setProperty("context", True)
            card.setToolTip("Shown for the subtasks inside it; it doesn't match the filters itself")
            card.setAccessibleName(f"{card.accessibleName()}, shown for the subtasks inside it")
        self.cards[task_id] = card
        return card

    def _controls(self) -> None:
        lay = self.controls_layout
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:  # hidden now, deleted once the signal that redraws the view has returned
                w.hide()
                w.deleteLater()
        m = self.model
        assert m is not None
        # Show (release 5.137, decision 550), in place of Fold subtasks: Work, Parents or All, first, as it's the board's
        # mode and the rest are its filters; drawn as the buckets above the board are
        show = QWidget()
        sl = QHBoxLayout(show)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        sl.addWidget(QLabel("Show", objectName="fieldLabel"))
        strip = QWidget(objectName="typeStrip")
        strip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        hl = QHBoxLayout(strip)
        hl.setContentsMargins(2, 2, 2, 2)
        hl.setSpacing(2)
        group = QButtonGroup(strip)
        group.setExclusive(True)
        self.show_buttons = {}
        for key, name, tip in priorities.SHOWS:
            b = QPushButton(name, objectName="subtle")
            b.setCheckable(True)
            b.setChecked(key == self.show_what)
            b.setToolTip(tip)
            b.setAccessibleName(f"Show: {name}")
            b.clicked.connect(lambda _=False, k=key: self._set("show_what", k))
            group.addButton(b)
            self.show_buttons[key] = b
            hl.addWidget(b)
        sl.addWidget(strip)
        lay.addWidget(show)
        choices, sets = people_filter(m)
        people = CheckMenuButton("People", "anyone", choices, self.people, sets)
        people.chosen.connect(lambda values: self._set("people", values))
        lay.addWidget(people)
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, self.labels, sets)
        labels.chosen.connect(lambda values: self._set("labels", values))
        lay.addWidget(labels)
        due = QComboBox()
        due.setAccessibleName("Due")
        for key, label in priorities.DUE_CHOICES:
            due.addItem(f"Due: {label.lower() if key != 'any' else 'any time'}", key)
        due.setCurrentIndex(max(0, due.findData(self.due)))
        due.currentIndexChanged.connect(lambda _: self._set("due", due.currentData()))
        lay.addWidget(due)
        routine = QCheckBox("Show routine")
        routine.setToolTip("Recurring tasks, such as meetings and reports")
        routine.setChecked(self.routine)
        routine.toggled.connect(lambda on: self._set("routine", on))
        lay.addWidget(routine)

    def _set(self, key: str, value) -> None:
        setattr(self, key, value)
        if self.model is not None:
            self.render(self.model, self.today, self.sel, self.me)

    def _strip(self) -> None:
        """The selected card, above the board: where it sits, its dates and people, its status, and the buckets."""
        m = self.model
        t = m.tasks.get(self.sel) if m and self.sel else None
        for w in (self.buckets, self.open_button, self.edit_button):
            w.setVisible(t is not None)
        self.strip.setVisible(t is not None or LOOK.show_help)  # no card, and no sentence about it, until a card is picked
        muted = tokens.colour("text2")
        if t is None or m is None:
            self.strip_text.setText(f'<span style="color:{muted}">{esc(NOTE)}</span>')
            return
        cell = due_cell(t, self.today)
        when = esc(cell.tip) if cell else "No due date"

        def names(ids: list[str]) -> str:
            return ", ".join(esc(m.person_name(p)) for p in ids) or "None"

        status = f'<br><span style="color:{muted}">Status: {esc(clip(t.current_status, 160))}</span>' if t.current_status else ""
        self.strip_text.setText(f"<b>{esc(t.title)}</b> {_chip(t.state, *STATE_COLOURS.get(t.state, ('text2', 'hover')))}{' ' + _urgent() if t.urgent else ''}"
                                f'<br><span style="color:{muted}">{esc(path_text(m, t.id) or "Top-level task")}</span>'
                                f"<br>{when} · Lead: {names(t.leads)} · Assignees: {names(t.assignees)}{status}")
        self.bucket_buttons[t.priority or ""].setChecked(True)

    # ---- choosing and moving ----
    def pick(self, task_id: str) -> None:
        if task_id == self.sel:
            return
        old, self.sel = self.sel, task_id
        for x in (old, task_id):
            for w in [self.cards.get(x or ""), *self.rows.get(x or "", [])]:
                if w is not None:
                    w.setProperty("sel", x == task_id)
                    w.style().unpolish(w)
                    w.style().polish(w)
        self._strip()
        self.picked.emit(task_id)

    def focus_card(self, task_id: str | None) -> None:
        """Pick a card, or a row in an open card, and give it the focus."""
        w = self._widget(task_id)
        if task_id and w is not None:
            self.pick(task_id)
            w.setFocus(Qt.FocusReason.OtherFocusReason)

    def drop(self, task_id: str, bucket: str, before: str | None) -> None:
        self.sel = task_id
        self.moved.emit(task_id, bucket, before)

    def _order(self, ci: int) -> list[str]:
        """A column's cards top to bottom, each open card followed by its rows (release 5.137): what Up and Down go through."""
        out: list[str] = []
        for x in self.columns[ci].ids:
            out.append(x)
            if self.show_what == "parents" and x in self.opened:
                out += self.folds.get(x, [])
        return out

    def _column_of(self, task_id: str) -> int:
        return next((i for i in range(len(self.columns)) if task_id in self._order(i)), -1)

    # ---- Find on the board ----
    def open_find(self) -> None:
        """Ctrl+F: the box above the board, which narrows it as you type."""
        self.find_bar.show()
        self.find_box.setFocus()
        self.find_box.selectAll()

    def close_find(self, render: bool = True) -> None:
        """Esc in the box, or another view: clear it, and the board shows every card again."""
        had = bool(self.find_box.text())
        self.find_box.blockSignals(True)
        self.find_box.clear()
        self.find_box.blockSignals(False)
        self.find_bar.hide()
        self.find_count.clear()
        if render and had and self.model is not None:
            self.render(self.model, self.today, self.sel, self.me)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - the keys, on a card
        if watched is self.find_box and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
            self.close_find()
            card = self.cards.get(self.sel or "")
            (card or self).setFocus()
            return True
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, (Card, Row)):
            self.pick(watched.task_id)
        if event.type() == QEvent.Type.KeyPress and isinstance(watched, (Card, Row)):
            return self.key(event.key(), event.modifiers())  # type: ignore[attr-defined]
        return super().eventFilter(watched, event)

    def key(self, key: int, mods) -> bool:
        """The board's keys, for the selected card or row. True when one was used."""
        if not self.sel:
            return False
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        digit = {Qt.Key.Key_0: "0", Qt.Key.Key_1: "1", Qt.Key.Key_2: "2", Qt.Key.Key_3: "3", Qt.Key.Key_4: "4"}.get(key)
        if digit is not None and not alt:
            self.moved.emit(self.sel, priorities.BY_DIGIT[digit], None)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_task.emit(self.sel)
            return True
        if key == Qt.Key.Key_Space and not alt and self.sel in self.cards and self.cards[self.sel].rows_box is not None:
            self.toggle(self.sel)  # a parent's card in Parents opens and closes (release 5.137)
            return True
        ci = self._column_of(self.sel)
        if ci < 0:
            return False
        ids, order = self.columns[ci].ids, self._order(ci)
        ri = order.index(self.sel)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            if alt:  # within its bucket: a card only, as a row has no place of its own in the column
                if self.columns[ci].key and self.sel in ids:
                    self.nudged.emit(self.sel, step, list(ids))
                return True
            if 0 <= ri + step < len(order):
                self.focus_card(order[ri + step])
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not alt:
            step = -1 if key == Qt.Key.Key_Left else 1
            j = ci + step
            while 0 <= j < len(self.columns):  # the nearest card or row at the same height in the next column that has any
                there = self._order(j)
                if there:
                    self.focus_card(there[min(ri, len(there) - 1)])
                    break
                j += step
            return True
        return False
