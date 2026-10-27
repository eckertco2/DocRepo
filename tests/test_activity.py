"""The Activity view (mods log round 2, M0032; release 5.23, decisions 70 to 73): what happened in a window, where each line
goes, the groups and filters, Copy as Markdown and Add to agenda, and the view, driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import activity, db, edits, priorities  # noqa: E402
from docrepo.activity import Activity, Filter, window  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import TODAY as TODAY_ID, Model  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402

TODAY = date(2026, 10, 8)  # a Thursday
AT = datetime(2026, 10, 8, 14, 10)


@pytest.fixture
def conn():
    c = db.connect_memory()
    load_sample(c)
    yield c
    c.close()


def this_week(conn):
    a = Activity(Model(conn), TODAY)
    return a, a.lines(*window("week", TODAY))


def test_the_windows():
    assert window("week", TODAY) == (date(2026, 10, 5), TODAY)
    assert window("last", TODAY) == (date(2026, 9, 28), date(2026, 10, 4))
    assert window("7d", TODAY) == (date(2026, 10, 2), TODAY)
    assert window("range", TODAY, date(2026, 10, 7), date(2026, 10, 1)) == (date(2026, 10, 1), date(2026, 10, 7))


def test_what_this_week_shows(conn):
    """Decision 70: captures, changes made outside a capture, document versions and agenda items, oldest first."""
    a, lines = this_week(conn)
    assert lines and [x.at for x in lines] == sorted(x.at for x in lines)
    assert all("2026-10-05" <= x.at[:10] <= "2026-10-08" for x in lines)
    by = {x.key: x for x in lines}
    # A new subtask is listed under its parent and is about itself.
    rigging = next(x for x in lines if x.chip == "New subtask" and x.text == "Rigging plan")
    assert (rigging.task, rigging.about, rigging.open) == ("T000008", "T000012", ("task", "T000012"))
    # An update says what it changed.
    vendor = next(x for x in lines if x.chip == "Update" and x.task == "T000009")
    assert "Due date moved to Fri 23 Oct." in vendor.facts and vendor.open[0] == "capture"
    # A change made in the browse tool is a line of its own; one made by a capture shows on the capture's line.
    assert any(x.kinds == ["change"] and x.task == "T000012" and x.text == "Work started." for x in lines)
    assert not any(x.kinds == ["change"] and x.facts and x.facts[0].startswith("By C") for x in lines)
    # A document version, a note put only on an agenda (under that meeting), and the unfiled captures.
    assert any(x.chip == "Document" and x.open[0] == "doc" for x in lines)
    assert any(x.chip == "Agenda" and x.task == "T000010" and x.facts == ["Put on its agenda, as a note"] for x in lines)
    unfiled = [x for x in lines if x.task is None]
    assert unfiled and all(x.open[0] == "capture" for x in unfiled)
    assert len(by) == len(lines)  # every line has its own key
    # Today's own items are left out.
    assert not any("Today" in x.text for x in lines if x.chip == "Agenda")


def test_the_groups(conn):
    """Decision 71: tree order under each top-level task, a top-level task's own lines first, unfiled last; or by person,
    group or label."""
    a, lines = this_week(conn)
    m = Model(conn)
    groups = a.groups(lines)
    assert groups[0].name == "Reactor impeller upgrade" and groups[0].colour == 0
    assert groups[-1].unfiled and groups[-1].name == "Not filed yet"
    reactor = groups[0]
    assert reactor.headings[0].task == "T000001"  # its own lines straight under the header
    order = [h.task for h in reactor.headings]
    assert order.index("T000008") < order.index("T000012")
    assert sum(len(g.lines) for g in groups) == len(lines)
    people = a.groups(lines, "person")
    assert people[0].name == m.people["P001"].name and people[0].person == "P001" and people[0].sub
    assert any(g.name == "No one" for g in people)
    assert [g.name for g in a.groups(lines, "group")][:2] == ["Engineering", "Maintenance"]
    assert any(g.name == "No label" for g in a.groups(lines, "label"))


def test_the_filters(conn):
    a, lines = this_week(conn)
    m = Model(conn)
    notes = [x for x in lines if a.passes(x, Filter(kinds=("note",)))]
    assert notes and all("note" in x.kinds for x in notes)
    mike = [x for x in lines if a.passes(x, Filter(people=("P004",)))]
    assert mike and all("P004" in (*m.task(x.about).leads, *m.task(x.about).assignees) for x in mike)
    assert not any(x.task is None for x in mike)  # an unfiled line has no task to match


def test_a_priority_move_shows(conn):
    priorities.place(conn, "T000012", "critical", at=AT, via=priorities.VIA)
    _, lines = this_week(conn)
    line = next(x for x in lines if x.chip == "Priority")
    assert (line.text, line.facts, line.task) == ("Ranked Critical.", ["On the Priorities board"], "T000012")


def test_markdown_and_agenda_notes(conn):
    a, lines = this_week(conn)
    md = a.markdown(a.groups(lines), window("week", TODAY))
    assert md.startswith("## Activity, Mon 5 Oct to today\n\n### Reactor impeller upgrade\n")
    assert "- **Installation**\n  - 5 Oct, document: Installation procedure.docx changed." in md
    vendor = next(x for x in lines if x.chip == "Update" and x.task == "T000009")
    rigging = next(x for x in lines if x.chip == "New subtask" and x.text == "Rigging plan")
    unfiled = next(x for x in lines if x.task is None)
    items = dict(a.agenda_items(lines, {"l:" + vendor.key, "t:T000002", "l:" + rigging.key, "l:" + unfiled.key}))
    assert items["T000009"].startswith("Update, 7 Oct: Vendor drawings came in late") and "Due date moved to Fri 23 Oct." in items["T000009"]
    assert items["T000002"] == ""  # a ticked task with no ticked lines
    assert items["T000012"] == "New on 5 Oct: Mike Ortiz, due 14 Oct."  # a new task's own line says only that it's new
    assert items[None] == unfiled.text


def test_add_to_agenda(sample_root):
    """Decision 72: one item per task; a task already open on that agenda isn't added twice."""
    conn, root, fs = sample_root
    m = Model(conn)
    meeting = m.open_meetings()[0].id
    already = next(a.subject for a in m.open_items_for(meeting) if a.subject)
    out = edits.add_activity_to_agenda(conn, root, fs, meeting, [("T000009", "Update, 7 Oct: late."), (already, ""), (None, "A loose note")], AT)
    assert out.message.startswith("Added 2 to the agenda of") and "Already on it" in out.message
    m = Model(conn)
    added = [a for a in m.agenda if a.added_by == activity.VIA]
    assert [(a.subject, a.note, a.target) for a in added] == [("T000009", "Update, 7 Oct: late.", meeting), (None, "A loose note", meeting)]
    edits.add_activity_to_agenda(conn, root, fs, TODAY_ID, [("T000009", "")], AT)
    assert any(a.subject == "T000009" for a in Model(conn).today_items())


# ---- the view, offscreen ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext

    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT), None)
    w.show_browse("activity")
    yield w
    w.hide()
    w.deleteLater()


def test_the_view(browse):
    """Decision 73: in the list pane, with the line's capture, task or document on the right."""
    keys = browse.tree.keys()
    lines = [k for k in keys if k and k[0] == "actline"]
    assert lines and ("task", "T000001") in keys and browse.view == "activity"
    assert "happened" in browse.pane_title.text()
    item = next(i for i in browse.tree.items() if i.data(0, 0x100) == lines[0])
    browse.tree.setCurrentItem(item)  # a click: the line opens its capture, and stays the selected row
    line = browse._act_lines[lines[0][1]]
    assert browse.sel == line.open and browse.tree.currentItem() is item
    browse.render_list()
    assert browse.tree.currentItem().data(0, 0x100) == lines[0]
    browse._set_act("group", "person")
    assert ("person", "P001") in browse.tree.keys()
    browse._set_act("kinds", ["note"])
    shown = [browse._act_lines[k[1]] for k in browse.tree.keys() if k and k[0] == "actline"]
    assert shown and all("note" in x.kinds for x in shown)
    browse.copy_activity()
    assert QGuiApplication.clipboard().text().startswith("## Activity, Mon 5 Oct to today")


def test_select_and_add_to_agenda(browse):
    browse._set_act("group", "top")
    browse._set_act_select(True)
    assert browse._act_add.isEnabled() is False and "Tick" in browse._act_count.text()
    vendor = next(k for k, x in browse._act_lines.items() if x.chip == "Update" and x.task == "T000009")
    browse._tick(("actline", vendor), True)
    browse._tick(("task", "T000017"), True)
    assert "2 ticked" in browse._act_count.text() and browse._act_add.isEnabled()
    target = browse.act["target"]
    assert target == browse.model().open_meetings()[0].id  # the next open meeting first
    browse.add_activity_to_agenda()
    assert "Added 2 to the agenda of" in browse.status.text() and not browse.act["select"] and not browse.act["picked"]
    m = browse.model()
    assert {a.subject for a in m.open_items_for(target) if a.added_by == activity.VIA} == {"T000009", "T000017"}


def test_the_sidebar_has_both(browse):
    assert [r for r in browse.nav.members["Plan"]] == ["agenda", "activity", "priorities", "timeline", "capacity"]
    browse.nav.rows["priorities"].click()
    assert browse.view == "priorities" and browse.middle.currentWidget() is browse.priorities
