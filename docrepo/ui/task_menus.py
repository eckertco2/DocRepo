"""A task's Edit and Add to menus, made from one list each (release 5.98; the consolidation plan's item 113, decision 392):
the task page's command bar, every task row's right-click menu in the browse window, and Find files' task rows use these,
so the menus say the same words in the same order everywhere. What they hold is ``docrepo.task_commands``; this module
only makes the ``QMenu`` and runs a pick through the browse window's own methods.

A tree move (Move…, Put under…, Also put under… and Remove from under…) is saved at once and says what it did, with Undo
for ten seconds (release 5.118, the consolidation mock's, decisions 435 to 439): ``move``. Undo puts the task back under
exactly the parents it had, in its old place, as one more Parents line in its status log.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu, QWidget

from docrepo import edits, task_commands, tasks
from docrepo.model import TODAY
from docrepo.task_commands import Entry
from docrepo.ui import t_mails
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: What redraws the place a move came from, and what says the move there with its Undo (Find files' footer), as a state
#: picked from a menu has them (decision 363).
After = Callable[[], None] | None
Tell = Callable[[str, Callable[[], None] | None], None] | None


def key_column() -> str:
    """A menu's key column: a tab in the new look; the Classic look puts the key after the label."""
    return "   " if LOOK.classic else "\t"


def run(browse: BrowseWindow, task_id: str, entry: Entry, anchor: QWidget | None = None, after: After = None, tell: Tell = None) -> None:
    """What an entry does, through the browse window: ``anchor`` is where the task picker opens for Move and Put under;
    ``after`` and ``tell`` are ``move``'s."""
    do, args = entry.do, entry.args
    if do == "edit":
        browse.edit_task(task_id)
    elif do == "move":
        browse._pick_parent(task_id, args[0], anchor=anchor, after=after, tell=tell)
    elif do == "also":
        browse._pick_parent(task_id, None, also=True, anchor=anchor, after=after, tell=tell)
    elif do == "top":
        browse.move_task(task_id, args[0], None, after, tell)
    elif do == "discard":
        browse.discard_task(task_id)
    elif do == "today":
        browse.add_to_today(task_id)
    elif do == "open_today":
        browse.show_agenda(TODAY)
    elif do == "agenda":
        browse.open_capture(task=task_id, mode="update", agenda=[args[0]])
    elif do == "agenda_other":
        browse.open_capture(task=task_id, mode="update", agenda_focus=True)


def fill(menu: QMenu, entries: list[Entry], picked: Callable[[Entry], None]) -> QMenu:
    """The entries as the menu's actions, each with its key in the key column, its tip (a greyed one's says why), and
    Today's sun; an entry with lines of its own opens them as a list."""
    menu.setToolTipsVisible(True)
    for e in entries:
        if e.separator:
            menu.addSeparator()
            continue
        if e.sub:
            sub = fill(menu.addMenu(e.label), list(e.sub), picked)
            sub.menuAction().setToolTip(e.tip)
            sub.menuAction().setEnabled(e.enabled)
            continue
        label = e.label + (key_column() + e.key if e.key else "")
        action = menu.addAction(icon("sun"), label) if e.do in ("today", "open_today") else menu.addAction(label)
        action.triggered.connect(lambda _=False, e=e: picked(e))
        action.setEnabled(e.enabled)
        if e.tip:
            action.setToolTip(e.tip)
    return menu


def edit_menu(browse: BrowseWindow, task_id: str, parent: QWidget | None, anchor: QWidget | None = None, after: After = None,
              tell: Tell = None) -> QMenu:
    """The Edit menu (decision 392): Edit task…, Move…, Put under…, Also put under…, Remove from under… and Discard…,
    always those six, greyed with a reason where one doesn't apply."""
    menu = QMenu(task_commands.EDIT, parent)
    menu.setIcon(icon("edit"))
    return fill(menu, task_commands.edit_entries(browse.model(), task_id), lambda e: run(browse, task_id, e, anchor, after, tell))


def add_to_menu(browse: BrowseWindow, task_id: str, parent: QWidget | None) -> QMenu:
    """The Add to menu (decision 392): Today, the open meetings, and anyone else."""
    menu = QMenu(task_commands.ADD_TO, parent)
    menu.setIcon(icon("agenda"))
    return fill(menu, task_commands.add_to_entries(browse.model(), task_id, browse.today()), lambda e: run(browse, task_id, e))


def add_row_menus(browse: BrowseWindow, task_id: str, menu: QMenu, anchor: QWidget | None = None, after: After = None,
                  tell: Tell = None, ask: bool = False) -> None:
    """A task row's right-click menu gets them too (decision 392), after its own actions: a quick task's Put under… on
    its own (release 5.99, decision 394), then Add to and Edit as submenus. Nothing for a discarded task. ``after`` and
    ``tell`` are ``move``'s, for a list outside the browse window (Find files). With ``ask`` (a row in Waiting on others),
    Ask for an update comes first (release 5.125, the cold-eyes plan's decision 481)."""
    m = browse.model()
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        return
    if not menu.isEmpty():
        menu.addSeparator()
    if ask:
        t_mails.add_ask(browse, task_id, menu)
    put = task_commands.put_under(m, task_id)
    if put is not None:
        fill(menu, [put], lambda e: run(browse, task_id, e, anchor, after, tell))
    menu.addMenu(add_to_menu(browse, task_id, menu))
    menu.addMenu(edit_menu(browse, task_id, menu, anchor, after, tell))


def move(browse: BrowseWindow, task_id: str, old_parent: str | None, new_parent: str | None, after: After = None, tell: Tell = None) -> bool:
    """A tree move from the Edit menu (release 5.118, decisions 435 to 439): saved at once, its words in the status line
    with Undo for ten seconds, as a state picked from a menu has (decision 363). ``after`` redraws the place it came from,
    and ``tell`` says it there too. Undo puts the task back under exactly the parents it had, in its old place, while its
    parents are as the move left them; it runs once, from whichever place it's clicked. True when the task moved."""
    conn, ctx = browse.conn, browse.ctx
    had = tasks.parent_links(conn, task_id)
    out = browse._do(lambda: edits.move_task(conn, ctx.data_root, ctx.fs, task_id, old_parent, new_parent, browse._now()))
    if not isinstance(out, edits.Outcome):
        if tell is not None:
            tell(browse.status.text(), None)  # why it didn't move, as the status line says it
        return False
    left = tasks.parent_links(conn, task_id)
    line = out.message + (" Problems: " + " ".join(out.problems) if out.problems else "")
    undone: list[bool] = []

    def undo() -> None:
        if undone:
            return
        undone.append(True)
        back = browse._do(lambda: edits.undo_move(conn, ctx.data_root, ctx.fs, task_id, had, left, browse._now()))
        if after is not None:
            after()
        if tell is not None:
            tell(back.message if isinstance(back, edits.Outcome) else browse.status.text(), None)

    browse.say_undo(line, undo)
    if after is not None:
        after()
    if tell is not None:
        tell(line, undo)
    return True
