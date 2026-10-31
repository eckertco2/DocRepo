"""The Capture wheel's blank capture, with a draft set aside (release 5.41; the wheel design's decision 215).

A blank capture has to be truly blank, and you shouldn't lose what you had: the draft goes to a second file, in the same
form as the draft file with the rest of the form beside it, and comes back when the blank one is saved, or closed with
nothing typed. Only one is held. A restart keeps it, but not its files, as a restart doesn't keep the draft's own files.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrepo.tasks import KeyDateRow
from docrepo.ui.widgets import Chip

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow

log = logging.getLogger(__name__)

ASIDE_FILE = Path("System") / "capture-draft-aside.json"
ASIDE_NOTE = "Your draft is set aside. It comes back when you save or close this one."
#: The form's fields, by kind, beyond what the draft file keeps.
TEXTS = ("n_deadline_desc", "u_deadline_desc", "n_lead_hours", "n_asg_hours", "u_lead_hours", "u_asg_hours")
PLAIN = ("summary", "u_status")
DATES = ("n_due", "n_deadline", "n_reminder", "n_repeat", "n_start", "u_due", "u_deadline", "u_start", "u_reminder", "u_repeat")
CHIPS = ("n_labels", "n_leads", "n_assignees", "u_leads", "u_assignees", "agenda")
TICKS = ("n_urgent", "n_meeting", "n_plant", "u_urgent", "u_meeting", "u_plant", "n_inherit", "same_all")
COMBOS = ("n_state", "n_recurrence", "u_state", "u_recurrence")


class DraftAside:
    """The one draft held aside for a capture window."""

    def __init__(self, capture: CaptureWindow) -> None:
        self.capture = capture
        self.data: dict[str, Any] | None = None
        self.rows: list[tuple] = []  # its files, as (row, src, line): kept only while DocRepo runs
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict) and str(data.get("content") or "").strip() or isinstance(data, dict) and data.get("title"):
            self.data = data

    @property
    def path(self) -> Path:
        return self.capture.ctx.data_root / ASIDE_FILE

    def holds_draft(self) -> bool:
        """Whether the window holds something worth keeping: words or files. A task picked and nothing else isn't."""
        c = self.capture
        return bool(c.content.value()[0].strip() or c.title.text().strip() or c.files or c.meeting_on or c.from_capture)

    def _form(self) -> dict[str, Any]:
        c = self.capture
        return {
            "texts": {n: getattr(c, n).text() for n in TEXTS},
            "plain": {n: getattr(c, n).toPlainText() for n in PLAIN},
            "dates": {n: getattr(c, n).value() for n in DATES},
            "chips": {n: [[x.value, x.label, x.new] for x in getattr(c, n).chips()] for n in CHIPS},
            "ticks": {n: getattr(c, n).isChecked() for n in TICKS},
            "combos": {n: getattr(c, n).currentText() for n in COMBOS},
            "refs": {"n": {k: b.text() for k, b in c.n_refs.items()}, "u": {k: b.text() for k, b in c.u_refs.items()}},
            "keydates": {"n": [asdict(r) for r in c.n_keydates.rows()], "u": [asdict(r) for r in c.u_keydates.rows()]},
        }

    def _restore_form(self, form: dict[str, Any]) -> None:
        c = self.capture
        for n, v in form.get("texts", {}).items():
            getattr(c, n).setText(str(v or ""))
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

    def set_aside(self) -> None:
        """The draft goes to the second file and the window is blank. If the file can't be written, the draft stays in
        memory, so it still comes back, and the log says so."""
        c = self.capture
        data = c._draft_data()
        pinned = c.pinned and c.pin_window is not None and c.pin_window.isVisible()
        data.update(from_capture=c.from_capture, today=c.today_on, note_auto=c.note_auto, touched=sorted(c.touched), pinned=pinned,
                    item_ov=c.item_ov, agenda_ticks={str(k): v for k, v in c.agenda_ticks.items()},
                    file_names=[e.row.name for e in c.files if e.row.of is None], form=self._form())
        self.data = data
        self.rows = [(e.row, e.src, e.line) for e in c.files]
        try:
            c.ctx.fs.write_text(self.path, json.dumps(data, ensure_ascii=False, indent=1))
        except (OSError, TypeError) as e:
            log.warning("the draft set aside wasn't written to its file: %s", type(e).__name__)
        c.reset_draft()
        c.forget_draft()
        log.info("a draft was set aside")

    def bring_back(self) -> None:
        """Back in the window, saying so; in the pinned window if that's where it was."""
        data, rows = self.data, self.rows
        if data is None:
            return
        self.data, self.rows = None, []
        try:
            self.capture.ctx.fs.write_text(self.path, "{}")
        except OSError as e:
            log.warning("the draft set aside wasn't emptied from its file: %s", type(e).__name__)
        c = self.capture
        c.reset_draft()
        c._apply_draft({**data, "content": str(data.get("content") or "")})
        c._setting = True
        self._restore_form(data.get("form") or {})
        c.today_on = bool(data.get("today"))
        c.note_auto = bool(data.get("note_auto"))
        c.touched = set(data.get("touched") or [])
        c.item_ov = dict(data.get("item_ov") or {})
        c.agenda_ticks = {int(k): bool(v) for k, v in (data.get("agenda_ticks") or {}).items()}
        c.from_capture = data.get("from_capture")
        c._setting = False
        for row, src, line in rows:
            c._add_file(row, src, line=line, focus=False)
        lost = data.get("file_names") if not rows else None
        c.draft_dirty = True
        c.keep_draft()
        c.draft_label.setText(f"Your draft came back. A restart lost its files: add {', '.join(lost)} again." if lost else "Your draft came back.")
        c.refresh()
        c.read_items()
        log.info("the draft set aside came back")
        if data.get("pinned"):
            c.pin()

    def window_hidden(self) -> None:
        """Saving, or hiding the blank capture with nothing typed, brings the draft back."""
        if self.data is not None and not self.capture.pinned and not self.holds_draft():
            self.bring_back()
