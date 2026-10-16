"""The capture window's look: close to the browse tool mockup, on top of Windows' own widgets."""

STYLE = """
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
QFrame#fileRow { border: 1px solid #d6dce3; border-radius: 5px; }
QGroupBox { background: #f4f6f8; border: 1px solid #d6dce3; border-radius: 6px; margin-top: 14px; padding: 10px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #87919c; font-size: 8.5pt; font-weight: 600; }
QToolButton#info { min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border: 1px solid #b8c1cb; border-radius: 8px;
                   color: #5a6571; font: italic bold 8pt Georgia; padding: 0; }
QToolButton#info:checked, QToolButton#info:hover { background: #1d5e98; border-color: #1d5e98; color: #ffffff; }
QToolButton#chip { border: 1px solid #b8c1cb; border-radius: 9px; background: #e9edf1; padding: 1px 6px; }
QToolButton#chip[filled="true"] { background: #fcefcf; border-color: #875700; color: #875700; }
QWidget#chips { border: 1px solid #b8c1cb; border-radius: 4px; background: #ffffff; }
QLineEdit[filled="true"], QPlainTextEdit[filled="true"], QComboBox[filled="true"] { background: #fcefcf; border: 1px solid #875700; }
QCheckBox[filled="true"] { background: #fcefcf; }
QPushButton#primary { background: #1d5e98; color: #ffffff; border: 1px solid #1d5e98; border-radius: 4px; padding: 4px 14px; }
QPushButton#primary:hover { background: #174d7d; }
QPushButton#link, QPushButton#moreLink { border: none; color: #1d5e98; text-decoration: underline; text-align: left; padding: 0; }
QWidget#footer { background: #f4f6f8; border-top: 1px solid #d6dce3; }
QListWidget#suggestions { border: 1px solid #b8c1cb; border-radius: 4px; }
"""
