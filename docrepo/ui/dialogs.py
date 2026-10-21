"""Small forms the browse tool opens: a person and a label. A task's fields are edited in ``task_forms``."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from docrepo.ui.style import STYLE


def split_list(text: str) -> list[str]:
    """A comma-separated list, such as aliases or keywords."""
    return [x.strip() for x in text.split(",") if x.strip()]


class _Form(QDialog):
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.layout_.addWidget(buttons)
        self.check: Callable[[], str | None] = lambda: None

    def _accept(self) -> None:
        problem = self.check()
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        self.accept()


class PersonDialog(_Form):
    """A person's name, aliases and hours a week."""

    def __init__(self, parent: QWidget | None, name: str = "", aliases: list[str] = (), hours: float | None = None, new: bool = False) -> None:
        super().__init__(parent, "Add person" if new else "Edit person",
                         "Tasks store a person's ID, so renaming someone changes nothing else. Aliases are other names Parse and populate "
                         "recognizes, such as a first name or initials.")
        self.name = QLineEdit(name)
        self.aliases = QLineEdit(", ".join(aliases))
        self.aliases.setPlaceholderText("Comma-separated, such as Priya, PS")
        self.hours = QLineEdit("" if hours is None else f"{hours:g}")
        self.hours.setPlaceholderText("Not set")
        self.form.addRow("Name", self.name)
        self.form.addRow("Aliases", self.aliases)
        self.form.addRow("Hours a week", self.hours)
        self.check = self._problem

    def _problem(self) -> str | None:
        if not self.name.text().strip():
            return "A person needs a name."
        try:
            hours = self.hours_value()
        except ValueError:
            return "Hours a week must be a number, such as 40 or 32.5, or empty."
        return "Hours a week can't be negative." if hours is not None and hours < 0 else None

    def hours_value(self) -> float | None:
        text = self.hours.text().strip()
        return float(text) if text else None

    def values(self) -> tuple[str, list[str], float | None]:
        return self.name.text().strip(), split_list(self.aliases.text()), self.hours_value()


class LabelDialog(_Form):
    """A label's name and keywords."""

    def __init__(self, parent: QWidget | None, name: str = "", keywords: list[str] = (), new: bool = False) -> None:
        super().__init__(parent, "Add label" if new else "Edit label",
                         "Renaming a label keeps it on its tasks. Keywords let Parse and populate suggest it; with none, its name is its keyword.")
        self.name = QLineEdit(name)
        self.keywords = QLineEdit(", ".join(keywords))
        self.keywords.setPlaceholderText("Comma-separated, such as safety, guard, rail")
        self.form.addRow("Name", self.name)
        self.form.addRow("Keywords", self.keywords)
        self.check = lambda: None if self.name.text().strip() else "A label needs a name."

    def values(self) -> tuple[str, list[str]]:
        name = self.name.text().strip()
        return name, split_list(self.keywords.text()) or [name]

