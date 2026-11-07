"""The shared matcher (release 5.103, the task pickers plan's item 117): ``items.task_matches`` is the # list's matching
(release 5.74, round 7's decisions 325 and 326), and every task picker searches with it. These are the # list's own cases
(``tests/test_hash_search.py``), asked of the matcher as a search box asks it, and of the # list as it is. Made-up names;
no Qt, so they're in the fast run."""
from __future__ import annotations

from dataclasses import dataclass, field

from docrepo import items


@dataclass
class Task:
    id: str
    title: str


@dataclass
class Tree:
    tasks: dict[str, Task]
    parents: dict[str, list[str]] = field(default_factory=dict)

    def ancestors_of(self, task_id: str) -> list[str]:
        out = []
        for p in self.parents.get(task_id, []):
            out += [p, *self.ancestors_of(p)]
        return out

    def top_level(self) -> list[Task]:
        return [t for t in self.tasks.values() if not self.parents.get(t.id)]


def tree(*titles: tuple[str, str, str | None]) -> Tree:
    return Tree({i: Task(i, t) for i, t, _ in titles}, {i: [p] for i, _, p in titles if p})


PUMPS = tree(("T1", "Installation", None), ("T2", "Pump", "T1"), ("T3", "Commissioning", None), ("T4", "Pump", "T3"),
             ("T5", "Pump station", None), ("T6", "Replace pump seals", "T1"), ("T7", "Valve", None), ("T8", "Check valve seat", "T3"))


def searched(typed: str, t: Tree = PUMPS) -> list[str]:
    """What a picker's search box lists: what's typed, stripped, through the shared matcher."""
    found = items.task_matches(typed.strip(), [(x.id, x.title) for x in t.tasks.values()], lambda i: items.ancestor_titles(t, i))
    return [t.tasks[i].title for i in found]


def hashed(typed: str, t: Tree = PUMPS) -> list[str]:
    """What the # list lists for "#" and what's typed."""
    names = items.Names([], [items.RefTask(x.id, x.title) for x in t.tasks.values()], model=t)
    return [o.label for o in items.options(items.typing("#" + typed), names)]


# The # list's pinned cases (tests/test_hash_search.py), as (typed, what it lists).
PINNED = [
    ("Pump s", ["Pump station", "Replace pump seals"]),
    ("seal pump", ["Replace pump seals"]),
    ("seat check", ["Check valve seat"]),
    ("rep sea", ["Replace pump seals"]),
    ("pump seals r", ["Replace pump seals"]),
    ("pump seals p", []),
    ("installation", ["Installation"]),
    ("Valve s", ["Check valve seat"]),
]


def test_the_matcher_gives_what_the_hash_list_pins():
    for typed, want in PINNED:
        assert searched(typed) == want == hashed(typed), typed


def test_the_path_tells_two_tasks_of_one_name_apart():
    found = items.task_matches("install pump", [(x.id, x.title) for x in PUMPS.tasks.values()], lambda i: items.ancestor_titles(PUMPS, i))
    assert found == ["T2", "T6"]
    assert items.task_matches("commis pump", [(x.id, x.title) for x in PUMPS.tasks.values()], lambda i: items.ancestor_titles(PUMPS, i)) == ["T4"]


def test_the_ranking():
    """Decision 326: the whole name, then names that start with what's typed, then names with every word, then path matches."""
    t = tree(("T1", "Seal kit", None), ("T2", "Check the seal", None), ("T3", "Seal", None), ("T4", "Gaskets", "T2"))
    assert searched("seal", t) == ["Seal", "Seal kit", "Check the seal"] == hashed("seal", t)


def test_a_search_box_strips_so_a_finished_name_still_lists():
    """In the content text, a space after a whole name closes the # list; a search box strips what's typed, so "Valve " still
    finds Valve, as "Valve" does."""
    assert hashed("Valve ") == [] and searched("Valve ") == searched("Valve") == ["Valve", "Check valve seat"]
    assert searched("Pump ") == hashed("Pump ") == ["Pump", "Pump", "Pump station", "Replace pump seals"]


def test_ids_match_and_nothing_typed_matches_everything_in_order():
    t = tree(("T000008", "Installation", None), ("T000012", "Rigging plan", "T000008"))
    assert items.task_matches("t000012", [(x.id, x.title) for x in t.tasks.values()], lambda i: items.ancestor_titles(t, i)) == ["T000012"]
    assert items.task_matches("", [("B", "Beta"), ("A", "Alpha")], lambda i: []) == ["B", "A"]


def test_a_path_isnt_read_without_words():
    asked = []
    items.task_matches("  ", [("T1", "Pump")], lambda i: asked.append(i) or [])
    assert asked == []
