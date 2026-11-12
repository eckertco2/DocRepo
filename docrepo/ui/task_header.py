"""The task page's header (release 5.84, the task pane review's T2; made calmer in release 5.113, the task panel plan in
the design workspace's ``docs/mods/task-panel-plan.md``).

The facts above the notes: the path, the title and the description, then the **facts grid** (its state and flags, its
dates, its people and its labels, each a grey name beside its value, release 5.113's decision 422), as one HTML part;
the status as a card with a bar down its left side, its log behind the button at its right (the owner's stage two: a
status panel that opens to its updates); then one **section** per group (Key dates, Agenda, Subtasks, Decisions since
release 5.124, Email conversations since release 5.122, Links, Files, Details), stacked in that order, open or closed. Every section's head
is the same row: a chevron hanging in the margin, the title, a count or a few words, and its one command at the right;
so the title, the grid, the sections, the notes and the history all start on one left edge (decision 423). Which groups
are open is the owner's, remembered per task. The bodies stay HTML from ``docrepo.detail``, so the page is still tested
as text.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.page_view import FitPageView

#: The groups, in the page's order, with their titles. When and who went into the facts grid in release 5.113. Decisions
#: (release 5.124, the cold-eyes plan's decision 477) come after Subtasks and before Email conversations.
GROUPS = (("key_dates", "Key dates"), ("agenda", "Agenda"), ("subtasks", "Subtasks"), ("decisions", "Decisions"), ("emails", "Email conversations"),
          ("links", "Links"), ("files", "Files"), ("details", "Details"))
#: Open until the owner folds them: what's dated and what's next, what's been decided (release 5.124) and the task's
#: emails (release 5.122, the email section plan's decision 455). The rest open on a click, remembered per task.
OPEN_BY_DEFAULT = frozenset({"key_dates", "agenda", "subtasks", "decisions", "emails"})
#: How far a section's chevron hangs into the margin, so its title starts on the page's left edge (decision 423).
HANG = 22
_TAGS = re.compile(r"<[^>]+>")


def fit_view(css: str, margins: tuple[int, int, int, int]) -> FitPageView:
    view = FitPageView()
    view.document().setDefaultStyleSheet(css)
    view.set_margins(*margins)
    view.viewport().setAutoFillBackground(False)
    return view


def words_of(html: str) -> str:
    """A summary's words for the closed group's label: its text without the links, images and spacing."""
    text = _TAGS.sub("", html).replace("&nbsp;", " ").replace("&amp;", "&")
    return " ".join(text.split())


class Expander(QWidget):
    """A section of the page: its head (the chevron and title on one button, a count or a few words, and the section's
    command at the right) and its body. Closed, the head shows ``short`` (a count) in the secondary colour; open, the
    summary in full, with its links. ``toggled`` carries the group's key and whether it's open now."""

    toggled = Signal(str, bool)

    def __init__(self, key: str, title: str, css: str, margin: int, body: FitPageView | None = None) -> None:
        super().__init__()
        self.key, self.margin = key, margin
        self.is_open = False
        self.present = False  # whether the page has anything for this group
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.head = QWidget(objectName="groupHeadRow")
        hl = QHBoxLayout(self.head)
        # The chevron hangs in the margin: the title's words start where the page's do.
        hl.setContentsMargins(max(0, margin - HANG), 3, margin, 3)
        hl.setSpacing(8)
        self.button = QToolButton(objectName="groupHead")
        self.button.setText(title)
        self.button.setFont(tokens.ui_font(tokens.BODY, semibold=True))
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setIcon(icon("chevron-right"))
        self.button.setAutoRaise(True)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip(f"Show or hide {title[0].lower() + title[1:]}")
        self.button.clicked.connect(self.toggle)
        self.label = QLabel(objectName="groupSummaryLabel")  # the closed group's few words
        self.label.setFont(tokens.ui_font(tokens.CAPTION))
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.mousePressEvent = lambda _e: self.toggle()
        self.summary = fit_view(css, (0, 2, 0, 0))  # the open group's summary in full, with its links
        self.summary.setObjectName("groupSummary")
        self.summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        hl.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(self.summary, 1, Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(0)  # nothing centres when the summary is empty (release 5.84 drew an open Details in the middle)
        self.short = ""
        self.body = body if body is not None else fit_view(css, (margin, 0, margin, 8))
        self.body.hide()
        self.lay.addWidget(self.head)
        self.lay.addWidget(self.body)

    def set_content(self, summary_html: str, body_html: str | None = None, short: str | None = None) -> None:
        self.summary.setHtml(summary_html)
        self.short = words_of(summary_html) if short is None else short
        self.label.setText(self.short)
        self._show_summary()
        if body_html is not None:
            self.body.setHtml(body_html)

    def _show_summary(self) -> None:
        self.label.setVisible(bool(self.short) and not self.is_open)
        self.summary.setVisible(bool(self.summary.toPlainText().strip()) and self.is_open)

    def set_open(self, is_open: bool, emit: bool = False) -> None:
        self.is_open = is_open
        self.body.setVisible(is_open)
        self.button.setIcon(icon("chevron-down" if is_open else "chevron-right"))
        self._show_summary()
        if emit:
            self.toggled.emit(self.key, is_open)

    def toggle(self) -> None:
        self.set_open(not self.is_open, emit=True)

    def views(self) -> list[FitPageView]:
        return [self.summary, self.body]

    def text(self) -> str:
        """The group in words: its title and summary, and its body while it's open (what the tests read)."""
        parts = [self.button.text(), self.summary.toPlainText() if self.is_open else self.label.text()]
        if self.is_open:
            parts.append(self.body.toPlainText())
        return " ".join(x for x in parts if x)


class TaskHeader(QWidget):
    """The header: the head part (with the facts grid), the status card and the sections. ``fold_changed`` carries a
    group's key (or "status_log") and whether it's open now, for the browse window to keep per task."""

    fold_changed = Signal(str, bool)

    def __init__(self, css: str, margin: int) -> None:
        super().__init__()
        self.setObjectName("taskHeader")
        self.margin = margin
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.head = fit_view(css, (margin, margin, margin, 0))
        # The status card: the page's one tinted block, with a bar down its left side, and the log of changes behind the
        # button at its right (release 5.113: the bar and the button's words, so the card reads as one and says what opens).
        self.card = QFrame(objectName="statusCard")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 8, 8, 10)
        cl.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.status_name = QLabel("Current status", objectName="statusName")
        self.status_name.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        self.status_when = QLabel("", objectName="statusWhen")
        self.status_when.setFont(tokens.ui_font(tokens.CAPTION))
        # "asked Mon" while an Ask for an update waits for a capture on the task (release 5.125, the cold-eyes plan's decision 485).
        self.status_asked = QLabel("", objectName="statusWhen")
        self.status_asked.setFont(tokens.ui_font(tokens.CAPTION))
        self.status_asked.hide()
        self.status_fold = QToolButton(objectName="statusLog")
        self.status_fold.setIcon(icon("chevron-right"))
        self.status_fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.status_fold.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # the chevron after the words
        self.status_fold.setFont(tokens.ui_font(tokens.CAPTION))
        self.status_fold.setAutoRaise(True)
        self.status_fold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_fold.clicked.connect(lambda: self.set_log_open(not self.log_open, emit=True))
        row.addWidget(self.status_name)
        row.addWidget(self.status_when)
        row.addWidget(self.status_asked)
        row.addStretch()
        row.addWidget(self.status_fold)
        self.status_body = fit_view(css, (0, 4, 0, 0))
        self.status_log = fit_view(css, (0, 8, 0, 0))
        self.status_log.hide()
        self.log_open = False
        cl.addLayout(row)
        cl.addWidget(self.status_body)
        cl.addWidget(self.status_log)
        self.card_wrap = QWidget()
        wl = QVBoxLayout(self.card_wrap)
        wl.setContentsMargins(margin, 14, margin, 10)
        wl.addWidget(self.card)
        self.groups = {key: Expander(key, title, css, margin) for key, title in GROUPS}
        lay.addWidget(self.head)
        lay.addWidget(self.card_wrap)
        for g in self.groups.values():
            g.toggled.connect(self._toggled)
            lay.addWidget(g)

    def _place(self, g: Expander) -> None:
        """A group with nothing in it (``present`` off) shows nowhere."""
        g.setVisible(g.present)

    def _toggled(self, key: str, is_open: bool) -> None:
        self._place(self.groups[key])
        self.fold_changed.emit(key, is_open)

    def show_parts(self, parts: dict[str, str], folds: dict[str, bool]) -> None:
        """Draw the page's parts. A group whose body is empty (no subtasks, no links) isn't shown."""
        self.head.setHtml(parts["head"])
        self.status_name.setText(parts["status_name"])
        self.status_when.setText(f"· {parts['status_when']}" if parts["status_when"] else "")
        self.status_when.setToolTip(f"The current status last changed {parts['status_age']}" if parts["status_age"] else "")
        asked = parts.get("status_asked", "")
        self.status_asked.setText(f"· {asked}")
        self.status_asked.setToolTip(parts.get("status_asked_tip", ""))
        self.status_asked.setVisible(bool(asked))
        self.status_body.setHtml(parts["status_body"])
        self.status_log.setHtml(parts["status_log"])
        self.status_fold.setText(parts["status_log_summary"])
        self.status_fold.setToolTip(f"The status log: {parts['status_log_summary']}")
        self.card.setProperty("empty", not parts["status_when"])
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        self.set_log_open(folds.get("status_log", False))
        for key, g in self.groups.items():
            body = parts.get(key, "")
            g.present = bool(body)
            if body:
                g.set_content(parts.get(key + "_summary", ""), body, parts.get(key + "_short"))
                g.set_open(folds.get(key, key in OPEN_BY_DEFAULT))
            self._place(g)

    def set_log_open(self, is_open: bool, emit: bool = False) -> None:
        self.log_open = is_open
        self.status_log.setVisible(is_open)
        self.status_fold.setIcon(icon("chevron-down" if is_open else "chevron-right"))
        if emit:
            self.fold_changed.emit("status_log", is_open)

    def views(self) -> list[FitPageView]:
        out = [self.head, self.status_body, self.status_log]
        for g in self.groups.values():
            out += g.views()
        return out

    def text(self) -> str:
        parts = [self.head.toPlainText(), self.status_name.text(), self.status_when.text(), self.status_body.toPlainText()]
        if self.log_open:
            parts.append(self.status_log.toPlainText())
        parts += [g.text() for g in self.groups.values() if g.present]
        return "\n".join(x for x in parts if x)
