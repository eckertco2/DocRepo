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
from dataclasses import replace
from datetime import date
from html import escape as esc

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPen,
    QSyntaxHighlighter,
    QTextBlock,
    QTextBlockUserData,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import items
from docrepo.dates import long_date, short
from docrepo.model import AgendaItem, Model
from docrepo.ui import tokens
from docrepo.ui.tokens import C
from docrepo.ui.icons import icon, tinted
from docrepo.ui.look import LOOK, Help
from docrepo.ui.widgets import DateField, ElidedCheck, ElidedLabel

#: Each line's tint, by the part it plays: the item it makes, the new task's own line, or a heading.
TINTS = {"task": tokens.colour("item_task"), "note": tokens.colour("item_note"), "update": tokens.colour("item_update"), "decision": tokens.colour("item_decision"),
         "date": tokens.colour("item_date"), "param": tokens.colour("item_date"), "heading": tokens.colour("item_heading")}
#: The operators' colours: (text, background).
REF_COLOURS = {"person": (tokens.colour("accent"), tokens.colour("info_bg")), "new": (tokens.colour("caution"), tokens.colour("caution_bg")),
               "none": (tokens.colour("text2"), tokens.colour("hover")), "task": (tokens.colour("ref_task"), tokens.colour("ref_task_bg")),
               "type": (tokens.colour("caution"), tokens.colour("caution_bg"))}
#: A line's colours: (its tint, and each operator's (start, length, a key of ``REF_COLOURS``)).
NO_COLOURS: tuple[str | None, tuple[tuple[int, int, str], ...]] = (None, ())


class _Coloured(QTextBlockUserData):
    """The colours a line was last given. It stays with its block as lines come and go above it."""

    def __init__(self, colours: tuple) -> None:
        super().__init__()
        self.colours = colours


class OperatorHighlighter(QSyntaxHighlighter):
    """Colours the operators and tints the lines of the content text, from the last ``items.read``."""

    def __init__(self, doc: QTextDocument) -> None:
        super().__init__(doc)
        self.reading: items.Reading | None = None
        self.kinds: dict[int, str] = {}

    def set_reading(self, reading: items.Reading | None) -> None:
        """Take a new reading. Only the lines whose colours change are coloured again, since that lays each one out again
        (release 5.52)."""
        self.reading = reading
        self.kinds = items.line_kinds(reading) if reading else {}
        block = self.document().begin()
        while block.isValid():
            shown = block.userData()
            if (shown.colours if shown else NO_COLOURS) != self._colours(block):
                self.rehighlightBlock(block)
            block = block.next()

    def _colours(self, block: QTextBlock) -> tuple:
        """What the last reading colours a block with."""
        r = self.reading
        n = block.blockNumber()
        if not r or n >= len(r.lines):
            return NO_COLOURS
        line = r.lines[n]
        # A list item made with the list buttons has no "- " in its text; one typed as text has.
        base = 0 if block.textList() is not None else line.off
        return (TINTS.get(self.kinds.get(n, "")),
                tuple((base + x.start, x.end - x.start, "type" if x.kind in ("type", "param") else "task" if x.kind == "task"
                       else "none" if x.none else "new" if x.is_new else "person") for x in line.toks))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt's name
        colours = self._colours(self.currentBlock())
        self.setCurrentBlockUserData(_Coloured(colours))
        tint, spans = colours
        if tint:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(tint))
            self.setFormat(0, len(text), fmt)
        for start, length, key in spans:
            fg, bg = REF_COLOURS[key]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(fg))
            fmt.setBackground(QColor(bg))
            if key == "new":
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DashUnderline)
                fmt.setUnderlineColor(QColor(fg))
            self.setFormat(start, length, fmt)


def _take_out(layout, w: QWidget) -> None:
    """One widget leaves a layout and the window at once."""
    layout.removeWidget(w)
    w.hide()
    w.setParent(None)
    w.deleteLater()


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


LONG_VALUE = 30  # characters a field's box on a card shows whole at its narrowest


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
        self.line_at = it.line
        self.line_button = QPushButton(f"line {it.line + 1}", objectName="link")
        self.line_button.setToolTip("Show its line in the content text")
        self.line_button.clicked.connect(lambda: self.go.emit(self.line_at))
        top.addWidget(self.line_button)
        lay.addLayout(top)
        self.title = QLineEdit(_pretty(it.title) if it.kind == "param" else it.title)
        self.title.setAccessibleName(f"{name} title")
        self.title.setEnabled(it.on)
        self.title.setReadOnly(it.kind == "param")  # a field's value is read from its line, and changed there
        self.title.textEdited.connect(lambda text: self.changed.emit(self.key, "title", text))
        lay.addWidget(self.title)
        if it.kind == "param" and len(self.title.text()) > LONG_VALUE:  # it wraps, so it keeps its end: a tie's last word says which end it counts from
            self.title.hide()
            said = QLabel(self.title.text(), objectName="itemValue", textFormat=Qt.TextFormat.PlainText, wordWrap=True)
            said.setEnabled(it.on)
            said.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lay.addWidget(said)
        facts = QLabel(_facts(it, where) + (f"  <b style='color:{C.critical}'>{esc(_pretty(it.problem))}</b>" if it.problem else ""), objectName="hint")
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

    @staticmethod
    def shows(it: items.Item, where: str, stripe: str | None = None) -> tuple:
        """Everything ``__init__`` draws except the item's place, which ``moved`` can change: items alike in this need one
        card, kept. Anything new a card draws goes here too."""
        return (it.kind, it.on, it.plant_event, it.label, it.state, it.changed, it.title, it.problem, it.due, _facts(it, where), stripe)

    def moved(self, it: items.Item) -> None:
        """The same item in another place: a line was added or taken away above it."""
        self.key, self.line_at = it.key, it.line
        self.line_button.setText(f"line {it.line + 1}")


class _UnreadCard(QFrame):
    """An Unread line card (release 5.92): a click goes to its line, as an item's card does."""

    go = Signal(int)

    def __init__(self, line: int) -> None:
        super().__init__(objectName="itemCard")
        self.setProperty("kind", "off")
        self.line = line

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.go.emit(self.line)
        super().mousePressEvent(event)


class ItemCards(QFrame):
    """A card for each item, beside the content text."""

    changed = Signal(str, str, object)
    go = Signal(int)
    open_capture = Signal(str)  # an email's capture, from its Already captured line (release 5.93)

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
        self._rows: list[tuple] = []  # what each card shows (``ItemCard.shows``)
        self._own_box: QFrame | None = None
        self._own_said: str | None = None
        # Release 5.92: a card for each ** line that read as nothing, and one for each new person an @ makes, ticked.
        self.extra_box = QVBoxLayout()
        self.extra_box.setSpacing(6)
        lay.insertLayout(lay.indexOf(self.hint), self.extra_box)
        self.unread_cards: list[QFrame] = []
        self.people_ticks: dict[str, QCheckBox] = {}
        self._extra: tuple = ()
        # Release 5.93: an email already captured, with a link to the capture that holds it.
        self.before_box = QVBoxLayout()
        self.before_box.setSpacing(4)
        lay.insertLayout(lay.indexOf(self.hint), self.before_box)
        self.before_notes: list[QLabel] = []

    def editing(self) -> bool:
        """Whether a card's title or due date has the keyboard: the cards aren't rebuilt under you."""
        w = self.focusWidget()
        return w is not None and isinstance(w, QLineEdit) and self.isAncestorOf(w)

    def show_items(self, r: items.Reading | None, own: items.SelfFields | None, where_text: Callable[[items.Item], str], names: items.Names,
                   stripe: Callable[[items.Item], str] | None = None) -> None:
        """Show a reading's items. A card takes some milliseconds to make and this runs whenever typing pauses, so one is made
        only for what no card shows yet. The rest stay, even when a line added above moves them (release 5.52)."""
        its = r.items if r else []
        said = None
        if own and own.any:
            parts = [f"Assignees: {', '.join(x.name for x in own.assignees)}" * bool(own.assignees),
                     f"Lead: {', '.join(x.name for x in own.leads)}" * bool(own.leads),
                     f"Also under: {', '.join(names.task_title(t) for t in own.tasks)}" * bool(own.tasks)]
            said = " · ".join(s for s in parts if s)
        if said != self._own_said:
            self._show_own(said)
        spare: dict[tuple, list[ItemCard]] = {}
        for row, card in zip(self._rows, self.cards):
            spare.setdefault(row, []).append(card)
        cards, rows = [], []
        for it in its:
            where, edge = where_text(it), stripe(it) if stripe else None
            row = ItemCard.shows(it, where, edge)
            if spare.get(row):
                card = spare[row].pop(0)
                card.moved(it)
            else:
                card = ItemCard(it, where, edge)
                card.changed.connect(self.changed)
                card.go.connect(self.go)
            cards.append(card)
            rows.append(row)
        for left in spare.values():
            for card in left:
                _take_out(self.cards_box, card)
        first = 0 if self._own_box is None else 1
        for i, card in enumerate(cards):
            held = self.cards_box.itemAt(first + i)
            if held is None or held.widget() is not card:
                self.cards_box.removeWidget(card)
                self.cards_box.insertWidget(first + i, card)
        self.cards, self._rows = cards, rows
        self._show_extra(r)
        on = [it for it in its if it.on]
        counts = [f"{n} {name.lower()}{'s' if n > 1 else ''}" for k, name in items.KIND_NAMES.items() if (n := sum(it.kind == k for it in on))]
        self.count.setText("Save makes " + _and(counts) if counts else "Nothing to make" if its else "")
        self.hint.setText(
            "Each line with an operator is a card. Untick one to skip it, or change its title or due date here: your change stays "
            "even when you edit the line." if its or said is not None else
            "In any capture, <b>@Tom</b> makes a task for Tom, <b>@L.Tom</b> makes him its lead, <b>@__</b> a task for no one yet, "
            "<b>#Rigging plan</b> files a note to that task, and <b>**closed,</b>, <b>**u,</b>, <b>**n,</b>, <b>**t,</b>, <b>**decision,</b> "
            "or <b>**event,</b> say what a line is. <b>**due, 5 Nov.</b> or <b>**key date, trial run 1 to 5 Dec, plant activity.</b> fills in "
            "a field: any field, by its name. Type @ or # for a list.")
        empty = not its and said is None and not self.unread_cards and not self.people_ticks
        if self.property("empty") != empty:
            self.setProperty("empty", empty)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_captured_before(self, notes: list[tuple[str, str]]) -> None:
        """For each email a capture already holds: its sentence, and Open it, which shows that capture's page."""
        for w in self.before_notes:
            self.before_box.removeWidget(w)
            w.deleteLater()
        self.before_notes = []
        for text, cid in notes:
            note = QLabel(f"{esc(text)} <a href='{esc(cid)}'>Open {esc(cid)}</a>. Save keeps it again, as a capture of its own.",
                          objectName="hint")
            note.setWordWrap(True)
            note.linkActivated.connect(self.open_capture)
            self.before_box.addWidget(note)
            self.before_notes.append(note)

    def _show_extra(self, r: items.Reading | None) -> None:
        """The Unread line cards and the new people's ticks (release 5.92, the review's F6), made again only when they change,
        so a tick isn't rebuilt under the pointer."""
        unread, people = (tuple(r.unread), tuple(r.new_people)) if r else ((), ())
        if (unread, people) == self._extra:
            return
        self._extra = (unread, people)
        while self.extra_box.count():
            w = self.extra_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.unread_cards, self.people_ticks = [], {}
        for n, text in unread:
            card = _UnreadCard(n)
            card.go.connect(self.go)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 5, 6, 6)
            cl.addWidget(QLabel(f"<b>Unread line</b>  <span style='color:{C.text2}'>line {n + 1}</span>"))
            words = QLabel(f"This ** line wasn't read; check its name and comma. <i>“{esc(text[:120])}”</i> Save keeps it as it is.",
                           objectName="hint")
            words.setWordWrap(True)
            cl.addWidget(words)
            self.extra_box.addWidget(card)
            self.unread_cards.append(card)
        for name, on in people:
            tick = QCheckBox(f"Add {name} to people")
            tick.setChecked(on)
            tick.setToolTip(f"Saving adds {name} to the people list, as @{name} names no one there yet. Untick it if that's a slip: "
                            f"the line's item is then for no one yet.")
            tick.toggled.connect(lambda checked, name=name: self.changed.emit(items.PEOPLE_KEY, name.lower(), checked))
            self.extra_box.addWidget(tick)
            self.people_ticks[name] = tick

    def _show_own(self, said: str | None) -> None:
        """The new task's own card, above the items, while its first line says anything."""
        if self._own_box is not None:
            _take_out(self.cards_box, self._own_box)
            self._own_box = None
        self._own_said = said
        if said is None:
            return
        box = QFrame(objectName="itemCard")
        box.setProperty("kind", "self")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(8, 5, 6, 6)
        bl.addWidget(QLabel(f"<b>The new task</b>  <span style='color:{C.text2}'>its first line</span>"))
        facts = QLabel(said, objectName="hint")
        facts.setWordWrap(True)
        bl.addWidget(facts)
        self.cards_box.insertWidget(0, box)
        self._own_box = box


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
        self.title = ElidedLabel()  # a meeting's name can be long: it ends in "…", and the count keeps its room
        self.title.setFont(tokens.ui_font(semibold=True))
        head.addWidget(self.title, 1)
        self.info_slot = head
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
            self.title.setText("Agenda")
            self.count.setText("")
            self.hint.setText("A new meeting has no agenda yet. Pick a meeting at the top to work through its agenda here.")
            self.start_button.hide()
            return
        self.title.setText(f"Agenda of {m.task(meeting).title}")
        n = 0
        for a in open_items:
            text = (m.task(a.subject).title + (f"  ·  {a.note}" if a.note else "")) if a.subject else a.note
            box = ElidedCheck(text)
            box.setToolTip(f"{text}\n\nTicked items close as Discussed when you save")
            box.setChecked(done(a))
            n += box.isChecked()
            box.toggled.connect(lambda on, i=a.id: self.ticked.emit(i, on))
            self.rows.addWidget(box)
            self.boxes[a.id] = box
        self.count.setText(f"{n} of {len(open_items)} discussed" if open_items else "No open items")
        self.start_button.setVisible(bool(open_items))
        self.hint.setText("Ticked items close as Discussed when you save. An item is ticked for you once its heading has notes under it."
                          if open_items else "")


#: The @ and # list (release 5.65, decision 310): as wide as its longest row, between these, and this many rows in view
#: before it scrolls. It never scrolls sideways: a scroll bar there hid a lone row's name.
REF_MIN_W, REF_MAX_W, REF_ROWS = 320, 480, 8
#: The grey part of a row gives way down to this before the name is shortened.
REF_SUB_MIN = 48
_OPTION, _HEAD = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1


class _RefDelegate(QStyledItemDelegate):
    """A row of the @ and # list: its name in the Body font, then its grey part (a task's path, a person's aliases) in the
    Caption size, the grey part shortened in its middle before the name is shortened at its end.

    For #, since release 5.75 (round 7's item 92, decisions 327 to 330), a task's row starts with its mark in an 8 px slot,
    so names line up: a top-level task's filled dot in its colour, with its name in Semibold and no grey part ("Top-level
    task" is in its tooltip), or another task's ring in its top-level task's colour. A task with open subtasks ends with
    how many, then the chevron (Right goes into them), which has a backplate under the pointer. Inside a level, the task
    heading it is a header row: a faint fill, a hairline under it, the back chevron (Left goes back up), and how many open
    subtasks it has; its subtasks are indented 16 px, the task tree's indent."""

    PAD, GAP, CHEV, SLOT, INDENT = 8, 12, 20, 8, 16

    def __init__(self, popup: "RefPopup") -> None:
        super().__init__(popup)
        self.popup = popup
        self.font = tokens.ui_font(tokens.BODY)
        self.bold = tokens.ui_font(tokens.BODY, semibold=True)
        self.small = tokens.ui_font(tokens.CAPTION)

    def row_height(self) -> int:
        return max(28, QFontMetrics(self.font).height() + 8)

    def parts(self, o: items.Option, head: bool) -> tuple[tuple[bool, str] | None, bool, str, str]:
        """What a row shows beside its name: its mark ((top-level, colour), or None for a person), whether it's indented
        under a level's header, its grey part, and the words at its right end."""
        p = self.popup
        mark = p.mark(o)
        kid = p.depth > 0 and not head
        n = p.kids(o)
        if head:
            return mark, False, "", f"{n} open subtask{'s' * (n != 1)}" if n else ""
        top = bool(mark and mark[0])
        return mark, kid, "" if top or kid else o.sub, str(n) if n else ""

    def name_font(self, o: items.Option, head: bool):
        mark = self.popup.mark(o)
        return self.bold if head or (mark and mark[0]) else self.font

    def natural_width(self, o: items.Option, head: bool) -> int:
        """The row's width with nothing shortened."""
        mark, kid, sub, right = self.parts(o, head)
        fs = QFontMetrics(self.small)
        w = 2 * self.PAD + 4 + QFontMetrics(self.name_font(o, head)).horizontalAdvance(o.label)  # 4 px to spare
        w += (self.INDENT if kid else 0) + (self.CHEV if head else 0) + (self.SLOT + 8 if mark else 0)
        if sub:
            w += self.GAP + fs.horizontalAdvance(sub)
        if right:
            w += self.GAP + fs.horizontalAdvance(right) + (0 if head else 4 + self.CHEV)
        return w

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        return QSize(1, self.row_height())  # as wide as the list, never wider

    def _plate(self, p: QPainter, box: QRect) -> None:
        """The backplate under a chevron the pointer is on: it's a button."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tokens.colour("hover")))
        p.drawRoundedRect(box, 4, 4)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        o: items.Option = index.data(_OPTION)
        head = bool(index.data(_HEAD))
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        rect = opt.rect
        if head:  # the level's header (decision 330): a faint fill under the style's hover and selection
            p.fillRect(rect, QColor(tokens.colour("base")))
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)  # the row's back and selection, from the style sheet
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if head:
            p.setPen(QPen(QColor(tokens.colour("stroke")), 1))
            p.drawLine(QPointF(rect.left(), rect.bottom() + 0.5), QPointF(rect.left() + rect.width(), rect.bottom() + 0.5))
        mark, kid, sub, right_words = self.parts(o, head)
        left = rect.left() + self.PAD + (self.INDENT if kid else 0)
        right = rect.left() + rect.width() - self.PAD  # QRect.right() is a pixel short of the edge
        mid = rect.top() + rect.height() / 2
        scale = p.device().devicePixelRatioF()
        grey = tokens.colour("text2")
        hot = self.popup.hot
        if head:
            on = hot == (index.row(), "back")
            if on:
                self._plate(p, QRect(left - 5, int(mid - self.CHEV / 2), self.CHEV, self.CHEV))
            p.drawPixmap(QPoint(left - 2, int(mid - 7)), tinted("chevron-left", tokens.colour("text") if on else grey, 14, scale))
            left += self.CHEV
        if mark:  # decisions 327 and 328: a dot for a top-level task, a ring in its top-level task's colour for the rest
            is_top, colour = mark
            centre = QPointF(left + self.SLOT / 2, mid)
            if is_top:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(colour))
                p.drawEllipse(centre, 4, 4)
            else:
                p.setPen(QPen(QColor(colour), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(centre, 2.75, 2.75)  # 7 px across, its 1.5 px line inside
            left += self.SLOT + 8
        fn, fs = QFontMetrics(self.name_font(o, head)), QFontMetrics(self.small)
        base = int(rect.top() + (rect.height() + fn.ascent() - fn.descent()) / 2)  # every part on one baseline
        if right_words:  # how many open subtasks, then the chevron into them (decision 329)
            if not head:
                box = QRect(right - self.CHEV, int(mid - self.CHEV / 2), self.CHEV, self.CHEV)
                on = hot == (index.row(), "into")
                if on:
                    self._plate(p, box)
                p.drawPixmap(QPoint(box.left() + 3, int(mid - 7)), tinted("chevron-right", tokens.colour("text") if on else grey, 14, scale))
                right -= self.CHEV + 4
            w = fs.horizontalAdvance(right_words)
            p.setFont(self.small)
            p.setPen(QColor(grey))
            p.drawText(QPoint(right - w, base), right_words)
            right -= w + self.GAP
        room = max(0, right - left)
        name_w = fn.horizontalAdvance(o.label)
        sub_w = fs.horizontalAdvance(sub) if sub else 0
        sub_room = 0
        if sub:  # the grey part gives way first, down to REF_SUB_MIN; then the name does
            sub_room = min(sub_w, max(room - name_w - self.GAP, min(sub_w, REF_SUB_MIN)))
            if sub_room < min(sub_w, REF_SUB_MIN) or room - sub_room - self.GAP < fn.horizontalAdvance("…") * 4:
                sub_room = 0
        name_room = room - (sub_room + self.GAP if sub_room else 0)
        # A part that fits is drawn whole: Qt's eliding wants a little more room than the words measure (release 5.64's
        # DropButton found the same), so it would shorten words that fit exactly.
        name = o.label if name_w <= name_room else fn.elidedText(o.label, Qt.TextElideMode.ElideRight, name_room)
        p.setFont(self.name_font(o, head))
        p.setPen(QColor(tokens.colour("text")))
        p.drawText(QPoint(left, base), name)
        if sub_room:
            shown = sub if sub_w <= sub_room else fs.elidedText(sub, Qt.TextElideMode.ElideMiddle, sub_room)
            p.setFont(self.small)
            p.setPen(QColor(grey))
            p.drawText(QPoint(left + fn.horizontalAdvance(name) + self.GAP, base), shown)
        p.restore()


class RefPopup(QListWidget):
    """The list @ and # open while typing the content text: Up and Down move, Enter or Tab picks, Esc closes it. For #,
    Right on a task with open subtasks lists them under the task itself, and Left goes back up (release 5.65, decisions
    311 and 312); typing goes back to the search, as the text box shows a new list."""

    picked = Signal(object)  # the items.Option

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("refPopup")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.delegate = _RefDelegate(self)
        self.setItemDelegate(self.delegate)
        #: A task's open subtasks as options, for Right; None for a list with no levels (@).
        self.subtasks: Callable[[str], list[items.Option]] | None = None
        #: For #: whether a task is top-level, and its top-level task's colour (release 5.75); None for @.
        self.task_info: Callable[[str], tuple[bool, str] | None] | None = None
        # Each level above this one: its rows, the row it was left from, and the task it was under (None at the top).
        self._levels: list[tuple[list[items.Option], int, items.Option | None]] = []
        self._kids: dict[str, int] = {}
        self._info: dict[str, tuple[bool, str] | None] = {}
        self._root: str | None = None  # the first task gone into: a level's marks take its colour
        self._under = ""  # the path of the level showing: its head's path and name
        self._at, self._above = QPoint(), None
        #: The chevron under the pointer, as (row, "into" or "back"), drawn with a backplate.
        self.hot: tuple[int, str] | None = None
        self.setFixedWidth(REF_MIN_W)
        self.itemClicked.connect(lambda item: self.picked.emit(item.data(_OPTION)))
        self.hide()

    # ---- what it shows ----
    def kids(self, o: items.Option | None) -> int:
        """How many open subtasks the row's task has: Right lists them."""
        if o is None or not o.ref or self.subtasks is None:
            return 0
        if o.ref not in self._kids:
            self._kids[o.ref] = len(self.subtasks(o.ref))
        return self._kids[o.ref]

    def opens(self, o: items.Option | None) -> bool:
        """True when Right on this row would list its task's subtasks."""
        return self.kids(o) > 0

    def _task(self, ref: str) -> tuple[bool, str] | None:
        if ref not in self._info:
            self._info[ref] = self.task_info(ref) if self.task_info is not None else None
        return self._info[ref]

    def mark(self, o: items.Option | None) -> tuple[bool, str] | None:
        """A task row's mark: (whether it's top-level, its colour). Inside a level, the colour is the first task gone
        into's, so a task with two parents shows the colour of the one it's listed under."""
        if o is None or not o.ref or self.task_info is None:
            return None
        info = self._task(o.ref)
        if info is None:
            return None
        root = self._task(self._root) if self._levels and self._root else None
        return (info[0], root[1]) if root else info

    def show_options(self, options: list[items.Option], at: QPoint, above: int | None = None) -> None:
        """The list for what's typed, at ``at`` (in its parent, or on the screen when it's a window of its own), or
        with its foot at ``above`` when it wouldn't fit under the cursor."""
        self._levels = []
        self._kids, self._info, self._root, self.hot = {}, {}, None, None
        self._at, self._above = QPoint(at), above
        self._fill(options, 0)
        self.show()
        self.raise_()

    def _fill(self, options: list[items.Option], row: int, head: items.Option | None = None) -> None:
        self.clear()
        self.hot = None
        rows = ([(head, True)] if head is not None else []) + [(o, False) for o in options]
        # A level's rows have no grey part of their own: they're under the task heading the list.
        under = " › ".join(x for x in ((head.sub if head.ref and head.sub != "Top-level task" else ""), head.label) if x) if head else ""
        self._under = under
        for o, is_head in rows:
            where = o.sub or ("" if is_head else under)
            n = self.kids(o)
            more = f"{n} open subtask{'s' * (n != 1)}" if n else ""
            item = QListWidgetItem(", ".join(x for x in (o.label, where, more) if x))  # what a screen reader says
            item.setData(_OPTION, o)
            item.setData(_HEAD, is_head)
            item.setToolTip("\n".join(x for x in (o.label, where, more) if x))
            self.addItem(item)
        self.setCurrentRow(min(row, max(0, self.count() - 1)))
        self._fit([(o, h) for o, h in rows])

    def _area(self) -> QRect:
        if self.isWindow():
            screen = self.screen() or QGuiApplication.primaryScreen()
            return screen.availableGeometry()
        parent = self.parentWidget()
        return parent.rect().adjusted(4, 4, -4, -4) if parent is not None else QRect(0, 0, REF_MAX_W, 600)

    def _fit(self, rows: list[tuple[items.Option, bool]]) -> None:
        """Size it to its rows and keep it in view: as wide as the widest row allows, one row tall per row up to
        REF_ROWS, its frame and padding counted as Qt reports them."""
        self.ensurePolished()
        area = self._area()
        frame = 2 * self.frameWidth()
        shown = min(REF_ROWS, len(rows))
        bar = self.verticalScrollBar().sizeHint().width() if len(rows) > REF_ROWS else 0
        natural = max((self.delegate.natural_width(o, h) for o, h in rows), default=REF_MIN_W) + frame + bar
        self.setFixedSize(max(REF_MIN_W, min(natural, REF_MAX_W, area.width())), shown * self.delegate.row_height() + frame)
        x = max(area.left(), min(self._at.x(), area.right() - self.width()))
        y = self._at.y()
        if y + self.height() > area.bottom() and self._above is not None:
            y = self._above - self.height()
        self.move(x, max(area.top(), min(y, area.bottom() - self.height())))

    # ---- levels ----
    def _current(self) -> tuple[items.Option | None, bool]:
        item = self.currentItem()
        return (item.data(_OPTION), bool(item.data(_HEAD))) if item is not None else (None, False)

    def go_into(self, row: int | None = None) -> bool:
        """List the subtasks of the task on ``row`` (the current one), under it; True when it has any."""
        item = self.item(self.currentRow() if row is None else row)
        o = item.data(_OPTION) if item is not None else None
        if o is None or bool(item.data(_HEAD)) or not self.opens(o):
            return False
        if not self._levels:
            self._root = o.ref
        self._levels.append(([self.item(i).data(_OPTION) for i in range(self.count()) if not self.item(i).data(_HEAD)],
                             self.row(item), self.item(0).data(_OPTION) if self.item(0).data(_HEAD) else None))
        # A level's row has no grey part of its own; as the next level's head it shows where it is.
        self._fill(self.subtasks(o.ref), 1, head=o if o.sub else replace(o, sub=self._under or "Top-level task"))
        return True

    def go_up(self) -> bool:
        """Back to the level above, with the task it came from picked; False at the top."""
        if not self._levels:
            return False
        options, row, head = self._levels.pop()
        if not self._levels:
            self._root = None
        self._fill(options, row, head=head)
        return True

    @property
    def depth(self) -> int:
        return len(self._levels)

    def chevron_at(self, pos: QPoint) -> tuple[int, str] | None:
        """The chevron at ``pos`` in the viewport, as (row, "into" or "back"), or None."""
        item = self.itemAt(pos)
        if item is None:
            return None
        x, d = pos.x(), self.delegate
        if item.data(_HEAD):
            return (self.row(item), "back") if x < d.PAD + d.CHEV else None
        if self.opens(item.data(_OPTION)) and x > self.viewport().width() - d.PAD - d.CHEV:
            return self.row(item), "into"
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        hot = self.chevron_at(event.position().toPoint())
        if hot != self.hot:
            self.hot = hot
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor)
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.hot is not None:
            self.hot = None
            self.viewport().unsetCursor()
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """A row's chevron goes into its subtasks, and the back chevron goes up; a click anywhere else picks the row."""
        if event.button() == Qt.MouseButton.LeftButton:
            hot = self.chevron_at(event.position().toPoint())
            if hot and hot[1] == "back":
                self.go_up()
                return
            if hot and hot[1] == "into" and self.go_into(hot[0]):
                return
        super().mousePressEvent(event)

    def handle_key(self, key: int) -> bool:
        """A key typed in the content text while the list is open; True when the list used it. Right and Left are the
        list's only when they do something there (decision 312): otherwise they move the cursor, as before."""
        if not self.isVisible():
            return False
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.setCurrentRow((self.currentRow() + (1 if key == Qt.Key.Key_Down else -1)) % max(1, self.count()))
            return True
        if key == Qt.Key.Key_Right:
            return self.go_into()
        if key == Qt.Key.Key_Left:
            return self.go_up()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            item = self.currentItem() or self.item(0)
            if item:
                self.picked.emit(item.data(_OPTION))
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
