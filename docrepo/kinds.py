"""A task tree entry's kind (release 5.167, the design workspace's docs/mods/collections-and-kinds-plan.md, decisions 774 to 777).

The task tree holds two things: **tasks** and **collections**. A collection is a container that isn't work, a place for
notes, files, links, captures, tasks and other collections; it's stored as a flag on the task's row (``Task.collection``,
schema 30). A task is one of three kinds, worked out from what's already stored and never stored itself (decision 775),
in this order:

- **routine:** Recurrence is set, or it's an occurrence of a regular meeting (a meeting with no recurrence of its own
  under a meeting with one, as Meeting notes makes it);
- **parent:** it has at least one subtask that's a task. A discarded subtask doesn't count, a closed one does, and a
  collection under it doesn't;
- **single:** the rest.

So a single task turns into a parent the moment a task is made under it, and back when the last one is moved away.
``is_work`` is what every list of work asks where it asked ``is_open`` before (decision 780).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from docrepo.schedule import is_open

if TYPE_CHECKING:
    from docrepo.model import Model, Task

COLLECTION = "collection"
SINGLE = "single"
PARENT = "parent"
ROUTINE = "routine"
KINDS = (COLLECTION, SINGLE, PARENT, ROUTINE)
#: Each kind's name, as Task.md's Kind row, a tooltip or a filter says it (decision 776).
NAMES = {COLLECTION: "Collection", SINGLE: "Single task", PARENT: "Parent task", ROUTINE: "Routine task"}
#: The status log's field and values for a change of kind (decision 779).
LOG_FIELD = "Kind"
LOG_COLLECTION = "Collection"
LOG_TASK = "Task"


def is_collection(t: Task | None) -> bool:
    """Whether a task tree entry is a collection."""
    return bool(t is not None and getattr(t, "collection", False))


def is_work(t: Task) -> bool:
    """Open work: Not started or In progress, not discarded, and not a collection (decision 780)."""
    return is_open(t) and not is_collection(t)


def is_occurrence(m: Model, t: Task) -> bool:
    """A regular meeting's occurrence: a meeting with no recurrence of its own under a meeting with one (``save.py``'s
    Meeting notes makes each one so)."""
    if not t.meeting or t.recurrence:
        return False
    for p in m.parents_of(t.id):
        parent = m.tasks.get(p)
        if parent is not None and parent.meeting and parent.recurrence and not parent.collection:
            return True
    return False


def is_routine(m: Model, t: Task) -> bool:
    """A routine task: a task with Recurrence set, or an occurrence of a regular meeting (decision 787). Never a collection."""
    return not is_collection(t) and (bool(t.recurrence) or is_occurrence(m, t))


def has_subtasks(m: Model, t: Task) -> bool:
    """Whether a task has a subtask that's a task: not discarded, and not a collection. A closed one counts."""
    for c in m.children_of(t.id):
        child = m.tasks.get(c)
        if child is not None and not child.discarded and not child.collection:
            return True
    return False


def kind_of(m: Model, t: Task) -> str:
    """A task tree entry's kind: ``COLLECTION``, ``ROUTINE``, ``PARENT`` or ``SINGLE``, in that order (decision 775). Asks
    only the Model's own indexes, so it adds nothing to reading one."""
    if is_collection(t):
        return COLLECTION
    if is_routine(m, t):
        return ROUTINE
    if has_subtasks(m, t):
        return PARENT
    return SINGLE


def name_of(m: Model, t: Task) -> str:
    """A task tree entry's kind in words: Collection, Single task, Parent task or Routine task."""
    return NAMES[kind_of(m, t)]


def work_parents(m: Model, task_id: str) -> list[str]:
    """A task's parents as the work sees them (decision 782): a collection has no card or row of its own, so a collection
    parent stands aside for its own parents, at every level. A task under a top-level collection has none: it's top-level
    work, as a project is."""
    out: list[str] = []
    seen: set[str] = {task_id}

    def go(x: str) -> None:
        for p in m.parents_of(x):
            if p in seen or p not in m.tasks:
                continue
            seen.add(p)
            if is_collection(m.task(p)):
                go(p)
            else:
                out.append(p)

    go(task_id)
    return list(dict.fromkeys(out))
