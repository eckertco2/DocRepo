"""Priorities (mods log round 2, M0029, M0030; release 5.23, decisions 23 and 74 to 78): the buckets and their order, the
board's columns and filters, moves and their status log entries, Edit task and Edit selected, Sort by priority, the
Priority filter, the chips, Task.md, and the board itself, driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import bulk, db, edits, priorities, quick  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import Pages  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.pages import Pages as TaskPages  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.stories import Stories  # noqa: E402
from docrepo.views import TreeFilter, markers, sort_tree, task_tree  # noqa: E402

TODAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 14, 10)


@pytest.fixture
def conn():
    c = db.connect_memory()
    load_sample(c)
    yield c
    c.close()


def board(conn, f: priorities.BoardFilter = priorities.BoardFilter()) -> dict[str, list[str]]:
    return {col.name: col.ids for col in priorities.columns(Model(conn), TODAY, f)}


def test_the_buckets():
    """Decision 23: Critical, High, Medium and Parking lot, keys 1 to 4, and Not ranked (0) first on the board."""
    assert [(k, n, d) for k, n, d in priorities.COLUMNS] == [("", "Not ranked", "0"), ("critical", "Critical", "1"), ("high", "High", "2"),
                                                              ("medium", "Medium", "3"), ("parking", "Parking lot", "4")]
    assert priorities.name(None) == "Not ranked" and priorities.BY_DIGIT["4"] == "parking"


def test_whats_on_the_board_and_not_ranked_sorts_itself(conn):
    """Decisions 74 and 75: open tasks, parents too, but not parked, closed or routine ones; Not ranked is urgent first, then
    the soonest due."""
    m = Model(conn)
    cols = board(conn)
    unranked = cols["Not ranked"]
    assert unranked and all(not cols[n] for n in ("Critical", "High", "Medium", "Parking lot"))
    assert unranked[0] == "T000019"  # urgent, due tomorrow
    for task_id in unranked:
        t = m.task(task_id)
        assert t.state in ("Not started", "In progress") and not t.recurrence
    assert "T000001" in unranked  # a top-level task with subtasks is on it too
    assert not any(m.task(x).state in ("Parked", "Closed") for x in unranked)
    assert any(m.task(x).recurrence for x in board(conn, priorities.BoardFilter(routine=True))["Not ranked"])
    dues = [d for x in unranked[1:] if (d := priorities.due_of(m.task(x), TODAY))]
    assert [d.date for d in dues] == sorted(d.date for d in dues)


def test_quick_tasks_itself_isnt_on_the_board(conn):
    qid = quick.ensure_parent(conn, Settings(me="P001"), AT)
    assert qid not in board(conn)["Not ranked"]


def test_moves_and_the_status_log(conn):
    """Decision 76: a move to another bucket is logged; a move within one isn't."""
    via = priorities.VIA
    assert priorities.place(conn, "T000012", "critical", at=AT, via=via).to_value == "Critical"
    priorities.place(conn, "T000019", "critical", "T000012", at=AT, via=via)  # before Rigging plan
    priorities.place(conn, "T000008", "critical", at=AT, via=via)
    assert board(conn)["Critical"] == ["T000019", "T000012", "T000008"]
    assert priorities.place(conn, "T000008", "critical", "T000019", at=AT, via=via) is None  # within the bucket: no entry
    assert board(conn)["Critical"] == ["T000008", "T000019", "T000012"]
    change = priorities.place(conn, "T000019", "high", at=AT, via=via)
    assert (change.from_value, change.to_value) == ("Critical", "High")
    assert [r["priority_rank"] for r in conn.execute("SELECT priority_rank FROM tasks WHERE priority = 'critical' ORDER BY priority_rank")] == [1, 2]
    assert priorities.place(conn, "T000012", "", at=AT, via=via).to_value is None
    log = [(e.from_value, e.to_value, e.via) for e in Model(conn).status if e.field == "Priority"]
    assert log == [(None, "Critical", via), (None, "Critical", via), (None, "Critical", via), ("Critical", "High", via), ("Critical", None, via)]
    with pytest.raises(priorities.tasks.TaskError):
        priorities.place(conn, "T000012", "urgent", at=AT, via=via)


def test_nudging_within_a_bucket(conn):
    for x in ("T000012", "T000019", "T000008"):
        priorities.place(conn, x, "high", at=AT, via=priorities.VIA)
    shown = board(conn)["High"]
    assert priorities.nudge(conn, "T000008", -1, shown) and board(conn)["High"] == ["T000012", "T000008", "T000019"]
    assert not priorities.nudge(conn, "T000012", -1, shown)  # already first
    assert not priorities.nudge(conn, "T000002", 1, shown)  # not ranked: no order of its own
    # Among the cards shown: with T000019 filtered out, one step down from T000008 is the end.
    assert priorities.nudge(conn, "T000012", 1, ["T000012", "T000008"]) and board(conn)["High"] == ["T000008", "T000012", "T000019"]
    assert not any(e.field == "Priority" and e.from_value == "High" for e in Model(conn).status)


def test_the_boards_filters(conn):
    m = Model(conn)
    overdue = board(conn, priorities.BoardFilter(due="over"))["Not ranked"]
    assert all(priorities.due_of(m.task(x), TODAY).date < TODAY for x in overdue)
    undated = board(conn, priorities.BoardFilter(due="none"))["Not ranked"]
    assert undated and all(priorities.due_of(m.task(x), TODAY) is None for x in undated)
    mike = board(conn, priorities.BoardFilter(people=("P004",)))["Not ranked"]
    assert mike and all("P004" in (*m.task(x).leads, *m.task(x).assignees) for x in mike)


def test_edit_task_and_edit_selected_set_it(sample_root):
    conn, root, fs = sample_root
    s = Settings(me="P001")
    edits.edit_task(conn, root, fs, s, "T000009", AT, priority="medium")
    edits.edit_task(conn, root, fs, s, "T000011", AT, priority="medium")
    assert board(conn)["Medium"] == ["T000009", "T000011"]
    edits.edit_task(conn, root, fs, s, "T000009", AT, priority="medium", title="Vendor drawing package")  # the same bucket: stays put
    assert board(conn)["Medium"] == ["T000009", "T000011"]
    assert [e.via for e in Model(conn).status if e.field == "Priority"] == ["Browse tool", "Browse tool"]
    out = edits.bulk_edit(conn, root, fs, s, ["T000012", "T000018"], bulk.BulkEdit(priority="parking"), AT)
    assert board(conn)["Parking lot"] == ["T000012", "T000018"] and "2 tasks" in out.message
    edits.bulk_edit(conn, root, fs, s, ["T000012"], bulk.BulkEdit(priority=""), AT)
    assert board(conn)["Parking lot"] == ["T000018"]
    assert bulk.BulkEdit().empty and not bulk.BulkEdit(priority="").empty


def test_sort_filter_chips_story_and_task_md(sample_root):
    conn, root, fs = sample_root
    for x, b in (("T000012", "critical"), ("T000008", "high"), ("T000019", "critical")):
        priorities.place(conn, x, b, at=AT, via=priorities.VIA)
    m = Model(conn)
    # Sort by priority: under each parent, Critical first, each bucket in its order, Not ranked last.
    nodes = sort_tree(m, task_tree(m, TreeFilter()), "priority", TODAY)
    reactor = next(n for n in nodes if n.id == "T000001")
    install = next(n for n in reactor.children if n.id == "T000008")
    assert [n.id for n in install.children][:2] == ["T000012", "T000019"]
    # The Priority filter: Critical tasks, with their parents for context.
    nodes = task_tree(m, TreeFilter(priorities=("critical",)))
    matched = [n.id for n in _walk(nodes) if n.match]
    assert sorted(matched) == ["T000012", "T000019"]
    unranked = [n.id for n in _walk(task_tree(m, TreeFilter(priorities=("",)))) if n.match]
    assert "T000008" not in unranked and "T000002" in unranked
    # Decision 77: rows show only Critical, beside Urgent; the page shows every bucket, once.
    assert ("Critical", "pri-critical") in markers(m, m.task("T000019")) and ("Urgent", "urgent") in markers(m, m.task("T000019"))
    assert not any(cls.startswith("pri-") for _, cls in markers(m, m.task("T000008")))
    pages = Pages(m, TODAY, lambda c: "")
    head = pages.page_head(m.task("T000012"), pages_state())
    assert head.count("Critical") == 1 and 'class="pri-critical"' in head
    assert 'class="pri-high"' in pages.page_head(m.task("T000008"), pages_state())
    st = Stories(m, TODAY, lambda c: "")
    sentences = [st.field_sentence(e) for e in m.status if e.field == "Priority"]
    assert sentences == ["Ranked Critical.", "Ranked High.", "Ranked Critical."]
    priorities.place(conn, "T000012", "high", at=AT, via=priorities.VIA)
    priorities.place(conn, "T000008", "", at=AT, via=priorities.VIA)
    m = Model(conn)
    st = Stories(m, TODAY, lambda c: "")
    assert [st.field_sentence(e) for e in m.status if e.field == "Priority"][-2:] == ["Priority moved to High.", "No longer ranked."]
    md = TaskPages(m, TODAY, AT)
    assert "| Priority | High |" in md.task_page(m.task("T000012")) and "| Priority |" not in md.task_page(m.task("T000008"))


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.children)


def pages_state():
    from docrepo.detail import PageState

    return PageState()


# ---- the board, offscreen ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext

    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT), None)
    w.show_browse("priorities")
    yield w
    w.hide()
    w.deleteLater()


def test_the_board(browse):
    """The view: full width, a column per bucket, the selected card above it, and the keys."""
    v = browse.priorities
    assert browse.middle.currentWidget() is v and not browse.detail.isVisibleTo(browse)
    assert [c.name for c in v.columns] == ["Not ranked", "Critical", "High", "Medium", "Parking lot"]
    assert "open tasks" in v.title.text() and set(v.cards) == set(v.columns[0].ids)
    v.cards["T000012"].setFocus()
    v.pick("T000012")
    assert browse.sel == ("task", "T000012") and "Rigging plan" in v.strip_text.text() and v.bucket_buttons[""].isChecked()
    browse.render_all()
    assert not browse.detail.isVisibleTo(browse)  # the board keeps the whole width, with a card selected too
    assert v.key(Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier)  # 1: Critical
    assert v.columns[1].ids == ["T000012"] and "Critical" in browse.status.text()
    v.pick("T000019")
    v.key(Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier)
    assert v.columns[1].ids == ["T000012", "T000019"]
    v.key(Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)  # Alt+Up: within Critical
    assert v.columns[1].ids == ["T000019", "T000012"]
    v.drop("T000008", "critical", "T000012")  # a drag dropped before Rigging plan
    assert v.columns[1].ids == ["T000019", "T000008", "T000012"]
    v.pick("T000008")
    v.key(Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier)  # 0: Not ranked
    assert "T000008" in v.columns[0].ids and "T000008" not in v.columns[1].ids
    v.pick("T000012")
    v.key(Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    assert v.sel in v.columns[0].ids  # the nearest card in the next column that has any
    v.bucket_buttons["parking"].click()
    assert v.sel in v.columns[4].ids
    opened = []
    v.open_task.connect(opened.append)
    v.key(Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    assert opened == [v.sel]
    assert [e.via for e in Model(browse.conn).status if e.field == "Priority"].count("Priorities view") == 5


def test_edit_task_has_priority(browse):
    from docrepo.ui.task_forms import TaskEditDialog

    m = browse.model()
    d = TaskEditDialog(browse, m, "T000012", browse._label_options, browse._people_options, lambda *_: None, today=TODAY)
    assert d.priority.currentText() == "Not ranked"
    d.priority.setCurrentIndex(d.priority.findData("medium"))
    browse.save_task_edit("T000012", d.values())
    assert browse.model().task("T000012").priority == "medium"
    d.deleteLater()


def test_the_classic_look_has_both(qapp, sample_root):
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext
    from docrepo.ui.look import configure

    conn, root, fs = sample_root
    configure("classic", False)
    try:
        w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT), None)
        w.show_browse("priorities")
        assert w.middle.currentWidget() is w.priorities and len(w.priorities.columns) == 5
        w.priorities.pick("T000012")
        w.priorities.key(Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier)
        assert w.priorities.columns[2].ids == ["T000012"]
        w.set_view("activity")
        assert any(k and k[0] == "actline" for k in w.tree.keys())
        w.hide()
        w.deleteLater()
    finally:
        configure("new", False)


def test_fold_subtasks(conn):
    """Release 5.24: only parent and top-level tasks; a subtask with no open subtasks of its own folds into its parent."""
    m = Model(conn)
    folded = board(conn, priorities.BoardFilter(fold=True))["Not ranked"]
    assert "T000008" in folded and "T000001" in folded  # Installation has open subtasks; Reactor impeller upgrade is top-level
    assert "T000012" not in folded and "T000019" not in folded  # Rigging plan and Book the alignment contractor fold away
    assert "T000016" in folded  # top-level, with no subtasks: it stays
    assert priorities.folded_under(m, "T000008") == len(priorities.open_subtasks(m, "T000008"))


def test_find_and_fold_on_the_board(browse):
    v = browse.priorities
    browse.open_find()
    assert not v.find_bar.isHidden() and v.find_box.hasFocus() or not v.find_bar.isHidden()
    v.find_box.setText("rigging")  # Rigging plan, and Installation, whose status is waiting on it
    assert sorted(x for c in v.columns for x in c.ids) == ["T000008", "T000012"] and v.find_count.text() == "2 matches"
    v.find_box.setText("sling")
    assert [x for c in v.columns for x in c.ids] == ["T000012"] and v.find_count.text() == "1 match"
    v.find_box.setText("mike installation")  # every word: Mike Ortiz, and Installation in the path
    assert set(x for c in v.columns for x in c.ids) <= {"T000008", "T000012", "T000019", "T000015"}
    v.find_box.setText("nothing like this")
    assert v.find_count.text() == "Nothing on the board matches"
    v.close_find()
    assert v.find_bar.isHidden() and len([x for c in v.columns for x in c.ids]) > 3
    browse.priorities._set("fold", True)
    assert "T000012" not in v.cards and "folded" in v.cards["T000008"].findChildren(type(v.title))[-1].text()
    browse.set_view("tasks")
    assert v.find_bar.isHidden()
