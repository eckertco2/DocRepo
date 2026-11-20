"""What the browse window and its list modules share (release 5.95, moved from ``browse_window.py`` unchanged): the
keys it keeps in ``app_state``, the views' settings, and the small helpers for rows and cells."""
from __future__ import annotations


import logging


from docrepo.detail import esc, row_state
from docrepo.model import Model
from docrepo.kinds import is_work
from docrepo.ui import confirm, tokens
from docrepo.views import (
    LIST_IDS,
)


log = logging.getLogger("docrepo.ui.browse_window")  # the window's own logger, as it was before the move

WINDOW_TITLE = "DocRepo"
VIEWS_HIDDEN_KEY = "browse_views_hidden"
TODAY_MINE_KEY = "today_due_mine"  # Mine only, on Today's Due in the next 7 days (mods log round 2, M0050)
NAV_FOLDED_KEY = "browse_nav_folded"  # the sidebar's folded groups (the visual overhaul's decision 10)
TIMELINE_OPEN_KEY = "timeline_open"  # the timeline's rows whose subtasks are shown (mods log round 4, decision 133)
TIMELINE_VIEW_KEY = "timeline_view"  # the timeline's range, Order by, bar colours, Hours and Show routine (release 5.29)
#: The least width of the pane on the right: a task page's format bar on its own line, and its margins and scroll bar (release 5.58).
DETAIL_MIN = 352
#: The views with Select mode, where tasks can be ticked for Edit selected.
SELECT_VIEWS = ("tasks", *LIST_IDS)
#: The views but the task tree whose rows nest, so they have Collapse a level and Expand a level (release 5.24).
NESTING_VIEWS = ("today", *LIST_IDS, "agenda", "activity", "docs", "labels", "templates")
#: Each view's rows (the list rows review, decision L1): its row height, and whether rows with a second line
#: take two. Every one-line row is 30 px since release 5.183 (decision 850); Agendas, Documents, Activity and Search show a
#: second line.
ROW_DENSITY = {"tasks": (tokens.TREE_ROW, False), **{v: (tokens.TREE_ROW, False) for v in LIST_IDS}, "labels": (tokens.TREE_ROW, False),
               "templates": (tokens.TREE_ROW, False), "docs": (tokens.TREE_ROW, True), "agenda": (tokens.LIST_ROW, True),
               "activity": (tokens.LIST_ROW, True), "search": (tokens.LIST_ROW, True)}
#: The views with column heads (release 5.183, the redesign's decision 856): the real tables only. Every other list's
#: columns say what they hold (decision L6).
HEADINGS = ("people", "tagged", "glossaries")
#: Activity's kinds as icons (release 5.78), in place of their chips.
ACT_ICONS = {"task": "task", "update": "update", "note": "note", "email": "type-mail", "change": "edit", "doc": "file", "agenda": "agenda"}
#: Unfiled's sources as icons (release 5.78), in place of a Source column.
SOURCE_ICONS = {"Email": ("type-mail", "type_mail"), "File path": ("file", "text2"), "Typed": ("note", "text2")}
UNFILED_NOTE = ("Unfiled captures: saved without a task. Their folders are already in Captures. Filing one links it in docs.db and sets "
                "the task in its capture.md; the folder doesn't move.")


def _answers(title: str, text: str) -> tuple[str, str]:
    """What a question's two buttons say: what each does, not Yes and No (release 5.61). Since release 5.187 the words
    are ``confirm.verbs``' table, found by the question's title."""
    v = confirm.verbs(title, text)
    return v.yes, v.no


def _due_css(cls: str) -> str:
    """A date's look in a list: red and bold when it's over, caution's colour and bold when it's soon."""
    return {"over": f"color:{tokens.colour('critical')}; font-weight:600", "soon": f"color:{tokens.colour('caution')}; font-weight:600"}.get(cls, "")


def _row_state(state: str) -> str:
    """A task's state in a list's row: words for the usual ones, and a chip only for what's out of the ordinary (the review's decision V6)."""
    return row_state(state)


def _row_word(word: str) -> str:
    """What stands in a row's State cell in place of a task's state, such as Note. There's no State column: the word is
    the row's icon's tooltip (decision L7)."""
    return f'<span class="faint">{esc(word)}</span>'


def priorities_of(m: Model) -> dict[str, str]:
    """Each open, ranked task's priority bucket, by its ID: its row's left edge (release 5.81, decision L9)."""
    return {t.id: t.priority for t in m.tasks.values() if t.priority and is_work(t)}


def _shape(cells: list) -> list:
    """A row's cells, written as title, State, then the rest, without the State cell: the state is an icon before the
    title (decision L7)."""
    return [cells[0], *cells[2:]]


def _cols(labels: list[str], widths: list[int] | None = None) -> tuple[list[str], list[int] | None]:
    """A list's columns, without State (decision L7)."""
    if "State" not in labels:
        return labels, widths
    i = labels.index("State")
    return labels[:i] + labels[i + 1:], (widths[:i] + widths[i + 1:] if widths else None)


def _due_html(cell) -> str:
    """A row's date, at its right: red when it's late, caution's colour when it's soon. A deadline is a red ◆ before it,
    rather than a line under it, so the row keeps one line."""
    if cell is None:
        return ""
    if cell.deadline:
        return f'<p align="right" style="{_due_css(cell.cls)}"><span class="critical">◆</span> {esc(cell.text)}</p>'
    return f'<p align="right" style="{_due_css(cell.cls)}">{esc(cell.text)}</p>'


#: The days number's column (release 5.138, the task tile plan's decision 568): the number and its unit since release 5.183
#: ("50 d", decision 857), so narrow.
DAYS_COL = 56


def tile_cells(m: Model, task_id: str, today, *, context: str = "", flat: bool = False, hide: tuple[str, ...] = (), dim: bool = False,
               under: str | None = None):
    """A task as a tile (release 5.138, the task tile plan's decisions 563 to 570): its ``Line`` (the state's icon, the title
    cut at its first sentence or clause, Urgent's flag, the two-parents mark, ``context``, the marks less ``hide``, and depth
    ticks in a ``flat`` list) and its days cell. A ``dim`` row, a parent kept for context, is its icon and title only."""
    from docrepo import task_tile
    from docrepo.ui.tree_view import Line, state_icon

    t = m.task(task_id)
    shown = task_tile.shown_state(t)  # a collection's folder (release 5.167)
    icon, colour = state_icon(shown)
    if dim:
        return Line(t.title, icon=icon, icon_tip=shown, dim=True, tile=True), ""
    tl = task_tile.tile(m, task_id, today, task_tile.marks(m, today), hide=hide, flat=flat, under=under)
    mark = task_tile.kind_mark(tl)  # release 5.168 (decision 786): branches for a parent, a loop for a routine task
    line = Line(t.title, icon=icon, icon_colour=colour, icon_tip=shown, context=context, closed=tl.closed, tile=True, flag=tl.urgent,
                parents=tl.parents, depth=tl.depth, depth_tip=tl.depth_tip, marks=tl.marks, kind=mark[0] if mark else "", kind_tip=mark[1] if mark else "")
    return line, task_tile.days_html(tl.days)


def _empty(layout) -> None:
    """Take every widget out of a layout at once, so none is left showing until Qt deletes it."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item else None
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
