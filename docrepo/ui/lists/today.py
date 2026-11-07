"""Today: its items, its Reminders and Due in the next 7 days, and their actions. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


from collections.abc import Callable
from datetime import date

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QPushButton,
)

from docrepo import db, key_dates
from docrepo.lists import reminders_due
from docrepo.dates import long_date, to_date
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.schedule import DueDate
from docrepo.ui.tree_view import Line, group_ground, state_icon, with_actions
from docrepo.views import (
    project_text,
    VIEW_IDS,
    due_cell,
    today_due_entries,
    full_path,
    since_text,
    today_groups,
)
from docrepo.ui.lists.common import (
    _cols,
    _due_css,
    _due_html,
    _row_state,
    _row_word,
    _shape,
    TODAY_MINE_KEY,
)


class TodayList:
    """Today: its items, its Reminders and Due in the next 7 days, and their actions."""


    def _today_view(self) -> None:
        """Today (mods log round 1, M0016): the day's list, items carried over first, then what's been done today."""
        m, today = self.model(), self.today()
        self._set_head("Today", VIEW_IDS["today"].note)
        # The box makes a quick task, or a note with the switch (mods log round 2, M0039).
        for kind, label in (("task", "Task"), ("note", "Note")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(self.today_kind == kind)
            b.setToolTip("The box makes a quick task, under Quick tasks" if kind == "task" else "The box adds a note to Today")
            b.clicked.connect(lambda _=False, k=kind: self.set_today_kind(k))
            self._filter_widget(b)
        self.today_note = QLineEdit()
        self.today_note.setPlaceholderText("A quick task, such as Call the vendor about seals by Fri" if self.today_kind == "task"
                                           else "A note for today, such as Sign the overtime sheets")
        self.today_note.setMinimumWidth(320)
        self.today_note.returnPressed.connect(self.add_today_item)
        self._filter_widget(self.today_note)
        self._button("Add", self.add_today_item)
        asked = m.tasks.get(self.today_ask) if self.today_ask else None
        if asked:
            self._filter_widget(QLabel(f"<b>{esc(asked.title)}</b> is done for today. Update the task too?"))
            self._button("Update…", lambda: self.answer_today("update"))
            self._button("Close the task…", lambda: self.answer_today("close"))
            self._button("No", lambda: self.answer_today(None))
        self.tree.set_columns(*_cols(*with_actions(["Item", "State", "Due"], [0, 96, 96], 220)))
        grey = group_ground()
        for name, group in today_groups(m, today):  # each group's items under its heading, which folds (release 5.24)
            head = self.tree.add_row(None, None, [f"<b>{esc(name)}</b>"], grey, selectable=False, span=True)
            for a in group:
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                # One line (decisions L1 and L3): the title, then its project and how long it's been carried, in quiet words.
                since = f"since {since_text(a.added, today)}" if a.added[:10] < today.isoformat() else ""
                context = " · ".join(x for x in (project_text(m, t.id) if t else "", a.note if t else "", since) if x)
                icon, colour = state_icon(t.state) if t else ("note", "text2")
                line = Line(t.title if t else a.note, icon=icon, icon_colour=colour, icon_tip=t.state if t else "Note", context=context)
                tip = f"{full_path(m, t.id)}\n" if t else ""
                item = self.tree.add_row(head, key, _shape([line, _row_state(t.state) if t else _row_word("Note"), _due_html(due_cell(t, today) if t else None, False)]),
                                         tip=f"{tip}Added {long_date(date.fromisoformat(a.added[:10]), today)}")
                self.tree.set_actions(item, self._today_actions(a.id, t.id if t else None))
            head.setExpanded(True)
        if not m.today_items():
            self.tree.add_row(None, None, ['<span class="sub">Nothing on Today. Select a task and press D, or type a quick task above.</span>'],
                              selectable=False, span=True)
        self._today_reminder_rows(m, today, grey)
        self._today_due_rows(m, today, grey)
        done = m.done_on(today)
        if done:
            head = self.tree.add_row(None, None, ["<b>Done today</b>"], grey, selectable=False, span=True)
            for a in done:
                t = m.tasks.get(a.subject) if a.subject else None
                line = Line(t.title if t else a.note, icon="state-cl", icon_tip="Done", context=f"Done at {(a.closed or '')[11:16]}", closed=True)
                self.tree.add_row(head, ("task", t.id) if t else None, _shape([line, _row_state(t.state) if t else _row_word("Note"), ""]))
            head.setExpanded(True)

    def _today_reminder_rows(self, m: Model, today: date, grey: QColor) -> None:
        """Reminders (item 77, decisions 236 to 238): each task whose reminder has come, under its own heading while there
        are any, with Add to Today and Clear. Like key dates' rows, it stays until it's dealt with."""
        due = reminders_due(m, today)
        if not due:
            return
        on_today = {a.subject for a in m.today_items() if a.subject}
        head = self.tree.add_row(None, None, ["<b>Reminders</b>"], grey, selectable=False, span=True)
        for t in due:
            cell = due_cell(t, today, DueDate(to_date(t.reminder), "Reminder"), use_due=False)
            line = Line(t.title, icon="reminders", icon_tip="Reminder", context=project_text(m, t.id))
            item = self.tree.add_row(head, ("task", t.id), _shape([line, _row_word("Reminder"), f'<p align="right" style="{_due_css(cell.cls)}">{esc(cell.text)}</p>']),
                                     tip=f"{full_path(m, t.id)}\n{cell.tip}")
            self.tree.set_actions(item, self._reminder_actions(t.id, t.id in on_today))
        head.setExpanded(True)

    def _reminder_actions(self, task_id: str, on_today: bool) -> list[tuple[str, Callable[[], None], str]]:
        add = [("Add to Today", lambda: self.add_to_today(task_id), "Put it on Today (D); the reminder stays until it's cleared")]
        return [*(() if on_today else add), ("Clear", lambda: self.clear_reminder(task_id, "Today"), "Clear this reminder. Its status log records it.")]

    def _today_due_rows(self, m: Model, today: date, grey: QColor) -> None:
        """Due in the next 7 days (mods log round 2, M0050): tasks overdue or due soon that aren't on Today, urgent ones first
        (release 5.97), each with Add to Today. Mine only, remembered in app_state, leaves those I neither lead nor am assigned to."""
        mine = db.get_state(self.conn, TODAY_MINE_KEY) == "1"
        box = QCheckBox("Mine only")
        box.setToolTip("Only tasks you lead or are assigned to, in Due in the next 7 days")
        box.setChecked(mine)
        box.toggled.connect(self.set_today_mine)
        self._filter_widget(box)
        head = self.tree.add_row(None, None, ["<b>Due in the next 7 days</b>" + (" <span class=\"sub\">· yours</span>" if mine else "")],
                                 grey, selectable=False, span=True)
        entries = today_due_entries(m, today, self.ctx.settings.me, mine)  # shared with the Today side panel (release 5.43)
        for t in entries:
            if isinstance(t, key_dates.Due):
                item = self.tree.add_row(head, ("task", t.task.id), self._key_date_cells(t),
                                         tip=f"A key date of {t.task.title}: {key_dates.label(t.key_date, today)}")
                self.tree.set_actions(item, self._key_date_actions(t.key_date.id))
                continue
            icon, colour = state_icon(t.state)
            # Urgent ones first, with their chip, since the Urgent view went into the tree's filter (release 5.97, decision 386).
            line = Line(t.title, icon=icon, icon_colour=colour, icon_tip=t.state, context=project_text(m, t.id),
                        chips=(("Urgent", "urgent"),) if t.urgent else ())
            item = self.tree.add_row(head, ("task", t.id), _shape([line, _row_state(t.state), _due_html(due_cell(t, today), False)]), tip=full_path(m, t.id))
            self.tree.set_actions(item, [("Add to Today", lambda i=t.id: self.add_to_today(i), "Put it on Today (D)")])
        if not entries:
            self.tree.add_row(head, None, ['<span class="sub">Nothing else is due in the next 7 days' + (" for you." if mine else ".") + "</span>"],
                              selectable=False, span=True)
        head.setExpanded(True)

    def set_today_mine(self, on: bool) -> None:
        """Mine only, on Today's Due in the next 7 days. The choice is kept in docs.db's app_state."""
        self.ctx.keep_state(TODAY_MINE_KEY, "1" if on else "0")
        self.render_list()

    def _today_actions(self, item_id: int, task_id: str | None) -> list[tuple[str, Callable[[], None], str]]:
        """A Today item's actions. A task has Edit (Edit task) and Note; a note has Edit and Make it a task (mods log round 2,
        M0040). Then Done and Remove. A quick task's row menu has Put under… too (release 5.99, decision 394)."""
        links = ((("Edit", lambda: self.edit_task(task_id), "Edit task (E). A quick task's right-click menu has Put under…, to file it"),
                  ("Note", lambda: self.open_capture(task=task_id, mode="note"), "Add a note, with files, to the task (N)")) if task_id else
                 (("Edit", lambda: self.edit_today_note(item_id), "Change the note's text"),
                  ("Make it a task", lambda: self.make_today_task(item_id), "Make it a quick task, under Quick tasks, in the note's place")))
        return [*links, ("Done", lambda: self.close_today_item(item_id, "Done"), "Take it off Today as done"),
                ("Remove", lambda: self.close_today_item(item_id, "Removed"), "Take it off Today")]
