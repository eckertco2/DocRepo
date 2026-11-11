"""The Documents view, and Search's results. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


import re
from datetime import date

from PySide6.QtWidgets import (
    QLabel,
)

from docrepo import search
from docrepo.dates import short
from docrepo.detail import esc
from docrepo.file_rows import GROUP_NAMES, dated_name, doc_places, place_words, type_colour, type_icon, type_name, without_title
from docrepo.overview import file_type
from docrepo.ui.look import LOOK
from docrepo.ui.tree_view import Line, group_ground, state_icon
from docrepo.ui.widgets import DropButton
from docrepo.views import (
    documents_tree,
    full_path,
)


class DocumentLists:
    """The Documents view, and Search's results."""


    def _docs_view(self) -> None:
        m = self.model()
        self._set_head("Documents", "Files DocRepo tracks, under the tasks they belong to. Originals stay where they are; their text is kept in Documents.",
                       str(sum(1 for d in m.documents if not m.only_in_discarded(d))))
        self._filter_widget(QLabel("Task"))
        picker = DropButton(full_path(m, self.doc_task) if self.doc_task in m.tasks else "Any task")
        picker.clicked.connect(lambda: self._pick_task(picker, self._set_doc_task, ("Any task", "Show every document")))
        self._filter_widget(picker)
        if self.doc_task:
            self._check("Include subtasks", self.doc_subs, self._set_doc_subs)
            self._button("Show all", lambda: self._set_doc_task(None))
        self.tree.set_columns(["Document", "Added"], [0, 76])  # no Status column: a chip says when one isn't current (release 5.114)
        nodes = documents_tree(m, self.doc_task if self.doc_task in m.tasks else None, self.doc_subs)
        # A task's row holds its documents: only its title, so nothing stands under Status and Checked but a document's.
        self._add_nodes(nodes, filtered=True, row=lambda n: (self._task_cells(n.id, n.depth, context=not n.match)[:1], full_path(m, n.id)))
        if not nodes:
            self.tree.add_row(None, None, ['<span class="sub">No documents for this task.</span>'], selectable=False, span=True)

    def _set_doc_task(self, task_id: str | None) -> None:
        self.doc_task, self.doc_subs = task_id, True
        self.render_list()

    def _set_doc_subs(self, on: bool) -> None:
        self.doc_subs = on
        self.render_list()

    def _search_view(self) -> None:
        m, today = self.model(), self.today()
        results = search.search(self.conn, m, self.query, today)
        scope, rest = search.read(self.query, m, today)  # File search's filters and the #task (release 5.121): the heading names them
        count = f"{len(results)} result{'s' if len(results) != 1 else ''}"
        if scope and scope.tasks is not None and not scope.tasks:
            self._set_head(f"Search: {self.query}", "No task matches what follows the #. Pick one from the list # opens.")
        elif scope and scope.name:
            self._set_head(f"Search {scope.name}: {rest}" if rest else f"Search {scope.name}",
                           f"{count}, only what the filters keep. " + ("Every word after them must be in the item." if rest else "Type words to narrow it."), count)
        else:
            self._set_head(f"Search: {rest if scope else self.query}", f"{count}. Every word you type must be in the item. "
                           "Narrow it as File search does, with type:pdf, from:name, after:1 sep, is:pinned or tag:, or a #task first.", count)
        if LOOK.classic:
            self.tree.set_columns(["Result"])
        else:  # a date at the row's end, as Documents has (release 5.114, decision 430)
            self.tree.set_columns(["Result", "When"], [0, 76])
        grey, group = group_ground(), ""
        places = doc_places(m) if not LOOK.classic else {}

        def say(text: str) -> None:  # a line of its own above or in place of the results
            self.tree.add_row(None, None, [f'<span class="sub">{esc(text)}</span>'] + ([] if LOOK.classic else [""]), selectable=False,
                              span=not LOOK.classic, tip=text)  # a long one is cut at the list's edge: hovering says it all

        for hint in scope.hints if scope else ():  # a filter still being typed, or one that names nothing (decision 452)
            say(hint)
        for r in results:
            if r.group != group:
                group = r.group
                n = sum(1 for x in results if x.group == group)
                head = f"<b>{esc(GROUP_NAMES.get(group, group))}</b>" + ("" if LOOK.classic else f' <span class="faint">&nbsp;{n}</span>')
                self.tree.add_row(None, None, [head] if LOOK.classic else [head, ""], grey, selectable=False, span=not LOOK.classic)
            if LOOK.classic:
                snippet = f'<br><span class="sub">{esc(r.snippet)}</span>' if r.snippet else ""
                self.tree.add_row(None, (r.kind, r.id), [f'{esc(r.title)}<br><span class="sub">{esc(r.sub)}</span>{snippet}'])
                continue
            line, when = self._result_line(m, r, places)
            self.tree.add_row(None, (r.kind, r.id), [line, f'<p align="right">{esc(when)}</p>'], tip=f"{r.title}\n{r.sub}")
        if not results and self.query.lower().startswith("search "):  # 5.108's place words went (decision 454)
            say(search.OLD_WAY)
        elif not results and scope and scope.senders and not scope.hints:
            who = " or ".join(f"“{s}”" for s in sorted(scope.senders))
            say(f"No email from {who} holds every word." if rest else f"No email's sender has {who} in it.")
        elif not results and not (scope and scope.hints):
            say("No matches.")

    def _result_line(self, m, r: search.Result, places: dict) -> tuple[Line, str]:
        """A result as a file's row is everywhere (release 5.114, decisions 427 to 430): its icon in its type's colour, its name,
        then one quiet line, where it is and the words that matched (or its description), and one short date at the end."""
        snippet = without_title(r.snippet, r.title)
        when, where, rest, title = "", "", snippet, r.title
        if r.kind == "doc" and r.id in m.documents:
            d = m.documents[r.id]
            kind = file_type(d.name, d.original)
            icon, colour, tip = type_icon(kind), type_colour(kind), type_name(kind)
            place = places.get(d.id)
            where = place_words(m, place)
            rest = snippet or d.description
            when = self._day(place.added if place else "")
        elif r.kind == "capture" and r.id in m.captures:
            c = m.captures[r.id]
            icon, colour, tip = ("type-mail", "type_mail", "Email") if c.emails or c.source == "outlook_email" else ("note", "text2", "Capture")
            where = m.task(c.task).title if c.task and c.task in m.tasks else "Unfiled"
            when = self._day(c.saved)
        elif r.group == "Saved copy":  # its name without the day it starts with, which is the row's date (decision 429)
            kind = file_type(r.title)
            icon, colour, tip = type_icon(kind), type_colour(kind), "Saved copy"
            where = m.task(r.id).title if r.id in m.tasks else ""
            day, title = dated_name(r.title)
            when = self._day(day)
        elif r.group == "Notes":
            icon, colour, tip = "note", "text2", "Notes page"
        elif r.kind == "task" and r.id in m.tasks:  # a task's state, as everywhere else (decision L7)
            t = m.task(r.id)
            (icon, colour), tip = state_icon(t.state), t.state
            where = " › ".join(m.task(x).title for x in m.chains_of(t.id)[0][:-1])  # the tasks it's under
            rest = snippet or ("" if where else t.state)
        else:
            icon, colour, tip = {"person": "person", "label": "labels", "tagged": "tagged"}.get(r.kind, "file"), "text2", r.kind.capitalize()
            rest = snippet or re.sub(rf"^{re.escape(r.id)}( · )?", "", r.sub)  # no ID (decision L4): it's in the tooltip
        second = " · ".join(x for x in (where, rest) if x)
        return Line(title, icon=icon, icon_colour=colour, icon_tip=tip, second=second or None), when

    def _day(self, at: str | None) -> str:
        """A short date ("7 Oct"), or nothing."""
        try:
            return short(date.fromisoformat(at[:10]), self.today()) if at else ""
        except ValueError:
            return ""
