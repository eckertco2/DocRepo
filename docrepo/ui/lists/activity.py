"""The Activity view, its controls and groups, and Add to agenda and Copy from it. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations



from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
)

from docrepo import activity, edits
from docrepo.dates import long_date, short, to_date
from docrepo.detail import chip, esc
from docrepo.model import TODAY
from docrepo.ui.look import LOOK
from docrepo.ui.tree_view import Line, state_icon
from docrepo.ui.widgets import CheckMenuButton, DateField, label_filter, people_filter
from docrepo.views import (
    VIEW_IDS,
    markers,
)
from docrepo.ui.lists.common import (
    _row_state,
    ACT_CHIPS,
    ACT_ICONS,
)


class ActivityList:
    """The Activity view, its controls and groups, and Add to agenda and Copy from it."""


    # ---- Activity (mods log round 2, M0032; release 5.23, decisions 70 to 73) ----
    def _activity_view(self) -> None:
        m, today, a = self.model(), self.today(), self.act
        act = activity.Activity(m, today)
        span = activity.window(a["win"], today, to_date(a["from"]) if a["from"] else None, to_date(a["to"]) if a["to"] else None)
        f = activity.Filter(tuple(a["people"]), tuple(a["labels"]), tuple(a["kinds"]))
        everything = act.lines(*span)
        lines = [x for x in everything if act.passes(x, f)]
        groups = act.groups(lines, a["group"], f)
        self._act_lines = {x.key: x for x in everything}
        self._act_shown = (act, span, groups)
        self._set_head("Activity", VIEW_IDS["activity"].note, f"{len(lines)} thing{'s' if len(lines) != 1 else ''} happened, "
                                                              f"{activity.window_text(span, today)}")
        self._activity_controls(m, today, span)
        self.tree.set_columns(["What happened", "When"], [0, 96])
        if not lines:
            filtered = a["people"] or a["labels"] or a["kinds"]
            self.tree.add_row(None, None, [f'<span class="sub">Nothing happened {"that matches these filters " if filtered else ""}from '
                                           f'{esc(activity.window_text(span, today))}.</span>'], selectable=False, span=True)
        # The summary: how much happened on how many tasks, and of what kinds.
        if lines:
            tasks_n = len({x.task for x in lines if x.task})
            loose = sum(1 for x in lines if not x.task)
            kinds = [f"{n} {label.lower() if n != 1 else label.lower().rstrip('s')}" for k, label in activity.KINDS
                     if (n := sum(1 for x in lines if x.kinds[0] == k))]
            self.tree.add_row(None, None, [f'{len(lines)} thing{"s" if len(lines) != 1 else ""} happened on {tasks_n} task{"s" if tasks_n != 1 else ""}'
                                           f'{f", and {loose} not filed yet" if loose else ""}. <span class="sub">{esc(" · ".join(kinds))}</span>'],
                              selectable=False, span=True)
        for t, first, last in act.plant_events(*span):
            line = Line(t.title, chips=(("Plant event", "new"),), context=f"{long_date(first, today)} to {long_date(last, today)}", strong=True)
            self.tree.add_row(None, ("task", t.id), [line, ""], span=True)
        for g in groups:
            self._activity_group(m, today, g)

    def _activity_controls(self, m, today, span) -> None:
        a = self.act
        show = QComboBox()
        show.setAccessibleName("Show")
        for key, label in activity.WINDOWS:
            show.addItem(f"Show: {label[0].lower()}{label[1:]}", key)
        show.setCurrentIndex(max(0, show.findData(a["win"])))
        show.currentIndexChanged.connect(lambda _: self._set_act_window(show.currentData()))
        self._filter_widget(show)
        if a["win"] == "range":
            for key, label, value in (("from", "From", span[0]), ("to", "To", span[1])):
                box = DateField()
                box.setAccessibleName(label)
                box.set_value(value.isoformat())
                box.edited.connect(lambda k=key, b=box: self._set_act(k, b.value()) if b.is_valid() and b.value() else None)
                self._filter_widget(QLabel(label))
                self._filter_widget(box)
        group = QComboBox()
        group.setAccessibleName("Group by")
        for key, label in activity.GROUPS:
            group.addItem(f"Group by {label.lower() if key != 'top' else 'top-level task'}", key)
        group.setCurrentIndex(max(0, group.findData(a["group"])))
        group.currentIndexChanged.connect(lambda _: self._set_act("group", group.currentData()))
        self._filter_widget(group)
        choices, sets = people_filter(m)
        who = CheckMenuButton("People", "anyone", choices, a["people"], sets)
        who.chosen.connect(lambda values: self._set_act("people", values))
        self._filter_widget(who)
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, a["labels"], sets)
        labels.chosen.connect(lambda values: self._set_act("labels", values))
        self._filter_widget(labels)
        what = CheckMenuButton("What", "anything", [(label, key) for key, label in activity.KINDS], a["kinds"])
        what.chosen.connect(lambda values: self._set_act("kinds", values))
        self._filter_widget(what)
        select = QPushButton("Done selecting" if a["select"] else "Select")
        select.setCheckable(True)
        select.setChecked(a["select"])
        select.setToolTip("Tick tasks and lines to put on an agenda, for meeting prep")
        select.clicked.connect(lambda: self._set_act_select(not a["select"]))
        self._filter_widget(select)
        self._button("Copy as Markdown", self.copy_activity, tip="Copy what's shown, as Markdown")
        if not a["select"]:
            return
        # Select's bar: how many are ticked, the agenda to add them to, and Add to agenda (decision 72).
        self._act_count = QLabel()
        self._filter_widget(self._act_count)
        target = QComboBox()
        target.setAccessibleName("Add to")
        for t in m.open_meetings():
            when = m.meeting_when(t.id, today)
            target.addItem(f"{t.title}{f', {when}' if when else ''}", t.id)
        target.addItem("Today", TODAY)
        for p in m.active_people():
            if p.id != self.ctx.settings.me:
                target.addItem(p.name, p.id)
        if a["target"] is None or target.findData(a["target"]) < 0:
            a["target"] = target.itemData(0)
        target.setCurrentIndex(max(0, target.findData(a["target"])))
        target.currentIndexChanged.connect(lambda _: a.__setitem__("target", target.currentData()))
        self._filter_widget(target)
        self._act_add = QPushButton("Add to agenda", objectName="primary" if LOOK.classic else "")
        self._act_add.setToolTip("Each ticked task as an agenda item; a ticked line goes on as its task, with the line as the item's note")
        self._act_add.clicked.connect(self.add_activity_to_agenda)
        self._filter_widget(self._act_add)
        self._act_clear = self._button("Clear ticks", lambda: self._set_act("picked", set()))
        self._sync_activity_bar()

    def _activity_group(self, m, today, g) -> None:
        """A group's header row, then a row for each task under it and a row for each line."""
        select = self.act["select"]
        head = f'<b>{esc(g.name)}</b>' + (f" {_row_state(m.task(g.task).state)}" if g.task else "") + \
            (f' <span class="sub">{esc(g.sub)}</span>' if g.sub else "") + f' <span class="sub">· {len(g.lines)}</span>'
        key = ("task", g.task) if g.task else ("person", g.person) if g.person else None
        top = self.tree.add_row(None, key, [head, ""], tip=f"{len(g.lines)} thing{'s' if len(g.lines) != 1 else ''} happened",
                                selectable=key is not None, span=True)
        if select and g.task:
            self.tree.add_tick(top, f"t:{g.task}" in self.act["picked"])
        self._activity_rows(m, today, g, top)
        top.setExpanded(True)

    def _activity_rows(self, m, today, g, top) -> None:
        """Under a group's row, a row for each task under it and a row for each line. The weekly review's step 4 (release
        5.128) puts a project's lines under its row with it."""
        select = self.act["select"] and self.view == "activity"
        for h in g.headings:
            parent = top
            if h.task and h.task != g.task:
                t = m.task(h.task)
                chain = m.chains_of(t.id)[0]
                above = " › ".join(m.task(x).title for x in chain[(1 if g.task else 0):-1])
                icon, colour = state_icon(t.state)
                cells = [Line(t.title, icon=icon, icon_colour=colour, icon_tip=t.state, lead=f"{above} ›" if above else "", strong=True,
                              chips=tuple(markers(m, t))) if not LOOK.classic else
                         (f'<span class="sub">{esc(above)} ›</span> ' if above else "") + f"<b>{esc(t.title)}</b> {_row_state(t.state)}"
                         + "".join(" " + chip(text, cls) for text, cls in markers(m, t)), ""]
                parent = self.tree.add_row(top, ("task", t.id), cells)
                if select:
                    self.tree.add_tick(parent, f"t:{t.id}" in self.act["picked"])
            for line in h.lines:
                facts = "".join(f'<br><span class="sub">{esc(x)}</span>' for x in line.facts)
                # Two lines (decision L1): its kind's icon and its words, then what kind it is and its facts.
                what = Line(line.text, icon=ACT_ICONS.get(line.kinds[0], "note"), icon_tip=line.chip, second=" · ".join((line.chip, *line.facts)))
                when = (f'<p align="right">{esc(short(line.day, today))}<br><span class="sub">{esc(long_date(line.day, today)[:3])} {esc(line.at[11:16])}</span></p>'
                        if LOOK.classic else f'<p align="right">{esc(short(line.day, today))} <span class="sub">{esc(line.at[11:16])}</span></p>')  # one line
                row = self.tree.add_row(parent, ("actline", line.key), [f"{chip(line.chip, ACT_CHIPS.get(line.kinds[0], 'lbl'))} {esc(line.text)}{facts}"
                                                                        if LOOK.classic else what, when],
                                        tip=f"{long_date(line.day, today)}, {line.at[11:16]}")
                if select:
                    self.tree.add_tick(row, f"l:{line.key}" in self.act["picked"])
            parent.setExpanded(True)

    def _set_act(self, key: str, value) -> None:
        self.act[key] = value
        self.render_list()

    def _set_act_window(self, choice: str) -> None:
        if choice == "range" and not self.act["from"]:
            first, last = activity.window(self.act["win"], self.today())
            self.act["from"], self.act["to"] = first.isoformat(), last.isoformat()
        self._set_act("win", choice)

    def _set_act_select(self, on: bool) -> None:
        self.act["select"] = on
        if not on:
            self.act["picked"] = set()
        self.render_list()

    def _sync_activity_bar(self) -> None:
        n = len(self.act["picked"])
        for name in ("_act_count", "_act_add", "_act_clear"):
            w = getattr(self, name, None)
            if w is None or w.parent() is None:
                return
        self._act_count.setText(f"<b>{n} ticked</b>" if n else "Tick tasks or lines")
        self._act_add.setEnabled(n > 0)
        self._act_clear.setEnabled(n > 0)

    def add_activity_to_agenda(self) -> None:
        """Add to agenda: one item per ticked task, its ticked lines joined as the note (decision 72)."""
        act, span, _ = self._act_shown
        entries = act.agenda_items(list(self._act_lines.values()), self.act["picked"])
        target = self.act["target"]
        if not entries or not target:
            return
        out = self._do(lambda: edits.add_activity_to_agenda(self.conn, self.ctx.data_root, self.ctx.fs, target, entries, self._now()), self.sel)
        if out is not None:
            self.act["picked"], self.act["select"] = set(), False
            self.render_list()

    def copy_activity(self) -> None:
        act, span, groups = self._act_shown
        QGuiApplication.clipboard().setText(act.markdown(groups, span))
        self.say("Copied what's shown, as Markdown.")
