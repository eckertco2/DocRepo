"""The visual overhaul's design tokens (``docs/ui-design`` in the parent workspace: the playbook and decisions 1 to 18).

One place holds every colour, size and spacing the new look uses. They generate the QPalette, the style sheet and the
pages' HTML styles, so no widget code needs a colour of its own. The colours answer from the active theme (release 5.180,
the redesign's decision 841): ``use("dark")`` before the look is set up (``style.apply_look``) and everything drawn after it
is dark. Light is the one offered; dark's values are filled in, for release 5.194 to settle (decision 14).
"""
from __future__ import annotations

from string import Template

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

# ---- colour (decisions 8, 9, 11 to 13; contrast checked against WCAG 2.2 AA): the values are in ``docrepo.colours``, which
# pages made without Qt read too; ``use`` sets the active theme (release 5.180, decision 841), and every colour below and in
# the windows is read from it when it's drawn ----
from docrepo.colours import DARK, LIGHT, THEMES, C, LiveList, LiveMap, active, colour, theme, use  # noqa: F401 - re-exported: docrepo.ui reads them here

GROUP_KEYS = ("g1", "g2", "g3", "g4")

# ---- type (decisions 1 and 2): Windows 11's ramp, in points for Qt (1 pt is 1.333 px at 100%) ----
#: The type scale (release 5.181, the redesign's decision 849), still Segoe UI Variable: one large title a screen, smaller and
#: greyer facts. ``SUBTITLE`` and ``TITLE`` are Windows' ramp, kept for the dialogs' subtitles.
PAGE_TITLE = 19.0       # a page's title: the pages' h2 and the workspace's, semibold, in the Display cut where a widget draws it
VIEW_TITLE = 11.5       # a view's title over its list (paneTitle), semibold
SECTION = 10.0          # a section's head on a page, semibold
BODY = 10.5             # body text and rows
NOTES = 11.0            # the notes' words
CAPTION = 9.5           # facts and secondary lines, in the third grey
LABEL = 9.0             # a field's name, a group's label (semibold), a column's head
SUBTITLE, TITLE = 15.0, 21.0
#: Text sizes off the scale, each a name of its own (release 5.180).
TOPIC = 12              # All notes' topic bands, and their loose notes' heading (release 5.157, By topic)
INITIALS = 12           # a person's initials in the quick summary's face
ZONE_TITLE, ZONE_LINE = 16, 10        # Save or link's two zones: the title, and the line under it
ZONE_TITLE_S, ZONE_LINE_S = 11, 8     # the same, compact
SMALLEST = 7.0          # the least the Timeline's small words shrink to
MARK_PX, SMALLEST_PX = 10, 7          # words sized in pixels: an avatar's initials and the timing chart's ruler; the least a mark's
#: The classes Windows' theme gives their own font, so the application's font doesn't reach them (release 5.57).
BODY_FONT_CLASSES = ("QAbstractItemView", "QMenu", "QMenuBar", "QMessageBox", "QDockWidgetTitle")

# ---- sizes and spacing (decision 3): a 4 px grid, and WinUI's standard heights ----
SPACE = {"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16, "xxl": 24, "xxxl": 32}
CONTROL = 32      # buttons, and the type strip
FIELD = 34        # a field: one line of text, a combo box, a spin box, a date (release 5.181, decision 848)
ICON_BUTTON = 28  # toolbar icon buttons, with a 16 px icon
TREE_ROW = 28
LIST_ROW = 32
#: The corner scale (release 5.181, the redesign's decision 845): four sizes for today's nine.
RADIUS_S = 6      # rows, chips and small controls: a row's tint, a chip, a tag, a subtask's row on a Priorities card
RADIUS = 8        # buttons and fields
RADIUS_L = 10     # cards and panels: the status card, a Priorities column, a settings card, a file's row, a Today bin
RADIUS_XL = 12    # what floats: a popover, the task picker, a drop's overlay (Windows rounds the floating windows themselves)
RADIUS_BOX = 5    # a tick box's corners and a key cap's, as the mock's Foundations board draws them
#: The small marks' corners (release 5.180), each the half of a thin bar's width or a mark's own.
RADIUS_HAIR = 1     # a 2 px line's ends (the timing chart's), the Priorities board's drop line
RADIUS_TICK = 0.75  # a depth tick's ends, 1.5 px wide (the task tile)
RADIUS_EDGE = 1.5   # a 3 px edge bar's round ends: a selected row's, a priority's
RADIUS_BAR = 2      # thin bars and small marks: a progress bar, a swatch, a priority's box, the Timeline's thin bars
#: Sizes for new code, beside SPACE (release 5.102): row heights, icon sizes and control heights, as the code already uses
#: them. New code names these rather than writing a number; the literals already in ``ui/`` stay as they are.
SIZE = {
    # rows
    "row_tree": TREE_ROW,         # the task tree, and the lists drawn like it
    "row_head": 30,               # a group's heading in a painted list (the Task view's)
    "row_list": LIST_ROW,         # a one-line list row, such as an agenda's or a compact result
    "row_two_line": 48,           # a row of two lines: a title, then a line of facts
    # icons
    "icon_xs": 10,                # a mark inside a small control
    "icon_s": 14,                 # a chevron, a pin or a menu's mark
    "icon": 16,                   # a toolbar's, a button's or a row's icon
    "icon_l": 20,                 # an item's type in a two-line row
    # controls
    "control_s": 24,              # a small square button on a row or a card
    "icon_button": ICON_BUTTON,   # a toolbar's icon button, holding a 16 px icon
    "control": CONTROL,           # inputs and buttons
}


def group_colour(group: int) -> str:
    """A top-level task's colour: the four categories in turn, grey for none."""
    return colour("stroke_strong") if group < 0 else colour(GROUP_KEYS[group % len(GROUP_KEYS)])


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
    """The full QPalette for the Fusion style, from the active theme's tokens. Every role is set, so nothing falls back to the
    system's colours (which, in Windows' dark mode, would mix dark controls into a light window)."""
    t = active()
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

/* text fields (release 5.181, decision 848): one even 1 px edge, 8 px corners, 34 px high; focus the accent edge, 2 px, with a
   pixel of padding off so a field keeps its size */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {
  background: $content; color: $text; border: 1px solid $stroke_strong; border-radius: ${radius}px;
  selection-background-color: $selected; selection-color: $text; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit { padding: 6px 8px; min-height: 20px; max-height: 20px; }
QPlainTextEdit, QTextEdit { padding: 5px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QDateEdit:focus { border: 2px solid $accent; padding: 5px 7px; }
QPlainTextEdit:focus, QTextEdit:focus { border: 2px solid $accent; padding: 4px; }
/* the text box inside a combo box or a spin box: its parent has the outline and the height */
QComboBox QLineEdit, QComboBox QLineEdit:focus, QAbstractSpinBox QLineEdit, QAbstractSpinBox QLineEdit:focus {
  background: transparent; border: none; padding: 0; min-height: 0; }
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: $sunken; color: $disabled; border-color: $stroke; }
QLineEdit[readOnly="true"] { background: $sunken; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("$arrow"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: $content; border: 1px solid $stroke_strong; selection-background-color: $hover;
  selection-color: $text; outline: 0; padding: 5px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QTimeEdit::up-button,
QTimeEdit::down-button { width: 0; border: none; }
/* filled from the capture text (decision 8): a soft caution tint and a marker, until it's edited */
QLineEdit[filled="true"], QPlainTextEdit[filled="true"], QComboBox[filled="true"] {
  background: $caution_bg; border-color: $caution_line; }
QLineEdit[filled="true"] { background-image: url("$marker"); background-repeat: no-repeat; background-position: right center;
  padding-right: 26px; }
QCheckBox[filled="true"] { background: $caution_bg; border-radius: ${radius_s}px; }
QLineEdit#dateLine[filled="true"], QLineEdit#dateLine[filled="dot"] { background-position: left center; padding-left: 24px; padding-right: 10px; }  /* its calendar button has the right */
/* when Parse and populate filled most of a window, each field has only its dot: a tint on all of them says nothing */
QLineEdit[filled="dot"] { background-image: url("$marker"); background-repeat: no-repeat; background-position: right center;
  padding-right: 26px; }

/* keyboard focus is look.FocusRing's, over these: no focus frame of Fusion's under it */
QPushButton, QToolButton, QCheckBox, QRadioButton { outline: none; }

/* buttons (release 5.181, decision 847), 32 px high: the secondary a soft fill and no edge; one primary a window, filled with the
   accent (the objectName "primary"); the quiet one words and an icon, a fill only under the pointer ("subtle") */
QPushButton { background: $hover; color: $text; border: 1px solid transparent; border-radius: ${radius}px; padding: 5px 12px;
  min-height: 20px; }
QPushButton:hover { background: $pressed; }
QPushButton:pressed { background: $stroke_strong; }
QPushButton:checked { background: $selected; border-color: transparent; color: $accent; }
QPushButton:disabled { color: $disabled; background: $sunken; border-color: transparent; }
QPushButton#primary { background: $accent_fill; color: $on_accent; border-color: $accent_fill; font-weight: 600; padding: 5px 16px; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#primary:disabled { color: $disabled; background: $sunken; border-color: transparent; }
QPushButton#subtle, QToolButton#subtle { background: transparent; border: 1px solid transparent; color: $text2; }
QPushButton#subtle { padding: 5px 8px; }  /* a command bar's: tighter, so the bar keeps to one row */
QPushButton#subtle[menu="true"] { padding-right: 8px; text-align: left; }  /* its chevron close after its words */
QPushButton#subtle:hover, QToolButton#subtle:hover { background: $hover; color: $text2; }
QPushButton#subtle:pressed, QToolButton#subtle:pressed { background: $pressed; }
QPushButton#subtle:disabled, QToolButton#subtle:disabled { background: transparent; color: $disabled; }
QPushButton#subtle:checked, QToolButton#subtle:checked { background: $selected; color: $accent; }
/* links that are commands (release 5.181, decision 844, the accent's six jobs): grey, underlined under the pointer */
QPushButton#link, QPushButton#moreLink, QPushButton#rowLink { background: transparent; border: none; color: $text2; padding: 0 2px;
  min-height: 0; text-align: left; }
QPushButton#link:hover, QPushButton#moreLink:hover, QPushButton#rowLink:hover { text-decoration: underline; }
/* a row's actions, over the row: its colour, so what's under them doesn't show through */
QWidget#rowActions { background: $hover; }
QWidget#rowActions[sel="true"] { background: $selected; }
/* their icon buttons (release 5.78, decision L5): no frame, a tint under the pointer */
QPushButton#rowIcon { background: transparent; border: none; border-radius: ${radius_s}px; padding: 0; min-height: 0; min-width: 0; }
QPushButton#rowIcon:hover { background: $pressed; }
QPushButton::menu-indicator { image: url("$arrow"); width: 12px; height: 12px; subcontrol-origin: padding; subcontrol-position: right center;
  right: 6px; }
QPushButton[menu="true"] { padding-right: 8px; text-align: left; }
/* an icon-only button at the end of a command bar, such as the task page's More (release 5.21) */
QPushButton#iconOnly { background: transparent; border: 1px solid transparent; border-radius: ${radius}px; padding: 0; min-width: 26px; max-width: 26px;
  min-height: 26px; max-height: 26px; }
QPushButton#iconOnly:hover { background: $hover; }
QPushButton#iconOnly::menu-indicator { image: none; width: 0; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: ${radius}px; padding: 4px; color: $text; }
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $pressed; }
QToolButton:checked { background: $selected; color: $accent; }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton[popupMode="1"] { padding-right: 14px; }
QToolButton::menu-button { border: none; background: transparent; width: 12px; }
QToolButton::menu-arrow { image: url("$arrow"); width: 10px; height: 10px; }
/* 18 + 8 of padding + 2 of border: the token's 28 px, since a style sheet's sizes beat setFixedSize */
QToolButton#iconButton { min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; }
QToolButton#iconButton:checked { background: transparent; }  /* the icon says it, in the accent: no tile */
QToolButton#iconButton:checked:hover { background: $hover; }

/* the capture types: toggles that combine, in one segmented strip, the height of the controls beside it */
QWidget#typeStrip { background: $sunken; border: 1px solid transparent; border-radius: ${radius}px; min-height: 30px; max-height: 30px; }
QCheckBox#typeToggle { color: $text2; padding: 2px 12px; border-radius: ${radius_s}px; spacing: 0; border: 1px solid transparent; }
QCheckBox#typeToggle::indicator { width: 0; height: 0; border: none; }
QCheckBox#typeToggle:hover { color: $text; background: $hover; }
QCheckBox#typeToggle:checked { background: $content; color: $text; font-weight: 600; border: 1px solid $stroke; }
QCheckBox#typeToggle:disabled { color: $disabled; }

/* tick boxes and radio buttons */
QCheckBox, QRadioButton { spacing: 8px; color: $text; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $control; border-radius: ${radius_box}px; background: $content; }
QCheckBox::indicator:hover { border-color: $text2; }
QCheckBox::indicator:checked { background: $accent_fill; border-color: $accent_fill; image: url("$tick"); }
QCheckBox::indicator:disabled { border-color: $stroke_strong; background: $sunken; }

/* menus */
QMenu { background: $content; border: 1px solid $stroke_strong; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: ${radius_s}px; color: $text; }
QMenu::item:selected { background: $hover; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $stroke; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 6px; }

/* tabs: an underline strip */
QTabWidget::pane { border: none; border-top: 1px solid $stroke; }
QTabBar::tab { background: transparent; color: $text2; padding: 6px 12px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; font-weight: 600; border-bottom-color: $accent; }

/* lists, trees and tables */
QTreeView, QListView, QTableView { background: $content; border: none; outline: 0; selection-background-color: $selected;
  selection-color: $text; alternate-background-color: $content; }
QTreeView[tiled="true"] { background: $base; }
QTreeView::item, QListView::item { padding: 2px 4px; }
QTreeView::item:hover, QListView::item:hover { background: $hover; }
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected { background: $selected; color: $text; }
QTreeView::indicator { width: 16px; height: 16px; border: 1px solid $control; border-radius: ${radius_box}px; background: $content; }
QTreeView::indicator:hover { border-color: $text2; }
QTreeView::indicator:checked { background: $accent_fill; border-color: $accent_fill; image: url("$tick"); }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:closed { image: url("$branch_closed"); }
QTreeView::branch:has-children:open { image: url("$branch_open"); }
QHeaderView { background: $content; border: none; }
QHeaderView::section { background: $content; color: $text3; border: none; border-bottom: 1px solid $stroke; padding: 6px 8px;
  font-size: ${label}pt; font-weight: 600; }
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
QAbstractScrollArea::corner { background: transparent; }
QWidget#emptyState { background: transparent; }
/* the date fields' calendar: the icons' chevrons, and no blue bar across its top */
QCalendarWidget QWidget#qt_calendar_navigationbar { background: $base; }
QCalendarWidget QToolButton { color: $text; background: transparent; font-weight: 600; }
QCalendarWidget QToolButton#qt_calendar_prevmonth { qproperty-icon: url("$chev_left"); }
QCalendarWidget QToolButton#qt_calendar_nextmonth { qproperty-icon: url("$chev_right"); }
QCalendarWidget QAbstractItemView { selection-background-color: $selected; selection-color: $text; outline: 0; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: $stroke; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

/* groups become headings with space around them, not boxes */
QGroupBox { border: none; margin-top: 0; padding: 0; background: transparent; }
QGroupBox[title=""] { margin-top: 0; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 0; padding: 0; color: $text; }
QLabel#heading { font-weight: 600; color: $text; }
/* Subtitles name Segoe UI: under Segoe UI Variable's "Text" style a weight in a style sheet comes out light at this size. Its
   Semibold matches ui_font's. */
QLabel#subtitle { font-family: "Segoe UI"; font-size: ${subtitle}pt; font-weight: 600; color: $text; }

/* text roles */
QLabel#fieldLabel { color: $text3; font-size: ${label}pt; }
QLabel#hint, QLabel#help, QLabel#paneNote { color: $text3; font-size: ${caption}pt; }
QLabel#does { color: $text3; font-size: ${caption}pt; }
QLabel#error { color: $critical; font-size: ${caption}pt; font-weight: 600; background: transparent; padding: 0; }
QLabel#tip { color: $text; background: $selected; border-radius: ${radius}px; padding: 6px 9px; font-size: ${caption}pt; }
QLabel#hotkey { color: $text2; font-family: Consolas; font-size: ${caption}pt; border: 1px solid $stroke_strong; border-radius: ${radius_box}px; padding: 1px 6px; }
QLabel#paneTitle { font-family: "Segoe UI"; font-size: ${view_title}pt; font-weight: 600; color: $text; }
/* a page's own title in a widget (the workspace's, a capture's edit form), as the pages' h2 (release 5.181) */
QLabel#pageTitle { font-family: "Segoe UI"; font-size: ${page_title}pt; font-weight: 600; color: $text; }
QLabel#count { color: $text3; font-size: ${caption}pt; }
QToolButton#info { min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; border: 1px solid $control; border-radius: 8px;
  color: $text2; font-size: ${caption}pt; font-weight: 600; padding: 0; }
QToolButton#info:checked, QToolButton#info:hover { background: $accent_fill; border-color: $accent_fill; color: $on_accent; }
QLabel#keyTip { background: $text; color: $content; border-radius: ${radius_box}px; padding: 0 5px; font-size: ${caption}pt; font-weight: 600; }

/* the task page with its notes page (release 5.25): one white page; the notes are part of it, not a box on it */
QWidget#taskPaneInner, QWidget#notesWrap { background: $content; }
/* the notes' frame (release 5.27, decision 130): the capture window's editor frame, its header band on the base colour */
QFrame#notesCard { background: $content; border: 1px solid $stroke_strong; border-radius: ${radius_l}px; }
QFrame#notesCard[typing="true"] { border: 1px solid $stroke_strong; border-bottom: 2px solid $accent; }
/* release 5.113 (the task panel plan): the Notes heading is a section's head over its frame, not a band inside it */
QWidget#notesHead { background: transparent; border: none; }
/* the outline at the notes' left (release 5.113, decision 349): a column with a divider, its rows painted from the tokens */
QFrame#outlineSlot { background: transparent; border: none; border-right: 1px solid $stroke; }
QListWidget#notesOutline { background: transparent; border: none; padding: 0; }
/* the task page's parts (release 5.113): no padding or white of their own, so their words start on the page's left edge
   and the status card's tint shows behind its words */
QTextBrowser#fitView { background: transparent; border: none; padding: 0; }
/* the task page's header (release 5.113): the status card with a bar down its left side, and every section's head alike */
QFrame#statusCard { background: $sunken; border: none; border-radius: ${radius_l}px; }
QFrame#statusCard[empty="true"] { background: $sunken; }
QLabel#statusName, QLabel#statusWhen, QLabel#groupSummaryLabel { color: $text2; }
QToolButton#statusLog { border: none; border-radius: ${radius_s}px; background: transparent; padding: 2px 4px 2px 6px; color: $text2; }
QToolButton#statusLog:hover { background: $hover; color: $text2; text-decoration: underline; }
QToolButton#groupHead { border: none; border-radius: ${radius_s}px; background: transparent; padding: 2px 6px 2px 2px; color: $text; }
QToolButton#groupHead:hover { background: $hover; }
QTextEdit#notesPage, QTextEdit#notesPage:focus { border: none; border-radius: 0; background: transparent; padding: 0; }  /* its size: NotesEdit's font */
QLabel#notesSaved { color: $text2; }
/* the Checklist summary (release 5.26): rows bound to the page's checklist lines */
QWidget#summaryBox { background: transparent; }
QWidget#checkRow { border-radius: ${radius_s}px; }
QWidget#checkRow:hover { background: $hover; }
QTextEdit#checkText, QTextEdit#checkText:focus { border: none; border-radius: 0; background: transparent; padding: 0; }
QLabel#checkCount, QLabel#checkHeading { color: $text2; }
QLabel#checkHeading { padding-top: 6px; padding-left: 4px; }
/* the sticky title line (release 5.86): the task's title once the header has scrolled off; opaque, over the page */
QWidget#stickyTitle { background: $content; border-bottom: 1px solid $stroke_strong; }
QToolButton#stickyButton { border: none; border-radius: ${radius_s}px; background: transparent; padding: 1px 8px; color: $text2; }
QToolButton#stickyButton:hover { background: $hover; text-decoration: underline; }
QToolButton#checkFold, QToolButton#rowAction { border: none; background: transparent; padding: 0 2px; }
QFrame#popover, QFrame#capCard { background: $content; border: 1px solid $stroke_strong; border-radius: ${radius_xl}px; }
QPushButton#filterChip { background: $info_bg; border: none; border-radius: ${radius_s}px; padding: 2px 10px; min-height: 18px; max-height: 22px; }
QPushButton#filterChip:hover { background: $pressed; }
QFrame#timelineFoot { background: $content; border-top: 1px solid $stroke; }
QSplitter#timelineSplit::handle:vertical { height: 7px; background: $base; border-top: 1px solid $stroke_strong; border-bottom: 1px solid $stroke_strong; }
QSplitter#timelineSplit::handle:vertical:hover { background: $hover; }
QToolButton#linkMark { border: none; background: transparent; padding: 0 3px; color: $text2; font-size: ${caption}pt; }
QToolButton#linkMark:hover { background: $hover; color: $accent; }
QLabel#linkLeaving { color: $caution; font-size: ${caption}pt; }
QLabel#progressProblem { color: $caution; font-size: ${caption}pt; }
QLineEdit[worked="true"] { color: $text2; font-style: italic; }
QWidget#checkRow QCheckBox { spacing: 0; padding-top: 3px; }
QWidget#checkRow QCheckBox::indicator { width: 13px; height: 13px; }
QLineEdit#addItem { margin-top: 4px; }
/* the capture window */
QWidget#capture QScrollArea, QWidget#capture QScrollArea > QWidget > QWidget { background: $content; }
QWidget#footer { background: $base; border-top: 1px solid $stroke; }
QFrame#editor { background: $content; border: 1px solid $stroke_strong; border-radius: ${radius}px; }
QFrame#editor QTextEdit, QFrame#editor QPlainTextEdit { border: none; border-radius: 0; background: transparent; padding: 6px 8px; }
/* the pinned capture window (mods log round 3, M0053): a drop zone that lights up while something is dragged over it */
QWidget#pinWindow { background: $content; border: 1px solid $stroke_strong; }
QLabel#pinTitle { font-weight: 600; }
QWidget#pinWindow QTextEdit { padding: 4px 6px; }
QPushButton#pinTask { text-align: left; padding: 2px 6px; font-weight: 600; background: transparent; border: 1px solid transparent; }
QPushButton#pinTask:hover { background: $hover; border-color: $stroke; }
QCheckBox#typeToggle[compact="true"] { padding: 2px 8px; font-size: ${caption}pt; border: 1px solid transparent; }
QCheckBox#typeToggle[compact="true"]:checked { border: 1px solid $stroke; }
QFrame#dropZone QLineEdit { border: none; background: transparent; padding: 0 2px; min-height: 0; }
QWidget#pinWindow QLineEdit { min-height: 0; padding: 1px 6px; }
QFrame#dropZone { background: $sunken; border: 1px dashed $stroke_strong; border-radius: ${radius_l}px; }
QFrame#dropZone[over="true"] { background: $selected; border: 1px solid $accent; }
QWidget#formatBar { border-bottom: 1px solid $stroke; }
QWidget#formatBar QToolButton { color: $text2; padding: 3px 6px; min-width: 16px; }
QWidget#formatBar QToolButton:hover { color: $text; background: $hover; border-color: $stroke; }
QWidget#formatBar QToolButton:checked { color: $accent; background: $selected; }
QFrame#found { background: $caution_bg; border: none; border-radius: ${radius}px; }
QFrame#found[empty="true"] { background: $base; }
QFrame#items, QFrame#agendaPanel { background: $sunken; border: none; border-radius: ${radius_l}px; }
QFrame#items[empty="true"] { background: transparent; }
QFrame#itemCard { background: $content; border: 1px solid $stroke; border-left: 3px solid $stroke_strong; border-radius: 0; }
QFrame#itemCard QLabel { background: transparent; border: none; }
QFrame#itemCard QLabel#itemValue { background: $sunken; border: 1px solid $stroke; border-radius: ${radius}px; padding: 5px 8px; }
QFrame#itemCard QLabel#itemValue:disabled { color: $disabled; }
QListWidget#refPopup, QListWidget#headingList, QListWidget#suggestions { background: $content; border: 1px solid $stroke_strong; border-radius: ${radius}px; padding: 2px; }
QListWidget#refPopup::item:selected, QListWidget#headingList::item:selected, QListWidget#suggestions::item:selected { background: $hover; color: $text; }
QFrame#taskPicker { background: $content; border: 1px solid $stroke_strong; border-radius: ${radius_xl}px; }
QListWidget#taskPickerList { background: $content; border: none; padding: 0; }
QListWidget#taskPickerList::item:selected { background: $hover; color: $text; }
QFrame#divider { color: $stroke; }
QPushButton#today { background: transparent; border: 1px solid transparent; }
QPushButton#today:hover { background: $hover; }
QPushButton#today:checked { background: $selected; color: $accent; border-color: $selected; }
QFrame#fileRow { border: 1px solid $stroke; border-radius: ${radius_l}px; background: $content; }
QToolButton#chip { border: 1px solid transparent; border-radius: ${radius_s}px; background: $sunken; padding: 1px 8px; font-size: ${caption}pt; }
QToolButton#chip[filled="true"] { background: $caution_bg; border-color: $caution_line; color: $text; }
QFrame#personChip { border: 1px solid transparent; border-radius: ${radius_s}px; background: $sunken; }
QFrame#personChip:focus { border: 1px solid $accent; }
QFrame#personChip QLabel { font-size: ${caption}pt; background: transparent; }
QFrame#personChip QLabel#personShare { color: $accent; font-weight: 600; }
QFrame#personChip QToolButton { border: none; background: transparent; padding: 0 2px; font-size: ${caption}pt; }
QFrame#involvementBox { border: 1px solid $stroke_strong; background: $content; }
QFrame#tieBox { border: 1px solid $stroke; border-radius: ${radius}px; background: $content; }
QFrame#timingHead { border-bottom: 1px solid $stroke_strong; }
QFrame#timingRow { border-bottom: 1px solid $stroke; }
QFrame#timingRow[anchor="true"] { background: $selected; }
QLabel#anchorPill { color: $accent; background: $info_bg; border: 1px solid $info_line; border-radius: ${radius_s}px; padding: 0 6px; font-size: ${caption}pt; }
QWidget#chips { border: 1px solid $stroke_strong; border-radius: ${radius}px; background: $content; }
/* with the chip field's margins, 34 px high as a field is, and its text where a text box's starts */
QWidget#chips QLineEdit, QWidget#chips QLineEdit:focus { background: transparent; border: none; padding: 4px 7px; min-height: 24px; max-height: 24px; }

/* the browse tool */
QWidget#toolbar { background: $base; border-bottom: 1px solid $stroke; }
QWidget#paneHead { background: $content; border-bottom: 1px solid $stroke; }
QWidget#actions { background: $content; }
QLabel#status { background: $base; border-top: 1px solid $stroke; color: $text; padding: 4px 12px; font-size: ${caption}pt; }
QLabel#status[error="true"] { background: $critical_bg; color: $critical; }
/* the sidebar (stage O10): docrepo/ui/nav_pane.py paints its rows from these same tokens */
QWidget#navPane, QWidget#navBody { background: $base; }
QFrame#navFoot { background: $base; border: none; border-top: 1px solid $stroke; }
/* the Priorities board (release 5.23): a column per bucket, a card per task; the card's left edge is painted in its colour */
QFrame#prCol { background: $sunken; border: 1px solid transparent; border-radius: ${radius_l}px; }
QFrame#prCol[over="true"] { background: $selected; border-color: $info_line; }
QWidget#prCards { background: transparent; }
QFrame#prCard { background: $content; border: 1px solid $stroke; border-radius: ${radius}px; }
QFrame#prCard:hover { border-color: $stroke_strong; }
QFrame#prCard[sel="true"] { background: $selected; border-color: $accent; }
QFrame#prDrop { background: $accent; border: none; border-radius: ${radius_hair}px; }
QLabel#prTitle { font-weight: 600; color: $text; }
/* a parent shown only for the subtasks folded into it (release 5.136): dimmed, as the task tree's parents are */
QFrame#prCard[context="true"] QLabel#prTitle { font-weight: 400; color: $text2; }
/* the subtasks inside a parent's card in Parents, and its opener (release 5.137, decisions 552 and 553) */
QFrame#prRows { border: none; border-top: 1px solid $stroke; background: transparent; }
QFrame#prRow { background: transparent; border: 1px solid transparent; border-radius: ${radius_s}px; }
QFrame#prRow:hover { background: $hover; }
QFrame#prRow[sel="true"] { background: $selected; border-color: $accent; }
QLabel#prRowTitle { color: $text; }
QPushButton#prOpener { border: none; background: transparent; color: $text2; padding: 0; border-radius: ${radius_s}px; }
QPushButton#prOpener:hover { background: $hover; color: $text; }
QTextBrowser { border: none; background: $content; }
QWidget#settingsCard { background: $content; border: 1px solid $stroke; border-radius: ${radius_l}px; }
QDialog#palette { background: $content; border: 1px solid $stroke_strong; }

/* The lanes' rules (the redesign plan's section 5a): one section a lane, each written only between its own two lines. */
/* ---- lane A (the shell) ---- */
/* release 5.182 (one content surface, the sidebar, the toast): the browse window's grey frame, its one white card
   (docrepo/ui/content_card.py paints it), the top bar with no line, the sidebar on the frame, and the message at the bottom
   (docrepo/ui/toast.py) where the status strip was */
QWidget#browse[frame="true"] { background: $base; }
/* scoped to this window: the quick summary and File search have a bar named toolbar too */
QWidget#browse[frame="true"] QWidget#toolbar { background: transparent; border-bottom: none; }
QWidget#browse[frame="true"] QWidget#toolbar QToolButton#iconButton { min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; border-radius: ${radius}px; }
QLineEdit#topSearch { background: $field; border: 1px solid transparent; border-radius: ${radius}px; padding: 5px 8px; min-height: 20px; max-height: 20px; }
QLineEdit#topSearch:focus { background: $content; border: 2px solid $accent; padding: 4px 7px; }
QPushButton#problemsLine { background: $caution_bg; color: $caution; border: none; border-radius: ${radius}px; padding: 6px 12px; min-height: 20px; text-align: left; }
QPushButton#problemsLine:hover { text-decoration: underline; }
QSplitter#browseSplit::handle { background: transparent; }
QWidget#browse[frame="true"] QWidget#paneHead { background: transparent; border-bottom: none; }
QWidget#browse[frame="true"] QTreeView[tiled="true"] { background: $content; }
QWidget#navPane, QWidget#navBody { background: transparent; }
QFrame#navFoot { background: transparent; border: none; }
QFrame#toast { background: $text; border: none; border-radius: ${radius_l}px; }
QFrame#toast[error="true"] { background: $critical_bg; border: 1px solid $critical; }
QLabel#toastText { background: transparent; color: $content; }
QLabel#toastText[error="true"] { color: $critical; }
QPushButton#toastUndo { background: $text2; color: $content; border: none; border-radius: ${radius_s}px; padding: 0 10px; min-height: 28px; max-height: 28px; font-weight: 600; }
QPushButton#toastUndo:hover { background: $text3; }
QToolButton#toastClose { background: transparent; border: none; border-radius: ${radius_s}px; padding: 4px; }
QToolButton#toastClose:hover { background: $content; }
/* ---- end lane A ---- */

/* ---- lane B (the lists) ---- */

/* ---- end lane B ---- */

/* ---- lane C (the pages) ---- */

/* ---- end lane C ---- */

/* ---- lane D (the floating windows) ---- */

/* ---- end lane D ---- */

/* ---- lane E (planning views and forms) ---- */

/* ---- end lane E ---- */
""")


#: The sizes the style sheets name, beside the colours.
_SIZES = {"page_title": PAGE_TITLE, "view_title": VIEW_TITLE, "section": SECTION, "body": BODY, "notes": NOTES, "caption": CAPTION,
          "label": LABEL, "subtitle": SUBTITLE, "topic": TOPIC,
          "radius_s": RADIUS_S, "radius": RADIUS, "radius_l": RADIUS_L, "radius_xl": RADIUS_XL, "radius_box": RADIUS_BOX,
          "radius_hair": RADIUS_HAIR, "radius_edge": RADIUS_EDGE, "radius_bar": RADIUS_BAR}


def qss() -> str:
    """The look's style sheet, from the active theme's tokens."""
    from docrepo.ui.icons import file_url  # the icons module reads the tokens too

    return _QSS.substitute(active(), **_SIZES, arrow=file_url("arrow-down-grey"), tick=file_url("tick-white"),
                           marker=file_url("filled-marker"), branch_closed=file_url("chevron-right"), branch_open=file_url("chevron-down"),
                           chev_left=file_url("chevron-left"), chev_right=file_url("chevron-right"))


#: The pages' and the list cells' HTML styles (Qt's rich text), from the same tokens. Numbers use Segoe UI so they line up.
_CSS = Template("""
body { color: $text; }
a { color: $accent; text-decoration: none; }
h2 { font-family: 'Segoe UI'; font-size: ${page_title}pt; font-weight: 600; margin-top: 2px; margin-bottom: 4px; }
.ptitle { font-family: 'Segoe UI'; font-size: ${page_title}pt; font-weight: 600; }
.crumbs { color: $text2; font-size: ${caption}pt; margin: 0; }
.sub { color: $text3; font-size: ${caption}pt; font-weight: 400; }
.faint { color: $text2; }
.k { color: $text3; padding-right: 12px; }
.fk { color: $text3; font-size: ${caption}pt; }
.note { color: $text3; font-size: ${caption}pt; }
.box { background-color: $base; }
.info { background-color: $info_bg; }
.caution { color: $caution; }
.critical { color: $critical; }
.warn { background-color: $caution_bg; }
.tab { color: $text2; }
.tabon { color: $text; font-weight: 600; border-bottom: 2px solid $accent; }
.day { color: $text3; font-size: ${caption}pt; font-family: 'Segoe UI'; }
.month { color: $text3; font-size: ${label}pt; font-weight: 600; }
.lead { color: $text3; font-size: ${caption}pt; }
.facts { color: $text3; font-size: ${caption}pt; }
.text { white-space: pre-wrap; }
.chs { color: $text; font-weight: 600; margin-top: 12px; }
.ch { background-color: $base; }
.num { font-family: 'Segoe UI'; }
.st-ns { color: $text2; background-color: $hover; }
.st-ip { color: $accent; background-color: $info_bg; }
.st-pk { color: $parked; background-color: $parked_bg; }
.st-cl { color: $success; background-color: $success_bg; }
.urgent { color: $critical; background-color: $critical_bg; font-weight: 600; }
.pri-critical { color: $on_accent; background-color: $critical; font-weight: 600; }
.pri-high { color: $caution; background-color: $caution_bg; font-weight: 600; }
.pri-medium { color: $accent; background-color: $info_bg; }
.pri-parking { color: $text2; background-color: $hover; }
.routine { color: $text; background-color: $hover; }
.multi { color: $accent; background-color: $info_bg; }
.lbl { color: $text; background-color: $hover; }
.tg { font-family: 'Cascadia Mono', 'Consolas'; color: $text; background-color: $base; }
.tgn { font-family: 'Cascadia Mono', 'Consolas'; color: $caution; background-color: $caution_bg; }
.tgw { color: $caution; font-size: ${caption}pt; }
.anchor { color: $accent; background-color: $info_bg; }
.inh { color: $text2; font-style: italic; }
.sec { font-size: ${section}pt; font-weight: 600; margin-top: 18px; margin-bottom: 4px; }
.secx { font-weight: 400; }
.factline { margin-top: 6px; margin-bottom: 0px; }
.ttl { font-weight: 600; }
.foldword { color: $text; }
.dt { color: $text3; font-size: ${caption}pt; padding-right: 14px; }
.rel { color: $text3; font-size: ${caption}pt; font-weight: 400; }
.over { color: $critical; }
.tile { background-color: $base; border-bottom: 2px solid $content; }
.stat { background-color: $base; }
.sk { color: $text3; font-size: ${caption}pt; }
.desc { color: $text2; margin-top: 4px; }
.lbli { color: $text2; }
.rule { background-color: $stroke; }
.tl { color: $text; }
.tq { color: $text2; }
.new { color: $caution; background-color: $caution_bg; }
.u1 { }
.u2 { background-color: $caution_bg; }
.u3 { color: $critical; background-color: $critical_bg; font-weight: 600; }
.away { color: $text2; background-color: $hover; }
.mark { background-color: $caution_bg; font-weight: 600; }
.line { margin: 0; }
.hitline { margin: 0; background-color: $caution_bg; }
.gap { margin: 0; color: $text2; }
.stext { margin-top: 4px; margin-bottom: 0; }
.gk { color: $text3; padding-right: 10px; }
.relb { color: $text2; font-weight: 400; }
.grid { margin-top: 12px; }
.anday { color: $text3; font-size: ${label}pt; font-weight: 600; margin-top: 14px; margin-bottom: 2px; }
.src { color: $text3; font-size: ${caption}pt; font-weight: 400; margin-top: 8px; margin-bottom: 2px; }
.nl { margin: 0; }
.also { color: $text3; font-size: ${caption}pt; }
.occ { font-weight: 600; }
.topic { font-size: ${topic}pt; font-weight: 600; }
.sub2 { font-weight: 600; }
.loose { color: $text2; font-size: ${topic}pt; font-weight: 600; }
.tag { color: $text3; font-size: ${caption}pt; }

/* The lanes' rules (the redesign plan's section 5a): one section a lane, each written only between its own two lines. In this
   CSS a rule a lane replaces is deleted where it stands, as Qt's rich text can't be trusted to let the later one win. */
/* ---- lane A (the shell) ---- */

/* ---- end lane A ---- */

/* ---- lane B (the lists) ---- */

/* ---- end lane B ---- */

/* ---- lane C (the pages) ---- */

/* ---- end lane C ---- */

/* ---- lane D (the floating windows) ---- */

/* ---- end lane D ---- */

/* ---- lane E (planning views and forms) ---- */

/* ---- end lane E ---- */
""")
_CSS_CACHE: dict[str, str] = {}


def css() -> str:
    """The pages' HTML styles in the active theme (made once a theme)."""
    name = theme()
    if name not in _CSS_CACHE:
        _CSS_CACHE[name] = _CSS.substitute(active(), **_SIZES)
    return _CSS_CACHE[name]
