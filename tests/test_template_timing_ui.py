"""The Timing window, the template's page, Make tasks with an anchor, a row's Tied to lines and Edit task's mark on a tie (release 5.51),
driven offscreen (no window appears) over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import tasks, template_pages, templates, timing  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Tie, load_tasks  # noqa: E402
from docrepo.templates import Library, RowTiming  # noqa: E402
from docrepo.timing import RowTie  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.page_view import picture  # noqa: E402
from docrepo.ui.task_forms import TaskEditDialog  # noqa: E402
from docrepo.ui.templates_view import MakeTasksDialog, PreviewDialog, RowDialog  # noqa: E402
from docrepo.ui.timing_view import TieLine, TimingDialog, source_options  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
MON_16, FRI_20, MON_23, FRI_27 = "2026-11-16", "2026-11-20", "2026-11-23", "2026-11-27"


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
    """A template with a group, an anchor, a row tied to it and a row tied to that row."""
    conn, settings = w.conn, w.ctx.settings
    top = templates.new_template(conn, "Product trial", NOW, {"leads": ["P001"]})

    def add(parent, title, **values):
        return templates.add_row(conn, settings, parent, {"title": title, "inherit_labels": True, **values}, NOW)[0]

    prep = add(top, "Trial preparation")
    change = add(prep, "Change record prep", duration=10)
    window = add(top, "Trial execution window", duration=5)
    report = add(top, "Trial report", duration=5)
    review = add(top, "Management review", duration=1)
    template = Library(conn).rows[top].template
    templates.apply_timing(conn, settings, template, window, {change: RowTiming({"start": RowTie(None, "start", 30)}, 10), window: RowTiming({}, 5),
                                                              report: RowTiming({"start": RowTie(None, "end", 1, direction="after")}, 5),
                                                              review: RowTiming({"start": RowTie(report, "end", 2, direction="after")}, 1)}, NOW)
    w.refresh()
    return {"top": top, "prep": prep, "change": change, "window": window, "report": report, "review": review, "id": template}


def tree(w, r, name="Trial 1", start=MON_16) -> dict[str, str]:
    made = templates.make_tasks(w.conn, w.ctx.settings, r["top"], name, None, {r["window"]: templates.Choice(start=start)}, NOW)
    w.refresh()
    lib = Library(w.conn)
    by_row = {lib.copies[x].row: x for x in made}
    return {k: by_row[v] for k, v in r.items() if k != "id" and v in by_row}


def get(w, task_id):
    return load_tasks(w.conn, [task_id])[task_id]


def buttons(w) -> list[str]:
    layout = w.actions_layout
    return [layout.itemAt(i).widget().text() for i in range(layout.count())]


def button(w, text):
    layout = w.actions_layout
    return next(layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget().text() == text)


def page_text(w) -> str:
    return w.page.toPlainText()


# ---- the view and its page ----
def test_the_template_page_shows_its_timing(browse):
    r = trial(browse)
    browse.templates.open_row(str(r["top"]))
    assert "Timing" in buttons(browse)
    text = page_text(browse)
    assert "In workdays around the anchor" in text and "Edit timing" in text
    assert "30 workdays before start" in text and "The anchor" in text and "2 workdays after Trial report ends" in text
    html = template_pages.row_page(Library(browse.conn), browse.model(), r["top"], NOW.date())
    assert f"tpltiming:{r['id']}" in html and html.count('src="timing:') == 7  # the ruler, and a lane for each of 6 rows


def test_a_narrow_pane_puts_each_lane_under_its_name(browse):
    r = trial(browse)
    lib, today = Library(browse.conn), NOW.date()
    wide, narrow = (template_pages.row_page(lib, browse.model(), r["top"], today, range(5), width) for width in (500, 300))
    assert f'width="{timing.LANE_WIDTH}">' in wide and narrow.count('src="timing:') == wide.count('src="timing:')
    assert wide.count("<tr>") < narrow.count("<tr>")


def test_a_page_with_no_anchor_says_how_to_start(browse):
    top = templates.new_template(browse.conn, "Audit", NOW)
    browse.refresh()
    browse.templates.open_row(str(top))
    assert "No anchor yet" in page_text(browse) and "Edit timing" in page_text(browse)


def test_a_row_page_says_what_it_is_tied_to(browse):
    r = trial(browse)
    browse.templates.open_row(str(r["report"]))
    assert "1 workday after the anchor ends" in page_text(browse)
    browse.templates.open_row(str(r["window"]))
    assert "its date is typed when you make tasks" in page_text(browse) and "Anchor" in page_text(browse)


def test_who_follows_says_a_tasks_own_gap(browse):
    r = trial(browse)
    t = tree(browse, r)
    tasks.update_task(browse.conn, browse.ctx.settings, t["report"], at=NOW, via="Browse tool", start="2026-11-25")
    browse.refresh()
    browse.templates.open_row(str(r["report"]))
    assert "own: start tie 3 workdays after Trial execution window ends" in page_text(browse)


def test_the_list_marks_the_anchor_and_says_what_rows_are_tied_to(browse):
    r = trial(browse)
    browse.set_view("templates")
    html = []

    def walk(item):
        for c in range(item.columnCount()):
            html.append(item.data(c, HTML_ROLE) or "")
        for i in range(item.childCount()):
            walk(item.child(i))
    for i in range(browse.tree.topLevelItemCount()):
        walk(browse.tree.topLevelItem(i))
    joined = " ".join(html)
    assert "Anchor" in joined and "30 workdays before start · 10 days" in joined and "2 workdays after Trial report ends · 1 day" in joined
    assert r  # the rows are made above


def test_the_page_draws_its_chart(qapp):
    scale = timing.scale_of({1: (-5, 5), 2: (0, 5)}, 5, 3)
    lane = timing.lane_address(scale, (-5, 5), "b")
    assert timing.parse_lane(lane.split(":", 1)[1])[1] == (-5, 5)
    assert not picture(QUrl(lane), 1.0).isNull() and not picture(QUrl(timing.lane_address(scale, None, "r")), 1.0).isNull()
    assert picture(QUrl("timing:nonsense"), 1.0) is None


def test_the_edit_timing_link_opens_the_window(browse):
    r = trial(browse)
    answer(browse, lambda d: False)
    browse.on_link(QUrl(f"tpltiming:{r['id']}"))
    assert isinstance(browse.shown[0], TimingDialog)


# ---- the Timing window ----
def timing_dialog(w, r) -> TimingDialog:
    return TimingDialog(w, Library(w.conn), r["id"], w._workdays())


def test_the_window_shows_each_row_as_it_stands(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    assert d.windowTitle() == "Timing: Product trial"
    assert d.rows[r["window"]].radio.isChecked() and not d.rows[r["top"]].line.placeable
    assert d.rows[r["report"]].start.amount.text() == "1" and d.rows[r["report"]].start.source.currentText() == "the anchor"
    assert d.rows[r["review"]].start.source.currentText() == "Trial report" and d.rows[r["review"]].start.point.currentData() == "end"
    assert not d.changed()
    d.mark_clean()


def test_the_chart_redraws_as_you_type(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    bar = d.rows[r["report"]].lane.bar
    d.rows[r["report"]].start.amount.setText("6")
    d.rows[r["report"]].start.amount.textEdited.emit("6")
    assert d.rows[r["report"]].lane.bar == (bar[0] + 5, bar[1])
    assert d.rows[r["review"]].lane.bar[0] == bar[0] + 5 + 4 + 2  # further down the chain: 2 workdays after the report's last day
    assert d.changed()
    d.mark_clean()


def test_the_sources_leave_out_what_would_make_a_circle(browse):
    r = trial(browse)
    lib = Library(browse.conn)
    options = source_options(lib.lines(r["id"]), r["window"], r["report"])
    assert options[0] == ("the anchor", None)
    assert [x[0] for x in options[1:]] == ["Change record prep"]  # not itself, the anchor, the group, or the review tied to it


def test_a_new_anchor_in_the_window_keeps_the_bars_and_says_so(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    before = {k: d.rows[k].lane.bar for k in (r["change"], r["window"], r["report"], r["review"])}
    d.group.button(r["report"]).click()
    assert d.anchor == r["report"] and d.note.text().startswith("The bars stayed where they were.")
    gap = before[r["report"]][0]
    assert {k: d.rows[k].lane.bar for k in before} == {k: (v[0] - gap, v[1]) for k, v in before.items()}
    assert d.rows[r["window"]].start.amount.text() == "5" and d.rows[r["window"]].start.direction.currentText() == "before"
    assert d.rows[r["review"]].start.source.currentText() == "the anchor"
    d.mark_clean()


def test_no_anchor_clears_the_ties_to_it(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    d.none_radio.click()
    assert d.anchor is None and d.rows[r["report"]].start.tie() is None and d.ruler.scale is None
    assert d.rows[r["review"]].start.tie().source == r["report"]
    d.mark_clean()


def test_both_dates_tied_grey_days(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    row = d.rows[r["report"]]
    assert row.add_due.isVisibleTo(d)
    row.add_due.click()
    row.due.amount.setText("3")
    row.due.amount.textEdited.emit("3")
    assert row.dash.isVisibleTo(d) and not row.days.isVisibleTo(d)
    assert d.result_rows()[r["report"]].days == 5  # the rule's kept in templates, which clears it
    d.mark_clean()


def test_saving_the_window_with_no_trees_needs_no_preview(browse):
    r = trial(browse)

    def fill(d):
        d.rows[r["report"]].start.amount.setText("2")
        d._read()
    answer(browse, fill)
    said = []
    browse.say = lambda text, error=False: said.append(text)
    browse.templates.timing(r["id"])
    assert len(browse.shown) == 1
    assert Library(browse.conn).rows[r["report"]].ties["start"].amount == 2
    assert said == ["Saved. No task's date changes."]


def test_saving_the_window_previews_what_moves_and_leaves_what_is_unticked(browse):
    r = trial(browse)
    t, other = tree(browse, r), tree(browse, r, "Trial 2", "2026-12-07")

    def fill(d):
        if isinstance(d, TimingDialog):
            d.rows[r["report"]].start.amount.setText("3")
            d._read()
            return True
        assert isinstance(d, PreviewDialog)
        assert d.windowTitle() == "This change reaches 4 tasks"
        assert "Trial 1 › Trial report" in [e.title for e in d.entries]
        d.ticks[other["report"]].setChecked(False)
        d.ticks[other["review"]].setChecked(False)
        assert d.commit_button.text() == "Apply to 2 tasks"
        return True
    answer(browse, fill)
    browse.templates.timing(r["id"])
    assert get(browse, t["report"]).start == "2026-11-25"
    held = get(browse, other["report"])
    assert held.start == "2026-12-14" and held.ties["start"].amount == 1
    log = Library(browse.conn).changes[r["id"]][0]
    assert log.text == "Timing around Trial execution window" and log.reached == 2 and log.left_out == 2


def test_back_from_the_preview_returns_to_the_window_as_typed(browse):
    r = trial(browse)
    tree(browse, r)
    seen = []

    def fill(d):
        seen.append(d)
        if isinstance(d, TimingDialog):
            d.rows[r["report"]].start.amount.setText("3")
            d._read()
            return len([x for x in seen if isinstance(x, TimingDialog)]) == 1
        return False  # Back
    answer(browse, fill)
    browse.templates.timing(r["id"])
    assert [type(x) for x in seen] == [TimingDialog, PreviewDialog, TimingDialog]
    assert Library(browse.conn).rows[r["report"]].ties["start"].amount == 1  # nothing was saved


def test_a_bad_days_says_which_row(browse):
    r = trial(browse)
    d = timing_dialog(browse, r)
    d.rows[r["report"]].days.setText("0")
    d._accept()
    assert "Trial report" in d.error.text() and not d.result()
    d.rows[r["report"]].days.setText("5")
    d.mark_clean()


# ---- a row's own form ----
def test_a_row_form_has_the_same_lines(browse):
    r = trial(browse)
    answer(browse, lambda d: False)
    browse.templates.edit_row(r["report"])
    d: RowDialog = browse.shown[0]
    assert d.tie_lines["start"].amount.text() == "1" and d.tie_lines["start"].source.currentText() == "the anchor"
    assert d.tie_lines["due"].tie() is None
    assert d.values()["ties"] == {"start": RowTie(None, "end", 1, "workdays", "after"), "due": None}


def test_the_anchors_form_says_it_is_the_anchor_and_ties_nothing(browse):
    r = trial(browse)
    answer(browse, lambda d: False)
    browse.templates.edit_row(r["window"])
    d: RowDialog = browse.shown[0]
    assert not d.tie_lines and "ties" not in d.values()


def test_a_group_and_a_top_row_have_no_lines(browse):
    r = trial(browse)
    answer(browse, lambda d: False)
    browse.templates.edit_row(r["prep"])
    browse.templates.edit_row(r["top"])
    assert all(d.timing_box is None for d in browse.shown)


def test_both_tied_in_a_row_form_greys_duration(browse):
    r = trial(browse)
    answer(browse, lambda d: False)
    browse.templates.edit_row(r["report"])
    d: RowDialog = browse.shown[0]
    d.tie_lines["due"].amount.setText("3")
    d.tie_lines["due"].amount.textEdited.emit("3")
    assert not d.duration.isEnabled() and d.duration.text() == ""


def test_a_row_form_can_open_the_timing_window(browse):
    r = trial(browse)
    seen = []

    def fill(d):
        seen.append(d)
        if isinstance(d, RowDialog):
            d._leave(("timing",))
        return False
    answer(browse, fill)
    browse.templates.edit_row(r["report"])
    assert [type(x) for x in seen] == [RowDialog, TimingDialog]


def test_a_tie_changed_in_a_row_form_lists_what_moves_with_it(browse):
    r = trial(browse)
    t = tree(browse, r)

    def fill(d):
        if isinstance(d, RowDialog):
            d.tie_lines["start"].amount.setText("3")
            return True
        assert isinstance(d, PreviewDialog) and d.windowTitle() == "This change reaches 2 tasks"
        assert set(d.ticks) == {t["report"], t["review"]}
        d.ticks[t["review"]].setChecked(False)
        return True
    answer(browse, fill)
    browse.templates.edit_row(r["report"])
    assert get(browse, t["report"]).ties["start"].amount == 3 and get(browse, t["report"]).start == "2026-11-25"
    assert get(browse, t["review"]).start == "2026-12-01"  # unticked, so it stayed


def test_a_new_subtask_says_it_arrives_tied(browse):
    r = trial(browse)
    t = tree(browse, r)

    def fill(d):
        if isinstance(d, RowDialog):
            d.title_box.setText("Lessons learned")
            d.duration.setText("2")
            d.tie_lines["start"].amount.setText("5")
            d.tie_lines["start"].point.setCurrentIndex(1)
            d.tie_lines["start"].direction.setCurrentText("after")
            d.tie_lines["start"].source.setCurrentIndex(d.tie_lines["start"].source.findText("Management review"))
            return True
        assert isinstance(d, PreviewDialog)
        return True
    answer(browse, fill)
    browse.templates.add_subtask(r["top"])
    made = [x for x in browse.model().tasks.values() if x.title == "Lessons learned"]
    assert len(made) == 1 and made[0].ties["start"].source == t["review"] and made[0].start == "2026-12-08"


# ---- Make tasks ----
def make_dialog(w, r, row=None) -> MakeTasksDialog:
    return MakeTasksDialog(w, w.model(), Library(w.conn), row or r["top"], w._people_options, lambda a, p: None, w._workdays(), lambda a, p: None, NOW.date())


def lines_of(d: MakeTasksDialog) -> dict[str, object]:
    return {x.row.title: x for x in d.lines}


def type_start(line, value) -> None:
    line.start.set_value(value)
    line.start.edited.emit()


def test_typing_the_anchors_start_fills_in_the_rest(browse):
    r = trial(browse)
    d = make_dialog(browse, r)
    lines = lines_of(d)
    a = lines["Trial execution window"]
    assert a.is_anchor and a.due_box and not lines["Trial report"].due_box
    type_start(a, MON_16)
    assert a.due_box.value() == FRI_20
    assert lines["Trial report"].start.value() == MON_23 and lines["Trial report"].start.line.property("worked") is True
    assert lines["Management review"].start.value() == "2026-12-01"
    assert "Fri 27 Nov" in lines["Trial report"].due.text()
    assert lines["Trial report"].says.text() == "1 workday after the anchor ends"
    assert "Change record prep" in d.early.text()  # 30 workdays before is before today, which warns and stops nothing
    d.mark_clean()


def test_typing_the_anchors_due_works_the_start_out(browse):
    r = trial(browse)
    d = make_dialog(browse, r)
    a = lines_of(d)["Trial execution window"]
    a.due_box.set_value(FRI_20)
    a.due_box.edited.emit()
    assert a.start.value() == MON_16 and lines_of(d)["Trial report"].start.value() == MON_23
    assert a.choice().start == MON_16 and a.choice().due is None
    d.mark_clean()


def test_new_days_on_an_anchor_with_only_a_due_count_back_from_it(browse):
    r = trial(browse)
    d = make_dialog(browse, r)
    a = lines_of(d)["Trial execution window"]
    a.days.clear()
    a.days.textEdited.emit("")
    a.due_box.set_value(FRI_20)
    a.due_box.edited.emit()
    assert not a.start.value() and a.choice().due == FRI_20  # with no length, it's a plain date
    a.days.setText("5")
    a.days.textEdited.emit("5")
    assert a.start.value() == MON_16 and a.choice().start == MON_16
    d.mark_clean()


def test_clearing_the_anchors_start_clears_its_due_too(browse):
    r = trial(browse)
    d = make_dialog(browse, r)
    lines = lines_of(d)
    a = lines["Trial execution window"]
    type_start(a, MON_16)
    type_start(a, None)
    assert not a.due_box.value() and not lines["Trial report"].start.value()
    d.mark_clean()


def test_a_discarded_templates_page_offers_no_timing(browse):
    r = trial(browse)
    templates.set_discarded(browse.conn, r["id"], "Made by mistake", NOW)
    html = template_pages.row_page(Library(browse.conn), browse.model(), r["top"], NOW.date())
    assert "tpltiming:" not in html


def test_typing_over_a_worked_out_date_shows_back_and_counts(browse):
    r = trial(browse)
    d = make_dialog(browse, r)
    lines = lines_of(d)
    type_start(lines["Trial execution window"], MON_16)
    report = lines["Trial report"]
    assert report.back.isHidden()
    type_start(report, "2026-11-25")
    assert report.over == "2026-11-25" and not report.back.isHidden()
    assert lines["Management review"].start.value() == "2026-12-03"
    assert d.choices()[r["report"]].start == "2026-11-25"
    report.back.click()
    assert report.over is None and report.start.value() == MON_23 and report.back.isHidden()
    assert d.choices()[r["report"]].start is None
    d.mark_clean()


def test_the_anchor_tied_to_another_task_takes_its_date_from_it(browse):
    r = trial(browse)
    conn, settings = browse.conn, browse.ctx.settings
    outage = tasks.create_task(conn, settings, title="Line 2 outage", at=NOW, created_by="Browse tool", start="2026-11-09", due="2026-11-11")
    browse.refresh()
    d = make_dialog(browse, r)
    a = lines_of(d)["Trial execution window"]
    d.tie_panel.open("start")
    d.tie_panel._picked(outage)
    d.tie_panel.amount.setValue(3)
    d.tie_panel.point.setCurrentIndex(1)
    d.tie_panel.direction.setCurrentText("after")
    d.tie_panel.close_editor()
    assert a.start.value() == MON_16 and not a.start.isEnabled() and lines_of(d)["Trial report"].start.value() == MON_23
    choice = d.choices()[r["window"]]
    assert choice.tie == Tie(outage, "end", 3, "workdays", "after") and choice.start is None
    d.mark_clean()


def test_making_from_the_dialog_gives_a_tree_with_its_ties(browse):
    r = trial(browse)

    def fill(d):
        d.name.setText("Trial 9")
        type_start(lines_of(d)["Trial execution window"], MON_16)
        return True
    answer(browse, fill)
    said = []
    browse.say = lambda text, error=False: said.append(text)
    browse.templates.make(r["top"])
    m = browse.model()
    report = next(t for t in m.tasks.values() if t.title == "Trial report")
    assert (report.start, report.due) == (MON_23, FRI_27) and report.ties
    assert "placed by their ties" in said[0]


def test_make_tasks_from_a_row_without_the_anchor_has_no_anchor(browse):
    r = trial(browse)
    d = make_dialog(browse, r, r["report"])
    line = d.lines[0]
    assert not line.is_anchor and not line.tied and d.tie_panel is None and line.has_start
    d.mark_clean()


def test_a_template_with_no_timing_shows_make_tasks_as_before(browse):
    top = templates.new_template(browse.conn, "Audit", NOW)
    templates.add_row(browse.conn, browse.ctx.settings, top, {"title": "Walk the equipment", "inherit_labels": True, "duration": 1}, NOW)
    browse.refresh()
    d = MakeTasksDialog(browse, browse.model(), Library(browse.conn), top, browse._people_options, lambda a, p: None, browse._workdays())
    assert d.tie_panel is None and not any(x.due_box or x.tied for x in d.lines)
    d.lines[1].start.set_value(MON_16)
    d.lines[1].start.edited.emit()
    assert "Mon 16 Nov" in d.lines[1].due.text()  # 1 day, so it ends the day it starts
    d.mark_clean()


# ---- Edit task's mark on a tie ----
def edit_dialog(w, task_id) -> TaskEditDialog:
    return TaskEditDialog(w, w.model(), task_id, w._label_options, w._people_options, lambda a, p: None, today=NOW.date(), link=w.templates.link_of(task_id), workdays=w._workdays())


def test_a_tie_following_its_row_has_a_quiet_mark(browse):
    r = trial(browse)
    t = tree(browse, r)
    d = edit_dialog(browse, t["report"])
    assert d.tie_panel.marks["start"].text() == "" and not d.tie_panel.marks["start"].isHidden()
    assert "start_tie" in d.values()["follow"]
    d.mark_clean()


def test_a_task_with_its_own_gap_offers_the_templates_back(browse):
    r = trial(browse)
    t = tree(browse, r)
    tasks.update_task(browse.conn, browse.ctx.settings, t["report"], at=NOW, via="Browse tool", start="2026-11-25")
    browse.refresh()
    d = edit_dialog(browse, t["report"])
    mark = d.tie_panel.marks["start"]
    assert mark.text() == "Template: 1 workday after the anchor ends ↺" and "start_tie" not in d.values()["follow"]
    mark.click()
    assert d.tie_panel.ties["start"].amount == 1 and d.start.value() == MON_23 and "start_tie" in d.values()["follow"]
    d.mark_clean()


def test_typing_a_new_date_says_it_will_stop_following(browse):
    r = trial(browse)
    t = tree(browse, r)
    d = edit_dialog(browse, t["report"])
    d.start.set_value("2026-11-25")
    d.start.edited.emit()
    assert not d.tie_panel.leaving.isHidden() and "start_tie" not in d.values()["follow"]
    assert d.tie_panel.marks["start"].text().startswith("Template:")
    d.mark_clean()


def test_saving_a_form_with_its_own_gap_ends_following(browse):
    r = trial(browse)
    t = tree(browse, r)

    def fill(d):
        d.start.set_value("2026-11-25")
        d.start.edited.emit()
        return True
    answer(browse, fill)
    browse.edit_task(t["report"])
    links = {x["field"] for x in browse.conn.execute("SELECT field FROM task_links WHERE task = ?", (t["report"],))}
    assert "start_tie" not in links and get(browse, t["report"]).ties["start"].amount == 3


def test_a_task_with_no_template_has_no_marks(browse):
    conn = browse.conn
    x = tasks.create_task(conn, browse.ctx.settings, title="Plain", at=NOW, created_by="Browse tool", start=MON_16, due=FRI_20)
    browse.refresh()
    d = edit_dialog(browse, x)
    assert all(m.isHidden() for m in d.tie_panel.marks.values())
    d.mark_clean()


def test_a_tie_line_reads_back_what_it_was_given(qapp):
    line = TieLine("due", "Trial report")
    line.set_options([("the anchor", None), ("Trial report", 7)])
    assert line.tie() is None
    tie = RowTie(7, "end", 2, "weeks", "after")
    line.set_tie(tie)
    assert line.tie() == tie
    line.set_tie(None)
    assert line.tie() is None
