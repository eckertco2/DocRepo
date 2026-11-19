"""Today: its items, its Reminders and Due in the next 7 days, and their actions. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``.

Since release 5.115 (the design workspace's ``docs/mods/today-reminders-plan.md``): Done opens an Update with no question,
and Done and Remove tell the Today side panel what they did, with Undo (decisions 420 and 421); Done today's rows have Put
back; and a file, link or email dropped on a task's row opens an Update with it (decision 419). Since release 5.116, a
reminder puts its task on Today as an item of its own, so Reminders has no heading here (decision 415), and a task's row on
Today or Due in the next 7 days has Later (decision 417). Since release 5.148 (``docs/mods/today-order-plan.md``, decisions 643
to 648) Today's items are one list in the owner's order: dragged, moved with Alt+Up and Alt+Down, or by Move to top and Move
to bottom on the right-click menu, while a file dropped on a task's row still opens an Update. Since release 5.154
(``docs/mods/today-priority-plan.md``, decisions 688 to 692) the list is in priority bands, each under a quiet heading, the
moves keep to a band, and a task's drag opens the bins (``ui/today_bins.py``), where a drop sets its priority."""
from __future__ import annotations


from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QInputDialog,
    QMenu,
    QLineEdit,
    QPushButton,
)

from docrepo import db, edits, key_dates, later, priorities, urgency, waits
from docrepo.dates import long_date
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.ui import today_bins, today_meetings
from docrepo.ui.lists import review as review_list
from docrepo.ui.tree_view import MOVE_ROLE, RULE_ROLE, Line, group_ground, state_icon, with_actions
from docrepo.views import (
    project_text,
    VIEW_IDS,
    due_cell,
    today_due_entries,
    full_path,
    since_text,
    today_bands,
)
from docrepo.ui.lists.common import (
    _cols,
    _due_html,
    _row_state,
    _row_word,
    _shape,
    DAYS_COL,
    TODAY_MINE_KEY,
    tile_cells,
)
from docrepo.ui.look import LOOK


#: Later's tooltip (release 5.116, decision 417).
LATER_TIP = "Off Today until a later day, when its reminder puts it back"


def show_menu(menu: QMenu, at: QPoint) -> None:
    """Show a menu where it's asked for and wait for a pick: a function of its own, so the tests can pick for it, as
    PySide6 doesn't let a test stand in for ``QMenu.exec``."""
    menu.exec(at)


#: The hairline's tooltip (release 5.176, the urgency plan's decision 821).
RULE_TIP = "Above: urgent (ticked, overdue, or due within two workdays)"

class TodayList:
    """Today: its items, its Reminders and Due in the next 7 days, and their actions."""


    def _today_view(self) -> None:
        """Today (mods log round 1, M0016): the day's list in the owner's order (release 5.148), then Due in the next 7 days and
        what's been done today."""
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
        self.tree.set_columns(*_cols(*with_actions(["Item", "State", "Due"], [0, 96, 96 if LOOK.classic else DAYS_COL], 220)))
        grey = group_ground()
        review_list.today_row(self, grey)  # on the review day, "Weekly review" first (release 5.128, decision 502)
        today_meetings.add_group(self, grey)  # Meetings first, from the Outlook calendar (release 5.127, decision 490)
        # One list in the owner's order (release 5.148), in priority bands (release 5.154, decision 688), each band's urgent
        # tasks first (release 5.176, the urgency plan's decision 820): ``views.today_order``, as everything that walks it.
        workdays = self._workdays()
        bands = today_bands(m, today, workdays)
        hot = urgency.urgent_ids(m, (a for _, _, g in bands for a in g), today, workdays)
        self._today_band_of: dict[int, tuple[str, bool]] = {}
        head = self.tree.add_row(None, None, ["<b>Today</b>"], grey, selectable=False, span=True) if bands else None
        for band, name, group in bands:
            colour = today_bins.colour_of(band).name()
            self.tree.add_row(head, None, [f'<span style="color:{colour}; font-weight:600">{esc(name)}</span>&nbsp;&nbsp;<span class="sub">{len(group)}</span>'],
                              selectable=False, span=True, tip=f"{name}: drag a task onto a bin to change its priority")
            halves = {True: [a.id for a in group if a.id in hot], False: [a.id for a in group if a.id not in hot]}
            for a in group:
                self._today_band_of[a.id] = (band, a.id in hot)
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                # One line (decisions L1 and L3): the title, then its project and how long it's been carried, in quiet words.
                since = f"since {since_text(a.added, today)}" if a.added[:10] < today.isoformat() else ""
                reminder = "reminder" if a.added_by == edits.REMINDER else ""  # a reminder put it here (decision 415)
                # Its wait (release 5.139, decisions 580 and 595; "asked Mon" in 5.125): "Follow up: no reply from Dana since
                # Thu" in place of "reminder" once its follow-up day has come. While it's waiting, the tile's hourglass says so
                # (release 5.138, decision 567); the Classic look keeps "waiting on Dana · Thu".
                wait = waits.current(m, t.id) if t else None
                asked = waits.words(m, wait, today, row=True) if wait is not None and not wait.late(today) and LOOK.classic else ""
                if wait is not None and wait.late(today):
                    reminder = f"Follow up: {waits.words(m, wait, today)}"
                context = " · ".join(x for x in (project_text(m, t.id) if t else "", a.note if t else "", reminder, asked, since) if x)
                icon, colour = state_icon(t.state) if t else ("note", "text2")
                if t and not LOOK.classic:  # a tile (release 5.138): depth ticks, as Today is flat, and no sun, as every task here is on it
                    line, days = tile_cells(m, t.id, today, context=context, flat=True, hide=("today",))
                else:
                    line = Line(t.title if t else a.note, icon=icon, icon_colour=colour, icon_tip=t.state if t else "Note", context=context)
                    days = _due_html(due_cell(t, today) if t else None, False)
                tip = f"{full_path(m, t.id)}\n" if t else ""
                why = urgency.why(m, t, today, workdays) if t and not t.urgent else ""  # first in its band by its date (821)
                item = self.tree.add_row(head, key, _shape([line, _row_state(t.state) if t else _row_word("Note"), days]),
                                         tip=f"{tip}Added {long_date(date.fromisoformat(a.added[:10]), today)}"
                                             + (f"\nUrgent: {why}" if why else ""))
                self.tree.set_actions(item, self._today_actions(a.id, t.id if t else None))
                half = halves[a.id in hot]
                if a.id not in hot and halves[True] and a.id == half[0]:  # the hairline between the halves (decision 821)
                    item.setData(0, RULE_ROLE, today_bins.colour_of(band).name())
                    item.setToolTip(0, item.toolTip(0) + "\n" + RULE_TIP)
                self._movable(item, a.id, first=a.id == half[0], last=a.id == half[-1], band=name if len(bands) > 1 else "",
                              urgent=(a.id in hot) if halves[True] and halves[False] else None)
        if head is not None:
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
                self.tree.set_actions(item, [("Back on Today", lambda i=a.id: self.put_back_today(i), "Put it back on Today, at the bottom")])
            head.setExpanded(True)
        # Today's rows dragged into the owner's order, or moved by Alt+Up and Alt+Down (release 5.148, decisions 643 and 646);
        # no other row is dragged. And a file, link or email dropped on a task's row (release 5.115, decision 419), as on the
        # Today side panel: told apart by what's dragged (decision 648).
        self.tree.allow_row_moves(self._today_dropped, self._today_can_drop, self._today_step)
        self.tree.set_bins(self._today_bins_for,  # release 5.154, decision 690; a bin's two parts since release 5.176 (822)
                           lambda key, target: self.bin_today(key[1], target[0], urgent=target[1]))
        for row in self.tree.items():
            if row.data(0, MOVE_ROLE) is None:
                row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
        self.tree.take_file_drops(lambda key: isinstance(key, tuple) and key[0] == "task" and key[1] in m.tasks,
                                  lambda key, kind, paths: self.drop_on_task(key[1], kind, paths))

    # ---- Today in the owner's order (release 5.148, decisions 643 to 646) ----
    def _movable(self, item, item_id: int, first: bool, last: bool, band: str = "", urgent: bool | None = None) -> None:
        """A Today item's row: dragged by its number, landed on only before or after (Qt's line between rows), with Move to
        top and Move to bottom on its right-click menu, each where it would move it: in its band since release 5.154
        (decision 689), ``band`` naming it when Today has more than one, and since release 5.176 in its half (decision 820),
        ``urgent`` saying which when the band has both."""
        item.setData(0, MOVE_ROLE, ("today", item_id))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        where = f"in {band}" if band else "on Today"
        if urgent is not None:
            where = f"among {'the urgent tasks' if urgent else 'the tasks after the urgent ones'} {where}"
        lines = [] if first else [("Move to top", lambda: self.move_today(item_id, to="top"), f"First {where}. Alt+Up moves it one place")]
        if not last:
            lines.append(("Move to bottom", lambda: self.move_today(item_id, to="bottom"), f"Last {where}. Alt+Down moves it one place"))
        self.tree.set_menu_lines(item, lines)

    def _today_can_drop(self, key: object, target: object, where: str) -> bool:
        """A Today item lands just before or after another (decision 643), never in one, and nothing else moves here; since
        release 5.154 only beside an item of its own band (decision 689), and since release 5.176 of its own half (820)."""
        if not (isinstance(key, tuple) and isinstance(target, tuple) and key[0] == target[0] == "today" and key != target
                and where in ("before", "after")):
            return False
        bands = getattr(self, "_today_band_of", {})
        return bands.get(key[1]) == bands.get(target[1])

    # ---- Today's bins (release 5.154, decisions 690 and 691) ----
    def _today_bins_for(self, key: object) -> tuple[str, dict[str, int], bool] | None:
        """What a row's drag opens the bins with: its band, each band's count and whether it's in its band's urgent half
        (release 5.176, decision 822), for a task on Today; None for a note (decision 692) or anything else."""
        if not (isinstance(key, tuple) and key[0] == "today"):
            return None
        m = self.model()
        items = m.today_items()
        a = next((x for x in items if x.id == key[1]), None)
        if a is None or not a.subject or a.subject not in m.tasks:
            return None
        return m.today_band(a), today_bins.counts_of(m, items), urgency.is_urgent(m, a.subject, self._now().date(), self._workdays())

    def bin_today(self, item_id: int, band: str, tell: Callable[[str, Callable[[], None] | None], None] | None = None,
                  follow: bool = True, urgent: bool | None = None) -> bool:
        """A Today task dropped on a bin: its priority set, and its place the end of its new band (decision 691). It stays
        selected. ``tell``: the Today side panel's line. True if it changed.

        Since release 5.159 (the design workspace's ``docs/mods/bin-drop-speed-plan.md``, decision 730) the drop is given the
        shared Model, as docs.db is now, and the one it reads after is kept; no view's count follows a priority, so the views
        pane isn't drawn again (``_do``'s ``counts``); only an open Find files window of the task, or of a task above it,
        reads its records again. ``follow`` False (the side panel's drop) leaves the Today view's selection as it is, rather
        than move it to the task and draw its page.

        Since release 5.176 (the urgency plan's decision 822) ``urgent`` is the bin's part: True ticks Urgent, False unticks
        it, None keeps it; and what it did is said with Undo for ten seconds, which puts the priority, the tick and Today's
        order back."""
        m = self.model()
        a = next((x for x in m.today_items() if x.id == item_id), None)
        reach = priorities.reach(m, a.subject) if a is not None and a.subject else set()
        out = self._do(lambda: edits.today_bin(self.conn, self.ctx.data_root, self.ctx.fs, item_id, band, self._now(), m, urgent=urgent,
                                               settings=self.ctx.settings, workdays=self._workdays()),
                       self.sel, counts=False, reach=reach)
        if not out or not out.message:
            return False
        if follow:
            self._keep_today_row(item_id)
        undo = (lambda u=out.undo: self.undo_bin_today(u)) if out.undo is not None else None
        if tell is not None:
            tell(out.message, undo)
        elif undo is not None:
            self.say_undo(out.message, undo)
        return True

    def undo_bin_today(self, undo: edits.BinUndo) -> None:
        """Undo a bin's drop (decision 822): the priority, the Urgent tick and Today's order as they were."""
        self._do(lambda: edits.undo_today_bin(self.conn, self.ctx.data_root, self.ctx.fs, undo, self._now(), settings=self.ctx.settings,
                                              model=self.model()), self.sel, counts=False, reach=priorities.reach(self.model(), undo.task))
        self.ctx.today_changed()

    def _keep_today_row(self, item_id: int) -> None:
        """The Today view's row of an item that moved stays the current one, so Alt+Up can go on (decisions 646 and 691)."""
        if self.view == "today" and self.isVisible():
            row = next((r for r in self.tree.items() if r.data(0, MOVE_ROLE) == ("today", item_id)), None)
            if row is not None and self.tree.currentItem() is not row:
                self.tree.setCurrentItem(row)

    def _today_dropped(self, key: tuple[str, int], target: tuple[str, int], where: str) -> None:
        self.move_today(key[1], beside=(target[1], where))

    def _today_step(self, key: object, step: int) -> None:
        """Alt+Up and Alt+Down on a Today item: one place up or down (decision 646)."""
        if isinstance(key, tuple) and key[0] == "today":
            self.move_today(key[1], to="up" if step < 0 else "down")

    def move_today(self, item_id: int, *, to: str | None = None, beside: tuple[int, str] | None = None,
                   tell: Callable[[str, Callable[[], None] | None], None] | None = None, follow: bool = True) -> bool:
        """Move a Today item (decisions 643 and 646): to the top, the bottom, up or down, or beside another as a drag drops it.
        It stays selected, so Alt+Up can go on. No Undo: it's moved back the same way. ``tell``: the Today side panel's line.
        True if it moved. Since release 5.159 a move, which changes no view's count and no Find files window, draws neither
        again, and ``follow`` False (the side panel's move) leaves the Today view's selection as it is."""
        out = self._do(lambda: edits.move_today_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now(), to=to, beside=beside,
                                                     model=self.model(), workdays=self._workdays()),
                       self.sel, counts=False, reach=())
        if not out:
            return False
        if follow:
            self._keep_today_row(item_id)
        if tell is not None and out.message:
            tell(out.message, None)
        return True

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
            # Urgent ones first, with their chip, since the Urgent view went into the tree's filter (release 5.97, decision 386);
            # since 5.138 a tile, whose flag says Urgent (decision 569).
            if LOOK.classic:
                line = Line(t.title, icon=icon, icon_colour=colour, icon_tip=t.state, context=project_text(m, t.id),
                            chips=(("Urgent", "urgent"),) if t.urgent else ())
                days = _due_html(due_cell(t, today), False)
            else:
                line, days = tile_cells(m, t.id, today, context=project_text(m, t.id), flat=True, hide=("today",))
            item = self.tree.add_row(head, ("task", t.id), _shape([line, _row_state(t.state), days]), tip=full_path(m, t.id))
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
        out = self._do(lambda: edits.later(*args, day, self._now(), item_id, self.model()))
        if not out:
            return

        def undo() -> None:
            back = self._do(lambda: edits.undo_later(*args, old, self._now(), item_id, self.model()), self.sel)
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
        out = self._do(lambda: edits.close_today_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, how, self._now(), self.model()))
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
            if not self._do(lambda: edits.reopen_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now(), self.model()), self.sel):
                return
            kept = self.capture.drop_if_untouched(task.id, opened) if opened and task is not None and self.capture is not None else ""
            if tell is not None:
                tell(f"Back on Today.{kept}", None)
            self.say(f"Back on Today.{kept}")

        if tell is not None:
            tell(words, undo)
        self.say_undo(words, undo)

    def put_back_today(self, item_id: int, tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Back on Today, on a row of Done today (decision 420): the item is on Today again, at the bottom since release 5.148
        (decision 645), as a new item goes."""
        out = self._do(lambda: edits.back_on_today(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now(), self.model()), self.sel)
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
        if task_id and waits.current(self.model(), task_id) is not None:  # a wait's row (release 5.139, decision 595)
            from docrepo import conversations
            from docrepo.ui import t_mails

            found = conversations.latest_email(self.model(), task_id)
            if found is not None:
                c, e = found
                links = (("Reply all", lambda: t_mails.reply_all(self, c.id, e.pos, task_id), "Reply all to the newest email on the task, "
                          "to follow up; then Log progress on it"), *links)
            links = (("Got it", lambda: self.got_it(task_id), "The answer came: stop waiting, and take away the follow-up"), *links)
        return [*links, ("Done", lambda: self.close_today_item(item_id, "Done"),
                         "Take it off Today as done, and open an Update on the task" if task_id else "Take it off Today as done"),
                ("Remove", lambda: self.close_today_item(item_id, "Removed"), "Take it off Today")]
