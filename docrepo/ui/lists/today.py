"""Today: its items, its Reminders and Due in the next 7 days, and their actions. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``.

Since release 5.115 (the design workspace's ``docs/mods/today-reminders-plan.md``): Done opens an Update with no question,
and Done and Remove tell the Today side panel what they did, with Undo (decisions 420 and 421); Done today's rows have Put
back; and a file, link or email dropped on a task's row opens an Update with it (decision 419). Since release 5.116, a
reminder puts its task on Today as an item of its own, so Reminders has no heading here (decision 415), and a task's row on
Today or Due in the next 7 days has Later (decision 417)."""
from __future__ import annotations


from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QInputDialog,
    QMenu,
    QLineEdit,
    QPushButton,
)

from docrepo import ask_update, db, edits, key_dates, later
from docrepo.dates import long_date
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.ui import today_meetings
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
    _due_html,
    _row_state,
    _row_word,
    _shape,
    TODAY_MINE_KEY,
)


#: Later's tooltip (release 5.116, decision 417).
LATER_TIP = "Off Today until a later day, when its reminder puts it back"


def show_menu(menu: QMenu, at: QPoint) -> None:
    """Show a menu where it's asked for and wait for a pick: a function of its own, so the tests can pick for it, as
    PySide6 doesn't let a test stand in for ``QMenu.exec``."""
    menu.exec(at)


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
        self.tree.set_columns(*_cols(*with_actions(["Item", "State", "Due"], [0, 96, 96], 220)))
        grey = group_ground()
        today_meetings.add_group(self, grey)  # Meetings first, from the Outlook calendar (release 5.127, decision 490)
        for name, group in today_groups(m, today):  # each group's items under its heading, which folds (release 5.24)
            head = self.tree.add_row(None, None, [f"<b>{esc(name)}</b>"], grey, selectable=False, span=True)
            for a in group:
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                # One line (decisions L1 and L3): the title, then its project and how long it's been carried, in quiet words.
                since = f"since {since_text(a.added, today)}" if a.added[:10] < today.isoformat() else ""
                reminder = "reminder" if a.added_by == edits.REMINDER else ""  # a reminder put it here (decision 415)
                asked = ask_update.asked_text(m, t.id, today) if t else ""  # "asked Mon" (release 5.125, decision 485)
                context = " · ".join(x for x in (project_text(m, t.id) if t else "", a.note if t else "", reminder, asked, since) if x)
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
        self._today_due_rows(m, today, grey)
        done = m.done_on(today)
        if done:
            head = self.tree.add_row(None, None, ["<b>Done today</b>"], grey, selectable=False, span=True)
            for a in done:
                t = m.tasks.get(a.subject) if a.subject else None
                line = Line(t.title if t else a.note, icon="state-cl", icon_tip="Done", context=f"Done at {(a.closed or '')[11:16]}", closed=True)
                item = self.tree.add_row(head, ("task", t.id) if t else None, _shape([line, _row_state(t.state) if t else _row_word("Note"), ""]))
                self.tree.set_actions(item, [("Back on Today", lambda i=a.id: self.put_back_today(i), "Put it back on Today, as it was")])
            head.setExpanded(True)
        # A file, link or email dropped on a task's row (release 5.115, decision 419), as on the Today side panel.
        self.tree.take_file_drops(lambda key: isinstance(key, tuple) and key[0] == "task" and key[1] in m.tasks,
                                  lambda key, kind, paths: self.drop_on_task(key[1], kind, paths))

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
            self.tree.set_actions(item, [("Add to Today", lambda i=t.id: self.add_to_today(i), "Put it on Today (D)"),
                                         ("Later…", lambda i=t.id: self.later_menu(i), LATER_TIP)])
        if not entries:
            self.tree.add_row(head, None, ['<span class="sub">Nothing else is due in the next 7 days' + (" for you." if mine else ".") + "</span>"],
                              selectable=False, span=True)
        head.setExpanded(True)

    def set_today_mine(self, on: bool) -> None:
        """Mine only, on Today's Due in the next 7 days. The choice is kept in docs.db's app_state."""
        self.ctx.keep_state(TODAY_MINE_KEY, "1" if on else "0")
        self.render_list()

    # ---- Later (release 5.116, decision 417) ----
    def later_menu(self, task_id: str, item_id: int | None = None, at: QPoint | None = None,
                   tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Later's menu: Tomorrow, 3 days, 1 week, 2 weeks, 1 month, each with its day, and Other…."""
        today, workdays = self.today(), self._workdays()
        menu = QMenu(self)
        for key, label in later.CHOICES:
            day = later.later_day(key, today, workdays)
            menu.addAction(f"{label}\t{long_date(day, today)}", lambda _=False, d=day: self.do_later(task_id, day=d, item_id=item_id, tell=tell))
        menu.addSeparator()
        menu.addAction("Other…", lambda: self._later_other(task_id, item_id, tell))
        show_menu(menu, at or QCursor.pos())

    def _later_other(self, task_id: str, item_id: int | None, tell) -> None:
        text, ok = QInputDialog.getText(self, "Later", "Back on Today in how many workdays, or on which day? Such as 4, Fri or 15 Dec")
        if not ok or not text.strip():
            return
        day = later.read_later(text, self.today(), self._workdays())
        if day is None:
            words = f"\"{text.strip()}\" isn't a number of workdays or a day after today, such as 4, Fri or 15 Dec."
            if tell is not None:
                tell(words, None)
            self.say(words, error=True)
            return
        self.do_later(task_id, day=day, item_id=item_id, tell=tell)

    def do_later(self, task_id: str, *, day, item_id: int | None = None,
                 tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Later to ``day``: off Today, or off Due in the next 7 days, with the task's Reminder set to bring it back then.
        Undo, for ten seconds, puts back the reminder it had and its Today item."""
        old = self.model().task(task_id).reminder
        args = (self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id)
        out = self._do(lambda: edits.later(*args, day, self._now(), item_id))
        if not out:
            return

        def undo() -> None:
            back = self._do(lambda: edits.undo_later(*args, old, self._now(), item_id), self.sel)
            if back and tell is not None:
                tell(back.message, None)

        if tell is not None:
            tell(out.message, undo)
        self.say_undo(out.message, undo)

    # ---- Done, Remove and Back on Today (release 5.115, decisions 420 and 421) ----
    def close_today_item(self, item_id: int, how: str, tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Done or Remove on Today. Done on a task opens the capture window as an Update on it, its text starting "Done
        today: ", with no question (decision 421). Undo, for ten seconds, puts the item back as it was and takes away that
        Update if nothing was typed in it, as Discussed's Undo does (release 5.91). ``tell``: where to say it, with Undo, such
        as the Today side panel's line (decision 420); the status line by default."""
        item = next((a for a in self.model().agenda if a.id == item_id), None)
        if item is None:
            return
        out = self._do(lambda: edits.close_today_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, how, self._now()))
        if not out:
            return
        task = self.model().tasks.get(item.subject) if item.subject else None
        opened = ""
        if how == "Done" and task is not None and not task.discarded:
            opened = "Done today: "
            self.open_capture(task=task.id, mode="update", content=opened)
            words = f"{task.title}: done for today. Type the update and save, or close it to skip."
        else:
            words = out.message

        def undo() -> None:
            if not self._do(lambda: edits.reopen_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now()), self.sel):
                return
            kept = self.capture.drop_if_untouched(task.id, opened) if opened and task is not None and self.capture is not None else ""
            if tell is not None:
                tell(f"Back on Today.{kept}", None)
            self.say(f"Back on Today.{kept}")

        if tell is not None:
            tell(words, undo)
        self.say_undo(words, undo)

    def put_back_today(self, item_id: int, tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Back on Today, on a row of Done today (decision 420): the item is on Today again, as Undo puts it."""
        out = self._do(lambda: edits.reopen_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now()), self.sel)
        if out and tell is not None:
            tell(out.message, None)

    def drop_on_task(self, task_id: str, kind: str = "", paths: list[str] | None = None, found=None) -> None:
        """A drop on a task in the Today view or the Today side panel (decisions 407 and 419): the capture window, opened as
        an Update on the task, with what was dropped in it, as if it had been dropped there. ``found``: what DocRepo's own
        drop target took, for an email or a file only a program holds. A capture it was holding goes to Drafts first."""
        self.open_capture(task=task_id, mode="update")
        if self.capture is None:
            return
        if found is not None:
            self.capture.take_drop(found)
        elif kind:
            self.capture.dropped(kind, list(paths or []))

    def _today_actions(self, item_id: int, task_id: str | None) -> list[tuple[str, Callable[[], None], str]]:
        """A Today item's actions. A task has Edit (Edit task) and Note; a note has Edit and Make it a task (mods log round 2,
        M0040). Then Done and Remove. A quick task's row menu has Put under… too (release 5.99, decision 394)."""
        links = ((("Edit", lambda: self.edit_task(task_id), "Edit task (E). A quick task's right-click menu has Put under…, to file it"),
                  ("Note", lambda: self.open_capture(task=task_id, mode="note"), "Add a note, with files, to the task (N)"),
                  ("Later…", lambda: self.later_menu(task_id, item_id), LATER_TIP)) if task_id else
                 (("Edit", lambda: self.edit_today_note(item_id), "Change the note's text"),
                  ("Make it a task", lambda: self.make_today_task(item_id), "Make it a quick task, under Quick tasks, in the note's place")))
        return [*links, ("Done", lambda: self.close_today_item(item_id, "Done"),
                         "Take it off Today as done, and open an Update on the task" if task_id else "Take it off Today as done"),
                ("Remove", lambda: self.close_today_item(item_id, "Removed"), "Take it off Today")]
