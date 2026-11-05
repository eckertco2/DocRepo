"""A task's state from its row (release 5.76, round 7's item 101, decisions 360 to 364).

Wherever a list shows a task's state, the state is a button: a chevron and a backplate on hover say it opens a menu. The
menu has the four states, each with its mark and the current one ticked, and, for a task with open subtasks, "Closed, with
its n open subtasks", which closes every open level below it. Every task row's right-click menu has the same menu as a
State submenu. A pick saves at once, as Edit task does: a status log line as "Browse tool", no capture. ``UndoButton`` takes
it back for ten seconds. ``docrepo.edits.set_states`` makes the change; this module only draws the menus.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPainter
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from docrepo.db import STATES
from docrepo.model import Model
from docrepo.ui import tokens
from docrepo.ui.icons import icon, tinted

#: Each state's mark: its icon, and the colour token it's drawn in (as the task page's marks and the Task view's rows are).
MARKS = {"Not started": ("state-ns", "text2"), "In progress": ("state-ip", "accent"), "Parked": ("state-pk", "parked"), "Closed": ("state-cl", "text2")}
#: How long Undo stays offered after a change (decision 363).
UNDO_MS = 10_000
#: The menu's line for closing a whole branch (decision 364).
BRANCH = "Closed, with its {n} open subtask{s}"


def state_icon(state: str) -> QIcon:
    name, colour = MARKS.get(state, MARKS["Not started"])
    c = tokens.LIGHT[colour]
    return icon(name, c, on=c)


def open_below(model: Model, task_id: str) -> list[str]:
    """Every task below ``task_id``, at every level, that isn't Closed or discarded, in the tree's order: what "Closed, with
    its open subtasks" closes too (decision 364, as mocked)."""
    return [x for x in model.descendants_of(task_id) if x in model.tasks and model.tasks[x].state != "Closed" and not model.tasks[x].discarded]


def can_change(model: Model, task_id: str | None) -> bool:
    """Whether a task's state can be changed from a row: it exists and isn't discarded."""
    t = model.tasks.get(task_id) if task_id else None
    return t is not None and not t.discarded


#: The tick after the current state, and how far it sits from the menu's right edge.
TICK, TICK_INSET = 14, 10


class StateMenu(QMenu):
    """A menu whose ticked action has its tick drawn at the right of its row, as the mock has it: Qt draws no tick beside an
    action that has an icon, and each state has its mark."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        p = QPainter(self)
        scale = self.devicePixelRatioF()
        for a in self.actions():
            if a.isCheckable() and a.isChecked():
                r = self.actionGeometry(a)
                p.drawPixmap(QPoint(r.right() - TICK_INSET - TICK, r.top() + (r.height() - TICK) // 2), tinted("tick", tokens.LIGHT["accent"], TICK, scale))
        p.end()


def state_menu(parent: QWidget | None, model: Model, task_id: str, pick: Callable[[str, bool], None], title: str = "State") -> QMenu:
    """The menu of states for a task: picking one calls ``pick(state, branch)``, where ``branch`` closes its open subtasks too.
    The current state is ticked and is where the keyboard starts. ``title`` names it as a submenu."""
    t = model.task(task_id)
    menu = StateMenu(title, parent)
    menu.setObjectName("stateMenu")
    menu.setToolTipsVisible(True)
    menu.setIcon(state_icon(t.state))
    group = QActionGroup(menu)
    group.setExclusive(True)
    current: QAction | None = None
    for s in STATES:
        a = menu.addAction(state_icon(s), s)
        a.setCheckable(True)
        a.setChecked(s == t.state)
        group.addAction(a)
        a.triggered.connect(lambda _=False, s=s: pick(s, False))
        if s == t.state:
            current = a
    below = open_below(model, task_id)
    if below and t.state != "Closed":
        menu.addSeparator()
        a = menu.addAction(state_icon("Closed"), BRANCH.format(n=len(below), s="" if len(below) == 1 else "s"))
        a.setToolTip("Closes every open task below it too, at every level. One Undo takes them all back.")
        a.triggered.connect(lambda: pick("Closed", True))
    if current is not None:
        menu.setActiveAction(current)
    return menu


def picked_line(model: Model, task_id: str, state: str, others: int) -> str:
    """What the status line says after a pick: "Closed: Order gaskets." or "Closed: Clean up and its 3 open subtasks."."""
    more = f" and its {others} open subtask{'s' if others != 1 else ''}" if others else ""
    return f"{state}: {model.task(task_id).title}{more}."


class UndoButton(QPushButton):
    """Undo beside a status line, for ten seconds after a change it can take back (decision 363). A new message hides it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Undo", parent, objectName="link")
        self.setToolTip("Set the state back. The status log keeps both changes.")
        self._undo: Callable[[], None] | None = None
        self._timer = QTimer(self, singleShot=True, interval=UNDO_MS, timeout=self.forget)
        self.clicked.connect(self._run)
        self.hide()

    def offer(self, undo: Callable[[], None]) -> None:
        self._undo = undo
        self.show()
        self._timer.start()

    def forget(self) -> None:
        self._undo = None
        self._timer.stop()
        self.hide()

    def _run(self) -> None:
        undo, self._undo = self._undo, None
        self.forget()
        if undo is not None:
            undo()
