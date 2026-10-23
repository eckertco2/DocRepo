"""The windows' look: close to the browse tool mockup, on top of Windows' own widgets.

DocRepo's colours are light. With Windows in dark mode, Qt would draw its own
controls dark and mix them with those light colours, so ``use_light_theme``
keeps the whole app light, whatever Windows is set to.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

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

STYLE = FORMAT_BAR_STYLE + """
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
QWidget#chips { border: 1px solid #b8c1cb; border-radius: 4px; background: #ffffff; }
QWidget#chips QLineEdit { background: transparent; border: none; }
QLineEdit[filled="true"], QPlainTextEdit[filled="true"], QComboBox[filled="true"] { background: #fcefcf; border: 1px solid #875700; }
QCheckBox[filled="true"] { background: #fcefcf; }
QPushButton#primary { background: #1d5e98; color: #ffffff; border: 1px solid #1d5e98; border-radius: 4px; padding: 4px 14px; }
QPushButton#primary:hover { background: #174d7d; }
QPushButton#link, QPushButton#moreLink { border: none; color: #1d5e98; text-decoration: underline; text-align: left; padding: 0; }
QWidget#footer { background: #f4f6f8; border-top: 1px solid #d6dce3; }
QListWidget#suggestions { border: 1px solid #b8c1cb; border-radius: 4px; }
"""
