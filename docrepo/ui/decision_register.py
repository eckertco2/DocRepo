"""The Decisions section's Copy on the task page (release 5.124; the design workspace's ``docs/mods/cold-eyes-plan.md``,
decision 479). A function of the browse window ``w``, as a page's commands are (``DocRepo/CLAUDE.md``); ``BrowseWindow``
only calls it.

**Copy** (``copydecisions:<task>``) puts the decision register on the clipboard: every decision on the task and the
tasks under it (the page's scope), newest first, as a table of Date, Decision, Task and Where. It goes in two forms at
once, so it pastes as a table wherever it lands: rich text (HTML) for an email or a document, and Markdown as its plain
text, for a Markdown file or a chat. The rows are ``docrepo.decisions``', the same as Task.md's Decisions table.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication

from docrepo import decisions

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

LINK = "copydecisions"


def mime(table: list[tuple[str, ...]]) -> QMimeData:
    """The register as the clipboard holds it: its HTML, and its Markdown as the text."""
    data = QMimeData()
    data.setHtml(decisions.html(table))
    data.setText(decisions.markdown(table))
    return data


def copy(w: BrowseWindow, task_id: str) -> None:
    """Copy a task's decision register, and say how many rows it holds."""
    if task_id not in w.model().tasks:
        return
    table = w.pages().decision_register(task_id, w.state.scope)
    if not table:
        w.say("There are no decisions to copy.")
        return
    QGuiApplication.clipboard().setMimeData(mime(table))
    n = len(table)
    w.say(f"Copied the decision register: {n} decision{'s' if n != 1 else ''}, as a table.")
