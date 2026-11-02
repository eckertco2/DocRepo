"""The browse tool's middle pane list: a tree of rows whose cells are small pieces of HTML.

Rows carry a key, such as ("task", "T000008"), that says what selecting them
opens. Each top-level task's group has a colour band: four muted colours in
turn, lighter for each level down, like the mockup's task tree.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QCursor, QPainter, QPalette, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QTreeWidget, QTreeWidgetItem, QWidget)

from docrepo.ui import tokens
from docrepo.ui.look import LOOK, paint_focus_ring
from docrepo.ui.style import CLASSIC_TREE, page_css

KEY_ROLE = Qt.ItemDataRole.UserRole
HTML_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row kept only for context, drawn faded: a parent of what Find in this view found (mods log round 2, M0026).
DIM_ROLE = Qt.ItemDataRole.UserRole + 2
#: The new look's colour edge on a top-level task's row: its group's colour (decision 9), never a tint across its rows.
EDGE_ROLE = Qt.ItemDataRole.UserRole + 3
#: A row's actions, a ``RowActions`` (release 5.59).
ACTIONS_ROLE = Qt.ItemDataRole.UserRole + 4

GROUP_COLOURS = tuple(tokens.LIGHT[k] for k in tokens.GROUP_KEYS)
GREY = "#b8c1cb"  # Classic's, for a task with no group
#: How strongly a group's colour shows, by depth: top-level tasks most, each level down less.
TINTS = (0.15, 0.09, 0.05, 0.025)
ROW_MIN_HEIGHT = 26
#: The new look's rows: 28 px, with a 16 px indent (decision 3).
NEW_ROW_MIN_HEIGHT = tokens.TREE_ROW
#: The room a row's tick box takes, in Select mode.
CHECK_WIDTH = 22
#: The least room a list's first column keeps: in a narrower list its last columns go first (release 5.58).
MIN_TITLE = 160


def tint(group: int, depth: int) -> QColor | None:
    """A group's colour mixed into white, for a row at ``depth``. The new look has none: the group's colour is an edge on
    its top-level row instead (``edge``)."""
    if not LOOK.classic:
        return None
    base = QColor(GREY if group < 0 else GROUP_COLOURS[group % len(GROUP_COLOURS)])
    p = TINTS[min(depth, len(TINTS) - 1)]
    return QColor(round(255 + (base.red() - 255) * p), round(255 + (base.green() - 255) * p), round(255 + (base.blue() - 255) * p))


def group_ground() -> QColor:
    """Behind a group's heading in a list."""
    return QColor(GREY).lighter(135) if LOOK.classic else QColor(tokens.colour("base"))


def edge(group: int, depth: int) -> str | None:
    """The new look's colour edge for a row: its group's colour on a top-level row, nothing below it."""
    return None if LOOK.classic or depth or group < 0 else tokens.group_colour(group)


def with_actions(labels: list[str], widths: list[int], width: int) -> tuple[list[str], list[int]]:
    """A list's columns. The Classic look gives a row's actions a column of ``width`` px; the new look shows them over the row."""
    return ([*labels, ""], [*widths, width]) if LOOK.classic else (labels, widths)


class RowActions:
    """What a row can do: (label, clicked, tooltip) for each. A plain object, so it comes back from the row as it went in."""

    def __init__(self, actions: list[tuple[str, Callable[[], None], str]]) -> None:
        self.actions = actions


class ActionStrip(QWidget):
    """A row's actions as links. In the new look it lies over the end of the row's first column, only while the row is under
    the mouse or current, so a list isn't a column of links (release 5.59). In the Classic look it's a cell, always there."""

    def __init__(self, row: RowActions, item: QTreeWidgetItem | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="rowActions")
        self.item = item
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0) if LOOK.classic else lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(4 if LOOK.classic else 10)
        for label, clicked, tip in row.actions:
            b = QPushButton(label, objectName="rowLink")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=clicked: c())
            lay.addWidget(b)
        if LOOK.classic:
            lay.addStretch()


class HtmlDelegate(QStyledItemDelegate):
    """Draws a cell's HTML, wrapping it to the column's width."""

    def __init__(self, view: QTreeWidget) -> None:
        super().__init__(view)
        self.view = view

    def _doc(self, html: str, width: int, option: QStyleOptionViewItem) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDefaultStyleSheet(page_css())  # the pages' colours, so chips look the same in lists
        doc.setDocumentMargin(2)
        doc.setHtml(html)
        doc.setTextWidth(max(20, width))
        return doc

    def _width(self, index: QModelIndex) -> int:
        width = self.view.columnWidth(index.column())
        if index.column() == 0:
            level, parent = 0, index.parent()
            while parent.isValid():
                level, parent = level + 1, parent.parent()
            width -= self.view.indentation() * (level + (1 if self.view.rootIsDecorated() else 0))
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            width -= CHECK_WIDTH
        return width - self.view.cell_pad - 3

    def paint(self, painter, option, index) -> None:  # noqa: D102 - Qt's
        html = index.data(HTML_ROLE)
        if html is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else self.view.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        left = opt.rect.left()
        if opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:  # a tick box, drawn above: the HTML goes after it
            left = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget).left()
        doc = self._doc(html, opt.rect.right() - left - self.view.cell_pad - 3, opt)
        painter.save()
        if index.siblingAtColumn(0).data(DIM_ROLE):
            painter.setOpacity(0.5)
        top = opt.rect.top() + max(0, (opt.rect.height() - doc.size().height()) / 2)
        painter.translate(left + self.view.cell_pad, top)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(tokens.colour("text")))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        html = index.data(HTML_ROLE)
        if html is None:
            return super().sizeHint(option, index)
        doc = self._doc(html, self._width(index), option)
        if LOOK.classic:
            return QSize(int(doc.idealWidth()), max(ROW_MIN_HEIGHT, int(doc.size().height()) + 6))
        return QSize(int(doc.idealWidth()), max(NEW_ROW_MIN_HEIGHT, int(doc.size().height()) + 4))  # one line of Body text: the token's 28 px


class RowTree(QTreeWidget):
    """The list of rows. ``picked`` sends the key of the row that became current, by click or keyboard. Rows given a tick box
    (``add_tick``) send ``ticked`` with their key when it's ticked or cleared by hand."""

    picked = Signal(object)
    ticked = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.cell_pad = 3  # the room before each cell's text; the sidebar's views have more
        self.setItemDelegate(HtmlDelegate(self))
        self.setUniformRowHeights(False)
        self.setWordWrap(True)
        self.setIndentation(14 if LOOK.classic else 16)
        self.setAlternatingRowColors(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        if LOOK.classic:
            self.setStyleSheet(CLASSIC_TREE)
        self._building = False
        self._moves: tuple[Callable, Callable, Callable] | None = None
        self._hover: QTreeWidgetItem | None = None
        self._strips: list[ActionStrip] = []
        self._widths: list[int] = []
        self._empty: QWidget | None = None
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(60)
        self._relayout.timeout.connect(self.doItemsLayout)
        self._relayout.timeout.connect(self._sync_strips)
        self.header().sectionResized.connect(lambda *_: self._relayout.start())
        if not LOOK.classic:
            self.setMouseTracking(True)
            self.verticalScrollBar().valueChanged.connect(lambda _: self._hover_from_cursor())
            self.horizontalScrollBar().valueChanged.connect(lambda _: self._sync_strips())
            self.itemExpanded.connect(lambda _: self._sync_strips())
            self.itemCollapsed.connect(lambda _: self._sync_strips())
        self.currentItemChanged.connect(self._current_changed)
        self.itemChanged.connect(self._item_changed)
        self.set_columns(["Title", "State", "Due"])

    # ---- moving rows (release 5.49, decision 261): only where a view asks for it ----
    def allow_row_moves(self, drop: Callable[[object, object, str], None], can: Callable[[object, object, str], bool], step: Callable[[object, int], None]) -> None:
        """Rows can be dragged here, and Alt+Up and Alt+Down move the current one. ``drop`` gets a row's key, the row it was dropped
        on, and "before", "after" or "in". ``can`` says whether that's allowed. The tree itself moves nothing: ``drop`` changes the
        records, and the view draws them again."""
        self._moves = (drop, can, step)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def stop_row_moves(self) -> None:
        self._moves = None
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def _drop_at(self, pos: QPoint) -> tuple[object, str] | None:
        """The row under a point and which part of it, by the margins Qt draws its drop line from, or None where nothing can land."""
        item = self.itemAt(pos)
        if item is None:
            return None
        rect = self.visualItemRect(item)
        margin = max(2, min(12, round(rect.height() / 5.5)))
        where = "before" if pos.y() - rect.top() < margin else "after" if rect.bottom() - pos.y() < margin else "in"
        return item.data(0, KEY_ROLE), where

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().dragEnterEvent(event)
        if self._moves:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().dragMoveEvent(event)
        if not self._moves:
            return
        at, key = self._drop_at(event.position().toPoint()), self.currentItem().data(0, KEY_ROLE) if self.currentItem() else None
        if at and self._moves[1](key, *at):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if not self._moves:
            super().dropEvent(event)
            return
        at, key = self._drop_at(event.position().toPoint()), self.currentItem().data(0, KEY_ROLE) if self.currentItem() else None
        event.setDropAction(Qt.DropAction.IgnoreAction)  # the records move, and the list is drawn again: Qt moves nothing
        event.accept()
        if at and self._moves[1](key, *at):
            drop = self._moves[0]
            QTimer.singleShot(0, lambda: drop(key, *at))  # after the drag has finished with these rows

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        alt = event.modifiers() == Qt.KeyboardModifier.AltModifier
        if self._moves and alt and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.currentItem() is not None:
            self._moves[2](self.currentItem().data(0, KEY_ROLE), -1 if event.key() == Qt.Key.Key_Up else 1)
            return
        super().keyPressEvent(event)

    def set_columns(self, labels: list[str], widths: list[int] | None = None) -> None:
        """The columns: the first stretches, the others keep their widths."""
        self.setColumnCount(len(labels))
        self.setHeaderLabels(labels)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        widths = widths or [0] + [96] * (len(labels) - 1)
        self._widths = list(widths)
        for i in range(1, len(labels)):
            self.setColumnHidden(i, False)
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(i, widths[i])
        self._fit_columns()

    def _fit_columns(self) -> None:
        """In a narrow list its columns go, the one after the title first, as a date at the row's end says more than a state, so
        the title keeps enough room to read. They come back with the room. What they say is on the row's page beside it (release 5.58)."""
        if LOOK.classic or not self._widths:
            return
        shown = list(range(1, len(self._widths)))
        while shown and self.viewport().width() - sum(self._widths[i] for i in shown) < MIN_TITLE:
            shown.pop(0)
        for i in range(1, len(self._widths)):
            if self.isColumnHidden(i) == (i in shown):
                self.setColumnHidden(i, i not in shown)
                if i in shown:
                    self.setColumnWidth(i, self._widths[i])

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._fit_columns()
        self._sync_strips()
        if self._empty is not None:
            self._empty.setFixedWidth(self.viewport().width())

    def begin(self) -> None:
        """Start filling the list again. Changing the current row while filling doesn't count as picking."""
        self._building = True
        self._forget_strips()
        if self._empty is not None:
            self._empty.hide()
            self._empty.deleteLater()
            self._empty = None
        self.clear()

    def end(self, select: object | None = None) -> None:
        if select is not None:
            self.select_key(select)
        self._building = False
        self._relayout.start()
        self._hover_from_cursor()

    def add_row(self, parent: QTreeWidgetItem | None, key: object, cells: list[str], background: QColor | None = None,
                tip: str = "", selectable: bool = True, span: bool = False, edge: str | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self)
        item.setData(0, KEY_ROLE, key)
        if edge:
            item.setData(0, EDGE_ROLE, edge)
        for i, html in enumerate(cells):
            item.setData(i, HTML_ROLE, html)
            if background is not None:
                item.setBackground(i, background)
            if tip:
                item.setToolTip(i, tip)
        if not selectable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if span:
            item.setFirstColumnSpanned(True)
        return item

    def add_tick(self, item: QTreeWidgetItem, on: bool) -> None:
        """Give a row a tick box in its first column. Setting it doesn't send ``ticked``."""
        building, self._building = self._building, True
        try:
            item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        finally:
            self._building = building

    # ---- a row's actions (release 5.59): over the row on hover and when current, and as its right-click menu ----
    def set_actions(self, item: QTreeWidgetItem, actions: list[tuple[str, Callable[[], None], str]]) -> None:
        """Give a row its actions: (label, clicked, tooltip). The Classic look has a column for them, its last."""
        row = RowActions(actions)
        item.setData(0, ACTIONS_ROLE, row)
        if LOOK.classic:
            self.setItemWidget(item, self.columnCount() - 1, ActionStrip(row))

    def action_strip(self, item: QTreeWidgetItem) -> ActionStrip | None:
        """The row's strip, showing it if it wasn't. What tests click, as a person would after moving the mouse there."""
        if LOOK.classic:
            return self.itemWidget(item, self.columnCount() - 1)
        self._hover = item
        self._sync_strips()
        return next((s for s in self._strips if s.item is item), None)

    def _forget_strips(self) -> None:
        self._hover = None
        for strip in self._strips:
            strip.item = None
            strip.hide()
            strip.deleteLater()
        self._strips = []

    def _sync_strips(self) -> None:
        """A strip on the row under the mouse and on the current row, each at the end of the first column."""
        if LOOK.classic or self._building:
            return
        wanted: list[QTreeWidgetItem] = []
        for item in (self._hover, self.currentItem()):
            if item is not None and not any(item is x for x in wanted) and item.data(0, ACTIONS_ROLE) is not None:
                wanted.append(item)
        for strip in [s for s in self._strips if not any(s.item is x for x in wanted)]:
            self._strips.remove(strip)
            strip.hide()
            strip.deleteLater()
        end = self.header().sectionViewportPosition(0) + self.columnWidth(0)
        for item in wanted:
            strip = next((s for s in self._strips if s.item is item), None)
            if strip is None:
                strip = ActionStrip(item.data(0, ACTIONS_ROLE), item, self.viewport())
                self._strips.append(strip)
            if item is not self._hover and self._covers_words(item, end - strip.sizeHint().width()):  # the current row stays readable: hover shows them
                strip.hide()
                continue
            selected = item.isSelected()
            if strip.property("sel") != selected:
                strip.setProperty("sel", selected)
                strip.style().unpolish(strip)
                strip.style().polish(strip)
            rect = self.visualItemRect(item)
            if not rect.isValid() or not self.is_shown(item) or item.isHidden():
                strip.hide()
                continue
            width = min(strip.sizeHint().width(), end)
            strip.setGeometry(end - width, rect.top(), width, rect.height())
            strip.show()
            strip.raise_()

    def _covers_words(self, item: QTreeWidgetItem, at: int) -> bool:
        """Whether a strip starting at ``at`` would lie over the words in the row's first column."""
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDefaultStyleSheet(page_css())
        doc.setDocumentMargin(2)
        doc.setHtml(item.data(0, HTML_ROLE) or "")
        rect = self.visualRect(self.indexFromItem(item, 0))
        doc.setTextWidth(max(20, rect.width() - self.cell_pad - 3))
        return rect.left() + self.cell_pad + doc.idealWidth() > at

    def show_empty(self, text: str, label: str, clicked: Callable[[], None]) -> None:
        """An empty list's words and the one action that adds something (the playbook's empty states, release 5.61). Gone at the next ``begin``."""
        self._empty = QWidget(self.viewport(), objectName="emptyState")
        lay = QHBoxLayout(self._empty)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        lay.addWidget(QLabel(text))
        button = QPushButton(label)
        button.clicked.connect(lambda _=False: clicked())
        lay.addWidget(button)
        lay.addStretch()
        self._empty.setGeometry(0, 0, self.viewport().width(), self._empty.sizeHint().height())
        self._empty.show()

    def _hover_from_cursor(self) -> None:
        """The row under the mouse now: after the list is drawn again or scrolls, it's under a still mouse."""
        if LOOK.classic or self._building:
            return
        at = self.viewport().mapFromGlobal(QCursor.pos())
        self._hover = self.itemAt(at) if self.viewport().rect().contains(at) else None
        self._sync_strips()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().mouseMoveEvent(event)
        if not LOOK.classic:
            item = self.itemAt(event.position().toPoint())
            if item is not self._hover:
                self._hover = item
                self._sync_strips()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().leaveEvent(event)
        self._hover = None
        self._sync_strips()

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name
        at = self.viewport().mapFromGlobal(event.globalPos())
        item = self.itemAt(at) if event.reason() == event.Reason.Mouse else self.currentItem()
        row = item.data(0, ACTIONS_ROLE) if item is not None else None
        if row is None:
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        for label, clicked, tip in row.actions:
            action = menu.addAction(label, clicked)
            action.setToolTip(tip)
        menu.setToolTipsVisible(True)
        menu.exec(event.globalPos())

    def is_shown(self, item: QTreeWidgetItem) -> bool:
        """True when every parent of the row is expanded, so the row can be seen."""
        parent = item.parent()
        while parent is not None:
            if not parent.isExpanded():
                return False
            parent = parent.parent()
        return True

    def items(self):
        """Every row, depth first."""
        def go(item: QTreeWidgetItem):
            for i in range(item.childCount()):
                yield item.child(i)
                yield from go(item.child(i))
        yield from go(self.invisibleRootItem())

    def select_key(self, key: object) -> bool:
        """Make the first row with ``key`` current, and scroll to it. Doesn't count as picking."""
        building, self._building = self._building, True
        try:
            for item in self.items():
                if item.data(0, KEY_ROLE) == key:
                    parent = item.parent()
                    while parent is not None:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    self.setCurrentItem(item)
                    self.scrollToItem(item)
                    return True
            self.setCurrentItem(None)
            return False
        finally:
            self._building = building

    def keys(self) -> list[object]:
        return [item.data(0, KEY_ROLE) for item in self.items()]

    def drawRow(self, painter, option, index) -> None:  # noqa: N802 - Qt's name
        """The new look's marks at a row's left edge: the accent bar on the selected row, else a top-level task's colour."""
        super().drawRow(painter, option, index)
        if LOOK.classic:
            return
        first = index.siblingAtColumn(0)
        mark = tokens.colour("accent") if self.selectionModel().isSelected(first) else first.data(EDGE_ROLE)
        if mark:
            painter.fillRect(0, option.rect.top() + 2, 3, option.rect.height() - 4, QColor(mark))

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._building or column != 0 or item.data(0, Qt.ItemDataRole.CheckStateRole) is None:
            return
        key = item.data(0, KEY_ROLE)
        if key is not None:
            self.ticked.emit(key, item.checkState(0) == Qt.CheckState.Checked)

    # ---- the keyboard's focus ring (release 5.57): round the whole current row, once Tab has brought the keyboard here ----
    def _row_rect(self, item: QTreeWidgetItem) -> QRect:
        rect = self.visualItemRect(item)
        rect.setLeft(0)
        rect.setRight(self.viewport().width() - 1)
        return rect

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        item = self.currentItem()
        if (not LOOK.classic and item is not None and self.hasFocus()
                and self.window().testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange)):
            p = QPainter(self.viewport())
            paint_focus_ring(p, self._row_rect(item))
            p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, False)  # the mouse has taken over: no ring
        self.viewport().update()
        super().mousePressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().focusOutEvent(event)
        self.viewport().update()

    def _current_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        self._sync_strips()
        if self._building or current is None:
            return
        if not LOOK.classic and self.hasFocus():  # Qt redraws only a row's cell here: the ring goes round the whole row
            self.viewport().update(self._row_rect(current))
            if previous is not None:
                self.viewport().update(self._row_rect(previous))
        key = current.data(0, KEY_ROLE)
        if key is not None:
            self.picked.emit(key)
