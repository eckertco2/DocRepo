"""The key map (mods log round 2, M0036): one letter per topic everywhere. In the browse tool the letter alone acts on the
selected task, in the capture window it's Alt and the letter, and as a global hotkey it's Ctrl+Shift and the letter, once
set in Settings. F1 shows it in either window. Ported from the browse tool mockup's ``keys.js``."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from docrepo.detail import CSS, esc
from docrepo.ui.style import STYLE

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
    ("P", "Parse", "", "", "Alt+P runs Parse and populate"),
    ("M", "Meeting notes", "", "Meeting notes for the selected task: its meeting, or a new one under it", "Alt+M turns meeting notes on or off"),
)
OTHER_KEYS = (
    ("Ctrl+Shift+Space", "Opens the capture window (the main hotkey)"),
    ("Ctrl+Enter", "Saves: the capture window, the mods log and every form"),
    ("Esc", "Hides the capture window, closes a form (asking first if you changed something), or clears Find"),
    ("F11", "Expands the capture window's content text"),
    ("Ctrl+B", "Hides the views on the left of the browse tool"),
    ("F5", "Reads docs.db again"),
    ("F1", "This list"),
)


def key_map_html(main_hotkey: str = "Ctrl+Shift+Space") -> str:
    """The key map as HTML: the letters, then the other keys."""
    def cell(text: str) -> str:
        return f"<td>{esc(text) or '–'}</td>"

    rows = "".join(f"<tr><td><b>{k}</b></td>{cell(topic)}{cell(g)}{cell(b)}{cell(c)}</tr>" for k, topic, g, b, c in KEY_MAP)
    other = "".join(f"<tr><td><b>{esc(main_hotkey if k == 'Ctrl+Shift+Space' else k)}</b></td><td>{esc(w)}</td></tr>" for k, w in OTHER_KEYS)
    return ("<p class='note'>One letter per topic. In the browse tool the letter alone acts on the selected task (not while you type in "
            "a box); in the capture window it's Alt and the letter; anywhere in Windows it's Ctrl+Shift and the letter, once you set "
            "it in Settings. While DocRepo runs, a global hotkey is taken from other programs, such as Outlook's Ctrl+Shift+N for a new note.</p>"
            "<table cellspacing='0' cellpadding='4' width='100%'><tr><th align='left'>Key</th><th align='left'>Topic</th>"
            "<th align='left'>Global hotkey</th><th align='left'>Browse tool</th><th align='left'>Capture window</th></tr>"
            f"{rows}</table><p></p><table cellspacing='0' cellpadding='4'>{other}</table>")


class KeyMapDialog(QDialog):
    """Every key, in one list (F1)."""

    def __init__(self, parent: QWidget | None, main_hotkey: str = "Ctrl+Shift+Space") -> None:
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.setObjectName("capture")
        self.setStyleSheet(STYLE)
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        page = QTextBrowser()
        page.document().setDefaultStyleSheet(CSS)
        page.setHtml(key_map_html(main_hotkey))
        lay.addWidget(page, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close", objectName="primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        QShortcut(QKeySequence("F1"), self, self.accept)
