"""Release 5.78, the list rows review (decisions L1 to L8): one line per row at one height per view, Regular weight, the
project as Today's context, no IDs, actions over the date, the state as an icon, and a folded parent's count. Driven
offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE, LINE_ROLE, TILE_GAP, TILE_INSET, TWO_LINE_ROW, HtmlDelegate, Line, RowTree  # noqa: E402
from docrepo.views import TASK_VIEWS  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
LONG = "Ring the vendor back about the impeller datasheet, the seals, the coupling and the crane booking before the 2 pm call"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1440, 900)
    yield w
    capture.deleteLater()
    w.deleteLater()


def put_on_today(ctx) -> None:
    """Two tasks carried over from Tuesday, one top-level task and a long note added today."""
    tue, now = datetime(2026, 10, 6, 9, 0), datetime(2026, 10, 8, 8, 30)
    for task_id in ("T000012", "T000009"):  # Rigging plan, Vendor drawing package
        edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, task_id, "", tue)
    edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, "T000016", "", now)  # Holiday coverage schedule, top-level
    edits.add_to_today(ctx.conn, ctx.data_root, ctx.fs, None, LONG, now)


def shown_rows(browse) -> list:
    t = browse.tree
    return [i for i in t.items() if t.is_shown(i) and not i.isHidden()]


def heights(browse, keyed: bool = True) -> set[int]:
    QApplication.processEvents()
    browse.tree.doItemsLayout()
    return {browse.tree.visualItemRect(i).height() for i in shown_rows(browse) if not keyed or i.data(0, KEY_ROLE) is not None}


def line_of(browse, key) -> Line:
    return next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == key).data(0, LINE_ROLE)


# ---- L1: one line, one height per view ----
@pytest.mark.parametrize(("view", "height"), [("tasks", tokens.TREE_ROW), ("due", tokens.TREE_ROW), ("waiting", tokens.TREE_ROW),
                                              ("today", tokens.LIST_ROW), ("unfiled", tokens.LIST_ROW), ("people", tokens.LIST_ROW),
                                              ("discarded", tokens.LIST_ROW)])
def test_every_row_in_a_one_line_view_is_its_height(browse, ctx, view, height):
    put_on_today(ctx)
    browse.refresh(render=False)
    browse.open.update(Model(ctx.conn).tasks)  # the whole tree open, chips, labels and deadlines with it
    browse.set_view(view)
    if view in TASK_VIEWS:  # a view of tasks draws its rows as tiles, TILE_GAP apart (release 5.138, decision 571); headings keep it
        assert heights(browse, keyed=False) <= {height + TILE_GAP}, view
    else:
        assert heights(browse, keyed=False) <= {height}, view  # headings too: one height, so Qt can lay them out as one


def test_a_long_title_is_cut_not_wrapped(browse, ctx):
    put_on_today(ctx)
    browse.refresh(render=False)
    browse.set_view("today")
    note = next(i for i in browse.tree.items() if (i.data(0, LINE_ROLE) and i.data(0, LINE_ROLE).title == LONG))
    assert browse.tree.visualItemRect(note).height() == tokens.LIST_ROW + TILE_GAP  # a tile (release 5.138)
    delegate: HtmlDelegate = browse.tree.itemDelegate()
    fm = QFontMetrics(browse.tree.font())
    parts = delegate._parts(note.data(0, LINE_ROLE), 300, fm, fm, False)
    assert parts[0][0] == "title" and parts[0][1].endswith("…") and parts[0][2] <= 300


@pytest.mark.parametrize("view", ["agenda", "docs", "activity"])
def test_a_two_line_view_gives_each_item_two_lines(browse, view):
    browse.set_view(view)
    lines = [i for i in shown_rows(browse) if i.data(0, LINE_ROLE) is not None and i.data(0, LINE_ROLE).second is not None]
    assert lines, view
    QApplication.processEvents()
    browse.tree.doItemsLayout()
    gap = TILE_GAP if view in TASK_VIEWS else 0  # tiles (release 5.138, decision 571)
    assert {browse.tree.visualItemRect(i).height() for i in lines} == {TWO_LINE_ROW + gap}, view


def test_an_agenda_item_with_no_note_still_takes_two_lines(browse):
    browse.set_view("agenda")
    rows = [i for i in shown_rows(browse) if i.data(0, LINE_ROLE) is not None and not i.data(0, LINE_ROLE).closed]
    assert any(i.data(0, LINE_ROLE).second == "" for i in rows) and any(i.data(0, LINE_ROLE).second for i in rows)
    QApplication.processEvents()
    browse.tree.doItemsLayout()
    assert {browse.tree.visualItemRect(i).height() for i in rows} == {TWO_LINE_ROW + TILE_GAP}


# ---- L2: no bold task rows ----
def test_no_task_row_is_bold_folded_or_open(browse):
    browse.set_view("tasks")
    browse.tree.collapseAll()
    for item in shown_rows(browse):
        assert "<b>" not in item.data(0, HTML_ROLE), item.data(0, HTML_ROLE)
    heads = [i for i in browse.tree.items() if i.data(0, KEY_ROLE) is None]
    browse._set_tree_group("group")
    heads = [i for i in browse.tree.items() if i.data(0, KEY_ROLE) is None]
    assert heads and all("<b>" in i.data(0, HTML_ROLE) for i in heads)  # headings that aren't tasks keep Body Strong


# ---- L3: Today's context is the project ----
def test_today_shows_the_project_and_no_filler_words(browse, ctx):
    put_on_today(ctx)
    browse.refresh(render=False)
    browse.set_view("today")
    rigging = line_of(browse, ("task", "T000012"))
    assert rigging.context == "Reactor impeller upgrade · since Tue"  # its project, not the whole path, and no boxed chip
    assert line_of(browse, ("task", "T000016")).context == ""  # a top-level task: nothing, not "Top-level task"
    words = " ".join(i.data(0, HTML_ROLE) or "" for i in browse.tree.items())
    assert "Top-level task" not in words and "A note" not in words and "Installation" not in rigging.context
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000012"))
    assert item.toolTip(0).startswith("Reactor impeller upgrade › Installation › Rigging plan")  # the whole path, on hover


# ---- L4: no IDs in rows, and Find still finds them ----
def test_unfiled_and_discarded_rows_show_no_ids(browse, ctx):
    browse.set_view("unfiled")
    for item in shown_rows(browse):
        assert "C0000" not in item.data(0, HTML_ROLE)
    assert line_of(browse, ("capture", "C000021")).context == "1 document"
    edits.discard_capture(ctx.conn, ctx.data_root, ctx.fs, "C000022", "Saved twice", NOW)
    browse.refresh(render=False)
    browse.set_view("discarded")
    assert not any("C0000" in (i.data(0, HTML_ROLE) or "") for i in shown_rows(browse))


def test_find_in_this_view_still_finds_a_capture_by_its_id(browse):
    browse.set_view("unfiled")
    browse.open_find()
    browse.find_box.setText("C000022")
    found = [i.data(0, KEY_ROLE) for i in shown_rows(browse)]
    assert found == [("capture", "C000022")]


# ---- L7: the state as an icon, and no State column ----
def test_the_state_is_an_icon_before_the_title(browse):
    browse.set_view("tasks")
    labels = [browse.tree.headerItem().text(i) for i in range(browse.tree.columnCount())]
    assert labels == ["Title", "Due"] and browse.tree.isHeaderHidden()
    line = line_of(browse, ("task", "T000001"))
    assert (line.icon, line.icon_colour, line.icon_tip) == ("state-ip", "accent", "In progress")
    assert line_of(browse, ("task", "T000016")).icon == "state-ns"


# ---- L8: a folded parent's count ----
def test_a_parent_counts_its_open_subtasks(browse):
    browse.set_view("tasks")
    m = Model(browse.conn)
    line = line_of(browse, ("task", "T000001"))
    assert line.count == sum(1 for c in m.children_of("T000001") if m.task(c).state != "Closed") > 0
    assert line_of(browse, ("task", "T000016")).count == 0
    delegate: HtmlDelegate = browse.tree.itemDelegate()
    fm = QFontMetrics(browse.tree.font())
    assert any(p[0] == "chip:count" for p in delegate._parts(line, 600, fm, fm, True))  # shown while folded
    assert not any(p[0] == "chip:count" for p in delegate._parts(line, 600, fm, fm, False))  # not while open


# ---- the marks that fit the line ----
def test_a_deadline_is_a_diamond_before_the_date_and_recurrence_is_quiet(browse):
    browse.set_view("tasks")
    walkthrough = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000002"))
    assert "◆" in walkthrough.data(1, HTML_ROLE) and "deadline" not in walkthrough.data(1, HTML_ROLE)
    weekly = line_of(browse, ("task", "T000010"))
    assert weekly.chips == () and not weekly.muted  # since release 5.138 recurrence leaves the tile (decision 569)
    browse.tree.end()
    assert browse.tree.columnWidth(1) >= QFontMetrics(browse.tree.font()).horizontalAdvance("◆ 23")  # never cut


def test_the_context_goes_before_the_title_is_cut(qapp):
    delegate = HtmlDelegate(RowTree())
    fm = QFontMetrics(QFont("Segoe UI", 10))
    line = Line("Update area 3 guard drawings", chips=(("Urgent", "urgent"),), muted=("Safety",), context="Verification walkthrough readiness")
    whole = sum(p[2] for p in delegate._parts(line, 2000, fm, fm, False))
    title, urgent = fm.horizontalAdvance(line.title), fm.horizontalAdvance("Urgent") + 12
    parts = delegate._parts(line, title + urgent + 8 + 30, fm, fm, False)
    assert [p[0] for p in parts] == ["title", "chip:urgent"] and parts[0][1] == line.title  # the context and labels went, the title stayed
    parts = delegate._parts(line, 60, fm, fm, False)
    assert parts[0][0] == "title" and parts[0][1].endswith("…")  # the title is cut last, never dropped
    assert whole > title + urgent


def test_the_classic_look_keeps_its_words_and_bold(qapp):
    line = Line("Reactor impeller upgrade", context="Top of the tree", strong=True, muted=("Line 1",))
    assert line.html(classic=True).startswith("<b>Reactor impeller upgrade</b>") and '<br><span class="sub">Top of the tree' in line.html(classic=True)
    assert "<b>" not in line.html() and "<br>" not in line.html()


def test_search_rows_show_no_ids_and_a_tasks_state(browse):
    browse.search_box.setText("impeller")
    browse._run_search()
    assert browse.view == "search"
    lines = [(i.data(0, KEY_ROLE), i.data(0, LINE_ROLE)) for i in shown_rows(browse) if i.data(0, LINE_ROLE) is not None]
    assert lines and not any(key[1] in line.words() for key, line in lines)  # its ID is in the tooltip only
    task, *copies = [line for key, line in lines if key == ("task", "T000001")]  # the task's row, then its saved copies'
    assert task.icon == "state-ip" and task.icon_tip == "In progress"
    assert copies and all(c.icon == "type-pdf" and c.icon_tip == "Saved copy" for c in copies)  # a file's mark (release 5.114)


# ---- release 5.81: a task's priority as its row's left edge (decision L9) ----
def rank(ctx, task_id: str, bucket: str) -> None:
    edits.set_priority(ctx.conn, ctx.data_root, ctx.fs, task_id, bucket, None, NOW)


def edge_pixel(browse, key) -> str:
    """The colour at the left edge of a row, as drawn."""
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == key)
    browse.tree.scrollToItem(item)
    QApplication.processEvents()
    rect = browse.tree.visualItemRect(item)
    x = TILE_INSET + 1 if browse.tree.tiled else 1  # a tile's edge is its own left edge (release 5.138, decision 571)
    return browse.tree.viewport().grab().toImage().pixelColor(x, rect.center().y()).name()


@pytest.mark.parametrize(("bucket", "token"), [("critical", "pri_critical"), ("high", "pri_high"), ("medium", "pri_medium"), ("parking", "pri_parking")])
def test_a_ranked_tasks_row_has_its_priority_down_its_edge(browse, ctx, bucket, token):
    rank(ctx, "T000012", bucket)  # Rigging plan, a subtask two levels down
    browse.refresh(render=False)
    browse.set_view("tasks")
    browse.open.update(Model(ctx.conn).tasks)
    browse.render_list()
    browse.select("task", "T000016")  # another row, so this one isn't selected
    assert browse.tree.row_priority(browse.tree.indexFromItem(next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000012")))) == bucket
    assert edge_pixel(browse, ("task", "T000012")) == tokens.colour(token)


def test_unranked_rows_have_no_edge_and_projects_no_colour(browse):
    browse.set_view("tasks")
    browse.select("task", "T000016")
    background = browse.tree.viewport().grab().toImage().pixelColor(browse.tree.viewport().width() // 2, 2).name()
    top = edge_pixel(browse, ("task", "T000001"))  # a top-level task, unranked: once its project's colour
    assert top not in {tokens.colour(k) for k in tokens.GROUP_KEYS} and top in (background, tokens.colour("hover"), "#ffffff")


def test_the_selected_row_keeps_the_accent_bar(browse, ctx):
    rank(ctx, "T000012", "high")
    browse.refresh(render=False)
    browse.set_view("tasks")
    browse.select("task", "T000012")
    assert edge_pixel(browse, ("task", "T000012")) == tokens.colour("accent")


def test_a_closed_or_unranked_task_gives_no_priority(browse, ctx):
    from docrepo.ui.browse_window import priorities_of

    rank(ctx, "T000012", "critical")
    rank(ctx, "T000007", "high")  # Order spare mechanical seal, closed
    assert priorities_of(Model(ctx.conn)) == {"T000012": "critical"}


def test_drawing_a_row_never_reads_the_database(browse, ctx, monkeypatch):
    """A window left over from an earlier list, painted after its database has closed, drew rows by loading the model: the
    edge comes from what the list was filled with."""
    rank(ctx, "T000012", "high")
    browse.refresh(render=False)
    browse.set_view("tasks")
    assert browse.tree.priorities == {"T000012": "high"}
    monkeypatch.setattr(type(browse), "model", lambda self: (_ for _ in ()).throw(AssertionError("read while drawing")))
    browse.tree.viewport().grab()


def test_todays_rows_and_the_side_panel_show_it_too(browse, ctx):
    from docrepo.ui.today_panel import edge_of

    put_on_today(ctx)
    rank(ctx, "T000009", "medium")  # Vendor drawing package, carried over
    browse.refresh(render=False)
    browse.set_view("today")
    browse.select("task", "T000016")
    assert edge_pixel(browse, ("task", "T000009")) == tokens.colour("pri_medium")
    m = Model(ctx.conn)
    assert edge_of(m.task("T000009")) == tokens.colour("pri_medium") and edge_of(m.task("T000016")) == "" and edge_of(None) == ""


def test_critical_is_its_edge_and_tooltip_not_a_chip(browse, ctx):
    """Release 5.138 (the task tile plan's decision 569): Critical's chip leaves the tile; its red edge and its tooltip say it."""
    rank(ctx, "T000008", "critical")  # Installation
    browse.refresh(render=False)
    browse.set_view("tasks")
    assert line_of(browse, ("task", "T000008")).chips == ()
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000008"))
    assert browse.tree.row_priority(browse.tree.indexFromItem(item)) == "critical"
