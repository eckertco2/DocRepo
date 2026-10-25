"""The browse tool's middle pane list: a tree of rows whose cells are small pieces of HTML.

Rows carry a key, such as ("task", "T000008"), that says what selecting them
opens. Each top-level task's group has a colour band: four muted colours in
turn, lighter for each level down, like the mockup's task tree.
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QPalette, QTextDocument
from PySide6.QtWidgets import QHeaderView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem

from docrepo.ui import tokens
from docrepo.ui.look import LOOK
from docrepo.ui.style import page_css

KEY_ROLE = Qt.ItemDataRole.UserRole
HTML_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row kept only for context, drawn faded: a parent of what Find in this view found (mods log round 2, M0026).
DIM_ROLE = Qt.ItemDataRole.UserRole + 2
#: The new look's colour edge on a top-level task's row: its group's colour (decision 9), never a tint across its rows.
EDGE_ROLE = Qt.ItemDataRole.UserRole + 3

GROUP_COLOURS = ("#3b78c4", "#2e9483", "#c08419", "#8460c2")
GREY = "#b8c1cb"
#: How strongly a group's colour shows, by depth: top-level tasks most, each level down less.
TINTS = (0.15, 0.09, 0.05, 0.025)
ROW_MIN_HEIGHT = 26
#: The new look's rows: 28 px, with a 16 px indent (decision 3).
NEW_ROW_MIN_HEIGHT = tokens.TREE_ROW
#: The room a row's tick box takes, in Select mode.
CHECK_WIDTH = 22


def tint(group: int, depth: int) -> QColor | None:
    """A group's colour mixed into white, for a row at ``depth``. The new look has none: the group's colour is an edge on
    its top-level row instead (``edge``)."""
    if not LOOK.classic:
        return None
    base = QColor(GREY if group < 0 else GROUP_COLOURS[group % len(GROUP_COLOURS)])
    p = TINTS[min(depth, len(TINTS) - 1)]
    return QColor(round(255 + (base.red() - 255) * p), round(255 + (base.green() - 255) * p), round(255 + (base.blue() - 255) * p))


def edge(group: int, depth: int) -> str | None:
    """The new look's colour edge for a row: its group's colour on a top-level row, nothing below it."""
    return None if LOOK.classic or depth or group < 0 else tokens.group_colour(group)


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
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor("#1a1f25"))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        html = index.data(HTML_ROLE)
        if html is None:
            return super().sizeHint(option, index)
        doc = self._doc(html, self._width(index), option)
        least = ROW_MIN_HEIGHT if LOOK.classic else NEW_ROW_MIN_HEIGHT
        return QSize(int(doc.idealWidth()), max(least, int(doc.size().height()) + 6))


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
            self.setStyleSheet("QTreeWidget { border: none; font-family: 'Segoe UI'; font-size: 10pt; }"
                               "QTreeWidget::item:selected { background: #dbe8f5; color: #1a1f25; }"
                               "QHeaderView::section { color: #87919c; font-size: 8pt; border: none; border-bottom: 1px solid #d6dce3;"
                               " padding: 3px 6px; background: #ffffff; }")
        self._building = False
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(60)
        self._relayout.timeout.connect(self.doItemsLayout)
        self.header().sectionResized.connect(lambda *_: self._relayout.start())
        self.currentItemChanged.connect(self._current_changed)
        self.itemChanged.connect(self._item_changed)
        self.set_columns(["Title", "State", "Due"])

    def set_columns(self, labels: list[str], widths: list[int] | None = None) -> None:
        """The columns: the first stretches, the others keep their widths."""
        self.setColumnCount(len(labels))
        self.setHeaderLabels(labels)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        widths = widths or [0] + [96] * (len(labels) - 1)
        for i in range(1, len(labels)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(i, widths[i])

    def begin(self) -> None:
        """Start filling the list again. Changing the current row while filling doesn't count as picking."""
        self._building = True
        self.clear()

    def end(self, select: object | None = None) -> None:
        if select is not None:
            self.select_key(select)
        self._building = False
        self._relayout.start()

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

    def _current_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if self._building or current is None:
            return
        key = current.data(0, KEY_ROLE)
        if key is not None:
            self.picked.emit(key)
