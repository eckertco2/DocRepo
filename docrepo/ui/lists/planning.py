"""The Timeline, Capacity and Priorities pages' hooks into the window: dates and key dates saved from a drag, what-ifs, moves that ask first, Quick edit, and Capacity's table. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


import json
from collections.abc import Callable
from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidgetItem,
    QWidget,
)

from docrepo import capacity, edits, priorities, ties, whatif
from docrepo.agenda import AgendaError
from docrepo.dates import long_date, short, to_date
from docrepo.people import PeopleError
from docrepo.tasks import TaskError
from docrepo.ui import tokens
from docrepo.ui.look import LOOK
from docrepo.ui.templates_view import PreviewDialog, PreviewEntry
from docrepo.timeline import bands as timeline_bands
from docrepo.ui.tokens import C
from docrepo.ui.tree_view import group_ground
from docrepo.views import (
    CapacityRow,
    capacity_grid,
    capacity_weeks,
)


class PlanningHooks:
    """The Timeline, Capacity and Priorities pages' hooks into the window: dates and key dates saved from a drag, what-ifs, moves that ask first, Quick edit, and Capacity's table."""


    # ---- the Priorities board (mods log round 2, M0029, M0030; release 5.23) ----
    def move_priority(self, task_id: str, bucket: str, before) -> None:
        """A card dragged, or moved by its key or the buckets above the board."""
        self._do(lambda: edits.set_priority(self.conn, self.ctx.data_root, self.ctx.fs, task_id, bucket, before, self._now()), ("task", task_id))

    def set_timeline_key_date(self, task_id: str, key_id: int, start: str | None, end: str | None, said: str) -> None:
        """A key date dragged in Plan mode, or put back by Ctrl+Z (release 5.31, decision 152): saved and logged."""
        from docrepo import tasks

        rows = tasks.key_date_rows(self.conn, task_id)
        for row in rows:
            if row.id == key_id:
                row.start, row.end = start, end
        leave = set() if said.endswith("back as it was.") else self._left_by_move(lambda: edits.key_dates_move(self.conn, self.ctx.settings, task_id, rows, self._now()), task_id)
        if leave is None:
            return self._move_taken_back()
        out = self._do(lambda: edits.set_key_dates(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, rows, self._now(), leave), ("task", task_id))
        if isinstance(out, edits.Outcome) and not out.problems and out.message != "Nothing changed.":
            self.say(f"{said} {out.moved}".strip())
        return None

    def set_timeline_dates(self, task_id: str, start: str | None, due: str | None, said: str) -> None:
        """A Plan mode drop on the timeline, or Ctrl+Z (release 5.30, decision 136): the dates saved and logged, as Edit
        task's are. A task with a Duration keeps its days when it's moved, and takes the new length when it's stretched."""
        leave = set() if said.endswith("back as they were.") else self._left_by_move(
            lambda: edits.change_moves(self.conn, self.ctx.settings, task_id, self._now(), start=start, due=due, dragged=True), task_id)
        if leave is None:
            return self._move_taken_back()
        out = self._do(lambda: edits.change_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now(),
                                                 start=start, due=due, dragged=True, leave=leave), ("task", task_id))
        if isinstance(out, edits.Outcome) and not out.problems:
            self.say(f"{said} {out.moved}".strip() if out.message != "Nothing changed." else out.message)
        return None

    # ---- what-ifs (release 5.64) ----
    def whatif_picture(self, w: whatif.WhatIf) -> whatif.Picture:
        """What a what-if would do, worked out again only when it or the database has changed, as each redraw asks."""
        real = self.model()
        key = (json.dumps([a.to_json() for a in w.actions]), w.name)
        held = self._whatif_held
        if held is not None and held[0] is real and held[1] == key:
            return held[2]
        pic = self.ctx.rolled_back(lambda: whatif.picture(self.conn, self.ctx.settings, w, self._now(), real))
        self._whatif_held = (real, key, pic)
        return pic

    def apply_whatif(self, wid: str, skip: list) -> None:
        """Review and apply's Apply (decision 226): the ticked changes made and logged, and the what-if gone."""
        view = self.timeline
        w = next((x for x in view.whatifs if x.id == wid), None)
        if w is None:
            return
        view.cur = None  # drawn after it as the real plan, which now has the changes
        out = self._do(lambda: edits.apply_whatif(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, w, skip, self._now()))
        if out is None:
            view.cur = wid
            view.render(self.model(), self.today())
            return
        view.whatifs.remove(w)
        view.wi_undo.pop(wid, None)
        whatif.save_all(self.conn, view.whatifs)
        view.render(self.model(), self.today())

    # ---- a move that reaches another tree asks first (release 5.50, decision 249) ----
    def ask_move(self, task_id: str, followed: list, parent: QWidget | None = None) -> set[str] | None:
        """Every task a move would take with it, ticked, when any of them is outside the task's own tree. Returns those to leave, which
        keep their dates, stay tied and take a new gap, or None for Back."""
        m, today = self.model(), self.today()
        mine = ties.tops(m.parents_of, task_id)
        away = [f for f in followed if not ties.tops(m.parents_of, f.task) & mine]
        if not away:
            return set()

        def shown(value: str | None) -> str:
            return long_date(to_date(value), today) if value and value != "None" else "None"

        def entry(f) -> PreviewEntry:
            t, top = m.task(f.task), sorted(ties.tops(m.parents_of, f.task))[0]
            return PreviewEntry(f.task, t.title if top == t.id else f"{t.title} · {m.task(top).title}",
                                [f"{c.field}: {shown(c.from_value)} → {shown(c.to_value)}" for c in f.changes if c.field in ties.FIELDS.values()], state=t.state,
                                off_lines=["Keeps its date, stays tied, and takes a new gap."])

        n, far = len(followed), len(away)
        dialog = PreviewDialog(parent or self, f"This move reaches {far} task{'' if far == 1 else 's'} in other trees",
                               f"{m.task(task_id).title} moved. {n} task{' is' if n == 1 else 's are'} tied to it, near or far.", [entry(f) for f in followed],
                               "An unticked task keeps its date, stays tied, and takes a new gap, and what's tied to it stays too. Each change goes in the "
                               "task's status log. Back puts this move back.",
                               lambda ticked: f"Move {len(ticked)} task{'' if len(ticked) == 1 else 's'}" if ticked else "Move only this one")
        self._move_dialog = dialog  # kept, so tests can reach it
        if not self.run_dialog(dialog):
            return None
        return {f.task for f in followed} - set(dialog.ticked())

    def _left_by_move(self, moves: Callable[[], list], task_id: str) -> set[str] | None:
        """What to leave behind, having asked if need be. A change that isn't allowed says why when it's made."""
        try:
            followed = moves()
        except (TaskError, PeopleError, AgendaError, edits.EditError, ValueError):
            return set()
        return self.ask_move(task_id, followed)

    def _move_taken_back(self) -> None:
        """Back, from asking first after a drag on the timeline: as if it hadn't happened."""
        if self.timeline.undo:
            self.timeline.undo.pop()
        self.refresh(render=False)
        self.render_all()
        self.say("Nothing moved.")

    def quick_edit(self, task_id: str, near) -> None:
        """Quick edit (release 5.30, item 55): the small window for one task's dates, people and hours, beside its bar."""
        from docrepo.ui.quick_edit import QuickEdit

        if self.quick_window is not None:  # one at a time: closing only hides it
            self.quick_window.close()
            self.quick_window.deleteLater()
        self.quick_window = QuickEdit(self.ctx, task_id, self)
        self.quick_window.ask_move = self.ask_move
        self.quick_window.saved.connect(lambda x: (self.refresh(render=False), setattr(self, "sel", ("task", x)), self.render_all()))
        self.quick_window.open_task.connect(self.go_task)
        self.quick_window.show_near(near)

    def nudge_priority(self, task_id: str, step: int, shown: list) -> None:
        """Alt+Up and Alt+Down on the board: one place up or down in its bucket, not in the status log."""
        self._do(lambda: priorities.nudge(self.conn, task_id, step, shown), ("task", task_id))

    # ---- capacity ----
    def render_capacity(self) -> None:
        m, today = self.model(), self.today()
        weeks = capacity_weeks(today, self.cap_offset)
        rows = capacity_grid(self.conn, m, weeks)
        nobody = not rows and not LOOK.classic
        for w in (self.cap_nav, self.cap_table, self.cap_legend, self.cap_detail):
            w.setVisible(not nobody)
        self.cap_empty.setVisible(nobody)
        # Grouped (release 5.9): each group's people under its heading, then those with no group.
        lines: list[CapacityRow | str] = list(rows)
        if self.cap_by_group.isChecked():
            group_of = {p.id: p.group or "" for p in m.people.values()}
            lines = []
            for g in [*m.groups(), ""]:
                members = [r for r in rows if group_of.get(r.person, "") == g]
                if members:
                    lines += [g or "No group", *members]
        t = self.cap_table
        t.clear()
        t.clearSpans()
        t.setRowCount(len(lines))
        t.setColumnCount(len(weeks) + 1)
        # A week with a plant event names it under its date (M0028).
        bands = timeline_bands(m, weeks[0], weeks[-1] + timedelta(days=7))
        heads = []
        for w in weeks:
            names = [b.title for b in bands if b.start <= w + timedelta(days=6) and b.end >= w]
            heads.append(short(w, today) + ("\n" + ", ".join(names) if names else ""))
        t.setHorizontalHeaderLabels(["Person", *heads])
        for i, _w in enumerate(weeks):
            if "\n" in heads[i]:
                t.horizontalHeaderItem(i + 1).setBackground(QColor(C.event_bg))
                t.horizontalHeaderItem(i + 1).setToolTip("A plant event this week: " + heads[i].split("\n", 1)[1])
        # Neutral under 80%, caution's tint from 80% to 100%, red over 100% (the Classic look: green, amber, red). Decision 18 had the
        # accent's tint in the middle, which was selection's, so a selected cell couldn't be told from a busy one (release 5.60).
        colours = ({"u1": "#e2f2e6", "u2": "#fcefcf", "u3": "#fbe3e1"} if LOOK.classic else
                   {"u2": tokens.colour("caution_bg"), "u3": tokens.colour("critical_bg")})
        t.setShowGrid(LOOK.classic)
        self._cap_line_rows = lines
        for r, row in enumerate(lines):
            if isinstance(row, str):  # a group's heading
                head = QTableWidgetItem(row)
                if LOOK.classic:
                    f = head.font()
                    f.setBold(True)
                    head.setFont(f)
                else:
                    head.setFont(tokens.ui_font(semibold=True))  # from the helper: setBold on an item's font is lost under its style name
                head.setBackground(group_ground())
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                t.setItem(r, 0, head)
                t.setSpan(r, 0, 1, len(weeks) + 1)
                continue
            head = QTableWidgetItem(f"{row.name}\n{'%g h a week' % row.hours_a_week if row.hours_a_week else 'Hours not set'}")
            t.setItem(r, 0, head)
            for i, c in enumerate(row.cells):
                sep = "\n" if LOOK.classic else "  ·  "
                text = f"{c.hours:.1f}" + (f"{sep}{round(c.use * 100)}%" if c.hours and c.use is not None else "") if c.hours else "–"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if LOOK.classic else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c.cls in colours:
                    item.setBackground(QColor(colours[c.cls]))
                if c.cls == "u3" and not LOOK.classic:  # over 100%: red and bold, so it never needs colour alone
                    item.setForeground(QColor(tokens.colour("critical")))
                    item.setFont(tokens.ui_font(semibold=True))
                item.setToolTip(f"{row.name}, week of {long_date(weeks[i], today)}: {c.hours:.1f} h")
                t.setItem(r, i + 1, item)
        t.resizeRowsToContents()
        if not LOOK.classic:
            header = t.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for i in range(1, t.columnCount()):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            # All its rows when there's room, with none cut by a scroll bar across it, and no gap under its last row.
            t.setMaximumHeight(header.sizeHint().height() + sum(t.rowHeight(r) for r in range(t.rowCount())) + t.horizontalScrollBar().sizeHint().height() + 4)
            if self.cap_cell:  # the cell clicked stays marked when the table is drawn again
                person, week = self.cap_cell
                for r, line in enumerate(lines):
                    if not isinstance(line, str) and line.person == person and week + 1 < t.columnCount():
                        t.setCurrentCell(r, week + 1)
        t.resizeColumnToContents(0)
        height = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(t.rowCount())) + 2 * t.frameWidth() + 2
        t.setFixedHeight(min(height, 420))
        self._cap_rows, self._cap_weeks = rows, weeks
        unestimated, unscheduled = capacity.unplaced(m, today, self.ctx.settings)
        self.cap_detail.setHtml(self.pages().capacity_detail(rows, weeks, self.cap_cell, unestimated, unscheduled))

    def _capacity_clicked(self, row: int, column: int) -> None:
        lines = getattr(self, "_cap_line_rows", self._cap_rows)
        if column == 0 or row >= len(lines) or isinstance(lines[row], str):
            return
        self.cap_cell = (lines[row].person, column - 1)
        self.render_capacity()

    def _move_capacity(self, step: int) -> None:
        self.cap_offset = 0 if step == 0 else self.cap_offset + step
        self.cap_cell = None
        self.render_capacity()
