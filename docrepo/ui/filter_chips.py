"""Filter chips: each filter in force as a chip with a cross that takes it off. The Task view's (release 5.42) and File
search's (release 5.165, decision 769: a filter typed there is seen, under the box, while the window is open).
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from docrepo import finder
from docrepo.model import Model
from docrepo.overview import SOURCE_NAMES, TYPE_NAMES
from docrepo.ui import tokens


def chips_of(f: finder.Filters, model: Model) -> list[tuple[str, Callable[[], None]]]:
    """Each filter in force, as its chip's words and what takes it off."""
    chips: list[tuple[str, Callable[[], None]]] = []
    chips += [(f"Type: {TYPE_NAMES.get(t, t)}", lambda t=t: f.types.discard(t)) for t in sorted(f.types)]
    chips += [(f"From: {SOURCE_NAMES.get(s, s)}", lambda s=s: f.sources.discard(s)) for s in sorted(f.sources)]
    chips += [(f"From: {s}", lambda s=s: f.senders.discard(s)) for s in sorted(f.senders)]
    if f.since:
        chips.append((f"Since: {f.since:%a %d %b}", lambda: setattr(f, "since", None)))
    if f.before:
        chips.append((f"Before: {f.before:%a %d %b}", lambda: setattr(f, "before", None)))
    if f.pinned:
        chips.append(("Pinned", lambda: setattr(f, "pinned", False)))
    if f.missing:
        chips.append(("Missing", lambda: setattr(f, "missing", False)))
    tg = model.tagged
    chips += [(f"Tag: {tg.by_key[k].label if k in tg.by_key else k}", lambda k=k: f.tagged.discard(k)) for k in sorted(f.tagged)]
    return chips


class FilterChips(QWidget):
    """A row of filter chips under a search box, hidden while no filter is in force. ``changed`` runs after a cross."""

    def __init__(self, changed: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.changed = changed
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(12, 0, 12, 6)
        self.row.setSpacing(4)
        self.setStyleSheet(f"QPushButton#filterChip {{ background: {tokens.colour('info_bg')}; border: none; border-radius: 4px;"
                           f" padding: 2px 10px; min-height: 18px; }}"
                           f" QPushButton#filterChip:hover {{ background: {tokens.colour('pressed')}; }}")
        self.hide()

    def show_filters(self, f: finder.Filters, model: Model) -> None:
        """Draw ``f``'s filters again."""
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w:
                w.deleteLater()
        chips = chips_of(f, model)
        for label, undo in chips:
            b = QPushButton(f"{label}  ×", objectName="filterChip")
            b.setToolTip(f"Remove {label}")
            b.clicked.connect(lambda _=False, undo=undo: (undo(), self.changed()))
            self.row.addWidget(b)
        self.row.addStretch(1)
        self.setVisible(bool(chips))

    def buttons(self) -> list[QPushButton]:
        """The chips, in order."""
        return [w for i in range(self.row.count()) if isinstance(w := self.row.itemAt(i).widget(), QPushButton)]
