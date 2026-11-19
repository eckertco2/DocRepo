"""The current task in the browse window and on Today (release 5.177, the design workspace's docs/mods/current-task-plan.md,
decisions 826 to 829). What's kept is ``docrepo.current``; this module is what the owner sees and does with it.

- ``work_on``: **Work on it** (the tile menu's line, the W key, the page's action) makes the task current and opens its
  workspace (decision 826). A plain open (a double-click, Enter, Task search, a link) changes nothing.
- ``stop``: **Stop working on it**, the first line of the current task's own menu (decision 827).
- ``back_to_it``: the command ``current.open`` and the hotkey ``current_hotkey``: the current task's workspace, the
  browse window in front, or a line saying there's none (decision 829).
- ``add_now_view`` and ``add_now_panel``: on Today, first, under **Now**, the current task's row with **Log progress** and
  **Workspace** always shown under its title, whether or not it's on Today, and shown once (decision 828).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docrepo import current
from docrepo.model import TODAY

if TYPE_CHECKING:
    from datetime import date

    from docrepo.model import Model
    from docrepo.ui.browse_window import BrowseWindow

#: The heading over it, and what the command says with no current task (decision 829).
NOW = "Now"
NONE_YET = "No current task. Use Work on it on a task."
STOP = "Stop working on it"
LOG = "Log progress"
WORKSPACE = "Workspace"


def now_task(browse: BrowseWindow, m: Model | None = None) -> str | None:
    """The current task's ID, or None (``current.get``: one ``app_state`` read)."""
    return current.get(browse.conn, m if m is not None else browse.model())


def work_on(browse: BrowseWindow, task_id: str) -> None:
    """Work on it (decision 826): the task becomes the current one, in the place of the one before, and its workspace opens.
    A collection can't be current: it opens at its workspace as before, with nothing kept."""
    from docrepo.ui import workspace as workspace_ui

    t = browse.model().tasks.get(task_id)
    if t is None or t.discarded:
        return
    if not t.collection and t.state != "Closed":
        current.start(browse.conn, task_id)
    workspace_ui.open_workspace(browse, task_id)
    _redraw(browse)


def stop(browse: BrowseWindow, task_id: str | None = None) -> None:
    """Stop working on it (decision 827): no current task. With ``task_id``, only when that's the current one."""
    if task_id is None or current.stored(browse.conn) == task_id:
        current.stop(browse.conn)
        browse.say("Not working on a task now.")
        _redraw(browse)


# ---- the workspace's bar (decision 826) ----
WORK_ON_THIS = "Work on this"
WORKING_ON_THIS = "Working on this"


def bar_toggle(w) -> QPushButton:
    """The workspace bar's toggle: **Work on this** while the task acted on isn't the current one, **Working on this**
    (pressed) while it is. A press makes it current, or, pressed again, stops it."""
    from docrepo.ui.icons import icon
    from docrepo.ui.look import LOOK

    b = QPushButton(WORK_ON_THIS, objectName="subtle")
    b.setCheckable(True)
    if not LOOK.classic:
        b.setIcon(icon("workspace"))
    b.clicked.connect(lambda on: _toggled(w, on))
    return b


def sync_toggle(w) -> None:
    """The toggle as it is now, for the task the workspace acts on. Hidden for a collection, which can't be current."""
    b = getattr(w, "current_button", None)
    if b is None:
        return
    m = w.browse.model()
    task_id = w.acting
    t = m.tasks.get(task_id)
    on = current.get(w.browse.conn, m) == task_id
    b.setVisible(t is not None and not t.collection)
    b.blockSignals(True)
    b.setChecked(on)
    b.blockSignals(False)
    b.setText(WORKING_ON_THIS if on else WORK_ON_THIS)
    b.setToolTip("The task you're working on, first on Today under Now: press to stop" if on
                 else "Make it the task you're working on: first on Today under Now, and the hotkey comes back to it")


def _toggled(w, on: bool) -> None:
    browse, task_id = w.browse, w.acting
    if on:
        current.start(browse.conn, task_id)
        browse.say("Working on it: it's first on Today under Now.")
    else:
        current.stop(browse.conn)
        browse.say("Not working on a task now.")
    browse.ctx.today_changed()
    sync_toggle(w)


def _redraw(browse: BrowseWindow) -> None:
    """Today as it is now, in the side panel, and in the browse window when it shows Today."""
    from docrepo.ui import workspace as workspace_ui

    browse.ctx.today_changed()
    if browse.view == TODAY and not workspace_ui.is_open(browse):
        browse.render_list()


def back_to_it(browse: BrowseWindow) -> bool:
    """Back to the task you're working on (decision 829): its workspace, the browse window in front (release 5.165's
    decision 771). With none, says so where the owner is looking, the browse window brought forward. True when it opened."""
    from docrepo.ui import workspace as workspace_ui

    task_id = now_task(browse)
    if task_id is None:
        if not browse.isVisible():
            browse.show_browse()
        from docrepo.ui.front import bring_to_front

        bring_to_front(browse)
        browse.say(NONE_YET)
        return False
    workspace_ui.open_workspace(browse, task_id)
    return True


def _buttons(browse: BrowseWindow, task_id: str, name: str, link: str, left: int = 28) -> QWidget:
    """Log progress and Workspace, under the current task's title, always shown (decision 828)."""
    from docrepo.ui import workspace as workspace_ui

    box = QWidget(objectName=name)
    lay = QHBoxLayout(box)
    lay.setContentsMargins(left, 0, 2, 2)  # under the title in the view; at the panel's narrow rest, from its edge
    lay.setSpacing(4)
    for label, tip, do in ((LOG, "A line of what you did, who you're waiting on and when to follow up: on this task",
                            lambda: browse.ctx.log_progress(task_id)),
                           (WORKSPACE, "Its workspace, to do the work", lambda: workspace_ui.open_workspace(browse, task_id))):
        b = QPushButton(label, objectName=link)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(do)
        lay.addWidget(b)
    lay.addStretch()
    return box


# ---- the Today view (``TodayList._today_view``) ----
def add_now_view(lists, m: Model, today: date) -> str | None:
    """Now on the Today view (decision 828): a heading in the accent colour, the current task's tile row (the accent edge
    and the ``now`` ground, ``tree_view.NOW_ROLE``), and a row under it with the two buttons. Returns the current task, for
    the bands to leave out; None, and nothing drawn, with no current task."""
    from docrepo.detail import esc
    from docrepo.ui import tokens
    from docrepo.ui.lists.common import _shape, tile_cells
    from docrepo.ui.tree_view import NOW_ROLE

    task_id = now_task(lists, m)
    if task_id is None:
        return None
    t = m.task(task_id)
    on_today = next((a for a in m.today_items() if a.subject == task_id), None)
    head = lists.tree.add_row(None, None, [f'<span style="color:{tokens.colour("accent")}; font-weight:600">{NOW}</span>'],
                              selectable=False, span=True, tip="The task you're working on: Work on it on a task makes it so")
    line, days = tile_cells(m, task_id, today, context="" if on_today else "not on Today", flat=True, hide=("today",))
    item = lists.tree.add_row(head, ("task", task_id), _shape([line, "", days]), tip=f"Working on {esc(t.title)}")
    item.setData(0, NOW_ROLE, True)
    if on_today is not None:
        lists.tree.set_actions(item, lists._today_actions(on_today.id, task_id))
    under = lists.tree.add_row(head, None, [""], selectable=False, span=True)
    lists.tree.setItemWidget(under, 0, _buttons(lists, task_id, "nowButtons", "link"))
    head.setExpanded(True)
    return task_id


# ---- the side panel (``TodayPanel.refresh``) ----
def add_now_panel(panel, m: Model, today: date) -> str | None:
    """Now in the Today side panel (decision 828): a heading in the accent colour, the current task's row (a Today row:
    its tick, menu and double-click, but not dragged and not among the keyboard's rows), and Log progress and Workspace
    under its title, at rest and widened. Returns the current task, for the bands to leave out."""
    from docrepo import task_tile
    from docrepo.ui import today_panel as tp

    task_id = now_task(panel.browse, m)
    if task_id is None:
        return None
    t = m.task(task_id)
    on_today = next((a for a in m.today_items() if a.subject == task_id), None)
    box = QWidget(objectName="tpNow")
    box.setProperty("now", True)
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(3, 2, 0, 2)
    lay.setSpacing(0)
    heading = QLabel(NOW, objectName="tpNowHead")
    heading.setToolTip("The task you're working on: Work on it on a task makes it so")
    lay.addWidget(heading)
    tile = task_tile.tile(m, task_id, today, task_tile.marks(m, today), hide=("today",), flat=True)
    row = NowRow(panel, on_today.id if on_today else None, task_id, t.title, "" if on_today else "Not on Today", None, t.state,
                 tp.edge_of(t), tile)
    lay.addWidget(row)
    lay.addWidget(_buttons(panel.browse, task_id, "tpNowButtons", "tpLink", left=4))
    panel.now_row = row
    panel._add(box)  # not one of the panel's extras, which go at rest: Now stays, at rest and widened
    return task_id


_NOW_ROW: type | None = None


def NowRow(*args, **kwargs):  # noqa: N802 - it makes the class once, when the panel's module is there, then an instance
    """The current task's row in the side panel: a Today row (``today_panel._Row``) that isn't dragged, isn't among the
    keyboard's rows, and, when the task isn't on Today, has no tick and the tile's own menu."""
    global _NOW_ROW
    if _NOW_ROW is None:
        from docrepo.ui import today_panel as tp

        class _NowRow(tp._Row):
            def __init__(self, *a, **k) -> None:
                super().__init__(*a, **k)
                self.setProperty("now", True)

            def set_wide(self, wide: bool) -> None:
                super().set_wide(wide)
                if self.item_id is None:
                    self.tick.hide()

            def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name: it isn't dragged (decision 828)
                self._press = None
                QWidget.mouseMoveEvent(self, event)

            def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
                if self.item_id is not None:
                    super().mouseReleaseEvent(event)

            def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name
                event.accept()
                if self.item_id is not None:
                    self.panel.row_menu(self, event.globalPos())
                    return
                from docrepo.ui import task_tile as tile_ui

                panel, task_id = self.panel, self.task_id
                menu = tile_ui.tile_menu(panel.browse, task_id, panel,
                                         state_pick=lambda to, branch: panel.browse.set_state(task_id, to, branch, panel.refresh, panel.tell_state))
                if menu is not None:
                    panel.run_menu(menu, event.globalPos())
                    menu.deleteLater()
                    panel.refresh()

        _NOW_ROW = _NowRow
    return _NOW_ROW(*args, **kwargs)
