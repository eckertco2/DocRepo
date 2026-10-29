"""The Task view's list (release 5.34; the task overview design, sections 5 and 6): a model of rows and a painted
delegate, as the playbook asks for every long list, so 500 files cost what 50 do.

Rows are group headings (which stay at the top while their rows scroll, and fold), a "found in the text" line, tips,
an empty notice, "Show all" rows, and items: a file, an email, a note or update, or a subtask, two lines each (one in
compact rows), with what matched in a mark, the type's coloured mark, and the subtask and date at the right. The chosen
row shows three quick actions at its right edge, as a hovered one does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from docrepo import finder
from docrepo.dates import short, to_date
from docrepo.overview import Record
from docrepo.ui import tokens
from docrepo.ui.icons import tinted

ITEM_HEIGHT, COMPACT_HEIGHT, HEAD_HEIGHT, SUB_HEIGHT, TIP_HEIGHT, MORE_HEIGHT, EMPTY_HEIGHT = 48, 32, 30, 26, 34, 32, 110
ROW_ROLE = Qt.ItemDataRole.UserRole + 1
#: Each row's quick actions, right to left: what they do, their icon and tooltip.
ACTIONS = (("copy", "copy", "Copy path (Ctrl+Shift+C)"), ("show", "folder", "Show in File Explorer (Ctrl+Enter)"), ("open", "open", "Open (Enter)"))


@dataclass
class Row:
    """One row of the list. ``kind`` is "item", "head", "sub" (a line under a group), "tip", "empty" or "more"."""

    kind: str
    record: Record | None = None
    label: str = ""                 # a heading's, sub line's, tip's or "Show all" row's words
    count: int | None = None
    hint: str = ""                  # a heading's words at the right
    fold: str = ""                  # a heading that folds: its key
    folded: bool = False
    more: str = ""                  # a "Show all" row's kind
    why: str = ""                   # Recent's "opened today", in place of the date
    words: list[str] = field(default_factory=list)
    slips: tuple[str, ...] = ()
    in_text: bool = False
    snippet: str = ""
    subtask: str = ""               # the subtask's title, when it isn't the scope
    pinned: bool = False
    missing: bool = False
    depth: int = 0

    @property
    def choosable(self) -> bool:
        return self.kind in ("item", "more")

    def accessible(self) -> str:
        r = self.record
        if self.kind == "head":
            return f"{self.label}, {self.count}" if self.count is not None else self.label
        if r is None:
            return self.label
        bits = [r.title, {"file": r.type.upper() if r.type not in ("other", "link") else r.type, "email": "email", "note": "note", "task": "subtask"}[r.kind]]
        bits += [x for x in (self.subtask, f"added {r.day}" if r.kind == "file" else r.day, "pinned" if self.pinned else "", "missing" if self.missing else "") if x]
        return ", ".join(bits)


class ResultModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Row] = []

    def set_rows(self, rows: list[Row]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt's name
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return row.record.title if row.record else row.label
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return row.accessible()
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if self.rows[index.row()].choosable else Qt.ItemFlag.ItemIsEnabled


def _c(name: str) -> QColor:
    return QColor(tokens.LIGHT.get(name, name))


class ResultDelegate(QStyledItemDelegate):
    """Paints the rows from the tokens."""

    def __init__(self, view: "ResultList") -> None:
        super().__init__(view)
        self.view = view
        self.font = tokens.ui_font(tokens.BODY)
        self.bold = tokens.ui_font(tokens.BODY, semibold=True)
        self.small = tokens.ui_font(tokens.CAPTION)
        self.small_bold = tokens.ui_font(tokens.CAPTION, semibold=True)
        self.numbers = tokens.numeric_font(tokens.CAPTION)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        row: Row = index.data(ROW_ROLE)
        h = {"head": HEAD_HEIGHT, "sub": SUB_HEIGHT, "tip": TIP_HEIGHT, "more": MORE_HEIGHT, "empty": EMPTY_HEIGHT}.get(row.kind)
        if h is None:
            h = COMPACT_HEIGHT if self.view.compact or row.record.kind == "task" and not row.record.desc else ITEM_HEIGHT
        return QSize(1, h)  # as wide as the view, never wider: the list never scrolls sideways

    # ---- painting ----
    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        row: Row = index.data(ROW_ROLE)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        if row.kind == "head":
            self.paint_head(p, rect, row)
        elif row.kind == "sub":
            p.setFont(self.small_bold)
            p.setPen(_c("text2"))
            p.drawText(rect.adjusted(52, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter, f"{row.label} · {row.count}" if row.count is not None else row.label)
        elif row.kind == "tip":
            box = rect.adjusted(16, 4, -16, -4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("base"))
            p.drawRoundedRect(box, 4, 4)
            p.setFont(self.small)
            p.setPen(_c("text2"))
            p.drawText(box.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, row.label)
        elif row.kind == "empty":
            p.setFont(self.bold)
            p.setPen(_c("text"))
            title, _, rest = row.label.partition("\n")
            p.drawText(rect.adjusted(16, 18, -16, -60), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title)
            p.setFont(self.small)
            p.setPen(_c("text2"))
            p.drawText(rect.adjusted(32, 46, -32, -8), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, rest)
        else:
            self.paint_back(p, option, rect)
            if row.kind == "more":
                p.setFont(self.font)
                p.setPen(_c("accent"))
                p.drawText(rect.adjusted(52, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter, row.label)
            else:
                self.paint_item(p, option, rect, row)
        p.restore()

    def paint_head(self, p: QPainter, rect: QRect, row: Row) -> None:
        p.fillRect(rect, _c("content"))
        p.setPen(QPen(_c("stroke"), 1))
        p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        x = rect.left() + 16
        if row.fold:
            p.drawPixmap(QPoint(x - 4, rect.top() + (rect.height() - 14) // 2), tinted("chevron-right" if row.folded else "chevron-down", tokens.LIGHT["text2"], 14,
                                                                                         p.device().devicePixelRatioF()))
            x += 14
        p.setFont(self.bold)
        p.setPen(_c("text"))
        fm = QFontMetrics(self.bold)
        p.drawText(QRect(x, rect.top(), rect.width(), rect.height()), Qt.AlignmentFlag.AlignVCenter, row.label)
        x += fm.horizontalAdvance(row.label) + 8
        if row.count is not None:
            p.setFont(self.numbers)
            p.setPen(_c("text2"))
            p.drawText(QRect(x, rect.top(), 80, rect.height()), Qt.AlignmentFlag.AlignVCenter, str(row.count))
        if row.hint:
            p.setFont(self.small)
            p.setPen(_c("text2"))
            p.drawText(rect.adjusted(0, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, row.hint)

    def paint_back(self, p: QPainter, option, rect: QRect) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            p.fillRect(rect, _c("selected"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("accent"))
            p.drawRoundedRect(QRect(rect.left() + 4, rect.top() + (rect.height() - 16) // 2, 3, 16), 1.5, 1.5)
            if self.view.hasFocus():  # keyboard focus: a 2 px ring inside the row (WCAG 2.2's focus appearance)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_c("accent"), 2))
                p.drawRect(rect.adjusted(1, 1, -1, -1))
        elif hovered:
            p.fillRect(rect, _c("hover"))

    def paint_item(self, p: QPainter, option, rect: QRect, row: Row) -> None:
        r = row.record
        one = rect.height() <= COMPACT_HEIGHT
        indent = 16 + row.depth * 18
        scale = p.device().devicePixelRatioF()
        icon_name, colour = self.icon_of(r)
        size = 20
        p.drawPixmap(QPoint(rect.left() + indent, rect.top() + (rect.height() - size) // 2), tinted(icon_name, colour, size, scale))
        left = rect.left() + indent + size + 12
        # The right side: the chosen or hovered row shows its quick actions; the others, the subtask and the date.
        right = rect.right() - 12
        show_actions = r.kind == "file" and (option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        if show_actions:
            for name, icon, _ in self.actions_for(r):
                right -= 28
                p.drawPixmap(QPoint(right + 6, rect.top() + (rect.height() - 16) // 2), tinted(icon, tokens.LIGHT["text2"], 16, scale))
            right -= 6
        else:
            right = self.paint_right(p, rect, row, right)
        top = rect.top() + (rect.height() // 2 - (9 if not one else 0))
        title_rect = QRect(left, rect.top() + (6 if not one else 0), right - left - 12, 22 if not one else rect.height())
        self.draw_marked(p, title_rect, r.title, finder.highlights(r.title, row.words, row.slips) if row.words else [], self.font, self.bold, _c("text"))
        if not one:
            line2 = self.second_line(row)
            spans = finder.highlights(line2, row.words) if row.words else []
            self.draw_marked(p, QRect(left, top + 13, right - left - 12, 18), line2, spans, self.small, self.small_bold, _c("text2"))

    def paint_right(self, p: QPainter, rect: QRect, row: Row, right: int) -> int:
        r = row.record
        p.setFont(self.numbers)
        p.setPen(_c("text2"))
        right -= 16
        if row.pinned:
            p.drawPixmap(QPoint(right + 2, rect.top() + (rect.height() - 14) // 2), tinted("pin", tokens.LIGHT["accent"], 14, p.device().devicePixelRatioF()))
        right -= 8
        when = row.why or (short(to_date(r.at), self.view.today) if r.kind != "task" else r.state)
        w = max(64, QFontMetrics(self.numbers).horizontalAdvance(when))
        p.drawText(QRect(right - w, rect.top(), w, rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, when)
        right -= w + 14
        if row.subtask:
            p.setFont(self.small)
            fm = QFontMetrics(self.small)
            text = fm.elidedText(row.subtask, Qt.TextElideMode.ElideRight, 160)
            tw = fm.horizontalAdvance(text)
            p.drawText(QRect(right - tw, rect.top(), tw, rect.height()), Qt.AlignmentFlag.AlignVCenter, text)
            right -= tw + 14
        if row.missing:
            p.setFont(self.small)
            p.setPen(_c("caution"))
            text = "⚠ Missing"
            tw = QFontMetrics(self.small).horizontalAdvance(text)
            p.drawText(QRect(right - tw, rect.top(), tw, rect.height()), Qt.AlignmentFlag.AlignVCenter, text)
            right -= tw + 14
        return right

    def second_line(self, row: Row) -> str:
        r = row.record
        if row.snippet:
            return ("in its text: " if r.kind == "file" else "") + row.snippet
        if r.kind == "file":
            came = f"from {r.came}" + (" · saved copy too" if r.copy and r.source != "Saved copy" else "")
            return f"{r.desc} · {came}" if r.desc else came
        if r.kind == "note":
            text = " ".join(r.text.split())
            return text[len(r.title):].lstrip(" .:;-") if text.startswith(r.title) else text
        return r.desc

    def icon_of(self, r: Record) -> tuple[str, str]:
        if r.kind == "task":
            return {"Not started": "state-ns", "In progress": "state-ip", "Parked": "state-pk", "Closed": "state-cl"}.get(r.state, "state-ns"), \
                tokens.LIGHT["accent" if r.state == "In progress" else "text2"]
        if r.kind == "note":
            return ("update" if r.type == "update" else "note"), tokens.LIGHT["text2"]
        if r.kind == "email":
            return "type-mail", tokens.LIGHT["type_mail"]
        return f"type-{r.type if r.type in ('doc', 'sheet', 'slides', 'pdf', 'picture', 'drawing', 'mail', 'link') else 'other'}", tokens.LIGHT.get(f"type_{r.type}", tokens.LIGHT["type_other"])

    @staticmethod
    def actions_for(r: Record) -> tuple:
        if r.type == "link":
            return (("copylink", "copy", "Copy link (Enter)"),)
        if r.source == "Email attachment":
            return (("copy", "copy", "Copy path (Ctrl+Shift+C)"), ("show", "folder", "Show in File Explorer (Enter); attachments aren't opened"))
        return ACTIONS

    def draw_marked(self, p: QPainter, rect: QRect, text: str, spans: list[tuple[int, int]], font: QFont, bold: QFont, colour: QColor) -> None:
        """One line of text, cut with "…" to fit, with the matched spans in semibold on the caution tint."""
        fm = QFontMetrics(font)
        width = rect.width()
        if fm.horizontalAdvance(text) > width:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fm.horizontalAdvance(text[:mid] + "…") <= width:
                    lo = mid
                else:
                    hi = mid - 1
            text = text[:lo] + "…"
            spans = [(a, min(b, lo)) for a, b in spans if a < lo]
        p.setClipRect(rect)
        x, at = rect.left(), 0
        baseline = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2
        for a, b in [*spans, (len(text), len(text))]:
            for part, mark in ((text[at:a], False), (text[a:b], True)):
                if not part:
                    continue
                f = bold if mark else font
                w = QFontMetrics(f).horizontalAdvance(part)
                if mark:
                    p.fillRect(QRect(x, rect.top() + (rect.height() - fm.height()) // 2, w, fm.height()), _c("caution_bg"))
                p.setFont(f)
                p.setPen(colour)
                p.drawText(x, baseline, part)
                x += w
            at = b
        p.setClipping(False)

    # ---- the quick actions ----
    def action_at(self, row: Row, rect: QRect, pos: QPoint) -> str | None:
        if row.kind != "item" or row.record.kind != "file":
            return None
        right = rect.right() - 12
        for name, _, _ in self.actions_for(row.record):
            right -= 28
            if QRect(right, rect.top() + (rect.height() - 28) // 2, 28, 28).contains(pos):
                return name
        return None

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802 - Qt's name
        row: Row = index.data(ROW_ROLE)
        name = self.action_at(row, option.rect, event.pos()) if row else None
        if name:
            from PySide6.QtWidgets import QToolTip

            QToolTip.showText(event.globalPos(), next(t for n, _, t in self.actions_for(row.record) if n == name), view)
            return True
        return super().helpEvent(event, view, option, index)


class ResultList(QListView):
    """The list. ``chosen`` fires when the chosen row changes, ``activated_row`` on a double-click, ``action`` for a quick
    action (its row and name), and ``folded`` when a group heading is clicked."""

    chosen = Signal(int)
    activated_row = Signal(int)
    action = Signal(int, str)
    folded = Signal(str)

    def __init__(self, today) -> None:
        super().__init__()
        self.today = today
        self.compact = False
        self.model_ = ResultModel()
        self.setModel(self.model_)
        self.delegate = ResultDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setUniformItemSizes(False)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setObjectName("taskViewList")
        self.setAccessibleName("Results")
        self.selectionModel().currentChanged.connect(lambda cur, _: self.chosen.emit(cur.row()) if cur.isValid() else None)

    @property
    def rows(self) -> list[Row]:
        return self.model_.rows

    def set_rows(self, rows: list[Row], choose: int | None) -> None:
        self.model_.set_rows(rows)
        if choose is not None and 0 <= choose < len(rows):
            self.choose(choose)

    def choosable(self) -> list[int]:
        return [i for i, r in enumerate(self.rows) if r.choosable]

    def current(self) -> int:
        i = self.currentIndex()
        return i.row() if i.isValid() else -1

    def choose(self, row: int) -> None:
        index = self.model_.index(row)
        self.setCurrentIndex(index)
        self.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        if row > 0 and self.rows[row - 1].kind == "head":  # keep a group's heading in sight with its first row
            self.scrollTo(self.model_.index(row - 1), QAbstractItemView.ScrollHint.EnsureVisible)

    def step(self, by) -> None:
        """Choose the next or previous choosable row (``by`` rows), the first or last ("first", "last"), or the first row
        of the next or previous group ("next group", "previous group")."""
        rows = self.choosable()
        if not rows:
            return
        cur = self.current()
        if by == "first":
            target = rows[0]
        elif by == "last":
            target = rows[-1]
        elif by in ("next group", "previous group"):
            heads = [i for i, r in enumerate(self.rows) if r.kind == "head"]
            if by == "next group":
                head = next((h for h in heads if h > cur), None)
            else:
                mine = max((h for h in heads if h < cur), default=None)
                head = max((h for h in heads if mine is not None and h < mine), default=heads[0] if heads else None)
            target = next((i for i in rows if head is not None and i > head), cur if cur in rows else rows[0])
        else:
            k = rows.index(cur) if cur in rows else -1
            target = rows[max(0, min(len(rows) - 1, k + by))] if k >= 0 else rows[0]
        self.choose(target)

    # ---- the mouse ----
    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            row = self.rows[index.row()]
            if row.kind == "head" and row.fold:
                self.folded.emit(row.fold)
                return
            name = self.delegate.action_at(row, self.visualRect(index), event.position().toPoint())
            if name:
                self.action.emit(index.row(), name)
                return
            if row.kind == "more":
                self.activated_row.emit(index.row())
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt's name
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and self.rows[index.row()].choosable:
            self.activated_row.emit(index.row())
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - redraw so a hovered row's actions go
        self.viewport().update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - the chosen row's focus ring
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.viewport().update()

    # ---- the heading that stays at the top ----
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        top = self.indexAt(QPoint(4, 1))
        if not top.isValid():
            return
        i = top.row()
        if self.rows[i].kind == "head" and self.visualRect(top).top() >= 0:
            return
        head = next((j for j in range(i, -1, -1) if self.rows[j].kind == "head"), None)
        if head is None:
            return
        rect = QRect(0, 0, self.viewport().width(), HEAD_HEIGHT)
        # The next heading pushes this one up as it arrives.
        nxt = next((j for j in range(i + 1, len(self.rows)) if self.rows[j].kind == "head"), None)
        if nxt is not None:
            nrect = self.visualRect(self.model_.index(nxt))
            if 0 <= nrect.top() < HEAD_HEIGHT:
                rect.moveTop(nrect.top() - HEAD_HEIGHT)
        p = QPainter(self.viewport())
        self.delegate.paint_head(p, rect, self.rows[head])
        p.end()

    def stuck_head(self, pos: QPoint) -> int | None:
        """The heading painted at the top, when ``pos`` is on it."""
        if pos.y() >= HEAD_HEIGHT:
            return None
        top = self.indexAt(QPoint(4, 1))
        if not top.isValid():
            return None
        return next((j for j in range(top.row(), -1, -1) if self.rows[j].kind == "head"), None)

    def viewportEvent(self, event) -> bool:  # noqa: N802 - a click on the stuck heading folds it
        if event.type() == QEvent.Type.MouseButtonRelease:
            head = self.stuck_head(event.position().toPoint())
            if head is not None and self.rows[head].fold and self.visualRect(self.model_.index(head)).top() < 0:
                self.folded.emit(self.rows[head].fold)
                return True
        return super().viewportEvent(event)
