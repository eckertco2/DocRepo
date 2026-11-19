"""The operators for collections and a task's kind (release 5.167, the design workspace's
docs/mods/collections-and-kinds-plan.md, decision 784): ``**collection,`` makes a collection, ``**task-routine,`` a task
with Recurrence (Weekly unless ``**recurrence,`` says another), and ``**task-single,``, ``**task-group,`` and
``**task-parent,`` are read as ``**task,`` without being in the ``**`` list, which stays open as a hyphen is typed."""
from __future__ import annotations

from datetime import date, datetime

from docrepo import items
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.parse import ParsePerson
from docrepo.save import CaptureDraft, save_capture

TODAY = date(2026, 10, 8)


def names_of(model: Model) -> items.Names:
    people = [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == "P001") for p in model.people.values()]
    return items.names_of(model, people)


def test_the_kinds_read(sample_conn):
    names = names_of(Model(sample_conn))
    r = items.read("**collection, Job aids.\n**task-routine, Check the seals.\n**task-routine, Walk the line. **recurrence, daily.\n"
                   "**task-single, Order gaskets.\n**task-group, Rebuild the pump.\n**task-parent, Paint the rails.", names, TODAY)
    got = [(it.kind, it.title, it.collection, it.recurrence) for it in r.items if it.kind == "task"]
    assert got == [("task", "Job aids", True, ""), ("task", "Check the seals", False, "Weekly"), ("task", "Walk the line", False, "Weekly"),
                   ("task", "Order gaskets", False, ""), ("task", "Rebuild the pump", False, ""), ("task", "Paint the rails", False, "")]


def test_the_star_list_stays_open_with_a_hyphen_and_hides_the_quiet_names(sample_conn):
    names = names_of(Model(sample_conn))
    t = items.typing("Notes **task-r")
    assert t is not None and t.sigil == "**" and t.q == "task-r"
    shown = [o.value for o in items.star_options("task", names)]
    assert "task," in shown and "task-routine," in shown and not any(x.startswith(("task-single", "task-group", "task-parent")) for x in shown)
    assert [o.value for o in items.star_options("coll", names)][0] == "collection,"
    rows = {row[0]: row for row in items.syntax_rows()}
    assert "**collection," in rows and "**task-routine," in rows and "task-single" not in rows["**task,"][1]


def test_saving_makes_a_collection_and_a_routine_task(sample_root):
    conn, root, fs = sample_root
    r = save_capture(conn, root, fs, Settings(me="P001"),
                     CaptureDraft(content="Filing.\n- **collection, Job aids\n- **task-routine, Check the seals", task="T000016", types={"note"}, files=[]),
                     datetime(2026, 10, 8, 9, 0))
    m = Model(conn)
    made = [m.task(m.captures[c].created_task) for c in r.items if m.captures[c].created_task]
    by_title = {t.title: t for t in made}
    assert by_title["Job aids"].collection and not by_title["Job aids"].recurrence
    assert by_title["Check the seals"].recurrence == "Weekly" and not by_title["Check the seals"].collection
    assert all("T000016" in m.parents_of(t.id) for t in made)
