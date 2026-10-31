"""The Task view (releases 5.34 and 5.35; the design workspace's task overview design, decisions 156 to 167): a window
of its own for one task, built so any of its documents can be found and opened in seconds from the keyboard.

- **The header:** the task's path, title, state, labels, due date, people and subtasks' progress, its current status
  with its age, and the latest note, update or email. The command bar is the task page's.
- **The outline (left):** Overview, then the task and its subtasks with how many files each holds. Picking one narrows
  everything to that branch.
- **The list (middle):** the search box has the cursor; what's typed searches the task's files, emails, notes and
  updates, and subtasks as you type, with the best match already chosen, so Enter opens it. The kinds, with their
  counts, Type, Date, From, and View (group by, sort, density) narrow and arrange it; typed filters (``type:pdf``)
  turn into chips. With nothing typed, Overview shows Pinned, Recent and Latest updates.
- **The preview (right):** the chosen record's facts and text, the lines that matched while searching, and its actions.
- **The Notes page tab (release 5.37, decisions 239 to 244):** the page of the task picked in the outline, in the frame
  it has on the task page (``TaskPane``, which the browse window's notes handlers serve), in place of the list. The
  preview stays hidden until a caption or file line is clicked. What's typed in the box shows results, and Esc comes back.

The words come from ``docrepo.task_view_pages`` and the search from ``docrepo.finder``, both without Qt. A file's
extracted text, the search's second tier, is read once and searched on a worker thread after typing pauses; Open runs
on one too (``docrepo.opener``), so a slow LAN drive never freezes the window.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QByteArray, QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFontMetrics, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabBar, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from docrepo import db, finder, opener, overview, pins
from docrepo import task_view_pages as pages
from docrepo.captures import capture_folder
from docrepo.overview import KIND_NAMES, KINDS, SOURCE_NAMES, SOURCES, TYPE_NAMES, TYPE_ORDER, Record
from docrepo.search import extracted_text
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.page_view import PageView
from docrepo.ui.result_list import ResultList, Row
from docrepo.ui.style import page_css
from docrepo.ui.task_pane import TaskPane

log = logging.getLogger(__name__)

GEOMETRY_KEY = "task_view_geometry"
FOOT = "Enter opens · Ctrl+Enter shows in File Explorer · Ctrl+Shift+C copies the path · P pins · Esc clears · Ctrl+O another task · F1 every key"
PAGE_FOOT = "It saves as you type · Click a caption or file line to see it here · Ctrl+Space shows or hides the preview · Esc goes to the search box · F1 every key"
KIND_ORDER = ("all", *KINDS)
#: The tab that shows the notes page (decision 239): it's in ``kind`` like the others, and no search gets it.
PAGE = "page"
TABS = (*KIND_ORDER, PAGE)
TAB_NAMES = {**KIND_NAMES, PAGE: "Notes page"}
#: The most the Notes frame's heading takes up, in pixels, for a subtask's long title.
PAGE_TITLE_WIDTH = 320
#: Each kind's grouping when nothing is typed (decision 163: files by date added, newest first).
DEFAULT_GROUP = {"file": "date", "email": "date", "note": "date"}
GROUPS = (("date", "Date added"), ("task", "Subtask"), ("type", "Type"), ("source", "Source"), ("none", "None"))
SORTS = (("", "Best match, or newest first"), ("old", "Oldest first"), ("name", "Name"), ("used", "Last opened"), ("type", "Type"))
#: How many of each kind All shows while searching, before Show all.
CAPS = {"file": 8, "email": 5, "note": 5, "task": 5}
NARROW, WIDE = 900, 1100
PANES = {"outline": 232, "preview": 380}

_QSS = """
QWidget#tvBand {{ background: {content}; border-bottom: 1px solid {stroke}; }}
QTreeWidget#tvOutline {{ background: {base}; border: none; border-right: 1px solid {stroke}; outline: 0; }}
QTreeWidget#tvOutline::item {{ height: 28px; padding-right: 8px; }}
QTreeWidget#tvOutline::item:selected {{ background: {selected}; color: {text}; }}
QTreeWidget#tvOutline::item:hover:!selected {{ background: {hover}; }}
QTabBar#tvKinds::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; padding: 6px 9px 7px 9px; color: {text}; }}
QTabBar#tvKinds::tab:selected {{ border-bottom: 2px solid {accent}; font-weight: 600; }}
QTabBar#tvKinds::tab:hover:!selected {{ background: {hover}; }}
QLabel#tvCount, QLabel#tvFoot {{ color: {text2}; }}
QWidget#tvFootBar {{ background: {base}; border-top: 1px solid {stroke}; }}
QPushButton#tvChip {{ background: {selected}; border: none; border-radius: 10px; padding: 2px 10px; min-height: 18px; }}
QPushButton#tvChip:hover {{ background: {pressed}; }}
QLineEdit#tvSearch {{ padding: 7px 10px; border-bottom: 2px solid {accent}; }}
QListView#taskViewList {{ background: {content}; border: none; }}
QWidget#tvPreview {{ background: {content}; border-left: 1px solid {stroke}; }}
QTextBrowser#tvPage {{ background: transparent; border: none; }}
"""


class _Done(QObject):
    done = Signal(int, object)


class _Job(QRunnable):
    """A piece of work off the UI thread; ``done`` brings its result (or the exception) back with its token."""

    def __init__(self, token: int, work: Callable[[], object]) -> None:
        super().__init__()
        self.token, self.work, self.signals = token, work, _Done()

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as e:  # noqa: BLE001 - brought back to the window, which says so
            result = e
        self.signals.done.emit(self.token, result)


def _page() -> PageView:
    view = PageView()
    view.setObjectName("tvPage")
    view.setOpenLinks(False)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.document().setDefaultStyleSheet(page_css())
    return view


class TaskView(QWidget):
    """One task's Task view. ``browse`` is the browse window, whose model, commands and capture window it uses."""

    def __init__(self, browse, task_id: str) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.browse, self.ctx, self.task_id = browse, browse.ctx, task_id
        self.setObjectName("browse")
        self.setStyleSheet(_QSS.format(**tokens.LIGHT))
        self.setAcceptDrops(True)
        #: Opens a file in its own program. Tests replace it.
        self.starter: Callable[[str], None] | None = None
        #: Whether a file is there; on a LAN path it can take seconds, so it's only asked on a worker thread. Tests replace it.
        self.exists: Callable[[Path], bool] = Path.exists
        # What's chosen
        self.scope = task_id
        self.kind = "all"
        self.query = ""
        self.filters = finder.Filters()
        self.group: str | None = None
        self.sort: str | None = None
        self.compact = False
        self.show_closed = False
        self.preview_on = True
        self.folded: set[str] = set()
        self.missing: set[str] = set()
        # The Notes page tab: its pane (made the first time it's shown), what's clicked on it, whether its preview is on,
        # and whether a search begun there comes back to it.
        self.pane: TaskPane | None = None
        self.page_record: Record | None = None
        self.page_preview = False
        self.back_to_page = False
        # What's known
        self.stale = False                            # a notes page was saved: the records are read again when next needed
        self.records: list[Record] = []
        self.texts: dict[str, str] | None = None      # each file's extracted text, as it is
        self.folded_texts: dict[str, str] = {}        # and folded, for the second tier
        self.second: tuple[str, list[finder.Hit]] | None = None
        self.second_busy = False
        self.recent_snap: tuple[str, list[overview.Recent]] | None = None
        self.pinned: list[str] = []
        self.used: list[tuple[str, str, str]] = []
        self.last_used: dict[str, str] = {}
        self.counts: dict[str, int] = dict.fromkeys(KIND_ORDER, 0)
        self.searched_ms = 0.0
        self._token = 0
        self._jobs: list[_Job] = []
        self._build()
        self._keys()
        self._second_timer = QTimer(self, singleShot=True, interval=150, timeout=self._start_second)
        self._preview_timer = QTimer(self, singleShot=True, interval=60, timeout=self.show_preview)
        self._foot_timer = QTimer(self, singleShot=True, interval=6000, timeout=lambda: self.say(""))
        self._head_timer = QTimer(self, singleShot=True, interval=0, timeout=self._fit_head)
        self.reload()
        self._restore_geometry()

    # ================= building it =================
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # The header band: the path and the commands, then the task at a glance.
        band = QWidget(objectName="tvBand")
        bv = QVBoxLayout(band)
        bv.setContentsMargins(16, 8, 16, 10)
        bv.setSpacing(2)
        top = QHBoxLayout()
        self.crumbs = QLabel(textFormat=Qt.TextFormat.RichText)
        self.crumbs.linkActivated.connect(lambda href: self.on_link(QUrl(href)))
        top.addWidget(self.crumbs)
        top.addStretch(1)
        self.commands = QHBoxLayout()
        self.commands.setSpacing(2)
        top.addLayout(self.commands)
        bv.addLayout(top)
        self.head = _page()
        self.head.anchorClicked.connect(self.on_link)
        self.head.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.head.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bv.addWidget(self.head)
        outer.addWidget(band)
        # The body: the outline, the list and the preview.
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.outline = QTreeWidget(objectName="tvOutline")
        self.outline.setHeaderHidden(True)
        self.outline.setColumnCount(2)
        self.outline.setIndentation(14)
        self.outline.setRootIsDecorated(True)
        self.outline.setAccessibleName("Overview and subtasks")
        self.outline.itemClicked.connect(lambda item, _c: self._outline_picked(item))
        self.outline.itemActivated.connect(lambda item, _c: self._outline_picked(item))
        self.split.addWidget(self.outline)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(16, 12, 16, 0)
        mv.setSpacing(6)
        self.box = QLineEdit(objectName="tvSearch")
        self.box.setAccessibleName("Search this task")
        self.box.textEdited.connect(self._typed)
        self.box.installEventFilter(self)
        mv.addWidget(self.box)
        kinds = QHBoxLayout()
        kinds.setSpacing(6)
        self.kinds = QTabBar(objectName="tvKinds")
        self.kinds.setDrawBase(False)
        self.kinds.setExpanding(False)
        for i, k in enumerate(TABS):
            self.kinds.addTab(TAB_NAMES[k])
            self.kinds.setTabToolTip(i, f"{TAB_NAMES[k]} (Ctrl+{i + 1})")
        self.kinds.currentChanged.connect(lambda i: self.set_kind(TABS[i]))
        kinds.addWidget(self.kinds)
        kinds.addStretch(1)
        mv.addLayout(kinds)
        self.view_menu = QMenu(self)
        self.view_menu.aboutToShow.connect(self._fill_view_menu)
        self.view_button = self._menu_button("View", self.view_menu, "Group by, sort and density")
        self.preview_button = QToolButton(checkable=True, checked=True)
        self.preview_button.setIcon(icon("sidebar"))
        self.preview_button.setToolTip("Show or hide the preview (Space in the list, Ctrl+Space anywhere)")
        self.preview_button.setAccessibleName("Preview")
        self.preview_button.toggled.connect(self.set_preview)
        kinds.addWidget(self.preview_button)  # up here, so it's in the same place on the Notes page, which has no row below
        self.filter_bar = QWidget()
        row = QHBoxLayout(self.filter_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.type_menu, self.date_menu, self.from_menu = QMenu(self), QMenu(self), QMenu(self)
        self.type_menu.aboutToShow.connect(self._fill_type_menu)
        self.date_menu.aboutToShow.connect(self._fill_date_menu)
        self.from_menu.aboutToShow.connect(self._fill_from_menu)
        self.type_button = self._menu_button("Type", self.type_menu, "File types")
        self.date_button = self._menu_button("Date", self.date_menu, "When it came")
        self.from_button = self._menu_button("From", self.from_menu, "Where files came from, and who sent the emails")
        for b in (self.type_button, self.date_button, self.from_button):
            row.addWidget(b)
        self.count = QLabel(objectName="tvCount")
        self.count.setAccessibleName("Results")
        self.count.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # never widens the column
        self.count.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.count, 1)
        row.addSpacing(8)
        row.addWidget(self.view_button)
        mv.addWidget(self.filter_bar)
        self.chips = QWidget()
        self.chips.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.chip_row = QHBoxLayout(self.chips)
        self.chip_row.setContentsMargins(0, 0, 0, 0)
        self.chip_row.setSpacing(4)
        mv.addWidget(self.chips)
        self.stack = QStackedWidget()
        self.list = ResultList(self.browse.today())
        self.list.chosen.connect(lambda _r: self._preview_timer.start())
        self.list.activated_row.connect(lambda r: self.act("open", r))
        self.list.action.connect(lambda r, name: self.act(name, r))
        self.list.folded.connect(self._fold)
        self.list.installEventFilter(self)
        self.stack.addWidget(self.list)
        self.empty = _page()
        self.empty.anchorClicked.connect(self.on_link)
        self.stack.addWidget(self.empty)
        mv.addWidget(self.stack, 1)
        self.split.addWidget(mid)
        self.preview = QWidget(objectName="tvPreview")
        pv = QVBoxLayout(self.preview)
        pv.setContentsMargins(16, 12, 12, 8)
        pv.setSpacing(8)
        self.preview_actions = QHBoxLayout()
        self.preview_actions.setSpacing(6)
        # Four buttons made once, labelled for each record and hidden when it has fewer actions, so nothing is rebuilt
        # as the choice moves.
        self.preview_buttons: list[QPushButton] = []
        for _ in range(4):
            b = QPushButton()
            b.clicked.connect(lambda _=False, b=b: self.act(b.property("act")))
            b.hide()
            self.preview_actions.addWidget(b)
            self.preview_buttons.append(b)
        self.preview_actions.addStretch(1)
        pv.addLayout(self.preview_actions)
        self.preview_page = _page()
        self.preview_page.setAccessibleName("Preview")
        self.preview_page.anchorClicked.connect(self.on_link)
        pv.addWidget(self.preview_page, 1)
        self.split.addWidget(self.preview)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([PANES["outline"], 700, PANES["preview"]])
        outer.addWidget(self.split, 1)
        foot = QWidget(objectName="tvFootBar")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(16, 5, 16, 5)
        self.foot = QLabel(FOOT, objectName="tvFoot")
        fh.addWidget(self.foot)
        outer.addWidget(foot)

    def _menu_button(self, label: str, menu: QMenu, tip: str) -> QPushButton:
        b = QPushButton(label, objectName="" if LOOK.classic else "subtle")
        b.setMenu(menu)
        b.setToolTip(tip)
        if not LOOK.classic:
            b.setProperty("menu", True)
        return b

    def _commands(self) -> None:
        """The task page's commands (release 5.21), plus Task page, which opens the task in the browse tool."""
        while self.commands.count():
            w = self.commands.takeAt(0).widget()
            if w:
                w.deleteLater()
        b = self.browse
        t = self.model().task(self.task_id)

        def button(label: str, run: Callable[[], None] | None, tip: str, name: str, menu: QMenu | None = None) -> QPushButton:
            btn = QPushButton(label if label else "", objectName="subtle" if not LOOK.classic else "")
            btn.setIcon(icon(name))
            btn.setToolTip(tip)
            if menu is not None:
                btn.setMenu(menu)
            elif run is not None:
                btn.clicked.connect(lambda _=False: run())
            self.commands.addWidget(btn)
            return btn

        tid = self.task_id
        button("Note", lambda: b.open_capture(task=tid, mode="note"), "A note on this task (N, or Alt+N from the search box)", "note")
        button("Update", lambda: b.open_capture(task=tid, mode="update"), "Update its state, status or dates (U)", "update")
        add_to = QMenu(self)
        add_to.addAction(icon("sun"), "Today\tD", lambda: self.command("today"))
        add_to.addAction("An agenda…\tA", lambda: self.command("agenda"))
        button("Add to", None, "Put it on Today (D) or an agenda (A)", "agenda", add_to)
        button("Edit", lambda: b.edit_task(tid), "Edit task (E)", "edit")
        button("Task page", self.open_task_page, "Open it in the browse tool: its status log and Details, with its notes page", "open")
        more = QMenu(self)
        more.addAction(icon("add"), "New subtask\tT", lambda: self.command("new_task"))
        more.addAction(icon("copy"), "Copy prompt", lambda: b.copy_prompt(tid))
        more.addAction(icon("folder"), "Open folder", lambda: b.reveal(self.ctx.data_root / "Tasks" / tid))
        m = button("", None, "More: New subtask, Copy prompt, Open folder", "more", more)
        m.setAccessibleName("More")
        if t.discarded:
            for i in range(self.commands.count()):
                self.commands.itemAt(i).widget().setEnabled(False)

    def _keys(self) -> None:
        def key(seq: str, run: Callable[[], None]) -> None:
            QShortcut(QKeySequence(seq), self, run)

        key("Ctrl+F", self.focus_box)
        key("/", self.focus_box)
        key("Ctrl+O", self.go_to_task)
        key("Alt+Up", self.go_to_parent)
        key("Ctrl+Space", lambda: self.set_preview(not self.preview_wanted()))
        key("F6", lambda: self.cycle_panes(1))
        key("Shift+F6", lambda: self.cycle_panes(-1))
        key("Ctrl+W", self.close)
        key("F1", self.browse.show_keys)
        key("F5", self.reload)
        key("Ctrl+K", self.open_palette)
        key("Ctrl+Backspace", self.clear_filters)
        for i, k in enumerate(TABS):  # in the notes page, Ctrl+1 stays the checklist key: RichEdit takes it first
            key(f"Ctrl+{i + 1}", lambda k=k: self.set_kind(k))
        key("P", lambda: self.act("pin"))
        key("Alt+P", lambda: self.act("pin"))
        key("Alt+Shift+Up", lambda: self.move_pin(-1))
        key("Alt+Shift+Down", lambda: self.move_pin(1))
        for letter, mode in (("N", "note"), ("U", "update"), ("T", "new_task"), ("A", "agenda"), ("D", "today"), ("E", "edit"), ("M", "meeting")):
            key(letter, lambda mode=mode: self.command(mode))
            key(f"Alt+{letter}", lambda mode=mode: self.command(mode))

    # ================= data =================
    def model(self):
        return self.browse.model()

    @property
    def conn(self):
        return self.ctx.conn

    def today(self):
        return self.browse.today()

    def reload(self) -> None:
        """Read the task's records again (when the window opens, and whenever DocRepo's data changes)."""
        m = self.model()
        if self.task_id not in m.tasks:
            self.close()
            return
        start = time.perf_counter()
        self.read_records()
        if self.scope not in overview.family(m, self.task_id):
            self.scope = self.task_id
        t = m.task(self.task_id)
        self.setWindowTitle(f"{t.title} – Task view")
        self.box.setPlaceholderText(f"Search {t.title}: files, emails, notes and updates")
        self._commands()
        self.render_head()
        self.render_outline()
        self.refresh(keep=True)
        log.info("task view %s: %d records in %.0f ms", self.task_id, len(self.records), (time.perf_counter() - start) * 1000)

    def read_records(self) -> None:
        m = self.model()
        texts = overview.capture_texts(self.conn, [c.id for c in m.live_captures()])
        self.records = overview.build(m, self.ctx.data_root, self.task_id, texts)
        self.by_key = {(r.kind, r.id): r for r in self.records}
        files = [r.id for r in self.records if r.kind == "file"]
        self.pinned = pins.pins_of(self.conn, self.task_id)
        self.used = pins.uses_of(self.conn, files)
        self.last_used = pins.last_uses(self.conn)
        self.texts, self.folded_texts, self.second, self.recent_snap = None, {}, None, None
        if self.page_record is not None:
            self.page_record = self.by_key.get((self.page_record.kind, self.page_record.id))
        self.stale = False

    def load_texts(self) -> None:
        """The files' extracted text, read once from the search index, for the second tier and the preview."""
        if self.texts is None:
            self.texts = overview.file_texts(self.conn, self.model(), [r.id for r in self.records if r.kind == "file"])
            self.folded_texts = {k: overview.fold(v) for k, v in self.texts.items()}

    def text_of(self, r: Record) -> str:
        if r.kind != "file":
            return r.text
        if self.texts is not None and r.id in self.texts:
            return self.texts[r.id]
        return extracted_text(self.ctx.data_root, r.id)

    def email_file(self, r: Record) -> str:
        """An email's .msg file, in its capture's folder, when it's there."""
        c = self.model().captures.get(r.capture)
        if c is None:
            return ""
        path = capture_folder(self.ctx.data_root, c.id, c.saved) / "email.msg"
        return str(path) if path.is_file() else ""

    def bonus(self, r: Record) -> float:
        """Ties between matches of about the same quality: a pinned file, one opened in the last week, the newer."""
        b = 0.0
        if r.kind == "file" and r.id in self.pinned:
            b += 1.0
        used = self.last_used.get(r.id)
        if used and (self.today() - date.fromisoformat(used[:10])).days <= 7:
            b += 0.8
        age = (self.today() - date.fromisoformat(r.day)).days
        return b + max(0.0, 0.5 - age / 730)

    def in_scope(self) -> list[Record]:
        m = self.model()
        return [r for r in self.records if overview.in_scope(m, r, self.scope, self.task_id)]

    def keep(self, r: Record) -> bool:
        return self.filters.keep(r, pinned=lambda d: d in self.pinned, missing=lambda d: d in self.missing)

    # ================= the header and the outline =================
    def render_head(self) -> None:
        m = self.model()
        t = m.task(self.task_id)
        self.crumbs.setText(f"<style>{page_css()}</style>{pages.crumbs(m, t)}")
        self.head.setHtml(pages.header(m, t, self.records, self.today(), self.ctx.settings.me))
        self._fit_head()

    def _fit_head(self) -> None:
        doc = self.head.document()
        doc.setTextWidth(max(200, self.head.viewport().width()))
        self.head.setFixedHeight(int(doc.size().height()) + 4)

    def render_outline(self) -> None:
        m = self.model()
        fam = overview.family(m, self.task_id)
        files = {}
        for r in self.records:
            if r.kind == "file":
                files[r.task] = files.get(r.task, 0) + 1

        def branch_count(tid: str) -> int:
            return sum(files.get(x, 0) for x in [tid, *m.descendants_of(tid)] if x in fam)

        self.outline.blockSignals(True)
        self.outline.clear()
        over = QTreeWidgetItem(["Overview", ""])
        over.setIcon(0, icon("tasks"))
        over.setData(0, Qt.ItemDataRole.UserRole, "overview")
        self.outline.addTopLevelItem(over)
        heading = QTreeWidgetItem(["Subtasks", ""])
        heading.setFlags(Qt.ItemFlag.NoItemFlags)
        f = heading.font(0)
        f.setPointSizeF(tokens.CAPTION)
        f.setBold(True)
        heading.setFont(0, f)
        self.outline.addTopLevelItem(heading)
        closed = 0

        def add(tid: str, parent, depth: int) -> QTreeWidgetItem:
            nonlocal closed
            t = m.task(tid)
            item = QTreeWidgetItem(["Whole task" if depth == 0 else t.title, str(branch_count(tid))])
            item.setData(0, Qt.ItemDataRole.UserRole, tid)
            item.setToolTip(0, t.title)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(1, QColor(tokens.LIGHT["text2"]))
            if t.state == "Closed" and depth:
                item.setForeground(0, QColor(tokens.LIGHT["text2"]))
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else self.outline.addTopLevelItem)(item)
            for child in m.children_of(tid):
                if child not in fam:
                    continue
                if m.task(child).state == "Closed" and not self.show_closed:
                    closed += 1
                    continue
                add(child, item, depth + 1)
            return item

        root = add(self.task_id, None, 0)
        root.setExpanded(True)
        if closed or self.show_closed:
            more = QTreeWidgetItem([("Hide" if self.show_closed else "Show") + (f" {closed} closed" if closed else " closed"), ""])
            more.setData(0, Qt.ItemDataRole.UserRole, "closed")
            more.setForeground(0, QColor(tokens.LIGHT["accent"]))
            self.outline.addTopLevelItem(more)
        self.outline.header().setStretchLastSection(False)
        self.outline.header().setSectionResizeMode(0, self.outline.header().ResizeMode.Stretch)
        self.outline.header().setSectionResizeMode(1, self.outline.header().ResizeMode.ResizeToContents)
        self._select_outline()
        self.outline.blockSignals(False)

    def _select_outline(self) -> None:
        want = "overview" if self.is_overview() else self.scope
        it = self._outline_item(want)
        if it is not None:
            self.outline.blockSignals(True)
            self.outline.setCurrentItem(it)
            self.outline.blockSignals(False)

    def _outline_item(self, key: str) -> QTreeWidgetItem | None:
        stack = [self.outline.topLevelItem(i) for i in range(self.outline.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, Qt.ItemDataRole.UserRole) == key:
                return it
            stack += [it.child(i) for i in range(it.childCount())]
        return None

    def _outline_picked(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key == "closed":
            self.show_closed = not self.show_closed
            self.render_outline()
            return
        if key == "overview":
            self.scope, self.kind = self.task_id, "all"
            self.query = ""
            self.box.clear()
            self.back_to_page = False
        elif key:
            self.set_scope(key)
            if self.kind == PAGE:  # that task's page, ready to type in
                self.pane.notes.setFocus()
            return
        self.refresh()

    def set_scope(self, task_id: str) -> None:
        """Narrow the window to a subtask's branch (or the whole task): its files, unless something is typed."""
        self.scope = task_id if task_id in overview.family(self.model(), self.task_id) else self.task_id
        if not self.query and self.kind == "all":
            self.kind = "file"
        self.recent_snap = None
        self.refresh()

    # ================= the list =================
    def is_overview(self) -> bool:
        return self.kind == "all" and not finder.terms(self.query)[0] and not self.filters.count()

    def refresh(self, keep: bool = False) -> None:
        """Draw the list again for what's chosen: Overview, a kind's list, or what the search finds; or the Notes page.
        ``keep`` keeps the chosen record and the scroll (the second tier's finds arrive below, so nothing on screen moves)."""
        if self.stale and self.kind != PAGE:
            self.reload()
            return
        chosen = self.chosen_record() if keep else None
        scroll = self.list.verticalScrollBar().value() if keep else 0
        rows = self.rows()
        self.kinds.blockSignals(True)
        self.kinds.setCurrentIndex(TABS.index(self.kind))
        for i, k in enumerate(TABS):
            self.kinds.setTabText(i, TAB_NAMES[k] if k == PAGE else f"{KIND_NAMES[k]}  {self.counts.get(k, 0)}")
        self.kinds.blockSignals(False)
        self.filter_bar.setVisible(self.kind != PAGE)
        self.list.compact = self.compact
        index = next((i for i, r in enumerate(rows) if chosen is not None and r.record is chosen), None)
        if index is None:
            index = next((i for i, r in enumerate(rows) if r.choosable), None)
        self.list.set_rows(rows, index)
        if keep:
            self.list.verticalScrollBar().setValue(scroll)
        self._empty_state(rows)
        self._chips()
        self._count_line()
        self._select_outline()
        self._buttons()
        self._sync_preview()
        self.show_preview()
        if not self._foot_timer.isActive() and self.foot.text() != (PAGE_FOOT if self.kind == PAGE else FOOT):
            self.say("")

    def chosen_record(self) -> Record | None:
        i = self.list.current()
        return self.list.rows[i].record if 0 <= i < len(self.list.rows) else None

    def rows(self) -> list[Row]:
        words, neg = finder.terms(self.query)
        scoped = self.in_scope()
        kept = [r for r in scoped if self.keep(r)]
        if words:
            start = time.perf_counter()
            hits = finder.find(kept, words, neg, bonus=self.bonus)
            self.searched_ms = (time.perf_counter() - start) * 1000
            second = self.second[1] if self.second and self.second[0] == self.query else []
            allowed = {id(r) for r in kept}
            second = [h for h in second if id(h.record) in allowed]
            self.counts = overview.counts([h.record for h in [*hits, *second]])
            return self.result_rows(hits, second, words)
        self.counts = overview.counts(kept)
        if self.kind == PAGE:
            return []
        if self.is_overview():
            return self.overview_rows(scoped)
        kind = "file" if self.kind == "all" else self.kind
        return self.kind_rows(kind, [r for r in kept if r.kind == kind])

    def _item(self, r: Record, **extra) -> Row:
        owner = r.id if r.kind == "task" else r.task
        sub = "" if owner in (self.scope, self.task_id) or r.kind == "task" else self.model().task(owner).title
        return Row("item", r, subtask=sub, pinned=r.kind == "file" and r.id in self.pinned, missing=r.id in self.missing, **extra)

    def overview_rows(self, scoped: list[Record]) -> list[Row]:
        files = [r for r in scoped if r.kind == "file"]
        by_id = {r.id: r for r in files}
        out: list[Row] = []
        if not files:
            out.append(Row("empty", label=f"No files yet.\nDrop files or Outlook emails on this window to add them to "
                                            f"{self.model().task(self.scope).title} as a note, or press N."))
        pinned = [by_id[d] for d in self.pinned if d in by_id]
        if pinned:
            out += [Row("head", label="Pinned", count=len(pinned), hint="Your key documents"),
                    *(self._item(r) for r in pinned)]
        if self.recent_snap is None or self.recent_snap[0] != self.scope:  # Recent stays put while it's on screen
            self.recent_snap = (self.scope, overview.recent(files, self.used, self.today()))
        recent = self.recent_snap[1]
        if recent:
            out += [Row("head", label="Recent", hint="Opened from DocRepo, or added lately"), *(self._item(x.record, why=x.why) for x in recent)]
        if files and not pinned:
            out.append(Row("tip", label="Press P on a file (Alt+P from the search box) to keep it at the top here."))
        latest = overview.latest(scoped)
        if latest:
            out += [Row("head", label="Latest updates"), *(self._item(r) for r in latest)]
        if files:
            out.append(Row("more", label=f"Show all {len(files)} files", more="file"))
        return out

    def kind_rows(self, kind: str, recs: list[Record]) -> list[Row]:
        m = self.model()
        if kind == "task":
            order = [x for x in m.descendants_of(self.scope) if ("task", x) in self.by_key]
            shown = [self.by_key[("task", x)] for x in order]
            closed = [r for r in shown if r.state == "Closed"]
            out = [self._item(r, depth=max(0, len(next((c for c in m.chains_of(r.id) if self.scope in c), [r.id])) - 2
                                          - next((c for c in m.chains_of(r.id) if self.scope in c), [r.id]).index(self.scope)))
                   for r in shown if self.show_closed or r.state != "Closed"]
            if closed and not self.show_closed:
                out.append(Row("more", label=f"Show {len(closed)} closed", more="closed"))
            return out
        how = self.group or DEFAULT_GROUP.get(kind, "none")
        if how == "task" and self.scope != self.task_id and not m.children_of(self.scope):
            how = "none"
        out = []
        for label, rs in overview.group(m, overview.sort(recs, self.sort or "new", self.last_used), how, self.today(), self.task_id):
            if label:
                out.append(Row("head", label=label, count=len(rs), fold=label, folded=label in self.folded))
            if label not in self.folded:
                out += [self._item(r) for r in rs]
        return out

    def result_rows(self, hits: list[finder.Hit], second: list[finder.Hit], words: list[str]) -> list[Row]:
        def item(h: finder.Hit) -> Row:
            r = h.record
            snippet = ""
            if h.in_text:
                text = self.text_of(r) if r.kind == "file" else r.text
                if r.kind == "note" and text.startswith(r.title):  # the title is on the row already
                    text = text[len(r.title):].lstrip(" .:;-")
                snippet = finder.snippet(text, words)
            return self._item(r, words=words, slips=h.slips, in_text=h.in_text, snippet=snippet)

        out: list[Row] = []
        kinds = KINDS if self.kind == "all" else (self.kind,)
        for k in kinds:
            mine = [h for h in hits if h.record.kind == k]
            if not mine:
                continue
            if self.kind == "all":
                out.append(Row("head", label=KIND_NAMES[k], count=len(mine)))
                out += [item(h) for h in mine[:CAPS[k]]]
                if len(mine) > CAPS[k]:
                    out.append(Row("more", label=f"Show all {len(mine)} {KIND_NAMES[k].lower()}", more=k))
            elif self.group and self.group != "none":
                by_record = {id(h.record): h for h in mine}
                for label, rs in overview.group(self.model(), [h.record for h in mine], self.group, self.today(), self.task_id):
                    out.append(Row("head", label=label, count=len(rs)))
                    out += [item(by_record[id(r)]) for r in rs]
            else:
                out += [item(h) for h in (mine if not self.sort else self._sorted_hits(mine))]
        if second and self.kind in ("all", "file"):
            if self.kind == "all":
                out.append(Row("head", label="Found in the text of files", count=len(second), hint="Their names don't match; their text does"))
                out += [item(h) for h in second[:5]]
                if len(second) > 5:
                    out.append(Row("more", label=f"Show all {len(second)} in Files", more="file"))
            else:
                out.append(Row("sub", label="Found in the text", count=len(second)))
                out += [item(h) for h in second]
        return out

    def _sorted_hits(self, hits: list[finder.Hit]) -> list[finder.Hit]:
        order = {id(r): i for i, r in enumerate(overview.sort([h.record for h in hits], self.sort, self.last_used))}
        return sorted(hits, key=lambda h: order[id(h.record)])

    def _empty_state(self, rows: list[Row]) -> None:
        if self.kind == PAGE:
            self._show_page()
            return
        if rows:
            self.stack.setCurrentIndex(0)
            return
        words, _ = finder.terms(self.query)
        title = self.model().task(self.scope).title
        narrowed = self.scope != self.task_id
        if words:
            if self.second_busy or not (self.second and self.second[0] == self.query):
                html = pages.still_searching()
            else:
                pool = [r for r in self.in_scope() if self.keep(r)]
                suggestion = finder.suggestion(words, self.records, lambda w: bool(finder.find(pool, w)))
                html = pages.nothing_found(title, self.query.strip(), self.filters.count(), narrowed, suggestion)
        else:
            html = pages.nothing_of_kind("file" if self.kind == "all" else self.kind, title, narrowed)
        self.empty.setHtml(html)
        self.stack.setCurrentIndex(1)

    def _count_line(self) -> None:
        if self.kind == PAGE:
            return
        words, _ = finder.terms(self.query)
        title = self.model().task(self.scope).title
        more = len(self.second[1]) if self.second and self.second[0] == self.query else 0
        shown = self.counts.get(self.kind, 0)
        self.count.setText(pages.count_line(self.kind, shown, title, bool(words), self.is_overview(), self.second_busy, more,
                                            self.scope != self.task_id))
        self.count.setToolTip(f"Searched in {self.searched_ms:.1f} ms" if words else "")

    def _chips(self) -> None:
        while self.chip_row.count():
            w = self.chip_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        f, chips = self.filters, []
        chips += [(f"Type: {TYPE_NAMES.get(t, t)}", lambda t=t: f.types.discard(t)) for t in sorted(f.types)]
        chips += [(f"From: {SOURCE_NAMES.get(s, s)}", lambda s=s: f.sources.discard(s)) for s in sorted(f.sources)]
        chips += [(f"From: {s}", lambda s=s: f.senders.discard(s)) for s in sorted(f.senders)]
        if f.since:
            chips.append((f"Since: {f.since:%a %d %b}", lambda: setattr(f, "since", None)))
        if f.before:
            chips.append((f"Before: {f.before:%a %d %b}", lambda: setattr(f, "before", None)))
        if f.pinned:
            chips.append(("Pinned", lambda: setattr(f, "pinned", False)))
        if f.missing:
            chips.append(("Missing", lambda: setattr(f, "missing", False)))
        if self.scope != self.task_id:
            chips.append((f"In: {self.model().task(self.scope).title}", lambda: setattr(self, "scope", self.task_id)))
        for label, undo in chips:
            b = QPushButton(f"{label}  ×", objectName="tvChip")
            b.setToolTip(f"Remove {label}")
            b.clicked.connect(lambda _=False, undo=undo: (undo(), self.refresh()))
            self.chip_row.addWidget(b)
        if len(chips) > 1:
            clear = QPushButton("Clear all", objectName="subtle" if not LOOK.classic else "")
            clear.clicked.connect(self.clear_filters)
            self.chip_row.addWidget(clear)
        self.chip_row.addStretch(1)
        self.chips.setVisible(bool(chips) and self.kind != PAGE)  # they narrow lists; the page says whose it is

    def _buttons(self) -> None:
        f = self.filters
        self.type_button.setText(f"Type: {TYPE_NAMES.get(next(iter(f.types)), '')}" if len(f.types) == 1 else f"Type: {len(f.types)}" if f.types else "Type")
        self.date_button.setText("Date: set" if f.since or f.before else "Date")
        n = len(f.sources) + len(f.senders)
        self.from_button.setText(f"From: {n}" if n else "From")

    def _fold(self, key: str) -> None:
        (self.folded.discard if key in self.folded else self.folded.add)(key)
        self.refresh(keep=True)

    # ================= the Notes page tab (decisions 239 to 244) =================
    def page_pane(self) -> TaskPane:
        if self.pane is None:
            self.pane = TaskPane(page_css(), 0)
            self.pane.notes_only()
            self.pane.title.setTextFormat(Qt.TextFormat.PlainText)
            self.browse.wire_notes(self.pane, self.say, self.page_ref)
            self.pane.notes.installEventFilter(self)
            self.pane.notes.viewport().installEventFilter(self)
            self.stack.addWidget(self.pane)
        return self.pane

    def _show_page(self) -> None:
        """The page of the task picked in the outline, in place of the list: the whole task's is the top task's own."""
        pane = self.page_pane()
        if pane.task_id != self.scope:
            self.page_record, self.page_preview = None, False
        self.browse.load_notes(self.scope, pane)
        title = self.model().task(self.scope).title
        whole = self.scope == self.task_id
        pane.title.setText("Notes" if whole else QFontMetrics(pane.title.font()).elidedText(f"Notes: {title}", Qt.TextElideMode.ElideRight, PAGE_TITLE_WIDTH))
        pane.title.setToolTip("" if whole else title)
        self.stack.setCurrentWidget(pane)

    def open_page(self, task_id: str | None = None) -> None:
        """To the Notes page tab, on that task's page (or the one it was on), with the caret in the page."""
        self.box.clear()
        self.query, self.second, self.second_busy, self.back_to_page = "", None, False, False
        self._second_timer.stop()
        self.scope = task_id or self.scope
        self.kind = PAGE
        self.refresh()
        self.pane.notes.setFocus()

    def page_ref(self, ref: str) -> None:
        """A caption, file line or picture clicked on the page: its preview beside the page, in this window. What isn't
        this task's opens in the browse tool, as it does from the task page."""
        if self.stale:
            self.read_records()
        r = self._record_of(ref)
        if r is None:
            self.browse.show_browse()
            self.browse.open_ref(ref)
            return
        self.page_record = r
        self.set_preview(True)

    def _record_of(self, ref: str) -> Record | None:
        """What a line on the page stands for: a file; a capture's note, update or email; or, for a capture with no words
        of its own, its first file."""
        r = next((self.by_key[(k, ref)] for k in ("file", "email", "note") if (k, ref) in self.by_key), None)
        c = self.model().captures.get(ref)
        return r or next((self.by_key[("file", d)] for d in (c.document_ids if c else ()) if ("file", d) in self.by_key), None)

    def _page_drop(self, event) -> bool:
        """Files dropped on the page go on the page (decision 126), which ``NotesEdit`` sees to. An email or a link goes to
        the capture window, as it does anywhere else in this window, rather than coming in as text."""
        from docrepo.ui.capture_window import read_drop

        kinds = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
        if event.type() not in kinds or read_drop(event.mimeData(), links=True)[0] in ("", "files"):
            return False
        if event.type() == QEvent.Type.Drop:
            self.dropEvent(event)
        else:
            event.acceptProposedAction()
        return True

    # ================= typing =================
    def _typed(self, text: str) -> None:
        from_page = self.kind == PAGE
        m = self.model()
        subtasks = [(t, m.task(t).title) for t in overview.family(m, self.task_id)]
        senders = sorted({r.sender for r in self.records if r.sender})
        typed = finder.take_filters(text, self.filters, subtasks, senders, self.today())
        if typed.changed:
            self.box.setText(typed.rest)
            if typed.scope:
                self.scope = typed.scope
            if typed.kind:
                self.kind = typed.kind
        self.say(typed.hint)
        self.query = self.box.text()
        self.second = None
        if finder.terms(self.query)[0]:
            self.second_busy = True
            self._second_timer.start()
        else:
            self.second_busy = False
            self._second_timer.stop()
        if from_page and (finder.terms(self.query)[0] or typed.changed):  # results show in place of the page (decision 242)
            self.back_to_page = True
            if self.kind == PAGE:
                self.kind = "all"
        elif self.back_to_page and not self.query.strip() and not self.filters.count():
            self.kind, self.back_to_page = PAGE, False
        self.refresh()

    def _start_second(self) -> None:
        """The second tier: the files' extracted text, on a worker thread."""
        words, neg = finder.terms(self.query)
        if not words:
            self.second_busy = False
            return
        self.load_texts()
        candidates = [r for r in self.in_scope() if r.kind == "file" and self.keep(r)]
        texts, query = self.folded_texts, self.query
        self._token += 1
        job = _Job(self._token, lambda: (query, finder.find(candidates, words, neg, texts=texts)))
        job.signals.done.connect(self._second_done)
        self._jobs.append(job)
        QThreadPool.globalInstance().start(job)

    def _second_done(self, token: int, result) -> None:
        self._jobs = [j for j in self._jobs if j.token != token]
        if token != self._token or isinstance(result, Exception):
            if isinstance(result, Exception):
                log.warning("task view: searching the files' text failed: %s", type(result).__name__)
                self.second_busy = False
            return
        query, hits = result
        if query != self.query:
            return
        self.second, self.second_busy = (query, hits), False
        self.refresh(keep=True)

    def wait_for_second(self, timeout: float = 5.0) -> None:
        """For tests: run the second tier now and wait for it."""
        self._second_timer.stop()
        self._start_second()
        QThreadPool.globalInstance().waitForDone(int(timeout * 1000))
        QGuiApplication.processEvents()

    def focus_box(self) -> None:
        self.box.setFocus()
        self.box.selectAll()

    def escape(self) -> None:
        """Esc: clears what's typed; then the filters, scope and kind; then goes back to the box. It never closes. A search
        begun on the Notes page comes back to it."""
        if self.back_to_page:
            self.filters.clear()
            self.open_page()
            return
        if self.query:
            self.box.clear()
            self.query, self.second, self.second_busy = "", None, False
        elif self.filters.count() or self.scope != self.task_id or self.kind != "all":
            self.filters.clear()
            self.scope, self.kind = self.task_id, "all"
        self.refresh()
        self.box.setFocus()

    def clear_filters(self) -> None:
        self.filters.clear()
        self.scope = self.task_id
        self.refresh()

    def set_kind(self, kind: str) -> None:
        if kind == PAGE:
            self.open_page()
            return
        if kind == self.kind and self.kinds.currentIndex() == TABS.index(kind):
            return
        self.kind = kind
        self.refresh()

    def preview_wanted(self) -> bool:
        """The Notes page has its own say: hidden until something on it is clicked (decision 241)."""
        return self.page_preview if self.kind == PAGE else self.preview_on

    def set_preview(self, on: bool) -> None:
        if self.kind == PAGE:
            self.page_preview = on
        else:
            self.preview_on = on
        self._sync_preview()
        self._layout()
        self.show_preview()

    def _sync_preview(self) -> None:
        on = self.preview_wanted()
        self.preview_button.blockSignals(True)
        self.preview_button.setChecked(on)
        self.preview_button.blockSignals(False)
        if self.preview.isVisibleTo(self) != on:
            self._layout()

    # ================= keys in the box and the list =================
    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if self.pane is not None:
            if watched is self.pane.notes.viewport():
                return self._page_drop(event)
            if watched is self.pane.notes:  # the page keeps its keys; only Esc goes to the search box (decision 242)
                if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                    self.focus_box()
                    return True
                return False
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        k, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if self.kind == PAGE and watched is self.box and not mods and k in (Qt.Key.Key_Down, Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.pane.notes.setFocus()  # from the box into the page
            return True
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.list.step(("next group" if k == Qt.Key.Key_Down else "previous group") if ctrl else (1 if k == Qt.Key.Key_Down else -1))
            return True
        if k in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            self.list.step(8 if k == Qt.Key.Key_PageDown else -8)
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.act("show" if ctrl else "open")
            return True
        if ctrl and shift and k == Qt.Key.Key_C:
            self.act("copy")
            return True
        if k == Qt.Key.Key_Escape:
            self.escape()
            return True
        if watched is self.box:
            if k == Qt.Key.Key_Tab and not mods:
                self.list.setFocus()
                return True
            return super().eventFilter(watched, event)
        # The list: Home and End, Space for the preview, Ctrl+C for the path, and any other typing goes to the box.
        if k in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.list.step("first" if k == Qt.Key.Key_Home else "last")
            return True
        if k == Qt.Key.Key_Space and not mods:
            self.set_preview(not self.preview_on)
            return True
        if ctrl and k == Qt.Key.Key_C:
            self.act("copy")
            return True
        text = event.text()
        if text and text.isprintable() and not ctrl and not (mods & Qt.KeyboardModifier.AltModifier) and not text.isalpha():
            self.box.setFocus()
            self.box.insert(text)
            self._typed(self.box.text())
            return True
        return super().eventFilter(watched, event)

    def cycle_panes(self, step: int) -> None:
        """F6: the outline, the search box, the list or the page, the preview's first action, as Windows' pane key does."""
        notes = self.pane.notes if self.pane is not None else None
        panes = [w for w in (self.outline, self.box, self.list, notes, self._first_action()) if w is not None and w.isVisible()]
        focus = QGuiApplication.focusObject()
        i = next((n for n, w in enumerate(panes) if w is focus or (isinstance(focus, QWidget) and w.isAncestorOf(focus))), -1)
        panes[(i + step) % len(panes)].setFocus()

    def _first_action(self) -> QWidget | None:
        return next((b for b in self.preview_buttons if b.isVisible()), None)

    # ================= the preview =================
    def show_preview(self) -> None:
        i = self.list.current()
        row = self.list.rows[i] if 0 <= i < len(self.list.rows) else None
        r = self.page_record if self.kind == PAGE else row.record if row else None
        words, _ = finder.terms(self.query)
        if r is None:
            self.preview_page.setHtml(pages.nothing_clicked() if self.kind == PAGE else pages.preview(self.model(), None, self.today(), words))
            self._preview_buttons([])
            return
        text = self.text_of(r) if r.kind == "file" else ""
        slips = row.slips if row else ()
        self.preview_page.setHtml(pages.preview(self.model(), r, self.today(), words, slips, text, self.last_used.get(r.id), r.id in self.missing))
        self._preview_buttons(self._actions_for(r))

    def _preview_buttons(self, actions: list[tuple[str, str, bool, str]]) -> None:
        for n, b in enumerate(self.preview_buttons):
            if n >= len(actions):
                b.hide()
                continue
            label, name, primary, tip = actions[n]
            b.setText(label)
            b.setToolTip(tip)
            b.setProperty("act", name)
            if b.objectName() != ("primary" if primary else ""):
                b.setObjectName("primary" if primary else "")
                b.style().unpolish(b)
                b.style().polish(b)
            b.show()

    def _actions_for(self, r: Record) -> list[tuple[str, str, bool, str]]:
        if r.kind == "file":
            if r.type == "link":
                out = [("Copy link", "copylink", True, "Enter. DocRepo never opens links")]
            else:
                p = opener.plan(r)
                first = ("Open", "open", True, "Enter: in its own program") if p.action == "open" else (
                    "Show in File Explorer", "open", True, f"Enter. {p.reason}")
                out = [first]
                if p.action == "open":
                    out.append(("Show in File Explorer", "show", False, "Ctrl+Enter"))
                out.append(("Copy path", "copy", False, "Ctrl+Shift+C"))
            out.append(("Unpin" if r.id in self.pinned else "Pin", "pin", False, "P, or Alt+P from the search box"))
            return out
        if r.kind == "email":
            return [("Open the email", "open", True, "Enter: in Outlook"), ("Open capture", "capture", False, "Its capture, in the browse tool")]
        if r.kind == "note":
            on_page = [("Open on the notes page", "open", True, "Enter: here, on the Notes page tab")]
            return on_page + ([("Open capture", "capture", False, "Its capture, in the browse tool")] if r.capture else [])
        return [("Show what's in it", "open", True, "Enter: narrow this window to it"), ("Open its Task view", "taskview", False, "")]

    # ================= actions =================
    def act(self, name: str, index: int | None = None) -> None:
        if self.kind == PAGE:  # the page has no list: it's what was clicked on it
            if self.page_record is not None:
                self._act_on(name, self.page_record)
            return
        i = self.list.current() if index is None else index
        if not 0 <= i < len(self.list.rows):
            return
        if index is not None:
            self.list.choose(i)
        row = self.list.rows[i]
        if row.kind == "more":
            if row.more == "closed":
                self.show_closed = True
                self.refresh(keep=True)
            else:
                self.kind = row.more
                self.refresh()
            return
        if row.record is not None:
            self._act_on(name, row.record)

    def _act_on(self, name: str, r: Record) -> None:
        if r.kind == "task":
            if name == "taskview":
                self.browse.open_task_view(r.id)
            elif name in ("open", "show"):
                self.box.clear()
                self.query = ""
                self.set_scope(r.id)
            return
        if r.kind == "note":
            if name in ("open", "show"):
                self.open_note(r)
            elif name == "capture" and r.capture:
                self.open_capture_page(r.capture)
            return
        if r.kind == "email":
            if name == "capture" or name == "show":
                self.open_capture_page(r.capture)
            elif name == "open":
                p = opener.plan(r, self.email_file)
                if p.action == "open":
                    self._start(p.path, r, record_use=False)
                else:
                    self.say(p.reason)
                    self.open_capture_page(r.capture)
            return
        self.file_action(name, r)

    def file_action(self, name: str, r: Record) -> None:
        if name == "pin":
            self.toggle_pin(r)
        elif name == "copy":
            QGuiApplication.clipboard().setText(opener.copy_text([r.path]))
            self.use(r, "copy_link" if r.type == "link" else "copy_path")
            self.say(f"Copied the {'link' if r.type == 'link' else 'path'} of {r.title}.")
        elif name == "copylink" or (name in ("open", "show") and r.type == "link"):
            QGuiApplication.clipboard().setText(r.path.strip())
            self.use(r, "copy_link")
            self.say(f"Copied the link to {r.title}. DocRepo never opens links: paste it into your browser.")
        elif name == "show":
            self.show_file(r)
        elif name == "open":
            p = opener.plan(r)
            if p.action == "open":
                self._start(p.path, r)
            else:
                self.show_file(r, p.reason)

    def show_file(self, r: Record, reason: str = "") -> None:
        found = self.browse.reveal(Path(r.path))
        self.use(r, "show")
        if found is False:
            self.missing.add(r.id)
            self.say(f"{r.title} isn't at {opener.folder_of(r.path)} any more. File Explorer shows the nearest folder that's there.", error=True)
            self.refresh(keep=True)
        else:
            self.missing.discard(r.id)
            self.say(reason or f"Showed {r.title} in File Explorer.")

    def _start(self, path: str, r: Record, record_use: bool = True) -> None:
        """Open a file in its own program, on a worker thread with a word after two seconds if the drive is slow."""
        self._token += 1
        token = self._token
        starter, exists = self.starter, self.exists
        job = _Job(token, lambda: opener.start(path, starter, exists))
        slow = QTimer(self, singleShot=True, interval=2000, timeout=lambda: self.say(f"Still opening {r.title}…"))

        def done(_t: int, result) -> None:
            slow.stop()
            self._jobs = [j for j in self._jobs if j is not job]
            error = str(result) if isinstance(result, Exception) else result
            if error:
                if "isn't at" in error and r.kind == "file":
                    self.missing.add(r.id)
                    self.refresh(keep=True)
                self.say(error, error=True)
            else:
                self.missing.discard(r.id)
                self.say(f"Opened {r.title}.")

        job.signals.done.connect(done)
        self._jobs.append(job)
        slow.start()
        if record_use and r.kind == "file":
            self.use(r, "open")
        QThreadPool.globalInstance().start(job)

    def use(self, r: Record, action: str) -> None:
        """Note what was done with a file (decision 159), for Recent and Last opened. Recent itself waits for the next
        time the window opens, so nothing moves while you look."""
        if r.kind != "file":
            return
        try:
            pins.record_use(self.conn, r.id, self.task_id, action, self.ctx.now())
            self.last_used[r.id] = f"{self.ctx.now():%Y-%m-%d %H:%M:%S}"
        except Exception as e:  # noqa: BLE001 - a use that isn't kept never stops the action
            log.warning("task view: a use of %s wasn't kept: %s", r.id, type(e).__name__)

    def toggle_pin(self, r: Record) -> None:
        if r.kind != "file":
            self.say("Only files can be pinned.")
            return
        on = r.id not in self.pinned
        pins.set_pinned(self.conn, self.task_id, r.id, on)
        self.pinned = pins.pins_of(self.conn, self.task_id)
        self.browse.task_view_pins_changed(self.task_id)
        self.say(f"Pinned {r.title}: it's first on Overview now." if on else f"Unpinned {r.title}.")
        self.refresh(keep=True)

    def move_pin(self, step: int) -> None:
        r = self.chosen_record()
        if r is None or r.id not in self.pinned:
            return
        if pins.move_pin(self.conn, self.task_id, r.id, step):
            self.pinned = pins.pins_of(self.conn, self.task_id)
            self.browse.task_view_pins_changed(self.task_id)
            self.refresh(keep=True)

    def open_note(self, r: Record) -> None:
        """A note or update on its task's notes page, here: at its block, or for words typed on the page, the page (decision 242)."""
        self.open_page(r.task)
        if r.type != "page" and r.capture:
            if self.pane.notes.go_to(r.capture):
                QTimer.singleShot(0, self.pane.scroll_to_caret)
            else:
                self.say(f"{r.capture} isn't on the notes page.")

    def open_capture_page(self, capture_id: str) -> None:
        self.browse.show_browse()
        self.browse.go_capture(capture_id)
        self.browse.raise_()
        self.browse.activateWindow()

    def open_task_page(self) -> None:
        self.browse.show_browse()
        self.browse.go_task(self.task_id)
        self.browse.raise_()
        self.browse.activateWindow()

    def command(self, mode: str) -> None:
        """The task's own commands, as the browse tool's letters: Note, Update, New subtask, Agenda, Today, Edit, Meeting."""
        b, tid = self.browse, self.task_id
        if mode == "edit":
            b.edit_task(tid)
        elif mode == "today":
            b.add_to_today(tid)
            self.say("Added to Today.")
        elif mode == "agenda":
            b.open_capture(task=tid, mode="update", agenda_focus=True)
        elif mode == "meeting":
            b.open_capture(task=tid, meeting=True)
        else:
            b.open_capture(task=tid, mode=mode)

    def go_to_task(self) -> None:
        """Ctrl+O: another task's Task view, from the task picker."""
        from docrepo.ui.task_picker import TaskPicker

        self._picker = TaskPicker(self, self.browse.model, None)
        self._picker.picked.connect(lambda tid: tid and self.browse.open_task_view(tid))
        self._picker.setMinimumWidth(max(360, self.box.width()))
        self._picker.popup(self.box.mapToGlobal(self.box.rect().bottomLeft()))

    def go_to_parent(self) -> None:
        parents = self.model().parents_of(self.task_id)
        if parents:
            self.browse.open_task_view(parents[0])
        else:
            self.say("It's a top-level task.")

    def on_link(self, url: QUrl) -> None:
        scheme, rest = url.scheme(), unquote(url.toString()[len(url.scheme()) + 1:])
        if scheme == "task":
            self.browse.open_task_view(rest)
        elif scheme == "scope":
            self.box.clear()
            self.query = ""
            self.set_scope(rest)
        elif scheme == "pick":
            kind, _, item = rest.partition(":")
            r = self.by_key.get((kind, item))
            if r is not None:
                self.box.clear()
                self.query, self.kind, self.scope, self.group, self.sort = "", kind, self.task_id, "none", None
                self.refresh()
                i = next((n for n, row in enumerate(self.list.rows) if row.record is r), None)
                if i is not None:
                    self.list.choose(i)
        elif scheme == "capture":
            self.open_capture_page(rest)
        elif scheme == "label":
            self.browse.show_browse()
            self.browse.select("label", rest)
        elif scheme == "q":
            self.box.setText(rest)
            self._typed(rest)
        elif scheme == "do":
            {"update": lambda: self.command("update"), "note": lambda: self.command("note"), "clear": self.clear_filters,
             "whole": lambda: self.set_scope(self.task_id), "everywhere": self.search_everywhere}.get(rest, lambda: None)()

    def search_everywhere(self) -> None:
        words = self.query
        self.browse.show_browse()
        self.browse.search_box.setText(words)
        self.browse.search_box.setFocus()
        self.browse.raise_()
        self.browse.activateWindow()

    def say(self, text: str, error: bool = False) -> None:
        self.foot.setText(text or (PAGE_FOOT if self.kind == PAGE else FOOT))
        self.foot.setStyleSheet(f"color: {tokens.LIGHT['critical' if error else 'text' if text else 'text2']};")
        if text:
            self._foot_timer.start()

    # ================= menus =================
    def _fill_type_menu(self) -> None:
        menu, f = self.type_menu, self.filters
        menu.clear()
        scoped = [r for r in self.in_scope() if r.kind in ("file", "email")]
        for t in TYPE_ORDER:
            n = sum(1 for r in scoped if r.type == t)
            if n:
                a = menu.addAction(icon(f"type-{t}", tokens.LIGHT.get(f"type_{t}")), f"{TYPE_NAMES[t]}\t{n}")
                a.setCheckable(True)
                a.setChecked(t in f.types)
                a.toggled.connect(lambda on, t=t: (f.types.add(t) if on else f.types.discard(t), self.refresh()))
        menu.addSeparator()
        menu.addAction("Or type type:pdf, type:excel, .docx …").setEnabled(False)

    def _fill_date_menu(self) -> None:
        menu, f = self.date_menu, self.filters
        menu.clear()
        group = QActionGroup(menu)
        today = self.today()
        choices = (("Any time", None), ("Last 7 days", today - timedelta(days=7)), ("Last 30 days", today - timedelta(days=30)),
                   ("This year", today.replace(month=1, day=1)))
        for label, since in choices:
            a = QAction(label, menu, checkable=True, checked=f.since == since and not f.before)
            group.addAction(a)
            menu.addAction(a)
            a.triggered.connect(lambda _=False, since=since: (setattr(f, "since", since), setattr(f, "before", None), self.refresh()))
        menu.addSeparator()
        menu.addAction("Or type since:1 sep, before:oct, after:last week").setEnabled(False)

    def _fill_from_menu(self) -> None:
        menu, f = self.from_menu, self.filters
        menu.clear()
        scoped = self.in_scope()
        menu.addSection("Source")
        for s in SOURCES:
            n = sum(1 for r in scoped if r.kind == "file" and r.source == s)
            if n:
                a = menu.addAction(f"{SOURCE_NAMES[s]}\t{n}")
                a.setCheckable(True)
                a.setChecked(s in f.sources)
                a.toggled.connect(lambda on, s=s: (f.sources.add(s) if on else f.sources.discard(s), self.refresh()))
        senders = sorted({r.sender for r in scoped if r.kind == "email" and r.sender})
        if senders:
            menu.addSection("Sent by")
        for s in senders:
            n = sum(1 for r in scoped if r.kind == "email" and r.sender == s)
            a = menu.addAction(f"{s}\t{n}")
            a.setCheckable(True)
            a.setChecked(s in f.senders)
            a.toggled.connect(lambda on, s=s: (f.senders.add(s) if on else f.senders.discard(s), self.refresh()))

    def _fill_view_menu(self) -> None:
        menu = self.view_menu
        menu.clear()
        menu.addSection("Group by")
        groups = QActionGroup(menu)
        current = self.group or ("none" if finder.terms(self.query)[0] else DEFAULT_GROUP.get("file" if self.kind == "all" else self.kind, "none"))
        for key, label in GROUPS:
            a = QAction(label, menu, checkable=True, checked=current == key)
            groups.addAction(a)
            menu.addAction(a)
            a.triggered.connect(lambda _=False, key=key: (setattr(self, "group", key), self.folded.clear(), self.refresh()))
        menu.addSection("Sort")
        sorts = QActionGroup(menu)
        for key, label in SORTS:
            a = QAction(label, menu, checkable=True, checked=(self.sort or "") == key)
            sorts.addAction(a)
            menu.addAction(a)
            a.triggered.connect(lambda _=False, key=key: (setattr(self, "sort", key or None), self.refresh()))
        menu.addSection("Display")
        compact = menu.addAction("Compact rows")
        compact.setCheckable(True)
        compact.setChecked(self.compact)
        compact.toggled.connect(lambda on: (setattr(self, "compact", on), self.refresh(keep=True)))

    def open_palette(self) -> None:
        from docrepo.ui.palette import Command, CommandPalette

        cmds = [Command("File", "Open", lambda: self.act("open"), "Enter"), Command("File", "Show in File Explorer", lambda: self.act("show"), "Ctrl+Enter"),
                Command("File", "Copy path", lambda: self.act("copy"), "Ctrl+Shift+C"), Command("File", "Pin or unpin", lambda: self.act("pin"), "P"),
                Command("View", "Show or hide the preview", lambda: self.set_preview(not self.preview_wanted()), "Ctrl+Space"),
                *(Command("View", f"Show {TAB_NAMES[k].lower()}", lambda k=k: self.set_kind(k), f"Ctrl+{i + 1}") for i, k in enumerate(TABS)),
                *(Command("View", f"Group by {label.lower()}", lambda key=key: (setattr(self, "group", key), self.refresh())) for key, label in GROUPS),
                Command("View", "Clear the filters", self.clear_filters, "Ctrl+Backspace"),
                *(Command("Go to", self.model().task(t).title, lambda t=t: self.set_scope(t)) for t in overview.family(self.model(), self.task_id)[1:]),
                Command("Go to", "Another task's Task view", self.go_to_task, "Ctrl+O"), Command("Go to", "The parent task's Task view", self.go_to_parent, "Alt+Up"),
                Command("Task", "Open task page", self.open_task_page), Command("Task", "Note", lambda: self.command("note"), "N"),
                Command("Task", "Update", lambda: self.command("update"), "U"), Command("Task", "New subtask", lambda: self.command("new_task"), "T"),
                Command("Task", "Add to Today", lambda: self.command("today"), "D"), Command("Task", "Edit task", lambda: self.command("edit"), "E")]
        self._palette = CommandPalette(self, cmds)
        self._palette.open_over(self)

    # ================= the window =================
    def _layout(self) -> None:
        """Three panes from 900 px; narrower ones below 1,100 px; below 900 px the outline folds away and the preview
        shows only when asked for."""
        w = self.width()
        narrow = w < NARROW
        on = self.preview_wanted()
        self.outline.setVisible(not narrow)
        self.preview.setVisible(on)
        if not narrow:
            outline, preview = (PANES["outline"], PANES["preview"]) if w >= WIDE else (200, 320)
            self.split.setSizes([outline, max(300, w - outline - (preview if on else 0)), preview if on else 0])

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._layout()
        self._head_timer.start()  # once the layout has given the header its new width, or it fits an old one

    def _restore_geometry(self) -> None:
        saved = db.get_state(self.conn, GEOMETRY_KEY)
        if not (saved and self.restoreGeometry(QByteArray.fromHex(saved.encode("ascii")))):
            self.resize(1280, 820)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if self.pane is not None:
            self.pane.notes.save_now()
        try:
            db.set_state(self.conn, GEOMETRY_KEY, bytes(self.saveGeometry().toHex()).decode("ascii"))
        except Exception as e:  # noqa: BLE001 - a size that isn't kept never stops the window closing
            log.warning("task view: its size wasn't kept: %s", type(e).__name__)
        self.browse.task_view_closed(self.task_id)
        super().closeEvent(event)

    # ---- dropping files and emails on it (decision 165): the capture window takes them, on this task ----
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        from docrepo.ui.capture_window import read_drop

        kind, _ = read_drop(event.mimeData(), links=True)
        if kind:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt's name
        from docrepo.ui.capture_window import read_drop

        kind, paths = read_drop(event.mimeData(), links=True)
        if not kind or self.browse.capture is None:
            return
        event.acceptProposedAction()
        self.browse.open_capture(task=self.task_id, mode="note")
        self.browse.capture.dropped(kind, paths)
        self.say("The capture window has them, as a note on this task. Add a word if you like, and save.")
