"""Reordering a template's rows by dragging or with Alt+Up and Alt+Down, and duplicating a template (release 5.49; the task templates
design, decisions 261 and 262)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402

from docrepo import templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.tasks import TaskError  # noqa: E402
from docrepo.templates import Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
PRIYA, TOM = "P002", "P003"


def build(conn) -> dict:
    """A made-up template: Prep (A, B), Window, Report, and an empty second template."""
    add = lambda parent, title, **x: templates.add_row(conn, SETTINGS, parent, {"title": title, "inherit_labels": True, **x}, NOW)[0]  # noqa: E731
    top = templates.new_template(conn, "Product trial", NOW, {"labels": ["Safety"], "leads": ["P001"]})
    prep = add(top, "Prep")
    a, b = add(prep, "A"), add(prep, "B")
    window = add(top, "Window", assignees=[PRIYA, TOM], assignee_per_week=3, duration=5, involvement={("assignee", TOM): 25}, notes="- [ ] Book the room")
    report = add(top, "Report", assignee_hours=12)
    other = templates.new_template(conn, "Equipment audit", NOW)
    return {"top": top, "prep": prep, "a": a, "b": b, "window": window, "report": report, "other": other, "x": add(other, "X")}


def order(conn, parent: int) -> list[str]:
    lib = Library(conn)
    return [r.title for r in lib.children(parent)]


def shape(conn, top: int) -> list[tuple[int, str]]:
    return [(d, r.title) for r, d in Library(conn).walk(top)]


# ---- placing a row ----
@pytest.fixture
def rows(sample_conn):
    return sample_conn, build(sample_conn)


def test_a_row_goes_before_or_after_another(rows):
    conn, r = rows
    assert templates.place_row(conn, r["report"], r["prep"], "before") is True
    assert order(conn, r["top"]) == ["Report", "Prep", "Window"]
    assert templates.place_row(conn, r["report"], r["window"], "after") is True
    assert order(conn, r["top"]) == ["Prep", "Window", "Report"]
    assert templates.place_row(conn, r["prep"], r["window"], "after") is True
    assert order(conn, r["top"]) == ["Window", "Prep", "Report"]


def test_a_row_goes_under_another_at_its_end(rows):
    conn, r = rows
    templates.place_row(conn, r["report"], r["prep"], "in")
    assert order(conn, r["prep"]) == ["A", "B", "Report"] and order(conn, r["top"]) == ["Prep", "Window"]


def test_a_row_can_go_beside_one_at_another_level(rows):
    conn, r = rows
    templates.place_row(conn, r["a"], r["window"], "before")
    assert order(conn, r["top"]) == ["Prep", "A", "Window", "Report"] and order(conn, r["prep"]) == ["B"]
    templates.place_row(conn, r["report"], r["b"], "before")
    assert order(conn, r["prep"]) == ["Report", "B"]


def test_what_is_under_a_row_moves_with_it(rows):
    conn, r = rows
    templates.place_row(conn, r["prep"], r["report"], "after")
    assert shape(conn, r["top"]) == [(0, "Product trial"), (1, "Window"), (1, "Report"), (1, "Prep"), (2, "A"), (2, "B")]


def test_dropping_a_row_where_it_is_changes_nothing(rows):
    conn, r = rows
    assert templates.place_row(conn, r["b"], r["a"], "after") is False
    assert templates.place_row(conn, r["a"], r["b"], "before") is False
    assert templates.place_row(conn, r["b"], r["prep"], "in") is False


@pytest.mark.parametrize("row, target, where", [
    ("top", "prep", "in"),  # a template's top row stays
    ("window", "top", "before"),  # nothing goes beside a top row
    ("window", "top", "after"),
    ("prep", "a", "in"),  # not under itself
    ("prep", "a", "before"),
    ("prep", "prep", "after"),
    ("window", "x", "in"),  # not into another template
    ("window", "x", "before"),
])
def test_what_cant_be_done_is_refused(rows, row, target, where):
    conn, r = rows
    before = shape(conn, r["top"])
    assert not templates.can_place(Library(conn), r[row], r[target], where)
    with pytest.raises(TaskError, match="only go beside or under"):
        templates.place_row(conn, r[row], r[target], where)
    assert shape(conn, r["top"]) == before


def test_a_row_can_go_under_the_top_row(rows):
    conn, r = rows
    assert templates.can_place(Library(conn), r["a"], r["top"], "in")
    templates.place_row(conn, r["a"], r["top"], "in")
    assert order(conn, r["top"]) == ["Prep", "Window", "Report", "A"]


def test_trees_already_made_keep_their_order_and_new_ones_use_the_new_one(rows):
    conn, r = rows
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, NOW)
    m = Model(conn)
    before = [m.task(x).title for x in m.children_of(made[0])]
    templates.place_row(conn, r["report"], r["prep"], "before")
    m = Model(conn)
    assert [m.task(x).title for x in m.children_of(made[0])] == before
    again = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 2", None, {}, NOW)
    m = Model(conn)
    assert sorted(m.task(x).title for x in m.children_of(again[0])) == sorted(before)
    assert m.task(again[1]).title == "Report"


# ---- duplicating ----
def test_a_duplicate_has_the_same_rows_in_the_same_order(rows):
    conn, r = rows
    templates.place_row(conn, r["report"], r["prep"], "before")
    copy = templates.duplicate(conn, Library(conn).rows[r["top"]].template, "Product trial copy", NOW)
    assert shape(conn, copy) == [(0, "Product trial copy"), (1, "Report"), (1, "Prep"), (2, "A"), (2, "B"), (1, "Window")]


def test_a_duplicate_holds_all_they_hold(rows):
    conn, r = rows
    lib = Library(conn)
    copy = templates.duplicate(conn, lib.rows[r["top"]].template, "Copy", NOW)
    lib = Library(conn)
    top = lib.rows[copy]
    assert top.labels == ["Safety"] and top.leads == ["P001"]
    window = next(x for x, _ in lib.walk(copy) if x.title == "Window")
    assert (window.assignees, window.assignee_per_week, window.duration) == ([PRIYA, TOM], 3, 5)
    assert window.involvement == {("assignee", TOM): 25} and "Book the room" in window.notes
    assert next(x for x, _ in lib.walk(copy) if x.title == "Report").assignee_hours == 12


def test_a_duplicate_is_a_template_of_its_own(rows):
    conn, r = rows
    tree = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {}, NOW)
    templates.apply_row(conn, SETTINGS, r["report"], {"title": "Report", "inherit_labels": True, "assignee_hours": 20}, NOW)
    lib = Library(conn)
    original = lib.rows[r["top"]].template
    copy = templates.duplicate(conn, original, "Copy", NOW)
    lib = Library(conn)
    new = lib.rows[copy].template
    assert new != original
    assert lib.trees(new) == [] and lib.changes.get(new, []) == []  # no trees, and an empty Changes list
    assert len(lib.trees(original)) == 1  # the tree still follows the original
    assert {x.id for x, _ in lib.walk(copy)}.isdisjoint(x.id for x, _ in lib.walk(r["top"]))
    # A change to the copy reaches nothing, and leaves the original alone
    report = next(x for x, _ in lib.walk(copy) if x.title == "Report")
    templates.apply_row(conn, SETTINGS, report.id, {"title": "Report", "inherit_labels": True, "assignee_hours": 99}, NOW)
    assert Library(conn).rows[r["report"]].assignee_hours == 20
    assert load_tasks(conn, [tree[-1]])[tree[-1]].assignee_hours == 20
    # A change to the original leaves the copy alone
    templates.apply_row(conn, SETTINGS, r["report"], {"title": "Report", "inherit_labels": True, "assignee_hours": 7}, NOW)
    assert Library(conn).rows[report.id].assignee_hours == 99


def test_making_tasks_from_a_duplicate_works(rows):
    conn, r = rows
    copy = templates.duplicate(conn, Library(conn).rows[r["top"]].template, "Copy", NOW)
    made = templates.make_tasks(conn, SETTINGS, copy, "Trial 9", None, {}, NOW)
    assert len(made) == 6 and load_tasks(conn, [made[0]])[made[0]].title == "Trial 9"


def test_the_original_is_unchanged(rows):
    conn, r = rows
    before = shape(conn, r["top"])
    templates.duplicate(conn, Library(conn).rows[r["top"]].template, "Copy", NOW)
    assert shape(conn, r["top"]) == before


def test_a_duplicate_needs_a_name(rows):
    conn, r = rows
    live = len(Library(conn).live())
    with pytest.raises(TaskError, match="needs a name"):
        templates.duplicate(conn, Library(conn).rows[r["top"]].template, "   ", NOW)
    assert len(Library(conn).live()) == live


# ---- the view ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, SETTINGS, now=lambda: NOW))
    w.confirm = lambda title, text: True
    w.resize(1400, 900)
    w.show_browse()
    w.r = build(conn)
    w.refresh()
    w.templates.open_row(str(w.r["top"]))
    QApplication.processEvents()
    yield w
    w.deleteLater()


def answer(w, fill):
    def run(dialog):
        fill(dialog)
        problem = dialog.problem() if hasattr(dialog, "problem") else None
        assert problem is None, problem
        return True
    w.run_dialog = run


def item_of(w, row_id: int):
    return next(x for x in w.tree.items() if x.data(0, KEY_ROLE) == ("tplrow", str(row_id)))


def point_in(w, row_id: int, where: str) -> QPoint:
    rect = w.tree.visualItemRect(item_of(w, row_id))
    y = {"before": rect.top() + 1, "after": rect.bottom() - 1, "in": rect.center().y()}[where]
    return QPoint(rect.left() + 40, y)


def drop(w, row_id: int, target: int, where: str) -> None:
    """A drag's last two events, as Qt sends them, and the tick that runs what they asked for."""
    w.select("tplrow", str(row_id), update_list=True)
    QApplication.processEvents()
    pos = point_in(w, target, where)
    mime = QMimeData()
    w.tree.dropEvent(QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()


def test_a_drag_puts_a_row_before_after_or_under(browse):
    r, conn = browse.r, browse.conn
    drop(browse, r["report"], r["prep"], "before")
    assert order(conn, r["top"]) == ["Report", "Prep", "Window"]
    drop(browse, r["report"], r["window"], "after")
    assert order(conn, r["top"]) == ["Prep", "Window", "Report"]
    drop(browse, r["report"], r["prep"], "in")
    assert order(conn, r["prep"]) == ["A", "B", "Report"]


def test_a_drag_draws_the_list_again_and_keeps_the_row_selected(browse):
    r = browse.r
    drop(browse, r["report"], r["prep"], "before")
    assert browse.sel == ("tplrow", str(r["report"]))
    assert browse.tree.currentItem().data(0, KEY_ROLE) == ("tplrow", str(r["report"]))
    titles = [item_of(browse, x).data(0, KEY_ROLE) for x in (r["report"], r["prep"])]
    keys = browse.tree.keys()
    assert keys.index(titles[0]) < keys.index(titles[1])


def test_a_drag_says_trees_keep_their_order(browse):
    said = []
    browse.say = lambda text, error=False: said.append(text)
    r = browse.r
    drop(browse, r["report"], r["prep"], "before")
    assert said and "trees already made keep theirs" in said[-1]


def test_a_refused_drop_does_nothing(browse):
    r, conn = browse.r, browse.conn
    before = shape(conn, r["top"])
    drop(browse, r["prep"], r["a"], "in")  # under itself
    drop(browse, r["window"], r["x"], "in")  # into another template
    assert shape(conn, r["top"]) == before and shape(conn, r["other"]) == [(0, "Equipment audit"), (1, "X")]


def test_the_drag_hover_refuses_what_a_drop_would(browse):
    r = browse.r
    browse.select("tplrow", str(r["prep"]), update_list=True)
    QApplication.processEvents()
    mime = QMimeData()

    def hover(target: int, where: str) -> bool:
        pos = point_in(browse, target, where)
        event = QDragMoveEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        browse.tree.dragMoveEvent(event)
        return event.isAccepted()
    assert hover(r["report"], "before") and hover(r["report"], "in")
    assert not hover(r["a"], "in") and not hover(r["x"], "before")


def test_the_top_row_cant_be_dragged(browse):
    r = browse.r
    assert not item_of(browse, r["top"]).flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert item_of(browse, r["window"]).flags() & Qt.ItemFlag.ItemIsDragEnabled


def test_alt_up_and_alt_down_move_the_selected_row(browse):
    r, conn = browse.r, browse.conn
    browse.select("tplrow", str(r["report"]), update_list=True)
    QApplication.processEvents()
    QTest.keyClick(browse.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert order(conn, r["top"]) == ["Prep", "Report", "Window"]
    assert browse.tree.currentItem().data(0, KEY_ROLE) == ("tplrow", str(r["report"]))
    QTest.keyClick(browse.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert order(conn, r["top"]) == ["Report", "Prep", "Window"]
    QTest.keyClick(browse.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)  # already first
    assert order(conn, r["top"]) == ["Report", "Prep", "Window"]
    QTest.keyClick(browse.tree, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert order(conn, r["top"]) == ["Prep", "Report", "Window"]


def test_alt_keys_leave_a_top_row_alone(browse):
    r, conn = browse.r, browse.conn
    browse.select("tplrow", str(r["top"]), update_list=True)
    QApplication.processEvents()
    QTest.keyClick(browse.tree, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert order(conn, r["top"]) == ["Prep", "Window", "Report"]


def test_plain_arrows_still_move_between_rows(browse):
    r, conn = browse.r, browse.conn
    browse.select("tplrow", str(r["report"]), update_list=True)
    QApplication.processEvents()
    QTest.keyClick(browse.tree, Qt.Key.Key_Up)
    assert order(conn, r["top"]) == ["Prep", "Window", "Report"]
    assert browse.tree.currentItem().data(0, KEY_ROLE) == ("tplrow", str(r["window"]))


def test_other_views_dont_get_it(browse):
    assert browse.tree.dragEnabled()
    browse.view = "tasks"
    browse.render_all()
    QApplication.processEvents()
    assert not browse.tree.dragEnabled() and browse.tree._moves is None
    before = list(browse.tree.keys())
    item = browse.tree.currentItem() or browse.tree.topLevelItem(0)
    browse.tree.setCurrentItem(item)
    QTest.keyClick(browse.tree, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert browse.tree.keys() == before
    browse.view = "templates"
    browse.render_all()
    assert browse.tree.dragEnabled()


def test_the_move_menu_still_works_and_says_so(browse):
    said = []
    browse.say = lambda text, error=False: said.append(text)
    r, conn = browse.r, browse.conn
    browse.templates.shift(r["report"], -1)
    assert order(conn, r["top"]) == ["Prep", "Report", "Window"] and "Moved Report" in said[-1]
    browse.templates.reparent(r["report"], r["prep"])
    assert order(conn, r["prep"]) == ["A", "B", "Report"]


def test_duplicate_on_a_template_asks_for_a_name_and_opens_the_copy(browse):
    r, conn = browse.r, browse.conn
    seen = {}

    def fill(d):
        seen["title"] = d.windowTitle()
        seen["name"] = d.name.text()
        assert d.commit_button.text() == "Duplicate"
        d.name.setText("Gloss trial")
    answer(browse, fill)
    browse.templates.duplicate(Library(conn).rows[r["top"]].template)
    assert seen == {"title": "Duplicate Product trial", "name": "Product trial copy"}
    lib = Library(conn)
    assert sorted(lib.name(t.id) for t in lib.live()) == ["Equipment audit", "Gloss trial", "Product trial"]
    new = next(t for t in lib.live() if lib.name(t.id) == "Gloss trial")
    assert browse.sel == ("tplrow", str(new.top)) and browse.view == "templates"


def test_a_duplicate_needs_a_name_in_its_form(browse):
    r, conn = browse.r, browse.conn
    seen = {}

    def run(d):
        d.name.setText("  ")
        seen["problem"] = d.check()
        return False
    browse.run_dialog = run
    browse.templates.duplicate(Library(conn).rows[r["top"]].template)
    assert seen["problem"] == "A template needs a name." and len(Library(conn).live()) == 2


def test_duplicate_shows_on_a_template_and_not_on_a_row(browse):
    r = browse.r
    shown = lambda: [b.text() for b in browse.findChildren(QPushButton) + browse.findChildren(QToolButton) if b.text() and b.isVisibleTo(browse)]  # noqa: E731
    browse.select("tplrow", str(r["top"]), update_list=True)
    QApplication.processEvents()
    assert "Duplicate…" in shown()
    browse.select("tplrow", str(r["window"]), update_list=True)
    QApplication.processEvents()
    assert "Duplicate…" not in shown() and "Move" in shown()
