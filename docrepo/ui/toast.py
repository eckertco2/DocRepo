"""The browse window's message at the bottom (release 5.182, the redesign's decision 853, the status strip goes).

What the browse window says (``BrowseWindow.say`` and ``say_undo``) shows for a few seconds as a small dark card at the
bottom centre of the window, over whatever is there, with Undo on it when there is one. A plain message stays 4 to 9
seconds by its length; one with Undo stays for Undo's ten seconds (decision 363); an error stays, with a close button,
until it's dismissed or the next thing is said. It waits while the pointer is on it. It never takes the keyboard.

No animation yet: release 5.195 (motion) adds the slide, in ``_appear`` and ``_leave``.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon

PLAIN_MS = 4000        # a message of up to 60 characters
PER_CHAR_MS = 50       # each character beyond 60
LONGEST_MS = 9000      # the status line's time until release 5.182; no message stays longer unless it has Undo or is an error
MARGIN = 24            # from the window's bottom edge: 16 px inside the card
MAX_TEXT = 520         # the words' greatest width before they wrap
LEAST_HEIGHT = 40      # the toast's height with one line
SIDE_ROOM = 120        # the window's width the toast leaves at its sides, at the least, before its words wrap
_NO_LIMIT = 16777215   # Qt's QWIDGETSIZE_MAX


def shown_for(text: str) -> int:
    """How long a plain message shows: 4 s up to 60 characters, 50 ms more for each after, at most 9 s."""
    return min(LONGEST_MS, PLAIN_MS + PER_CHAR_MS * max(0, len(text) - 60))


class Toast(QFrame):
    """The browse window's message: at the bottom centre, for a few seconds (release 5.182, decision 853)."""

    closed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 6, 6)
        lay.setSpacing(12)
        self.label = QLabel(objectName="toastText")  # its text format Qt's own guess, as the status line's was
        self.label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.label, 1)
        self.undo = QPushButton("Undo", objectName="toastUndo")
        self.undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo.clicked.connect(self.undo.hide)  # offered once: connected first, so it's gone before the undo runs
        self.undo.hide()
        lay.addWidget(self.undo)
        self.close_button = QToolButton(objectName="toastClose")
        self.close_button.setIcon(icon("close", tokens.colour("critical")))
        self.close_button.setAccessibleName("Dismiss")
        self.close_button.setToolTip("Dismiss")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.dismiss)
        self.close_button.hide()
        lay.addWidget(self.close_button)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.error = False
        parent.installEventFilter(self)
        self.hide()

    # ---- what it says ----
    def say(self, text: str, error: bool = False, undo: bool = False, ms: int | None = None) -> None:
        """Show ``text``: with Undo when ``undo``, until dismissed when ``error``, else for ``ms`` or by its length. An
        empty ``text`` dismisses it."""
        if not text:
            self.dismiss()
            return
        self.label.setText(text)
        self._set_error(error)
        self.undo.setVisible(undo)
        self.close_button.setVisible(error)
        if error:
            self.timer.stop()
        else:
            self.timer.start(ms if ms is not None else shown_for(text))
        self.place()
        self._appear()

    def offers_undo(self) -> bool:
        """Whether Undo is on the toast now."""
        return not self.isHidden() and not self.undo.isHidden()

    def dismiss(self) -> None:
        """Take the message away: hidden, its words emptied, ``closed`` said."""
        self.timer.stop()
        self._leave()
        self.label.setText("")
        self._set_error(False)
        self.undo.hide()
        self.close_button.hide()
        self.closed.emit()

    def _set_error(self, error: bool) -> None:
        self.error = error
        for w in (self, self.label):
            w.setProperty("error", error)
            w.style().unpolish(w)
            w.style().polish(w)

    # ---- showing and hiding (release 5.195 animates these) ----
    def _appear(self) -> None:
        self.show()
        self.raise_()

    def _leave(self) -> None:
        self.hide()

    # ---- where it goes ----
    def place(self) -> None:
        """At the bottom centre of the window, ``MARGIN`` above its bottom edge; its words wrap past ``MAX_TEXT`` (or
        the window's width less ``SIDE_ROOM``), and it grows upward."""
        parent = self.parentWidget()
        limit = max(SIDE_ROOM, min(MAX_TEXT, parent.width() - SIDE_ROOM))
        self.label.setWordWrap(False)
        self.label.setMinimumWidth(0)
        self.label.setMaximumWidth(_NO_LIMIT)
        if self.label.sizeHint().width() > limit:
            self.label.setWordWrap(True)
            self.label.setFixedWidth(limit)
        self.adjustSize()
        self.resize(self.width(), max(LEAST_HEIGHT, self.height()))
        self.move((parent.width() - self.width()) // 2, parent.height() - MARGIN - self.height())

    # ---- the pointer ----
    def enterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.timer.stop()  # not while it's read, or its Undo reached for
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if not self.error and not self.isHidden():
            self.timer.start()  # at the interval it has
        super().leaveEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and not self.isHidden():
            self.place()
        return super().eventFilter(watched, event)
