"""An agenda target's open items, and their actions. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
)

from docrepo.dates import long_date, short
from docrepo.detail import esc
from docrepo.model import TODAY, is_person
from docrepo.schedule import is_open
from docrepo.ui.tree_view import Line, group_ground, state_icon, with_actions
from docrepo.views import (
    agenda_groups,
    closed_items,
    current_target,
    full_path,
)
from docrepo.ui.look import LOOK
from docrepo.ui.lists.common import (
    _cols,
    _row_state,
    _row_word,
    _shape,
    tile_cells,
)


class AgendaList:
    """An agenda target's open items, and their actions."""


    def _agenda_view(self) -> None:
        m = self.model()
        target = current_target(m, self.target)
        self.target = target
        if not target:
            self._set_head("Agendas", "No agendas yet. Check Meeting on a task to give it an agenda, or put something on an agenda with "
                                      "Add to agenda in the capture window.")
            self.tree.set_columns(*_cols(*with_actions(["Item", "State", "Added"], [0, 96, 70], 130)))
            return
        when = m.meeting_when(target, self.today())
        when_text = f" {'Next meeting' if m.task(target).recurrence else 'Date'}: {when}." if when and when != "no date set" else ""
        self._set_head("Agendas", "Open agenda items, grouped by the work they're about. Each stays open, carrying over, until you mark it "
                                  f"Discussed or Remove it.{when_text}")
        pick = QComboBox()
        for x in [TODAY, *m.agenda_targets()]:  # Today first; picking it opens the Today view
            pick.addItem(m.target_name(x) + (" (person)" if is_person(x) else ""), x)
        pick.setCurrentIndex(max(0, pick.findData(target)))
        pick.currentIndexChanged.connect(lambda _: self.show_agenda(pick.currentData()))
        self._filter_widget(QLabel("Agenda for"))
        self._filter_widget(pick)
        self._button("Copy as Markdown", lambda: self.copy_agenda(target))
        # Release 5.131: the agenda's quick summary, its items with their tasks' dates and what's changed.
        self._button("Quick summary", lambda: self.ctx.open_summary(f"{'person' if is_person(target) else 'agenda'}:{target}"))
        meeting = m.tasks.get(target)
        if meeting and meeting.meeting and is_open(meeting):  # release 5.8
            self._button("Meeting notes", lambda: self.open_capture(task=target, meeting=True))
        self.tree.set_columns(*_cols(*with_actions(["Item", "State", "Added"], [0, 96, 70], 130)))
        grey = group_ground()
        for name, group in agenda_groups(m, target):  # each topic's items under its heading, which folds (release 5.24)
            head = self.tree.add_row(None, None, [f"<b>{esc(name)}</b>"], grey, selectable=False, span=True)
            for a in group:
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                # Two lines (decision L1): the item, then its note. Its heading already names its project.
                icon, colour = state_icon(t.state) if t else ("note", "text2")
                line = Line(t.title if t else a.note, icon=icon, icon_colour=colour, icon_tip=t.state if t else "A note, with no task",
                            second=a.note if t else "")
                if t is not None and not LOOK.classic:  # a task tile (release 5.138, decision 563): every row is on this agenda
                    line, _days = tile_cells(m, t.id, self.today(), hide=("agenda",))
                    line.second = a.note
                tip = f"{full_path(m, t.id)}\n" if t else ""
                item = self.tree.add_row(head, key, _shape([line, _row_state(t.state) if t else _row_word("Note"),
                                                            f'<p align="right">{esc(short(date.fromisoformat(a.added[:10]), self.today()))}</p>']),
                                         tip=f"{tip}Added {long_date(date.fromisoformat(a.added[:10]), self.today())}")
                self.tree.set_actions(item, self._agenda_actions(a.id))
            head.setExpanded(True)
        closed = closed_items(m, target)
        if closed:
            head = self.tree.add_row(None, None, ["<b>Closed recently</b>"], grey, selectable=False, span=True)
            for a in closed:
                t = m.tasks.get(a.subject) if a.subject else None
                line = Line(t.title if t else a.note, icon="state-cl", icon_tip=a.how, closed=True,
                            second=f"{a.how} {long_date(date.fromisoformat(a.closed[:10]), self.today())}")
                self.tree.add_row(head, ("task", t.id) if t else None,
                                  _shape([line, _row_state(t.state) if t else _row_word("Note"),
                                          f'<p align="right">{esc(short(date.fromisoformat(a.closed[:10]), self.today()))}</p>']))
            head.setExpanded(True)
        if not agenda_groups(m, target):
            self.tree.add_row(None, None, ['<span class="sub">No open agenda items.</span>'], selectable=False, span=True)

    def _agenda_actions(self, item_id: int) -> list[tuple[str, Callable[[], None], str]]:
        return [("Discussed", lambda: self.close_agenda_item(item_id, "Discussed"), "Close it as discussed, then note the outcome in an update"),
                ("Remove", lambda: self.close_agenda_item(item_id, "Removed"), "Take it off the agenda")]
