"""The view counts, faster (release 5.162, the design workspace's ``docs/mods/view-counts-plan.md``, decisions 741 to 744).

``Model.only_in_discarded`` is worked out for every document once per Model (decision 742), and ``Model.is_unfiled`` looks a
capture up among those that added an agenda item rather than going through the agenda (decision 743). ``Before`` keeps
5.155's functions as they were, and each answer is compared with theirs, on the sample data and on a made-up root with
discarded captures, saved files (current and old versions) and documents shared between live and discarded captures.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from docrepo import tagged, views
from docrepo.lists import key_dates_due, list_tasks
from docrepo.model import TODAY as TODAY_TARGET
from docrepo.model import Capture, Model
from docrepo.schedule import is_open

TODAY = date(2026, 10, 8)
GONE = "2026-10-08 16:00:00"


class Before:
    """Release 5.155's answers, as they were."""

    @staticmethod
    def only_in_discarded(m: Model, document_id: str) -> bool:
        holding = [c for c in m.captures.values() if document_id in c.document_ids]
        return bool(holding) and all(c.discarded for c in holding) and not any(f.document == document_id for f in m.copies)

    @staticmethod
    def is_unfiled(m: Model, c: Capture) -> bool:
        return not c.discarded and not m.capture_tasks(c) and not any(a.added_by == c.id for a in m.agenda)

    @staticmethod
    def unfiled_captures(m: Model) -> list[Capture]:
        return [c for c in m.captures.values() if Before.is_unfiled(m, c)]

    @staticmethod
    def view_counts(m: Model, today: date, me: str | None) -> dict[str, int]:
        counts = {
            "today": len(m.today_items()),
            "unfiled": len(Before.unfiled_captures(m)),
            "tasks": sum(1 for t in m.tasks.values() if is_open(t)),
            "people": len(m.active_people()),
            "labels": len(m.active_labels()),
            "docs": sum(1 for d in m.documents if not Before.only_in_discarded(m, d)),
            "discarded": len(m.discarded_tasks()) + len(m.discarded_captures()),
        }
        counts.update({x.id: len(list_tasks(m, x, today, me)) for x in views.VIEW_LISTS})
        counts["due"] += len(key_dates_due(m, today))
        return counts


def _capture(conn: sqlite3.Connection, cid: str, task: str | None, discarded: bool, *docs: str) -> None:
    conn.execute("INSERT INTO captures (id, saved, source, task, types, title, discarded, discard_reason) VALUES (?, ?, 'typed', ?, 'note', ?, ?, ?)",
                 (cid, "2026-10-08 15:00:00", task, f"Made-up note {cid}", GONE if discarded else None, "Made by mistake" if discarded else None))
    for pos, d in enumerate(docs, 1):
        conn.execute("INSERT INTO capture_documents (capture, document, pos, save_a_copy, extract) VALUES (?, ?, ?, 0, 1)", (cid, d, pos))


def _saved(conn: sqlite3.Connection, task: str, document: str, old: bool = False, from_capture: str | None = None) -> None:
    conn.execute("INSERT INTO saved_copies (task, name, document, from_capture, old) VALUES (?, ?, ?, ?, ?)",
                 (task, f"2026-10-08 {document}.pdf", document, from_capture, int(old)))


@pytest.fixture
def made_up(sample_conn: sqlite3.Connection) -> sqlite3.Connection:
    """The sample data, with made-up discarded captures, saved files and shared documents on top."""
    conn = sample_conn
    for n in range(101, 112):
        # Each kept as a capture's attachment (a document needs an original or a capture): which capture doesn't matter here.
        conn.execute("INSERT INTO documents (id, name, capture) VALUES (?, ?, 'C000001')", (f"D000{n}", f"Made-up file {n}.pdf"))
    _capture(conn, "C000101", "T000001", True, "D000101", "D000102", "D000107")  # discarded, on a task
    _capture(conn, "C000102", "T000008", False, "D000102", "D000108")  # live: D000102 is shared with a discarded capture
    _capture(conn, "C000103", None, True, "D000103", "D000104", "D000107")  # discarded while it was unfiled
    _capture(conn, "C000104", "T000002", True, "D000109", "D000110", "D000111")
    _capture(conn, "C000105", None, False, "D000110")  # live and unfiled: D000110 is shared too
    _capture(conn, "C000106", None, False)  # no task, but it put an item on Today: not unfiled
    _capture(conn, "C000107", None, False)  # the same, its item since closed: still not unfiled
    conn.execute("INSERT INTO agenda_items (subject, target, note, added, added_by) VALUES (NULL, ?, 'Call the vendor', ?, 'C000106')",
                 (TODAY_TARGET, GONE))
    conn.execute("INSERT INTO agenda_items (subject, target, note, added, added_by, closed, how) VALUES (NULL, ?, 'Order gaskets', ?, 'C000107', ?, 'Done')",
                 (TODAY_TARGET, GONE, GONE))
    _saved(conn, "T000001", "D000103")  # a saved file: not only in discarded captures
    _saved(conn, "T000001", "D000104", old=True)  # only an old version: still counts as a saved file, as before
    _saved(conn, "T000001", "D000106")  # saved, in no capture
    _saved(conn, "T000002", "D000111", from_capture="C000104")  # saved from the discarded capture that brought it
    # The sample's own: its unfiled email (D000003, no saved file) and the procedure with saved files (D000002) discarded.
    conn.execute("UPDATE captures SET discarded = ?, discard_reason = 'Made by mistake' WHERE id IN ('C000021', 'C000005')", (GONE,))
    conn.execute("UPDATE tasks SET discarded = ?, discard_reason = 'Typed twice' WHERE id = 'T000016'", (GONE,))
    # Two made-up tagged labels, mentioned by documents only discarded captures brought, shared ones, saved ones and live ones.
    conn.executemany("INSERT INTO tagged_labels (id, label, key, added) VALUES (?, ?, ?, ?)", [(1, "V-110", "V110", GONE), (2, "P-204A", "P204A", GONE)])
    mentions = [("document", d, 1) for d in ("D000001", "D000003", "D000101", "D000102", "D000103", "D000104", "D000109")]
    mentions += [("document", "D000107", 2), ("document", "D000110", 2), ("capture", "C000101", 2), ("capture", "C000102", 2)]
    conn.executemany("INSERT INTO tagged_mentions (kind, id, label, how, n, written) VALUES (?, ?, ?, 'label', 1, '{}')", mentions)
    conn.execute("INSERT INTO tagged_choices (kind, id, key, choice, at) VALUES ('document', 'D000102', 'V110', 'removed', ?)", (GONE,))
    conn.commit()
    return conn


@pytest.fixture(params=["sample", "made-up"])
def root(request: pytest.FixtureRequest) -> sqlite3.Connection:
    return request.getfixturevalue("sample_conn" if request.param == "sample" else "made_up")


def test_only_in_discarded_gives_the_old_answer_for_every_document(root):
    m = Model(root)
    for d in [*m.documents, "D999999", ""]:  # and IDs no capture or saved file names
        assert m.only_in_discarded(d) == Before.only_in_discarded(m, d), d


def test_which_documents_only_discarded_captures_brought(made_up):
    m = Model(made_up)
    assert sorted(d for d in m.documents if m.only_in_discarded(d)) == ["D000003", "D000101", "D000107", "D000109"]
    assert not any(Model(made_up).only_in_discarded(d) for d in ("D000102", "D000103", "D000104", "D000105", "D000106", "D000110", "D000111"))


def test_worked_out_once_per_model_and_a_new_model_sees_a_change(made_up):
    m = Model(made_up)
    assert m.only_in_discarded("D000101")
    made_up.execute("UPDATE captures SET discarded = NULL, discard_reason = NULL WHERE id = 'C000101'")  # brought back
    assert m.only_in_discarded("D000101")  # a Model is docs.db as it was read
    again = Model(made_up)
    assert not again.only_in_discarded("D000101") and not again.only_in_discarded("D000107")  # C000103 still holds D000107, discarded
    assert [d for d in again.documents if again.only_in_discarded(d)] == ["D000003", "D000109"]
    assert all(again.only_in_discarded(d) == Before.only_in_discarded(again, d) for d in again.documents)


def test_unfiled_captures_as_before(root):
    m = Model(root)
    assert [c.id for c in m.unfiled_captures()] == [c.id for c in Before.unfiled_captures(m)]
    assert all(m.is_unfiled(c) == Before.is_unfiled(m, c) for c in m.captures.values())


def test_the_made_up_unfiled_captures(made_up):
    m = Model(made_up)
    # The sample's C000022 and C000023, and C000105; C000021 is discarded, and C000024, C000106 and C000107 put an item on an agenda.
    assert [c.id for c in m.unfiled_captures()] == ["C000022", "C000023", "C000105"]


@pytest.mark.parametrize("me", ["P001", "P002", None])
@pytest.mark.parametrize("days", [0, 30])
def test_view_counts_as_before(root, me, days):
    m = Model(root)
    today = TODAY + timedelta(days=days)
    assert views.view_counts(m, today, me) == Before.view_counts(Model(root), today, me)
    assert views.view_counts(m, today, me) == Before.view_counts(m, today, me)  # asked again of the same Model


def test_the_made_up_counts(made_up):
    counts = views.view_counts(Model(made_up), TODAY, "P001")
    assert counts["docs"] == 4 + 11 - 4  # the sample's four and the eleven made up, but the four only discarded captures brought
    assert counts["discarded"] == 1 + 5  # T000016, and C000021, C000005, C000101, C000103 and C000104
    assert counts["today"] == 1  # C000106's item; C000107's is closed
    assert counts["unfiled"] == 3


def test_the_documents_view_and_the_tagged_labels_as_before(root):
    """The other callers of only_in_discarded: the Documents view's Not filed yet, and a tagged label's live items."""
    m = Model(root)
    tree = views.documents_tree(m)
    unfiled = next((n for n in tree if n.kind == "group"), None)
    want = [d for d in m.documents if not m.document_holders(d) and not Before.only_in_discarded(m, d)]
    assert ([n.id for n in unfiled.children] if unfiled else []) == want
    assert all(tagged.live(m, "document", d) == (not Before.only_in_discarded(m, d)) for d in m.documents)



def test_the_tagged_labels_counts_as_before(root, monkeypatch):
    """The Tagged labels view's Items column (``tagged.counts``) and a label's page (``tagged.uses_of``) asked
    only_in_discarded for each mention of a document."""
    m = Model(root)
    now = tagged.counts(m), [tagged.uses_of(m, lb) for lb in m.tagged.sorted_labels()]
    monkeypatch.setattr(Model, "only_in_discarded", Before.only_in_discarded)
    old = Model(root)
    assert now == (tagged.counts(old), [tagged.uses_of(old, lb) for lb in old.tagged.sorted_labels()])
