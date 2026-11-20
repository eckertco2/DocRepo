"""The notes page's outline (release 5.113): the notes workspace plan's decision 349, built for the task page at the owner's
ask of 2026-11-10 ("a navigation panel for the headers of the notes panel").

A column at the left of the notes lists the page's headings and day dividers in order, the owner's headings indented
by level under their day, and marks the one you're in: the heading over the caret while you type, or else the one at
the top of the view. A click goes there, unfolding what hides it, as Jump to does. The pane has one scroll bar (the
notes are as tall as their text), so the column can't be a pane of its own: ``OutlineSlot`` keeps its place beside
the notes, and the outline moves itself down that slot as the page scrolls, so it stays in view while the notes are.
When the list is taller than the view it scrolls on its own. Nothing here is saved: the list is read from the page.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from docrepo import notes_page
from docrepo.ui import tokens

#: The outline's width, its divider included.
OUTLINE_WIDTH = 188
#: The narrowest the notes' text may get beside the outline (about 60 characters); in a narrower pane the outline steps
#: aside and its button opens the Jump to list instead.
OUTLINE_MIN_TEXT = 360
#: A row of the outline.
ROW = 26
#: How far each level of heading is indented under the one above it.
INDENT = 12

NUMBER, LEVEL, DAY = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 2
#: A row's count at its right (release 5.157, decision 713): a topic's runs in All notes By topic.
COUNT = Qt.ItemDataRole.UserRole + 3


class _Rows(QStyledItemDelegate):
    """Paints a row: the heading's words indented by level, in the second grey; a day as a small label in the third; the
    owner's top headings in Semibold; a tint under the pointer; and the row you're in dark and semibold. Since release 5.186
    (the redesign's decision 860) the outline is a quiet gutter: no bar and no accent, which isn't one of its six jobs."""

    def __init__(self, outline: NotesOutline) -> None:
        super().__init__(outline)
        self.outline = outline

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802 - Qt's name
        return QSize(OUTLINE_WIDTH - 12, ROW)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        p.save()
        r = option.rect.adjusted(2, 1, -4, -1)
        current = index.data(NUMBER) == self.outline.current
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tokens.colour("hover")))
            p.drawRoundedRect(r, tokens.RADIUS_S, tokens.RADIUS_S)
        level, day = index.data(LEVEL) or 1, bool(index.data(DAY))
        font = tokens.ui_font(tokens.LABEL if day else tokens.BODY, semibold=current or (level == 1 and not day) or day)
        p.setFont(font)
        colour = QColor(tokens.colour("text" if current else "text3" if day else "text2"))
        p.setPen(colour)
        x = r.x() + 10 + INDENT * max(0, level - 1)
        right = r.right()
        count = index.data(COUNT)
        if count is not None:  # its count in the muted grey, at the right (release 5.157)
            small = tokens.ui_font(tokens.CAPTION)
            words = str(count)
            width = QFontMetrics(small).horizontalAdvance(words)
            p.setFont(small)
            p.setPen(QColor(tokens.colour("text3")))
            p.drawText(QRect(right - width - 6, r.y(), width + 2, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, words)
            right -= width + 10
            p.setFont(font)
            p.setPen(colour)
        text = QFontMetrics(font).elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideRight, right - x - 4)
        p.drawText(QRect(x, r.y(), right - x, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.restore()


class NotesOutline(QListWidget):
    """The list of the page's headings. ``picked`` carries the block number of the heading clicked."""

    picked = Signal(int)
    #: The list was read from the page again, with something new in it.
    rebuilt = Signal()

    def __init__(self, notes=None) -> None:
        """``notes`` is the editor it reads its headings from; with none, it shows what ``set_entries`` gives it (All
        notes' days and pages, release 5.140)."""
        super().__init__()
        self.setObjectName("notesOutline")
        self.notes = notes
        self.current = -1  # the block number of the heading you're in
        self._entries: list[tuple[int, int, bool, str]] | None = []
        self._counts: dict[int, int] = {}
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the caret stays in the notes; Ctrl+G is the keyboard's way
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setItemDelegate(_Rows(self))
        self.itemClicked.connect(lambda it: self.picked.emit(int(it.data(NUMBER))))
        # The list follows the page: its words, its headings and its folds, read again a moment after they change.
        self._timer = QTimer(self, singleShot=True, interval=150, timeout=self.rebuild)
        if notes is not None:
            notes.document().contentsChanged.connect(self._timer.start)
            notes.folds_changed.connect(self._timer.start)
            notes.page_set.connect(self._page_set)

    def _page_set(self) -> None:
        """Another page (or the same one again): read at once, so the list never shows the page before, and marked from
        its first heading until the view says otherwise."""
        self._timer.stop()
        self.current = -1
        self._entries = None  # read it again even if it's the same, so the pane fits the outline to it
        self.rebuild()
        self.scrollToTop()

    def entries(self) -> list[tuple[int, int, bool, str]]:
        """What the list shows: (block number, level, whether it's a day, words), in the page's order."""
        return list(self._entries or [])

    def rebuild(self) -> None:
        if self.notes is None:
            return
        self.set_entries([(b.blockNumber(), level, day, " ".join(b.text().split()) or "(an empty heading)") for b, level, day in self.notes.outline()])

    def set_entries(self, entries: list[tuple[int, int, bool, str]], counts: dict[int, int] | None = None) -> None:
        """Show these entries: (a number ``picked`` carries back, level, whether it's a day, words), in order; ``counts``,
        by an entry's number, shows at its right (release 5.157: a topic's runs)."""
        counts = counts or {}
        if entries == self._entries and counts == self._counts:
            return
        self._entries, self._counts = entries, counts
        self.clear()
        # A day's year only where the page's days span more than one: "Thu 16 Jul", as the lists write a date.
        years = {d.year for _n, _l, day, text in entries if day and (d := notes_page.day_of(text))}
        for number, level, day, text in entries:
            shown = text.rsplit(" ", 1)[0] if day and len(years) == 1 and notes_page.day_of(text) else text
            it = QListWidgetItem(shown)
            it.setData(NUMBER, number)
            it.setData(LEVEL, level)
            it.setData(DAY, day)
            if number in counts:
                it.setData(COUNT, counts[number])
            it.setToolTip(text)
            self.addItem(it)
        self.rebuilt.emit()

    def minimum_slot(self) -> int:
        """How tall the slot beside the notes should be at least, so a short page doesn't squeeze the list into a scroll."""
        return min(self.rows_height() + 8, 8 * ROW)

    def rows_height(self) -> int:
        return self.count() * ROW + 2 * self.frameWidth() + 8

    def set_current(self, number: int) -> None:
        """Mark the heading you're in, and bring it into the list's view."""
        if number == self.current:
            return
        self.current = number
        for i in range(self.count()):
            if self.item(i).data(NUMBER) == number:
                self.scrollToItem(self.item(i), QListWidget.ScrollHint.EnsureVisible)
                break
        self.viewport().update()


class OutlineSlot(QFrame):
    """The outline's place beside the notes: as tall as the notes, with a divider at its right. The outline inside it
    stays at the top of the view while the notes scroll past, and stops at the slot's end."""

    def __init__(self, outline: NotesOutline, offset: Callable[[], int] = lambda: 0, view_height: Callable[[], int] = lambda: 600) -> None:
        super().__init__()
        self.setObjectName("outlineSlot")
        self.setFixedWidth(OUTLINE_WIDTH)
        self.outline = outline
        outline.setParent(self)
        #: How far the slot's top has scrolled above the view's top (less what covers it, the sticky title line), and the
        #: view's height: the pane says, as these are the pane's.
        self.offset, self.view_height = offset, view_height

    def place(self) -> None:
        """Put the outline at the top of the view, within the slot."""
        if self.isHidden():
            return
        if self.minimumHeight() != self.outline.minimum_slot():
            self.setMinimumHeight(self.outline.minimum_slot())
        room = max(ROW * 2, self.view_height() - 16)
        h = min(self.outline.rows_height(), room, max(ROW, self.height() - 8))
        top = max(4, min(self.offset() + 8, self.height() - h - 4))
        geo = QRect(0, top, OUTLINE_WIDTH - 1, h)
        if self.outline.geometry() != geo:
            self.outline.setGeometry(geo)
        self.outline.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self.place()
