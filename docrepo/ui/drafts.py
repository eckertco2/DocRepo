"""The capture window's side of drafts (release 5.77, round 7's item 94, decisions 333 to 338): what goes into a
draft's folder and back out of it, and the footer's Drafts list. ``docrepo.drafts`` keeps the folders.

A draft holds the whole form, as the Capture wheel's draft set aside did (release 5.41, which this replaces), and its
files: an email as its .msg file, with the description and Keep of each of its parts; a file a program handed over as
its bytes; a pasted picture as its PNG; a path or a link as text.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from docrepo import drafts, msg
from docrepo.layer0 import Part
from docrepo.save import Attachment, EmailItem, FileRow, email_rows
from docrepo.tasks import KeyDateRow
from docrepo.ui.icons import icon
from docrepo.ui.widgets import Chip

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow

log = logging.getLogger(__name__)

#: The form's fields, by kind, beyond what ``CaptureWindow._draft_data`` keeps (release 5.41's draft set aside).
TEXTS = ("n_deadline_desc", "u_deadline_desc", "n_lead_hours", "n_asg_hours", "u_lead_hours", "u_asg_hours", "n_duration", "u_duration")
UNITS = ("n_lead_row", "n_asg_row", "u_lead_row", "u_asg_row")
PLAIN = ("summary", "u_status")
DATES = ("n_due", "n_deadline", "n_reminder", "n_repeat", "n_start", "u_due", "u_deadline", "u_start", "u_reminder", "u_repeat")
CHIPS = ("n_labels", "n_leads", "n_assignees", "u_leads", "u_assignees", "agenda")
TICKS = ("n_urgent", "n_meeting", "n_plant", "u_urgent", "u_meeting", "u_plant", "n_inherit", "same_all", "n_calendar", "u_calendar")
COMBOS = ("n_state", "n_recurrence", "u_state", "u_recurrence")
#: The email's fields a draft keeps beside its .msg file, for an email that had none to keep.
EMAIL_FIELDS = ("subject", "sender", "sent", "to", "body", "html", "entry_id", "store_id")


def holds_draft(c: CaptureWindow) -> bool:
    """Whether the window holds something worth keeping: words, a title, files, meeting notes or Make it a task. A task
    picked and nothing else isn't (decision 333)."""
    return bool(c.content.value()[0].strip() or c.title.text().strip() or c.files or c.meeting_on or c.from_capture)


# ---- the form ----
def form_of(c: CaptureWindow) -> dict[str, Any]:
    return {
        "texts": {n: getattr(c, n).text() for n in TEXTS},
        "units": {n: getattr(c, n).unit_name() for n in UNITS},
        "plain": {n: getattr(c, n).toPlainText() for n in PLAIN},
        "dates": {n: getattr(c, n).value() for n in DATES},
        "chips": {n: [[x.value, x.label, x.new] for x in getattr(c, n).chips()] for n in CHIPS},
        "ticks": {n: getattr(c, n).isChecked() for n in TICKS},
        "combos": {n: getattr(c, n).currentText() for n in COMBOS},
        "refs": {"n": {k: b.text() for k, b in c.n_refs.items()}, "u": {k: b.text() for k, b in c.u_refs.items()}},
        "keydates": {"n": [asdict(r) for r in c.n_keydates.rows()], "u": [asdict(r) for r in c.u_keydates.rows()]},
    }


def restore_form(c: CaptureWindow, form: dict[str, Any]) -> None:
    for n, v in form.get("texts", {}).items():
        getattr(c, n).setText(str(v or ""))
    for n, v in form.get("units", {}).items():
        getattr(c, n).set_unit_name(v if v in ("all", "day", "week") else "day" if v else "all")  # a draft set aside before h a week said True or False
    for n, v in form.get("plain", {}).items():
        getattr(c, n).setPlainText(str(v or ""))
    for n, v in form.get("dates", {}).items():
        getattr(c, n).set_value(v)
    for n, v in form.get("chips", {}).items():
        getattr(c, n).set_chips([Chip(str(x[0]), str(x[1]), bool(x[2])) for x in v])
    for n, v in form.get("ticks", {}).items():
        getattr(c, n).setChecked(bool(v))
    for n, v in form.get("combos", {}).items():
        box = getattr(c, n)
        box.setCurrentIndex(max(0, box.findText(str(v))))
    refs = form.get("refs", {})
    for boxes, values in ((c.n_refs, refs.get("n", {})), (c.u_refs, refs.get("u", {}))):
        for k, b in boxes.items():
            b.setText(str(values.get(k, "")))
    keydates = form.get("keydates", {})
    c.n_keydates.set_rows([KeyDateRow(**r) for r in keydates.get("n", [])])
    c.u_keydates.set_rows([KeyDateRow(**r) for r in keydates.get("u", [])])


# ---- what goes into a draft ----
def snapshot(c: CaptureWindow) -> tuple[dict[str, Any], list[tuple[str, Callable[[Any], None]]]]:
    """The window as a draft: draft.json's data, and each file to write beside it, as (its name in the folder, a function
    that writes it to a path). A file already in the folder isn't written again."""
    c._file_rows()  # the description boxes into the rows
    data = c._draft_data()
    data.update(from_capture=c.from_capture, today=c.today_on, note_auto=c.note_auto, touched=sorted(c.touched), item_ov=c.item_ov,
                agenda_ticks={str(k): v for k, v in c.agenda_ticks.items()}, form=form_of(c))
    fs = c.ctx.fs
    writes: list[tuple[str, Callable[[Any], None]]] = []
    emails: list[EmailItem] = []
    rows: list[dict[str, Any]] = []
    email_parts: dict[int, int] = {}
    for n, e in enumerate(c.files, 1):
        row = e.row
        if row.email is not None:
            i = len(emails)
            emails.append(row.email)
            rows.append({"kind": "email", "name": row.name, "email": i, "description": row.description, "src": e.src})
            continue
        if row.of is not None:
            i = next((k for k, x in enumerate(emails) if x is row.of), None)
            if i is None:
                continue
            j = email_parts.get(i, 0)
            email_parts[i] = j + 1
            rows.append({"kind": "part", "part_of_email": i, "n": j, "name": row.name, "keep": row.keep, "description": row.description,
                         "save_a_copy": row.save_a_copy, "extract": row.extract})
            continue
        record: dict[str, Any] = {"kind": "file", "name": row.name, "path": row.path, "description": row.description,
                                  "save_a_copy": row.save_a_copy, "extract": row.extract, "keep": row.keep, "section": row.section,
                                  "src": e.src, "line": e.line, "stored": None, "part": None}
        part = row.part
        if part is not None and part.attachment is not None:
            a = part.attachment
            record["part"] = {"kind": part.kind, "name": part.name, "size": part.size, "pasted": part.pasted}
            if part.pasted and part.kind == "picture" and a.save is not None:
                stored = f"files/{n} {_safe(row.name)}"
                if not stored.lower().endswith(".png"):
                    stored += ".png"
                record["stored"] = stored
                writes.append((stored, a.save))  # through SafeFS.write_picture, as the capture's own save does
            elif a.data is not None:
                stored = f"files/{n} {_safe(row.name)}"
                record["stored"] = stored
                writes.append((stored, lambda target, d=a.data: fs.write_copy(target, d)))
        rows.append(record)
    data["emails"] = []
    for i, email in enumerate(emails, 1):
        record = {k: getattr(email, k) for k in EMAIL_FIELDS}
        record["refused"] = list(email.refused)
        record["stored"] = None
        if email.msg_bytes is not None:
            record["stored"] = f"emails/{i}.msg"
            writes.append((record["stored"], lambda target, d=email.msg_bytes: fs.write_copy(target, d)))
        elif email.save_msg is not None:
            record["stored"] = f"emails/{i}.msg"
            writes.append((record["stored"], lambda target, s=email.save_msg: s(fs.checked_path(target))))
        data["emails"].append(record)
    data["files"] = rows
    return data, writes


def _safe(name: str) -> str:
    """A file's name as it can be written in a draft's folder."""
    out = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in name).strip(" .")
    return out[:100] or "file"


# ---- and back out ----
def restore_files(c: CaptureWindow, draft_id: str, data: dict[str, Any]) -> list[str]:
    """Each of a draft's files, back in the window. Returns the names of those that couldn't come back."""
    root = c.ctx.data_root
    lost: list[str] = []
    emails: dict[int, EmailItem] = {}
    for i, record in enumerate(data.get("emails") or []):
        email = None
        stored = record.get("stored")
        raw = drafts.file_bytes(root, draft_id, stored) if stored else None
        if raw is not None:
            try:
                email = msg.read(raw)
            except msg.MsgError:
                email = None
        if email is None:  # its .msg can't be read without Outlook, or there was none to keep: as its fields said
            email = EmailItem(**{k: str(record.get(k) or "") for k in ("subject", "sender", "sent", "to", "body")}, html=str(record.get("html") or ""),
                              refused=tuple(record.get("refused") or ()), msg_bytes=raw)
            if stored and raw is None:
                lost.append(f"{email.subject or 'an email'}'s .msg file")
        email.entry_id = str(record.get("entry_id") or "")
        email.store_id = str(record.get("store_id") or "")
        emails[i] = email
    parts = [r for r in data.get("files") or [] if isinstance(r, dict) and r.get("kind") == "part"]
    for record in data.get("files") or []:
        if not isinstance(record, dict):
            continue
        kind = record.get("kind")
        if kind == "part":
            continue  # with its email
        if kind == "email":
            email = emails.get(int(record.get("email") or 0))
            if email is None:
                continue
            rows = email_rows(email)
            rows[0].description = str(record.get("description") or "")
            mine = [p for p in parts if p.get("part_of_email") == record.get("email")]
            for j, row in enumerate(rows[1:]):
                # By its name, else by its place: the email read again from its .msg gives the same parts.
                p = next((x for x in mine if x.get("name") == row.name), None) or next((x for x in mine if int(x.get("n") or 0) == j), None)
                if p is not None:
                    mine.remove(p)
                    row.keep, row.description = bool(p.get("keep")), str(p.get("description") or "")
                    row.save_a_copy, row.extract = bool(p.get("save_a_copy")), bool(p.get("extract"))
            for row in rows:
                c._add_file(row, str(record.get("src") or "outlook") if row.email else "email", focus=False)
                _fill(c, row)
            continue
        part = None
        p = record.get("part")
        if isinstance(p, dict):
            stored = record.get("stored")
            raw = drafts.file_bytes(root, draft_id, stored) if stored else None
            if raw is None:
                lost.append(str(record.get("name") or "a file"))
                continue
            if p.get("pasted"):
                fs = c.ctx.fs
                a = Attachment(str(p.get("name") or record.get("name")), save=lambda target, d=raw: fs.write_picture(target, d), size=len(raw))
            else:
                a = Attachment(str(p.get("name") or record.get("name")), size=len(raw), data=raw)
            part = Part(str(p.get("kind") or "attachment"), str(p.get("name") or record.get("name")), attachment=a, size=len(raw), pasted=bool(p.get("pasted")))
        row = FileRow(str(record.get("name") or ""), record.get("path"), description=str(record.get("description") or ""),
                      save_a_copy=bool(record.get("save_a_copy")), extract=bool(record.get("extract")), part=part,
                      keep=bool(record.get("keep", True)), section=record.get("section"))
        c._add_file(row, str(record.get("src") or "dropped"), line=record.get("line"), focus=False)
        _fill(c, row)
    return lost


def _fill(c: CaptureWindow, row: FileRow) -> None:
    """A row's description and choices, back in its widgets."""
    entry = next((e for e in c.files if e.row is row), None)
    if entry is None:
        return
    if entry.desc is not None:
        entry.desc.setText(row.description)
    if entry.email_desc is not None:
        entry.email_desc.setText(row.description)
    if entry.copy is not None:
        entry.copy.setChecked(row.save_a_copy)
    if entry.extract is not None:
        entry.extract.setChecked(row.extract)


# ---- the footer's list ----
class DraftsList(QFrame):
    """The Drafts button's list (decision 335): each draft's first words, its task, its files and when it changed. A click
    opens it; × discards it, with Undo in the footer."""

    def __init__(self, parent: QWidget, items: list[drafts.Draft], task_name: Callable[[str | None], str], today: date,
                 opened: Callable[[str], None], discarded: Callable[[str], None]) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("draftsList")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        head = QLabel("<b>Drafts</b>")
        lay.addWidget(head)
        sub = QLabel("Captures closed before they were saved, kept until you save or discard them.", objectName="hint")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.rows: list[tuple[QPushButton, QToolButton]] = []
        self.texts: list[str] = []  # what each row says, its two lines
        for d in items:
            line = QHBoxLayout()
            line.setSpacing(4)
            n = d.file_count()
            files = f"{n} file{'s' if n != 1 else ''}" if n else "no files"
            task = task_name(d.data.get("task")) or ("Meeting notes" if d.data.get("meeting") else "No task")
            when = d.when(today)
            # A two-line row (the playbook's 48 px, Body over Caption): its words, then its task, files and when it changed.
            open_ = QPushButton(objectName="subtle")
            open_.setToolTip("Open this draft")
            open_.setAccessibleName(f"Open the draft {d.words()}")
            inner = QVBoxLayout(open_)
            inner.setContentsMargins(8, 4, 8, 4)
            inner.setSpacing(0)
            lines = (d.words(), f"{task} · {files}" + (f" · changed {when}" if when else ""))
            for text, name in zip(lines, ("draftWords", "hint")):
                label = QLabel(text, objectName=name)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                inner.addWidget(label)
            self.texts.append("\n".join(lines))
            # At least 48 px, as tall as its two lines: in its own style sheet, as the look's sets every button's height.
            open_.setStyleSheet(f"QPushButton {{ min-height: {max(48, inner.sizeHint().height() + 8)}px; padding: 0px; }}")
            open_.clicked.connect(lambda _=False, i=d.id: (self.close(), opened(i)))
            x = QToolButton()
            x.setIcon(icon("close"))
            x.setToolTip("Discard this draft")
            x.setAccessibleName(f"Discard the draft {d.words()}")
            x.clicked.connect(lambda _=False, i=d.id: (self.close(), discarded(i)))
            line.addWidget(open_, 1)
            line.addWidget(x)
            lay.addLayout(line)
            self.rows.append((open_, x))
        self.setMinimumWidth(360)

    def show_at(self, button: QWidget) -> None:
        """Above the button, as the footer is the window's last row."""
        self.adjustSize()
        at = button.mapToGlobal(QPoint(0, 0))
        self.move(at.x(), at.y() - self.height() - 4)
        self.show()
        if self.rows:
            self.rows[0][0].setFocus()
