"""What every list view shares: the state marks, the row to select, Find in this view, the level buttons and folds, grouping, and the command bar's buttons. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


import html
import re
from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QWidget,
)

from docrepo.detail import esc
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.keymap import KeyMapDialog
from docrepo.ui.tree_view import DIM_ROLE, HTML_ROLE, KEY_ROLE, LINE_ROLE, group_ground, state_icon
from docrepo.ui.widgets import DropButton
from docrepo.views import (
    Node,
    collapse_level,
    find_text,
    expand_level,
    full_path,
)
from docrepo.ui.lists.common import (
    _empty,
    _row_state,
)


class ListBasics:
    """What every list view shares: the state marks, the row to select, Find in this view, the level buttons and folds, grouping, and the command bar's buttons."""


    def _mark_states(self) -> None:
        """Each task row's State cell becomes a button that opens the state menu (release 5.76, decisions 360 and 361): the
        cells that show the row's task's own state, not a key date's, a reminder's or a context row's."""
        m = self.model()
        if not LOOK.classic:
            # The new look has no State column: a task's state is the icon before its title (release 5.78, the list rows
            # review's decision L7), and that icon is the menu's button, on rows whose icon is their task's own state.
            for item in self.tree.items():
                line = item.data(0, LINE_ROLE)
                task_id = self.tree.row_task(item)
                t = m.tasks.get(task_id) if task_id and line is not None else None
                if t is not None and not t.discarded and line.icon_tip == t.state and line.icon == state_icon(t.state)[0]:
                    self.tree.mark_state(item, 0, t.id, t.state)
            return
        header = self.tree.headerItem()
        column = next((i for i in range(self.tree.columnCount()) if header.text(i) == "State"), None)
        if column is None:
            return
        for item in self.tree.items():
            task_id = self.tree.row_task(item)
            t = m.tasks.get(task_id) if task_id else None
            if t is not None and not t.discarded and item.data(column, HTML_ROLE) == _row_state(t.state):
                self.tree.mark_state(item, column, t.id, t.state)

    def _row_to_select(self):
        """The row to show selected: the page on the right's, or in Activity the line clicked last, while it opens that page."""
        line = self._act_lines.get(self.act["line"] or "") if self.view == "activity" else None
        return ("actline", line.key) if line is not None and line.open == self.sel else self.sel

    # ---- Find in this view (mods log round 2, M0026) ----
    def open_find(self) -> None:
        """Ctrl+F: a box above the list that narrows the view you're in as you type."""
        if self.view == "priorities":  # release 5.24: the board has a box of its own
            self.priorities.open_find()
            return
        if self.view in ("timeline", "capacity", "settings"):
            self.say("The timeline and capacity have their own filters. Find in this view works on Today, the task tree, the lists, "
                     "Unfiled, Agendas, Activity, Priorities, People, Labels, Templates, Documents and Discarded. Ctrl+Shift+F searches everything.")
            return
        self.find_bar.show()
        self.find_box.setFocus()
        self.find_box.selectAll()

    def close_find(self) -> None:
        """Esc in the box, or another view: clear it, and the list shows everything again."""
        self.find_box.blockSignals(True)
        self.find_box.clear()
        self.find_box.blockSignals(False)
        self.find_bar.hide()
        self.find_count.clear()

    def _apply_find(self) -> None:
        """Keep the rows that hold every word typed, each with its parents, faded, for context; closed branches open while
        finding. A task is found by its ID, title, description, current status, labels and people too."""
        words = self.find_box.text().lower().split() if not self.find_bar.isHidden() else []
        if not words:
            self.find_count.clear()
            return
        m = self.model()

        def text_of(item) -> str:
            key = item.data(0, KEY_ROLE)
            cells = " ".join(item.data(i, HTML_ROLE) or "" for i in range(self.tree.columnCount()))
            text = html.unescape(re.sub(r"<[^>]+>", " ", cells)).lower()
            if key and isinstance(key, tuple) and len(key) > 1 and isinstance(key[1], str):  # its ID, which rows no longer show (decision L4)
                text += " " + key[1].lower()
            return text + (" " + find_text(m, key[1]) if key and key[0] == "task" and key[1] in m.tasks else "")

        hits = 0

        def visit(item) -> bool:
            nonlocal hits
            hit = item.data(0, KEY_ROLE) is not None and all(w in text_of(item) for w in words)
            hits += hit
            kept = [visit(item.child(i)) for i in range(item.childCount())]
            keep = hit or any(kept)
            item.setHidden(not keep)
            item.setData(0, DIM_ROLE, True if keep and not hit else None)
            if any(kept):
                item.setExpanded(True)
            return keep

        with self.tree.building():  # opening branches here isn't remembered
            root = self.tree.invisibleRootItem()
            for i in range(root.childCount()):
                visit(root.child(i))
            # A heading row (Today's groups) stays when a row under it does.
            heading = None
            for i in range(root.childCount()):
                item = root.child(i)
                if item.data(0, KEY_ROLE) is None and not item.childCount():
                    heading = item
                elif heading is not None and not item.isHidden():
                    heading.setHidden(False)
                    heading.setData(0, DIM_ROLE, None)
        self.find_count.setText(f"{hits} match{'es' if hits != 1 else ''}" if hits else "Nothing in this view matches")

    def show_keys(self) -> None:
        """F1: every key, in one list (mods log round 2, M0036)."""
        self.run_dialog(KeyMapDialog(self, self.ctx.settings.hotkey))

    def _level(self, nodes: list[Node], direction: str) -> None:
        self.open = collapse_level(nodes, self.open) if direction == "collapse" else expand_level(nodes, self.open)
        self.render_list()

    def _expanded(self, item, on: bool) -> None:
        if self.tree.is_building:
            return
        key = item.data(0, KEY_ROLE)
        if self.view != "tasks":  # release 5.24: a row folded by hand stays folded when the view is drawn again
            (self.shut.setdefault(self.view, set()).discard if on else self.shut.setdefault(self.view, set()).add)(self._row_id(item))
            self._sync_level_buttons()
        elif key and key[0] == "task":
            (self.open.add if on else self.open.discard)(key[1])

    # ---- Collapse a level and Expand a level, on every view whose rows nest (release 5.24) ----
    @staticmethod
    def _row_id(item):
        return item.data(0, KEY_ROLE) or ("row", item.data(0, HTML_ROLE))

    def _level_button(self, expand: bool, clicked: Callable[[], None], enabled: bool = True) -> QPushButton:
        """Collapse a level or Expand a level. Two icon buttons in the new look, which often were the reason a bar wrapped (release 5.59)."""
        name, sign, tip_text = ("Expand a level", "+", "Open every branch one more level") if expand else ("Collapse a level", "−", "Fold every branch up one level")
        if LOOK.classic:
            return self._button(f"{sign} {name}", clicked, enabled, tip_text)
        b = self._button("", clicked, enabled, f"{name}: {tip_text.lower()}")
        b.setObjectName("iconOnly")
        b.setIcon(icon("level-open" if expand else "level-fold"))
        b.setAccessibleName(name)
        return b

    def _level_buttons(self) -> None:
        self._lvl_collapse = self._level_button(False, lambda: self._tree_level(False))
        self._lvl_expand = self._level_button(True, lambda: self._tree_level(True))

    def _branches(self) -> list:
        """The rows you can see that have rows under them."""
        return [item for item in self.tree.items() if item.childCount() and not item.isHidden() and self.tree.is_shown(item)]

    def _tree_level(self, expand: bool) -> None:
        """As the task tree's: Collapse a level closes every open row none of whose rows is open, so each branch folds up one
        step; Expand a level opens every folded row you can see."""
        rows = self._branches()
        if expand:
            targets = [x for x in rows if not x.isExpanded()]
        else:
            targets = [x for x in rows if x.isExpanded() and not any(
                x.child(i).childCount() and x.child(i).isExpanded() for i in range(x.childCount()))]
        for item in targets:
            item.setExpanded(expand)  # each one's signal keeps it in self.shut
        self._sync_level_buttons()

    def _sync_level_buttons(self) -> None:
        for name in ("_lvl_collapse", "_lvl_expand"):
            b = getattr(self, name, None)
            if b is None or b.parent() is None:
                return
        rows = self._branches()
        self._lvl_collapse.setEnabled(any(x.isExpanded() for x in rows))
        self._lvl_expand.setEnabled(any(not x.isExpanded() for x in rows))
        if not LOOK.classic:  # gone where nothing nests
            self._lvl_collapse.setVisible(bool(rows))
            self._lvl_expand.setVisible(bool(rows))

    def _apply_shut(self) -> None:
        """Fold again the rows folded by hand in this view."""
        shut = self.shut.get(self.view)
        if not shut:
            return
        with self.tree.building():
            for item in self.tree.items():
                if item.childCount() and self._row_id(item) in shut:
                    item.setExpanded(False)

    def _group_box(self, view_id: str) -> str | None:
        """The lists' Group by (release 5.9, M0051): a parent label, putting each task under its sublabel's heading. Shown
        when there's a parent label. Returns the parent label picked, if any."""
        m = self.model()
        parents = [lb.name for lb in m.active_labels() if m.is_parent_label(lb.name)]
        if not parents:
            return None
        box = QComboBox()
        box.setAccessibleName("Group by")
        box.addItem("No grouping", "")
        for name in parents:
            box.addItem(f"Group by {name}", name)
        picked = self.list_groups.get(view_id, "")
        box.setCurrentIndex(max(0, box.findData(picked)))
        box.setToolTip("Put each task under its sublabel's heading")
        box.currentIndexChanged.connect(lambda _: self._set_list_group(view_id, box.currentData()))
        self._filter_widget(box)
        return picked if picked in parents else None

    def _set_list_group(self, view_id: str, parent: str) -> None:
        self.list_groups[view_id] = parent
        self.render_list()

    def _grouped_list(self, view_id: str, parent: str, nodes: list[Node]) -> None:
        """A list grouped by a parent label: its matching tasks under each sublabel, then "No …" last."""
        m = self.model()
        order: list[str] = []

        def walk(ns: list[Node]) -> None:
            for n in ns:
                if n.match and n.id not in order:
                    order.append(n.id)
                walk(n.children)

        walk(nodes)
        subs = m.sublabels(parent)
        grey = group_ground()
        for name, ids in [*((s, [x for x in order if any(n == s for n, _ in m.labels_of(x))]) for s in subs),
                          (f"No {parent.lower()}", [x for x in order if not any(n in subs for n, _ in m.labels_of(x))])]:
            if not ids:
                continue
            self.tree.add_row(None, None, [f"<b>{esc(name)}</b> &nbsp;<span class=\"sub\">{len(ids)}</span>"], grey, selectable=False, span=True)
            for x in ids:
                self.tree.add_row(None, ("task", x), self._task_cells(x, 0), tip=full_path(m, x))
        if not order:
            self.tree.add_row(None, None, ['<span class="sub">Nothing here right now.</span>'], selectable=False, span=True)

    def _matching(self, task_list):
        from docrepo.lists import list_tasks

        return list_tasks(self.model(), task_list, self.today(), self.ctx.settings.me)

    # ================= the detail pane =================
    def _clear_actions(self) -> None:
        _empty(self.actions_layout)
        self.keytips.clear("actions")

    def _action(self, label: str, clicked: Callable[[], None] | None = None, tip: str = "", enabled: bool = True,
                menu: QMenu | None = None, primary: bool = False, icon_name: str | None = None, key: str = "", drop: bool = False) -> QPushButton:
        """A command on the detail pane's bar. In the new look it's a subtle button with an icon and its key in the tooltip
        (and under Alt); in the Classic look the key is in its label. ``primary`` is the page's main command: neutral, not
        subtle, as New capture is the window's one accent button (the review's decision V2). ``drop`` gives it a chevron."""
        if LOOK.classic and key:
            label = f"{label}   {key}"
        name = "primary" if primary and LOOK.classic else "" if primary or LOOK.classic else "subtle"
        b = DropButton(label) if drop else QPushButton(label)
        b.setObjectName(name)
        b.setToolTip(f"{tip} ({key})" if key and tip and not LOOK.classic else tip)
        if icon_name and not LOOK.classic:
            b.setIcon(icon(icon_name))
        if menu is not None and not LOOK.classic:
            b.setProperty("menu", True)
        if key and not LOOK.classic:
            self.keytips.add(b, key, group="actions")
        b.setEnabled(enabled)
        if menu is not None:
            b.setMenu(menu)
        elif clicked is not None:
            b.clicked.connect(lambda _=False: clicked())
        self.actions_layout.addWidget(b)
        b.show()
        return b

    def _split_action(self, label: str, clicked: Callable[[], None], tip: str, menu: QMenu, menu_tip: str,
                      icon_name: str | None = None, key: str = "") -> tuple[QPushButton, QPushButton]:
        """A split button on the bar (the task page's Edit, decision 392): its words do the main command, and the chevron
        beside them, its accessible name ``menu_tip``'s first words, opens ``menu``. The two sit together as one."""
        box = QWidget(self.actions)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        main = QPushButton(f"{label}   {key}" if LOOK.classic and key else label, box)
        main.setObjectName("" if LOOK.classic else "subtle")
        main.setToolTip(f"{tip} ({key})" if key and not LOOK.classic else tip)
        if icon_name and not LOOK.classic:
            main.setIcon(icon(icon_name))
        if key and not LOOK.classic:
            self.keytips.add(main, key, group="actions")
        main.clicked.connect(lambda _=False: clicked())
        chevron = QPushButton("", box)
        chevron.setObjectName("" if LOOK.classic else "iconOnly")
        chevron.setIcon(icon("chevron-down"))
        chevron.setToolTip(menu_tip)
        chevron.setAccessibleName(menu_tip.split(":")[0])
        chevron.setMenu(menu)
        lay.addWidget(main)
        lay.addWidget(chevron)
        self.actions_layout.addWidget(box)
        box.show()
        return main, chevron
