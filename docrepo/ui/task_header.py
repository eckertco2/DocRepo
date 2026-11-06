"""The task page's header (release 5.84, the task pane review's T2: R1, R2, R6 and decisions P1, P4, P6 and P10 in
the design workspace's ``docs/ui-design/task-pane-review.md``).

The facts above the notes were one HTML page. Now they're a short header the notes follow within the first screen:
the path, title, chips, the fact line and the description (one HTML part); the status in a tinted card, with the
status log behind its chevron (the owner's stage two: a status panel that opens to its updates); then one
**expander** per group (When and who, Key dates, Agenda, Subtasks, Links, Files, Details). A closed group is a button
with its title and a few words of summary, and the closed groups share one flowing row; an open group takes a row
of its own, its summary in full (a count, a bar, a link) and its body under it. Which groups are open is the owner's,
remembered per task. The bodies stay HTML from ``docrepo.detail``, so the page is still tested as text. On a wide
pane the browse window puts When, Who, Links and Details in the rail instead, and those groups don't show.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.page_view import FitPageView
from docrepo.ui.widgets import FlowLayout

#: The groups, in the page's order, with their titles.
GROUPS = (("when_who", "When and who"), ("key_dates", "Key dates"), ("agenda", "Agenda"), ("subtasks", "Subtasks"),
          ("links", "Links"), ("files", "Files"), ("details", "Details"))
#: Open until the owner folds them: what's dated and what's next. The rest open on a click, remembered per task.
OPEN_BY_DEFAULT = frozenset({"key_dates", "agenda", "subtasks"})
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
    """A group of the page: its head (the title on a button with a chevron, and its summary) and its body. ``toggled``
    carries the group's key and whether it's open now. The header moves a closed group's head into its shared row."""

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
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
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
        self.summary = fit_view(css, (2, 2, 2, 2))  # the open group's summary in full, with its links
        self.summary.setObjectName("groupSummary")
        self.summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        hl.addWidget(self.button)
        hl.addWidget(self.label)
        hl.addWidget(self.summary, 1)
        self.body = body if body is not None else fit_view(css, (margin, 0, margin, 6))
        self.body.hide()
        self.lay.addWidget(self.head)
        self.lay.addWidget(self.body)

    def set_content(self, summary_html: str, body_html: str | None = None) -> None:
        self.summary.setHtml(summary_html)
        self.label.setText(words_of(summary_html))
        self._show_summary()
        if body_html is not None:
            self.body.setHtml(body_html)

    def _show_summary(self) -> None:
        has = bool(self.label.text())
        self.label.setVisible(has and not self.is_open)
        self.summary.setVisible(has and self.is_open)

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
    """The header: the head part, the status card, the closed groups' row and the open groups. ``fold_changed`` carries
    a group's key (or "status_log") and whether it's open now, for the browse window to keep per task."""

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
        # The status card: the page's one tint, with the log of changes behind its chevron.
        self.card = QFrame(objectName="statusCard")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(12, 6, 10, 8)
        cl.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status_name = QLabel("Current status", objectName="statusName")
        self.status_name.setFont(tokens.ui_font(tokens.CAPTION))
        self.status_when = QLabel("", objectName="statusWhen")
        self.status_when.setFont(tokens.ui_font(tokens.CAPTION))
        self.status_fold = QToolButton(objectName="groupFold")
        self.status_fold.setIcon(icon("chevron-right"))
        self.status_fold.setAutoRaise(True)
        self.status_fold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_fold.clicked.connect(lambda: self.set_log_open(not self.log_open, emit=True))
        row.addWidget(self.status_name)
        row.addStretch()
        row.addWidget(self.status_when)
        row.addWidget(self.status_fold)
        self.status_body = fit_view(css, (0, 2, 0, 0))
        self.status_log = fit_view(css, (0, 6, 0, 0))
        self.status_log.hide()
        self.log_open = False
        cl.addLayout(row)
        cl.addWidget(self.status_body)
        cl.addWidget(self.status_log)
        self.card_wrap = QWidget()
        wl = QVBoxLayout(self.card_wrap)
        wl.setContentsMargins(margin, 8, margin, 4)
        wl.addWidget(self.card)
        # The closed groups share one row that wraps; an open group has a row of its own, then its body.
        self.strip = QWidget(objectName="groupStrip")
        self.strip_layout = FlowLayout(self.strip, spacing=10)
        self.strip_layout.setContentsMargins(max(0, margin - 4), 4, margin, 2)
        self.groups = {key: Expander(key, title, css, margin) for key, title in GROUPS}
        lay.addWidget(self.head)
        lay.addWidget(self.card_wrap)
        lay.addWidget(self.strip)
        for g in self.groups.values():
            g.toggled.connect(self._toggled)
            g.lay.setContentsMargins(max(0, margin - 4), 4, margin, 0)
            lay.addWidget(g)

    def _place(self, g: Expander) -> None:
        """A closed group's head goes into the shared row; an open group's comes back above its body. A group with
        nothing in it (``present`` off) shows nowhere."""
        if g.present and g.is_open:
            if g.head.parentWidget() is not g:
                self.strip_layout.removeWidget(g.head)
                g.lay.insertWidget(0, g.head)
            g.head.show()
            g.show()
        else:
            if g.present and g.head.parentWidget() is not self.strip:
                g.lay.removeWidget(g.head)
                self.strip_layout.addWidget(g.head)
            g.head.setVisible(g.present)
            g.hide()
        self.strip.setVisible(any(x.present and not x.is_open for x in self.groups.values()))

    def _toggled(self, key: str, is_open: bool) -> None:
        self._place(self.groups[key])
        self.fold_changed.emit(key, is_open)

    def show_parts(self, parts: dict[str, str], folds: dict[str, bool]) -> None:
        """Draw the page's parts. A group whose body is empty (no subtasks, no links, in the rail) isn't shown."""
        self.head.setHtml(parts["head"])
        self.status_name.setText(parts["status_name"])
        self.status_when.setText(parts["status_when"])
        self.status_when.setToolTip(f"The current status last changed {parts['status_age']}" if parts["status_age"] else "")
        self.status_body.setHtml(parts["status_body"])
        self.status_log.setHtml(parts["status_log"])
        self.status_fold.setToolTip(f"The status log: {parts['status_log_summary']}")
        self.set_log_open(folds.get("status_log", False))
        for key, g in self.groups.items():
            body = parts.get(key, "")
            g.present = bool(body)
            if body:
                g.set_content(parts.get(key + "_summary", ""), body)
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
