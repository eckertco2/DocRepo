"""Items and meeting notes in the capture window (mods log round 2, M0048 phase 2, M0049, M0052; release 5.8).

- ``OperatorHighlighter`` colours the content text's operators and tints each line by the item it makes. Its colours
  are shown, never saved: they're not part of the text's formatting.
- ``ItemCards``: a card for each item, beside the content text. Untick one to skip it, or change its title or due
  date: the change stays, even when its line is edited later.
- ``AgendaPanel``: the meeting's open agenda items, each ticked once it's discussed, and Start from the agenda.
- ``RefPopup``: the list @ and # open while typing, narrowing as you type.

Ported from the mockup's ``items.js`` and ``capture.js``. ``docrepo.items`` reads the operators.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from html import escape as esc

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from docrepo import items
from docrepo.dates import long_date, short
from docrepo.model import AgendaItem, Model
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK, Help
from docrepo.ui.widgets import DateField

#: Each line's tint, by the part it plays: the item it makes, the new task's own line, or a heading.
TINTS = {"task": "#e3ecf7", "note": "#e0f1ee", "update": "#f6ecd8", "decision": "#ece6f6", "date": "#e8f0dc", "param": "#e8f0dc", "heading": "#e9edf1"}
#: The operators' colours: (text, background).
REF_COLOURS = {"person": ("#1d5e98", "#dbe8f5"), "new": ("#875700", "#fcefcf"), "none": ("#5a6571", "#e9edf1"),
               "task": ("#22706a", "#d6eeea"), "type": ("#875700", "#fcefcf")}


class OperatorHighlighter(QSyntaxHighlighter):
    """Colours the operators and tints the lines of the content text, from the last ``items.read``."""

    def __init__(self, doc: QTextDocument) -> None:
        super().__init__(doc)
        self.reading: items.Reading | None = None
        self.kinds: dict[int, str] = {}

    def set_reading(self, reading: items.Reading | None) -> None:
        self.reading = reading
        self.kinds = items.line_kinds(reading) if reading else {}
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt's name
        r = self.reading
        n = self.currentBlock().blockNumber()
        if not r or n >= len(r.lines):
            return
        line = r.lines[n]
        tint = TINTS.get(self.kinds.get(n, ""))
        if tint:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(tint))
            self.setFormat(0, len(text), fmt)
        # A list item made with the list buttons has no "- " in its text; one typed as text has.
        base = 0 if self.currentBlock().textList() is not None else line.off
        for x in line.toks:
            key = "type" if x.kind in ("type", "param") else "task" if x.kind == "task" else "none" if x.none else "new" if x.is_new else "person"
            fg, bg = REF_COLOURS[key]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(fg))
            fmt.setBackground(QColor(bg))
            if key == "new":
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DashUnderline)
                fmt.setUnderlineColor(QColor(fg))
            self.setFormat(base + x.start, x.end - x.start, fmt)


def _drop(layout) -> None:
    """Empty a layout at once: its widgets leave the window now, not when Qt gets round to deleting them."""
    while layout.count():
        w = layout.takeAt(0).widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()


def _pretty(text: str) -> str:
    """A parameter's words with its dates as you'd read them: "Due is already Fri 30 Oct"."""
    today = date.today()

    def one(m: re.Match[str]) -> str:
        try:
            return long_date(date.fromisoformat(m.group(0)), today)
        except ValueError:
            return m.group(0)  # a reference number that only looks like a date

    return re.sub(r"\d{4}-\d{2}-\d{2}", one, text)


def _facts(it: items.Item, where: str) -> str:
    who = lambda xs: ", ".join(x.name + (" (new)" if x.is_new else "") for x in xs)  # noqa: E731
    out = []
    if it.kind == "task":
        out.append(f"For {who(it.assignees)}" if it.assignees else "No one yet" if it.none else "")
        out.append(f"lead {who(it.leads)}" if it.leads else "no lead")
        if it.deadline:
            day = date.fromisoformat(it.deadline)
            out.append(f"deadline {short(day, day)}")
        if it.labels:
            out.append(", ".join(it.labels))
        if it.assignee_hours or it.lead_hours:
            out.append(f"{it.assignee_hours or it.lead_hours} h")
        out.append(f"under {where}")
    elif it.kind == "param":  # whose field it fills (release 5.38)
        if it.where:
            out.append(f"on {where}")
    elif it.kind == "date" and it.key_date:  # a key date (release 5.31): its dates, its ticks, and whose it is
        kd = it.key_date
        a, b = (date.fromisoformat(kd.start) if kd.start else None), (date.fromisoformat(kd.end) if kd.end else None)
        today = date.today()  # the year shows when it isn't this year's
        out.append(f"on {short(a, today)}" if a and a == b else f"{short(a, today)} to {short(b, today)}" if a and b
                   else f"from {short(a, today)}" if a else f"by {short(b, today)}" if b else "")
        out += ["plant activity" * kd.plant, "deadline" * kd.deadline]
        if it.where:
            out.append(f"on {where}")
    elif it.where:
        out.append(f"{'updates' if it.kind == 'update' else 'on'} {where}" + (f": {it.state}" if it.state else ""))
    return " · ".join(x for x in out if x)


def task_colour(m: Model, task_id: str | None) -> str:
    """A task's top-level task's colour: the task tree's group colours, in turn, as the timeline gives them (decision 9)."""
    if not task_id or task_id not in m.tasks:
        return tokens.colour("stroke_strong")
    top = m.chains_of(task_id)[0][0]
    order = [t.id for t in m.top_level()]
    return tokens.group_colour(order.index(top)) if top in order else tokens.colour("stroke_strong")


class ItemCard(QFrame):
    """One item: tick, kind, its line, its title, what was read from it, and a task's due date. In the new look its edge is
    its top-level task's colour, and its kind is an icon and a word (decision 9)."""

    changed = Signal(str, str, object)  # key, "off", "title" or "due", value
    go = Signal(int)  # show its line in the content text

    def __init__(self, it: items.Item, where: str, stripe: str | None = None) -> None:
        super().__init__(objectName="itemCard")
        self.key = it.key
        self.setProperty("kind", it.kind if it.on else "off")  # its left edge's colour (style.py)
        if stripe and not LOOK.classic:
            self.setStyleSheet(f"QFrame#itemCard {{ border-left: 3px solid {stripe if it.on else tokens.colour('stroke_strong')}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 6, 6)
        lay.setSpacing(3)
        top = QHBoxLayout()
        name = "Plant event" if it.plant_event else it.label or items.KIND_NAMES[it.kind]
        self.tick = QCheckBox(name + (f": {it.state}" if it.state else ""))
        if not LOOK.classic:
            self.tick.setIcon(icon("task" if it.kind == "task" else "calendar" if it.kind == "date"
                                   else it.kind if it.kind in ("note", "update", "decision") else "note"))
        self.tick.setChecked(it.on)
        self.tick.setEnabled(not it.problem)
        self.tick.setToolTip("Untick to skip it")
        self.tick.toggled.connect(lambda on: self.changed.emit(self.key, "off", not on))
        top.addWidget(self.tick)
        if it.changed:
            top.addWidget(QLabel("changed here", objectName="hint"))  # state, not help
        top.addStretch()
        line = QPushButton(f"line {it.line + 1}", objectName="link")
        line.setToolTip("Show its line in the content text")
        line.clicked.connect(lambda: self.go.emit(it.line))
        top.addWidget(line)
        lay.addLayout(top)
        self.title = QLineEdit(_pretty(it.title) if it.kind == "param" else it.title)
        self.title.setAccessibleName(f"{name} title")
        self.title.setEnabled(it.on)
        self.title.setReadOnly(it.kind == "param")  # a field's value is read from its line, and changed there
        self.title.textEdited.connect(lambda text: self.changed.emit(self.key, "title", text))
        lay.addWidget(self.title)
        facts = QLabel(_facts(it, where) + (f"  <b style='color:#b0261e'>{esc(_pretty(it.problem))}</b>" if it.problem else ""), objectName="hint")
        facts.setWordWrap(True)
        facts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(facts)
        self.due: DateField | None = None
        if it.kind == "task":
            row = QHBoxLayout()
            row.addWidget(QLabel("Due", objectName="hint"))
            self.due = DateField()
            self.due.set_value(it.due)
            self.due.setEnabled(it.on)
            self.due.edited.connect(lambda: self.changed.emit(self.key, "due", self.due.value() or ""))
            row.addWidget(self.due, 1)
            lay.addLayout(row)


class ItemCards(QFrame):
    """A card for each item, beside the content text."""

    changed = Signal(str, str, object)
    go = Signal(int)

    def __init__(self) -> None:
        super().__init__(objectName="items")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Items</b>"))
        self.info_slot = head  # the capture window adds the "i" button here
        head.addStretch()
        self.count = QLabel(objectName="hint")
        head.addWidget(self.count)
        lay.addLayout(head)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(6)
        lay.addLayout(self.cards_box)
        self.hint = Help()  # what the operators do, and how the cards work: with Show hints (decision 7)
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.hint)
        self.cards: list[ItemCard] = []

    def editing(self) -> bool:
        """Whether a card's title or due date has the keyboard: the cards aren't rebuilt under you."""
        w = self.focusWidget()
        return w is not None and isinstance(w, QLineEdit) and self.isAncestorOf(w)

    def show_items(self, r: items.Reading | None, own: items.SelfFields | None, where_text: Callable[[items.Item], str], names: items.Names,
                   stripe: Callable[[items.Item], str] | None = None) -> None:
        _drop(self.cards_box)
        self.cards = []
        its = r.items if r else []
        if own and own.any:
            box = QFrame(objectName="itemCard")
            box.setProperty("kind", "self")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 5, 6, 6)
            bl.addWidget(QLabel("<b>The new task</b>  <span style='color:#5a6571'>its first line</span>"))
            said = [f"Assignees: {', '.join(x.name for x in own.assignees)}" * bool(own.assignees),
                    f"Lead: {', '.join(x.name for x in own.leads)}" * bool(own.leads),
                    f"Also under: {', '.join(names.task_title(t) for t in own.tasks)}" * bool(own.tasks)]
            facts = QLabel(" · ".join(s for s in said if s), objectName="hint")
            facts.setWordWrap(True)
            bl.addWidget(facts)
            self.cards_box.addWidget(box)
        for it in its:
            card = ItemCard(it, where_text(it), stripe(it) if stripe else None)
            card.changed.connect(self.changed)
            card.go.connect(self.go)
            self.cards_box.addWidget(card)
            self.cards.append(card)
        on = [it for it in its if it.on]
        counts = [f"{n} {name.lower()}{'s' if n > 1 else ''}" for k, name in items.KIND_NAMES.items() if (n := sum(it.kind == k for it in on))]
        self.count.setText("Save makes " + _and(counts) if counts else "Nothing to make" if its else "")
        self.hint.setText(
            "Each line with an operator is a card. Untick one to skip it, or change its title or due date here: your change stays "
            "even when you edit the line." if its or (own and own.any) else
            "In any capture, <b>@Tom</b> makes a task for Tom, <b>@L.Tom</b> makes him its lead, <b>@__</b> a task for no one yet, "
            "<b>#Rigging plan</b> files a note to that task, and <b>**closed,</b>, <b>**u,</b>, <b>**n,</b>, <b>**t,</b>, <b>**decision,</b> "
            "or <b>**event,</b> say what a line is. <b>**due, 5 Nov.</b> or <b>**key date, trial run 1 to 5 Dec, plant activity.</b> fills in "
            "a field: any field, by its name. Type @ or # for a list.")
        self.setProperty("empty", not its and not (own and own.any))
        self.style().unpolish(self)
        self.style().polish(self)


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


class AgendaPanel(QFrame):
    """The meeting's open agenda items, each ticked once the notes discuss it, and Start from the agenda."""

    ticked = Signal(int, bool)  # agenda item ID, discussed
    start = Signal()

    def __init__(self) -> None:
        super().__init__(objectName="agendaPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        head = QHBoxLayout()
        self.title = QLabel()
        head.addWidget(self.title)
        self.info_slot = head
        head.addStretch()
        self.count = QLabel(objectName="hint")
        head.addWidget(self.count)
        lay.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(3)
        lay.addLayout(self.rows)
        row = QHBoxLayout()
        self.start_button = QPushButton("Start from the agenda")
        self.start_button.setToolTip("Put each open item in the notes: a task as a # heading, a note on its own as an “Agenda:” line")
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)
        row.addStretch()
        lay.addLayout(row)
        self.hint = Help()
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.hint)
        self.boxes: dict[int, QCheckBox] = {}

    def show_agenda(self, m: Model, meeting: str | None, open_items: list[AgendaItem], done: Callable[[AgendaItem], bool]) -> None:
        _drop(self.rows)
        self.boxes = {}
        if not meeting:
            self.title.setText("<b>Agenda</b>")
            self.count.setText("")
            self.hint.setText("A new meeting has no agenda yet. Pick a meeting at the top to work through its agenda here.")
            self.start_button.hide()
            return
        self.title.setText(f"<b>Agenda of {m.task(meeting).title}</b>")
        n = 0
        for a in open_items:
            text = (m.task(a.subject).title + (f"  ·  {a.note}" if a.note else "")) if a.subject else a.note
            box = QCheckBox(text)
            box.setToolTip("Ticked items close as Discussed when you save")
            box.setChecked(done(a))
            n += box.isChecked()
            box.toggled.connect(lambda on, i=a.id: self.ticked.emit(i, on))
            self.rows.addWidget(box)
            self.boxes[a.id] = box
        self.count.setText(f"{n} of {len(open_items)} discussed" if open_items else "No open items")
        self.start_button.setVisible(bool(open_items))
        self.hint.setText("Ticked items close as Discussed when you save. An item is ticked for you once its heading has notes under it."
                          if open_items else "")


class RefPopup(QListWidget):
    """The list @ and # open while typing the content text: Up and Down move, Enter or Tab picks, Esc closes it."""

    picked = Signal(object)  # the items.Option

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("refPopup")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(320)
        self.itemClicked.connect(lambda item: self.picked.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.hide()

    def show_options(self, options: list[items.Option], at: QPoint) -> None:
        self.clear()
        for o in options:
            item = QListWidgetItem(o.label + (f"    {o.sub}" if o.sub else ""))
            item.setData(Qt.ItemDataRole.UserRole, o)
            self.addItem(item)
        self.setCurrentRow(0)
        self.setFixedHeight(min(8, len(options)) * (self.sizeHintForRow(0) or 22) + 6)
        self.move(at)
        self.show()
        self.raise_()

    def handle_key(self, key: int) -> bool:
        """A key typed in the content text while the list is open; True when the list used it."""
        if not self.isVisible():
            return False
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.setCurrentRow((self.currentRow() + (1 if key == Qt.Key.Key_Down else -1)) % max(1, self.count()))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            item = self.currentItem() or self.item(0)
            if item:
                self.picked.emit(item.data(Qt.ItemDataRole.UserRole))
            return True
        if key == Qt.Key.Key_Escape:
            self.hide()
            return True
        return False


def where_text(it: items.Item, home: str, names: items.Names, r: items.Reading) -> str:
    """Where an item goes, in words: "Business team meeting 8 Oct and Reactor impeller upgrade"."""
    out = []
    for w in it.where:
        if w.kind == "quick":
            out.append("Quick tasks")
        elif w.kind == "home":
            out.append(home or "the capture's task")
        elif w.kind == "item":
            parent = next((x for x in r.items if x.key == w.ref), None)
            out.append(f"“{parent.title}”" if parent else "the task above")
        else:
            out.append(names.task_title(w.ref or ""))
    return _and(out)
