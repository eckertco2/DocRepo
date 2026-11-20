"""The windows' look.

The look (the visual overhaul, releases 5.10 to 5.16) is Qt's Fusion style with a palette, a style sheet and page styles
all made from the design tokens in ``tokens``. ``apply_look`` sets it up when DocRepo starts. Release 5.179 (the redesign's
decision 840) retired release 5.9's look, which Settings kept selectable until then, with its own style sheets here.

The theme (release 5.180, the redesign's decision 841) is light, or dark, which isn't offered yet. With Windows in dark mode,
Qt would draw its own controls dark and mix them with light colours, so ``apply_look`` asks Qt for the theme's own colour
scheme and sets every role of the palette.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from docrepo.ui import tokens
from docrepo.ui.look import LOOK, configure, watch_focus

#: The style sheet, made once a theme.
_QSS_CACHE: dict[str, str] = {}


def style_sheet() -> str:
    """The style sheet a window sets on itself, from the tokens. When DocRepo runs, it's set once on the application
    instead (``apply_look``), so this is empty: Qt parses it only once."""
    if LOOK.app_sheet:
        return ""
    theme = tokens.theme()
    if theme not in _QSS_CACHE:
        _QSS_CACHE[theme] = tokens.qss()
    app = QApplication.instance()
    if app is not None:  # the first window to ask puts it on the application, for every window after it
        app.setStyleSheet(_QSS_CACHE[theme])
        LOOK.app_sheet = True
        return ""
    return _QSS_CACHE[theme]


def page_css() -> str:
    """The HTML styles of the browse tool's pages and list cells, and the forms' previews, in the active theme."""
    return tokens.css()


def theme_of(app: QGuiApplication, theme: str) -> str:
    """The set a Settings theme means (release 5.194, decision 869): "dark" and "light" themselves; "system" Windows' own
    setting, as Qt reads it with nothing asked of it; anything else, such as the "new" and "classic" looks callers passed
    before, light."""
    if theme == "system":
        hints = app.styleHints()
        if hasattr(hints, "unsetColorScheme"):  # Qt 6.8: forget any scheme asked before, to read Windows' own
            hints.unsetColorScheme()
        return "dark" if hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark else "light"
    return theme if theme in tokens.THEMES else "light"


def apply_look(app: QGuiApplication, theme: str = "light", hints: bool = False) -> None:
    """Set the look up from Settings, once the application exists and before any window is made. ``theme`` is Settings'
    Theme: "light", "dark" (release 5.180) or "system" (release 5.194, as Windows is set); anything else is light."""
    tokens.use(theme_of(app, theme))
    configure(hints)
    hints_ = app.styleHints()
    if hasattr(hints_, "setColorScheme"):  # Qt 6.8: the theme's own, whatever Windows is set to
        hints_.setColorScheme(Qt.ColorScheme.Dark if tokens.theme() == "dark" else Qt.ColorScheme.Light)
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
