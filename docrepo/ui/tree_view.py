"""The browse tool's middle pane list: a tree of rows.

Rows carry a key, such as ("task", "T000008"), that says what selecting them
opens. A row is one line at its view's height (the list rows review, release
5.78): its first column a ``Line``, painted part by part and cut with "…" to
fit, and its other cells small pieces of HTML on one line. A top-level task's
row has its group's colour as an edge.
"""
from __future__ import annotations

import contextlib
import html as html_lib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QCursor, QFont, QFontMetrics, QPainter, QPalette, QTextDocument,
                           QTextOption)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QToolTip, QTreeWidget, QTreeWidgetItem, QWidget)

from docrepo.detail import chip, esc
from docrepo.model import PRIORITY_NAMES
from docrepo.task_tile import fit_title
from docrepo.ui import tokens
from docrepo.ui.icons import icon, icon_size, tinted
from docrepo.ui.look import paint_focus_ring
from docrepo.ui.style import page_css
from docrepo.ui.task_tile import FLAG, KIND, STATE_ICONS, TICK_SLOT, marks_width, paint_marks, paint_ticks

KEY_ROLE = Qt.ItemDataRole.UserRole
HTML_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row kept only for context, drawn faded: a parent of what Find in this view found (mods log round 2, M0026).
DIM_ROLE = Qt.ItemDataRole.UserRole + 2
#: A task's priority as its row's left edge (release 5.81, decision L9): each bucket's colour token. An unranked or closed task
#: has none. It took the edge from the top-level task's colour (release 5.57), which stays on the Timeline and the board.
PRIORITY_EDGES = {"critical": "pri_critical", "high": "pri_high", "medium": "pri_medium", "parking": "pri_parking"}
#: A row's actions, a ``RowActions`` (release 5.59).
ACTIONS_ROLE = Qt.ItemDataRole.UserRole + 4
#: A row's first column, a ``Line`` (release 5.78).
LINE_ROLE = Qt.ItemDataRole.UserRole + 5
#: On a task's state: the task, so the state is a button that opens the state menu (release 5.76, decision 360). It's on
#: the first column, whose icon is the state (the list rows review's decision L7).
STATE_ROLE = Qt.ItemDataRole.UserRole + 6
#: What a row move calls the row, when it isn't the row's key (release 5.148): a Today item's number, as ("today", 7), since
#: a task's row is keyed by its task and a note's may have no key. ``allow_row_moves``' callbacks get it.
MOVE_ROLE = Qt.ItemDataRole.UserRole + 7
#: A row's lines for its right-click menu only, a ``RowActions`` (release 5.148): ``set_menu_lines``.
MENU_ROLE = Qt.ItemDataRole.UserRole + 8
#: A hairline over a row, in this colour (release 5.176, the urgency plan's decision 821): between a Today band's urgent tasks
#: and the rest, drawn in the gap above the row, so it takes no height of its own.
RULE_ROLE = Qt.ItemDataRole.UserRole + 9
#: The current task's row under Now on Today (release 5.177, the current task plan's decision 828): the ``now`` ground and
#: the accent edge.
NOW_ROLE = Qt.ItemDataRole.UserRole + 10
#: A group's head (release 5.183, the redesign's decision 856): a ``Head``, painted as a small grey label with no band.
HEAD_ROLE = Qt.ItemDataRole.UserRole + 11

#: The categories' colours, read from the active theme when they're drawn (release 5.180).
GROUP_COLOURS = tokens.LiveList(tokens.GROUP_KEYS)
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

#: A task's state as the icon before its title (decision L7) is ``task_tile.STATE_ICONS``, imported: one recipe for every
#: tile since release 5.168 (decision 786).
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
#: Flat rows on white (release 5.183, the redesign's decision 850, retiring decision 571's tiles): a row's rounded ground stands
#: ``ROW_INSET`` from the pane's left and right edges, and its last words stop ``ROW_END`` inside it.
ROW_INSET, ROW_END = 6, 10
#: A task's priority mark (decision L9), in the gutter left of the ground: its left, its width and its height.
EDGE_X, EDGE_W, EDGE_H = 2, 3, 16
#: A group head's dot (Today's bands), and the room after it.
HEAD_DOT, HEAD_DOT_GAP = 7, 7
#: The depth ticks' slot and the room after it, before the state circle, in a flat list (decision 570).
TICKS_W = TICK_SLOT + 2


def state_icon(state: str) -> tuple[str, str]:
    return STATE_ICONS.get(state, STATE_ICONS["Not started"])


@dataclass
class Line:
    """A row's first column (the list rows review, release 5.78): one line, or two in a two-line view, painted
    by ``HtmlDelegate``. When it doesn't fit, its parts are cut in turn: the context first, then the quiet words, the lead,
    the chips, and the title last. ``html`` says the same words for Find and the tests."""

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
    #: A top-level task. Drawn no differently (no bold top-level task, decision L2); its callers still set it.
    strong: bool = False
    #: Struck through and quiet: done or closed.
    closed: bool = False
    #: All quiet: a parent kept for context.
    dim: bool = False
    # The task tile's parts (release 5.138, the task tile plan, decisions 565 to 570). A tile's title is cut at its first
    # sentence, then its first clause, before its end (565).
    tile: bool = False
    #: Urgent, as a small red flag after the title (569).
    flag: bool = False
    #: The two-parents mark's tooltip, or "" (570).
    parents: str = ""
    #: Generations above the task, as ticks before its state in a flat list (570); -1 where the list indents instead.
    depth: int = -1
    depth_tip: str = ""
    #: The marks' slots at the line's right end (566): each a ``task_tile.Mark``, or None for an empty slot.
    marks: tuple = ()
    #: The kind's mark between the state and the title (release 5.168, decision 786): its icon ("kind-parent" or
    #: "kind-routine", ``task_tile.kind_mark``) and its words; "" for a single task.
    kind: str = ""
    kind_tip: str = ""

    @property
    def icon_offset(self) -> int:
        """How far the state's icon sits from the line's start: past the depth ticks, in a flat list."""
        return TICKS_W if self.depth >= 0 else 0

    def html(self) -> str:
        title = esc(self.title)
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
            out += f' <span class="faint">&nbsp;{esc(self.context)}</span>'
        if self.second:
            out += f'<br><span class="sub">{esc(self.second)}</span>'
        return out

    def words(self) -> str:
        """Everything the row says, as plain text, for its tooltip and for Find."""
        return " ".join(x for x in (self.icon_tip, self.lead, self.title, "Urgent" if self.flag else "", *(t for t, _ in self.chips), *self.muted,
                                    self.context, self.second or "") if x)


def tint(group: int, depth: int) -> QColor | None:
    """A row's ground by its group, for a row at ``depth``: none, as the group's colour is an edge on its top-level row
    instead (``edge``)."""
    return None


def group_ground() -> QColor:
    """The sign of a group's head, passed as ``add_row``'s ``background``: since release 5.183 (decision 856) a head paints no
    band, so this is never set on the row, and a row given it that can't be selected and says ``<b>…</b>`` is a ``Head``."""
    return QColor(tokens.colour("base"))


@dataclass
class Head:
    """A group's head (release 5.183, the redesign's decision 856): a small grey semibold name, its count and any words after
    it, on one line, with no band. ``dot`` is a colour for a dot before the name (Today's bands); ``tag`` is the view's own,
    such as Today's band key."""

    name: str
    count: str = ""
    sub: str = ""
    dot: str = ""
    tag: str = ""


_TAGS = re.compile(r"<[^>]+>")
_COUNT = re.compile(r"[\d,\s]+")


def _plain(markup: str) -> str:
    return " ".join(html_lib.unescape(_TAGS.sub(" ", markup)).replace("\xa0", " ").split())


def head_of(markup: str) -> Head:
    """A head from the HTML its caller wrote (``<b>Name</b> <span class="sub">12</span>``): the words inside the first
    ``<b>…</b>`` are the name; the plain text of the rest, a leading "·" dropped, is the count when it's digits, commas and
    spaces only, else the words after the name."""
    m = re.search(r"<b>(.*?)</b>", markup, re.S)
    if m is None:
        return Head(_plain(markup))
    rest = _plain(markup[m.end():]).lstrip("·").strip()
    if rest and _COUNT.fullmatch(rest):
        return Head(_plain(m.group(1)), count=rest)
    return Head(_plain(m.group(1)), sub=rest)


def with_actions(labels: list[str], widths: list[int], width: int) -> tuple[list[str], list[int]]:
    """A list's columns: a row's actions take no column (``width`` is unused), as they show over the row."""
    return (labels, widths)


class RowActions:
    """What a row can do: (label, clicked, tooltip) for each. A plain object, so it comes back from the row as it went in."""

    def __init__(self, actions: list[tuple[str, Callable[[], None], str]]) -> None:
        self.actions = actions


class ActionStrip(QWidget):
    """A row's actions: icon buttons over the end of the row, where its date is, only while the row is under
    the mouse, so a list isn't a column of links and the title is never covered (release 5.78, decision L5). Each button's
    words are its accessible name and start its tooltip."""

    def __init__(self, row: RowActions, item: QTreeWidgetItem | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="rowActions")
        self.item = item
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(ACTION_PAD, 0, ACTION_PAD, 0)
        lay.setSpacing(0)
        for label, clicked, tip in row.actions:
            name = ACTION_ICONS.get(label)
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


def strip_width(row: RowActions) -> int:
    """How wide a row's strip of icon buttons is, so the row's words stop short of it."""
    return 2 * ACTION_PAD + sum(ACTION_W if a[0] in ACTION_ICONS else QFontMetrics(tokens.ui_font()).horizontalAdvance(a[0]) + 16 for a in row.actions)


class HtmlDelegate(QStyledItemDelegate):
    """Draws a row's cells (release 5.78): a ``Line`` is painted part by part, and any other cell's HTML on one
    line, at the view's row height, cut with "…" when it doesn't fit."""

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

    def paint(self, painter, option, index) -> None:  # noqa: D102 - Qt's
        line = index.data(LINE_ROLE)
        html = index.data(HTML_ROLE)
        if html is None and line is None:
            super().paint(painter, option, index)
            return
        head = index.siblingAtColumn(0).data(HEAD_ROLE)
        if head is not None:  # a group's head: a small grey label, no band (release 5.183, decision 856)
            if index.column() == 0:
                self._paint_head(painter, option, head)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else self.view.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        left = opt.rect.left()
        if opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:  # a tick box, drawn above: the words go after it
            left = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget).left()
        # A state that's a button, under the mouse or with its menu open, has a backplate (release 5.76, decision 360): round
        # the state's icon before the title (decision L7).
        lit = index.data(STATE_ROLE) is not None and self.view.state_lit(index)
        painter.save()
        if index.siblingAtColumn(0).data(DIM_ROLE):
            painter.setOpacity(0.5)
        painter.setClipRect(opt.rect)
        rect = QRect(left + self.view.cell_pad, opt.rect.top(), opt.rect.right() - left - self.view.cell_pad - 3, opt.rect.height())
        if self.view.is_last_shown(index.column()) or (index.column() == 0 and self.view.itemFromIndex(index).isFirstColumnSpanned()):
            # the row's ground stops ROW_INSET short of the pane's edge, so its last words stop sooner (release 5.183)
            rect.setRight(min(rect.right(), self.view.viewport().width() - ROW_INSET - ROW_END))
        if index.column() == 0:  # a hovered row's actions lie over its end: its words stop short of them
            strip = self.view.strip_left(self.view.itemFromIndex(index))
            if strip is not None:
                rect.setRight(min(rect.right(), strip - 8))
        if line is not None:
            self._paint_line(painter, rect, line, opt, index, lit)
        else:
            self._paint_html(painter, rect, html, opt)
        painter.restore()

    @staticmethod
    def _plate(painter: QPainter, rect: QRect) -> None:
        """The backplate under a state that's a button."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.colour("pressed")))
        painter.drawRoundedRect(rect, tokens.RADIUS_S, tokens.RADIUS_S)
        painter.restore()

    def _paint_head(self, painter: QPainter, option: QStyleOptionViewItem, head: Head) -> None:
        """A group's head (release 5.183, decision 856): on one line in the middle of the row, from the cell's own left, the dot
        when there is one, the name small and semibold in the third grey, then its count and any words after it, small and
        regular, cut with "…" at the row's end. No fill and no line."""
        r = option.rect
        right = self.view.viewport().width() - ROW_INSET - ROW_END
        x = r.left() + self.view.cell_pad + 2
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(QRect(r.left(), r.top(), max(0, right - r.left()), r.height()))
        if head.dot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(head.dot))
            painter.drawEllipse(QRectF(x, r.center().y() - HEAD_DOT / 2 + 1, HEAD_DOT, HEAD_DOT))
            x += HEAD_DOT + HEAD_DOT_GAP
        name_font, rest_font = tokens.ui_font(tokens.LABEL, semibold=True), tokens.ui_font(tokens.LABEL)
        nfm, rfm = QFontMetrics(name_font), QFontMetrics(rest_font)
        painter.setPen(QColor(tokens.colour("text3")))
        painter.setFont(name_font)
        name = nfm.elidedText(head.name, Qt.TextElideMode.ElideRight, max(0, right - x))
        painter.drawText(QRect(x, r.top(), max(0, right - x), r.height()), Qt.AlignmentFlag.AlignVCenter, name)
        x += nfm.horizontalAdvance(name) + 6
        rest = " ".join(w for w in (head.count, head.sub) if w)
        if rest and x < right:
            painter.setFont(rest_font)
            painter.drawText(QRect(x, r.top(), right - x, r.height()), Qt.AlignmentFlag.AlignVCenter,
                             rfm.elidedText(rest, Qt.TextElideMode.ElideRight, right - x))
        painter.restore()

    @staticmethod
    def icon_box(cell: QRect) -> QRect:
        """Where a one-line row's icon sits in its first cell, with 3 px round it: the state's button."""
        left = cell.left() + 2
        top = cell.center().y() - ROW_ICON // 2 + 1
        return QRect(left - 3, top - 3, ROW_ICON + 6, ROW_ICON + 6)

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
        the quiet words, the lead, the chips and the count, then a tile's two-parents mark and flag, and the title last, which
        is cut but never dropped: a tile's at its first sentence or clause (decision 565), any other with "…"."""
        gap = 8
        parts: list[list] = []  # [part, text, width, priority, can be cut]
        if line.kind:  # the kind's mark, never dropped; drawn into the gap after it, so it sits close to the title (decision 786)
            parts.append(["kind", line.kind_tip, KIND - 3, 10, False])
        if line.lead:
            parts.append(["lead", line.lead, fm.horizontalAdvance(line.lead), 3, True])
        parts.append(["title", line.title, fm.horizontalAdvance(line.title), 9, True])
        if line.flag:
            parts.append(["flag", "Urgent", FLAG, 8, False])
        if line.parents:
            parts.append(["parents", line.parents, FLAG, 7, False])
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
                room = max(0, room)
                if line.tile:
                    p[1] = fit_title(line.title, room, fm.horizontalAdvance, lambda s, w: fm.elidedText(s, Qt.TextElideMode.ElideRight, int(w)))
                else:
                    p[1] = fm.elidedText(line.title, Qt.TextElideMode.ElideRight, room)
                p[2] = fm.horizontalAdvance(p[1])
                break
            if p[4] and room >= 48:
                p[1] = fm.elidedText(p[1], Qt.TextElideMode.ElideRight, room)
                p[2] = fm.horizontalAdvance(p[1])
            else:
                parts.remove(p)
        return [(p[0], p[1], p[2]) for p in parts]

    def _layout(self, line: Line, rect: QRect, opt: QStyleOptionViewItem, index: QModelIndex):
        """Where each part of a ``Line`` goes in ``rect``: its first line's rectangle, whether it shows two, where the depth
        ticks and the icon start, the parts as (part, text, rectangle), and where the marks end. One layout for painting and
        for tooltips."""
        font, _small, chip_font = self._fonts(opt)
        fm, chip_fm = QFontMetrics(font), QFontMetrics(chip_font)
        two = line.second is not None and rect.height() >= TWO_LINE_ROW
        first = QRect(rect.left(), rect.top() + 5, rect.width(), fm.height() + 4) if two and line.second else QRect(rect)
        x = rect.left() + 2
        ticks = None
        if line.depth >= 0:
            ticks, x = x, x + TICKS_W
        icon_at = None
        if line.icon:
            icon_at, x = x, x + ROW_ICON + ROW_ICON_GAP
        right = rect.right()
        marks_right = None
        if line.marks:  # the marks keep the line's end, in fixed slots, so they line up down a list (decision 566)
            marks_right = right - 2
            right -= marks_width(line.marks) + 10
        item = self.view.itemFromIndex(index)
        folded = item is not None and item.childCount() > 0 and not item.isExpanded()
        parts = []
        for part, text, w in self._parts(line, right - x, fm, chip_fm, folded):
            parts.append((part, text, QRect(x, first.top(), w + 2, first.height())))
            x += w + 8
        return first, two, ticks, icon_at, parts, marks_right

    def _paint_line(self, painter: QPainter, rect: QRect, line: Line, opt: QStyleOptionViewItem, index: QModelIndex, lit: bool = False) -> None:
        font, small, chip_font = self._fonts(opt)
        small_fm = QFontMetrics(small)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        first, two, ticks, icon_at, parts, marks_right = self._layout(line, rect, opt, index)
        mid = first.center().y() + 1
        scale = painter.device().devicePixelRatioF()
        if ticks is not None:
            paint_ticks(painter, ticks, mid, line.depth)
        if icon_at is not None:
            if lit:  # the state's icon is its menu's button (release 5.76 on the list rows review's decision L7)
                self._plate(painter, self.icon_box(first.adjusted(icon_at - rect.left() - 2, 0, 0, 0)))
            painter.drawPixmap(QPoint(icon_at, first.center().y() - ROW_ICON // 2 + 1), tinted(line.icon, tokens.colour(line.icon_colour), ROW_ICON, scale))
        quiet, normal = QColor(tokens.colour("text2")), QColor(tokens.colour("text2" if line.closed or line.dim else "text"))
        for part, text, box in parts:
            x, w = box.left(), box.width() - 2
            if part == "kind":
                painter.drawPixmap(QPoint(x, mid - KIND // 2), tinted(line.kind, tokens.colour("text2"), KIND, scale))
            elif part in ("flag", "parents"):  # Urgent's flag (decision 569) and the two-parents mark (570)
                name, colour = ("urgent", "critical") if part == "flag" else ("parents", "text2")
                painter.drawPixmap(QPoint(x, mid - FLAG // 2), tinted(name, tokens.colour(colour), FLAG, scale))
            elif part.startswith("chip:") and part[5:] not in MARKS:
                fg, bg, bold = CHIPS.get(part[5:], CHIPS["lbl"])
                pill = QRect(x, first.center().y() - 9, w, 19)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(tokens.colour(bg)))
                painter.drawRoundedRect(pill, tokens.RADIUS_S, tokens.RADIUS_S)
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
        if marks_right is not None:
            paint_marks(painter, marks_right, mid, line.marks, scale)
        if two and line.second:
            left = rect.left() + 2 + line.icon_offset + (ROW_ICON + ROW_ICON_GAP if line.icon else 0)
            second = QRect(left, first.bottom() - 1, rect.right() - left, small_fm.height() + 4)
            painter.setFont(small)
            painter.setPen(quiet)
            painter.drawText(second, Qt.AlignmentFlag.AlignVCenter, small_fm.elidedText(" ".join(line.second.split()), Qt.TextElideMode.ElideRight, second.width()))

    def line_tip(self, line: Line, option: QStyleOptionViewItem, index: QModelIndex, pos: QPoint) -> str | None:
        """What the part of a ``Line`` under ``pos`` says: a tile's depth ticks, flag, two-parents mark or a mark; None
        elsewhere. The state's icon is ``helpEvent``'s own."""
        rect = QRect(option.rect.left() + self.view.cell_pad, option.rect.top(), option.rect.width() - self.view.cell_pad - 3, option.rect.height())
        first, _two, ticks, _icon_at, parts, marks_right = self._layout(line, rect, option, index)
        mid = first.center().y() + 1
        if ticks is not None and line.depth > 0 and ticks <= pos.x() < ticks + TICK_SLOT:
            return line.depth_tip or None
        for part, text, box in parts:
            if part in ("flag", "parents", "kind") and box.adjusted(0, 0, 3, 0).contains(pos):
                return text
        if marks_right is not None:
            x = marks_right - marks_width(line.marks)
            for mk in line.marks:
                if mk is not None and QRect(x, mid - 8, 14, 16).contains(pos):
                    return mk.tip
                x += 17
        return None

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802 - Qt's name
        """Over a row's icon, what the icon means (decision L7); over a tile's ticks, flag, two-parents mark or marks, what
        each says (decisions 566 to 570); elsewhere, the row's own tooltip."""
        line = index.data(LINE_ROLE)
        if line is not None and index.column() == 0:
            left = option.rect.left() + self.view.cell_pad + 2 + line.icon_offset
            if line.icon_tip and left - 2 <= event.pos().x() <= left + ROW_ICON + 2:
                tip = line.icon_tip + (". Click to change the state." if index.data(STATE_ROLE) else "")
                QToolTip.showText(event.globalPos(), tip, view)
                return True
            said = self.line_tip(line, option, index, event.pos())
            if said:
                QToolTip.showText(event.globalPos(), said, view)
                return True
        bucket = self.view.row_priority(index)
        if bucket:  # the row's tooltip names its priority, as its edge shows it only by colour (decision L9)
            said = f"Priority: {PRIORITY_NAMES.get(bucket, bucket)}"
            tip = index.data(Qt.ItemDataRole.ToolTipRole) or index.siblingAtColumn(0).data(Qt.ItemDataRole.ToolTipRole) or ""
            QToolTip.showText(event.globalPos(), said if event.pos().x() <= 8 or not tip else "\n".join((tip, said)), view)
            return True
        return super().helpEvent(event, view, option, index)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        html = index.data(HTML_ROLE)
        # one height per view (decision L1): its row height, or two lines for a two-line row
        line = index.data(LINE_ROLE)
        if html is None and line is None:
            return super().sizeHint(option, index)
        return QSize(1, TWO_LINE_ROW if line is not None and line.second is not None and self.view.two_lines else self.view.row_height)


class RowTree(QTreeWidget):
    """The list of rows. ``picked`` sends the key of the row that became current, by click or keyboard. Rows given a tick box
    (``add_tick``) send ``ticked`` with their key when it's ticked or cleared by hand."""

    picked = Signal(object)
    ticked = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("rowTree")  # the style sheet's handle on the list's own ground (release 5.183)
        self.cell_pad = 3  # the room before each cell's text; the sidebar's views have more
        #: The row height for the view shown, and whether its rows with a second line take two lines (``set_density``).
        self.row_height = tokens.TREE_ROW
        self.two_lines = False
        #: Each open, ranked task's priority bucket, by its ID: its row's left edge (release 5.81). The browse window sets it as it
        #: fills the list, so drawing a row never reads the database.
        self.priorities: dict[str, str] = {}
        self.setItemDelegate(HtmlDelegate(self))
        self.setUniformRowHeights(True)
        self.setWordWrap(False)
        self.setIndentation(16)
        self.setAlternatingRowColors(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._building = False
        self._moves: tuple[Callable, Callable, Callable] | None = None
        #: Files, links and emails dropped on a row (release 5.115, decision 419): whether a row's key takes one, and what to do.
        self._file_drops: tuple[Callable[[object], bool], Callable[[object, str, list[str]], None]] | None = None
        #: Today's bins (release 5.154, decision 690): what a row's drag opens them with, and what a drop on one does.
        self._bin_hooks: tuple[Callable[[object], tuple[str, dict[str, int]] | None], Callable[[object, str], None]] | None = None
        self._bins = None
        self._hover: QTreeWidgetItem | None = None
        self._strips: list[ActionStrip] = []
        self._widths: list[int] = []
        self._empty: QWidget | None = None
        # A task's state from its row (release 5.76, round 7's item 101): the browse window gives these.
        #: Opens the state menu for a task, at a point on the screen, when its State cell is clicked.
        self.state_clicked: Callable[[str, QPoint], None] | None = None
        #: The state menu for a task, as a submenu of ``parent``, for a task row's right-click menu; None when it has none.
        self.state_menu: Callable[[str, QWidget], QMenu | None] | None = None
        #: Adds a task's Add to and Edit menus to its row's right-click menu (release 5.98, the consolidation plan's decision 392).
        self.task_menus: Callable[[str, QMenu], None] | None = None
        #: A task tile's whole right-click menu (release 5.138, the task tile plan's decision 573): given the task, the menu and
        #: the row's own actions, it fills the menu. When set, it's used for task rows in place of ``task_menus`` and ``state_menu``.
        self.tile_menu: Callable[[str, QMenu, list], None] | None = None
        #: Enter on a task's row (decision 572): the browse window opens its page.
        self.task_opened: Callable[[str], None] | None = None
        self._state_hover: tuple[QTreeWidgetItem, int] | None = None  # the State cell under the mouse
        self._state_open: tuple[QTreeWidgetItem, int] | None = None  # the State cell whose menu is open
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(60)
        self._relayout.timeout.connect(self.doItemsLayout)
        self._relayout.timeout.connect(self._sync_strips)
        self.header().sectionResized.connect(lambda *_: self._relayout.start())
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
        records, and the view draws them again. A row's ``MOVE_ROLE``, when it has one, stands for it in place of its key
        (release 5.148). A row that takes no drop in it (no ``ItemIsDropEnabled``) is landed on before or after, by its halves,
        as Qt draws the line between rows for it. With ``take_file_drops`` too, a drag of a row moves it and a drag of files,
        links or an email is a file drop (release 5.148, decision 648)."""
        self._moves = (drop, can, step)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def stop_row_moves(self) -> None:
        """No row moves and no file drops: each view turns on what it takes."""
        self._moves = None
        self._file_drops = None
        self._bin_hooks = None
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def take_file_drops(self, takes: Callable[[object], bool], dropped: Callable[[object, str, list[str]], None]) -> None:
        """Files, folders, web links and Outlook emails can be dropped on a row (release 5.115, decision 419): ``takes`` says
        whether a row's key takes one, and ``dropped`` gets the key and what the capture window's ``read_drop`` made of the
        drop, after the drop."""
        self._file_drops = (takes, dropped)
        self.setAcceptDrops(True)

    def set_bins(self, opens: Callable[[object], tuple | None], dropped: Callable[[object, tuple[str, bool]], None]) -> None:
        """Today's bins (release 5.154, decisions 690 and 691), with row moves on: when a row's drag starts, ``opens`` gets its
        move key and says the band it's in, each band's count and whether it's in the band's urgent half, or None for no bins
        (a note's drag). While the drag lasts the bins are drawn down the list's left side; a drop on one calls ``dropped``
        with the key and the target, the bin's band and whether its urgent part (release 5.176, decision 822)."""
        from docrepo.ui.today_bins import VIEW_WIDTH, Bins  # here: today_bins needs nothing of this module, but keeps it light

        self._bin_hooks = (opens, dropped)
        if self._bins is None:
            self._bins = Bins(self.viewport(), VIEW_WIDTH)

    def startDrag(self, actions) -> None:  # noqa: N802 - Qt's name
        """A row's drag. Where the view asks for bins (``set_bins``), they open beside the list while it lasts (release 5.154)."""
        opened = False
        if self._bin_hooks and self._bins is not None:
            found = self._bin_hooks[0](self.move_key(self.currentItem()))
            if found is not None:
                self._bins.open_for(found[0], found[1], self.viewport().rect(), *found[2:])
                opened = True
        try:
            super().startDrag(actions)
        finally:
            if opened:
                self._bins.close_bins()

    def _over_bins(self, event) -> tuple[str, bool] | None | bool:
        """Where a row's drag is over the bins: the target (the bin's band, and whether its urgent part), None on the bins but
        not on one a drop would go to, or False away from them (the list's own rules then)."""
        bins = self._bins
        if not self._bin_hooks or bins is None or not bins.isVisible():
            return False
        at = self.viewport().mapToGlobal(event.position().toPoint())
        if not bins.over(at):
            bins.set_hot(None)
            return False
        found = bins.bin_at(at)
        bins.set_hot(found)
        return found

    def _file_drop(self, event) -> tuple[object, str, list[str]] | None:
        """A file drop's row key, kind and paths, when it's over a row that takes one."""
        from docrepo.ui.capture_window import read_drop  # here: the capture window's module imports this one

        kind, paths = read_drop(event.mimeData(), links=True)
        item = self.itemAt(event.position().toPoint())
        key = item.data(0, KEY_ROLE) if item is not None else None
        if not kind or key is None or not self._file_drops or not self._file_drops[0](key):
            return None
        return key, kind, paths

    def _drop_at(self, pos: QPoint) -> tuple[object, str] | None:
        """The row under a point and which part of it, by the margins Qt draws its drop line from, or None where nothing can land."""
        item = self.itemAt(pos)
        if item is None:
            return None
        rect = self.visualItemRect(item)
        margin = max(2, min(12, round(rect.height() / 5.5)))
        where = "before" if pos.y() - rect.top() < margin else "after" if rect.bottom() - pos.y() < margin else "in"
        if where == "in" and not item.flags() & Qt.ItemFlag.ItemIsDropEnabled:  # as Qt's own line: the nearer half
            where = "before" if pos.y() < rect.center().y() else "after"
        return self.move_key(item), where

    @staticmethod
    def move_key(item: QTreeWidgetItem | None) -> object:
        """What a row move calls a row: its ``MOVE_ROLE``, else its key (release 5.148)."""
        if item is None:
            return None
        moved = item.data(0, MOVE_ROLE)
        return moved if moved is not None else item.data(0, KEY_ROLE)

    def _row_drag(self, event) -> bool:
        """Whether a drag is one of this list's own rows being moved, rather than files, links or an email to drop on a row
        (decision 648): told apart by where it comes from. With only row moves on, every drag is a row's, as before."""
        if not self._moves:
            return False
        return not self._file_drops or event.source() is self

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self._file_drops and not self._row_drag(event):
            from docrepo.ui.capture_window import note_drag

            if note_drag("enter", event.mimeData(), links=True):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        super().dragEnterEvent(event)
        if self._moves:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self._file_drops and not self._row_drag(event):
            if self._file_drop(event):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        if self._moves:
            on_bin = self._over_bins(event)
            if on_bin is not False:  # over Today's bins: no line, and a drop only on a bin (release 5.154)
                self.setDropIndicatorShown(False)
                self.viewport().update()
                if on_bin is None:
                    event.ignore()
                else:
                    event.setDropAction(Qt.DropAction.MoveAction)
                    event.accept()
                return
            self.setDropIndicatorShown(True)  # so Qt works out where its line goes
        super().dragMoveEvent(event)
        if not self._moves:
            return
        at, key = self._drop_at(event.position().toPoint()), self.move_key(self.currentItem())
        ok = bool(at and self._moves[1](key, *at))
        self.setDropIndicatorShown(ok)  # Qt's line or box only where a row can land (release 5.148)
        if ok:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self._file_drops and not self._row_drag(event):
            from docrepo.ui.capture_window import note_drag

            note_drag("drop", event.mimeData(), links=True)
            found = self._file_drop(event)
            if found is None:
                event.ignore()
                return
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            dropped = self._file_drops[1]
            QTimer.singleShot(0, lambda: dropped(*found))  # after the drop, so the program dragging is let go
            return
        if not self._moves:
            super().dropEvent(event)
            return
        on_bin = self._over_bins(event)
        if on_bin is not False:  # a drop on Today's bins (release 5.154, decision 691)
            event.setDropAction(Qt.DropAction.IgnoreAction)  # the records change, and the list is drawn again: Qt moves nothing
            event.accept()
            if on_bin is not None and self._bin_hooks:
                key, dropped = self.move_key(self.currentItem()), self._bin_hooks[1]
                QTimer.singleShot(0, lambda: dropped(key, on_bin))
            return
        at, key = self._drop_at(event.position().toPoint()), self.move_key(self.currentItem())
        event.setDropAction(Qt.DropAction.IgnoreAction)  # the records move, and the list is drawn again: Qt moves nothing
        event.accept()
        if at and self._moves[1](key, *at):
            drop = self._moves[0]
            QTimer.singleShot(0, lambda: drop(key, *at))  # after the drag has finished with these rows

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        shift_only = event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and shift_only and self.task_opened is not None
                and self.currentItem() is not None):  # a task tile's Enter opens it as its double-click does; Shift the other way (5.174)
            task = self.row_task(self.currentItem())
            if task:
                self.task_opened(task)
                return
        alt = event.modifiers() == Qt.KeyboardModifier.AltModifier
        if self._moves and alt and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.currentItem() is not None:
            self._moves[2](self.move_key(self.currentItem()), -1 if event.key() == Qt.Key.Key_Up else 1)
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
        if not self._widths:
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
        self._state_hover = self._state_open = None
        if self._empty is not None:
            self._empty.hide()
            self._empty.deleteLater()
            self._empty = None
        self.clear()

    def set_density(self, height: int, two_lines: bool = False) -> None:
        """The view's row height (decision L1): ``tokens.TREE_ROW`` where rows nest, ``tokens.LIST_ROW`` elsewhere. In a view with
        ``two_lines``, a row whose ``Line`` has a second line is ``TWO_LINE_ROW`` high, and its headings keep ``height``."""
        self.row_height, self.two_lines = height, two_lines
        self.setUniformRowHeights(not two_lines)

    def end(self, select: object | None = None) -> None:
        if select is not None:
            self.select_key(select)
        self._building = False
        self._size_columns()
        self._relayout.start()
        self._hover_from_cursor()

    def _size_columns(self) -> None:
        """A column after the title is as wide as the widest thing in it, from its set width up to ``MAX_CELL``,
        so a date such as "◆ 31 Oct · 23 d" is never cut. Its words never wrap."""
        if not self._widths:
            return
        widths = list(self._widths)
        option = QStyleOptionViewItem()
        option.font = self.font()
        delegate = self.itemDelegate()
        last = self.columnCount() - 1  # the last column's words stop inside the row's ground (release 5.183)
        for item in self.items():
            for i in range(1, self.columnCount()):
                html = item.data(i, HTML_ROLE)
                if html and not item.isFirstColumnSpanned():
                    need = int(delegate._doc(html, 1000, option, wrap=False).idealWidth()) + self.cell_pad + 12
                    end = ROW_INSET + ROW_END if i == last else 0
                    widths[i] = max(widths[i], min(MAX_CELL, need) + end)
        if widths != self._widths:
            self._widths = widths
            for i in range(1, len(widths)):
                self.setColumnWidth(i, widths[i])
            self._fit_columns()

    def add_row(self, parent: QTreeWidgetItem | None, key: object, cells: list, background: QColor | None = None,
                tip: str = "", selectable: bool = True, span: bool = False) -> QTreeWidgetItem:
        """A row. Its first cell may be a ``Line`` (painted part by part; its HTML is kept for Find), and
        the rest are HTML."""
        item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self)
        item.setData(0, KEY_ROLE, key)
        for i, html in enumerate(cells):
            if isinstance(html, Line):
                item.setData(i, LINE_ROLE, html)
                html = html.html()
            item.setData(i, HTML_ROLE, html)
            if tip:
                item.setToolTip(i, tip)
        # No ground is set on a row (release 5.183, decision 856): a row given one that can't be selected and whose first cell
        # names a group in <b>…</b> is a head, painted as a small grey label.
        first = cells[0] if cells else None
        if background is not None and not selectable and isinstance(first, str) and "<b>" in first:
            item.setData(0, HEAD_ROLE, head_of(first))
        if not selectable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if span:
            item.setFirstColumnSpanned(True)
        return item

    def add_head(self, parent: QTreeWidgetItem | None, name: str, count: str = "", sub: str = "", dot: str = "", tag: str = "",
                 tip: str = "") -> QTreeWidgetItem:
        """A group's head made directly (release 5.183, decision 856): a row that can't be selected, spanning the list, its
        ``HTML_ROLE`` written as ``add_row``'s callers write a head's, so Find and the tests read it the same."""
        words = " ".join(esc(w) for w in (count, sub) if w)
        item = self.add_row(parent, None, [f"<b>{esc(name)}</b>" + (f' <span class="sub">{words}</span>' if words else "")], None, tip,
                            selectable=False, span=True)
        item.setData(0, HEAD_ROLE, Head(name, count, sub, dot, tag))
        return item

    @contextlib.contextmanager
    def building(self) -> Iterator[None]:
        """While the rows are being set up rather than changed by the owner (release 5.95, the review's F11, for callers
        outside this class): opening, folding or ticking a row then isn't remembered or sent on. Nested use keeps it on."""
        was, self._building = self._building, True
        try:
            yield
        finally:
            self._building = was

    @property
    def is_building(self) -> bool:
        """Whether the rows are being set up now (``building``), rather than changed by the owner."""
        return self._building

    def add_tick(self, item: QTreeWidgetItem, on: bool) -> None:
        """Give a row a tick box in its first column. Setting it doesn't send ``ticked``."""
        with self.building():
            item.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    # ---- a task's state from its row (release 5.76, round 7's item 101, decisions 360 and 361) ----
    def mark_state(self, item: QTreeWidgetItem, column: int, task_id: str, state: str) -> None:
        """Make a row's state a button that opens the state menu for ``task_id``: the first column, whose icon is the state
        (the list rows review's decision L7), which says so in its own tooltip, or another column, which gets a tooltip."""
        item.setData(column, STATE_ROLE, task_id)
        if column != 0:
            item.setToolTip(column, f"{state}. Click to change the state.")

    def state_cell(self, pos: QPoint) -> tuple[QTreeWidgetItem, int, str] | None:
        """The state at a point in the viewport: its row, its column and its task. In the first column only the state's icon is
        the button: the rest of it is the row."""
        item = self.itemAt(pos)
        column = self.columnAt(pos.x())
        task = item.data(column, STATE_ROLE) if item is not None and column >= 0 else None
        if not task:
            return None
        if column == 0:
            cell = self.visualRect(self.indexFromItem(item, 0))
            line = item.data(0, LINE_ROLE)
            left = cell.left() + self.cell_pad + 2 + (line.icon_offset if isinstance(line, Line) else 0)
            if left - 3 > pos.x() or pos.x() > left + ROW_ICON + 3:
                return None
        return item, column, task

    def state_lit(self, index: QModelIndex) -> bool:
        """Whether a State cell shows as a button now: under the mouse, or with its menu open."""
        item = self.itemFromIndex(index)
        return any(cell is not None and cell[0] is item and cell[1] == index.column() for cell in (self._state_hover, self._state_open))

    def row_task(self, item: QTreeWidgetItem) -> str | None:
        """The task a row is: the one its State cell shows, or its key's."""
        for column in range(self.columnCount()):
            task = item.data(column, STATE_ROLE)
            if task:
                return task
        key = item.data(0, KEY_ROLE)
        return key[1] if isinstance(key, tuple) and len(key) == 2 and key[0] == "task" else None

    def open_state_menu(self, item: QTreeWidgetItem, column: int) -> None:
        """Open a State cell's menu under it, lit while it's open. What a click on the cell does."""
        task = item.data(column, STATE_ROLE)
        if not task or self.state_clicked is None:
            return
        rect = self.visualRect(self.indexFromItem(item, column))
        self._state_open = (item, column)
        self.viewport().update(rect)
        try:
            self.state_clicked(task, self.viewport().mapToGlobal(QPoint(rect.left() + self.cell_pad - 3, rect.bottom() + 2)))
        finally:
            self._state_open = None
            self._state_hover = None
            self.viewport().update()

    def _hover_state(self, pos: QPoint | None) -> None:
        cell = self.state_cell(pos) if pos is not None else None
        now = (cell[0], cell[1]) if cell else None
        was = self._state_hover
        if (now is None and was is None) or (now is not None and was is not None and now[0] is was[0] and now[1] == was[1]):
            return
        self._state_hover = now
        for c in (was, now):
            if c is not None:
                self.viewport().update(self.visualRect(self.indexFromItem(c[0], c[1])))
        if now is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()

    # ---- a row's actions (release 5.59): over the row on hover and when current, and as its right-click menu ----
    def set_actions(self, item: QTreeWidgetItem, actions: list[tuple[str, Callable[[], None], str]]) -> None:
        """Give a row its actions: (label, clicked, tooltip)."""
        item.setData(0, ACTIONS_ROLE, RowActions(actions))

    def set_menu_lines(self, item: QTreeWidgetItem, lines: list[tuple[str, Callable[[], None], str]]) -> None:
        """Lines for a row's right-click menu only, after its actions, with no button on the row: Today's Move to top and
        Move to bottom (release 5.148, decision 646)."""
        item.setData(0, MENU_ROLE, RowActions(lines))

    def action_strip(self, item: QTreeWidgetItem) -> ActionStrip | None:
        """The row's strip, showing it if it wasn't. What tests click, as a person would after moving the mouse there."""
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
        if self._building:
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
        fill = self.fill_rect(rect)  # inside the row's ground, at its end (release 5.183)
        strip.setGeometry(fill.right() + 1 - width, fill.top(), width, fill.height())
        strip.show()
        strip.raise_()
        self.viewport().update(rect)  # its words stop short of the strip

    def strip_left(self, item: QTreeWidgetItem | None) -> int | None:
        """Where the row's strip of actions starts, while the row is under the mouse, so its words stop short of it."""
        if item is None or item is not self._hover or item.data(0, ACTIONS_ROLE) is None:
            return None
        return self.viewport().width() - ROW_INSET - strip_width(item.data(0, ACTIONS_ROLE))

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
        if self._building:
            return
        at = self.viewport().mapFromGlobal(QCursor.pos())
        was = self._hover
        self._hover = self.itemAt(at) if self.viewport().rect().contains(at) else None
        if self._hover is not was:  # the ground follows the row under a still pointer (release 5.183)
            for row in (was, self._hover):
                if row is not None and self.indexFromItem(row).isValid():
                    self.viewport().update(self._row_rect(row))
        self._sync_strips()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().mouseMoveEvent(event)
        self._hover_state(event.position().toPoint())
        item = self.itemAt(event.position().toPoint())
        if item is not self._hover:
            for was in (self._hover, item):  # the rows' words make room for the strip, or take it back
                if was is not None:
                    self.viewport().update(self._row_rect(was))
            self._hover = item
            self._sync_strips()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().leaveEvent(event)
        if self._hover is not None and self.indexFromItem(self._hover).isValid():  # its ground goes (release 5.183)
            self.viewport().update(self._row_rect(self._hover))
        self._hover = None
        self._hover_state(None)
        self._sync_strips()

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt's name
        at = self.viewport().mapFromGlobal(event.globalPos())
        item = self.itemAt(at) if event.reason() == event.Reason.Mouse else self.currentItem()
        menu = self.row_menu(item)
        if menu is None:
            super().contextMenuEvent(event)
            return
        menu.exec(event.globalPos())
        menu.deleteLater()

    def row_menu(self, item: QTreeWidgetItem | None) -> QMenu | None:
        """A row's right-click menu: its actions, then a task row's Add to and Edit (release 5.98, decision 392), then its
        State submenu (release 5.76, decision 361), which is also where the keyboard reaches a state, with the menu key. A
        task row's own Edit action is left to the Edit menu, whose first line is Edit task. None for a row with nothing."""
        if item is None:
            return None
        row = item.data(0, ACTIONS_ROLE)
        lines = item.data(0, MENU_ROLE)  # the menu's own lines, after the row's actions (release 5.148)
        lines = list(lines.actions) if lines is not None else []
        task = self.row_task(item) if self.state_menu is not None or self.task_menus is not None or self.tile_menu is not None else None
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        if task and self.tile_menu is not None:  # a task tile's one menu (decision 573), with the row's own actions in it
            own = [a for a in (row.actions if row is not None else ()) if a[0] not in ("Edit", "Note")]  # the menu has both
            self.tile_menu(task, menu, [*own, *lines])
            if menu.isEmpty():
                menu.deleteLater()
                return None
            return menu
        for label, clicked, tip in [*(row.actions if row is not None else ()), *lines]:
            if task and self.task_menus is not None and label == "Edit":
                continue
            action = menu.addAction(label, clicked)
            action.setToolTip(tip)
        if task and self.task_menus is not None:
            self.task_menus(task, menu)
        sub = self.state_menu(task, menu) if task and self.state_menu is not None else None
        if sub is not None:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addMenu(sub)
        if menu.isEmpty():
            menu.deleteLater()
            return None
        return menu

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

    def row_priority(self, index: QModelIndex) -> str:
        """The priority bucket of the open task a row is, from its key, or "" (release 5.81)."""
        key = index.siblingAtColumn(0).data(KEY_ROLE)
        return self.priorities.get(key[1], "") if isinstance(key, tuple) and len(key) == 2 and key[0] == "task" else ""

    def fill_rect(self, rect: QRect) -> QRect:
        """A row's rounded ground (release 5.183, decision 850): ``ROW_INSET`` in from the pane's left and right edges, and a
        pixel off its top and bottom, so a hovered row beside the selected one reads as two."""
        return QRect(ROW_INSET, rect.top() + 1, self.viewport().width() - 2 * ROW_INSET, rect.height() - 2)

    def is_last_shown(self, column: int) -> bool:
        """Whether ``column`` is the last one not hidden: its words stop inside the row's ground."""
        return column == max((i for i in range(self.columnCount()) if not self.isColumnHidden(i)), default=0)

    def drawRow(self, painter, option, index) -> None:  # noqa: N802 - Qt's name
        """A row flat on white (release 5.183, decision 850): under a row that can be selected, a rounded ground, the
        accent's tint when it's selected, the hover grey under the pointer, ``now`` on the current task's row; then the row;
        then, in the gutter left of the ground, its mark: the task's priority in its colour (decision L9), selected or not, or
        the accent on the current task's row (5.177). A row kept for context has its mark faded. A head has none of it."""
        first = index.siblingAtColumn(0)
        selected = self.selectionModel().isSelected(first)
        ground = None
        if first.flags() & Qt.ItemFlag.ItemIsSelectable:
            item = self.itemFromIndex(first)
            ground = ("selected" if selected else "hover" if item is not None and item is self._hover
                      else "now" if first.data(NOW_ROLE) else None)
        if ground:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.colour(ground)))
            painter.drawRoundedRect(QRectF(self.fill_rect(option.rect)), tokens.RADIUS_S, tokens.RADIUS_S)
            painter.restore()
        super().drawRow(painter, option, index)
        bucket = self.row_priority(first)
        mark = (tokens.colour("accent") if first.data(NOW_ROLE)  # the current task's row: the accent mark (5.177)
                else tokens.colour(PRIORITY_EDGES[bucket]) if bucket in PRIORITY_EDGES else None)
        if mark:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if first.data(DIM_ROLE):
                painter.setOpacity(0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(mark))
            painter.drawRoundedRect(QRectF(EDGE_X, option.rect.center().y() + 0.5 - EDGE_H / 2, EDGE_W, EDGE_H), tokens.RADIUS_EDGE, tokens.RADIUS_EDGE)
            painter.restore()
        rule = first.data(RULE_ROLE)
        if rule:  # the hairline over the first of a band's rest (decision 821)
            painter.fillRect(ROW_INSET + 8, option.rect.top(), self.viewport().width() - 2 * (ROW_INSET + 8), 1, QColor(rule))

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
        if (item is not None and self.hasFocus()
                and self.window().testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange)):
            p = QPainter(self.viewport())
            paint_focus_ring(p, self.fill_rect(self.visualItemRect(item)))  # round the row's ground (release 5.183)
            p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, False)  # the mouse has taken over: no ring
        self.viewport().update()
        cell = self.state_cell(event.position().toPoint()) if event.button() == Qt.MouseButton.LeftButton else None
        if cell is not None and self.state_clicked is not None:  # the state opens its menu, and doesn't pick the row (decision 360)
            event.accept()
            self.open_state_menu(cell[0], cell[1])
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.state_clicked is not None and self.state_cell(event.position().toPoint()) is not None:
            event.accept()  # a quick second click on a state isn't a double-click on its row
            return
        super().mouseDoubleClickEvent(event)

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
        if self.hasFocus():  # Qt redraws only a row's cell here: the ring goes round the whole row
            self.viewport().update(self._row_rect(current))
            if previous is not None:
                self.viewport().update(self._row_rect(previous))
        key = current.data(0, KEY_ROLE)
        if key is not None:
            self.picked.emit(key)
