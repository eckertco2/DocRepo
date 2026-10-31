"""The windows' look.

The new look (the visual overhaul, releases 5.10 to 5.16) is Qt's Fusion style with a palette, a style sheet and page
styles all made from the design tokens in ``tokens``. The Classic look is release 5.9's: Windows' own widgets with the
colours below, kept selectable in Settings (decision 15). ``apply_look`` sets either one up when DocRepo starts.

DocRepo's colours are light. With Windows in dark mode, Qt would draw its own
controls dark and mix them with those light colours, so ``use_light_theme``
keeps the whole app light, whatever Windows is set to.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from docrepo.ui import tokens
from docrepo.ui.look import LOOK, configure

#: The light palette, from the mockup's light colours.
LIGHT = {
    QPalette.ColorRole.Window: "#f4f6f8", QPalette.ColorRole.WindowText: "#1a1f25", QPalette.ColorRole.Base: "#ffffff",
    QPalette.ColorRole.AlternateBase: "#f4f6f8", QPalette.ColorRole.Text: "#1a1f25", QPalette.ColorRole.Button: "#f4f6f8",
    QPalette.ColorRole.ButtonText: "#1a1f25", QPalette.ColorRole.BrightText: "#ffffff", QPalette.ColorRole.Highlight: "#dbe8f5",
    QPalette.ColorRole.HighlightedText: "#1a1f25", QPalette.ColorRole.ToolTipBase: "#ffffff", QPalette.ColorRole.ToolTipText: "#1a1f25",
    QPalette.ColorRole.PlaceholderText: "#87919c", QPalette.ColorRole.Link: "#1d5e98", QPalette.ColorRole.LinkVisited: "#1d5e98",
    QPalette.ColorRole.Light: "#ffffff", QPalette.ColorRole.Midlight: "#e9edf1", QPalette.ColorRole.Mid: "#b8c1cb",
    QPalette.ColorRole.Dark: "#87919c", QPalette.ColorRole.Shadow: "#5a6571",
}
#: Text that's turned off: buttons and fields that can't be used now.
DISABLED_TEXT = "#9aa3ad"


def light_palette() -> QPalette:
    palette = QPalette()
    for role, colour in LIGHT.items():
        palette.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(DISABLED_TEXT))
    return palette


def use_light_theme(app: QGuiApplication) -> None:
    """Keep DocRepo light even when Windows is in dark mode. Call it before any window is made."""
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8 and later; Windows 11's style draws its controls by the colour scheme
        hints.setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(light_palette())


#: The formatting buttons above a content text box (``rich_edit.FormatBar``), in both windows.
FORMAT_BAR_STYLE = """
QWidget#formatBar QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 1px 6px; color: #1a1f25; }
QWidget#formatBar QToolButton:hover { border-color: #b8c1cb; }
QWidget#formatBar QToolButton:checked { background: #dbe8f5; border-color: #9dc0e3; }
"""

#: The task page's notes (releases 5.25 to 5.27): its frame, the page and the Checklist summary, in the browse window.
NOTES_STYLE = """
QWidget#taskPaneInner, QWidget#notesWrap { background: #ffffff; }
QFrame#notesCard { background: #ffffff; border: 1px solid #b8c1cb; border-radius: 4px; }
QFrame#notesCard[typing="true"] { border: 1px solid #1d5e98; }
QFrame#notesCard QWidget#notesHead { background: #f4f6f8; border: none; border-bottom: 1px solid #d6dce3; }
QTextEdit#notesPage { border: none; background: transparent; padding: 0; }
QLabel#notesSaved { color: #5a6571; }
QWidget#summaryBox { background: transparent; }
QWidget#checkRow:hover { background: #eef1f4; }
QTextEdit#checkText { border: none; background: transparent; padding: 0; }
QLabel#checkCount, QLabel#checkHeading { color: #5a6571; }
QToolButton#checkFold, QToolButton#rowAction { border: none; background: transparent; }
"""

STYLE = FORMAT_BAR_STYLE + NOTES_STYLE + """
QWidget#capture { background: #ffffff; color: #1a1f25; font-family: "Segoe UI"; font-size: 10pt; }
QWidget#header { background: #f4f6f8; border-bottom: 1px solid #d6dce3; }
QLabel#appName { font-weight: 600; }
QLabel#hotkey { color: #87919c; font-family: Consolas; font-size: 8pt;
                border: 1px solid #d6dce3; border-radius: 3px; padding: 1px 4px; }
QLabel#fieldLabel { color: #5a6571; font-size: 9pt; }
QLabel#hint { color: #5a6571; font-size: 8.5pt; }
QLabel#does { background: #dbe8f5; border-left: 3px solid #1d5e98; padding: 6px 10px; }
QLabel#error { background: #fbe3e1; color: #b0261e; padding: 6px 10px; border-radius: 4px; }
QLabel#tip { background: #dbe8f5; border: 1px solid #9dc0e3; border-radius: 5px; padding: 6px 9px; font-size: 9pt; }
QFrame#found { background: #fcefcf; border: 1px solid #875700; border-radius: 6px; }
QFrame#found[empty="true"] { background: #f4f6f8; border: 1px dashed #b8c1cb; }
QFrame#items, QFrame#agendaPanel { background: #f4f6f8; border: 1px solid #d6dce3; border-radius: 6px; }
QFrame#items[empty="true"] { border-style: dashed; border-color: #b8c1cb; }
QFrame#itemCard { background: #ffffff; border: 1px solid #d6dce3; border-left: 3px solid #b8c1cb; border-radius: 4px; }
QFrame#itemCard[kind="task"] { border-left-color: #3b78c4; }
QFrame#itemCard[kind="note"] { border-left-color: #2e9483; }
QFrame#itemCard[kind="update"] { border-left-color: #c08419; }
QFrame#itemCard[kind="decision"] { border-left-color: #8460c2; }
QFrame#itemCard[kind="self"] { border-left-color: #1d5e98; }
QFrame#itemCard[kind="date"] { border-left-color: #b07a12; }
QFrame#itemCard[kind="param"] { border-left-color: #b07a12; }
QFrame#itemCard QLabel { background: transparent; border: none; }
QListWidget#refPopup { background: #ffffff; border: 1px solid #b8c1cb; border-radius: 4px; }
QListWidget#refPopup::item:selected { background: #dbe8f5; color: #1a1f25; }
QFrame#divider { color: #d6dce3; }
QPushButton#today { border: 1px solid #b8c1cb; border-radius: 11px; background: #ffffff; padding: 2px 10px; }
QPushButton#today:checked { background: #1d5e98; border-color: #1d5e98; color: #ffffff; }
QPushButton#today:disabled { color: #b8c1cb; border-color: #d6dce3; }
QFrame#fileRow { border: 1px solid #d6dce3; border-radius: 5px; }
QGroupBox { background: #f4f6f8; border: 1px solid #d6dce3; border-radius: 6px; margin-top: 14px; padding: 10px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #87919c; font-size: 8.5pt; font-weight: 600; }
QToolButton#info { min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border: 1px solid #b8c1cb; border-radius: 8px;
                   color: #5a6571; font: italic bold 8pt Georgia; padding: 0; }
QToolButton#info:checked, QToolButton#info:hover { background: #1d5e98; border-color: #1d5e98; color: #ffffff; }
QToolButton#chip { border: 1px solid #b8c1cb; border-radius: 9px; background: #e9edf1; padding: 1px 6px; }
QToolButton#chip[filled="true"] { background: #fcefcf; border-color: #875700; color: #875700; }
QFrame#personChip { border: 1px solid #b8c1cb; border-radius: 9px; background: #e9edf1; }
QFrame#personChip:focus { border: 1px solid #1d5e98; }
QFrame#personChip QToolButton { border: none; background: transparent; padding: 0 2px; }
QFrame#personChip QLabel#personShare { color: #1d5e98; font-weight: 600; }
QFrame#involvementBox { border: 1px solid #b8c1cb; background: #ffffff; }
QFrame#tieBox { border: 1px solid #b8c1cb; background: #ffffff; }
QWidget#chips { border: 1px solid #b8c1cb; border-radius: 4px; background: #ffffff; }
QWidget#chips QLineEdit { background: transparent; border: none; }
QLineEdit[filled="true"], QPlainTextEdit[filled="true"], QComboBox[filled="true"] { background: #fcefcf; border: 1px solid #875700; }
QCheckBox[filled="true"] { background: #fcefcf; }
QPushButton#primary { background: #1d5e98; color: #ffffff; border: 1px solid #1d5e98; border-radius: 4px; padding: 4px 14px; }
QPushButton#primary:hover { background: #174d7d; }
QPushButton#link, QPushButton#moreLink { border: none; color: #1d5e98; text-decoration: underline; text-align: left; padding: 0; }
QWidget#footer { background: #f4f6f8; border-top: 1px solid #d6dce3; }
QListWidget#suggestions { border: 1px solid #b8c1cb; border-radius: 4px; }
QLabel#help { color: #5a6571; font-size: 8.5pt; }
QFrame#editor { border: none; }
QWidget#pinWindow { background: #ffffff; border: 1px solid #b8c1cb; }
QWidget#pinWindow QTextEdit { border: 1px solid #b8c1cb; border-radius: 4px; padding: 4px 6px; }
QPushButton#pinTask { text-align: left; padding: 2px 6px; font-weight: 600; }
QFrame#dropZone QLineEdit { border: none; background: transparent; }
QLabel#pinTitle { font-weight: 600; }
QFrame#dropZone { background: #f4f6f8; border: 1px dashed #87919c; border-radius: 6px; }
QFrame#dropZone[over="true"] { background: #e8f0f8; border: 1px solid #1d5e98; }
"""
#: Release 5.9's style sheet, the Classic look's.
CLASSIC_STYLE = STYLE


_QSS_CACHE: list[str] = []


def style_sheet() -> str:
    """The style sheet a window sets on itself: the Classic look's, or the new look's from the tokens. When DocRepo runs,
    the new look's is set once on the application instead (``apply_look``), so this is empty: Qt parses it only once."""
    if LOOK.classic:
        return CLASSIC_STYLE
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
    from docrepo.detail import CSS as CLASSIC_CSS

    return CLASSIC_CSS if LOOK.classic else tokens.CSS


def apply_look(app: QGuiApplication, look: str = "new", hints: bool = False) -> None:
    """Set the look up from Settings, once the application exists and before any window is made."""
    configure(look, hints)
    if LOOK.classic:
        app.setFont(QFont("Segoe UI", 9))
        use_light_theme(app)
        return
    hints_ = app.styleHints()
    if hasattr(hints_, "setColorScheme"):  # Qt 6.8: light, whatever Windows is set to (a dark theme comes later, decision 14)
        hints_.setColorScheme(Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    app.setPalette(tokens.palette())
    app.setFont(tokens.ui_font())
    LOOK.app_sheet = False
    style_sheet()  # sets the new look's style sheet on the application, once
