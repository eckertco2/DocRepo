"""Today's drop targets: the priority groups a task's row is dropped on (release 5.189, the redesign's decision 864, which
redraws decision 690's bins and keeps decision 822's urgent part).

While a task's row on Today is dragged, in the Today view and in the Today side panel while it's widened, each priority
band of Today is a target: its head and its rows together, outlined with a dashed line, and the band under the pointer
outlined in the accent with a line where the task will land. A band with nothing on Today shows a slim head of its own
while the drag lasts, so every band (``model.TODAY_BANDS``: Critical, High, Medium, Not ranked and Parking lot) can be
dropped on. Each band takes a drop two ways (decision 822): on its head's Urgent chip, or among its urgent rows, it ticks
Urgent; on its head or among the rest, it unticks it. The dragged task's own half is no target (the row drag reorders
there); its band's other half is one, so a drag can tick or untick without changing the priority. A drop sets the task's
priority (``edits.today_bin``). A note's drag opens none (decision 692).

``DropGroups`` only draws lines, in the list's margins and between rows, so nothing covers a title: the list under it takes
the drag and asks ``bin_at`` where it is, so a file, a link or an email dragged in from elsewhere never meets a target.
``target_at`` is the rule, in one place.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from docrepo.model import TODAY_BAND_NAMES, TODAY_BANDS
from docrepo.ui import tokens
from docrepo.ui.icons import tinted

#: A target: a band ("" for Not ranked) and whether it's the band's urgent part.
Target = tuple[str, bool]

#: Each band's colour token and its ground's (decision 690): the head's dot is the first.
COLOURS = {"critical": ("pri_critical", "critical_bg"), "high": ("pri_high", "caution_bg"), "medium": ("pri_medium", "info_bg"),
           "": ("control", "hover"), "parking": ("pri_parking", "hover")}
#: How far a group's outline stands outside its head and rows, and the outline's and the insert line's widths, in pixels.
OUTSET, OUTLINE, INSERT = 2, 1.5, 3
#: The Urgent chip on a band's head, while a drag is on: its height, and the room round its words.
CHIP_HEIGHT, CHIP_PAD = 20, 6


@dataclass(frozen=True)
class Group:
    """One band as a target, in the overlay's coordinates: its head, the Urgent chip on it, the rectangle spanning each
    half's rows (null when that half is empty), the whole of it (head and rows, ``OUTSET`` out all round), and its count."""

    band: str
    head: QRect
    chip: QRect
    urgent_rows: QRect
    rest_rows: QRect
    whole: QRect
    count: int = 0


def make_group(band: str, head: QRect, chip: QRect, urgent: list[QRect], rest: list[QRect], count: int) -> Group:
    """A group from its head's, its chip's and its rows' rectangles."""
    def span(rects: list[QRect]) -> QRect:
        out = QRect()
        for r in rects:
            out = out.united(r)
        return out

    u, r = span(urgent), span(rest)
    whole = head.united(u).united(r).adjusted(-OUTSET, -OUTSET, OUTSET, OUTSET)
    return Group(band, head, chip, u, r, whole, count)


def _in(rect: QRect, point: QPoint) -> bool:
    return not rect.isNull() and rect.contains(point)


def target_at(groups: list[Group], own: str | None, own_urgent: bool, point: QPoint) -> Target | None | bool:
    """Where a drop at ``point`` goes: a target; None inside a group where a drop changes nothing (the dragged task's own
    part of its head); or False away from every group, and over the dragged task's own half's rows, where the row drag's
    reorder takes it."""
    for g in groups:
        if not g.whole.contains(point):
            continue
        if g.band == own:
            mine, other = (g.urgent_rows, g.rest_rows) if own_urgent else (g.rest_rows, g.urgent_rows)
            if _in(mine, point):
                return False
            if _in(other, point):
                return g.band, not own_urgent
            if not own_urgent and _in(g.chip, point):  # the other half is the urgent one: its chip
                return g.band, True
            if own_urgent and _in(g.head, point) and not _in(g.chip, point):  # the other half is the rest: the head
                return g.band, False
            return None
        if _in(g.chip, point) or _in(g.urgent_rows, point):
            return g.band, True
        return g.band, False
    return False


def insert_at(group: Group, urgent: bool) -> int:
    """The y of the line where a task dropped on a group's half lands: the foot of that half, under the head when it's
    empty; the rest's foot follows the urgent rows when the rest is empty."""
    if urgent:
        return (group.urgent_rows if not group.urgent_rows.isNull() else group.head).bottom() + 1
    if not group.rest_rows.isNull():
        return group.rest_rows.bottom() + 1
    return (group.urgent_rows if not group.urgent_rows.isNull() else group.head).bottom() + 1


class DropGroups(QWidget):
    """The outlines over a list while a task's row is dragged: one round each band, dashed, the band a drop would go to
    solid in the accent with its insert line. It lets the mouse through and takes no drops. With ``heads`` set (the Today
    view, whose head rows can't draw a drag's words), it also draws each head's Urgent chip and, on the lit one, its words."""

    def __init__(self, parent: QWidget, heads: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("todayDropGroups")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAcceptDrops(False)
        self.heads = heads
        self.own: str | None = None
        self.own_urgent = False
        self.counts: dict[str, int] = {}
        self.hot: Target | None = None
        self.groups: list[Group] = []
        self.hide()

    def open_for(self, own: str, counts: dict[str, int], area: QRect, own_urgent: bool = False, groups: list[Group] | None = None) -> None:
        """Open over the list: ``own`` is the dragged task's band and ``own_urgent`` whether it's in the band's urgent half,
        ``counts`` each band's items on Today, ``area`` the list's rectangle in the parent's coordinates, ``groups`` the
        bands as targets, in this widget's coordinates."""
        self.own, self.own_urgent, self.counts, self.hot = own, own_urgent, dict(counts), None
        self.groups = list(groups or [])
        self.setGeometry(area)
        self.show()
        self.raise_()
        self.update()

    def set_groups(self, area: QRect, groups: list[Group]) -> None:
        """The groups again, as the list scrolled or a head showed."""
        self.setGeometry(area)
        self.groups = list(groups)
        self.update()

    def close_bins(self) -> None:
        self.own, self.hot, self.groups = None, None, []
        self.hide()

    def rects(self) -> list[tuple[str, QRect]]:
        """Each band and its whole, top to bottom."""
        return [(g.band, g.whole) for g in self.groups]

    def parts(self) -> list[tuple[Target, QRect]]:
        """The ten targets, each with a rectangle to aim at the middle of: a band's urgent part its chip, the rest its head
        left of the chip (decision 822)."""
        out: list[tuple[Target, QRect]] = []
        for g in self.groups:
            out.append(((g.band, True), g.chip))
            out.append(((g.band, False), QRect(g.head.left(), g.head.top(), max(1, g.chip.left() - g.head.left() - 2), g.head.height())))
        return out

    def target(self, global_point: QPoint) -> Target | None | bool:
        """``target_at`` for a point on the screen."""
        if not self.isVisible():
            return False
        return target_at(self.groups, self.own, self.own_urgent, self.mapFromGlobal(global_point))

    def bin_at(self, global_point: QPoint) -> Target | None:
        """The target under a point on the screen, or None: away from the groups, or on what a drop there wouldn't change."""
        found = self.target(global_point)
        return None if found is False else found

    def over(self, global_point: QPoint) -> bool:
        """Whether a point on the screen is inside a group at all."""
        at = self.mapFromGlobal(global_point)
        return self.isVisible() and any(g.whole.contains(at) for g in self.groups)

    def set_hot(self, key: Target | None) -> None:
        """Light the group a drop would go to, or none."""
        if key != self.hot:
            self.hot = key
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(tokens.colour("accent"))
        for g in self.groups:
            lit = self.hot is not None and self.hot[0] == g.band
            pen = QPen(accent if lit else QColor(tokens.colour("stroke_strong")), OUTLINE, Qt.PenStyle.SolidLine if lit else Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(g.whole).adjusted(OUTLINE / 2, OUTLINE / 2, -OUTLINE / 2, -OUTLINE / 2), tokens.RADIUS, tokens.RADIUS)
            if self.heads:
                self._paint_head(p, g, lit)
            if lit:
                y = insert_at(g, self.hot[1])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(accent)
                p.drawRoundedRect(QRectF(g.whole.left() + OUTSET + 4, y - INSERT / 2, g.whole.width() - 2 * OUTSET - 8, INSERT),
                                  tokens.RADIUS_BAR, tokens.RADIUS_BAR)
        p.end()

    def _paint_head(self, p: QPainter, g: Group, lit: bool) -> None:
        """The view's head: its Urgent chip at the right end and, lit, what a drop does, before the chip."""
        chip_lit = lit and self.hot is not None and self.hot[1]
        paint_chip(p, g.chip, chip_lit, self.devicePixelRatioF())
        if lit and self.hot is not None:
            p.setPen(QColor(tokens.colour("accent")))
            p.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
            words = drop_words(g.band, self.hot[1], g.band == self.own)
            p.drawText(QRect(g.head.left(), g.head.top(), g.chip.left() - g.head.left() - 8, g.head.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, words)


def chip_rect(head: QRect) -> QRect:
    """The Urgent chip's rectangle at a head's right end."""
    width = 72
    return QRect(head.right() - width - 4, head.top() + (head.height() - CHIP_HEIGHT) // 2, width, CHIP_HEIGHT)


def paint_chip(p: QPainter, r: QRect, lit: bool, scale: float) -> None:
    """The Urgent chip: the Urgent icon and the word, ``critical`` on its ground, or ``on_accent`` on ``critical`` when lit."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(tokens.colour("critical" if lit else "critical_bg")))
    p.drawRoundedRect(QRectF(r), tokens.RADIUS_S, tokens.RADIUS_S)
    ink = tokens.colour("on_accent" if lit else "critical")
    size = 12
    p.drawPixmap(r.left() + CHIP_PAD, r.top() + (r.height() - size) // 2, tinted("urgent", ink, size, scale))
    p.setPen(QColor(ink))
    p.setFont(tokens.ui_font(tokens.LABEL, semibold=True))
    p.drawText(QRect(r.left() + CHIP_PAD + size + 4, r.top(), r.width() - CHIP_PAD * 2 - size - 4, r.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Urgent")
    p.restore()


def drop_words(band: str, urgent: bool, own: bool) -> str:
    """What a drop on a band's half does, said on its head: "Make it High", "High, urgent", "Not urgent", "Urgent"."""
    name = TODAY_BAND_NAMES[band]
    if own:
        return "Urgent" if urgent else "Not urgent"
    return f"{name}, urgent" if urgent else f"Make it {name}"


def counts_of(model, items) -> dict[str, int]:
    """How many of Today's items are in each band."""
    out = dict.fromkeys(TODAY_BANDS, 0)
    for a in items:
        out[model.today_band(a)] += 1
    return out


def colour_of(key: str) -> QColor:
    """A band's colour, for its head's dot."""
    return QColor(tokens.colour(COLOURS.get(key, COLOURS[""])[0]))
