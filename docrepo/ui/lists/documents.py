"""The Documents view, and Search's results. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


import re

from PySide6.QtWidgets import (
    QLabel,
)

from docrepo import search
from docrepo.detail import esc
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
        self.tree.set_columns(["Document", "Status", "Checked"])
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
        m = self.model()
        results = search.search(self.conn, m, self.query)
        self._set_head(f"Search: {self.query}", f"{len(results)} result{'s' if len(results) != 1 else ''}. Every word you type must be in the item.")
        self.tree.set_columns(["Result"])
        grey, group = group_ground(), ""
        for r in results:
            if r.group != group:
                group = r.group
                self.tree.add_row(None, None, [f"<b>{esc(group)}</b>"], grey, selectable=False)
            if LOOK.classic:
                snippet = f'<br><span class="sub">{esc(r.snippet)}</span>' if r.snippet else ""
                self.tree.add_row(None, (r.kind, r.id), [f'{esc(r.title)}<br><span class="sub">{esc(r.sub)}</span>{snippet}'])
                continue
            kind = file_type(r.title) if r.kind == "doc" else ""
            name = {"task": "task", "capture": "note", "person": "person", "label": "labels", "tagged": "tagged"}.get(r.kind, f"type-{kind}" if kind not in ("", "other") else "file")
            colour, tip = "text2", r.kind.capitalize()
            if r.kind == "task" and r.id in m.tasks:  # a task's state, as everywhere else (decision L7)
                (name, colour), tip = state_icon(m.task(r.id).state), m.task(r.id).state
            sub = re.sub(rf"^{re.escape(r.id)}( · )?", "", r.sub)  # no ID (decision L4): it's in the tooltip
            line = Line(r.title, icon=name, icon_colour=colour, icon_tip=tip, context=sub if r.snippet else "", second=r.snippet or sub)
            self.tree.add_row(None, (r.kind, r.id), [line], tip=f"{r.title}\n{r.sub}")
        if not results:
            self.tree.add_row(None, None, ['<span class="sub">No matches.</span>'], selectable=False)
