"""The Templates view's pages (release 5.44): a template or a row, as HTML for the browse tool's detail pane.

A template's page is its top row's. A row's page says what it fills, what's under it, its starting notes, and who follows
it. Nothing here touches Qt, so the pages are tested as text. A ``tplrow:12`` link opens a row, as ``task:`` opens a task.
"""
from __future__ import annotations

from docrepo import markup
from docrepo.detail import PROGRESS_WIDTH, box, chip, esc, group, label_href, link, multiline, none_text, section, state_chip
from docrepo.dates import long_date, to_date
from docrepo.model import Model
from docrepo.pages import num
from docrepo.tasks import FIELD_NAMES, stated
from docrepo.templates import Library, Row, days_text, field_text, own_fields, plural, summary


def _hours_text(row: Row, key: str) -> str:
    """A row's hours as it states them, with what a rate comes to over its Duration: "6 h a day = 30 h each"."""
    value = stated(row, key)
    if value is None:
        return ""
    text = field_text(None, key, value)
    if isinstance(value, tuple) and row.duration:
        text += f" = {num(value[1] * row.duration)} h each"
    return text


def _people(m: Model, ids: list[str], hours: str, row: Row, role: str) -> str:
    names = ", ".join(link(f"person:{p}", m.person_name(p)) + (f' <span class="rel">{row.involvement[(role, p)]}%</span>' if (role, p) in row.involvement else "")
                      for p in ids)
    return names + (f' <span class="rel">{esc(hours)}</span>' if hours else "")


def _who(m: Model, row: Row) -> list[tuple[str, str]]:
    rows = []
    for ids, key, role, one, many, word in ((row.leads, "lead_hours", "lead", "Lead", "Leads", "Lead hours"),
                                            (row.assignees, "assignee_hours", "assignee", "Assignee", "Assignees", "Assignee hours")):
        hours = _hours_text(row, key)
        if ids:
            rows.append((many if len(ids) > 1 else one, _people(m, ids, hours, row, role)))
        elif hours:
            rows.append((word, esc(hours)))
    return rows or [("People", none_text("Left blank"))]


def _when(row: Row) -> list[tuple[str, str]]:
    rows = [("Dates", none_text("Each task's own"))]
    if row.recurrence:
        rows.append(("Repeats", esc(row.recurrence)))
    else:
        rows.append(("Duration", (esc(days_text(row.duration)) + (' <span class="rel">through weekends</span>' if row.calendar_days else ""))
                     if row.duration else none_text("Left blank")))
    return rows


def _subtasks(lib: Library, row: Row) -> str:
    under = lib.walk(row.id)[1:]
    if not under:
        return ""
    cells = "".join(f'<tr><td>{"&nbsp;" * 4 * (d - 1)}{link(f"tplrow:{x.id}", x.title, quiet="tl")}</td>'
                    f'<td align="right" class="rel">{esc(summary(x))}</td></tr>' for x, d in under)
    return (section("Subtasks", f' <span class="rel">{len(under)} under it</span>')
            + f'<table width="100%" cellspacing="0" cellpadding="3">{cells}</table>')


def _notes(row: Row) -> str:
    if not row.notes.strip():
        return ""
    return section("Starting notes", ' <span class="rel">Copied to each new task, never linked</span>') + markup.to_html(row.notes)


def _own_text(key: str, task) -> str:
    """A field a task has gone its own way on: "assignee hours 20 h", "duration 3 days", or just its name when its value won't
    fit a line."""
    name = FIELD_NAMES[key].lower()
    return f"{name} {field_text(None, key, stated(task, key))}" if key in ("lead_hours", "assignee_hours", "duration") and stated(task, key) is not None else name


def _follow(lib: Library, m: Model, row: Row) -> str:
    """Who follows a row (the design's Templates view): "9 tasks follow · 1 with its own values · 1 closed"."""
    head = section("Who follows it")
    copies = [c for c in lib.copies_of(row.id) if c.task in m.tasks and not m.task(c.task).discarded]
    if not copies:
        return head + '<p class="note">No tasks yet.</p>'
    closed = [c for c in copies if m.task(c.task).state == "Closed"]
    still = [c for c in copies if m.task(c.task).state != "Closed"]

    def own(c) -> list[str]:
        return own_fields(row, m.task(c.task), lib.links.get(c.task, set()), c.task == c.tree)

    withown = [c for c in still if own(c)]
    follow = len(still) - len(withown)
    parts = [f"{plural(follow, 'task')} follow{'s' if follow == 1 else ''}"]
    if withown:
        parts.append(f"{len(withown)} with {'its' if len(withown) == 1 else 'their'} own values")
    if closed:
        parts.append(f"{len(closed)} closed")
    lines = []
    for c in copies:
        t, gone = m.task(c.task), own(c)
        sub = f'<br><span class="rel">own: {esc(", ".join(_own_text(k, t) for k in gone))}</span>' if gone else ""
        tree = m.tasks.get(c.tree, t)  # each is named by its tree, as they all have the row's title
        lines.append(f'<tr><td>{link(f"task:{t.id}", tree.title, t.title, quiet="tl")}{sub}</td><td align="right">{state_chip(t.state)}</td></tr>')
    return head + f'<p class="note">{" · ".join(parts)}</p><table width="100%" cellspacing="0" cellpadding="3">{"".join(lines)}</table>'


def _trees(lib: Library, m: Model, template: int) -> str:
    """The trees made from a template, each with how far along it is."""
    trees = [c for c in lib.trees(template) if c.task in m.tasks and not m.task(c.task).discarded]
    if not trees:
        return section("Trees made from it") + '<p class="note">None yet.</p>'
    lines = []
    for c in trees:
        ids = [x for x in lib.in_tree(c.task) if x in m.tasks and not m.task(x).discarded]
        shut = sum(1 for x in ids if m.task(x).state == "Closed")
        bar = f'<img src="progress:{shut}:{len(ids)}" width="{PROGRESS_WIDTH}" height="4" title="{shut} of {len(ids)} closed">'
        lines.append(f'<tr><td>{link(f"task:{c.task}", m.task(c.task).title, quiet="tl")}</td><td align="right" width="{PROGRESS_WIDTH + 8}">{bar}</td>'
                     f'<td align="right" class="rel" width="96">{shut} of {len(ids)} closed</td></tr>')
    return section("Trees made from it", f' <span class="rel">{len(trees)}</span>') + f'<table width="100%" cellspacing="0" cellpadding="3">{"".join(lines)}</table>'


def _changes(lib: Library, template: int, today) -> str:
    """The template's Changes list, newest first (decision 187). Undoing one is changing the template back."""
    lines = lib.changes.get(template, [])
    if not lines:
        return section("Changes") + '<p class="note">None yet.</p>'
    cells = "".join(f'<tr><td>{esc(x.text)}<br><span class="rel">{esc(long_date(to_date(x.at[:10]), today))} · {esc(x.said())}</span></td></tr>' for x in lines)
    return section("Changes") + f'<table width="100%" cellspacing="0" cellpadding="3">{cells}</table>'


def row_page(lib: Library, m: Model, row_id: int, today) -> str:
    """A template's page (its top row's) or a row's."""
    row = lib.rows[row_id]
    template = lib.templates[row.template]
    top = template.top == row_id
    above = lib.path(row_id)[:-1]
    crumbs = f'<p class="crumbs">{" › ".join(link(f"tplrow:{x.id}", x.title, quiet="tq") for x in above)} ›</p>' if above else ""
    flags = "".join(" " + chip(name, cls) for name, cls, on in (("Urgent", "urgent", row.urgent), ("Meeting", "routine", row.meeting),
                                                                ("Plant event", "new", row.plant_event)) if on)
    labels = "".join(f' <a href="{esc(label_href(name))}">{chip(name, "lbl")}</a>' for name in row.labels)
    tags = chip("Template" if top else "Template row", "routine") + flags + labels
    desc = f'<p class="desc">{multiline(row.description)}</p>' if row.description else ""
    gone = ""
    if template.discarded:
        why = f": {esc(template.discard_reason.rstrip('.'))}" if template.discard_reason else ""
        gone = box(f"<b>Discarded</b> {esc(long_date(to_date(template.discarded[:10]), today))}{why}. It's hidden from Templates, and its tasks keep "
                   "their values. Nothing is deleted: Bring back restores it.", "warn")
    head = f'{gone}{crumbs}<h2>{esc(row.title)}</h2><p class="tags">{tags}</p>{desc}'
    return (head + group("When", _when(row)) + group("Who", _who(m, row)) + _subtasks(lib, row) + _notes(row)
            + (_trees(lib, m, template.id) + _changes(lib, template.id, today) if top else _follow(lib, m, row)))
