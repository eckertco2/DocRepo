"""The command palette (the visual overhaul's O7, decision 6): Ctrl+K lists every action and view, with its key on the right,
and narrows as you type. Enter runs the highlighted one; Esc closes it.

Matching is fuzzy: "edt tsk" finds Edit task. RapidFuzz (MIT) does it when it's installed; otherwise the standard
library's difflib does a simpler job, so the palette never needs it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QTreeWidgetItem, QVBoxLayout, QWidget

from docrepo.detail import esc
from docrepo.ui.tree_view import KEY_ROLE, RowTree

try:  # an approved package, used when it's there (requirements.txt pins it)
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - the fallback below
    fuzz = None

#: How many commands the palette shows at once.
SHOWN = 12


@dataclass(frozen=True)
class Command:
    """One thing the palette can do: "Task: Edit task", run by ``run``; ``key`` is its shortcut, shown on the right."""

    group: str
    name: str
    run: Callable[[], None]
    key: str = ""

    @property
    def label(self) -> str:
        return f"{self.group}: {self.name}" if self.group else self.name


def score(query: str, text: str) -> float:
    """How well ``query`` matches ``text``, 0 to 100: the words as typed count most, then any fuzzy likeness."""
    q, t = query.strip().lower(), text.lower()
    if not q:
        return 100.0
    if q in t:
        return 100.0 - t.index(q) * 0.1  # a match early in the name first
    if fuzz is not None:
        return float(max(fuzz.partial_ratio(q, t), fuzz.token_set_ratio(q, t)))
    if all(w in t for w in q.split()):
        return 90.0
    if all(_in_order(w, t) for w in q.split()):  # "edt tsk": each word's letters in order
        return 75.0
    return SequenceMatcher(None, q, t).ratio() * 80


def _in_order(word: str, text: str) -> bool:
    """Whether ``word``'s letters all appear in ``text`` in the same order."""
    rest = iter(text)
    return all(ch in rest for ch in word)


def rank(query: str, commands: list[Command], least: float = 55.0) -> list[Command]:
    """The commands that match ``query``, best first; all of them, in their own order, when it's empty."""
    if not query.strip():
        return list(commands)
    scored = [(score(query, c.label), i, c) for i, c in enumerate(commands)]
    return [c for s, _i, c in sorted(scored, key=lambda x: (-x[0], x[1])) if s >= least]


class CommandPalette(QDialog):
    """The palette over a window: a search box, then the matching commands, each with its key on the right."""

    def __init__(self, parent: QWidget, commands: list[Command]) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("palette")
        self.commands = commands
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Type a command or a view")
        self.box.textChanged.connect(self._fill)
        self.box.installEventFilter(self)
        lay.addWidget(self.box)
        self.list = RowTree()
        self.list.setObjectName("paletteList")
        self.list.set_columns(["Command", "Key"], [0, 130])
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setIndentation(0)
        self.list.itemActivated.connect(lambda item, _col: self._run_item(item))
        self.list.itemClicked.connect(lambda item, _col: self._run_item(item))
        lay.addWidget(self.list)
        self.none = QLabel("Nothing matches.", objectName="hint")
        self.none.hide()
        lay.addWidget(self.none)
        self._shown: list[Command] = []
        self._fill("")

    def open_over(self, window: QWidget) -> None:
        """Show it near the top of ``window``, centred, with the cursor in the box."""
        width = max(self.minimumWidth(), min(640, window.width() - 80))
        self.resize(width, self.sizeHint().height())
        top = window.mapToGlobal(window.rect().topLeft())
        self.move(top.x() + (window.width() - width) // 2, top.y() + 56)
        self.show()
        self.box.setFocus()

    def shown(self) -> list[Command]:
        return list(self._shown)

    def _fill(self, text: str) -> None:
        self._shown = rank(text, self.commands)[:SHOWN]
        self.list.begin()
        for i, c in enumerate(self._shown):
            group = f'<span class="sub">{esc(c.group)}:</span> ' if c.group else ""
            self.list.add_row(None, i, [group + esc(c.name), f'<p align="right" class="sub">{esc(c.key)}</p>' if c.key else ""])
        self.list.end(0 if self._shown else None)
        self.none.setVisible(not self._shown)
        self.list.setFixedHeight(max(1, min(SHOWN, len(self._shown))) * 32 + 6)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if watched is self.box and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._shown:
                now = self.list.currentItem()
                row = now.data(0, KEY_ROLE) if now is not None else -1
                self.list.select_key((row + (1 if key == Qt.Key.Key_Down else -1)) % len(self._shown))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item is not None:
                    self._run_item(item)
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return False

    def _run_item(self, item: QTreeWidgetItem) -> None:
        row = item.data(0, KEY_ROLE)
        if row is None or not 0 <= row < len(self._shown):
            return
        command = self._shown[row]
        self.close()
        command.run()
