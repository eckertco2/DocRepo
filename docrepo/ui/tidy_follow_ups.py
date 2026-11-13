"""Tidy (release 5.142, the design workspace's notes consolidation plan, decision 612): the follow-ups older Meeting notes
left under their meetings, moved to the work, with a preview first and one Undo after. On a meeting's page it's that
meeting; on another task's page, the meetings under it; from the command palette, every meeting.

A module of its own (release 5.95, the review's F11): a function of the browse window, its dialog, and the model.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from docrepo import edits
from docrepo.model import Model

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: What the command is called, on the page's More menu and in the command palette.
NAME = "Move follow-ups out of meetings…"


def row_words(m: Model, mv: edits.Tidy) -> str:
    """A move in words: "Fill media order: out of Cooling tower kickoff, under Cooling tower 2 rebuild"."""
    under = " and ".join(m.task(p).title for p in mv.parents if p in m.tasks)
    return f"{m.task(mv.task).title}: out of {m.task(mv.meeting).title}" + (f", under {under}" if under else ", a top-level task")


class TidyDialog(QDialog):
    """The preview: each follow-up with where it goes, ticked; Move moves the ticked ones."""

    def __init__(self, parent: QWidget | None, m: Model, moves: list[edits.Tidy]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move follow-ups out of meetings")
        self.moves = moves
        lay = QVBoxLayout(self)
        n = len(moves)
        lay.addWidget(QLabel(f"{n} task{'s' if n != 1 else ''} made in meeting notes {'are' if n != 1 else 'is'} still under the meeting. "
                             "Move takes the meeting off as a parent and puts each under the meeting's task, unless it's under "
                             "other work already. The meeting still lists them as Follow-ups. Untick any to leave.", wordWrap=True))
        self.rows = QListWidget()
        self.rows.setAccessibleName("Follow-ups to move")
        self.rows.setWordWrap(True)  # a long title and its meeting wrap, rather than scrolling sideways
        self.rows.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for mv in moves:
            it = QListWidgetItem(row_words(m, mv))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.rows.addItem(it)
        lay.addWidget(self.rows, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.move_button = buttons.addButton("Move", QDialogButtonBox.ButtonRole.AcceptRole)
        self.move_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(720, min(560, 170 + 30 * n))

    def chosen(self) -> list[edits.Tidy]:
        return [mv for i, mv in enumerate(self.moves) if self.rows.item(i).checkState() == Qt.CheckState.Checked]


def candidates(browse: BrowseWindow, task_id: str | None) -> list[edits.Tidy]:
    m = browse.model()
    return edits.follow_ups_to_tidy(m, edits.meetings_in(m, task_id))


def run(browse: BrowseWindow, task_id: str | None) -> bool:
    """Tidy on a task (or, with None, every meeting): the preview, then the move, said with Undo for ten seconds. True
    when something moved."""
    moves = candidates(browse, task_id)
    if not moves:
        browse.say("No follow-ups are under their meetings here.")
        return False
    dialog = TidyDialog(browse, browse.model(), moves)
    if not browse.run_dialog(dialog):
        return False
    chosen = dialog.chosen()
    if not chosen:
        browse.say("Nothing ticked, so nothing moved.")
        return False
    conn, ctx = browse.conn, browse.ctx
    done = browse._do(lambda: edits.tidy_follow_ups(conn, ctx.data_root, ctx.fs, chosen, browse._now()))
    if not isinstance(done, tuple):
        return False
    out, undo = done
    undone: list[bool] = []

    def back() -> None:
        if not undone:
            undone.append(True)
            browse._do(lambda: edits.undo_tidy(conn, ctx.data_root, ctx.fs, undo, browse._now()))

    browse.say_undo(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), back)
    browse.render_detail(keep_scroll=True)
    return True
