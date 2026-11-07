"""The task picker (release 5.103): a box to search, and under it the `#` list's rows, matching and levels (``task_list``), with
Recent and None at the top. It opens as a popup, under the button or the box that opened it.

Before anything is typed it lists the last tasks captures were saved to (Recent), the picker's None entry, then the top-level
tasks (Tasks). Right goes into a task's open subtasks, under the task itself, and Left comes back out, as in the `#` list.
Typing lists the tasks that match, up to 12, each with its path, as the `#` list finds them: words anywhere in a name, in any
order, from the start of a word, and on the task's path. Up and Down move, Enter or Tab picks the row that's current (the
first, until you move), a click picks a row, and Esc closes it.

Parked, closed and discarded tasks are left out of Recent's and the tree's rows; search still finds parked ones, marked
"(parked)", and, with ``closed_too`` (Task search), closed ones, marked "(closed)". ``keep``, a caller's own test of a task's
ID, leaves out what it can't take, everywhere in the list.

It replaces phase 3's cascading menus, where hovering a task showed its subtasks. What its callers use is as it was: the
constructor, ``picked``, ``aboutToShow`` and ``aboutToHide``, ``popup``, ``pick``, ``closed_too``, ``hint`` and ``no_match``.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QVBoxLayout, QWidget

from docrepo import items
from docrepo.model import Model
from docrepo.schedule import is_open
from docrepo.ui.task_list import Row, TaskList, Words, subtask_options, task_mark

RECENT_COUNT = 5
SEARCH_LIMIT = 12
#: The picker's list: as wide as its widest row, between these (or wider, to the caller's minimum), and this many rows in view
#: before it scrolls.
LIST_MIN_W, LIST_MAX_W, LIST_ROWS = 300, 560, 14


def path_text(model: Model, task_id: str) -> str:
    """The task's first chain of parents, such as "Reactor impeller upgrade › Installation"."""
    return " › ".join(model.task(x).title for x in model.chains_of(task_id)[0][:-1])


def full_path(model: Model, task_id: str) -> str:
    return " › ".join(model.task(x).title for x in model.chains_of(task_id)[0])


def recent_tasks(model: Model) -> list[str]:
    """The last tasks captures were saved to, newest first, leaving out closed ones."""
    out: list[str] = []
    for c in sorted(model.live_captures(), key=lambda c: c.saved, reverse=True):
        tasks = model.capture_tasks(c)
        if tasks and model.task(tasks[0]).state != "Closed" and not model.task(tasks[0]).discarded and tasks[0] not in out:
            out.append(tasks[0])
        if len(out) == RECENT_COUNT:
            break
    return out


class TaskPicker(QFrame):
    """The picker's popup. ``picked`` sends a task ID, or None for the None entry. ``modifiers`` holds the keys held with
    Enter, for a caller that does something else on Ctrl+Enter (Task search)."""

    picked = Signal(object)
    aboutToShow = Signal()  # as a menu's, which the picker was
    aboutToHide = Signal()

    def __init__(self, parent: QWidget | None, model_fn: Callable[[], Model], none_entry: tuple[str, str] | None = ("None", "Keep it unfiled"),
                 keep: Callable[[str], bool] | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("taskPicker")
        self._model_fn = model_fn
        self.none_entry = none_entry
        self.keep = keep
        # Task search (release 5.42, decision 213): it also finds closed tasks, says what Enter does, and offers Search
        # everything when nothing matches.
        self.closed_too = False
        self.hint = ""
        self.no_match: Callable[[str], None] | None = None
        self.modifiers = Qt.KeyboardModifier.NoModifier
        self.model = model_fn()
        self._at = QPoint()
        self._none: items.Option | None = None
        self._everything: items.Option | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and IDs")
        self.search.setAccessibleName("Search tasks")
        self.search.textChanged.connect(self._refill)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.note = QLabel(objectName="hint")  # the hint: what Enter does, in Task search
        self.note.setContentsMargins(4, 0, 4, 0)
        self.note.hide()
        layout.addWidget(self.note)
        self.list = TaskList(self)
        self.list.setObjectName("taskPickerList")
        self.list.max_rows = LIST_ROWS
        self.list.subtasks = self._subtasks
        self.list.task_info = lambda ref: task_mark(self.model, ref)
        self.list.picked.connect(self._chosen)
        self.list.refitted.connect(self._place)
        layout.addWidget(self.list)

    # ---- opening and closing ----
    def popup(self, at: QPoint) -> None:
        """Open with its top left at ``at``, a point on the screen, kept on the screen, as a menu does."""
        self._at = QPoint(at)
        self.aboutToShow.emit()
        self._opening()
        self.show()  # a popup takes the keyboard without taking the window's place, as a menu does
        self._place()
        self.raise_()
        self.search.setFocus()

    def _opening(self) -> None:
        self.model = self._model_fn()
        self.modifiers = Qt.KeyboardModifier.NoModifier
        self.note.setText(self.hint)
        self.note.setVisible(bool(self.hint))
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._refill()
        self.search.setFocus()

    def _place(self) -> None:
        """Its size from the list's, under the point it opened at and kept on that screen."""
        if not self.isVisible():
            return
        self.adjustSize()
        screen = QGuiApplication.screenAt(self._at) or self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self._at.x(), area.left() + area.width() - self.width()))
        y = max(area.top(), min(self._at.y(), area.top() + area.height() - self.height()))
        self.move(x, y)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.aboutToHide.emit()
        super().hideEvent(event)

    # ---- what it lists ----
    def _kept(self, task_id: str) -> bool:
        return self.keep is None or self.keep(task_id)

    def _findable(self, task_id: str) -> bool:
        t = self.model.task(task_id)
        return not t.discarded and (self.closed_too or t.state != "Closed") and self._kept(task_id)

    def _option(self, task_id: str) -> items.Option:
        """A task's row: its name, marked when it's parked or closed, with its path as its grey part."""
        t = self.model.task(task_id)
        words = t.title + (" (parked)" if t.state == "Parked" else "") + (" (closed)" if t.state == "Closed" else "")
        return items.Option(t.title, words, path_text(self.model, task_id) or "Top-level task", ref=task_id)

    def _subtasks(self, task_id: str) -> list[items.Option]:
        """A task's open subtasks, for Right: Not started or In progress, and kept."""
        return subtask_options(self.model, task_id, lambda k: is_open(k) and self._kept(k.id))

    def list_rows(self, query: str) -> list[Row]:
        """The rows for what's typed: the matches; or, with nothing typed, Recent, None and the top-level tasks."""
        m = self.model
        self._none = self._everything = None
        if query:
            found = items.task_matches(query, [(t.id, t.title) for t in m.tasks.values() if self._findable(t.id)],
                                       lambda i: items.ancestor_titles(m, i))
            rows: list[Row] = [self._option(x) for x in found[:SEARCH_LIMIT]]
            if not rows and self.no_match is not None:
                self._everything = items.Option(query, f"No task matches. Search everything for “{query}”")
                rows = [self._everything]
            elif not rows:
                rows = [Words("No open or parked task matches.", heading=False)]
            return rows
        rows = []
        recent = [x for x in recent_tasks(m) if self._kept(x)]
        if recent:
            rows.append(Words("Recent"))
            rows += [self._option(x) for x in recent]
        if self.none_entry:
            title, note = self.none_entry
            self._none = items.Option("", title, note)
            rows.append(self._none)
        tops = [t.id for t in m.top_level() if is_open(t) and self._kept(t.id)]
        if tops:
            rows.append(Words("Tasks"))
            rows += [self._option(x) for x in tops]
        return rows or [Words("No open tasks.", heading=False)]

    def _refill(self) -> None:
        self.ensurePolished()  # the style sheet's border is in frameWidth only once it's polished
        inner =self.minimumWidth() - 2 * self.frameWidth() - self.layout().contentsMargins().left() - self.layout().contentsMargins().right()
        self.list.min_width = max(LIST_MIN_W, inner)
        self.list.max_width = max(LIST_MAX_W, self.list.min_width)
        self.list.show_rows(self.list_rows(self.search.text().strip()))

    def rows(self) -> list[Row]:
        """The rows showing: a level's header first when one is open."""
        return self.list.rows()

    # ---- keys and picks ----
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        """The search box keeps the keyboard; the list takes the keys it uses (Right and Left only when they do something)."""
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self.modifiers = event.modifiers()
                self._pick_first()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Right, Qt.Key.Key_Left) and self.list.handle_key(key):
                return True
        return super().eventFilter(watched, event)

    def _pick_first(self) -> None:
        """Enter: the row that's current, or the first; Search everything when nothing matches."""
        o = self.list.current()
        if o is not None:
            self._chosen(o)
        elif self.no_match is not None and self.search.text().strip():
            self._search_everything()

    def _chosen(self, o: Row) -> None:
        if o.ref:
            self.pick(o.ref)
        elif self._everything is not None and o == self._everything:
            self._search_everything()
        elif self._none is not None and o == self._none:
            self.pick(None)

    def _search_everything(self) -> None:
        text = self.search.text().strip()
        self.close()
        self.no_match(text)

    def type_into_search(self, text: str) -> None:
        self.search.setFocus()
        self.search.insert(text)

    def pick(self, task_id: str | None) -> None:
        self.close()
        self.picked.emit(task_id)
