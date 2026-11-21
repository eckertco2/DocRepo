"""Empty states (release 5.196, the redesign's decision 871): what a list view says when it has nothing to show, as one
widget, ``EmptyState``: the view's icon, one sentence, and the one button that fills it, where one makes sense.

Three cases, each with its own words:

- **First use** (``FIRST``): nothing has ever been there. It says what the view is for and offers the button that makes
  the first one (New task, New capture, Add person, Import…).
- **Nothing matching** (``MATCHING``): Find in this view, or a filter that's off its default (a chip under the header,
  release 5.184), hides everything. It says so and offers to clear it.
- **Nothing left** (``LEFT``): it's been emptied by doing the work: Today done, Unfiled filed, nothing due. It says so,
  with no button where none makes sense.

A view says its first-use and nothing-left words while it's drawn (``say``); nothing matching is worked out for every view
at once after Find has been applied (``settle``, from ``ListBasics._apply_find``), since only then is it known what's hidden.
The widget sits in the list, under the last row still showing (at the top when none is), and goes at the list's next
``begin``."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from docrepo.ui import tokens

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

FIRST, MATCHING, LEFT = "first", "matching", "left"
#: The icon's size, and the room above the empty state (below the last row, or the list's top) and around its words.
ICON = 28
GAP = 40
WIDTH = 420


@dataclass(frozen=True)
class Empty:
    """What a view says when it's empty: its case, its one sentence, and its one button (its words and what it does)."""
    case: str
    words: str
    button: str = ""
    action: Callable[[], None] | None = None


class EmptyState(QWidget):
    """An icon, one sentence and at most one button, in a column in the middle of the list (``tree_view.RowTree`` holds one
    and places it)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="emptyState")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(tokens.SPACE["l"], 0, tokens.SPACE["l"], tokens.SPACE["l"])
        lay.setSpacing(tokens.SPACE["m"])
        self.icon = QLabel(alignment=Qt.AlignmentFlag.AlignHCenter)
        self.words = QLabel(objectName="emptyWords", alignment=Qt.AlignmentFlag.AlignHCenter)
        self.words.setWordWrap(True)
        self.words.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.button = QPushButton()
        self.button.clicked.connect(lambda _=False: self._clicked())
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.words, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty: Empty | None = None

    def show_for(self, empty: Empty, icon_name: str) -> None:
        """Fill it: the view's icon (none when it has no icon), the words, and the button if the case has one."""
        from docrepo.ui.icons import tinted

        self.empty = empty
        self.icon.setVisible(bool(icon_name))
        if icon_name:
            pixmap = tinted(icon_name, tokens.colour("text3"), ICON, self.devicePixelRatioF())
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            self.icon.setPixmap(pixmap)
        self.words.setText(empty.words)
        self.button.setText(empty.button)
        self.button.setVisible(bool(empty.button and empty.action))

    def fit(self, width: int) -> None:
        """Across a list ``width`` px wide: its words wrapped at ``WIDTH`` (or the list's width less its margins), and as tall
        as they and the rest need."""
        for w in (self, self.icon, self.words, self.button):
            w.ensurePolished()  # the style sheet's font, before the words are measured
        room = width - 2 * tokens.SPACE["l"]
        self.words.setFixedWidth(max(120, min(WIDTH, room)))
        self.setFixedWidth(width)
        lay = self.layout()
        parts = [w for w in (self.icon, self.button) if not w.isHidden()]
        lines = QFontMetrics(self.words.font()).boundingRect(QRect(0, 0, self.words.width(), 100_000),
                                                             int(Qt.TextFlag.TextWordWrap), self.words.text())
        self.words.setFixedHeight(lines.height() + 2 * self.words.margin())  # a wrapped label's own hint is one line
        height = (sum(w.sizeHint().height() for w in parts) + self.words.height()
                  + lay.spacing() * len(parts) + lay.contentsMargins().top() + lay.contentsMargins().bottom())
        self.setFixedHeight(height)

    def _clicked(self) -> None:
        if self.empty is not None and self.empty.action is not None:
            self.empty.action()


def say(w: BrowseWindow, empty: Empty) -> None:
    """A view's words for when it's empty (first use or nothing left), said while it's drawn; ``settle`` shows them once
    Find has been applied, unless Find or a filter is the reason nothing shows."""
    w.tree.wanted_empty = empty


# ---- the words the views share ----
#: Each list's words when the work has emptied it (nothing left).
LIST_LEFT = {
    "due": "Nothing is overdue or due in the next 7 days.",
    "reminders": "No reminders in the next 7 days.",
    "waiting": "Nothing is waiting on someone else.",
    "mine": "Nothing open is assigned to you.",
    "unplanned": "Every open task has what the capacity calendar needs to place it.",
}


def has_tasks(w: BrowseWindow) -> bool:
    """Whether any task has ever been made (and not discarded): if not, a view of tasks is at its first use."""
    return any(not t.discarded for t in w.model().tasks.values())


def no_tasks_yet(w: BrowseWindow) -> Empty:
    """A view of tasks before the first task: what a task is, and New task."""
    return Empty(FIRST, "No tasks yet. A task is a piece of work you track; a project is a task at the top of the tree.",
                 "New task", lambda: w.open_capture(mode="new_task"))


def list_empty(w: BrowseWindow, view_id: str) -> Empty:
    """A list (Overdue and next 7 days, Reminders, Waiting on others, Assigned to me, No dates or hours) with no rows."""
    if not has_tasks(w):
        return no_tasks_yet(w)
    return Empty(LEFT, LIST_LEFT.get(view_id, "Nothing here right now."))


def _clear_find(w: BrowseWindow) -> None:
    w.close_find()
    w.render_list()


def _clear_filters(w: BrowseWindow, chips: list[tuple[str, Callable[[], None]]]) -> None:
    """Put every filter that's off its default back, as each chip's cross does, one after another."""
    for _words, clear in chips:
        clear()


def settle(w: BrowseWindow) -> None:
    """After a list view is drawn and Find applied: its empty state, or none while a row is showing. Find typed, or a filter
    off its default, with nothing showing is nothing matching; otherwise it's the words the view said, if it said any."""
    tree = w.tree
    showing = tree.shows_a_row()
    words = w.find_box.text().split() if not w.find_bar.isHidden() else []
    chips = list(getattr(w.head, "_chips", []))
    wanted: Empty | None = tree.wanted_empty
    empty: Empty | None = None
    if not showing and words and any(k is not None for k in tree.keys()):
        empty = Empty(MATCHING, f"Nothing in this view has “{' '.join(words)}”.", "Clear Find", lambda: _clear_find(w))
    elif wanted is not None and wanted.case == FIRST:
        empty = wanted
    elif not showing and chips:
        empty = Empty(MATCHING, "Nothing here matches the filters." if len(chips) > 1 else f"Nothing here matches the filter “{chips[0][0]}”.",
                      "Clear filters" if len(chips) > 1 else "Clear filter", lambda: _clear_filters(w, chips))
    elif wanted is not None:
        empty = wanted
    from docrepo.ui.nav_pane import ICONS

    tree.show_state(empty, ICONS.get(w.view, ""))
