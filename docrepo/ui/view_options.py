"""A list view's header (release 5.184, the redesign's decision 855, Filter and Display): one 48 px row with the view's
title, its count, its commands, Filter, Display and the fold buttons, and under it, each only when it has something, the
view's note, the chips of the filters that are on, a tool row and the Find box.

Each control a view adds says where it goes (``PLACES``):

- ``filter``: what narrows or widens the rows (a tick, a ``CheckMenuButton``, a choice), in the Filter panel; a chip under
  the row while it's off its default;
- ``display``: how the rows are arranged or drawn (Sort, Group by, Select), in the Display panel;
- ``command``: a button that acts, on the row as a quiet button, folded under More from the right when the row is narrow;
- ``fold``: Collapse a level and Expand a level, on the row as the icon buttons they are;
- ``tool``: the view's own input, or what steps through something, in the tool row under the header.

The panels are popovers that hold the controls as the widgets they are, so their state, their settings keys and their
keys stay as they were, and ``findChildren`` on the header still finds every one. The views make their controls anew on
every draw, so a panel left open is refilled in place, with the keyboard back on the control it was on.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from docrepo.ui.filter_chips import FilterChips
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.look import Help
from docrepo.ui.widgets import CheckMenuButton, ElidedLabel, FlowLayout

PLACES = ("filter", "display", "command", "fold", "tool")
#: The header row's height, and its margins at the left and the right.
ROW_HEIGHT, ROW_LEFT, ROW_RIGHT = 48, 18, 10
#: The row's buttons (Filter, Display and the commands), and the room between the row's parts.
BUTTON_HEIGHT, GAP = 28, 8
#: A panel's padding, the room between its rows, and its least width.
PANEL_PAD, PANEL_GAP, PANEL_MIN = 12, 8, 240
#: The room kept for the count before a command folds under More: none, so a command keeps its place on the row while the
#: count can be cut to make room for it (no command moves into a menu while there's room for it).
COUNT_KEEP = 0
#: Qt's largest widget size (QWIDGETSIZE_MAX, which PySide6 doesn't export): a width with no cap.
WIDGET_MAX = (1 << 24) - 1
#: The least of the title the row keeps when it's at its narrowest.
TITLE_LEAST = 40
#: The least room a cut count is shown in: with less, it goes, rather than show a stub such as "2…".
COUNT_MIN = 48
#: The header's least width, and the most its row asks for: the list pane keeps room for a title, Filter and More, and asks
#: for its row's whole width up to this, as the bar of controls it replaces held the pane open.
HEAD_MIN, HEAD_NATURAL_MAX = 160, 560


def shown(widget: QWidget | None) -> bool:
    """Whether a control a view added shows: unless it was hidden on purpose. A widget added a moment ago reads as hidden
    until Qt shows it, so ``isHidden`` alone would hide a row made only of new widgets (release 5.151)."""
    if widget is None:
        return False
    return not (widget.isHidden() and widget.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide))


def _empty(layout: QLayout) -> None:
    """Take every widget out of a layout at once, so none is left showing until Qt deletes it."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item else None
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


def _cap(label: QWidget, width: int) -> None:
    """A label's widest, set only when it changes, so the row isn't laid out again for nothing."""
    if label.maximumWidth() != width:
        label.setMaximumWidth(width)


def _key(widget: QWidget) -> str:
    """What finds a control again after a refill: its accessible name, its words or its noun."""
    return widget.accessibleName() or getattr(widget, "noun", "") or (widget.text() if hasattr(widget, "text") else "")


class OptionsPanel(QFrame):
    """A popover of controls, one a row (objectName "popover", a ``Qt.Popup``). It stays open while its controls are used."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("popover")
        self.setProperty("options", True)  # the style sheet's handle on these panels alone (release 5.184)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(PANEL_PAD, PANEL_PAD, PANEL_PAD, PANEL_PAD)
        self.lay.setSpacing(PANEL_GAP)
        self.setMinimumWidth(PANEL_MIN)
        #: The controls in it, in order, without their labels.
        self.controls: list[QWidget] = []
        #: The button it opens under.
        self.button: QWidget | None = None

    def clear(self) -> None:
        self.controls = []
        _empty(self.lay)

    def add(self, widget: QWidget, label: str = "") -> None:
        """A control on a row of its own, at full width; with ``label``, a field label before it on the same row."""
        if isinstance(widget, (QCheckBox, QComboBox, CheckMenuButton)):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
        if label:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(GAP)
            h.addWidget(QLabel(label, objectName="fieldLabel"))
            h.addWidget(widget, 1)
            self.lay.addWidget(row)
        else:
            self.lay.addWidget(widget)
        self.controls.append(widget)

    def is_empty(self) -> bool:
        return not any(shown(w) for w in self.controls)

    def _show_controls(self) -> None:
        """The controls just put in, shown now: Qt shows a widget a layout takes only at its next turn, and one not shown yet
        can't take the keyboard. A control hidden on purpose stays hidden."""
        for w in self.controls:
            if shown(w) and w.isHidden():
                (w.parentWidget() if w.parentWidget() is not self else w).show()
                w.show()

    def focus_first(self) -> None:
        self._show_controls()
        first = next((w for w in self.controls if shown(w) and w.isEnabled()), None)
        if first is not None:
            first.setFocus(Qt.FocusReason.TabFocusReason)

    def open_under(self, button: QWidget) -> None:
        """Open with its right edge on the button's, under it, kept on the button's screen, the keyboard on its first control."""
        self.button = button
        self.show()
        self._place()
        self.raise_()
        self.focus_first()

    def _place(self) -> None:
        if self.button is None:
            return
        self.adjustSize()
        b = self.button
        at = b.mapToGlobal(QPoint(b.width() - self.width(), b.height() + 4))
        screen = (b.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(screen.left(), min(at.x(), screen.right() - self.width()))
        y = at.y() if at.y() + self.height() <= screen.bottom() else b.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
        self.move(x, max(screen.top(), y))

    def refit(self, focus: str = "") -> None:
        """After a refill while open: its size, its place, and the keyboard back on the control called ``focus``."""
        if not self.isVisible():
            return
        self._show_controls()
        self._place()
        target = next((w for w in self.controls if focus and _key(w) == focus), None)
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        elif self.focusWidget() is None or not self.isAncestorOf(self.focusWidget()):
            self.focus_first()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.key() == Qt.Key.Key_Escape:  # back to the button it opened from
            self.hide()
            if self.button is not None:
                self.button.setFocus(Qt.FocusReason.PopupFocusReason)
            return
        super().keyPressEvent(event)


class _Row(QWidget):
    """The header's row. Its least width is its fixed parts' (``least``: room for the title, Filter, Display, the folds and
    More), not its commands', which fold under More instead (``ViewHeader._fit``), so the commands never hold the list pane
    wider than it's dragged."""

    def __init__(self, least: Callable[[], int]) -> None:
        super().__init__()
        self.least = least

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(self.least(), super().minimumSizeHint().height())


class ViewHeader(QWidget):
    """The list pane's head (objectName "paneHead"): one 48 px row, then what a view puts under it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("paneHead")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # ---- the row ----
        self.row = _Row(self._row_least)
        self.row.setFixedHeight(ROW_HEIGHT)
        h = QHBoxLayout(self.row)
        h.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        h.setContentsMargins(ROW_LEFT, 0, ROW_RIGHT, 0)
        h.setSpacing(GAP)
        self.title = ElidedLabel(objectName="paneTitle")
        self.count = ElidedLabel(objectName="paneCount")
        for label in (self.title, self.count):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            h.addWidget(label)
        h.addStretch(1)
        self.commands_box = QWidget()
        self.commands_layout = QHBoxLayout(self.commands_box)
        self.commands_layout.setContentsMargins(0, 0, 0, 0)
        self.commands_layout.setSpacing(GAP)
        h.addWidget(self.commands_box)
        self.filter_button = self._row_button("Filter", "filter", "Filter: what the list shows")
        self.display_button = self._row_button("Display", "display", "Display: how the list is sorted, grouped and picked from")
        h.addWidget(self.filter_button)
        h.addWidget(self.display_button)
        self.folds_box = QWidget()
        self.folds_layout = QHBoxLayout(self.folds_box)
        self.folds_layout.setContentsMargins(0, 0, 0, 0)
        self.folds_layout.setSpacing(2)
        h.addWidget(self.folds_box)
        self.more_button = QPushButton(objectName="iconOnly")
        self.more_button.setIcon(icon("more"))
        self.more_button.setIconSize(icon_size(16))
        self.more_button.setAccessibleName("More commands")
        self.more_button.setToolTip("More commands: those the row has no room for")
        self.more_menu = QMenu(self.more_button)
        self.more_menu.aboutToShow.connect(self._fill_more)
        self.more_button.setMenu(self.more_menu)
        self.more_button.hide()
        h.addWidget(self.more_button)
        outer.addWidget(self.row)
        # ---- under it ----
        self.note = Help()  # what the view is: with Show hints (decision 7)
        self.note.setObjectName("paneNote")
        self.note.setContentsMargins(ROW_LEFT, 0, ROW_RIGHT, 6)
        outer.addWidget(self.note)
        self.chips = FilterChips(lambda: None)
        self.chips.row.setContentsMargins(ROW_LEFT, 0, ROW_RIGHT, 6)
        outer.addWidget(self.chips)
        self.tools = QWidget()
        self.tools_layout = FlowLayout(self.tools, spacing=GAP)
        self.tools_layout.setContentsMargins(ROW_LEFT, 0, ROW_RIGHT, 6)
        self.tools.hide()
        outer.addWidget(self.tools)
        self.under = QVBoxLayout()
        self.under.setContentsMargins(ROW_LEFT, 0, ROW_RIGHT, 6)
        outer.addLayout(self.under)
        # ---- the panels ----
        self.filter_panel = OptionsPanel(self)
        self.display_panel = OptionsPanel(self)
        self.filter_button.clicked.connect(lambda: self._toggle(self.filter_panel, self.filter_button))
        self.display_button.clicked.connect(lambda: self._toggle(self.display_panel, self.display_button))
        self._commands: list[QPushButton] = []
        self._chips: list[tuple[str, Callable[[], None]]] = []
        self._view: str | None = None
        self._title, self._count = "", ""
        #: While a view is drawn: the panel that was open, and the control in it that had the keyboard.
        self._open: OptionsPanel | None = None
        self._focus = ""
        self._fitting = False
        self._fitted = -1  # the width the row was last fitted to
        #: Filter's and Display's words, which a narrow row leaves off (``_compact``).
        self._words = {self.filter_button: "Filter", self.display_button: "Display"}
        self._compacted = False
        self._natural = -1  # the row's natural width when last asked

    def _row_button(self, words: str, icon_name: str, tip: str) -> QPushButton:
        b = QPushButton(words, objectName="subtle")
        b.setIcon(icon(icon_name))
        b.setIconSize(icon_size(16))
        b.setFixedHeight(BUTTON_HEIGHT)
        b.setToolTip(tip)
        b.setAccessibleName(words)
        b.hide()
        return b

    def _toggle(self, panel: OptionsPanel, button: QPushButton) -> None:
        if panel.isVisible():
            panel.hide()
            return
        panel.open_under(button)

    # ---- a render ----
    def set_head(self, title: str, note: str = "", total: str = "") -> None:
        """The view's title, its count (such as "18 open") and what it is, with Show hints."""
        self._title, self._count = title, total
        self.title.setText(title)
        self.count.setText(total)
        self.count.setVisible(bool(total))
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self._fit()

    def clear(self, view: str) -> None:
        """The start of a render: every control out. A panel open on the same view stays open, to be refilled; changing the
        view closes it."""
        self._open = next((p for p in (self.filter_panel, self.display_panel) if p.isVisible()), None)
        had = self._open.focusWidget() if self._open is not None else None  # the panel's own: it may not be the active window
        self._focus = _key(had) if had is not None and self._open.isAncestorOf(had) else ""
        if view != self._view:
            for p in (self.filter_panel, self.display_panel):
                p.hide()
            self._open = None
        self._view = view
        self.filter_panel.clear()
        self.display_panel.clear()
        self._commands = []
        _empty(self.commands_layout)
        _empty(self.folds_layout)
        _empty(self.tools_layout)
        self.tools_layout.invalidate()  # its least width was the last view's: the next view's tool row asks again
        self._chips = []

    def add(self, widget: QWidget, where: str, label: str = "") -> QWidget:
        """Put a view's control where it goes (``PLACES``); with ``label``, a field label before it."""
        if where not in PLACES:
            raise ValueError(f"no place called {where!r}")
        if where == "filter":
            self.filter_panel.add(widget, label)
        elif where == "display":
            self.display_panel.add(widget, label)
        elif where == "command":
            if isinstance(widget, QPushButton) and not widget.objectName():
                widget.setObjectName("subtle")
                widget.setFixedHeight(BUTTON_HEIGHT)
            self.commands_layout.addWidget(widget)
            self._commands.append(widget)
        elif where == "fold":
            self.folds_layout.addWidget(widget)
        else:
            if label:
                self.tools_layout.addWidget(QLabel(label, objectName="fieldLabel"))
            self.tools_layout.addWidget(widget)
        return widget

    def add_chip(self, words: str, clear: Callable[[], None]) -> None:
        """A filter that's off its default, as a chip under the row; its cross puts the default back."""
        self._chips.append((words, clear))

    def done(self) -> None:
        """The end of a render: the buttons, the chips and the tool row for what the view put in, the row fitted, and an open
        panel refilled."""
        self.chips.show_chips(self._chips)
        n = len(self._chips)
        self._words[self.filter_button] = f"Filter · {n}" if n else "Filter"
        if not self._compacted:
            self.filter_button.setText(self._words[self.filter_button])
        self._tips()
        self.filter_button.setVisible(not self.filter_panel.is_empty())
        self.display_button.setVisible(not self.display_panel.is_empty())
        self.tools.setVisible(any(shown(self.tools_layout.itemAt(i).widget()) for i in range(self.tools_layout.count())))
        self.folds_box.setVisible(self.folds_layout.count() > 0)
        natural = self._row_natural()
        if self.isVisible():  # the pane's layout asks again: the row's width, and the tool row's least, are this view's now
            self._natural = natural
            self.updateGeometry()
        self._fit()
        if self._open is not None:
            if self._open.is_empty():
                self._open.hide()
            else:
                self._open.refit(self._focus)
        self._open, self._focus = None, ""

    def commands(self) -> list[QPushButton]:
        """The commands on the row, in order, those folded under More too."""
        return list(self._commands)

    # ---- fitting the row ----
    def _fit(self) -> None:
        """Every command shows while the row has room; the last ones go under More, from the right, while it hasn't. After
        the commands, the count is cut with "…", then the title."""
        if self._fitting or not self.isVisible():  # a hidden header (the workspace in its place) is fitted when it shows
            return
        self._fitting = True
        try:
            self._fit_row()
        finally:
            self._fitting = False

    def _fit_row(self) -> None:
        room = self.width() - ROW_LEFT - ROW_RIGHT
        self._fitted = self.width()
        fm_title, fm_count = self.title.fontMetrics(), self.count.fontMetrics()
        title_w = fm_title.horizontalAdvance(self._title) + 2
        count_w = fm_count.horizontalAdvance(self._count) + 2 if self._count else 0
        if room <= 0:  # not laid out yet: each at its own width until it is
            _cap(self.title, title_w)
            _cap(self.count, count_w)
            return
        fixed = [w for w in (self.filter_button, self.display_button, self.folds_box) if shown(w)]
        self._compact(False)

        def width(widgets: list[QWidget]) -> int:
            return sum(w.sizeHint().width() for w in widgets) + GAP * len(widgets)

        commands = [b for b in self._commands]
        for b in commands:
            b.setVisible(True)
        hidden: list[QPushButton] = []
        more = self.more_button.sizeHint().width() + GAP

        def need() -> int:
            on = [b for b in commands if b not in hidden]
            return title_w + (min(count_w, COUNT_KEEP) + GAP if count_w else 0) + width(fixed) + width(on) + (more if hidden else 0)

        while need() > room and len(hidden) < len(commands):
            hidden.insert(0, commands[len(commands) - 1 - len(hidden)])
        if need() - title_w + min(title_w, TITLE_LEAST) > room:  # still too narrow: Filter and Display as their icons alone
            self._compact(True)
        for b in hidden:
            b.setVisible(False)
        self.more_button.setVisible(bool(hidden))
        self.commands_box.setVisible(len(hidden) < len(commands))
        rest = room - width(fixed) - width([b for b in commands if b not in hidden]) - (more if hidden else 0)
        title_shown = max(0, min(title_w, rest))
        count_shown = max(0, min(count_w, rest - title_shown - GAP)) if count_w else 0
        if count_shown < min(count_w, COUNT_MIN):
            count_shown = 0
        _cap(self.title, title_shown)  # a cap, not a size: the labels ask for no width (ElidedLabel)
        _cap(self.count, count_shown)

    def _compact(self, on: bool) -> None:
        """Filter and Display with their words, or, in a row too narrow for them once every command has folded, as their
        icons alone, their words (and Filter's count) in their tooltips: so the list pane can be dragged as narrow as it
        could before release 5.184."""
        if on == self._compacted:  # nothing to change: no relayout asked for
            return
        self._compacted = on
        for b, words in self._words.items():
            b.setText("" if on else words)
            if on:
                b.setFixedWidth(BUTTON_HEIGHT)
            else:
                b.setMinimumWidth(0)
                b.setMaximumWidth(WIDGET_MAX)
        self._tips()

    def _tips(self) -> None:
        """Filter's and Display's tooltips start with their words, which say Filter's count while the words are off."""
        for b, words in self._words.items():
            tip = f"{words}: {b.toolTip().split(': ', 1)[-1]}"
            if b.toolTip() != tip:
                b.setToolTip(tip)

    def folded(self) -> list[QPushButton]:
        """The commands under More now."""
        return [b for b in self._commands if b.isHidden()]

    def _fill_more(self) -> None:
        """More's menu, as it opens: a line for each command the row has no room for, which clicks it."""
        self.more_menu.clear()
        self.more_menu.setToolTipsVisible(True)
        for b in self.folded():
            action = self.more_menu.addAction(b.text())
            action.setToolTip(b.toolTip())
            action.setEnabled(b.isEnabled())
            action.triggered.connect(lambda _=False, b=b: b.click())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        if self.width() != self._fitted:
            self._fit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().showEvent(event)
        self._natural = -1
        self._fit()

    def _row_least(self) -> int:
        """The row's width with every command folded and the count gone: the title's first letters, Filter and Display as
        their icons alone, the folds and More."""
        buttons = sum(BUTTON_HEIGHT + GAP for w in (self.filter_button, self.display_button) if shown(w))
        folds = self.folds_box.sizeHint().width() + GAP if shown(self.folds_box) else 0
        more = self.more_button.sizeHint().width() + GAP if self._commands else 0
        title = min(self.title.fontMetrics().horizontalAdvance(self._title) + 2, TITLE_LEAST)
        return ROW_LEFT + ROW_RIGHT + title + buttons + folds + more

    def _row_natural(self) -> int:
        """The row's width with nothing folded or cut."""
        parts = [w for w in (self.filter_button, self.display_button, self.folds_box) if shown(w)] + list(self._commands)
        words = self.title.fontMetrics().horizontalAdvance(self._title) + (self.count.fontMetrics().horizontalAdvance(self._count) + GAP if self._count else 0)
        return ROW_LEFT + ROW_RIGHT + words + sum(w.sizeHint().width() + GAP for w in parts)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        return QSize(min(HEAD_NATURAL_MAX, max(HEAD_MIN, self._row_natural())), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        """A title, Filter and More, or what the rows under the header can't go narrower than (Today's quick box)."""
        base = super().minimumSizeHint()
        return QSize(max(HEAD_MIN, base.width()), base.height())
