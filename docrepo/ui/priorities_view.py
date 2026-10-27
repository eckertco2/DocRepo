"""The browse tool's Priorities board (mods log round 2, M0029, M0030; release 5.23, decisions 23 and 74 to 78).

The open tasks as cards, in a column per bucket, Not ranked first. Drag a card to another column, or up and down in its
own (Not ranked sorts itself, so a card dropped there just leaves its bucket). Or with the keys written on each column's
header: 1 to 4 put the selected card at the end of that bucket and 0 takes it out, Alt+Up and Alt+Down move it within its
bucket, the arrow keys move between cards, and Enter opens the task. Double-clicking a card opens Edit task. The board
only says what was asked for (``moved``, ``nudged``); the browse window makes the change and draws the board again.
Like the timeline, it takes the middle and right panes together. ``docrepo/priorities.py`` has the rules.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from docrepo import priorities
from docrepo.detail import esc
from docrepo.model import Model, Task
from docrepo.stories import clip
from docrepo.ui import tokens
from docrepo.ui.look import Help
from docrepo.ui.widgets import CheckMenuButton, FlowLayout, label_filter, people_filter
from docrepo.views import due_cell, find_text, path_text

#: A dragged card carries its task's ID.
MIME = "application/x-docrepo-task"
#: A state's chip colours, as the pages draw them.
STATE_COLOURS = {"In progress": ("accent", "selected"), "Not started": ("text2", "hover"), "Parked": ("text2", "hover"), "Closed": ("text2", "hover")}


def _chip(text: str, fg: str, bg: str, bold: bool = False) -> str:
    """A chip for a label: its colours inline, since a label doesn't have the pages' style sheet."""
    weight = " font-weight:600;" if bold else ""
    return f'<span style="color:{tokens.colour(fg)}; background-color:{tokens.colour(bg)};{weight}">&nbsp;{esc(text)}&nbsp;</span>'


def _urgent() -> str:
    return _chip("Urgent", "critical", "critical_bg", True)


NOTE = ("Click a card to see it here. Drag cards between columns, or use the keys on the column headers: 1 to 4 and 0 move the "
        "selected card, Alt+Up and Alt+Down move it within its column, the arrow keys move between cards, and Enter opens the task.")


class Card(QFrame):
    """A task's card: its title, its path, and a line of facts (Urgent, the due date, its people, its open subtasks), with
    its top-level task's colour down its left edge."""

    def __init__(self, view: "PrioritiesView", t: Task, colour: str, facts: str, path: str, selected: bool) -> None:
        super().__init__(objectName="prCard")
        self.view, self.task_id, self.colour = view, t.id, colour
        self.setProperty("sel", selected)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName(f"{t.title}, {priorities.name(t.priority)}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(2)
        title = QLabel(esc(t.title), objectName="prTitle")
        title.setWordWrap(True)
        lay.addWidget(title)
        if path:
            p = QLabel(esc(path), objectName="fieldLabel")
            p.setWordWrap(True)
            lay.addWidget(p)
        if facts:
            f = QLabel(facts)
            f.setWordWrap(True)
            f.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(f)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._press: QPoint | None = None
        self.installEventFilter(view)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(0, 1, 3, self.height() - 2, QColor(self.colour))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.view.pick(self.task_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, QByteArray(self.task_id.encode("ascii")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        self.view.dragging = self.task_id
        drag.exec(Qt.DropAction.MoveAction)
        self.view.dragging = None

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - opens Edit task, as a double-click does since release 5.17
        self.view.edit_task.emit(self.task_id)


class Column(QFrame):
    """A bucket's column: its key, name and count, then its cards. A card dropped on it goes where the line shows, before
    the card under the pointer's middle, or at the end; Not ranked has no order, so there's no line."""

    def __init__(self, view: "PrioritiesView", col: priorities.Column) -> None:
        super().__init__(objectName="prCol")
        self.view, self.key = view, col.key
        self.setAcceptDrops(True)
        self.setAccessibleName(col.name)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        key = QLabel(col.digit, objectName="hotkey")
        key.setToolTip(f"Press {col.digit} to move the selected card {'out of its bucket' if not col.key else 'here'}")
        head.addWidget(key)
        head.addWidget(QLabel(f"<b>{esc(col.name)}</b>"))
        head.addStretch(1)
        head.addWidget(QLabel(str(len(col.ids)), objectName="count"))
        lay.addLayout(head)
        if not col.key:
            note = QLabel("Sorted for you: urgent first, then the soonest due.", objectName="fieldLabel")
            note.setWordWrap(True)
            lay.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="prCards")
        self.cards_layout = QVBoxLayout(body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards: list[Card] = []
        for task_id in col.ids:
            card = view.make_card(task_id)
            self.cards.append(card)
            self.cards_layout.addWidget(card)
        if not col.ids:
            empty = QLabel("Drop a card here", objectName="fieldLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(empty)
        self.cards_layout.addStretch(1)
        self.line = QFrame(objectName="prDrop")
        self.line.setFixedHeight(3)
        self.line.hide()
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

    def _spot(self, y_in_column: int) -> Card | None:
        """The card a drop at this height lands before: the first whose middle is below the pointer."""
        for card in self.cards:
            if card.task_id == self.view.dragging:
                continue
            middle = card.mapTo(self, QPoint(0, card.height() // 2)).y()
            if y_in_column < middle:
                return card
        return None

    def _show_line(self, before: Card | None) -> None:
        self.cards_layout.removeWidget(self.line)
        if not self.key:
            self.line.hide()
            return
        at = self.cards_layout.indexOf(before) if before is not None else len(self.cards)
        self.cards_layout.insertWidget(at, self.line)
        self.line.show()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            self.setProperty("over", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            self._show_line(self._spot(event.position().toPoint().y()))
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._end_drag()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(MIME):
            return
        task_id = bytes(event.mimeData().data(MIME).data()).decode("ascii")
        before = self._spot(event.position().toPoint().y()) if self.key else None
        self._end_drag()
        event.acceptProposedAction()
        self.view.drop(task_id, self.key, before.task_id if before else None)

    def _end_drag(self) -> None:
        self.line.hide()
        self.setProperty("over", False)
        self.style().unpolish(self)
        self.style().polish(self)


class PrioritiesView(QWidget):
    """The Priorities view: its filters, the card for the selected task with the buckets as buttons, and the board.
    ``picked`` sends the task a click selects, ``open_task`` one to open, ``edit_task`` one to edit, ``moved`` a task with
    the bucket it goes to ("" for Not ranked) and the task it goes before (or None, the end), and ``nudged`` a task and a
    step (-1 up, +1 down) with the IDs shown in its column."""

    picked = Signal(str)
    open_task = Signal(str)
    edit_task = Signal(str)
    moved = Signal(str, str, object)
    nudged = Signal(str, int, list)

    def __init__(self) -> None:
        super().__init__()
        self.model: Model | None = None
        self.today = date.today()
        self.me: str | None = None
        self.sel: str | None = None
        self.people: list[str] = []
        self.labels: list[str] = []
        self.due = "any"
        self.routine = False
        self.fold = False
        self.dragging: str | None = None
        self.columns: list[priorities.Column] = []
        self.cards: dict[str, Card] = {}
        self._colours: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(8)
        self.title = QLabel(objectName="paneTitle")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.title)
        lay.addWidget(Help("Open tasks by priority. Rank them by dragging, or with the keys on each column. A move to another column "
                           "goes into the task's status log. Urgent stays a flag of its own; parked, closed and routine tasks aren't here."))
        self.controls = QWidget()
        self.controls_layout = FlowLayout(self.controls, spacing=8)
        lay.addWidget(self.controls)
        # Find on the board (release 5.24): Ctrl+F, as Find in this view elsewhere; it narrows the cards as you type, and
        # Esc clears it.
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find on the board")
        self.find_box.setAccessibleName("Find in this view")
        self.find_box.setToolTip("Find in this view: a card stays when its task holds every word. Esc clears it. (Ctrl+F)")
        self.find_box.textChanged.connect(lambda _: self.model is not None and self.render(self.model, self.today, self.sel, self.me))
        self.find_box.installEventFilter(self)
        fb.addWidget(self.find_box, 1)
        self.find_count = QLabel(objectName="paneNote")
        fb.addWidget(self.find_count)
        self.find_bar.hide()
        lay.addWidget(self.find_bar)
        self.strip = QFrame(objectName="fileRow")
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)
        self.strip_text = QLabel()
        self.strip_text.setWordWrap(True)
        self.strip_text.setTextFormat(Qt.TextFormat.RichText)
        sl.addWidget(self.strip_text)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.buckets = QWidget(objectName="typeStrip")
        self.buckets.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        bl = QHBoxLayout(self.buckets)
        bl.setContentsMargins(2, 2, 2, 2)
        bl.setSpacing(2)
        self.bucket_group = QButtonGroup(self)
        self.bucket_group.setExclusive(True)
        self.bucket_buttons: dict[str, QPushButton] = {}
        for key, label, digit in priorities.COLUMNS:
            b = QPushButton(f"{digit}  {label}", objectName="subtle")
            b.setCheckable(True)
            b.setToolTip(f"{label} ({digit})")
            b.clicked.connect(lambda _=False, k=key: self.sel and self.moved.emit(self.sel, k, None))
            self.bucket_group.addButton(b)
            self.bucket_buttons[key] = b
            bl.addWidget(b)
        row.addWidget(self.buckets)
        row.addStretch(1)
        self.open_button = QPushButton("Open task", objectName="primary")
        self.open_button.clicked.connect(lambda: self.sel and self.open_task.emit(self.sel))
        self.edit_button = QPushButton("Edit")
        self.edit_button.setToolTip("Edit task (E)")
        self.edit_button.clicked.connect(lambda: self.sel and self.edit_task.emit(self.sel))
        row.addWidget(self.open_button)
        row.addWidget(self.edit_button)
        sl.addLayout(row)
        lay.addWidget(self.strip)
        self.board = QWidget()
        self.board_layout = QHBoxLayout(self.board)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setSpacing(8)
        lay.addWidget(self.board, 1)

    # ---- drawing ----
    def render(self, model: Model, today: date, sel: str | None, me: str | None = None) -> None:
        """Draw the board again from the model, keeping its filters, and the focus on the selected card if it had it."""
        had_focus = isinstance(QApplication.focusWidget(), Card)  # not while typing in Find
        self.model, self.today, self.me = model, today, me
        tops = [t.id for t in model.top_level() if not t.discarded]
        self._colours = {}
        for t in model.tasks.values():
            top = model.chains_of(t.id)[0][0]
            self._colours[t.id] = tokens.group_colour(tops.index(top)) if top in tops else tokens.group_colour(-1)
        f = priorities.BoardFilter(tuple(self.people), tuple(self.labels), self.due, self.routine, self.fold)
        self.columns = priorities.columns(model, today, f)
        words = self.find_box.text().lower().split() if not self.find_bar.isHidden() else []
        if words:  # every word in the task's ID, title, description, status, labels, people or path
            for col in self.columns:
                col.ids = [x for x in col.ids if all(w in find_text(model, x) + " " + path_text(model, x).lower() for w in words)]
            hits = sum(len(c.ids) for c in self.columns)
            self.find_count.setText(f"{hits} match{'es' if hits != 1 else ''}" if hits else "Nothing on the board matches")
        else:
            self.find_count.clear()
        shown = {x for c in self.columns for x in c.ids}
        self.sel = sel if sel in shown else None
        self._controls()
        n, unranked = len(shown), len(self.columns[0].ids)
        self.title.setText(f'Priorities&nbsp;&nbsp;<span style="color:{tokens.colour("text2")}; font-size:{tokens.CAPTION}pt; font-weight:400">'
                           f'{n} open task{"" if n == 1 else "s"}{f", {unranked} not ranked" if unranked else ""}</span>')
        self._strip()
        while self.board_layout.count():
            w = self.board_layout.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.cards = {}
        for col in self.columns:
            self.board_layout.addWidget(Column(self, col), 1)
        if had_focus and self.sel in self.cards:
            self.cards[self.sel].setFocus(Qt.FocusReason.OtherFocusReason)

    def make_card(self, task_id: str) -> Card:
        m = self.model
        assert m is not None
        t = m.task(task_id)
        bits = []
        if t.urgent:
            bits.append(_urgent())
        d = due_cell(t, self.today)
        if d:
            colour = tokens.colour("critical") if d.cls == "over" else tokens.colour("caution") if d.cls == "soon" else tokens.colour("text2")
            bits.append(f'<span style="color:{colour}">{esc(d.text)}</span>')
        who = ", ".join("Me" if p == self.me else m.person_name(p).split()[0] for p in dict.fromkeys((*t.leads, *t.assignees)))
        if who:
            bits.append(f'<span style="color:{tokens.colour("text2")}">{esc(who)}</span>')
        kids = len(priorities.open_subtasks(m, t.id))
        shut = priorities.folded_under(m, t.id) if self.fold else 0
        if kids:
            text = f"{shut} subtask{'' if shut == 1 else 's'} folded" if shut == kids else \
                f"{kids} open subtask{'' if kids == 1 else 's'}" + (f", {shut} folded" if shut else "")
            if shut:  # what the folded ones are ranked, so a Critical subtask isn't lost from sight
                ranked = [priorities.name(m.task(c).priority) for c in priorities.open_subtasks(m, t.id)
                          if m.task(c).priority and priorities.folded(m, m.task(c))]
                counts = [f"{ranked.count(n)} {n}" for _, n, _ in priorities.BUCKETS if n in ranked]
                text += f" ({', '.join(counts)})" if counts else ""
            bits.append(f'<span style="color:{tokens.colour("text2")}">{text}</span>')
        card = Card(self, t, self._colours.get(t.id, tokens.group_colour(-1)), " &nbsp;".join(bits), path_text(m, t.id), t.id == self.sel)
        self.cards[task_id] = card
        return card

    def _controls(self) -> None:
        lay = self.controls_layout
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:  # hidden now, deleted once the signal that redraws the view has returned
                w.hide()
                w.deleteLater()
        m = self.model
        assert m is not None
        choices, sets = people_filter(m)
        people = CheckMenuButton("People", "anyone", choices, self.people, sets)
        people.chosen.connect(lambda values: self._set("people", values))
        lay.addWidget(people)
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, self.labels, sets)
        labels.chosen.connect(lambda values: self._set("labels", values))
        lay.addWidget(labels)
        due = QComboBox()
        due.setAccessibleName("Due")
        for key, label in priorities.DUE_CHOICES:
            due.addItem(f"Due: {label.lower() if key != 'any' else 'any time'}", key)
        due.setCurrentIndex(max(0, due.findData(self.due)))
        due.currentIndexChanged.connect(lambda _: self._set("due", due.currentData()))
        lay.addWidget(due)
        routine = QCheckBox("Show routine")
        routine.setToolTip("Recurring tasks, such as meetings and reports")
        routine.setChecked(self.routine)
        routine.toggled.connect(lambda on: self._set("routine", on))
        lay.addWidget(routine)
        fold = QCheckBox("Fold subtasks")
        fold.setToolTip("Only parent and top-level tasks: a subtask with no open subtasks of its own folds into its parent's card")
        fold.setChecked(self.fold)
        fold.toggled.connect(lambda on: self._set("fold", on))
        lay.addWidget(fold)

    def _set(self, key: str, value) -> None:
        setattr(self, key, value)
        if self.model is not None:
            self.render(self.model, self.today, self.sel, self.me)

    def _strip(self) -> None:
        """The selected card, above the board: where it sits, its dates and people, its status, and the buckets."""
        m = self.model
        t = m.tasks.get(self.sel) if m and self.sel else None
        for w in (self.buckets, self.open_button, self.edit_button):
            w.setVisible(t is not None)
        muted = tokens.colour("text2")
        if t is None or m is None:
            self.strip_text.setText(f'<span style="color:{muted}">{esc(NOTE)}</span>')
            return
        cell = due_cell(t, self.today)
        when = esc(cell.tip) if cell else "No due date"

        def names(ids: list[str]) -> str:
            return ", ".join(esc(m.person_name(p)) for p in ids) or "None"

        status = f'<br><span style="color:{muted}">Status: {esc(clip(t.current_status, 160))}</span>' if t.current_status else ""
        self.strip_text.setText(f"<b>{esc(t.title)}</b> {_chip(t.state, *STATE_COLOURS.get(t.state, ('text2', 'hover')))}{' ' + _urgent() if t.urgent else ''}"
                                f'<br><span style="color:{muted}">{esc(path_text(m, t.id) or "Top-level task")}</span>'
                                f"<br>{when} · Lead: {names(t.leads)} · Assignees: {names(t.assignees)}{status}")
        self.bucket_buttons[t.priority or ""].setChecked(True)

    # ---- choosing and moving ----
    def pick(self, task_id: str) -> None:
        if task_id == self.sel:
            return
        old, self.sel = self.sel, task_id
        for x in (old, task_id):
            card = self.cards.get(x or "")
            if card is not None:
                card.setProperty("sel", x == task_id)
                card.style().unpolish(card)
                card.style().polish(card)
        self._strip()
        self.picked.emit(task_id)

    def focus_card(self, task_id: str | None) -> None:
        if task_id and task_id in self.cards:
            self.pick(task_id)
            self.cards[task_id].setFocus(Qt.FocusReason.OtherFocusReason)

    def drop(self, task_id: str, bucket: str, before: str | None) -> None:
        self.sel = task_id
        self.moved.emit(task_id, bucket, before)

    def _column_of(self, task_id: str) -> int:
        return next((i for i, c in enumerate(self.columns) if task_id in c.ids), -1)

    # ---- Find on the board ----
    def open_find(self) -> None:
        """Ctrl+F: the box above the board, which narrows it as you type."""
        self.find_bar.show()
        self.find_box.setFocus()
        self.find_box.selectAll()

    def close_find(self, render: bool = True) -> None:
        """Esc in the box, or another view: clear it, and the board shows every card again."""
        had = bool(self.find_box.text())
        self.find_box.blockSignals(True)
        self.find_box.clear()
        self.find_box.blockSignals(False)
        self.find_bar.hide()
        self.find_count.clear()
        if render and had and self.model is not None:
            self.render(self.model, self.today, self.sel, self.me)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - the keys, on a card
        if watched is self.find_box and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
            self.close_find()
            card = self.cards.get(self.sel or "")
            (card or self).setFocus()
            return True
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, Card):
            self.pick(watched.task_id)
        if event.type() == QEvent.Type.KeyPress and isinstance(watched, Card):
            return self.key(event.key(), event.modifiers())  # type: ignore[attr-defined]
        return super().eventFilter(watched, event)

    def key(self, key: int, mods) -> bool:
        """The board's keys, for the selected card. True when one was used."""
        if not self.sel:
            return False
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        digit = {Qt.Key.Key_0: "0", Qt.Key.Key_1: "1", Qt.Key.Key_2: "2", Qt.Key.Key_3: "3", Qt.Key.Key_4: "4"}.get(key)
        if digit is not None and not alt:
            self.moved.emit(self.sel, priorities.BY_DIGIT[digit], None)
            return True
        ci = self._column_of(self.sel)
        if ci < 0:
            return False
        ids = self.columns[ci].ids
        ri = ids.index(self.sel)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            if alt:
                if self.columns[ci].key:
                    self.nudged.emit(self.sel, step, list(ids))
                return True
            if 0 <= ri + step < len(ids):
                self.focus_card(ids[ri + step])
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not alt:
            step = -1 if key == Qt.Key.Key_Left else 1
            j = ci + step
            while 0 <= j < len(self.columns):  # the nearest card at the same height in the next column that has any
                if self.columns[j].ids:
                    self.focus_card(self.columns[j].ids[min(ri, len(self.columns[j].ids) - 1)])
                    break
                j += step
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_task.emit(self.sel)
            return True
        return False
