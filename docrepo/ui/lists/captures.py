"""Unfiled and Discarded. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations




from docrepo.detail import chip, esc
from docrepo.ui.look import LOOK
from docrepo.ui.tree_view import Line
from docrepo.views import (
    VIEW_IDS,
    discarded_rows,
    unfiled_rows,
)
from docrepo.ui.lists.common import (
    SOURCE_ICONS,
    UNFILED_NOTE,
)


class CaptureLists:
    """Unfiled and Discarded."""


    def _unfiled_view(self) -> None:
        self._set_head("Unfiled", UNFILED_NOTE)
        self.tree.set_columns(["Capture", "Source", "Saved"] if LOOK.classic else ["Capture", "Saved"])
        rows = unfiled_rows(self.model(), self.today())
        for r in rows:  # one line: its source's icon, its title and how many documents; no ID (decision L4)
            name, colour = SOURCE_ICONS.get(r.source, ("note", "text2"))
            line = Line(r.title, icon=name, icon_colour=colour, icon_tip=r.source, context=r.sub)
            source = [chip(r.source, "st-ns")] if LOOK.classic else []
            self.tree.add_row(None, ("capture", r.id), [line, *source, f'<p align="right">{esc(r.saved)}</p>'], tip=f"{r.id} · {r.source}")
        if not rows:
            self.tree.add_row(None, None, ['<span class="sub">No unfiled captures.</span>'], selectable=False, span=True)

    def _discarded_view(self) -> None:
        """Tasks and captures discarded as made by mistake (mods log round 1, M0021), the latest first."""
        self._set_head("Discarded", VIEW_IDS["discarded"].note)
        self.tree.set_columns(["Item", "Why", "Discarded"], [0, 180, 80])
        rows = discarded_rows(self.model(), self.today(), self.templates.discarded())
        for r in rows:
            line = Line(r.title, icon={"task": "task", "capture": "note"}.get(r.kind, "templates"), icon_tip=r.kind.capitalize(), context=r.sub)
            self.tree.add_row(None, (r.kind, r.id), [line, esc(r.reason), f'<p align="right">{esc(r.when)}</p>'], tip=f"{r.id} · {r.reason}" if r.reason else r.id)
        if not rows:
            self.tree.add_row(None, None, ['<span class="sub">Nothing is discarded.</span>'], selectable=False, span=True)
