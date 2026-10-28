"""The capture window: the hotkey window where everything enters DocRepo.

Top to bottom: the task picker, the capture types (Note, New task, Update) with
Agenda and Today beside them, a line saying what Save will do, then the title
(New task only) and the content text, with what Parse and populate found beside
them, then the files, Copy prompt and the summary, and the New task and Update
fields. A "?" button opens the mods log. Esc hides the window and keeps the
draft; Ctrl+Enter saves; Alt+P parses; Alt+N, Alt+T and Alt+U tick the capture
types, Alt+A goes to the agenda picker and Alt+D to Today; F11 expands the
content text; F1 lists the keys (mods log round 2, M0036, M0037, M0042, M0046).

Release 5.8 (M0048 phase 2, M0049, M0052): the content text's operators make items, with a card for each beside it
(``docrepo.items``, ``items_panel``), and Meeting notes (Alt+M) takes a meeting's notes, with its agenda beside them.
The draft saves itself every 30 seconds to the data root, and comes back after a crash or a restart.

Ported from the browse tool mockup's ``capture.js``; SPEC section 7 describes it.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import diagnose, items, key_dates, msg, outlook, timeline
from docrepo.db import RECURRENCES, STATES
from docrepo.extract import extract_text, to_unc
from docrepo.layer0 import Part, size_text
from docrepo.links import is_link, link_name
from docrepo.text import typed_path
from docrepo.model import TODAY, Model, is_person
from docrepo.parse import Found, Known, Who, as_plant_event, parse_capture, quick_update
from docrepo.prompts import capture_blocks, load_summary_types, prompt_text
from docrepo.save import (
    CaptureDraft,
    Attachment,
    EmailItem,
    FileRow,
    NewTaskFields,
    SaveError,
    default_description,
    email_layer0_line,
    email_rows,
    item_names,
    meeting_case,
    meeting_name,
    held_text,
    msg_name,
    part_of,
    save_capture,
    split_parts,
)
from docrepo.schedule import is_open, start_of
from docrepo.tasks import KeyDateRow
from docrepo.ui import tokens
from docrepo.ui.context import AppContext
from docrepo.ui.drop_target import DropOverlay, DropRead
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.items_panel import AgendaPanel, ItemCards, OperatorHighlighter, RefPopup, _drop, task_colour, where_text
from docrepo.ui.keymap import KeyMapDialog
from docrepo.ui.look import LOOK, Help, KeyBadge, KeyTips, set_hints, tip
from docrepo.ui.mods_panel import ModsPanel
from docrepo.ui.palette import Command, CommandPalette
from docrepo.ui.rich_edit import KEYS as FORMAT_KEYS, FormatBar, RichEdit
from docrepo.ui.style import style_sheet
from docrepo.ui.task_picker import TaskPicker, full_path, path_text
from docrepo.ui.widgets import (
    Chip,
    ChipPicker,
    DateField,
    FlowLayout,
    HoursField,
    InfoButton,
    Option,
    field,
    label_options,
    people_options,
    set_filled,
)

log = logging.getLogger(__name__)

#: A line of the content text that is a file path adds that file; deleting the line removes it. A link on a line of its
#: own does the same (``links.LINK_LINE``).
PATH_LINE = re.compile(r"^(?:\\\\[^\\\s][^\\]*\\.+|[A-Za-z]:\\.+)\.[A-Za-z0-9]{1,5}$")


def existing_file(path: str) -> str | None:
    """``path`` if it's a file, else the same path with its no-break spaces as spaces when that is one (a path copied
    from an email or a chat can have them), else None (release 5.26.1)."""
    for candidate in dict.fromkeys((path, path.replace(" ", " "))):
        try:
            if Path(candidate).is_file():
                return candidate
        except OSError:
            continue
    return None


WIDTH = 940
#: Below this width, what Parse and populate found goes under the content text instead of beside it.
NARROW = 700
#: The draft the capture window keeps every 30 seconds (release 5.8), in the data root.
DRAFT_FILE = Path("System") / "capture-draft.json"
DRAFT_EVERY_MS = 30_000
DRAFT_NOTE = "The draft saves itself every 30 seconds."
#: The content text's placeholder: what to type, while the box is empty (decision 7).
CONTENT_PLACEHOLDER = "Type a note. @name makes a task, #task files it on a task, ** says what a line is."
MEETING_PLACEHOLDER = "Meeting notes. @name makes a task, #task files a line on a task, ** says what a line is."
#: The items' and the agenda's column, beside the content text.
SIDE_WIDTH = 300
#: The new look's shortest window: it grows with the content, up to most of the screen.
MIN_HEIGHT = 380
#: The placeholder in the found list, before Parse and populate runs (shown with Show hints).
FOUND_EMPTY = ("<span style='color:#5a6571'>Alt+P reads the content text and fills the fields. What it finds is listed here, beside "
               "the text, so you can check it without scrolling.</span>")


def understood_html(found: list) -> str:
    """What Parse and populate understood, as one line under the content text (the visual overhaul's O3)."""
    sep = " &nbsp;·&nbsp; "
    parts = []
    for lead, f in found:
        value = f.value if len(f.value) <= 40 else f.value[:40] + "…"
        why = f" <span style='color:{tokens.colour('text2')}'>({esc(f.why)})</span>" if f.why else ""
        parts.append(f"<b>{esc(lead + f.field)}</b> {esc(value)}{why}")
    return f"<span style='color:{tokens.colour('caution')}'>Understood</span>&nbsp;&nbsp;" + sep.join(parts)


def and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class FileEntry:
    """A file or email added to the capture, with its row of widgets. An email's own row has no description: its parts
    (email layer 0) are rows of their own, each with Keep."""

    row: FileRow
    src: str  # dropped, picked, pasted, added (Add link…), outlook (an email) or email (one of its parts)
    line: str | None = None  # for a pasted path or link, the line in the content text it came from
    doc: str | None = None  # an already tracked document this file reuses
    widget: QWidget | None = None
    desc: QLineEdit | None = None
    copy: QCheckBox | None = None
    extract: QCheckBox | None = None
    keep: QCheckBox | None = None  # an email's part: whether it's kept
    layer0: QLabel | None = None  # an email's row: what email layer 0 kept and left out
    note: QLabel | None = None  # the line beside its name (_file_note); an email's names its .msg file
    goes: QToolButton | None = None  # in a note split by # task, which capture it goes with (release 5.32)
    what: str = ""  # the description's question, the start of its placeholder


def read_drop(mime, links: bool = False) -> tuple[str, list[str]]:
    """What a drop holds: ("files", paths) for files that have a place on disk; ("outlook", []) for an email dragged
    from Outlook; ("virtual", []) for files only another program holds, such as one inside a zip folder; with ``links``,
    ("links", addresses) for web links dragged from a browser or an email (mods log round 3, M0053); ("", []) for
    anything else (text, which the content text box takes as text).

    Files come first: File Explorer's drags carry the same "virtual file" format as Outlook's (FileGroupDescriptorW)
    next to the files, so only Outlook's own formats mean an email.
    """
    paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
    if paths:
        return "files", paths
    formats = mime.formats()
    if outlook.is_outlook_drop(formats):
        return "outlook", []
    if any("FileGroupDescriptor" in f for f in formats):
        return "virtual", []
    web = [u.toString() for u in mime.urls() if u.scheme() in ("http", "https")] if links else []
    if web:
        return "links", web
    return "", []


def note_drag(stage: str, mime, links: bool = False) -> str:
    """read_drop's answer, after noting the drag for the troubleshooting report: its formats' names and how many
    URLs it carried, never their paths or contents."""
    kind, _paths = read_drop(mime, links)
    urls = mime.urls()
    diagnose.note_drag(stage, list(mime.formats()), len(urls), sum(1 for u in urls if u.isLocalFile()), kind)
    return kind


def _accept_copy(event) -> None:
    """Take a drop as a copy, never a move: the original stays where it is."""
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()


class ContentEdit(RichEdit):
    """The content text box, with formatting and lists (mods log round 2, M0045). Files and Outlook emails can be dropped
    on it; ``dropped`` sends read_drop's answer."""

    dropped = Signal(str, list)
    #: Whether a web link dropped on it is added as a link, as the pinned window's box does, rather than typed in.
    take_links = False
    #: Headings that fold, while the note is taken (release 5.28, mods log round 4).
    takes_headings = True
    folds_here = True

    #: Called with read_drop's answer when a drag comes in (release 5.33): an email or a file with no path on disk puts
    #: up the window's DropOverlay, for DocRepo's own drop target.
    drag_entered: Callable[[str], None] | None = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt's name
        if kind := note_drag("enter", event.mimeData(), self.take_links):
            _accept_copy(event)
            if self.drag_entered:
                self.drag_entered(kind)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData(), self.take_links)[0]:
            _accept_copy(event)
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        note_drag("drop", event.mimeData(), self.take_links)
        kind, paths = read_drop(event.mimeData(), self.take_links)
        if kind:
            _accept_copy(event)
            # The cursor goes where it was dropped: in a note split by # task, the file goes with that section (release 5.32).
            self.setTextCursor(self.cursorForPosition(event.position().toPoint()))
            self.dropped.emit(kind, paths)
        else:
            super().dropEvent(event)

    #: The @ and # list's keys (release 5.8): given a key, True when the open list used it.
    list_keys: Callable[[int], bool] | None = None
    #: Called when the box loses the keyboard, to close that list.
    left: Callable[[], None] | None = None

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.list_keys and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier and self.list_keys(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if self.left:
            self.left()


class _KeyDateLine(QFrame):
    """One key date in the Key dates rows: its description and ✕, then its dates and its three ticks."""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, row: KeyDateRow | None = None) -> None:
        super().__init__(objectName="keyDateRow")
        self.key_id = row.id if row else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self.description = QLineEdit(row.description if row else "")
        self.description.setPlaceholderText("Description, such as Trial execution window")
        self.description.setAccessibleName("Key date description")
        self.description.textEdited.connect(lambda _: self.changed.emit())
        top.addWidget(self.description, 1)
        x = QToolButton(text="✕")
        x.setAutoRaise(True)
        x.setToolTip("Take this key date off")
        x.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(x)
        lay.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.start, self.end = DateField(), DateField()
        for w, name, value in ((self.start, "Start", row.start if row else None), (self.end, "End", row.end if row else None)):
            w.set_value(value)
            w.line.setPlaceholderText(name)
            w.line.setAccessibleName(f"Key date {name.lower()}")
            w.setMaximumWidth(150)
            w.edited.connect(self.changed.emit)
        bottom.addWidget(self.start)
        bottom.addWidget(QLabel("to", objectName="hint"))
        bottom.addWidget(self.end)
        self.plant, self.deadline, self.done = QCheckBox("Plant activity"), QCheckBox("Deadline"), QCheckBox("Done")
        for box, on, tip in ((self.plant, row.plant if row else False, "A major plant activity: a plant event of its own"),
                             (self.deadline, row.deadline if row else False, "A hard deadline: a red diamond at its end"),
                             (self.done, row.done if row else False, "Done: off Today and the lists")):
            box.setChecked(on)
            box.setToolTip(tip)
            box.toggled.connect(lambda _: self.changed.emit())
            bottom.addWidget(box)
        bottom.addStretch()
        lay.addLayout(bottom)

    def value(self) -> KeyDateRow:
        return KeyDateRow(self.start.value(), self.end.value(), self.description.text().strip(), self.plant.isChecked(),
                          self.deadline.isChecked(), self.done.isChecked(), self.key_id)

    def blank(self) -> bool:
        return not (self.start.line.text().strip() or self.end.line.text().strip() or self.description.text().strip())


class KeyDatesEditor(QWidget):
    """Key dates (release 5.31, the key dates plan, item 57) in New task and Update: any number of rows, each a start, an
    end, a description and the Plant activity, Deadline and Done ticks, with ✕, and Add key date. Folded under its link
    until there's one. A ``**date`` line's card adds its key date only when the capture is saved, not here."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.toggle = QPushButton("Key dates ▸", objectName="moreLink")
        self.toggle.setToolTip("Dates on the task beside its own: a start, an end or both, with a description")
        self.toggle.clicked.connect(lambda: self._fold(not self.body.isHidden()))
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(2)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(2)
        bl.addLayout(self.rows_box)
        add = QPushButton("+ Add key date", objectName="link")
        add.clicked.connect(lambda: self.add_row(focus=True))
        bl.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.hide()
        lay.addWidget(self.body)
        self.lines: list[_KeyDateLine] = []

    def _fold(self, folded: bool) -> None:
        self.body.setVisible(not folded)
        if not folded and not self.lines:
            self.add_row(focus=True)
        self._sync()

    def _sync(self) -> None:
        n = sum(not x.blank() for x in self.lines)
        self.toggle.setText(f"Key dates{f' ({n})' if n else ''} {'▸' if self.body.isHidden() else '▾'}")

    def add_row(self, row: KeyDateRow | None = None, focus: bool = False) -> None:
        line = _KeyDateLine(row)
        line.changed.connect(self._changed)
        line.removed.connect(self._remove)
        self.rows_box.addWidget(line)
        self.lines.append(line)
        self.body.show()
        self._sync()
        if focus:
            line.description.setFocus()

    def _remove(self, line: _KeyDateLine) -> None:
        self.lines.remove(line)
        line.hide()
        line.setParent(None)
        line.deleteLater()
        self._changed()

    def _changed(self) -> None:
        self._sync()
        self.changed.emit()

    def set_rows(self, rows: list[KeyDateRow]) -> None:
        """Show these key dates (none: folded), without counting it as a change."""
        for line in self.lines:
            line.hide()
            line.setParent(None)
            line.deleteLater()
        self.lines = []
        for row in rows:
            self.add_row(row)
        self.body.setVisible(bool(rows))
        self._sync()

    def rows(self) -> list[KeyDateRow]:
        """The key dates in the rows, in order; a row with nothing in it is left out."""
        return [x.value() for x in self.lines if not x.blank()]

    def problem(self) -> tuple[str, QWidget] | None:
        """The first row that can't be saved, as (what's wrong, where to put the cursor)."""
        for x in self.lines:
            if x.blank():
                continue
            for w, name in ((x.start, "start"), (x.end, "end")):
                if not w.is_valid():
                    return f"A key date's {name} isn't a date. Use YYYY-MM-DD.", w.line
            p = key_dates.problem(x.start.value(), x.end.value())
            if p:
                return p, x.start.line
        return None


class CaptureWindow(QWidget):
    """The capture window. It's made once at start-up and shown or hidden, so it opens at once."""

    #: Sends the SaveResult after each save, so the browse tool can show what Save did.
    saved = Signal(object)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx = ctx
        self.setObjectName("capture")
        self.setWindowTitle("DocRepo Capture")
        self.setStyleSheet(style_sheet())
        self.setAcceptDrops(True)
        self._setting = False  # True while the window fills fields itself, so it doesn't count as typing
        self._after_pick: str | None = None  # "update" or "agenda" when that hotkey opened the task picker
        self._summary_types: list = []
        self.expanded = False  # Expand (F11): the content text fills the window (mods log round 2, M0046, M0048 phase 1)
        self.pinned = False  # Pin (F12): the small window at the bottom right (mods log round 3, M0053, M0054)
        self.pin_window = None  # made the first time it's pinned (docrepo/ui/pin_window.py)
        # DocRepo's own drop target, for emails from Outlook (release 5.33): a cover that's up while one is dragged over.
        self.drop_overlay = DropOverlay(self, self.take_drop)
        self._saving = False
        self.today_on = False  # Today, beside the capture types (M0037)
        self._missing_paths: dict[str, bool] = {}  # path lines that aren't files DocRepo can find, and whether it's said so
        self._path_timer = QTimer(self)
        self._path_timer.setSingleShot(True)
        self._path_timer.setInterval(350)
        self._path_timer.timeout.connect(self._sync_paths)
        # Items and meeting notes (release 5.8): the content text is read again a moment after you stop typing.
        self.meeting_on = False
        self.reading: items.Reading | None = None
        self._names: items.Names | None = None
        self._typing: items.Typing | None = None
        self._highlighting = False
        self._items_timer = QTimer(self)
        self._items_timer.setSingleShot(True)
        self._items_timer.setInterval(250)
        self._items_timer.timeout.connect(self.read_items)
        # The draft keeps itself every 30 seconds, in the data root, and comes back after a crash or a restart.
        self.draft_dirty = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setInterval(DRAFT_EVERY_MS)
        self._draft_timer.timeout.connect(self.keep_draft)
        # The new look's window fits its content (O3), a moment after a change, by a timer that goes with the window.
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit)
        self._build()
        self.reset_draft()
        self.restore_draft()
        self._draft_timer.start()
        for keys, handler in (("Ctrl+Return", self.save), ("Ctrl+Enter", self.save), ("Alt+P", self.parse),
                              # One letter per topic (mods log round 2, M0036)
                              ("Alt+N", lambda: self._alt_type("note")), ("Alt+T", lambda: self._alt_type("new_task")),
                              ("Alt+U", lambda: self._alt_type("update")), ("Alt+A", self._alt_agenda), ("Alt+D", self._alt_today),
                              ("Alt+M", self.toggle_meeting), ("F11", self.toggle_expand), ("F12", self.toggle_pin),
                              ("F1", self.show_keys), ("Ctrl+K", self.open_palette)):
            QShortcut(QKeySequence(keys), self, handler)

    # ================= building the window =================
    def _build(self) -> None:
        """The new look (the visual overhaul's stage O3, release 5.12): what the capture is, Today and Agenda, and the icon
        tools on one row; the task picker (with State for an update, or the meeting's name) under it; the content text in
        one outlined editor, with Parse, Attach and what Parse and populate understood under it; the items and the agenda
        beside it only when there are any; and a footer that says what Save will do, with More and Save."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.keytips = KeyTips(self)
        self.hotkey_label = KeyBadge(self.ctx.settings.hotkey)  # the main hotkey, shown with Show hints

        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        capture_page = QWidget()
        cp = QVBoxLayout(capture_page)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(12)
        scroll.setWidget(body)
        self.scroll = scroll
        cp.addWidget(scroll, 1)
        self._footer = self._build_footer()
        cp.addWidget(self._footer)
        self.pages.addWidget(capture_page)
        self.mods = ModsPanel(self.ctx)
        self.mods.back.connect(lambda: self.show_mods(False))
        self.pages.addWidget(self.mods)

        b = self.body
        # ---- row 1: what the capture is, Today and Agenda, then Meeting notes, Expand and the mods log ----
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        types_box = self.types_box = QWidget(objectName="typeStrip")
        types = QHBoxLayout(types_box)
        types.setContentsMargins(2, 2, 2, 2)
        types.setSpacing(2)
        self.type_boxes: dict[str, QCheckBox] = {}
        for key, label, letter in (("note", "Note", "N"), ("new_task", "New task", "T"), ("update", "Update", "U")):
            box = QCheckBox(label, objectName="typeToggle")
            tip(box, {"note": "Reference information, or a note on the picked task", "new_task": "A new task, from this text",
                      "update": "A status update to the picked task"}[key], f"Alt+{letter}")
            box.clicked.connect(lambda checked, k=key: self.set_type(k, checked))
            self.type_boxes[key] = box
            types.addWidget(box)
            types.addWidget(KeyBadge(f"Alt+{letter}"))
            self.keytips.add(box, letter)
        row1.addWidget(types_box)
        types_note = QLabel()
        row1.addWidget(InfoButton("types", types_note))
        self.meeting_title = QLabel("Meeting notes", objectName="heading")  # meeting notes take the capture types' place
        self.meeting_title.hide()
        row1.addWidget(self.meeting_title)
        row1.addStretch(1)
        agenda_note = QLabel()
        row1.addWidget(InfoButton("agenda", agenda_note))
        self.today_button = QPushButton("Today", objectName="today")
        self.today_button.setIcon(icon("sun"))
        self.today_button.setCheckable(True)
        self.today_button.clicked.connect(self.set_today)
        self.keytips.add(self.today_button, "D")
        row1.addWidget(self.today_button)
        self.agenda = ChipPicker(self._agenda_options, "Agenda")
        self.agenda.setFixedWidth(220)
        self.agenda.changed.connect(self.refresh)
        self.keytips.add(self.agenda, "A")
        row1.addWidget(self.agenda)
        line = self.agenda_divider = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setObjectName("divider")
        row1.addWidget(line)
        self.meeting_button = self._icon_button("people", "Meeting notes: the meeting's name, its agenda and room to write", "Alt+M", "M")
        self.meeting_button.setCheckable(True)
        self.meeting_button.clicked.connect(lambda _=False: self.toggle_meeting())
        row1.addWidget(self.meeting_button)
        self.expand_button = self._icon_button("expand", "Expand the content text", "F11", "F11")
        self.expand_button.clicked.connect(self.toggle_expand)
        row1.addWidget(self.expand_button)
        self.pin_button = self._icon_button("pin", "Pin: a small window at the bottom right, to drop files, emails and links on",
                                            "F12", "F12")
        self.pin_button.clicked.connect(self.pin)
        row1.addWidget(self.pin_button)
        mods_button = self._icon_button("feedback", "Mods log: note a change you want in DocRepo")
        mods_button.clicked.connect(lambda: self.show_mods(True))
        row1.addWidget(mods_button)
        b.addLayout(row1)
        b.addWidget(types_note)
        b.addWidget(agenda_note)
        # ---- row 2: the task picker, with State beside it for an update, or the meeting's name ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.task_button = QPushButton()
        self.task_button.setStyleSheet("text-align: left; padding-left: 10px;")
        self.task_button.setIcon(icon("chevron-down"))
        self.task_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # the arrow at the right end
        tip(self.task_button, "The task this capture belongs to")
        self.task_button.clicked.connect(self._open_picker)
        task_note = QLabel()
        row2.addWidget(self.task_button, 1)
        row2.addWidget(InfoButton("task", task_note))
        self.u_state = QComboBox()
        self.u_state.addItems(list(STATES))
        self.state_row = QWidget()
        sr = QHBoxLayout(self.state_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        sr.addWidget(QLabel("State", objectName="fieldLabel"))
        self.u_state.setFixedWidth(150)
        sr.addWidget(self.u_state)
        self.state_row.hide()
        row2.addWidget(self.state_row)
        self.meeting_row = QWidget()
        mr = QHBoxLayout(self.meeting_row)
        mr.setContentsMargins(0, 0, 0, 0)
        self.meet_name = QLineEdit()
        self.meet_name.setPlaceholderText("Name the meeting")
        self.meet_name.setAccessibleName("Meeting")
        self.meet_name.textEdited.connect(self._meet_typed)
        mr.addWidget(self.meet_name, 1)
        meet_note = QLabel()
        mr.addWidget(InfoButton("meetmode", meet_note))
        self.meeting_row.hide()
        row2.addWidget(self.meeting_row, 1)
        b.addLayout(row2)
        b.addWidget(task_note)
        self.meet_what = Help()
        b.addWidget(self.meet_what)
        b.addWidget(meet_note)
        self.meet_what.hide()
        self._meet_name_typed = False
        # ---- the title and the content text on the left; the agenda and the items beside them (M0042, release 5.8) ----
        self.main = QWidget()
        self.main_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.main)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(16)
        left = QWidget()
        lc = QVBoxLayout(left)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(8)
        self.main_layout.addWidget(left, 8)
        b.addWidget(self.main)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Taken from the content text if you leave it empty")
        self.title.textEdited.connect(lambda: self._touch("new.title", self.title))
        self.title.textChanged.connect(lambda _: self._apply_same_all())  # empty descriptions name the new task
        self.title_field = field("Title", self.title, "title")
        lc.addWidget(self.title_field)
        self.content = ContentEdit()
        self.content.takes_pictures = True  # a picture pasted becomes the capture's file (release 5.27, decision 129)
        self.content.image_pasted.connect(self._picture_pasted)
        self.content.setMinimumHeight(120)
        self.content.setPlaceholderText(CONTENT_PLACEHOLDER)
        self.content.textChanged.connect(self._content_changed)
        self.content.dropped.connect(self.dropped)
        self.content.drag_entered = self._drag_entered
        self.content.cursorPositionChanged.connect(self._ref_list)
        self.content.cursorPositionChanged.connect(self._tell_missing_paths)
        self.content.list_keys = lambda key: self.ref_popup.handle_key(key)
        self.content.left = lambda: self.ref_popup.hide()
        self.highlighter = OperatorHighlighter(self.content.document())
        self.format_bar = FormatBar(self.content)
        for key, keys in FORMAT_KEYS.items():
            self.keytips.add(self.format_bar.buttons[key], keys, ctrl=True)
        editor = QFrame(objectName="editor")  # one outlined box: the formatting toolbar along its top, then the text
        el = QVBoxLayout(editor)
        el.setContentsMargins(1, 1, 1, 1)
        el.setSpacing(0)
        self.format_bar.layout().setContentsMargins(4, 2, 4, 2)
        el.addWidget(self.format_bar)
        el.addWidget(self.content, 1)
        if not LOOK.classic:
            self.format_bar.show_on_use(editor)
        self.content_field = field("Content text", editor, "content")
        self.content_field.property("label").setVisible(LOOK.show_help)  # the editor speaks for itself; its placeholder says what to type
        lc.addWidget(self.content_field, 1)
        self.content_hint = Help()
        lc.addWidget(self.content_hint)
        # Under the editor: Parse, Attach, and what Parse and populate understood (in place of the found panel)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.parse_button = QPushButton("Parse", objectName="subtle")
        self.parse_button.setIcon(icon("wand"))
        tip(self.parse_button, "Parse and populate: fill the fields from the content text", "Alt+P")
        self.parse_button.clicked.connect(self.parse)
        self.keytips.add(self.parse_button, "P")
        tools.addWidget(self.parse_button)
        parse_note = QLabel()
        tools.addWidget(InfoButton("parse", parse_note))
        self.attach_button = QPushButton("Attach", objectName="subtle")
        self.attach_button.setIcon(icon("attach"))
        self.attach_button.setProperty("menu", True)
        tip(self.attach_button, "Add files, a link or the email selected in Outlook. Or drop them anywhere on this window.")
        attach_menu = QMenu(self.attach_button)
        attach_menu.addAction(icon("file"), "Files…", self._pick_files)
        attach_menu.addAction(icon("link"), "A link…", self.add_link)
        attach_menu.addAction(icon("mail"), "The email selected in Outlook", self.add_outlook)
        self.attach_button.setMenu(attach_menu)
        tools.addWidget(self.attach_button)
        self.found_box = QFrame(objectName="found")  # what Parse and populate understood: one line, under the text
        fbl = QHBoxLayout(self.found_box)
        fbl.setContentsMargins(8, 4, 8, 4)
        fbl.setSpacing(8)
        self.found_label = QLabel()
        self.found_label.setWordWrap(True)
        self.found_label.setTextFormat(Qt.TextFormat.RichText)
        self.found_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # it wraps to the room it has
        fbl.addWidget(self.found_label, 1)
        self.clear_found = QPushButton("Clear", objectName="link")
        tip(self.clear_found, "Forget what Parse and populate found. The fields keep their values.")
        self.clear_found.clicked.connect(self._clear_found)
        fbl.addWidget(self.clear_found, 0, Qt.AlignmentFlag.AlignTop)
        tools.addWidget(self.found_box, 1)
        tools.addStretch(0)
        lc.addLayout(tools)
        lc.addWidget(parse_note)
        # Beside the content text: the meeting's agenda and the items (release 5.8), only when there are any.
        self.side = QWidget()
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self.agenda_panel = AgendaPanel()
        agenda_panel_note = QLabel()
        self.agenda_panel.info_slot.insertWidget(1, InfoButton("agendaPanel", agenda_panel_note))
        self.agenda_panel.ticked.connect(self._agenda_ticked)
        self.agenda_panel.start.connect(self.start_from_agenda)
        self.agenda_panel.hide()
        sl.addWidget(self.agenda_panel)
        sl.addWidget(agenda_panel_note)
        self.item_cards = ItemCards()
        items_note = QLabel()
        self.item_cards.info_slot.insertWidget(1, InfoButton("items", items_note))
        self.item_cards.changed.connect(self._item_changed)
        self.item_cards.go.connect(self._go_line)
        sl.addWidget(self.item_cards)
        sl.addWidget(items_note)
        sl.addStretch()
        self.side.setFixedWidth(SIDE_WIDTH)
        self.main_layout.addWidget(self.side, 0)
        self.ref_popup = RefPopup(self)
        self.ref_popup.picked.connect(self._pick_ref)
        # Below the content text: what Expand folds away
        self.folded = Help()
        self.folded.hide()
        b.addWidget(self.folded)
        self.lower = QWidget()
        self.lower_layout = QVBoxLayout(self.lower)
        self.lower_layout.setContentsMargins(0, 0, 0, 0)
        self.lower_layout.setSpacing(12)
        b.addWidget(self.lower)
        b = self.lower_layout
        # Files: a row for each, once there are any (Attach, above, adds them)
        self.files_box = QVBoxLayout()
        self.files_box.setSpacing(8)
        self.files_label = field("Files", None, "files", "a description for each")
        b.addWidget(self.files_label)
        b.addLayout(self.files_box)
        self.same_all = QCheckBox("Use the first file's description and choices for every file")
        self.same_all.toggled.connect(self._apply_same_all)
        b.addWidget(self.same_all)
        self.copy_hint = Help()
        b.addWidget(self.copy_hint)
        # Copy prompt and the summary: the summary type is picked in More, beside Save
        self.prompt_type = QComboBox()
        self.prompt_type.setAccessibleName("Summary type")
        self.prompt_type.hide()
        b.addWidget(self.prompt_type)
        self.summary = QPlainTextEdit()
        self.summary.setFixedHeight(70)
        self.summary_field = field("Summary", self.summary, "summary", "paste the LLM's answer here")
        b.addWidget(self.summary_field)
        self.add_summary = QPushButton("Add a summary", objectName="link")  # also in More
        self.add_summary.clicked.connect(lambda: self._show_summary(True))
        self.add_summary.hide()
        b.addWidget(self.add_summary)
        self._build_new_fields()
        self._build_update_fields()
        self.body.addStretch()

    def _icon_button(self, name: str, text: str, key: str = "", tip_key: str = "") -> QToolButton:
        """A 28 px icon button with its tooltip, and its key tip while Alt is held."""
        button = QToolButton(objectName="iconButton")
        button.setIcon(icon(name))
        button.setIconSize(icon_size(16))
        button.setFixedSize(tokens.ICON_BUTTON, tokens.ICON_BUTTON)
        button.setAccessibleName(text.split(":")[0])
        tip(button, text, key)
        if tip_key:
            self.keytips.add(button, tip_key)
        return button

    def _build_footer(self) -> QWidget:
        """The footer: what Save will do and the draft's state on the left; More and Save on the right."""
        footer = QWidget(objectName="footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)
        status = QVBoxLayout()
        status.setSpacing(2)
        self.does = QLabel(objectName="does")
        self.does.setWordWrap(True)
        status.addWidget(self.does)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        status.addWidget(self.error)
        state = QHBoxLayout()
        state.setSpacing(8)
        self.draft_label = QLabel(DRAFT_NOTE if LOOK.show_help else "", objectName="hint")
        self.draft_label.setToolTip(f"In {DRAFT_FILE} in the data root. After a crash or a restart, the capture window opens with it.")
        state.addWidget(self.draft_label)
        self.undo_clear = QPushButton("Undo", objectName="link")
        self.undo_clear.clicked.connect(self._undo_clear)
        self.undo_clear.hide()
        state.addWidget(self.undo_clear)
        state.addStretch()
        status.addLayout(state)
        fl.addLayout(status, 1)
        footer_hint = Help("Ctrl+Enter saves. Esc hides the window and keeps the draft. F1 lists the keys.")
        fl.addWidget(footer_hint)
        more = QPushButton("More", objectName="subtle")
        more.setIcon(icon("more"))
        more.setProperty("menu", True)
        tip(more, "Copy prompt, a summary, Clear, hints, keys and the mods log")
        self.more_menu = QMenu(more)
        self.more_menu.aboutToShow.connect(self._fill_more)
        more.setMenu(self.more_menu)
        fl.addWidget(more)
        self.clear_button = QPushButton("Clear")  # in More in the new look; beside Save in the Classic one
        self.clear_button.clicked.connect(self.clear)
        self.clear_button.setVisible(LOOK.classic)
        fl.addWidget(self.clear_button)
        save = QPushButton("Save", objectName="primary")
        save.setMinimumWidth(96)
        tip(save, "Save", "Ctrl+Enter")
        save.clicked.connect(self.save)
        self.keytips.add(save, "Ctrl+Enter", ctrl=True)
        fl.addWidget(save)
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.setInterval(10_000)
        self._undo_timer.timeout.connect(lambda: (self.undo_clear.hide(), setattr(self, "_cleared", None)))
        self._cleared: dict | None = None
        return footer

    def _fill_more(self) -> None:
        """More, beside Save: Copy prompt for each summary type, a summary, Clear, Show hints, the keys and the mods log."""
        menu = self.more_menu
        menu.clear()
        self._load_summary_types()
        prompt = menu.addMenu(icon("copy"), "Copy prompt")
        for i in range(self.prompt_type.count()):
            prompt.addAction(self.prompt_type.itemText(i), lambda n=i: (self.prompt_type.setCurrentIndex(n), self.copy_prompt()))
        add = menu.addAction("Add a summary", lambda: self._show_summary(True))
        add.setEnabled(self.summary_field.isHidden())
        menu.addSeparator()
        menu.addAction("Clear the capture", self.clear)
        menu.addSeparator()
        hints = menu.addAction("Show hints", lambda: self._set_hints(not LOOK.hints))
        hints.setCheckable(True)
        hints.setChecked(LOOK.hints)
        menu.addAction(icon("search"), "Command palette\tCtrl+K", self.open_palette)
        menu.addAction(icon("keyboard"), "Keys\tF1", self.show_keys)
        menu.addAction(icon("feedback"), "Mods log", lambda: self.show_mods(True))

    def palette_commands(self) -> list[Command]:
        """Every command the capture window's palette offers (the visual overhaul's O7)."""
        self._load_summary_types()
        out = [Command("Capture", "Note", lambda: self._alt_type("note"), "Alt+N"),
               Command("Capture", "New task", lambda: self._alt_type("new_task"), "Alt+T"),
               Command("Capture", "Update", lambda: self._alt_type("update"), "Alt+U"),
               Command("Capture", "Today", self._alt_today, "Alt+D"),
               Command("Capture", "Put it on an agenda", self._alt_agenda, "Alt+A"),
               Command("Capture", "Pick its task", self._open_picker),
               Command("Capture", "Parse and populate", self.parse, "Alt+P"),
               Command("Capture", "Meeting notes", self.toggle_meeting, "Alt+M"),
               Command("Capture", "Expand", self.toggle_expand, "F11"),
               Command("Capture", "Pin it at the bottom right", self.pin, "F12"),
               Command("Attach", "Files", self._pick_files),
               Command("Attach", "A link", self.add_link),
               Command("Attach", "The email selected in Outlook", self.add_outlook)]
        out += [Command("Copy prompt", self.prompt_type.itemText(i), lambda n=i: (self.prompt_type.setCurrentIndex(n), self.copy_prompt()))
                for i in range(self.prompt_type.count())]
        out += [Command("", "Add a summary", lambda: self._show_summary(True)),
                Command("", "Save", self.save, "Ctrl+Enter"),
                Command("", "Clear the capture", self.clear),
                Command("", "Hide hints" if LOOK.hints else "Show hints", lambda: self._set_hints(not LOOK.hints)),
                Command("", "Keys", self.show_keys, "F1"),
                Command("", "Mods log", lambda: self.show_mods(True)),
                Command("", "Hide the window", self.hide, "Esc")]
        return out

    def open_palette(self) -> None:
        """Ctrl+K: every command here, narrowed as you type (decision 6)."""
        if self.pages.currentIndex() != 0:
            return
        self._palette = CommandPalette(self, self.palette_commands())
        self._palette.open_over(self)

    def _set_hints(self, on: bool) -> None:
        """Show hints, from More: at once, and kept in Settings."""
        set_hints(on)
        self.ctx.settings.show_hints = on
        try:
            self.ctx.settings.save(self.ctx.fs, self.ctx.data_root)
        except OSError as e:
            log.warning("Couldn't keep Show hints in settings.json: %s", e)
        if self.draft_label.text() in ("", DRAFT_NOTE):  # not while it says the draft was kept, cleared or brought back
            self.draft_label.setText(DRAFT_NOTE if LOOK.show_help else "")
        self.refresh()

    def _build_new_fields(self) -> None:
        self.new_group = QGroupBox()
        g = QVBoxLayout(self.new_group)
        g.setSpacing(12)
        self.n_labels = ChipPicker(self._label_options, "Search or add", "Create label “{}”")
        self.n_inherit = QCheckBox("Inherit parent labels")
        self.n_inherit.setChecked(True)
        self.n_inherit.toggled.connect(self.refresh)
        self.n_inherited = QLabel(objectName="hint")
        g.addWidget(field("Labels", self.n_labels, "labels"))
        inh = QHBoxLayout()
        inh.addWidget(self.n_inherit)
        inh.addWidget(self.n_inherited, 1)
        self.n_inherit_row = QWidget()
        self.n_inherit_row.setLayout(inh)
        g.addWidget(self.n_inherit_row)
        grid = QGridLayout()
        self.n_leads = ChipPicker(self._people_options, "Search names and aliases", "Add “{}” to people")
        self.n_assignees = ChipPicker(self._people_options, "Search names and aliases", "Add “{}” to people")
        self.n_due, self.n_deadline = DateField(), DateField()
        grid.addWidget(field("Lead", self.n_leads, "leads"), 0, 0)
        grid.addWidget(field("Assignees", self.n_assignees, "assignees"), 0, 1)
        grid.addWidget(field("Due", self.n_due, "due"), 1, 0)
        grid.addWidget(field("Deadline", self.n_deadline, "deadline"), 1, 1)
        g.addLayout(grid)
        self.n_deadline_desc = QLineEdit()
        g.addWidget(field("Deadline description", self.n_deadline_desc, "deadlineDesc"))
        self.n_during = self._during_label(g)
        flags = QHBoxLayout()
        self.n_urgent, self.n_meeting, self.n_plant = QCheckBox("Urgent"), QCheckBox("Meeting"), QCheckBox("Plant event")
        for box, key in ((self.n_urgent, "urgent"), (self.n_meeting, "meeting"), (self.n_plant, "plantEvent")):
            flags.addWidget(box)
            note = QLabel()
            flags.addWidget(InfoButton(key, note))
            g.addWidget(note)
        flags.addStretch()
        g.addLayout(flags)
        self.n_keydates = KeyDatesEditor()  # release 5.31: the new task's key dates
        self.n_keydates.changed.connect(self.refresh)
        g.addWidget(self.n_keydates)
        self.n_more_button = QPushButton("More fields ▸", objectName="moreLink")
        self.n_more_button.clicked.connect(lambda: self._toggle_more(self.n_more, self.n_more_button))
        g.addWidget(self.n_more_button)
        self.n_more = QWidget()
        more = QGridLayout(self.n_more)
        more.setContentsMargins(0, 0, 0, 0)
        self.n_state = QComboBox()
        self.n_state.addItems(list(STATES))
        self.n_start, self.n_reminder, self.n_repeat = DateField(), DateField(), DateField()
        self.n_recurrence = QComboBox()
        self.n_recurrence.addItems(["No recurrence", *RECURRENCES])
        self.n_recurrence.currentIndexChanged.connect(self.refresh)
        self.n_lead_hours, self.n_asg_hours = HoursField(), HoursField()
        self.n_repeat_field = field("Repeat until", self.n_repeat, "repeatUntil")
        for i, (w, label, key) in enumerate(((self.n_state, "State", "state"), (self.n_start, "Start", "start"),
                                             (self.n_reminder, "Reminder", "reminder"), (self.n_recurrence, "Recurrence", "recurrence"))):
            more.addWidget(field(label, w, key), i // 2, i % 2)
        more.addWidget(self.n_repeat_field, 2, 0)
        more.addWidget(field("Lead hours", self.n_lead_hours, "hours"), 3, 0)
        more.addWidget(field("Assignee hours", self.n_asg_hours), 3, 1)
        self.n_refs_grid = QGridLayout()  # the reference fields' boxes (release 5.9), built by _sync_refs
        more.addLayout(self.n_refs_grid, 4, 0, 1, 2)
        self.n_refs: dict[str, QLineEdit] = {}
        self.n_more.hide()
        g.addWidget(self.n_more)
        self.new_heading = QLabel(objectName="heading")
        g.insertWidget(0, self.new_heading)
        if not LOOK.classic:
            g.setContentsMargins(0, 12, 0, 0)
        self.new_heading.setVisible(not LOOK.classic)
        self.lower_layout.addWidget(self.new_group)
        self._watch("new", {"due": self.n_due, "deadline": self.n_deadline, "deadline_desc": self.n_deadline_desc, "urgent": self.n_urgent,
                            "meeting": self.n_meeting, "plant_event": self.n_plant, "state": self.n_state, "start": self.n_start,
                            "reminder": self.n_reminder, "recurrence": self.n_recurrence, "repeat_until": self.n_repeat,
                            "lead_hours": self.n_lead_hours, "assignee_hours": self.n_asg_hours})

    def _build_update_fields(self) -> None:
        self.upd_group = QGroupBox()  # State is beside the task picker (u_state, built with row 2)
        g = QVBoxLayout(self.upd_group)
        g.setSpacing(12)
        self.u_due, self.u_deadline = DateField(), DateField()
        self.u_status = QPlainTextEdit()
        self.u_status.setFixedHeight(56)
        g.addWidget(field("Current status", self.u_status, "status"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.addWidget(field("Due", self.u_due, "due"), 0, 0)
        grid.addWidget(field("Deadline", self.u_deadline, "deadline"), 0, 1)
        g.addLayout(grid)
        self.u_deadline_desc = QLineEdit()
        g.addWidget(field("Deadline description", self.u_deadline_desc, "deadlineDesc"))
        self.u_during = self._during_label(g)
        self.u_keydates = KeyDatesEditor()  # release 5.31: the task's key dates, to change, add to or take off
        self.u_keydates.changed.connect(self.refresh)
        self._u_keydates_were: list[KeyDateRow] = []
        g.addWidget(self.u_keydates)
        self.u_more_button = QPushButton("More fields ▸", objectName="moreLink")
        self.u_more_button.clicked.connect(lambda: self._toggle_more(self.u_more, self.u_more_button))
        g.addWidget(self.u_more_button)
        self.u_more = QWidget()
        more = QGridLayout(self.u_more)
        more.setContentsMargins(0, 0, 0, 0)
        self.u_leads = ChipPicker(self._people_options, "Search names and aliases", "Add “{}” to people")
        self.u_assignees = ChipPicker(self._people_options, "Search names and aliases", "Add “{}” to people")
        self.u_lead_hours, self.u_asg_hours = HoursField(), HoursField()
        self.u_start, self.u_reminder, self.u_repeat = DateField(), DateField(), DateField()
        self.u_recurrence = QComboBox()
        self.u_recurrence.addItems(["No recurrence", *RECURRENCES])
        self.u_urgent, self.u_meeting, self.u_plant = QCheckBox("Urgent"), QCheckBox("Meeting"), QCheckBox("Plant event")
        self.u_repeat_field = field("Repeat until", self.u_repeat, "repeatUntil")
        cells = [(field("Lead", self.u_leads, "leads"), 0, 0), (field("Assignees", self.u_assignees, "assignees"), 0, 1),
                 (field("Lead hours", self.u_lead_hours, "hours"), 1, 0), (field("Assignee hours", self.u_asg_hours), 1, 1),
                 (field("Start", self.u_start, "start"), 2, 0), (field("Reminder", self.u_reminder, "reminder"), 2, 1),
                 (field("Recurrence", self.u_recurrence, "recurrence"), 3, 0), (self.u_repeat_field, 3, 1),
                 (self.u_urgent, 4, 0), (self.u_meeting, 4, 1), (self.u_plant, 5, 0)]
        for w, r, c in cells:
            more.addWidget(w, r, c)
        self.u_refs_grid = QGridLayout()  # the reference fields' boxes (release 5.9), built by _sync_refs
        more.addLayout(self.u_refs_grid, 6, 0, 1, 2)
        self.u_refs: dict[str, QLineEdit] = {}
        self.u_more.hide()
        g.addWidget(self.u_more)
        self.changes_label = QLabel(objectName="hint")
        self.changes_label.setWordWrap(True)
        g.addWidget(self.changes_label)
        self.upd_heading = QLabel(objectName="heading")
        g.insertWidget(0, self.upd_heading)
        if not LOOK.classic:
            g.setContentsMargins(0, 12, 0, 0)
        self.upd_heading.setVisible(not LOOK.classic)
        self.lower_layout.addWidget(self.upd_group)
        self._watch("upd", {"state": self.u_state, "current_status": self.u_status, "due": self.u_due, "deadline": self.u_deadline,
                            "deadline_desc": self.u_deadline_desc, "lead_hours": self.u_lead_hours, "assignee_hours": self.u_asg_hours,
                            "start": self.u_start, "reminder": self.u_reminder, "recurrence": self.u_recurrence, "repeat_until": self.u_repeat,
                            "urgent": self.u_urgent, "meeting": self.u_meeting, "plant_event": self.u_plant})
        for chips in (self.u_leads, self.u_assignees):
            chips.changed.connect(self.refresh)

    @staticmethod
    def _during_label(g: QVBoxLayout) -> QLabel:
        """The line under a group's dates naming the plant event they fall in (release 5.9), filled by refresh."""
        label = QLabel(objectName="hint")
        label.setWordWrap(True)
        label.hide()
        g.addWidget(label)
        return label

    def _sync_refs(self) -> None:
        """One box per reference field named in Settings (release 5.9), under More fields in New task and Update.
        They're rebuilt when Settings changes the names; the More fields links name them."""
        names = list(self.ctx.settings.reference_fields)
        if names != getattr(self, "_ref_names", None):
            self._ref_names = names
            fields = self.__dict__.setdefault("_fields", {})
            for prefix, grid, boxes in (("new", self.n_refs_grid, self.n_refs), ("upd", self.u_refs_grid, self.u_refs)):
                for name in boxes:
                    fields.pop(f"{prefix}.ref:{name}", None)
                    self.touched.discard(f"{prefix}.ref:{name}")
                _drop(grid)
                boxes.clear()
                for i, name in enumerate(names):
                    boxes[name] = QLineEdit()
                    grid.addWidget(field(name, boxes[name], "references" if i == 0 else None), i // 2, i % 2)
                self._watch(prefix, {f"ref:{name}": box for name, box in boxes.items()})
        for button, words in ((self.n_more_button, ["state", "start", "reminder", "recurrence", "hours"]),
                              (self.u_more_button, ["people", "hours", "start", "reminder", "recurrence", "urgent", "meeting", "plant event"])):
            words += names
            button.setText(f"More fields: {', '.join(words[:-1])} and {words[-1]} {button.text()[-1]}")

    def _show_during(self, m: Model) -> None:
        """Under New task's and Update's dates: each that falls in a plant event (release 5.9, M0028)."""
        today = self.ctx.now().date()
        for label, start, due, deadline, task_id, on in (
                (self.n_during, self.n_start, self.n_due, self.n_deadline, None, "new_task" in self.types),
                (self.u_during, self.u_start, self.u_due, self.u_deadline, self.task, "update" in self.types and bool(self.task))):
            text = timeline.during_text(m, [("Start", start.value()), ("Due", due.value()), ("Deadline", deadline.value())],
                                        today, task_id) if on else ""
            label.setText(text)
            label.setVisible(bool(text))

    def _watch(self, prefix: str, widgets: dict[str, QWidget]) -> None:
        """Note when the owner edits a field, so Parse and populate never overwrites it."""
        for key, w in widgets.items():
            name = f"{prefix}.{key}"
            if isinstance(w, DateField):
                w.edited.connect(lambda n=name, x=w.line: self._touch(n, x))
            elif isinstance(w, QLineEdit):
                w.textEdited.connect(lambda _=None, n=name, x=w: self._touch(n, x))
            elif isinstance(w, QPlainTextEdit):
                w.textChanged.connect(lambda n=name, x=w: self._touch(n, x))
            elif isinstance(w, QComboBox):
                w.activated.connect(lambda _=None, n=name, x=w: self._touch(n, x))
            elif isinstance(w, QCheckBox):
                w.clicked.connect(lambda _=None, n=name, x=w: self._touch(n, x))
        self.__dict__.setdefault("_fields", {}).update({f"{prefix}.{k}": w for k, w in widgets.items()})

    def _touch(self, name: str, widget: QWidget) -> None:
        if self._setting:
            return
        self.touched.add(name)
        set_filled(widget, False)
        self.refresh()

    # ================= showing and hiding =================
    def show_capture(self, task: str | None = None, mode: str | None = None, content: str | None = None, mods: bool = False,
                     agenda: list[str] | None = None, agenda_focus: bool = False, from_capture: str | None = None, meeting: bool = False) -> None:
        """Open the window. ``mode`` checks only that capture type ("note", "new_task" or "update"). ``agenda`` picks
        agenda targets under Add to agenda. ``from_capture`` starts Make it a task from an unfiled capture. ``meeting``
        turns on meeting notes (release 5.8), for the picked task's meeting. A pinned capture comes back in full."""
        self._close_pin()
        self._load_summary_types()
        self._names = None  # people and tasks may have changed in the browse tool
        self._sync_refs()  # and the reference fields, in Settings
        if from_capture:
            self.make_task_from(from_capture)
        else:
            if task:
                self.set_task(task)
            if meeting and not self.meeting_on:
                self.toggle_meeting(focus=False)
            if mode:
                self.types, self.note_auto = {mode}, mode == "note"
                if mode == "update":
                    self.prefill()
            if content is not None:
                self._set_plain(self.content, content)
                cursor = self.content.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.content.setTextCursor(cursor)
            if agenda is not None:
                m = self.ctx.model()
                self.today_on = TODAY in agenda  # Today is its own button, beside the capture types
                self.agenda.set_chips([Chip(x, m.target_name(x)) for x in agenda if x != TODAY])
        self.error.hide()
        self.refresh()
        self.show_mods(mods)
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()
        target = (self.mods.text if mods else self.agenda.edit if agenda_focus else self.meet_name if self.meeting_on and not self.meet_name.text()
                  else self.title if "new_task" in self.types and not self.title.text() else self.content)
        target.setFocus()
        self.read_items()

    def open_with_hotkey(self, kind: str) -> None:
        """A capture type's own hotkey (mods log round 1, M0010 and M0020): "note", "new_task", "update" or "agenda", or
        "today" for a quick task on Today (round 2, M0039).
        Note and New task open with that type checked. Update and Add to agenda need a task: with the draft's task,
        Update is checked at once (and for Add to agenda, the cursor goes there); with none, the task picker opens,
        and picking a task does the same."""
        if kind in ("note", "new_task"):
            self.show_capture(mode=kind)
            return
        if kind == "today":  # a quick task on Today (mods log round 2, M0039): New task, Today on, the cursor in Title
            self.show_capture(mode="new_task", agenda=[TODAY, *self.agenda.values()])
            return
        agenda = kind == "agenda"
        if self.task:
            self.show_capture(mode="update", agenda_focus=agenda)
            return
        self.show_capture()
        self._after_pick = kind
        QTimer.singleShot(0, self._open_picker)  # once the window is placed, so the picker opens under the task button

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if self.expanded:  # most of the screen, for meeting notes
            self.setGeometry(area.adjusted(16, 16, -16, -16))
            return
        width = min(WIDTH, area.width() - 32)
        self.resize(width, self._fitting_height(area))
        self.move(area.x() + (area.width() - width) // 2, area.y() + max(16, int(area.height() * 0.05)))

    def _fitting_height(self, area) -> int:
        """The Classic look's window is 600 px or more; the new look's fits its content, up to most of the screen."""
        if LOOK.classic:
            return min(int(area.height() * 0.88), max(600, self.sizeHint().height()))
        inner = self.scroll.widget().sizeHint().height() + self._footer.sizeHint().height() + 4
        return min(int(area.height() * 0.88), max(MIN_HEIGHT, inner))

    def _fit(self) -> None:
        """Grow or shrink to the content as capture types and fields come and go, keeping the window's top where it is."""
        if LOOK.classic or self.expanded or not self.isVisible() or self.pages.currentIndex() != 0:
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        height = self._fitting_height(screen.availableGeometry())
        if abs(height - self.height()) > 8:
            self.resize(self.width(), height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange(self.width())

    def _arrange(self, width: int) -> None:
        """Narrow, what Parse and populate found goes under the content text instead of beside it."""
        narrow = width < NARROW
        self.main_layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        if narrow:
            self.side.setMinimumWidth(0)
            self.side.setMaximumWidth(16_777_215)
        else:
            self.side.setFixedWidth(SIDE_WIDTH)

    def toggle_expand(self) -> None:
        """Expand (F11, mods log round 2, M0046, M0048 phase 1): the content text fills the window, and the files, Copy
        prompt and the New task and Update fields fold away until it's turned off."""
        if self.pages.currentIndex() == 1:
            return
        self._set_expanded(not self.expanded)
        self.content.setFocus()

    def _set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.lower.setVisible(not self.expanded)
        self.content.setMinimumHeight(360 if self.expanded else 140)
        self.expand_button.setIcon(icon("collapse" if self.expanded else "expand"))
        tip(self.expand_button, "Back to the usual size" if self.expanded else "Expand the content text", "F11")
        self.refresh()
        if self.isVisible():
            self._place()

    # ---- meeting notes (release 5.8) ----
    def toggle_meeting(self, focus: bool = True) -> None:
        """Meeting notes (Alt+M): Expand, plus the meeting's name and its agenda. The task picked at the top decides the
        meeting (``save.meeting_case``)."""
        if self.pages.currentIndex() == 1:
            return
        if self.from_capture:
            self._fail("Make it a task can't take meeting notes.", self.content)
            return
        self.meeting_on = not self.meeting_on
        if self.meeting_on:
            self.types, self.note_auto, self.today_on = {"note"}, True, False
            self.agenda.set_chips([])
            self.agenda_ticks: dict[int, bool] = {}
            self._meet_name_typed = False
            self._fill_meet_name()
        if self.expanded != self.meeting_on:
            self._set_expanded(self.meeting_on)
        self.error.hide()
        self._clear_found()
        self.read_items()
        if focus:
            (self.meet_name if self.meeting_on and not self.meet_name.text() else self.content).setFocus()

    def _fill_meet_name(self) -> None:
        """The meeting's name, unless you typed one: a regular meeting's with today's date, a one-off's own, else empty."""
        m = self.ctx.model()
        case = meeting_case(m, self.task)
        if not self._meet_name_typed:
            self.meet_name.setText(meeting_name(m, self.task, self.ctx.now().date()))
        self.meet_name.setReadOnly(case == "oneoff")
        t = m.tasks.get(self.task) if self.task else None
        self.meet_what.setText(f"This time's meeting: a new subtask of {t.title}, In progress until you close it." if case == "regular" else
                               "This meeting, as it is." if case == "oneoff" else
                               f"A new meeting under {t.title}." if t else "A new top-level meeting. Pick a task at the top to put it under one.")

    def _meet_typed(self, _: str) -> None:
        self._meet_name_typed = True
        self.refresh()

    def _agenda_ticked(self, item_id: int, on: bool) -> None:
        self.agenda_ticks[item_id] = on
        self.refresh()

    def _show_agenda(self) -> None:
        """The agenda panel: the meeting's open agenda items, each ticked once it's discussed."""
        self.agenda_panel.setVisible(self.meeting_on)
        if not self.meeting_on:
            return
        m = self.ctx.model()
        meeting = self.task if meeting_case(m, self.task) != "new" else None
        if meeting is None and not LOOK.show_help:
            self.agenda_panel.hide()
            return
        self.agenda_panel.show_agenda(m, meeting, m.open_items_for(meeting) if meeting else [], self._discussed)

    def _discussed(self, a: Any) -> bool:
        if a.id in self.agenda_ticks:
            return self.agenda_ticks[a.id]
        return items.discussed(self.reading, a.subject) if self.reading else False

    def start_from_agenda(self) -> None:
        """Each open agenda item goes into the notes: a note on its own as an "Agenda:" line, then each task as a # heading."""
        m = self.ctx.model()
        if not self.task or meeting_case(m, self.task) == "new":
            return
        have = {line.strip() for line in self.content.plain().split("\n")}
        open_items = m.open_items_for(self.task)
        add = [f"Agenda: {a.note}" for a in open_items if not a.subject] + [f"#{m.task(a.subject).title}" for a in open_items if a.subject]
        for a in open_items:
            if a.subject:
                self.ref_ids["#" + m.task(a.subject).title.lower()] = a.subject  # the heading names that very task
        add = [line for line in add if line not in have]
        if not add:
            self._fail("Every open item is in the notes already.", self.content)
            return
        cursor = self.content.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.content.toPlainText().strip():
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        elif cursor.block().textList() is not None:
            cursor.block().textList().remove(cursor.block())
        cursor.insertText("\n\n".join(add) + "\n")
        self.content.setTextCursor(cursor)
        self.content.setFocus()
        self.read_items()

    # ---- items (release 5.8) ----
    def names(self) -> items.Names:
        if self._names is None:
            self._names = item_names(self.ctx.model(), self.ctx.settings, self.ref_ids)
        return self._names

    def read_items(self) -> None:
        """Read the content text's items again: the colours, the cards, the agenda and Save's line."""
        if not hasattr(self, "item_cards"):
            return
        self._items_timer.stop()
        new = "new_task" in self.types and not self.meeting_on and not self.from_capture
        if self.from_capture:
            self.reading = None
        else:
            self.reading = self._read()
            if self._follow_hash():
                self.reading = self._read()
        self._highlighting = True
        try:
            self.highlighter.set_reading(self.reading)
        finally:
            self._highlighting = False
        if not self.item_cards.editing():
            own = items.self_fields(self.reading, self.names()) if self.reading and new else None
            home = self._home_name()
            self.item_cards.show_items(self.reading, own, lambda it: where_text(it, home, self.names(), self.reading), self.names(),
                                       self._stripe)
        self.item_cards.setVisible(not self.from_capture and (bool(self.item_cards.cards) or LOOK.show_help))
        self._show_agenda()
        self.side.setVisible(not self.item_cards.isHidden() or not self.agenda_panel.isHidden())
        self.refresh()

    def _read(self) -> items.Reading:
        """The content text's items, as Save will read them."""
        m = self.ctx.model()
        new = "new_task" in self.types and not self.meeting_on and not self.from_capture
        own = self.task if self.task and not self.meeting_on and (not new or "update" in self.types) else None
        return items.read(self.content.plain(), self.names(), self.ctx.now().date(), labels=self.ctx.parse_labels(m),
                          events=self.ctx.settings.event_words, home=bool(self.task) or new or self.meeting_on, new_task=new,
                          overrides=self.item_ov, own=own)

    def _follow_hash(self) -> bool:
        """One # task in the content text fills the task picker, until a task is picked by hand; the # going, or a second
        # task, empties it again (the knowledge base's decision 28, release 5.32). True when the task changed."""
        if self.by_hand or self.meeting_on or self.from_capture or not self.reading or (self.task and not self.task_auto):
            return False
        m = self.ctx.model()
        named = [t for t in items.named_tasks(self.reading) if t in m.tasks and not m.tasks[t].discarded]
        want = named[0] if len(named) == 1 else None
        if want == self.task:
            return False
        self.task, self.task_auto = want, bool(want)
        if want and "update" in self.types:
            self.prefill()
        return True

    def split(self) -> list[CaptureDraft] | None:
        """The captures Save makes when several # tasks split this note (the knowledge base's decision 29, release 5.32),
        as save_capture's split_parts makes them, or None when it isn't split."""
        if self.task or self.meeting_on or self.from_capture or self.types != {"note"} or not self.reading:
            return None
        if len(items.named_tasks(self.reading)) < 2:
            return None
        content, formatted = self.content.value()
        key = (content, formatted, tuple((id(e.row), e.row.section) for e in self.files))
        if key == getattr(self, "_split_key", None):  # refresh runs on each key pressed: the parts are read once per change
            return self._split_parts
        draft = CaptureDraft(content=content, formatted=formatted, files=[e.row for e in self.files])
        names, today = self.names(), self.ctx.now().date()

        def read(p: CaptureDraft) -> items.Reading:
            return items.read(p.lines(), names, today, home=bool(p.task), own=p.own_task())

        self._split_key, self._split_parts = key, split_parts(draft, read(draft), read)
        return self._split_parts

    def _cursor_section(self) -> str | None:
        """The # task whose section holds the text cursor: where a file added now goes, if several # tasks split the note
        (decision 30). Read afresh, as if no task were picked, so a # that's also the picked task counts."""
        box = self.pin_window.text if self.pinned and self.pin_window is not None else self.content
        reading = items.read(self.content.plain(), self.names(), self.ctx.now().date())
        return items.section_at(reading, box.textCursor().blockNumber())

    def _show_goes(self, parts: list[CaptureDraft] | None) -> None:
        """Each file's row says which capture of a split note it goes with, and its menu changes it (decision 30)."""
        m = self.ctx.model()
        ids = [p.task for p in parts or [] if p.task]
        rows = [e.row for e in self.files]
        for e in self.files:
            if e.goes is None:
                continue
            e.goes.setVisible(bool(parts))
            if parts:
                task = part_of(e.row, rows, ids)
                e.goes.setText(f"→ {m.tasks[task].title if task in m.tasks else 'Unfiled'}")
                e.goes.setToolTip("Several #tasks split this note into a capture per task. This goes with the one shown; click to change it.")

    def _goes_menu(self, entry: FileEntry) -> None:
        """The captures of a split note a file can go with: each #task's, or the unfiled one."""
        menu = entry.goes.menu()
        menu.clear()
        m = self.ctx.model()
        for task in [p.task for p in self.split() or [] if p.task] + [None]:
            action = menu.addAction(m.tasks[task].title if task in m.tasks else "Unfiled: the lines under no #task")
            action.setCheckable(True)
            action.setChecked(part_of(entry.row, [e.row for e in self.files], [task] if task else []) == task)
            action.triggered.connect(lambda _=False, task=task: self._set_goes(entry, task))

    def _set_goes(self, entry: FileEntry, task: str | None) -> None:
        entry.row.section = task
        self.refresh()

    def _stripe(self, it: items.Item) -> str:
        """An item card's edge: the top-level task's colour of where it goes first (decision 9)."""
        m = self.ctx.model()
        for w in it.where:
            if w.kind == "task" and w.ref:
                return task_colour(m, w.ref)
            if w.kind == "home" and self.task:
                return task_colour(m, self.task)
        return tokens.colour("stroke_strong")

    def _home_name(self) -> str:
        """What the items go under, in words: the meeting, the new task or the picked task."""
        if self.meeting_on:
            return self.meet_name.text().strip() or "the meeting"
        if "new_task" in self.types:
            return f"“{self.title.text().strip()}”" if self.title.text().strip() else "the new task"
        t = self.ctx.model().tasks.get(self.task) if self.task else None
        return t.title if t else ""

    def _item_changed(self, key: str, what: str, value: Any) -> None:
        """A card's change: it stays, even when its line is edited later."""
        self.item_ov.setdefault(key, {})[what] = value
        if what == "off":
            self.read_items()
        else:
            self.refresh()

    def _go_line(self, n: int) -> None:
        block = self.content.document().findBlockByNumber(n)
        if block.isValid():
            cursor = self.content.textCursor()
            cursor.setPosition(block.position())
            self.content.setTextCursor(cursor)
        self.content.setFocus()

    def _ref_box(self) -> tuple[ContentEdit, RefPopup]:
        """The text box the @ and # list follows, and its list: the pinned window's own while pinned, where the full
        window's list can't show (release 5.32)."""
        if self.pinned and self.pin_window is not None:
            return self.pin_window.text, self.pin_window.ref_popup
        return self.content, self.ref_popup

    def _ref_list(self) -> None:
        """The @ or # list, while a name is being typed after one."""
        if not hasattr(self, "ref_popup"):
            return
        box, popup = self._ref_box()
        cursor = box.textCursor()
        t = None
        if not cursor.hasSelection() and not self.from_capture and box.hasFocus():
            t = items.typing(cursor.block().text()[:cursor.positionInBlock()])
        options = items.options(t, self.names()) if t else []
        if not options:
            popup.hide()
            self._typing = None
            return
        if t.sigil == "#":
            m = self.ctx.model()
            options = [replace(o, sub=path_text(m, o.ref) or "Top-level task") if o.ref in m.tasks else o for o in options]
        self._typing = t
        if popup is self.ref_popup:
            at = self.content.viewport().mapTo(self, self.content.cursorRect(cursor).bottomLeft()) + QPoint(0, 3)
            at.setX(max(4, min(at.x(), self.width() - self.ref_popup.width() - 4)))
            self.ref_popup.show_options(options, at)
            return
        # The pinned window's list is a window of its own, placed under the cursor, or above it at the screen's foot.
        rect = box.cursorRect(cursor)
        area = box.screen().availableGeometry()
        at = box.viewport().mapToGlobal(rect.bottomLeft()) + QPoint(0, 3)
        popup.show_options(options, QPoint(max(area.left(), min(at.x(), area.right() - popup.width())), at.y()))
        if popup.geometry().bottom() > area.bottom():
            popup.move(popup.x(), box.viewport().mapToGlobal(rect.topLeft()).y() - popup.height() - 3)

    def _pick_ref(self, option: items.Option) -> None:
        """Put the picked name in, with a space after it; a picked one's ID is kept, ahead of names alike."""
        t = self._typing
        box, popup = self._ref_box()
        popup.hide()
        if not t:
            return
        cursor = box.textCursor()
        cursor.setPosition(cursor.position() - (cursor.positionInBlock() - t.start), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(t.sigil + option.value + " ")
        box.setTextCursor(cursor)
        if option.ref:
            self.ref_ids[("#" if t.sigil == "#" else "@") + option.value.lower()] = option.ref
            self._names = None
        self._typing = None
        self.read_items()

    # ---- the draft keeps itself (release 5.8) ----
    def _draft_path(self) -> Path:
        return self.ctx.data_root / DRAFT_FILE

    def _draft_data(self) -> dict:
        """The draft as capture-draft.json keeps it."""
        content, formatted = self.content.value()
        return {"saved": self.ctx.now().isoformat(timespec="seconds"), "task": self.task, "task_auto": self.task_auto, "by_hand": self.by_hand,
                "types": sorted(self.types), "title": self.title.text(),
                "content": content, "formatted": formatted, "meeting": self.meeting_on,
                "meeting_name": self.meet_name.text() if self._meet_name_typed else "", "refs": self.ref_ids}

    def keep_draft(self) -> None:
        """Every 30 seconds, when something changed: the draft goes to System\\capture-draft.json in the data root."""
        if not self.draft_dirty:
            return
        data = self._draft_data()
        if not data["content"].strip():
            return
        try:
            self.ctx.fs.write_text(self._draft_path(), json.dumps(data, ensure_ascii=False, indent=1))
        except OSError as e:
            self.draft_label.setText(f"The draft couldn't be kept ({type(e).__name__}).")
            return
        self.draft_dirty = False
        self.draft_label.setText(f"Draft kept at {self.ctx.now():%H:%M:%S}.")

    def restore_draft(self) -> None:
        """After a crash or a restart: the window opens with the draft it kept."""
        try:
            data = json.loads(self._draft_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or not str(data.get("content") or "").strip():
            return
        self._apply_draft(data)
        self.draft_label.setText(f"The draft from {str(data.get('saved', ''))[11:16]} came back.")
        self.read_items()

    def _apply_draft(self, data: dict) -> None:
        """Put a kept draft back in the window."""
        m = self.ctx.model()
        self._setting = True
        task = data.get("task")
        self.task = task if task in m.tasks else None
        self.task_auto = bool(data.get("task_auto")) and self.task is not None
        self.by_hand = bool(data.get("by_hand"))
        self.types = {k for k in data.get("types") or [] if k in self.type_boxes} or {"note"}
        self.note_auto = self.types == {"note"}
        self.title.setText(str(data.get("title") or ""))
        self.content.set_value(str(data["content"]), bool(data.get("formatted")))
        self.ref_ids = {str(k): str(v) for k, v in (data.get("refs") or {}).items()}
        self._setting = False
        if data.get("meeting"):
            self.toggle_meeting(focus=False)
            if data.get("meeting_name"):
                self.meet_name.setText(str(data["meeting_name"]))
                self._meet_name_typed = True

    def forget_draft(self) -> None:
        """Once the capture is saved or cleared, the kept draft is emptied."""
        self.draft_dirty = False
        if self._draft_path().exists():
            try:
                self.ctx.fs.write_text(self._draft_path(), "{}")
            except OSError:
                pass
        self.draft_label.setText(DRAFT_NOTE if LOOK.show_help else "")

    def clear(self) -> None:
        """Clear: a fresh capture, and no kept draft. In the new look, Undo in the footer brings it back for ten seconds."""
        data = self._draft_data()
        self.reset_draft()
        self.forget_draft()
        if not LOOK.classic and (data["content"].strip() or data["title"].strip()):
            self._cleared = data
            self.draft_label.setText("Cleared.")
            self.undo_clear.show()
            self._undo_timer.start()

    def _undo_clear(self) -> None:
        data, self._cleared = self._cleared, None
        self.undo_clear.hide()
        self._undo_timer.stop()
        if data:
            self._apply_draft(data)
            self.draft_dirty = True
            self.draft_label.setText("Brought back.")
            self.read_items()
            self.content.setFocus()

    def show_keys(self) -> None:
        """F1: every key, in one list (mods log round 2, M0036)."""
        KeyMapDialog(self, self.ctx.settings.hotkey).exec()

    # ---- Alt and the topic's letter (mods log round 2, M0036) ----
    def _alt_type(self, key: str) -> None:
        if self.pages.currentIndex() == 0 and not self.from_capture and not self.meeting_on:  # meeting notes are a note
            self.set_type(key, key not in self.types)

    def _alt_agenda(self) -> None:
        if self.pages.currentIndex() != 0:
            return
        if self._agenda_shown():
            self.agenda.edit.setFocus()
        else:
            self._fail("With a task picked, check New task or Update to put something on an agenda.", self.content)

    def _alt_today(self) -> None:
        if self.pages.currentIndex() == 0:
            self.set_today(not self.today_on)

    def set_today(self, on: bool) -> None:
        """Today, beside the capture types (mods log round 2, M0037): on or off in one click."""
        if on and not self._agenda_shown():
            self.today_button.setChecked(False)
            self._fail("With a task picked, check New task or Update to put something on Today.", self.content)
            return
        self.today_on = on
        self.error.hide()
        self.refresh()

    def _targets(self) -> list[str]:
        """The agenda targets Save puts the capture on: Today first, then the picker's."""
        if not self._agenda_shown():
            return []
        return [TODAY] * self.today_on + [x for x in self.agenda.values() if x != TODAY]

    def _quick(self) -> bool:
        """A new task with no task picked that goes on Today is a quick task, under Quick tasks (mods log round 2, M0039)."""
        return "new_task" in self.types and not self.task and not self.from_capture and TODAY in self._targets()

    def hide_capture(self) -> None:
        self.hide()

    # ---- pinned (mods log round 3, M0053, M0054) ----
    def toggle_pin(self) -> None:
        """F12 and the Pin hotkey: pin the capture, or bring the full window back."""
        if self.pinned:
            self.unpin()
        else:
            self.pin()

    def pin(self) -> None:
        """The capture as a small window at the bottom right, on top of the others, to drop files, emails and links on."""
        if self.pages.currentIndex() != 0:
            self.show_mods(False)
        if self.pin_window is None:
            from docrepo.ui.pin_window import PinWindow  # here, as it builds on this module

            self.pin_window = PinWindow(self)
        self._load_summary_types()
        self.pin_window.show_message("")
        self.pin_window.sync()
        self.pin_window.path.clear()
        self.pin_window.place()
        self.pinned = True
        self.hide()
        self.pin_window.show()
        self.pin_window.raise_()
        self.pin_window.activateWindow()
        cursor = self.pin_window.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)  # ready to add a line
        self.pin_window.text.setTextCursor(cursor)
        self.pin_window.text.setFocus()

    def unpin(self) -> None:
        """Back to the full window, on the same capture (the main hotkey, F12, or the pinned window's open button)."""
        self.show_capture()

    def _close_pin(self) -> None:
        self.pinned = False
        if self.pin_window is not None:
            self.pin_window.hide()

    def hide_pinned(self) -> None:
        """Esc on the pinned window: it hides, and the capture stays as a draft; the main hotkey opens it in full."""
        self._close_pin()
        self.keep_draft()

    def show_mods(self, on: bool) -> None:
        self.pages.setCurrentIndex(1 if on else 0)
        if on:
            self.mods.refresh()
            self.mods.text.setFocus()
        else:
            self.content.setFocus()

    def closeEvent(self, event) -> None:  # noqa: N802 - the X hides it; the draft is kept
        event.ignore()
        self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self.pages.currentIndex() == 1 and self.mods.editing:
                self.mods.cancel_edit()  # Esc first stops an edit, then goes back to the capture
            elif self.pages.currentIndex() == 1:
                self.show_mods(False)
            else:
                self.hide()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - files can be dropped anywhere on the window
        if kind := note_drag("enter", event.mimeData(), links=True):
            _accept_copy(event)
            self._drag_entered(kind)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData(), links=True)[0]:
            _accept_copy(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        note_drag("drop", event.mimeData(), links=True)
        kind, paths = read_drop(event.mimeData(), links=True)
        if kind:
            _accept_copy(event)
            self.dropped(kind, paths)

    def dropped(self, kind: str, paths: list[str]) -> None:
        """What a drop on the window, the content text or the pinned window brought: files, an Outlook email, web links,
        or files DocRepo can't read."""
        if self.pin_window is not None:
            self.pin_window.show_message("")
        if kind == "files":
            self.add_paths(paths)
        elif kind == "links":
            for url in paths:
                self.add_link_url(url)
        elif kind == "outlook":
            # Outlook is asked only after its drag is over: asking during the drop can hang it (release 5.33).
            QTimer.singleShot(0, self.add_outlook)
        elif kind == "virtual":
            self._fail("These files come from a program that doesn't hand DocRepo a file it can read, such as a zip folder. "
                       "Save or extract them to a folder first, then drop them from there.", self.content)
        if self.pinned:
            self.pin_window.sync()

    def _drag_entered(self, kind: str) -> None:
        """A drag of an email from Outlook, or of a file only a program holds, puts up the cover with DocRepo's own drop
        target, on the pinned window while pinned (release 5.33)."""
        if kind in ("outlook", "virtual"):
            (self.pin_window.drop_overlay if self.pinned and self.pin_window is not None else self.drop_overlay).cover(email=kind == "outlook")

    def take_drop(self, found: DropRead) -> None:
        """What DocRepo's own drop target took, after the drop (release 5.33): each email as its .msg, read without
        Outlook, and each other file (an attachment dragged from an email, a file in a zip folder) as its bytes, saved
        in the capture's attachments folder."""
        if self.pin_window is not None:
            self.pin_window.show_message("")
        emails, problems = [], list(found.problems)
        for item in found.items:
            if item.email:
                try:
                    emails.append(msg.read(item.data))
                except msg.MsgError as e:
                    problems.append(f"{item.name}: {e}")
            else:
                a = Attachment(item.name, size=len(item.data), data=item.data)
                self._add_file(FileRow(item.name, part=Part("attachment", item.name, a, size=len(item.data))), "dropped")
        if emails and found.outlook and self.ctx.settings.outlook_categories:
            try:  # where each is in Outlook, to mark it with its task when it's saved
                outlook.match_places(emails, outlook.selected_places())
            except outlook.OutlookError:
                pass  # Save says which couldn't be marked
        for email in emails:
            self._add_email(email)
        if problems:
            self._fail("Not all of the drop could be read: " + "; ".join(problems) + ". Settings → Troubleshooting report has the details.",
                       self.content)
        if self.pinned:
            self.pin_window.sync()

    # ================= the draft =================
    def reset_draft(self) -> None:
        """Clear the window for a new capture."""
        self._setting = True
        self.task: str | None = None
        # The task came from the content text's one # task, and follows it; by_hand: a task (or none) was picked by hand,
        # so the text no longer picks it (the knowledge base's decision 28, release 5.32).
        self.task_auto = False
        self.by_hand = False
        self.from_capture: str | None = None
        self.today_on = False
        self.types: set[str] = {"note"}
        self.note_auto = True
        self.touched: set[str] = set()
        self.files: list[FileEntry] = []
        for i in reversed(range(self.files_box.count())):
            w = self.files_box.itemAt(i).widget()
            if w:
                w.deleteLater()
        for w in (self.title, self.n_deadline_desc, self.u_deadline_desc, self.n_lead_hours, self.n_asg_hours, self.u_lead_hours, self.u_asg_hours):
            w.clear()
        for w in (self.content, self.summary, self.u_status):
            w.clear()
        for d in (self.n_due, self.n_deadline, self.n_reminder, self.n_repeat, self.u_due, self.u_deadline, self.u_start, self.u_reminder, self.u_repeat):
            d.set_value(None)
        self.n_start.set_value(self.ctx.now().date().isoformat())
        for c in (self.n_labels, self.n_leads, self.n_assignees, self.u_leads, self.u_assignees, self.agenda):
            c.set_chips([])
        for box in (self.n_urgent, self.n_meeting, self.n_plant, self.u_urgent, self.u_meeting, self.u_plant):
            box.setChecked(False)
        self._sync_refs()
        for box in (*self.n_refs.values(), *self.u_refs.values()):
            box.clear()
        self.n_keydates.set_rows([])
        self.u_keydates.set_rows([])
        self._u_keydates_were = []
        self.n_inherit.setChecked(True)
        self.n_state.setCurrentText("Not started")
        self.n_recurrence.setCurrentIndex(0)
        self.same_all.setChecked(False)
        for w in self.__dict__.get("_fields", {}).values():
            set_filled(w.line if isinstance(w, DateField) else w, False)
        # Items and meeting notes (release 5.8)
        self.ref_ids: dict[str, str] = {}  # names picked from the @ and # lists, with their IDs
        self.item_ov: dict[str, dict[str, Any]] = {}  # the cards' changes, by item key
        self.agenda_ticks: dict[int, bool] = {}  # agenda items ticked or unticked by hand
        self._names = None
        self._meet_name_typed = False
        self.meet_name.clear()
        if self.meeting_on:
            self.meeting_on = False
            if self.expanded:
                self._set_expanded(False)
        self._setting = False
        self._show_summary(False)
        self._clear_found()
        self.error.hide()
        self.read_items()

    def make_task_from(self, capture_id: str) -> None:
        """Make it a task: a new task from an unfiled capture. Saving creates it and files the capture to it."""
        from docrepo.captures import plain, read_content
        from docrepo.text import first_sentence, plain_text

        m = self.ctx.model()
        c = m.captures[capture_id]
        content = read_content(self.ctx.data_root, c) or ""
        self.reset_draft()
        self.from_capture = capture_id
        self.types, self.note_auto = {"new_task"}, False
        self._setting = True
        self.content.set_value(content, c.formatted)
        self._setting = False
        sentence = first_sentence(plain_text(plain(c, content) or ""), 400)
        title = parse_capture(sentence, "new_task", self.ctx.now().date(), self.ctx.parse_people(m), [], []).title if sentence else ""
        self.title.setText(title or c.title)
        self.refresh()

    def set_task(self, task_id: str | None, auto: bool = False) -> None:
        """Pick the capture's task: by hand, or (``auto``) from the content text's one # task, which it then follows until
        a task, or none, is picked by hand (the knowledge base's decision 28, release 5.32)."""
        was = self.task_auto
        self.task_auto = auto and bool(task_id)
        self.by_hand = self.by_hand or not auto
        if task_id == self.task:
            if was != self.task_auto:
                self.refresh()
            return
        self.task = task_id
        if not task_id and "update" in self.types and not auto:  # the # going doesn't uncheck Update: it may come back
            self._drop_type("update")
        if "update" in self.types:
            self.prefill()
        if self.meeting_on:  # another task picked: another meeting
            self.agenda_ticks = {}
            self._fill_meet_name()
        self._clear_found()
        self.error.hide()
        self.read_items()

    def set_type(self, key: str, checked: bool) -> None:
        """Check or uncheck a capture type. Checking New task or Update unchecks Note, unless Note was checked by hand."""
        if key == "update" and checked and not self.task:
            self.type_boxes["update"].setChecked(False)
            self._fail("Pick a task to update first.", self.task_button)
            return
        if checked:
            self.types.add(key)
            if key != "note" and self.note_auto:
                self.types.discard("note")
            if key == "note":
                self.note_auto = False
        else:
            self._drop_type(key)
        if key == "update" and checked:
            self.prefill()
        self.error.hide()
        self._clear_found()
        self.read_items()  # with New task, the first line is the new task itself
        if key == "new_task" and checked:
            self.title.setFocus()

    def _drop_type(self, key: str) -> None:
        self.types.discard(key)
        if key == "note":
            self.note_auto = False
        if not self.types:
            self.types, self.note_auto = {"note"}, True

    def prefill(self) -> None:
        """Fill the Update fields with the picked task's current values."""
        if not self.task:
            return
        t = self.ctx.model().task(self.task)
        m = self.ctx.model()
        self._setting = True
        self.u_state.setCurrentText(t.state)
        self.u_status.setPlainText(t.current_status)
        self.u_due.set_value(t.due)
        self.u_deadline.set_value(t.deadline)
        self.u_deadline_desc.setText(t.deadline_desc or "")
        self.u_leads.set_chips([Chip(p, m.person_name(p)) for p in t.leads])
        self.u_assignees.set_chips([Chip(p, m.person_name(p)) for p in t.assignees])
        self.u_lead_hours.set_value(t.lead_hours)
        self.u_asg_hours.set_value(t.assignee_hours)
        self.u_start.set_value(start_of(t).isoformat())
        self.u_reminder.set_value(t.reminder)
        self.u_recurrence.setCurrentText(t.recurrence or "No recurrence")
        self.u_repeat.set_value(t.repeat_until)
        self.u_urgent.setChecked(t.urgent)
        self.u_meeting.setChecked(t.meeting)
        self.u_plant.setChecked(t.plant_event)
        for name, box in self.u_refs.items():
            box.setText(t.references.get(name, ""))
        self._u_keydates_were = [KeyDateRow(kd.start, kd.end, kd.description, kd.plant, kd.deadline, bool(kd.done), kd.id)
                                 for kd in m.key_dates_of(t.id)]
        self.u_keydates.set_rows(self._u_keydates_were)
        for key, w in self.__dict__.get("_fields", {}).items():
            if key.startswith("upd."):
                self.touched.discard(key)
                set_filled(w.line if isinstance(w, DateField) else w, False)
        self._setting = False

    # ================= what Save will do =================
    def refresh(self) -> None:
        """Show the parts that apply to the checked capture types, and say what Save will do."""
        if not hasattr(self, "upd_group"):
            return
        m = self.ctx.model()
        t = m.tasks.get(self.task) if self.task else None
        new, upd = "new_task" in self.types, "update" in self.types
        self._setting = True
        for key, box in self.type_boxes.items():
            box.setChecked(key in self.types)
            box.setEnabled(not self.from_capture)
        self._setting = False
        self._show_during(m)
        parts = self.split()
        self.task_button.setText(full_path(m, t.id) + ("  (from #)" if self.task_auto else "") if t else
                                 ("None: a quick task, under Quick tasks" if self._quick() else "None: a new top-level task" if new
                                  else "None: a capture per #task" if parts else "None: keep it unfiled"))
        self._show_goes(parts)
        self.title_field.setVisible(new)
        self.content_field.property("label").setText("Content text" + ("  <span style='color:#87919c'>becomes the new task's description</span>" if new else ""))
        self.parse_button.setEnabled(new or upd or bool(t))
        self.new_group.setVisible(new)
        if LOOK.classic:
            self.new_group.setTitle(f"NEW TASK UNDER {t.title.upper()}" if t else "NEW TOP-LEVEL TASK")
        else:
            self.new_heading.setText(f"New task under {t.title}" if t else "New top-level task")
        inherited = [name for name, _ in m.labels_of(t.id)] if t else []
        self.n_inherit_row.setVisible(bool(t))
        self.n_inherited.setText(("Inherited: " + ", ".join(inherited) if inherited else "The parent has none.") if self.n_inherit.isChecked() else "")
        self.n_repeat_field.setVisible(self.n_recurrence.currentIndex() > 0)
        self.upd_group.setVisible(upd and bool(t))
        if t:
            if LOOK.classic:
                self.upd_group.setTitle(f"UPDATE {t.title.upper()}")
            else:
                self.upd_heading.setText(f"Update {t.title}")
        self.u_repeat_field.setVisible(self.u_recurrence.currentIndex() > 0)
        shown = self._agenda_shown()
        what = "the new task" if new else "the picked task" if upd and t else "this note"
        self.today_button.setEnabled(shown)
        self.today_button.setChecked(self.today_on and shown)
        self.today_button.setToolTip(f"Put {what} on Today (Alt+D)" if shown else "With a task picked, check New task or Update to put something on Today")
        self.agenda.setEnabled(shown)
        self.agenda.setToolTip(f"Put {what} on a meeting's, a task's or a person's agenda (Alt+A)" if shown else
                               "With a task picked, check New task or Update to put something on an agenda")
        if self.expanded:
            folded = [f"{len(self.files)} file{'s' if len(self.files) != 1 else ''}"] * bool(self.files) + ["Copy prompt and the summary"]
            folded += ["the New task fields"] * new + ["the Update fields"] * (upd and bool(t))
            self.folded.setText(f"While expanded, {and_list(folded)} {'are' if len(folded) > 1 else 'is'} folded away. Drop files on the "
                                "window as usual. F11 brings them back.")
        self.folded.setVisible(self.expanded)
        self.files_label.setVisible(bool(self.files))
        self.same_all.setVisible(sum(e.desc is not None for e in self.files) > 1)
        self._apply_same_all()  # the placeholders name the task
        where ="the new task's Files folder" if new else f"Tasks\\{t.id}\\Files\\" if t else "the task's Files folder once the capture is filed"
        has_files = any(e.copy is not None and not e.copy.isHidden() for e in self.files)  # rows that offer Save a copy
        self.copy_hint.setText(f"Save a copy puts the file in {where}, named with today's date. Extract information marks it for the later processing stage."
                               if has_files else "")
        self.copy_hint.setVisible(has_files)
        changes = self.update_changes(t) if upd and t else {}
        parts = [(k.replace('_', ' '), v) for k, v in changes.items() if k != "references"] + list(changes.get("references", {}).items())
        if upd and t and self.update_key_dates() is not None:  # release 5.31
            parts.append(("key dates", f"{len(self.u_keydates.rows())} in all"))
        self.changes_label.setText(
            "Status log: " + "; ".join(f"{k} → {self._short(v)}" for k, v in parts)
            if parts else "Prefilled with the task's current values. Each change goes into its status log.")
        self.does.setText(self._does(m, len(parts)))
        if self.from_capture:
            self.does.setText(f"Save creates {'a subtask under <b>' + esc(t.title) + '</b>' if t else 'a top-level task'} from "
                              f"{self.from_capture}, with this content text as its description, and files {self.from_capture} to it. "
                              "The capture's own text stays as it was.")
        # Meeting notes (release 5.8): the meeting's name takes the capture types' place.
        self.types_box.setVisible(not self.meeting_on)
        self.meeting_title.setVisible(self.meeting_on)
        self.meeting_row.setVisible(self.meeting_on)
        self.state_row.setVisible(upd and bool(t) and not self.meeting_on)
        for w in (self.today_button, self.agenda, self.agenda_divider):
            w.setVisible(not self.meeting_on)
        self.content.setPlaceholderText(MEETING_PLACEHOLDER if self.meeting_on else CONTENT_PLACEHOLDER)
        self.meet_what.setVisible(self.meeting_on)
        self.meeting_button.setChecked(self.meeting_on)
        self.meeting_button.setEnabled(not self.from_capture)
        self.content_field.property("label").setText("Meeting notes" if self.meeting_on else self.content_field.property("label").text())
        self.content_hint.setText(
            f"The content text of {self.from_capture}. It stays in that capture." if self.from_capture else
            "Each line with an operator becomes an item when you save: @Tom a task for Tom, #Rigging plan a note on it, **Closed. an update, "
            "**Decision. a decision. Type @ or # for a list." if self.meeting_on else
            "Type or paste. Drop files or Outlook emails anywhere on this window. Start with “Closed.” or another state for a quick update. "
            "@, # and ** make items (Items, on the right).")
        self._fit_timer.start()
        if self.pinned:
            self.pin_window.sync()

    @staticmethod
    def _short(value: Any) -> str:
        text = ", ".join(w.name if isinstance(w, Who) else str(w) for w in value) if isinstance(value, list) else "none" if value in (None, "") else str(value)
        return text if len(text) <= 40 else text[:40] + "…"

    def _agenda_shown(self) -> bool:
        return "new_task" in self.types or ("update" in self.types and bool(self.task)) or not self.task

    def _does(self, m: Model, n_changes: int) -> str:
        t = m.tasks.get(self.task) if self.task else None
        name = f"<b>{esc(t.title)}</b>" if t else ""
        # The items each line with an operator makes (release 5.8).
        its = [it for it in self.reading.items if it.on] if self.reading and not self.from_capture else []
        counts = [f"{n} {label.lower()}{'s' if n > 1 else ''}" for k, label in items.KIND_NAMES.items() if (n := sum(it.kind == k for it in its))]
        items_text = f" From its items it makes {and_list(counts)}." if counts else ""
        if self.meeting_on:
            case, typed = meeting_case(m, self.task), self.meet_name.text().strip()
            meeting = f"<b>{esc(typed)}</b>" if typed else "the meeting (name it first)"
            done = sum(self._discussed(a) for a in m.open_items_for(self.task)) if case != "new" else 0
            return (f"Save keeps these notes on {name}." if case == "oneoff" else
                    f"Save makes {meeting}, a meeting {'under ' + name if t else 'at the top level'}, In progress until you close it, and keeps "
                    "these notes on it.") + items_text + (f" {done} agenda item{'s close' if done > 1 else ' closes'} as Discussed." if done else "")
        split = self.split()
        if split:
            said = []
            for p in split:
                held = held_text(p.files)
                if p.task:
                    said.append(f"a note on <b>{esc(m.task(p.task).title)}</b>" + (f" with {held}" if held else ""))
                elif p.words().strip():
                    said.append("an unfiled note with the lines under no #task" + (f" and {held}" if held else ""))
                else:
                    said.append(f"an unfiled note with {held}")
            agenda_text = " Each goes on the agenda you picked." if self._targets() else ""
            # A note on a part's own task is its text, not an item: the parts' items are counted, not the whole text's.
            names, today = self.names(), self.ctx.now().date()
            its = [it for p in split for it in items.read(p.lines(), names, today, home=bool(p.task), own=p.own_task()).items if it.on]
            counts = [f"{n} {label.lower()}{'s' if n > 1 else ''}" for k, label in items.KIND_NAMES.items() if (n := sum(it.kind == k for it in its))]
            return (f"Save makes {len(split)} capture{'s' if len(split) != 1 else ''}, one per #task: {and_list(said)}.{agenda_text}"
                    + (f" From their items it makes {and_list(counts)}." if counts else ""))
        text = bool(self.content.toPlainText().strip())
        new, upd, note = ("new_task" in self.types, "update" in self.types, "note" in self.types)
        parts = []
        if new:
            what = ("a subtask under " + name if t else "a quick task, under <b>Quick tasks</b> until you put it under its real task" if self._quick()
                    else "a top-level task")
            parts.append(f"creates {what}" + (", with this content text as its description" if text else ""))
        if upd and t:
            parts.append(f"updates {name}: " + (f"{n_changes} changed field{'s go' if n_changes > 1 else ' goes'} into its status log" if n_changes
                                                   else "this goes into its status log" if text else "nothing has changed yet"))
        targets = self._targets()
        if note and not new:
            parts.append(f"adds this to the raw text log of {name}" if t else "" if targets else "keeps this as an unfiled capture, to file later")
        if note and new:
            parts.append("keeps this as reference information on the new task")
        if targets:
            subject = "the new task" if new else name if upd and t else "this note"
            others = [f"<b>{esc(m.target_name(x))}</b>" for x in targets if x != TODAY]
            where = ["<b>Today</b>"] * (TODAY in targets) + [f"the agenda of {and_list(others)}"] * bool(others)
            parts.append(f"puts {subject} on {' and '.join(where)}")
        parts = [p for p in parts if p]
        if not parts:
            return "Pick a task, or uncheck Update."
        return "Save " + parts[0] + "." + (" It also " + and_list(parts[1:]) + "." if len(parts) > 1 else "") + items_text

    # ================= the task picker and other pickers =================
    def _open_picker(self, anchor: QWidget | None = None) -> None:
        """The task picker, under the task button, or under ``anchor`` (the pinned window's, mods log round 3, M0062)."""
        anchor = anchor or self.task_button
        none = ("None", "A new top-level task" if "new_task" in self.types else "Keep it unfiled")
        self.picker = TaskPicker(self, self.ctx.model, none)
        self.picker.picked.connect(self._picked)
        self.picker.setMinimumWidth(max(300, anchor.width()))
        self.picker.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _picked(self, task_id: str | None) -> None:
        self.set_task(task_id)  # by hand: the text's # no longer picks it
        after, self._after_pick = self._after_pick, None
        if after and task_id:  # the Update or Add to agenda hotkey opened the picker: only Update is checked, as with a task already picked
            self.show_capture(mode="update", agenda_focus=after == "agenda")
            return
        if self.pinned:  # picked on the pinned window: the cursor goes back to its box
            self.pin_window.text.setFocus()
            return
        (self.title if "new_task" in self.types else self.content).setFocus()

    def _label_options(self, text: str, picked: list[str]) -> list[Option]:
        return label_options(self.ctx.model(), text, picked)

    def _people_options(self, text: str, picked: list[str]) -> list[Option]:
        return people_options(self.ctx.model(), self.ctx.settings.me, text, picked)

    def _agenda_options(self, text: str, picked: list[str]) -> list[Option]:
        """Open meetings and people; typing also finds any open task. The task going on the agenda is left out. Today has
        its own button beside the capture types (mods log round 2, M0037)."""
        m = self.ctx.model()
        q = text.strip().lower()
        subject = None if "new_task" in self.types else self.task
        today = self.ctx.now().date()
        options = [Option(t.id, t.title, f"Meeting, next {m.meeting_when(t.id, today)}" if t.recurrence else "Meeting", ) for t in m.open_meetings()]
        options += [Option(p.id, p.name, " · ".join(["Person", *p.aliases])) for p in m.active_people() if p.id != self.ctx.settings.me]
        if q:
            options += [Option(t.id, t.title, path_text(m, t.id) or "Top-level task") for t in m.tasks.values() if is_open(t) and not t.meeting]

        def names(o: Option) -> list[str]:
            return [o.label, *(m.people[o.value].aliases if is_person(o.value) else [o.value])]

        return [o for o in options if o.value != subject and o.value not in picked and (not q or any(q in n.lower() for n in names(o)))][:9]

    # ================= content text and files =================
    def _set_plain(self, edit: QPlainTextEdit, text: str) -> None:
        self._setting = True
        edit.setPlainText(text)
        self._setting = False

    def _content_changed(self) -> None:
        if self._highlighting:  # the operators' colours, not a change to the text
            return
        self._path_timer.start()
        self._items_timer.start()
        if not self._setting:
            self.draft_dirty = True
            self.refresh()

    def _sync_paths(self) -> None:
        """A line of the content text that's an existing file's path, or a link, adds a row for it; deleting the line
        removes it. A path may have the quotes File Explorer's Copy as path puts round it (release 5.26.1). A path line
        that isn't a file DocRepo can find says so once the cursor leaves it, rather than staying text without a word."""
        lines = [line.strip() for line in self.content.toPlainText().split("\n") if PATH_LINE.match(typed_path(line)) or is_link(line)]
        keep = {line.lower() for line in lines}
        for entry in [e for e in self.files if e.src == "pasted" and (e.line or "").lower() not in keep]:
            self._remove_file(entry, from_content=False)
        self._missing_paths = {line: told for line, told in self._missing_paths.items() if line in lines}
        for line in lines:
            if not any(line.lower() == (e.line or "").lower() or typed_path(line).lower() == (e.row.path or "").lower() for e in self.files):
                if is_link(line):
                    # No focus move: a link typed by hand matches before it's finished, and typing must go on.
                    self._add_file(FileRow(link_name(line), line), "pasted", line, focus=False)
                    continue
                if line in self._missing_paths:
                    continue  # looked for already; editing the line looks again
                path = existing_file(typed_path(line))
                if path:
                    self._add_file(FileRow(Path(path).name, to_unc(path)), "pasted", line)
                else:
                    self._missing_paths[line] = False
        self._tell_missing_paths()

    def _tell_missing_paths(self) -> None:
        """Say which path lines aren't files DocRepo can find, each once, and not while the cursor is still on it: a path
        being typed matches the pattern before it's finished."""
        if not self._missing_paths:
            return
        here = self.content.textCursor().block().text().strip()
        untold = [line for line, told in self._missing_paths.items() if not told and line != here]
        if not untold:
            return
        for line in untold:
            self._missing_paths[line] = True
        names = ", ".join(Path(typed_path(line)).name for line in untold)
        verb = "isn't a file" if len(untold) == 1 else "aren't files"
        self._fail(f"{names} {verb} DocRepo can find, so it's kept as text and not attached. Check the path (the drive "
                   "and each folder's name), or drop the file on the window.")

    def add_paths(self, paths: list[str]) -> None:
        """Files dropped or picked. A .msg file is read through Outlook as an email. A folder, or something that
        isn't there, is left out, and the window says so."""
        left_out = []
        for p in paths:
            path = Path(p)
            if path.suffix.lower() == ".msg":
                self._read_emails(lambda path=path: [read_msg_file(path)], "reading a dropped .msg file")
                continue
            try:
                is_file, is_dir = path.is_file(), path.is_dir()
            except OSError:
                is_file = is_dir = False
            if not is_file:
                left_out.append(f"{path.name or p} is a folder: add the files in it instead." if is_dir else f"{path.name or p} can't be found.")
            elif not any((e.row.path or "").lower() == to_unc(str(path)).lower() for e in self.files):
                self._add_file(FileRow(path.name, to_unc(str(path))), "dropped")
        if left_out:
            self._fail(" ".join(left_out), self.content)

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to the capture")
        self.add_paths(paths)

    def add_link(self) -> None:
        """Add link…: asks for the address, starting with the clipboard's when it holds one."""
        clip = QGuiApplication.clipboard().text().strip()
        url, ok = QInputDialog.getText(self, "Add link", "A web or SharePoint link. DocRepo keeps the address, and never opens or fetches it.",
                                       text=clip if is_link(clip) else "")
        if ok and url.strip():
            self.add_link_url(url)

    def add_link_url(self, url: str) -> None:
        """A link as a row of its own, like a file (mods log round 1, M0001)."""
        url = url.strip()
        if not is_link(url):
            self._fail("That isn't a web link: a link starts with http:// or https:// and has no spaces.", self.content)
        elif any(e.row.path == url for e in self.files):
            self._fail(f"{link_name(url)} is already added.", self.content)
        else:
            self._add_file(FileRow(link_name(url), url), "added")

    def add_outlook(self) -> None:
        """The email selected in Outlook, copied whole through an attachment where Outlook allows it (release 5.33.1)."""
        scratch = outlook.copy_path(self.ctx.fs, self.ctx.data_root)
        self._read_emails(lambda: outlook.selected_emails(scratch), "adding the selected Outlook email")

    def add_selected_email(self) -> None:
        """The Outlook email hotkey (release 5.33.1): the email selected in Outlook joins the capture. The pinned window shows
        it; it opens first when nothing is showing, and otherwise the keyboard stays in Outlook, for the next email."""
        if not (self.pinned and self.pin_window is not None and self.pin_window.isVisible()) and not self.isVisible():
            self.pin()
        if self.pinned and self.pin_window is not None:
            self.pin_window.show_message("")
        self.add_outlook()
        if self.pinned and self.pin_window is not None:
            self.pin_window.sync()

    def _read_emails(self, read: Callable[[], list[EmailItem]], step: str) -> None:
        """Add the emails ``read`` gets from Outlook. Every failure shows here, never silently: under pythonw an error
        that escaped would show nowhere."""
        try:
            emails = read()
        except outlook.OutlookError as e:
            self._fail(str(e), self.content)
            return
        except Exception as e:  # noqa: BLE001 - anything Outlook or pywin32 raises that outlook.py didn't expect
            detail = outlook.record_problem(step, e)
            log.exception("Outlook: %s failed", step)
            self._fail(f"Outlook didn't give DocRepo the email ({detail}). Settings → Troubleshooting report collects the details.", self.content)
            return
        for email in emails:
            self._add_email(email)
        note = outlook.refused_note(emails)
        if note:
            self._fail(note, self.content)

    def _add_email(self, email: EmailItem) -> None:
        """The email's row, then a row for each attachment, link and picture email layer 0 finds in it (mods log round 1,
        M0024), with the cursor in the first kept part's description."""
        rows = email_rows(email)
        for row in rows:
            self._add_file(row, "outlook" if row.email else "email", focus=False)
        first = next((e for e in self.files if e.row.of is email and e.row.keep), None)
        (first.desc if first and first.desc else self.content).setFocus()

    def _file_note(self, row: FileRow, doc_id: str | None, link: bool) -> str:
        """The line beside a row's name: where its file stays or goes, or what layer 0 made of it."""
        part = row.part
        if row.email:
            emails = [e.row for e in self.files if e.row.email]
            position = next((n for n, r in enumerate(emails) if r is row), len(emails))
            return f"Saved as {msg_name(position)} in the capture's folder."
        if part and part.kind != "link":
            size = f"{size_text(part.size)}. " if part.size else ""
            if part.kind == "picture":
                return size + ("In the email's body. Small, so probably a logo or signature picture: unticked." if part.small
                               else "In the email's body. Saved in the capture's attachments folder.")
            return size + "Saved in the capture's attachments folder."
        if doc_id:
            return f"Already tracked as {doc_id}, so that record is reused."
        if link:
            return ("Unwrapped from Outlook's Safe Links. " if part and part.safe else "") + "Only the address is kept. DocRepo never opens or fetches it."
        return "It stays where it is."

    def _picture_pasted(self, image) -> None:
        """A picture pasted in the content text (release 5.27, decision 129): a file of the capture's, as a dropped file is,
        written as a PNG in the capture's attachments folder when it's saved, and shown on its task's notes page."""
        from docrepo.layer0 import Part
        from docrepo.save import Attachment
        from docrepo.ui.rich_edit import png_bytes

        data = png_bytes(image)
        taken = {e.row.name for e in self.files}
        base = f"Picture {self.ctx.now():%Y-%m-%d %H%M}"
        name, n = f"{base}.png", 2
        while name in taken:
            name, n = f"{base} ({n}).png", n + 1
        fs = self.ctx.fs
        attachment = Attachment(name, save=lambda target, data=data: fs.write_picture(target, data), size=len(data))
        self._add_file(FileRow(name, None, part=Part("picture", name, attachment=attachment, size=len(data), pasted=True)), "pasted")

    def _add_file(self, row: FileRow, src: str, line: str | None = None, focus: bool = True) -> None:
        m = self.ctx.model()
        link = is_link(row.path)  # a link is matched exactly; a path in any case, as Windows does
        kind = row.part.kind if row.part else ""

        def same(original: str) -> bool:
            return original == row.path if link else original.lower() == (row.path or "").lower()

        doc = next((d for d in m.documents.values() if row.path and d.original and same(d.original)), None)
        entry = FileEntry(row, src, line=line, doc=doc.id if doc else None)
        if row.of is None and row.section is None:
            row.section = self._cursor_section()  # where it goes if several # tasks split the note (release 5.32)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(18 if row.of else 0, 0, 0, 0)  # an email's parts sit under it
        frame = QFrame(objectName="fileRow")
        hl.addWidget(frame)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(7, 6, 7, 6)
        top = QHBoxLayout()
        if row.of is not None:
            entry.keep = QCheckBox("Keep")
            entry.keep.setChecked(row.keep)
            entry.keep.setToolTip("Untick to leave it out of the capture")
            entry.keep.toggled.connect(lambda on: self._keep(entry, on))
            top.addWidget(entry.keep)
        label = "Email" if row.email else {"attachment": "Attachment", "picture": "Picture"}.get(kind) or (
            "Link" if link else "Path" if src == "pasted" else "File")
        name = QLabel(f"<span style='color:#5a6571'>{label}</span>  <b>{esc(row.name)}</b>")
        name.setToolTip(row.path or "")
        top.addWidget(name)
        entry.note = QLabel(self._file_note(row, doc.id if doc else None, link), objectName="hint")
        top.addWidget(entry.note, 1)
        if row.of is None:
            entry.goes = QToolButton(objectName="goes")
            entry.goes.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            entry.goes.setMenu(QMenu(entry.goes))
            entry.goes.menu().aboutToShow.connect(lambda: self._goes_menu(entry))
            entry.goes.hide()
            top.addWidget(entry.goes)
            remove = QToolButton(text="×")
            remove.setToolTip(f"Remove {row.name}")
            remove.clicked.connect(lambda: self._remove_file(entry))
            top.addWidget(remove)
        fl.addLayout(top)
        entry.widget = holder
        self.files.append(entry)
        self.files_box.addWidget(holder)
        if row.email:
            entry.layer0 = QLabel(objectName="hint")
            entry.layer0.setWordWrap(True)
            fl.addWidget(entry.layer0)
            self._show_layer0()
            self.refresh()
            return
        entry.what = ("What's at this link?" if link else "What does this picture show?" if kind == "picture" else "What's in this file?")
        entry.desc = QLineEdit(doc.description or "" if doc else "")
        entry.desc.setAccessibleName(f"Description of {row.name}")
        fl.addWidget(entry.desc)
        opts = QHBoxLayout()
        entry.copy, entry.extract = QCheckBox("Save a copy"), QCheckBox("Extract information")
        opts.addWidget(entry.copy)
        opts.addWidget(entry.extract)
        opts.addStretch()
        fl.addLayout(opts)
        entry.copy.setVisible(not link)  # a link has nothing to copy or read, and a picture no text
        entry.extract.setVisible(not link and kind != "picture")
        entry.desc.textEdited.connect(self._apply_same_all)
        for box in (entry.copy, entry.extract):
            box.toggled.connect(self._apply_same_all)
        self._apply_same_all()
        self.refresh()
        if focus:
            entry.desc.setFocus()

    def _keep(self, entry: FileEntry, on: bool) -> None:
        """Keep, on an email's part: unticked, it's left out of the capture, and the email's layer 0 line says so."""
        entry.row.keep = on
        self._apply_same_all()
        self._show_layer0()
        self.refresh()

    def _show_layer0(self) -> None:
        rows = [e.row for e in self.files]
        for e in self.files:
            if e.layer0 is not None and e.row.email is not None:
                e.layer0.setText(f"<b>Email layer 0</b>  {esc(email_layer0_line(e.row.email, rows))} "
                                 "Each part has its own row below; untick one to leave it out.")

    def _remove_file(self, entry: FileEntry, from_content: bool = True) -> None:
        # Removing an email removes the rows email layer 0 made for its parts.
        gone = [entry, *(e for e in self.files if entry.row.email is not None and e.row.of is entry.row.email)]
        for e in gone:
            if e in self.files:
                self.files.remove(e)
            if e.widget:
                e.widget.deleteLater()
        for e in self.files:  # the emails after a removed one move up: email 2.msg becomes email.msg
            if e.row.email and e.note:
                e.note.setText(self._file_note(e.row, e.doc, False))
        if from_content and entry.src == "pasted" and entry.line:
            self._setting = True
            self.content.remove_line(entry.line)  # the rest keeps its formatting
            self._setting = False
        if sum(e.desc is not None for e in self.files) < 2:
            self.same_all.setChecked(False)
        self.refresh()

    def _apply_same_all(self) -> None:
        """With "Use the first file's…" on, the other described rows follow the first. An unticked part is left out.
        A description box left empty shows what Save will put there (mods log round 2, M0041)."""
        if not hasattr(self, "same_all"):
            return  # still being built
        described = [e for e in self.files if e.desc is not None]
        same = self.same_all.isChecked() and len(described) > 1
        first = described[0] if described else None
        for e in described:
            follows = same and e is not first
            for w in (e.desc, e.copy, e.extract):
                w.setEnabled(e.row.keep and not follows)
            e.desc.setPlaceholderText("Left out" if not e.row.keep else "Same as the first file" if follows
                                      else f"{e.what} Left empty: {self._default_desc(e.row)}")

    def _default_desc(self, row: FileRow) -> str:
        """The description Save gives a row left empty: the new task's title, or the picked task's."""
        if "new_task" in self.types:
            title = self.title.text().strip() or "(the new task's title)"
        else:
            t = self.ctx.model().tasks.get(self.task) if self.task else None
            title = t.title if t else None
        return default_description(row, title)

    def _file_rows(self) -> list[FileRow]:
        described = [e for e in self.files if e.desc is not None]
        first = described[0] if described else None
        for e in described:
            source = first if self.same_all.isChecked() and e is not first else e
            e.row.description = source.desc.text()
            # A choice a row doesn't offer (a link's, a picture's Extract information) stays off.
            e.row.save_a_copy = source.copy.isChecked() and not e.copy.isHidden()
            e.row.extract = source.extract.isChecked() and not e.extract.isHidden()
        return [e.row for e in self.files]

    def _email_texts(self) -> list[str]:
        return [e.row.email.text() for e in self.files if e.row.email]

    # ================= Parse and populate =================
    def parse(self) -> None:
        """Fill the fields for the checked capture types from the content text. Fields you typed in stay as they are."""
        if self.pages.currentIndex() == 1:
            return
        m = self.ctx.model()
        content = self.content.plain()  # its words: list items keep "- ", marks are dropped
        self.read_items()
        if self.reading:  # the items' lines are theirs: Parse and populate reads the rest (release 5.8)
            content = items.parse_text(self.reading, self.names())
        if "new_task" not in self.types and "update" not in self.types:
            if self.task and quick_update(content):
                self.types.add("update")
                if self.note_auto:
                    self.types.discard("note")
                self.prefill()
            else:
                self._fail("Check New task or Update first. For a quick update, start the content text with a state and a full stop, such as “Closed.”"
                           if self.task else "Check New task, or pick a task, first.", self.content)
                return
        text = "\n".join([content, *self._email_texts()])
        today = self.ctx.now().date()
        people, labels, events = self.ctx.parse_people(m), self.ctx.parse_labels(m), self.ctx.settings.event_words
        found: list[tuple[str, Found]] = []
        if "new_task" in self.types:
            typed = lambda key, w: w.value() if f"new.{key}" in self.touched else None  # noqa: E731
            known = Known(start=date.fromisoformat(self.n_start.value()) if self.n_start.is_valid() and self.n_start.value() else today,
                          due=_as_date(typed("due", self.n_due)), deadline=_as_date(typed("deadline", self.n_deadline)),
                          recurrence=self.n_recurrence.currentText() if self.n_recurrence.currentIndex() else "")
            r = parse_capture(text, "new_task", today, people, labels, events, known, refs=self.ctx.settings.reference_fields)
            own = items.self_fields(self.reading, self.names()) if self.reading else None
            if own and own.plant_event and not r.plant_event:  # **event on its own line (mods log round 3, M0059)
                as_plant_event(r, "**event")
            self._fill("new", r)
            for name in r.labels:
                if name not in self.n_labels.values():
                    self.n_labels.set_chips([*self.n_labels.chips(), Chip(name, name, filled=True)])
            for who, chips in ((r.leads, self.n_leads), (r.assignees, self.n_assignees)):
                for w in who:
                    value = w.id or w.name
                    if value not in chips.values():
                        chips.set_chips([*chips.chips(), Chip(value, m.person_name(w.id) if w.id else w.name, new=w.is_new, filled=True)])
            if any(f.key in ("start", "recurrence", "reminder", "state", "lead_hours", "assignee_hours", "plant_event", "refs") and not f.why
                   for f in r.found):
                self._set_more(self.n_more, self.n_more_button, True)
            found += [("", f) for f in r.found]
        if "update" in self.types and self.task:
            r = parse_capture(text, "update", today, people, labels, events, refs=self.ctx.settings.reference_fields)
            if "new_task" in self.types:  # the dates and first sentence belong to the new task; Update takes only a quick update's
                r.found = [f for f in r.found if f.key == "state" or (f.key == "status" and r.state)]
                if not r.state:
                    r.status = ""
                r.due = r.deadline = None
                r.deadline_desc = ""
            self._fill("upd", r)
            if any(f.key in ("plant_event", "refs") and not f.why for f in r.found):
                self._set_more(self.u_more, self.u_more_button, True)
            found += [("Update: " if "new_task" in self.types else "", f) for f in r.found]
        self._show_found(found)
        self.refresh()

    def _fill(self, prefix: str, r: Any) -> None:
        fields = self.__dict__.get("_fields", {})
        title_widget = {"new.title": self.title}
        for f in r.found:
            if f.key in ("labels", "leads", "assignees") or f.why:
                continue
            key = "current_status" if f.key == "status" else f"ref:{f.field}" if f.key == "refs" else f.key
            name = f"{prefix}.{key}"
            widget = title_widget.get(name) or fields.get(name)
            if widget is None:
                continue
            if name in self.touched:
                f.why = "Not filled: you typed in this field."
                continue
            value = r.refs[f.field] if f.key == "refs" else getattr(r, f.key)
            self._setting = True
            if isinstance(widget, DateField):
                widget.set_value(value.isoformat() if value else None)
                target = widget.line
            elif isinstance(widget, HoursField):
                widget.set_value(value)
                target = widget
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value or "No recurrence")
                target = widget
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
                target = widget
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
                target = widget
            else:
                widget.setText(value)
                target = widget
            self._setting = False
            set_filled(target, True)

    def _clear_found(self) -> None:
        """The found list, before Parse and populate runs (or after Clear): hidden in the new look, unless hints are shown."""
        self.found_label.setText(FOUND_EMPTY if LOOK.show_help else "")
        self.clear_found.hide()
        set_filled(self.found_box, False, "empty", True)
        self.found_box.setVisible(LOOK.show_help)

    def _show_found(self, found: list[tuple[str, Found]]) -> None:
        if not found:
            self.found_label.setText("<span style='color:#5a6571'>Nothing found. Fill in the fields by hand.</span>")
        else:
            items = []
            for lead, f in found:
                value = f.value if len(f.value) <= 80 else f.value[:80] + "…"
                source = f.source if len(f.source) <= 80 else f.source[:80] + "…"
                extra = (f": {esc(f.calc)}" if f.calc else "") + (f". {esc(f.why)}" if f.why else "")
                items.append(f"<li><b>{esc(lead + f.field)}</b> {esc(value)} <span style='color:#5a6571'>from “{esc(source)}”{extra}</span></li>")
            if LOOK.classic:
                self.found_label.setText(f"<ul style='margin:0'>{''.join(items)}</ul><span style='color:#5a6571'>Filled fields stay "
                                         "highlighted until you edit them. Nothing is saved until you press Save.</span>")
            else:  # one line of what it understood (the Title field shows the title); where each value came from is in the tooltip
                self.found_label.setText(understood_html([(lead, f) for lead, f in found if f.field != "Title"] or found))
                self.found_box.setToolTip("<br>".join(f"<b>{esc(lead + f.field)}</b> from “{esc(f.source[:80])}”" for lead, f in found))
        self.clear_found.show()
        set_filled(self.found_box, False, "empty", False)
        self.found_box.show()

    # ================= Copy prompt =================
    def _load_summary_types(self) -> None:
        current = self.prompt_type.currentText()
        self._summary_types = load_summary_types(self.ctx.data_root)
        self.prompt_type.clear()
        self.prompt_type.addItems([st.name for st in self._summary_types])
        if current:
            self.prompt_type.setCurrentText(current)

    def copy_prompt(self) -> None:
        if not self._summary_types:
            self._fail("There are no summary types in Config\\prompts.", self.prompt_type)
            return
        st = self._summary_types[self.prompt_type.currentIndex()]
        # The markup, as saved: an LLM reads Markdown's bold and lists (mods log round 2, M0045).
        text = "\n\n".join(x for x in [self.content.value()[0].strip(), *self._email_texts()] if x)
        cap = self.ctx.settings.extracted_text_cap_chars
        file_texts = [(e.row.name, extract_text(Path(e.row.path), cap).text) for e in self.files if e.row.path and not is_link(e.row.path)]
        blocks = capture_blocks(st, self.ctx.model(), text, file_texts, self.task)
        if not blocks:
            self._fail("Type or paste something first. This summary type sends the capture's content text."
                       if "raw_text_latest" in st.fields else "Pick a task first. This summary type sends the task's records.", self.content)
            return
        prompt = prompt_text(st, blocks)
        QGuiApplication.clipboard().setText(prompt)
        warn = self.ctx.settings.prompt_warn_chars
        long_note = f" That's long (over {warn}); check the LLM takes that much." if len(prompt) > warn else ""
        self.ctx.notify("Prompt copied", f"{len(prompt)} characters.{long_note} Paste the answer into Summary.")
        self._show_summary(True)

    def _show_summary(self, on: bool) -> None:
        self.summary_field.setVisible(on)
        self.add_summary.setVisible(not on and LOOK.classic)  # in the new look, Add a summary is in More
        if on:
            self.summary.setFocus()

    def _toggle_more(self, box: QWidget, button: QPushButton) -> None:
        self._set_more(box, button, box.isHidden())

    @staticmethod
    def _set_more(box: QWidget, button: QPushButton, on: bool) -> None:
        box.setVisible(on)
        button.setText(button.text()[:-1] + ("▾" if on else "▸"))

    # ================= Save =================
    def _fail(self, message: str, focus: QWidget | None = None) -> None:
        if self.pinned and not self._saving:  # a problem with something added, or a type, shows on the pinned window
            self.pin_window.show_message(message)
            return
        if self.pinned:  # Save couldn't save: the full window shows where to fix it
            self.unpin()
        self.error.setText(message)
        self.error.show()
        self.scroll.ensureWidgetVisible(self.error)
        if focus is not None:
            focus.setFocus()

    def _chips_people(self, chips: ChipPicker) -> list[Who]:
        return [Who(name=c.value) if c.new else Who(c.value) for c in chips.chips()]

    def update_values(self) -> dict[str, Any]:
        """The Update fields' values, in the form tasks.update_task takes them."""
        recurrence = self.u_recurrence.currentText() if self.u_recurrence.currentIndex() else None
        return {
            "state": self.u_state.currentText(), "current_status": self.u_status.toPlainText().strip(), "due": self.u_due.value(),
            "deadline": self.u_deadline.value(), "deadline_desc": self.u_deadline_desc.text().strip() or None,
            "leads": self._chips_people(self.u_leads), "assignees": self._chips_people(self.u_assignees),
            "lead_hours": self.u_lead_hours.value() if self.u_lead_hours.is_valid() else None,
            "assignee_hours": self.u_asg_hours.value() if self.u_asg_hours.is_valid() else None,
            "start": self.u_start.value(), "reminder": self.u_reminder.value(), "recurrence": recurrence,
            "repeat_until": self.u_repeat.value() if recurrence else None, "urgent": self.u_urgent.isChecked(), "meeting": self.u_meeting.isChecked(),
            "plant_event": self.u_plant.isChecked(), "references": {name: box.text().strip() for name, box in self.u_refs.items()},
        }

    def update_changes(self, t: Any) -> dict[str, Any]:
        """The Update fields that differ from the task: only these are changed."""
        if t is None:
            return {}
        current = {
            "state": t.state, "current_status": t.current_status, "due": t.due, "deadline": t.deadline, "deadline_desc": t.deadline_desc,
            "leads": [Who(p) for p in t.leads], "assignees": [Who(p) for p in t.assignees], "lead_hours": t.lead_hours,
            "assignee_hours": t.assignee_hours, "start": start_of(t).isoformat(), "reminder": t.reminder, "recurrence": t.recurrence,
            "repeat_until": t.repeat_until, "urgent": t.urgent, "meeting": t.meeting, "plant_event": t.plant_event,
        }
        values = self.update_values()
        out = {k: v for k, v in values.items() if k != "references" and v != current[k]}
        refs = {name: v for name, v in values["references"].items() if v != t.references.get(name, "")}
        if refs:  # only the reference fields that changed (release 5.9)
            out["references"] = refs
        return out

    def _check_fields(self) -> bool:
        groups = []
        if "new_task" in self.types:
            groups += [(self.n_due, "Due"), (self.n_deadline, "Deadline"), (self.n_start, "Start"), (self.n_reminder, "Reminder"),
                       (self.n_repeat, "Repeat until"), (self.n_lead_hours, "Lead hours"), (self.n_asg_hours, "Assignee hours")]
        if "update" in self.types:
            groups += [(self.u_due, "Due"), (self.u_deadline, "Deadline"), (self.u_start, "Start"), (self.u_reminder, "Reminder"),
                       (self.u_repeat, "Repeat until"), (self.u_lead_hours, "Lead hours"), (self.u_asg_hours, "Assignee hours")]
        for w, name in groups:
            if not w.is_valid():
                hours = isinstance(w, HoursField)
                self._fail(f"{name} isn't {'a number of hours' if hours else 'a date. Use YYYY-MM-DD'}.", w if hours else w.line)
                return False
        for on, editor in (("new_task" in self.types, self.n_keydates), ("update" in self.types and bool(self.task), self.u_keydates)):
            p = editor.problem() if on else None
            if p:
                self._fail(p[0], p[1])
                return False
        return True

    def update_key_dates(self) -> list[KeyDateRow] | None:
        """Update's key dates when they differ from the task's own (release 5.31), else None."""
        rows = self.u_keydates.rows()
        return rows if rows != self._u_keydates_were else None

    def draft(self) -> CaptureDraft:
        """Everything in the window, ready for save_capture."""
        recurrence = self.n_recurrence.currentText() if self.n_recurrence.currentIndex() else None
        # A plant event's Start counts only when it was typed or Parse and populate read it: the field starts at today,
        # and an event with no Start is one day (release 5.30).
        start = self.n_start.value()
        if self.n_plant.isChecked() and "new.start" not in self.touched and not self.n_start.line.property("filled"):
            start = None
        new = NewTaskFields(
            title=self.title.text(), labels=self.n_labels.values(), inherit_labels=self.n_inherit.isChecked(),
            leads=self._chips_people(self.n_leads), assignees=self._chips_people(self.n_assignees), due=self.n_due.value(),
            deadline=self.n_deadline.value(), deadline_desc=self.n_deadline_desc.text().strip() or None, urgent=self.n_urgent.isChecked(),
            meeting=self.n_meeting.isChecked(), state=self.n_state.currentText(), start=start, reminder=self.n_reminder.value(),
            recurrence=recurrence, repeat_until=self.n_repeat.value() if recurrence else None,
            lead_hours=self.n_lead_hours.value(), assignee_hours=self.n_asg_hours.value(), plant_event=self.n_plant.isChecked(),
            references={name: box.text().strip() for name, box in self.n_refs.items() if box.text().strip()},
            key_dates=self.n_keydates.rows(),
        )
        t = self.ctx.model().tasks.get(self.task) if self.task else None
        summary_type = self._summary_types[self.prompt_type.currentIndex()].name if not self.summary_field.isHidden() and self._summary_types else None
        content, formatted = self.content.value()
        return CaptureDraft(
            content=content, formatted=formatted, task=self.task, types=set(self.types), files=self._file_rows(),
            agenda=self._targets(), summary=self.summary.toPlainText() if not self.summary_field.isHidden() else "",
            summary_type=summary_type, new_task=new, update=self.update_changes(t) if "update" in self.types else {},
            update_key_dates=self.update_key_dates() if "update" in self.types and t else None,
            from_capture=self.from_capture, quick=self._quick(),
            meeting=self.meeting_on, meeting_name=self.meet_name.text() if self.meeting_on else "", agenda_ticks=dict(self.agenda_ticks),
            item_overrides={k: dict(v) for k, v in self.item_ov.items()}, refs=dict(self.ref_ids),
        )

    def save(self) -> None:
        if self.pages.currentIndex() == 1:
            self.mods.save()
            return
        self._saving = True
        try:
            if not self._check_fields():
                return
            draft = self.draft()
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result = save_capture(self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, draft, self.ctx.now())
            except SaveError as e:
                QGuiApplication.restoreOverrideCursor()
                self._fail(str(e), {"task": self.task_button, "title": self.title, "content": self.content, "meeting": self.meet_name}.get(e.focus))
                return
            QGuiApplication.restoreOverrideCursor()
        finally:
            self._saving = False
        found = list(result.problems)
        message = result.message
        if self.ctx.settings.outlook_categories and result.filed_emails:  # release 5.33
            marked, trouble = outlook.mark_filed(result.filed_emails, self.ctx.model(), self.ctx.settings.outlook_category_colour)
            message += f" Marked {marked} email{'s' if marked != 1 else ''} in Outlook with {'its' if len(result.filed_emails) == 1 else 'their'} task's name." if marked else ""
            found += trouble
        problems = (" Problems: " + " ".join(found)) if found else ""
        self.ctx.notify("Saved", message + problems)
        self.reset_draft()
        self.forget_draft()
        self._close_pin()
        self.hide()
        self.saved.emit(result)


def read_msg_file(path: Path) -> EmailItem:
    """A .msg file dropped from File Explorer (release 5.33): read without Outlook, and kept as it is; through Outlook
    only when DocRepo's own reader can't read it."""
    try:
        return msg.read(path.read_bytes())
    except (OSError, msg.MsgError):
        return outlook.open_msg_file(path)


def _as_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
