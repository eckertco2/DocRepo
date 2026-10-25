"""Which look the windows wear, and the parts of it that come and go: help text and key tips.

The visual overhaul (releases 5.10 to 5.16) keeps release 5.9's colours selectable as the Classic look (decision 15).
Help text, the ⓘ buttons and key badges show only with Show hints on, or in the Classic look (decision 7). Keys live in
tooltips, menus, F1 and the command palette; holding Alt shows each control's letter key, and holding Ctrl for half a
second shows the Ctrl shortcuts (decision 5).
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget


@dataclass
class Look:
    classic: bool = False  # release 5.9's colours, fonts and hints
    hints: bool = False    # Show hints: help text, ⓘ buttons and key badges
    app_sheet: bool = False  # the new look's style sheet is set on the application, so windows needn't set it again

    @property
    def show_help(self) -> bool:
        return self.classic or self.hints


LOOK = Look()
_gated: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


def configure(look: str, hints: bool) -> None:
    """Set the look from Settings, before any window is made."""
    LOOK.classic = look == "classic"
    LOOK.hints = hints


def set_hints(on: bool) -> None:
    """Show hints, at once, in every window."""
    LOOK.hints = on
    for w in list(_gated):
        w.apply_gate()


class _Gate:
    """A widget that shows only when help is shown. Its code still shows and hides it as before; that's remembered, and
    applied whenever help is on."""

    def _init_gate(self) -> None:
        self._wanted = True
        _gated.add(self)  # type: ignore[arg-type]

    def setVisible(self, visible: bool) -> None:  # noqa: N802 - Qt's name
        self._wanted = visible
        super().setVisible(visible and LOOK.show_help)  # type: ignore[misc]

    def apply_gate(self) -> None:
        super().setVisible(self._wanted and LOOK.show_help)  # type: ignore[misc]


class Help(_Gate, QLabel):
    """Help text: what a field is for, what to type, which keys do what. Shown only with Show hints on (decision 7)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("help")
        self.setWordWrap(True)
        self._init_gate()
        if not LOOK.show_help:
            QLabel.setVisible(self, False)


class KeyBadge(_Gate, QLabel):
    """A key printed beside a control, such as "Alt+N". Shown only with Show hints on, or in the Classic look."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("hotkey")
        self._init_gate()
        if not LOOK.show_help:
            QLabel.setVisible(self, False)


def with_key(label: str, key: str) -> str:
    """A button's label: with its key in the Classic look, as release 5.9 had it, else alone (the key is in its tooltip)."""
    return f"{label}   {key}" if LOOK.classic else label


def tip(widget: QWidget, text: str, key: str = "") -> None:
    """A control's tooltip: what it does, then its key, such as "Save (Ctrl+Enter)"."""
    widget.setToolTip(f"{text} ({key})" if key else text)


_KEYS = (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.WindowDeactivate, QEvent.Type.ApplicationDeactivate)


class _TipsHub(QObject):
    """One application-wide watcher for the key tips, whatever the number of windows: it hands key events to the tips of
    the window that has the keyboard, and lets every other event straight through."""

    _instance: "_TipsHub | None" = None

    def __init__(self) -> None:
        super().__init__()
        self.tips: "weakref.WeakSet[KeyTips]" = weakref.WeakSet()

    @classmethod
    def join(cls, tips: "KeyTips") -> None:
        app = QApplication.instance()
        if app is None:
            return
        if cls._instance is None:
            cls._instance = _TipsHub()
            app.installEventFilter(cls._instance)
        cls._instance.tips.add(tips)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if event.type() not in _KEYS:
            return False
        active = QApplication.activeWindow()
        for tips in list(self.tips):
            if tips.window is active or tips._shown:
                tips.key_event(event)
        return False


class KeyTips(QObject):
    """The key tips over one window (decision 5): holding Alt shows each registered control's letter key, Windows-style,
    and holding Ctrl for half a second shows the Ctrl shortcuts. Only visible controls get a tip."""

    CTRL_DELAY_MS = 500

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.alt: list[tuple[QWidget, str, str]] = []
        self.ctrl: list[tuple[QWidget, str, str]] = []
        self._labels: list[QLabel] = []
        self._shown = ""
        self._ctrl_timer = QTimer(self)
        self._ctrl_timer.setSingleShot(True)
        self._ctrl_timer.setInterval(self.CTRL_DELAY_MS)
        self._ctrl_timer.timeout.connect(lambda: self.show_tips("ctrl"))
        _TipsHub.join(self)

    def add(self, widget: QWidget, key: str, ctrl: bool = False, group: str = "") -> None:
        (self.ctrl if ctrl else self.alt).append((widget, key, group))

    def clear(self, group: str) -> None:
        """Forget a group's tips, such as the detail pane's commands when it's drawn again."""
        self.alt = [x for x in self.alt if x[2] != group]
        self.ctrl = [x for x in self.ctrl if x[2] != group]

    def show_tips(self, kind: str) -> None:
        if LOOK.classic or not self.window.isVisible() or not self.window.isActiveWindow():
            return
        self.hide_tips()
        self._shown = kind
        for widget, key, _group in self.alt if kind == "alt" else self.ctrl:
            if not widget.isVisible() or not widget.isVisibleTo(self.window):
                continue
            label = QLabel(key, self.window)
            label.setObjectName("keyTip")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.adjustSize()
            corner = widget.mapTo(self.window, QPoint(widget.width(), 0))
            label.move(max(0, corner.x() - label.width() + 4), max(0, corner.y() - label.height() // 2))
            label.show()
            label.raise_()
            self._labels.append(label)

    def hide_tips(self) -> None:
        for label in self._labels:
            label.deleteLater()
        self._labels.clear()
        self._shown = ""

    def key_event(self, event) -> None:
        """A key event while this window has the keyboard (from ``_TipsHub``)."""
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Alt and not event.isAutoRepeat():
                self.show_tips("alt")
            elif key == Qt.Key.Key_Control and not event.isAutoRepeat():
                self._ctrl_timer.start()
            elif key not in (Qt.Key.Key_Alt, Qt.Key.Key_Control):
                self._ctrl_timer.stop()
                if self._shown == "ctrl":
                    self.hide_tips()
        elif kind == QEvent.Type.KeyRelease:
            if event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_Control) and not event.isAutoRepeat():
                self._ctrl_timer.stop()
                if self._shown:
                    self.hide_tips()
        elif self._shown:  # the window or the app lost the keyboard
            self._ctrl_timer.stop()
            self.hide_tips()
