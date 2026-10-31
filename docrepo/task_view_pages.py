"""The Task view's pages as HTML (release 5.34; the task overview design, sections 3 to 8): its header, the preview of
the chosen record and the list's empty states. Like ``docrepo.detail``, there's no Qt here, so the words are tested as
text; the window shows them in page views, which draw the pictures they name (``avatar:``, ``progress:``).

Links say what to do: ``task:T…`` opens that task's Task view, ``scope:T…`` narrows the window to a subtask,
``pick:kind:id`` chooses a record in the list, ``capture:C…`` opens a capture, ``do:…`` runs one of the window's
commands, and ``q:…`` searches for its words.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from docrepo import finder
from docrepo.dates import days_words, long_date, to_date
from docrepo.detail import Pages, chip, esc, label_href, link, multiline, state_chip
from docrepo.model import Model, Task
from docrepo.overview import KIND_NAMES, TYPE_NAMES, Record, ago, family

PREVIEW_LINES = 40


def marked(text: str, words: list[str], slips: tuple[str, ...] = ()) -> str:
    """Text with the words that matched in a mark (semibold on the caution tint), escaped."""
    spans = finder.highlights(text, words, slips)
    out, at = [], 0
    for a, b in spans:
        out.append(esc(text[at:a]) + f'<span class="mark">{esc(text[a:b])}</span>')
        at = b
    return "".join(out) + esc(text[at:])


# ---- the header ----
def crumbs(model: Model, task: Task) -> str:
    """The task's path, its parents as links that open their Task views; empty for a top-level task."""
    chain = next(iter(c for c in model.chains_of(task.id) if len(c) > 1), [])
    return (" › ".join(link(f"task:{x}", model.task(x).title, "Open its Task view", "tq") for x in chain[:-1]) + " ›") if chain else ""


def header(model: Model, task: Task, records: list[Record], today: date, me: str | None) -> str:
    """The task at a glance: its title, state, priority, flags and labels; the next date, the people and the subtasks'
    progress; then the current status with its age beside the latest update."""
    pages = Pages(model, today, lambda _: "", me)
    labels = "".join(f' <a href="{esc(label_href(name))}">{chip(name, "lbli" if inherited else "lbl")}</a>' for name, inherited in model.labels_of(task.id))
    tags = state_chip(task.state) + pages.priority_chip(task) + pages.markers_html(task, critical=False) + labels
    kids = [model.task(x) for x in family(model, task.id)[1:]]
    closed = sum(1 for k in kids if k.state == "Closed")
    facts = [f'<span class="fk">{"Closed" if task.state == "Closed" else "Due"}</span>&nbsp; {due_text(pages, task, today)}']
    people = list(dict.fromkeys([*task.leads, *task.assignees]))
    if people:
        facts.append('<span class="fk">Who</span>&nbsp; ' + " ".join(pages.avatar(p) for p in people))
    if kids:
        facts.append(f'<span class="fk">Subtasks</span>&nbsp; {len(kids) - closed} of {len(kids)} open '
                     f'<img src="progress:{closed}:{len(kids)}" width="72" height="4" style="vertical-align: middle">')
    head = (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td valign="middle"><h2 title="{esc(task.id)}">{esc(task.title)}</h2></td>'
            f'<td width="12"></td><td valign="middle">{tags}</td><td align="right" valign="middle" class="facts">{" &nbsp;&nbsp;&nbsp; ".join(facts)}</td></tr></table>')
    return head + status_and_latest(pages, task, records, today)


def due_text(pages: Pages, task: Task, today: date) -> str:
    if task.state == "Closed":
        return esc(long_date(to_date(task.closed or task.created), today))
    day = task.due or task.deadline
    if not day:
        return '<span class="sub">No due date</span>'
    d = to_date(day)
    count = "" if task.state == "Parked" else f" · {pages.days(d)}"
    return f'{esc(long_date(d, today))}{count}'


def status_and_latest(pages: Pages, task: Task, records: list[Record], today: date) -> str:
    """The status block (the page's one tint) beside the latest note, update or email, which picks it in the list."""
    name = "Final status" if task.state == "Closed" else "Current status"
    since = pages.status_since(task)
    when = f' <span class="rel">{esc(pages.long(since))} · {ago(since, today)}</span>' if task.current_status and since else ""
    body = multiline(task.current_status) if task.current_status else f'<span class="sub">No status yet.</span> {link("do:update", "Add one")}'
    status = f'<span class="sk">{name}</span>{when}<br>{body}'
    newest = next(iter(sorted((r for r in records if r.kind in ("note", "email") and r.type != "page"), key=lambda r: r.at, reverse=True)), None)
    if newest is None:
        return (f'<table width="100%" cellspacing="0" cellpadding="8" style="margin-top: 8px"><tr><td class="stat">{status}</td></tr></table>')
    what = f"Email from {newest.sender}" if newest.kind == "email" else "Update" if newest.type == "update" else "Note"
    where = f" · {esc(pages.m.task(newest.task).title)}" if newest.task != task.id else ""
    latest = (f'<span class="sk">Latest</span> <span class="rel">{esc(what)} · {ago(newest.at, today)}{where}</span><br>'
              f'{link(f"pick:{newest.kind}:{newest.id}", newest.title, "Show it in the list", "tl")}')
    return (f'<table width="100%" cellspacing="0" cellpadding="8" style="margin-top: 8px"><tr><td class="stat" width="60%" valign="top">{status}</td>'
            f'<td width="16"></td><td valign="top">{latest}</td></tr></table>')  # the status keeps the one tint


# ---- the preview ----
def preview(model: Model, r: Record | None, today: date, words: list[str], slips: tuple[str, ...] = (), text: str = "",
            last_opened: str | None = None, missing: bool = False) -> str:
    """The chosen record: what it is, its facts and its text (the lines that matched while searching). ``text`` is a
    file's extracted text, when it's been read."""
    if r is None:
        return '<p class="note">Choose something in the list to see it here.</p>'
    title = f'<h3 style="margin: 0">{marked(r.title, words, slips)}</h3>'
    rows: list[tuple[str, str]] = []
    if r.kind == "file":
        head = title + (f'<p class="desc">{esc(r.desc)}</p>' if r.desc else "")
        size = f" · {len(text) / 1000:.1f} k characters of text" if text else ""
        rows += [("Type", esc(TYPE_NAMES.get(r.type, "Other")) + size),
                 ("Added", f"{esc(long_date(to_date(r.at), today))} · {link(f'capture:{r.capture}', r.came) if r.capture else esc(r.came)}"),
                 ("In", link(f"scope:{r.task}", model.task(r.task).title, "Show what's in it")),
                 ("Where", esc(r.path)), ("Source", esc(r.source) + (" · a saved copy too" if r.copy and r.source != "Saved copy" else ""))]
        if last_opened:
            rows.append(("Opened", f"{esc(ago(last_opened, today))}, from DocRepo"))
        warn = ('<p class="warn">&nbsp;Not found at its path when it was last opened. Show in File Explorer opens the nearest folder '
                "that's there; relinking a moved file comes with phase 6.&nbsp;</p>" if missing else "")
        body = text_part(text, words, "Text", empty=("Links have no text: DocRepo never fetches them." if r.type == "link"
                                                    else "" if r.type == "picture" else "No text was pulled out of this file."))
        return head + warn + table(rows) + body
    if r.kind == "email":
        rows += [("Sent", esc(long_date(to_date(r.at), today)) + " " + esc(r.at[11:16])), ("In", link(f"scope:{r.task}", model.task(r.task).title)),
                 ("Files", "<br>".join(link(f"pick:file:{d}", model.documents[d].name) for d in r.attachments if d in model.documents) or none())]
        return title + f'<p class="desc">From {esc(r.sender or "an unknown sender")}</p>' + table(rows) + text_part(r.text, words, "Its text")
    if r.kind == "note":
        what = "On the notes page" if r.type == "page" else "Update" if r.type == "update" else "Note"
        rows += [("What", f"{what} · {esc(long_date(to_date(r.at), today))}" if r.type != "page" else what),
                 ("In", link(f"scope:{r.task}", model.task(r.task).title))]
        return title + table(rows) + text_part(r.text, words, "As it reads on the notes page")
    t = model.task(r.id)
    rows += [("State", esc(t.state)), ("Due", esc(long_date(to_date(t.due), today)) + f" · {esc(days_words(to_date(t.due), today))}" if t.due else none("No due date")),
             ("Who", esc(", ".join(model.person_name(p) for p in dict.fromkeys([*t.leads, *t.assignees]))) or none("No one yet"))]
    status = f'<p class="desc">{multiline(t.current_status)}</p>' if t.current_status else ""
    return title + status + table(rows)


def none(text: str = "None") -> str:
    return f'<span class="sub">{esc(text)}</span>'


def table(rows: list[tuple[str, str]]) -> str:
    cells = "".join(f'<tr><td class="dt" valign="top" width="64">{esc(k)}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table cellspacing="0" cellpadding="3" style="margin-top: 8px">{cells}</table>'


def text_part(text: str, words: list[str], label: str, empty: str = "") -> str:
    """A record's text: while searching, the lines that matched with a line either side; else its first lines."""
    if not text.strip():
        return f'<p class="note">{esc(empty)}</p>' if empty else ""
    if words:
        lines = finder.matched_lines(text, words)
        hits = sum(1 for _, _, hit in lines if hit)
        if hits:
            shown = "".join('<p class="gap">…</p>' if n < 0 else f'<p class="{"hitline" if hit else "line"}">{marked(line, words) or "&nbsp;"}</p>'
                            for n, line, hit in lines)
            return f'<p class="sec">{esc(label)} · {hits} matching line{"s" * (hits != 1)}</p>{shown}'
    lines = text.split("\n")
    more = f'<p class="note">… {len(lines) - PREVIEW_LINES} more lines</p>' if len(lines) > PREVIEW_LINES else ""
    return f'<p class="sec">{esc(label)}</p>' + "".join(f'<p class="line">{esc(line) or "&nbsp;"}</p>' for line in lines[:PREVIEW_LINES]) + more


# ---- the list's empty states ----
def nothing_found(scope_title: str, query: str, filters: int, narrowed: bool, suggestion: str | None) -> str:
    """No results: what was searched, and the ways out."""
    ways = []
    if suggestion:
        ways.append(f'Did you mean {link("q:" + quote(suggestion), suggestion)}?')
    if filters:
        ways.append(link("do:clear", f"Clear the {filters} filter{'s' * (filters != 1)}") + ' <span class="sub">Ctrl+Backspace</span>')
    if narrowed:
        ways.append(link("do:whole", "Search the whole task"))
    ways.append(link("do:everywhere", "Search all of DocRepo") + ' <span class="sub">Ctrl+Shift+F</span>')
    return (f'<p align="center"><b>Nothing in {esc(scope_title)} matches “{esc(query)}”.</b></p>'
            + "".join(f'<p align="center">{w}</p>' for w in ways))


def still_searching() -> str:
    return '<p align="center" class="note">No names or notes match. Searching the files\' text…</p>'


def nothing_clicked() -> str:
    """The preview on the Notes page tab, before anything on the page has been clicked."""
    return '<p class="note">Click a caption or a file line on the page to see it here.</p>'


def nothing_of_kind(kind: str, scope_title: str, narrowed: bool) -> str:
    out = f'<p align="center"><b>No {esc(KIND_NAMES[kind].lower())} in {esc(scope_title)}.</b></p>'
    return out + (f'<p align="center">{link("do:whole", "Show the whole task")}</p>' if narrowed else "")


def no_files(scope_title: str) -> str:
    return (f'<p align="center"><b>No files yet.</b></p><p align="center">Drop files or Outlook emails on this window to add them to '
            f'{esc(scope_title)} as a note, or press N.</p><p align="center">{link("do:note", "Add a note with files")}</p>')


def count_line(kind: str, count: int, scope_title: str, searching: bool, overview: bool, busy: bool, more_in_text: int,
               narrowed: bool = True) -> str:
    """The line beside the filters: what's shown, and the scope when it's a subtask (the whole task's name is in the
    window's title and the box)."""
    where = f" in {scope_title}" if narrowed else ""
    if not searching:
        return "Overview" + where if overview else f"{count} {KIND_NAMES[kind].lower() if kind != 'all' else 'items'}{where}"
    extra = " · searching file text…" if busy else f" · {more_in_text} more in file text" if more_in_text else ""
    return f"{count} result{'s' * (count != 1)}{where}{extra}"


def kind_label(kind: str, count: int) -> str:
    return f"{KIND_NAMES[kind]}  {count}"
