"""The task page with its notes page (release 5.25; the notes page plan's "The task page in three parts").

The task page was one HTML view. Its notes page is edited in place, so the task page is three parts in one scroll:
the facts (``detail.task_page`` "top": where it sits, its status, When, Who, its agenda, subtasks and Details), the
Notes heading with the format bar and its menu, the Checklist summary (release 5.26, ``checklist_summary``), the notes
page's editor (``NotesEdit``), as tall as its text, and the history ("bottom": Captures, Status log, Summaries, Files). The two HTML parts are ``PageView``s as tall as their pages, so the pane has the one scroll bar. A wheel notch
glides there, and the scroll keeps the caret in view as you type (the Qt sample's findings).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QScrollArea, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.checklist_summary import ChecklistSummary
from docrepo.ui.notes_edit import NotesEdit
from docrepo.ui.page_view import PageView
from docrepo.ui.rich_edit import FormatBar

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
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top, self.bottom = FitPageView(), FitPageView()
        for view in (self.top, self.bottom):
            view.document().setDefaultStyleSheet(css)
            view.document().setDocumentMargin(margin)
            view.viewport().installEventFilter(self)
        head = QWidget(objectName="notesHead")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 8, 8, 8)
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
        self.notes = NotesEdit()
        self.format_bar = FormatBar(self.notes)  # the capture window's, with the Checklist button (release 5.26)
        # A table (release 5.27, decision 128): rows and columns from the menu; Tab adds rows, right-click adds columns.
        self.table_button = QToolButton(objectName="notesTable")
        self.table_button.setIcon(icon("table"))
        self.table_button.setToolTip("Insert a table: the first row is its header. Tab moves between cells; right-click adds or removes rows and columns.")
        self.table_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.table_button.setAutoRaise(True)
        self.table_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sizes = QMenu(self.table_button)
        for rows, columns in ((2, 2), (3, 2), (3, 3), (4, 4)):
            sizes.addAction(f"{columns} columns, {rows} rows", lambda r=rows, c=columns: self.notes.insert_table(r, c))
        self.table_button.setMenu(sizes)
        hl.addWidget(self.title)
        hl.addSpacing(8)
        hl.addWidget(self.saved)
        hl.addStretch()
        hl.addWidget(self.format_bar)
        hl.addWidget(self.table_button)
        hl.addWidget(self.menu_button)
        self.notes.viewport().installEventFilter(self)
        self.notes.on_page_key = self.page_key
        self.notes.cursorPositionChanged.connect(self.follow_caret)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 14, 10)
        rl.addWidget(self.notes, 1)
        # Each layer of the frame holds at least what's in it, so the notes, as tall as their text, are never cut short.
        rl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.summary = ChecklistSummary(self.notes)
        box = QWidget(objectName="summaryBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 6)
        bl.addWidget(self.summary, 1)
        # The frame round the notes (decision 130): the capture window's editor frame, by the UI playbook's grouping
        # ladder, so the one editable part of the page stands apart. Its bottom edge turns to the accent while you type.
        self.card = QFrame(objectName="notesCard")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        for w in (head, box, row):
            cl.addWidget(w)
        self.card.setMaximumWidth(NOTES_MAX)
        self.notes.focus_changed.connect(self._card_focus)
        wrap = QWidget(objectName="notesWrap")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(margin, 20, margin, 20)
        wl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        wl.addWidget(self.card, 1)
        lay.addWidget(self.top)
        lay.addWidget(wrap)
        lay.addWidget(self.bottom)
        lay.addStretch(1)
        self.setWidget(inner)

    def _card_focus(self, on: bool) -> None:
        self.card.setProperty("typing", on)  # not "focus": every widget has a read-only one
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

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
