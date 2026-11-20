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

import json
import sqlite3
from collections.abc import Callable, Collection
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import activity, bulk, capacity, captures, db, edits, items, notes_page, opener, outlook, people, pins, prompts, search, whatif
from docrepo.agenda import AgendaError
from docrepo.captures import capture_folder, capture_md_path
from docrepo.dates import workday_numbers
from docrepo.detail import PageState, Pages, esc
from docrepo.links import is_folder, is_link
from docrepo.model import TODAY, Model, is_person
from docrepo.people import PeopleError
from docrepo.safe_fs import WriteRefused
from docrepo.save import EmailItem, SaveError, SaveResult, add_quick_task, note_to_task
from docrepo.tasks import TaskError
from docrepo.ui.context import AppContext
from docrepo.ui.dialogs import LabelDialog, PersonDialog
from docrepo.ui.lists import review as review_list
from docrepo.ui.lists import glossaries as glossary_list
from docrepo.ui.lists import tagged as tagged_list
from docrepo.ui.rich_edit import RichEdit
from docrepo.ui.explorer import show_in_explorer
from docrepo.ui.front import bring_to_front
from docrepo.ui.problems import ProblemsLine
from docrepo.ui.content_card import CARD_GAP, CARD_PAD, ContentCard
from docrepo.ui.toast import Toast
from docrepo.ui.settings_view import SettingsView
from docrepo.ui.search_scope import ScopeList, open_search
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK, Help, KeyTips, set_hints, tip
from docrepo.ui.nav_pane import WIDTH as NAV_WIDTH, NavPane
from docrepo.ui.page_view import PageView
from docrepo.ui.task_pane import TaskPane
from docrepo.ui.templates_view import TemplatesPane
from docrepo.ui.tree_import import TreeFilesPane
from docrepo.ui.priorities_view import PrioritiesView
from docrepo.ui.palette import GLOSSARY_LOOKUP, RECENT_CAPTURES, Command, CommandPalette, summary_commands
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.task_forms import LabelMatchDialog, TaskEditDialog
from docrepo.ui.task_picker import TaskPicker
from docrepo.ui.timeline_view import TimelineView
from docrepo.ui.state_menu import MAKE_TASK as STATE_MAKE_TASK
from docrepo.ui.state_menu import UNDO_MS, can_change, open_below, picked_line, state_menu
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE, RowTree
from docrepo.ui import conversation_page, people_import, task_menus, task_open, tidy_follow_ups, tidy_notes, today_meetings
from docrepo.ui import workspace as workspace_ui
from docrepo.ui import task_tile as tile_ui
from docrepo.ui.widgets import SAVE_KEYS, FlowLayout, Option, ViewStack, ask, label_options, people_options
from docrepo.views import (
    LIST_IDS,
    RETIRED_VIEWS,
    TASK_VIEWS,
    VIEW_IDS,
    VIEWS,
    today_order,
    current_target,
    discarded_rows,
    view_counts,
)
from docrepo.ui.lists.base import ListBasics
from docrepo.ui.lists.tasks import TaskLists
from docrepo.ui.lists.today import TodayList
from docrepo.ui.lists.agendas import AgendaList
from docrepo.ui.lists.people_labels import PeopleAndLabelLists
from docrepo.ui.lists.documents import DocumentLists
from docrepo.ui.lists.captures import CaptureLists
from docrepo.ui.lists.activity import ActivityList
from docrepo.ui.lists.planning import PlanningHooks
from docrepo.ui.lists.page_commands import PageCommands
from docrepo.ui.lists.notes_pages import NotesPages
from docrepo.ui.lists.common import (  # noqa: F401 - the helpers, here as before
    _answers,
    _cols,
    _due_css,
    _due_html,
    _empty,
    _row_state,
    _row_word,
    _shape,
    ACT_ICONS,
    DETAIL_MIN,
    log,
    NAV_FOLDED_KEY,
    NESTING_VIEWS,
    NO_HEADINGS,
    priorities_of,
    ROW_DENSITY,
    SELECT_VIEWS,
    SOURCE_ICONS,
    TIMELINE_OPEN_KEY,
    TIMELINE_VIEW_KEY,
    TODAY_MINE_KEY,
    UNFILED_NOTE,
    VIEWS_HIDDEN_KEY,
    WINDOW_TITLE,
)

#: What other modules and the tests read from here (release 5.95): the window, and names that lived here before the move.
__all__ = ["BrowseWindow", "DETAIL_MIN", "HTML_ROLE", "NAV_FOLDED_KEY", "TODAY_MINE_KEY", "_answers", "priorities_of"]

#: The views with no page beside them (release 5.159): their own page fills the window, so a selection's page isn't drawn.
NO_PAGE_VIEWS = ("capacity", "settings", "timeline", "priorities")


def _in_bar(item) -> bool:
    """Whether a filter bar's item shows: a widget unless it was hidden on purpose (release 5.151). A widget a view has just
    added reads as hidden until Qt shows it a moment later, so the bar of a view made only of new widgets (People, Labels,
    Tagged labels, Templates, Activity, Assigned to me) was hidden whole since release 5.61, which meant to hide only a bar
    with nothing showing in it."""
    w = item.widget() if item is not None else None
    if w is None:
        return item is not None and not item.isEmpty()
    return not (w.isHidden() and w.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide))


class BrowseWindow(ListBasics, TaskLists, TodayList, AgendaList, PeopleAndLabelLists, DocumentLists, CaptureLists, ActivityList, PlanningHooks, PageCommands, NotesPages, QWidget):
    """The browse tool's window. ``capture`` is the capture window it opens for new captures and updates."""

    def __init__(self, ctx: AppContext, capture=None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.ctx = ctx
        self.capture = capture
        ctx.save_open_pages = self.save_open_notes  # before the capture window adds a note to a page (release 5.69)
        ctx.open_capture_page = lambda cid: (self.show_browse(), self.go_capture(cid))  # an email captured before (release 5.93)
        self.setObjectName("browse")
        # The grey frame (release 5.182, decision 851): this window alone, as four others share its object name.
        self.setProperty("frame", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(WINDOW_TITLE)
        self.setStyleSheet(style_sheet())
        #: Shows a file in File Explorer. Tests replace it.
        self.reveal: Callable[[Path], bool] = show_in_explorer
        #: What hands a checked link to the browser (release 5.67): Windows' "open", or a stand-in in the tests.
        self.link_starter: Callable[[str], None] | None = None
        #: Asks a yes-or-no question. Tests replace it.
        self.confirm: Callable[[str, str], bool] = lambda title, text: ask(self, title, text, *_answers(title, text))
        #: Shows a form and waits for it: true when it was saved. Tests replace it.
        self.run_dialog: Callable[[QDialog], bool] = lambda dialog: bool(dialog.exec())
        #: Asks why something is discarded: the reason, or None to cancel. Tests replace it.
        self.ask_reason: Callable[[str, str], str | None] = self._ask_reason
        self.ask_text: Callable[[str, str, str], str | None] = self._ask_text
        #: Picks a tagged label to add by hand (release 5.79): from the glossary's labels or typed, or None. Tests replace it.
        self.pick_tagged: Callable[[list[str]], str | None] = lambda names: tagged_list.pick(self, names)
        self.view = "tasks"
        self.sel: tuple[str, str] | None = None
        self.pin: str | None = None
        self.tree_filter = {"parked": False, "closed": False, "routine": True, "labels": [], "people": [], "priorities": [], "urgent": False}
        #: Each task view's sort order (views.SORTS); "default" is its own order.
        self.sorts: dict[str, str] = {}
        self.list_groups: dict[str, str] = {}  # each list's Group by: a parent label (release 5.9)
        self.tree_group = ""  # the task tree's Group by (release 5.24): views.TREE_GROUPS, or "pl:" and a parent label
        #: The rows folded by hand in each view but the task tree (release 5.24), so they stay folded when it's drawn again.
        self.shut: dict[str, set] = {}
        #: The Activity view's choices (release 5.23): its window, grouping and filters, Select and its ticks ("t:" a task,
        #: "l:" a line), the agenda Add to agenda puts them on, and the line clicked last.
        self.act: dict = {"win": "week", "from": None, "to": None, "group": "top", "people": [], "labels": [], "kinds": [],
                          "select": False, "picked": set(), "target": None, "line": None}
        self._act_lines: dict[str, activity.Line] = {}
        #: Select mode (mods log round 1, M0009): tick boxes on the task tree's and the lists' rows, for Edit selected.
        self.selecting = False
        self.ticked: set[str] = set()
        #: A task just marked Done on Today: the Today view asks whether to update it too (mods log round 1, M0016).
        self.today_kind = "task"  # what Today's box makes: a quick task, or a note
        self.open: set[str] = set()
        self.doc_task: str | None = None
        self.doc_subs = True
        self.target: str | None = None
        self.retired = {"people": False, "labels": False}
        self.glossary_find = ""  # the Glossaries view's Find in rows (release 5.171, decision 804)
        self.tagged_mentioned: bool | None = None  # the Tagged labels view's Mentioned only (release 5.79); None: not set yet
        self.query = ""
        self.before_search = "tasks"
        self.state = PageState(order="new")  # the history reads newest first (release 5.84, R6)
        self.file_to: dict[str, str] = {}
        self.editing: str | None = None
        self._edit_start: tuple[str, str] = ("", "")  # the capture edit's text and summary as it opened
        self.dirty = True
        self._contents: dict[str, tuple[int, str]] = {}
        self._placed = False
        #: The open Task views (releases 5.34 and 5.35): one window per task.
        self.task_views: dict = {}
        self.last_task_view: str | None = None
        #: The Templates view (release 5.44): its list, pages and forms.
        self.templates = TemplatesPane(self)
        self.tree_files = TreeFilesPane(self)
        self._build()
        # One letter per topic (mods log round 2, M0036): N note, T new task, U update, A agenda, E edit, D Today, and
        # M meeting notes (release 5.8).
        for keys, handler in (("N", lambda: self._key("note")), ("T", lambda: self._key("new_task")), ("U", lambda: self._key("update")),
                              ("A", lambda: self._key("agenda")), ("E", lambda: self._key("edit")), ("D", lambda: self._key("today")),
                              ("M", lambda: self._key("meeting")), ("O", lambda: self._key("find_files")),
                              ("Ctrl+F", self.open_find), ("Ctrl+Shift+F", lambda: open_search(self.search_box)), ("F1", self.show_keys), ("F5", self.read_again),
                              ("Ctrl+B", lambda: self.show_views_pane(not self.views_button.isChecked())), ("Ctrl+K", self.open_palette),
                              # The weekly review (release 5.128): R marks a project reviewed in step 4.
                              ("R", lambda: None if self._typing() else review_list.mark_reviewed(self)),
                              # Work on it (release 5.152, the workspace plan's decision 663): the selected task's workspace.
                              ("W", lambda: workspace_ui.work_key(self))):
            QShortcut(QKeySequence(keys), self, handler)
        # Review's Next and Back (release 5.128) work from the list pane, so the task page keeps its own Alt+Left, back to
        # All notes (release 5.140): two shortcuts on one key where focus is would fire neither.
        for keys, handler in (("Alt+Right", lambda: review_list.go(self)), ("Alt+Left", lambda: review_list.go(self, back=True))):
            QShortcut(QKeySequence(keys), self.middle, context=Qt.ShortcutContext.WidgetWithChildrenShortcut, activated=handler)
        if capture is not None:
            capture.saved.connect(self.capture_saved)

    # ================= building the window =================
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QWidget(objectName="toolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)  # with 32 px controls, a 48 px bar (release 5.182, decision 852)
        bl.setSpacing(8)
        self.keytips = KeyTips(self)
        # The visual overhaul's O5: an icon button folds the sidebar
        self.views_button = QToolButton(objectName="iconButton")
        # grey whether the sidebar shows or not: it isn't one of the accent's six jobs (release 5.182, decision 844)
        self.views_button.setIcon(icon("sidebar", on=tokens.colour("text2")))
        self.views_button.setFixedSize(tokens.ICON_BUTTON, tokens.ICON_BUTTON)
        self.views_button.setAccessibleName("Views")
        self.views_button.setCheckable(True)
        tip(self.views_button, "Hide or show the list of views on the left", "Ctrl+B")
        self.keytips.add(self.views_button, "Ctrl+B", ctrl=True)
        bl.addWidget(self.views_button)
        self.search_box = QLineEdit(objectName="topSearch")  # a soft fill on the frame (release 5.182, decision 852)
        self.search_box.setPlaceholderText("Search everything: tasks, captures, documents and people")
        tip(self.search_box, "Search everything. Narrow it as File search does: type:pdf, type:notes, type:decision, from:name, after:1 sep, is:pinned, tag:V-110, or a #task first", "Ctrl+Shift+F")
        self.search_box.addAction(icon("search", tokens.colour("text3")), QLineEdit.ActionPosition.LeadingPosition)
        self.search_box.setMaximumWidth(560)
        self.keytips.add(self.search_box, "Ctrl+Shift+F", ctrl=True)
        self.search_box.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)
        self.search_box.textChanged.connect(lambda _: self._search_timer.start())
        self.search_box.installEventFilter(self)
        self.search_scope = ScopeList(self.search_box, self.model, self)  # "#" lists tasks to search in (release 5.108)
        bl.addWidget(self.search_box, 1)
        bl.addStretch(0)
        # The last save's problems until they're opened (release 5.91, the review's F12): in the top bar since release 5.182
        # (decision 853), an amber pill beside New capture, as it has to outlast the messages at the bottom.
        self.problems_line = ProblemsLine(self.ctx.problem_log, lambda path: self.reveal(path))
        self.problems_line.setObjectName("problemsLine")
        bl.addWidget(self.problems_line)
        new = QPushButton("New capture", objectName="primary")
        new.setIcon(icon("add", tokens.colour("on_accent")))
        tip(new, "A new note, task or update in the capture window", self.ctx.settings.hotkey)
        new.clicked.connect(lambda: self.open_capture())
        self.tb_new = QPushButton("New task")
        self.tb_new.clicked.connect(lambda: self.capture_for_selected("new_task"))
        self.tb_update = QPushButton("Update")
        self.tb_update.clicked.connect(lambda: self.capture_for_selected("update"))
        keys = QPushButton("Keys")
        keys.setToolTip("Every key, in one list")
        keys.clicked.connect(self.show_keys)
        for w in (new, self.tb_new, self.tb_update, keys):
            bl.addWidget(w)
        # New task and Update act on the selected task: they're on its command bar; the keys are in More
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
        self.split.setObjectName("browseSplit")  # its handles unpainted: the card draws the line (release 5.182)
        # The visual overhaul's O10 (release 5.22): a sidebar of its own, not the tree.
        # Capacity is under the Timeline now, on one page (decision 229), and its key and other routes lead there.
        self.nav = NavPane([v for v in VIEWS if v.id != "capacity"])
        self.nav.picked.connect(self.set_view)
        self.nav.folded.connect(self._nav_folded)
        self.nav.setMinimumWidth(NAV_WIDTH)  # the sidebar keeps its width, so its names aren't cut; the room comes from the list
        self.split.addWidget(self.nav)

        self.middle = ViewStack()
        list_page = QWidget()
        lp = QVBoxLayout(list_page)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(0)
        head = QWidget(objectName="paneHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(16, 12, 16, 10)
        hl.setSpacing(8)
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
        self.find_box.setPlaceholderText("Find in this view")
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
        # A task's state from its row (release 5.76, round 7's item 101): a State cell opens the state menu, and a task row's
        # right-click menu has it as a submenu.
        self.tree.state_clicked = self.popup_state_menu
        self.tree.state_menu = lambda task_id, parent: self.state_menu_for(task_id, parent)
        # One Edit and one Add to (release 5.98, decision 392): a task row's menu has them too, from the task page's own lists;
        # in Waiting on others, Ask for an update first (release 5.125, the cold-eyes plan's decision 481).
        # The weekly review's Waiting step too (release 5.128).
        self.tree.task_menus = lambda task_id, menu: task_menus.add_row_menus(self, task_id, menu, anchor=self.tree, ask=self._asks())
        # The task tile's one menu (release 5.138, the task tile plan's decision 573): Open, the row's own lines, State, Add to,
        # Ask for an update, Log progress, Note, Update, New task under, Edit, Priority and Copy, in every view of tasks; Ask
        # for an update first among a waiting list's own (Waiting on others, the review's Waiting step).
        # Work on it on every tile's menu, first where Enter and a double-click open the workspace: as Settings' Open a task in
        # says since release 5.174 (decision 815; on Today only until then, the workspace plan's decisions 663 and 667).
        self.tree.tile_menu = lambda task_id, menu, own: tile_ui.fill_menu(self, task_id, menu, own, anchor=self.tree, ask_first=self._asks())
        self.tree.task_opened = lambda task_id: workspace_ui.open_row(self, task_id)  # Enter, as a double-click; Shift the other way
        lp.addWidget(self.tree, 1)
        self.middle.addWidget(list_page)
        self.settings_view = SettingsView(self.ctx, self.say, lambda title, text: self.confirm(title, text),
                                          lambda path: self.reveal(path), lambda: self.open_import())
        self.middle.addWidget(self.settings_view)
        self.timeline = TimelineView()  # mods log round 1, M0019; round 4, M0067 (releases 5.29 and 5.30)
        self.timeline.open_ids = set(filter(None, (db.get_state(self.ctx.conn, TIMELINE_OPEN_KEY) or "").split(",")))
        self.timeline.open_task.connect(lambda task_id: self.go_task(task_id))
        self.timeline.update_task.connect(lambda task_id: self.open_capture(task=task_id, mode="update"))
        self.timeline.folds_changed.connect(lambda ids: self.ctx.keep_state(TIMELINE_OPEN_KEY, ",".join(ids)))
        try:  # its range, Order by, the bars' colour, Hours and Show routine, as left last time
            self.timeline.restore(json.loads(db.get_state(self.ctx.conn, TIMELINE_VIEW_KEY) or "{}"))
        except ValueError:
            pass
        self.timeline.settings_changed.connect(lambda kept: self.ctx.keep_state(TIMELINE_VIEW_KEY, json.dumps(kept)))
        self.timeline.set_dates.connect(self.set_timeline_dates)
        self.timeline.set_key_date.connect(self.set_timeline_key_date)
        self.timeline.quick_edit.connect(self.quick_edit)
        self.timeline.edit_task.connect(self.edit_task)  # a double-click (release 5.91)
        self.timeline.load_cells = lambda weeks: capacity.week_cells(self.ctx.conn, weeks)
        self.timeline.load_unplaced = lambda m, today: capacity.unplaced(m, today, self.ctx.settings)
        self.timeline.workdays = self._workdays  # a Duration's days while it's dragged (release 5.48)
        self.timeline.add_person.connect(self.add_person)
        # What-ifs (release 5.64): kept in app_state; what one would do is worked out in a transaction always rolled back.
        self.timeline.whatifs = whatif.load_all(self.ctx.conn)
        self.timeline.whatifs_changed.connect(lambda: whatif.save_all(self.ctx.conn, self.timeline.whatifs))
        self.timeline.picture_of = self.whatif_picture
        self.timeline.apply_whatif.connect(self.apply_whatif)
        self.timeline.said.connect(self.say)
        self.timeline.card_menu.connect(lambda task_id, at: self.card_menu(task_id, at))
        self.timeline.confirm = lambda title, text: self.confirm(title, text)
        self.timeline.run_dialog = lambda dialog: self.run_dialog(dialog)
        self._whatif_held: tuple | None = None
        self.quick_window = None
        self.middle.addWidget(self.timeline)
        self.priorities = PrioritiesView()  # mods log round 2, M0029, M0030 (release 5.23)
        self.priorities.picked.connect(lambda task_id: setattr(self, "sel", ("task", task_id)))
        self.priorities.open_task.connect(lambda task_id: task_open.open_task(self, task_id, other=task_open.shift_held()))  # release 5.174, decision 815
        self.priorities.state_clicked.connect(lambda task_id, at: self.popup_state_menu(task_id, at))  # decision 564
        self.priorities.edit_task.connect(self.edit_task)
        self.priorities.moved.connect(self.move_priority)
        self.priorities.nudged.connect(self.nudge_priority)
        self.priorities.card_menu.connect(lambda task_id, at: self.card_menu(task_id, at))
        self.middle.addWidget(self.priorities)
        self.split.addWidget(self.middle)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        self.actions = QWidget(objectName="actions")
        self.actions_layout = FlowLayout(self.actions, spacing=4)
        self.actions_layout.setContentsMargins(16, 10, 16, 2)
        dl.addWidget(self.actions)
        detail.setMinimumWidth(DETAIL_MIN)
        self.detail_stack = ViewStack()
        self.page = PageView()
        self.page.setOpenLinks(False)
        self.page.setOpenExternalLinks(False)
        self.page.document().setDefaultStyleSheet(page_css())
        # 32, so a person's, a capture's and a document's page start where the task page does (release 5.182)
        self.page.document().setDocumentMargin(32)
        self.page.anchorClicked.connect(self.on_link)
        self.page.link_menu = self.page_link_menu  # a task's link: the tile's menu (release 5.138)
        self.page.layout_changed.connect(self._page_width_changed)
        self.detail_stack.addWidget(self.page)
        self.detail_stack.addWidget(self._build_edit_form())
        # A task's page with its notes page (release 5.25): its facts, the notes and its history in one scroll.
        # The page's left edge is 24 px in from the pane (release 5.113, decision 423), so a section's
        # chevron can hang in the margin and every title, grid and frame starts on that one edge.
        self.task_pane = TaskPane(page_css(), 24)
        for view in self.task_pane.views():
            view.anchorClicked.connect(self.on_link)
            view.link_menu = self.page_link_menu  # a subtask's link or circle: the tile's menu (release 5.138, decision 577)
        self.task_pane.layout_changed.connect(self._page_width_changed)
        # Which groups are open on each task's page (release 5.84), kept in docs.db like the notes' folds.
        self.task_pane.header.fold_changed.connect(self._save_page_fold)
        self.task_pane.history.toggled.connect(self._save_page_fold)
        self.wire_notes(self.task_pane, self.say, self.open_ref)
        self.detail_stack.addWidget(self.task_pane)
        dl.addWidget(self.detail_stack, 1)
        self.detail = detail
        self.split.addWidget(detail)
        self.split.setSizes([NAV_WIDTH, 430, 560])
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 1)
        # One white card holds the list and the page, set into the grey frame (release 5.182, decision 851).
        self.card = ContentCard(self.split)
        outer.addWidget(self.card, 1)
        hidden = db.get_state(self.ctx.conn, VIEWS_HIDDEN_KEY) == "1"
        self.views_button.setChecked(not hidden)
        self.nav.setVisible(not hidden)
        self.card.sync()
        self.views_button.toggled.connect(self.show_views_pane)

        # The message at the bottom of the window (release 5.182, decision 853: the status strip goes). The names the rest
        # of the code and the tests read stay: ``status`` is its words, ``_status_timer`` its timer.
        self.toast = Toast(self)
        self.status = self.toast.label
        self._status_timer = self.toast.timer
        #: Each minute while Today shows: the next meeting's minutes, and the calendar read again when it's 5 minutes old (release 5.127).
        self.meetings_timer = today_meetings.start_timer(self)
        #: Undo after a state picked from a row: a button on the message, for ten seconds (release 5.76, decision 363).
        self._undo: Callable[[], None] | None = None
        self.toast.undo.clicked.connect(lambda: self._status_link("undo"))
        self.toast.closed.connect(lambda: setattr(self, "_undo", None))
        self.status.linkActivated.connect(self._status_link)

    def _build_edit_form(self) -> QWidget:
        form = QWidget()
        lay = QVBoxLayout(form)
        lay.setContentsMargins(14, 10, 14, 14)
        self.edit_title = QLabel(objectName="pageTitle")
        lay.addWidget(self.edit_title)
        # Release 5.25 (decision 112): Edit fixes the title and summary. The text stays as it arrived, and its words are
        # fixed on the task's notes page, which Go to it on the page opens.
        lay.addWidget(QLabel("Title", objectName="fieldLabel"))
        self.edit_capture_title = QLineEdit()
        lay.addWidget(self.edit_capture_title)
        head = QHBoxLayout()
        head.addWidget(QLabel("Its text, as it arrived", objectName="fieldLabel"))
        head.addStretch()
        self.edit_goto = QPushButton("Go to it on the page")
        self.edit_goto.setToolTip("Its block on the task's notes page, where its words are edited")
        self.edit_goto.clicked.connect(self._edit_goto)
        head.addWidget(self.edit_goto)
        lay.addLayout(head)
        self.edit_content = RichEdit()  # shown with its formatting and lists, read-only
        self.edit_content.setReadOnly(True)
        lay.addWidget(self.edit_content, 3)
        lay.addWidget(QLabel("Summary", objectName="fieldLabel"))
        self.edit_summary = QPlainTextEdit()
        self.edit_summary.setPlaceholderText("No summary")
        lay.addWidget(self.edit_summary, 1)
        note = Help("Its capture.md stays as it arrived: the title and summary are kept in docs.db. Ctrl+Enter saves; Esc cancels.")
        lay.addWidget(note)
        row = QHBoxLayout()
        save = QPushButton("Save")
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
            # the sidebar starts at its own width, not a share of the window's (O10)
            rest = self.width() - NAV_WIDTH - 2 * self.split.handleWidth() - CARD_GAP - CARD_PAD  # the card's right margin too
            self.split.setSizes([NAV_WIDTH, rest * 43 // 99, rest - rest * 43 // 99])
            self._placed = True
        if self.dirty:
            self.refresh(render=False)
        if view == "capacity":  # one page for both (decision 229): a wheel's slice can still name it
            self.timeline.show_capacity()
            view = "timeline"
        view = self._route_retired(view)
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
        bring_to_front(self)  # restored if it was minimized (release 5.106, decision 405)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().showEvent(event)
        if self.dirty:
            self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - closing only hides it; the app keeps running in the tray
        event.ignore()
        self.hide()

    # ================= data =================
    def model(self) -> Model:
        """The shared Model (release 5.90): the context loads it again only once docs.db has changed, so nothing here
        needs resetting by hand after a write."""
        return self.ctx.model()

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
        return Pages(self.model(), self.today(), self.content_of, self.ctx.settings.me, self.conn, LOOK.show_help,
                     self.ctx.settings.reference_links)

    def refresh(self, render: bool = True, reach: Collection[str] | None = None) -> None:
        """Read docs.db again and show what's there now. ``reach``: the tasks a change can show on (release 5.159), so only
        their open Find files windows read their records again; None for every one."""
        self.dirty = False
        if self.sel and not self._exists(self.sel):
            self.sel = None
        if render:
            self.render_all()
        for view in list(self.task_views.values()):  # the open Task views read the data again too
            if reach is None or view.task_id in reach:
                view.reload()
        self.ctx.today_changed()  # and the Today side panel (release 5.43)

    def read_again(self) -> None:
        """F5: read docs.db again, and today's calendar too (release 5.127, decision 493)."""
        today_meetings.read_again(self.ctx)
        self.refresh()

    def _exists(self, key: tuple[str, str]) -> bool:
        kind, item = key
        m = self.model()
        if kind == "label":
            return any(lb.name == item for lb in m.labels)
        if kind == "tagged":  # release 5.79: a tagged label, by its key
            return item in m.tagged.by_key
        if kind == glossary_list.KIND:  # release 5.171: a glossary, by its ID, asked of docs.db (the Model never reads one)
            return glossary_list.exists(self, item)
        if kind == conversation_page.KIND:  # release 5.122: an email conversation, from a task's page
            return conversation_page.exists(self, item)
        if kind == "tplrow":
            return self.templates.exists(item)
        return item in {"task": m.tasks, "capture": m.captures, "doc": m.documents, "person": m.people}.get(kind, {})

    def render_all(self) -> None:
        self.render_nav()
        self.render_list()
        self.render_detail()

    def say(self, text: str, error: bool = False) -> None:
        """A message at the bottom of the window for a few seconds (release 5.182, decision 853). An error stays until it's
        dismissed or the next thing is said (release 5.59)."""
        self._undo = None  # a new message: an Undo was for the last one
        self.toast.say(text, error=error)

    def say_undo(self, text: str, undo: Callable[[], None]) -> None:
        """A message with Undo on it, for ten seconds (release 5.76, decision 363)."""
        self.say(text)  # through ``say`` as before, so whatever stands in for it (a test's recorder) hears it too
        self.toast.say(text, undo=True, ms=UNDO_MS)
        self._undo = undo

    def _status_link(self, href: str) -> None:
        if href == "undo" and self._undo is not None:
            undo, self._undo = self._undo, None
            undo()

    # ================= a task's state from its row (release 5.76, round 7's item 101, decisions 360 to 364) =================
    def state_menu_for(self, task_id: str | None, parent: QWidget | None) -> QMenu | None:
        """The state menu for a task, or None for one that's gone or discarded. ``parent`` owns it: a row's menu, as a submenu."""
        m = self.model()
        if not can_change(m, task_id):
            return None
        return state_menu(parent, m, task_id, lambda to, branch: self.set_state(task_id, to, branch), wait=self.wait_on(task_id))

    def wait_on(self, task_id: str) -> Callable[[], None]:
        """The state menu's Waiting on a reply… (release 5.166, decision 762): Log progress on the task, on that state."""
        return lambda: self.ctx.log_progress(task_id, state="Waiting")

    def popup_state_menu(self, task_id: str, at: QPoint, after: Callable[[], None] | None = None,
                         tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """Open the state menu at a point on the screen: a State cell's click, the task page's state, the Task view or the Today
        side panel. ``after`` redraws the place it came from, and ``tell`` says what happened there too."""
        m = self.model()
        if not can_change(m, task_id):
            return
        menu = state_menu(self, m, task_id, lambda to, branch: self.set_state(task_id, to, branch, after, tell), wait=self.wait_on(task_id))
        menu.addSeparator()  # a tile's circle: Log progress… and Got it under the states (release 5.138, decision 567)
        tile_ui.add_wait_lines(self, task_id, menu)
        try:
            self.run_menu(menu, at)
        finally:
            menu.deleteLater()

    def run_menu(self, menu: QMenu, at: QPoint) -> None:
        """Show a menu and wait for it. Tests replace it."""
        menu.exec(at)

    def set_state(self, task_id: str, to: str, branch: bool = False, after: Callable[[], None] | None = None,
                  tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> bool:
        """A state picked from a menu: saved at once, a status log line as "Browse tool" and no capture (decision 362); with
        ``branch``, every open task below closes too (364). The status line says so, with Undo for ten seconds (363), and a
        closed task leaves a list of open ones at once, as the list is drawn again. True when something changed."""
        m = self.model()
        if not can_change(m, task_id):
            return False
        if to == STATE_MAKE_TASK:  # a collection's Make it a task (release 5.167, decision 781)
            from docrepo.ui import collections_ui

            collections_ui.make_task(self, task_id)
            if after is not None:
                after()
            return True
        ids = [task_id, *(open_below(m, task_id) if branch else [])]
        was = {x: m.task(x).state for x in ids}
        if all(state == to for state in was.values()):
            return False
        out = self._do(lambda: edits.set_states(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, {x: to for x in ids}, self._now(),
                                                self.model()))
        if out is None:
            return False
        line = picked_line(m, task_id, to, len(ids) - 1) + (" Problems: " + " ".join(out.problems) if out.problems else "")

        def undo() -> None:
            back = self._do(lambda: edits.set_states(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, was, self._now(), self.model()))
            if back is None:
                return
            self.say("Set back. The history keeps both changes.")
            if after is not None:
                after()
            if tell is not None:
                tell("Set back. The history keeps both changes.", None)

        self.say_undo(line, undo)
        if after is not None:
            after()
        if tell is not None:
            tell(line, undo)
        return True

    def card_menu(self, task_id: str, at: QPoint, open_it: bool = True) -> None:
        """The right-click menu of a Priorities card, a row inside one, or the timeline's card: a task tile's one menu
        (release 5.138, the task tile plan's decision 573), in place of 5.76's Open task, Edit task and State."""
        menu = tile_ui.tile_menu(self, task_id, self, open_it=open_it)
        if menu is None:
            return
        try:
            self.run_menu(menu, at)
        finally:
            menu.deleteLater()

    # ================= the views pane =================
    def render_nav(self) -> None:
        """The sidebar (O10): an icon per view, counts only where they ask for something, and the groups
        folded as the owner left them (in docs.db)."""
        counts = view_counts(self.model(), self.today(), self.ctx.settings.me)
        self.nav.show_state(counts, self.view if self.view != "search" else None, self._folded_groups())

    def _folded_groups(self) -> set[str]:
        """The sidebar's folded groups, from docs.db. Manage is folded until a group has been folded or opened by hand
        (release 5.182, decision 854)."""
        kept = db.get_state(self.ctx.conn, NAV_FOLDED_KEY)
        return {"Manage"} if kept is None else set(filter(None, kept.split(",")))

    def _nav_folded(self, section: str, closed: bool) -> None:
        """A group in the sidebar was folded or unfolded; the choice is kept in docs.db's app_state."""
        folded = self._folded_groups()
        (folded.add if closed else folded.discard)(section)
        self.ctx.keep_state(NAV_FOLDED_KEY, ",".join(sorted(folded)))

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
                out.append(Command("Task", "Discussion or meeting", lambda: self.open_capture(task=tid, meeting=True), "M"))
            out += [Command("Task", "Find files", lambda: self.open_task_view(tid), "O"),
                    Command("Task", "Copy prompt", lambda: self.copy_prompt(tid)),
                    Command("Task", "Save as template", lambda: self.templates.save_as(tid)),
                    Command("Task", "Apply template", lambda: self.templates.apply([tid])),
                    Command("Task", "Export tree", lambda: self.tree_files.export_task(tid)),
                    Command("Task", "Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / tid)),
                    Command("Task", tidy_follow_ups.NAME, lambda: tidy_follow_ups.run(self, tid)),
                    Command("Task", tidy_notes.NAME, lambda: tidy_notes.run(self, tid))]  # release 5.150
        out += [Command("View", v.label, lambda v=v.id: self.set_view(v)) for v in VIEWS]
        # The Urgent view's place in the palette (release 5.97, decision 386): the task tree, Urgent only.
        out.append(Command("View", "Urgent tasks (the task tree, Urgent only)", self.show_urgent))
        out += [Command("", "New capture", lambda: self.open_capture(), self.ctx.settings.hotkey),
                Command("", "Import a tree file", self.tree_files.import_tree),
                Command("", people_import.NAME, lambda: people_import.run(self)),  # release 5.151
                Command("", "Move follow-ups out of every meeting…", lambda: tidy_follow_ups.run(self, None)),  # release 5.142
                Command("", tidy_notes.EVERY, lambda: tidy_notes.run(self, None)),  # release 5.150
                Command("", "Search everything", lambda: open_search(self.search_box), "Ctrl+Shift+F"),
                Command("", "Quick summary: a person, an agenda or a label", lambda: self.ctx.open_summary(None)),
                *summary_commands(self.ctx),  # each saved set (release 5.149, decision 651)
                Command("", RECENT_CAPTURES, lambda: self.ctx.open_recent()),  # release 5.158, decision 723
                Command("", GLOSSARY_LOOKUP, lambda: self.ctx.open_lookup()),  # release 5.172, decision 808
                Command("", "Find in this view", self.open_find, "Ctrl+F"),
                Command("", "Show or hide the views", lambda: self.show_views_pane(not self.views_button.isChecked()), "Ctrl+B"),
                Command("", "Read docs.db and the calendar again", self.read_again, "F5"),
                Command("", "Keys", self.show_keys, "F1"),
                Command("", "Hide hints" if LOOK.hints else "Show hints", lambda: self._set_hints(not LOOK.hints)),
                *self.ctx.wheel_palette()]  # the wheels' slots (release 5.41)
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
        self.card.sync()  # the frame's 8 px at the card's left when the sidebar's hidden (release 5.182)
        if self.views_button.isChecked() != on:
            self.views_button.setChecked(on)  # its toggled signal calls this again, which then finds nothing to do
        if db.get_state(self.ctx.conn, VIEWS_HIDDEN_KEY) != ("0" if on else "1"):
            self.ctx.keep_state(VIEWS_HIDDEN_KEY, "0" if on else "1")

    # ================= the list pane =================
    def _set_head(self, title: str, note: str = "", total: str = "") -> None:
        """The view's title and what it is. ``total`` (such as "18 open") follows the title, as the sidebar
        counts only what asks for something (O10)."""
        if total:
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
        if workspace_ui.is_open(self):  # the workspace takes the list's and the page's room (release 5.152, decision 682)
            workspace_ui.render(self)
            return
        self.detail.setVisible(self.view not in NO_PAGE_VIEWS)
        if self.view == "priorities":
            self.middle.setCurrentWidget(self.priorities)
            self.priorities.render(self.model(), self.today(), self.sel[1] if self.sel and self.sel[0] == "task" else None, self.ctx.settings.me)
            return
        if self.view == "timeline":
            self.middle.setCurrentWidget(self.timeline)
            self.timeline.render(self.model(), self.today())
            return
        if self.view == "settings":
            self.middle.setCurrentWidget(self.settings_view)
            self.settings_view.load()
            return
        self.middle.setCurrentIndex(0)
        self._clear_filters()
        self.filters.setVisible(True)
        builder = {"today": self._today_view, "review": lambda: review_list.view(self), "tasks": self._tasks_view, "unfiled": self._unfiled_view, "agenda": self._agenda_view,
                   "people": self._people_view, "templates": self.templates.render_list,
                   "labels": self._labels_view, "tagged": lambda: tagged_list.view(self), "glossaries": lambda: glossary_list.view(self), "docs": self._docs_view, "search": self._search_view,
                   "discarded": self._discarded_view, "activity": self._activity_view}.get(self.view)
        self.tree.stop_row_moves()  # the Templates view turns it back on
        self.tree.begin()
        self.tree.set_density(*ROW_DENSITY.get(self.view, (tokens.LIST_ROW, False)))
        self.tree.set_tiled(self.view in TASK_VIEWS)  # tiles set apart by tone (release 5.138, decision 571)
        self.tree.priorities = priorities_of(self.model())
        try:
            if builder:
                builder()
            else:
                self._list_view(self.view)
            if self.view in NESTING_VIEWS:
                self._apply_shut()
                self._level_buttons()
            self._mark_states()
        finally:
            self.tree.end(self._row_to_select())
        # no column headings over nothing, or where they say nothing the cells don't (decision L6)
        self.tree.setHeaderHidden(self.view in NO_HEADINGS or not any(k is not None for k in self.tree.keys()))
        if self.view in NESTING_VIEWS:
            self._sync_level_buttons()
        self.filters.setVisible(any(_in_bar(self.filters_layout.itemAt(i)) for i in range(self.filters_layout.count())))
        self._apply_find()

    def render_detail(self, keep_scroll: bool = False) -> None:
        if workspace_ui.is_open(self):  # the workspace shows the task (release 5.152)
            self.detail.hide()
            return
        scroll = self.page.verticalScrollBar().value() if keep_scroll else 0
        self._clear_actions()
        self.sync_toolbar()
        if self.view in NO_PAGE_VIEWS:  # no page shows beside these (release 5.159, decision 730): it's drawn when one does
            self.actions.hide()
            return
        s = self.sel
        if s and s[0] == "capture" and s[1] == self.editing:
            self.detail_stack.setCurrentIndex(1)
            self.actions.hide()
            return
        self.detail_stack.setCurrentIndex(0)
        if not s or not self._exists(s):
            self.actions.hide()
            self.page.setHtml('<p class="note">Pick a task, capture or document to see it here.</p>')
            if self.view not in NO_PAGE_VIEWS:
                self.detail.hide()  # the list takes the room until something is picked
            return
        if self.view not in NO_PAGE_VIEWS:
            self.detail.show()
        self.actions.show()
        pages = self.pages()
        kind, item = s
        if kind == "task":
            self._task_actions(item)
            self._show_task(item, keep_scroll)
            return
        if kind == "capture":
            self._capture_actions(item)
            html = pages.capture_page(item, self._capture_text(item), self._old_versions(item))
        elif kind == "doc":
            self._doc_actions(item)
            html = pages.document_page(item)
        elif kind == "person":
            self._person_actions(item)
            html = pages.person_page(item)
        elif kind == "tplrow":
            self.templates.actions(item)
            html = self.templates.page(item)
        elif kind == "tagged":  # release 5.79
            tagged_list.actions(self, item)
            html = pages.tagged_page(item)
        elif kind == glossary_list.KIND:  # release 5.171: a glossary and its rows (the glossaries plan's decision 804)
            glossary_list.actions(self, item)
            html = glossary_list.page(self, item)
        elif kind == conversation_page.KIND:  # release 5.122: an email conversation (the email section plan's decision 459)
            conversation_page.actions(self, item)
            html = conversation_page.page(self, item)
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

    def double_click(self, item: QTreeWidgetItem) -> None:
        """Double-clicking a row opens its edit form (mods log round 3, M0056; decision 57), but a task's opens its page (release
        5.138, the task tile plan's decision 572: Edit task is E and the menu), Edit for a capture (a note on Today edits the note), and Edit… for a person or a label. A document has
        no form yet, so it still shows its file, or copies a link's address. Subtasks open and close by the row's arrow and
        the Right, Left, + and − keys."""
        key = item.data(0, KEY_ROLE)
        if not key:
            return
        kind, ident = key
        m = self.model()
        if kind == "task":  # a task tile opens as Settings' Open a task in says (release 5.174, decision 815): Edit task is E
            t = m.tasks.get(ident)
            if t is not None and not t.discarded:
                workspace_ui.open_row(self, ident)
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
        elif kind == "tagged":  # release 5.79
            tagged_list.edit(self, ident)
        elif kind == "tplrow":
            self.templates.edit_row(int(ident))
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
                self.open_document_link(item)  # a link opens in the browser, on this click (release 5.67)
                return
            source = edits.source_of(root, m, item)
            if source:
                self.reveal(source)
                self._used(item, "show")
        elif kind == "copy":
            f = next((x for x in m.copies if str(x.id) == item), None)
            if f:
                self.reveal(root / "Tasks" / f.task / "Files" / ("_old versions" if f.old else "") / f.name)

    # ================= navigation =================
    def _row_picked(self, key) -> None:
        if key[0] == "actline":  # an Activity line opens its capture, task or document, and stays the row shown selected
            line = self._act_lines.get(key[1])
            if line is not None:
                self.act["line"] = line.key
                self.select(*line.open, keep_row=True)
            return
        self.act["line"] = None
        self.select(*key)

    def select(self, kind: str, item: str, tab: str | None = None, update_list: bool = False, keep_row: bool = False) -> None:
        """Show an item's page. Each task opens with the scope at With subtasks, and its chapters closed. The workspace
        goes first, when it's open (release 5.152)."""
        workspace_ui.leave(self)
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
        elif not keep_row:
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

    def _route_retired(self, view: str | None) -> str | None:
        """A view that's gone (release 5.97): its name leads to the view that took it over, with its filter on. The Urgent
        view is the task tree with Urgent only ticked (the consolidation plan's decision 386)."""
        if view in RETIRED_VIEWS:
            view, flag = RETIRED_VIEWS[view]
            self.tree_filter[flag] = True
            if flag == "urgent":
                self.open_to_urgent()
        return view

    def show_urgent(self) -> None:
        """The urgent tasks: the task tree with its Urgent filter on, where the Urgent view's keys and commands lead."""
        self.set_view("urgent")

    def set_view(self, view: str) -> None:
        view = self._route_retired(view) or ""
        if view not in VIEW_IDS:
            return
        workspace_ui.leave(self)  # a place picked in the sidebar leaves the workspace for it (release 5.152, decision 682)
        if view == "capacity":  # one page for both (decision 229)
            self.timeline.show_capacity()
            view = "timeline"
        if self.query:
            self.query = ""
            self.search_box.blockSignals(True)
            self.search_box.clear()
            self.search_box.blockSignals(False)
        self.view = view
        self.ticked.clear()
        self.close_find()
        self.priorities.close_find(render=False)
        if view == "review":  # release 5.128: the review in hand carries on, or a new one starts
            review_list.enter(self)
        self._select_first()
        self.render_all()

    def _select_first(self) -> None:
        """What a view selects when it opens."""
        m, v = self.model(), self.view
        new = None
        if v == "today":
            # The first task as Today shows it (release 5.176, decision 820: urgent first in each band).
            first = next((a.subject for a in today_order(m, self._now().date(), self._workdays()) if a.subject), None)
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
        elif v == "tagged":  # release 5.79: the first label it lists
            new = tagged_list.first(self)
        elif v == "glossaries":  # release 5.171: the first glossary, by name
            new = glossary_list.first(self)
        elif v == "review":  # release 5.128: the step's first row
            new = review_list.first(self)
        elif v == "templates":
            new = self.templates.first()
        elif v == "discarded":
            first = next(iter(discarded_rows(m, self.today())), None)
            new = (first.kind, first.id) if first else None
        elif v == "agenda":
            target = current_target(m, self.target)
            new = (("person" if is_person(target) else "task"), target) if target else None
        elif v in ("activity", "priorities"):  # release 5.23: what was open stays open, if it's a page these views show
            new = self.sel if self.sel and self.sel[0] in (("task",) if v == "priorities" else ("task", "capture", "doc")) else None
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

    def _typing(self) -> bool:
        """Whether the keyboard is in a box being typed in, where a letter is a letter, not a command."""
        focus = QGuiApplication.focusObject()
        return isinstance(focus, (QLineEdit, QPlainTextEdit, QSpinBox)) or (isinstance(focus, QTextEdit) and not focus.isReadOnly()) or (
            isinstance(focus, QComboBox) and focus.isEditable())

    def _asks(self) -> bool:
        """Whether a task row's right-click menu has Ask for an update first: in Waiting on others (release 5.125, decision
        481) and in the weekly review's Waiting step (release 5.128)."""
        return self.view == "waiting" or self.view == "review" and review_list.step_id(self) == "waiting"

    def _key(self, mode: str) -> None:
        if not self._typing():
            self.capture_for_selected(mode)

    def _pick_task(self, anchor: QWidget, picked: Callable[[str | None], None], none: tuple[str, str] | None,
                   keep: Callable[[str], bool] | None = None) -> None:
        """The task picker under ``anchor``; ``keep`` leaves out the tasks it says no to, everywhere in the list."""
        self._picker = TaskPicker(self, self.model, none, keep=keep)
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
        elif mode in ("find_files", "task_view"):  # O: its Find files (decision 164; the Task view until release 5.98, decision 389)
            self.open_task_view(self.sel[1])
        elif mode == "today":
            self.add_to_today(self.sel[1])
        elif mode == "agenda":
            self.open_capture(task=self.sel[1], mode="update", agenda_focus=True)
        elif mode == "meeting":  # M: meeting notes for it, its own if it's a meeting (release 5.8)
            self.open_capture(task=self.sel[1], meeting=True)
        else:
            self.open_capture(task=self.sel[1], mode=mode)

    def capture_saved(self, result: SaveResult) -> None:
        """After the capture window saves: show what it did, as the mockup does, with the save's problems after the status
        line until they're opened, and Undo when the save can be taken back (release 5.91)."""
        self.ctx.today_changed()  # the Today side panel reads it again (release 5.43)
        self.problems_line.refresh()
        if not self.isVisible():
            self.dirty = True
            return
        self.refresh(render=False)
        if workspace_ui.is_open(self):  # the workspace stays, drawn again with what was saved (release 5.152)
            self.render_all()
        elif result.created_task:
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
        if result.undo is not None:
            undo = result.undo
            self.say_undo(result.message, lambda: undo() and (self.refresh(), self.say(f"{result.capture_id} is undone: it's discarded, "
                                                                                       "and the capture is back in the window to save again.")))
        else:
            self.say(result.message)

    # ================= changes =================
    def _do(self, change: Callable[[], object], select: tuple[str, str] | None = None, counts: bool = True,
            reach: Collection[str] | None = None) -> object | None:
        """Make a change, then show the result. A change that isn't allowed says why and changes nothing.

        Since release 5.159 (the design workspace's ``docs/mods/bin-drop-speed-plan.md``, decision 730): the Model a change
        read after its writes is kept as the shared one (``AppContext.keep``), so nothing reads every table again; the
        window, while it's hidden, is drawn once it's shown, as after a capture's save; ``counts`` False, for a change no
        view's count follows (a priority, Today's order), leaves the views pane as it is, since the counts take longest; and
        ``reach``, the tasks the change can show on, reloads only their open Find files windows (``refresh``).

        Since release 5.163 (the design workspace's ``docs/mods/one-read-plan.md``, decisions 746 and 747) every change that
        writes its touched pages hands that Model back, and those called here are handed the shared Model (``self.model()``)
        as the one from before, so a change reads docs.db once, after it."""
        try:
            out = change()
        except (TaskError, PeopleError, AgendaError, edits.EditError, WriteRefused, OSError, sqlite3.Error, ValueError) as e:
            self.say(str(e), error=True)
            return None
        if isinstance(out, edits.Outcome):
            self.ctx.keep(out.model)
        self.refresh(render=False, reach=reach)
        if select:
            self.sel = select
        if not self.isVisible():
            self.dirty = True
        elif counts:
            self.render_all()
        else:
            self.render_list()
            self.render_detail()
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
        out = self._do(lambda: edits.file_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, task_id, self._now(), self.model()),
                       ("capture", capture_id))
        if out and self.ctx.settings.outlook_categories:  # release 5.93: filed later, marked as a save marks it
            marked, trouble = self.mark_emails(capture_id, task_id)
            if marked or trouble:
                self.say(out.message + (f" Marked {marked} email{'s' if marked != 1 else ''} in Outlook with its task's name." if marked else "")
                         + (" Problems: " + " ".join(trouble) if trouble else ""), bool(trouble))

    def mark_emails(self, capture_id: str, task_id: str) -> tuple[int, list[str]]:
        """Mark a filed capture's emails in Outlook with the task's name (release 5.93, the review's F14), from where the save
        found them. Returns how many were marked, and the problems in words."""
        m = self.model()
        c = m.captures.get(capture_id)
        if c is None or not c.emails:
            return 0, []
        places = captures.email_places(self.conn, capture_id)
        filed = []
        for e in c.emails:
            entry, store = places[e.pos] if e.pos < len(places) else ("", "")
            filed.append((EmailItem(e.subject, e.sender, e.sent, "", "", entry_id=entry, store_id=store), task_id))
        return outlook.mark_filed(filed, m, self.ctx.settings.outlook_category_colour)

    def start_capture_edit(self, capture_id: str) -> None:
        c = self.model().captures[capture_id]
        self.editing = capture_id
        self.edit_title.setText(f"Edit capture {capture_id}")
        self.edit_capture_title.setText(c.title)
        self.edit_content.clear()
        self.edit_content.set_value(items.unstore(self._capture_text(capture_id) or ""), c.formatted)  # each @ and # by its name
        self.edit_summary.setPlainText(c.summary or "")
        m = self.model()
        self._edit_page = next((t for t in m.capture_tasks(c) if capture_id in notes_page.capture_ids(m.pages.get(t, ""))), None)
        self.edit_goto.setVisible(self._edit_page is not None)
        self._edit_start = (self.edit_capture_title.text(), self.edit_summary.toPlainText())
        self.render_detail()
        self.edit_capture_title.setFocus()

    def _edit_goto(self) -> None:
        """Go to it on the page: its block on a task's notes page, leaving the form (asking first if it changed)."""
        task_id, capture_id = self._edit_page, self.editing
        self.cancel_capture_edit()
        if self.editing is None and task_id and capture_id:
            self.go_to_block(task_id, capture_id)

    def cancel_capture_edit(self) -> None:
        if not self.editing:
            return
        changed = (self.edit_capture_title.text(), self.edit_summary.toPlainText()) != self._edit_start
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
        try:
            out = edits.edit_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, self.edit_capture_title.text(),
                                     self.edit_summary.toPlainText(), default_type, self._now(), self.model())
        except (edits.EditError, WriteRefused, OSError) as e:
            self.say(str(e), error=True)
            return
        self.ctx.keep(out.model)  # release 5.163: the Model it read after, so the window doesn't read docs.db again
        self.editing = None
        self._contents.pop(capture_id, None)
        self.refresh()
        self.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))

    def clear_reminder(self, task_id: str, via: str = "Reminders list") -> None:
        self._do(lambda: edits.clear_reminder(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now(), via, self.model()))

    def close_agenda_item(self, item_id: int, how: str) -> None:
        item = next((a for a in self.model().agenda if a.id == item_id), None)
        if item is None:
            return
        out = self._do(lambda: edits.close_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, how, self._now(), self.model()))
        if not out:
            return
        opened = ""
        if how == "Discussed" and item.subject:
            opened = f"Discussed at {self.model().target_name(item.target)}: "
            self.open_capture(task=item.subject, mode="update", content=opened)
            words = f"{self.model().task(item.subject).title}: discussed. Type what was decided and save, or press Esc to skip."
        else:
            words = out.message

        def undo() -> None:  # release 5.91: the item opens again, and the Update it opened goes if nothing was typed in it
            if not self._do(lambda: edits.reopen_agenda_item(self.conn, self.ctx.data_root, self.ctx.fs, item_id, self._now(), self.model())):
                return
            kept = ""
            if opened:
                kept = self.capture.drop_if_untouched(item.subject, opened)
            self.say(f"Back on the agenda as it was.{kept}")

        self.say_undo(words, undo)

    # ---- Today (mods log round 1, M0016) ----
    def add_to_today(self, task_id: str) -> None:
        """D, or Add to Today: the task goes on Today, and the window stays where it is. It's no quick task: the task is as it
        was (release 5.99, the consolidation plan's decision 393)."""
        self._do(lambda: edits.add_to_today(self.conn, self.ctx.data_root, self.ctx.fs, task_id, "", self._now(), self.model()), self.sel)

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

    def add_today_text(self, kind: str, text: str) -> bool:
        """The Today side panel's box (release 5.43): a quick task, or a note, from text. True if it was added."""
        if kind == "note":
            return bool(self._do(lambda: edits.add_to_today(self.conn, self.ctx.data_root, self.ctx.fs, None, text, self._now(), self.model()), self.sel))
        return self._save_quick(lambda: add_quick_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, text, self._now())) is not None

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
            self._do(lambda: edits.edit_today_note(self.conn, self.ctx.data_root, self.ctx.fs, item_id, text, self._now(), self.model()), self.sel)

    def add_today_note(self) -> None:
        box = getattr(self, "today_note", None)
        text = box.text().strip() if box is not None else ""
        if not text:
            self.say("Type the note first.", error=True)
            return
        if self._do(lambda: edits.add_to_today(self.conn, self.ctx.data_root, self.ctx.fs, None, text, self._now(), self.model()), self.sel):
            self.today_note.setFocus()

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
        """Put a link's address on the clipboard."""
        d = self.model().documents.get(document_id)
        if d is None or not is_link(d.original):
            return
        QGuiApplication.clipboard().setText(d.original.strip())
        self._used(document_id, "copy_link")
        self.say(f"Copied the link to {d.name}.")

    def open_document_link(self, document_id: str) -> None:
        """Open a link document in the default browser, or a folder in File Explorer, on the owner's click (release 5.67,
        round 6's decision 314), and note the use."""
        d = self.model().documents.get(document_id)
        if d is None:
            return
        if is_folder(d.original):
            found = self.reveal(Path(d.original))
            self._used(document_id, "show")
            self.say(f"Opened {d.name} in File Explorer." if found is not False else f"{d.name} isn't at {d.original} any more.", error=found is False)
            return
        if not is_link(d.original):
            return
        problem = opener.start_link(d.original, self.link_starter)
        if problem:
            self.say(problem, error=True)
            return
        self._used(document_id, "open")
        self.say(f"Opened {d.name} in your browser.")

    def open_address(self, address: str) -> None:
        """Open an address that isn't a document (a reference field's link, or one in a note's words) in the default
        browser, on the owner's click (release 5.67)."""
        problem = opener.start_link(address, self.link_starter)
        self.say(problem or "Opened the link in your browser.", error=bool(problem))

    def _used(self, document_id: str, action: str) -> None:
        """Note a file shown or a link copied from the task page (the Task view's uses, decision 159)."""
        task = self.sel[1] if self.sel and self.sel[0] == "task" else None
        try:
            pins.record_use(self.conn, document_id, task, action, self.ctx.now())
        except Exception as e:  # noqa: BLE001 - a use that isn't kept never stops the action
            log.warning("a use of %s wasn't kept: %s", document_id, type(e).__name__)

    # ================= the Task view (releases 5.34 and 5.35) =================
    def open_task_view(self, task_id: str | None = None, file_type: str | None = None) -> None:
        """A task's Find files (the Task view until release 5.98, decision 389): a window of its own (decision 156), one per
        task, brought forward when it's open. ``file_type`` shows only that type of file, such as "link" from the Links
        group (release 5.67)."""
        task_id = task_id or (self.sel[1] if self.sel and self.sel[0] == "task" else None)
        if not task_id or task_id not in self.model().tasks:
            self.say("Select a task first. O opens Find files for the task that's selected.")
            return
        from docrepo.ui.task_view import TaskView

        view = self.task_views.get(task_id)
        if view is None:
            view = self.task_views[task_id] = TaskView(self, task_id)
        self.last_task_view = task_id
        bring_to_front(view)
        if file_type:
            view.show_type(file_type)
        view.focus_box()

    def current_task_for_view(self) -> str | None:
        """The Execution wheel's Find files (release 5.41): the task selected here, or else the last Find files opened."""
        if self.sel and self.sel[0] == "task" and self.sel[1] in self.model().tasks:
            return self.sel[1]
        return self.last_task_view if self.last_task_view in self.model().tasks else None

    def task_view_closed(self, task_id: str) -> None:
        view = self.task_views.pop(task_id, None)
        if view is not None:
            view.deleteLater()

    def task_view_pins_changed(self, task_id: str) -> None:
        """A pin changed: Task.md's Key documents line is written again."""
        from docrepo.pages import write_task_page

        try:
            write_task_page(Model(self.conn), self.ctx.data_root, self.ctx.fs, task_id, self.today(), self.ctx.now())
        except OSError as e:
            log.warning("Task.md of %s wasn't written after a pin: %s", task_id, type(e).__name__)

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

    def edit_task(self, task_id: str, more: bool = False) -> None:
        """Edit task (E): every field on one page (mods log round 1, M0008, M0011). ``more`` opens it at More options, as
        Quick edit's More options… does (release 5.100)."""
        if task_id not in self.model().tasks:
            return
        # Its checklist (release 5.26, decision 88 as redone): the Checklist summary, bound to the notes page's lines, so
        # a tick or a rewording there changes the page at once, and Cancel leaves it.
        from docrepo.ui.checklist_summary import ChecklistSummary

        if self.task_pane.task_id != task_id and self.sel == ("task", task_id):
            self.render_detail()
        showing = next((p for p in self.note_panes() if p.task_id == task_id), None)  # the task page's
        notes = showing.notes if showing else self.task_pane.notes
        checklist = ChecklistSummary(notes, foldable=False) if showing else None
        dialog = TaskEditDialog(self, self.model(), task_id, self._label_options, self._people_options,
                                lambda anchor, picked: self._pick_task(anchor, picked, None),
                                reference_fields=self.ctx.settings.reference_fields, today=self.today(), checklist=checklist,
                                link=self.templates.link_of(task_id), workdays=self._workdays(),
                                reference_links=self.ctx.settings.reference_links, open_link=self.open_address,
                                review_weeks=self.ctx.settings.review_weeks)
        if more:
            dialog.show_more()
        self._edit_dialog = dialog  # kept, so tests can reach it
        while True:
            try:
                accepted = self.run_dialog(dialog)
            finally:
                notes.save_now()
            if not accepted:
                self.templates.after_form(task_id, dialog)
                return
            if self.save_task_edit(task_id, dialog.values()):
                return  # otherwise it's Back from asking what the move would reach: the form again, as it was

    def _workdays(self) -> frozenset[int]:
        return workday_numbers(self.ctx.settings.workdays)

    def save_task_edit(self, task_id: str, values: dict) -> bool:
        """Save Edit task. False when the move would reach another tree, and the owner went Back rather than saving."""
        leave = self._left_by_move(lambda: edits.edit_moves(self.conn, self.ctx.settings, task_id, self._now(), **values), task_id)
        if leave is None:
            return False
        self._do(lambda: edits.edit_task(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, self._now(), self.model(),
                                         **values, leave=leave))
        return True

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
                                                    "stays, and any changes it made to tasks stay in their histories.\n\nWhy?")
        if reason is None:
            return
        # Its block comes off its tasks' notes pages; one edited there stays unless you say (decision 106).
        self.save_open_notes()
        model, stories = edits.stories_for(self.conn, self.ctx.data_root, self._now())
        edited = notes_page.edited_blocks(model, stories, capture_id)
        off = False
        if edited:
            names = ", ".join(model.task(t).title for t in edited)
            off = self.confirm("Discard capture", f"{capture_id}'s block on the notes page of {names} was edited there. "
                                                  "Take it off the page too?")
        self._do(lambda: edits.discard_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, reason, self._now(), off), ("capture", capture_id))

    def bring_back_capture(self, capture_id: str) -> None:
        if self._do(lambda: edits.bring_back_capture(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, self._now())):
            message = self.status.text()
            self.go_capture(capture_id)
            self.say(message)

    def _pick_parent(self, task_id: str, old_parent: str | None, also: bool = False, anchor: QWidget | None = None,
                     after: Callable[[], None] | None = None, tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> None:
        """The task picker for Move, Put under and Also put under, under ``anchor`` (the command bar unless a menu says),
        without the task itself and every task under it, which it can't go under (release 5.98, with 5.103's ``keep``: the
        owner's yes of 2026-11-07). ``after`` and ``tell`` are ``move_task``'s."""
        out = {task_id, *self.model().descendants_of(task_id)}
        self._pick_task(anchor or self.actions,
                        lambda new: self.move_task(task_id, None if also else old_parent, new, after, tell) if new else None, None,
                        keep=lambda t: t not in out)

    def move_task(self, task_id: str, old_parent: str | None, new_parent: str | None, after: Callable[[], None] | None = None,
                  tell: Callable[[str, Callable[[], None] | None], None] | None = None) -> bool:
        """A move from the Edit menu, with Undo for ten seconds (release 5.118): ``task_menus.move``."""
        return task_menus.move(self, task_id, old_parent, new_parent, after, tell)

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
