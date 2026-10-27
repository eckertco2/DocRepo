"""The task tree's Group by, and Collapse a level and Expand a level on every view whose rows nest (release 5.24), driven
offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE  # noqa: E402
from docrepo.views import TreeFilter, tree_sections, walk  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)


@pytest.fixture
def m():
    c = db.connect_memory()
    load_sample(c)
    yield Model(c)
    c.close()


def test_sections(m):
    """A section per group, person or label, each with its tasks in tree shape; the ones in none last."""
    groups = tree_sections(m, TreeFilter(), "group")
    assert [s.name for s in groups] == [*m.groups(), "No group", "No one"]
    eng = groups[0]
    matched = [n.id for n in walk(eng.nodes) if n.match]
    assert eng.count == len(matched)
    members = set(m.group_people("Engineering"))
    assert all(members & {*m.task(x).leads, *m.task(x).assignees} for x in matched)
    # The tree shape: a matching subtask keeps its parents, dimmed when they don't match.
    reactor = next(n for n in eng.nodes if n.id == "T000001")
    assert reactor.children
    people = tree_sections(m, TreeFilter(), "person")
    assert people[0].name == m.people["P001"].name and people[0].sub == "Engineering, Project engineer"
    assert any(s.name == "No label" for s in tree_sections(m, TreeFilter(), "label"))


def test_only_whats_ticked_gets_a_section(m):
    maintenance = tuple(m.group_people("Maintenance"))
    assert [s.name for s in tree_sections(m, TreeFilter(people=maintenance), "group")] == ["Maintenance"]
    assert [s.name for s in tree_sections(m, TreeFilter(people=("P003",)), "person")] == ["Tom Becker"]
    assert [s.name for s in tree_sections(m, TreeFilter(labels=("Safety",)), "label")] == ["Safety"]
    # A task in two groups is in both.
    both = [s for s in tree_sections(m, TreeFilter(), "group") if s.name in ("Engineering", "Maintenance")]
    ids = [{n.id for n in walk(s.nodes) if n.match} for s in both]
    assert ids[0] & ids[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext

    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT), None)
    w.show_browse("tasks")
    yield w
    w.hide()
    w.deleteLater()


def heads(w) -> list[str]:
    root = w.tree.invisibleRootItem()
    return [root.child(i).data(0, 0x101) or "" for i in range(root.childCount())]


def test_the_trees_group_by(browse):
    from PySide6.QtWidgets import QComboBox

    box = next(b for b in browse.filters.findChildren(QComboBox) if b.accessibleName() == "Group by")
    assert box.currentData() == "" and box.findData("group") >= 0
    browse._set_tree_group("group")
    root = browse.tree.invisibleRootItem()
    names = [root.child(i).data(0, 0x101) for i in range(root.childCount())]
    assert len(names) == 5 and "Engineering" in names[0] and "No one" in names[-1]
    first = root.child(0)
    assert first.data(0, KEY_ROLE) is None and first.childCount() and first.child(0).data(0, KEY_ROLE)[0] == "task"
    browse.tree_filter["people"] = list(browse.model().group_people("Maintenance"))
    browse.render_list()
    assert root.childCount() == 1 and "Maintenance" in root.child(0).data(0, 0x101)
    browse.tree_filter["people"] = []
    browse._set_tree_group("")
    assert root.child(0).data(0, KEY_ROLE) == ("task", "T000001")


def test_level_buttons_on_the_other_views(browse):
    """Collapse a level and Expand a level on Agendas, Activity, the lists and the rest whose rows nest; a row folded by
    hand stays folded when the view is drawn again."""
    browse.set_view("activity")
    assert browse._lvl_collapse.isEnabled() and not browse._lvl_expand.isEnabled()
    browse._lvl_collapse.click()  # each branch folds up one step: the task headings fold, and groups of lines only
    root = browse.tree.invisibleRootItem()
    groups = [root.child(i) for i in range(root.childCount()) if root.child(i).childCount()]
    nested = [g for g in groups if any(g.child(i).childCount() for i in range(g.childCount()))]
    assert nested and all(g.isExpanded() for g in nested) and browse._lvl_expand.isEnabled()
    assert not any(g.child(i).isExpanded() for g in groups for i in range(g.childCount()) if g.child(i).childCount())
    browse._lvl_collapse.click()
    assert not any(g.isExpanded() for g in groups)
    browse.render_list()  # drawn again: still folded
    root = browse.tree.invisibleRootItem()
    assert not any(root.child(i).isExpanded() for i in range(root.childCount()) if root.child(i).childCount())
    browse._lvl_expand.click()
    browse._lvl_expand.click()
    assert not browse._lvl_expand.isEnabled()
    for view in ("due", "agenda", "docs", "labels", "today"):
        browse.set_view(view)
        assert browse._lvl_collapse.parent() is not None, view
    browse.set_view("people")
    assert browse._lvl_collapse.parent() is None or not browse._lvl_collapse.isVisibleTo(browse)  # always flat: none
