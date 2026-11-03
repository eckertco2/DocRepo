"""What-ifs (release 5.64; round 5's item 73, decisions 226 to 228 and 290): the plan changed on the Timeline page without
changing any task, to see what it does to the load, then applied as a deliberate last step.

A what-if is the list of things done in it (``Action``): a task taken off with everything under it, a bar moved or stretched,
a whole parent moved in whole weeks with its key dates, and a key date moved. Each keeps the tasks it touches as they were, so a
change whose task has changed since says so, and Apply leaves it out. What-ifs are kept by name in docs.db's ``app_state`` until
they're applied or deleted (decision 228), as DocRepo's own JSON, read back as data and checked.

Nothing here works out what a what-if does. ``picture`` makes its changes through ``tasks.update_task`` and ``tasks.set_key_dates``,
the calls Apply makes, inside a transaction that is always rolled back, and reads back the tasks, key dates and hours they
changed. So what's tied to a task moves with it, a Duration keeps its days and hours are spread as they would be, and what a
what-if shows is what Apply would do. Nothing outlives that transaction but what was read from it.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from docrepo import db, key_dates, tasks, timeline
from docrepo.config import Settings
from docrepo.dates import monday_of, short, to_date
from docrepo.load import Cells
from docrepo.model import KeyDate, Model, Task, load_tasks
from docrepo.schedule import is_open
from docrepo.stories import and_list

#: Where the what-ifs are kept, in ``app_state``.
KEY = "timeline_whatifs"
#: What can be done in a what-if (decision 227).
KINDS = ("off", "dates", "parent", "key")


def via(name: str) -> str:
    """What the status log says a what-if's change came from."""
    return f"What-if: {name}"


@dataclass
class Action:
    """One thing done in a what-if. ``task`` is the one it was done to. "off" parks ``off``, the task and its open subtasks; "dates"
    gives ``dates`` its task's Start and Due; "parent" moves ``dates`` and ``keys``, a parent and what's under it, ``weeks`` whole
    weeks; "key" gives one key date in ``keys`` its days. ``base`` is each task touched as it was, [Start, Due, State], and each key
    date, "k" and its ID, as [Start, End]."""

    kind: str
    task: str
    dates: dict[str, dict[str, str | None]] = field(default_factory=dict)
    keys: dict[int, tuple[str | None, str | None]] = field(default_factory=dict)
    off: list[str] = field(default_factory=list)
    weeks: int = 0
    base: dict[str, list] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"kind": self.kind, "task": self.task, "dates": self.dates, "keys": {str(k): list(v) for k, v in self.keys.items()},
                "off": self.off, "weeks": self.weeks, "base": self.base}

    @classmethod
    def from_json(cls, d: dict) -> Action | None:
        """One read back, or None when it isn't one: what's kept is checked, as everything read is."""
        try:
            kind, task = d["kind"], d["task"]
            if kind not in KINDS or not isinstance(task, str):
                return None
            dates = {str(x): {f: _day(v) for f, v in fields.items() if f in ("start", "due")} for x, fields in d.get("dates", {}).items()}
            keys = {int(k): (_day(v[0]), _day(v[1])) for k, v in d.get("keys", {}).items()}
            off = [str(x) for x in d.get("off", [])]
            base = {str(k): list(v) for k, v in d.get("base", {}).items() if isinstance(v, list)}
            return cls(kind, task, dates, keys, off, int(d.get("weeks", 0)), base)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            return None


def _day(value) -> str | None:
    """A date as kept: YYYY-MM-DD, or None."""
    if value is None:
        return None
    return date.fromisoformat(str(value)).isoformat()


@dataclass
class WhatIf:
    id: str
    name: str
    actions: list[Action] = field(default_factory=list)


# ---- kept ----
def load_all(conn: sqlite3.Connection) -> list[WhatIf]:
    """The what-ifs kept, in the order they were made. Anything that doesn't read as one is left out."""
    try:
        kept = json.loads(db.get_state(conn, KEY) or "[]")
    except ValueError:
        return []
    out = []
    for d in kept if isinstance(kept, list) else []:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not isinstance(d.get("name"), str):
            continue
        actions = [a for a in (Action.from_json(x) for x in d.get("actions", []) if isinstance(x, dict)) if a is not None]
        out.append(WhatIf(d["id"], d["name"], actions))
    return out


def save_all(conn: sqlite3.Connection, whatifs: list[WhatIf]) -> None:
    db.set_state(conn, KEY, json.dumps([{"id": w.id, "name": w.name, "actions": [a.to_json() for a in w.actions]} for w in whatifs]))


def new(whatifs: list[WhatIf], name: str = "") -> WhatIf:
    """A new, empty what-if, at the end of the list: "What-if 3" unless it's named."""
    n = 1 + max((int(w.id[1:]) for w in whatifs if w.id[1:].isdigit()), default=0)
    w = WhatIf(f"W{n}", " ".join(name.split()) or f"What-if {n}")
    whatifs.append(w)
    return w


# ---- the things done in one ----
def _as_was(t: Task) -> list:
    return [t.start, t.due, t.state]


def _key_was(kd: KeyDate) -> list:
    return [kd.start, kd.end]


def take_off(m: Model, task_id: str) -> Action:
    """A task and everything open under it taken off: Parked when it's applied, so their hours stop counting (decision 227)."""
    ids = [task_id, *(x for x in m.descendants_of(task_id) if is_open(m.task(x)))]
    return Action("off", task_id, off=ids, base={x: _as_was(m.task(x)) for x in ids})


def move(m: Model, task_id: str, start: str | None, due: str | None) -> Action:
    """A bar moved or stretched, or a task with no dates given some: Plan mode's drop, kept in the what-if."""
    return Action("dates", task_id, dates={task_id: {"start": start, "due": due}}, base={task_id: _as_was(m.task(task_id))})


def move_parent(m: Model, task_id: str, weeks: int, real: Model | None = None) -> Action:
    """A whole parent moved ``weeks`` whole weeks, so weekdays stay as they are, with its open subtasks and their key dates
    (decision 290). Routine subtasks, deadlines and done key dates stay put. Only the dates a task has move. ``m`` has the dates
    it moves from, a what-if's own when it's moved them already, and ``real`` the tasks as they are, which it keeps."""
    shift = timedelta(weeks=weeks)
    real = real or m

    def moved(value: str | None) -> str | None:
        return (to_date(value) + shift).isoformat() if value else None

    a = Action("parent", task_id, weeks=weeks)
    for x in [task_id, *m.descendants_of(task_id)]:
        t = m.task(x)
        if not is_open(t) or t.recurrence:
            continue
        dates = {f: moved(v) for f, v in (("start", t.start), ("due", t.due)) if v}
        if dates and x in real.tasks:
            a.dates[x], a.base[x] = dates, _as_was(real.task(x))
        as_is = {k.id: k for k in real.key_dates_of(x)}
        for kd in m.key_dates_of(x):
            if kd.done or kd.deadline or not (kd.start or kd.end) or kd.id not in as_is:
                continue
            a.keys[kd.id], a.base[f"k{kd.id}"] = (moved(kd.start), moved(kd.end)), _key_was(as_is[kd.id])
    return a


def move_key(m: Model, task_id: str, key_id: int, start: str | None, end: str | None) -> Action:
    """A key date moved or stretched (decision 152), kept in the what-if."""
    kd = next(k for k in m.key_dates_of(task_id) if k.id == key_id)
    return Action("key", task_id, keys={key_id: (start, end)}, base={f"k{key_id}": _key_was(kd)})


def add(w: WhatIf, a: Action) -> bool:
    """Add a thing done, the latest last. A bar or a key date moved again replaces its earlier move, keeping what it was first, so
    the review says each once. A task already taken off isn't taken off again. Returns whether anything was added."""
    if a.kind == "off" and any(x.kind == "off" and a.task in x.off for x in w.actions):
        return False
    if a.kind in ("dates", "key"):
        same = next((x for x in w.actions if x.kind == a.kind and x.task == a.task and (a.kind == "dates" or x.keys.keys() == a.keys.keys())), None)
        if same is not None:
            a.base = {**a.base, **same.base}
            w.actions.remove(same)
    w.actions.append(a)
    return True


def put_back(w: WhatIf, task_id: str) -> bool:
    """Put back a task taken off, with everything taken off with it. Returns whether there was one."""
    found = [a for a in w.actions if a.kind == "off" and task_id in a.off]
    for a in found:
        w.actions.remove(a)
    return bool(found)


def taken_off(w: WhatIf | None) -> set[str]:
    return {x for a in (w.actions if w else []) if a.kind == "off" for x in a.off}


def stale(m: Model, a: Action) -> list[str]:
    """The tasks it touches that have changed since, or are gone: a key date's task when it's the key date that changed."""
    found = {k.id: k for kds in m.key_dates.values() for k in kds}
    out = []
    for name, was in a.base.items():
        if name.startswith("k"):
            kd = found.get(int(name[1:])) if name[1:].isdigit() else None
            if kd is None or _key_was(kd) != was:
                out.append(kd.task if kd else a.task)
        elif name not in m.tasks or _as_was(m.task(name)) != was:
            out.append(name)
    return list(dict.fromkeys(out))


# ---- making them ----
@dataclass
class Done:
    """What one thing done changed when it was made: the tasks it changed, those tied to them that moved too, and why it couldn't
    be made, if it couldn't."""

    changed: list[str] = field(default_factory=list)
    followed: list[str] = field(default_factory=list)
    problem: str = ""


def run(conn: sqlite3.Connection, settings: Settings, actions: list[Action], at: datetime, said: str, skip: Collection[int] = ()) -> list[Done | None]:
    """Make the actions in order, in the caller's transaction, each logged as ``said``. Each is made in a savepoint, so one that
    can't be made, such as a task that's gone, leaves nothing behind and the rest go on. Those in ``skip`` (their places) aren't
    made, and their place in the result is None."""
    if not conn.in_transaction:
        raise RuntimeError("What-ifs are made inside a transaction, so they can be rolled back.")
    out: list[Done | None] = []
    for i, a in enumerate(actions):
        if i in skip:
            out.append(None)
            continue
        conn.execute("SAVEPOINT whatif")
        try:
            done = _make(conn, settings, a, at, said)
        except ValueError as e:  # tasks.TaskError and key_dates' are ValueErrors
            conn.execute("ROLLBACK TO whatif")
            done = Done(problem=str(e))
        conn.execute("RELEASE whatif")
        out.append(done)
    return out


def _make(conn: sqlite3.Connection, settings: Settings, a: Action, at: datetime, said: str) -> Done:
    done = Done()

    def note(logged: tasks.Logged, task_id: str) -> None:
        if logged:
            done.changed.append(task_id)
        done.followed += [f.task for f in getattr(logged, "followed", [])]

    if a.kind == "off":
        now = load_tasks(conn, a.off)
        for x in a.off:
            if x in now and is_open(now[x]):
                note(tasks.update_task(conn, settings, x, at=at, via=said, state="Parked"), x)
        return done
    # Key dates first: nothing moves a key date, and a task tied to one has then moved before it's set, so no gap counts twice.
    by_task: dict[str, dict[int, tuple[str | None, str | None]]] = {}
    for key_id, days in a.keys.items():
        r = conn.execute("SELECT task FROM task_dates WHERE id = ?", (key_id,)).fetchone()
        if r is None:
            raise tasks.TaskError("A key date in it is gone.")
        by_task.setdefault(r["task"], {})[key_id] = days
    for task_id, days in by_task.items():
        rows = tasks.key_date_rows(conn, task_id)
        for row in rows:
            if row.id in days:
                row.start, row.end = days[row.id]
        note(tasks.set_key_dates(conn, task_id, rows, at=at, via=said, settings=settings), task_id)
    for x in _tie_order(conn, list(a.dates)):
        note(tasks.update_task(conn, settings, x, at=at, via=said, dragged=True, **a.dates[x]), x)
    return done


def _tie_order(conn: sqlite3.Connection, ids: list[str]) -> list[str]:
    """The tasks, each after any it's tied to among them: a task moved first takes its followers along, and setting a follower
    afterwards to where it already is changes nothing, where setting it first would give its tie a new gap (decision 247)."""
    found = load_tasks(conn, ids)
    missing = [x for x in ids if x not in found]
    if missing:
        raise tasks.TaskError(f"There's no task {missing[0]}.")
    order: list[str] = []
    seen: set[str] = set()

    def visit(x: str, path: frozenset[str]) -> None:
        if x in seen or x in path:
            return
        for tie in found[x].ties.values():
            if tie.source in found:
                visit(tie.source, path | {x})
        seen.add(x)
        order.append(x)

    for x in ids:
        visit(x, frozenset())
    return order


# ---- what one looks like ----
@dataclass
class Picture:
    """A what-if as it would be: ``model`` has its tasks and key dates, with the real model's everything else, and ``hours`` each
    task it changed, (person, day, hours) as ``work_calendar`` would have them. ``done`` is what each thing done changed."""

    model: Model
    hours: dict[str, list[tuple[str, date, float]]]
    done: list[Done | None]
    off: set[str]

    @property
    def touched(self) -> set[str]:
        return set(self.hours)


def picture(conn: sqlite3.Connection, settings: Settings, w: WhatIf, at: datetime, real: Model) -> Picture:
    """Make the what-if's changes and read back what they changed, then roll it all back, always. The real model is the rest."""
    if conn.in_transaction:
        raise RuntimeError("A what-if can't be worked out inside another transaction: it couldn't be rolled back on its own.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        done = run(conn, settings, w.actions, at, via(w.name))
        touched = sorted({x for d in done if d for x in (*d.changed, *d.followed)})
        changed = load_tasks(conn, touched) if touched else {}
        hours: dict[str, list[tuple[str, date, float]]] = {x: [] for x in touched}
        kds: dict[str, list[KeyDate]] = {}
        for x in touched:
            for r in conn.execute("SELECT person, date, hours FROM work_calendar WHERE task = ? ORDER BY date, person", (x,)):
                hours[x].append((r["person"], to_date(r["date"]), r["hours"]))
            for r in conn.execute("SELECT * FROM task_dates WHERE task = ? ORDER BY pos, id", (x,)):
                kds.setdefault(x, []).append(KeyDate(r["id"], r["task"], r["start_day"], r["end_day"], r["description"], bool(r["plant"]),
                                                     bool(r["deadline"]), r["done"], r["pos"]))
    finally:
        conn.execute("ROLLBACK")
    model = copy.copy(real)
    model.tasks = {**real.tasks, **changed}
    model.key_dates = {**real.key_dates, **{x: kds.get(x, []) for x in touched}}
    return Picture(model, hours, done, taken_off(w))


def drawn(pic: Picture, real: Model) -> Model:
    """The model the chart draws: the what-if's, but with the tasks it takes off as they are, so they stay on the chart as rows to
    put back rather than going, as a Parked task does."""
    m = copy.copy(pic.model)
    m.tasks = {**pic.model.tasks, **{x: real.tasks[x] for x in pic.off if x in real.tasks}}
    return m


def cells(real: Cells, pic: Picture, weeks: Iterable[date]) -> Cells:
    """The load as the what-if has it: the real hours, but each task it changed with its hours as they would be."""
    wanted, touched = set(weeks), pic.touched
    out: Cells = {p: {w: {t: h for t, h in by.items() if t not in touched} for w, by in ws.items()} for p, ws in real.items()}
    for task_id, rows in pic.hours.items():
        for person, day, h in rows:
            week = monday_of(day)
            if week in wanted:
                cell = out.setdefault(person, {}).setdefault(week, {})
                cell[task_id] = cell.get(task_id, 0.0) + h
    return out


def past_deadline(real: Model, pic: Picture) -> list[str]:
    """The tasks it pushes past their deadlines, which stay put: due after the deadline in the what-if, and not on the real plan."""
    def late(t: Task) -> bool:
        return bool(t.deadline and t.due and t.due > t.deadline)

    return sorted(x for x in pic.touched - pic.off if x in pic.model.tasks and late(pic.model.task(x)) and not (x in real.tasks and late(real.task(x))))


# ---- the review ----
@dataclass
class Line:
    """One thing done, as Review and apply says it: what, what it would do, and why it's left out."""

    index: int
    title: str
    says: list[str]
    stale: list[str]
    problem: str = ""


def _span(start: str | None, due: str | None, today: date) -> str:
    return f"{short(to_date(start), today) if start else 'no start'} to {short(to_date(due), today) if due else 'no end date'}"


def _shift_words(days: int) -> str:
    later = "later" if days > 0 else "earlier"
    n = abs(days)
    if n % 7 == 0:
        return f"{n // 7} week{'' if n == 7 else 's'} {later}"
    return f"{n} day{'' if n == 1 else 's'} {later}"


def lines(real: Model, w: WhatIf, pic: Picture, today: date) -> list[Line]:
    """Each thing done, in order, as Review and apply lists it."""
    late = set(past_deadline(real, pic))
    out = []
    for i, a in enumerate(w.actions):
        t = real.tasks.get(a.task)
        title = t.title if t else a.task
        d = pic.done[i] if i < len(pic.done) else None
        own = set(a.off) | set(a.dates) | {a.task}
        says: list[str] = []
        if a.kind == "off":
            n = len(a.off) - 1
            title += f" and {n} under it" if n else ""
            says.append("Taken off: Parked, so its hours stop counting.")
        elif a.kind == "parent":
            n = len(set(a.dates) - {a.task})
            title += f" and {n} under it" if n else ""
            kd = len(a.keys)
            says.append(f"Moved {_shift_words(a.weeks * 7)}" + (f", with {kd} key date{'' if kd == 1 else 's'}" if kd else "")
                        + ". Deadlines and routine subtasks stay put.")
        elif a.kind == "dates":
            new, was = a.dates.get(a.task, {}), a.base.get(a.task, [None, None, ""])
            s, e = new.get("start"), new.get("due")
            if not was[0] and not was[1]:
                says.append(f"Given dates: {_span(s, e, today)}.")
            elif s and e and was[0] and was[1] and (to_date(s) - to_date(was[0])) == (to_date(e) - to_date(was[1])) and s != was[0]:
                says.append(f"Moved {_shift_words((to_date(s) - to_date(was[0])).days)}, now {_span(s, e, today)}.")
            else:
                says.append(f"Now {_span(s, e, today)}.")
            if t is not None and a.task in pic.model.tasks:
                before, after = timeline.hours(t, today), timeline.hours(pic.model.task(a.task), today)
                if before and after and round(before[0], 1) == round(after[0], 1):
                    says[-1] = says[-1][:-1] + ", hours kept."
        else:  # a key date
            key_id = next(iter(a.keys), None)
            kd = next((k for k in real.key_dates_of(a.task) if k.id == key_id), None)
            s, e = a.keys.get(key_id, (None, None)) if key_id is not None else (None, None)
            moved = KeyDate(key_id or 0, a.task, s, e, kd.description if kd else "")
            says.append(f"{(kd.description if kd and kd.description else 'Its key date')} now {key_dates.when_text(moved, today)}.")
        if d is not None and not d.problem:
            near = [x for x in dict.fromkeys(d.followed) if x not in own]
            if near:
                names = [pic.model.task(x).title for x in near if x in pic.model.tasks]
                says.append(f"{and_list(names) if len(names) <= 3 else f'{len(names)} tasks'} tied to it move{'s' if len(names) == 1 else ''} with it.")
            mine = [x for x in (*d.changed, *d.followed) if x in late]
            if mine:
                says.append("Past " + ("its deadline" if len(mine) == 1 else "their deadlines") + ": "
                            + "; ".join(f"{pic.model.task(x).title}, {short(to_date(pic.model.task(x).deadline), today)}" for x in dict.fromkeys(mine)) + ".")
        changed = stale(real, a)
        out.append(Line(i, title, says, [real.task(x).title if x in real.tasks else x for x in changed], d.problem if d else ""))
    return out


def out_of_date(real: Model, w: WhatIf) -> int:
    """How many of its things done have a task that has changed since."""
    return sum(1 for a in w.actions if stale(real, a))
