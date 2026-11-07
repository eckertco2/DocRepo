"""One Edit and one Add to (release 5.98; the consolidation plan's item 113, decision 392): what a task's Edit menu and its
Add to menu hold, worked out once, without Qt, for every place that offers them: the task page's command bar, every task
row's right-click menu and Find files' rows. ``docrepo.ui.task_menus`` makes the menus from these entries.

- **Edit** is the same six, in the same order, everywhere (the mock's, the owner's choice of 2026-11-07): Edit task… (E),
  Move…, Put under…, Also put under…, Remove from under… and Discard…. One that doesn't apply is greyed, its tip saying
  why; with several parents, Move… and Remove from under… open a list of them. A quick task, under the built-in Quick
  tasks, has Put under…, which takes it out of Quick tasks in one step (release 5.99, decision 394).
- **Add to** is Today (D), or On Today ✓ when it's there, then the open meetings, those with open items first, then
  "An agenda…" (A, a person's or another task's), each opening an Update capture with that agenda.

An entry names what it does (``do``) and its arguments; it never holds a callable, so the same list is tested as data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from docrepo import quick
from docrepo.model import Model
from docrepo.views import meetings_for_menu

#: The two menus' names, the same on the task page's bar, a row's menu and Find files (decision 392).
EDIT = "Edit"
ADD_TO = "Add to"


@dataclass(frozen=True)
class Entry:
    """One line of a menu: its words, what it does and with what, its letter key, whether it can be picked (a greyed one's
    tip says why), and the lines of its own list, for one that opens a list. An entry with no words is a separator."""

    label: str
    do: str = ""
    args: tuple[str | None, ...] = ()
    key: str = ""
    enabled: bool = True
    tip: str = ""
    sub: tuple[Entry, ...] = ()

    @property
    def separator(self) -> bool:
        return not self.label


SEPARATOR = Entry("")


def quick_parent(m: Model, task_id: str) -> str | None:
    """The built-in Quick tasks, when the task waits under it (it's a quick task), else None."""
    return next((p for p in m.parents_of(task_id) if p in m.tasks and quick.is_parent(m.task(p))), None)


def is_quick_task(m: Model, task_id: str) -> bool:
    return quick_parent(m, task_id) is not None


def put_under(m: Model, task_id: str) -> Entry | None:
    """A quick task's Put under… (decision 394): the Edit menu's own entry, which a quick task's row offers on its own too.
    None for a task that isn't waiting under Quick tasks."""
    q = quick_parent(m, task_id)
    if q is None:
        return None
    return Entry("Put under…", "move", (q,), tip="Its real task, out of Quick tasks")


def edit_entries(m: Model, task_id: str) -> list[Entry]:
    """The Edit anatomy (decision 392): the same six in the same order whatever the task, each greyed with its reason
    when it doesn't apply, so a key or a click finds each in its place."""
    parents = m.parents_of(task_id)
    q = quick_parent(m, task_id)
    real = [p for p in parents if p != q]
    title = lambda p: m.task(p).title  # noqa: E731

    if len(real) > 1:
        move = Entry("Move…", tip="Out from under one of its parents, to a task you pick",
                     sub=tuple(Entry(f"From under {title(p)}…", "move", (p,)) for p in real))
    elif real:
        move = Entry("Move…", "move", (real[0],), tip=f"Out from under {title(real[0])}, to a task you pick")
    else:
        move = Entry("Move…", enabled=False, tip=("A quick task has no real parent to move from: Put under… gives it one." if q
                                                  else "A top-level task has no parent to move from: Put under… gives it one."))
    if q is not None:
        put = put_under(m, task_id)
    elif not parents:
        put = Entry("Put under…", "move", (None,), tip="A parent, so it's no longer a top-level task")
    else:
        put = Entry("Put under…", enabled=False, tip=f"It's under {' and '.join(title(p) for p in real)}: Move… or Also put under… changes that.")
    also = (Entry("Also put under…", "also", tip=f"A second parent; it stays under {' and '.join(title(p) for p in real)} too") if real
            else Entry("Also put under…", enabled=False, tip="Put under… gives it its first parent."))
    if len(parents) > 1:
        remove = Entry("Remove from under…", tip="One of its parents; it stays under the others",
                       sub=tuple(Entry(f"From under {title(p)}", "top", (p,)) for p in parents))
    elif parents:
        remove = Entry("Remove from under…", "top", (parents[0],), tip=f"From under {title(parents[0])}: it becomes a top-level task")
    else:
        remove = Entry("Remove from under…", enabled=False, tip="A top-level task isn't under anything.")
    return [Entry("Edit task…", "edit", key="E", tip="Every field on one page"), SEPARATOR, move, put, also, remove,  # type: ignore[list-item]
            SEPARATOR, Entry("Discard…", "discard", tip="Hide it, with a reason, if it was made by mistake. Nothing is deleted.")]


def add_to_entries(m: Model, task_id: str, today: date) -> list[Entry]:
    """The Add to menu (decision 392): Today, or On Today ✓; the open meetings with their next dates; anyone else."""
    if any(a.subject == task_id for a in m.today_items()):
        out = [Entry("On Today ✓   ·   open the Today view", "open_today")]
    else:
        out = [Entry("Today   ·   your list for today, straight away", "today", key="D")]
    out.append(SEPARATOR)
    for meeting in meetings_for_menu(m, task_id):
        when = m.meeting_when(meeting.id, today)
        out.append(Entry(f"{meeting.title}   ·   {meeting.recurrence + ', next ' + when if meeting.recurrence else 'One-off, ' + when}",
                         "agenda", (meeting.id,)))
    out.append(Entry("An agenda…", "agenda_other", key="A", tip="A person's, or another task's: picked in the capture window"))
    return out
