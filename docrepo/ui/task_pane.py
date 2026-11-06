"""The task page with its notes page (release 5.25; the notes page plan's "The task page in three parts").

The task page was one HTML view. Its notes page is edited in place, so the task page is three parts in one scroll:
the facts (``detail.task_page`` "top": where it sits, its status, When, Who, its agenda, subtasks and Details), the
Notes heading with the format bar and its menu, the Checklist summary (release 5.26, ``checklist_summary``), the notes
page's editor (``NotesEdit``), as tall as its text, and the history ("bottom": Captures, Status log, Summaries, Files). The two HTML parts are ``PageView``s as tall as their pages, so the pane has the one scroll bar. A wheel notch
glides there, and the scroll keeps the caret in view as you type (the Qt sample's findings).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QScrollArea, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.checklist_summary import ChecklistSummary
from docrepo.ui.notes_edit import NotesEdit
from docrepo.detail import RAIL
from docrepo.ui.page_view import FitPageView, layout_of
from docrepo.ui.task_header import Expander, TaskHeader
from docrepo.ui.rich_edit import FormatBar

#: The widest the Notes frame gets, as the task page's HTML stops widening at 1040 px (release 5.21).
NOTES_MAX = 1040
#: The most characters a line of notes holds (release 5.83, the task pane review's R11): the frame's chrome keeps its width,
#: the text stops at about 90 characters, the top of Butterick's 45 to 90 (Segoe UI Variable's average character is 6 px
#: at the Body size, so 90 is 552 px: narrower than the usual pane's 628 px of text, and far from the wide page's 1,000).
NOTES_LINE = 90
#: How long the format bar stays after the caret leaves the notes, so a click on one of its menus keeps it (release 5.83, R8).
BAR_LINGER_MS = 200


class TaskPane(QScrollArea):
    """The task page's one scroll: ``top``, the Notes heading with its menu, ``notes``, and ``bottom``."""

    #: A Notes menu choice: "fold", "unfold" or "history".
    notes_menu = Signal(str)
    #: The pane crossed a width at which the page lays itself out differently (release 5.84; PageView's did this before).
    layout_changed = Signal()

    def __init__(self, css: str, margin: int) -> None:
        super().__init__()
        self.setObjectName("taskPane")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_id: str | None = None
        #: Where its messages go: the window it's in says them (``BrowseWindow.wire_notes``).
        self.say = lambda text, error=False: None
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
        # Release 5.84 (the task pane review's T2): the facts are a header of widgets (the head, the status card and the
        # groups as expanders), with ``top`` as the rail beside it on a wide pane, and the history an expander after the notes.
        self.header = TaskHeader(css, margin)
        self.top.setFixedWidth(RAIL + 2 * margin)
        self.top.hide()
        self.facts = QWidget(objectName="factsRow")
        fl = QHBoxLayout(self.facts)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        fl.addWidget(self.header, 1)
        fl.addWidget(self.top, 0, Qt.AlignmentFlag.AlignTop)
        self.history = Expander("history", "History", css, margin, body=self.bottom)
        self._layout, self._margin = -1, margin
        for view in self.views():
            view.viewport().installEventFilter(self)
        head = QWidget(objectName="notesHead")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hv = QVBoxLayout(head)
        hv.setContentsMargins(14, 8, 8, 8)
        hv.setSpacing(4)
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hv.addLayout(hl)
        self.head_lines = hv
        self.title = QLabel("Notes", font=tokens.ui_font(tokens.BODY, semibold=True))
        self.saved = QLabel("", objectName="notesSaved")
        self.saved.setFont(tokens.ui_font(tokens.CAPTION))
        self.menu_button = QToolButton(objectName="notesMenu")
        self.menu_button.setIcon(icon("more"))
        self.menu_button.setToolTip("Notes: fold, and the page's history")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setAutoRaise(True)
        menu = QMenu(self.menu_button)
        menu.addAction("Fold all headings", lambda: self.notes_menu.emit("fold"))
        menu.addAction("Unfold all", lambda: self.notes_menu.emit("unfold"))
        # Release 5.69 retired "Day headings for new captures" (decision 119): new notes and captures always go under
        # their day's heading, or a note under its own headings (the notes workspace plan's decision 345).
        menu.addSeparator()
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
        # In a narrow pane the format bar has a line of its own, so the page can be as narrow as the pane (release 5.58).
        self.head_row, self.bar_row, self.head_margin = hl, None, margin
        self.notes.viewport().installEventFilter(self)
        self.notes.on_page_key = self.page_key
        self.notes.cursorPositionChanged.connect(self.follow_caret)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 14, 10)
        rl.addWidget(self.notes, 1)
        rl.addStretch(0)
        # The text stops at NOTES_LINE characters (R11), however wide the frame: the eye loses a longer line on the way back.
        margin_px = 2 * round(self.notes.document().documentMargin())
        self.notes.setMaximumWidth(round(QFontMetrics(self.notes.font()).averageCharWidth() * NOTES_LINE) + margin_px + 4)
        # Each layer of the frame holds at least what's in it, so the notes, as tall as their text, are never cut short.
        rl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.summary = ChecklistSummary(self.notes)
        box = QWidget(objectName="summaryBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 6)
        bl.addWidget(self.summary, 1)
        # The Checklist summary only when the page has a checklist line (R8): Ctrl+1 or the Checklist button makes the first.
        self.summary_box = box
        box.hide()
        self.summary.changed.connect(lambda n: box.setVisible(n > 0))
        # The format bar only while the caret is in the notes (R8, decision P6), kept a moment for a click on one of its menus.
        self._bar_timer = QTimer(self)
        self._bar_timer.setSingleShot(True)
        self._bar_timer.setInterval(BAR_LINGER_MS)
        self._bar_timer.timeout.connect(self._bar_check)
        for w in (self.format_bar, self.table_button):
            w.hide()
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
        self.wrap = QWidget(objectName="notesWrap")
        wl = QHBoxLayout(self.wrap)
        wl.setContentsMargins(margin, 20, margin, 20)
        wl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        wl.addWidget(self.card, 1)
        lay.addWidget(self.facts)
        lay.addWidget(self.wrap)
        lay.addWidget(self.history)
        lay.addStretch(1)
        self.setWidget(inner)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._fit_head()
        now = layout_of(self.page_width())
        if self._layout not in (-1, now):
            self._layout = now
            self.layout_changed.emit()
        self._layout = now

    def views(self) -> list[FitPageView]:
        """Every HTML part of the page, for the browse window to wire its links."""
        return [self.top, self.bottom, *self.header.views(), self.history.summary]

    def show_parts(self, parts: dict[str, str], folds: dict[str, bool], wide: bool) -> None:
        """Draw a task's page from its parts (``Pages.task_parts``): the header, the rail when the pane is wide, and the
        history, open or closed as the owner left it on this task."""
        self.header.show_parts(parts, folds)
        self.top.setVisible(wide)
        if wide:
            self.top.setHtml(parts["rail"])
        self.history.set_content(parts["history_summary"], parts["history"])
        self.history.set_open(folds.get("history", False))

    def _fit_head(self) -> None:
        """The format bar beside the Notes heading while it fits there, or else on a line of its own under it."""
        spare = self.viewport().width() - 2 * self.head_margin - 22
        need = sum(w.sizeHint().width() + 8 for w in (self.title, self.saved, self.format_bar, self.table_button, self.menu_button)
                   if not w.isHidden())
        narrow = need > spare
        if narrow == (self.bar_row is not None):
            return
        if narrow:
            self.head_row.removeWidget(self.format_bar)
            self.bar_row = QHBoxLayout()
            self.bar_row.setContentsMargins(0, 0, 0, 0)
            self.bar_row.addWidget(self.format_bar)
            self.bar_row.addStretch()
            self.head_lines.addLayout(self.bar_row)
        else:
            self.bar_row.removeWidget(self.format_bar)
            self.head_lines.removeItem(self.bar_row)
            self.bar_row = None
            self.head_row.insertWidget(self.head_row.count() - 2, self.format_bar)

    def notes_only(self) -> None:
        """Only the Notes frame, as the Task view's Notes page tab shows it (release 5.37, decision 243)."""
        self.facts.hide()
        self.history.hide()
        self.wrap.layout().setContentsMargins(0, 0, 0, 12)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def _card_focus(self, on: bool) -> None:
        self.card.setProperty("typing", on)  # not "focus": every widget has a read-only one
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        if on:
            self._bar_timer.stop()
            self._show_bar(True)
        else:
            self._bar_timer.start()

    def _bar_check(self) -> None:
        """The caret left the notes a moment ago: the bar goes unless one of its menus is open, or the caret came back."""
        if QApplication.activePopupWidget() is not None:
            self._bar_timer.start()
            return
        if not self.notes.hasFocus():
            self._show_bar(False)

    def _show_bar(self, on: bool) -> None:
        if self.format_bar.isHidden() != on:
            return
        for w in (self.format_bar, self.table_button):
            w.setVisible(on)
        self._fit_head()

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
        """The width a page's HTML has in this pane: the viewport's, less the document margins."""
        return self.viewport().width() - 2 * self._margin

    def text(self) -> str:
        """Everything the pane shows, as words: what the tests read. The history's words are included whether it's open or
        not, as they were when it was always shown."""
        rail = self.top.toPlainText() if not self.top.isHidden() else ""
        return "\n".join((self.header.text(), rail, "Notes", self.notes.toPlainText(), "History", self.bottom.toPlainText()))
