"""The task page with its notes page (release 5.25; the notes page plan's "The task page in three parts").

The task page was one HTML view. Its notes page is edited in place, so the task page is three parts in one scroll:
the facts (``detail.task_page`` "top": where it sits, its status, When, Who, its agenda, subtasks and Details), the
notes page's editor (``NotesEdit``), as tall as its text, and the history ("bottom": Captures, Status log, Summaries,
Files). The two HTML parts are ``PageView``s as tall as their pages, so the pane has the one scroll bar. A wheel notch
glides there, and the scroll keeps the caret in view as you type (the Qt sample's findings).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QScrollArea, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.notes_edit import NotesEdit
from docrepo.ui.page_view import PageView

#: The widest the notes page's lines get, as the task page's HTML stops widening at 1040 px (release 5.21).
NOTES_MAX = 1040


class FitPageView(PageView):
    """A part of the task page as tall as its HTML, with no scroll bar of its own."""

    def __init__(self) -> None:
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().documentLayout().documentSizeChanged.connect(lambda _: self._fit())

    def _fit(self) -> None:
        h = int(self.document().size().height()) + (self.height() - self.viewport().height())
        if h != self.height():
            self.setFixedHeight(max(h, 8))


class TaskPane(QScrollArea):
    """The task page's one scroll: ``top``, the Notes heading with its menu, ``notes``, and ``bottom``."""

    #: A Notes menu choice: "fold", "unfold", "history" or "day_headings".
    notes_menu = Signal(str)

    def __init__(self, css: str, margin: int) -> None:
        super().__init__()
        self.setObjectName("taskPane")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_id: str | None = None
        self.smooth = not LOOK.classic
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        inner = QWidget(objectName="taskPaneInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top, self.bottom = FitPageView(), FitPageView()
        for view in (self.top, self.bottom):
            view.document().setDefaultStyleSheet(css)
            view.document().setDocumentMargin(margin)
            view.viewport().installEventFilter(self)
        head = QWidget(objectName="notesHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(margin, 12, margin, 2)
        self.title = QLabel("Notes", font=tokens.ui_font(tokens.BODY + 1.5, semibold=True))
        self.saved = QLabel("", objectName="notesSaved")
        self.saved.setFont(tokens.ui_font(tokens.CAPTION))
        self.menu_button = QToolButton(objectName="notesMenu")
        self.menu_button.setIcon(icon("more"))
        self.menu_button.setToolTip("Notes: fold, the page's history, day headings")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setAutoRaise(True)
        menu = QMenu(self.menu_button)
        menu.addAction("Fold all headings", lambda: self.notes_menu.emit("fold"))
        menu.addAction("Unfold all", lambda: self.notes_menu.emit("unfold"))
        menu.addSeparator()
        self.day_action = QAction("Day headings for new captures", menu, checkable=True)
        self.day_action.setToolTip("New captures go under a heading for their day, in date order")
        self.day_action.triggered.connect(lambda: self.notes_menu.emit("day_headings"))
        menu.addAction(self.day_action)
        menu.addAction("Page history…", lambda: self.notes_menu.emit("history"))
        self.menu_button.setMenu(menu)
        hl.addWidget(self.title)
        hl.addSpacing(8)
        hl.addWidget(self.saved)
        hl.addStretch()
        hl.addWidget(self.menu_button)
        self.notes = NotesEdit()
        self.notes.viewport().installEventFilter(self)
        self.notes.on_page_key = self.page_key
        self.notes.cursorPositionChanged.connect(self.follow_caret)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(max(0, margin - 16), 0, margin, 4)
        self.notes.setMaximumWidth(NOTES_MAX)
        rl.addWidget(self.notes, 1)
        lay.addWidget(self.top)
        lay.addWidget(head)
        lay.addWidget(row)
        lay.addWidget(self.bottom)
        lay.addStretch(1)
        self.setWidget(inner)

    # ---- the one scroll ----
    def wheel(self, event) -> None:
        bar = self.verticalScrollBar()
        if not event.pixelDelta().isNull():  # a touchpad scrolls by pixels already
            self._anim.stop()
            bar.setValue(bar.value() - event.pixelDelta().y())
            return
        step = event.angleDelta().y() / 120 * QApplication.wheelScrollLines() * bar.singleStep()
        if not self.smooth:
            bar.setValue(int(bar.value() - step))
            return
        start = self._anim.endValue() if self._anim.state() == QPropertyAnimation.State.Running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), int(start - step)))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.wheel(event)
        event.accept()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Type.Wheel and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.wheel(event)
            return True
        return False

    def follow_caret(self) -> None:
        """The notes have no scroll bar of their own, so the pane keeps the caret in view as you type."""
        if not self.notes.hasFocus():
            return
        r = self.notes.cursorRect()
        p = self.notes.viewport().mapTo(self.widget(), r.center())
        self.ensureVisible(p.x(), p.y(), 20, r.height() + 40)

    def page_key(self, step: int, keep: bool) -> None:
        """Page Up and Page Down in the notes: the scroll moves a screen, and the caret keeps its place on the screen."""
        from PySide6.QtGui import QTextCursor

        bar = self.verticalScrollBar()
        r = self.notes.cursorRect()
        screen_y = self.notes.viewport().mapTo(self.viewport(), r.center()).y()
        bar.setValue(int(bar.value() + step * self.viewport().height() * 0.9))
        y = self.notes.viewport().mapFrom(self.viewport(), QPoint(0, screen_y)).y()
        c = self.notes.cursorForPosition(QPoint(r.x(), max(0, min(y, self.notes.viewport().height() - 1))))
        cur = self.notes.textCursor()
        cur.setPosition(c.position(), QTextCursor.MoveMode.KeepAnchor if keep else QTextCursor.MoveMode.MoveAnchor)
        self.notes.setTextCursor(cur)

    def scroll_to_caret(self) -> None:
        r = self.notes.cursorRect()
        p = self.notes.viewport().mapTo(self.widget(), r.center())
        self.ensureVisible(p.x(), p.y(), 20, max(80, self.viewport().height() // 3))

    def page_width(self) -> int:
        return self.top.page_width()

    def text(self) -> str:
        """Everything the pane shows, as words: what the tests read."""
        return "\n".join((self.top.toPlainText(), "Notes", self.notes.toPlainText(), self.bottom.toPlainText()))
