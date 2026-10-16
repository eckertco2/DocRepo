"""The browse tool's lists: Overdue and next 7 days, Reminders, Waiting on others, Assigned to me, Urgent,
and No dates or hours. Each holds open tasks only, soonest first.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from docrepo.dates import day_diff, to_date
from docrepo.model import Model, Task
from docrepo.schedule import due_of, is_open


@dataclass(frozen=True)
class TaskList:
    id: str
    label: str
    matches: Callable[[Task, date, str | None], bool]
    #: The date the list sorts by and shows; None means days until due.
    date_of: Callable[[Task, date], date | None] | None = None


def _due_soon(t: Task, today: date, me: str | None) -> bool:
    due = due_of(t, today)
    return not t.recurrence and due is not None and day_diff(today, due.date) <= 7


def _reminder_soon(t: Task, today: date, me: str | None) -> bool:
    return bool(t.reminder) and day_diff(today, to_date(t.reminder)) <= 7


def _unplanned(t: Task, today: date, me: str | None) -> bool:
    has_people = bool(t.leads or t.assignees)
    has_hours = bool((t.leads and t.lead_hours) or (t.assignees and t.assignee_hours))
    return has_people and (not has_hours or (not t.recurrence and not t.due and not t.deadline))


LISTS = (
    # Routine tasks are left out, or a weekly meeting would always be on it.
    TaskList("due", "Overdue and next 7 days", _due_soon),
    TaskList("reminders", "Reminders", _reminder_soon, lambda t, today: to_date(t.reminder) if t.reminder else None),
    TaskList("waiting", "Waiting on others", lambda t, today, me: bool(t.assignees) and me not in t.assignees),
    TaskList("mine", "Assigned to me", lambda t, today, me: me in t.assignees),
    TaskList("urgent", "Urgent", lambda t, today, me: t.urgent),
    TaskList("unplanned", "No dates or hours", _unplanned),
)


def list_tasks(model: Model, task_list: TaskList, today: date, me: str | None) -> list[Task]:
    """The open tasks on a list, soonest first. Tasks with no date come last, in ID order."""
    def sort_date(t: Task) -> str:
        if task_list.date_of:
            d = task_list.date_of(t, today)
        else:
            due = due_of(t, today)
            d = due.date if due else None
        return d.isoformat() if d else "9999"

    matching = [t for t in model.tasks.values() if is_open(t) and task_list.matches(t, today, me)]
    return sorted(matching, key=sort_date)
