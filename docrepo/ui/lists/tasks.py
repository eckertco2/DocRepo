"""The task tree and the lists of tasks (Overdue, Reminders and the rest): their rows and cells, Group by, Sort, Select mode and Edit selected, and the key dates' rows. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


from collections.abc import Callable
from dataclasses import replace
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
)

from docrepo import bulk, edits, key_dates, priorities
from docrepo.lists import key_dates_due
from docrepo.dates import short
from docrepo.detail import chip, esc
from docrepo.links import is_link
from docrepo.overview import file_type
from docrepo.schedule import DueDate, is_open
from docrepo.ui import tokens
from docrepo.ui.look import LOOK
from docrepo.ui.task_forms import BulkEditDialog
from docrepo.ui.tree_view import KEY_ROLE, Line, group_ground, state_icon, tint, with_actions
from docrepo.ui.widgets import CheckMenuButton, label_filter, people_filter
from docrepo.views import (
    LIST_IDS,
    SORTS,
    TREE_GROUPS,
    VIEW_IDS,
    Node,
    TreeFilter,
    collapse_level,
    due_cell,
    key_date_cell,
    expand_level,
    full_path,
    list_date,
    list_tree,
    markers,
    sort_tree,
    task_tree,
    tree_sections,
    walk,
)
from docrepo.ui.lists.common import (
    _cols,
    _due_css,
    _due_html,
    _row_state,
    _row_word,
    _shape,
    SELECT_VIEWS,
)


class TaskLists:
    """The task tree and the lists of tasks (Overdue, Reminders and the rest): their rows and cells, Group by, Sort, Select mode and Edit selected, and the key dates' rows."""


    # ---- rows ----
    def _task_cells(self, task_id: str, depth: int, context: bool = False, muted: tuple[str, ...] = (), people: str = "",
                    when: DueDate | None = None, use_due: bool = True) -> list:
        """A task's row: a ``Line`` (its state's icon, its title, Urgent or Critical as chips, its other marks and ``muted`` as
        quiet words, and ``people``), then its State in the Classic look, and its date. Regular weight in the new look
        (decision L2); the Classic look's top-level tasks are bold."""
        m, t = self.model(), self.model().task(task_id)
        icon, colour = state_icon(t.state)
        if context:
            return _shape([Line(t.title, icon=icon, icon_tip=t.state, dim=True, strong=depth == 0), "", ""])
        chips, quiet = [], []
        for text, cls in markers(m, t):  # a chip only for an exception; the rest are quiet words (the review's recipe)
            (chips if LOOK.classic or cls in ("urgent", "pri-critical") else quiet).append((text, cls))
        line = Line(t.title, icon=icon, icon_colour=colour, icon_tip=t.state, chips=tuple(chips), muted=(*(x for x, _ in quiet), *muted),
                    context=people, strong=depth == 0, closed=t.state == "Closed")
        return _shape([line, _row_state(t.state), _due_html(due_cell(t, self.today(), when, use_due))])

    def _label_words(self, task_id: str, skip: str = "") -> tuple[str, ...]:
        """After a title in the task tree (item 76, decision 235): the task's own labels, as quiet words rather than chips.
        Not the ones it inherits, or every subtask would repeat its parent's, nor ``skip``, which its section is named for."""
        return tuple(name for name in self.model().task(task_id).labels if name != skip)

    def _add_nodes(self, nodes: list[Node], parent=None, filtered: bool = False, expand_all: bool = True,
                   row: Callable[[Node], tuple[list[str], str]] | None = None) -> None:
        m = self.model()
        for n in nodes:
            if n.kind == "group":
                item = self.tree.add_row(parent, None, [f"<b>{esc(n.label)}</b>"], group_ground(), selectable=False, span=True)
            elif n.kind == "doc":
                d = m.documents[n.id]
                link = is_link(d.original)
                kind = file_type(d.name, d.original)
                cells = [Line(d.name, icon="folder" if kind == "folder" else f"type-{kind}", icon_colour=f"type_{kind}" if f"type_{kind}" in tokens.LIGHT else "type_other",
                              icon_tip=kind.capitalize(), second=d.description or "No description yet"),
                         chip("Link", "st-ns") if link else chip(d.status, "st-ns" if d.status == "Current" else "st-pk"),
                         f'<p align="right">{esc(short(date.fromisoformat(d.checked[:10]), self.today())) if d.checked else ""}</p>']
                tip = f"{d.original} (double-click copies it)" if link else f"Last checked {d.checked or 'not yet'}"
                item = self.tree.add_row(parent, ("doc", n.id), cells, tint(n.group, n.depth), tip=tip)
            else:
                cells, tip = row(n) if row else (self._task_cells(n.id, n.depth, filtered and not n.match), full_path(m, n.id))
                if isinstance(cells[0], Line) and n.children:  # a folded parent says how many open subtasks it holds (decision L8)
                    cells[0].count = sum(1 for c in n.children if c.kind == "task" and c.id in m.tasks and is_open(m.task(c.id)))
                item = self.tree.add_row(parent, ("task", n.id), cells, tint(n.group, n.depth), tip=tip)
                if self.selecting and n.match and self.view in SELECT_VIEWS:
                    self.tree.add_tick(item, n.id in self.ticked)
            self._add_nodes(n.children, item, filtered, expand_all, row)
            item.setExpanded(expand_all or n.id in self.open)

    def _tree_filter(self, pin: bool = True) -> TreeFilter:
        """The task tree's filters as they're ticked, with the task just saved pinned (``pin``)."""
        f = self.tree_filter
        return TreeFilter(parked=f["parked"], closed=f["closed"], routine=f["routine"], labels=tuple(f["labels"]), people=tuple(f["people"]),
                          pin=self.pin if pin else None, priorities=tuple(f["priorities"]), urgent=bool(f.get("urgent")))

    def _tasks_view(self) -> None:
        f = self.tree_filter
        filtered = bool(f["labels"] or f["people"] or f["priorities"] or f.get("urgent"))
        m = self.model()
        self._set_head("Task tree", "Dimmed rows don't match the filter. They're parents of tasks that do, shown for context." if filtered else "",
                       f"{sum(1 for t in m.tasks.values() if is_open(t))} open")
        # Urgent only (release 5.97, the consolidation plan's decision 386): what the Urgent view listed, in the tree, first
        # among the filters (the mock's place, the owner's choice of 2026-11-07).
        self._check("Urgent only", bool(f.get("urgent")), lambda on: self._set_filter("urgent", on),
                    "Only the tasks ticked Urgent, with their parents dimmed. Today's Due in the next 7 days puts them first too.")
        self._check("Show parked", f["parked"], lambda on: self._set_filter("parked", on))
        self._check("Show closed", f["closed"], lambda on: self._set_filter("closed", on))
        self._check("Show routine", f["routine"], lambda on: self._set_filter("routine", on), "Recurring tasks, such as meetings, and their subtasks")
        # Several labels and people at once (mods log round 1, M0018): a task matches with any of each.
        # A parent label ticks its sublabels, and a group its people (release 5.9).
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, f["labels"], sets)
        labels.chosen.connect(lambda values: self._set_filter("labels", values))
        self._filter_widget(labels)
        people_button = CheckMenuButton("People", "anyone", people_filter(m)[0], f["people"], people_filter(m)[1])
        people_button.chosen.connect(lambda values: self._set_filter("people", values))
        people_button.setToolTip(people_button.toolTip() or "Tasks any of the ticked people lead or are assigned")
        self._filter_widget(people_button)
        # Priority (release 5.23): tasks in any of the ticked buckets, Not ranked among them.
        ranked = CheckMenuButton("Priority", "any", [(label, key) for key, label, _ in priorities.COLUMNS], f["priorities"])
        ranked.chosen.connect(lambda values: self._set_filter("priorities", values))
        self._filter_widget(ranked)
        self._sort_box("tasks")
        self._tree_group_box(m)
        self._select_controls()
        tf = self._tree_filter()
        how = self.tree_group if self.tree_group in dict(TREE_GROUPS) or self.tree_group[3:] in {lb.name for lb in m.labels} else ""
        sections = [replace(s, nodes=sort_tree(m, s.nodes, self.sorts.get("tasks", "default"), self.today()))
                    for s in tree_sections(m, tf, how)] if how else []
        nodes = [n for s in sections for n in s.nodes] if how else sort_tree(m, task_tree(m, tf), self.sorts.get("tasks", "default"), self.today())
        can_fold, can_open = collapse_level(nodes, self.open) != self.open, expand_level(nodes, self.open) != self.open
        collapse = self._level_button(False, lambda: self._level(nodes, "collapse"), can_fold)
        expand = self._level_button(True, lambda: self._level(nodes, "expand"), can_open)
        collapse.setVisible(can_fold or can_open or LOOK.classic)  # gone where nothing nests
        expand.setVisible(can_fold or can_open or LOOK.classic)
        self.tree.set_columns(*_cols(["Title", "State", "Due"]))

        def row(n: Node, section: str = "") -> tuple[list, str]:
            dimmed = bool(how or filtered) and not n.match
            return self._task_cells(n.id, n.depth, dimmed, muted=self._label_words(n.id, section)), full_path(m, n.id)

        if how:  # a section per group, each with its tasks in tree shape (release 5.24)
            grey = group_ground()
            for s in sections:
                sub = f' <span class="sub">{esc(s.sub)}</span>' if s.sub else ""
                head = self.tree.add_row(None, None, [f'<b>{esc(s.name)}</b>{sub} &nbsp;<span class="sub">{s.count}</span>'], grey,
                                         selectable=False, span=True)
                named = s.name if how == "label" or how.startswith("pl:") else ""  # its section says it already
                self._add_nodes(s.nodes, head, filtered=True, expand_all=False, row=lambda n, x=named: row(n, x))
                head.setExpanded(True)
        else:
            self._add_nodes(nodes, filtered=filtered, expand_all=False, row=row)
        if not nodes and not LOOK.classic and not any(not t.discarded for t in m.tasks.values()):  # first use, not a filter's doing
            self.tree.show_empty("No tasks yet.", "New task", lambda: self.open_capture(mode="new_task"))
        elif not nodes:
            self.tree.add_row(None, None, ['<span class="sub">No tasks match these filters.</span>'], selectable=False, span=True)

    def _tree_group_box(self, m) -> None:
        """The task tree's Group by (release 5.24): Group, Person or Label, or a parent label's sublabels."""
        box = QComboBox()
        box.setAccessibleName("Group by")
        for key, label in TREE_GROUPS:
            box.addItem("No grouping" if not key else f"Group by {label.lower()}", key)
        for lb in m.active_labels():
            if m.is_parent_label(lb.name):
                box.addItem(f"Group by {lb.name}", "pl:" + lb.name)
        box.setCurrentIndex(max(0, box.findData(self.tree_group)))
        box.setToolTip("A section for each group, person or label, each with its tasks in tree shape. With People or Labels ticked, "
                       "only those get a section.")
        box.currentIndexChanged.connect(lambda _: self._set_tree_group(box.currentData()))
        self._filter_widget(box)

    def _set_tree_group(self, how: str) -> None:
        """Group by, chosen: the branches open down to each section's tasks, so the groups show what's in them."""
        self.tree_group = how
        if how:
            m = self.model()
            for section in tree_sections(m, self._tree_filter(pin=False), how):
                for n in walk(section.nodes):
                    if n.match:
                        self.open.update(m.ancestors_of(n.id))
        self.render_list()

    def _set_filter(self, key: str, value) -> None:
        self.tree_filter[key] = value
        if key == "urgent" and value:
            self.open_to_urgent()
        self.render_list()

    def open_to_urgent(self) -> None:
        """Urgent only, ticked: the branches open down to each urgent task, so the tree shows them (release 5.97)."""
        m = self.model()
        for t in m.tasks.values():
            if t.urgent and is_open(t):
                self.open.update(m.ancestors_of(t.id))

    def _sort_box(self, view_id: str) -> None:
        """The Sort list for the task tree or a list (mods log round 1, M0015)."""
        box = QComboBox()
        box.setAccessibleName("Sort")
        for key, label in SORTS:
            box.addItem(f"Sort: {label.lower() if key != 'default' else ('tree order' if view_id == 'tasks' else 'soonest first')}", key)
        box.setCurrentIndex(max(0, box.findData(self.sorts.get(view_id, "default"))))
        box.setToolTip("Sorts the tasks under each parent, so the tree keeps its shape")
        box.currentIndexChanged.connect(lambda _: self._set_sort(view_id, box.currentData()))
        self._filter_widget(box)

    def _set_sort(self, view_id: str, how: str) -> None:
        self.sorts[view_id] = how
        self.render_list()

    # ---- Select mode and Edit selected (mods log round 1, M0009) ----
    def _select_controls(self) -> None:
        self._check("Select", self.selecting, self.set_selecting, "Tick tasks in this list, then Edit selected changes them all at once")
        if not self.selecting:
            return
        self._button("Select all shown", lambda: self.tick_shown(True), tip="Tick every task you can see in the list")
        self.clear_ticks_button = self._button("Clear", lambda: self.tick_shown(False), tip="Untick them all")
        self.edit_selected_button = self._button("", self.edit_selected, tip="Change the ticked tasks, after a preview")
        self.apply_template_button = self._button("", self.apply_template_to_ticked, tip="Put a template into the ticked tasks, which keep all they have")
        self._sync_edit_selected()

    def set_selecting(self, on: bool) -> None:
        self.selecting = on
        if not on:
            self.ticked.clear()
        self.render_list()

    def _tick(self, key, on: bool) -> None:
        if self.view == "activity":  # Select in Activity (release 5.23): tasks and lines, for Add to agenda
            pick = f"l:{key[1]}" if key[0] == "actline" else f"t:{key[1]}" if key[0] == "task" else None
            if pick:
                (self.act["picked"].add if on else self.act["picked"].discard)(pick)
                self._sync_activity_bar()
            return
        if key[0] == "task":
            (self.ticked.add if on else self.ticked.discard)(key[1])
            self._sync_edit_selected()

    def _sync_edit_selected(self) -> None:
        n = len(self.ticked)
        b = getattr(self, "edit_selected_button", None)
        if b is not None and b.parent() is not None:
            b.setText(f"Edit selected ({n})…" if n else "Edit selected…")
            b.setEnabled(n > 0)
        a = getattr(self, "apply_template_button", None)
        if a is not None and a.parent() is not None:
            a.setText(f"Apply template ({n})…" if n else "Apply template…")
            a.setEnabled(n > 0)
        clear = getattr(self, "clear_ticks_button", None)
        if clear is not None and clear.parent() is not None:
            clear.setEnabled(n > 0)

    def tick_shown(self, on: bool) -> None:
        """Select all shown, or Clear: every task row you can see, not those under a collapsed task."""
        if on:
            self.ticked |= {item.data(0, KEY_ROLE)[1] for item in self.tree.items()
                            if item.data(0, Qt.ItemDataRole.CheckStateRole) is not None and self.tree.is_shown(item)}
        else:
            self.ticked.clear()
        self.render_list()

    def ticked_in_order(self) -> list[str]:
        """The ticked tasks, as the list shows them."""
        shown = [k[1] for k in self.tree.keys() if k and k[0] == "task" and k[1] in self.ticked]
        return list(dict.fromkeys(shown + sorted(self.ticked - set(shown))))

    def apply_template_to_ticked(self) -> None:
        self.templates.apply(self.ticked_in_order())

    def edit_selected(self) -> None:
        ids = self.ticked_in_order()
        if not ids:
            self.say("Tick some tasks first.", error=True)
            return
        dialog = BulkEditDialog(self, self.model(), ids, self._label_options, self._people_options,
                                lambda e: bulk.preview(self.conn, self.ctx.settings, ids, e, self._now(), edits.BROWSE),
                                lambda anchor, picked: self._pick_task(anchor, picked, ("None", "Leave them where they are")))
        if self.run_dialog(dialog):
            edit = dialog.edit()
            self._do(lambda: edits.bulk_edit(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, ids, edit, self._now()))

    def _list_view(self, view_id: str) -> None:
        v, task_list, m = VIEW_IDS[view_id], LIST_IDS[view_id], self.model()
        self._set_head(v.label, v.note + " Dimmed rows are their parents, shown for context.")
        reminders = view_id == "reminders"
        with_keys = view_id == "due"  # key dates have a row each, with Done (release 5.31, decision 150)
        self.tree.set_columns(*_cols(*(with_actions(["Title", "State", "Reminder" if reminders else "Due"], [0, 96, 96], 56)
                                       if reminders or with_keys else (["Title", "State", "Due"], None))))
        self._sort_box(view_id)
        grouped = self._group_box(view_id)
        self._select_controls()
        nodes = sort_tree(m, list_tree(m, task_list, self.today(), self.ctx.settings.me), self.sorts.get(view_id, "default"), self.today())
        if grouped:  # under each sublabel's heading (release 5.9, M0051)
            self._grouped_list(view_id, grouped, nodes)
            if with_keys:
                self._key_date_rows(None)
            return

        def row(n: Node) -> tuple[list[str], str]:
            if not n.match:
                return self._task_cells(n.id, n.depth, context=True), full_path(m, n.id)
            t = m.task(n.id)
            who = ", ".join(m.person_name(p) for p in t.assignees) if view_id == "waiting" else ""
            when = list_date(task_list, t, self.today()) if reminders else None
            return self._task_cells(n.id, n.depth, people=who, when=when, use_due=not reminders), full_path(m, n.id)

        self._add_nodes(nodes, row=row)
        if reminders:
            for item in self.tree.items():
                key = item.data(0, KEY_ROLE)
                if key and key[0] == "task" and m.task(key[1]).reminder and key[1] in {t.id for t in self._matching(task_list)}:
                    self.tree.set_actions(item, [("Clear", lambda tid=key[1]: self.clear_reminder(tid), "Clear this reminder. Its status log records it.")])
        keyed = self._key_date_rows(None) if with_keys else 0
        if not nodes and not keyed:
            self.tree.add_row(None, None, ['<span class="sub">Nothing here right now.</span>'], selectable=False, span=True)

    def _key_date_cells(self, d: key_dates.Due) -> list:
        """A key date's row (release 5.31): its task's title, the key date's words after it in quiet text (under it in the
        Classic look), its plant and deadline marks, a Key date icon (a chip in the Classic look), and its days until due, red
        when it's overdue."""
        today = self.today()
        cell = key_date_cell(d, today)
        marks = ((("⚑", "caution"),) if d.key_date.plant else ()) + ((("◆", "critical"),) if d.key_date.deadline else ())
        line = Line(d.task.title, icon="calendar", icon_tip="Key date", chips=marks, context=d.text(today))
        return _shape([line, _row_word("Key date"), f'<p align="right" style="{_due_css(cell.cls)}">{esc(cell.text)}</p>'])

    def _key_date_actions(self, key_id: int) -> list[tuple[str, Callable[[], None], str]]:
        return [("Done", lambda: self.key_date_done(key_id, True), "Mark this key date done: off Today and this list, and in its task's status log (decision 148)")]

    def _key_date_rows(self, parent) -> int:
        """The Overdue and next 7 days list's key dates (release 5.31, decision 150): under a Key dates heading, a row each,
        soonest first, opening its task, with Done. Returns how many."""
        dues = key_dates_due(self.model(), self.today())
        if not dues:
            return 0
        head = self.tree.add_row(parent, None, [f'<b>Key dates</b> &nbsp;<span class="sub">{len(dues)}</span>'], group_ground(),
                                 selectable=False, span=True)
        for d in dues:
            item = self.tree.add_row(head, ("task", d.task.id), self._key_date_cells(d),
                                     tip=f"A key date of {d.task.title}: {key_dates.label(d.key_date, self.today())}")
            self.tree.set_actions(item, self._key_date_actions(d.key_date.id))
        head.setExpanded(True)
        return len(dues)

    def key_date_done(self, key_id: int, done: bool) -> None:
        """A key date's Done tick, from the lists, Today or the task page (release 5.31, decision 148)."""
        self._do(lambda: edits.set_key_date_done(self.conn, self.ctx.data_root, self.ctx.fs, key_id, done, self._now()))

    def key_date_subtask(self, key_id: int) -> None:
        """Make it a subtask (item 61), from the task page."""
        self._do(lambda: edits.key_date_subtask(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, key_id, self._now()))
