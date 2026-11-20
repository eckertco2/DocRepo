"""DocRepo's own confirmation (release 5.187, the redesign's decision 863): a small floating dialog with a title, a sentence,
an optional one-line box and two buttons named by what they do ("Discard task", "Keep it"), in place of Qt's stock message
box and text box.

The safe answer is the default, as release 5.61 made it: in a question, Enter and Esc both keep things as they are; in a
question with a box, Enter does it, as the stock box's OK did, and Esc still cancels. ``run`` shows the dialog and waits;
tests replace it, so no window is shown.

The buttons' words for each question the browse tool asks live in one table, ``verbs``, found by the question's title,
so a caller changes one string and every test that replaces ``browse.confirm`` with a two-argument lambda keeps working.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from docrepo.ui import look

#: The dialog's width and its room, in pixels (the mock's floating board).
WIDTH = 400
MARGINS = (20, 20, 20, 16)
#: The gaps under the title, under the sentence (before the box) and over the buttons, and between the two buttons.
GAP_TEXT, GAP_BOX, GAP_BUTTONS, GAP_BETWEEN = 6, 12, 18, 8


@dataclass(frozen=True)
class Verbs:
    """A question's two buttons: the one that does it, and the safe one."""

    yes: str              # the button that does it: "Discard task"
    no: str = "Cancel"    # the safe answer: "Keep it"
    danger: bool = False  # the doing button filled in ``critical``, for what can't be undone from the same place


class Confirm(QDialog):
    """A title, a sentence, an optional one-line box, and two buttons named by the caller."""

    def __init__(self, parent: QWidget | None, title: str, text: str, verbs: Verbs, *, value: str | None = None,
                 placeholder: str = "") -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("confirm")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(WIDTH)
        look.floating(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*MARGINS)
        lay.setSpacing(0)
        self.title_label = QLabel(title, objectName="confirmTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        lay.addWidget(self.title_label)
        lay.addSpacing(GAP_TEXT)
        self.text_label = QLabel(text, objectName="confirmText")
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        lay.addWidget(self.text_label)
        self.box: QLineEdit | None = None
        if value is not None:
            lay.addSpacing(GAP_BOX)
            self.box = QLineEdit(value)
            self.box.setPlaceholderText(placeholder)
            self.box.selectAll()
            lay.addWidget(self.box)
        lay.addSpacing(GAP_BUTTONS)
        row = QHBoxLayout()
        row.setSpacing(GAP_BETWEEN)
        row.addStretch(1)
        self.stay = QPushButton(verbs.no)
        self.go = QPushButton(verbs.yes, objectName="danger" if verbs.danger else "primary")
        row.addWidget(self.stay)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.stay.clicked.connect(self.reject)
        self.go.clicked.connect(self.accept)
        if self.box is not None:  # Enter does it, from the box
            self.go.setDefault(True)
            self.stay.setAutoDefault(False)
            self.box.setFocus()
        else:  # Enter and Esc both keep things as they are
            self.stay.setDefault(True)
            self.stay.setFocus()
        self.setTabOrder(self.stay, self.go)

    def typed(self) -> str:
        """What's in the box, or nothing when there's none."""
        return self.box.text() if self.box is not None else ""

    def fit(self) -> None:
        """Give the title and the sentence the height their words wrap to at the dialog's width (a wrapped label's own size
        hint doesn't know the width it'll have), then size the dialog to what's in it."""
        self.ensurePolished()
        inner = WIDTH - MARGINS[0] - MARGINS[2]
        for label in (self.title_label, self.text_label):
            label.ensurePolished()
            label.setFixedHeight(label.heightForWidth(inner))
        self.setFixedHeight(self.layout().totalMinimumSize().height())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.fit()
        self._centre()
        super().showEvent(event)

    def _centre(self) -> None:
        """Over the middle of the window that asked, or of the screen under the pointer when nothing did."""
        parent = self.parentWidget()
        if parent is not None:
            area = parent.window().frameGeometry()
        else:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)


def _shown(box: Confirm) -> bool:
    return box.exec() == QDialog.DialogCode.Accepted


#: Shows a Confirm and waits: True when ``go`` was pressed. Tests replace it.
run: Callable[[Confirm], bool] = _shown

#: The browse tool's questions, by title: the buttons each gets (the redesign's lane D plan, 5.187's table).
_TABLE: dict[str, Verbs] = {
    "Close without saving?": Verbs("Close without saving", "Keep editing", True),
    "Take its block off the notes page?": Verbs("Take it off the page", "Leave it on the page"),
    "Remove this glossary?": Verbs("Remove glossary", "Keep it", True),
    "Add it to the tag list?": Verbs("Add to the tag list", "Cancel"),
    "Change the data root?": Verbs("Change data root", "Keep this one"),
    "Detach from its template?": Verbs("Detach", "Keep it attached"),
    "Delete this what-if?": Verbs("Delete what-if", "Keep it", True),
    "Discard this task?": Verbs("Discard task", "Keep it", True),
    "Discard this capture?": Verbs("Discard capture", "Keep it", True),
    "Discard this template?": Verbs("Discard template", "Keep it", True),
}
_CLOSE_ALL = re.compile(r"Close all \d+\?")


def verbs(title: str, text: str = "") -> Verbs:
    """The buttons for a question, from its title: whole, or by its shape for one that carries a number ("Close all 4?"
    gives "Close all 4"). A title it doesn't know gives itself and Cancel, as release 5.61's answers did, but for the two
    questions those answers knew by their sentence."""
    if title in _TABLE:
        return _TABLE[title]
    if _CLOSE_ALL.fullmatch(title):
        return Verbs(title[:-1], "Cancel")
    if "without saving" in text:
        return Verbs("Close without saving", "Keep editing", True)
    if "off the page" in text:
        return Verbs("Take it off the page", "Leave it on the page")
    return Verbs(title, "Cancel")


def ask(parent: QWidget | None, title: str, text: str, yes: str, no: str = "Cancel", *, danger: bool = False) -> bool:
    """A question whose buttons say what they do; Enter and Esc give the safe answer. True for ``yes``."""
    return run(Confirm(parent, title, text, Verbs(yes, no, danger)))


def ask_for(parent: QWidget | None, title: str, text: str) -> bool:
    """``ask``, with the buttons ``verbs`` gives the title."""
    v = verbs(title, text)
    return ask(parent, title, text, v.yes, v.no, danger=v.danger)


def ask_text(parent: QWidget | None, title: str, text: str, value: str = "", *, yes: str = "OK", no: str = "Cancel",
             placeholder: str = "", danger: bool = False) -> str | None:
    """A question with a one-line box: what's typed on ``yes`` (or Enter), None on ``no`` (or Esc)."""
    box = Confirm(parent, title, text, Verbs(yes, no, danger), value=value, placeholder=placeholder)
    return box.typed() if run(box) else None
