"""The browse tool's lists: Overdue and next 7 days, Reminders, Waiting on others, Assigned to me, Urgent,
and No dates or hours. Each holds open tasks only, soonest first. Overdue and next 7 days also has the key dates that are
overdue or due soon (release 5.31, decision 150), each a row of its own (``key_dates_due``). Today shows the reminders
whose day has come (release 5.36, ``reminders_due``).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from docrepo import key_dates
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


def key_dates_due(model: Model, today: date, me: str | None = None, mine_only: bool = False) -> list[key_dates.Due]:
    """The key dates on Overdue and next 7 days and Today's Due in the next 7 days (release 5.31, decisions 148 and 150):
    open ones on open tasks, overdue or due (or starting) in the next 7 days, soonest first, each a row of its own. With
    Mine only, those on tasks I lead or am assigned to."""
    ids = {t.id for t in model.tasks.values() if me in t.leads or me in t.assignees} if mine_only else None
    return key_dates.due(model, today, task_ids=ids)


def reminders_due(model: Model, today: date) -> list[Task]:
    """Today's Reminders (item 77, decisions 236 and 237): open tasks whose reminder has come, today or before, the oldest
    first. A reminder still to come stays on the Reminders list until its day."""
    reminders = next(x for x in LISTS if x.id == "reminders")
    return [t for t in list_tasks(model, reminders, today, None) if to_date(t.reminder) <= today]


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
