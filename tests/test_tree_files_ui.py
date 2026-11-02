"""The Import window, Copy prompt, Export and the edit review (releases 5.53 to 5.56), driven offscreen (no window appears) over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import html  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import tasks, templates, tree_files as tf  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model, load_tasks  # noqa: E402
from docrepo.templates import Choice, Library  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.settings_view import SettingsProblem, check_values  # noqa: E402
from docrepo.ui.tree_import import EditReviewDialog, TextWindow, TreeImportDialog  # noqa: E402

NOW = datetime(2026, 11, 1, 9, 15)
TALK = {
    "format": tf.TREE_FORMAT, "anchor": "prep",
    "rows": [
        {"key": "top", "title": "Coating qualification"},
        {"key": "change", "parent": "top", "title": "Change record", "quote": "the change record"},
        {"key": "prep", "parent": "change", "title": "Prepare change record", "duration": 10, "assignees": ["Priya Shah"], "assignee_hours": 30, "quote": "about thirty hours", "assumed": ["'two weeks' read as 10 workdays"]},
        {"key": "ok", "parent": "change", "title": "Approval: change record", "assignees": ["Tom Baker"], "start_tie": {"source": "prep", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}, "quote": "Tom Baker signs it"},
        {"key": "notice", "parent": "top", "title": "Tell the supplier", "start_tie": {"source": "change", "point": "end", "amount": 2, "unit": "workdays", "direction": "after"}, "quote": "two days after"},
        {"key": "window", "parent": "top", "title": "Trial window", "labels": ["Coatings"], "notes": "- [ ] Book the lab", "duration": 5, "plant_event": True, "start_tie": {"source": "ok", "point": "end", "amount": 5, "unit": "workdays", "direction": "after"}, "quote": "five days after"},
    ],
    "unplaced": ["Ask: who approves if Tom is away?"],
}
BAD = {"format": tf.TREE_FORMAT, "priority": "high", "rows": [{"key": "a", "title": "A"}, {"key": "b", "title": "B"}]}


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


def answer(w, *steps):
    """Say what the next windows do: each step fills one in, and it's accepted unless the step says False."""
    todo = list(steps)

    def run(dialog):
        w.shown.append(dialog)
        said = todo.pop(0)(dialog)
        return said is not False
    w.run_dialog = run


def importing(w, fill):
    dialog = TreeImportDialog(w, w.ctx)
    fill(dialog)
    return dialog


def test_the_window_starts_with_the_steps_and_import_off(browse):
    d = importing(browse, lambda _: None)
    assert not d.commit_button.isEnabled() and not d.questions_button.isVisible()
    assert d.content.itemAt(0).widget().text().startswith("<ol")


def test_enter_goes_to_import_not_the_toolbar(browse):
    d = importing(browse, lambda _: None)
    assert d.commit_button.isDefault()
    assert not any(b.autoDefault() for b in (d.prompt_button, d.paste_button, d.questions_button))


def test_a_good_file_is_reviewed(browse):
    d = importing(browse, lambda x: x.load(json.dumps(TALK), "talk.json"))
    assert d.commit_button.isEnabled()
    assert [d.tree.topLevelItem(0).text(0), d.tree.topLevelItem(0).child(0).text(0), d.tree.topLevelItem(0).child(0).child(0).text(1)] == ["Coating qualification", "Change record", "10 days · 30 h"]
    assert set(d.name_boxes) == {"Tom Baker"} and set(d.label_boxes) == {"Coatings"} and set(d.tie_boxes) == {("notice", "start_tie")}
    assert d.name_boxes["Tom Baker"].currentData() == "" and d.label_boxes["Coatings"].currentData() == ""
    assert d.name_boxes["Tom Baker"].itemText(1) == "Tom Becker (close match)"


def test_clicking_a_row_shows_what_it_holds_and_its_evidence(browse):
    d = importing(browse, lambda x: x.load(json.dumps(TALK), "talk.json"))
    d.select_row("prep")
    words = d.detail.toPlainText()
    for said in ("Prepare change record", "10 days", "Priya Shah", "30 h", "about thirty hours", "'two weeks' read as 10 workdays", "The anchor: typed at Make tasks"):
        assert said in words, said
    d.select_row("window")
    assert "Plant event" in d.detail.toPlainText() and "☐ Book the lab" in d.detail.toPlainText()


def test_a_warning_links_to_its_row(browse):
    d = importing(browse, lambda x: x.load(json.dumps(TALK), "talk.json"))
    d.select_row("ok")
    assert d.shown_key == "ok" and d.tree.currentItem().text(0) == "Approval: change record"


def test_the_settled_tie_shows_in_the_row(browse):
    d = importing(browse, lambda x: x.load(json.dumps(TALK), "talk.json"))
    d.select_row("notice")
    assert "2 workdays after Approval: change record ends" in d.detail.toPlainText()
    box = d.tie_boxes[("notice", "start_tie")]
    box.setCurrentIndex(box.count() - 1)
    assert "Left untied: 2 workdays after Change record ends" in d.detail.toPlainText()


def test_a_file_with_problems_cant_be_imported(browse):
    d = importing(browse, lambda x: x.load(json.dumps(BAD), "bad.json"))
    assert not d.commit_button.isEnabled() and d.tree is None
    assert "problems to fix first" in d.content.itemAt(0).widget().text()
    assert "priority" in d.content.itemAt(1).widget().text()
    d.save()
    assert not d.result()


@pytest.mark.parametrize(("text", "said"), [("", "nothing here"), (json.dumps(TALK)[:200], "cut off"), ('{"format": "other"}', 'format is "other"'), ('{"rows": []}', 'no "format"')])
def test_what_cant_be_read_says_why(browse, text, said):
    d = importing(browse, lambda x: x.load(text, "x"))
    assert said in html.unescape(d.content.itemAt(0).widget().text()) and not d.commit_button.isEnabled()


def test_a_paste_with_words_around_it_says_so(browse):
    d = importing(browse, lambda x: x.load(f"Here you go:\n```json\n{json.dumps(TALK)}\n```\nDone.", "a paste"))
    assert d.commit_button.isEnabled()
    assert "words around the JSON" in d.content.itemAt(1).widget().text()


def test_copy_questions(browse, qapp):
    d = importing(browse, lambda x: x.load(json.dumps(TALK), "talk.json"))
    assert not d.questions_button.isHidden()
    d._copy_questions()
    assert "who approves if Tom is away" in QGuiApplication.clipboard().text()


def test_copy_prompt_shows_the_text_and_copies_it(browse):
    d = importing(browse, lambda _: None)
    seen = []
    d.run_prompt = seen.append
    d.show_prompt()
    window: TextWindow = seen[0]
    assert "Never estimate hours" in window.box.toPlainText() and "- Priya Shah" in window.box.toPlainText()
    assert (browse.ctx.data_root / tf.TREE_RULES_FILE).exists()
    window.copies[0].click()
    assert QGuiApplication.clipboard().text() == window.box.toPlainText() and "Copied the prompt" in window.said.text()


def test_the_prompt_uses_the_owners_rules(browse):
    (browse.ctx.data_root / tf.TREE_RULES_FILE).write_text("My own rules.\n", encoding="utf-8")
    d = importing(browse, lambda _: None)
    seen = []
    d.run_prompt = seen.append
    d.show_prompt()
    assert seen[0].box.toPlainText().startswith("My own rules.")


def test_import_makes_the_template_opens_it_and_keeps_a_copy(browse):
    before = len(browse.model().tasks)

    def fill(d):
        d.load(json.dumps(TALK), "talk.json")
        d.name_boxes["Tom Baker"].setCurrentIndex(1)
    answer(browse, fill)
    browse.tree_files.import_tree()
    lib = Library(browse.conn)
    t = lib.live()[0]
    assert lib.name(t.id) == "Coating qualification" and len(browse.model().tasks) == before
    assert browse.view == "templates" and browse.sel == ("tplrow", str(t.top))
    row = next(x for x, _ in lib.walk(t.top) if x.title == "Approval: change record")
    assert browse.model().person_name(row.assignees[0]) == "Tom Becker"
    assert len(list((browse.ctx.data_root / "Imports").iterdir())) == 1
    assert "Imported Coating qualification, with 6 rows" in browse.status.text()


def test_import_that_cant_stand_stays_in_the_window_saying_why(browse):
    """Two ties settled into a circle: nothing's made, and the window's still there to change them."""
    data = {"format": tf.TREE_FORMAT, "rows": [
        {"key": "top", "title": "Top"}, {"key": "p1", "parent": "top", "title": "P1", "quote": "q"}, {"key": "p2", "parent": "top", "title": "P2", "quote": "q"},
        {"key": "a", "parent": "p1", "title": "A", "quote": "q", "start_tie": {"source": "p2", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}},
        {"key": "b", "parent": "p2", "title": "B", "quote": "q", "start_tie": {"source": "p1", "point": "end", "amount": 0, "unit": "workdays", "direction": "after"}}]}
    seen = []

    def first(d):
        d.load(json.dumps(data), "circle.json")

    def second(d):
        seen.append(d.error.text())
        return False
    answer(browse, first, second)
    browse.tree_files.import_tree()
    assert "circle" in seen[0] and Library(browse.conn).live() == []


def test_the_templates_view_has_import_and_a_template_has_export(browse):
    top = templates.new_template(browse.conn, "Product trial", NOW)
    browse.set_view("templates")
    assert "Import…" in [b.text() for b in browse.findChildren(QPushButton)]
    browse.templates.open_row(str(top))
    assert "Export" in [b.text() for b in browse.findChildren(QPushButton) if b.isVisibleTo(browse)]


def test_export_of_a_template_saves_copies_and_shows_it(browse):
    top = templates.new_template(browse.conn, "Product trial", NOW)
    template = Library(browse.conn).rows[top].template
    answer(browse, lambda d: None)
    browse.tree_files.export_template(template)
    d: TextWindow = browse.shown[0]
    assert json.loads(d.box.toPlainText())["of"] == f"template {template}"
    assert QGuiApplication.clipboard().text() == d.box.toPlainText()
    assert "Exports\\2026-11-01 0915 Product trial.json" in d.note.text()
    assert (browse.ctx.data_root / "Exports" / "2026-11-01 0915 Product trial.json").exists()
    d.copies[1].click()
    assert "The tree as it stands" in QGuiApplication.clipboard().text() and "Keep every" in QGuiApplication.clipboard().text()


def test_a_task_has_export_tree_and_bring_back_in_its_more_menu(browse):
    browse.set_view("tasks")
    browse.go_task("T000001")
    more = next(b for b in browse.findChildren(QPushButton) if b.accessibleName() == "More" and b.menu() is not None)
    words = [a.text() for a in more.menu().actions()]
    assert "Export tree…" in words and "Bring back an edit file…" in words


# ---- the edit review ----
def built(w) -> dict:
    conn, settings = w.conn, w.ctx.settings
    top = templates.new_template(conn, "Product trial", NOW)
    add = lambda parent, **v: templates.add_row(conn, settings, parent, {"title": "T", "inherit_labels": True, **v}, NOW)[0]  # noqa: E731
    window = add(top, title="Window", duration=5, assignees=["P002"], assignee_hours=30)
    prep = add(top, title="Preparation")
    return {"top": top, "window": window, "prep": prep, "template": Library(conn).rows[top].template}


def review(w, data) -> EditReviewDialog:
    answer(w, lambda d: d.load(json.dumps(data), "edit.json"), lambda d: False)
    w.tree_files.import_tree()
    return w.shown[1]


def test_an_edit_file_goes_to_the_review(browse):
    r = built(browse)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": r["window"], "duration": 3, "quote": "three days now"}]})
    assert isinstance(d, EditReviewDialog) and d.ticks[0].isChecked()
    assert d.commit_button.text() == "Apply 1 change" and d.commit_button.isEnabled()
    assert Library(browse.conn).rows[r["window"]].duration == 5


def test_a_change_with_no_quote_starts_unticked(browse):
    r = built(browse)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": r["window"], "description": "Reworded"}]})
    assert not d.ticks[0].isChecked() and not d.commit_button.isEnabled()
    d.ticks[0].setChecked(True)
    assert d.commit_button.isEnabled() and d.plan.changes[0].ticked


def test_a_file_with_problems_cant_be_applied(browse):
    r = built(browse)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": 99999, "duration": 3}]})
    assert not d.commit_button.isEnabled() and d.ticks == {}


def test_nothing_to_change_says_so(browse):
    r = built(browse)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": r["window"], "duration": 5, "quote": "q"}]})
    assert not d.commit_button.isEnabled() and d.plan.changes == [] and "1 row the same" in d.plan.counts() or d.plan.unchanged


def test_what_a_change_reaches_folds_out_with_ticks(browse):
    r = built(browse)
    templates.make_tasks(browse.conn, browse.ctx.settings, r["top"], "Trial 1", None, {}, NOW)
    first = templates.make_tasks(browse.conn, browse.ctx.settings, r["top"], "Trial 2", None, {}, NOW)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": r["window"], "assignee_hours": 10, "quote": "ten hours"}]})
    assert d._reach_labels[0].text().startswith("Reaches 2 tasks. Work across them")
    keys = list(d.subs[0])
    assert len(keys) == 2
    d.subs[0][keys[0]].setChecked(False)
    assert d._reach_labels[0].text().startswith("Reaches 1 task.")
    assert keys[0] in d.plan.changes[0].off
    assert first


def test_applying_a_template_edit_opens_the_template(browse):
    r = built(browse)
    data = {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"id": r["window"], "duration": 3, "quote": "q"}, {"key": "n", "parent": r["prep"], "title": "New one", "quote": "q"}]}
    answer(browse, lambda d: d.load(json.dumps(data), "edit.json"), lambda d: None)
    browse.tree_files.import_tree()
    lib = Library(browse.conn)
    assert lib.rows[r["window"]].duration == 3 and "New one" in [x.title for x, _ in lib.walk(r["top"])]
    assert browse.sel == ("tplrow", str(r["top"])) and "Applied 2 changes" in browse.status.text()


def tree_of(w) -> tuple[dict, dict, str]:
    r = built(w)
    made = templates.make_tasks(w.conn, w.ctx.settings, r["top"], "Trial 1", None, {r["window"]: Choice(start="2027-03-01")}, NOW)
    m = Model(w.conn)
    return r, {m.task(x).title: x for x in made}, made[0]


def test_a_task_edit_says_a_link_ends_and_applies(browse):
    _, ids, top = tree_of(browse)
    data = {"format": tf.EDIT_FORMAT, "of": f"task {top}", "rows": [{"id": ids["Window"], "assignee_hours": 12, "quote": "twelve hours"}]}
    answer(browse, lambda d: d.load(json.dumps(data), "edit.json"), lambda d: None)
    browse.tree_files.import_tree()
    d = browse.shown[1]
    assert d.plan.changes[0].linked
    assert load_tasks(browse.conn, [ids["Window"]])[ids["Window"]].assignee_hours == 12
    assert browse.sel == ("task", top) and "Applied 1 change" in browse.status.text()


def test_what_moves_leaves_out_a_task_this_file_closes(browse):
    r, ids, top = tree_of(browse)
    templates.apply_row(browse.conn, browse.ctx.settings, r["prep"], {**tf._row_form(Library(browse.conn).rows[r["prep"]]), "ties": {"start": templates.timing.RowTie(r["window"], "end", 1, "workdays", "after")}}, NOW)
    data = {"format": tf.EDIT_FORMAT, "of": f"task {top}", "rows": [{"id": ids["Window"], "start": "2027-03-08", "quote": "a week later"}, {"id": ids["Preparation"], "state": "Closed", "quote": "it's done"}]}
    d = review(browse, data)
    start = next(i for i, c in enumerate(d.plan.changes) if c.field_name == "start")
    state = next(i for i, c in enumerate(d.plan.changes) if c.field_name == "state")
    assert d._moves[start].isHidden()
    d.ticks[state].setChecked(False)
    assert "Moves 1 tied task with it" in d._moves[start].text()


def test_a_blocked_discard_cant_be_ticked(browse):
    r, ids, top = tree_of(browse)
    kid = tasks.create_task(browse.conn, browse.ctx.settings, title="A subtask", at=NOW, created_by="Test", parents=[ids["Preparation"]])
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"task {top}", "rows": [{"id": ids["Preparation"], "remove": True, "quote": "drop it"}]})
    assert not d.ticks[0].isEnabled() and not d.ticks[0].isChecked() and not d.commit_button.isEnabled()
    assert kid


def test_a_new_row_under_an_unticked_one_says_so(browse):
    r = built(browse)
    d = review(browse, {"format": tf.EDIT_FORMAT, "of": f"template {r['template']}", "rows": [{"key": "a", "parent": r["prep"], "title": "A", "quote": "q"}, {"key": "b", "parent": "a", "title": "B", "quote": "q"}]})
    d.ticks[0].setChecked(False)
    assert "A, a new row that's unticked" in d.error.text() and not d.commit_button.isEnabled()
    d.ticks[1].setChecked(False)
    assert not d.error.text()


# ---- Copilot's folder ----
def test_the_window_offers_whats_waiting_and_not_whats_imported(browse, tmp_path):
    folder = tmp_path / "Copilot"
    folder.mkdir()
    (folder / "talk.json").write_text(json.dumps(TALK), encoding="utf-8")
    browse.ctx.settings.copilot_folder = str(folder)
    d = importing(browse, lambda _: None)
    assert d.waiting_box.count() == 1
    d.load_file(folder / "talk.json")
    assert d.commit_button.isEnabled() and d.name == "talk.json"

    def fill(x):
        x.load_file(folder / "talk.json")
    answer(browse, fill)
    browse.tree_files.import_tree()
    assert importing(browse, lambda _: None).waiting_box.count() == 0


def test_a_file_that_cant_be_read_says_so(browse, tmp_path):
    d = importing(browse, lambda _: None)
    d.load_file(tmp_path / "gone.json")
    assert "couldn't be read" in d.error.text()


def test_the_folder_cant_be_in_the_data_root(browse, tmp_path):
    base = {**browse.ctx.settings.__dict__}
    with pytest.raises(SettingsProblem, match="inside the data root"):
        check_values(browse.ctx, {**base, "copilot_folder": str(browse.ctx.data_root / "Copilot")})
    with pytest.raises(SettingsProblem, match="full path"):
        check_values(browse.ctx, {**base, "copilot_folder": "Copilot"})
    assert check_values(browse.ctx, {**base, "copilot_folder": str(tmp_path / "Copilot")})["copilot_folder"] == str(tmp_path / "Copilot")
    assert check_values(browse.ctx, {**base, "copilot_folder": "  "})["copilot_folder"] is None
