"""The task list (release 5.103): the `#` list's rows and levels as one component, so every place a task is picked from a list
is the same code. The `@` and `#` list (``items_panel.RefPopup``) is one; the task picker (``task_picker.TaskPicker``, in the
capture window, the browse window, Find files, Task search and the Timeline's Focus on) holds another.

- **Rows** (release 5.75, round 7's decisions 327 to 330): a leading 8 px slot, holding a top-level task's filled dot in its
  colour, with its name in Semibold, or a ring in its top-level task's colour for every other task. A task with open
  subtasks ends with how many, then the chevron, which has a backplate under the pointer. A person's row (``@``) has no slot.
- **Levels** (release 5.65, decisions 311 and 312): Right on a task with open subtasks lists them under the task itself, as a
  header row with its mark and the back chevron, the subtasks indented 16 px; Left goes back up.
- **Keys** (``handle_key``): Up and Down move, passing over a row that can't be picked (a section's heading); Right and Left
  go into a level and back out, and are the list's only when they do something there; Enter or Tab picks. Esc is the
  owner's: the `#` list hides, the picker closes.
- **Matching** is ``items.task_matches``: words anywhere in a name, in any order, from the start of a word, and on the task's
  path, the names that start with what's typed first (release 5.74, decisions 325 and 326).

What each place lists, and what a pick does, stays the place's own: the list shows the rows it's given, and ``subtasks``
gives a task's rows for Right.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from docrepo import items
from docrepo.task_tile import fit_title
from docrepo.model import Model, Task
from docrepo.ui import tokens
from docrepo.ui.icons import tinted

#: The `#` list's sizes (release 5.65, decision 310): as wide as its longest row, between these, and this many rows in view
#: before it scrolls. It never scrolls sideways: a scroll bar there hid a lone row's name.
MIN_W, MAX_W, ROWS = 320, 480, 8
#: The grey part of a row gives way down to this before the name is shortened.
SUB_MIN = 48
#: A row's ``items.Option`` (or ``Words``), and whether it's a level's header.
OPTION_ROLE, HEAD_ROLE = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class Words:
    """A row that can't be picked: a section's heading, such as "Recent", or a line, such as "No open or parked task
    matches.". Up and Down pass over it. ``sub`` and ``ref`` let it be read as an ``items.Option`` is."""

    label: str
    heading: bool = True
    sub: str = ""
    ref: None = None


Row = items.Option | Words


def can_pick(o: Row | None) -> bool:
    return isinstance(o, items.Option)


def task_colour(m: Model, task_id: str | None) -> str:
    """A task's top-level task's colour: the task tree's group colours, in turn, as the timeline gives them (decision 9)."""
    if not task_id or task_id not in m.tasks:
        return tokens.colour("stroke_strong")
    top = m.chains_of(task_id)[0][0]
    order = [t.id for t in m.top_level()]
    return tokens.group_colour(order.index(top)) if top in order else tokens.colour("stroke_strong")


def task_mark(m: Model, task_id: str) -> tuple[bool, str] | None:
    """A task's mark in a list (release 5.75, round 7's decisions 327 and 328): whether it's top-level, and its top-level
    task's colour, as the task tree and the timeline give it."""
    if task_id not in m.tasks:
        return None
    return not m.parents_of(task_id), task_colour(m, task_id)


def subtask_options(m: Model, task_id: str, keep: Callable[[Task], bool]) -> list[items.Option]:
    """A task's subtasks that ``keep`` lets through, in the tree's order, for Right (release 5.65, decision 311). They have no
    grey path: the task they're under heads the list, and each one's tooltip has the whole path."""
    if task_id not in m.tasks:
        return []
    kids = (m.task(x) for x in m.children_of(task_id))
    return [items.Option(k.title, k.title, ref=k.id) for k in kids if keep(k)]


class TaskRowDelegate(QStyledItemDelegate):
    """A row of a task list: its name in the Body font, then its grey part (a task's path, a person's aliases) in the Caption
    size, the grey part shortened in its middle before the name is shortened at its end.

    A task's row starts with its mark in an 8 px slot, so names line up: a top-level task's filled dot in its colour, with
    its name in Semibold and no grey part ("Top-level task" is in its tooltip), or another task's ring in its top-level
    task's colour. In a list of tasks, an entry that isn't a task (the picker's None) keeps the slot empty, so its name lines
    up too. A task with open subtasks ends with how many, then the chevron (Right goes into them), which has a backplate
    under the pointer. Inside a level, the task heading it is a header row: a faint fill, a hairline under it, the back
    chevron (Left goes back up), and how many open subtasks it has; its subtasks are indented 16 px, the task tree's indent.
    A section's heading is grey Caption Semibold, and a line that can't be picked is grey."""

    PAD, GAP, CHEV, SLOT, INDENT = 8, 12, 20, 8, 16

    def __init__(self, popup: TaskList) -> None:
        super().__init__(popup)
        self.popup = popup
        self.font = tokens.ui_font(tokens.BODY)
        self.bold = tokens.ui_font(tokens.BODY, semibold=True)
        self.small = tokens.ui_font(tokens.CAPTION)
        self.small_bold = tokens.ui_font(tokens.CAPTION, semibold=True)

    def row_height(self) -> int:
        return max(28, QFontMetrics(self.font).height() + 8)

    def parts(self, o: Row, head: bool) -> tuple[tuple[bool, str] | None, bool, str, str]:
        """What a row shows beside its name: its mark ((top-level, colour), or None for a person), whether it's indented
        under a level's header, its grey part, and the words at its right end."""
        if isinstance(o, Words):
            return None, False, "", ""
        p = self.popup
        mark = p.mark(o)
        kid = p.depth > 0 and not head
        n = p.kids(o)
        if head:
            return mark, False, "", f"{n} open subtask{'s' * (n != 1)}" if n else ""
        top = bool(mark and mark[0])
        return mark, kid, "" if top or kid else o.sub, str(n) if n else ""

    def slot(self, o: Row, mark: tuple[bool, str] | None) -> bool:
        """Whether the row has the 8 px slot: a task's, or an entry of a list of tasks that isn't one."""
        return mark is not None or (self.popup.task_info is not None and can_pick(o) and not o.ref)

    def name_font(self, o: Row, head: bool):
        if isinstance(o, Words):
            return self.small_bold if o.heading else self.font
        mark = self.popup.mark(o)
        return self.bold if head or (mark and mark[0]) else self.font

    def natural_width(self, o: Row, head: bool) -> int:
        """The row's width with nothing shortened."""
        mark, kid, sub, right = self.parts(o, head)
        fs = QFontMetrics(self.small)
        w = 2 * self.PAD + 4 + QFontMetrics(self.name_font(o, head)).horizontalAdvance(o.label)  # 4 px to spare
        w += (self.INDENT if kid else 0) + (self.CHEV if head else 0) + (self.SLOT + 8 if self.slot(o, mark) else 0)
        if sub:
            w += self.GAP + fs.horizontalAdvance(sub)
        if right:
            w += self.GAP + fs.horizontalAdvance(right) + (0 if head else 4 + self.CHEV)
        return w

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        return QSize(1, self.row_height())  # as wide as the list, never wider

    def _plate(self, p: QPainter, box: QRect) -> None:
        """The backplate under a chevron the pointer is on: it's a button."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tokens.colour("hover")))
        p.drawRoundedRect(box, 4, 4)

    def _words(self, p: QPainter, o: Words, rect: QRect) -> None:
        """A row that can't be picked: no hover, no selection, its words in grey."""
        f = self.name_font(o, False)
        fm = QFontMetrics(f)
        base = int(rect.top() + (rect.height() + fm.ascent() - fm.descent()) / 2)
        left = rect.left() + self.PAD
        room = max(0, rect.width() - 2 * self.PAD)
        p.save()
        p.setFont(f)
        p.setPen(QColor(tokens.colour("text2")))
        p.drawText(QPoint(left, base), o.label if fm.horizontalAdvance(o.label) <= room else fm.elidedText(o.label, Qt.TextElideMode.ElideRight, room))
        p.restore()

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        o: Row = index.data(OPTION_ROLE)
        if isinstance(o, Words):
            self._words(p, o, option.rect)
            return
        head = bool(index.data(HEAD_ROLE))
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        rect = opt.rect
        if head:  # the level's header (decision 330): a faint fill under the style's hover and selection
            p.fillRect(rect, QColor(tokens.colour("base")))
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)  # the row's back and selection, from the style sheet
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if head:
            p.setPen(QPen(QColor(tokens.colour("stroke")), 1))
            p.drawLine(QPointF(rect.left(), rect.bottom() + 0.5), QPointF(rect.left() + rect.width(), rect.bottom() + 0.5))
        mark, kid, sub, right_words = self.parts(o, head)
        left = rect.left() + self.PAD + (self.INDENT if kid else 0)
        right = rect.left() + rect.width() - self.PAD  # QRect.right() is a pixel short of the edge
        mid = rect.top() + rect.height() / 2
        scale = p.device().devicePixelRatioF()
        grey = tokens.colour("text2")
        hot = self.popup.hot
        if head:
            on = hot == (index.row(), "back")
            if on:
                self._plate(p, QRect(left - 5, int(mid - self.CHEV / 2), self.CHEV, self.CHEV))
            p.drawPixmap(QPoint(left - 2, int(mid - 7)), tinted("chevron-left", tokens.colour("text") if on else grey, 14, scale))
            left += self.CHEV
        if mark:  # decisions 327 and 328: a dot for a top-level task, a ring in its top-level task's colour for the rest
            is_top, colour = mark
            centre = QPointF(left + self.SLOT / 2, mid)
            if is_top:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(colour))
                p.drawEllipse(centre, 4, 4)
            else:
                p.setPen(QPen(QColor(colour), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(centre, 2.75, 2.75)  # 7 px across, its 1.5 px line inside
        if self.slot(o, mark):
            left += self.SLOT + 8
        fn, fs = QFontMetrics(self.name_font(o, head)), QFontMetrics(self.small)
        base = int(rect.top() + (rect.height() + fn.ascent() - fn.descent()) / 2)  # every part on one baseline
        if right_words:  # how many open subtasks, then the chevron into them (decision 329)
            if not head:
                box = QRect(right - self.CHEV, int(mid - self.CHEV / 2), self.CHEV, self.CHEV)
                on = hot == (index.row(), "into")
                if on:
                    self._plate(p, box)
                p.drawPixmap(QPoint(box.left() + 3, int(mid - 7)), tinted("chevron-right", tokens.colour("text") if on else grey, 14, scale))
                right -= self.CHEV + 4
            w = fs.horizontalAdvance(right_words)
            p.setFont(self.small)
            p.setPen(QColor(grey))
            p.drawText(QPoint(right - w, base), right_words)
            right -= w + self.GAP
        room = max(0, right - left)
        name_w = fn.horizontalAdvance(o.label)
        sub_w = fs.horizontalAdvance(sub) if sub else 0
        sub_room = 0
        if sub:  # the grey part gives way first, down to SUB_MIN; then the name does
            sub_room = min(sub_w, max(room - name_w - self.GAP, min(sub_w, SUB_MIN)))
            if sub_room < min(sub_w, SUB_MIN) or room - sub_room - self.GAP < fn.horizontalAdvance("…") * 4:
                sub_room = 0
        name_room = room - (sub_room + self.GAP if sub_room else 0)
        # A part that fits is drawn whole: Qt's eliding wants a little more room than the words measure (release 5.64's
        # DropButton found the same), so it would shorten words that fit exactly.
        # A long name is cut as a task tile's is (release 5.138, the task tile plan's decision 574): its first sentence, then its
        # first clause, then at the edge.
        name = o.label if name_w <= name_room else fit_title(o.label, name_room, fn.horizontalAdvance,
                                                                  lambda t, w: fn.elidedText(t, Qt.TextElideMode.ElideRight, int(w)))
        p.setFont(self.name_font(o, head))
        p.setPen(QColor(tokens.colour("text")))
        p.drawText(QPoint(left, base), name)
        if sub_room:
            shown = sub if sub_w <= sub_room else fs.elidedText(sub, Qt.TextElideMode.ElideMiddle, sub_room)
            p.setFont(self.small)
            p.setPen(QColor(grey))
            p.drawText(QPoint(left + fn.horizontalAdvance(name) + self.GAP, base), shown)
        p.restore()


class TaskList(QListWidget):
    """The rows, their levels and their keys; see the module's notes. ``show_rows`` lists a place's rows (at the top, with
    no level open), ``handle_key`` takes a key the place's text box was given, and ``picked`` sends the row picked."""

    picked = Signal(object)  # the row's items.Option
    #: Its size changed with its rows: a place that holds it lays itself out again.
    refitted = Signal()

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.delegate = TaskRowDelegate(self)
        self.setItemDelegate(self.delegate)
        #: A task's subtasks as rows, for Right; None for a list with no levels (@).
        self.subtasks: Callable[[str], list[items.Option]] | None = None
        #: Whether a task is top-level, and its top-level task's colour (release 5.75); None for a list of people.
        self.task_info: Callable[[str], tuple[bool, str] | None] | None = None
        #: Its width's limits, and how many rows show before it scrolls.
        self.min_width, self.max_width, self.max_rows = MIN_W, MAX_W, ROWS
        # Each level above this one: its rows, the row it was left from, and the task it was under (None at the top).
        self._levels: list[tuple[list[Row], int, items.Option | None]] = []
        self._kids: dict[str, int] = {}
        self._info: dict[str, tuple[bool, str] | None] = {}
        self._root: str | None = None  # the first task gone into: a level's marks take its colour
        self._under = ""  # the path of the level showing: its head's path and name
        #: The chevron under the pointer, as (row, "into" or "back"), drawn with a backplate.
        self.hot: tuple[int, str] | None = None
        self.setFixedWidth(MIN_W)
        self.itemClicked.connect(self._clicked)

    # ---- what it shows ----
    def kids(self, o: Row | None) -> int:
        """How many open subtasks the row's task has: Right lists them."""
        if o is None or not o.ref or self.subtasks is None:
            return 0
        if o.ref not in self._kids:
            self._kids[o.ref] = len(self.subtasks(o.ref))
        return self._kids[o.ref]

    def opens(self, o: Row | None) -> bool:
        """True when Right on this row would list its task's subtasks."""
        return self.kids(o) > 0

    def _task(self, ref: str) -> tuple[bool, str] | None:
        if ref not in self._info:
            self._info[ref] = self.task_info(ref) if self.task_info is not None else None
        return self._info[ref]

    def mark(self, o: Row | None) -> tuple[bool, str] | None:
        """A task row's mark: (whether it's top-level, its colour). Inside a level, the colour is the first task gone
        into's, so a task with two parents shows the colour of the one it's listed under."""
        if o is None or not o.ref or self.task_info is None:
            return None
        info = self._task(o.ref)
        if info is None:
            return None
        root = self._task(self._root) if self._levels and self._root else None
        return (info[0], root[1]) if root else info

    def show_rows(self, rows: Sequence[Row], row: int = 0) -> None:
        """List ``rows`` at the top, with no level open, the first that can be picked from ``row`` on current."""
        self._levels = []
        self._kids, self._info, self._root, self.hot = {}, {}, None, None
        self._fill(list(rows), row)

    def rows(self) -> list[Row]:
        """The rows showing, a level's header first when one is open."""
        return [self.item(i).data(OPTION_ROLE) for i in range(self.count())]

    def _fill(self, options: list[Row], row: int, head: items.Option | None = None) -> None:
        self.clear()
        self.hot = None
        rows = ([(head, True)] if head is not None else []) + [(o, False) for o in options]
        # A level's rows have no grey part of their own: they're under the task heading the list, named as it is (a picker's
        # row may say "(parked)" after the name).
        under = " › ".join(x for x in ((head.sub if head.ref and head.sub != "Top-level task" else ""), head.value or head.label) if x) if head else ""
        self._under = under
        for o, is_head in rows:
            where = o.sub or ("" if is_head or isinstance(o, Words) else under)
            n = self.kids(o)
            more = f"{n} open subtask{'s' * (n != 1)}" if n else ""
            item = QListWidgetItem(", ".join(x for x in (o.label, where, more) if x))  # what a screen reader says
            item.setData(OPTION_ROLE, o)
            item.setData(HEAD_ROLE, is_head)
            if isinstance(o, Words):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setToolTip("\n".join(x for x in (o.label, where, more) if x))
            self.addItem(item)
        self.setCurrentRow(self._first_from(min(row, max(0, self.count() - 1))))
        self._fit([(o, h) for o, h in rows])

    def _first_from(self, row: int) -> int:
        """The first row from ``row`` on that can be picked, or -1."""
        return next((i for i in range(row, self.count()) if can_pick(self.item(i).data(OPTION_ROLE))), -1)

    def _area(self) -> QRect:
        """Where it must fit: the screen it's on."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _fit(self, rows: list[tuple[Row, bool]]) -> None:
        """Size it to its rows: as wide as the widest row allows, one row tall per row up to ``max_rows``, its frame and
        padding counted as Qt reports them."""
        self.ensurePolished()
        area = self._area()
        frame = 2 * self.frameWidth()
        shown = min(self.max_rows, len(rows))
        bar = self.verticalScrollBar().sizeHint().width() if len(rows) > self.max_rows else 0
        natural = max((self.delegate.natural_width(o, h) for o, h in rows), default=self.min_width) + frame + bar
        self.setFixedSize(max(self.min_width, min(natural, self.max_width, area.width())), shown * self.delegate.row_height() + frame)
        self.refitted.emit()

    # ---- levels ----
    def go_into(self, row: int | None = None) -> bool:
        """List the subtasks of the task on ``row`` (the current one), under it; True when it has any."""
        item = self.item(self.currentRow() if row is None else row)
        o = item.data(OPTION_ROLE) if item is not None else None
        if o is None or bool(item.data(HEAD_ROLE)) or not self.opens(o):
            return False
        if not self._levels:
            self._root = o.ref
        self._levels.append(([self.item(i).data(OPTION_ROLE) for i in range(self.count()) if not self.item(i).data(HEAD_ROLE)],
                             self.row(item), self.item(0).data(OPTION_ROLE) if self.item(0).data(HEAD_ROLE) else None))
        # A level's row has no grey part of its own; as the next level's head it shows where it is.
        self._fill(self.subtasks(o.ref), 1, head=o if o.sub else replace(o, sub=self._under or "Top-level task"))
        return True

    def go_up(self) -> bool:
        """Back to the level above, with the task it came from picked; False at the top."""
        if not self._levels:
            return False
        options, row, head = self._levels.pop()
        if not self._levels:
            self._root = None
        self._fill(options, row, head=head)
        return True

    @property
    def depth(self) -> int:
        """How many levels down the list is: 0 at the top, one more for each task gone into."""
        return len(self._levels)

    def chevron_at(self, pos: QPoint) -> tuple[int, str] | None:
        """The chevron at ``pos`` in the viewport, as (row, "into" or "back"), or None."""
        item = self.itemAt(pos)
        if item is None:
            return None
        x, d = pos.x(), self.delegate
        if item.data(HEAD_ROLE):
            return (self.row(item), "back") if x < d.PAD + d.CHEV else None
        if self.opens(item.data(OPTION_ROLE)) and x > self.viewport().width() - d.PAD - d.CHEV:
            return self.row(item), "into"
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        hot = self.chevron_at(event.position().toPoint())
        if hot != self.hot:
            self.hot = hot
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor)
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.hot is not None:
            self.hot = None
            self.viewport().unsetCursor()
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """A row's chevron goes into its subtasks, and the back chevron goes up; a click anywhere else picks the row."""
        if event.button() == Qt.MouseButton.LeftButton:
            hot = self.chevron_at(event.position().toPoint())
            if hot and hot[1] == "back":
                self.go_up()
                return
            if hot and hot[1] == "into" and self.go_into(hot[0]):
                return
        super().mousePressEvent(event)

    def _clicked(self, item: QListWidgetItem) -> None:
        o = item.data(OPTION_ROLE)
        if can_pick(o):
            self.picked.emit(o)

    # ---- keys ----
    def step(self, by: int) -> None:
        """Up or Down a row, round from the end to the start, passing over a row that can't be picked."""
        n = self.count()
        row = self.currentRow()
        for _ in range(n):
            row = (row + by) % n
            if can_pick(self.item(row).data(OPTION_ROLE)):
                self.setCurrentRow(row)
                return

    def current(self) -> Row | None:
        """The row Enter would pick: the current one, or the first that can be picked."""
        item = self.currentItem()
        if item is not None and can_pick(item.data(OPTION_ROLE)):
            return item.data(OPTION_ROLE)
        first = self._first_from(0)
        return self.item(first).data(OPTION_ROLE) if first >= 0 else None

    def handle_key(self, key: int) -> bool:
        """A key typed in the place's text box; True when the list used it. Right and Left are the list's only when they do
        something there (decision 312): otherwise they move the cursor, as before."""
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.step(1 if key == Qt.Key.Key_Down else -1)
            return True
        if key == Qt.Key.Key_Right:
            return self.go_into()
        if key == Qt.Key.Key_Left:
            return self.go_up()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            o = self.current()
            if o is not None:
                self.picked.emit(o)
            return True
        return False
