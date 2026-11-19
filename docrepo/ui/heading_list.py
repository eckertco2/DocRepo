"""The heading list (release 5.156; the design workspace's ``docs/mods/notes-topics-plan.md``, decisions 704 to 707).

Typing in a topic heading (``docrepo.topics``) lists the topic headings already used at its level, under the caret: the
task's own and what's under it, then, after a grey "Elsewhere in …" row, the rest of its project's, then, after a grey
"Stock headings" row, the owner's stock headings the page doesn't have yet (release 5.169). Its rows and look
are the `#` list's (``task_list.TaskList``, release 5.103); its keys are a free-text line's (decision 706):

- what's typed narrows it; nothing is highlighted until Down or Up;
- Enter takes the highlighted row, and with none leaves the list to the box, which keeps what's typed and starts the line
  below, as Enter on a heading always has;
- Tab takes the highlighted row, or else the top one; a click takes its row;
- Esc closes it until something more is typed.

``RichEdit`` holds one and drives it (``heading_options``); a row taken replaces the heading line's words.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget

from docrepo import items, topics
from docrepo.ui.task_list import OPTION_ROLE, TaskList, Words, can_pick


#: The divider over the stock headings the page doesn't have yet (release 5.169, decision 789).
STOCK = "Stock headings"


def rows_of(listing: topics.Listing, today: date) -> list[items.Option | Words]:
    """The list's rows: the task's, then "Elsewhere in …" and the rest, then "Stock headings" and the stock headings the
    page doesn't have (release 5.169). Each row's value is its words; its grey part says what it's under, how often and
    when last (``topics.sub_text``), or for a stock heading what belongs under it."""
    out: list[items.Option | Words] = [items.Option(r.words, r.words, topics.sub_text(r, today)) for r in listing.here]
    if listing.others:
        out.append(Words(f"Elsewhere in {listing.elsewhere}"))
        out += [items.Option(r.words, r.words, topics.sub_text(r, today)) for r in listing.others]
    if listing.stock:
        out.append(Words(STOCK))
        out += [items.Option(r.words, r.words, topics.sub_text(r, today)) for r in listing.stock]
    return out


def abouts(listing: topics.Listing) -> dict[str, str]:
    """What belongs under each of the task's own rows that's a stock heading, by its words, for its tooltip (decision 789:
    a stock heading the page already uses is listed with the task's own, its tooltip still saying what belongs under it)."""
    return {r.words: r.about for r in listing.here + listing.others if r.about}


class HeadingList(TaskList):
    """The list under a topic heading being typed. ``show_at`` lists rows with none highlighted; ``handle_key`` takes the
    box's keys while it shows; ``picked`` sends the row taken (an ``items.Option``, its ``value`` the words)."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("headingList")
        self._at, self._above = QPoint(), None
        self.min_width = 280
        self.hide()

    def show_at(self, rows: list[items.Option | Words], at: QPoint, above: int | None = None,
                about: dict[str, str] | None = None) -> None:
        """Show ``rows`` with nothing highlighted (decision 706), under ``at`` in the parent, or with its foot at
        ``above`` when it wouldn't fit under it. ``about``: what belongs under a row that's a stock heading, by its words,
        added to its tooltip (release 5.169)."""
        self._at, self._above = QPoint(at), above
        self.show_rows(rows)
        for i in range(self.count()):
            item = self.item(i)
            o = item.data(OPTION_ROLE)
            if can_pick(o) and about and about.get(o.value):
                item.setToolTip(f"{item.toolTip()}\nStock heading: {about[o.value]}")
        self.setCurrentRow(-1)
        self.show()
        self.raise_()

    def _area(self) -> QRect:
        parent = self.parentWidget()
        return parent.rect().adjusted(4, 4, -4, -4) if parent is not None else super()._area()

    def _fit(self, rows) -> None:
        """Size it to its rows, and keep it in the window: under the caret, or above it where it wouldn't fit."""
        super()._fit(rows)
        area = self._area()
        x = max(area.left(), min(self._at.x(), area.right() - self.width()))
        y = self._at.y()
        if y + self.height() > area.bottom() and self._above is not None:
            y = self._above - self.height()
        self.move(x, max(area.top(), min(y, area.bottom() - self.height())))

    def highlighted(self) -> items.Option | None:
        """The row Down or Up has highlighted, or None."""
        item = self.currentItem()
        o = item.data(OPTION_ROLE) if item is not None and self.currentRow() >= 0 else None
        return o if can_pick(o) else None

    def step(self, by: int) -> None:
        """Down from nothing highlighted goes to the first row, Up to the last; then as the `#` list steps."""
        if self.currentRow() < 0:
            rows = [i for i in range(self.count()) if can_pick(self.item(i).data(OPTION_ROLE))]
            if rows:
                self.setCurrentRow(rows[0] if by > 0 else rows[-1])
            return
        super().step(by)

    def handle_key(self, key: int) -> bool:
        """A key typed in the box while the list shows; True when the list used it (decision 706)."""
        if not self.isVisible():
            return False
        if key == Qt.Key.Key_Escape:
            self.hide()
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.step(1 if key == Qt.Key.Key_Down else -1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            o = self.highlighted()
            if o is None:
                self.hide()
                return False  # the box keeps what's typed and starts the line below
            self.picked.emit(o)
            return True
        if key == Qt.Key.Key_Tab:
            o = self.highlighted() or self.current()
            if o is not None:
                self.picked.emit(o)
            return True
        return False
