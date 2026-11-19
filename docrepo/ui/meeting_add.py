"""Add summary… and Add transcript… on a meeting's page and in its workspace (release 5.170, the design workspace's
``docs/mods/discussions-plan.md``, decision 798): a summary from Zoom, or a recording's transcript, arrives after the
meeting, so each has a box to paste into. What it does is ``docrepo/transcripts.py``'s.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from docrepo import transcripts

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: Asks for the text: (parent, title, what to paste, the text it starts with) to the text, or None when cancelled. Tests
#: replace it.
ASK: Callable[[QWidget, str, str, str], str | None] | None = None


def ask_text(parent: QWidget, title: str, hint: str, text: str = "") -> str | None:
    """A box to paste into, with Save and Cancel. The text, or None when cancelled."""
    if ASK is not None:
        return ASK(parent, title, hint, text)
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(640, 460)
    lay = QVBoxLayout(dialog)
    note = QLabel(hint, objectName="hint")
    note.setWordWrap(True)
    lay.addWidget(note)
    box = QPlainTextEdit()
    box.setPlainText(text)
    lay.addWidget(box, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    lay.addWidget(buttons)
    box.setFocus()
    return box.toPlainText() if dialog.exec() == QDialog.DialogCode.Accepted else None


def add_summary(w: BrowseWindow, task_id: str) -> None:
    """Add summary… (Edit summary… once there's one): the summary of the meeting's newest notes."""
    m = w.model()
    if task_id not in m.tasks:
        return
    now = transcripts.summaries(m, task_id)
    text = ask_text(w, f"Summary of {m.task(task_id).title}", "Paste the summary: from the call's own summary, or one made from "
                    "the transcript and the notes. It's kept as text, and nothing in it is acted on.", now[0][1] if now else "")
    if text is None:
        return
    out = transcripts.set_summary(w.conn, w.ctx.data_root, w.ctx.fs, task_id, text, w.ctx.now(), settings=w.ctx.settings)
    w.say(" ".join([out.message, *out.problems]), bool(out.problems))
    w.refresh()


def add_transcript(w: BrowseWindow, task_id: str) -> None:
    """Add transcript…: a new transcript file of the meeting's, never over one that's there."""
    m = w.model()
    if task_id not in m.tasks:
        return
    text = ask_text(w, f"Transcript of {m.task(task_id).title}", "Paste the transcript. It's kept whole, as a file in the "
                    "meeting's Files (transcript.md, or transcript-2.md when there's one), searched, and never put on the notes page.")
    if text is None or not text.strip():
        return
    out = transcripts.add_later(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, task_id, text, w.ctx.now())
    w.say(" ".join([out.message, *out.problems]), bool(out.problems))
    w.refresh()
