"""The task picker: cascading menus of open tasks, with search, Recent and None at the top.

Hovering a task shows its subtasks; clicking a task picks it, even when it has
subtasks (Qt menus normally only open the submenu, so these menus pick on click
and on Enter). Typing switches to a flat list of matching tasks with their paths,
which keeps it keyboard-only. Parked, closed and discarded tasks are hidden, but
search still finds parked ones.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QLineEdit, QMenu, QWidget, QWidgetAction

from docrepo.model import Model
from docrepo.schedule import is_open

RECENT_COUNT = 5
SEARCH_LIMIT = 12


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


class _Menu(QMenu):
    """A menu of tasks whose submenu items can be picked by clicking or pressing Enter."""

    def __init__(self, picker: TaskPicker, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.picker = picker
        self.setToolTipsVisible(True)

    def add_task(self, task_id: str, with_path: bool = False) -> QAction:
        m = self.picker.model
        t = m.task(task_id)
        text = t.title + (" ↻" if t.recurrence else "") + (" (parked)" if t.state == "Parked" else "")
        if with_path:
            text += f"   ·   {path_text(m, task_id) or 'Top-level task'}"
        kids = [k for k in m.children_of(task_id) if is_open(m.task(k))] if not with_path else []
        if kids:
            sub = _Menu(self.picker, self)
            sub.setTitle(text)
            sub.aboutToShow.connect(lambda sub=sub, kids=kids: sub.fill(kids))
            action = sub.menuAction()
            self.addAction(action)
        else:
            action = self.addAction(text)
            action.triggered.connect(lambda _=False, t=task_id: self.picker.pick(t))
        action.setData(task_id)
        action.setToolTip(full_path(m, task_id))
        return action

    def fill(self, task_ids: list[str]) -> None:
        if self.actions():
            return
        for k in task_ids:
            self.add_task(k)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        action = self.actionAt(event.position().toPoint())
        if action is not None and action.menu() is not None and action.data():
            self.picker.pick(action.data())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        action = self.activeAction()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and action is not None and action.menu() is not None and action.data():
            self.picker.pick(action.data())
            return
        if event.text() and event.text().isprintable() and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self.picker.type_into_search(event.text())  # typing switches to search
            return
        super().keyPressEvent(event)


class TaskPicker(_Menu):
    """The picker's top menu. ``picked`` sends a task ID, or None for the None entry."""

    picked = Signal(object)

    def __init__(self, parent: QWidget | None, model_fn: Callable[[], Model], none_entry: tuple[str, str] | None = ("None", "Keep it unfiled")) -> None:
        super().__init__(self, parent)
        self._model_fn = model_fn
        self.none_entry = none_entry
        self.model = model_fn()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and IDs")
        self.search.textChanged.connect(self._refill)
        self.search.returnPressed.connect(self._pick_first)
        self.search.installEventFilter(self)
        action = QWidgetAction(self)
        action.setDefaultWidget(self.search)
        self.addAction(action)
        self._search_action = action
        self.aboutToShow.connect(self._opening)

    def _opening(self) -> None:
        self.model = self._model_fn()
        self.search.clear()
        self._refill()
        self.search.setFocus()

    def _clear(self) -> None:
        for action in self.actions():
            if action is not self._search_action:
                self.removeAction(action)
                if action.menu() is not None:
                    action.menu().deleteLater()

    def _refill(self) -> None:
        self._clear()
        m = self.model
        query = self.search.text().strip().lower()
        if query:
            matches = [t for t in m.tasks.values() if t.state != "Closed" and not t.discarded and (query in t.title.lower() or query in t.id.lower())]
            for t in matches[:SEARCH_LIMIT]:
                self.add_task(t.id, with_path=True)
            if not matches:
                self.addAction("No open or parked task matches.").setEnabled(False)
            return
        recent = recent_tasks(m)
        if recent:
            self.addSection("Recent")
            for task_id in recent:
                self.add_task(task_id, with_path=True)
        if self.none_entry:
            title, note = self.none_entry
            none = self.addAction(f"{title}: {note}")
            none.triggered.connect(lambda: self.pick(None))
        self.addSection("Tasks")
        for t in m.top_level():
            if is_open(t):
                self.add_task(t.id)

    def _pick_first(self) -> None:
        first = next((a for a in self.actions() if a is not self._search_action and a.data()), None)
        if first is not None:
            self.pick(first.data())

    def type_into_search(self, text: str) -> None:
        self.search.setFocus()
        self.search.insert(text)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.search and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Down:
            first = next((a for a in self.actions() if a is not self._search_action and a.isEnabled() and not a.isSeparator()), None)
            if first is not None:
                self.setFocus()
                self.setActiveAction(first)
                return True
        return super().eventFilter(watched, event)

    def pick(self, task_id: str | None) -> None:
        for menu in self.findChildren(QMenu):
            menu.hide()
        self.close()
        self.picked.emit(task_id)
