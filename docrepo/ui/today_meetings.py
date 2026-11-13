"""Today's meetings in the windows (release 5.127; the design workspace's ``docs/mods/cold-eyes-plan.md``, section 5, decisions
488 to 495). What's worked out is ``docrepo/meetings.py``'s; this draws it, with the rows' commands.

- **The Meetings group** (``add_group``, decision 490): Today's first group, before Today's items. An all-day line, then the
  past meetings folded under "2 earlier", then the rest, each a row of the Today view's own kind (a ``Line`` and the Due
  column's cell, here the time), the next one with "in 20 min" after its subject and one under way with "now". A quiet line
  says why there are none, or how old the list is when a read failed. Free ones are grey; a private one is its time and
  "Private appointment".
- **The commands** (``actions``, decisions 490 to 492): a linked meeting has **Agenda** (its task's page at its Agenda
  section, or the person's agenda) and **Meeting notes** (the capture window's, with that meeting and today's occurrence);
  an unlinked one has **Link** when a meeting task has its words, else **Make a meeting task**, and **Link…**, the `#` list
  of meetings and people (``MeetingPicker``).
- **The minute tick** (``tick``): while Today shows, each minute the next one's "in 20 min" moves on in place; when the list
  itself changed (a meeting ended, a read found another), Today is drawn again, unless its box is being typed in.
- **Settings' links** (``MeetingLinks``, decision 491): each linked subject with what it's linked to, and Remove.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QPushButton, QTreeWidgetItem, QWidget

from docrepo import items, meetings
from docrepo.detail import esc
from docrepo.meetings import DayMeetings, Meeting
from docrepo.model import Model, is_person
from docrepo.ui.lists.common import _due_html, _row_word, _shape
from docrepo.ui.look import LOOK
from docrepo.ui.task_list import Row, Words
from docrepo.ui.task_picker import SEARCH_LIMIT, TaskPicker
from docrepo.ui.tree_view import HTML_ROLE, LINE_ROLE, Line
from docrepo.views import DueCell

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext

#: The group's heading, first on Today.
HEADING = "Meetings"
#: The folded row the past meetings are under: a key of its own, so a fold by hand is kept (release 5.24's way), and it
#: starts folded.
EARLIER_KEY = ("meetings", "earlier")
TICK_MS = 60_000


def day_of(ctx: AppContext) -> tuple[DayMeetings | None, meetings.TodayCalendar]:
    """Today's meetings as they're to be shown, reading the calendar again when it's due; None with the switch off (decision
    494), when nothing is read."""
    cal = ctx.calendar
    if not ctx.settings.today_meetings:
        return None, cal
    now = ctx.now()
    cal.get(now)
    return meetings.day_view(cal.appointments, ctx.model(), meetings.links(ctx.conn), now), cal


def time_cell(x: Meeting, day: date) -> DueCell:
    """A row's time, where a task's row has its date: "09:00–10:00", its start alone where it's short ("09:00"), the mark
    when there is one ("in 20 min", "now"), its place in the tooltip."""
    a = x.appointment
    span = meetings.time_text(a, day)
    mark = meetings.mark_text(x)
    tip = " · ".join(p for p in (span, a.location, mark) if p)
    return DueCell(text=span, days=mark or f"{a.start:%H:%M}", cls="soon" if x.when == "now" or (x.when == "next" and x.minutes <= 10) else "",
                   tip=tip)


def meeting_line(m: Model, x: Meeting) -> Line:
    """A meeting's row: its subject, the mark after it as a chip, its place, the task it's linked to when named otherwise, how
    many are on its agenda, or the suggested meeting task with a question mark. Grey when it's Free; "tentative" when it's
    that. The icon says what it's linked to."""
    a = x.appointment
    mark = meetings.mark_text(x)
    if x.target and is_person(x.target):
        icon, tip = "person", f"A one-to-one: linked to {meetings.target_name(m, x.target)}'s agenda"
    elif x.target:
        icon, tip = "agenda", f"Linked to {meetings.target_name(m, x.target)}"
    else:
        icon, tip = "calendar", "A private appointment" if a.private else "Not linked yet"
    return Line(a.title, icon=icon, icon_colour="accent" if x.target else "text2", icon_tip=tip, chips=((mark, "st-ip"),) if mark else (),
                muted=("tentative",) if a.busy == meetings.TENTATIVE else (), context=meetings.context_words(m, x),
                dim=a.free or x.when == "past")


def row_key(x: Meeting) -> tuple[str, str] | None:
    """A linked meeting's row is its task's or person's, so a click shows that page; an unlinked one has none."""
    if not x.target:
        return None
    return ("person", x.target) if is_person(x.target) else ("task", x.target)


def add_group(browse: BrowseWindow, grey) -> None:
    """The Meetings group, first on Today (decision 490). Nothing with the switch off. A problem reading the calendar is said
    in the status line once (decision 493)."""
    browse.meeting_rows = {}
    day, cal = day_of(browse.ctx)
    browse.meetings_drawn = signature(day, cal)
    if day is None:
        return
    told = cal.tell()
    if told:
        browse.say(told, error=cal.kind in ("refused", "failed"))
    m, tree = browse.model(), browse.tree
    head = tree.add_row(None, None, [f"<b>{HEADING}</b>"], grey, selectable=False, span=True)
    if day.all_day:
        tree.add_row(head, None, [f'<span class="sub">{esc(meetings.all_day_line(day))}</span>'], selectable=False, span=True)
    if day.earlier:
        fold = tree.add_row(head, EARLIER_KEY, [f'<span class="sub">{len(day.earlier)} earlier</span>'], selectable=False, span=True)
        for x in day.earlier:
            _add_row(browse, fold, m, x)
        if not getattr(browse, "meetings_seeded", False):  # folded until it's opened by hand, then kept as it's left
            browse.shut.setdefault("today", set()).add(EARLIER_KEY)
            browse.meetings_seeded = True
        fold.setExpanded(EARLIER_KEY not in browse.shut.get("today", set()))
    for x in day.rest:
        _add_row(browse, head, m, x)
    quiet = cal.quiet_line(day.count + len(day.all_day))
    if quiet:
        tree.add_row(head, None, [f'<span class="sub">{esc(quiet)}</span>'], selectable=False, span=True)
    head.setExpanded(True)


def _add_row(browse: BrowseWindow, parent: QTreeWidgetItem, m: Model, x: Meeting) -> None:
    cell = time_cell(x, browse.today())
    item = browse.tree.add_row(parent, row_key(x), _shape([meeting_line(m, x), _row_word("Meeting"), _due_html(cell, False)]), tip=cell.tip)
    browse.tree.set_actions(item, actions(browse, x))
    browse.meeting_rows[x.appointment] = item


def signature(day: DayMeetings | None, cal: meetings.TodayCalendar) -> tuple:
    """What the group shows, but the minutes: when this changes, Today is drawn again."""
    if day is None:
        return ()
    rows = tuple((x.appointment, x.when, x.target, x.suggestion, x.agenda) for x in (*day.earlier, *day.rest))
    return (day.day, day.all_day, rows, cal.kind, cal.read_at if cal.kind else None)


# ---- the commands (decisions 490 to 492) ----
def actions(browse: BrowseWindow, x: Meeting) -> list[tuple[str, Callable[[], None], str]]:
    """A meeting row's commands: Agenda and Meeting notes once it's linked; Link (the suggestion) or Make a meeting task, and
    Link…, until it is. None for a private one, or one with no subject to remember a link by."""
    a = x.appointment
    if a.private or not a.key:
        return []
    m = browse.model()
    if x.target:
        whose = f"{meetings.target_name(m, x.target)}'s agenda" if is_person(x.target) else "its page, at its Agenda section"
        return [("Agenda", lambda: open_agenda(browse, x.target), f"Open {whose}"),
                ("Meeting notes", lambda: open_notes(browse, x), "The capture window's meeting notes, for today's meeting")]
    pick = ("Link…", lambda: pick_link(browse, x), "Link it to a meeting task, or to a person for a one-to-one: it stays linked each time it's on your calendar")
    if x.suggestion:
        name = meetings.target_name(m, x.suggestion)
        return [("Link", lambda: link(browse, a.subject, x.suggestion), f"Link it to “{name}”, the meeting task with its words: it stays "
                                                                       "linked each time it's on your calendar"), pick]
    return [pick, ("Make a meeting task", lambda: make_task(browse, x), "New task, with Meeting ticked and the subject as its title")]


def link(browse: BrowseWindow, subject: str, target: str) -> None:
    """Link a subject to a task or a person (decision 491), with Undo for ten seconds."""
    conn = browse.conn
    key = meetings.subject_key(subject)
    before = meetings.links(conn).get(key)
    if not browse._do(lambda: meetings.set_link(conn, subject, target, browse.ctx.now())):
        return
    m = browse.model()
    name = "its meeting task" if not is_person(target) and meetings.same_words(m, target, subject) else meetings.target_name(m, target)

    def undo() -> None:
        if browse._do(lambda: meetings.put_back(conn, before, key)):
            browse.say(f"“{subject}” is linked as it was before." if before else f"“{subject}” isn't linked.")

    browse.say_undo(f"“{subject}” is linked to {name}, each time it's on your calendar.", undo)


def pick_link(browse: BrowseWindow, x: Meeting, at: QPoint | None = None) -> MeetingPicker:
    """Link…: the `#` list of meetings and people (decision 491), the suggestion first. A pick links it."""
    picker = MeetingPicker(browse, browse.model, x.appointment.subject, x.suggestion, browse.ctx.settings.me)
    picker.picked.connect(lambda target: link(browse, x.appointment.subject, target) if target else None)
    picker.popup(at or QCursor.pos())
    browse.meeting_picker = picker  # kept, so it lives while it's open
    return picker


def open_agenda(browse: BrowseWindow, target: str) -> None:
    """Agenda (decision 492): a meeting task's page at its Agenda section, or a person's agenda in the Agendas view."""
    if is_person(target):
        browse.show_agenda(target)
        return
    browse.go_task(target)
    QTimer.singleShot(0, lambda: show_section(browse, "agenda"))


def show_section(browse: BrowseWindow, key: str) -> bool:
    """Open a section of the task page showing and scroll it to the top. False when the page has no such section (a task
    with nothing on its agenda), or isn't showing."""
    pane = getattr(browse, "task_pane", None)
    group = pane.header.groups.get(key) if pane is not None else None
    if group is None or group.isHidden() or browse.detail_stack.currentWidget() is not pane:
        return False
    group.set_open(True, emit=True)
    pane.widget().adjustSize()
    pane.verticalScrollBar().setValue(group.mapTo(pane.widget(), QPoint(0, 0)).y())
    return True


def open_notes(browse: BrowseWindow, x: Meeting) -> None:
    """Meeting notes (decision 492): on the linked task, today's meeting of a regular one or the one-off as it is; for a
    one-to-one linked to a person, a new meeting named by the subject."""
    if x.target and not is_person(x.target):
        browse.open_capture(task=x.target, meeting=True)
    else:
        browse.open_capture(meeting=True, meeting_name=x.appointment.subject)


def make_task(browse: BrowseWindow, x: Meeting) -> None:
    """Make a meeting task (decision 491): New task with Meeting ticked and the subject as its title. Once it's saved, the row
    suggests it, for Link."""
    browse.open_capture(mode="new_task", title=x.appointment.subject, as_meeting=True)


# ---- the minute tick ----
def start_timer(browse: BrowseWindow) -> QTimer:
    """Each minute while Today shows (``tick``)."""
    timer = QTimer(browse, interval=TICK_MS, timeout=lambda: tick(browse))
    timer.start()
    return timer


def tick(browse: BrowseWindow) -> None:
    """While Today shows: the calendar read again when it's 5 minutes old (decision 493); Today drawn again when what it
    lists changed, unless something's being typed in its box or a menu is open; else the next meeting's minutes, in place."""
    if not browse.isVisible() or browse.view != "today" or browse.query:
        return
    day, cal = day_of(browse.ctx)
    if signature(day, cal) != getattr(browse, "meetings_drawn", ()):
        box = getattr(browse, "today_note", None)
        busy = box is not None and (box.hasFocus() or box.text()) or QApplication.activePopupWidget() is not None
        if not busy:
            browse.render_list()
        return
    if day is None:
        return
    m = browse.model()
    for x in day.rest:
        item = getattr(browse, "meeting_rows", {}).get(x.appointment)
        if item is None:
            continue
        line = meeting_line(m, x)
        if item.data(0, LINE_ROLE) != line:
            item.setData(0, LINE_ROLE, line)
            item.setData(0, HTML_ROLE, line.html(LOOK.classic))
            cell = time_cell(x, browse.today())
            item.setData(browse.tree.columnCount() - (2 if LOOK.classic else 1), HTML_ROLE, _due_html(cell, False))
            item.setToolTip(0, cell.tip)


def read_again(ctx: AppContext) -> None:
    """F5: the calendar is read again the next time Today is drawn."""
    ctx.calendar.forget()


# ---- Link…'s list ----
class MeetingPicker(TaskPicker):
    """Link…: the `#` list (release 5.103's rows and keys) of meetings and people. With nothing typed: the suggested meeting
    task, the open meetings (without a regular meeting's occurrences) and the people; typing finds meetings, then people by
    any part of a name or alias, then any other open task, as Add to agenda's picker does. A pick sends a task's or a
    person's ID."""

    def __init__(self, parent: QWidget | None, model_fn: Callable[[], Model], subject: str, suggestion: str | None, me: str | None) -> None:
        super().__init__(parent, model_fn, none_entry=None)
        self.subject, self.suggestion, self.me = subject, suggestion, me
        self.hint = f"Link “{subject}” to a meeting, or to a person for a one-to-one"
        self.search.setPlaceholderText("Search meetings, people and tasks")
        self.search.setAccessibleName("Search meetings and people")

    def _person(self, person_id: str) -> items.Option:
        p = self.model.people[person_id]
        return items.Option(p.name, p.name, " · ".join(["Person", *p.aliases]), ref=p.id)

    def _people(self, query: str) -> list[str]:
        q = query.lower()
        return [p.id for p in self.model.active_people() if p.id != self.me and (not q or any(q in n.lower() for n in (p.name, *p.aliases)))]

    def list_rows(self, query: str) -> list[Row]:
        m = self.model
        meeting_ids = [t.id for t in meetings.meeting_tasks(m)]
        if query:
            found = items.task_matches(query, [(t.id, t.title) for t in m.tasks.values() if self._findable(t.id)],
                                       lambda i: items.ancestor_titles(m, i))
            rows: list[Row] = [self._option(x) for x in found if x in meeting_ids]
            rows += [self._person(p) for p in self._people(query)]
            rows += [self._option(x) for x in found if x not in meeting_ids]
            return rows[:SEARCH_LIMIT] or [Words("No meeting, person or open task matches.", heading=False)]
        rows = []
        if self.suggestion and self.suggestion in m.tasks:
            rows += [Words("Suggested"), self._option(self.suggestion)]
        others = [x for x in meeting_ids if x != self.suggestion]
        if others:
            rows += [Words("Meetings"), *(self._option(x) for x in others)]
        people = self._people("")
        if people:
            rows += [Words("People"), *(self._person(p) for p in people)]
        return rows or [Words("No meetings or people yet.", heading=False)]


# ---- Settings → Today's meeting links (decision 491) ----
class MeetingLinks(QWidget):
    """Each linked subject, what it's linked to, and Remove, which forgets the link at once (Today offers Link… again)."""

    def __init__(self, ctx: AppContext, message: Callable[[str], None]) -> None:
        super().__init__()
        self.ctx, self.message = ctx, message
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 12)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.removes: dict[str, QPushButton] = {}

    def load(self) -> None:
        """Show the links as they are in docs.db."""
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.removes = {}
        m = self.ctx.model()
        found = meetings.links(self.ctx.conn)
        if not found:
            self.grid.addWidget(QLabel("No meetings are linked yet. Link one on Today, from its row.", objectName="hint"), 0, 0, 1, 3)
            return
        for col, words in enumerate(("Subject", "Linked to")):
            self.grid.addWidget(QLabel(words, objectName="hint"), 0, col)
        for row, link in enumerate(found.values(), 1):
            subject = QLabel(link.subject)
            subject.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            gone = meetings.live_target(m, link) is None
            t = m.tasks.get(link.task or "")
            kind = "person" if link.person else "meeting" if t is not None and t.meeting else "task"
            to = QLabel(f"{meetings.target_name(m, link.target)} ({kind})" + (" · discarded, so it isn't shown" if gone else ""),
                        objectName="hint" if gone else "")
            remove = QPushButton("Remove")
            remove.setToolTip("Forget this link. The task, the person and the appointment stay as they are")
            remove.setAccessibleName(f"Remove the link of {link.subject}")
            remove.clicked.connect(lambda _=False, k=link.key: self.remove(k))
            self.removes[link.key] = remove
            self.grid.addWidget(subject, row, 0)
            self.grid.addWidget(to, row, 1)
            self.grid.addWidget(remove, row, 2)

    def remove(self, key: str) -> None:
        old = meetings.remove_link(self.ctx.conn, key)
        self.load()
        self.ctx.today_changed()
        if old is not None:
            self.message(f"“{old.subject}” is no longer linked; Today offers Link… for it again.")
