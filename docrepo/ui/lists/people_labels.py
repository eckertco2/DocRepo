"""The People and Labels views. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations




from docrepo.detail import chip, esc
from docrepo.ui.tree_view import Line
from docrepo.views import (
    open_count,
)


class PeopleAndLabelLists:
    """The People and Labels views."""


    def _people_view(self) -> None:
        m = self.model()
        self._set_head("People", "Stored in docs.db. Tasks store a person's ID, so renaming someone changes nothing else.",
                       f"{len(m.active_people())} active")
        self._check("Show retired", self.retired["people"], lambda on: self._set_retired("people", on))
        self._button("Add person", self.add_person)
        # Group and role (mods log round 2, M0033, M0038): the aliases go under the name.
        self.tree.set_columns(["Name", "Group", "Role", "Hours a week", "Open tasks"], [0, 120, 130, 90, 76])
        for p in m.people.values():
            if p.status != "active" and not self.retired["people"]:
                continue
            chips = ((("me", "st-ip"),) if p.id == self.ctx.settings.me else ()) + ((("retired", "st-cl"),) if p.status == "retired" else ()) + \
                ((("new", "new"),) if p.added_note else ())
            count = open_count(m, lambda t, pid=p.id: pid in (*t.leads, *t.assignees))
            line = Line(p.name, chips=chips, context=", ".join(p.aliases))
            self.tree.add_row(None, ("person", p.id), [line, esc(p.group or ""), esc(p.role or ""),
                                                        f'<p align="right">{"–" if p.hours is None else f"{p.hours:g}"}</p>', f'<p align="right">{count}</p>'])

    def _labels_view(self) -> None:
        m = self.model()
        self._set_head("Labels", "Stored in docs.db. Keywords let Parse and populate suggest the label.", f"{len(m.active_labels())} active")
        self._check("Show retired", self.retired["labels"], lambda on: self._set_retired("labels", on))
        self._button("Add label", self.add_label)
        self.tree.set_columns(["Label", "Keywords", "Open tasks"], [0, 200, 76])

        def add(lb, parent_item=None):
            if lb.status != "active" and not self.retired["labels"]:
                return
            # A parent label (release 5.9, M0051) counts the open tasks with any of its sublabels.
            names = {lb.name, *m.sublabels(lb.name, active=False)}
            count = open_count(m, lambda t, ns=names: any(n in ns for n, _ in m.labels_of(t.id)))
            retired = " " + chip("retired", "st-cl") if lb.status == "retired" else ""
            item = self.tree.add_row(parent_item, ("label", lb.name), [esc(lb.name) + retired, esc(", ".join(lb.keywords)), f'<p align="right">{count}</p>'])
            for sub in (x for x in m.labels if x.parent == lb.id):
                add(sub, item)
            item.setExpanded(True)

        for lb in m.labels:
            if lb.parent is None or not any(x.id == lb.parent for x in m.labels):
                add(lb)

    def _set_retired(self, which: str, on: bool) -> None:
        self.retired[which] = on
        self.render_list()
