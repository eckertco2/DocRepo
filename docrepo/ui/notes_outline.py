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
from docrepo.ui.look import LOOK

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


class _Rows(QStyledItemDelegate):
    """Paints a row: the heading's words indented by level, a day in the secondary colour and the Caption size, the
    owner's top headings in Semibold, a tint under the pointer, and the row you're in in the accent with a bar at its
    left, the way the sidebar marks its view."""

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
            p.drawRoundedRect(r, 4, 4)
        accent = QColor(tokens.colour("accent") if not LOOK.classic else "#1d5e98")
        if current:
            p.fillRect(QRect(r.x(), r.y() + 5, 2, r.height() - 10), accent)
        level, day = index.data(LEVEL) or 1, bool(index.data(DAY))
        font = tokens.ui_font(tokens.CAPTION if day else tokens.BODY, semibold=current or (level == 1 and not day))
        p.setFont(font)
        colour = accent if current else QColor(tokens.colour("text2" if day else "text"))
        p.setPen(colour)
        x = r.x() + 10 + INDENT * max(0, level - 1)
        text = QFontMetrics(font).elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideRight, r.right() - x - 4)
        p.drawText(QRect(x, r.y(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.restore()


class NotesOutline(QListWidget):
    """The list of the page's headings. ``picked`` carries the block number of the heading clicked."""

    picked = Signal(int)
    #: The list was read from the page again, with something new in it.
    rebuilt = Signal()

    def __init__(self, notes) -> None:
        super().__init__()
        self.setObjectName("notesOutline")
        self.notes = notes
        self.current = -1  # the block number of the heading you're in
        self._entries: list[tuple[int, int, bool, str]] | None = []
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
        entries = [(b.blockNumber(), level, day, " ".join(b.text().split()) or "(an empty heading)") for b, level, day in self.notes.outline()]
        if entries == self._entries:
            return
        self._entries = entries
        self.clear()
        # A day's year only where the page's days span more than one: "Thu 16 Jul", as the lists write a date.
        years = {d.year for _n, _l, day, text in entries if day and (d := notes_page.day_of(text))}
        for number, level, day, text in entries:
            shown = text.rsplit(" ", 1)[0] if day and len(years) == 1 and notes_page.day_of(text) else text
            it = QListWidgetItem(shown)
            it.setData(NUMBER, number)
            it.setData(LEVEL, level)
            it.setData(DAY, day)
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
