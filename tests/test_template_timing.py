"""A template's timing (release 5.51; the task templates design, decisions 248 and 255 to 258): the anchor, ties on rows, Make tasks, and
what a change to them reaches. The sums, the rules, and the owner's own example: build a template with links, make a tree, change the
anchor's date, and the linked tasks move."""
from __future__ import annotations

from datetime import datetime

import pytest

from docrepo import db, tasks, templates, timing
from docrepo.config import Settings
from docrepo.model import Model, Tie, load_tasks
from docrepo.stories import Stories
from docrepo.tasks import TaskError
from docrepo.templates import Choice, Library, RowTiming
from docrepo.timing import Line, RowTie, Typed

AT = datetime(2026, 10, 8, 9, 30)
LATER = datetime(2026, 10, 9, 11, 0)
TODAY = AT.date()
SETTINGS = Settings(me="P001")
WEEK = range(5)
MON_16, FRI_20, MON_23, FRI_27, TUE_DEC_1 = "2026-11-16", "2026-11-20", "2026-11-23", "2026-11-27", "2026-12-01"


def start_tie(amount, direction="before", point="start", source=None, unit="workdays") -> RowTie:
    return RowTie(source, point, amount, unit, direction)


def row(title: str, **values) -> dict:
    return {"title": title, "inherit_labels": True, **values}


def add(conn, parent: int, values: dict) -> int:
    return templates.add_row(conn, SETTINGS, parent, values, AT)[0]


@pytest.fixture
def trial(sample_conn):
    """The mock's Product trial: a top row and a group that span their subtasks, an anchor, and rows tied to it or to another row."""
    conn = sample_conn
    top = templates.new_template(conn, "Product trial", AT)
    prep = add(conn, top, row("Trial preparation"))
    change = add(conn, prep, row("Change record prep", duration=10))
    supplier = add(conn, prep, row("Supplier follow-up", duration=30))
    training = add(conn, prep, row("Operations training", duration=3))
    window = add(conn, top, row("Trial execution window", duration=5))
    report = add(conn, top, row("Trial report", duration=5))
    review = add(conn, top, row("Management review", duration=1))
    r = {"top": top, "prep": prep, "change": change, "supplier": supplier, "training": training, "window": window, "report": report, "review": review}
    plan = {change: RowTiming({"start": start_tie(30)}, 10), supplier: RowTiming({"start": start_tie(6, unit="weeks")}, 30),
            training: RowTiming({"due": start_tie(1)}, 3), window: RowTiming({}, 5), report: RowTiming({"start": start_tie(1, "after", "end")}, 5),
            review: RowTiming({"start": start_tie(2, "after", "end", report)}, 1)}
    r["id"] = Library(conn).rows[top].template
    templates.apply_timing(conn, SETTINGS, r["id"], window, plan, AT)
    return conn, r


def make_tree(conn, r, name="Trial 1", start=MON_16, **choice) -> dict[str, str]:
    """A tree, with its anchor's Start typed. Returns each row's task, by the fixture's names."""
    choices = {r["window"]: Choice(start=start, **choice)}
    made = templates.make_tasks(conn, SETTINGS, r["top"], name, None, choices, AT)
    lib = Library(conn)
    by_row = {lib.copies[x].row: x for x in made}
    return {k: by_row[v] for k, v in r.items() if k != "id" and v in by_row}


def get(conn, task_id):
    return load_tasks(conn, [task_id])[task_id]


def dates(conn, task_id):
    t = get(conn, task_id)
    return t.start, t.due


def links_of(conn, task_id) -> set[str]:
    return {x["field"] for x in conn.execute("SELECT field FROM task_links WHERE task = ?", (task_id,))}


def lines_of(conn, task_id) -> list[str]:
    m = Model(conn)
    stories = Stories(m, TODAY, lambda _: "")
    return [stories.field_sentence(e) for e in m.status_log_of(task_id)]


def edit(conn, task_id, **values):
    return tasks.update_task(conn, SETTINGS, task_id, at=LATER, via="Browse tool", **values)


def timing_of(conn, r) -> tuple[int | None, dict[int, RowTiming]]:
    """The template's timing as the window would give it back, unchanged."""
    lib = Library(conn)
    return lib.templates[r["id"]].anchor, {x.id: RowTiming(dict(x.ties), x.days) for x in lib.lines(r["id"]) if x.placeable}


# ---- the owner's example ----
def test_make_tasks_places_every_row_from_the_anchor(trial):
    conn, r = trial
    t = make_tree(conn, r)
    assert dates(conn, t["window"]) == (MON_16, FRI_20)
    assert dates(conn, t["change"]) == ("2026-10-05", "2026-10-16")  # 30 workdays before, for 10 days
    assert dates(conn, t["supplier"]) == ("2026-10-05", "2026-11-13")  # 6 weeks before, the same weekday, for 30 days
    assert dates(conn, t["training"]) == ("2026-11-11", "2026-11-13")  # its Due is the workday before, and it's 3 days
    assert dates(conn, t["report"]) == (MON_23, FRI_27)
    assert dates(conn, t["review"]) == (TUE_DEC_1, TUE_DEC_1)  # 2 workdays after the report ends, which is tied to the anchor


def test_changing_the_anchors_due_moves_the_linked_tasks_in_that_tree_only(trial):
    conn, r = trial
    t, other = make_tree(conn, r), make_tree(conn, r, "Trial 2", "2026-12-07")
    held = dates(conn, other["report"])
    logged = edit(conn, t["window"], due="2026-11-27")  # a week later: with a Duration, the block moves
    assert dates(conn, t["window"]) == (MON_23, "2026-11-27")
    assert dates(conn, t["report"]) == ("2026-11-30", "2026-12-04")
    assert dates(conn, t["review"]) == ("2026-12-08", "2026-12-08")  # further down the chain
    assert dates(conn, t["change"]) == ("2026-10-12", "2026-10-23")
    assert dates(conn, other["report"]) == held
    assert {f.task for f in logged.followed} == {t[k] for k in ("change", "supplier", "training", "report", "review")}
    assert tasks.moved_words(logged) == "Moved 5 tasks with it."


def test_ties_arrive_following_their_rows(trial):
    conn, r = trial
    t = make_tree(conn, r)
    assert get(conn, t["report"]).ties["start"] == Tie(t["window"], "end", 1, "workdays", "after")
    assert get(conn, t["review"]).ties["start"] == Tie(t["report"], "end", 2, "workdays", "after")
    assert get(conn, t["training"]).ties["due"] == Tie(t["window"], "start", 1, "workdays", "before")
    assert {"start_tie", "duration"} <= links_of(conn, t["report"])
    assert "due_tie" in links_of(conn, t["training"]) and "start_tie" not in links_of(conn, t["training"])
    assert "start_tie" not in links_of(conn, t["window"]) and not get(conn, t["window"]).ties
    assert get(conn, t["top"]).start is None and get(conn, t["prep"]).start is None  # those that span their subtasks stay undated


def test_a_tree_left_blank_waits_and_lands_when_the_anchor_gets_a_date(trial):
    conn, r = trial
    t = make_tree(conn, r, start=None)
    assert all(dates(conn, t[k]) == (None, None) for k in ("window", "report", "review", "change"))
    assert get(conn, t["report"]).ties and get(conn, t["report"]).duration == 5
    edit(conn, t["window"], start=MON_16)
    assert dates(conn, t["report"]) == (MON_23, FRI_27) and dates(conn, t["review"]) == (TUE_DEC_1, TUE_DEC_1)
    assert "start_tie" in links_of(conn, t["report"])  # moved by its tie, so its gap still follows the template


def test_the_anchors_due_can_be_what_is_typed(trial):
    conn, r = trial
    t = make_tree(conn, r, start=None, due=FRI_20)
    assert dates(conn, t["window"]) == (MON_16, FRI_20) and dates(conn, t["report"]) == (MON_23, FRI_27)


def test_the_anchor_can_be_tied_to_another_task(trial, sample_conn):
    conn, r = trial
    outage = tasks.create_task(conn, SETTINGS, title="Line 2 outage", at=AT, created_by="Browse tool", start="2026-11-09", due="2026-11-11")
    t = make_tree(conn, r, start=None, tie=Tie(outage, "end", 3, "workdays", "after"))
    assert dates(conn, t["window"]) == (MON_16, FRI_20)
    assert "start_tie" not in links_of(conn, t["window"])  # it's the task's own
    edit(conn, outage, start="2026-11-16", due="2026-11-18")
    assert dates(conn, t["window"]) == (MON_23, "2026-11-27") and dates(conn, t["report"]) == ("2026-11-30", "2026-12-04")


def test_a_date_typed_over_one_worked_out_keeps_its_tie_with_a_new_gap(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["top"], "Trial 1", None, {r["window"]: Choice(start=MON_16), r["report"]: Choice(start="2026-11-24")}, AT)
    t = {Library(conn).copies[x].row: x for x in made}
    report = get(conn, t[r["report"]])
    assert report.start == "2026-11-24" and report.ties["start"].amount == 2  # Tuesday: 2 workdays after Friday
    assert "start_tie" not in links_of(conn, report.id) and "duration" in links_of(conn, report.id)
    assert dates(conn, t[r["review"]]) == ("2026-12-02", "2026-12-02")  # what's tied to it moved too


def test_make_tasks_from_a_row_drops_a_tie_whose_source_is_not_being_made(trial):
    conn, r = trial
    made = templates.make_tasks(conn, SETTINGS, r["report"], "", None, {r["report"]: Choice(start=MON_23)}, AT)
    t = get(conn, made[0])
    assert t.start == MON_23 and not t.ties and "start_tie" not in links_of(conn, made[0])


def test_make_dates_says_what_make_tasks_does(trial):
    conn, r = trial
    lib = Library(conn)
    typed = {x.id: Typed(x.ties, x.duration, False) for x, _ in lib.walk(r["top"])}
    typed[r["window"]] = Typed({}, 5, False, MON_16)
    shown = timing.make_dates(typed, r["window"], WEEK)
    t = make_tree(conn, r)
    for key, task in t.items():
        assert shown[r[key]] == dates(conn, task), key


def test_make_dates_with_a_date_typed_over_and_the_anchor_blank():
    typed = {1: Typed({}, 5), 2: Typed({"start": start_tie(1, "after", "end")}, 5), 3: Typed({"start": start_tie(1, "after", "end", 2)}, 1)}
    assert timing.make_dates(typed, 1, WEEK) == {1: (None, None), 2: (None, None), 3: (None, None)}
    typed[1] = Typed({}, 5, False, MON_16)
    typed[2] = Typed({"start": start_tie(1, "after", "end")}, 5, over="2026-11-24")
    assert timing.make_dates(typed, 1, WEEK)[2] == ("2026-11-24", "2026-11-30")
    assert timing.make_dates(typed, 1, WEEK)[3] == ("2026-12-01", "2026-12-01")


def test_make_says_how_many_were_placed(trial, tmp_path):
    conn, r = trial
    from docrepo.safe_fs import SafeFS

    fs = SafeFS([tmp_path])
    _, out = templates.make(conn, tmp_path, fs, SETTINGS, r["top"], "Trial 1", None, {r["window"]: Choice(start=MON_16)}, AT)
    assert "5 placed by their ties, and they'll move with what they're tied to." in out.message


# ---- changing a tied date on a task (decision 247) ----
def test_a_tied_date_changed_by_hand_stays_tied_and_stops_following_the_number(trial):
    conn, r = trial
    t = make_tree(conn, r)
    edit(conn, t["report"], start="2026-11-25")
    report = get(conn, t["report"])
    assert report.ties["start"].amount == 3 and "start_tie" not in links_of(conn, report.id)
    assert any("Start tie: no longer follows Product trial" in x for x in lines_of(conn, report.id))
    edit(conn, t["window"], start=MON_23)  # it stays tied, so it still moves
    assert get(conn, t["report"]).start == "2026-12-02"


def test_following_the_tie_again_takes_the_templates_number_back(trial):
    conn, r = trial
    t = make_tree(conn, r)
    edit(conn, t["report"], start="2026-11-25")
    link = templates.task_link(conn, t["report"])
    assert link.ties["start"] == Tie(t["window"], "end", 1, "workdays", "after") and link.tie_words["start"] == "1 workday after the anchor ends"
    tasks.update_task(conn, SETTINGS, t["report"], at=LATER, via="Browse tool", keep_links=True, ties={"start": link.ties["start"]})
    tasks.set_links(conn, t["report"], [*links_of(conn, t["report"]), "start_tie"], at=LATER, via="Browse tool")
    assert dates(conn, t["report"]) == (MON_23, FRI_27) and "start_tie" in links_of(conn, t["report"])


def test_detach_ends_following_and_ties_stay(trial, tmp_path):
    conn, r = trial
    from docrepo.safe_fs import SafeFS

    t = make_tree(conn, r)
    templates.detach(conn, tmp_path, SafeFS([tmp_path]), t["report"], LATER)
    assert not links_of(conn, t["report"]) and get(conn, t["report"]).ties
    edit(conn, t["window"], start=MON_23)
    assert get(conn, t["report"]).start == "2026-11-30"


# ---- the Timing window (decisions 255 and 257) ----
def retimed(conn, r, **changes) -> dict[int, RowTiming]:
    """The template's timing with these rows changed, by the fixture's names."""
    _, rows = timing_of(conn, r)
    return {**rows, **{r[k]: v for k, v in changes.items()}}


def test_a_new_gap_on_a_row_previews_each_tree_and_what_follows(trial):
    conn, r = trial
    t, other = make_tree(conn, r), make_tree(conn, r, "Trial 2", "2026-12-07")
    held = dates(conn, t["report"])
    plan = templates.preview_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(3, "after", "end")}, 5)), LATER)
    assert dates(conn, t["report"]) == held and Library(conn).rows[r["report"]].ties["start"].amount == 1  # nothing changed yet
    assert plan.changed and plan.what == "Timing around Trial execution window"
    assert [i.task for i in plan.items] == [t["report"], t["review"], other["report"], other["review"]]
    assert plan.items[0].tree == "Trial 1 › Trial report"
    assert any(x.startswith("Start ") and "→" in x for x in plan.items[0].lines)


def test_saving_a_new_gap_moves_the_tasks_following_it(trial):
    conn, r = trial
    t = make_tree(conn, r)
    plan = templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(3, "after", "end")}, 5)), LATER)
    assert {i.task for i in plan.items} == {t["report"], t["review"]}
    assert dates(conn, t["report"]) == ("2026-11-25", "2026-12-01")
    assert "start_tie" in links_of(conn, t["report"])
    assert any("Template: Product trial" in e.via for e in Model(conn).status_log_of(t["report"]))
    lib = Library(conn)
    assert lib.changes[r["id"]][0].text == "Timing around Trial execution window" and lib.changes[r["id"]][0].reached == 2


def test_an_unticked_task_keeps_its_date_stays_tied_and_stops_following(trial):
    conn, r = trial
    t, other = make_tree(conn, r), make_tree(conn, r, "Trial 2", "2026-12-07")
    held = dates(conn, t["report"])
    plan = templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(3, "after", "end")}, 5)), LATER, left=[t["report"]])
    assert dates(conn, t["report"]) == held and get(conn, t["report"]).ties["start"].amount == 1
    assert "start_tie" not in links_of(conn, t["report"])
    assert dates(conn, t["review"]) == (TUE_DEC_1, TUE_DEC_1)  # what's tied to it stays too
    assert get(conn, other["report"]).ties["start"].amount == 3
    assert {i.task for i in plan.items} == {other["report"], other["review"]}
    assert Library(conn).changes[r["id"]][0].left_out == 1


def test_a_follower_left_behind_takes_a_new_gap(trial):
    conn, r = trial
    t = make_tree(conn, r)
    templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(3, "after", "end")}, 5)), LATER, left=[t["review"]])
    assert dates(conn, t["review"]) == (TUE_DEC_1, TUE_DEC_1) and get(conn, t["review"]).ties["start"].amount == 0  # the report now ends that day
    assert "start_tie" not in links_of(conn, t["review"])


def test_a_new_days_reaches_what_follows_it(trial):
    conn, r = trial
    t = make_tree(conn, r)
    templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(1, "after", "end")}, 10)), LATER)
    assert dates(conn, t["report"]) == (MON_23, "2026-12-04") and get(conn, t["report"]).duration == 10
    assert dates(conn, t["review"]) == ("2026-12-08", "2026-12-08")


def test_closed_tasks_never_change_and_are_listed(trial):
    conn, r = trial
    t = make_tree(conn, r)
    held = dates(conn, t["report"])
    edit(conn, t["report"], state="Closed")
    rows = retimed(conn, r, report=RowTiming({"start": start_tie(3, "after", "end")}, 5))
    plan = templates.preview_timing(conn, SETTINGS, r["id"], r["window"], rows, LATER)
    assert [(x.task, x.why) for x in plan.not_changing] == [(t["report"], "closed")]
    templates.apply_timing(conn, SETTINGS, r["id"], r["window"], rows, LATER)
    assert dates(conn, t["report"]) == held and get(conn, t["report"]).ties["start"].amount == 1


def test_a_row_that_starts_having_a_tie_reaches_only_tasks_with_no_date_there(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Audit", AT)
    walk, write = add(conn, top, row("Walk the equipment", duration=1)), add(conn, top, row("Write up findings", duration=2))
    template = Library(conn).rows[top].template
    empty = templates.make_tasks(conn, SETTINGS, top, "Audit 1", None, {walk: Choice(start=MON_16)}, AT)
    dated = templates.make_tasks(conn, SETTINGS, top, "Audit 2", None, {walk: Choice(start=MON_16), write: Choice(start=FRI_27)}, AT)
    lib = Library(conn)
    copy_empty, copy_dated = (next(x for x in ids if lib.copies[x].row == write) for ids in (empty, dated))
    rows = {walk: RowTiming({}, 1), write: RowTiming({"start": start_tie(1, "after", "end")}, 2)}
    plan = templates.preview_timing(conn, SETTINGS, template, walk, rows, LATER)
    assert [i.task for i in plan.items] == [copy_empty]
    assert [(x.task, x.why) for x in plan.not_changing] == [(copy_dated, "own")] and "its own start date" in plan.not_changing[0].text
    templates.apply_timing(conn, SETTINGS, template, walk, rows, LATER)
    assert get(conn, copy_empty).start == "2026-11-17" and "start_tie" in links_of(conn, copy_empty)
    assert get(conn, copy_dated).start == FRI_27 and not get(conn, copy_dated).ties and "start_tie" not in links_of(conn, copy_dated)


def test_a_row_that_drops_a_tie_leaves_its_tasks_tied_as_their_own(trial):
    conn, r = trial
    t = make_tree(conn, r)
    templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({}, 5)), LATER)
    report = get(conn, t["report"])
    assert report.ties["start"].source == t["window"] and "start_tie" not in links_of(conn, report.id)
    assert any("Start tie: no longer follows Product trial" in x for x in lines_of(conn, report.id))
    edit(conn, t["window"], start=MON_23)
    assert get(conn, t["report"]).start == "2026-11-30"


def test_a_new_anchor_keeps_the_picture(trial):
    conn, r = trial
    lines = Library(conn).lines(r["id"])
    was = timing.positions(lines, r["window"], 5)
    moved = timing.rebased(lines, r["window"], r["report"], 5)
    now = timing.positions(moved, r["report"], 5)
    gap = was[r["report"]][0]
    assert all(now[k][0] == was[k][0] - gap and now[k][1] == was[k][1] for k in was)
    by_id = {x.id: x for x in moved}
    assert not by_id[r["report"]].ties
    assert by_id[r["window"]].ties == {"start": RowTie(None, "start", 5, "workdays", "before")}  # the report started 5 workdays after it
    assert by_id[r["review"]].ties["start"].source is None  # it was tied to the report, which is now the anchor


def test_saving_a_new_anchor_leaves_a_tree_where_it_is(trial):
    conn, r = trial
    t = make_tree(conn, r)
    held = {k: dates(conn, x) for k, x in t.items()}
    lines = timing.rebased(Library(conn).lines(r["id"]), r["window"], r["report"], 5)
    rows = {x.id: RowTiming(dict(x.ties), x.days) for x in lines if x.placeable}
    plan = templates.preview_timing(conn, SETTINGS, r["id"], r["report"], rows, LATER)
    assert plan.changed and not plan.items and plan.what == "Timing around Trial report"
    templates.apply_timing(conn, SETTINGS, r["id"], r["report"], rows, LATER)
    assert {k: dates(conn, x) for k, x in t.items()} == held
    assert not get(conn, t["report"]).ties and "start_tie" not in links_of(conn, t["report"])
    assert get(conn, t["window"]).ties["start"].source == t["report"] and "start_tie" in links_of(conn, t["window"])
    edit(conn, t["report"], start="2026-11-30")  # the new anchor moves them all
    assert dates(conn, t["window"]) == (MON_23, "2026-11-27")


def test_a_tree_tied_to_another_task_stays_driven_from_it_when_the_anchor_changes(trial):
    conn, r = trial
    outage = tasks.create_task(conn, SETTINGS, title="Line 2 outage", at=AT, created_by="Browse tool", start="2026-11-09", due="2026-11-11")
    t = make_tree(conn, r, start=None, tie=Tie(outage, "end", 3, "workdays", "after"))
    plain = make_tree(conn, r, "Trial 2", "2026-12-07")
    held = {k: dates(conn, x) for k, x in t.items()}
    lines = timing.rebased(Library(conn).lines(r["id"]), r["window"], r["report"], 5)
    rows = {x.id: RowTiming(dict(x.ties), x.days) for x in lines if x.placeable}
    plan = templates.preview_timing(conn, SETTINGS, r["id"], r["report"], rows, LATER)
    assert not plan.items and [(x.task, x.why) for x in plan.not_changing] == [(t["window"], "own")] and "start tie" in plan.not_changing[0].text
    templates.apply_timing(conn, SETTINGS, r["id"], r["report"], rows, LATER)
    assert {k: dates(conn, x) for k, x in t.items()} == held
    assert get(conn, t["window"]).ties["start"].source == outage  # the tie to the outage stays, and the chain still runs from it
    assert get(conn, t["report"]).ties["start"].source == t["window"] and "start_tie" not in links_of(conn, t["report"])
    edit(conn, outage, start="2026-11-16", due="2026-11-18")
    assert dates(conn, t["window"]) == (MON_23, "2026-11-27") and dates(conn, t["report"]) == ("2026-11-30", "2026-12-04")
    assert dates(conn, t["review"]) == ("2026-12-08", "2026-12-08") and dates(conn, t["change"]) == ("2026-10-12", "2026-10-23")
    assert not get(conn, plain["report"]).ties and get(conn, plain["window"]).ties["start"].source == plain["report"]  # the other tree moves over as usual


def test_no_anchor_places_the_rows_tied_to_it_by_hand(trial):
    conn, r = trial
    t = make_tree(conn, r)
    lines = timing.without_anchor(Library(conn).lines(r["id"]))
    templates.apply_timing(conn, SETTINGS, r["id"], None, {x.id: RowTiming(dict(x.ties), x.days) for x in lines if x.placeable}, LATER)
    lib = Library(conn)
    assert lib.templates[r["id"]].anchor is None and not lib.rows[r["report"]].ties
    assert lib.rows[r["review"]].ties["start"].source == r["report"]  # tied to a row, so it stays
    assert get(conn, t["report"]).ties and "start_tie" not in links_of(conn, t["report"])
    assert "start_tie" in links_of(conn, t["review"])


def test_a_rows_tie_that_would_make_a_circle_with_a_tasks_own_doesnt_take(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Audit", AT)
    walk, write = add(conn, top, row("Walk the equipment", duration=1)), add(conn, top, row("Write up findings", duration=2))
    made = templates.make_tasks(conn, SETTINGS, top, "Audit 1", None, {}, AT)
    lib = Library(conn)
    copy = {lib.copies[x].row: x for x in made}
    edit(conn, copy[walk], ties={"start": Tie(copy[write], "end", 1, "workdays", "after")})  # a tie of the task's own
    template = lib.rows[top].template
    templates.apply_timing(conn, SETTINGS, template, walk, {walk: RowTiming({}, 1), write: RowTiming({"start": start_tie(1, "after", "end")}, 2)}, LATER)
    assert get(conn, copy[walk]).ties["start"].source == copy[write]
    assert not get(conn, copy[write]).ties and "start_tie" not in links_of(conn, copy[write])


def test_a_template_with_no_ties_makes_undated_tasks_as_before(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Audit", AT)
    add(conn, top, row("Walk the equipment", duration=1))
    made = templates.make_tasks(conn, SETTINGS, top, "Audit 1", None, {}, AT)
    assert all(dates(conn, x) == (None, None) and not get(conn, x).ties for x in made)


def test_saving_the_same_timing_changes_nothing(trial):
    conn, r = trial
    make_tree(conn, r)
    anchor, rows = timing_of(conn, r)
    plan = templates.preview_timing(conn, SETTINGS, r["id"], anchor, rows, LATER)
    assert not plan.changed and not plan.items


# ---- what can be tied (decisions 250 and 253) ----
def test_a_circle_is_refused(trial):
    conn, r = trial
    with pytest.raises(TaskError, match="go in a circle"):
        templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=RowTiming({"start": start_tie(1, "after", "end", r["review"])}, 5)), LATER)
    assert Library(conn).rows[r["report"]].ties["start"].source is None


def test_a_row_that_repeats_cant_be_a_source_or_the_anchor(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Audit", AT)
    weekly = add(conn, top, row("Weekly check", recurrence="Weekly"))
    other = add(conn, top, row("Write up findings", duration=2))
    template = Library(conn).rows[top].template
    with pytest.raises(TaskError, match="repeats"):
        templates.apply_timing(conn, SETTINGS, template, weekly, {other: RowTiming({}, 2)}, AT)
    with pytest.raises(TaskError, match="repeats"):
        templates.apply_timing(conn, SETTINGS, template, None, {other: RowTiming({"start": start_tie(1, "after", "end", weekly)}, 2)}, AT)


def test_a_row_that_repeats_keeps_no_ties(trial):
    conn, r = trial
    templates.apply_row(conn, SETTINGS, r["review"], row("Management review", recurrence="Weekly", ties={"start": start_tie(1, "after", "end")}), AT)
    assert not Library(conn).rows[r["review"]].ties


def test_a_row_others_count_from_cant_start_repeating(trial):
    conn, r = trial
    with pytest.raises(TaskError, match="anchor, so it can't repeat"):
        templates.apply_row(conn, SETTINGS, r["window"], row("Trial execution window", recurrence="Weekly"), AT)
    with pytest.raises(TaskError, match="Management review is tied to Trial report, so it can't repeat"):
        templates.apply_row(conn, SETTINGS, r["report"], row("Trial report", recurrence="Weekly"), AT)
    assert Library(conn).rows[r["report"]].recurrence is None


def test_both_dates_tied_take_their_length_from_them(trial):
    conn, r = trial
    both = RowTiming({"start": start_tie(1, "after", "end"), "due": start_tie(3, "after", "end")}, 5)
    templates.apply_timing(conn, SETTINGS, r["id"], r["window"], retimed(conn, r, report=both), AT)
    assert Library(conn).rows[r["report"]].duration is None
    t = make_tree(conn, r)
    report = get(conn, t["report"])
    assert (report.start, report.due, report.duration) == (MON_23, "2026-11-25", None)
    assert {"start_tie", "due_tie"} <= links_of(conn, report.id) and "duration" not in links_of(conn, report.id)


# ---- a row's own form (decision 255) ----
def test_a_row_form_changes_its_ties_through_the_preview(trial):
    conn, r = trial
    t = make_tree(conn, r)
    values = row("Trial report", duration=5, ties={"start": start_tie(3, "after", "end")})
    plan = templates.preview_row(conn, SETTINGS, r["report"], values, LATER)
    assert "Start tie 1 workday after the anchor ends → 3 workdays after the anchor ends" in plan.lines
    assert [i.task for i in plan.items] == [t["report"]] and "Start tie" in " ".join(plan.items[0].lines)
    assert any(x.startswith("Start ") and "→" in x for x in plan.items[0].lines)
    assert [i.task for i in plan.moved] == [t["review"]] and plan.moved[0].tree == "Trial 1 › Management review"
    assert get(conn, t["report"]).ties["start"].amount == 1  # nothing changed yet
    done = templates.apply_row(conn, SETTINGS, r["report"], values, LATER)
    assert done.followed == 1 and get(conn, t["report"]).ties["start"].amount == 3
    assert dates(conn, t["report"]) == ("2026-11-25", "2026-12-01") and dates(conn, t["review"]) == ("2026-12-03", "2026-12-03")


def test_a_row_form_can_leave_a_follower_behind(trial):
    conn, r = trial
    t = make_tree(conn, r)
    templates.apply_row(conn, SETTINGS, r["report"], row("Trial report", duration=5, ties={"start": start_tie(3, "after", "end")}), LATER, left=[t["review"]])
    assert dates(conn, t["review"]) == (TUE_DEC_1, TUE_DEC_1) and "start_tie" not in links_of(conn, t["review"])


def test_a_row_form_with_no_ties_given_leaves_them(trial):
    conn, r = trial
    templates.apply_row(conn, SETTINGS, r["report"], row("Trial report", duration=5), LATER)
    assert Library(conn).rows[r["report"]].ties["start"].amount == 1


def test_a_tied_task_whose_own_gap_differs_isnt_changed_by_a_row_form(trial):
    conn, r = trial
    t = make_tree(conn, r)
    edit(conn, t["report"], start="2026-11-25")
    plan = templates.preview_row(conn, SETTINGS, r["report"], row("Trial report", duration=5, ties={"start": start_tie(4, "after", "end")}), LATER)
    assert not plan.items and plan.not_changing[0].why == "own" and "start tie, 3 workdays after" in plan.not_changing[0].text


def test_a_new_subtask_arrives_tied_and_placed_in_each_tree(trial):
    conn, r = trial
    t, other = make_tree(conn, r), make_tree(conn, r, "Trial 2", "2026-12-07")
    values = row("Lessons learned", duration=2, ties={"start": start_tie(5, "after", "end", r["review"])})
    plan = templates.preview_new_row(conn, r["top"], values, LATER)
    assert plan.tied == "5 workdays after Management review ends"
    row_id, _, made = templates.add_row(conn, SETTINGS, r["top"], values, LATER, left=[other["top"]])
    assert len(made) == 1 and get(conn, made[0]).start == "2026-12-08" and "start_tie" in links_of(conn, made[0])
    assert get(conn, made[0]).ties["start"].source == t["review"]
    assert Library(conn).rows[row_id].ties["start"].source == r["review"]
    edit(conn, t["window"], start=MON_23)
    assert get(conn, made[0]).start == "2026-12-15"


def test_a_new_subtask_tied_to_the_anchor_says_so_with_no_anchor(sample_conn):
    conn = sample_conn
    top = templates.new_template(conn, "Audit", AT)
    row_id = add(conn, top, row("Walk the equipment", ties={"start": start_tie(1)}))  # there's no anchor to count from
    assert not Library(conn).rows[row_id].ties


# ---- taking out, duplicating and saving as a template (decision 258) ----
def test_taking_out_a_source_places_those_tied_to_it_by_hand(trial):
    conn, r = trial
    t = make_tree(conn, r)
    assert templates.preview_remove(conn, r["report"]).untied == ["Management review"]
    templates.remove_row(conn, SETTINGS, r["report"], LATER)
    lib = Library(conn)
    assert not lib.rows[r["review"]].ties
    assert get(conn, t["review"]).ties["start"].source == t["report"] and "start_tie" not in links_of(conn, t["review"])


def test_taking_out_the_anchor_leaves_no_anchor(trial):
    conn, r = trial
    make_tree(conn, r)
    assert "Trial report" in templates.preview_remove(conn, r["window"]).untied
    templates.remove_row(conn, SETTINGS, r["window"], LATER)
    lib = Library(conn)
    assert lib.templates[r["id"]].anchor is None and not lib.rows[r["report"]].ties and not lib.rows[r["change"]].ties
    assert lib.rows[r["review"]].ties  # tied to the report, which stays


def test_duplicate_keeps_the_timing_inside_the_copy(trial):
    conn, r = trial
    top = templates.duplicate(conn, r["id"], "Trial copy", AT)
    lib = Library(conn)
    copy = lib.rows[top].template
    titles = {x.title: x for x, _ in lib.walk(top)}
    assert lib.templates[copy].anchor == titles["Trial execution window"].id
    assert titles["Management review"].ties["start"].source == titles["Trial report"].id
    assert titles["Trial report"].ties["start"].source is None and titles["Operations training"].ties["due"].amount == 1
    assert lib.rows[r["review"]].ties["start"].source == r["report"]  # the original's are its own


def test_save_as_template_carries_the_ties_inside_the_tree(sample_conn):
    conn = sample_conn
    outage = tasks.create_task(conn, SETTINGS, title="Line 2 outage", at=AT, created_by="Browse tool", start="2026-11-09", due="2026-11-11")
    top = tasks.create_task(conn, SETTINGS, title="Trial 7", at=AT, created_by="Browse tool")
    first = tasks.create_task(conn, SETTINGS, title="First", at=AT, created_by="Browse tool", parents=[top], start=MON_16, duration=5)
    second = tasks.create_task(conn, SETTINGS, title="Second", at=AT, created_by="Browse tool", parents=[top], duration=2)
    third = tasks.create_task(conn, SETTINGS, title="Third", at=AT, created_by="Browse tool", parents=[top], duration=2)
    edit(conn, second, ties={"start": Tie(first, "end", 1, "workdays", "after")})
    edit(conn, third, ties={"start": Tie(outage, "end", 1, "workdays", "after")})
    row_top = templates.save_as_template(conn, SETTINGS, top, "Saved trial", True, AT)
    lib = Library(conn)
    rows = {x.title: x for x, _ in lib.walk(row_top)}
    assert rows["Second"].ties["start"] == RowTie(rows["First"].id, "end", 1, "workdays", "after")
    assert not rows["Third"].ties  # it reaches outside the tree
    assert lib.templates[rows["First"].template].anchor is None
    assert "start_tie" in links_of(conn, second) and "start_tie" not in links_of(conn, third)
    assert get(conn, third).ties  # the task keeps its own
    made = templates.make_tasks(conn, SETTINGS, row_top, "Trial 8", None, {rows["First"].id: Choice(start=MON_23)}, AT)
    copies = {Library(conn).copies[x].row: x for x in made}
    assert get(conn, copies[rows["Second"].id]).start == "2026-11-30"  # a tie to a row needs no anchor


# ---- the sums ----
def test_a_row_tie_in_words():
    titles = {7: "Trial report"}
    assert timing.words(start_tie(30), titles) == "30 workdays before the anchor starts"
    assert timing.words(start_tie(1, "after", "end", 7), titles) == "1 workday after Trial report ends"
    assert timing.words(start_tie(0), titles) == "The day the anchor starts"
    assert timing.words(start_tie(6, unit="weeks"), titles) == "6 weeks before the anchor starts"
    assert timing.brief(start_tie(30), titles) == "30 workdays before start"
    assert timing.brief(start_tie(1, "after", "end"), titles) == "1 workday after end"
    assert timing.brief(start_tie(2, "after", "end", 7), titles) == "2 workdays after Trial report ends"
    assert timing.timing_words({"due": start_tie(1)}, titles) == "Due 1 workday before start"


def test_the_list_says_what_a_row_is_tied_to(trial):
    conn, r = trial
    lib = Library(conn)
    titles = lib.titles(r["id"])
    assert templates.list_summary(lib.rows[r["change"]], titles) == "30 workdays before start · 10 days"
    assert templates.list_summary(lib.rows[r["review"]], titles) == "2 workdays after Trial report ends · 1 day"
    assert templates.list_summary(lib.rows[r["window"]], titles) == "5 days"


def test_positions_count_from_the_anchor():
    lines = [Line(1, "Group", spans=True), Line(2, "Before", parent=1, days=10, ties={"start": start_tie(30)}), Line(3, "Anchor", days=5),
             Line(4, "After", days=5, ties={"start": start_tie(1, "after", "end")}), Line(5, "Last", days=1, ties={"start": start_tie(2, "after", "end", 4)}),
             Line(6, "Due tied", days=3, ties={"due": start_tie(1)}), Line(7, "By hand", days=2), Line(8, "Weeks", days=1, ties={"start": start_tie(2, "after", unit="weeks")})]
    pos = timing.positions(lines, 3, 5)
    assert pos == {2: (-30, 10), 3: (0, 5), 4: (5, 5), 5: (11, 1), 6: (-3, 3), 8: (10, 1)}
    assert timing.span_of(lines, 1, pos) == (-30, 10)


def test_positions_with_both_dates_tied_take_their_length_from_them():
    lines = [Line(1, "Anchor", days=5), Line(2, "Both", ties={"start": start_tie(1, "after"), "due": start_tie(3, "after")})]
    assert timing.positions(lines, 1, 5)[2] == (1, 3)


def test_the_scale_has_the_anchor_and_every_row():
    pos = {2: (-30, 10), 3: (0, 5), 5: (11, 1)}
    s = timing.scale_of(pos, 5)
    assert s.low < -30 and s.high > 12 and s.step == 2
    assert 0 in s.ticks() and all(k % s.step == 0 for k in s.ticks())
    assert 0 < s.at(0) < 1 and timing.tick_label(0) == "Anchor" and timing.tick_label(-2) == "−2 wk" and timing.tick_label(4) == "+4 wk"


def test_moves_with_finds_a_chain():
    lines = [Line(1, "A"), Line(2, "B", ties={"start": start_tie(1)}), Line(3, "C", ties={"start": start_tie(1, source=2)})]
    assert timing.moves_with(lines, 1, 3, 1) and timing.moves_with(lines, 1, 3, 2)
    assert not timing.moves_with(lines, 1, 1, 3)


def test_the_schema_holds_a_timing(sample_conn):
    assert db.SCHEMA_VERSION >= 20
    assert sample_conn.execute("SELECT count(*) FROM template_row_ties").fetchone()[0] == 0
    assert sample_conn.execute("SELECT count(*) FROM templates WHERE anchor_row IS NOT NULL").fetchone()[0] == 0
