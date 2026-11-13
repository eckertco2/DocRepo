"""What the browse window and its list modules share (release 5.95, moved from ``browse_window.py`` unchanged): the
keys it keeps in ``app_state``, the views' settings, and the small helpers for rows and cells."""
from __future__ import annotations


import logging


from docrepo.detail import chip, esc, row_state, state_chip
from docrepo.model import Model
from docrepo.schedule import is_open
from docrepo.ui import tokens
from docrepo.ui.look import LOOK
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
#: Activity's line chips, by what happened (release 5.23): the pages' chip classes.
ACT_CHIPS = {"task": "multi", "update": "st-ip", "note": "lbl", "email": "lbl", "change": "routine", "doc": "st-pk", "agenda": "new"}
#: Each view's rows in the new look (the list rows review, decision L1): its row height, and whether rows with a second line
#: take two. Views whose rows nest are 28 px; Agendas, Documents, Activity and Search show a second line. Others are 32 px.
ROW_DENSITY = {"tasks": (tokens.TREE_ROW, False), **{v: (tokens.TREE_ROW, False) for v in LIST_IDS}, "labels": (tokens.TREE_ROW, False),
               "templates": (tokens.TREE_ROW, False), "docs": (tokens.TREE_ROW, True), "agenda": (tokens.LIST_ROW, True),
               "activity": (tokens.LIST_ROW, True), "search": (tokens.LIST_ROW, True)}
#: Views whose column headings say nothing their cells don't (decision L6). Search has one column, so none either.
NO_HEADINGS = ("today", "tasks", "unfiled", "search", *LIST_IDS)
#: Activity's kinds as icons (release 5.78), in place of their chips.
ACT_ICONS = {"task": "task", "update": "update", "note": "note", "email": "type-mail", "change": "edit", "doc": "file", "agenda": "agenda"}
#: Unfiled's sources as icons (release 5.78), in place of a Source column.
SOURCE_ICONS = {"Email": ("type-mail", "type_mail"), "File path": ("file", "text2"), "Typed": ("note", "text2")}
UNFILED_NOTE = ("Unfiled captures: saved without a task. Their folders are already in Captures. Filing one links it in docs.db and sets "
                "the task in its capture.md; the folder doesn't move.")


def _answers(title: str, text: str) -> tuple[str, str]:
    """What a question's two buttons say: what each does, not Yes and No (release 5.61)."""
    if "without saving" in text:
        return "Close without saving", "Keep editing"
    if "off the page" in text:
        return "Take it off the page", "Leave it on the page"
    return title, "Cancel"


def _due_css(cls: str) -> str:
    """A date's look in a list: red and bold when it's over, caution's colour and bold when it's soon."""
    return {"over": f"color:{tokens.colour('critical')}; font-weight:600", "soon": f"color:{tokens.colour('caution')}; font-weight:600"}.get(cls, "")


def _row_state(state: str) -> str:
    """A task's state in a list's row: words for the usual ones, and a chip only for what's out of the ordinary (the review's decision V6)."""
    return state_chip(state) if LOOK.classic else row_state(state)


def _row_word(word: str) -> str:
    """What stands in a row's State column in place of a task's state, such as Note. The new look has no State column: the
    word is the row's icon's tooltip (decision L7)."""
    return chip(word, "st-ns") if LOOK.classic else f'<span class="faint">{esc(word)}</span>'


def priorities_of(m: Model) -> dict[str, str]:
    """Each open, ranked task's priority bucket, by its ID: its row's left edge (release 5.81, decision L9)."""
    return {t.id: t.priority for t in m.tasks.values() if t.priority and is_open(t)}


def _shape(cells: list) -> list:
    """A row's cells, written as the Classic look's (title, State, then the rest), without the State cell in the new look,
    where the state is an icon before the title (decision L7)."""
    return cells if LOOK.classic else [cells[0], *cells[2:]]


def _cols(labels: list[str], widths: list[int] | None = None) -> tuple[list[str], list[int] | None]:
    """A list's columns, without State in the new look (decision L7)."""
    if LOOK.classic or "State" not in labels:
        return labels, widths
    i = labels.index("State")
    return labels[:i] + labels[i + 1:], (widths[:i] + widths[i + 1:] if widths else None)


#: The Classic look's deadline: a small grey word under the date (release 5.9's colours).
CLASSIC_DEADLINE = '<br><span style="color:#87919c; font-weight:400; font-size:8pt">deadline</span>'


def _due_html(cell, deadline_line: bool = True) -> str:
    """A row's date, at its right: red when it's late, caution's colour when it's soon. A deadline is a red ◆ before it in the
    new look, rather than a line under it, so the row keeps one line."""
    if cell is None:
        return ""
    if cell.deadline and not LOOK.classic:
        return f'<p align="right" style="{_due_css(cell.cls)}"><span class="critical">◆</span> {esc(cell.text)}</p>'
    mark = CLASSIC_DEADLINE if cell.deadline and deadline_line else ""
    return f'<p align="right" style="{_due_css(cell.cls)}">{esc(cell.text)}{mark}</p>'


#: The days number's column (release 5.138, the task tile plan's decision 568): an integer, so narrow.
DAYS_COL = 44


def tile_cells(m: Model, task_id: str, today, *, context: str = "", flat: bool = False, hide: tuple[str, ...] = (), dim: bool = False,
               under: str | None = None):
    """A task as a tile (release 5.138, the task tile plan's decisions 563 to 570): its ``Line`` (the state's icon, the title
    cut at its first sentence or clause, Urgent's flag, the two-parents mark, ``context``, the marks less ``hide``, and depth
    ticks in a ``flat`` list) and its days cell. A ``dim`` row, a parent kept for context, is its icon and title only."""
    from docrepo import task_tile
    from docrepo.ui.tree_view import Line, state_icon

    t = m.task(task_id)
    icon, colour = state_icon(t.state)
    if dim:
        return Line(t.title, icon=icon, icon_tip=t.state, dim=True, tile=True), ""
    tl = task_tile.tile(m, task_id, today, task_tile.marks(m, today), hide=hide, flat=flat, under=under)
    line = Line(t.title, icon=icon, icon_colour=colour, icon_tip=t.state, context=context, closed=tl.closed, tile=True, flag=tl.urgent,
                parents=tl.parents, depth=tl.depth, depth_tip=tl.depth_tip, marks=tl.marks)
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
