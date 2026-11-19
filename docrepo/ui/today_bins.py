"""Today's bins (release 5.154, the design workspace's ``docs/mods/today-priority-plan.md``, decisions 690 and 691).

While a task's row on Today is dragged, in the Today view and in the Today side panel while it's widened, five narrow
bins open down the list's left-hand side, one per band, top to bottom: Critical, High, Medium, Not ranked and Parking
lot (``model.TODAY_BANDS``). Each is drawn in its priority's colour with its name and how many of Today's items are in
it; the dragged task's own band is dimmed, and the bin under the pointer lights up with "Make it High". A drop on one sets
the task's priority (``edits.today_bin``). They close when the drag ends. A note's drag opens none (decision 692).

The bins are only drawn here: the list under them takes the drag and asks ``bin_at`` where it is, so the bins never take
a file, a link or an email dragged in from elsewhere.

Since release 5.176 (the design workspace's ``docs/mods/urgency-plan.md``, decision 822) each bin has two parts, stacked
as the strip is 72 to 88 px wide: its top two fifths **urgent**, with the Urgent icon and a stronger tint of the bin's
colour, and the rest the bin as it was. A drop on the upper part ticks Urgent, on the lower unticks it. The dragged task's
own part is no target, and its band's other part is one, so a drag can tick or untick without changing the priority.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from docrepo.model import TODAY_BAND_NAMES, TODAY_BANDS
from docrepo.ui import tokens
from docrepo.ui.icons import tinted

#: A target: a band ("" for Not ranked) and whether it's the bin's urgent part.
Target = tuple[str, bool]
#: How much of a bin its urgent part takes, from the top (decision 822).
URGENT_SHARE = 0.4

#: Each band's colour token and its ground's (decision 690).
COLOURS = {"critical": ("pri_critical", "critical_bg"), "high": ("pri_high", "caution_bg"), "medium": ("pri_medium", "info_bg"),
           "": ("control", "hover"), "parking": ("pri_parking", "hover")}
#: How wide the bins are, in the view and in the panel; the gap between two, and around them.
VIEW_WIDTH, PANEL_WIDTH = 88, 72
GAP = 4


class Bins(QWidget):
    """Five bins, drawn over the left of a list while a task's row is dragged. ``open_for`` shows them, ``close`` hides them."""

    def __init__(self, parent: QWidget, width: int) -> None:
        super().__init__(parent)
        self.setObjectName("todayBins")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # the list under them takes the drag
        self.setAcceptDrops(False)
        self.bin_width = width
        self.own: str | None = None
        self.own_urgent = False
        self.counts: dict[str, int] = {}
        self.hot: Target | None = None
        self.hide()

    def open_for(self, own: str, counts: dict[str, int], area: QRect, own_urgent: bool = False) -> None:
        """Open beside the list: ``own`` is the dragged task's band and ``own_urgent`` whether it's in the band's urgent half,
        ``counts`` each band's items on Today, ``area`` the list's rectangle in the parent's coordinates (the bins take its
        left side, its whole height)."""
        self.own, self.own_urgent, self.counts, self.hot = own, own_urgent, dict(counts), None
        self.setGeometry(area.x(), area.y(), min(self.bin_width, area.width()), area.height())
        self.show()
        self.raise_()
        self.update()

    def close_bins(self) -> None:
        self.own, self.hot = None, None
        self.hide()

    def rects(self) -> list[tuple[str, QRect]]:
        """Each bin's rectangle, top to bottom, in the bins' own coordinates."""
        n = len(TODAY_BANDS)
        height = max(0, self.height() - GAP * (n + 1))
        each = height / n if n else 0
        return [(key, QRect(GAP, round(GAP + i * (each + GAP)), max(0, self.width() - GAP * 2), max(0, round(each))))
                for i, key in enumerate(TODAY_BANDS)]

    def parts(self) -> list[tuple[Target, QRect]]:
        """Each bin's two parts, top to bottom (decision 822): its urgent part (the top two fifths), then the rest."""
        out: list[tuple[Target, QRect]] = []
        for key, r in self.rects():
            top = round(r.height() * URGENT_SHARE)
            out.append(((key, True), QRect(r.left(), r.top(), r.width(), top)))
            out.append(((key, False), QRect(r.left(), r.top() + top, r.width(), r.height() - top)))
        return out

    def bin_at(self, global_point: QPoint) -> Target | None:
        """The target under a point on the screen, a band and whether its urgent part, or None: away from the bins, between
        two, or on the dragged task's own part (a drop there changes nothing). Its band's other part is a target."""
        if not self.isVisible():
            return None
        at = self.mapFromGlobal(global_point)
        if not self.rect().contains(at):
            return None
        found = next((t for t, r in self.parts() if r.contains(at)), None)
        return None if found == (self.own, self.own_urgent) else found

    def over(self, global_point: QPoint) -> bool:
        """Whether a point on the screen is over the bins at all, a gap or the own bin included: the list's drop line
        doesn't show there."""
        return self.isVisible() and self.rect().contains(self.mapFromGlobal(global_point))

    def set_hot(self, key: Target | None) -> None:
        """Light the part a drop would go to, or none."""
        if key != self.hot:
            self.hot = key
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(tokens.colour("content")))
        base = QFont(self.font())
        scale = self.devicePixelRatioF()
        for key, r in self.rects():
            ink, ground = (QColor(tokens.colour(c)) for c in COLOURS[key])
            hot = self.hot is not None and self.hot[0] == key
            own = key == self.own
            p.setOpacity(1.0)
            pen = QPen(ink, 1.5, Qt.PenStyle.SolidLine if hot else Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(ground)
            p.drawRoundedRect(QRectF(r).adjusted(0.75, 0.75, -0.75, -0.75), 6, 6)
            # Its two parts (decision 822): the urgent part a stronger tint with the Urgent icon; the part a drop goes to
            # filled with the bin's colour; the dragged task's own part dimmed.
            for (_k, urgent), part in ((t, q) for t, q in self.parts() if t[0] == key):
                inner = QRectF(part).adjusted(1.5, 1.5 if urgent else 0, -1.5, 0 if urgent else -1.5)
                lit = self.hot == (key, urgent)
                mine = own and urgent == self.own_urgent
                tint = QColor(ink)
                tint.setAlphaF(1.0 if lit else 0.28 if urgent else 0.0)
                p.setOpacity(0.4 if mine else 1.0)
                p.setPen(Qt.PenStyle.NoPen)
                if tint.alphaF() > 0:
                    p.setBrush(tint)
                    p.drawRoundedRect(inner, 5, 5)
                if urgent:
                    size = 10
                    colour = tokens.colour("content") if lit else tokens.colour("critical")
                    p.drawPixmap(round(inner.left() + 3), round(inner.top() + 2), tinted("urgent", colour, size, scale))
                    p.setPen(QPen(ink, 1, Qt.PenStyle.DotLine))
                    p.drawLine(round(inner.left() + 4), part.bottom(), round(inner.right() - 4), part.bottom())
            p.setOpacity(1.0)
            hot_urgent = hot and self.hot is not None and self.hot[1]
            # The words over the whole bin, as before 5.176: the panel's bins are short.
            name = TODAY_BAND_NAMES[key].replace(" ", "\n")
            words = (f"{name},\nurgent" if hot_urgent else f"Make it\n{name}" if hot and key != self.own else
                     "Not\nurgent" if hot else name)
            hot = hot and not hot_urgent  # the lower part's words light up only when it's the target
            bold = QFont(base)
            bold.setBold(True)
            p.setFont(bold)
            p.setPen(QColor(tokens.colour("content")) if hot else ink)
            count = self.counts.get(key, 0)
            text_rect = r.adjusted(2, 2, -2, -2)
            lines = words.count("\n") + 1
            line_h = p.fontMetrics().height()
            block = line_h * (lines + 1)
            top = text_rect.top() + max(0, (text_rect.height() - block) // 2)
            p.drawText(QRect(text_rect.left(), top, text_rect.width(), line_h * lines), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, words)
            p.setFont(base)
            p.setPen(QColor(tokens.colour("content" if hot else "text2")))
            p.drawText(QRect(text_rect.left(), top + line_h * lines, text_rect.width(), line_h), Qt.AlignmentFlag.AlignHCenter, str(count))
        p.setOpacity(1.0)
        p.end()


def counts_of(model, items) -> dict[str, int]:
    """How many of Today's items are in each band, for the bins' numbers."""
    out = dict.fromkeys(TODAY_BANDS, 0)
    for a in items:
        out[model.today_band(a)] += 1
    return out


def colour_of(key: str) -> QColor:
    """A band's colour, for its heading."""
    return QColor(tokens.colour(COLOURS.get(key, COLOURS[""])[0]))
