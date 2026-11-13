"""The task page with its notes page (release 5.25; the notes page plan's "The task page in three parts").

The task page was one HTML view. Its notes page is edited in place, so the task page is three parts in one scroll:
the facts (``detail.task_page`` "top": where it sits, its status, When, Who, its agenda, subtasks and Details), the
Notes heading with the format bar and its menu, the Checklist summary (release 5.26, ``checklist_summary``), the notes
page's editor (``NotesEdit``), as tall as its text, and the history ("bottom": Captures, Status log, Summaries, Files). The two HTML parts are ``PageView``s as tall as their pages, so the pane has the one scroll bar. A wheel notch
glides there, and the scroll keeps the caret in view as you type (the Qt sample's findings).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QShortcut, QTextCursor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QPushButton, QScrollArea, QScrollBar,
                               QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget)

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.checklist_summary import ChecklistSummary
from docrepo.ui.notes_edit import NotesEdit
from docrepo.ui.notes_outline import OUTLINE_MIN_TEXT, OUTLINE_WIDTH, NotesOutline, OutlineSlot
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
#: How close to a landmark the pointer has to be, in pixels along the scroll bar, for its tooltip (release 5.86).
LANDMARK_NEAR = 4


class LandmarkBar(QScrollBar):
    """The pane's scroll bar with landmarks (release 5.86, the task pane review's R9): a short line across the bar where
    each heading of the notes page sits in the scroll, the owner's headings in the accent and the day dividers in the
    handle's hover grey, with the heading's words in a tooltip. Alexander et al. (2009) and Mollashahi, Uddin and
    Gutwin (2018) found such marks cut the time to get back to a place on a long page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self.marks: list[tuple[int, int, bool, str]] = []  # (top on the page, level, whether it's a day, text)
        self.total = 0  # the page's height, which the whole bar stands for

    def set_marks(self, marks: list[tuple[int, int, bool, str]], total: int) -> None:
        if (marks, total) != (self.marks, self.total):
            self.marks, self.total = list(marks), total
            self.update()

    def bar_y(self, page_y: int) -> int:
        """Where a place on the page falls along the bar."""
        return round(page_y / self.total * (self.height() - 4)) + 2 if self.total > 0 else 0

    def marks_near(self, y: int) -> list[str]:
        return [text for top, _level, _day, text in self.marks if abs(self.bar_y(top) - y) <= LANDMARK_NEAR]

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().paintEvent(event)
        if not self.marks or self.total <= 0:
            return
        p = QPainter(self)
        heading = QColor(tokens.colour("accent") if not LOOK.classic else "#1d5e98")
        divider = QColor(tokens.colour("scroll_hover") if not LOOK.classic else "#888888")
        for top, _level, day, _text in self.marks:
            p.fillRect(QRect(2, self.bar_y(top), self.width() - 4, 2), divider if day else heading)
        p.end()

    def event(self, event) -> bool:  # noqa: D102 - Qt's
        if event.type() == QEvent.Type.ToolTip:
            near = self.marks_near(event.pos().y())
            if near:
                QToolTip.showText(event.globalPos(), "\n".join(near[:6]), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


class AllNotesView(FitPageView):
    """All notes (release 5.140, the notes consolidation plan's decisions 602 to 605): the pages read as one, read only,
    as tall as its HTML. A double-click on a line opens the page it's on at its block: ``edit_there`` carries the task and
    the block's capture (empty for lines typed on the page), read from the nearest "block:" anchor above the line."""

    edit_there = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("allNotes")

    @staticmethod
    def anchors_of(block) -> list[str]:
        out, it = [], block.begin()
        while not it.atEnd():
            out += it.fragment().charFormat().anchorNames()
            it += 1
        return out

    def block_at(self, pos: QPoint) -> tuple[str, str] | None:
        """The page and capture of the block a point on the view is in."""
        b = self.cursorForPosition(pos).block()
        while b.isValid():
            for name in self.anchors_of(b):
                if name.startswith("block:"):
                    _kind, task, capture = name.split(":", 2)
                    return task, capture
            b = b.previous()
        return None

    def anchor_top(self, name: str) -> int | None:
        """Where an anchor's line starts in the view, or None."""
        b = self.document().begin()
        while b.isValid():
            if name in self.anchors_of(b):
                return int(self.document().documentLayout().blockBoundingRect(b).top())
            b = b.next()
        return None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt's name
        found = self.block_at(event.position().toPoint())
        if found is not None:
            self.edit_there.emit(*found)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TaskPane(QScrollArea):
    """The task page's one scroll: ``top``, the Notes heading with its menu, ``notes``, and ``bottom``."""

    #: A Notes menu choice: "fold", "unfold", "old_days", "history" or "outline" (the outline shown or hidden, release 5.113).
    notes_menu = Signal(str)
    #: The pane crossed a width at which the page lays itself out differently (release 5.84; PageView's did this before).
    layout_changed = Signal()
    #: The Notes heading's switch (release 5.140, decision 602): "page" for This page, "all" for All notes.
    notes_mode = Signal(str)
    #: A link All notes asks the window to follow: a page picked in its outline ("allnotes:only:T…"), or a double-click's
    #: block ("notesgo:T…:C…", decision 605).
    all_notes_link = Signal(str)

    def __init__(self, css: str, margin: int) -> None:
        super().__init__()
        self.setObjectName("taskPane")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_id: str | None = None
        #: Where its messages go: the window it's in says them (``BrowseWindow.wire_notes``).
        self.say = lambda text, error=False: None
        self.smooth = not LOOK.classic
        self.setVerticalScrollBar(LandmarkBar(self))  # with landmarks for the page's headings (release 5.86)
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        inner = QWidget(objectName="taskPaneInner")
        lay = QVBoxLayout(inner)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top, self.bottom = FitPageView(), FitPageView()
        self.all_view = AllNotesView()  # All notes (release 5.140), shown in the notes' frame in their place
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
        # The Notes heading is a section's head over the frame (release 5.113, the task panel plan's decision 423), on the
        # page's left edge with the other sections' titles; the frame holds only what's typed in.
        head = QWidget(objectName="notesHead")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hv = QVBoxLayout(head)
        hv.setContentsMargins(0, 0, 0, 6)
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
        # Days older than a fortnight folded as the page opens (release 5.86, R9, decision P7): off until the owner asks,
        # per task, since a folded day is hidden content; Jump to and the fold arrow open one.
        self.old_days_action = menu.addAction("Fold days older than two weeks")
        self.old_days_action.setCheckable(True)
        self.old_days_action.triggered.connect(lambda: self.notes_menu.emit("old_days"))
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
        # Jump to (release 5.86, R9): the page's headings and days in a popover, from this button or Ctrl+G.
        self.jump_button = QToolButton(objectName="notesJump")
        self.jump_button.setIcon(icon("jump"))
        self.jump_button.setToolTip("Jump to a heading or a day on the page, or to the latest notes (Ctrl+G)")
        self.jump_button.setAutoRaise(True)
        self.jump_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.jump_button.clicked.connect(lambda: self.show_jump_menu())
        self._jump_menu: QMenu | None = None
        # The outline (release 5.113, the notes workspace plan's decision 349): a column of the page's headings at the
        # notes' left, shown or hidden by this button and kept for every task. Where it doesn't fit, Jump to stands in.
        self.outline_button = QToolButton(objectName="notesOutlineButton")
        self.outline_button.setIcon(icon("outline"))
        self.outline_button.setCheckable(True)
        self.outline_button.setAutoRaise(True)
        self.outline_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.outline_button.setToolTip("Show or hide the outline: the page's headings and days at the notes' left")
        self.outline_button.clicked.connect(self._outline_clicked)
        self.outline_on = True
        #: The heading picked in the outline, kept marked until the page is scrolled by hand (the scroll it made can leave
        #: an earlier heading at the top, near the page's end), and the scroll that pick left.
        self._outline_hold: int | None = None
        self._hold_value: int | None = None
        QShortcut(QKeySequence("Ctrl+G"), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut, activated=self._jump_key)
        # This page or All notes (release 5.140, decision 602): shown when there's more than the page to read; the choice is
        # kept per task, as a section's fold is.
        self.mode_strip = QWidget(objectName="typeStrip")
        self.mode_strip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        ml = QHBoxLayout(self.mode_strip)
        ml.setContentsMargins(2, 2, 2, 2)
        ml.setSpacing(2)
        self.mode_group = QButtonGroup(self.mode_strip)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, name, tip in (("page", "This page", "This task's notes page, where you read and write its notes"),
                               ("all", "All notes", "This page and the pages of every task and meeting under it, as one page by day, "
                                                    "each meeting as it was said: read only")):
            b = QPushButton(name, objectName="subtle")
            b.setCheckable(True)
            b.setChecked(key == "page")
            b.setToolTip(tip)
            b.setAccessibleName(f"Notes: {name}")
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.clicked.connect(lambda _=False, k=key: self.notes_mode.emit(k))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            ml.addWidget(b)
        self.mode_strip.hide()
        self.all_mode = False
        hl.addWidget(self.title)
        hl.addSpacing(8)
        hl.addWidget(self.mode_strip)
        hl.addSpacing(8)
        hl.addWidget(self.saved)
        hl.addStretch()
        hl.addWidget(self.format_bar)
        hl.addWidget(self.table_button)
        hl.addWidget(self.outline_button)
        hl.addWidget(self.jump_button)
        hl.addWidget(self.menu_button)
        # In a narrow pane the format bar has a line of its own, so the page can be as narrow as the pane (release 5.58).
        self.head_row, self.bar_row, self.head_margin = hl, None, margin
        self.notes.viewport().installEventFilter(self)
        self.notes.on_page_key = self.page_key
        self.notes.cursorPositionChanged.connect(self.follow_caret)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 14, 10)
        rl.setSpacing(6)
        self.outline = NotesOutline(self.notes)
        self.outline.picked.connect(self._outline_picked)
        self.outline_slot = OutlineSlot(self.outline, self._outline_offset, self._outline_view_height)
        self.outline_slot.hide()
        rl.addWidget(self.outline_slot)
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
        self.summary.changed.connect(lambda n: box.setVisible(n > 0 and not self.all_mode))
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
        for w in (box, row):
            cl.addWidget(w)
        # All notes in the frame, in the notes' place (release 5.140, decisions 602 to 605): read only, with an outline of
        # its days and the pages in it, which narrow it to one.
        self.all_view.document().setDefaultStyleSheet(css)
        self.all_view.document().setDocumentMargin(10)
        self.all_view.edit_there.connect(lambda task, capture: self.all_notes_link.emit(f"notesgo:{task}:{capture}"))
        self.all_outline = NotesOutline()
        self.all_outline.picked.connect(self._all_picked)
        self.all_slot = OutlineSlot(self.all_outline, self._outline_offset_all, self._outline_view_height)
        self.all_slot.hide()
        self._all_targets: list[tuple[str, str]] = []
        self.all_row = QWidget(objectName="allNotesRow")
        al = QHBoxLayout(self.all_row)
        al.setContentsMargins(0, 0, 14, 10)
        al.setSpacing(6)
        al.addWidget(self.all_slot)
        al.addWidget(self.all_view, 1)
        al.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.all_row.hide()
        cl.addWidget(self.all_row)
        self.notes_row = row
        self.card.setMaximumWidth(NOTES_MAX)
        head.setMaximumWidth(NOTES_MAX)
        self.notes.focus_changed.connect(self._card_focus)
        self.wrap = QWidget(objectName="notesWrap")
        wl = QVBoxLayout(self.wrap)
        wl.setContentsMargins(margin, 14, margin, 16)
        wl.setSpacing(0)
        wl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        wl.addWidget(head)
        wl.addWidget(self.card, 1)
        self.notes_head = head
        lay.addWidget(self.facts)
        lay.addWidget(self.wrap)
        lay.addWidget(self.history)
        lay.addStretch(1)
        self.setWidget(inner)
        # The sticky title line (release 5.86, R9): the task's title once the header has scrolled off, with Jump to and
        # Latest, which goes to the page's end. Small, opaque and unanimated (NN/g's rule), over the page, not in it.
        self.sticky = QWidget(self, objectName="stickyTitle")
        self.sticky.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QHBoxLayout(self.sticky)
        sl.setContentsMargins(margin, 3, 8, 3)
        sl.setSpacing(4)
        self.sticky_name = QLabel(objectName="stickyName")
        self.sticky_name.setFont(tokens.ui_font(tokens.BODY, semibold=True))
        self.sticky_jump = QToolButton(objectName="stickyButton")
        self.sticky_jump.setText("Jump to")
        self.sticky_jump.setToolTip("Jump to a heading or a day on the page (Ctrl+G)")
        self.sticky_jump.clicked.connect(lambda: self.show_jump_menu(self.sticky_jump.mapToGlobal(self.sticky_jump.rect().bottomLeft())))
        self.sticky_latest = QToolButton(objectName="stickyButton")
        self.sticky_latest.setText("Latest")
        self.sticky_latest.setToolTip("The end of the notes, where the newest are")
        self.sticky_latest.clicked.connect(self.latest)
        for w in (self.sticky_jump, self.sticky_latest):
            w.setAutoRaise(True)
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            w.setCursor(Qt.CursorShape.PointingHandCursor)
        sl.addWidget(self.sticky_name, 1)
        sl.addWidget(self.sticky_jump)
        sl.addWidget(self.sticky_latest)
        self.sticky.hide()
        self._title = ""
        self.verticalScrollBar().valueChanged.connect(lambda _: self._sticky_check())
        self.verticalScrollBar().valueChanged.connect(lambda _: self._outline_follow_scroll())
        self.notes.cursorPositionChanged.connect(self._outline_follow_caret)
        self.outline.rebuilt.connect(self._fit_outline)
        self.notes.page_set.connect(self._outline_release)
        # The landmarks follow the page: the notes' layout, their folds, and the page's height as groups open and close.
        self._landmark_timer = QTimer(self, singleShot=True, interval=0, timeout=self._relandmark)
        self.notes.document().documentLayout().documentSizeChanged.connect(lambda _: self._landmark_timer.start())
        self.notes.folds_changed.connect(self._landmark_timer.start)
        inner.installEventFilter(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._fit_head()
        self._fit_outline()
        self._place_sticky()
        self._landmark_timer.start()
        now = layout_of(self.page_width())
        if self._layout not in (-1, now):
            self._layout = now
            self.layout_changed.emit()
        self._layout = now

    # ---- ways down a long page (release 5.86, R9) ----
    def set_title(self, title: str) -> None:
        self._title = " ".join(title.split())
        self._place_sticky()

    def _place_sticky(self) -> None:
        vp = self.viewport().geometry()
        self.sticky.setGeometry(vp.x(), vp.y(), vp.width(), self.sticky.sizeHint().height())
        room = (vp.width() - self.sticky.layout().contentsMargins().left() - 8 - self.sticky_jump.sizeHint().width()
                - self.sticky_latest.sizeHint().width() - 16)
        self.sticky_name.setText(QFontMetrics(self.sticky_name.font()).elidedText(self._title, Qt.TextElideMode.ElideRight, max(40, room)))
        self.sticky_name.setToolTip(self._title)
        self.sticky.raise_()

    def _sticky_check(self) -> None:
        """The sticky line shows once the facts have scrolled off the top, and goes as they come back."""
        on = not self.facts.isHidden() and self.verticalScrollBar().value() > self.facts.geometry().bottom()
        if on != self.sticky.isVisible():
            self.sticky.setVisible(on)
        self.outline_slot.place()

    def show_jump_menu(self, at: QPoint | None = None) -> None:
        """Jump to: the page's headings and day dividers in the page's order, with the owner's headings indented by level
        under their day, Top of the page first and Latest last. From the Notes header's button, the sticky line or Ctrl+G."""
        menu = QMenu(self)
        if not self.facts.isHidden():
            menu.addAction("Top of the page", lambda: self.verticalScrollBar().setValue(0))
        outline = self.notes.outline()
        if outline:
            menu.addSeparator()
        for b, level, day in outline:
            text = " ".join(b.text().split()) or "(an empty heading)"
            a = menu.addAction("\u2003" * (level - 1) + text)
            a.setFont(tokens.ui_font(tokens.BODY, semibold=not day))
            a.triggered.connect(lambda _=False, b=b: self.jump_to(b))
        menu.addSeparator()
        menu.addAction("Latest", self.latest)
        self._jump_menu = menu  # the tests read it
        menu.popup(at if at is not None else self.jump_button.mapToGlobal(self.jump_button.rect().bottomLeft()))

    def _jump_key(self) -> None:
        if self.notes.hasFocus():
            self.show_jump_menu(self.notes.viewport().mapToGlobal(self.notes.cursorRect().bottomLeft()))
        else:
            self.show_jump_menu()

    def jump_to(self, block) -> None:
        """A heading from Jump to: unfolded, with the caret at its end, and scrolled to the top of the pane."""
        self.notes.go_to_block(block)
        self._block_to_top(block)
        QTimer.singleShot(0, lambda: self._block_to_top(block))  # again once the page has laid out what unfolded

    def _block_to_top(self, block) -> None:
        if not block.isValid():
            return
        top = self.notes.cursorRect(QTextCursor(block)).top()
        y = self.notes.viewport().mapTo(self.widget(), QPoint(0, top)).y()
        self.verticalScrollBar().setValue(max(0, y - self.sticky.sizeHint().height() - 8))

    def latest(self) -> None:
        """Latest: the caret at the end of the notes, in view."""
        self.notes.go_to_end()
        self.scroll_to_caret()
        QTimer.singleShot(0, self.scroll_to_caret)

    def _relandmark(self) -> None:
        inner = self.widget()
        if self.all_mode:  # the landmarks are the page's headings, which All notes doesn't show
            self.verticalScrollBar().set_marks([], inner.height())
            return
        base = self.notes.viewport().mapTo(inner, QPoint(0, 0)).y()
        marks = [(base + top, level, day, text) for top, level, day, text in self.notes.landmarks()]
        self.verticalScrollBar().set_marks(marks, inner.height())

    def views(self) -> list[FitPageView]:
        """Every HTML part of the page, for the browse window to wire its links."""
        return [self.top, self.bottom, *self.header.views(), self.history.summary, self.all_view]

    # ---- All notes (release 5.140, the notes consolidation plan's decisions 602 to 605) ----
    def set_mode_switch(self, shown: bool, mode: str) -> None:
        """The Notes heading's switch, shown when there's more than the page to read, on ``mode``."""
        self.mode_strip.setVisible(shown)
        self.mode_buttons["all" if mode == "all" and shown else "page"].setChecked(True)
        self._fit_head()

    def show_all_notes(self, html: str | None, entries=(), targets=(), current: int = -1) -> None:
        """All notes in the frame with its outline's ``entries`` (with a ``targets`` entry each: ("day", "2026-11-03"),
        ("page", "T000022"), or ("", "") for a heading), ``current`` marked; or, with ``html`` None, the page again."""
        self.all_mode = html is not None
        self.notes_row.setVisible(not self.all_mode)
        self.all_row.setVisible(self.all_mode)
        if self.all_mode:
            self.summary_box.hide()
            self.all_view.setHtml(html)
            self._all_targets = list(targets)
            self.all_outline.set_entries(list(entries))
            self.all_outline.current = -1
            self.all_outline.set_current(current)
        else:
            self.summary_box.setVisible(getattr(self.summary, "total", 0) > 0)
        self._fit_outline()
        self._landmark_timer.start()

    def _all_picked(self, number: int) -> None:
        """A day picked in All notes' outline goes there; a page narrows All notes to it (the window draws it again)."""
        if not 0 <= number < len(self._all_targets):
            return
        kind, key = self._all_targets[number]
        if kind == "day":
            top = self.all_view.anchor_top(f"day:{key}")
            if top is not None:
                y = self.all_view.viewport().mapTo(self.widget(), QPoint(0, top)).y()
                self.verticalScrollBar().setValue(max(0, y - self.sticky.sizeHint().height() - 8))
        elif kind == "page":
            self.all_notes_link.emit(f"allnotes:only:{key}")

    def _outline_offset_all(self) -> int:
        covered = self.sticky.height() if self.sticky.isVisible() else 0
        return covered - self.all_slot.mapTo(self.viewport(), QPoint(0, 0)).y()

    def show_parts(self, parts: dict[str, str], folds: dict[str, bool], wide: bool) -> None:
        """Draw a task's page from its parts (``Pages.task_parts``): the header, the rail when the pane is wide, and the
        history, open or closed as the owner left it on this task."""
        self.header.show_parts(parts, folds)
        rail = wide and bool(parts.get("rail"))  # no rail since release 5.113: the facts grid holds what it held
        self.top.setVisible(rail)
        if rail:
            self.top.setHtml(parts["rail"])
        self.history.set_content(parts["history_summary"], parts["history"], parts.get("history_short"))
        self.history.set_open(folds.get("history", False))
        self.set_title(parts.get("title", ""))
        QTimer.singleShot(0, self._sticky_check)

    def _fit_head(self) -> None:
        """The format bar beside the Notes heading while it fits there, or else on a line of its own under it."""
        spare = self.viewport().width() - 2 * self.head_margin - 22
        need = sum(w.sizeHint().width() + 8 for w in (self.title, self.mode_strip, self.saved, self.format_bar, self.table_button,
                                                      self.outline_button, self.jump_button, self.menu_button)
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

    # ---- the outline (release 5.113) ----
    def set_outline_on(self, on: bool) -> None:
        """Show the outline beside the notes (where it fits), or hide it: the owner's choice, kept for every task."""
        self.outline_on = on
        self._fit_outline()

    def outline_fits(self) -> bool:
        """Whether the notes keep OUTLINE_MIN_TEXT of text beside the outline in this pane."""
        text = self.viewport().width() - 2 * self._margin - OUTLINE_WIDTH - 2 * round(self.notes.document().documentMargin()) - 40
        return text >= OUTLINE_MIN_TEXT

    def outline_shown(self) -> bool:
        return not self.outline_slot.isHidden()

    def _fit_outline(self) -> None:
        """The outline shows when it's on, fits and the page has a heading; Jump to's button shows whenever it doesn't.
        In All notes (release 5.140) its own outline of days and pages shows instead, and Jump to isn't there."""
        fits = self.outline_fits()
        if self.all_mode:
            if self.outline_shown():
                self.outline_slot.hide()
            show_all = self.outline_on and fits and self.all_outline.count() > 0
            self.all_slot.setVisible(show_all)
            self.outline_button.setVisible(fits)
            self.outline_button.setChecked(self.outline_on and fits)
            self.jump_button.setVisible(False)
            if show_all:
                self.all_slot.place()
            return
        self.all_slot.hide()
        if self.outline.count() == 0 and self.outline_on:
            self.outline.rebuild()
        show = self.outline_on and fits and self.outline.count() > 0
        if show != self.outline_shown():
            self.outline_slot.setVisible(show)
        self.outline_button.setVisible(fits)
        self.outline_button.setChecked(self.outline_on and fits)
        self.jump_button.setVisible(not show)
        if show:
            self.outline_slot.place()
            self._outline_follow_scroll()

    def _outline_clicked(self) -> None:
        self.outline_on = not self.outline_on
        self._fit_outline()
        self.notes_menu.emit("outline")

    def _outline_offset(self) -> int:
        """How far the outline's slot has scrolled above the view's top, less the sticky line over it."""
        covered = self.sticky.height() if self.sticky.isVisible() else 0
        return covered - self.outline_slot.mapTo(self.viewport(), QPoint(0, 0)).y()

    def _outline_view_height(self) -> int:
        return self.viewport().height() - (self.sticky.height() if self.sticky.isVisible() else 0)

    def _outline_picked(self, number: int) -> None:
        block = self.notes.document().findBlockByNumber(number)
        if block.isValid():
            self._outline_hold, self._hold_value = number, None
            self.jump_to(block)
            self.outline.set_current(number)
            QTimer.singleShot(0, self._outline_settled)  # after jump_to's own second scroll

    def _outline_settled(self) -> None:
        if self._outline_hold is not None:
            self._hold_value = self.verticalScrollBar().value()

    def _outline_release(self) -> None:
        self._outline_hold = self._hold_value = None

    def _outline_follow_scroll(self) -> None:
        """Mark the heading at the top of the view: the last one whose line has reached it (the first, before any has)."""
        if self.all_mode:
            self.all_slot.place()
            return
        if not self.outline_shown():
            return
        self.outline_slot.place()
        bar = self.verticalScrollBar()
        if self._outline_hold is not None:
            if self._hold_value is None or bar.value() == self._hold_value:
                self.outline.set_current(self._outline_hold)
                return
            self._outline_release()  # scrolled by hand since
        covered = self.sticky.height() if self.sticky.isVisible() else 0
        top = self.notes.viewport().mapFrom(self.viewport(), QPoint(0, covered)).y()
        # At the page's end the last headings can't reach the top: the last one in view is where you are.
        line = top + (self.viewport().height() - covered - 24 if bar.maximum() > 0 and bar.value() >= bar.maximum() else 24)
        layout = self.notes.document().documentLayout()
        current = -1
        for b, _level, _day in self.notes.outline():
            if not b.isVisible():
                continue
            if current != -1 and layout.blockBoundingRect(b).top() > line:
                break
            current = b.blockNumber()
        self.outline.set_current(current)

    def _outline_follow_caret(self) -> None:
        """While you type, the heading over the caret is the one marked."""
        if not self.outline_shown() or not self.notes.hasFocus():
            return
        h = self.notes.heading_of(self.notes.textCursor().block())
        self.outline.set_current(h.blockNumber() if h is not None else -1)

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
        if watched is self.widget() and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self._landmark_timer.start()  # the page's height changed: the landmarks move with it
            self._sticky_check()
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
        notes = self.all_view.toPlainText() if self.all_mode else self.notes.toPlainText()
        return "\n".join((self.header.text(), rail, "Notes", notes, "History", self.bottom.toPlainText()))
