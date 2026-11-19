"""The workspace's parts (release 5.152; the design workspace's ``docs/mods/workspace-view-plan.md``): the widgets
``docrepo.ui.workspace`` lays out. What they show is ``docrepo.workspace``'s; they draw it and say what was clicked.

- ``ChainOutline``: the notes' outline with the chain's pages round the page being edited (decision 683).
- ``WorkPane``: the task page's ``TaskPane`` as the workspace's middle column: the status card, the notes and Dates in
  one scroll, without the facts and the history (664).
- ``StatusCard``: the status card with its quick entry bar (678, 701 and 702).
- ``DatesView``: Dates under the notes (681, 698 and 699).
- ``ChainColumn``: the chain's tiles and this task's subtasks (664, 684 and 686).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QStyle,
                               QStyleOptionButton, QStylePainter, QToolButton, QVBoxLayout, QWidget)

from docrepo import task_tile
from docrepo import workspace as ws
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.notes_outline import NotesOutline
from docrepo.ui.task_header import fit_view
from docrepo.ui.task_pane import TaskPane
from docrepo.ui.task_tile import STATE_ICONS, TileWidget
from docrepo.ui.widgets import DropButton, ElidedLabel

#: The status card's quick entry, closed and opened into Log progress's form (release 5.175, decision 764).
HINT = "Enter update · Shift+Enter note"
MORE_HINT = "Enter logs it all · Shift+Enter note"
MORE_TIP = "More (Alt+Down): State, Waiting on and Today under the line, as Log progress has them"
LESS_TIP = "Less (Alt+Down): the line alone, Enter keeping an update"
#: Below this width the card's hint goes, so the line keeps its room.
HINT_ROOM = 640
#: The chain's column's width, and the resources'.
CHAIN_WIDTH = 270
RESOURCES_WIDTH = 300
#: How much of a task's current status a chain's tile shows.
STATUS_CHARS = 130


def _caption(text: str) -> QLabel:
    """A column's or a group's small heading: "UP THE CHAIN", "SUBTASKS", "and under"."""
    lb = QLabel(text, objectName="wsCaption")
    lb.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
    return lb


def _clip(text: str, n: int) -> str:
    words = " ".join(text.split())
    return words if len(words) <= n else words[: n - 1].rstrip() + "…"


# ---- the outline (decision 683) ----
class ChainOutline(NotesOutline):
    """The notes' outline in the workspace: the chain's pages before the page being edited (``before``), that page's name
    (``title``), its own headings from the editor (their block numbers, a level under its name), then the pages after it
    and Dates (``after``). The entries not in the editor carry numbers below -1, which ``WorkPane`` turns into places."""

    def __init__(self, notes=None) -> None:
        super().__init__(notes)
        self.before: list[tuple[int, int, bool, str]] = []
        self.title: tuple[int, int, bool, str] | None = None
        self.after: list[tuple[int, int, bool, str]] = []

    def set_frame(self, before: list, title: tuple | None, after: list) -> None:
        if (before, title, after) == (self.before, self.title, self.after):
            return
        self.before, self.title, self.after = list(before), title, list(after)
        self._entries = None  # drawn again, with the same headings
        self.rebuild()

    def rebuild(self) -> None:
        if self.notes is None:
            return
        own = [(b.blockNumber(), level + 1, day, " ".join(b.text().split()) or "(an empty heading)") for b, level, day in self.notes.outline()]
        self.set_entries(self.before + ([self.title] if self.title else []) + own + self.after)


# ---- the middle column ----
class WorkPane(TaskPane):
    """The task page's pane laid out for the workspace (decision 664): the status card at its top (``card_slot``), the
    Notes heading saying whose they are (``of_label``), the line over notes read in place or a subtask edited
    (``banner``), the notes, and Dates (``dates_slot``). The facts and the history aren't shown. ``place_picked`` carries
    an outline entry that isn't a heading of the page being edited: ("page", task, heading), ("dates",) or ("top",)."""

    OUTLINE = ChainOutline
    place_picked = Signal(object)
    banner_link = Signal(str)

    def __init__(self, css: str, margin: int) -> None:
        super().__init__(css, margin)
        self.setObjectName("workPane")
        self.facts.hide()
        self.history.hide()
        #: The outline's places that aren't the editor's headings, by their numbers.
        self.places: dict[int, tuple] = {}
        inner = self.widget().layout()
        self.card_slot = QWidget(objectName="wsCardSlot")
        cl = QVBoxLayout(self.card_slot)
        cl.setContentsMargins(margin, 14, margin, 0)
        inner.insertWidget(0, self.card_slot)
        self.of_label = QLabel("", objectName="notesSaved")
        self.of_label.setFont(tokens.ui_font(tokens.CAPTION))
        self.head_row.insertWidget(1, self.of_label)
        self.banner = QLabel(objectName="wsBanner")
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.linkActivated.connect(self.banner_link)
        self.banner.hide()
        self.wrap.layout().insertWidget(1, self.banner)
        self.dates_slot = QWidget(objectName="wsDatesSlot")
        dl = QVBoxLayout(self.dates_slot)
        dl.setContentsMargins(margin, 4, margin, 18)
        inner.insertWidget(inner.indexOf(self.wrap) + 1, self.dates_slot)
        # The chain's outline is often taller than a short page: the notes start at the frame's top, beside it.
        self.notes_row.layout().setAlignment(self.notes, Qt.AlignmentFlag.AlignTop)

    def set_banner(self, html: str) -> None:
        self.banner.setText(html)
        self.banner.setVisible(bool(html))

    def _outline_picked(self, number: int) -> None:
        if number < -1:
            place = self.places.get(number)
            if place is not None:
                self.place_picked.emit(place)
            return
        super()._outline_picked(number)

    def _all_picked(self, number: int) -> None:
        """Notes read in place, or All notes: an anchor in them scrolls there; any other place is the workspace's."""
        if not 0 <= number < len(self._all_targets):
            return
        place = self._all_targets[number]
        if place[0] == "anchor":
            self.all_outline.set_current(number)
            self.scroll_to_anchor(place[1])
        else:
            self.place_picked.emit(place)

    def scroll_to_anchor(self, name: str) -> None:
        top = self.all_view.anchor_top(name)
        if top is not None:
            y = self.all_view.viewport().mapTo(self.widget(), QPoint(0, top)).y()
            self.verticalScrollBar().setValue(max(0, y - 8))

    def scroll_to(self, w: QWidget) -> None:
        """Scroll so ``w``'s top is at the view's top: Dates, or the notes' heading."""
        y = w.mapTo(self.widget(), QPoint(0, 0)).y()
        self.verticalScrollBar().setValue(max(0, y - 8))


# ---- the status card with its quick entry bar (decisions 678, 701 and 702) ----
class EntryBox(QLineEdit):
    """The quick entry's line: Enter keeps an Update, Shift+Enter a note (701); ``entered`` says which."""

    entered = Signal(str, bool)
    #: Esc with nothing typed, before it goes back: True when it did something (the card's form closed, release 5.175).
    on_escape: Callable[[], bool] | None = None

    def keyPressEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if e.key() == Qt.Key.Key_Escape and not self.text() and self.on_escape is not None and self.on_escape():
            e.accept()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            self.entered.emit(self.text(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        if e.key() == Qt.Key.Key_Escape and self.text():  # Esc clears what's typed first, then goes back
            e.accept()
            self.clear()
            return
        super().keyPressEvent(e)


@dataclass
class CardFacts:
    """What the status card shows: whose it is (empty for this task's), its name ("Current status"), when it was written,
    the waiting mark, its body and log as HTML, how many changes, and the quick entry bar's state: whether it's there (a
    task being edited), the task's state, and which of Later… or Add to Today shows (702)."""

    whose: str = ""
    name: str = "Current status"
    when: str = ""
    when_tip: str = ""
    wait: str = ""
    wait_tip: str = ""
    late: bool = False
    body: str = ""
    log: str = ""
    changes: str = ""
    entry: bool = False
    title: str = ""
    state: str = ""
    later: bool = False
    add: bool = False


class StateButton(DropButton):
    """The quick entry bar's state dropdown: the state's circle, its name and the icons' chevron (no typed arrow)."""

    def __init__(self, objectName: str = "") -> None:  # noqa: N803 - Qt's keyword
        super().__init__()
        self.setObjectName(objectName)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        hint = super().sizeHint()
        return QSize(hint.width() + (self.iconSize().width() + 6 if not self.icon().isNull() else 0), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        from docrepo.ui.icons import tinted

        p = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        words, option.text, option.icon = option.text, "", QIcon()
        p.drawControl(QStyle.ControlElement.CE_PushButton, option)
        room = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        left = room.left()
        if not self.icon().isNull():
            size = self.iconSize()
            p.drawPixmap(left, (self.height() - size.height()) // 2, self.icon().pixmap(size))
            left += size.width() + 6
        wide = self.fontMetrics().horizontalAdvance(words)
        self.style().drawItemText(p, QRect(left, room.top(), wide + 2, room.height()),
                                  int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), option.palette, self.isEnabled(), words,
                                  self.foregroundRole())
        p.drawPixmap(left + wide + 6, (self.height() - 14) // 2, tinted(self.arrow, tokens.colour("text2"), 14, max(1.0, self.devicePixelRatioF())))


class StatusCard(QFrame):
    """The status card at the middle column's top (664): whose it is when another task is picked, its status with its log
    behind "4 changes", Got it and Log progress…, then the quick entry bar (678): the line to type in, the state's dropdown,
    and Later… while the task is on Today or Add to Today while it isn't (702)."""

    link = Signal(str)
    entered = Signal(str, bool)
    state_clicked = Signal(QPoint)
    later_clicked = Signal(QPoint)
    add_clicked = Signal()
    #: More (release 5.175, decision 764): the card opened into Log progress's form, or closed again.
    more_toggled = Signal(bool)

    def __init__(self, css: str) -> None:
        super().__init__(objectName="statusCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 10)
        lay.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.whose = QLabel(objectName="wsWhose")
        self.whose.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        self.whose.setTextFormat(Qt.TextFormat.RichText)
        self.whose.linkActivated.connect(self.link)
        self.name = QLabel("Current status", objectName="statusName")
        self.name.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        self.when = QLabel("", objectName="statusWhen")
        self.when.setFont(tokens.ui_font(tokens.CAPTION))
        self.wait = QLabel("", objectName="statusWhen")
        self.wait.setFont(tokens.ui_font(tokens.CAPTION))
        self.log_button = QToolButton(objectName="statusLog")
        self.log_button.setIcon(icon("chevron-right"))
        self.log_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.log_button.setFont(tokens.ui_font(tokens.CAPTION))
        self.log_button.setAutoRaise(True)
        self.log_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_button.clicked.connect(lambda: self.set_log_open(not self.log_open))
        for w in (self.whose, self.name, self.when, self.wait):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.log_button)
        self.body = fit_view(css, (0, 4, 0, 0))
        self.body.anchorClicked.connect(lambda url: self.link.emit(url.toString()))
        self.log = fit_view(css, (0, 8, 0, 0))
        self.log.anchorClicked.connect(lambda url: self.link.emit(url.toString()))
        self.log.hide()
        self.log_open = False
        lay.addLayout(row)
        lay.addWidget(self.body)
        lay.addWidget(self.log)
        self.entry_row = QWidget(objectName="wsEntryRow")
        el = QHBoxLayout(self.entry_row)
        el.setContentsMargins(0, 8, 4, 0)
        el.setSpacing(6)
        self.box = EntryBox(objectName="wsEntry")
        self.box.setMinimumWidth(140)
        self.box.setAccessibleName("Quick entry: Enter keeps an update, Shift+Enter a note")
        self.box.setToolTip("Enter keeps an update, Shift+Enter a note; More (Alt+Down) for State, Waiting on and Today")
        self.box.entered.connect(self.entered)
        if not LOOK.classic:
            self.box.addAction(icon("update"), QLineEdit.ActionPosition.LeadingPosition)
        # More (release 5.175, decision 764): the card grows to show Log progress's form under the line. The arrow is in
        # the line, at its end, so it takes no room from the line.
        self.more_action = self.box.addAction(icon("chevron-right"), QLineEdit.ActionPosition.TrailingPosition)
        self.more_action.setToolTip(MORE_TIP)
        self.more_action.setText("More: State, Waiting on and Today")
        self.more_action.triggered.connect(lambda: self.set_more(not self.more_open))
        QShortcut(QKeySequence("Alt+Down"), self.box, lambda: self.set_more(not self.more_open),
                  context=Qt.ShortcutContext.WidgetShortcut)
        self.more_open = False
        self.box.on_escape = lambda: self.more_open and (self.set_more(False) or True)
        self.hint = ElidedLabel(HINT, objectName="hint")  # it gives way first when the card is narrow, ending in "…" (5.175)
        self.hint.setToolTip("Enter keeps an update: its words become the current status. Shift+Enter keeps a note under today's day.")
        self.state_button = StateButton(objectName="wsState")
        self.state_button.setToolTip("Change the state")
        self.state_button.clicked.connect(lambda: self.state_clicked.emit(self.state_button.mapToGlobal(self.state_button.rect().bottomLeft())))
        self.later_button = QPushButton("Later…", objectName="wsLater")
        self.later_button.setIcon(icon("reminders"))
        self.later_button.setToolTip("Off Today until a day you pick: Tomorrow, 3 days, 1 week, 2 weeks, 1 month or Other…")
        self.later_button.clicked.connect(lambda: self.later_clicked.emit(self.later_button.mapToGlobal(self.later_button.rect().bottomLeft())))
        self.add_button = QPushButton("Add to Today", objectName="wsAdd")
        self.add_button.setIcon(icon("sun"))
        self.add_button.setToolTip("Put it on Today (D)")
        self.add_button.clicked.connect(self.add_clicked)
        el.addWidget(self.box, 1)
        el.addWidget(self.hint)
        for w in (self.state_button, self.later_button, self.add_button):
            el.addWidget(w)
        lay.addWidget(self.entry_row)
        self.form_box = QWidget(objectName="wsForm")  # Log progress's form, placed here by the workspace (place_form)
        self.form_grid = QGridLayout(self.form_box)
        self.form_grid.setContentsMargins(0, 8, 4, 0)
        self.form_grid.setHorizontalSpacing(12)
        self.form_grid.setVerticalSpacing(8)
        self.form_grid.setColumnStretch(1, 1)
        self.form_box.hide()
        lay.addWidget(self.form_box)
        self._buttons_shown = (False, False)

    def resizeEvent(self, e) -> None:  # noqa: N802 - Qt's name
        """A narrow card gives the line the hint's room (release 5.175): the hint goes, its words in the line's tooltip."""
        super().resizeEvent(e)
        self.hint.setVisible(self.width() >= HINT_ROOM)

    def place_form(self, form) -> None:
        """Put Log progress's form (``ui.progress_form.ProgressForm``, its line this card's box) under the entry row."""
        form.place(self.form_grid, 0)

    def set_more(self, on: bool) -> None:
        """Open the card into the form, or close it (decision 764). Open, the form has State and Today, so the card's own
        State button and Later… or Add to Today step aside; Enter then logs it all at once."""
        if on == self.more_open:
            return
        self.more_open = on
        self.more_action.setIcon(icon("chevron-down" if on else "chevron-right"))
        self.more_action.setToolTip(LESS_TIP if on else MORE_TIP)
        self.form_box.setVisible(on)
        self.hint.setText(MORE_HINT if on else HINT)
        self.state_button.setVisible(not on)
        later, add = self._buttons_shown
        self.later_button.setVisible(later and not on)
        self.add_button.setVisible(add and not on)
        self.box.setFocus()
        self.more_toggled.emit(on)

    def set_log_open(self, on: bool) -> None:
        self.log_open = on
        self.log.setVisible(on)
        self.log_button.setIcon(icon("chevron-down" if on else "chevron-right"))

    def show_facts(self, f: CardFacts) -> None:
        self.whose.setText(f.whose)
        self.whose.setVisible(bool(f.whose))
        self.name.setText(f.name)
        self.when.setText(f"· {f.when}" if f.when else "")
        self.when.setToolTip(f.when_tip)
        self.wait.setText(f"· {f.wait}" if f.wait else "")
        self.wait.setToolTip(f.wait_tip)
        self.wait.setStyleSheet(f"color: {tokens.colour('caution')}; font-weight: 600" if f.late else f"color: {tokens.colour('accent')}")
        self.wait.setVisible(bool(f.wait))
        self.body.setHtml(f.body)
        self.log.setHtml(f.log or '<p class="note">No changes yet.</p>')
        self.log_button.setText(f.changes)
        self.log_button.setVisible(bool(f.changes))
        if not f.changes:
            self.set_log_open(False)
        self.setProperty("empty", not f.when)
        self.style().unpolish(self)
        self.style().polish(self)
        self.entry_row.setVisible(f.entry)
        if not f.entry:
            self.set_more(False)
        if f.entry:
            self.box.setPlaceholderText(f"Type an update, or a note, for {f.title}")
            name, colour = STATE_ICONS.get(f.state, STATE_ICONS["Not started"])
            self.state_button.setIcon(icon(name, tokens.colour(colour)))
            self.state_button.setText(f.state)
            self._buttons_shown = (f.later, f.add)
            self.later_button.setVisible(f.later and not self.more_open)
            self.add_button.setVisible(f.add and not self.more_open)
            self.state_button.setVisible(not self.more_open)


# ---- Dates (decisions 681, 698 and 699) ----
class DayBox(QLineEdit):
    """A day being changed: Enter keeps it, Esc leaves it (681)."""

    kept = Signal(str)
    left = Signal()

    def keyPressEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            self.kept.emit(self.text())
            return
        if e.key() == Qt.Key.Key_Escape:
            e.accept()
            self.left.emit()
            return
        super().keyPressEvent(e)


#: Each kind's chip colours: (text, background) token names.
KIND_COLOURS = {"Due": ("text2", "hover"), "Deadline": ("critical", "critical_bg"), "Meeting": ("parked", "parked_bg"),
                "Key date": ("accent", "info_bg"), "Plant event": ("accent", "info_bg"), "Follow-up": ("parked", "parked_bg"),
                "Reminder": ("caution", "caution_bg")}


def _chip_style(kind: str) -> str:
    fg, bg = KIND_COLOURS.get(kind, ("text2", "hover"))
    return (f"color: {tokens.colour(fg)}; background: {tokens.colour(bg)}; border-radius: 9px; padding: 1px 8px;"
            f" font-size: {tokens.CAPTION}pt")


class DatesView(QWidget):
    """Dates (681): its heading with its count and Add a key date, then a frame of rows: Show earlier, the earlier ones once
    shown, a line for today, and today's and the ones to come. Each row: its day (a click changes it in place), how far off,
    its kind, its words with whose it is, and its menu."""

    day_clicked = Signal(str)
    day_typed = Signal(str, str)
    day_left = Signal()
    row_menu = Signal(str, QPoint)
    earlier = Signal()
    add = Signal()
    link = Signal(str)

    def __init__(self) -> None:
        super().__init__(objectName="wsDates")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.title = QLabel("Dates", font=tokens.ui_font(tokens.BODY, semibold=True))
        self.count = QLabel("", objectName="count")
        self.words = QLabel("", objectName="hint")
        self.words.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.add_button = QPushButton("Add a key date", objectName="wsLink")
        self.add_button.setFlat(True)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setToolTip("A key date on the task being edited: a day in words and what it is, such as 24 nov Base plate drawing")
        self.add_button.clicked.connect(self.add)
        for w in (self.title, self.count, self.words):
            head.addWidget(w)
        head.addStretch()
        head.addWidget(self.add_button)
        lay.addLayout(head)
        self.frame = QFrame(objectName="notesCard")
        self.grid = QGridLayout(self.frame)
        self.grid.setContentsMargins(12, 8, 8, 8)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(4)
        lay.addWidget(self.frame)
        #: The rows shown, by key, for the tests: (row, its widgets).
        self.shown: dict[str, tuple[ws.DateRow, dict[str, QWidget]]] = {}
        self.box: DayBox | None = None

    def _clear(self) -> None:
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.shown = {}
        self.box = None

    def show_rows(self, rows: list[ws.DateRow], today, *, show_earlier: bool, editing: str, words: str,
                  cell: Callable[[ws.DateRow], str], shown_when: Callable[[ws.DateRow], str]) -> None:
        """Draw the rows. ``editing`` is the key of the row whose day is being changed; ``cell`` gives a row's words as
        HTML, with whose it is; ``shown_when`` a row's day as words."""
        self._clear()
        earlier, coming = ws.split_dates(rows, today)
        self.count.setText(str(len(rows)))
        self.words.setText(words)
        r = 0
        if earlier:
            more = QPushButton(("Hide " if show_earlier else "Show ") + f"{len(earlier)} earlier", objectName="wsLink")
            more.setFlat(True)
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.clicked.connect(self.earlier)
            self.grid.addWidget(more, r, 0, 1, 5, Qt.AlignmentFlag.AlignLeft)
            r += 1
            if show_earlier:
                for row in earlier:
                    r = self._row(row, r, today, editing, cell, shown_when)
        line = QLabel(f"Today · {shown_when(ws.DateRow(today, 'Due', '', '', ''))}", objectName="wsTodayLine")
        line.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        line.setStyleSheet(f"color: {tokens.colour('accent')}; border-bottom: 1px solid {tokens.colour('accent')}; padding-bottom: 2px")
        self.grid.addWidget(line, r, 0, 1, 5)
        r += 1
        for row in coming:
            r = self._row(row, r, today, editing, cell, shown_when)
        if not rows:
            none = QLabel("No dates on these tasks yet. Add a key date, or give one a Due in Quick edit.", objectName="hint")
            self.grid.addWidget(none, r, 0, 1, 5)
        self.grid.setColumnStretch(3, 1)

    def _row(self, row: ws.DateRow, r: int, today, editing: str, cell: Callable[[ws.DateRow], str], shown_when) -> int:
        parts: dict[str, QWidget] = {}
        if row.key == editing:
            box = DayBox(objectName="wsDayBox")
            box.setText(ws.day_text(row.day, today))
            box.selectAll()
            box.setFixedWidth(120)
            box.kept.connect(lambda text, k=row.key: self.day_typed.emit(k, text))
            box.left.connect(self.day_left)
            self.box = box
            parts["day"] = box
        else:
            day = QPushButton(shown_when(row), objectName="wsDay")
            day.setFlat(True)
            day.setCursor(Qt.CursorShape.PointingHandCursor)
            day.setEnabled(bool(row.field))
            day.setToolTip("Change the day: type it in words" if row.field else "A repeating meeting's next one: change it in Edit task")
            day.clicked.connect(lambda _=False, k=row.key: self.day_clicked.emit(k))
            parts["day"] = day
        when = QLabel(row.when(today), objectName="wsWhen")
        soon = 0 <= (row.day - today).days <= 2
        when.setStyleSheet(f"color: {tokens.colour('critical' if row.day < today else 'caution' if soon else 'text2')}"
                           + ("; font-weight: 600" if soon or row.day < today else ""))
        kind = QLabel(("◆ " if row.deadline and row.kind != "Deadline" else "") + row.kind, objectName="wsKind")
        kind.setStyleSheet(_chip_style(row.kind))
        words = QLabel(objectName="wsWords")
        words.setTextFormat(Qt.TextFormat.RichText)
        words.setWordWrap(True)
        words.setMinimumWidth(80)
        words.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        end = f' <span style="color: {tokens.colour("text2")}">to {shown_when(ws.DateRow(row.end, "", "", "", ""))}</span>' if row.end else ""
        words.setText(f"{cell(row)}{end}")
        words.linkActivated.connect(self.link)
        menu = QToolButton(objectName="iconOnly")
        menu.setIcon(icon("more"))
        menu.setAutoRaise(True)
        menu.setToolTip("Its menu")
        menu.clicked.connect(lambda _=False, k=row.key, b=menu: self.row_menu.emit(k, b.mapToGlobal(b.rect().bottomLeft())))
        parts.update(when=when, kind=kind, words=words, menu=menu)
        for col, w in enumerate((parts["day"], when, kind, words, menu)):
            # The words fill their column; the rest keep to their own width.
            across = Qt.AlignmentFlag(0) if col == 3 else Qt.AlignmentFlag.AlignRight if col == 4 else Qt.AlignmentFlag.AlignLeft
            self.grid.addWidget(w, r, col, Qt.AlignmentFlag.AlignVCenter | across)
        self.shown[row.key] = (row, parts)
        r += 1
        if row.key == editing:
            hint = QLabel(ws.DAY_HINT, objectName="hint")
            hint.setWordWrap(True)
            self.grid.addWidget(hint, r, 1, 1, 4)
            parts["hint"] = hint
            r += 1
        return r


# ---- the chain (decisions 664, 684 and 686) ----
class ChainCard(QFrame):
    """A tile in the chain's column: the tile's line (its circle, title and days), then its status's first words and the
    day it was written; this task's says so, with its waiting mark. A click picks it, a double-click works on it, the
    right-click is the tile's menu."""

    clicked = Signal(str)
    opened = Signal(str)
    menu = Signal(str, QPoint)
    state_clicked = Signal(str, QPoint)

    def __init__(self, tile: task_tile.Tile, *, status: str = "", this: bool = False, note: str = "", picked: bool = False,
                 compact: bool = False) -> None:
        super().__init__(objectName="wsChainCard")
        self.task_id = tile.task_id
        self.setProperty("picked", picked)
        self.setProperty("this", this)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 8, 6 if not compact else 4)
        lay.setSpacing(1)
        self.tile = TileWidget(tile, self)
        self.tile.state_clicked.connect(self.state_clicked)
        self.tile.opened.connect(self.opened)
        lay.addWidget(self.tile)
        self.labels: list[QLabel] = []
        for text, name in (("THIS TASK", "wsThis") if this else ("", ""), (status, "wsStatus"), (note, "wsNote")):
            if not text:
                continue
            lb = QLabel(text, objectName=name)
            lb.setWordWrap(True)
            lb.setFont(tokens.ui_font(tokens.CAPTION, semibold=name == "wsThis"))
            lb.setContentsMargins(26, 0, 0, 0)
            lay.addWidget(lb)
            self.labels.append(lb)
        self.setAccessibleName(f"{tile.title}{', this task' if this else ''}")

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.task_id)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802 - Qt's name
        e.accept()
        self.opened.emit(self.task_id)

    def contextMenuEvent(self, e) -> None:  # noqa: N802 - Qt's name
        e.accept()
        self.menu.emit(self.task_id, e.globalPos())

    def text(self) -> str:
        return "\n".join([self.tile.tile.title] + [lb.text() for lb in self.labels])


class ChainColumn(QScrollArea):
    """The chain's column (664): UP THE CHAIN, a tile per task from the project down, a group's words over a second path
    ("and under") and over the task under both (686: nothing about a parent's other subtasks), this task's tile, then
    SUBTASKS with its open subtasks, New task and Show closed."""

    picked = Signal(str)
    opened = Signal(str)
    menu = Signal(str, QPoint)
    state_clicked = Signal(str, QPoint)
    link = Signal(str)

    def __init__(self) -> None:
        super().__init__(objectName="wsChain")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(CHAIN_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget(objectName="wsChainInner")
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(12, 12, 10, 12)
        self.lay.setSpacing(4)
        self.setWidget(inner)
        self.cards: dict[str, ChainCard] = {}

    def clear(self) -> None:
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.cards = {}

    def add_caption(self, text: str, link_html: str = "") -> None:
        if not link_html:
            self.lay.addWidget(_caption(text))
            return
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 8, 0, 0)
        rl.addWidget(_caption(text))
        rl.addStretch()
        lb = QLabel(link_html, objectName="hint")
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.linkActivated.connect(self.link)
        rl.addWidget(lb)
        self.lay.addWidget(row)

    def add_card(self, card: ChainCard, indent: int = 0) -> None:
        card.clicked.connect(self.picked)
        card.opened.connect(self.opened)
        card.menu.connect(self.menu)
        card.state_clicked.connect(self.state_clicked)
        if indent:
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(min(indent, 3) * 10, 0, 0, 0)
            bl.addWidget(card)
            self.lay.addWidget(box)
        else:
            self.lay.addWidget(card)
        self.cards[card.task_id] = card

    def add_link(self, html: str) -> None:
        lb = QLabel(html, objectName="hint")
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.linkActivated.connect(self.link)
        self.lay.addWidget(lb)

    def finish(self) -> None:
        self.lay.addStretch(1)

    def text(self) -> str:
        return "\n".join(c.text() for c in self.cards.values())


def status_line(text: str, day: str) -> str:
    """A chain tile's status: its first words, then the day it was written."""
    clipped = _clip(text, STATUS_CHARS)
    return f"{clipped} · {day}" if clipped and day else clipped


def search_box() -> QLineEdit:
    box = QLineEdit(objectName="wsSearch")
    box.setPlaceholderText("Search links, files, emails, meetings")
    box.setClearButtonEnabled(True)
    box.setAccessibleName("Search the resources")
    if not LOOK.classic:
        box.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return box
