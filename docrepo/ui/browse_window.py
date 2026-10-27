"""The browse tool: views on the left, a list in the middle and the selected item's page on the right.

Search is always at the top. New capture, and the Add note, Update and New task
buttons on a task page, open the capture window, so tasks are entered in one
place only. While browsing (not typing), A adds a note to the selected task, N
a new task under it, U an update and G puts it on an agenda. Ctrl+B hides the views. Changes made here (filing a capture,
fixing one, clearing a reminder, closing an agenda item, editing people, labels
and a task's title, labels and parents) go into docs.db and the status log at
once, and the generated pages are written again.

Ported from the mockup's ``views.js`` and ``detail.js``; SPEC section 8 describes it.
"""
from __future__ import annotations

import html
import logging
import re
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import bulk, capacity, db, edits, items, people, prompts, search
from docrepo.agenda import AgendaError
from docrepo.captures import capture_folder, capture_md_path
from docrepo.dates import long_date, short
from docrepo.detail import SCOPE_NAMES, PageState, Pages, chip, esc, state_chip
from docrepo.links import is_link
from docrepo.model import TODAY, Model, is_person
from docrepo.people import PeopleError
from docrepo.safe_fs import WriteRefused
from docrepo.save import SaveError, SaveResult, add_quick_task, note_to_task
from docrepo.schedule import DueDate, is_open
from docrepo.tasks import TaskError
from docrepo.ui.context import AppContext
from docrepo.ui.dialogs import LabelDialog, PersonDialog
from docrepo.ui.rich_edit import FormatBar, RichEdit
from docrepo.ui.explorer import show_in_explorer
from docrepo.ui.settings_view import SettingsView
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK, Help, KeyTips, set_hints, tip, with_key
from docrepo.ui.nav_pane import WIDTH as NAV_WIDTH, NavPane
from docrepo.ui.page_view import PageView
from docrepo.ui.palette import Command, CommandPalette
from docrepo.ui.style import FORMAT_BAR_STYLE, page_css, style_sheet
from docrepo.ui.task_forms import BulkEditDialog, LabelMatchDialog, TaskEditDialog
from docrepo.ui.task_picker import TaskPicker
from docrepo.ui.timeline_view import TimelineView
from docrepo.ui.keymap import KeyMapDialog
from docrepo.timeline import bands as timeline_bands
from docrepo.ui.tree_view import DIM_ROLE, GREY, HTML_ROLE, KEY_ROLE, RowTree, edge, tint
from docrepo.ui.widgets import SAVE_KEYS, CheckMenuButton, FlowLayout, Option, label_filter, label_options, people_filter, people_options
from docrepo.views import (
    LIST_IDS,
    SORTS,
    TASK_VIEWS,
    VIEW_IDS,
    VIEWS,
    CapacityRow,
    Node,
    TreeFilter,
    agenda_groups,
    capacity_grid,
    capacity_weeks,
    closed_items,
    collapse_level,
    current_target,
    discarded_rows,
    documents_tree,
    due_cell,
    due_this_week,
    find_text,
    expand_level,
    full_path,
    list_date,
    list_tree,
    markers,
    meetings_for_menu,
    open_count,
    path_text,
    since_text,
    sort_tree,
    task_tree,
    today_groups,
    unfiled_rows,
    view_counts,
)

log = logging.getLogger(__name__)

WINDOW_TITLE = "DocRepo"
VIEWS_HIDDEN_KEY = "browse_views_hidden"
TODAY_MINE_KEY = "today_due_mine"  # Mine only, on Today's Due in the next 7 days (mods log round 2, M0050)
NAV_FOLDED_KEY = "browse_nav_folded"  # the sidebar's folded groups (the visual overhaul's decision 10)
STYLE = """
QWidget#browse { background: #ffffff; color: #1a1f25; font-family: "Segoe UI"; font-size: 10pt; }
QWidget#toolbar { background: #f4f6f8; border-bottom: 1px solid #d6dce3; }
QWidget#paneHead { background: #ffffff; border-bottom: 1px solid #d6dce3; }
QWidget#actions { background: #ffffff; }
QLabel#paneTitle { font-size: 12pt; font-weight: 600; }
QLabel#paneNote, QLabel#hint { color: #5a6571; font-size: 9pt; }
QLabel#status { background: #f4f6f8; border-top: 1px solid #d6dce3; color: #1a1f25; padding: 4px 10px; }
QLabel#status[error="true"] { background: #fbe3e1; color: #b0261e; }
QTreeWidget#nav { background: #f4f6f8; border: none; border-right: 1px solid #d6dce3; }
QTextBrowser { border: none; }
QPushButton { padding: 3px 9px; }
QPushButton#primary { background: #1d5e98; color: #ffffff; border: 1px solid #1d5e98; border-radius: 4px; padding: 4px 14px; }
QPushButton#rowLink { border: none; color: #1d5e98; text-decoration: underline; padding: 0 4px; background: transparent; }
""" + FORMAT_BAR_STYLE
#: The views with Select mode, where tasks can be ticked for Edit selected.
SELECT_VIEWS = ("tasks", *LIST_IDS)
UNFILED_NOTE = ("Unfiled captures: saved without a task. Their folders are already in Captures. Filing one links it in docs.db and sets "
                "the task in its capture.md; the folder doesn't move.")


class BrowseWindow(QWidget):
    """The browse tool's window. ``capture`` is the capture window it opens for new captures and updates."""

    def __init__(self, ctx: AppContext, capture=None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self.capture = capture
        self.setObjectName("browse")
        self.setWindowTitle(WINDOW_TITLE)
        self.setStyleSheet(STYLE if LOOK.classic else style_sheet())
        #: Shows a file in File Explorer. Tests replace it.
        self.reveal: Callable[[Path], bool] = show_in_explorer
        #: Asks a yes-or-no question. Tests replace it.
        self.confirm: Callable[[str, str], bool] = lambda title, text: QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes
        #: Shows a form and waits for it: true when it was saved. Tests replace it.
        self.run_dialog: Callable[[QDialog], bool] = lambda dialog: bool(dialog.exec())
        #: Asks why something is discarded: the reason, or None to cancel. Tests replace it.
        self.ask_reason: Callable[[str, str], str | None] = self._ask_reason
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text
        self.view = "tasks"
        self.sel: tuple[str, str] | None = None
        self.pin: str | None = None
        self.tree_filter = {"parked": False, "closed": False, "routine": True, "labels": [], "people": []}
        #: Each task view's sort order (views.SORTS); "default" is its own order.
        self.sorts: dict[str, str] = {}
        self.list_groups: dict[str, str] = {}  # each list's Group by: a parent label (release 5.9)
        #: Select mode (mods log round 1, M0009): tick boxes on the task tree's and the lists' rows, for Edit selected.
        self.selecting = False
        self.ticked: set[str] = set()
        #: A task just marked Done on Today: the Today view asks whether to update it too (mods log round 1, M0016).
        self.today_ask: str | None = None
        self.today_kind = "task"  # what Today's box makes: a quick task, or a note
        self.open: set[str] = set()
        self.doc_task: str | None = None
        self.doc_subs = True
        self.target: str | None = None
        self.cap_offset = 0
        self.cap_cell: tuple[str, int] | None = None
        self.retired = {"people": False, "labels": False}
        self.query = ""
        self.before_search = "tasks"
        self.state = PageState()
        self.file_to: dict[str, str] = {}
        self.editing: str | None = None
        self._edit_start: tuple[str, str] = ("", "")  # the capture edit's text and summary as it opened
        self.dirty = True
        self._model: Model | None = None
        self._contents: dict[str, tuple[int, str]] = {}
        self._placed = False
        self._build()
        # One letter per topic (mods log round 2, M0036): N note, T new task, U update, A agenda, E edit, D Today, and
        # M meeting notes (release 5.8).
        for keys, handler in (("N", lambda: self._key("note")), ("T", lambda: self._key("new_task")), ("U", lambda: self._key("update")),
                              ("A", lambda: self._key("agenda")), ("E", lambda: self._key("edit")), ("D", lambda: self._key("today")),
                              ("M", lambda: self._key("meeting")),
                              ("Ctrl+F", self.open_find), ("Ctrl+Shift+F", self.search_box.setFocus), ("F1", self.show_keys), ("F5", self.refresh),
                              ("Ctrl+B", lambda: self.show_views_pane(not self.views_button.isChecked())), ("Ctrl+K", self.open_palette)):
            QShortcut(QKeySequence(keys), self, handler)
        if capture is not None:
            capture.saved.connect(self.capture_saved)

    # ================= building the window =================
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QWidget(objectName="toolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 12, 8)
        bl.setSpacing(8)
        self.keytips = KeyTips(self)
        if LOOK.classic:
            self.views_button = QPushButton("≡ Views")
        else:  # the visual overhaul's O5: an icon button folds the sidebar
            self.views_button = QToolButton(objectName="iconButton")
            self.views_button.setIcon(icon("sidebar"))
            self.views_button.setFixedSize(tokens.ICON_BUTTON, tokens.ICON_BUTTON)
            self.views_button.setAccessibleName("Views")
        self.views_button.setCheckable(True)
        tip(self.views_button, "Hide or show the list of views on the left", "Ctrl+B")
        self.keytips.add(self.views_button, "Ctrl+B", ctrl=True)
        bl.addWidget(self.views_button)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search everything: tasks, captures, documents and people" + ("   (Ctrl+Shift+F)" if LOOK.classic else ""))
        tip(self.search_box, "Search everything", "Ctrl+Shift+F")
        if not LOOK.classic:
            self.search_box.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
            self.search_box.setMaximumWidth(560)
        self.keytips.add(self.search_box, "Ctrl+Shift+F", ctrl=True)
        self.search_box.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)
        self.search_box.textChanged.connect(lambda _: self._search_timer.start())
        self.search_box.installEventFilter(self)
        bl.addWidget(self.search_box, 1)
        if not LOOK.classic:
            bl.addStretch(0)
        new = QPushButton("New capture", objectName="primary")
        if not LOOK.classic:
            new.setIcon(icon("add", tokens.colour("on_accent")))
        tip(new, "A new note, task or update in the capture window", self.ctx.settings.hotkey)
        new.clicked.connect(lambda: self.open_capture())
        self.tb_new = QPushButton(with_key("New task", "T"))
        self.tb_new.clicked.connect(lambda: self.capture_for_selected("new_task"))
        self.tb_update = QPushButton(with_key("Update", "U"))
        self.tb_update.clicked.connect(lambda: self.capture_for_selected("update"))
        keys = QPushButton(with_key("Keys", "F1"))
        keys.setToolTip("Every key, in one list")
        keys.clicked.connect(self.show_keys)
        for w in (new, self.tb_new, self.tb_update, keys):
            bl.addWidget(w)
        if not LOOK.classic:  # New task and Update act on the selected task: they're on its command bar; the keys are in More
            for w in (self.tb_new, self.tb_update, keys):
                w.hide()
            more = QToolButton(objectName="iconButton")
            more.setIcon(icon("more"))
            more.setFixedSize(tokens.ICON_BUTTON, tokens.ICON_BUTTON)
            more.setAccessibleName("More")
            more.setToolTip("Keys, the command palette and Show hints")
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.top_menu = QMenu(more)
            self.top_menu.aboutToShow.connect(self._fill_top_menu)
            more.setMenu(self.top_menu)
            bl.addWidget(more)
        outer.addWidget(bar)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        if LOOK.classic:
            self.nav = RowTree()
            self.nav.setObjectName("nav")
            self.nav.set_columns(["View", ""], [0, 34])
            self.nav.setHeaderHidden(True)
            self.nav.setRootIsDecorated(False)
            self.nav.setIndentation(0)
            self.nav.picked.connect(lambda key: self.set_view(key[1]) if key[0] == "view" else None)
        else:  # the visual overhaul's O10 (release 5.22): a sidebar of its own, not the tree
            self.nav = NavPane(VIEWS)
            self.nav.picked.connect(self.set_view)
            self.nav.folded.connect(self._nav_folded)
        self.split.addWidget(self.nav)

        self.middle = QStackedWidget()
        list_page = QWidget()
        lp = QVBoxLayout(list_page)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(0)
        head = QWidget(objectName="paneHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 8, 12, 6) if LOOK.classic else hl.setContentsMargins(16, 12, 16, 10)
        hl.setSpacing(4 if LOOK.classic else 8)
        self.pane_title = QLabel(objectName="paneTitle")
        self.pane_note = Help()  # what the view is: with Show hints (decision 7)
        self.pane_note.setObjectName("paneNote")
        self.filters = QWidget()
        self.filters_layout = FlowLayout(self.filters, spacing=8)
        # Find in this view (mods log round 2, M0026): Ctrl+F; it narrows the list as you type, and Esc clears it.
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find in this view   Esc clears" if LOOK.classic else "Find in this view")
        tip(self.find_box, "Find in this view. Esc clears it.", "Ctrl+F")
        self.find_box.setAccessibleName("Find in this view")
        self.find_box.textChanged.connect(lambda _: self.render_list())
        self.find_box.installEventFilter(self)
        fb.addWidget(self.find_box, 1)
        self.find_count = QLabel(objectName="paneNote")
        fb.addWidget(self.find_count)
        self.find_bar.hide()
        for w in (self.pane_title, self.pane_note, self.filters, self.find_bar):
            hl.addWidget(w)
        lp.addWidget(head)
        self.tree = RowTree()
        self.tree.picked.connect(self._row_picked)
        self.tree.ticked.connect(self._tick)
        self.tree.itemExpanded.connect(lambda item: self._expanded(item, True))
        self.tree.itemCollapsed.connect(lambda item: self._expanded(item, False))
        self.tree.itemDoubleClicked.connect(lambda item, _col: self.double_click(item))
        lp.addWidget(self.tree, 1)
        self.middle.addWidget(list_page)
        self.middle.addWidget(self._build_capacity())
        self.settings_view = SettingsView(self.ctx, self.say, lambda title, text: self.confirm(title, text),
                                          lambda path: self.reveal(path), lambda: self.open_import())
        self.middle.addWidget(self.settings_view)
        self.timeline = TimelineView()  # mods log round 1, M0019
        self.timeline.open_task.connect(lambda task_id: self.go_task(task_id))
        self.timeline.update_task.connect(lambda task_id: self.open_capture(task=task_id, mode="update"))
        self.middle.addWidget(self.timeline)
        self.split.addWidget(self.middle)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        self.actions = QWidget(objectName="actions")
        self.actions_layout = FlowLayout(self.actions, spacing=6 if LOOK.classic else 4)
        self.actions_layout.setContentsMargins(14, 8, 14, 4) if LOOK.classic else self.actions_layout.setContentsMargins(16, 10, 16, 2)
        dl.addWidget(self.actions)
        self.detail_stack = QStackedWidget()
        self.page = PageView()
        self.page.setOpenLinks(False)
        self.page.setOpenExternalLinks(False)
        self.page.document().setDefaultStyleSheet(page_css())
        self.page.document().setDocumentMargin(14 if LOOK.classic else 16)
        self.page.anchorClicked.connect(self.on_link)
        self.page.layout_changed.connect(self._page_width_changed)
        self.detail_stack.addWidget(self.page)
        self.detail_stack.addWidget(self._build_edit_form())
        dl.addWidget(self.detail_stack, 1)
        self.detail = detail
        self.split.addWidget(detail)
        self.split.setSizes([190 if LOOK.classic else NAV_WIDTH, 430, 560])
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 1)
        outer.addWidget(self.split, 1)
        hidden = db.get_state(self.ctx.conn, VIEWS_HIDDEN_KEY) == "1"
        self.views_button.setChecked(not hidden)
        self.nav.setVisible(not hidden)
        self.views_button.toggled.connect(self.show_views_pane)

        self.status = QLabel(objectName="status")
        self.status.setWordWrap(True)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(9000)
        self._status_timer.timeout.connect(lambda: self.status.setText(""))
        outer.addWidget(self.status)

    def _build_capacity(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        title = QLabel("Capacity", objectName="paneTitle")
        note = Help("Scheduled hours per person and week, spread over each task's workdays. Parked tasks don't count. Click a cell "
                    "to see which tasks fill it.")
        nav = QHBoxLayout()
        for text, step in (("◀ Earlier", -1), ("This week", 0), ("Later ▶", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=step: self._move_capacity(s))
            nav.addWidget(b)
        nav.addStretch()
        # Release 5.9: people under their groups' headings (M0033). A week with a plant event says so at its top (M0028).
        self.cap_by_group = QCheckBox("Group by group")
        self.cap_by_group.setToolTip("Put people under their groups' headings")
        self.cap_by_group.toggled.connect(lambda _: self.render_capacity())
        nav.addWidget(self.cap_by_group)
        self.cap_table = QTableWidget()
        self.cap_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cap_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cap_table.cellClicked.connect(self._capacity_clicked)
        self.cap_table.verticalHeader().setVisible(False)
        self.cap_detail = QTextBrowser()
        self.cap_detail.setOpenLinks(False)
        self.cap_detail.document().setDefaultStyleSheet(page_css())
        self.cap_detail.anchorClicked.connect(self.on_link)
        legend = QLabel(" ".join(f'<span style="background-color:{c}">&nbsp;{t}&nbsp;</span>' for t, c in (
            (("Under 80%", "#e2f2e6"), ("80 to 100%", "#fcefcf"), ("Over 100%", "#fbe3e1")) if LOOK.classic else
            (("Under 80%", tokens.colour("content")), ("80 to 100%", tokens.colour("selected")), ("Over 100%", tokens.colour("critical_bg"))))))
        for w in (title, note):
            lay.addWidget(w)
        lay.addLayout(nav)
        lay.addWidget(self.cap_table)
        lay.addWidget(legend)
        lay.addWidget(self.cap_detail, 1)
        return page

    def _build_edit_form(self) -> QWidget:
        form = QWidget()
        lay = QVBoxLayout(form)
        lay.setContentsMargins(14, 10, 14, 14)
        self.edit_title = QLabel(objectName="paneTitle")
        lay.addWidget(self.edit_title)
        lay.addWidget(QLabel("Content text", objectName="fieldLabel"))
        self.edit_content = RichEdit()  # with formatting and lists (mods log round 2, M0045)
        lay.addWidget(FormatBar(self.edit_content))
        lay.addWidget(self.edit_content, 3)
        lay.addWidget(QLabel("Summary", objectName="fieldLabel"))
        self.edit_summary = QPlainTextEdit()
        self.edit_summary.setPlaceholderText("No summary")
        lay.addWidget(self.edit_summary, 1)
        note = Help("Saving rewrites capture.md and keeps the previous version in the capture's _old versions folder. Nothing is lost. "
                    "Ctrl+Enter saves; Esc cancels.")
        lay.addWidget(note)
        row = QHBoxLayout()
        save = QPushButton("Save", objectName="primary")
        save.clicked.connect(self.save_capture_edit)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel_capture_edit)
        row.addWidget(save)
        row.addWidget(cancel)
        row.addStretch()
        lay.addLayout(row)
        # As in the browse tool's other forms (mods log round 2, M0035), while typing in this one.
        for keys, handler in ((SAVE_KEYS[0], self.save_capture_edit), (SAVE_KEYS[1], self.save_capture_edit), ("Escape", self.cancel_capture_edit)):
            QShortcut(QKeySequence(keys), form, handler, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        return form

    # ================= showing =================
    def show_browse(self, view: str | None = None, task: str | None = None) -> None:
        """Open the window, on a view or a task."""
        if not self._placed:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(int(screen.width() * 0.82), int(screen.height() * 0.85))
            self.move(screen.x() + (screen.width() - self.width()) // 2, screen.y() + (screen.height() - self.height()) // 3)
            if not LOOK.classic:  # the sidebar starts at its own width, not a share of the window's (O10)
                rest = self.width() - NAV_WIDTH - 2 * self.split.handleWidth()
                self.split.setSizes([NAV_WIDTH, rest * 43 // 99, rest - rest * 43 // 99])
            self._placed = True
        if self.dirty:
            self.refresh(render=False)
        if view:
            self.view = view
        if task:
            if view:
                self.select("task", task)
                self.render_all()
            else:
                self.go_task(task)
        elif view:
            self.set_view(view)
        else:
            if self.sel is None:
                self._select_first()
            self.render_all()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().showEvent(event)
        if self.dirty:
            self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - closing only hides it; the app keeps running in the tray
        event.ignore()
        self.hide()

    # ================= data =================
    def model(self) -> Model:
        if self._model is None:
            self._model = Model(self.ctx.conn)
        return self._model

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ctx.conn

    def today(self) -> date:
        return self.ctx.now().date()

    def content_of(self, capture_id: str) -> str:
        """A capture's content text from its capture.md, read again only when the file changes."""
        c = self.model().captures.get(capture_id)
        if c is None:
            return ""
        path = capture_md_path(self.ctx.data_root, c)
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return ""
        cached = self._contents.get(capture_id)
        if cached and cached[0] == stamp:
            return cached[1]
        from docrepo.captures import read_content

        text = read_content(self.ctx.data_root, c) or ""
        self._contents[capture_id] = (stamp, text)
        return text

    def pages(self) -> Pages:
        return Pages(self.model(), self.today(), self.content_of, self.ctx.settings.me, self.conn)

    def refresh(self, render: bool = True) -> None:
        """Read docs.db again and show what's there now."""
        self._model = None
        self.dirty = False
        if self.sel and not self._exists(self.sel):
            self.sel = None
        if render:
            self.render_all()

    def _exists(self, key: tuple[str, str]) -> bool:
        kind, item = key
        m = self.model()
        if kind == "label":
            return any(lb.name == item for lb in m.labels)
        return item in {"task": m.tasks, "capture": m.captures, "doc": m.documents, "person": m.people}.get(kind, {})

    def render_all(self) -> None:
        self.render_nav()
        self.render_list()
        self.render_detail()

    def say(self, text: str, error: bool = False) -> None:
        """A line in the status line at the bottom, for a few seconds."""
        self.status.setText(text)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._status_timer.start()

    # ================= the views pane =================
    def render_nav(self) -> None:
        if not LOOK.classic:
            self._render_nav_new()
            return
        counts = view_counts(self.model(), self.today(), self.ctx.settings.me)
        self.nav.begin()
        section = ""
        for v in VIEWS:
            if v.section != section:
                section = v.section
                self.nav.add_row(None, None, [f'<span style="color:#87919c; font-size:8pt; font-weight:600">{esc(section.upper())}</span>', ""],
                                 selectable=False)
            count = counts.get(v.id)
            label = f"<b>{esc(v.label)}</b>" if v.id == self.view else esc(v.label)
            self.nav.add_row(None, ("view", v.id), [label, f'<p align="right" class="sub">{count}</p>' if count is not None else ""])
        self.nav.end(("view", self.view) if self.view != "search" else None)

    def _render_nav_new(self) -> None:
        """The new look's sidebar (O10): an icon per view, counts only where they ask for something, and the groups
        folded as the owner left them (in docs.db)."""
        counts = view_counts(self.model(), self.today(), self.ctx.settings.me)
        folded = set(filter(None, (db.get_state(self.ctx.conn, NAV_FOLDED_KEY) or "").split(",")))
        self.nav.show_state(counts, self.view if self.view != "search" else None, folded)

    def _nav_folded(self, section: str, closed: bool) -> None:
        """A group in the sidebar was folded or unfolded; the choice is kept in docs.db's app_state."""
        folded = set(filter(None, (db.get_state(self.ctx.conn, NAV_FOLDED_KEY) or "").split(",")))
        (folded.add if closed else folded.discard)(section)
        db.set_state(self.ctx.conn, NAV_FOLDED_KEY, ",".join(sorted(folded)))

    # ---- the command palette (the visual overhaul's O7) ----
    def palette_commands(self) -> list[Command]:
        """Every command the palette offers here: the selected task's, then the views, then the window's own."""
        out: list[Command] = []
        task = self.model().tasks.get(self.sel[1]) if self.sel and self.sel[0] == "task" else None
        if task is not None and not task.discarded:
            tid = task.id
            out += [Command("Task", "Add a note", lambda: self.open_capture(task=tid, mode="note"), "N"),
                    Command("Task", "Update", lambda: self.open_capture(task=tid, mode="update"), "U"),
                    Command("Task", "New task under it", lambda: self.open_capture(task=tid, mode="new_task"), "T"),
                    Command("Task", "Add to Today", lambda: self.add_to_today(tid), "D"),
                    Command("Task", "Add to an agenda", lambda: self.open_capture(task=tid, mode="update", agenda_focus=True), "A"),
                    Command("Task", "Edit task", lambda: self.edit_task(tid), "E")]
            if task.meeting:
                out.append(Command("Task", "Meeting notes", lambda: self.open_capture(task=tid, meeting=True), "M"))
            out += [Command("Task", "Copy prompt", lambda: self.copy_prompt(tid)),
                    Command("Task", "Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / tid))]
        out += [Command("View", v.label, lambda v=v.id: self.set_view(v)) for v in VIEWS]
        out += [Command("", "New capture", lambda: self.open_capture(), self.ctx.settings.hotkey),
                Command("", "Search everything", self.search_box.setFocus, "Ctrl+Shift+F"),
                Command("", "Find in this view", self.open_find, "Ctrl+F"),
                Command("", "Show or hide the views", lambda: self.show_views_pane(not self.views_button.isChecked()), "Ctrl+B"),
                Command("", "Read docs.db again", self.refresh, "F5"),
                Command("", "Keys", self.show_keys, "F1"),
                Command("", "Hide hints" if LOOK.hints else "Show hints", lambda: self._set_hints(not LOOK.hints))]
        return out

    def open_palette(self) -> None:
        """Ctrl+K: every action and view, narrowed as you type (decision 6)."""
        self._palette = CommandPalette(self, self.palette_commands())
        self._palette.open_over(self)

    def _fill_top_menu(self) -> None:
        """The top bar's More: every key, the command palette and Show hints."""
        menu = self.top_menu
        menu.clear()
        menu.addAction(icon("keyboard"), "Keys\tF1", self.show_keys)
        if hasattr(self, "open_palette"):
            menu.addAction(icon("search"), "Command palette\tCtrl+K", self.open_palette)
        menu.addSeparator()
        hints = menu.addAction("Show hints", lambda: self._set_hints(not LOOK.hints))
        hints.setCheckable(True)
        hints.setChecked(LOOK.hints)

    def _set_hints(self, on: bool) -> None:
        """Show hints, at once in every window, and kept in Settings (decision 7)."""
        set_hints(on)
        self.ctx.settings.show_hints = on
        try:
            self.ctx.settings.save(self.ctx.fs, self.ctx.data_root)
        except OSError as e:
            log.warning("Couldn't keep Show hints in settings.json: %s", e)
        self.render_all()

    def show_views_pane(self, on: bool) -> None:
        """Show or hide the views on the left (mods log round 1, M0012). The choice is kept in docs.db's app_state."""
        self.nav.setVisible(on)
        if self.views_button.isChecked() != on:
            self.views_button.setChecked(on)  # its toggled signal calls this again, which then finds nothing to do
        if db.get_state(self.ctx.conn, VIEWS_HIDDEN_KEY) != ("0" if on else "1"):
            db.set_state(self.ctx.conn, VIEWS_HIDDEN_KEY, "0" if on else "1")

    # ================= the list pane =================
    def _set_head(self, title: str, note: str = "", total: str = "") -> None:
        """The view's title and what it is. ``total`` (such as "18 open") follows the title in the new look, whose sidebar
        counts only what asks for something (O10)."""
        if total and not LOOK.classic:
            self.pane_title.setTextFormat(Qt.TextFormat.RichText)
            self.pane_title.setText(f'{esc(title)}&nbsp;&nbsp;<span style="color:{tokens.colour("text2")}; font-size:{tokens.CAPTION}pt; '
                                    f'font-weight:400">{esc(total)}</span>')
        else:
            self.pane_title.setTextFormat(Qt.TextFormat.PlainText)
            self.pane_title.setText(title)
        self.pane_note.setText(note)
        self.pane_note.setVisible(bool(note))

    def _clear_filters(self) -> None:
        _empty(self.filters_layout)

    def _filter_widget(self, widget: QWidget) -> QWidget:
        self.filters_layout.addWidget(widget)
        return widget

    def _check(self, label: str, on: bool, changed: Callable[[bool], None], tip: str = "") -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(on)
        if tip:
            box.setToolTip(tip)
        box.toggled.connect(changed)
        return self._filter_widget(box)

    def _button(self, label: str, clicked: Callable[[], None], enabled: bool = True, tip: str = "") -> QPushButton:
        b = QPushButton(label)
        b.setEnabled(enabled)
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(lambda _=False: clicked())
        return self._filter_widget(b)

    def render_list(self) -> None:
        self.detail.setVisible(self.view not in ("capacity", "settings", "timeline"))
        if self.view == "capacity":
            self.middle.setCurrentIndex(1)
            self.render_capacity()
            return
        if self.view == "timeline":
            self.middle.setCurrentWidget(self.timeline)
            self.timeline.render(self.model(), self.today())
            return
        if self.view == "settings":
            self.middle.setCurrentIndex(2)
            self.settings_view.load()
            return
        self.middle.setCurrentIndex(0)
        self._clear_filters()
        self.filters.setVisible(True)
        builder = {"today": self._today_view, "tasks": self._tasks_view, "unfiled": self._unfiled_view, "agenda": self._agenda_view,
                   "people": self._people_view,
                   "labels": self._labels_view, "docs": self._docs_view, "search": self._search_view,
                   "discarded": self._discarded_view}.get(self.view)
        self.tree.begin()
        try:
            if builder:
                builder()
            else:
                self._list_view(self.view)
        finally:
            self.tree.end(self.sel)
        self.filters.setVisible(self.filters_layout.count() > 0)
        self._apply_find()

    # ---- Find in this view (mods log round 2, M0026) ----
    def open_find(self) -> None:
        """Ctrl+F: a box above the list that narrows the view you're in as you type."""
        if self.view in ("timeline", "capacity", "settings"):
            self.say("The timeline and capacity have their own filters. Find in this view works on Today, the task tree, the lists, "
                     "Unfiled, Agendas, People, Labels, Documents and Discarded. Ctrl+Shift+F searches everything.")
            return
        self.find_bar.show()
        self.find_box.setFocus()
        self.find_box.selectAll()

    def close_find(self) -> None:
        """Esc in the box, or another view: clear it, and the list shows everything again."""
        self.find_box.blockSignals(True)
        self.find_box.clear()
        self.find_box.blockSignals(False)
        self.find_bar.hide()
        self.find_count.clear()

    def _apply_find(self) -> None:
        """Keep the rows that hold every word typed, each with its parents, faded, for context; closed branches open while
        finding. A task is found by its ID, title, description, current status, labels and people too."""
        words = self.find_box.text().lower().split() if not self.find_bar.isHidden() else []
        if not words:
            self.find_count.clear()
            return
        m = self.model()

        def text_of(item) -> str:
            key = item.data(0, KEY_ROLE)
            cells = " ".join(item.data(i, HTML_ROLE) or "" for i in range(self.tree.columnCount()))
            text = html.unescape(re.sub(r"<[^>]+>", " ", cells)).lower()
            return text + (" " + find_text(m, key[1]) if key and key[0] == "task" and key[1] in m.tasks else "")

        hits = 0

        def visit(item) -> bool:
            nonlocal hits
            hit = item.data(0, KEY_ROLE) is not None and all(w in text_of(item) for w in words)
            hits += hit
            kept = [visit(item.child(i)) for i in range(item.childCount())]
            keep = hit or any(kept)
            item.setHidden(not keep)
            item.setData(0, DIM_ROLE, True if keep and not hit else None)
            if any(kept):
                item.setExpanded(True)
            return keep

        building, self.tree._building = self.tree._building, True  # opening branches here isn't remembered
        try:
            root = self.tree.invisibleRootItem()
            for i in range(root.childCount()):
                visit(root.child(i))
            # A heading row (Today's groups) stays when a row under it does.
            heading = None
            for i in range(root.childCount()):
                item = root.child(i)
                if item.data(0, KEY_ROLE) is None and not item.childCount():
                    heading = item
                elif heading is not None and not item.isHidden():
                    heading.setHidden(False)
                    heading.setData(0, DIM_ROLE, None)
        finally:
            self.tree._building = building
        self.find_count.setText(f"{hits} match{'es' if hits != 1 else ''}" if hits else "Nothing in this view matches")

    def show_keys(self) -> None:
        """F1: every key, in one list (mods log round 2, M0036)."""
        self.run_dialog(KeyMapDialog(self, self.ctx.settings.hotkey))

    # ---- rows ----
    def _task_cells(self, task_id: str, depth: int, context: bool = False, extra: str = "", when: DueDate | None = None,
                    use_due: bool = True) -> list[str]:
        m, t = self.model(), self.model().task(task_id)
        title = esc(t.title)
        if depth == 0:
            title = f"<b>{title}</b>"
        if context:
            return [f'<span style="color:#5a6571">{title}</span>', "", ""]
        if t.state == "Closed":
            title = f'<s><span style="color:#87919c">{title}</span></s>'
        chips = "".join(" " + chip(text, cls) for text, cls in markers(m, t))
        cell = due_cell(t, self.today(), when, use_due)
        colour = {"over": "color:#b0261e; font-weight:600", "soon": "color:#875700; font-weight:600"}.get(cell.cls if cell else "", "")
        mark = '<br><span style="color:#87919c; font-weight:400; font-size:8pt">deadline</span>' if cell and cell.deadline else ""
        due = f'<p align="right" style="{colour}">{esc(cell.text)}{mark}</p>' if cell else ""
        return [title + chips + extra, state_chip(t.state), due]

    def _add_nodes(self, nodes: list[Node], parent=None, filtered: bool = False, expand_all: bool = True,
                   row: Callable[[Node], tuple[list[str], str]] | None = None) -> None:
        m = self.model()
        for n in nodes:
            if n.kind == "group":
                item = self.tree.add_row(parent, None, [f"<b>{esc(n.label)}</b>"], QColor(GREY).lighter(135), selectable=False, span=True)
            elif n.kind == "doc":
                d = m.documents[n.id]
                link = is_link(d.original)
                cells = [f'{esc(d.name)}<br><span class="sub">{esc(d.description or "No description yet")}</span>',
                         chip("Link", "st-ns") if link else chip(d.status, "st-ns" if d.status == "Current" else "st-pk"),
                         f'<p align="right">{esc(short(date.fromisoformat(d.checked[:10]), self.today())) if d.checked else ""}</p>']
                tip = f"{d.original} (double-click copies it)" if link else f"Last checked {d.checked or 'not yet'}"
                item = self.tree.add_row(parent, ("doc", n.id), cells, tint(n.group, n.depth), tip=tip, edge=edge(n.group, n.depth))
            else:
                cells, tip = row(n) if row else (self._task_cells(n.id, n.depth, filtered and not n.match), full_path(m, n.id))
                item = self.tree.add_row(parent, ("task", n.id), cells, tint(n.group, n.depth), tip=tip, edge=edge(n.group, n.depth))
                if self.selecting and n.match and self.view in SELECT_VIEWS:
                    self.tree.add_tick(item, n.id in self.ticked)
            self._add_nodes(n.children, item, filtered, expand_all, row)
            item.setExpanded(expand_all or n.id in self.open)

    def _tasks_view(self) -> None:
        f = self.tree_filter
        filtered = bool(f["labels"] or f["people"])
        m = self.model()
        self._set_head("Task tree", "Dimmed rows don't match the filter. They're parents of tasks that do, shown for context." if filtered else "",
                       f"{sum(1 for t in m.tasks.values() if is_open(t))} open")
        self._check("Show parked", f["parked"], lambda on: self._set_filter("parked", on))
        self._check("Show closed", f["closed"], lambda on: self._set_filter("closed", on))
        self._check("Show routine", f["routine"], lambda on: self._set_filter("routine", on), "Recurring tasks, such as meetings, and their subtasks")
        # Several labels and people at once (mods log round 1, M0018): a task matches with any of each.
        # A parent label ticks its sublabels, and a group its people (release 5.9).
        choices, sets = label_filter(m)
        labels = CheckMenuButton("Labels", "any", choices, f["labels"], sets)
        labels.chosen.connect(lambda values: self._set_filter("labels", values))
        self._filter_widget(labels)
        people_button = CheckMenuButton("People", "anyone", people_filter(m)[0], f["people"], people_filter(m)[1])
        people_button.chosen.connect(lambda values: self._set_filter("people", values))
        people_button.setToolTip(people_button.toolTip() or "Tasks any of the ticked people lead or are assigned")
        self._filter_widget(people_button)
        self._sort_box("tasks")
        self._select_controls()
        nodes = task_tree(m, TreeFilter(parked=f["parked"], closed=f["closed"], routine=f["routine"], labels=tuple(f["labels"]),
                                        people=tuple(f["people"]), pin=self.pin))
        nodes = sort_tree(m, nodes, self.sorts.get("tasks", "default"), self.today())
        self._button("− Collapse a level", lambda: self._level(nodes, "collapse"), collapse_level(nodes, self.open) != self.open,
                     "Fold every branch up one level")
        self._button("+ Expand a level", lambda: self._level(nodes, "expand"), expand_level(nodes, self.open) != self.open,
                     "Open every branch one more level")
        self.tree.set_columns(["Title", "State", "Due"])
        self._add_nodes(nodes, filtered=filtered, expand_all=False)
        if not nodes:
            self.tree.add_row(None, None, ['<span class="sub">No tasks match these filters.</span>'], selectable=False, span=True)

    def _set_filter(self, key: str, value) -> None:
        self.tree_filter[key] = value
        self.render_list()

    def _sort_box(self, view_id: str) -> None:
        """The Sort list for the task tree or a list (mods log round 1, M0015)."""
        box = QComboBox()
        box.setAccessibleName("Sort")
        for key, label in SORTS:
            box.addItem(f"Sort: {label.lower() if key != 'default' else ('tree order' if view_id == 'tasks' else 'soonest first')}", key)
        box.setCurrentIndex(max(0, box.findData(self.sorts.get(view_id, "default"))))
        box.setToolTip("Sorts the tasks under each parent, so the tree keeps its shape")
        box.currentIndexChanged.connect(lambda _: self._set_sort(view_id, box.currentData()))
        self._filter_widget(box)

    def _set_sort(self, view_id: str, how: str) -> None:
        self.sorts[view_id] = how
        self.render_list()

    # ---- Select mode and Edit selected (mods log round 1, M0009) ----
    def _select_controls(self) -> None:
        self._check("Select", self.selecting, self.set_selecting, "Tick tasks in this list, then Edit selected changes them all at once")
        if not self.selecting:
            return
        self._button("Select all shown", lambda: self.tick_shown(True), tip="Tick every task you can see in the list")
        self.clear_ticks_button = self._button("Clear", lambda: self.tick_shown(False), tip="Untick them all")
        self.edit_selected_button = self._button("", self.edit_selected, tip="Change the ticked tasks, after a preview")
        self._sync_edit_selected()

    def set_selecting(self, on: bool) -> None:
        self.selecting = on
        if not on:
            self.ticked.clear()
        self.render_list()

    def _tick(self, key, on: bool) -> None:
        if key[0] == "task":
            (self.ticked.add if on else self.ticked.discard)(key[1])
            self._sync_edit_selected()

    def _sync_edit_selected(self) -> None:
        n = len(self.ticked)
        b = getattr(self, "edit_selected_button", None)
        if b is not None and b.parent() is not None:
            b.setText(f"Edit selected ({n})…" if n else "Edit selected…")
            b.setEnabled(n > 0)
        clear = getattr(self, "clear_ticks_button", None)
        if clear is not None and clear.parent() is not None:
            clear.setEnabled(n > 0)

    def tick_shown(self, on: bool) -> None:
        """Select all shown, or Clear: every task row you can see, not those under a collapsed task."""
        if on:
            self.ticked |= {item.data(0, KEY_ROLE)[1] for item in self.tree.items()
                            if item.data(0, Qt.ItemDataRole.CheckStateRole) is not None and self.tree.is_shown(item)}
        else:
            self.ticked.clear()
        self.render_list()

    def ticked_in_order(self) -> list[str]:
        """The ticked tasks, as the list shows them."""
        shown = [k[1] for k in self.tree.keys() if k and k[0] == "task" and k[1] in self.ticked]
        return list(dict.fromkeys(shown + sorted(self.ticked - set(shown))))

    def edit_selected(self) -> None:
        ids = self.ticked_in_order()
        if not ids:
            self.say("Tick some tasks first.", error=True)
            return
        dialog = BulkEditDialog(self, self.model(), ids, self._label_options, self._people_options,
                                lambda e: bulk.preview(self.conn, self.ctx.settings, ids, e, self._now(), edits.BROWSE),
                                lambda anchor, picked: self._pick_task(anchor, picked, ("None", "Leave them where they are")))
        if self.run_dialog(dialog):
            edit = dialog.edit()
            self._do(lambda: edits.bulk_edit(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, ids, edit, self._now()))

    def _level(self, nodes: list[Node], direction: str) -> None:
        self.open = collapse_level(nodes, self.open) if direction == "collapse" else expand_level(nodes, self.open)
        self.render_list()

    def _expanded(self, item, on: bool) -> None:
        if self.tree._building or self.view != "tasks":
            return
        key = item.data(0, KEY_ROLE)
        if key and key[0] == "task":
            (self.open.add if on else self.open.discard)(key[1])

    def _list_view(self, view_id: str) -> None:
        v, task_list, m = VIEW_IDS[view_id], LIST_IDS[view_id], self.model()
        self._set_head(v.label, v.note + " Dimmed rows are their parents, shown for context.")
        reminders = view_id == "reminders"
        self.tree.set_columns(["Title", "State", "Reminder" if reminders else "Due", ""] if reminders else ["Title", "State", "Due"],
                              [0, 96, 96, 56] if reminders else None)
        self._sort_box(view_id)
        grouped = self._group_box(view_id)
        self._select_controls()
        nodes = sort_tree(m, list_tree(m, task_list, self.today(), self.ctx.settings.me), self.sorts.get(view_id, "default"), self.today())
        if grouped:  # under each sublabel's heading (release 5.9, M0051)
            self._grouped_list(view_id, grouped, nodes)
            return

        def row(n: Node) -> tuple[list[str], str]:
            if not n.match:
                return self._task_cells(n.id, n.depth, context=True), full_path(m, n.id)
            t = m.task(n.id)
            who = f' <span class="sub">{esc(", ".join(m.person_name(p) for p in t.assignees))}</span>' if view_id == "waiting" else ""
            when = list_date(task_list, t, self.today()) if reminders else None
            return self._task_cells(n.id, n.depth, extra=who, when=when, use_due=not reminders), full_path(m, n.id)

        self._add_nodes(nodes, row=row)
        if reminders:
            for item in self.tree.items():
                key = item.data(0, KEY_ROLE)
                if key and key[0] == "task" and m.task(key[1]).reminder and key[1] in {t.id for t in self._matching(task_list)}:
                    b = QPushButton("Clear", objectName="rowLink")
                    b.setToolTip("Clear this reminder. Its status log records it.")
                    b.clicked.connect(lambda _=False, tid=key[1]: self.clear_reminder(tid))
                    self.tree.setItemWidget(item, 3, b)
        if not nodes:
            self.tree.add_row(None, None, ['<span class="sub">Nothing here right now.</span>'], selectable=False, span=True)

    def _group_box(self, view_id: str) -> str | None:
        """The lists' Group by (release 5.9, M0051): a parent label, putting each task under its sublabel's heading. Shown
        when there's a parent label. Returns the parent label picked, if any."""
        m = self.model()
        parents = [lb.name for lb in m.active_labels() if m.is_parent_label(lb.name)]
        if not parents:
            return None
        box = QComboBox()
        box.setAccessibleName("Group by")
        box.addItem("No grouping", "")
        for name in parents:
            box.addItem(f"Group by {name}", name)
        picked = self.list_groups.get(view_id, "")
        box.setCurrentIndex(max(0, box.findData(picked)))
        box.setToolTip("Put each task under its sublabel's heading")
        box.currentIndexChanged.connect(lambda _: self._set_list_group(view_id, box.currentData()))
        self._filter_widget(box)
        return picked if picked in parents else None

    def _set_list_group(self, view_id: str, parent: str) -> None:
        self.list_groups[view_id] = parent
        self.render_list()

    def _grouped_list(self, view_id: str, parent: str, nodes: list[Node]) -> None:
        """A list grouped by a parent label: its matching tasks under each sublabel, then "No …" last."""
        m = self.model()
        order: list[str] = []

        def walk(ns: list[Node]) -> None:
            for n in ns:
                if n.match and n.id not in order:
                    order.append(n.id)
                walk(n.children)

        walk(nodes)
        subs = m.sublabels(parent)
        grey = QColor(GREY).lighter(135)
        for name, ids in [*((s, [x for x in order if any(n == s for n, _ in m.labels_of(x))]) for s in subs),
                          (f"No {parent.lower()}", [x for x in order if not any(n in subs for n, _ in m.labels_of(x))])]:
            if not ids:
                continue
            self.tree.add_row(None, None, [f"<b>{esc(name)}</b> &nbsp;<span class=\"sub\">{len(ids)}</span>"], grey, selectable=False, span=True)
            for x in ids:
                self.tree.add_row(None, ("task", x), self._task_cells(x, 0), tip=full_path(m, x))
        if not order:
            self.tree.add_row(None, None, ['<span class="sub">Nothing here right now.</span>'], selectable=False, span=True)

    def _matching(self, task_list):
        from docrepo.lists import list_tasks

        return list_tasks(self.model(), task_list, self.today(), self.ctx.settings.me)

    def _unfiled_view(self) -> None:
        self._set_head("Unfiled", UNFILED_NOTE)
        self.tree.set_columns(["Capture", "Source", "Saved"])
        rows = unfiled_rows(self.model(), self.today())
        for r in rows:
            self.tree.add_row(None, ("capture", r.id), [f'{esc(r.title)}<br><span class="sub">{esc(r.sub)}</span>', chip(r.source, "st-ns"),
                                                         f'<p align="right">{esc(r.saved)}</p>'])
        if not rows:
            self.tree.add_row(None, None, ['<span class="sub">No unfiled captures.</span>'], selectable=False, span=True)

    def _today_view(self) -> None:
        """Today (mods log round 1, M0016): the day's list, items carried over first, then what's been done today."""
        m, today = self.model(), self.today()
        self._set_head("Today", VIEW_IDS["today"].note)
        # The box makes a quick task, or a note with the switch (mods log round 2, M0039).
        for kind, label in (("task", "Task"), ("note", "Note")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(self.today_kind == kind)
            b.setToolTip("The box makes a quick task, under Quick tasks" if kind == "task" else "The box adds a note to Today")
            b.clicked.connect(lambda _=False, k=kind: self.set_today_kind(k))
            self._filter_widget(b)
        self.today_note = QLineEdit()
        self.today_note.setPlaceholderText("A quick task, such as Call the vendor about seals by Fri" if self.today_kind == "task"
                                           else "A note for today, such as Sign the overtime sheets")
        self.today_note.setMinimumWidth(320)
        self.today_note.returnPressed.connect(self.add_today_item)
        self._filter_widget(self.today_note)
        self._button("Add", self.add_today_item)
        asked = m.tasks.get(self.today_ask) if self.today_ask else None
        if asked:
            self._filter_widget(QLabel(f"<b>{esc(asked.title)}</b> is done for today. Update the task too?"))
            self._button("Update…", lambda: self.answer_today("update"))
            self._button("Close the task…", lambda: self.answer_today("close"))
            self._button("No", lambda: self.answer_today(None))
        self.tree.set_columns(["Item", "State", "Due", ""], [0, 96, 96, 220])
        grey = QColor(GREY).lighter(135)
        for name, items in today_groups(m, today):
            self.tree.add_row(None, None, [f"<b>{esc(name)}</b>"], grey, selectable=False, span=True)
            for a in items:
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                since = chip(f"since {since_text(a.added, today)}", "st-ns") + " " if a.added[:10] < today.isoformat() else ""
                where = esc(path_text(m, t.id) or "Top-level task") if t else "A note"
                note = f" · {esc(a.note)}" if t and a.note else ""
                cell = due_cell(t, today) if t else None
                colour = {"over": "color:#b0261e; font-weight:600", "soon": "color:#875700; font-weight:600"}.get(cell.cls if cell else "", "")
                item = self.tree.add_row(None, key, [f'{esc(t.title if t else a.note)}<br><span class="sub">{since}{where}{note}</span>',
                                                     state_chip(t.state) if t else chip("Note", "st-ns"),
                                                     f'<p align="right" style="{colour}">{esc(cell.text)}</p>' if cell else ""],
                                         tip=f"Added {long_date(date.fromisoformat(a.added[:10]), today)}")
                self.tree.setItemWidget(item, 3, self._today_buttons(a.id, t.id if t else None))
        if not m.today_items():
            self.tree.add_row(None, None, ['<span class="sub">Nothing on Today. Select a task and press D, or type a quick task above.</span>'],
                              selectable=False, span=True)
        self._today_due_rows(m, today, grey)
        done = m.done_on(today)
        if done:
            self.tree.add_row(None, None, ["<b>Done today</b>"], grey, selectable=False, span=True)
            for a in done:
                t = m.tasks.get(a.subject) if a.subject else None
                self.tree.add_row(None, ("task", t.id) if t else None,
                                  [f'<s><span style="color:#87919c">{esc(t.title if t else a.note)}</span></s><br>'
                                   f'<span class="sub">Done at {esc((a.closed or "")[11:16])}</span>',
                                   state_chip(t.state) if t else chip("Note", "st-ns"), ""])

    def _today_due_rows(self, m: Model, today: date, grey: QColor) -> None:
        """Due in the next 7 days (mods log round 2, M0050): tasks overdue or due soon that aren't on Today, each with Add
        to Today. Mine only, remembered in app_state, leaves those I neither lead nor am assigned to."""
        mine = db.get_state(self.conn, TODAY_MINE_KEY) == "1"
        box = QCheckBox("Mine only")
        box.setToolTip("Only tasks you lead or are assigned to, in Due in the next 7 days")
        box.setChecked(mine)
        box.toggled.connect(self.set_today_mine)
        self._filter_widget(box)
        tasks = due_this_week(m, today, self.ctx.settings.me, mine)
        self.tree.add_row(None, None, ["<b>Due in the next 7 days</b>" + (" <span class=\"sub\">· yours</span>" if mine else "")],
                          grey, selectable=False, span=True)
        for t in tasks:
            cell = due_cell(t, today)
            colour = {"over": "color:#b0261e; font-weight:600", "soon": "color:#875700; font-weight:600"}.get(cell.cls if cell else "", "")
            item = self.tree.add_row(None, ("task", t.id), [f'{esc(t.title)}<br><span class="sub">{esc(path_text(m, t.id) or "Top-level task")}</span>',
                                                          state_chip(t.state), f'<p align="right" style="{colour}">{esc(cell.text)}</p>' if cell else ""])
            add = QPushButton("Add to Today", objectName="rowLink")
            add.setToolTip("Put it on Today (D)")
            add.clicked.connect(lambda _=False, i=t.id: self.add_to_today(i))
            holder = QWidget()
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(add)
            lay.addStretch()
            self.tree.setItemWidget(item, 3, holder)
        if not tasks:
            self.tree.add_row(None, None, ['<span class="sub">Nothing else is due in the next 7 days' + (" for you." if mine else ".") + "</span>"],
                              selectable=False, span=True)

    def set_today_mine(self, on: bool) -> None:
        """Mine only, on Today's Due in the next 7 days. The choice is kept in docs.db's app_state."""
        db.set_state(self.conn, TODAY_MINE_KEY, "1" if on else "0")
        self.render_list()

    def _today_buttons(self, item_id: int, task_id: str | None) -> QWidget:
        """A Today item's links. A task has Edit (Edit task, where Parents files a quick task) and Note; a note has Edit and
        Make it a task (mods log round 2, M0040). Then Done and Remove."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        links = ((("Edit", lambda: self.edit_task(task_id), "Edit task, such as putting it under its real task (E)"),
                  ("Note", lambda: self.open_capture(task=task_id, mode="note"), "Add a note, with files, to the task (N)")) if task_id else
                 (("Edit", lambda: self.edit_today_note(item_id), "Change the note's text"),
                  ("Make it a task", lambda: self.make_today_task(item_id), "Make it a quick task, under Quick tasks, in the note's place")))
        for label, clicked, tip in links:
            b = QPushButton(label, objectName="rowLink")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=clicked: c())
            lay.addWidget(b)
        for label, how, tip in (("Done", "Done", "Take it off Today as done"), ("Remove", "Removed", "Take it off Today")):
            b = QPushButton(label, objectName="rowLink")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, h=how: self.close_today_item(item_id, h))
            lay.addWidget(b)
        lay.addStretch()
        return box

    def _discarded_view(self) -> None:
        """Tasks and captures discarded as made by mistake (mods log round 1, M0021), the latest first."""
        self._set_head("Discarded", VIEW_IDS["discarded"].note)
        self.tree.set_columns(["Item", "Why", "Discarded"], [0, 180, 80])
        rows = discarded_rows(self.model(), self.today())
        for r in rows:
            self.tree.add_row(None, (r.kind, r.id), [f'{esc(r.title)}<br><span class="sub">{esc(r.sub)}</span>', esc(r.reason),
                                                      f'<p align="right">{esc(r.when)}</p>'])
        if not rows:
            self.tree.add_row(None, None, ['<span class="sub">Nothing is discarded.</span>'], selectable=False, span=True)

    def _agenda_view(self) -> None:
        m = self.model()
        target = current_target(m, self.target)
        self.target = target
        if not target:
            self._set_head("Agendas", "No agendas yet. Check Meeting on a task to give it an agenda, or put something on an agenda with "
                                      "Add to agenda in the capture window.")
            self.tree.set_columns(["Item", "State", "Added", ""], [0, 96, 70, 130])
            return
        when = m.meeting_when(target, self.today())
        when_text = f" {'Next meeting' if m.task(target).recurrence else 'Date'}: {when}." if when and when != "no date set" else ""
        self._set_head("Agendas", "Open agenda items, grouped by the work they're about. Each stays open, carrying over, until you mark it "
                                  f"Discussed or Remove it.{when_text}")
        pick = QComboBox()
        for x in [TODAY, *m.agenda_targets()]:  # Today first; picking it opens the Today view
            pick.addItem(m.target_name(x) + (" (person)" if is_person(x) else ""), x)
        pick.setCurrentIndex(max(0, pick.findData(target)))
        pick.currentIndexChanged.connect(lambda _: self.show_agenda(pick.currentData()))
        self._filter_widget(QLabel("Agenda for"))
        self._filter_widget(pick)
        self._button("Copy as Markdown", lambda: self.copy_agenda(target))
        meeting = m.tasks.get(target)
        if meeting and meeting.meeting and is_open(meeting):  # release 5.8
            self._button("Meeting notes", lambda: self.open_capture(task=target, meeting=True))
        self.tree.set_columns(["Item", "State", "Added", ""], [0, 96, 70, 130])
        grey = QColor(GREY).lighter(135)
        for name, items in agenda_groups(m, target):
            self.tree.add_row(None, None, [f"<b>{esc(name)}</b>"], grey, selectable=False, span=True)
            for a in items:
                t = m.tasks.get(a.subject) if a.subject else None
                key = ("task", t.id) if t else ("capture", a.added_by) if a.added_by in m.captures else None
                main = esc(t.title if t else a.note)
                note = f'<br><span class="sub">{esc(a.note)}</span>' if t and a.note else ""
                where = f'<br><span class="sub">{esc(path_text(m, t.id) or "Top-level task") if t else "A note, with no task"}</span>'
                item = self.tree.add_row(None, key, [main + note + where, state_chip(t.state) if t else chip("Note", "st-ns"),
                                                     f'<p align="right">{esc(short(date.fromisoformat(a.added[:10]), self.today()))}</p>'],
                                         tip=f"Added {long_date(date.fromisoformat(a.added[:10]), self.today())}")
                self.tree.setItemWidget(item, 3, self._agenda_buttons(a.id))
        closed = closed_items(m, target)
        if closed:
            self.tree.add_row(None, None, ["<b>Closed recently</b>"], grey, selectable=False, span=True)
            for a in closed:
                t = m.tasks.get(a.subject) if a.subject else None
                self.tree.add_row(None, ("task", t.id) if t else None,
                                  [f'<s><span style="color:#87919c">{esc(t.title if t else a.note)}</span></s><br>'
                                   f'<span class="sub">{esc(a.how)} {esc(long_date(date.fromisoformat(a.closed[:10]), self.today()))}</span>',
                                   state_chip(t.state) if t else chip("Note", "st-ns"),
                                   f'<p align="right">{esc(short(date.fromisoformat(a.closed[:10]), self.today()))}</p>'])
        if not agenda_groups(m, target):
            self.tree.add_row(None, None, ['<span class="sub">No open agenda items.</span>'], selectable=False, span=True)

    def _agenda_buttons(self, item_id: int) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        for label, how, tip in (("Discussed", "Discussed", "Close it as discussed, then note the outcome in an update"),
                                ("Remove", "Removed", "Take it off the agenda")):
            b = QPushButton(label, objectName="rowLink")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, h=how: self.close_agenda_item(item_id, h))
            lay.addWidget(b)
        lay.addStretch()
        return box

    def _people_view(self) -> None:
        m = self.model()
        self._set_head("People", "Stored in docs.db. Tasks store a person's ID, so renaming someone changes nothing else.",
                       f"{len(m.active_people())} active")
        self._check("Show retired", self.retired["people"], lambda on: self._set_retired("people", on))
        self._button("Add person", self.add_person)
        # Group and role (mods log round 2, M0033, M0038): the aliases go under the name.
        self.tree.set_columns(["Name", "Group", "Role", "Hours a week", "Open tasks"], [0, 120, 130, 90, 76])
        for p in m.people.values():
            if p.status != "active" and not self.retired["people"]:
                continue
            chips = (" " + chip("me", "st-ip") if p.id == self.ctx.settings.me else "") + (" " + chip("retired", "st-cl") if p.status == "retired" else "") + \
                (" " + chip("new", "new") if p.added_note else "")
            aliases = f'<br><span class="sub">{esc(", ".join(p.aliases))}</span>' if p.aliases else ""
            count = open_count(m, lambda t, pid=p.id: pid in (*t.leads, *t.assignees))
            self.tree.add_row(None, ("person", p.id), [esc(p.name) + chips + aliases, esc(p.group or ""), esc(p.role or ""),
                                                        f'<p align="right">{"–" if p.hours is None else f"{p.hours:g}"}</p>', f'<p align="right">{count}</p>'])

    def _labels_view(self) -> None:
        m = self.model()
        self._set_head("Labels", "Stored in docs.db. Keywords let Parse and populate suggest the label.", f"{len(m.active_labels())} active")
        self._check("Show retired", self.retired["labels"], lambda on: self._set_retired("labels", on))
        self._button("Add label", self.add_label)
        self.tree.set_columns(["Label", "Keywords", "Open tasks"], [0, 200, 76])

        def add(lb, parent_item=None):
            if lb.status != "active" and not self.retired["labels"]:
                return
            # A parent label (release 5.9, M0051) counts the open tasks with any of its sublabels.
            names = {lb.name, *m.sublabels(lb.name, active=False)}
            count = open_count(m, lambda t, ns=names: any(n in ns for n, _ in m.labels_of(t.id)))
            retired = " " + chip("retired", "st-cl") if lb.status == "retired" else ""
            item = self.tree.add_row(parent_item, ("label", lb.name), [esc(lb.name) + retired, esc(", ".join(lb.keywords)), f'<p align="right">{count}</p>'])
            for sub in (x for x in m.labels if x.parent == lb.id):
                add(sub, item)
            item.setExpanded(True)

        for lb in m.labels:
            if lb.parent is None or not any(x.id == lb.parent for x in m.labels):
                add(lb)

    def _set_retired(self, which: str, on: bool) -> None:
        self.retired[which] = on
        self.render_list()

    def _docs_view(self) -> None:
        m = self.model()
        self._set_head("Documents", "Files DocRepo tracks, under the tasks they belong to. Originals stay where they are; their text is kept in Documents.",
                       str(sum(1 for d in m.documents if not m.only_in_discarded(d))))
        self._filter_widget(QLabel("Task"))
        picker = QPushButton((full_path(m, self.doc_task) if self.doc_task in m.tasks else "Any task") + "  ▾")
        picker.clicked.connect(lambda: self._pick_task(picker, self._set_doc_task, ("Any task", "Show every document")))
        self._filter_widget(picker)
        if self.doc_task:
            self._check("Include subtasks", self.doc_subs, self._set_doc_subs)
            self._button("Show all", lambda: self._set_doc_task(None))
        self.tree.set_columns(["Document", "Status", "Checked"])
        nodes = documents_tree(m, self.doc_task if self.doc_task in m.tasks else None, self.doc_subs)
        self._add_nodes(nodes, filtered=True, row=lambda n: (self._task_cells(n.id, n.depth, context=not n.match), full_path(m, n.id)))
        if not nodes:
            self.tree.add_row(None, None, ['<span class="sub">No documents for this task.</span>'], selectable=False, span=True)

    def _set_doc_task(self, task_id: str | None) -> None:
        self.doc_task, self.doc_subs = task_id, True
        self.render_list()

    def _set_doc_subs(self, on: bool) -> None:
        self.doc_subs = on
        self.render_list()

    def _search_view(self) -> None:
        m = self.model()
        results = search.search(self.conn, m, self.query)
        self._set_head(f"Search: {self.query}", f"{len(results)} result{'s' if len(results) != 1 else ''}. Every word you type must be in the item.")
        self.tree.set_columns(["Result"])
        grey, group = QColor(GREY).lighter(135), ""
        for r in results:
            if r.group != group:
                group = r.group
                self.tree.add_row(None, None, [f"<b>{esc(group)}</b>"], grey, selectable=False)
            snippet = f'<br><span class="sub">{esc(r.snippet)}</span>' if r.snippet else ""
            self.tree.add_row(None, (r.kind, r.id), [f'{esc(r.title)}<br><span class="sub">{esc(r.sub)}</span>{snippet}'])
        if not results:
            self.tree.add_row(None, None, ['<span class="sub">No matches.</span>'], selectable=False)

    # ---- capacity ----
    def render_capacity(self) -> None:
        m, today = self.model(), self.today()
        weeks = capacity_weeks(today, self.cap_offset)
        rows = capacity_grid(self.conn, m, weeks)
        # Grouped (release 5.9): each group's people under its heading, then those with no group.
        lines: list[CapacityRow | str] = list(rows)
        if self.cap_by_group.isChecked():
            group_of = {p.id: p.group or "" for p in m.people.values()}
            lines = []
            for g in [*m.groups(), ""]:
                members = [r for r in rows if group_of.get(r.person, "") == g]
                if members:
                    lines += [g or "No group", *members]
        t = self.cap_table
        t.clear()
        t.clearSpans()
        t.setRowCount(len(lines))
        t.setColumnCount(len(weeks) + 1)
        # A week with a plant event names it under its date (M0028).
        bands = timeline_bands(m, weeks[0], weeks[-1] + timedelta(days=7))
        heads = []
        for w in weeks:
            names = [b.title for b in bands if b.start <= w + timedelta(days=6) and b.end >= w]
            heads.append(short(w, today) + ("\n" + ", ".join(names) if names else ""))
        t.setHorizontalHeaderLabels(["Person", *heads])
        for i, w in enumerate(weeks):
            if "\n" in heads[i]:
                t.horizontalHeaderItem(i + 1).setBackground(QColor("#f3e6cc"))
                t.horizontalHeaderItem(i + 1).setToolTip("A plant event this week: " + heads[i].split("\n", 1)[1])
        # Decision 18: neutral under 80%, the accent's tint from 80% to 100%, red over 100% (the Classic look: green, amber, red).
        colours = ({"u1": "#e2f2e6", "u2": "#fcefcf", "u3": "#fbe3e1"} if LOOK.classic else
                   {"u2": tokens.colour("selected"), "u3": tokens.colour("critical_bg")})
        t.setShowGrid(LOOK.classic)
        self._cap_line_rows = lines
        for r, row in enumerate(lines):
            if isinstance(row, str):  # a group's heading
                head = QTableWidgetItem(row)
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                head.setBackground(QColor(GREY).lighter(135))
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                t.setItem(r, 0, head)
                t.setSpan(r, 0, 1, len(weeks) + 1)
                continue
            head = QTableWidgetItem(f"{row.name}\n{'%g h a week' % row.hours_a_week if row.hours_a_week else 'Hours not set'}")
            t.setItem(r, 0, head)
            for i, c in enumerate(row.cells):
                sep = "\n" if LOOK.classic else "  ·  "
                text = f"{c.hours:.1f}" + (f"{sep}{round(c.use * 100)}%" if c.hours and c.use is not None else "") if c.hours else "–"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if LOOK.classic else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c.cls in colours:
                    item.setBackground(QColor(colours[c.cls]))
                if c.cls == "u3" and not LOOK.classic:  # over 100%: red and bold, so it never needs colour alone
                    item.setForeground(QColor(tokens.colour("critical")))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                item.setToolTip(f"{row.name}, week of {long_date(weeks[i], today)}: {c.hours:.1f} h")
                t.setItem(r, i + 1, item)
        t.resizeRowsToContents()
        t.resizeColumnToContents(0)
        height = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(t.rowCount())) + 2 * t.frameWidth() + 2
        t.setFixedHeight(min(height, 420))
        self._cap_rows, self._cap_weeks = rows, weeks
        unestimated, unscheduled = capacity.unplaced(m, today, self.ctx.settings)
        self.cap_detail.setHtml(self.pages().capacity_detail(rows, weeks, self.cap_cell, unestimated, unscheduled))

    def _capacity_clicked(self, row: int, column: int) -> None:
        lines = getattr(self, "_cap_line_rows", self._cap_rows)
        if column == 0 or row >= len(lines) or isinstance(lines[row], str):
            return
        self.cap_cell = (lines[row].person, column - 1)
        self.render_capacity()

    def _move_capacity(self, step: int) -> None:
        self.cap_offset = 0 if step == 0 else self.cap_offset + step
        self.cap_cell = None
        self.render_capacity()

    # ================= the detail pane =================
    def _clear_actions(self) -> None:
        _empty(self.actions_layout)
        self.keytips.clear("actions")

    def _action(self, label: str, clicked: Callable[[], None] | None = None, tip: str = "", enabled: bool = True,
                menu: QMenu | None = None, primary: bool = False, icon_name: str | None = None, key: str = "") -> QPushButton:
        """A command on the detail pane's bar. In the new look it's a subtle button with an icon and its key in the tooltip
        (and under Alt); in the Classic look the key is in its label."""
        if LOOK.classic and key:
            label = f"{label}   {key}"
        b = QPushButton(label, objectName="primary" if primary else "" if LOOK.classic else "subtle")
        b.setToolTip(f"{tip} ({key})" if key and tip and not LOOK.classic else tip)
        if icon_name and not LOOK.classic:
            b.setIcon(icon(icon_name))
        if menu is not None and not LOOK.classic:
            b.setProperty("menu", True)
        if key and not LOOK.classic:
            self.keytips.add(b, key, group="actions")
        b.setEnabled(enabled)
        if menu is not None:
            b.setMenu(menu)
        elif clicked is not None:
            b.clicked.connect(lambda _=False: clicked())
        self.actions_layout.addWidget(b)
        b.show()
        return b

    def render_detail(self, keep_scroll: bool = False) -> None:
        scroll = self.page.verticalScrollBar().value() if keep_scroll else 0
        self._clear_actions()
        self.sync_toolbar()
        s = self.sel
        if s and s[0] == "capture" and s[1] == self.editing:
            self.detail_stack.setCurrentIndex(1)
            self.actions.hide()
            return
        self.detail_stack.setCurrentIndex(0)
        if not s or not self._exists(s):
            self.actions.hide()
            self.page.setHtml('<p class="note">Pick a task, capture or document to see it here.</p>')
            if not LOOK.classic and self.view not in ("capacity", "settings", "timeline"):
                self.detail.hide()  # the list takes the room until something is picked
            return
        if not LOOK.classic and self.view not in ("capacity", "settings", "timeline"):
            self.detail.show()
        self.actions.show()
        pages = self.pages()
        kind, item = s
        if kind == "task":
            self._task_actions(item)
            html = pages.task_page(item, self.state, self.page.page_width())
        elif kind == "capture":
            self._capture_actions(item)
            html = pages.capture_page(item, self._capture_text(item), self._old_versions(item))
        elif kind == "doc":
            self._doc_actions(item)
            html = pages.document_page(item)
        elif kind == "person":
            self._person_actions(item)
            html = pages.person_page(item)
        else:
            self._label_actions(item)
            html = pages.label_page(item)
        self.page.setHtml(html)
        if keep_scroll:
            QTimer.singleShot(0, lambda: self.page.verticalScrollBar().setValue(scroll))

    def _capture_text(self, capture_id: str) -> str | None:
        from docrepo.captures import read_content

        return read_content(self.ctx.data_root, self.model().captures[capture_id])

    def _old_versions(self, capture_id: str) -> int:
        c = self.model().captures[capture_id]
        folder = capture_folder(self.ctx.data_root, c.id, c.saved) / "_old versions"
        try:
            return sum(1 for p in folder.iterdir() if p.name.startswith("capture ") and p.suffix == ".md")
        except OSError:
            return 0

    def sync_toolbar(self) -> None:
        task = self.model().tasks.get(self.sel[1]) if self.sel and self.sel[0] == "task" else None
        for b, verb in ((self.tb_new, "New task under"), (self.tb_update, "Update")):
            b.setEnabled(task is not None)
            b.setToolTip(f"{verb} {task.title}" if task else "Select a task first")

    # ---- the task page's actions ----
    def _task_actions(self, task_id: str) -> None:
        """The task page's command bar (release 5.21, decision 68): Note, Update, Meeting notes for an open meeting, Add to
        (Today and the agendas), Edit, and More at the row's end. The keys and the palette's commands are as they were."""
        m, t = self.model(), self.model().task(task_id)
        if t.discarded:
            self._action("Bring back", lambda: self.bring_back_task(task_id), "Restore it as it was: back in the task tree, the lists and search",
                         primary=True)
            self._action("Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / task_id), f"Open Tasks\\{task_id} in File Explorer")
            return
        menu_key = "   " if LOOK.classic else "\t"  # a menu's key column; the Classic look puts the key after the label
        self._action("Note", lambda: self.open_capture(task=task_id, mode="note"), "Add a note to this task's raw text log", icon_name="note", key="N")
        self._action("Update", lambda: self.open_capture(task=task_id, mode="update"), "Update this task: its state, status, dates and more",
                     icon_name="update", key="U")
        if t.meeting and is_open(t):  # release 5.8
            self._action("Meeting notes", lambda: self.open_capture(task=task_id, meeting=True),
                         "Take this meeting's notes, with its agenda beside them", icon_name="people", key="M")
        add_to = QMenu(self)
        if any(a.subject == task_id for a in m.today_items()):
            add_to.addAction(icon("sun"), "On Today ✓   ·   open the Today view", lambda: self.show_agenda(TODAY))
        else:
            add_to.addAction(icon("sun"), f"Today   ·   your list for today, straight away{menu_key}D", lambda: self.add_to_today(task_id))
        add_to.addSeparator()
        for meeting in meetings_for_menu(m, task_id):
            when = m.meeting_when(meeting.id, self.today())
            act = add_to.addAction(f"{meeting.title}   ·   {meeting.recurrence + ', next ' + when if meeting.recurrence else 'One-off, ' + when}")
            act.triggered.connect(lambda _=False, x=meeting.id: self.open_capture(task=task_id, mode="update", agenda=[x]))
        other = add_to.addAction("Someone else or another task…")
        other.triggered.connect(lambda: self.open_capture(task=task_id, mode="update", agenda_focus=True))
        self._action("Add to", tip="Put it on Today (D) or an agenda", menu=add_to, icon_name="agenda", key="A")
        edit = QMenu(self)
        edit.addAction(f"Edit task…{menu_key}E", lambda: self.edit_task(task_id))
        edit.addSeparator()
        parents = m.parents_of(task_id)
        for p in parents:
            edit.addAction(f"Move from under {m.task(p).title}…", lambda x=p: self._pick_parent(task_id, x))
        if not parents:
            edit.addAction("Put under a task…", lambda: self._pick_parent(task_id, None))
        edit.addAction("Also put under…", lambda: self._pick_parent(task_id, None, also=True)).setEnabled(bool(parents))
        if len(parents) > 1:
            for p in parents:
                edit.addAction(f"Take out from under {m.task(p).title}", lambda x=p: self.move_task(task_id, x, None))
        elif parents:
            edit.addAction("Make it a top-level task", lambda: self.move_task(task_id, parents[0], None))
        edit.addSeparator()
        edit.addAction("Discard…", lambda: self.discard_task(task_id))
        self._action("Edit", tip="Edit any of its fields, move it in the tree, or discard it if it was made by mistake", menu=edit, icon_name="edit")
        # More: New subtask, the agenda, Copy (release 5.9: its people's email addresses, M0031, and each reference field,
        # M0034), Copy prompt for each summary type, and the folder.
        more = QMenu(self)
        more.addAction(icon("add"), f"New subtask{menu_key}T", lambda: self.open_capture(task=task_id, mode="new_task"))
        if self.pages().has_agenda(t):
            more.addAction(icon("agenda"), "Open agenda", lambda: self.show_agenda(task_id))
        copy = QMenu("Copy", more)
        copy.setIcon(icon("copy"))
        people_ids = [*t.leads, *t.assignees]
        if any(m.people[p].email for p in people_ids if p in m.people):
            copy.addAction("Emails of its lead and assignees", lambda: self.copy_emails(people_ids))
        for name, value in t.references.items():
            copy.addAction(f"{name} {value}", lambda n=name: self.copy_reference(task_id, n))
        if copy.actions():
            more.addMenu(copy)
        self.summary_type = QComboBox()
        self.summary_type.setAccessibleName("Summary type")
        self._summary_types = prompts.load_summary_types(self.ctx.data_root)
        self.summary_type.addItems([st.name for st in self._summary_types])
        prompt = more.addMenu(icon("copy"), "Copy prompt")
        for i, st in enumerate(self._summary_types):
            prompt.addAction(st.name, lambda n=i: (self.summary_type.setCurrentIndex(n), self.copy_prompt(task_id)))
        more.addAction(icon("folder"), "Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / task_id))
        b = self._action("More" if LOOK.classic else "", tip="More: New subtask, Open agenda, Copy, Copy prompt and Open folder", menu=more,
                         icon_name="more")
        b.setAccessibleName("More")
        b.setProperty("flowEnd", True)  # at the row's end
        if not LOOK.classic:
            b.setObjectName("iconOnly")
            b.setProperty("menu", False)
            b.style().unpolish(b)
            b.style().polish(b)

    def _capture_actions(self, capture_id: str) -> None:
        m = self.model()
        c = m.captures[capture_id]
        if c.discarded:
            self._action("Bring back", lambda: self.bring_back_capture(capture_id), "Restore it to its tasks' logs and search", primary=True)
            self._action("Show in File Explorer", lambda: self.reveal(capture_md_path(self.ctx.data_root, c)))
            return
        readable = self._capture_text(capture_id) is not None
        self._action("Edit", lambda: self.start_capture_edit(capture_id), "Fix the content text or summary", readable)
        self._action("Show in File Explorer", lambda: self.reveal(capture_md_path(self.ctx.data_root, c)))
        self._action("Discard…", lambda: self.discard_capture(capture_id), "Hide a capture saved by mistake. Its folder stays.")
        if m.is_unfiled(c):
            picked = self.file_to.get(capture_id)
            text = full_path(m, picked) if picked in m.tasks else "Pick a task"
            pick = self._action(f"{text}  ▾", tip="Pick the task to file this capture to")
            pick.clicked.connect(lambda: self._pick_task(pick, lambda tid: self._set_file_to(capture_id, tid), None))
            self._action("File to task", lambda: self.file_capture(capture_id), "File this capture to the picked task", picked in m.tasks, primary=True)
            self._action("Make it a task", lambda: self.open_capture(from_capture=capture_id), "Create a task from this capture, and file it there")

    def _doc_actions(self, document_id: str) -> None:
        m = self.model()
        if is_link(m.documents[document_id].original):
            self._action("Copy link", lambda: self.copy_link(document_id), "Copy the address, to paste into your browser", primary=True)
            return
        source = edits.source_of(self.ctx.data_root, m, document_id)
        self._action("Show in File Explorer", lambda: self.reveal(source) if source else None, "Show the original", source is not None)
        text = self.ctx.data_root / "Documents" / document_id / "extracted.txt"
        self._action("Show extracted text", lambda: self.reveal(text), "Show its extracted.txt", text.exists())

    def _person_actions(self, person_id: str) -> None:
        p = self.model().people[person_id]
        self._action("Edit…", lambda: self.edit_person(person_id))
        if p.email:
            self._action("Copy email", lambda: self.copy_emails([person_id]), "Copy their address. DocRepo never sends email.")
        if p.status == "active":
            self._action("Retire", lambda: self.set_person_status(person_id, "retired"), "Hide this person from pickers and lists. Nothing is deleted.",
                         person_id != self.ctx.settings.me)
        else:
            self._action("Make active", lambda: self.set_person_status(person_id, "active"))
        if self.model().open_items_for(person_id):
            self._action("Open agenda", lambda: self.show_agenda(person_id))

    def _label_actions(self, name: str) -> None:
        label = next(lb for lb in self.model().labels if lb.name == name)
        self._action("Edit…", lambda: self.edit_label(name))
        self._action("Find matching tasks…", lambda: self.find_label_tasks(name),
                     "List the open tasks that mention its keywords but don't have it, to add it to those you tick")
        if label.status == "active":
            self._action("Retire", lambda: self.set_label_status(name, "retired"), "Hide this label from pickers. Its tasks keep it.")
        else:
            self._action("Make active", lambda: self.set_label_status(name, "active"))

    # ---- links on a page ----
    def on_link(self, url: QUrl) -> None:
        kind, _, rest = url.toString().partition(":")
        st = self.state
        if kind == "task":
            self.go_task(rest)
        elif kind == "capture":
            self.go_capture(rest)
        elif kind == "doc":
            self.view = "docs"
            self.select("doc", rest, update_list=True)
        elif kind == "person":
            self.select("person", rest, update_list=True)
        elif kind == "label":
            self.select("label", unquote(rest), update_list=True)
        elif kind == "agenda":
            self.show_agenda(rest)
        elif kind == "show":
            self.reveal_key(tuple(rest.split(":", 1)))
        elif kind == "copylink":
            self.copy_link(rest)
        elif kind in ("tab", "scope", "order"):
            setattr(st, kind, rest)
            self.render_detail(keep_scroll=kind != "tab")
        elif kind in ("chap", "more", "orig"):
            group = {"chap": st.chapters, "more": st.expanded, "orig": st.originals}[kind]
            group.symmetric_difference_update({rest})
            self.render_detail(keep_scroll=True)
        elif kind == "chapall":
            st.chapters = set(self.model().tasks) if rest == "open" else set()
            self.render_detail(keep_scroll=True)
        # The task page's own (release 5.21): Details, the whole description and the closed subtasks, the history's scope
        # and order menus, New subtask, Add one (an update), a reference field's Copy, and the task's folder.
        elif kind == "fold" and rest in ("details", "desc", "closed"):
            setattr(st, rest, not getattr(st, rest))
            self.render_detail(keep_scroll=True)
        elif kind == "menu":
            self._page_menu(rest)
        elif kind == "new":
            self.open_capture(task=rest, mode="new_task")
        elif kind == "update":
            self.open_capture(task=rest, mode="update")
        elif kind == "copyref" and self.sel and self.sel[0] == "task":
            self.copy_reference(self.sel[1], unquote(rest))
        elif kind == "folder" and rest in self.model().tasks:
            self.reveal(self.ctx.data_root / "Tasks" / rest)

    def _page_menu(self, which: str) -> None:
        """The task page's history menus: which tasks' entries it shows, with Open all and Close all chapters, and the
        order (release 5.21)."""
        st, menu = self.state, QMenu(self)

        def pick(name: str, value: str) -> Callable[[], None]:
            return lambda: (setattr(st, name, value), self.render_detail(keep_scroll=True))

        if which == "scope":
            for key, label in SCOPE_NAMES.items():
                act = menu.addAction(label, pick("scope", key))
                act.setCheckable(True)
                act.setChecked(st.scope == key)
            menu.addSeparator()
            menu.addAction("Open all chapters", lambda: self.on_link(QUrl("chapall:open")))
            menu.addAction("Close all chapters", lambda: self.on_link(QUrl("chapall:close")))
        elif which == "order":
            for key, label in (("old", "Oldest first"), ("new", "Newest first")):
                act = menu.addAction(label, pick("order", key))
                act.setCheckable(True)
                act.setChecked(st.order == key)
        else:
            return
        self._menu = menu  # kept, so it stays open and tests can read it
        menu.popup(QCursor.pos())

    def _page_width_changed(self) -> None:
        """The pane crossed a width at which a task page lays itself out differently: draw it again."""
        if self.sel and self.sel[0] == "task" and self.detail_stack.currentIndex() == 0:
            self.render_detail(keep_scroll=True)

    def double_click(self, item: QTreeWidgetItem) -> None:
        """Double-clicking a row opens its edit form (mods log round 3, M0056; decision 57): Edit task for a task, wherever
        it's listed, Edit for a capture (a note on Today edits the note), and Edit… for a person or a label. A document has
        no form yet, so it still shows its file, or copies a link's address. Subtasks open and close by the row's arrow and
        the Right, Left, + and − keys."""
        key = item.data(0, KEY_ROLE)
        if not key:
            return
        kind, ident = key
        m = self.model()
        if kind == "task":
            t = m.tasks.get(ident)
            if t is not None and not t.discarded:
                self.edit_task(ident)
        elif kind == "capture":
            note = next((a for a in m.today_items() if a.subject is None and a.added_by == ident), None) if self.view == TODAY else None
            c = m.captures.get(ident)
            if note is not None:
                self.edit_today_note(note.id)
            elif c is not None and not c.discarded and self._capture_text(ident) is not None:
                self.start_capture_edit(ident)
        elif kind == "person":
            self.edit_person(ident)
        elif kind == "label":
            self.edit_label(ident)
        else:
            self.reveal_key(key)

    def reveal_key(self, key) -> None:
        """Show what a row or link points to in File Explorer."""
        if not key:
            return
        kind, item = key
        m, root = self.model(), self.ctx.data_root
        if kind == "task":
            self.reveal(root / "Tasks" / item)
        elif kind == "capture" and item in m.captures:
            self.reveal(capture_md_path(root, m.captures[item]))
        elif kind == "doc" and item in m.documents:
            if is_link(m.documents[item].original):
                self.copy_link(item)  # a link has no file to show, and is never opened
                return
            source = edits.source_of(root, m, item)
            if source:
                self.reveal(source)
        elif kind == "copy":
            f = next((x for x in m.copies if str(x.id) == item), None)
            if f:
                self.reveal(root / "Tasks" / f.task / "Files" / ("_old versions" if f.old else "") / f.name)

    # ================= navigation =================
    def _row_picked(self, key) -> None:
        self.select(*key)

    def select(self, kind: str, item: str, tab: str | None = None, update_list: bool = False) -> None:
        """Show an item's page. Each task opens with the scope at With subtasks, and its chapters closed."""
        new = (kind, item)
        if new != self.sel:
            if kind == "task":
                self.state = PageState(tab=self.state.tab, order=self.state.order)
            else:
                self.state.chapters, self.state.expanded, self.state.originals = set(), set(), set()
        if tab:
            self.state.tab = tab
        if not (kind == "task" and item == self.pin):
            self.pin = None
        if self.editing and new != ("capture", self.editing):
            self.editing = None
        self.sel = new
        if update_list:
            self.render_nav()
            self.render_list()
        else:
            self.tree.select_key(new)
        self.render_detail()

    def go_task(self, task_id: str, pin: bool = False, tab: str | None = None) -> None:
        """Open a task, in the view it's in when that's a view of tasks, else in the task tree, making sure it shows there."""
        m = self.model()
        if task_id not in m.tasks:
            return
        if m.task(task_id).discarded:
            self.view = "discarded"
            self.select("task", task_id, tab, update_list=True)
            return
        if self.view not in TASK_VIEWS:
            self.view = "tasks"
        if pin:
            self.pin = task_id
        if self.view == "tasks":
            self.open.update(m.chains_of(task_id)[0][:-1])
            t = m.task(task_id)
            if not pin:
                if t.state == "Parked":
                    self.tree_filter["parked"] = True
                if t.state == "Closed":
                    self.tree_filter["closed"] = True
                if all(any(m.task(x).recurrence for x in chain) for chain in m.chains_of(task_id)):
                    self.tree_filter["routine"] = True
        self.select("task", task_id, tab, update_list=True)
        if pin:
            self.pin = task_id

    def go_capture(self, capture_id: str) -> None:
        m = self.model()
        if capture_id not in m.captures:
            return
        if m.captures[capture_id].discarded:
            self.view = "discarded"
        elif m.is_unfiled(m.captures[capture_id]):
            self.view = "unfiled"
        self.select("capture", capture_id, update_list=True)

    def show_agenda(self, target: str) -> None:
        """The Agendas view for one target, with the target's page selected. Today has a view of its own."""
        if target == TODAY:
            self.set_view("today")
            return
        self.view, self.target = "agenda", target
        self.select("person" if is_person(target) else "task", target, update_list=True)

    def set_view(self, view: str) -> None:
        if view not in VIEW_IDS:
            return
        if self.query:
            self.query = ""
            self.search_box.blockSignals(True)
            self.search_box.clear()
            self.search_box.blockSignals(False)
        self.view, self.cap_cell = view, None
        self.ticked.clear()
        self.close_find()
        self._select_first()
        self.render_all()

    def _select_first(self) -> None:
        """What a view selects when it opens."""
        m, v = self.model(), self.view
        new = None
        if v == "today":
            first = next((a.subject for a in m.today_items() if a.subject), None)
            new = ("task", first) if first else None
        elif v == "unfiled":
            caps = m.unfiled_captures()
            new = ("capture", caps[-1].id) if caps else None
        elif v == "docs":
            new = ("doc", next(iter(m.documents))) if m.documents else None
        elif v == "people":
            me = self.ctx.settings.me
            new = ("person", me) if me in m.people else (("person", next(iter(m.people))) if m.people else None)
        elif v == "labels":
            new = ("label", m.labels[0].name) if m.labels else None
        elif v == "discarded":
            first = next(iter(discarded_rows(m, self.today())), None)
            new = (first.kind, first.id) if first else None
        elif v == "agenda":
            target = current_target(m, self.target)
            new = (("person" if is_person(target) else "task"), target) if target else None
        elif v in LIST_IDS:
            ts = self._matching(LIST_IDS[v])
            new = ("task", ts[0].id) if ts else None
        else:
            new = self.sel
            tops = [t for t in m.top_level() if not t.discarded]
            if new is None and tops:
                new = ("task", tops[0].id)
        if new != self.sel:
            if new and new[0] == "task":
                self.state = PageState(tab=self.state.tab, order=self.state.order)
            self.editing = None
        self.sel = new

    def _run_search(self) -> None:
        text = self.search_box.text()
        if len(text.strip()) >= 2:
            if self.view != "search":
                self.before_search = self.view
            self.query, self.view = text.strip(), "search"
            self.render_nav()
            self.render_list()
        elif self.view == "search":
            self.query = ""
            self.view = self.before_search
            self.render_all()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Esc in the search box, or in Find, clears it
        if watched is self.search_box and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.search_box.clear()
            return True
        if watched is getattr(self, "find_box", None) and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.close_find()
            self.render_list()
            self.tree.setFocus()
            return True
        return super().eventFilter(watched, event)

    def _key(self, mode: str) -> None:
        focus = QGuiApplication.focusObject()
        typing = isinstance(focus, (QLineEdit, QPlainTextEdit, QSpinBox)) or (isinstance(focus, QTextEdit) and not focus.isReadOnly()) or (
            isinstance(focus, QComboBox) and focus.isEditable())
        if not typing:
            self.capture_for_selected(mode)

    def _pick_task(self, anchor: QWidget, picked: Callable[[str | None], None], none: tuple[str, str] | None) -> None:
        self._picker = TaskPicker(self, self.model, none)
        self._picker.picked.connect(picked)
        self._picker.setMinimumWidth(max(320, anchor.width()))
        self._picker.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _set_file_to(self, capture_id: str, task_id: str | None) -> None:
        if task_id:
            self.file_to[capture_id] = task_id
        else:
            self.file_to.pop(capture_id, None)
        self.render_detail()

    def open_import(self) -> None:
        """The one-time import of the project list from Excel."""
        from docrepo.ui.import_dialog import ImportDialog

        dialog = ImportDialog(self, self.ctx)
        if dialog.exec() and dialog.outcome:
            self.refresh(render=False)
            self.set_view("tasks")
            self.say(dialog.outcome)

    # ================= the capture window =================
    def open_capture(self, **options) -> None:
        """Open the capture window: on a task with one capture type checked, with an agenda, or to make a task from a capture."""
        if self.capture is None:
            self.say("The capture window isn't running. Start DocRepo with: python -m docrepo app", error=True)
            return
        self.capture.show_capture(**options)

    def capture_for_selected(self, mode: str) -> None:
        """A note (N), a new task under it (T) or an update (U) for the selected task; "agenda" (A) is an update with the
        cursor in Add to agenda (mods log round 1, M0020; the letters from round 2, M0036)."""
        if not (self.sel and self.sel[0] == "task"):
            self.say("Select a task first. The shortcut works on the task that's selected in the browse tool.")
            return
        if mode == "edit":
            self.edit_task(self.sel[1])
        elif mode == "today":
            self.add_to_today(self.sel[1])
        elif mode == "agenda":
            self.open_capture(task=self.sel[1], mode="update", agenda_focus=True)
        elif mode == "meeting":  # M: meeting notes for it, its own if it's a meeting (release 5.8)
            self.open_capture(task=self.sel[1], meeting=True)
        else:
            self.open_capture(task=self.sel[1], mode=mode)

    def capture_saved(self, result: SaveResult) -> None:
        """After the capture window saves: show what it did, as the mockup does."""
        self._model = None
        if not self.isVisible():
            self.dirty = True
            return
        self.refresh(render=False)
        if result.created_task:
            self.go_task(result.created_task, pin=True, tab="notes")
        elif result.agenda_targets and not result.changes:
            self.show_agenda(result.agenda_targets[0])
        elif result.updated_task:
            self.go_task(result.updated_task, pin=True, tab="log")
        elif result.picked_task:
            self.go_task(result.picked_task, pin=True, tab="notes")
        elif result.capture_id:
            self.go_capture(result.capture_id)
        else:
            self.render_all()
        self.say(result.message)

    # ================= changes =================
    def _do(self, change: Callable[[], object], select: tuple[str, str] | None = None) -> object | None:
        """Make a change, then show the result. A change that isn't allowed says why and changes nothing."""
        try:
            out = change()
        except (TaskError, PeopleError, AgendaError, edits.EditError, WriteRefused, OSError, sqlite3.Error, ValueError) as e:
            self.say(str(e), error=True)
            return None
        self.refresh(render=False)
        if select:
            self.sel = select
        self.render_all()
        if isinstance(out, edits.Outcome):
            self.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))
        return out

    def _now(self):
        return self.ctx.now()

    def file_capture(self, capture_id: str) -> None:
        task_id = self.file_to.get(capture_id)
        if not task_id:
            self.say("Pick a task first.", error=True)
            return
        self._do(lambda: edits.file_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, task_id, self._now()), ("capture", capture_id))

    def start_capture_edit(self, capture_id: str) -> None:
        c = self.model().captures[capture_id]
        self.editing = capture_id
        self.edit_title.setText(f"Edit capture {capture_id}")
        self.edit_content.clear()
        # Each @ and # shows by its name; saving keeps them with their IDs again (release 5.8, edits.edit_capture).
        self.edit_content.set_value(items.unstore(self._capture_text(capture_id) or ""), c.formatted)
        self.edit_summary.setPlainText(c.summary or "")
        self._edit_start = (self.edit_content.value(), self.edit_summary.toPlainText())
        self.render_detail()
        self.edit_content.setFocus()

    def cancel_capture_edit(self) -> None:
        if not self.editing:
            return
        changed = (self.edit_content.value(), self.edit_summary.toPlainText()) != self._edit_start
        if changed and not self.confirm(f"Edit capture {self.editing}", "Close without saving your changes?"):
            return
        self.editing = None
        self.render_detail()

    def save_capture_edit(self) -> None:
        capture_id = self.editing
        if not capture_id:
            return
        types = prompts.load_summary_types(self.ctx.data_root)
        default_type = types[0].name if types else None
        content, formatted = self.edit_content.value()
        try:
            out = edits.edit_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, content,
                                     self.edit_summary.toPlainText(), default_type, self._now(), formatted)
        except (edits.EditError, WriteRefused, OSError) as e:
            self.say(str(e), error=True)
            return
        self.editing = None
        self._contents.pop(capture_id, None)
        self.refresh()
        self.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))

    def clear_reminder(self, task_id: str) -> None:
        self._do(lambda: edits.clear_reminder(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now()))

    def close_agenda_item(self, item_id: int, how: str) -> None:
        item = next((a for a in self.model().agenda if a.id == item_id), None)
        if item is None:
            return
        out = self._do(lambda: edits.close_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, how, self._now()))
        if out and how == "Discussed" and item.subject:
            self.open_capture(task=item.subject, mode="update", content=f"Discussed at {self.model().target_name(item.target)}: ")
            self.say(f"{self.model().task(item.subject).title}: discussed. Type what was decided and save, or press Esc to skip.")

    # ---- Today (mods log round 1, M0016) ----
    def add_to_today(self, task_id: str) -> None:
        """T, or Add to Today: the task goes on Today, and the window stays where it is."""
        self._do(lambda: edits.add_to_today(self.conn, self.ctx.data_root, self.ctx.fs, task_id, "", self._now()), self.sel)

    def set_today_kind(self, kind: str) -> None:
        """Today's box makes a quick task ("task") or a note ("note")."""
        self.today_kind = kind
        self.render_list()
        self.today_note.setFocus()

    def add_today_item(self) -> None:
        """Add, or Enter, in Today's box: a quick task, or a note, as its switch says."""
        if self.today_kind == "note":
            self.add_today_note()
        else:
            self.add_today_task()

    def add_today_task(self) -> None:
        """A quick task on Today from the box (mods log round 2, M0039), read by Parse and populate."""
        box = getattr(self, "today_note", None)
        text = box.text().strip() if box is not None else ""
        if not text:
            self.say("Type the task first.", error=True)
            return
        if self._save_quick(lambda: add_quick_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, text, self._now())):
            self.today_note.setFocus()

    def make_today_task(self, item_id: int) -> None:
        """Make it a task, on a note on Today (mods log round 2, M0040): a quick task in the note's place."""
        self._save_quick(lambda: note_to_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, item_id, self._now()))

    def _save_quick(self, make: Callable[[], SaveResult]) -> SaveResult | None:
        try:
            result = make()
        except (SaveError, TaskError, AgendaError, WriteRefused, OSError, sqlite3.Error, ValueError) as e:
            self.say(str(e), error=True)
            return None
        self.refresh(render=False)
        self.sel = ("task", result.created_task)
        self.render_all()
        self.say(result.message + (" Problems: " + " ".join(result.problems) if result.problems else ""), bool(result.problems))
        return result

    def edit_today_note(self, item_id: int) -> None:
        """Edit, on a note on Today (mods log round 2, M0040): change its text."""
        item = next((a for a in self.model().agenda if a.id == item_id), None)
        if item is None:
            return
        text = self.ask_text("Edit the note", "The note on Today:", item.note)
        if text is not None and text.strip() != item.note:
            self._do(lambda: edits.edit_today_note(self.conn, self.ctx.data_root, self.ctx.fs, item_id, text, self._now()), self.sel)

    def add_today_note(self) -> None:
        box = getattr(self, "today_note", None)
        text = box.text().strip() if box is not None else ""
        if not text:
            self.say("Type the note first.", error=True)
            return
        if self._do(lambda: edits.add_to_today(self.conn, self.ctx.data_root, self.ctx.fs, None, text, self._now()), self.sel):
            self.today_note.setFocus()

    def close_today_item(self, item_id: int, how: str) -> None:
        """Done or Remove on Today. Done on a task then asks, in the Today view, whether to update the task too."""
        item = next((a for a in self.model().agenda if a.id == item_id), None)
        if item is None:
            return
        self.today_ask = item.subject if how == "Done" else None
        if not self._do(lambda: edits.close_today_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, how, self._now())):
            self.today_ask = None
            self.render_list()

    def answer_today(self, answer: str | None) -> None:
        """The answer to "Update the task too?": an Update capture starting "Done today: " or "Closed. ", or nothing."""
        task_id, self.today_ask = self.today_ask, None
        self.render_list()
        if task_id and answer:
            self.open_capture(task=task_id, mode="update", content="Done today: " if answer == "update" else "Closed. ")

    def copy_agenda(self, target: str) -> None:
        from docrepo.views import agenda_markdown

        text = agenda_markdown(self.model(), target, self.today())
        QGuiApplication.clipboard().setText(text)
        self.say(f"Agenda copied ({len(text)} characters).")

    def copy_emails(self, person_ids: list[str]) -> None:
        """Copy email addresses, for Outlook's To box (mods log round 2, M0031). DocRepo never sends email."""
        m = self.model()
        found = [m.people[p].email for p in dict.fromkeys(person_ids) if p in m.people and m.people[p].email]
        missing = [m.people[p].name for p in dict.fromkeys(person_ids) if p in m.people and not m.people[p].email]
        if not found:
            self.say("No email address is set" + (f" for {', '.join(missing)}." if missing else "."), error=True)
            return
        QGuiApplication.clipboard().setText("; ".join(found))
        self.say(f"Copied {len(found)} email address{'es' if len(found) > 1 else ''}. Paste into Outlook's To box."
                 + (f" No address set for {', '.join(missing)}." if missing else ""))

    def copy_reference(self, task_id: str, name: str) -> None:
        """Copy a reference field's value (mods log round 2, M0034)."""
        value = self.model().task(task_id).references.get(name, "")
        QGuiApplication.clipboard().setText(value)
        self.say(f"Copied {name} {value}.")

    def copy_link(self, document_id: str) -> None:
        """Put a link's address on the clipboard. DocRepo only copies links; it never opens one (round 1 plan, decision 5)."""
        d = self.model().documents.get(document_id)
        if d is None or not is_link(d.original):
            return
        QGuiApplication.clipboard().setText(d.original.strip())
        self.say(f"Copied the link to {d.name}. Paste it into your browser to open it.")

    def copy_prompt(self, task_id: str) -> None:
        if not self._summary_types:
            self.say("There are no summary types in Config\\prompts.", error=True)
            return
        st = self._summary_types[self.summary_type.currentIndex()]
        blocks = prompts.task_blocks(st, self.model(), task_id, content_of=self.content_of,
                                     file_text_of=lambda d: search.extracted_text(self.ctx.data_root, d))
        text = prompts.prompt_text(st, blocks)
        QGuiApplication.clipboard().setText(text)
        warn = self.ctx.settings.prompt_warn_chars
        self.say(f"Prompt copied ({len(text)} characters)." + (f" That's long (over {warn}); check the LLM takes that much." if len(text) > warn else "")
                 + " Paste the answer into a capture's Summary.")

    # ---- tasks ----
    def _label_options(self, text: str, picked: list[str]) -> list[Option]:
        return label_options(self.model(), text, picked)

    def _people_options(self, text: str, picked: list[str]) -> list[Option]:
        return people_options(self.model(), self.ctx.settings.me, text, picked)

    def edit_task(self, task_id: str) -> None:
        """Edit task (E): every field on one page (mods log round 1, M0008, M0011)."""
        if task_id not in self.model().tasks:
            return
        dialog = TaskEditDialog(self, self.model(), task_id, self._label_options, self._people_options,
                                lambda anchor, picked: self._pick_task(anchor, picked, None),
                                reference_fields=self.ctx.settings.reference_fields, today=self.today())
        if self.run_dialog(dialog):
            self.save_task_edit(task_id, dialog.values())

    def save_task_edit(self, task_id: str, values: dict) -> None:
        self._do(lambda: edits.edit_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now(), **values))

    def _ask_text(self, title: str, label: str, text: str) -> str | None:
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value if ok else None

    # ---- discarding (mods log round 1, M0021) ----
    def _ask_reason(self, title: str, text: str) -> str | None:
        reason, ok = QInputDialog.getText(self, title, text, text=edits.DISCARD_REASON)
        return reason if ok else None

    def discard_task(self, task_id: str) -> None:
        t = self.model().task(task_id)
        reason = self.ask_reason("Discard task", f"Discard {t.title}? It's hidden from the task tree, the lists, the pickers, search and the "
                                                 "capacity calendar, and kept in the Discarded view, where Bring back restores it. Nothing "
                                                 "is deleted.\n\nWhy?")
        if reason is None:
            return
        parent = next(iter(self.model().parents_of(task_id)), None)
        if self._do(lambda: edits.discard_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, reason, self._now()),
                    ("task", parent) if parent else None) is not None and not parent:
            self.sel = None
            self._select_first()
            self.render_all()

    def bring_back_task(self, task_id: str) -> None:
        if self._do(lambda: edits.bring_back_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now())):
            message = self.status.text()
            self.view = "tasks"
            self.go_task(task_id)
            self.say(message)

    def discard_capture(self, capture_id: str) -> None:
        reason = self.ask_reason("Discard capture", f"Discard {capture_id}? It leaves its tasks' raw text logs, the Unfiled view and "
                                                    "search, and is kept in the Discarded view, where Bring back restores it. Its folder "
                                                    "stays, and any changes it made to tasks stay in their status logs.\n\nWhy?")
        if reason is None:
            return
        self._do(lambda: edits.discard_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, reason, self._now()), ("capture", capture_id))

    def bring_back_capture(self, capture_id: str) -> None:
        if self._do(lambda: edits.bring_back_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, self._now())):
            message = self.status.text()
            self.go_capture(capture_id)
            self.say(message)

    def _pick_parent(self, task_id: str, old_parent: str | None, also: bool = False) -> None:
        anchor = self.actions
        self._pick_task(anchor, lambda new: self.move_task(task_id, None if also else old_parent, new) if new else None, None)

    def move_task(self, task_id: str, old_parent: str | None, new_parent: str | None) -> None:
        self._do(lambda: edits.move_task(self.conn, self.ctx.data_root, self.ctx.fs, task_id, old_parent, new_parent, self._now()))

    # ---- people and labels ----
    def add_person(self) -> None:
        dialog = PersonDialog(self, new=True, groups=self.model().groups())
        if self.run_dialog(dialog):
            self.save_person(None, *dialog.values(), **dialog.details())

    def edit_person(self, person_id: str) -> None:
        p = self.model().people[person_id]
        dialog = PersonDialog(self, p.name, p.aliases, p.hours, email=p.email, group=p.group, role=p.role, groups=self.model().groups())
        if self.run_dialog(dialog):
            self.save_person(person_id, *dialog.values(), **dialog.details())

    def save_person(self, person_id: str | None, name: str, aliases: list[str], hours: float | None,
                    email: str | None = None, group: str | None = None, role: str | None = None) -> None:
        """Save a person. ``email``, ``group`` and ``role`` (release 5.9): None leaves them as they are, "" clears them."""
        details = {k: v for k, v in (("email", email), ("group", group), ("role", role)) if v is not None}

        def change():
            pid = person_id or people.add_person(self.conn, name, aliases=aliases, hours=hours, **details)
            if person_id:
                people.update_person(self.conn, person_id, name=name, aliases=aliases, hours=hours, **details)
            out = edits.Outcome(f"Saved {name} ({pid}).")
            edits.write_all_pages(self.conn, self.ctx.data_root, self.ctx.fs, self._now(), out.problems)
            self._saved_person = pid
            return out
        self._do(change)
        if getattr(self, "_saved_person", None):
            self.select("person", self._saved_person, update_list=True)

    def set_person_status(self, person_id: str, status: str) -> None:
        if status == "retired" and person_id == self.ctx.settings.me:
            self.say("You can't retire yourself. Pick someone else as me in Settings first.", error=True)
            return
        def change():
            people.update_person(self.conn, person_id, status=status)
            name = Model(self.conn).people[person_id].name
            return edits.Outcome(f"{name} is {'retired: hidden from pickers and lists' if status == 'retired' else 'active again'}.")
        self._do(change)

    def _parent_choices(self) -> list[str]:
        """The labels another can go under: active ones that aren't under one themselves (one level, mods log round 2, M0051)."""
        return [lb.name for lb in self.model().active_labels() if lb.parent is None]

    def add_label(self) -> None:
        dialog = LabelDialog(self, new=True, parents=self._parent_choices())
        if self.run_dialog(dialog):
            self.save_label(None, *dialog.values(), under=dialog.under())

    def edit_label(self, name: str) -> None:
        m = self.model()
        label = m.label(name)
        dialog = LabelDialog(self, label.name, label.keywords, under=m.parent_label(name), parents=self._parent_choices(),
                             has_sublabels=m.is_parent_label(name))
        if self.run_dialog(dialog):
            self.save_label(name, *dialog.values(), under=dialog.under())

    def save_label(self, old_name: str | None, name: str, keywords: list[str], under: str | None | object = ...) -> None:
        """Save a label. A new label, or new keywords, then lists the open tasks that mention them (mods log round 1, M0014).
        ``under`` (release 5.9): the label it goes under, None for none; left out, it stays where it is."""
        before = next((lb.keywords for lb in self.model().labels if lb.name == old_name), None) if old_name else None

        def change():
            if old_name:
                people.update_label(self.conn, old_name, new_name=name if name != old_name else None, keywords=keywords,
                                    **({} if under is ... else {"parent": under}))
            else:
                people.add_label(self.conn, name, keywords, parent=None if under is ... else under)
            out = edits.Outcome(f"Saved the label {name}.")
            edits.write_all_pages(self.conn, self.ctx.data_root, self.ctx.fs, self._now(), out.problems)
            return out
        if self._do(change, ("label", name)):
            self.select("label", name, update_list=True)
            if before is None or before != next(lb.keywords for lb in self.model().labels if lb.name == name):
                self.find_label_tasks(name, quiet=True)

    def find_label_tasks(self, name: str, quiet: bool = False) -> None:
        """Find matching tasks: the open tasks that mention a label's keywords but don't have it, to tick and add it to.
        ``quiet`` says nothing when there are none, as after saving a label."""
        matches = bulk.label_matches(self.model(), name)
        if not matches:
            if not quiet:
                self.say(f"No open task mentions {name}'s keywords without having the label already.")
            return
        dialog = LabelMatchDialog(self, self.model(), name, matches, lambda ids: self._do(lambda: edits.bulk_edit(
            self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, ids, bulk.BulkEdit(add_labels=[name]), self._now())))
        self.run_dialog(dialog)

    def set_label_status(self, name: str, status: str) -> None:
        def change():
            people.update_label(self.conn, name, status=status)
            return edits.Outcome(f"{name} is {'retired: hidden from pickers' if status == 'retired' else 'active again'}.")
        self._do(change)


def _empty(layout) -> None:
    """Take every widget out of a layout at once, so none is left showing until Qt deletes it."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item else None
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
