"""Opening a task (release 5.174, the design workspace's docs/mods/today-workspace-carry-plan.md, decision 815).

One helper every place that opens a task calls: a double-click or Enter on a list's row or a tile (the browse tool's lists,
the Today side panel, the Priorities board), Task search, the quick summary's task link, File search's Task and the side
panel's Open. It follows Settings' **Open a task in** (``Settings.open_tasks_in``): its **workspace**, to start, or its
**page**. Shift with the double-click or Enter, and the tile menu's second line, give the other one.

A link inside a page still goes to the task's page (``BrowseWindow.go_task``): reading on from one page to the next isn't
starting work. A collection (release 5.167) has no workspace of work, so it always opens at its page.

This supersedes decisions 667 (a double-click on Today opens the workspace) and 572 (a double-click opens the task's
page), and takes in 756 (the side panel's double-click).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

WORKSPACE, PAGE = "workspace", "page"


#: Where Shift is read: Windows' live state of the keys (release 5.177), not the state Qt remembers from the last event it
#: was given, which a window that never takes the keyboard (the Today side panel) may not have had, and a test's synthetic
#: Shift leaves held. Tests set it. On Qt's offscreen platform it answers what Qt remembers.
query_modifiers = QGuiApplication.queryKeyboardModifiers


def shift_held() -> bool:
    """Whether Shift is held now: with a double-click or Enter, it opens the task the other way."""
    return bool(query_modifiers() & Qt.KeyboardModifier.ShiftModifier)


def opens_workspace(browse: BrowseWindow, task_id: str, other: bool = False) -> bool:
    """Whether opening the task goes to its workspace: as the setting says, or the other way with ``other``. Never for a
    collection, or a task that's gone."""
    t = browse.model().tasks.get(task_id)
    if t is None or t.collection:
        return False
    return (browse.ctx.settings.open_tasks_in != PAGE) != other


def open_task(browse: BrowseWindow, task_id: str, *, other: bool = False, from_today: bool | None = None, origin: str | None = None) -> None:
    """Open a task as Settings says, or the other way with ``other``: its workspace (``workspace.open_workspace``, the
    browse window coming forward maximised) or its page (``task_tile.open_task``, the browse window forward at it).
    ``from_today`` and ``origin`` are the workspace's: where Esc goes back to."""
    from docrepo.ui import task_tile as tile_ui
    from docrepo.ui import workspace as workspace_ui

    if opens_workspace(browse, task_id, other):
        workspace_ui.open_workspace(browse, task_id, from_today, origin)
    else:
        tile_ui.open_task(browse, task_id)
