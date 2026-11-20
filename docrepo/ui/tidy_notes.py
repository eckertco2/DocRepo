"""Tidy the notes (release 5.150, the design workspace's notes syntax plan, decision 656): the lines older notes pages keep
as they were typed, operators and all, written as release 5.150 writes them, with a preview first and one Undo after. On
the task page's More menu it's that page; from the command palette, that page or every page.

A module of its own (release 5.95, the review's F11): a function of the browse window, its dialog, and the model.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from docrepo import edits, markup, notes_page, page_lines
from docrepo.model import Model

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: What the command is called, on the page's More menu and in the command palette.
NAME = "Tidy the notes…"
#: A list item's marker, which a row of the preview leaves out.
_MARKER = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
#: The palette's command for every page.
EVERY = "Tidy the notes of every page…"


def line_words(line: str) -> str:
    """A page line in words, as the page shows it: a change line's words and what it did, a task line's words, text
    without its marks."""
    x = notes_page.read_line(line)
    if x.kind in ("change", "set"):
        return notes_page.DOT.join(w for w in (x.text, x.did) if w)
    if x.kind == "text":
        return _MARKER.sub("", " ".join(markup.to_plain(x.text).split()))
    return x.text


def row_words(m: Model, t: page_lines.TidyLine, page_name: bool = False) -> str:
    """A change in words: "#Rigging plan **due, 30 Nov **lead, Tom → Rigging plan · Due Mon 30 Nov · Lead Tom Becker", the
    page's name first when several pages are listed."""
    before = " / ".join(w for w in (line_words(x) for x in t.before) if w)
    after = " / ".join(w for w in (line_words(x) for x in t.after) if w)
    head = f"{m.task(t.task).title}: " if page_name and t.task in m.tasks else ""
    return f"{head}{before}  →  {after}"


def has_typed_operators(page: str) -> bool:
    """Whether a page may hold lines Tidy would change, by a quick look: an operator's ``**`` or an ``@`` in its words. The
    More menu offers Tidy only then, so opening the menu reads no captures."""
    return "\\*\\*" in page or "**" in page or "@" in page


class TidyNotesDialog(QDialog):
    """The preview: each line with what it becomes, ticked; Tidy changes the ticked ones."""

    def __init__(self, parent: QWidget | None, m: Model, lines: list[page_lines.TidyLine]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tidy the notes")
        self.lines = lines
        lay = QVBoxLayout(self)
        n = len(lines)
        several = len({t.task for t in lines}) > 1
        lay.addWidget(QLabel(f"{n} line{'s' if n != 1 else ''} on {'these pages' if several else 'this page'} still "
                             f"{'show' if n != 1 else 'shows'} the operators {'they were' if n != 1 else 'it was'} typed with. Tidy writes each as "
                             "the notes do now: its words, then what it did. The captures keep the words as typed. Untick any to leave.",
                             wordWrap=True))
        self.rows = QListWidget()
        self.rows.setAccessibleName("Lines to tidy")
        self.rows.setWordWrap(True)
        self.rows.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for t in lines:
            it = QListWidgetItem(row_words(m, t, several))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.rows.addItem(it)
        lay.addWidget(self.rows, 1)
        buttons = QHBoxLayout()  # Tidy at the right end, as a form's primary (release 5.193); Windows' button box put it first
        buttons.addStretch()
        self.tidy_button = QPushButton("Tidy")
        self.tidy_button.setDefault(True)
        self.tidy_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addWidget(self.tidy_button)
        lay.addLayout(buttons)
        QWidget.setTabOrder(self.tidy_button, cancel)
        self.resize(760, min(560, 170 + 30 * n))

    def chosen(self) -> list[page_lines.TidyLine]:
        return [t for i, t in enumerate(self.lines) if self.rows.item(i).checkState() == Qt.CheckState.Checked]


def candidates(browse: BrowseWindow, task_id: str | None) -> list[page_lines.TidyLine]:
    """The lines to tidy on a task's page, or with None on every page."""
    m, stories = edits.stories_for(browse.conn, browse.ctx.data_root, browse._now(), browse.model(), browse.ctx.settings)
    ids = [task_id] if task_id else [t.id for t in m.tasks.values() if not t.discarded and has_typed_operators(m.pages.get(t.id, ""))]
    return edits.notes_to_tidy(m, stories, ids)


def run(browse: BrowseWindow, task_id: str | None) -> bool:
    """Tidy on a task's page (or, with None, every page): the preview, then the change, said with Undo for ten seconds.
    True when something changed."""
    browse.save_open_notes()  # typing not yet saved goes first, so the pages are read as they are
    lines = candidates(browse, task_id)
    if not lines:
        browse.say("Nothing to tidy: every line here is written as the notes write it now." if task_id
                   else "Nothing to tidy on any page.")
        return False
    dialog = TidyNotesDialog(browse, browse.model(), lines)
    if not browse.run_dialog(dialog):
        return False
    chosen = dialog.chosen()
    if not chosen:
        browse.say("Nothing ticked, so nothing changed.")
        return False
    conn, ctx = browse.conn, browse.ctx
    done = browse._do(lambda: edits.tidy_notes(conn, ctx.data_root, ctx.fs, chosen, browse._now()))
    if not isinstance(done, tuple):
        return False
    out, undo = done
    undone: list[bool] = []

    def back() -> None:
        if not undone:
            undone.append(True)
            browse._do(lambda: edits.undo_tidy_notes(conn, ctx.data_root, ctx.fs, undo, browse._now()))
            browse.render_detail(keep_scroll=True)

    browse.say_undo(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), back)
    browse.render_detail(keep_scroll=True)
    return True
