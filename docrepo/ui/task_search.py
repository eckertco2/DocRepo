"""Task search (release 5.42, decision 213): the task picker itself, opened on its own at the centre of the monitor, with the
cursor in its box, so it's the same list as a parent's: Recent, the tree, then matches with their paths as you type.

A menu opened from no window can't take the keyboard, because Windows gives it to the active window of the program. So a
tiny window of DocRepo's own is shown and activated first, and the menu opens from that: it's a host and nothing else.
Enter opens the task's page in the browse tool, and Ctrl+Enter its Task view. Unlike when picking a parent, it also finds
closed tasks, marked as closed, since you browse those too.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from docrepo.ui.style import style_sheet
from docrepo.ui.task_picker import TaskPicker

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

WIDTH = 460
HINT = {"page": "Enter opens its page; Ctrl+Enter its Task view", "task_view": "Enter opens its Task view; Ctrl+Enter its page"}


class TaskSearch(QWidget):
    """The host window, and the picker that opens from it."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.app = app
        self.then = "page"
        self.setFixedSize(1, 1)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.picker = TaskPicker(self, app.ctx.model, none_entry=None)
        self.picker.setMinimumWidth(WIDTH)
        self.picker.closed_too = True
        self.picker.no_match = self._search_everything
        self.picker.picked.connect(self._picked)
        self.picker.aboutToHide.connect(lambda: QTimer.singleShot(0, self._hidden))
        self._chose = False

    def open_it(self, then: str, screen) -> None:
        self.then = then
        self.picker.hint = HINT.get(then, HINT["page"])
        self._chose = False
        area = screen.availableGeometry()
        at = QPoint(area.x() + (area.width() - WIDTH) // 2, area.y() + area.height() // 6)
        self.move(at)
        self.show()
        self.raise_()
        self.activateWindow()
        self.picker.popup(at)
        self.picker.search.setFocus()

    def _hidden(self) -> None:
        """Just after the menu closes, so what it picked has already opened while this window held the foreground."""
        if not self._chose:
            self.app.wheels.give_back()
        self.hide()

    def _picked(self, task_id: str | None) -> None:
        if task_id is None:
            return
        self._chose = True
        other = bool(QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        self.open_task(task_id, other)

    def open_task(self, task_id: str, other: bool = False) -> None:
        """The chosen task: as the wheel's slot says, or the other way with Ctrl."""
        if (self.then == "task_view") != other:
            self.app.browse.open_task_view(task_id)
        else:
            self.app.show_browse(None, task_id)

    def _search_everything(self, text: str) -> None:
        """Nothing matched: what was typed carries to Search everything."""
        self._chose = True
        self.app.show_browse()
        self.app.browse.search_box.setText(text)
        self.app.browse.search_box.setFocus()
