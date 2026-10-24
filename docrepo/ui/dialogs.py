"""Small forms the browse tool opens: a person and a label. A task's fields are edited in ``task_forms``."""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from docrepo.ui.style import STYLE
from docrepo.ui.widgets import FormDialog


def split_list(text: str) -> list[str]:
    """A comma-separated list, such as aliases or keywords."""
    return [x.strip() for x in text.split(",") if x.strip()]


class _Form(FormDialog):
    def __init__(self, parent: QWidget | None, title: str, note: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("capture")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(440)
        self.layout_ = QVBoxLayout(self)
        if note:
            hint = QLabel(note, objectName="hint")
            hint.setWordWrap(True)
            self.layout_.addWidget(hint)
        self.form = QFormLayout()
        self.layout_.addLayout(self.form)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.layout_.addWidget(self.error)
        keys = QLabel(self.KEYS_HINT, objectName="hint")
        keys.setWordWrap(True)
        self.layout_.addWidget(keys)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.layout_.addWidget(buttons)
        self.check: Callable[[], str | None] = lambda: None

    def save(self) -> None:
        self._accept()

    def _accept(self) -> None:
        problem = self.check()
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        self.accept()


EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class PersonDialog(_Form):
    """A person's name, aliases and hours a week, and (release 5.9) their email, group and role."""

    def __init__(self, parent: QWidget | None, name: str = "", aliases: list[str] = (), hours: float | None = None, new: bool = False,
                 email: str | None = None, group: str | None = None, role: str | None = None, groups: list[str] = ()) -> None:
        super().__init__(parent, "Add person" if new else "Edit person",
                         "Tasks store a person's ID, so renaming someone changes nothing else. Aliases are other names Parse and populate "
                         "recognizes, such as a first name or initials. DocRepo only keeps an email address: it never sends email.")
        self.name = QLineEdit(name)
        self.aliases = QLineEdit(", ".join(aliases))
        self.aliases.setPlaceholderText("Comma-separated, such as Priya, PS")
        self.hours = QLineEdit("" if hours is None else f"{hours:g}")
        self.hours.setPlaceholderText("Not set")
        self.email = QLineEdit(email or "")
        self.email.setPlaceholderText("name@example.com")
        # One group a person (mods log round 2, M0033): pick one already used, or type a new one.
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems(["", *groups])
        self.group.setCurrentText(group or "")
        self.group.lineEdit().setPlaceholderText("None, or such as Maintenance")
        self.role = QLineEdit(role or "")
        self.role.setPlaceholderText("Such as Planner")
        self.form.addRow("Name", self.name)
        self.form.addRow("Aliases", self.aliases)
        self.form.addRow("Hours a week", self.hours)
        self.form.addRow("Email", self.email)
        self.form.addRow("Group", self.group)
        self.form.addRow("Role", self.role)
        self.check = self._problem
        self.mark_clean()

    def _problem(self) -> str | None:
        if not self.name.text().strip():
            return "A person needs a name."
        try:
            hours = self.hours_value()
        except ValueError:
            return "Hours a week must be a number, such as 40 or 32.5, or empty."
        if hours is not None and hours < 0:
            return "Hours a week can't be negative."
        email = self.email.text().strip()
        return f"{email} isn't an email address." if email and not EMAIL.fullmatch(email) else None

    def hours_value(self) -> float | None:
        text = self.hours.text().strip()
        return float(text) if text else None

    def values(self) -> tuple[str, list[str], float | None]:
        return self.name.text().strip(), split_list(self.aliases.text()), self.hours_value()

    def details(self) -> dict[str, str]:
        """Email, group and role, as typed: empty clears them."""
        return {"email": self.email.text().strip(), "group": self.group.currentText().strip(), "role": self.role.text().strip()}


class LabelDialog(_Form):
    """A label's name and keywords, and (release 5.9) the label it's under."""

    def __init__(self, parent: QWidget | None, name: str = "", keywords: list[str] = (), new: bool = False,
                 under: str | None = None, parents: list[str] = (), has_sublabels: bool = False) -> None:
        super().__init__(parent, "Add label" if new else "Edit label",
                         "Renaming a label keeps it on its tasks. Keywords let Parse and populate suggest it; with none, its name is its keyword. "
                         "A label can go under another, such as Line 1 under Production line: one level only.")
        self.name = QLineEdit(name)
        self.keywords = QLineEdit(", ".join(keywords))
        self.keywords.setPlaceholderText("Comma-separated, such as safety, guard, rail")
        # The label it's under (mods log round 2, M0051): one level, so only labels that aren't under one are offered.
        self.parent_box = QComboBox()
        self.parent_box.addItem("None", "")
        for p in parents:
            if p != name:
                self.parent_box.addItem(p, p)
        self.parent_box.setCurrentIndex(max(0, self.parent_box.findData(under or "")))
        if has_sublabels:
            self.parent_box.setEnabled(False)
            self.parent_box.setToolTip("It has labels under it, so it can't go under another")
        self.form.addRow("Name", self.name)
        self.form.addRow("Keywords", self.keywords)
        self.form.addRow("Under", self.parent_box)
        self.check = lambda: None if self.name.text().strip() else "A label needs a name."
        self.mark_clean()

    def values(self) -> tuple[str, list[str]]:
        name = self.name.text().strip()
        return name, split_list(self.keywords.text()) or [name]

    def under(self) -> str | None:
        return self.parent_box.currentData() or None

