"""The visual overhaul's design tokens (``docs/ui-design`` in the parent workspace: the playbook and decisions 1 to 18).

One place holds every colour, size and spacing the new look uses. They generate the QPalette, the style sheet and the
pages' HTML styles, so no widget code needs a colour of its own. Light values are used now; the dark names are reserved
and filled in, so a dark theme is a change of values, not of code (decision 14).
"""
from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

# ---- colour (decisions 8, 9, 11 to 13; contrast checked against WCAG 2.2 AA) ----
LIGHT = {
    "base": "#f4f6f8",        # the window's base layer: the sidebar, toolbars, footers
    "content": "#ffffff",     # the content layer: lists, pages, inputs, cards
    "hover": "#eef1f4",
    "pressed": "#e3e7ec",
    "selected": "#dbe8f5",    # a selected row, with the accent bar beside it
    "text": "#1a1f25",        # 16.6:1 on white
    "text2": "#5a6571",       # secondary text, 5.9:1 on white
    "disabled": "#87919c",    # disabled controls only
    "stroke": "#e3e6ea",      # cards, dividers, pane edges, an input's outline
    "stroke_strong": "#d6dce3",
    "control": "#7d8793",     # an input's bottom edge, a tick box's outline: 3.6:1 on white
    "accent": "#1d5e98",      # the one accent: primary buttons, links, focus, selection
    "accent_hover": "#174d7d",
    "accent_pressed": "#123e66",
    "on_accent": "#ffffff",
    "caution": "#9d5d00", "caution_bg": "#fff4ce", "caution_line": "#ead9a4",   # filled from the capture text, warnings
    "critical": "#c42b1c", "critical_bg": "#fde7e9",                           # overdue, over capacity, errors
    "success": "#0f7b0f", "success_bg": "#dff6dd",
    "scroll": "#c3cbd4", "scroll_hover": "#9aa4af",
    # Categories: the top-level tasks' colours (decision 9), as marks, never as text.
    "g1": "#3b78c4", "g2": "#2e9483", "g3": "#c08419", "g4": "#8460c2",
}
#: The dark theme's values, reserved for later (decision 14): the same names, not yet used.
DARK = {
    "base": "#202020", "content": "#2b2b2b", "hover": "#333333", "pressed": "#3a3a3a", "selected": "#1f3447",
    "text": "#ffffff", "text2": "#c5c5c5", "disabled": "#7a7a7a", "stroke": "#3a3a3a", "stroke_strong": "#454545",
    "control": "#9a9a9a", "accent": "#7cb0e2", "accent_hover": "#93bfe8", "accent_pressed": "#6aa2d8", "on_accent": "#0c1622",
    "caution": "#e8b85c", "caution_bg": "#3a2e13", "caution_line": "#5a4720", "critical": "#f3968e", "critical_bg": "#3e1f1c",
    "success": "#82d098", "success_bg": "#1b3323", "scroll": "#555555", "scroll_hover": "#777777",
    "g1": "#6fa6e8", "g2": "#56c2b0", "g3": "#dca64a", "g4": "#ad8ee8",
}
GROUP_KEYS = ("g1", "g2", "g3", "g4")

# ---- type (decisions 1 and 2): Windows 11's ramp, in points for Qt (1 pt is 1.333 px at 100%) ----
CAPTION, BODY, SUBTITLE, TITLE = 9.0, 10.5, 15.0, 21.0

# ---- sizes and spacing (decision 3): a 4 px grid, and WinUI's standard heights ----
SPACE = {"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16, "xxl": 24, "xxxl": 32}
CONTROL = 32      # inputs and buttons
ICON_BUTTON = 28  # toolbar icon buttons, with a 16 px icon
TREE_ROW = 28
LIST_ROW = 32
RADIUS = 4        # controls; windows, menus and dialogs use 8


def colour(name: str) -> str:
    return LIGHT[name]


def group_colour(group: int) -> str:
    """A top-level task's colour: the four categories in turn, grey for none."""
    return LIGHT["stroke_strong"] if group < 0 else LIGHT[GROUP_KEYS[group % len(GROUP_KEYS)]]


# ---- fonts (decision 1): Segoe UI Variable where Windows has it, Segoe UI otherwise; numbers in Segoe UI ----
def _has_variable() -> bool:
    try:
        return "Segoe UI Variable" in QFontDatabase.families()
    except Exception:  # noqa: BLE001 - no font database yet (no application)
        return False


def ui_font(size: float = BODY, semibold: bool = False, role: str = "Text") -> QFont:
    """The UI font at ``size`` points. ``role`` is Segoe UI Variable's optical size: Small, Text or Display."""
    if _has_variable():
        f = QFont("Segoe UI Variable")
        f.setStyleName(f"{role} Semibold" if semibold else role)
    else:
        f = QFont("Segoe UI")
        f.setWeight(QFont.Weight.DemiBold if semibold else QFont.Weight.Normal)
    f.setPointSizeF(size)
    return f


def numeric_font(size: float = BODY) -> QFont:
    """Dates, times, hours and counts: Segoe UI Regular, whose digits all have the same width, so columns line up."""
    f = QFont("Segoe UI")
    f.setPointSizeF(size)
    return f


def palette() -> QPalette:
    """The full QPalette for the Fusion style, from the light tokens. Every role is set, so nothing falls back to the
    system's colours (which, in Windows' dark mode, would mix dark controls into a light window)."""
    t = LIGHT
    roles = {
        QPalette.ColorRole.Window: t["base"], QPalette.ColorRole.WindowText: t["text"], QPalette.ColorRole.Base: t["content"],
        QPalette.ColorRole.AlternateBase: t["base"], QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["content"],
        QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.BrightText: t["on_accent"], QPalette.ColorRole.Highlight: t["selected"],
        QPalette.ColorRole.HighlightedText: t["text"], QPalette.ColorRole.ToolTipBase: t["content"], QPalette.ColorRole.ToolTipText: t["text"],
        QPalette.ColorRole.PlaceholderText: t["text2"], QPalette.ColorRole.Link: t["accent"], QPalette.ColorRole.LinkVisited: t["accent"],
        QPalette.ColorRole.Light: t["content"], QPalette.ColorRole.Midlight: t["hover"], QPalette.ColorRole.Mid: t["stroke_strong"],
        QPalette.ColorRole.Dark: t["control"], QPalette.ColorRole.Shadow: t["text2"], QPalette.ColorRole.Accent: t["accent"],
    }
    p = QPalette()
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["disabled"]))
    return p


# ---- the style sheet: every widget's look in one place ----
_QSS = Template("""
QWidget#capture, QWidget#browse, QDialog { background: $content; color: $text; }
QToolTip { background: $content; color: $text; border: 1px solid $stroke_strong; padding: 4px 8px; }

/* text fields: a soft outline with a 3:1 bottom edge, and the accent there when focused (decision 11) */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {
  background: $content; color: $text; border: 1px solid $stroke; border-bottom: 1px solid $control; border-radius: 4px;
  selection-background-color: $selected; selection-color: $text; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit { padding: 5px 8px; min-height: 20px; }
QPlainTextEdit, QTextEdit { padding: 4px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {
  border-bottom: 2px solid $accent; }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: $base; color: $disabled; }
QLineEdit[readOnly="true"] { background: $base; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("$arrow"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: $content; border: 1px solid $stroke_strong; selection-background-color: $hover;
  selection-color: $text; outline: 0; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QTimeEdit::up-button,
QTimeEdit::down-button { width: 0; border: none; }
/* filled from the capture text (decision 8): a soft caution tint and a marker, until it's edited */
QLineEdit[filled="true"], QPlainTextEdit[filled="true"], QComboBox[filled="true"] {
  background: $caution_bg; border-color: $caution_line; border-bottom-color: $caution; }
QLineEdit[filled="true"] { background-image: url("$marker"); background-repeat: no-repeat; background-position: right center;
  padding-right: 24px; }
QCheckBox[filled="true"] { background: $caution_bg; border-radius: 4px; }

/* buttons: neutral by default, one accent button per window (the objectName "primary"), 32 px high */
QPushButton { background: $content; color: $text; border: 1px solid $stroke_strong; border-radius: 4px; padding: 5px 12px;
  min-height: 20px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:checked { background: $selected; border-color: $selected; color: $accent; }
QPushButton:disabled { color: $disabled; background: $base; border-color: $stroke; }
QPushButton#primary { background: $accent; color: $on_accent; border-color: $accent; font-weight: 600; padding: 5px 16px; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_pressed; }
QPushButton#subtle, QToolButton#subtle { background: transparent; border: 1px solid transparent; }
QPushButton#subtle:hover, QToolButton#subtle:hover { background: $hover; }
QPushButton#subtle:checked, QToolButton#subtle:checked { background: $selected; color: $accent; }
QPushButton#link, QPushButton#moreLink, QPushButton#rowLink { background: transparent; border: none; color: $accent; padding: 0 2px;
  min-height: 0; text-align: left; }
QPushButton#link:hover, QPushButton#moreLink:hover, QPushButton#rowLink:hover { text-decoration: underline; }
QPushButton::menu-indicator { image: url("$arrow"); width: 12px; height: 12px; subcontrol-origin: padding; subcontrol-position: right center;
  right: 6px; }
QPushButton[menu="true"] { padding-right: 24px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px; color: $text; }
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $pressed; }
QToolButton:checked { background: $selected; color: $accent; }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton[popupMode="1"] { padding-right: 14px; }
QToolButton::menu-button { border: none; background: transparent; width: 12px; }
QToolButton::menu-arrow { image: url("$arrow"); width: 10px; height: 10px; }
QToolButton#iconButton { min-width: 20px; min-height: 20px; }

/* the capture types: toggles that combine, in one segmented strip */
QWidget#typeStrip { background: $base; border: 1px solid $stroke; border-radius: 6px; }
QCheckBox#typeToggle { color: $text2; padding: 5px 12px; border-radius: 4px; spacing: 0; }
QCheckBox#typeToggle::indicator { width: 0; height: 0; border: none; }
QCheckBox#typeToggle:hover { color: $text; background: $hover; }
QCheckBox#typeToggle:checked { background: $content; color: $text; font-weight: 600; border: 1px solid $stroke; border-bottom: 2px solid $accent; }
QCheckBox#typeToggle:disabled { color: $disabled; }

/* tick boxes and radio buttons */
QCheckBox, QRadioButton { spacing: 8px; color: $text; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $control; border-radius: 3px; background: $content; }
QCheckBox::indicator:hover { border-color: $text2; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$tick"); }
QCheckBox::indicator:disabled { border-color: $stroke_strong; background: $base; }

/* menus */
QMenu { background: $content; border: 1px solid $stroke_strong; padding: 4px; }
QMenu::item { padding: 6px 28px 6px 12px; border-radius: 4px; color: $text; }
QMenu::item:selected { background: $hover; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $stroke; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 6px; }

/* tabs: an underline strip */
QTabWidget::pane { border: none; border-top: 1px solid $stroke; }
QTabBar::tab { background: transparent; color: $text2; padding: 6px 12px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; font-weight: 600; border-bottom-color: $accent; }

/* lists, trees and tables */
QTreeView, QListView, QTableView { background: $content; border: none; outline: 0; selection-background-color: $selected;
  selection-color: $text; alternate-background-color: $content; }
QTreeView::item, QListView::item { padding: 2px 4px; }
QTreeView::item:hover, QListView::item:hover { background: $hover; }
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected { background: $selected; color: $text; }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:closed { image: url("$branch_closed"); }
QTreeView::branch:has-children:open { image: url("$branch_open"); }
QHeaderView { background: $content; border: none; }
QHeaderView::section { background: $content; color: $text2; border: none; border-bottom: 1px solid $stroke; padding: 6px 8px;
  font-size: ${caption}pt; }
QTableView { gridline-color: $stroke; }
QTableCornerButton::section { background: $content; border: none; }

/* scroll bars: thin, no arrows */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 28px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: $stroke; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

/* groups become headings with space around them, not boxes */
QGroupBox { border: none; margin-top: 0; padding: 0; background: transparent; }
QGroupBox[title=""] { margin-top: 0; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 0; padding: 0; color: $text; }
QLabel#heading { font-weight: 600; color: $text; }
QLabel#subtitle { font-size: ${subtitle}pt; font-weight: 600; color: $text; }

/* text roles */
QLabel#fieldLabel { color: $text2; font-size: ${caption}pt; }
QLabel#hint, QLabel#help, QLabel#paneNote { color: $text2; font-size: ${caption}pt; }
QLabel#does { color: $text2; font-size: ${caption}pt; }
QLabel#error { color: $critical; font-size: ${caption}pt; font-weight: 600; background: transparent; padding: 0; }
QLabel#tip { color: $text; background: $selected; border-radius: 4px; padding: 6px 9px; font-size: ${caption}pt; }
QLabel#hotkey { color: $text2; font-family: Consolas; font-size: ${caption}pt; border: 1px solid $stroke; border-radius: 3px; padding: 1px 4px; }
QLabel#paneTitle { font-size: ${subtitle}pt; font-weight: 600; color: $text; }
QLabel#count { color: $text2; font-size: ${caption}pt; }
QToolButton#info { min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border: 1px solid $control; border-radius: 8px;
  color: $text2; font-size: 8pt; font-weight: 600; padding: 0; }
QToolButton#info:checked, QToolButton#info:hover { background: $accent; border-color: $accent; color: $on_accent; }
QLabel#keyTip { background: $text; color: $content; border-radius: 3px; padding: 0 5px; font-size: ${caption}pt; font-weight: 600; }

/* the capture window */
QWidget#capture QScrollArea, QWidget#capture QScrollArea > QWidget > QWidget { background: $content; }
QWidget#footer { background: $base; border-top: 1px solid $stroke; }
QFrame#editor { background: $content; border: 1px solid $stroke; border-bottom: 1px solid $control; border-radius: 4px; }
QFrame#editor QTextEdit, QFrame#editor QPlainTextEdit { border: none; border-radius: 0; background: transparent; padding: 6px 8px; }
QWidget#formatBar { border-bottom: 1px solid $stroke; }
QWidget#formatBar QToolButton { color: $text2; padding: 3px 6px; min-width: 16px; }
QWidget#formatBar QToolButton:hover { color: $text; background: $hover; border-color: $stroke; }
QWidget#formatBar QToolButton:checked { color: $accent; background: $selected; }
QFrame#found { background: $caution_bg; border: none; border-radius: 4px; }
QFrame#found[empty="true"] { background: $base; }
QFrame#items, QFrame#agendaPanel { background: $base; border: none; border-radius: 6px; }
QFrame#items[empty="true"] { background: transparent; }
QFrame#itemCard { background: $content; border: 1px solid $stroke; border-left: 3px solid $stroke_strong; border-radius: 0; }
QFrame#itemCard QLabel { background: transparent; border: none; }
QListWidget#refPopup, QListWidget#suggestions { background: $content; border: 1px solid $stroke_strong; border-radius: 4px; padding: 2px; }
QListWidget#refPopup::item:selected, QListWidget#suggestions::item:selected { background: $hover; color: $text; }
QFrame#divider { color: $stroke; }
QPushButton#today { background: transparent; border: 1px solid transparent; }
QPushButton#today:hover { background: $hover; }
QPushButton#today:checked { background: $selected; color: $accent; border-color: $selected; }
QFrame#fileRow { border: 1px solid $stroke; border-radius: 6px; background: $content; }
QToolButton#chip { border: 1px solid $stroke; border-radius: 10px; background: $hover; padding: 1px 8px; font-size: ${caption}pt; }
QToolButton#chip[filled="true"] { background: $caution_bg; border-color: $caution_line; color: $text; }
QWidget#chips { border: 1px solid $stroke; border-bottom: 1px solid $control; border-radius: 4px; background: $content; }
QWidget#chips QLineEdit { background: transparent; border: none; padding: 4px 2px; min-height: 20px; }
QWidget#chips QLineEdit:focus { border: none; }

/* the browse tool */
QWidget#toolbar { background: $base; border-bottom: 1px solid $stroke; }
QWidget#paneHead { background: $content; border-bottom: 1px solid $stroke; }
QWidget#actions { background: $content; }
QLabel#status { background: $base; border-top: 1px solid $stroke; color: $text; padding: 4px 12px; font-size: ${caption}pt; }
QLabel#status[error="true"] { background: $critical_bg; color: $critical; }
QTreeWidget#nav { background: $base; border: none; }
QTextBrowser { border: none; background: $content; }
QWidget#settingsCard { background: $content; border: 1px solid $stroke; border-radius: 6px; }
""")


def qss() -> str:
    """The new look's style sheet, from the tokens."""
    from docrepo.ui.icons import file_url  # the icons module reads the tokens too

    return _QSS.substitute(LIGHT, caption=CAPTION, subtitle=SUBTITLE, arrow=file_url("arrow-down-grey"), tick=file_url("tick-white"),
                           marker=file_url("filled-marker"), branch_closed=file_url("chevron-right"), branch_open=file_url("chevron-down"))


#: The pages' and the list cells' HTML styles (Qt's rich text), from the same tokens. Numbers use Segoe UI so they line up.
CSS = Template("""
body { color: $text; }
a { color: $accent; text-decoration: none; }
h2 { font-size: ${subtitle}pt; font-weight: 600; margin-top: 2px; margin-bottom: 4px; }
.crumbs { color: $text2; font-size: ${caption}pt; margin: 0; }
.sub { color: $text2; font-size: ${caption}pt; }
.faint { color: $text2; }
.k { color: $text2; padding-right: 12px; }
.note { color: $text2; font-size: ${caption}pt; }
.box { background-color: $base; }
.info { background-color: $selected; }
.warn { background-color: $caution_bg; }
.tab { color: $text2; }
.tabon { color: $text; font-weight: 600; border-bottom: 2px solid $accent; }
.day { color: $text2; font-size: ${caption}pt; font-family: 'Segoe UI'; }
.month { color: $text2; font-size: ${caption}pt; font-weight: 600; }
.lead { color: $text2; font-size: ${caption}pt; }
.facts { color: $text2; font-size: ${caption}pt; }
.text { white-space: pre-wrap; }
.chs { color: $text2; font-size: ${caption}pt; font-weight: 600; }
.ch { background-color: $base; }
.num { font-family: 'Segoe UI'; }
.st-ns { color: $text2; background-color: $hover; }
.st-ip { color: $accent; background-color: $selected; }
.st-pk { color: #585a70; background-color: #eae8f2; }
.st-cl { color: $text2; background-color: $hover; }
.urgent { color: $critical; background-color: $critical_bg; font-weight: 600; }
.routine { color: $text; background-color: $hover; }
.multi { color: $accent; background-color: $selected; }
.lbl { color: $text; background-color: $hover; }
.inh { color: $text2; font-style: italic; }
.new { color: $caution; background-color: $caution_bg; }
.u1 { }
.u2 { background-color: $selected; }
.u3 { color: $critical; background-color: $critical_bg; font-weight: 600; }
.away { color: $text2; background-color: $hover; }
""").substitute(LIGHT, caption=CAPTION, subtitle=SUBTITLE)
