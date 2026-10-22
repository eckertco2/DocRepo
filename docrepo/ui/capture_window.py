"""The capture window: the hotkey window where everything enters DocRepo.

Top to bottom: the task picker, the capture types (Note, New task, Update), a
line saying what Save will do, the title (New task only), the content text,
Parse and populate with what it found, the files, Add to agenda, Copy prompt and
the summary, then the New task and Update fields. A "?" button opens the mods
log. Esc hides the window and keeps the draft; Ctrl+Enter saves; Alt+P parses.

Ported from the browse tool mockup's ``capture.js``; SPEC section 7 describes it.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QDragEnterEvent, QDropEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import diagnose, outlook, paste
from docrepo.db import RECURRENCES, STATES
from docrepo.extract import extract_text, to_unc
from docrepo.layer0 import size_text
from docrepo.links import is_link, link_name
from docrepo.model import TODAY, Model, is_person
from docrepo.parse import Found, Known, Who, parse_capture, quick_update
from docrepo.prompts import capture_blocks, load_summary_types, prompt_text
from docrepo.save import (
    CaptureDraft,
    EmailItem,
    FileRow,
    NewTaskFields,
    SaveError,
    default_description,
    email_layer0_line,
    email_rows,
    save_capture,
)
from docrepo.schedule import is_open, start_of
from docrepo.ui.context import AppContext
from docrepo.ui.mods_panel import ModsPanel
from docrepo.ui.style import STYLE
from docrepo.ui.task_picker import TaskPicker, full_path, path_text
from docrepo.ui.widgets import (
    Chip,
    ChipPicker,
    DateField,
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
WIDTH = 640


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
    what: str = ""  # the description's question, the start of its placeholder


def read_drop(mime) -> tuple[str, list[str]]:
    """What a drop holds: ("files", paths) for files that have a place on disk; ("outlook", []) for an email dragged
    from Outlook; ("virtual", []) for files only another program holds, such as one inside a zip folder; ("", []) for
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
    return "", []


def note_drag(stage: str, mime) -> str:
    """read_drop's answer, after noting the drag for the troubleshooting report: its formats' names and how many
    URLs it carried, never their paths or contents."""
    kind, _paths = read_drop(mime)
    urls = mime.urls()
    diagnose.note_drag(stage, list(mime.formats()), len(urls), sum(1 for u in urls if u.isLocalFile()), kind)
    return kind


def _accept_copy(event) -> None:
    """Take a drop as a copy, never a move: the original stays where it is."""
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()


class ContentEdit(QPlainTextEdit):
    """The content text box. Files and Outlook emails can be dropped on it; ``dropped`` sends read_drop's answer."""

    dropped = Signal(str, list)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt's name
        if note_drag("enter", event.mimeData()):
            _accept_copy(event)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData())[0]:
            _accept_copy(event)
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        note_drag("drop", event.mimeData())
        kind, paths = read_drop(event.mimeData())
        if kind:
            _accept_copy(event)
            self.dropped.emit(kind, paths)
        else:
            super().dropEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802 - Qt's name; pasting, and dropping text
        """Lists keep their bullets: OneNote's are only in the clipboard's HTML (mods log round 1, M0022)."""
        as_list = source.hasHtml() and paste.has_list(source.html())
        diagnose.note_drag("paste", list(source.formats()), 0, 0, "a list, from its HTML" if as_list else "text")
        if as_list:
            self.insertPlainText(paste.html_to_text(source.html()))
        elif source.hasText():
            self.insertPlainText(paste.bullets_to_dashes(source.text()))
        else:
            super().insertFromMimeData(source)


class CaptureWindow(QWidget):
    """The capture window. It's made once at start-up and shown or hidden, so it opens at once."""

    #: Sends the SaveResult after each save, so the browse tool can show what Save did.
    saved = Signal(object)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.ctx = ctx
        self.setObjectName("capture")
        self.setWindowTitle("DocRepo Capture")
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._setting = False  # True while the window fills fields itself, so it doesn't count as typing
        self._after_pick: str | None = None  # "update" or "agenda" when that hotkey opened the task picker
        self._summary_types: list = []
        self._path_timer = QTimer(self)
        self._path_timer.setSingleShot(True)
        self._path_timer.setInterval(350)
        self._path_timer.timeout.connect(self._sync_paths)
        self._build()
        self.reset_draft()
        for keys, handler in (("Ctrl+Return", self.save), ("Ctrl+Enter", self.save), ("Alt+P", self.parse)):
            QShortcut(QKeySequence(keys), self, handler)

    # ================= building the window =================
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget(objectName="header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 6, 8, 6)
        hl.addWidget(QLabel("DocRepo", objectName="appName"))
        hl.addWidget(QLabel("Capture"))
        self.hotkey_label = QLabel(self.ctx.settings.hotkey, objectName="hotkey")
        hl.addWidget(self.hotkey_label)
        hl.addStretch()
        mods_button = QToolButton(text="?")
        mods_button.setToolTip("Mods log: note a change you want in DocRepo")
        mods_button.clicked.connect(lambda: self.show_mods(True))
        hl.addWidget(mods_button)
        outer.addWidget(header)

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
        self.body.setContentsMargins(14, 12, 14, 14)
        self.body.setSpacing(10)
        scroll.setWidget(body)
        self.scroll = scroll
        cp.addWidget(scroll, 1)
        footer = QWidget(objectName="footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 8, 14, 8)
        footer_hint = QLabel("Ctrl+Enter saves. Esc hides the window and keeps the draft.", objectName="hint")
        footer_hint.setWordWrap(True)
        fl.addWidget(footer_hint, 1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.reset_draft)
        fl.addWidget(clear)
        save = QPushButton("Save", objectName="primary")
        save.clicked.connect(self.save)
        fl.addWidget(save)
        cp.addWidget(footer)
        self.pages.addWidget(capture_page)
        self.mods = ModsPanel(self.ctx)
        self.mods.back.connect(lambda: self.show_mods(False))
        self.pages.addWidget(self.mods)

        b = self.body
        # Task
        self.task_button = QPushButton()
        self.task_button.setStyleSheet("text-align: left; padding: 5px 9px;")
        self.task_button.clicked.connect(self._open_picker)
        b.addWidget(field("Task", self.task_button, "task"))
        # Capture types
        types = QHBoxLayout()
        types.addWidget(QLabel("Capture types", objectName="fieldLabel"))
        self.type_boxes: dict[str, QCheckBox] = {}
        for key, label in (("note", "Note"), ("new_task", "New task"), ("update", "Update")):
            box = QCheckBox(label)
            box.clicked.connect(lambda checked, k=key: self.set_type(k, checked))
            self.type_boxes[key] = box
            types.addWidget(box)
        types_note = QLabel()
        types.addWidget(InfoButton("types", types_note))
        types.addStretch()
        b.addLayout(types)
        b.addWidget(types_note)
        self.does = QLabel(objectName="does")
        self.does.setWordWrap(True)
        b.addWidget(self.does)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        b.addWidget(self.error)
        # Title and content text
        self.title = QLineEdit()
        self.title.textEdited.connect(lambda: self._touch("new.title", self.title))
        self.title.textChanged.connect(lambda _: self._apply_same_all())  # empty descriptions name the new task
        self.title_field = field("Title", self.title, "title", "or leave it empty to take it from the content text")
        b.addWidget(self.title_field)
        self.content = ContentEdit()
        self.content.setMinimumHeight(110)
        self.content.textChanged.connect(self._content_changed)
        self.content.dropped.connect(self.dropped)
        self.content_field = field("Content text", self.content, "content")
        b.addWidget(self.content_field)
        hint = QLabel("Type or paste. Drop files or Outlook emails anywhere on this window. Start with “Closed.” or another state for a quick update.",
                      objectName="hint")
        hint.setWordWrap(True)
        b.addWidget(hint)
        # Parse and populate
        row = QHBoxLayout()
        self.parse_button = QPushButton("Parse and populate   Alt+P")
        self.parse_button.clicked.connect(self.parse)
        row.addWidget(self.parse_button)
        parse_note = QLabel()
        row.addWidget(InfoButton("parse", parse_note))
        parse_hint = QLabel("Fills the fields below from the content text.", objectName="hint")
        parse_hint.setWordWrap(True)
        row.addWidget(parse_hint, 1)
        b.addLayout(row)
        b.addWidget(parse_note)
        self.found_box = QFrame(objectName="found")
        fbl = QVBoxLayout(self.found_box)
        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Parse and populate found</b>"))
        top.addStretch()
        hide_found = QPushButton("Hide", objectName="link")
        hide_found.clicked.connect(lambda: self.found_box.hide())
        top.addWidget(hide_found)
        fbl.addLayout(top)
        self.found_label = QLabel()
        self.found_label.setWordWrap(True)
        self.found_label.setTextFormat(Qt.TextFormat.RichText)
        fbl.addWidget(self.found_label)
        self.found_box.hide()
        b.addWidget(self.found_box)
        # Files
        self.files_box = QVBoxLayout()
        self.files_box.setSpacing(5)
        self.files_label = field("Files", None, "files", "a description for each")
        b.addWidget(self.files_label)
        b.addLayout(self.files_box)
        self.same_all = QCheckBox("Use the first file's description and choices for every file")
        self.same_all.toggled.connect(self._apply_same_all)
        b.addWidget(self.same_all)
        attach = QHBoxLayout()
        add_files = QPushButton("Add files…")
        add_files.clicked.connect(self._pick_files)
        attach.addWidget(add_files)
        add_link = QPushButton("Add link…")
        add_link.setToolTip("A web or SharePoint link. DocRepo keeps the address, and never opens or fetches it.")
        add_link.clicked.connect(self.add_link)
        attach.addWidget(add_link)
        add_email = QPushButton("Add selected Outlook email")
        add_email.clicked.connect(self.add_outlook)
        attach.addWidget(add_email)
        attach.addStretch()
        b.addLayout(attach)
        self.copy_hint = QLabel(objectName="hint")
        self.copy_hint.setWordWrap(True)
        b.addWidget(self.copy_hint)
        # Add to agenda
        self.agenda = ChipPicker(self._agenda_options, "Search meetings, people and tasks")
        self.agenda.changed.connect(self.refresh)
        self.agenda_field = field("Add to agenda", self.agenda, "agenda")
        b.addWidget(self.agenda_field)
        # Copy prompt and the summary
        row = QHBoxLayout()
        self.prompt_type = QComboBox()
        self.prompt_type.setAccessibleName("Summary type")
        row.addWidget(self.prompt_type, 1)
        copy = QPushButton("Copy prompt")
        copy.clicked.connect(self.copy_prompt)
        row.addWidget(copy)
        prompt_note = QLabel()
        row.addWidget(InfoButton("prompt", prompt_note))
        b.addLayout(row)
        b.addWidget(prompt_note)
        self.summary = QPlainTextEdit()
        self.summary.setFixedHeight(70)
        self.summary_field = field("Summary", self.summary, "summary", "paste the LLM's answer here")
        b.addWidget(self.summary_field)
        self.add_summary = QPushButton("Add a summary", objectName="link")
        self.add_summary.clicked.connect(lambda: self._show_summary(True))
        b.addWidget(self.add_summary)
        self._build_new_fields()
        self._build_update_fields()
        b.addStretch()

    def _build_new_fields(self) -> None:
        self.new_group = QGroupBox()
        g = QVBoxLayout(self.new_group)
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
        flags = QHBoxLayout()
        self.n_urgent, self.n_meeting = QCheckBox("Urgent"), QCheckBox("Meeting")
        for box, key in ((self.n_urgent, "urgent"), (self.n_meeting, "meeting")):
            flags.addWidget(box)
            note = QLabel()
            flags.addWidget(InfoButton(key, note))
            g.addWidget(note)
        flags.addStretch()
        g.addLayout(flags)
        self.n_more_button = QPushButton("More fields: state, start, reminder, recurrence and hours ▸", objectName="moreLink")
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
        self.n_more.hide()
        g.addWidget(self.n_more)
        self.body.addWidget(self.new_group)
        self._watch("new", {"due": self.n_due, "deadline": self.n_deadline, "deadline_desc": self.n_deadline_desc, "urgent": self.n_urgent,
                            "meeting": self.n_meeting, "state": self.n_state, "start": self.n_start, "reminder": self.n_reminder,
                            "recurrence": self.n_recurrence, "repeat_until": self.n_repeat, "lead_hours": self.n_lead_hours,
                            "assignee_hours": self.n_asg_hours})

    def _build_update_fields(self) -> None:
        self.upd_group = QGroupBox()
        g = QVBoxLayout(self.upd_group)
        grid = QGridLayout()
        self.u_state = QComboBox()
        self.u_state.addItems(list(STATES))
        self.u_due, self.u_deadline = DateField(), DateField()
        grid.addWidget(field("State", self.u_state, "state"), 0, 0)
        grid.addWidget(field("Due", self.u_due, "due"), 0, 1)
        g.addLayout(grid)
        self.u_status = QPlainTextEdit()
        self.u_status.setFixedHeight(48)
        g.addWidget(field("Current status", self.u_status, "status"))
        grid2 = QGridLayout()
        self.u_deadline_desc = QLineEdit()
        grid2.addWidget(field("Deadline", self.u_deadline, "deadline"), 0, 0)
        grid2.addWidget(field("Deadline description", self.u_deadline_desc, "deadlineDesc"), 0, 1)
        g.addLayout(grid2)
        self.u_more_button = QPushButton("More fields: people, hours, start, reminder, recurrence, urgent and meeting ▸", objectName="moreLink")
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
        self.u_urgent, self.u_meeting = QCheckBox("Urgent"), QCheckBox("Meeting")
        self.u_repeat_field = field("Repeat until", self.u_repeat, "repeatUntil")
        cells = [(field("Lead", self.u_leads, "leads"), 0, 0), (field("Assignees", self.u_assignees, "assignees"), 0, 1),
                 (field("Lead hours", self.u_lead_hours, "hours"), 1, 0), (field("Assignee hours", self.u_asg_hours), 1, 1),
                 (field("Start", self.u_start, "start"), 2, 0), (field("Reminder", self.u_reminder, "reminder"), 2, 1),
                 (field("Recurrence", self.u_recurrence, "recurrence"), 3, 0), (self.u_repeat_field, 3, 1),
                 (self.u_urgent, 4, 0), (self.u_meeting, 4, 1)]
        for w, r, c in cells:
            more.addWidget(w, r, c)
        self.u_more.hide()
        g.addWidget(self.u_more)
        self.changes_label = QLabel(objectName="hint")
        self.changes_label.setWordWrap(True)
        g.addWidget(self.changes_label)
        self.body.addWidget(self.upd_group)
        self._watch("upd", {"state": self.u_state, "current_status": self.u_status, "due": self.u_due, "deadline": self.u_deadline,
                            "deadline_desc": self.u_deadline_desc, "lead_hours": self.u_lead_hours, "assignee_hours": self.u_asg_hours,
                            "start": self.u_start, "reminder": self.u_reminder, "recurrence": self.u_recurrence, "repeat_until": self.u_repeat,
                            "urgent": self.u_urgent, "meeting": self.u_meeting})
        for chips in (self.u_leads, self.u_assignees):
            chips.changed.connect(self.refresh)

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
                     agenda: list[str] | None = None, agenda_focus: bool = False, from_capture: str | None = None) -> None:
        """Open the window. ``mode`` checks only that capture type ("note", "new_task" or "update"). ``agenda`` picks
        agenda targets under Add to agenda. ``from_capture`` starts Make it a task from an unfiled capture."""
        self._load_summary_types()
        if from_capture:
            self.make_task_from(from_capture)
        else:
            if task:
                self.set_task(task)
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
                self.agenda.set_chips([Chip(x, m.target_name(x)) for x in agenda])
        self.error.hide()
        self.refresh()
        self.show_mods(mods)
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()
        target = (self.mods.text if mods else self.agenda.edit if agenda_focus
                  else self.title if "new_task" in self.types and not self.title.text() else self.content)
        target.setFocus()

    def open_with_hotkey(self, kind: str) -> None:
        """A capture type's own hotkey (mods log round 1, M0010 and M0020): "note", "new_task", "update" or "agenda".
        Note and New task open with that type checked. Update and Add to agenda need a task: with the draft's task,
        Update is checked at once (and for Add to agenda, the cursor goes there); with none, the task picker opens,
        and picking a task does the same."""
        if kind in ("note", "new_task"):
            self.show_capture(mode=kind)
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
        height = min(int(area.height() * 0.88), max(560, self.sizeHint().height()))
        self.resize(WIDTH, height)
        self.move(area.x() + (area.width() - WIDTH) // 2, area.y() + max(16, int(area.height() * 0.05)))

    def hide_capture(self) -> None:
        self.hide()

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
        if note_drag("enter", event.mimeData()):
            _accept_copy(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData())[0]:
            _accept_copy(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        note_drag("drop", event.mimeData())
        kind, paths = read_drop(event.mimeData())
        if kind:
            _accept_copy(event)
            self.dropped(kind, paths)

    def dropped(self, kind: str, paths: list[str]) -> None:
        """What a drop on the window or the content text brought: files, an Outlook email, or files DocRepo can't read."""
        if kind == "files":
            self.add_paths(paths)
        elif kind == "outlook":
            self.add_outlook()
        elif kind == "virtual":
            self._fail("These files come from a program that doesn't hand DocRepo a file it can read, such as a zip folder. "
                       "Save or extract them to a folder first, then drop them from there.", self.content)

    # ================= the draft =================
    def reset_draft(self) -> None:
        """Clear the window for a new capture."""
        self._setting = True
        self.task: str | None = None
        self.from_capture: str | None = None
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
        for box in (self.n_urgent, self.n_meeting, self.u_urgent, self.u_meeting):
            box.setChecked(False)
        self.n_inherit.setChecked(True)
        self.n_state.setCurrentText("Not started")
        self.n_recurrence.setCurrentIndex(0)
        self.same_all.setChecked(False)
        for w in self.__dict__.get("_fields", {}).values():
            set_filled(w.line if isinstance(w, DateField) else w, False)
        self._setting = False
        self._show_summary(False)
        self.found_box.hide()
        self.error.hide()
        self.refresh()

    def make_task_from(self, capture_id: str) -> None:
        """Make it a task: a new task from an unfiled capture. Saving creates it and files the capture to it."""
        from docrepo.captures import read_content
        from docrepo.text import first_sentence, plain_text

        m = self.ctx.model()
        c = m.captures[capture_id]
        content = read_content(self.ctx.data_root, c) or ""
        self.reset_draft()
        self.from_capture = capture_id
        self.types, self.note_auto = {"new_task"}, False
        self._set_plain(self.content, content)
        sentence = first_sentence(plain_text(content), 400)
        title = parse_capture(sentence, "new_task", self.ctx.now().date(), self.ctx.parse_people(m), [], []).title if sentence else ""
        self.title.setText(title or c.title)
        self.refresh()

    def set_task(self, task_id: str | None) -> None:
        if task_id == self.task:
            return
        self.task = task_id
        if not task_id and "update" in self.types:
            self._drop_type("update")
        if "update" in self.types:
            self.prefill()
        self.found_box.hide()
        self.error.hide()
        self.refresh()

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
        self.found_box.hide()
        self.refresh()
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
        self.task_button.setText(full_path(m, t.id) if t else ("None: a new top-level task" if new else "None: keep it unfiled"))
        self.title_field.setVisible(new)
        self.content_field.property("label").setText("Content text" + ("  <span style='color:#87919c'>becomes the new task's description</span>" if new else ""))
        self.parse_button.setEnabled(new or upd or bool(t))
        self.new_group.setVisible(new)
        self.new_group.setTitle(f"NEW TASK UNDER {t.title.upper()}" if t else "NEW TOP-LEVEL TASK")
        inherited = [name for name, _ in m.labels_of(t.id)] if t else []
        self.n_inherit_row.setVisible(bool(t))
        self.n_inherited.setText(("Inherited: " + ", ".join(inherited) if inherited else "The parent has none.") if self.n_inherit.isChecked() else "")
        self.n_repeat_field.setVisible(self.n_recurrence.currentIndex() > 0)
        self.upd_group.setVisible(upd and bool(t))
        if t:
            self.upd_group.setTitle(f"UPDATE {t.title.upper()}")
        self.u_repeat_field.setVisible(self.u_recurrence.currentIndex() > 0)
        shown = self._agenda_shown()
        self.agenda_field.setVisible(shown)
        self.agenda_field.property("label").setText("Add to agenda  <span style='color:#87919c'>" + (
            "puts the new task on it" if new else "puts the picked task on it" if upd and t else "puts this note on it") + "</span>")
        self.files_label.setVisible(bool(self.files))
        self.same_all.setVisible(sum(e.desc is not None for e in self.files) > 1)
        self._apply_same_all()  # the placeholders name the task
        where ="the new task's Files folder" if new else f"Tasks\\{t.id}\\Files\\" if t else "the task's Files folder once the capture is filed"
        has_files = any(e.copy is not None and not e.copy.isHidden() for e in self.files)  # rows that offer Save a copy
        self.copy_hint.setText(f"Save a copy puts the file in {where}, named with today's date. Extract information marks it for the later processing stage."
                               if has_files else "")
        self.copy_hint.setVisible(has_files)
        changes = self.update_changes(t) if upd and t else {}
        self.changes_label.setText(
            "Status log: " + "; ".join(f"{k.replace('_', ' ')} → {self._short(v)}" for k, v in changes.items())
            if changes else "Prefilled with the task's current values. Each change goes into its status log.")
        self.does.setText(self._does(m, len(changes)))
        if self.from_capture:
            self.does.setText(f"Save creates {'a subtask under <b>' + esc(t.title) + '</b>' if t else 'a top-level task'} from "
                              f"{self.from_capture}, with this content text as its description, and files {self.from_capture} to it. "
                              "The capture's own text stays as it was.")

    @staticmethod
    def _short(value: Any) -> str:
        text = ", ".join(w.name if isinstance(w, Who) else str(w) for w in value) if isinstance(value, list) else "none" if value in (None, "") else str(value)
        return text if len(text) <= 40 else text[:40] + "…"

    def _agenda_shown(self) -> bool:
        return "new_task" in self.types or ("update" in self.types and bool(self.task)) or not self.task

    def _does(self, m: Model, n_changes: int) -> str:
        t = m.tasks.get(self.task) if self.task else None
        name = f"<b>{esc(t.title)}</b>" if t else ""
        text = bool(self.content.toPlainText().strip())
        new, upd, note = ("new_task" in self.types, "update" in self.types, "note" in self.types)
        parts = []
        if new:
            parts.append(f"creates {'a subtask under ' + name if t else 'a top-level task'}" + (", with this content text as its description" if text else ""))
        if upd and t:
            parts.append(f"updates {name}: " + (f"{n_changes} changed field{'s go' if n_changes > 1 else ' goes'} into its status log" if n_changes
                                                   else "this goes into its status log" if text else "nothing has changed yet"))
        targets = self.agenda.values() if self._agenda_shown() else []
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
        return "Save " + parts[0] + "." + (" It also " + and_list(parts[1:]) + "." if len(parts) > 1 else "")

    # ================= the task picker and other pickers =================
    def _open_picker(self) -> None:
        none = ("None", "A new top-level task" if "new_task" in self.types else "Keep it unfiled")
        self.picker = TaskPicker(self, self.ctx.model, none)
        self.picker.picked.connect(self._picked)
        self.picker.setMinimumWidth(max(300, self.task_button.width()))
        self.picker.popup(self.task_button.mapToGlobal(self.task_button.rect().bottomLeft()))

    def _picked(self, task_id: str | None) -> None:
        self.set_task(task_id)
        after, self._after_pick = self._after_pick, None
        if after and task_id:  # the Update or Add to agenda hotkey opened the picker: only Update is checked, as with a task already picked
            self.show_capture(mode="update", agenda_focus=after == "agenda")
            return
        (self.title if "new_task" in self.types else self.content).setFocus()

    def _label_options(self, text: str, picked: list[str]) -> list[Option]:
        return label_options(self.ctx.model(), text, picked)

    def _people_options(self, text: str, picked: list[str]) -> list[Option]:
        return people_options(self.ctx.model(), self.ctx.settings.me, text, picked)

    def _agenda_options(self, text: str, picked: list[str]) -> list[Option]:
        """Today first (mods log round 1, M0016), then open meetings and people; typing also finds any open task. The task
        going on the agenda is left out."""
        m = self.ctx.model()
        q = text.strip().lower()
        subject = None if "new_task" in self.types else self.task
        today = self.ctx.now().date()
        options = [Option(TODAY, "Today", "Your list for today")]
        options += [Option(t.id, t.title, f"Meeting, next {m.meeting_when(t.id, today)}" if t.recurrence else "Meeting", ) for t in m.open_meetings()]
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
        self._path_timer.start()
        if not self._setting:
            self.refresh()

    def _sync_paths(self) -> None:
        """A line of the content text that's an existing file's path, or a link, adds a row for it; deleting the line
        removes it."""
        lines = [line.strip() for line in self.content.toPlainText().split("\n") if PATH_LINE.match(line.strip()) or is_link(line)]
        keep = {line.lower() for line in lines}
        for entry in [e for e in self.files if e.src == "pasted" and (e.line or "").lower() not in keep]:
            self._remove_file(entry, from_content=False)
        for line in lines:
            if not any(line.lower() in ((e.line or "").lower(), (e.row.path or "").lower()) for e in self.files):
                if is_link(line):
                    # No focus move: a link typed by hand matches before it's finished, and typing must go on.
                    self._add_file(FileRow(link_name(line), line), "pasted", line, focus=False)
                    continue
                try:
                    exists = Path(line).is_file()
                except OSError:
                    exists = False
                if exists:
                    self._add_file(FileRow(Path(line).name, to_unc(line)), "pasted", line)

    def add_paths(self, paths: list[str]) -> None:
        """Files dropped or picked. A .msg file is read through Outlook as an email. A folder, or something that
        isn't there, is left out, and the window says so."""
        left_out = []
        for p in paths:
            path = Path(p)
            if path.suffix.lower() == ".msg":
                self._read_emails(lambda path=path: [outlook.open_msg_file(path)], "reading a dropped .msg file")
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
        self._read_emails(outlook.selected_emails, "adding the selected Outlook email")

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
            return "Saved as email.msg in the capture's folder."
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

    def _add_file(self, row: FileRow, src: str, line: str | None = None, focus: bool = True) -> None:
        m = self.ctx.model()
        link = is_link(row.path)  # a link is matched exactly; a path in any case, as Windows does
        kind = row.part.kind if row.part else ""

        def same(original: str) -> bool:
            return original == row.path if link else original.lower() == (row.path or "").lower()

        doc = next((d for d in m.documents.values() if row.path and d.original and same(d.original)), None)
        entry = FileEntry(row, src, line=line, doc=doc.id if doc else None)
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
        top.addWidget(QLabel(self._file_note(row, doc.id if doc else None, link), objectName="hint"), 1)
        if row.of is None:
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
        if from_content and entry.src == "pasted":
            lines = [line for line in self.content.toPlainText().split("\n") if line.strip().lower() != (entry.line or "").lower()]
            self._set_plain(self.content, "\n".join(lines))
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
        content = self.content.toPlainText()
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
            r = parse_capture(text, "new_task", today, people, labels, events, known)
            self._fill("new", r)
            for name in r.labels:
                if name not in self.n_labels.values():
                    self.n_labels.set_chips([*self.n_labels.chips(), Chip(name, name, filled=True)])
            for who, chips in ((r.leads, self.n_leads), (r.assignees, self.n_assignees)):
                for w in who:
                    value = w.id or w.name
                    if value not in chips.values():
                        chips.set_chips([*chips.chips(), Chip(value, m.person_name(w.id) if w.id else w.name, new=w.is_new, filled=True)])
            if any(f.key in ("start", "recurrence", "reminder", "state", "lead_hours", "assignee_hours") and not f.why for f in r.found):
                self._set_more(self.n_more, self.n_more_button, True)
            found += [("", f) for f in r.found]
        if "update" in self.types and self.task:
            r = parse_capture(text, "update", today, people, labels, events)
            if "new_task" in self.types:  # the dates and first sentence belong to the new task; Update takes only a quick update's
                r.found = [f for f in r.found if f.key == "state" or (f.key == "status" and r.state)]
                if not r.state:
                    r.status = ""
                r.due = r.deadline = None
                r.deadline_desc = ""
            self._fill("upd", r)
            found += [("Update: " if "new_task" in self.types else "", f) for f in r.found]
        self._show_found(found)
        self.refresh()

    def _fill(self, prefix: str, r: Any) -> None:
        fields = self.__dict__.get("_fields", {})
        title_widget = {"new.title": self.title}
        for f in r.found:
            if f.key in ("labels", "leads", "assignees") or f.why:
                continue
            key = "current_status" if f.key == "status" else f.key
            name = f"{prefix}.{key}"
            widget = title_widget.get(name) or fields.get(name)
            if widget is None:
                continue
            if name in self.touched:
                f.why = "Not filled: you typed in this field."
                continue
            value = getattr(r, f.key)
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
            self.found_label.setText(f"<ul style='margin:0'>{''.join(items)}</ul><span style='color:#5a6571'>Filled fields stay highlighted "
                                     "until you edit them. Nothing is saved until you press Save.</span>")
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
        text = "\n\n".join(x for x in [self.content.toPlainText().strip(), *self._email_texts()] if x)
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
        self.add_summary.setVisible(not on)
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
        }

    def update_changes(self, t: Any) -> dict[str, Any]:
        """The Update fields that differ from the task: only these are changed."""
        if t is None:
            return {}
        current = {
            "state": t.state, "current_status": t.current_status, "due": t.due, "deadline": t.deadline, "deadline_desc": t.deadline_desc,
            "leads": [Who(p) for p in t.leads], "assignees": [Who(p) for p in t.assignees], "lead_hours": t.lead_hours,
            "assignee_hours": t.assignee_hours, "start": start_of(t).isoformat(), "reminder": t.reminder, "recurrence": t.recurrence,
            "repeat_until": t.repeat_until, "urgent": t.urgent, "meeting": t.meeting,
        }
        return {k: v for k, v in self.update_values().items() if v != current[k]}

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
        return True

    def draft(self) -> CaptureDraft:
        """Everything in the window, ready for save_capture."""
        recurrence = self.n_recurrence.currentText() if self.n_recurrence.currentIndex() else None
        new = NewTaskFields(
            title=self.title.text(), labels=self.n_labels.values(), inherit_labels=self.n_inherit.isChecked(),
            leads=self._chips_people(self.n_leads), assignees=self._chips_people(self.n_assignees), due=self.n_due.value(),
            deadline=self.n_deadline.value(), deadline_desc=self.n_deadline_desc.text().strip() or None, urgent=self.n_urgent.isChecked(),
            meeting=self.n_meeting.isChecked(), state=self.n_state.currentText(), start=self.n_start.value(), reminder=self.n_reminder.value(),
            recurrence=recurrence, repeat_until=self.n_repeat.value() if recurrence else None,
            lead_hours=self.n_lead_hours.value(), assignee_hours=self.n_asg_hours.value(),
        )
        t = self.ctx.model().tasks.get(self.task) if self.task else None
        summary_type = self._summary_types[self.prompt_type.currentIndex()].name if self.summary_field.isVisible() and self._summary_types else None
        return CaptureDraft(
            content=self.content.toPlainText(), task=self.task, types=set(self.types), files=self._file_rows(),
            agenda=self.agenda.values(), summary=self.summary.toPlainText() if self.summary_field.isVisible() else "",
            summary_type=summary_type, new_task=new, update=self.update_changes(t) if "update" in self.types else {},
            from_capture=self.from_capture,
        )

    def save(self) -> None:
        if self.pages.currentIndex() == 1:
            self.mods.save()
            return
        if not self._check_fields():
            return
        draft = self.draft()
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = save_capture(self.ctx.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, draft, self.ctx.now())
        except SaveError as e:
            self._fail(str(e), {"task": self.task_button, "title": self.title, "content": self.content}.get(e.focus))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        problems = (" Problems: " + " ".join(result.problems)) if result.problems else ""
        self.ctx.notify("Saved", result.message + problems)
        self.reset_draft()
        self.hide()
        self.saved.emit(result)


def _as_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
