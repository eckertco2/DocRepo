"""One read of docs.db for a change (release 5.163, the design workspace's ``docs/mods/one-read-plan.md``, decisions 746 and
747), without Qt: every change that writes its touched pages is handed the Model from before (``model_now``, which uses it
only while docs.db is as it was read) and hands back the one it read after its writes (``hand_back``), which is the same as
a fresh read; its pages are the same as when it reads its own; and a change in a transaction hands back nothing.

Over the sample data, with the workspace's made-up work for a wait's follow-up. Every name and line here is made up."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest

from docrepo import capacity, db, edits, priorities, prompts, search, waits
from docrepo import workspace as ws
from docrepo.config import Settings
from docrepo.db import transaction
from docrepo.model import TODAY, Model
from docrepo.pages import write_pages
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample, write_sample_files
from workspace_example import AT as WORK_AT

AT = datetime(2026, 10, 8, 9, 30)
SETTINGS = Settings(me="P001")
IMPELLER, INSTALLATION, VENDOR, MEETING, RIGGING, ALIGNMENT = "T000001", "T000008", "T000009", "T000010", "T000012", "T000019"


def make_root(folder: Path) -> tuple:
    """A data root holding the sample data with its files, as conftest's ``sample_root`` makes it, with its pages written."""
    folder.mkdir()
    fs = SafeFS([folder])
    conn = db.connect(fs, folder)
    load_sample(conn)
    write_sample_files(conn, folder, fs)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    prompts.write_defaults(fs, folder)
    search.rebuild(conn, folder)
    write_pages(Model(conn), folder, fs, AT.date(), AT)
    return conn, folder, fs


@pytest.fixture
def root(tmp_path: Path):
    env = make_root(tmp_path / "DocRepoData")
    yield env
    env[0].close()


@pytest.fixture
def twins(tmp_path: Path):
    """Two data roots made the same way: one for the change handed the Model, one for the change reading its own."""
    a, b = make_root(tmp_path / "a"), make_root(tmp_path / "b")
    yield a, b
    a[0].close()
    b[0].close()


def today_item(env, model: Model | None, subject: str | None, note: str = "") -> int:
    """A Today item's ID, from the Model handed to the change, so finding it reads nothing more."""
    m = model if model is not None else Model(env[0])
    return next(a.id for a in m.today_items() if a.subject == subject and (subject or a.note == note))


def put_on_today(env, *subjects: str | None, note: str = "") -> None:
    for s in subjects:
        edits.add_to_today(env[0], env[1], env[2], s, note if s is None else "", AT)


@dataclass
class Case:
    """A change: what's made first (not counted), then the change, handed ``model`` (None: it reads its own)."""

    prepare: Callable[[tuple], object]
    change: Callable[[tuple, Model | None], edits.Outcome] | None
    at: datetime = AT  # the day its pages are written for


def nothing(env) -> None:
    return None


def _with_a_wait(env) -> None:
    from workspace_example import make

    make(*env)


def _follow_up(env, model):
    m = model if model is not None else Model(env[0])
    crane = next(t.id for t in m.tasks.values() if waits.current(m, t.id) is not None)
    return ws.set_follow_up(env[0], env[1], env[2], SETTINGS, crane, date(2026, 11, 19), WORK_AT, model)


#: Every caller of ``write_touched_pages`` (decision 747): the 22 in edits.py and workspace's one.
CASES = {
    "file_capture": Case(nothing, lambda e, m: edits.file_capture(*e, "C000021", RIGGING, AT, m)),
    "edit_capture": Case(nothing, lambda e, m: edits.edit_capture(*e, "C000001", "Impeller datasheet, rev B", "", None, AT, m)),
    "clear_reminder": Case(nothing, lambda e, m: edits.clear_reminder(*e, SETTINGS, ALIGNMENT, AT, model=m)),
    "close_agenda_item": Case(nothing, lambda e, m: edits.close_agenda_item(*e, 2, "Discussed", AT, m)),
    "reopen_agenda_item": Case(lambda e: edits.close_agenda_item(*e, 2, "Removed", AT),
                               lambda e, m: edits.reopen_agenda_item(*e, 2, AT, m)),
    "back_on_today": Case(lambda e: (put_on_today(e, RIGGING), edits.close_today_item(*e, today_item(e, None, RIGGING), "Done", AT)),
                          lambda e, m: edits.back_on_today(*e, next(a.id for a in (m or Model(e[0])).agenda if a.subject == RIGGING and a.target == TODAY), AT, m)),
    "move_today_item": Case(lambda e: put_on_today(e, RIGGING, INSTALLATION),
                            lambda e, m: edits.move_today_item(*e, today_item(e, m, INSTALLATION), AT, to="top", model=m)),
    "today_bin": Case(lambda e: put_on_today(e, RIGGING, INSTALLATION),
                      lambda e, m: edits.today_bin(*e, today_item(e, m, RIGGING), "high", AT, m)),
    "add_agenda_item": Case(nothing, lambda e, m: edits.add_agenda_item(*e, MEETING, RIGGING, "Bring the lift plan", AT, m)),
    "discuss_agenda_item": Case(nothing, lambda e, m: edits.discuss_agenda_item(*e, 2, AT, m)),
    "add_to_today": Case(nothing, lambda e, m: edits.add_to_today(*e, RIGGING, "", AT, m)),
    "close_today_item": Case(lambda e: put_on_today(e, RIGGING), lambda e, m: edits.close_today_item(*e, today_item(e, m, RIGGING), "Done", AT, m)),
    "reminders_to_today": Case(lambda e: edits.change_task(*e, SETTINGS, ALIGNMENT, AT, reminder="2026-10-08"), None),  # its own test below
    "later": Case(nothing, lambda e, m: edits.later(*e, SETTINGS, RIGGING, date(2026, 10, 12), AT, None, m)),
    "undo_later": Case(lambda e: edits.later(*e, SETTINGS, RIGGING, date(2026, 10, 12), AT),
                       lambda e, m: edits.undo_later(*e, SETTINGS, RIGGING, None, AT, None, m)),
    "edit_today_note": Case(lambda e: put_on_today(e, None, note="Call the crane vendor"),
                            lambda e, m: edits.edit_today_note(*e, today_item(e, m, None, "Call the crane vendor"), "Call the crane vendor back", AT, m)),
    "change_task": Case(nothing, lambda e, m: edits.change_task(*e, SETTINGS, IMPELLER, AT, m, labels=["Safety"])),
    "mark_reviewed": Case(nothing, lambda e, m: edits.mark_reviewed(*e, SETTINGS, IMPELLER, AT, m)),
    "set_reviewed": Case(lambda e: edits.mark_reviewed(*e, SETTINGS, IMPELLER, AT), lambda e, m: edits.set_reviewed(*e, IMPELLER, None, AT, m)),
    "set_states": Case(nothing, lambda e, m: edits.set_states(*e, SETTINGS, {ALIGNMENT: "In progress", "T000007": "Parked"}, AT, m)),
    "edit_task": Case(nothing, lambda e, m: edits.edit_task(*e, SETTINGS, RIGGING, AT, m, parents=[VENDOR], title="Rigging and lift plan")),
    "set_priority": Case(nothing, lambda e, m: edits.set_priority(*e, RIGGING, "critical", None, AT)),
    "workspace.set_follow_up": Case(_with_a_wait, _follow_up, WORK_AT),
}
CHANGES = [name for name, c in CASES.items() if c.change is not None]


def assert_same(kept: Model, fresh: Model) -> None:
    """What the windows read from a Model: the tasks, the captures, the status log, the agendas, the pages and the rest of
    the records. (Its tagged labels are read when asked, since release 5.160.)"""
    for name in ("tasks", "captures", "status", "agenda", "pages", "key_dates", "links", "waits", "t_mails", "people", "labels",
                 "documents", "versions", "copies", "page_edits", "origins"):
        assert getattr(kept, name) == getattr(fresh, name), name


def files_of(folder: Path) -> dict[str, bytes]:
    """Every file DocRepo wrote in a data root, but docs.db and the logs."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.name.startswith("docs.db") and "Logs" not in p.parts}


def reads(monkeypatch) -> list[int]:
    """Each Model read from docs.db from now on."""
    import docrepo.model as model_module

    loads: list[int] = []
    init = model_module.Model.__init__
    monkeypatch.setattr(model_module.Model, "__init__", lambda self, c: (loads.append(1), init(self, c))[1])
    return loads


# ---- the Model handed back is a fresh read's (decision 747) ----
@pytest.mark.parametrize("name", CHANGES)
def test_the_model_handed_back_is_the_same_as_a_fresh_read(root, name, monkeypatch):
    conn = root[0]
    CASES[name].prepare(root)
    shared = Model(conn)  # as the browse tool's is, read as docs.db is now
    loads = reads(monkeypatch)
    out = CASES[name].change(root, shared)
    assert out.model is not None and out.model is not shared
    assert out.model.read_at == edits.read_now(conn)  # nothing written after it was read, so the browse tool keeps it
    n = len(loads)
    assert_same(out.model, Model(conn))
    # Handed the Model from before, a change reads docs.db once, after its writes. Filing a capture still reads it in its own
    # steps (its records, its saved files, its capture.md, its notes page and the search index), and so does fixing one's
    # title (the search index).
    assert n == 1 or name in ("file_capture", "edit_capture"), f"{name} read docs.db {n} times"


@pytest.mark.parametrize("name", CHANGES)
def test_the_pages_are_the_same_as_when_the_change_reads_its_own_model(twins, name):
    """The touched pages written from the Model handed in are those written when the change reads docs.db itself, as it
    did before release 5.163; and a full write after it finds nothing left (``test_touched_pages``'s oracle)."""
    (a, b) = twins
    for env in (a, b):
        CASES[name].prepare(env)
        write_pages(Model(env[0]), env[1], env[2], CASES[name].at.date(), CASES[name].at)  # what was made first is on the pages too
    out_a = CASES[name].change(a, Model(a[0]))
    out_b = CASES[name].change(b, None)
    assert out_a.message == out_b.message and out_a.problems == out_b.problems == []
    assert files_of(a[1]) == files_of(b[1])
    assert_same(Model(a[0]), Model(b[0]))
    assert write_pages(Model(a[0]), a[1], a[2], CASES[name].at.date(), CASES[name].at) == 0


def test_reminders_on_today_hand_their_model_to_keep(root, monkeypatch):
    conn = root[0]
    CASES["reminders_to_today"].prepare(root)
    shared, kept = Model(conn), []
    loads = reads(monkeypatch)
    assert ALIGNMENT in edits.reminders_to_today(*root, SETTINGS, AT, shared, kept.append)
    assert len(loads) == 1 and len(kept) == 1 and kept[0].read_at == edits.read_now(conn)
    assert_same(kept[0], Model(conn))
    assert ALIGNMENT in {a.subject for a in kept[0].today_items()}


# ---- a Model handed in is used only while it's docs.db as it is (decision 746) ----
def test_model_now_uses_the_one_handed_in_only_while_docs_db_is_as_it_read_it(root):
    conn = root[0]
    shared = Model(conn)
    assert edits.model_now(conn, shared) is shared
    assert edits.model_now(conn, None) is not shared
    priorities.place(conn, RIGGING, "high", None, at=AT, via=priorities.VIA)  # a write since it was read
    now = edits.model_now(conn, shared)
    assert now is not shared and now.task(RIGGING).priority == "high" and shared.task(RIGGING).priority is None
    conn.execute("BEGIN")
    try:
        inside = Model(conn)  # read inside a transaction: it could still be rolled back
        assert inside.read_at is None and edits.model_now(conn, inside) is not inside
    finally:
        conn.execute("ROLLBACK")
    other = db.connect_memory()  # another connection's Model, however its counts fall
    try:
        load_sample(other)
        theirs = Model(other)
        assert edits.model_now(conn, theirs) is not theirs
    finally:
        other.close()


def test_a_stale_model_handed_in_is_read_again_and_the_change_is_right(root, monkeypatch):
    """A Model read before another write isn't used: the change reads docs.db itself. A drop on a bin works out Today's new
    order from it, so with the stale one the item put on Today since would be left out of the order."""
    conn, data_root, fs = root
    put_on_today(root, RIGGING, INSTALLATION)
    stale = Model(conn)
    put_on_today(root, IMPELLER)  # a write since the stale Model was read
    loads = reads(monkeypatch)
    out = edits.today_bin(conn, data_root, fs, today_item(root, stale, RIGGING), "high", AT, stale)
    assert len(loads) == 2  # before and after, as before release 5.163
    assert [a.subject for a in out.model.today_items()] == [RIGGING, INSTALLATION, IMPELLER]
    assert_same(out.model, Model(conn))
    loads.clear()
    stale = Model(conn)
    edits.edit_task(conn, data_root, fs, SETTINGS, RIGGING, AT, parents=[VENDOR])  # Rigging plan now under the drawings
    out = edits.set_states(conn, data_root, fs, SETTINGS, {RIGGING: "Parked"}, AT, stale)
    assert_same(out.model, Model(conn))
    assert write_pages(Model(conn), data_root, fs, AT.date(), AT) == 0


def test_a_change_in_a_transaction_hands_back_no_model(root):
    """What's read inside a transaction could still be rolled back, so it's never handed back to be kept."""
    conn, data_root, fs = root
    with transaction(conn):
        out = edits.set_states(conn, data_root, fs, SETTINGS, {ALIGNMENT: "In progress"}, AT, Model(conn))
        assert out.model is None
    assert Model(conn).task(ALIGNMENT).state == "In progress"

    class Back(Exception):
        pass

    with pytest.raises(Back):
        with transaction(conn):
            out = edits.add_to_today(conn, data_root, fs, RIGGING, "", AT, Model(conn))
            raise Back
    assert out.model is None and RIGGING not in {a.subject for a in Model(conn).today_items()}


def test_the_sample_roots_are_twins(twins):
    """The pages test compares two roots, so they start the same."""
    (a, b) = twins
    assert files_of(a[1]) == files_of(b[1]) and files_of(a[1])
    shutil.rmtree(a[1] / "Tasks" / RIGGING, ignore_errors=True)
    assert files_of(a[1]) != files_of(b[1])
