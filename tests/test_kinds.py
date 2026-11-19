"""Collections and a task's kind (release 5.167, the design workspace's docs/mods/collections-and-kinds-plan.md,
decisions 774 to 785 and 787): schema 30's flag, the kinds worked out, each view's rule, making and archiving a
collection, the Timeline's Show routine, and Task.md's Kind row. The sample is made up."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pytest

from docrepo import (capacity, collection_edits, db, edits, key_dates, kinds, lists, priorities, progress, quick, review, search,
                     summary, tasks, timeline, views, waits, whatif)
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import Pages
from docrepo.safe_fs import SafeFS
from docrepo.save import SaveError
from tests.test_migrations import unzip_root

TODAY_ = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 0)
SETTINGS = Settings(me="P001")


def new(conn: sqlite3.Connection, title: str, parents: tuple[str, ...] = (), **fields) -> str:
    return tasks.create_task(conn, SETTINGS, title=title, at=AT, created_by="test", parents=parents, **fields)


def kind(conn: sqlite3.Connection, task_id: str) -> str:
    m = Model(conn)
    return kinds.kind_of(m, m.task(task_id))


# ---- the schema ----
def test_a_schema_29_root_comes_up_with_quick_tasks_a_collection(tmp_path):
    root = unzip_root("v29", tmp_path)
    conn = db.connect(SafeFS([root]), root)
    try:
        rows = {r["id"]: (r["created_by"], r["collection"]) for r in conn.execute("SELECT id, created_by, collection FROM tasks")}
    finally:
        conn.close()
    assert [x for x, (by, on) in rows.items() if on] == [x for x, (by, _) in rows.items() if by == quick.CREATOR] != []
    assert sum(on for _, on in rows.values()) == 1


def test_a_new_quick_tasks_is_a_collection(sample_conn):
    pid = quick.ensure_parent(sample_conn, SETTINGS, AT)
    assert Model(sample_conn).task(pid).collection


def test_the_flag_is_a_check_of_0_or_1(sample_conn):
    with pytest.raises(sqlite3.IntegrityError):
        sample_conn.execute("UPDATE tasks SET collection = 2 WHERE id = 'T000016'")


# ---- the kinds (decision 775) ----
def test_each_kind_from_what_is_stored(sample_conn):
    c = new(sample_conn, "Job aids", collection=True)
    m = Model(sample_conn)
    got = {x: kinds.kind_of(m, m.task(x)) for x in ("T000001", "T000006", "T000010", "T000016", "T000007", c)}
    assert got == {"T000001": "parent", "T000006": "routine", "T000010": "routine", "T000016": "single", "T000007": "single", c: "collection"}
    assert kinds.name_of(m, m.task("T000001")) == "Parent task" and kinds.NAMES["single"] == "Single task"


def test_a_regular_meetings_occurrence_is_routine_and_its_action_item_is_not(sample_conn):
    occ = new(sample_conn, "Business team meeting 8 Oct", ("T000010",), meeting=True, start="2026-10-08")
    item = new(sample_conn, "Send the minutes", ("T000010",))
    assert kind(sample_conn, occ) == "routine" and kind(sample_conn, item) == "single"
    assert kind(sample_conn, "T000010") == "routine"  # a rhythm and subtasks: routine comes first


def test_a_closed_subtask_counts_a_discarded_one_and_a_collection_dont(sample_conn):
    p = new(sample_conn, "Pump P-204A rebuild")
    done = new(sample_conn, "Order the seal kit", (p,), state="Closed")
    assert kind(sample_conn, p) == "parent"
    tasks.set_discarded(sample_conn, SETTINGS, done, "Made by mistake", at=AT, via="test")
    assert kind(sample_conn, p) == "single"
    new(sample_conn, "Pump drawings", (p,), collection=True)
    assert kind(sample_conn, p) == "single"


def test_a_single_task_becomes_a_parent_and_back(sample_conn):
    assert kind(sample_conn, "T000016") == "single"
    sub = new(sample_conn, "Ask Dana for the rota", ("T000016",))
    assert kind(sample_conn, "T000016") == "parent"
    tasks.remove_parent(sample_conn, sub, "T000016", at=AT, via="test")
    assert kind(sample_conn, "T000016") == "single"


def test_two_parents_one_a_collection(sample_conn):
    c = new(sample_conn, "Job aids", collection=True)
    x = new(sample_conn, "Lift plan checklist", (c, "T000016"))
    m = Model(sample_conn)
    assert kinds.kind_of(m, m.task("T000016")) == "parent" and kinds.kind_of(m, m.task(c)) == "collection"
    assert kinds.work_parents(m, x) == ["T000016"]
    deep = new(sample_conn, "Sling chart", (x,))
    top = new(sample_conn, "Under the collection", (c,))
    m = Model(sample_conn)
    assert kinds.work_parents(m, top) == [] and kinds.work_parents(m, deep) == [x]


def test_kind_of_adds_nothing_to_a_models_read(sample_conn, monkeypatch):
    m = Model(sample_conn)
    calls = []
    real = m.children_of
    monkeypatch.setattr(m, "children_of", lambda x: calls.append(x) or real(x))
    for t in m.tasks.values():
        kinds.kind_of(m, t)
    assert len(calls) <= len(m.tasks)


# ---- each view (decision 780) ----
@pytest.fixture
def filed(sample_root):
    """A collection that was a task with everything a list could want: dates, a reminder, Urgent, people, a priority, a
    key date and hours, and a dated task under it."""
    conn, root, fs = sample_root
    c = new(conn, "Rigging job aids", due="2026-10-09", deadline="2026-10-10", reminder="2026-10-08", urgent=True, assignees=["P002"],
            lead_hours=4, start="2026-10-05", leads=["P001"])
    priorities.place(conn, c, "critical", at=AT, via="test")
    tasks.add_key_dates(conn, c, [tasks.KeyDateRow("2026-10-09", "", "Crane on site", False, False)], at=AT, via="test")
    under = new(conn, "Check the sling certificates", (c,), due="2026-10-12", start="2026-10-06", assignees=["P002"])
    collection_edits.make_collection(conn, root, fs, SETTINGS, c, AT)
    return conn, root, fs, c, under


def test_a_collection_is_out_of_the_work(filed):
    conn, _, _, c, under = filed
    m = Model(conn)
    for x in lists.LISTS:
        assert c not in [t.id for t in lists.list_tasks(m, x, TODAY_, "P001")], x.id
    assert c not in [t.id for t in views.due_this_week(m, TODAY_, "P001")]
    assert c not in [d.task.id for d in key_dates.due(m, TODAY_)]
    board = priorities.columns(m, TODAY_, priorities.BoardFilter())
    assert c not in [x for col in board for x in col.ids] and under in [x for col in board for x in col.ids]
    rows = [r.task for r in timeline.build(m, TODAY_, date(2026, 10, 5), 4, open_ids={c, under}).rows]
    assert c not in rows and under in rows
    assert c not in [t.id for t in review.due_for_review(m, TODAY_, 1)] and c not in review.gone_quiet(m, TODAY_, 0)
    assert c not in [t.id for t in review.no_next_step(m, TODAY_)]
    assert capacity.task_rows(m.task(c), TODAY_, SETTINGS) == {} and c not in sum(capacity.unplaced(m, TODAY_, SETTINGS), [])
    assert not summary.worklike(m.task(c)) and summary.worklike(m.task(under))
    assert views.view_counts(m, TODAY_, "P001")["tasks"] == sum(1 for t in m.tasks.values() if kinds.is_work(t))
    assert under in whatif.take_off(m, c).off and c in whatif.take_off(m, c).off[:1]
    assert c not in [t.id for t in m.open_meetings()]


def test_a_collection_is_in_where_things_are_filed(filed):
    conn, root, _, c, under = filed
    m = Model(conn)
    tree = views.task_tree(m, views.TreeFilter())
    ids = [n.id for n in tree] + [k.id for n in tree for k in n.children]
    assert c in ids
    assert c in str(search.search(conn, m, "Rigging job aids", TODAY_))
    page = (root / "Tasks" / c / "Task.md").read_text(encoding="utf-8")
    assert "| Kind | Collection |" in page and "\n| State |" not in page and "\n| Due |" not in page and "## Latest update" not in page
    assert f"{c} · collection" in (root / "Contents.md").read_text(encoding="utf-8")
    sub = (root / "Tasks" / under / "Task.md").read_text(encoding="utf-8")
    assert "| Kind | Single task |" in sub


def test_the_tree_filters_dont_match_a_collections_hidden_fields(filed):
    conn, _, _, c, _ = filed
    m = Model(conn)
    for f in (views.TreeFilter(urgent=True), views.TreeFilter(priorities=("critical",)), views.TreeFilter(people=("P002",))):
        top = next((n for n in views.task_tree(m, f) if n.id == c), None)
        assert top is None or not top.match  # at most the context of a task under it that matches


def test_making_one_takes_it_off_today_and_ends_its_wait_and_back(sample_root):
    conn, root, fs = sample_root
    x = "T000016"
    edits.add_to_today(conn, root, fs, x, "", AT)
    waits.start(conn, Model(conn), x, at="2026-10-08 09:00:00", line="Asked Dana", on=["P002"], follow_up=date(2026, 10, 12), via="test")
    tasks.update_task(conn, SETTINGS, x, at=AT, via="test", reminder="2026-10-12")
    out = collection_edits.make_collection(conn, root, fs, SETTINGS, x, AT)
    m = Model(conn)
    assert m.task(x).collection and "Off Today" in out.message and "wait ended" in out.message
    assert x not in [a.subject for a in m.today_items()] and waits.current(m, x) is None
    assert [(e.field, e.from_value, e.to_value) for e in m.status_log_of(x) if e.field == "Kind"] == [("Kind", "Task", "Collection")]
    assert m.task(x).reminder is None  # the reminder the wait set went with it
    with pytest.raises(edits.EditError, match="collection"):
        edits.add_to_today(conn, root, fs, x, "", AT)
    with pytest.raises(SaveError, match="collection"):
        progress.log_progress(conn, root, fs, SETTINGS, task_id=x, line="Called Dana", on=[], follow_up=None, at=AT)
    collection_edits.make_task(conn, root, fs, SETTINGS, x, AT)
    m = Model(conn)
    assert not m.task(x).collection and m.task(x).state == "Not started"
    assert [e.to_value for e in m.status_log_of(x) if e.field == "Kind"][-1] == "Task"


def test_with_everything_under_it(sample_root):
    conn, root, fs = sample_root
    out = collection_edits.make_collection(conn, root, fs, SETTINGS, "T000002", AT, with_below=True)
    m = Model(conn)
    assert all(m.task(x).collection for x in ("T000002", "T000017", "T000018")) and "2 more" in out.message


def test_quick_tasks_stays_a_collection(sample_root):
    conn, root, fs = sample_root
    pid = quick.ensure_parent(conn, SETTINGS, AT)
    with pytest.raises(collection_edits.CollectionError, match="built in"):
        collection_edits.make_task(conn, root, fs, SETTINGS, pid, AT)
    assert not collection_edits.can_archive(Model(conn), pid)


def test_archive_and_restore(sample_root):
    conn, root, fs = sample_root
    collection_edits.make_collection(conn, root, fs, SETTINGS, "T000002", AT)
    m = Model(conn)
    assert collection_edits.can_archive(m, "T000002")
    edits.set_states(conn, root, fs, SETTINGS, collection_edits.archive_ids(m, "T000002", False), AT)
    m = Model(conn)
    assert m.task("T000002").state == "Closed" and m.task("T000017").state != "Closed"  # Archive takes nothing under it along
    assert [e.field for e in m.status_log_of("T000002")][-1] == tasks.ARCHIVED
    shown = [n.id for n in views.task_tree(m, views.TreeFilter())]
    assert "T000002" not in shown and "T000002" in [n.id for n in views.task_tree(m, views.TreeFilter(closed=True))]
    edits.set_states(conn, root, fs, SETTINGS, {"T000002": collection_edits.RESTORED_STATE}, AT)
    m = Model(conn)
    assert m.task("T000002").state == "Not started"
    assert "| Kind | Collection |" in Pages(m, TODAY_, AT).task_page(m.task("T000002"))
    every = collection_edits.archive_ids(m, "T000002", True)
    assert set(every) == {"T000002", "T000017", "T000018"}


# ---- under and over (decision 782) ----
def test_a_collection_parent_has_no_card_and_its_tasks_keep_theirs(sample_conn):
    c = new(sample_conn, "Job aids", collection=True)
    a = new(sample_conn, "Write the lift job aid", (c,))
    m = Model(sample_conn)
    parents_view = priorities.columns(m, TODAY_, priorities.BoardFilter(show="parents"))
    assert a in [x for col in parents_view for x in col.ids] and c not in [x for col in parents_view for x in col.ids]
    assert a in [t.id for t in review.no_next_step(m, TODAY_)]  # top-level work, under a top-level collection
    assert review.is_project_like(m, m.task(a))


def test_a_collection_under_a_task_doesnt_make_it_a_parent_on_the_board(sample_conn):
    c = new(sample_conn, "Holiday rota files", ("T000016",), collection=True)
    m = Model(sample_conn)
    assert priorities.open_subtasks(m, "T000016") == [] and c not in priorities.open_subtasks(m, "T000016")


# ---- routine off the Timeline (decision 783) ----
def test_the_timeline_and_the_tree_agree_with_show_routine_off(sample_conn):
    only = new(sample_conn, "Collect the area 3 figures", ("T000006",), start="2026-10-06", due="2026-10-09")
    both = new(sample_conn, "Report template", ("T000006", "T000016"), start="2026-10-06", due="2026-10-09")
    occ = new(sample_conn, "Business team meeting 13 Oct", ("T000010",), meeting=True, start="2026-10-13")
    m = Model(sample_conn)
    every = {"T000006", "T000010", "T000016", only, both, occ}

    def tree_ids(routine: bool) -> set[str]:
        out: set[str] = set()

        def walk(ns):
            for n in ns:
                out.add(n.id)
                walk(n.children)

        walk(views.task_tree(m, views.TreeFilter(routine=routine)))
        return out

    def timeline_ids(routine: bool) -> set[str]:
        return {r.task for r in timeline.build(m, TODAY_, date(2026, 10, 5), 4, routine=routine, open_ids=every).rows}

    off_tl, off_tree = timeline_ids(False), tree_ids(False)
    assert only not in off_tl and only not in off_tree and "T000006" not in off_tl and occ not in off_tl
    assert both in off_tl and both in off_tree
    assert only in timeline_ids(True) and only in tree_ids(True)
    board = priorities.columns(m, TODAY_, priorities.BoardFilter())
    assert occ not in [x for col in board for x in col.ids]
    assert occ in [x for col in priorities.columns(m, TODAY_, priorities.BoardFilter(routine=True)) for x in col.ids]


# ---- the pages (decision 785) ----
def test_task_md_says_each_kind_after_state(sample_conn):
    m = Model(sample_conn)
    p = Pages(m, TODAY_, AT)
    assert "| State | In progress |\n| Kind | Parent task |" in p.task_page(m.task("T000001"))
    assert "| Kind | Routine task |" in p.task_page(m.task("T000006"))
    assert "| Kind | Single task |" in p.task_page(m.task("T000016"))


def test_a_collections_subtask_row_says_so(sample_conn):
    new(sample_conn, "Holiday rota files", ("T000016",), collection=True)
    m = Model(sample_conn)
    assert "| Collection |  |  |" in Pages(m, TODAY_, AT).task_page(m.task("T000016"))


# ---- the review's fixes (2026-11-18, before the merge) ----
def test_quick_tasks_tasks_stay_out_of_the_review_and_an_ordinary_collections_are_in(tmp_path):
    root = unzip_root("v29", tmp_path)
    conn = db.connect(SafeFS([root]), root)
    try:
        q = quick.parent_id(conn)
        quick_one = new(conn, "Call the crane hire", (q,))
        c = new(conn, "Job aids", collection=True)
        filed_one = new(conn, "Write the lift job aid", (c,))
        m = Model(conn)
        for x in (quick_one, filed_one):
            assert m.task(x).review_every is None and not m.task(x).due
        due = {t.id for t in review.due_for_review(m, TODAY_, 1)}
        none = {t.id for t in review.no_next_step(m, TODAY_)}
        assert quick_one not in due and quick_one not in none and not review.is_project_like(m, m.task(quick_one))
        assert filed_one in due and filed_one in none and review.is_project_like(m, m.task(filed_one))
    finally:
        conn.close()


def test_no_way_onto_today_for_a_collection(sample_root):
    from docrepo import agenda
    from docrepo.model import TODAY
    from docrepo.save import CaptureDraft, save_capture

    conn, root, fs = sample_root
    c = new(conn, "Job aids", collection=True)
    with pytest.raises(agenda.AgendaError, match="collection"):
        agenda.add_item(conn, subject=c, target=TODAY, note="", added="2026-10-08 09:00", added_by="test")
    # An Update with Today ticked: the capture is kept, the Today item isn't made, and the message says why.
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Binder checked.", task=c, types={"update"}, agenda=[TODAY], files=[]), AT)
    assert r.capture_id and "isn't put on Today" in r.message and "On Today" not in r.message
    # **today on its own line, on a note on it.
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="Check the binder **today", task=c, types={"update"}, files=[]), AT)
    # Activity's Add to agenda, with Today as its target.
    out = edits.add_activity_to_agenda(conn, root, fs, TODAY, [(c, ""), ("T000016", "")], AT)
    assert "Not on Today" in out.message and "Job aids" in out.message
    m = Model(conn)
    assert c not in [a.subject for a in m.today_items()] and "T000016" in [a.subject for a in m.today_items()]
    assert not [a for a in m.agenda if a.subject == c and a.target == TODAY]


def test_an_old_today_item_on_a_collection_isnt_counted(sample_root):
    conn, root, fs = sample_root
    edits.add_to_today(conn, root, fs, "T000016", "", AT)
    conn.execute("UPDATE tasks SET collection = 1 WHERE id = 'T000016'")  # as an older version could leave it
    m = Model(conn)
    assert "T000016" not in [a.subject for a in m.today_items()]
    assert views.view_counts(m, TODAY_, "P001")["today"] == len(m.today_items())


def test_a_labelled_collection_isnt_opened_closed_or_in_the_trend(sample_conn):
    from docrepo import summary as qs

    def counts() -> tuple[str, list[int]]:
        b = qs.Builder(Model(sample_conn), TODAY_, "P001", sample_conn)
        s = b.build(qs.subject_of(b.m, "label:Safety", "P001"))
        return dict(s.facts)["Last 30 days"], b.trend(b.label_task_ids("Safety"))

    before = counts()
    new(sample_conn, "Safety job aids", labels=["Safety"], collection=True)
    new(sample_conn, "Old safety binder", labels=["Safety"], collection=True, state="Closed")
    assert counts() == before


def test_archive_restore_and_make_it_a_task_keep_the_state(sample_root):
    conn, root, fs = sample_root
    x = "T000002"  # In progress
    collection_edits.make_collection(conn, root, fs, SETTINGS, x, AT)
    edits.set_states(conn, root, fs, SETTINGS, collection_edits.archive_ids(Model(conn), x, False), AT)
    m = Model(conn)
    assert [(e.field, e.from_value) for e in m.status_log_of(x)][-1] == (tasks.ARCHIVED, "In progress")
    edits.set_states(conn, root, fs, SETTINGS, {x: collection_edits.restored_state(m, x)}, AT)
    collection_edits.make_task(conn, root, fs, SETTINGS, x, AT)
    assert Model(conn).task(x).state == "In progress"
