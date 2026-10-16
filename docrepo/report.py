"""A plain-text report of what DocRepo works out from docs.db: capacity, days until due, the lists,
labels and parent chains, raw text logs and agendas.

It's for checking the task model by hand. Its sections and tables have the same
form as the mockup's ``test-vectors.md``, so the two can be compared line by line.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from docrepo import capacity
from docrepo.config import Settings
from docrepo.dates import day_diff, short
from docrepo.lists import LISTS, list_tasks
from docrepo.model import AgendaItem, Model, is_person
from docrepo.schedule import due_of, is_open


def fixed2(value: float) -> str:
    """Two decimals, rounding halves up, as the mockup's ``toFixed(2)`` does."""
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_report(conn: sqlite3.Connection, model: Model, today: date, settings: Settings, weeks: list[date], detail_week: date) -> str:
    """The report's text. ``weeks`` are the Mondays of the capacity table; ``detail_week`` is broken down by task."""
    m = model

    def tl(task_id: str) -> str:
        return f"{task_id} {m.task(task_id).title}"

    cells = capacity.week_cells(conn, sorted(set(weeks) | {detail_week}))
    unestimated, unscheduled = capacity.unplaced(m, today, settings)
    out = [f"# DocRepo report, as of {today.isoformat()}", ""]

    out += ["## Capacity: scheduled hours per person and week", "",
            f"| Person | {' | '.join(short(w, today) for w in weeks)} |", f"|---|{'|'.join('---:' for _ in weeks)}|"]
    for p in m.active_people():
        out.append(f"| {p.name} | {' | '.join(fixed2(capacity.week_total(cells, p.id, w)) for w in weeks)} |")
    out += ["", f"- Unestimated (people but no hours): {'; '.join(tl(i) for i in unestimated) or 'none'}",
            f"- Unscheduled (hours but no dates): {'; '.join(tl(i) for i in unscheduled) or 'none'}", ""]

    out += [f"## Capacity: week of {short(detail_week, today)}, by task", "", "| Person | Task | Hours |", "|---|---|---:|"]
    for p in m.active_people():
        by_task = cells.get(p.id, {}).get(detail_week, {})
        for task_id, hours in sorted(by_task.items(), key=lambda kv: -kv[1]):
            out.append(f"| {p.name} | {tl(task_id)} | {fixed2(hours)} |")
    out.append("")

    out += ["## Days until due", "", "| Task | Date used | Days |", "|---|---|---:|"]
    for t in m.tasks.values():
        if is_open(t):
            due = due_of(t, today)
            out.append(f"| {tl(t.id)} | {f'{due.label} {due.date.isoformat()}' if due else 'None'} | {day_diff(today, due.date) if due else ''} |")
    out.append("")

    out += ["## Lists", ""]
    for task_list in LISTS:
        ids = [t.id for t in list_tasks(m, task_list, today, settings.me)]
        out.append(f"- {task_list.label}: {', '.join(ids) or 'none'}")
    out.append("")

    out += ["## Labels and parent chains", "", "| Task | Labels | Chains |", "|---|---|---|"]
    for t in m.tasks.values():
        labels = ", ".join(f"_{name}_" if inherited else name for name, inherited in m.labels_of(t.id))
        chains = "; ".join(" › ".join(chain) for chain in m.chains_of(t.id))
        out.append(f"| {tl(t.id)} | {labels} | {chains} |")
    out.append("")

    out += ["## Raw text log", "", "| Task | Entries |", "|---|---|"]
    for t in m.tasks.values():
        entries = [e.capture.id if e.capture else f"V {e.version.document} {e.version.at[:10]}" for e in m.raw_log_of(t.id)]
        if entries:
            out.append(f"| {tl(t.id)} | {', '.join(entries)} |")
    out += ["", f"- Unfiled: {', '.join(c.id for c in m.unfiled_captures()) or 'none'}", ""]

    out += ["## Agendas", "", "| Target | Open items | Closed items |", "|---|---|---|"]

    def item(a: AgendaItem) -> str:
        text = a.subject if a.subject else f'note "{a.note}"'
        return text + (f" ({(a.how or '').lower()} {a.closed[:10]})" if a.closed else "")

    for target in dict.fromkeys(a.target for a in m.agenda):
        name = f"{target} {m.person_name(target)}" if is_person(target) else tl(target)
        open_items = "; ".join(item(a) for a in m.agenda if a.target == target and not a.closed) or "none"
        closed_items = "; ".join(item(a) for a in m.agenda if a.target == target and a.closed) or "none"
        out.append(f"| {name} | {open_items} | {closed_items} |")
    out.append("")
    for t in m.tasks.values():
        on = m.agendas_on(t.id)
        if on:
            out.append(f"- {tl(t.id)} is on the agenda of {', '.join(m.target_name(a.target) for a in on)}")
    out.append("")
    return "\n".join(out)
