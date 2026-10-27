"""The browse tool's sidebar in the new look (the visual overhaul's stage O10, release 5.22, decisions 79 to 84).

Each view is a row with its icon, its name and, where it asks for something (``views.ASKS``), a count. The groups
(Lists, Plan, Manage) have small headings with a chevron that fold them, and a folded group still shows the view
that's open. Discarded and Settings are pinned at the foot, below a hairline, and the rows above scroll on their own.
The rows are painted here from the design tokens: a style sheet can't draw the selected row's short pill or put the
count at the right edge.

Tab gives the pane one stop (the open view's row, or the row last moved to); the arrow keys, Home and End move between
rows and headings, Enter or Space opens a view or folds a group, and Left and Right fold and unfold a heading.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QScrollArea, QToolTip, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.views import ASKS, ViewDef

#: Each view's icon, from ``docrepo/ui/icons/``.
ICONS = {
    "today": "sun", "unfiled": "unfiled", "tasks": "tasks", "due": "due", "reminders": "reminders", "waiting": "waiting",
    "mine": "person", "urgent": "urgent", "unplanned": "unplanned", "agenda": "agenda", "activity": "activity", "priorities": "priorities", "timeline": "timeline",
    "capacity": "capacity", "people": "people", "labels": "labels", "docs": "file", "discarded": "discarded",
    "settings": "settings",
}
#: The views pinned at the foot (decision 83).
FOOT = ("discarded", "settings")
#: The sidebar's width to start with. Decision 84 chose 228 px, at the mock's 13 px text; DocRepo's 14 px text needs
#: 248 px for "Overdue and next 7 days" in semibold and its count to fit, with room for the scroll bar.
WIDTH = 248
ROW = 32     # a view's row (the playbook's compact sidebar item)
HEADING = 26
PAD = 12     # the icon's, and a heading's, distance from the row's left edge
GAP = 10     # between the icon and the name


def _c(name: str) -> QColor:
    return QColor(tokens.colour(name))


class _Row(QAbstractButton):
    """A row the sidebar paints itself. It takes focus only from the pane (Tab and the arrow keys), never from a click,
    so the focus ring shows only when the keyboard is in use."""

    def __init__(self, text: str, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(160, self.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(48, self.height())

    def _backplate(self, p: QPainter, fill: QColor | None) -> None:
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(self.rect()), tokens.RADIUS, tokens.RADIUS)
        if self.hasFocus():
            p.setPen(QPen(_c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), tokens.RADIUS, tokens.RADIUS)

    def _hover_fill(self) -> QColor | None:
        if self.isDown():
            return _c("pressed")
        return _c("hover") if self.underMouse() else None


class ViewRow(_Row):
    """A view: its icon, its name (ending in "…" when it doesn't fit, with the full name as the tooltip) and its count.
    The open view has an inset backplate, a short accent pill at its left, its icon in the accent and its name in
    semibold (decision 82)."""

    def __init__(self, view: ViewDef, parent: QWidget | None = None) -> None:
        super().__init__(view.label, ROW, parent)
        self.view_id = view.id
        self.setCheckable(True)
        self._icon: QIcon = icon(ICONS.get(view.id, "task"))
        self.count = 0
        self._elided = False
        self.setAccessibleName(view.label)

    def set_count(self, n: int) -> None:
        if n != self.count:
            self.count = n
            self.setAccessibleName(f"{self.text()}, {n}" if n else self.text())
            self.update()

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.ToolTip:  # the full name, only when it's cut short
            if self._elided:
                QToolTip.showText(e.globalPos(), self.text(), self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        on = self.isChecked()
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._backplate(p, _c("selected") if on else self._hover_fill())
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("accent"))
            p.drawRoundedRect(QRectF(0, (h - 16) / 2, 3, 16), 1.5, 1.5)
        self._icon.paint(p, QRect(PAD, (h - 16) // 2, 16, 16), Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal,
                         QIcon.State.On if on else QIcon.State.Off)
        right = w - GAP
        if self.count:
            font = tokens.numeric_font(tokens.CAPTION)
            text = str(self.count)
            cw = QFontMetrics(font).horizontalAdvance(text)
            p.setFont(font)
            p.setPen(_c("text2"))
            p.drawText(QRect(right - cw, 0, cw, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            right -= cw + 8
        font = tokens.ui_font(tokens.BODY, semibold=on)
        left = PAD + 16 + GAP
        label = QFontMetrics(font).elidedText(self.text(), Qt.TextElideMode.ElideRight, max(0, right - left))
        self._elided = label != self.text()
        p.setFont(font)
        p.setPen(_c("text"))
        p.drawText(QRect(left, 0, max(0, right - left), h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        p.end()


class Heading(_Row):
    """A group's heading: its name in Caption, semibold and muted, then a chevron that points down while it's open. The
    whole heading is the button (decision 79)."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, HEADING, parent)
        self.section = name
        self.folded = False
        self.set_folded(False)

    def set_folded(self, folded: bool) -> None:
        self.folded = folded
        self.setToolTip(f"{'Unfold' if folded else 'Fold'} {self.section}")
        self.setAccessibleName(self.section)
        self.setAccessibleDescription("Folded" if folded else "Open")
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        h = self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._backplate(p, self._hover_fill())
        font = tokens.ui_font(tokens.CAPTION, semibold=True)
        tw = QFontMetrics(font).horizontalAdvance(self.text())
        p.setFont(font)
        p.setPen(_c("text") if self.underMouse() else _c("text2"))
        p.drawText(QRect(PAD, 0, tw + 2, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        chevron = icon("chevron-right" if self.folded else "chevron-down", size=12)
        chevron.paint(p, QRect(PAD + tw + 4, (h - 12) // 2, 12, 12))
        p.end()


class NavPane(QWidget):
    """The views on the left, in ``views`` order, with the groups' headings and the foot. ``show_state`` sets the open
    view, the counts and the folded groups; the pane says when a view is picked (``picked``) or a group folded
    (``folded``), and the browse window keeps the folded groups in docs.db."""

    picked = Signal(str)
    folded = Signal(str, bool)

    def __init__(self, views: Iterable[ViewDef], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        views = list(views)
        self.rows: dict[str, ViewRow] = {}
        self.headings: dict[str, Heading] = {}
        self.members: dict[str, list[str]] = {}
        self.current: str | None = None
        self.shut: set[str] = set()
        self.order: list[_Row] = []  # every row and heading, top to bottom

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(objectName="navBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 6, 4, 8)
        lay.setSpacing(0)
        for v in views:
            if v.id in FOOT:
                continue
            if v.section and v.section not in self.headings:
                lay.addSpacing(tokens.SPACE["l"])
                heading = Heading(v.section)
                heading.clicked.connect(lambda _=False, s=v.section: self.toggle(s))
                self.headings[v.section] = heading
                self.members[v.section] = []
                self._add(heading, lay)
            if v.section:
                self.members[v.section].append(v.id)
            self._add(ViewRow(v), lay)
        lay.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        self.foot = QFrame(objectName="navFoot")
        fl = QVBoxLayout(self.foot)
        fl.setContentsMargins(4, 4, 4, 4)
        fl.setSpacing(0)
        by_id = {v.id: v for v in views}
        for vid in FOOT:
            if vid in by_id:
                self._add(ViewRow(by_id[vid]), fl)
        outer.addWidget(self.foot)
        self._tab_stop(self.order[0] if self.order else None)

    def _add(self, row: _Row, layout: QVBoxLayout) -> None:
        if isinstance(row, ViewRow):
            self.rows[row.view_id] = row
            row.clicked.connect(lambda _=False, vid=row.view_id: self._pick(vid))
        row.installEventFilter(self)
        self.order.append(row)
        layout.addWidget(row)

    # ---- state ----
    def show_state(self, counts: dict[str, int], current: str | None, shut: Iterable[str]) -> None:
        """The open view (None while searching), each view's count (shown only for ``views.ASKS``, and not when 0) and
        the folded groups."""
        self.current = current
        for vid, row in self.rows.items():
            row.setChecked(vid == current)
            row.set_count(counts.get(vid, 0) if vid in ASKS else 0)
        self.shut = set(shut) & set(self.headings)
        self._apply_folds()
        if not self._focus_inside():
            row = self.rows.get(current or "")
            self._tab_stop(row if row is not None and not row.isHidden() else None)

    def _apply_folds(self) -> None:
        """A folded group hides its views but the open one, which stays in sight under the heading (decision 80)."""
        for section, heading in self.headings.items():
            closed = section in self.shut
            heading.set_folded(closed)
            for vid in self.members[section]:
                self.rows[vid].setHidden(closed and vid != self.current)

    def toggle(self, section: str) -> None:
        closed = section not in self.shut
        (self.shut.add if closed else self.shut.discard)(section)
        self._apply_folds()
        self.folded.emit(section, closed)

    def _pick(self, view_id: str) -> None:
        for vid, row in self.rows.items():
            row.setChecked(vid == view_id)  # a click on the open view would otherwise untick it
        self.picked.emit(view_id)

    # ---- the keyboard ----
    def _focus_inside(self) -> bool:
        return any(r.hasFocus() for r in self.order)

    def _tab_stop(self, row: _Row | None) -> None:
        """Make ``row`` the pane's one Tab stop: the first row shown when it's None or hidden."""
        if row is None or row.isHidden():
            row = next((r for r in self.order if not r.isHidden()), None)
        for r in self.order:
            r.setFocusPolicy(Qt.FocusPolicy.TabFocus if r is row else Qt.FocusPolicy.NoFocus)

    def focus_row(self, row: _Row) -> None:
        self._tab_stop(row)
        row.setFocus(Qt.FocusReason.TabFocusReason)
        if self.scroll.widget().isAncestorOf(row):
            self.scroll.ensureWidgetVisible(row, 0, 0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Type.FocusIn and watched in self.order:
            self._tab_stop(watched)  # type: ignore[arg-type]
        elif event.type() == QEvent.Type.KeyPress and watched in self.order:
            shown = [r for r in self.order if not r.isHidden()]
            i = shown.index(watched) if watched in shown else 0  # type: ignore[arg-type]
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End) and shown:
                j = {Qt.Key.Key_Up: max(0, i - 1), Qt.Key.Key_Down: min(len(shown) - 1, i + 1),
                     Qt.Key.Key_Home: 0, Qt.Key.Key_End: len(shown) - 1}[key]
                self.focus_row(shown[j])
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                watched.click()  # type: ignore[attr-defined]
                return True
            if isinstance(watched, Heading) and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                if watched.folded != (key == Qt.Key.Key_Left):
                    self.toggle(watched.section)
                return True
        return super().eventFilter(watched, event)
