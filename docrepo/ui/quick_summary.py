"""The quick summary's window (release 5.131; the design workspace's ``docs/mods/quick-summary-plan.md``, decisions 517 to 539).

A window of its own (decision 518), opened from the Execution wheel's S (decision 517), Ctrl+K, or Quick summary on a
person's, a label's or an agenda's page. It opens over the window you were in, with the cursor in its box; Esc closes it.

- **The box** (decision 519): with nothing typed it lists the pinned subjects, then the recent ones, numbered for 1 to 9,
  each with its count; typing lists the people, agendas, labels and tagged labels that match, with `@` keeping to people.
  Up and Down move, Enter opens. With nothing matching, **New agenda "…"** opens New task with Meeting ticked and the words
  as its title (decision 528).
- **Several together** (decisions 555 to 562): Ctrl+Enter, a Ctrl+click or a `+` before the words adds a subject to what's
  showing, as a chip before the box; Backspace in the empty box or a chip's ✕ takes one off. Each agenda shows as its own
  section, with its own add box.
- **The summary** is ``docrepo.summary``'s, drawn as the task page draws its sections (release 5.113): the header (the face,
  the name, what it is, its facts, the headline), then a section each, open or folded.
- **The agenda** (decisions 526 and 527): a tick marks an item Discussed and opens a line for the answer, which Enter keeps as
  a note (``save.save_answer``) and Esc skips; Undo opens the item again. The add box adds a note, and `#` picks a task with
  the task picker, the rest of the line its note.
- **Copy** (decision 533) puts it on the clipboard as rich text and Markdown; **☆** pins it (decision 534); **Open page**
  shows its page in the browse tool.

A link opens what it names in the browse tool: a task's page, a conversation's page, a capture, the Activity view.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import unquote

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import edits, save, summary
from docrepo.detail import esc, section_head
from docrepo.summary import AgendaRow, Builder, Section, Subject, Summary
from docrepo.ui import conversation_page, tokens
from docrepo.ui.front import bring_to_front
from docrepo.ui.icons import icon
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.task_header import Expander, fit_view
from docrepo.ui.task_picker import TaskPicker

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

#: The window's size (decision 518): a column you read top to bottom.
WIDTH, HEIGHT = 760, 820
MARGIN = 24
#: How long a message, with its Undo, stays at the foot.
MESSAGE_MS = 10_000
#: The box's list: the role holding a row's (kind, key, words).
ROW_ROLE = Qt.ItemDataRole.UserRole


def summary_css() -> str:
    """The page styles, and the headline's chips (decision 522): grey, with the accent for what to raise, red for late and
    amber for soon."""
    t = tokens.LIGHT
    return page_css() + f"""
.chip {{ color: {t['text2']}; background-color: {t['hover']}; }}
.chipraise {{ color: {t['accent']}; background-color: {t['info_bg']}; }}
.chiplate {{ color: {t['critical']}; background-color: {t['critical_bg']}; }}
.chipsoon {{ color: {t['caution']}; background-color: {t['caution_bg']}; }}
.chipcalm {{ color: {t['text2']}; }}
.fl {{ color: {t['text2']}; font-size: 9pt; }}
.kindline {{ color: {t['text2']}; }}
"""


def window_css() -> str:
    """The window's own styles: the page white, as the browse tool's pages are; an agenda item's tick a box that fills with
    the accent; the add box's task as a chip."""
    t = tokens.LIGHT
    return f"""
QScrollArea#summaryScroll, QWidget#summaryPage {{ background: {t['content']}; border: none; }}
QToolButton#agendaTick {{ border: 1px solid {t['control']}; border-radius: 4px; background: {t['content']}; padding: 0; }}
QToolButton#agendaTick:hover {{ border-color: {t['accent']}; }}
QToolButton#agendaTick:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QToolButton#addTask, QToolButton#summaryChip {{ background: {t['info_bg']}; color: {t['accent']}; border: none; border-radius: 10px; padding: 2px 8px; }}
QToolButton#summaryChip:hover {{ background: {t['selected']}; }}
QWidget#agendaRow {{ border-radius: 6px; }}
QWidget#agendaRow:hover {{ background: {t['hover']}; }}
"""


def header_html(s: Summary) -> str:
    """The face, the name, what it is, the facts on one grey line, and the headline (decisions 521 and 522)."""
    facts = " &nbsp; &nbsp; ".join(f'<span class="fl">{esc(k)}</span> {esc(v)}' for k, v in s.facts)
    chips = " ".join(f'<span class="chip{c.kind}">&nbsp;{c.html}&nbsp;</span>' for c in s.chips)
    face = esc(s.face)
    return (f'<table cellspacing="0" cellpadding="0"><tr><td valign="top" width="54"><img src="face:{face}" width="40" height="40"></td>'
            f'<td valign="top"><h2 style="margin: 0">{esc(s.subject.name)}</h2><p class="kindline" style="margin: 0">{esc(s.kind_line)}</p>'
            f'<p style="margin: 6px 0 0 0">{facts}</p></td></tr></table><p style="margin: 10px 0 0 0">{chips}</p>')


def head_words(sec: Section) -> str:
    """A section's count and few words, beside its title."""
    return " · ".join(x for x in (sec.count, sec.extra) if x)


# ---- the box's list ----
class SubjectDelegate(QStyledItemDelegate):
    """A row of the box's list: its number (for 1 to 9), a person's initials or an agenda's or a label's mark, the name, what
    it is in grey, a star when pinned, and its count at the right. A heading is small grey capitals."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        kind = index.data(ROW_ROLE)[0]
        return QSize(200, 26 if kind == "head" else 36)

    def paint(self, p: QPainter, option, index) -> None:
        kind, _key, words = index.data(ROW_ROLE)
        t = tokens.LIGHT
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "head":
            f = tokens.ui_font(tokens.CAPTION, semibold=True)
            p.setFont(f)
            p.setPen(QColor(t["text2"]))
            p.drawText(r.adjusted(12, 6, -12, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, words["title"].upper())
            p.restore()
            return
        if option.state & QStyle.StateFlag.State_Selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["selected"]))
            p.drawRoundedRect(r.adjusted(4, 1, -4, -1), 5, 5)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["hover"]))
            p.drawRoundedRect(r.adjusted(4, 1, -4, -1), 5, 5)
        x = r.left() + 12
        small = tokens.ui_font(tokens.CAPTION)
        if words.get("number"):
            box = QRect(x, r.center().y() - 10, 20, 20)
            p.setPen(QColor(t["stroke_strong"]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 4, 4)
            p.setFont(small)
            p.setPen(QColor(t["text2"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, words["number"])
        x += 30
        circle = QRect(x, r.center().y() - 13, 26, 26)
        p.setPen(Qt.PenStyle.NoPen)
        if kind == "person":
            p.setBrush(QColor(t["info_bg"]))
            p.drawEllipse(circle)
            f = tokens.ui_font(tokens.CAPTION, semibold=True)
            p.setFont(f)
            p.setPen(QColor(t["accent"]))
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, words.get("initials", ""))
        else:
            p.setBrush(QColor(t["base"]))
            p.drawEllipse(circle)
            name = {"agenda": "agenda", "label": "labels", "tag": "tagged", "many": "people", "new": "add"}.get(kind, "agenda")
            p.drawPixmap(circle.adjusted(5, 5, -5, -5), icon(name).pixmap(16, 16))
        x += 36
        count = words.get("count", "")
        body = tokens.ui_font(tokens.BODY)
        fm = QFontMetrics(small)
        count_w = fm.horizontalAdvance(count) + 8 if count else 0
        right = r.right() - 14
        if count:
            p.setFont(small)
            p.setPen(QColor(t["text2"]))
            p.drawText(QRect(right - count_w, r.top(), count_w, r.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count)
            right -= count_w + 6
        if words.get("pinned"):
            p.drawPixmap(QRect(right - 14, r.center().y() - 7, 14, 14), icon("pin", t["caution"]).pixmap(14, 14))
            right -= 20
        p.setFont(body)
        p.setPen(QColor(t["text"]))
        name_fm = QFontMetrics(body)
        kind_words = words.get("kind", "")
        room = right - x
        name = name_fm.elidedText(words["name"], Qt.TextElideMode.ElideRight, max(40, room - (fm.horizontalAdvance(kind_words) + 14 if kind_words else 0)))
        p.drawText(QRect(x, r.top(), room, r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        if kind_words:
            nx = x + name_fm.horizontalAdvance(name) + 8
            p.setFont(small)
            p.setPen(QColor(t["text2"]))
            p.drawText(QRect(nx, r.top(), max(0, right - nx), r.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, kind_words)
        p.restore()


class SubjectList(QListWidget):
    """The box's list: headings, subjects and New agenda. ``picked`` sends the row's (kind, key)."""

    picked = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("summaryList")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(SubjectDelegate(self))
        self.itemClicked.connect(self._clicked)

    def fill(self, rows: list[tuple[str, str, dict]]) -> None:
        """Rows as (kind, key, words); the first that can be picked is current."""
        self.clear()
        for kind, key, words in rows:
            item = QListWidgetItem()
            item.setData(ROW_ROLE, (kind, key, words))
            if kind == "head":
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(item)
        self.setCurrentRow(self._next(0, 1))

    def rows(self) -> list[tuple[str, str, dict]]:
        return [self.item(i).data(ROW_ROLE) for i in range(self.count())]

    def _next(self, row: int, step: int) -> int:
        while 0 <= row < self.count():
            if self.item(row).data(ROW_ROLE)[0] != "head":
                return row
            row += step
        return -1

    def step(self, by: int) -> None:
        row = self._next(self.currentRow() + by, by)
        if row >= 0:
            self.setCurrentRow(row)

    def current(self) -> tuple[str, str] | None:
        item = self.currentItem()
        if item is None:
            return None
        kind, key, _words = item.data(ROW_ROLE)
        return None if kind == "head" else (kind, key)

    def numbered(self, n: int) -> tuple[str, str] | None:
        for kind, key, words in self.rows():
            if words.get("number") == str(n):
                return kind, key
        return None

    def _clicked(self, item: QListWidgetItem) -> None:
        kind, key, _words = item.data(ROW_ROLE)
        if kind != "head":
            self.picked.emit(kind, key)


# ---- the agenda ----
class AgendaBody(QWidget):
    """The agenda's rows, each with its tick, the answer line under a row just discussed, and the add box (decisions 526,
    527 and 529)."""

    ticked = Signal(int, bool)  # item, discussed
    answered = Signal(int, str)  # item, the answer ("" to skip)
    add = Signal(str, object)  # the note, and the task picked with # (or None)
    pick_task = Signal()

    def __init__(self, rows: list[AgendaRow], answering: int | None, said: dict[int, tuple[str, str]], add_words: str, margin: int,
                 task_name: str = "") -> None:
        super().__init__()
        self.setObjectName("agendaBody")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin - 8, 0, margin, 8)
        lay.setSpacing(0)
        t = tokens.LIGHT
        self.answer_box: QLineEdit | None = None
        self.ticks: dict[int, QToolButton] = {}
        for a in rows:
            row = QWidget(objectName="agendaRow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 7, 0, 7)
            rl.setSpacing(10)
            tick = QToolButton(objectName="agendaTick")
            tick.setCheckable(True)
            tick.setChecked(a.discussed)
            tick.setFixedSize(20, 20)
            if a.discussed:
                tick.setIcon(icon("tick-white", t["on_accent"], t["on_accent"], 12))
            tick.setToolTip("Open it again" if a.discussed else "Discussed: tick it, then type the answer")
            tick.setCursor(Qt.CursorShape.PointingHandCursor)
            tick.clicked.connect(lambda _c=False, a=a: self.ticked.emit(a.item, not a.discussed))
            self.ticks[a.item] = tick
            words = QLabel(objectName="agendaWords")
            words.setWordWrap(True)
            words.setTextFormat(Qt.TextFormat.RichText)
            q = f'<span style="color: {t["text2"]}; text-decoration: line-through">{esc(a.question)}</span>' if a.discussed else esc(a.question)
            words.setText(f'<span style="font-size: {tokens.BODY + 0.5}pt">{q}</span><br>'
                          f'<span style="color: {t["text2"]}; font-size: {tokens.CAPTION}pt">{esc(a.about)}</span>')
            words.setToolTip(a.tip)
            side = QLabel(objectName="agendaWhen")
            side.setTextFormat(Qt.TextFormat.RichText)
            colour = {"over": t["critical"], "caution": t["caution"]}.get(a.when_class, t["text2"])
            weight = "600" if a.when_class in ("over", "caution") else "400"
            urgent = (f'<span style="color: {t["critical"]}; background-color: {t["critical_bg"]}; font-weight: 600">&nbsp;Urgent&nbsp;</span><br>'
                      if a.urgent else "")
            side.setText(f'<p align="right" style="margin: 0">{urgent}<span style="color: {colour}; font-weight: {weight}">{esc(a.when)}</span></p>')
            side.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            rl.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
            rl.addWidget(words, 1)
            rl.addWidget(side, 0, Qt.AlignmentFlag.AlignTop)
            lay.addWidget(row)
            if a.discussed and a.item == answering:
                box = QLineEdit(objectName="answerBox")
                box.setPlaceholderText("What was said? Enter keeps it as a note; Esc skips")
                box.setToolTip(f"Kept as a note on {a.tip.splitlines()[0] if a.task else 'the agenda'}")
                box.installEventFilter(self)
                self.answer_box = box
                self._answer_item = a.item
                wrap = QWidget()
                wl = QHBoxLayout(wrap)
                wl.setContentsMargins(38, 0, 0, 8)
                wl.addWidget(box)
                lay.addWidget(wrap)
            elif a.item in said:
                words_said, where = said[a.item]
                note = QLabel(objectName="agendaSaid")
                note.setWordWrap(True)
                note.setTextFormat(Qt.TextFormat.RichText)
                note.setText(f'↳ {esc(words_said)} <span style="color: {t["text2"]}; font-size: {tokens.CAPTION}pt">&nbsp;{esc(where)}</span>')
                nl = QHBoxLayout()
                nl.setContentsMargins(38, 0, 0, 8)
                nl.addWidget(note)
                lay.addLayout(nl)
        # The add box (decision 527).
        add_row = QWidget(objectName="addRow")
        al = QHBoxLayout(add_row)
        al.setContentsMargins(8, 6, 0, 2)
        al.setSpacing(6)
        self.task_chip = QToolButton(objectName="addTask")
        self.task_chip.setText(f"{task_name}  ✕" if task_name else "")
        self.task_chip.setToolTip("The task the item is about: click to take it off")
        self.task_chip.setVisible(bool(task_name))
        self.task_chip.clicked.connect(lambda: self.add.emit("", "clear"))
        self.add_box = QLineEdit(objectName="addBox")
        self.add_box.setPlaceholderText(f"Add to {add_words}…  # picks a task")
        self.add_box.setClearButtonEnabled(True)
        self.add_box.installEventFilter(self)
        self.add_box.textEdited.connect(self._typed)
        al.addWidget(self.task_chip)
        al.addWidget(self.add_box, 1)
        lay.addWidget(add_row)

    def _typed(self, text: str) -> None:
        if "#" in text:
            self.add_box.setText(text.replace("#", "", 1))
            self.pick_task.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if watched is self.answer_box:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.answered.emit(self._answer_item, self.answer_box.text())
                    return True
                if key == Qt.Key.Key_Escape:
                    self.answered.emit(self._answer_item, "")
                    return True
            elif watched is self.add_box:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.add.emit(self.add_box.text(), None)
                    return True
                if key == Qt.Key.Key_Backspace and not self.add_box.text() and self.task_chip.isVisible():
                    self.add.emit("", "clear")
                    return True
                if key == Qt.Key.Key_Escape and self.add_box.text():
                    self.add_box.clear()
                    return True
        return super().eventFilter(watched, event)


# ---- the window ----
class QuickSummary(QWidget):
    """One window per DocRepo, kept and brought back (decision 518)."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.app, self.ctx = app, app.ctx
        self.setObjectName("browse")
        self.setStyleSheet(style_sheet() + window_css())
        self.setWindowTitle("Quick summary")
        self.resize(WIDTH, HEIGHT)
        self.css = summary_css()
        self.subject: Subject | None = None
        self.view: Summary | None = None
        #: Per subject, while the window's open: the lists shown in full, the sections folded or opened by hand, the items
        #: discussed here (still shown, ticked), and what was said (decision 526).
        self.more: dict[str, set[str]] = {}
        self.folds: dict[tuple[str, str], bool] = {}
        self.discussed: dict[str, list[AgendaRow]] = {}
        self.said: dict[int, tuple[str, str]] = {}
        self.answering: int | None = None
        #: The task picked with # in each agenda's add box, by the agenda's target (decision 527).
        self.add_task: dict[str, str] = {}
        self.agenda_bodies: dict[str, AgendaBody] = {}
        self._picking: str | None = None
        self.undo = None
        self.sections: dict[str, Expander] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QWidget(objectName="toolbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(6)
        # Each subject showing, as a chip with its ✕, before the box (decision 555).
        self.chips = QWidget(objectName="summaryChips")
        self.chips_lay = QHBoxLayout(self.chips)
        self.chips_lay.setContentsMargins(0, 0, 0, 0)
        self.chips_lay.setSpacing(4)
        self.box = QLineEdit(objectName="summaryBox")
        self.box.setPlaceholderText("A person, an agenda, a label or a tag")
        self.box.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.box.setMinimumHeight(34)
        self.box.textEdited.connect(self._typed)
        self.box.installEventFilter(self)
        self.pin_button = QToolButton(objectName="summaryPin")
        self.pin_button.setIcon(icon("pin"))
        self.pin_button.setCheckable(True)
        self.pin_button.setAutoRaise(True)
        self.pin_button.setToolTip("Pin it: first in the box's list (decision 534)")
        self.pin_button.clicked.connect(self.toggle_pin)
        self.copy_button = QPushButton(icon("copy"), "Copy")
        self.copy_button.setToolTip("Copy it as rich text and Markdown (Ctrl+Shift+C)")
        self.copy_button.clicked.connect(self.copy)
        self.page_button = QPushButton(icon("open"), "Open page")
        self.page_button.setToolTip("Its page in the browse tool")
        self.page_button.clicked.connect(self.open_page)
        tl.addWidget(self.chips)
        tl.addWidget(self.box, 1)
        tl.addWidget(self.pin_button)
        tl.addWidget(self.copy_button)
        tl.addWidget(self.page_button)
        lay.addWidget(top)

        self.stack = QStackedWidget()
        self.list = SubjectList()
        self.list.picked.connect(self._clicked)
        self.stack.addWidget(self.list)
        self.scroll = QScrollArea(objectName="summaryScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page = QWidget(objectName="summaryPage")
        self.page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.page_lay = QVBoxLayout(self.page)
        self.page_lay.setContentsMargins(0, 0, 0, 18)
        self.page_lay.setSpacing(0)
        self.header = fit_view(self.css, (MARGIN, 16, MARGIN, 12))
        self.header.anchorClicked.connect(self.on_link)
        self.header.link_menu = self.link_menu
        self.page_lay.addWidget(self.header)
        rule = QFrame(objectName="summaryRule")
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet(f"color: {tokens.LIGHT['stroke']}")
        self.page_lay.addWidget(rule)
        self.sections_lay = QVBoxLayout()
        self.sections_lay.setContentsMargins(0, 8, 0, 0)
        self.sections_lay.setSpacing(4)
        self.page_lay.addLayout(self.sections_lay)
        self.page_lay.addStretch(1)
        self.scroll.setWidget(self.page)
        self.stack.addWidget(self.scroll)
        lay.addWidget(self.stack, 1)

        foot = QWidget(objectName="toolbar")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(14, 6, 14, 6)
        self.message = QLabel(objectName="hint")
        self.undo_button = QPushButton("Undo")
        self.undo_button.hide()
        self.undo_button.clicked.connect(self.do_undo)
        fl.addWidget(self.message, 1)
        fl.addWidget(self.undo_button)
        lay.addWidget(foot)
        self._message_timer = QTimer(self, singleShot=True, interval=MESSAGE_MS, timeout=self.clear_message)
        self.picker = TaskPicker(self, self.ctx.model, none_entry=None)
        self.picker.picked.connect(self._task_picked)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.copy)
        QShortcut(QKeySequence("Ctrl+L"), self, self.focus_box)
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_box)
        QShortcut(QKeySequence("Ctrl+W"), self, self.hide)
        self._sync_buttons()

    # ---- opening ----
    def builder(self) -> Builder:
        return Builder(self.ctx.model(), self.today(), self.ctx.settings.me, self.ctx.conn, self.ctx.settings.quiet_days)

    def today(self) -> date:
        return self.ctx.now().date()

    def open_it(self, screen=None, key: str | None = None) -> None:
        """Show the window at the centre of the monitor: on ``key``'s summary, or with the cursor in the box and its list."""
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.x() + (area.width() - self.width()) // 2, area.y() + max(0, (area.height() - self.height()) // 4))
        bring_to_front(self)
        if key and self.show_key(key):
            return
        self.box.clear()
        self.show_list("")
        self.box.setFocus()

    def show_key(self, key: str) -> bool:
        s = summary.subject_of(self.ctx.model(), key, self.ctx.settings.me)
        if s is None:
            self.say("That's gone: it isn't a person, an agenda, a label or a tag any more.")
            return False
        self.show_subject(s)
        return True

    @property
    def agenda_body(self) -> AgendaBody | None:
        """The first agenda's body: where A goes."""
        return next(iter(self.agenda_bodies.values()), None)

    # ---- the box ----
    def focus_box(self) -> None:
        self.box.setFocus()
        self.box.selectAll()
        self.show_list("")

    def _typed(self, text: str) -> None:
        self.show_list(text)

    def show_list(self, text: str) -> None:
        """The box's list for what's typed (decision 519)."""
        b = self.builder()
        m = b.m
        rows: list[tuple[str, str, dict]] = []

        def row(s: Subject, number: str = "") -> tuple[str, str, dict]:
            words = {"name": s.name, "kind": summary.KIND_WORDS[s.kind], "count": b.count_line(s), "number": number,
                     "pinned": s.key in self.ctx.settings.summary_pins}
            if s.kind == summary.PERSON:
                from docrepo.detail import initials

                words["initials"] = initials(s.name)
            return s.kind, s.key, words

        if not text.strip():
            pinned, recent = summary.start_list(m, self.ctx.settings.me, self.ctx.settings.summary_pins, self.ctx.settings.summary_recent)
            n = 0
            for title, group in (("Pinned", pinned), ("Recent", recent)):
                if group:
                    rows.append(("head", "", {"title": title}))
                    for s in group:
                        n += 1
                        rows.append(row(s, str(n)))
            if not rows:
                rows.append(("head", "", {"title": "Type a person, an agenda or a label"}))
                rows += [row(s) for s in summary.subjects(m, self.ctx.settings.me)[:summary.START_MAX]]
        else:
            found = summary.matches(m, summary.subjects(m, self.ctx.settings.me), text.strip().lstrip("+"))
            for kind, title in ((summary.PERSON, "People"), (summary.AGENDA, "Agendas"), (summary.LABEL, "Labels"), (summary.TAG, "Tagged labels")):
                group = [s for s in found if s.kind == kind]
                if group:
                    rows.append(("head", "", {"title": title}))
                    rows += [row(s) for s in group]
            words = text.strip().lstrip("+").strip()
            if words and not words.startswith("@") and not any(s.name.lower() == words.lower() for s in found):
                rows.append(("head", "", {"title": "Nothing called that" if not found else "Or"}))
                rows.append(("new", words, {"name": f"New agenda “{words}”…", "kind": "a meeting task"}))
        if self.subject is not None and any(r[0] not in ("head", "new") for r in rows):
            rows.append(("head", "", {"title": f"Enter opens it · Ctrl+Enter adds it to {self.subject.name}"}))
        self.list.fill(rows)
        self.stack.setCurrentWidget(self.list)
        self._sync_buttons()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if watched is self.box and event.type() == QEvent.Type.KeyPress:
            key, text = event.key(), event.text()
            listing = self.stack.currentWidget() is self.list
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if not listing:
                    self.show_list(self.box.text())
                self.list.step(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and listing:
                picked = self.list.current()
                if picked:
                    self._picked(*picked, add=ctrl or self.box.text().strip().startswith("+"))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not listing and self.box.text().strip():
                self.show_list(self.box.text())
                return True
            if text.isdigit() and text != "0" and listing and not self.box.text().strip():
                picked = self.list.numbered(int(text))
                if picked:
                    self._picked(*picked, add=ctrl)
                    return True
            if key == Qt.Key.Key_Backspace and not self.box.text() and self.subject is not None:
                self.remove_part(self.subject.each()[-1].key)  # decision 555: the last chip off
                return True
            if key == Qt.Key.Key_Escape:
                if self.box.text():
                    self.box.clear()
                    if self.subject is not None:
                        self.back_to_summary()
                    else:
                        self.show_list("")
                elif self.subject is not None and listing:
                    self.back_to_summary()
                else:
                    self.hide()
                return True
        return super().eventFilter(watched, event)

    def back_to_summary(self) -> None:
        self.stack.setCurrentWidget(self.scroll)
        self._sync_buttons()

    def _clicked(self, kind: str, key: str) -> None:
        """A row clicked: Ctrl+click adds it to what's showing (decision 555)."""
        self._picked(kind, key, add=bool(QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier))

    def _picked(self, kind: str, key: str, add: bool = False) -> None:
        if kind == "new":
            self.new_agenda(key)
            return
        if add and self.subject is not None:
            picked = summary.subject_of(self.ctx.model(), key, self.ctx.settings.me)
            both = summary.combine([self.subject, picked]) if picked else None
            if both is not None:
                self.box.clear()
                self.show_subject(both)
                return
        self.box.clear()
        self.show_key(key)

    def remove_part(self, key: str) -> None:
        """A chip's ✕, or Backspace in the empty box: that subject off; with none left, the box's list."""
        if self.subject is None:
            return
        rest = summary.combine(p for p in self.subject.each() if p.key != key)
        if rest is None:
            self.subject, self.view = None, None
            self._show_chips()
            self.show_list(self.box.text())
            return
        self.show_subject(rest)

    def _show_chips(self) -> None:
        while self.chips_lay.count():
            w = self.chips_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for p in self.subject.each() if self.subject is not None else ():
            chip = QToolButton(objectName="summaryChip")
            chip.setText(f"{p.name}  ✕")
            chip.setToolTip(f"Take {p.name} off (Backspace takes the last one off)")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _c=False, k=p.key: self.remove_part(k))
            self.chips_lay.addWidget(chip)
        self.chips.setVisible(self.subject is not None)

    def new_agenda(self, words: str) -> None:
        """New agenda "…" (decision 528): New task, Meeting ticked, the words as its title; its agenda is then here."""
        browse = self.app.browse
        browse.open_capture(mode="new_task", content=words)
        capture = getattr(browse, "capture", None)
        if capture is not None:
            capture.n_meeting.setChecked(True)
        self.say(f"New task, with Meeting ticked: save it, and “{words}” is an agenda here.")

    # ---- the summary ----
    def show_subject(self, s: Subject) -> None:
        if self.subject is None or self.subject.key != s.key:
            self.answering, self.add_task = None, {}
        self.subject = s
        self._show_chips()
        st = self.ctx.settings
        if st.summary_recent[:1] != [s.key]:
            st.summary_recent = summary.remember(st.summary_recent, s.key)
            self._save_settings()
        self.render()
        self.stack.setCurrentWidget(self.scroll)
        self.scroll.verticalScrollBar().setValue(0)
        self._sync_buttons()

    def render(self) -> None:
        """Build the subject's summary again and draw it, keeping the scroll."""
        if self.subject is None:
            return
        at = self.scroll.verticalScrollBar().value()
        b = self.builder()
        s = summary.subject_of(b.m, self.subject.key, self.ctx.settings.me)
        if s is None:
            self.subject = None
            self.show_list("")
            return
        self.view = view = b.build(s, self.more.get(s.key, set()))
        gone = self.discussed.get(s.key, [])
        for agenda in (x for x in view.sections if x.agenda is not None):
            open_ids = {a.item for a in agenda.agenda or ()}
            shown = [a for a in gone if a.item not in open_ids and a.target == agenda.add_to]
            agenda.agenda = [*(agenda.agenda or ()), *shown]
            if shown and not open_ids:
                agenda.extra = "all discussed"
        self.header.setHtml(header_html(view))
        for g in self.sections.values():
            g.setParent(None)
            g.deleteLater()
        self.sections = {}
        self.agenda_bodies = {}
        for sec in view.sections:
            self.sections[sec.key] = g = self._section(sec)
            self.sections_lay.addWidget(g)
        self._sync_buttons()
        QTimer.singleShot(0, self.scroll, lambda: self.scroll.verticalScrollBar().setValue(at))  # with the scroll as context: gone with it

    def _section(self, sec: Section) -> Expander:
        key = (self.subject.key, sec.key) if self.subject else ("", sec.key)
        if sec.agenda is not None:
            m, target = self.ctx.model(), sec.add_to or ""
            picked = self.add_task.get(target)
            body = AgendaBody(sec.agenda, self.answering, self.said, self._add_words(target), MARGIN,
                              m.task(picked).title if picked and picked in m.tasks else "")
            body.ticked.connect(self.tick)
            body.answered.connect(self.answer)
            body.add.connect(lambda words, task, target=target: self.add_item(words, task, target))
            body.pick_task.connect(lambda target=target: self.pick_task(target))
            g = Expander(sec.key, sec.title, self.css, MARGIN, body=body)
            self.agenda_bodies[target] = body
            if body.answer_box is not None:
                QTimer.singleShot(0, body.answer_box, body.answer_box.setFocus)
        else:
            g = Expander(sec.key, sec.title, self.css, MARGIN)
            g.body.anchorClicked.connect(self.on_link)
            g.body.link_menu = self.link_menu
        action = f'<a href="{esc(sec.action[0])}">{esc(sec.action[1])}</a>' if sec.action else ""
        g.set_content(section_head(esc(head_words(sec)), action, raw=True), None if sec.agenda is not None else sec.body, head_words(sec))
        g.summary.anchorClicked.connect(self.on_link)
        g.summary.link_menu = self.link_menu
        g.set_open(not self.folds.get(key, sec.folded))
        g.toggled.connect(lambda k, is_open, key=key: self.folds.__setitem__(key, not is_open))
        return g

    def _add_words(self, target: str) -> str:
        """Whose agenda an add box adds to: "Mike's agenda", "Control room's agenda"."""
        m = self.ctx.model()
        if target in m.people:
            name = m.person_name(target)
            return f"{name.split()[0] if name.split() else name}'s agenda"
        return f"{m.task(target).title}'s agenda" if target in m.tasks else "the agenda"

    # ---- the agenda (decisions 526 and 527) ----
    def tick(self, item: int, discussed: bool) -> None:
        ctx = self.ctx
        if not discussed:
            self._reopen(item)
            return
        rows = [a for sec in (self.view.sections if self.view else ()) for a in sec.agenda or ()]
        row = next((a for a in rows if a.item == item), None)
        try:
            edits.discuss_agenda_item(ctx.conn, ctx.data_root, ctx.fs, item, ctx.now())
        except Exception as e:  # noqa: BLE001 - said in the window, as the browse tool does
            self.say(f"It couldn't be marked discussed: {e}", error=True)
            return
        if row is not None and self.subject is not None:
            row.discussed = True
            self.discussed.setdefault(self.subject.key, []).append(row)
        self.answering = item
        self.say("Discussed. Type the answer, or Esc.", undo=lambda: self._reopen(item))
        self.render()

    def _reopen(self, item: int) -> None:
        ctx = self.ctx
        try:
            edits.reopen_agenda_item(ctx.conn, ctx.data_root, ctx.fs, item, ctx.now())
        except Exception as e:  # noqa: BLE001
            self.say(f"It couldn't be opened again: {e}", error=True)
            return
        for rows in self.discussed.values():
            rows[:] = [a for a in rows if a.item != item]
        self.said.pop(item, None)
        if self.answering == item:
            self.answering = None
        self.say("Back on the agenda.")
        self.render()

    def answer(self, item: int, words: str) -> None:
        ctx = self.ctx
        self.answering = None
        if not words.strip():
            self.say("Discussed, with no answer kept.", undo=lambda: self._reopen(item))
            self.render()
            return
        try:
            r = save.save_answer(ctx.conn, ctx.data_root, ctx.fs, ctx.settings, item, words, ctx.now())
        except Exception as e:  # noqa: BLE001
            self.say(f"The answer wasn't kept: {e}", error=True)
            self.render()
            return
        m = ctx.model()
        where = f"a note on {m.task(r.noted_on).title}" if r.noted_on else (
            f"a note on {m.task(r.picked_task).title}" if r.picked_task and r.picked_task in m.tasks else "in Unfiled")
        self.said[item] = (" ".join(words.split()), where)
        self.say(f"Kept as {where}.", problems=r.problems)
        self.render()

    def pick_task(self, target: str = "") -> None:
        """# in an agenda's add box: the task picker under it (decision 527)."""
        self._picking = target or next(iter(self.agenda_bodies), None)
        body = self.agenda_bodies.get(self._picking or "")
        at = body.add_box.mapToGlobal(QPoint(0, body.add_box.height())) if body is not None else self.mapToGlobal(QPoint(40, 120))
        self.picker.popup(at)

    def _refocus(self, target: str, text: str) -> None:
        body = self.agenda_bodies.get(target)
        if body is not None:
            body.add_box.setText(text)
            body.add_box.setFocus()

    def _task_picked(self, task_id: str | None) -> None:
        target = self._picking or next(iter(self.agenda_bodies), "")
        if task_id and target:
            self.add_task[target] = task_id
            body = self.agenda_bodies.get(target)
            text = body.add_box.text() if body is not None else ""
            self.render()
            self._refocus(target, text)

    def add_item(self, words: str, task: object, target: str = "") -> None:
        target = target or next(iter(self.agenda_bodies), "")
        if task == "clear":
            self.add_task.pop(target, None)
            body = self.agenda_bodies.get(target)
            text = body.add_box.text() if body is not None else ""
            self.render()
            self._refocus(target, text)
            return
        picked = self.add_task.get(target)
        if not target or not (words.strip() or picked):
            return
        ctx = self.ctx
        try:
            out = edits.add_agenda_item(ctx.conn, ctx.data_root, ctx.fs, target, picked, words, ctx.now())
        except Exception as e:  # noqa: BLE001
            self.say(f"It wasn't added: {e}", error=True)
            return
        self.add_task.pop(target, None)
        self.say(out.message, problems=out.problems)
        self.render()
        QTimer.singleShot(0, self, lambda: self._refocus(target, ""))

    # ---- the commands ----
    def toggle_pin(self) -> None:
        if self.subject is None:
            return
        st = self.ctx.settings
        key = self.subject.key
        st.summary_pins = [k for k in st.summary_pins if k != key] if key in st.summary_pins else [key, *st.summary_pins]
        self._save_settings()
        self.say("Pinned: first in the box's list." if key in st.summary_pins else "Unpinned.")
        self._sync_buttons()

    def copy(self) -> None:
        if self.view is None:
            return
        data = QMimeData()
        data.setText(self.view.markdown)
        data.setHtml(self.view.html)
        QGuiApplication.clipboard().setMimeData(data)
        self.say("Copied, as rich text and Markdown.")

    def open_page(self) -> None:
        """The subject's page in the browse tool."""
        s, browse = self.subject, self.app.browse
        if s is None or s.kind == summary.MANY:
            return
        if s.kind == summary.AGENDA:
            browse.show_agenda(s.ref)
        elif s.kind == summary.PERSON:
            browse.set_view("people")
            browse.select("person", s.ref, update_list=True)
        elif s.kind == summary.TAG:
            browse.view = "tagged"
            browse.select("tagged", s.ref, update_list=True)
        else:
            browse.set_view("labels")
            browse.select("label", s.ref, update_list=True)
        self.app.show_browse()

    def on_link(self, url: QUrl) -> None:
        kind, _, rest = url.toString().partition(":")
        browse = self.app.browse
        if kind == "more":
            if self.subject is not None:
                self.more.setdefault(self.subject.key, set()).add(rest)
                self.render()
            return
        if kind == "state":  # a task tile's circle (release 5.138, decision 564): the state menu, drawn again after
            browse.popup_state_menu(rest, QCursor.pos(), after=self.render)
            return
        if kind == "task":
            self.app.show_browse(None, rest)
        elif kind == "capture":
            browse.go_capture(rest)
            self.app.show_browse()
        elif kind == "conv":
            task, _, conv = rest.partition("/")
            conversation_page.go(browse, task, conv)
            self.app.show_browse()
        elif kind == "activity":
            window = summary.activity_window(url.toString())
            if window is None:
                return
            what, ref, since = window
            people = [p.ref for p in self.subject.each() if p.kind == summary.PERSON] if self.subject else []
            labels = [p.ref for p in self.subject.each() if p.kind == summary.LABEL] if self.subject else []
            browse.act.update({"win": "range", "from": since.isoformat(), "to": self.today().isoformat(),
                               "people": people or ([ref] if what == summary.PERSON else []),
                               "labels": labels or ([unquote(ref)] if what == summary.LABEL else [])})
            browse.set_view("activity")
            self.app.show_browse()

    def link_menu(self, href: str, at: QPoint) -> bool:
        """A right-click on a task's link or circle (release 5.138, the task tile plan's decision 577): the tile's menu, as in
        the browse window; the summary is drawn again after it."""
        from docrepo.ui import task_tile as tile_ui

        kind, _, rest = href.partition(":")
        if kind not in ("task", "state") or rest not in self.app.browse.model().tasks:
            return False
        menu = tile_ui.tile_menu(self.app.browse, rest, self)
        if menu is None:
            return False
        try:
            menu.exec(at)
        finally:
            menu.deleteLater()
        self.render()
        return True

    # ---- messages ----
    def say(self, text: str, error: bool = False, undo=None, problems: list[str] | None = None) -> None:
        if problems:
            text += " " + " ".join(problems)
        self.message.setText(text)
        self.message.setProperty("error", error)
        self.undo = undo
        self.undo_button.setVisible(undo is not None)
        self._message_timer.start()

    def clear_message(self) -> None:
        self.message.setText("")
        self.undo = None
        self.undo_button.hide()

    def do_undo(self) -> None:
        undo, self.undo = self.undo, None
        self.undo_button.hide()
        if undo is not None:
            undo()

    def _save_settings(self) -> None:
        try:
            self.ctx.settings.save(self.ctx.fs, self.ctx.data_root)
        except OSError as e:
            log.warning("quick summary: settings not saved (%s)", type(e).__name__)

    def _sync_buttons(self) -> None:
        on = self.subject is not None and self.stack.currentWidget() is self.scroll
        for b in (self.copy_button, self.page_button, self.pin_button):
            b.setEnabled(on)
        self.page_button.setEnabled(on and self.subject.kind != summary.MANY)  # several have no one page
        self.pin_button.setChecked(bool(self.subject) and self.subject.key in self.ctx.settings.summary_pins)
        self.pin_button.setToolTip("Unpin it" if self.pin_button.isChecked() else "Pin it: first in the box's list")
        self.setWindowTitle(f"{self.subject.name}: quick summary" if self.subject and on else "Quick summary")

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """/ goes to the box, A to the agenda's add box, Esc closes (the box and the lines have their own keys first)."""
        text = event.text()
        if text == "/":
            self.focus_box()
            return
        body = self.agenda_body
        if text.lower() == "a" and not event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier and body is not None:
            for key, g in self.sections.items():
                if key == "agenda" or key.startswith("agenda:"):
                    g.set_open(True)
                    break
            body.add_box.setFocus()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

