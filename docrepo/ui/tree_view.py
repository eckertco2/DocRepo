"""The browse tool's middle pane list: a tree of rows.

Rows carry a key, such as ("task", "T000008"), that says what selecting them
opens. In the new look a row is one line at its view's height (the list rows
review, release 5.78): its first column a ``Line``, painted part by part and cut
with "…" to fit, and its other cells small pieces of HTML on one line. A
top-level task's row has its group's colour as an edge. The Classic look keeps
release 5.9's rows: HTML that wraps, tinted by group.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QCursor, QFont, QFontMetrics, QPainter, QPalette, QTextDocument, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QToolTip, QTreeWidget, QTreeWidgetItem, QWidget)

from docrepo.detail import chip, esc
from docrepo.ui import tokens
from docrepo.ui.icons import icon, icon_size, tinted
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
#: The new look's first column, a ``Line`` (release 5.78).
LINE_ROLE = Qt.ItemDataRole.UserRole + 5

GROUP_COLOURS = tuple(tokens.LIGHT[k] for k in tokens.GROUP_KEYS)
GREY = "#b8c1cb"  # Classic's, for a task with no group
#: How strongly a group's colour shows, by depth: top-level tasks most, each level down less.
TINTS = (0.15, 0.09, 0.05, 0.025)
ROW_MIN_HEIGHT = 26
#: The room a row's tick box takes, in Select mode.
CHECK_WIDTH = 22
#: The least room a list's first column keeps: in a narrower list its last columns go first (release 5.58).
MIN_TITLE = 160
#: A row in a two-line view (decision L1): Agendas, Documents, Activity and Search, whose second line is the substance.
TWO_LINE_ROW = 48
#: A row action's icon button, and the room at each end of their strip (decision L5).
ACTION_W, ACTION_PAD = 28, 6
#: An icon before a row's title, and the room after it.
ROW_ICON, ROW_ICON_GAP = 16, 8
#: The widest a column after the title grows to fit what it says.
MAX_CELL = 220

#: A task's state as the icon before its title (decision L7): the icon, and its colour's token.
STATE_ICONS = {"Not started": ("state-ns", "text2"), "In progress": ("state-ip", "accent"), "Parked": ("state-pk", "parked"),
               "Closed": ("state-cl", "text2")}
#: A row action's icon, by its words (decision L5). An action not here keeps its words.
ACTION_ICONS = {"Edit": "edit", "Note": "note", "Done": "state-cl", "Remove": "close", "Clear": "close", "Discussed": "state-cl",
                "Add to Today": "sun", "Make it a task": "task"}
#: The chips a row can carry, from the pages' chip classes: text colour, fill and whether it's semibold.
CHIPS = {"urgent": ("critical", "critical_bg", True), "pri-critical": ("on_accent", "critical", True), "new": ("caution", "caution_bg", False),
         "st-pk": ("parked", "parked_bg", False), "st-ip": ("accent", "info_bg", False), "st-cl": ("text2", "hover", False),
         "st-ns": ("text2", "hover", False), "lbl": ("text", "hover", False), "multi": ("accent", "info_bg", False),
         "routine": ("text", "hover", False), "count": ("text2", "hover", False)}
#: Marks drawn as coloured words, not chips: a key date's plant flag and deadline diamond.
MARKS = ("critical", "caution")


def state_icon(state: str) -> tuple[str, str]:
    return STATE_ICONS.get(state, STATE_ICONS["Not started"])


@dataclass
class Line:
    """A row's first column in the new look (the list rows review, release 5.78): one line, or two in a two-line view, painted
    by ``HtmlDelegate``. When it doesn't fit, its parts are cut in turn: the context first, then the quiet words, the lead,
    the chips, and the title last. ``html`` says the same words for Find, the tests and the Classic look."""

    title: str
    #: Drawn before the title: a task's state (decision L7), or the kind of thing the row is. ``icon_tip`` says it in words.
    icon: str = ""
    icon_colour: str = "text2"
    icon_tip: str = ""
    #: Quiet words before the title, such as the parents above it.
    lead: str = ""
    #: Chips after the title, only for exceptions such as Urgent: (text, chip class), or (text, "critical") for a coloured mark.
    chips: tuple[tuple[str, str], ...] = ()
    #: Quiet words after the title, such as its labels and how it repeats.
    muted: tuple[str, ...] = ()
    #: Quiet words last: the project, the people, "1 document".
    context: str = ""
    #: The second line, in a two-line view. None is a one-line row.
    second: str | None = None
    #: A parent's open subtasks, shown while it's folded (decision L8).
    count: int = 0
    #: The Classic look's bold top-level task (the new look has none, decision L2).
    strong: bool = False
    #: Struck through and quiet: done or closed.
    closed: bool = False
    #: All quiet: a parent kept for context.
    dim: bool = False

    def html(self, classic: bool = False) -> str:
        title = esc(self.title)
        if classic and self.strong:
            title = f"<b>{title}</b>"
        if self.closed:
            title = f'<s><span class="faint">{title}</span></s>'
        elif self.dim:
            title = f'<span class="faint">{title}</span>'
        out = (f'<span class="faint">{esc(self.lead)}</span> ' if self.lead else "") + title
        if self.count:
            out += f' <span class="faint">{self.count}</span>'
        for text, kind in self.chips:
            out += " " + (f'<span class="{kind}">{esc(text)}</span>' if kind in MARKS else chip(text, kind))
        if self.muted:
            out += f' <span class="faint">&nbsp;{esc(" · ".join(self.muted))}</span>'
        if self.context:
            out += f'<br><span class="sub">{esc(self.context)}</span>' if classic else f' <span class="faint">&nbsp;{esc(self.context)}</span>'
        if self.second:
            out += f'<br><span class="sub">{esc(self.second)}</span>'
        return out

    def words(self) -> str:
        """Everything the row says, as plain text, for its tooltip and for Find."""
        return " ".join(x for x in (self.icon_tip, self.lead, self.title, *(t for t, _ in self.chips), *self.muted, self.context, self.second or "") if x)


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
    """A row's actions. In the new look, icon buttons over the end of the row, where its date is, only while the row is under
    the mouse, so a list isn't a column of links and the title is never covered (release 5.78, decision L5). Each button's
    words are its accessible name and start its tooltip. In the Classic look they're links in a cell, always there."""

    def __init__(self, row: RowActions, item: QTreeWidgetItem | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="rowActions")
        self.item = item
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0) if LOOK.classic else lay.setContentsMargins(ACTION_PAD, 0, ACTION_PAD, 0)
        lay.setSpacing(4 if LOOK.classic else 0)
        for label, clicked, tip in row.actions:
            name = None if LOOK.classic else ACTION_ICONS.get(label)
            if name:
                b = QPushButton(objectName="rowIcon")
                b.setIcon(icon(name, tokens.colour("text2")))
                b.setIconSize(icon_size(16))
                b.setFixedSize(ACTION_W, ACTION_W)
                b.setToolTip(f"{label}: {tip}")
            else:
                b = QPushButton(label, objectName="rowLink")
                b.setToolTip(tip)
            b.setAccessibleName(label)
            b.clicked.connect(lambda _=False, c=clicked: c())
            lay.addWidget(b)
        if LOOK.classic:
            lay.addStretch()


def strip_width(row: RowActions) -> int:
    """How wide a row's strip of icon buttons is, so the row's words stop short of it."""
    return 2 * ACTION_PAD + sum(ACTION_W if a[0] in ACTION_ICONS else QFontMetrics(tokens.ui_font()).horizontalAdvance(a[0]) + 16 for a in row.actions)


class HtmlDelegate(QStyledItemDelegate):
    """Draws a row's cells. In the new look (release 5.78) a ``Line`` is painted part by part, and any other cell's HTML on one
    line, at the view's row height, cut with "…" when it doesn't fit. In the Classic look a cell's HTML wraps to the column's
    width, and the row grows to hold it."""

    def __init__(self, view: QTreeWidget) -> None:
        super().__init__(view)
        self.view = view

    def _doc(self, html: str, width: int, option: QStyleOptionViewItem, wrap: bool = True) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDefaultStyleSheet(page_css())  # the pages' colours, so chips look the same in lists
        doc.setDocumentMargin(2)
        if not wrap:
            o = QTextOption()
            o.setWrapMode(QTextOption.WrapMode.NoWrap)
            doc.setDefaultTextOption(o)
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
        line = None if LOOK.classic else index.data(LINE_ROLE)
        html = index.data(HTML_ROLE)
        if html is None and line is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else self.view.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        left = opt.rect.left()
        if opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:  # a tick box, drawn above: the words go after it
            left = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget).left()
        painter.save()
        if index.siblingAtColumn(0).data(DIM_ROLE):
            painter.setOpacity(0.5)
        if LOOK.classic:
            doc = self._doc(html, opt.rect.right() - left - self.view.cell_pad - 3, opt)
            top = opt.rect.top() + max(0, (opt.rect.height() - doc.size().height()) / 2)
            painter.translate(left + self.view.cell_pad, top)
            self._draw_doc(painter, doc)
        else:
            painter.setClipRect(opt.rect)
            rect = QRect(left + self.view.cell_pad, opt.rect.top(), opt.rect.right() - left - self.view.cell_pad - 3, opt.rect.height())
            if index.column() == 0:  # a hovered row's actions lie over its end: its words stop short of them
                strip = self.view.strip_left(self.view.itemFromIndex(index))
                if strip is not None:
                    rect.setRight(min(rect.right(), strip - 8))
            if line is not None:
                self._paint_line(painter, rect, line, opt, index)
            else:
                self._paint_html(painter, rect, html, opt)
        painter.restore()

    @staticmethod
    def _draw_doc(painter: QPainter, doc: QTextDocument) -> None:
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(tokens.colour("text")))
        doc.documentLayout().draw(painter, ctx)

    def _paint_html(self, painter: QPainter, rect: QRect, html: str, opt: QStyleOptionViewItem) -> None:
        """A cell's HTML on one line, in the middle of the row. When it's too long for its cell, its words, cut with "…"."""
        doc = self._doc(html, rect.width(), opt, wrap=False)
        if doc.idealWidth() <= rect.width() + 4 or "<br" in html:
            painter.translate(rect.left(), rect.top() + (rect.height() - doc.size().height()) / 2)
            self._draw_doc(painter, doc)
            return
        words = " ".join(doc.toPlainText().split())
        painter.setFont(opt.font)
        painter.setPen(QColor(tokens.colour("text2" if 'class="sub"' in html or 'class="faint"' in html else "text")))
        painter.drawText(rect.adjusted(2, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(opt.font).elidedText(words, Qt.TextElideMode.ElideRight, rect.width() - 2))

    # ---- a Line, part by part ----
    def _fonts(self, opt: QStyleOptionViewItem) -> tuple[QFont, QFont, QFont]:
        small = tokens.ui_font(tokens.CAPTION)
        return opt.font, small, tokens.ui_font(tokens.CAPTION, semibold=True)

    def _parts(self, line: Line, width: int, fm: QFontMetrics, chip_fm: QFontMetrics, folded: bool) -> list[tuple[str, str, int]]:
        """What the first line shows, left to right, as (part, text, width), cut to fit ``width``: the context goes first, then
        the quiet words, the lead, the chips and the count, and the title last, which is cut with "…" but never dropped."""
        gap = 8
        parts: list[list] = []  # [part, text, width, priority, can be cut]
        if line.lead:
            parts.append(["lead", line.lead, fm.horizontalAdvance(line.lead), 3, True])
        parts.append(["title", line.title, fm.horizontalAdvance(line.title), 9, True])
        if line.count and folded:  # a small neutral badge, so it can't be read as a label
            parts.append(["chip:count", str(line.count), chip_fm.horizontalAdvance(str(line.count)) + 12, 5, False])
        for text, kind in line.chips:
            w = fm.horizontalAdvance(text) if kind in MARKS else chip_fm.horizontalAdvance(text) + 12
            parts.append([f"chip:{kind}", text, w, 6, False])
        if line.muted:
            text = " · ".join(line.muted)
            parts.append(["muted", text, fm.horizontalAdvance(text), 2, True])
        if line.context:
            parts.append(["context", line.context, fm.horizontalAdvance(line.context), 1, True])

        def total() -> int:
            return sum(p[2] for p in parts) + gap * (len(parts) - 1)

        while total() > width and parts:
            p = min(parts, key=lambda x: x[3])
            room = p[2] - (total() - width)
            if p[0] == "title":
                p[1] = fm.elidedText(line.title, Qt.TextElideMode.ElideRight, max(0, room))
                p[2] = fm.horizontalAdvance(p[1])
                break
            if p[4] and room >= 48:
                p[1] = fm.elidedText(p[1], Qt.TextElideMode.ElideRight, room)
                p[2] = fm.horizontalAdvance(p[1])
            else:
                parts.remove(p)
        return [(p[0], p[1], p[2]) for p in parts]

    def _paint_line(self, painter: QPainter, rect: QRect, line: Line, opt: QStyleOptionViewItem, index: QModelIndex) -> None:
        font, small, chip_font = self._fonts(opt)
        fm, chip_fm, small_fm = QFontMetrics(font), QFontMetrics(chip_font), QFontMetrics(small)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        two = line.second is not None and rect.height() >= TWO_LINE_ROW
        line_h = fm.height() + 4
        first = QRect(rect.left(), rect.top() + 5, rect.width(), line_h) if two and line.second else QRect(rect)
        x = rect.left() + 2
        if line.icon:
            scale = painter.device().devicePixelRatioF()
            painter.drawPixmap(QPoint(x, first.center().y() - ROW_ICON // 2 + 1), tinted(line.icon, tokens.colour(line.icon_colour), ROW_ICON, scale))
            x += ROW_ICON + ROW_ICON_GAP
        item = self.view.itemFromIndex(index)
        folded = item is not None and item.childCount() > 0 and not item.isExpanded()
        quiet, normal = QColor(tokens.colour("text2")), QColor(tokens.colour("text2" if line.closed or line.dim else "text"))
        for part, text, w in self._parts(line, rect.right() - x, fm, chip_fm, folded):
            box = QRect(x, first.top(), w + 2, first.height())
            if part.startswith("chip:") and part[5:] not in MARKS:
                fg, bg, bold = CHIPS.get(part[5:], CHIPS["lbl"])
                pill = QRect(x, first.center().y() - 9, w, 19)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(tokens.colour(bg)))
                painter.drawRoundedRect(pill, 4, 4)
                painter.setFont(chip_font if bold else small)
                painter.setPen(QColor(tokens.colour(fg)))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
            else:
                f = QFont(font)
                if part == "title" and line.closed:
                    f.setStrikeOut(True)
                painter.setFont(f)
                painter.setPen(normal if part == "title" else QColor(tokens.colour(part[5:])) if part.startswith("chip:") else quiet)
                painter.drawText(box, Qt.AlignmentFlag.AlignVCenter, text)
            x += w + 8
        if two and line.second:
            left = rect.left() + 2 + (ROW_ICON + ROW_ICON_GAP if line.icon else 0)
            second = QRect(left, first.bottom() - 1, rect.right() - left, small_fm.height() + 4)
            painter.setFont(small)
            painter.setPen(quiet)
            painter.drawText(second, Qt.AlignmentFlag.AlignVCenter, small_fm.elidedText(" ".join(line.second.split()), Qt.TextElideMode.ElideRight, second.width()))

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802 - Qt's name
        """Over a row's icon, what the icon means (decision L7); elsewhere, the row's own tooltip."""
        line = None if LOOK.classic else index.data(LINE_ROLE)
        if line is not None and line.icon_tip and index.column() == 0:
            left = option.rect.left() + self.view.cell_pad + 2
            if left - 2 <= event.pos().x() <= left + ROW_ICON + 2:
                QToolTip.showText(event.globalPos(), line.icon_tip, view)
                return True
        return super().helpEvent(event, view, option, index)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        html = index.data(HTML_ROLE)
        if not LOOK.classic:  # one height per view (decision L1): its row height, or two lines for a two-line row
            line = index.data(LINE_ROLE)
            if html is None and line is None:
                return super().sizeHint(option, index)
            return QSize(1, TWO_LINE_ROW if line is not None and line.second is not None and self.view.two_lines else self.view.row_height)
        if html is None:
            return super().sizeHint(option, index)
        doc = self._doc(html, self._width(index), option)
        return QSize(int(doc.idealWidth()), max(ROW_MIN_HEIGHT, int(doc.size().height()) + 6))


class RowTree(QTreeWidget):
    """The list of rows. ``picked`` sends the key of the row that became current, by click or keyboard. Rows given a tick box
    (``add_tick``) send ``ticked`` with their key when it's ticked or cleared by hand."""

    picked = Signal(object)
    ticked = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.cell_pad = 3  # the room before each cell's text; the sidebar's views have more
        #: The new look's row height for the view shown, and whether its rows with a second line take two lines (``set_density``).
        self.row_height = tokens.TREE_ROW
        self.two_lines = False
        self.setItemDelegate(HtmlDelegate(self))
        self.setUniformRowHeights(not LOOK.classic)
        self.setWordWrap(LOOK.classic)
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

    def set_density(self, height: int, two_lines: bool = False) -> None:
        """The view's row height (decision L1): ``tokens.TREE_ROW`` where rows nest, ``tokens.LIST_ROW`` elsewhere. In a view with
        ``two_lines``, a row whose ``Line`` has a second line is ``TWO_LINE_ROW`` high, and its headings keep ``height``."""
        self.row_height, self.two_lines = height, two_lines
        if not LOOK.classic:
            self.setUniformRowHeights(not two_lines)

    def end(self, select: object | None = None) -> None:
        if select is not None:
            self.select_key(select)
        self._building = False
        self._size_columns()
        self._relayout.start()
        self._hover_from_cursor()

    def _size_columns(self) -> None:
        """In the new look a column after the title is as wide as the widest thing in it, from its set width up to ``MAX_CELL``,
        so a date such as "◆ 31 Oct · 23 d" is never cut. Its words never wrap."""
        if LOOK.classic or not self._widths:
            return
        widths = list(self._widths)
        option = QStyleOptionViewItem()
        option.font = self.font()
        delegate = self.itemDelegate()
        for item in self.items():
            for i in range(1, self.columnCount()):
                html = item.data(i, HTML_ROLE)
                if html and not item.isFirstColumnSpanned():
                    need = int(delegate._doc(html, 1000, option, wrap=False).idealWidth()) + self.cell_pad + 12
                    widths[i] = max(widths[i], min(MAX_CELL, need))
        if widths != self._widths:
            self._widths = widths
            for i in range(1, len(widths)):
                self.setColumnWidth(i, widths[i])
            self._fit_columns()

    def add_row(self, parent: QTreeWidgetItem | None, key: object, cells: list, background: QColor | None = None,
                tip: str = "", selectable: bool = True, span: bool = False, edge: str | None = None) -> QTreeWidgetItem:
        """A row. Its first cell may be a ``Line`` (the new look paints it; its HTML is kept for Find and the Classic look), and
        the rest are HTML."""
        item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self)
        item.setData(0, KEY_ROLE, key)
        if edge:
            item.setData(0, EDGE_ROLE, edge)
        for i, html in enumerate(cells):
            if isinstance(html, Line):
                item.setData(i, LINE_ROLE, html)
                html = html.html(LOOK.classic)
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
        """A strip on the row under the mouse, at the row's right end, over its date (decision L5). The current row shows its
        date; its actions are on hover, in its right-click menu and on their keys."""
        if LOOK.classic or self._building:
            return
        item = self._hover if self._hover is not None and self._hover.data(0, ACTIONS_ROLE) is not None else None
        for strip in [s for s in self._strips if s.item is not item]:
            self._strips.remove(strip)
            strip.hide()
            strip.deleteLater()
        if item is None:
            return
        strip = next((s for s in self._strips if s.item is item), None)
        if strip is None:
            strip = ActionStrip(item.data(0, ACTIONS_ROLE), item, self.viewport())
            self._strips.append(strip)
        selected = item.isSelected()
        if strip.property("sel") != selected:
            strip.setProperty("sel", selected)
            strip.style().unpolish(strip)
            strip.style().polish(strip)
        rect = self.visualItemRect(item)
        if not rect.isValid() or not self.is_shown(item) or item.isHidden():
            strip.hide()
            return
        width = strip_width(item.data(0, ACTIONS_ROLE))
        strip.setGeometry(self.viewport().width() - width, rect.top(), width, rect.height())
        strip.show()
        strip.raise_()
        self.viewport().update(rect)  # its words stop short of the strip

    def strip_left(self, item: QTreeWidgetItem | None) -> int | None:
        """Where the row's strip of actions starts, while the row is under the mouse, so its words stop short of it."""
        if LOOK.classic or item is None or item is not self._hover or item.data(0, ACTIONS_ROLE) is None:
            return None
        return self.viewport().width() - strip_width(item.data(0, ACTIONS_ROLE))

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
                for was in (self._hover, item):  # the rows' words make room for the strip, or take it back
                    if was is not None:
                        self.viewport().update(self._row_rect(was))
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
