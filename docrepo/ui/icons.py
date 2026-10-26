"""DocRepo's icons: small SVG files in ``icons/``, drawn in the style of Fluent UI System Icons (the visual overhaul's
decision 4). Each is drawn in ``currentColor``; ``icon`` paints it in the colours for each state, sharp at any scale.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from docrepo.ui import tokens

ICON_DIR = Path(__file__).resolve().parent / "icons"


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def _pixmap(name: str, colour: str, size: int, scale: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name).replace("currentColor", colour).encode("utf-8")))
    px = max(1, round(size * scale))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def tinted(name: str, colour: str, size: int, scale: float = 1.0) -> QPixmap:
    """The icon ``name`` in ``colour``, ``size`` px square at ``scale``, for drawing into a picture (the task page's marks)."""
    return _pixmap(name, colour, size, scale)


@lru_cache(maxsize=None)
def icon(name: str, colour: str | None = None, on: str | None = None, size: int = 16) -> QIcon:
    """The icon ``name`` in ``colour`` (secondary text by default), the disabled colour when disabled, and ``on`` (the
    accent by default) when its button is checked. Drawn at 1x, 1.5x and 2x so it stays sharp at 125% to 200%."""
    t = tokens.LIGHT
    result = QIcon()
    for scale in (1.0, 1.5, 2.0):
        result.addPixmap(_pixmap(name, colour or t["text2"], size, scale), QIcon.Mode.Normal, QIcon.State.Off)
        result.addPixmap(_pixmap(name, on or t["accent"], size, scale), QIcon.Mode.Normal, QIcon.State.On)
        result.addPixmap(_pixmap(name, t["disabled"], size, scale), QIcon.Mode.Disabled, QIcon.State.Off)
    return result


def icon_size(size: int = 16) -> QSize:
    return QSize(size, size)


def file_url(name: str) -> str:
    """An icon file's path as the style sheet's url() wants it."""
    return (ICON_DIR / f"{name}.svg").as_posix()
