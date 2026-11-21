"""DocRepo's own icon (release 5.196, the redesign's decision 871), for the title bars, the taskbar, the tray and its
notifications: drawn here, so no image file is needed and nothing is fetched.

The mark is a task tree, what DocRepo is built around, drawn as its lists draw it: a parent task's row (its status
circle and a bar for its title), and under it two subtasks' rows, indented, in white on a rounded square of the accent's
indigo (``brand`` and ``brand_ink``, the same in both themes, so the icon is one icon wherever Windows shows it). It's drawn
on a 16-unit grid whose every edge is a whole unit, so at 16 px (the title bar and the tray) each bar falls on whole
pixels and stays sharp; at 32 and 48 px it's the same drawing at two and three times. It replaces the blue square with a "D" in Segoe UI that DocRepo had since release 5.57,
which depended on a font and read as a letter rather than as DocRepo."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from docrepo.ui import tokens

#: The sizes Windows asks for: the title bar and the tray (16, 20, 24 at 125% and 150%), Alt+Tab and the taskbar (32 to 64).
SIZES = (16, 20, 24, 32, 40, 48, 64)
#: The grid the mark is drawn on; every edge below is a whole unit of it.
GRID = 16
#: The rounded square, inset half a unit so its edge isn't cut, and its corner.
SQUARE = QRectF(0.5, 0.5, 15, 15)
CORNER = 3.5
#: The titles' bars' corners, in grid units: just off square, as the lists' rows are.
BAR_CORNER = 0.5
#: The mark, three rows: each a status circle and a title's bar; the two subtasks' rows indented under the parent's.
DOTS = (
    QRectF(3, 3, 2, 2),    # the parent task's status circle
    QRectF(6, 7, 2, 2),    # its first subtask's
    QRectF(6, 11, 2, 2),   # its second's
)
BARS = (
    QRectF(6, 3, 7, 2),    # the parent's title
    QRectF(9, 7, 4, 2),    # the first subtask's
    QRectF(9, 11, 4, 2),   # the second's
)


def draw(size: int) -> QPixmap:
    """The icon at ``size`` px square, transparent outside its rounded square."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / GRID, size / GRID)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor(tokens.colour("brand")))
    p.drawRoundedRect(SQUARE, CORNER, CORNER)
    p.setBrush(QColor(tokens.colour("brand_ink")))
    for r in DOTS:
        p.drawEllipse(r)
    for r in BARS:
        p.drawRoundedRect(r, BAR_CORNER, BAR_CORNER)
    p.end()
    return pixmap


def make_icon() -> QIcon:
    """The icon at every size Windows asks for, so it's drawn for the size shown rather than scaled."""
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(draw(size))
    return icon
