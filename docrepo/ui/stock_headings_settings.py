"""Settings' Stock headings card (release 5.169; the design workspace's ``docs/mods/stock-headings-plan.md``, decision
791), a form of its own as new forms are (``DocRepo/CLAUDE.md``): a row for each stock heading, its name, its level and
what belongs under it, with Remove, then Add a stock heading and Restore defaults, as the tag patterns' rows are
(``tagged_settings``).

Nothing is kept until Save settings, which checks the rows (``stock_headings.check``), writes settings.json and the
agents' page, ``Views\\Stock headings.md`` (``settings_view``).
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget

from docrepo import stock_headings


class StockHeadingsSettings(QWidget):
    """The card's form. ``set`` fills it from settings.json's ``stock_headings``; ``headings`` reads it back as typed."""

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(8)
        intro = QLabel("Topic headings every task's notes may use, each with what belongs under it. They're offered in the "
                       "heading list on every task, after the task's own headings, and what belongs under one shows on the "
                       "empty line below it until something is written there. An agent reads them in Views\\Stock headings.md.",
                       objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        box = QWidget()
        self.grid = QGridLayout(box)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        for col, words in enumerate(("Name", "Level", "What belongs under it")):
            self.grid.addWidget(QLabel(words, objectName="hint"), 0, col)
        self.grid.setColumnStretch(0, 2)
        self.grid.setColumnStretch(2, 5)
        self.none = QLabel("No stock headings: the heading list offers only each task's own. Add one, or restore the defaults.",
                           objectName="hint")
        self.grid.addWidget(self.none, 1, 0, 1, 4)
        lay.addWidget(box)
        self.rows: list[tuple[QLineEdit, QComboBox, QLineEdit, QToolButton]] = []
        self._grid_row = 1  # the grid's last row used (1 is No stock headings): a removed row's place isn't used again
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.add = QPushButton("Add a stock heading")
        self.add.clicked.connect(lambda: self.add_row("", 1, "", focus=True))
        self.restore = QPushButton("Restore defaults")
        self.restore.setToolTip("Puts the four that ship back: " + ", ".join(h.name for h in stock_headings.DEFAULTS)
                                + ". Save settings keeps them.")
        self.restore.clicked.connect(lambda: self.set(stock_headings.defaults()))
        buttons.addWidget(self.add)
        buttons.addWidget(self.restore)
        buttons.addStretch()
        lay.addLayout(buttons)

    def add_row(self, name: str, level: int, description: str, focus: bool = False) -> None:
        n = len(self.rows) + 1
        name_box = QLineEdit(name)
        name_box.setPlaceholderText("Such as Risks")
        name_box.setAccessibleName(f"Stock heading {n}'s name")
        name_box.setMaxLength(stock_headings.NAME_MAX)
        level_box = QComboBox()
        for lv in (1, 2, 3):
            level_box.addItem(f"{lv} ({'#' * lv})", lv)
        level_box.setCurrentIndex(max(0, level_box.findData(level)))
        level_box.setAccessibleName(f"Stock heading {n}'s level")
        level_box.setToolTip("The heading's level: 1 is a heading, 2 one under it, 3 one under that.")
        about = QLineEdit(description)
        about.setPlaceholderText("Such as What could go wrong, and what's being done about it.")
        about.setAccessibleName(f"What belongs under stock heading {n}")
        about.setMaxLength(stock_headings.DESCRIPTION_MAX)
        remove = QToolButton(text="×")
        remove.setAccessibleName(f"Remove stock heading {n}")
        remove.setToolTip("Remove this stock heading. Headings already on pages stay as they are.")
        row = (name_box, level_box, about, remove)
        remove.clicked.connect(lambda: self.remove_row(row))
        self.rows.append(row)
        self._grid_row += 1
        for col, w in enumerate(row):
            self.grid.addWidget(w, self._grid_row, col)
        self.none.setVisible(not self.rows)
        if focus:
            name_box.setFocus()

    def remove_row(self, row) -> None:
        self.rows.remove(row)
        for w in row:
            w.deleteLater()
        self.none.setVisible(not self.rows)

    def set(self, headings: list[dict]) -> None:
        """Fill the form from settings.json's ``stock_headings`` (or the defaults, for Restore defaults)."""
        for row in list(self.rows):
            for w in row:
                w.deleteLater()
        self.rows = []
        for h in stock_headings.stock_of(headings):
            self.add_row(h.name, h.level, h.description)
        self.none.setVisible(not self.rows)

    def headings(self) -> list[dict]:
        """The rows as typed, for Save settings to check: each with a name or words."""
        return [{"name": r[0].text().strip(), "level": r[1].currentData(), "description": r[2].text().strip()} for r in self.rows
                if r[0].text().strip() or r[2].text().strip()]
