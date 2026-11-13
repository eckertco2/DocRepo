"""The weekly review (release 5.128, the design workspace's ``docs/mods/cold-eyes-plan.md``, section 6, decisions 496 to
503): what each of its steps holds, worked out from a Model with no Qt. The Review view (``docrepo/ui/lists/review.py``)
draws each step with the code that draws its list today.

The steps (decision 497), in order:

1. **Unfiled:** the captures saved with no task.
2. **Overdue and due in the next 7 days:** the list of that name, with its key dates.
3. **Waiting on others:** that list, the longest wait first (``longest_first``): the task nothing has touched for longest.
4. **Projects due for review** (``due_for_review``): each task whose review interval has passed. An open top-level task
   has Settings' interval (weekly by default) unless it has its own; any task can have its own, 1, 2 or 4 weeks, or never
   (decision 499, ``interval``). Intervals count by the week, not the day (``is_due``), so a review a day late doesn't
   push a project past the next one.
5. **Gone quiet** (``gone_quiet``): open tasks that nothing (a capture, a status change, an edit of their notes, on them
   or under them) has touched for ``Settings.quiet_days`` days, which aren't in step 4 (decision 500), nor were in it in
   this review: marking a project reviewed isn't a touch, but it's been looked at.
6. **No next step** (``no_next_step``): open projects with no open subtask, no Due (nor a deadline in its place), no
   reminder and nothing on Today (decision 501).
7. **Done:** what the review did (``did``).

Routine tasks, meetings, plant events and Quick tasks itself are none of steps 4 to 6's business by default: they're
standing work, agendas and dates, not projects that drift.

A review is a ``Session`` kept in ``app_state`` (``KEY``): when it started, the step it's at, and when it, and the last
one, finished. No history of reviews is kept (decision 503), and what Done counts is read from docs.db since the start.
"""
from __future__ import annotations

import json
import weakref
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from docrepo import quick
from docrepo.activity import Group, Heading, Line
from docrepo.dates import WEEKDAYS, monday_of, stamp, to_date
from docrepo.lists import LISTS, key_dates_due, list_tasks
from docrepo.model import TODAY, Model, Task
from docrepo.schedule import due_of, is_open
from docrepo.summary import touched
from docrepo.views import Node, last_updated

#: Where the review in hand is kept, in docs.db's app_state.
KEY = "weekly_review"
#: A review left unfinished this many days is set aside: opening Review starts a new one.
STALE_DAYS = 6


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    #: What to do in it, in a line under the step's place.
    hint: str


STEPS = (
    Step("unfiled", "Unfiled", "File each capture to its task, or make it a task."),
    Step("due", "Overdue and due in the next 7 days", "Move each date, or close or park the task."),
    Step("waiting", "Waiting on others", "The longest waits first. Ask for an update where one is due."),
    Step("projects", "Projects due for review", "Read each one's status, what's happened since its last review and what's next, "
                                                  "then Mark reviewed (R)."),
    Step("quiet", "Gone quiet", "Nothing has touched these for {days} days. Update, park or close each one."),
    Step("nonext", "No next step", "No open subtask, no Due, no reminder and nothing on Today. Give each its next step."),
    Step("done", "Done", "What this review did."),
)
STEP_IDS = [s.id for s in STEPS]


def step_hint(step: Step, quiet_days: int) -> str:
    return step.hint.format(days=quiet_days)


# ---- intervals (decisions 498 and 499) ----
def is_project_like(m: Model, t: Task) -> bool:
    """A task the review takes as a project by default: top-level, and not routine, a meeting, a plant event or Quick tasks."""
    return not m.parents_of(t.id) and not t.recurrence and not t.meeting and not t.plant_event and not quick.is_parent(t)


def interval(m: Model, t: Task, default_weeks: int) -> int:
    """How many weeks apart a task comes up for review: its own interval, else Settings' for a project, else 0 (never)."""
    if t.review_every is not None:
        return t.review_every
    return default_weeks if is_project_like(m, t) else 0


def next_review(t: Task, weeks: int) -> date | None:
    """The Monday of the week a reviewed task comes up again, or None when it's never been reviewed (it's due now)."""
    if not t.reviewed:
        return None
    return monday_of(to_date(t.reviewed)) + timedelta(weeks=weeks)


def is_due(m: Model, t: Task, today: date, default_weeks: int) -> bool:
    """Whether an open task is due for review: it has an interval, and was never reviewed or was last reviewed that many
    weeks ago or more, counting by the week."""
    weeks = interval(m, t, default_weeks)
    if weeks <= 0 or not is_open(t):
        return False
    nxt = next_review(t, weeks)
    return nxt is None or monday_of(today) >= nxt


def tree_order(m: Model) -> dict[str, int]:
    """Each task's place in the tree, top to bottom."""
    order: dict[str, int] = {}

    def go(task_id: str) -> None:
        if task_id not in order:
            order[task_id] = len(order)
            for child in m.children_of(task_id):
                go(child)

    for t in m.top_level():
        if not t.discarded:
            go(t.id)
    return order


def due_for_review(m: Model, today: date, default_weeks: int) -> list[Task]:
    """Step 4's tasks, in tree order."""
    order = tree_order(m)
    return sorted((t for t in m.tasks.values() if is_due(m, t, today, default_weeks)), key=lambda t: order.get(t.id, 1 << 30))


def since(t: Task, today: date, weeks: int) -> str:
    """When step 4's "what's happened since its last review" starts, as a stored time to the minute: its last review, else
    its interval back from today."""
    if t.reviewed:
        return t.reviewed[:16]
    return f"{(today - timedelta(weeks=max(1, weeks))).isoformat()} 00:00"


def since_group(m: Model, lines: Iterable[Line], t: Task, start: str, order: dict[str, int]) -> Group:
    """What's happened on a task and the tasks under it since ``start``, as the Activity view groups it: a heading per task,
    the task's own lines first, each heading's lines oldest first."""
    ids = {t.id, *m.descendants_of(t.id)}
    mine = [x for x in lines if x.task in ids and x.at > start]
    heads: dict[str | None, Heading] = {}
    for line in mine:
        heads.setdefault(line.task, Heading(line.task)).lines.append(line)
    g = Group(t.title, 0, task=t.id, lines=mine)
    g.headings = sorted(heads.values(), key=lambda h: -1 if h.task == t.id else order.get(h.task or "", 1 << 30))
    return g


# ---- gone quiet and no next step (decisions 500 and 501) ----
def standing(t: Task) -> bool:
    """Routine work, a meeting, a plant event or Quick tasks itself: not something that goes quiet or lacks a next step."""
    return bool(t.recurrence or t.meeting or t.plant_event or quick.is_parent(t))


# Worked out once per model, as ``ask_update.asked_all`` is: each read goes through every capture and status log row.
_CACHE: "weakref.WeakKeyDictionary[Model, dict[str, object]]" = weakref.WeakKeyDictionary()


def _once(m: Model, name: str, make: Callable[[], object]) -> object:
    held = _CACHE.setdefault(m, {})
    if name not in held:
        held[name] = make()
    return held[name]


def updated_at(m: Model) -> dict[str, str]:
    """``views.last_updated``, once per model."""
    return _once(m, "updated", lambda: last_updated(m))  # type: ignore[return-value]


def last_touched(m: Model) -> dict[str, date]:
    """When each task, or anything under it, was last touched: a capture, a status change or an edit of its notes. Once
    per model."""
    return _once(m, "touched", lambda: _last_touched(m))  # type: ignore[return-value]


def _last_touched(m: Model) -> dict[str, date]:
    own = touched(m)
    out: dict[str, date] = {}

    def of(task_id: str) -> date | None:
        if task_id in out:
            return out[task_id]
        days = [d for d in (own.get(task_id), *(own.get(x) for x in m.descendants_of(task_id))) if d]
        out[task_id] = max(days) if days else None  # type: ignore[assignment]
        return out[task_id]

    for t in m.tasks.values():
        of(t.id)
    return out


def gone_quiet(m: Model, today: date, quiet_days: int, leave: Iterable[str] = ()) -> dict[str, int]:
    """Step 5: each open task nothing has touched for ``quiet_days`` days or more, on it or under it, and how many days,
    leaving out ``leave`` (step 4's) and standing work."""
    left = set(leave)
    last = last_touched(m)
    out: dict[str, int] = {}
    for t in m.tasks.values():
        if t.id in left or not is_open(t) or standing(t):
            continue
        day = last.get(t.id)
        n = (today - day).days if day else 0
        if n >= quiet_days:
            out[t.id] = n
    return out


def no_next_step(m: Model, today: date) -> list[Task]:
    """Step 6: open projects with no open subtask, no Due (nor a deadline in its place), no reminder and nothing on Today,
    in tree order."""
    on_today = {a.subject for a in m.today_items() if a.subject}
    order = tree_order(m)
    out = []
    for t in m.top_level():
        if not is_open(t) or standing(t) or t.reminder or t.id in on_today or due_of(t, today) is not None:
            continue
        if any(x in m.tasks and is_open(m.task(x)) for x in m.children_of(t.id)):
            continue
        out.append(t)
    return sorted(out, key=lambda t: order.get(t.id, 1 << 30))


# ---- step 3's order ----
def longest_first(m: Model, nodes: list[Node]) -> list[Node]:
    """Waiting on others with the longest wait first: at each level, the task that was last updated longest ago first,
    the top-level tasks' colour bands numbered again in the new order."""
    updated = updated_at(m)

    def waited(n: Node) -> str:
        return min((updated.get(x.id, "") for x in walk([n]) if x.match), default=updated.get(n.id, ""))

    def sort(level: list[Node]) -> list[Node]:
        for n in level:
            n.children = sort(n.children)
        return sorted(level, key=waited)

    out = sort(nodes)
    for g, top in enumerate(out):
        for x in walk([top]):
            x.group = g
    return out


def walk(nodes: list[Node]) -> Iterable[Node]:
    """Every node, top to bottom."""
    for n in nodes:
        yield n
        yield from walk(n.children)


def waited_days(m: Model, task_id: str, today: date) -> int:
    """How many days since a task was last updated, for step 3's quiet words."""
    at = updated_at(m).get(task_id)
    return (today - to_date(at)).days if at else 0


# ---- each step's count ----
def looked_at(m: Model, today: date, default_weeks: int, started: str | None) -> set[str]:
    """What step 5 leaves out: the tasks in step 4, and those marked reviewed since the review started."""
    out = {t.id for t in due_for_review(m, today, default_weeks)}
    if started:
        out |= {t.id for t in m.tasks.values() if t.reviewed and t.reviewed[:16] >= started[:16]}
    return out


def counts(m: Model, today: date, me: str | None, default_weeks: int, quiet_days: int, started: str | None = None) -> dict[str, int]:
    """How many each step holds: captures, tasks and key dates. Done holds nothing."""
    lists = {x.id: x for x in LISTS}
    due = due_for_review(m, today, default_weeks)
    return {
        "unfiled": len(m.unfiled_captures()),
        "due": len(list_tasks(m, lists["due"], today, me)) + len(key_dates_due(m, today)),
        "waiting": len(list_tasks(m, lists["waiting"], today, me)),
        "projects": len(due),
        "quiet": len(gone_quiet(m, today, quiet_days, looked_at(m, today, default_weeks, started))),
        "nonext": len(no_next_step(m, today)),
        "done": 0,
    }


def place_line(index: int, n: int) -> str:
    """Where you are: "Step 3 of 7 · Waiting on others · 8"."""
    step = STEPS[index]
    return f"Step {index + 1} of {len(STEPS)} · {step.name}" + ("" if step.id == "done" else f" · {n}")


def step_after(index: int, have: dict[str, int], back: bool = False) -> tuple[int, list[int]]:
    """The step Next (or Back) goes to: the next one that holds something, Done always, Unfiled when going back past it;
    and the empty ones it passes over, which the status line names (decision 497: an empty step says so and moves on)."""
    skipped: list[int] = []
    i = index
    while True:
        i += -1 if back else 1
        if i <= 0:
            return 0, skipped
        if i >= len(STEPS) - 1:
            return len(STEPS) - 1, skipped
        if have.get(STEPS[i].id, 0):
            return i, skipped
        skipped.append(i)


def passed_line(skipped: list[int]) -> str:
    """The status line for empty steps passed over: "Nothing waiting on others, or gone quiet."."""
    words = {"unfiled": "nothing unfiled", "due": "nothing overdue or due in the next 7 days", "waiting": "nothing waiting on others",
             "projects": "no project due for review", "quiet": "nothing gone quiet", "nonext": "no project without a next step"}
    said = [words[STEPS[i].id] for i in skipped if STEPS[i].id in words]
    if not said:
        return ""
    text = said[0] if len(said) == 1 else f"{', '.join(said[:-1])} and {said[-1]}"
    return text[:1].upper() + text[1:] + "."


# ---- the review in hand (decision 503: no history) ----
@dataclass
class Session:
    """The review in hand: when it started, its step (an index into ``STEPS``), when it finished, and when the last one
    did, for Today's line."""

    started: str | None = None
    step: int = 0
    finished: str | None = None
    last_finished: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def read_session(value: str | None) -> Session:
    """The session as kept, or a fresh one when there's none or it can't be read."""
    try:
        data = json.loads(value) if value else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    s = Session(**{k: v for k, v in data.items() if k in Session.__dataclass_fields__})
    if not isinstance(s.step, int) or not 0 <= s.step < len(STEPS):
        s.step = 0
    return s


def begin(s: Session, now: datetime) -> tuple[Session, bool]:
    """Opening Review: the review in hand carries on where it was; one that's finished, set aside (``STALE_DAYS``) or never
    started gives way to a new one at step 1. True when a new one started."""
    fresh = s.started is None or s.finished is not None or (now.date() - to_date(s.started)).days > STALE_DAYS
    if not fresh:
        return s, False
    return Session(started=stamp(now), step=0, finished=None, last_finished=s.finished or s.last_finished), True


def finish(s: Session, now: datetime) -> Session:
    """Done reached: the review finished now, and Today's line goes."""
    at = s.finished or stamp(now)
    return Session(started=s.started, step=len(STEPS) - 1, finished=at, last_finished=at)


def is_review_day(today: date, review_day: str) -> bool:
    return WEEKDAYS[today.weekday()] == review_day


def offer_today(s: Session, today: date, review_day: str) -> bool:
    """Whether Today shows its "Weekly review" line (decision 502): on the review day, until a review is finished; one
    finished in the six days before counts, so a review done a day early isn't asked for again."""
    if not is_review_day(today, review_day):
        return False
    last = s.last_finished or s.finished
    return not (last and (today - to_date(last)).days < 7)


def in_hand(s: Session, today: date) -> bool:
    """A review started and not finished, nor set aside: Today's line says Carry on rather than Start."""
    return bool(s.started and not s.finished and (today - to_date(s.started)).days <= STALE_DAYS)


# ---- Done (step 7) ----
def did(m: Model, started: str) -> list[tuple[str, int]]:
    """What happened since the review started, as Done says it: captures filed, projects reviewed, updates asked for, tasks
    closed and parked, and dates moved. Read from docs.db, so it's right after a restart; it counts any change made since
    the start, wherever it was made."""
    start = started[:16]
    filed = sum(1 for c in m.live_captures() if c.filed and c.filed[:16] >= start)
    reviewed = sum(1 for t in m.tasks.values() if t.reviewed and t.reviewed[:16] >= start and not t.discarded)
    asked = sum(1 for x in m.t_mails if x.kind == "ask" and x.opened[:16] >= start)
    since = [e for e in m.status if e.at[:16] >= start and e.task in m.tasks]
    closed = sum(1 for e in since if e.field == "State" and e.to_value == "Closed")
    parked = sum(1 for e in since if e.field == "State" and e.to_value == "Parked")
    moved = len({e.task for e in since if e.field in ("Due", "Deadline", "Start", "Reminder")})
    return [(word, n) for word, n in (("filed", filed), ("reviewed", reviewed), ("asked", asked), ("closed", closed),
                                      ("parked", parked), ("dates moved", moved)) if n]


def did_line(done: list[tuple[str, int]]) -> str:
    """"Filed 4, reviewed 6, asked 2" (decision 497's words), or that nothing changed."""
    if not done:
        return "Nothing changed during this review."
    parts = [f"dates moved on {n}" if word == "dates moved" else f"{word} {n}" for word, n in done]
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "."


def is_on_today(m: Model, task_id: str) -> bool:
    return any(a.subject == task_id and a.target == TODAY for a in m.today_items())
