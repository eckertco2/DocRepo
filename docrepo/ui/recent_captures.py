"""Recent captures (release 5.158, the design workspace's ``docs/mods/recent-captures-plan.md``, decisions 722 to 727): the
Capture wheel's NE (``capture.recent``), a popup listing the last captures saved, so a capture's words are worked on where
they live, its block on a notes page, and never in the capture window again (decision 722).

Each row (decision 724) shows its capture type's icon (meeting notes in the accent, so they stand out), its title, the task
whose notes page it opens on, or "Unfiled", and when it was saved, in the browse tool's short form ("9:40", "Mon", "12 Nov").
What's listed is ``docrepo.recent_captures``'s. Typing narrows it by title, across every capture, still newest first and
still at most 10. It moves as the `#` list does (``task_list``, decision 403's keys): Up and Down, Enter or Tab opens the
row that's current (the first, until you move), a click opens a row, and Esc closes it.

Enter brings the browse tool forward on the task's notes page at the capture's block, unfolded, with the caret on its
caption (``open_capture``, decision 725, the Captures tab's ``go_to_block``). A capture on no notes page opens its own
capture page, the status line saying why (decision 726).

It's a popup like the task picker, from a host window of its own as Task search has (``task_search``): a popup opened from
no window can't take the keyboard. No new view, window, field or schema change (decision 727).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import items, recent_captures
from docrepo.recent_captures import RecentRow
from docrepo.task_tile import fit_title
from docrepo.ui import tokens
from docrepo.ui.icons import tinted
from docrepo.ui.style import style_sheet
from docrepo.ui.task_list import OPTION_ROLE, Row, TaskList, Words

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

#: The popup's list: as wide as its widest row, between these, and every row in view (there are at most 10).
LIST_MIN_W, LIST_MAX_W = 460, 680
#: The share of a row the task it opens on keeps, at most, when the title needs the rest.
WHERE_SHARE = 0.4
WIDTH = LIST_MIN_W + 8
HINT = "Enter opens it on its notes page, where its words are worked on"
#: Each kind's icon and its colour token: meeting notes in the accent (decision 724), an email as the Unfiled view shows one.
ICONS = {"meeting": ("people", "accent"), "t_mail": ("type-mail", "type_mail"), "email": ("type-mail", "type_mail"),
         "new_task": ("task", "text2"), "update": ("update", "text2"), "note": ("note", "text2")}
#: The status line's words when a capture is on no notes page (decision 726).
NOT_ON_A_PAGE = "{id} isn't on a notes page, so its capture page is open instead."


def open_capture(app: CaptureApp, capture_id: str) -> None:
    """Enter on a row: the browse tool forward on the task's notes page at the capture's block (decision 725), or, when no
    notes page holds it, on its own capture page with the status line saying why (decision 726)."""
    m = app.ctx.model()
    c = m.captures.get(capture_id)
    if c is None:
        return
    task_id = recent_captures.page_of(m, c)
    browse = app.browse
    if task_id is not None:
        app.show_browse(None, task_id)
        browse.go_to_block(task_id, capture_id)
    else:
        app.show_browse()
        browse.go_capture(capture_id)
        browse.say(NOT_ON_A_PAGE.format(id=capture_id))


class RecentRowDelegate(QStyledItemDelegate):
    """A row: its kind's icon, its title in the Body font, the task it opens on in grey Caption, and when it was saved at
    its right end. The task keeps up to ``WHERE_SHARE`` of the row, shortened in its middle past that, and the title is cut
    as a task tile's is. A line that can't be picked is grey."""

    PAD, GAP, ICON = 8, 12, 16

    def __init__(self, popup: RecentList) -> None:
        super().__init__(popup)
        self.popup = popup
        self.font = tokens.ui_font(tokens.BODY)
        self.small = tokens.ui_font(tokens.CAPTION)

    def row_height(self) -> int:
        return max(30, QFontMetrics(self.font).height() + 10)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        return QSize(1, self.row_height())

    def natural_width(self, o: Row, head: bool) -> int:
        """The row's width with nothing shortened (``TaskList._fit`` asks)."""
        fs = QFontMetrics(self.small)
        w = 2 * self.PAD + 4 + QFontMetrics(self.font).horizontalAdvance(o.label)
        r = self.popup.recent.get(o.ref or "")
        if r is not None:
            w += self.ICON + 8 + self.GAP + fs.horizontalAdvance(r.where) + self.GAP + fs.horizontalAdvance(r.when)
        return w

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        o: Row = index.data(OPTION_ROLE)
        rect = option.rect
        fn, fs = QFontMetrics(self.font), QFontMetrics(self.small)
        base = int(rect.top() + (rect.height() + fn.ascent() - fn.descent()) / 2)
        left, right = rect.left() + self.PAD, rect.left() + rect.width() - self.PAD
        if isinstance(o, Words):
            p.save()
            p.setFont(self.small)
            p.setPen(QColor(tokens.colour("text2")))
            p.drawText(QPoint(left, base), fs.elidedText(o.label, Qt.TextElideMode.ElideRight, max(0, right - left)))
            p.restore()
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)  # the row's back and selection
        r = self.popup.recent.get(o.ref or "")
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grey = QColor(tokens.colour("text2"))
        if r is not None:
            name, colour = ICONS.get(r.kind, ("note", "text2"))
            mid = rect.top() + rect.height() / 2
            p.drawPixmap(QPoint(left, int(mid - self.ICON / 2)), tinted(name, tokens.colour(colour), self.ICON, p.device().devicePixelRatioF()))
            left += self.ICON + 8
            when_w = fs.horizontalAdvance(r.when)
            p.setFont(self.small)
            p.setPen(grey)
            p.drawText(QPoint(right - when_w, base), r.when)
            right -= when_w + self.GAP
        room = max(0, right - left)
        title_w = fn.horizontalAdvance(o.label)
        where = r.where if r is not None else ""
        where_w = fs.horizontalAdvance(where) if where else 0
        # Where it opens is what Enter does, so it keeps up to WHERE_SHARE of the row, and all of what the title leaves.
        where_room = min(where_w, int(room * WHERE_SHARE)) if where else 0
        title_room = room - (where_room + self.GAP if where_room else 0)
        if where and title_w < title_room:
            where_room = min(where_w, where_room + title_room - title_w)
            title_room = room - where_room - self.GAP
        # A long title is cut as a task tile's is (release 5.138): its first sentence, then its first clause, then at the edge.
        title = o.label if title_w <= title_room else fit_title(o.label, title_room, fn.horizontalAdvance,
                                                                  lambda t, w: fn.elidedText(t, Qt.TextElideMode.ElideRight, int(w)))
        p.setFont(self.font)
        p.setPen(QColor(tokens.colour("text")))
        p.drawText(QPoint(left, base), title)
        if where_room:
            shown = where if where_w <= where_room else fs.elidedText(where, Qt.TextElideMode.ElideMiddle, where_room)
            p.setFont(self.small)
            p.setPen(grey)
            p.drawText(QPoint(left + fn.horizontalAdvance(title) + self.GAP, base), shown)
        p.restore()


class RecentList(TaskList):
    """The `#` list's rows and keys (``task_list.TaskList``), drawn as recent captures: no levels and no task marks."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        #: Each row's capture, by its ID, for the delegate.
        self.recent: dict[str, RecentRow] = {}
        self.delegate = RecentRowDelegate(self)
        self.setItemDelegate(self.delegate)
        self.min_width, self.max_width, self.max_rows = LIST_MIN_W, LIST_MAX_W, recent_captures.LIMIT

    def show_recent(self, rows: list[RecentRow], empty: str) -> None:
        """List ``rows``, or ``empty`` as a line that can't be picked when there are none."""
        self.recent = {r.id: r for r in rows}
        options: list[Row] = [items.Option(r.id, r.title, f"{r.where} · {r.kind_words} · {r.id}", ref=r.id) for r in rows]
        self.show_rows(options or [Words(empty, heading=False)])


class RecentPopup(QFrame):
    """The popup: a box to type in, a line saying what Enter does, and the list. ``chosen`` is called with the capture ID."""

    def __init__(self, parent: QWidget | None, app: CaptureApp, chosen) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("taskPicker")  # the task picker's frame and list, so the two look alike
        self.app = app
        self.chosen = chosen
        self._at = QPoint()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the titles of every capture")
        self.search.setAccessibleName("Search recent captures")
        self.search.textChanged.connect(self.refill)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.note = QLabel(HINT, objectName="hint")
        self.note.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.note)
        self.list = RecentList(self)
        self.list.setObjectName("taskPickerList")
        self.list.picked.connect(self._picked)
        self.list.refitted.connect(self._place)
        layout.addWidget(self.list)

    # ---- opening ----
    def popup(self, at: QPoint) -> None:
        """Open with its top left at ``at``, kept on the screen, the box empty and the newest captures listed."""
        self._at = QPoint(at)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refill()
        self.show()
        self._place()
        self.raise_()
        self.search.setFocus()

    def _place(self) -> None:
        if not self.isVisible():
            return
        self.adjustSize()
        screen = QGuiApplication.screenAt(self._at) or self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self._at.x(), area.left() + area.width() - self.width()))
        y = max(area.top(), min(self._at.y(), area.top() + area.height() - self.height()))
        self.move(x, y)

    # ---- what it lists ----
    def refill(self) -> None:
        """The rows for what's typed (decision 724)."""
        typed = self.search.text().strip()
        ctx = self.app.ctx
        rows = recent_captures.recent_rows(ctx.model(), ctx.now().date(), typed)
        empty = f"No capture's title matches “{typed}”." if typed else "No captures yet."
        self.list.show_recent(rows, empty)

    def rows(self) -> list[RecentRow]:
        """The rows showing, as the list has them."""
        return [self.list.recent[o.ref] for o in self.list.rows() if isinstance(o, items.Option) and o.ref in self.list.recent]

    # ---- keys and picks ----
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        """The box keeps the keyboard; Up, Down, Enter and Tab are the list's (decision 403's keys), Esc closes it."""
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab) and self.list.handle_key(key):
                return True
        return super().eventFilter(watched, event)

    def _picked(self, o: Row) -> None:
        if isinstance(o, items.Option) and o.ref:
            self.close()
            self.chosen(o.ref)


class RecentCaptures(QWidget):
    """The host window, and the popup that opens from it, as Task search has them."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.app = app
        self.setFixedSize(1, 1)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.popup = RecentPopup(self, app, self._chosen)
        self.popup.installEventFilter(self)
        self._chose = False

    def open_it(self, screen) -> None:
        """At the centre of ``screen``, a sixth of the way down, as Task search opens."""
        self._chose = False
        area = screen.availableGeometry()
        at = QPoint(area.x() + (area.width() - WIDTH) // 2, area.y() + area.height() // 6)
        self.move(at)
        self.show()
        self.raise_()
        self.activateWindow()
        self.popup.popup(at)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if watched is self.popup and event.type() == QEvent.Type.Hide:
            QTimer.singleShot(0, self._hidden)
        return super().eventFilter(watched, event)

    def _hidden(self) -> None:
        """Just after the popup closes, so what it picked has already opened while this window held the foreground; closed
        with nothing picked, the keyboard goes back to the window you were in."""
        if not self._chose:
            self.app.wheels.give_back()
        self.hide()

    def _chosen(self, capture_id: str) -> None:
        self._chose = True
        open_capture(self.app, capture_id)
