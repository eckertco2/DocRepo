"""The Templates view, its forms, the preview and Edit task's marks (releases 5.44 and 5.45), driven offscreen (no window
appears) over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import tasks, templates  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.templates import Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.templates_view import MakeTasksDialog, PreviewDialog, RowDialog, SaveAsDialog  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE  # noqa: E402
from docrepo.ui.widgets import Chip  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW))
    w.confirm = lambda title, text: True
    w.shown = []
    w.show_browse()
    yield w
    w.deleteLater()


def answer(w, fill):
    """Say what the next forms do: ``fill`` fills each in, and it's saved unless ``fill`` says False."""
    def run(dialog):
        w.shown.append(dialog)
        said = fill(dialog)
        problem = dialog.problem() if hasattr(dialog, "problem") else None
        assert problem is None, problem
        return said is not False
    w.run_dialog = run


def trial(w) -> dict:
    conn = w.conn
    top = templates.new_template(conn, "Product trial", NOW, {"labels": ["Safety"], "leads": ["P001"]})
    settings = w.ctx.settings
    window = templates.add_row(conn, settings, top, {"title": "Trial execution window", "inherit_labels": True, "assignees": ["P002"], "assignee_hours": 6,
                                                     "notes": "- [ ] Book the room"}, NOW)[0]
    report = templates.add_row(conn, settings, top, {"title": "Trial report", "inherit_labels": True}, NOW)[0]
    w.refresh()
    return {"top": top, "window": window, "report": report}


def tree(w, r, name="Trial 1") -> list[str]:
    made = templates.make_tasks(w.conn, w.ctx.settings, r["top"], name, None, {}, NOW)
    w.refresh()
    return made


def buttons(w) -> list[str]:
    layout = w.actions_layout
    return [layout.itemAt(i).widget().text() for i in range(layout.count())]


def button(w, text):
    layout = w.actions_layout
    return next(layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget().text() == text)


def test_the_view_is_under_manage_and_says_how_to_start(browse):
    assert "templates" in browse.nav.rows and browse.nav.members["Manage"].index("templates") == 2
    browse.set_view("templates")
    assert browse.view == "templates" and browse.sel is None and not browse.detail.isVisible()
    assert browse.pane_title.text() == "Templates"
    words = browse.tree.topLevelItem(0).data(0, HTML_ROLE)
    assert "No templates yet" in words and "Save as template" in words


def test_the_list_shows_templates_and_their_rows(browse):
    r = trial(browse)
    browse.set_view("templates")
    assert browse.sel == ("tplrow", str(r["top"]))
    assert ("tplrow", str(r["window"])) in browse.tree.keys() and ("tplrow", str(r["report"])) in browse.tree.keys()
    assert "Product trial" in browse.page.toPlainText()
    assert buttons(browse)[:3] == ["Make tasks", "Add subtask", "Edit"] and "Discard…" in buttons(browse)
    assert "Changes" in browse.page.toPlainText() and "None yet" in browse.page.toPlainText()
    browse.select("tplrow", str(r["window"]))
    assert buttons(browse)[0] == "Make tasks from here" and "Take out…" in buttons(browse) and "Move" in buttons(browse)
    text = browse.page.toPlainText()
    assert "Trial execution window" in text and "Starting notes" in text and "Book the room" in text and "No tasks yet" in text


def test_a_template_never_reaches_the_task_tree(browse):
    trial(browse)
    browse.set_view("tasks")
    assert not any(k[0] == "tplrow" for k in browse.tree.keys())
    assert not any("Product trial" == t.title for t in browse.model().tasks.values())


def test_new_template(browse):
    browse.set_view("templates")
    answer(browse, lambda d: d.name.setText("Equipment audit"))
    browse.templates.new_template()
    lib = Library(browse.conn)
    assert [lib.name(t.id) for t in lib.live()] == ["Equipment audit"]
    assert browse.view == "templates" and browse.sel == ("tplrow", str(lib.live()[0].top))


def test_add_and_edit_a_row_with_no_trees(browse):
    """With nothing to reach, there's no preview."""
    r = trial(browse)
    browse.set_view("templates")

    def fill(d: RowDialog):
        d.title_box.setText("Pre-trial review")
        d.description.setPlainText("Check it's ready.")
        d.assignees.set_chips([Chip("P003", "Tom")])
        d.asg_hours.setText("4")
        d.notes.setPlainText("[] not typed as a key here")
    answer(browse, fill)
    browse.templates.add_subtask(r["top"])
    assert not any(isinstance(d, PreviewDialog) for d in browse.shown)
    lib = Library(browse.conn)
    new = next(x for x in lib.children(r["top"]) if x.title == "Pre-trial review")
    assert browse.sel == ("tplrow", str(new.id)) and new.assignees == ["P003"] and new.assignee_hours == 4 and new.description == "Check it's ready."
    assert new.notes

    def more(d: RowDialog):
        assert d.title_box.text() == "Pre-trial review" and d.asg_hours.text() == "4" and d.assignees.values() == ["P003"]
        d.asg_hours.setText("8")
        d.urgent.setChecked(True)
        d.recurrence.setCurrentText("Weekly")
    browse.shown.clear()
    answer(browse, more)
    browse.templates.edit_row(new.id)
    assert not any(isinstance(d, PreviewDialog) for d in browse.shown)
    again = Library(browse.conn).rows[new.id]
    assert again.assignee_hours == 8 and again.urgent and again.recurrence == "Weekly" and again.notes == new.notes
    assert "Saved. No tasks follow it yet." in browse.status.text()


def test_a_row_form_saves_formatted_starting_notes(browse):
    r = trial(browse)

    def fill(d: RowDialog):
        assert d.notes.toPlainText() == "Book the room"  # the checklist line, shown as one
        d.title_box.setText("Trial execution window")
    answer(browse, fill)
    browse.templates.edit_row(r["window"])
    assert Library(browse.conn).rows[r["window"]].notes == "- [ ] Book the room"


def test_a_row_form_asks_for_a_title(browse):
    r = trial(browse)
    lib = Library(browse.conn)
    d = RowDialog(browse, browse.model(), lib.rows[r["top"]], browse._label_options, browse._people_options, "Edit template", True)
    d.title_box.setText("  ")
    assert d.problem() == "A template needs a name."
    d.title_box.setText("Trial")
    d.asg_hours.setText("many")
    assert d.problem() == "Assignee hours isn't a number of hours."


# ---- the preview, in its three forms (decisions 186 and 188) ----
def test_a_changed_field_shows_what_it_reaches_and_applies_what_is_ticked(browse):
    r = trial(browse)
    a, b = tree(browse, r), tree(browse, r, "Trial 2")
    c = tree(browse, r, "Trial 3")
    tasks.update_task(browse.conn, browse.ctx.settings, c[1], at=NOW, via="Browse tool", assignee_hours=9)
    browse.refresh()
    seen = {}

    def fill(d):
        if isinstance(d, RowDialog):
            d.asg_hours.setText("2")
            return True
        seen["heading"] = d.windowTitle()
        seen["keys"] = list(d.ticks)
        seen["button"] = d.commit_button.text()
        seen["total"] = d.total_line.text()
        seen["folded"] = d.fold_button.text()
        d.ticks[b[1]].setChecked(False)
        seen["then"] = (d.commit_button.text(), d.total_line.text())
        return True
    answer(browse, fill)
    browse.templates.edit_row(r["window"])
    assert seen["heading"] == "This change reaches 2 tasks" and seen["keys"] == [a[1], b[1]]
    assert seen["button"] == "Apply to 2 tasks" and seen["total"] == "Work across these tasks: 12 h → 4 h"
    assert seen["folded"].startswith("Not changing: 1 with its own value")
    assert seen["then"] == ("Apply to 1 task", "Work across these tasks: 6 h → 2 h")
    ts = load_tasks(browse.conn, [a[1], b[1], c[1]])
    assert (ts[a[1]].assignee_hours, ts[b[1]].assignee_hours, ts[c[1]].assignee_hours) == (2, 6, 9)
    assert "1 task changed, 1 left as it was." in browse.status.text()
    assert browse.sel == ("tplrow", str(r["window"]))
    browse.select("tplrow", str(r["top"]))
    assert "Assignee hours 6 h → 2 h" in browse.page.toPlainText() and "1 task changed, 1 left as it was" in browse.page.toPlainText()


def test_back_returns_to_the_form_as_typed(browse):
    r = trial(browse)
    a = tree(browse, r)
    forms = []

    def fill(d):
        if isinstance(d, RowDialog):
            forms.append(d.asg_hours.text())
            if len(forms) == 1:
                d.asg_hours.setText("2")
                return True
            return False  # then Cancel the form
        return False  # Back
    answer(browse, fill)
    browse.templates.edit_row(r["window"])
    assert forms == ["6", "2"]  # the form again, as typed
    assert load_tasks(browse.conn, [a[1]])[a[1]].assignee_hours == 6  # and nothing changed
    assert Library(browse.conn).rows[r["window"]].assignee_hours == 6


def test_unticking_every_task_saves_changing_none(browse):
    r = trial(browse)
    a = tree(browse, r)
    words = []

    def fill(d):
        if isinstance(d, RowDialog):
            d.asg_hours.setText("2")
        else:
            d.ticks[a[1]].setChecked(False)
            words.append(d.commit_button.text())
            assert not d.total_line.isVisibleTo(d)
    answer(browse, fill)
    browse.templates.edit_row(r["window"])
    assert words == ["Save, changing no tasks"]
    assert Library(browse.conn).rows[r["window"]].assignee_hours == 2 and load_tasks(browse.conn, [a[1]])[a[1]].assignee_hours == 6


def test_a_new_subtask_is_offered_to_the_open_trees(browse):
    r = trial(browse)
    a, b = tree(browse, r), tree(browse, r, "Trial 2")
    c = tree(browse, r, "Trial 3")
    tasks.update_task(browse.conn, browse.ctx.settings, c[0], at=NOW, via="Browse tool", state="Closed")
    browse.refresh()
    seen = {}

    def fill(d):
        if isinstance(d, RowDialog):
            d.title_box.setText("Pre-trial review")
            return True
        seen.update(heading=d.windowTitle(), keys=list(d.ticks), folded=d.fold_button.text(), button=d.commit_button.text())
        d.ticks[b[0]].setChecked(False)
        return True
    answer(browse, fill)
    browse.templates.add_subtask(r["top"])
    assert seen["heading"] == "Add “Pre-trial review” to existing trees?" and seen["keys"] == [a[0], b[0]]
    assert seen["folded"].startswith("Not offered: 1 closed tree") and seen["button"] == "Add to 2 trees"
    m = Model(browse.conn)
    assert any(m.task(k).title == "Pre-trial review" for k in m.children_of(a[0]))
    assert not any(m.task(k).title == "Pre-trial review" for k in m.children_of(b[0]))
    assert "Added to 1 tree" in browse.status.text()


def test_taking_a_row_out_offers_to_discard_its_copies(browse):
    r = trial(browse)
    a, b = tree(browse, r), tree(browse, r, "Trial 2")
    tasks.update_task(browse.conn, browse.ctx.settings, b[1], at=NOW, via="Browse tool", state="In progress")
    browse.refresh()
    browse.set_view("templates")
    browse.select("tplrow", str(r["window"]), update_list=True)
    seen = {}

    def fill(d: PreviewDialog):
        seen.update(heading=d.windowTitle(), button=d.commit_button.text(), ticked=d.ticked(), can=[d.ticks[k].isEnabled() for k in d.ticks])
    answer(browse, fill)
    browse.templates.take_out(r["window"])
    assert seen["heading"] == "Take “Trial execution window” out of the template?" and seen["button"] == "Take it out"
    assert seen["ticked"] == [a[1]] and seen["can"] == [True, False]
    assert r["window"] not in Library(browse.conn).rows and browse.sel == ("tplrow", str(r["top"]))
    m = Model(browse.conn)
    assert m.task(a[1]).discarded and m.task(a[1]).discard_reason == "Taken out of template Product trial" and not m.task(b[1]).discarded
    assert "1 copy discarded" in browse.status.text() and "stays, no longer following" in browse.status.text()


def test_cancelling_a_take_out_changes_nothing(browse):
    r = trial(browse)
    tree(browse, r)
    answer(browse, lambda d: False)
    browse.templates.take_out(r["window"])
    assert r["window"] in Library(browse.conn).rows


def test_taking_a_row_with_no_tasks_out_says_so(browse):
    r = trial(browse)
    seen = {}

    def fill(d: PreviewDialog):
        seen["words"] = " ".join(x.text() for x in d.findChildren(QLabel))
    answer(browse, fill)
    browse.templates.take_out(r["report"])
    assert "No tasks were made from it." in seen["words"] and r["report"] not in Library(browse.conn).rows


# ---- Edit task's marks (decision 184) ----
def form(w, task_id) -> TaskEditDialog:
    return TaskEditDialog(w, w.model(), task_id, w._label_options, w._people_options, reference_fields=(), link=w.templates.link_of(task_id))


def test_a_task_with_no_template_has_no_marks(browse):
    d = form(browse, "T000001")
    assert d.marks == {} and "follow" not in d.values() and not hasattr(d, "row_button")


def test_each_field_the_row_fills_has_its_mark(browse):
    r = trial(browse)
    made = tree(browse, r)
    d = form(browse, made[1])
    assert set(d.marks) == {"title", "assignees", "assignee_hours"}
    assert d.row_button.text() == "Product trial › Trial execution window"
    mark = d.marks["assignee_hours"]
    assert mark.following and mark.mark.text() == "" and "Linked to Product trial: 6 h" in mark.mark.toolTip()
    assert d.values()["follow"] == ["title", "assignees", "assignee_hours"]
    top = form(browse, made[0])
    assert "title" not in top.marks and set(top.marks) == {"labels", "leads"}  # the top task's name is its own


def test_typing_a_different_value_warns_and_stops_on_save(browse):
    r = trial(browse)
    made = tree(browse, r)
    d = form(browse, made[1])
    mark = d.marks["assignee_hours"]
    d.show()
    d.asg_hours.setText("10")
    d.asg_hours.textEdited.emit("10")
    assert mark.leaving.isVisible() and mark.mark.text() == "Template: 6 h ↺"
    assert d.values()["follow"] == ["title", "assignees"]
    browse.save_task_edit(made[1], d.values())
    assert load_tasks(browse.conn, [made[1]])[made[1]].assignee_hours == 10
    assert browse.conn.execute("SELECT count(*) FROM task_links WHERE task = ? AND field = 'assignee_hours'", (made[1],)).fetchone()[0] == 0
    d.hide()
    d.deleteLater()


def test_the_chain_mark_keeps_the_value_and_stops_following(browse):
    r = trial(browse)
    made = tree(browse, r)
    d = form(browse, made[1])
    mark = d.marks["assignee_hours"]
    mark.mark.click()
    assert not mark.following and mark.mark.text() == "Follow template ↺" and d.values()["assignee_hours"] == 6
    assert d.values()["follow"] == ["title", "assignees"] and d.changed()
    browse.save_task_edit(made[1], d.values())
    assert browse.conn.execute("SELECT count(*) FROM task_links WHERE task = ? AND field = 'assignee_hours'", (made[1],)).fetchone()[0] == 0


def test_the_back_mark_takes_the_template_value_and_follows_it_again(browse):
    r = trial(browse)
    made = tree(browse, r)
    tasks.update_task(browse.conn, browse.ctx.settings, made[1], at=NOW, via="Browse tool", assignee_hours=20, assignees=["P003"])
    browse.refresh()
    d = form(browse, made[1])
    hours, people = d.marks["assignee_hours"], d.marks["assignees"]
    assert not hours.following and hours.mark.text() == "Template: 6 h ↺" and people.mark.text() == "Template: Priya Shah ↺"
    hours.mark.click()
    people.mark.click()
    assert d.asg_hours.value() == 6 and d.assignees.values() == ["P002"] and hours.following and hours.mark.text() == ""
    browse.save_task_edit(made[1], d.values())
    t = load_tasks(browse.conn, [made[1]])[made[1]]
    assert t.assignee_hours == 6 and t.assignees == ["P002"]
    fields = {x["field"] for x in browse.conn.execute("SELECT field FROM task_links WHERE task = ?", (made[1],))}
    assert fields == {"title", "assignees", "assignee_hours"}


def test_a_closed_task_stays_following_until_it_reopens(browse):
    """Decision 185: saving a closed task's form leaves a field that fell behind; reopening makes it its own."""
    r = trial(browse)
    made = tree(browse, r)
    settings, conn = browse.ctx.settings, browse.conn
    tasks.update_task(conn, settings, made[1], at=NOW, via="Browse tool", state="Closed")
    values = {"title": "Trial execution window", "inherit_labels": True, "assignees": ["P002"], "assignee_hours": 2, "notes": "- [ ] Book the room"}
    templates.apply_row(conn, settings, r["window"], values, NOW)
    browse.refresh()
    d = form(browse, made[1])
    mark = d.marks["assignee_hours"]
    assert mark.mark.text() == "Template: 2 h ↺" and not mark.leaving.isVisibleTo(d)
    assert "assignee_hours" in d.values()["follow"]
    d.state.setCurrentText("In progress")
    assert "assignee_hours" not in d.values()["follow"]
    browse.save_task_edit(made[1], d.values())
    assert load_tasks(conn, [made[1]])[made[1]].assignee_hours == 6
    entry = [e for e in Model(conn).status_log_of(made[1]) if e.field == "Template link"]
    assert entry[-1].from_value == "Assignee hours: fell behind Product trial while closed, and stays as it is"


def test_a_discarded_templates_tasks_show_no_marks(browse):
    r = trial(browse)
    made = tree(browse, r)
    templates.set_discarded(browse.conn, Library(browse.conn).rows[r["top"]].template, "Not needed", NOW)
    browse.refresh()
    d = form(browse, made[1])
    assert d.marks == {} and "follow" not in d.values()
    browse.go_task(made[1])
    assert "(discarded)" in browse.task_pane.text()


def test_the_forms_line_opens_the_row_or_detaches(browse):
    r = trial(browse)
    made = tree(browse, r)

    def open_row(d):
        d.row_button.click()
        assert d.after == ("row", r["window"])
        return False
    answer(browse, open_row)
    browse.edit_task(made[1])
    assert browse.view == "templates" and browse.sel == ("tplrow", str(r["window"]))

    def detach(d):
        d.detach_button.click()
        assert d.after == ("detach",)
        return False
    answer(browse, detach)
    browse.edit_task(made[1])
    assert made[1] not in Model(browse.conn).origins and load_tasks(browse.conn, [made[1]])[made[1]].assignee_hours == 6


def test_leaving_the_form_with_changes_asks_first(browse):
    r = trial(browse)
    made = tree(browse, r)
    d = form(browse, made[1])
    d.ask_discard = lambda: False
    d.title.setText("Changed")
    d.row_button.click()
    assert d.after is None


def test_detach_from_the_more_menu_asks_first(browse):
    r = trial(browse)
    made = tree(browse, r)
    browse.go_task(made[1])
    more = next(browse.actions_layout.itemAt(i).widget() for i in range(browse.actions_layout.count())
                if browse.actions_layout.itemAt(i).widget().accessibleName() == "More")
    assert "Detach from template…" in [a.text() for a in more.menu().actions()]
    asked = []
    browse.confirm = lambda title, text: asked.append(text) or False
    browse.templates.detach(made[1])
    assert "Its values stay" in asked[0] and made[1] in Model(browse.conn).origins
    browse.confirm = lambda title, text: True
    browse.templates.detach(made[1])
    assert made[1] not in Model(browse.conn).origins and "Detached." in browse.status.text()
    browse.go_task("T000001")
    more = next(browse.actions_layout.itemAt(i).widget() for i in range(browse.actions_layout.count())
                if browse.actions_layout.itemAt(i).widget().accessibleName() == "More")
    assert "Detach from template…" not in [a.text() for a in more.menu().actions()]


# ---- Make tasks and the rest ----
def test_make_tasks_opens_the_new_tree(browse):
    r = trial(browse)
    browse.set_view("templates")

    def fill(d: MakeTasksDialog):
        assert d.commit_button.text() == "Make 3 tasks"
        assert d.problem()  # a name, first
        d.name.setText("Trial 5: gloss finish")
        line = next(x for x in d.lines if x.row.id == r["window"])
        assert line.has_start and line.people.values() == ["P002"]
        line.start.set_value("2026-11-02")
        line.people.add(Chip("P003", "Tom"))
    answer(browse, fill)
    browse.templates.make(r["top"])
    m = Model(browse.conn)
    top = next(t for t in m.tasks.values() if t.title == "Trial 5: gloss finish")
    assert browse.view == "tasks" and browse.sel == ("task", top.id)
    assert top.created_by == "Template: Product trial" and top.labels == ["Safety"]
    kids = [m.task(k) for k in m.children_of(top.id)]
    window = next(k for k in kids if k.title == "Trial execution window")
    assert window.start == "2026-11-02" and window.assignees == ["P002", "P003"] and window.assignee_hours == 6
    assert ("task", window.id) in browse.tree.keys()
    assert "Made 3 tasks." in browse.status.text()
    assert browse.task_pane.text().count("From template:") == 1


def test_make_from_a_row_under_a_task(browse):
    r = trial(browse)

    def fill(d: MakeTasksDialog):
        assert d.name.text() == "Trial execution window" and d.problem() is None
        d.set_under("T000001")
    answer(browse, fill)
    browse.templates.make(r["window"])
    m = Model(browse.conn)
    made = next(t for t in m.tasks.values() if t.title == "Trial execution window")
    assert m.parents_of(made.id) == ["T000001"]


def test_a_row_with_rows_under_it_and_no_hours_has_no_start_box(browse):
    r = trial(browse)
    templates.add_row(browse.conn, browse.ctx.settings, r["report"], {"title": "Draft", "inherit_labels": True}, NOW)
    d = MakeTasksDialog(browse, browse.model(), Library(browse.conn), r["top"], browse._people_options, lambda a, p: None)
    by_row = {x.row.id: x for x in d.lines}
    assert not by_row[r["report"]].has_start and by_row[r["window"]].has_start
    d.name.setText("Trial")
    next(x for x in d.lines if x.row.id == r["window"]).start.line.setText("not a date")
    assert "isn't a date" in d.problem()


def test_moving_a_row(browse):
    r = trial(browse)
    browse.set_view("templates")
    browse.select("tplrow", str(r["report"]), update_list=True)
    browse.templates.shift(r["report"], -1)
    assert [x.id for x in Library(browse.conn).children(r["top"])] == [r["report"], r["window"]]
    browse.templates.reparent(r["report"], r["window"])
    assert [x.id for x in Library(browse.conn).children(r["window"])] == [r["report"]]


def test_discarding_and_bringing_back(browse):
    r = trial(browse)
    made = tree(browse, r)
    browse.ask_reason = lambda title, text: "Not needed"
    browse.set_view("templates")
    t = Library(browse.conn).rows[r["top"]].template
    browse.templates.discard(t)
    lib = Library(browse.conn)
    assert lib.live() == [] and browse.sel is None
    browse.set_view("discarded")
    assert ("tplrow", str(r["top"])) in browse.tree.keys()
    browse.select("tplrow", str(r["top"]), update_list=True)
    assert buttons(browse) == ["Bring back"] and "Discarded" in browse.page.toPlainText()
    assert Model(browse.conn).task(made[0]).title == "Trial 1"
    button(browse, "Bring back").click()
    assert Library(browse.conn).live() and browse.view == "templates" and browse.sel == ("tplrow", str(r["top"]))


def test_the_from_template_link_opens_the_row(browse):
    r = trial(browse)
    made = tree(browse, r)
    browse.go_task(made[1])
    assert "From template: Product trial › Trial execution window" in browse.task_pane.text()
    browse.on_link(QUrl(f"tplrow:{r['window']}"))
    assert browse.view == "templates" and browse.sel == ("tplrow", str(r["window"]))
    assert "1 task follows" in browse.page.toPlainText()


def test_double_click_edits_a_row(browse):
    r = trial(browse)
    browse.set_view("templates")
    opened = []
    browse.templates.edit_row = opened.append
    row = next(x for x in browse.tree.items() if x.data(0, KEY_ROLE) == ("tplrow", str(r["window"])))
    browse.double_click(row)
    assert opened == [r["window"]]


def test_save_as_template_from_a_task(browse):
    m = browse.model()
    task = next(t.id for t in m.tasks.values() if m.children_of(t.id) and not t.discarded)
    below = [x for x in m.descendants_of(task) if not m.task(x).discarded]
    browse.go_task(task)

    def fill(d: SaveAsDialog):
        assert d.name.text() == m.task(task).title and d.link.isChecked()
        d.name.setText("Installation pattern")
    answer(browse, fill)
    browse.templates.save_as(task)
    lib = Library(browse.conn)
    top = lib.live()[0].top
    assert lib.rows[top].title == "Installation pattern" and len(lib.walk(top)) == 1 + len(below)
    assert browse.view == "templates" and browse.sel == ("tplrow", str(top))
    assert "This tree now follows it." in browse.status.text()
    assert Model(browse.conn).origins[task].template == "Installation pattern"


def test_more_has_save_as_template(browse):
    browse.go_task("T000001")
    more = next(browse.actions_layout.itemAt(i).widget() for i in range(browse.actions_layout.count())
                if browse.actions_layout.itemAt(i).widget().accessibleName() == "More")
    assert "Save as template…" in [a.text() for a in more.menu().actions()]
    assert any(c.name == "Save as template" for c in browse.palette_commands())


def test_find_and_the_level_buttons_work_on_the_view(browse):
    r = trial(browse)
    browse.set_view("templates")
    browse.open_find()
    browse.find_box.setText("report")
    assert "1 match" in browse.find_count.text()
    browse.close_find()
    browse.render_list()
    assert browse._lvl_collapse.isEnabled()
    browse._tree_level(False)
    assert browse.shut["templates"]
    browse.render_list()
    item = next(x for x in browse.tree.items() if x.childCount())
    assert not item.isExpanded() and item.data(0, KEY_ROLE) == ("tplrow", str(r["top"]))
