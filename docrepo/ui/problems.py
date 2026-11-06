"""Problems you can see (release 5.91, the review of 2026-11-06, F12): what went wrong with the last save stays in view.

A save can succeed and still have problems: a copy that failed, an email not marked in Outlook, a file whose text
couldn't be read. Until release 5.91 they were only in a tray balloon, gone in six seconds. Now the capture window's
footer and the browse window's status line each have a **Problems line**, "2 problems with the last save", that stays
until it's clicked. The click opens a list of them, with Show in File Explorer for the capture's folder. The balloon
stays as well, and the log has each, as before. The session's problems are kept in memory (``ProblemLog``); nothing is
written for them.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget


@dataclass
class Problems:
    """One save's problems: when, what was saved, and where its files are, if it has a folder."""

    at: datetime
    what: str
    problems: list[str]
    folder: Path | None = None

    def words(self) -> str:
        n = len(self.problems)
        return f"{n} problem{'s' if n != 1 else ''} with the last save"


@dataclass
class ProblemLog:
    """This session's saves that had problems, the newest last. The Problems lines show the newest until it's seen."""

    saves: list[Problems] = field(default_factory=list)
    seen: int = 0  # how many of ``saves`` have been opened from a Problems line

    def add(self, p: Problems) -> None:
        if p.problems:
            self.saves.append(p)

    @property
    def unseen(self) -> Problems | None:
        return self.saves[-1] if len(self.saves) > self.seen else None

    def mark_seen(self) -> None:
        self.seen = len(self.saves)


class ProblemsDialog(QDialog):
    """The last save's problems, one a line, with Show in File Explorer when the save has a folder."""

    def __init__(self, parent: QWidget | None, p: Problems, reveal: Callable[[Path], bool]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Problems with the last save")
        self.resize(560, 320)
        lay = QVBoxLayout(self)
        intro = QLabel(f"Saved at {p.at:%H:%M}: {p.what} It was saved; these parts of it weren't. Each is in DocRepo's log too.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        self.list.addItems(p.problems)
        self.list.setWordWrap(True)
        lay.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        if p.folder is not None:
            show = QPushButton("Show in File Explorer")
            show.setToolTip(f"The capture's folder: {p.folder}")
            show.clicked.connect(lambda: reveal(p.folder))
            buttons.addWidget(show)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        lay.addLayout(buttons)


class ProblemsLine(QPushButton):
    """"2 problems with the last save", as a link, hidden until a save has some, and until it's clicked after that."""

    def __init__(self, log: ProblemLog, reveal: Callable[[Path], bool], parent: QWidget | None = None) -> None:
        super().__init__("", parent, objectName="link")
        self.log, self.reveal = log, reveal
        self.setFlat(True)
        self.setToolTip("Open the list of what went wrong")
        self.clicked.connect(self.open)
        self.hide()
        self.last_dialog: ProblemsDialog | None = None
        self.show_dialogs = True  # tests look at the dialog without opening it

    def refresh(self) -> None:
        """Show the newest save's problems, unless they've been opened already."""
        p = self.log.unseen
        self.setText(p.words() if p else "")
        self.setVisible(p is not None)

    def open(self) -> None:
        p = self.log.unseen or (self.log.saves[-1] if self.log.saves else None)
        if p is None:
            return
        self.log.mark_seen()
        self.refresh()
        self.last_dialog = ProblemsDialog(self.window(), p, self.reveal)
        if self.show_dialogs:
            self.last_dialog.exec()
