"""The key map (mods log round 2, M0036): one letter per topic everywhere. In the browse tool the letter alone acts on the
selected task, in the capture window it's Alt and the letter, and as a global hotkey it's Ctrl+Shift and the letter, once
set in Settings. F1 shows it in either window. Ported from the browse tool mockup's ``keys.js``."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from docrepo.detail import esc
from docrepo.ui.style import page_css, style_sheet

#: Each letter: its topic, then what it does as a global hotkey, in the browse tool and in the capture window.
KEY_MAP = (
    ("T", "New task", "Ctrl+Shift+T opens the capture window on New task", "A new subtask of the selected task", "Alt+T ticks New task"),
    ("N", "Note", "Ctrl+Shift+N, on Note", "A note on the selected task", "Alt+N ticks Note"),
    ("U", "Update", "Ctrl+Shift+U, on Update (the task picker first)", "Update the selected task", "Alt+U ticks Update"),
    ("A", "Agenda", "Ctrl+Shift+A, in the agenda picker", "Put the selected task on an agenda", "Alt+A goes to the agenda picker"),
    ("D", "Today (do)", "Ctrl+Shift+D, a quick task on Today", "Put the selected task on Today", "Alt+D puts it on Today, or takes it off"),
    ("E", "Edit", "", "Edit task", ""),
    ("F", "Find", "", "Ctrl+F finds in this view; Ctrl+Shift+F searches everything", ""),
    ("B", "Browse tool", "Ctrl+Shift+B shows it", "", ""),
    ("P", "Parse, Plan", "", "On the timeline: Plan mode, to drag dates (Ctrl+Z undoes a drop)", "Alt+P runs Parse and populate"),
    ("M", "Meeting notes", "", "Meeting notes for the selected task: its meeting, or a new one under it", "Alt+M turns meeting notes on or off"),
    ("O", "Open (Task view)", "", "The selected task's Task view: a window of its own for finding and opening its files", ""),
)
OTHER_KEYS = (
    ("Ctrl+Shift+Space", "Opens the capture window (the main hotkey)"),
    ("Ctrl+Enter", "Saves: the capture window, the mods log and every form"),
    ("Esc", "Hides the capture window, closes a form (asking first if you changed something), or clears Find"),
    ("F11", "Expands the capture window's content text"),
    ("F12", "Pins the capture window at the bottom right, to drop files, emails and links on; the main hotkey brings it back"),
    ("Ctrl+B", "Hides the views on the left of the browse tool"),
    ("F5", "Reads docs.db again"),
    ("Ctrl+K", "The command palette: every action and view, narrowed as you type"),
    ("Alt, held", "Shows each control's letter key in the window"),
    ("Ctrl, held", "Shows the Ctrl shortcuts in the window, after half a second"),
    ("1 to 4, 0", "On the Priorities board: puts the selected card in Critical, High, Medium or Parking lot, or takes it out (0)"),
    ("Alt+Up, Alt+Down", "On the Priorities board: moves the selected card up or down in its bucket. The arrow keys move between cards; "
                         "Enter opens the task"),
    ("F1", "This list"),
)
#: The Task view's keys (releases 5.34 and 5.35). The letters above act on its task there too, with Alt from its box.
TASK_VIEW_KEYS = (
    ("Typing", "Searches the task's files, emails, notes and updates, and subtasks; the best match is chosen"),
    ("Up, Down, Page Up, Page Down", "Choose a row (the cursor stays in the box); Ctrl+Up and Ctrl+Down go by group"),
    ("Enter", "Opens the chosen file in its own program (an attachment is shown in File Explorer; a link is copied)"),
    ("Ctrl+Enter", "Shows it in File Explorer"),
    ("Ctrl+Shift+C", "Copies its path (Ctrl+C in the list)"),
    ("P, Alt+P", "Pins or unpins it; Alt+Shift+Up and Alt+Shift+Down move a pinned file"),
    ("Space, Ctrl+Space", "Shows or hides the preview (Space in the list)"),
    ("Ctrl+1 to Ctrl+5", "All, Files, Emails, Notes and updates, Subtasks"),
    ("Ctrl+F, /", "Back to the search box"),
    ("Ctrl+O", "Another task's Task view"),
    ("Alt+Up", "The parent task's Task view"),
    ("F6", "The next pane: the outline, the box, the list, the preview"),
    ("Esc", "Clears what's typed; again, the filters; it never closes the window"),
    ("Ctrl+W", "Closes the Task view"),
)
#: The content text's keys, as OneNote's (mods log round 3, M0055).
EDITOR_KEYS = (
    ("Ctrl+B, Ctrl+I, Ctrl+U", "Bold, italic, underline"),
    ("Ctrl+-", "Strikethrough"),
    ("Ctrl+Alt+H", "Highlight"),
    ("Ctrl+.", "Bulleted list, or type “- ” or “* ” at a line's start"),
    ("Ctrl+/", "Numbered list, or type “1. ”"),
    ("Tab, Shift+Tab", "A list item in or out a level; also Alt+Shift+Right and Alt+Shift+Left"),
    ("Ctrl+Up, Ctrl+Down", "To the paragraph above or below; with Shift, selects as it goes"),
    ("Alt+Shift+Up, Alt+Shift+Down", "Moves the line up or down, with the list items under it"),
    ("Ctrl+Alt+1, 2, 3", "Makes the line a heading at that level, which folds what's under it; Ctrl+Alt+0 makes it text again"),
    ("Alt+Shift+-, Alt+Shift++", "Folds or opens the heading the caret is under; or click the arrow beside it"),
)


def key_map_html(main_hotkey: str = "Ctrl+Shift+Space") -> str:
    """The key map as HTML: the letters, then the other keys."""
    def cell(text: str) -> str:
        return f"<td>{esc(text) or '–'}</td>"

    rows = "".join(f"<tr><td><b>{k}</b></td>{cell(topic)}{cell(g)}{cell(b)}{cell(c)}</tr>" for k, topic, g, b, c in KEY_MAP)
    other = "".join(f"<tr><td><b>{esc(main_hotkey if k == 'Ctrl+Shift+Space' else k)}</b></td><td>{esc(w)}</td></tr>" for k, w in OTHER_KEYS)
    editor = "".join(f"<tr><td><b>{esc(k)}</b></td><td>{esc(w)}</td></tr>" for k, w in EDITOR_KEYS)
    task_view = "".join(f"<tr><td><b>{esc(k)}</b></td><td>{esc(w)}</td></tr>" for k, w in TASK_VIEW_KEYS)
    return ("<p class='note'>One letter per topic. In the browse tool the letter alone acts on the selected task (not while you type in "
            "a box); in the capture window it's Alt and the letter; anywhere in Windows it's Ctrl+Shift and the letter, once you set "
            "it in Settings. While DocRepo runs, a global hotkey is taken from other programs, such as Outlook's Ctrl+Shift+N for a new note.</p>"
            "<table cellspacing='0' cellpadding='4' width='100%'><tr><th align='left'>Key</th><th align='left'>Topic</th>"
            "<th align='left'>Global hotkey</th><th align='left'>Browse tool</th><th align='left'>Capture window</th></tr>"
            f"{rows}</table><p></p><table cellspacing='0' cellpadding='4'>{other}</table>"
            f"<p><b>In the content text</b>, as in OneNote</p><table cellspacing='0' cellpadding='4'>{editor}</table>"
            f"<p><b>In the Task view</b> (O)</p><table cellspacing='0' cellpadding='4'>{task_view}</table>")


class KeyMapDialog(QDialog):
    """Every key, in one list (F1)."""

    def __init__(self, parent: QWidget | None, main_hotkey: str = "Ctrl+Shift+Space") -> None:
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        page = QTextBrowser()
        page.document().setDefaultStyleSheet(page_css())
        page.setHtml(key_map_html(main_hotkey))
        lay.addWidget(page, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close", objectName="primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        QShortcut(QKeySequence("F1"), self, self.accept)
