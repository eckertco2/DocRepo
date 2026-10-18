"""Small forms the browse tool opens: a person, a label, a task's title and description, and a task's labels."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from docrepo.ui.style import STYLE
from docrepo.ui.widgets import Chip, ChipPicker, Option


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


class TaskTextDialog(_Form):
    """A task's title and description, to fix a mistake. Both changes go into its status log."""

    def __init__(self, parent: QWidget | None, title: str, description: str) -> None:
        super().__init__(parent, "Title and description", "Fixes a task's title or description. Each change goes into its status log.")
        self.title = QLineEdit(title)
        self.description = QPlainTextEdit(description)
        self.description.setMinimumHeight(140)
        self.form.addRow("Title", self.title)
        self.form.addRow("Description", self.description)
        self.check = lambda: None if self.title.text().strip() else "A task needs a title."

    def values(self) -> tuple[str, str]:
        return self.title.text().strip(), self.description.toPlainText().strip()


class TaskLabelsDialog(_Form):
    """A task's own labels, and whether it inherits its parents'."""

    def __init__(self, parent: QWidget | None, options: Callable[[str, list[str]], list[Option]], labels: list[str], inherit: bool,
                 inherited: list[str]) -> None:
        super().__init__(parent, "Labels", "A task's own labels come first, then its parents', unless it doesn't inherit them.")
        self.labels = ChipPicker(options, "Search or add", "Create label “{}”")
        self.labels.set_chips([Chip(name, name) for name in labels])
        self.inherit = QCheckBox("Inherit parent labels")
        self.inherit.setChecked(inherit)
        self.form.addRow("Labels", self.labels)
        self.form.addRow("", self.inherit)
        if inherited:
            self.form.addRow("", QLabel("Its parents have: " + ", ".join(inherited), objectName="hint"))

    def values(self) -> tuple[list[str], list[str], bool]:
        """(labels, new labels to create, inherit)."""
        chips = self.labels.chips()
        return [c.value for c in chips], [c.value for c in chips if c.new], self.inherit.isChecked()
