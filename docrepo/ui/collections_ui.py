"""A row's kind lines in the browse window (release 5.167, the design workspace's docs/mods/collections-and-kinds-plan.md,
decisions 779 and 781): Make it a collection, with everything under it, and Make it a task. Each is saved at once, through
``docrepo.collection_edits``, and says what it did in the status line. Archive and Restore are a collection's state menu
(``docrepo.ui.state_menu``), so they have that menu's Undo.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu

from docrepo import collection_edits, task_commands

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow


def make_collection(browse: BrowseWindow, task_id: str, with_below: bool = False) -> None:
    """Make it a collection (with everything under it): off Today, its wait ended, its other fields kept unseen."""
    ctx = browse.ctx
    browse._do(lambda: collection_edits.make_collection(browse.conn, ctx.data_root, ctx.fs, ctx.settings, task_id, browse._now(),
                                                        with_below=with_below, model=browse.model()))


def make_task(browse: BrowseWindow, task_id: str) -> None:
    """Make it a task: a collection is work again, its fields as they were."""
    ctx = browse.ctx
    browse._do(lambda: collection_edits.make_task(browse.conn, ctx.data_root, ctx.fs, ctx.settings, task_id, browse._now(), model=browse.model()))


def run(browse: BrowseWindow, task_id: str, do: str) -> bool:
    """What a kind line does; False for an entry that isn't one."""
    if do == "collection":
        make_collection(browse, task_id)
    elif do == "collection_all":
        make_collection(browse, task_id, with_below=True)
    elif do == "make_task":
        make_task(browse, task_id)
    else:
        return False
    return True


def add_kind_lines(browse: BrowseWindow, task_id: str, menu: QMenu) -> None:
    """A row's right-click menu's kind lines, under a line (decision 779)."""
    from docrepo.ui import task_menus

    entries = task_commands.kind_entries(browse.model(), task_id)
    if not entries:
        return
    menu.addSeparator()
    task_menus.fill(menu, entries, lambda e: run(browse, task_id, e.do))
