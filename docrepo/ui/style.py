"""The windows' look.

The look (the visual overhaul, releases 5.10 to 5.16) is Qt's Fusion style with a palette, a style sheet and page styles
all made from the design tokens in ``tokens``. ``apply_look`` sets it up when DocRepo starts. Release 5.179 (the redesign's
decision 840) retired release 5.9's look, which Settings kept selectable until then, with its own style sheets here.

DocRepo's colours are light. With Windows in dark mode, Qt would draw its own controls dark and mix them with those light
colours, so ``apply_look`` asks for the light colour scheme and sets every role of the palette.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from docrepo.ui import tokens
from docrepo.ui.look import LOOK, configure, watch_focus

_QSS_CACHE: list[str] = []


def style_sheet() -> str:
    """The style sheet a window sets on itself, from the tokens. When DocRepo runs, it's set once on the application
    instead (``apply_look``), so this is empty: Qt parses it only once."""
    if LOOK.app_sheet:
        return ""
    if not _QSS_CACHE:
        _QSS_CACHE.append(tokens.qss())
    app = QApplication.instance()
    if app is not None:  # the first window to ask puts it on the application, for every window after it
        app.setStyleSheet(_QSS_CACHE[0])
        LOOK.app_sheet = True
        return ""
    return _QSS_CACHE[0]


def page_css() -> str:
    """The HTML styles of the browse tool's pages and list cells, and the forms' previews."""
    return tokens.CSS


def apply_look(app: QGuiApplication, look: str = "new", hints: bool = False) -> None:
    """Set the look up from Settings, once the application exists and before any window is made. ``look`` is kept for
    its callers and has one value since release 5.179: any other is read as it (5.180 makes it the theme)."""
    configure(hints)
    hints_ = app.styleHints()
    if hasattr(hints_, "setColorScheme"):  # Qt 6.8: light, whatever Windows is set to (a dark theme comes later, decision 14)
        hints_.setColorScheme(Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    app.setPalette(tokens.palette())
    app.setFont(tokens.ui_font())
    LOOK.app_sheet = False
    style_sheet()  # sets the new look's style sheet on the application, once
    # Windows' theme gives these classes fonts of their own (Segoe UI 9 pt), which setFont above leaves in place (release 5.57).
    # After the style sheet, which puts them back.
    for name in tokens.BODY_FONT_CLASSES:
        QApplication.setFont(tokens.ui_font(), name)
    QApplication.setFont(tokens.ui_font(tokens.CAPTION), "QTipLabel")
    watch_focus(app)
