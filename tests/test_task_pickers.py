"""Every dropdown that picks or navigates tasks works as the # list does (release 5.103, the task pickers plan's item 117,
decisions 398 to 404): one task list (``docrepo/ui/task_list.py``) with the # list's rows, matching and levels, in the
capture window's task picker, the browse window's (Move, Put under, File to, the Documents filter, templates, ties), the Task
view's Ctrl+O, Task search and the Timeline's Focus on; and each place's own extras kept. Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from docrepo import items  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.schedule import is_open  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import RefPopup  # noqa: E402
from docrepo.ui.task_list import TaskList, TaskRowDelegate, Words  # noqa: E402
from docrepo.ui.task_picker import TaskPicker, recent_tasks  # noqa: E402
from docrepo.ui.task_search import TaskSearch  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
REACTOR, VERIFICATION, Q4_COST, INSTALLATION, RIGGING = "T000001", "T000002", "T000003", "T000008", "T000012"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    capture.show_capture()
    browse = BrowseWindow(ctx, capture)
    QApplication.processEvents()  # the windows' own events first: a window coming forward closes any popup, a menu's too
    yield ctx, capture, browse
    QApplication.processEvents()
    capture._items_timer.stop()
    for w in (capture, browse, *browse.task_views.values()):
        w.hide()
        w.deleteLater()


class FakeApp:
    """As much of the app as Task search uses: the model, and where it opens a task."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.opened: list[tuple[str, str | None]] = []
        self.browse = type("Browse", (), {})()
        self.browse.open_task_view = lambda t: self.opened.append(("task_view", t))
        self.browse.search_box = QLineEdit()
        self.wheels = type("Wheels", (), {"give_back": lambda _self: None})()

    def show_browse(self, view=None, task_id=None) -> None:
        self.opened.append(("page", task_id))


def key(picker: TaskPicker, k: Qt.Key, mods=Qt.KeyboardModifier.NoModifier) -> None:
    """A key pressed in the picker's search box, as the keyboard sends it."""
    QApplication.sendEvent(picker.search, QKeyEvent(QEvent.Type.KeyPress, k, mods))


def labels(picker: TaskPicker) -> list[str]:
    return [o.label for o in picker.rows()]


def current(picker: TaskPicker) -> str:
    return picker.list.current().label


def opened(capture: CaptureWindow) -> TaskPicker:
    capture._open_picker()
    QApplication.processEvents()
    return capture.picker


# ---- one component everywhere ----
def test_every_picker_is_the_task_list(env):
    ctx, capture, browse = env
    search = TaskSearch(FakeApp(ctx))

    def timeline() -> TaskPicker:
        browse.show_browse()
        browse.set_view("timeline")
        QApplication.processEvents()
        browse.timeline.focus_box.click()
        return browse.timeline.focus_picker

    def task_view() -> TaskPicker:
        browse.open_task_view(REACTOR)
        browse.task_views[REACTOR].go_to_task()  # Ctrl+O
        return browse.task_views[REACTOR]._picker

    def browse_window() -> TaskPicker:  # Move, Put under, File to, the Documents filter, templates, ties
        browse._pick_task(browse.search_box, lambda t: None, ("Any task", "Show every document"))
        return browse._picker

    def task_search() -> TaskPicker:
        search.open_it("page", QGuiApplication.primaryScreen())
        return search.picker

    for where, open_it in (("capture", lambda: opened(capture)), ("browse", browse_window), ("task view", task_view),
                           ("task search", task_search), ("focus on", timeline)):
        p = open_it()
        assert isinstance(p, TaskPicker) and type(p.list) is TaskList and isinstance(p.list.delegate, TaskRowDelegate), where
        assert p.isVisible() and p.list.task_info is not None and p.list.subtasks is not None, where
        p.close()
    # The # and @ list is the same list, placed at the text cursor.
    assert isinstance(capture.ref_popup, TaskList) and issubclass(RefPopup, TaskList)
    assert type(capture.ref_popup.delegate) is TaskRowDelegate
    search.hide()


def test_hash_and_the_picker_mark_a_task_alike(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("rigging")
    p.close()
    capture.activateWindow()
    capture.content.setFocus()
    QApplication.processEvents()
    capture.content.insertPlainText("#rigging")
    ref = capture.ref_popup
    o = p.rows()[0]
    assert o.ref == ref.item(0).data(Qt.ItemDataRole.UserRole).ref == RIGGING
    assert p.list.mark(o) == ref.mark(ref.item(0).data(Qt.ItemDataRole.UserRole))  # its ring, in its top-level task's colour
    assert p.list.delegate.parts(o, False) == ref.delegate.parts(ref.item(0).data(Qt.ItemDataRole.UserRole), False)


# ---- before anything is typed ----
def test_before_typing_recent_none_then_the_top_level_tasks(env):
    ctx, capture, _ = env
    p = opened(capture)
    m = ctx.model()
    recent = [m.task(x).title for x in recent_tasks(m)]
    tops = [t.title for t in m.top_level() if is_open(t)]
    assert recent and labels(p) == ["Recent", *recent, "None", "Tasks", *tops]
    assert isinstance(p.rows()[0], Words) and current(p) == recent[0]  # the heading can't be picked
    assert "Q4 cost reduction" not in labels(p)  # parked: hidden from the tree
    none = p.rows()[len(recent) + 1]
    assert none.sub == "Keep it unfiled" and none.ref is None
    p.close()


def test_right_and_left_walk_the_tree_before_typing(env):
    ctx, capture, _ = env
    p = opened(capture)
    tops = labels(p).index("Tasks") + 1
    while current(p) != "Reactor impeller upgrade":
        key(p, Qt.Key.Key_Down)
    key(p, Qt.Key.Key_Right)
    assert p.list.depth == 1 and labels(p) == ["Reactor impeller upgrade", "Installation", "Vendor drawing package", "Draft monitoring plan"]
    assert p.list.item(0).data(Qt.ItemDataRole.UserRole + 1)  # the level's header row
    key(p, Qt.Key.Key_Left)
    assert p.list.depth == 0 and current(p) == "Reactor impeller upgrade" and p.list.currentRow() == tops
    assert "Recent" in labels(p) and "None" in labels(p)  # back to the whole list
    p.close()


def test_up_and_down_pass_over_the_headings_and_go_round(env):
    ctx, capture, _ = env
    p = opened(capture)
    key(p, Qt.Key.Key_Up)  # from the first, round to the last
    assert current(p) == labels(p)[-1]
    key(p, Qt.Key.Key_Down)
    assert current(p) == p.rows()[1].label  # Recent's heading passed over
    for _ in range(len(p.rows())):
        key(p, Qt.Key.Key_Down)
        assert not isinstance(p.list.currentItem().data(Qt.ItemDataRole.UserRole), Words)
    p.close()


def test_none_picks_none(env):
    ctx, capture, _ = env
    capture.set_task(INSTALLATION)
    p = opened(capture)
    while current(p) != "None":
        key(p, Qt.Key.Key_Down)
    key(p, Qt.Key.Key_Return)
    assert not p.isVisible() and capture.task is None


# ---- typing ----
def test_typing_finds_as_the_hash_list_does(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("plan rigging")
    assert labels(p) == ["Rigging plan"]
    p.search.setText("installation book")
    assert labels(p) == ["Book the alignment contractor"]  # through its path
    p.search.setText("Rigging plan ")  # a search box strips: the space doesn't end it
    assert labels(p) == ["Rigging plan"]
    m = ctx.model()
    found = items.task_matches("pl", [(t.id, t.title) for t in m.tasks.values() if not t.discarded and t.state != "Closed"],
                               lambda i: items.ancestor_titles(m, i))
    p.search.setText("pl")
    assert [o.ref for o in p.rows()] == found[:12]
    p.close()


def test_right_and_left_in_a_search(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("reac")
    assert labels(p) == ["Reactor impeller upgrade"]
    p.search.setCursorPosition(2)
    key(p, Qt.Key.Key_Right)
    assert p.list.depth == 1 and p.search.text() == "reac" and p.search.cursorPosition() == 2  # the list's, not the box's
    assert current(p) == "Installation"
    key(p, Qt.Key.Key_Right)  # Installation has its own
    assert labels(p)[0] == "Installation" and p.list.depth == 2
    assert labels(p)[1:] == ["Rigging plan", "Q4 overtime budget", "Book the alignment contractor"]
    key(p, Qt.Key.Key_Left)
    assert p.list.depth == 1 and current(p) == "Installation" and p.search.cursorPosition() == 2
    key(p, Qt.Key.Key_Left)
    assert p.list.depth == 0 and p.search.cursorPosition() == 2
    key(p, Qt.Key.Key_Left)
    assert p.search.cursorPosition() == 1  # at the top, Left is the box's (decision 312)
    p.search.setText("rigg")
    p.search.setCursorPosition(1)
    key(p, Qt.Key.Key_Right)
    assert p.search.cursorPosition() == 2 and p.list.depth == 0  # nothing to go into: the box's
    p.close()


def test_typing_goes_back_to_the_search(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("reac")
    key(p, Qt.Key.Key_Right)
    assert p.list.depth == 1
    p.search.insert("t")
    assert p.list.depth == 0 and labels(p) == ["Reactor impeller upgrade"]
    p.close()


def test_enter_and_tab_pick_the_current_row_and_esc_closes(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("reac")
    key(p, Qt.Key.Key_Right)
    key(p, Qt.Key.Key_Down)
    assert current(p) == "Vendor drawing package"
    key(p, Qt.Key.Key_Return)
    assert not p.isVisible() and capture.task == "T000009"
    p = opened(capture)
    p.search.setText("reac")
    key(p, Qt.Key.Key_Right)
    key(p, Qt.Key.Key_Up)  # the header: the task itself
    key(p, Qt.Key.Key_Tab)
    assert capture.task == REACTOR
    p = opened(capture)
    hidden = []
    p.aboutToHide.connect(lambda: hidden.append(True))
    key(p, Qt.Key.Key_Escape)
    assert not p.isVisible() and hidden and capture.task == REACTOR


def test_parked_tasks_are_found_and_marked(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("q4 cost")
    o = p.rows()[0]
    assert o.ref == Q4_COST and o.label == "Q4 cost reduction (parked)"
    p.search.setText("zzzqqq")
    assert labels(p) == ["No open or parked task matches."] and p.list.current() is None
    key(p, Qt.Key.Key_Return)
    assert p.isVisible()  # nothing to pick
    p.close()


def _click(lst: TaskList, row: int, x: int) -> None:
    rect = lst.visualItemRect(lst.item(row))
    at = QPointF(x, rect.center().y())
    glob = QPointF(lst.viewport().mapToGlobal(at.toPoint()))
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(lst.viewport(), QMouseEvent(kind, at, glob, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                                            Qt.KeyboardModifier.NoModifier))


def test_the_mouse_chevrons_and_picks(env):
    ctx, capture, _ = env
    p = opened(capture)
    p.search.setText("reac")
    _click(p.list, 0, p.list.viewport().width() - 8)  # the chevron goes in
    assert p.list.depth == 1 and p.isVisible()
    _click(p.list, 0, 6)  # the back chevron comes up
    assert p.list.depth == 0 and p.isVisible()
    _click(p.list, 0, 60)  # anywhere else picks
    assert not p.isVisible() and capture.task == REACTOR


def test_a_heading_cant_be_clicked(env):
    ctx, capture, _ = env
    p = opened(capture)
    picked = []
    p.picked.connect(picked.append)
    _click(p.list, 0, 60)  # Recent
    assert p.isVisible() and picked == []
    p.close()


def test_it_is_as_wide_as_its_caller_asks_and_never_scrolls_sideways(env):
    ctx, capture, _ = env
    p = opened(capture)
    assert p.width() >= p.minimumWidth() and p.list.width() <= p.width()
    assert not p.list.horizontalScrollBar().isVisible()
    assert p.list.min_width >= p.minimumWidth() - 2 * p.frameWidth() - 8
    p.close()


def test_a_callers_keep_leaves_tasks_out_everywhere(env):
    ctx, _, _ = env
    p = TaskPicker(None, ctx.model, None, keep=lambda x: x != INSTALLATION)
    p.popup(QPoint(40, 40))
    assert "None" not in labels(p)  # none_entry None: no None row
    p.search.setText("reac")
    key(p, Qt.Key.Key_Right)
    assert "Installation" not in labels(p) and p.list.depth == 1
    p.search.setText("installation")
    assert labels(p) == ["No open or parked task matches."]
    p.close()


# ---- Task search ----
@pytest.fixture
def search(env):
    ctx, _, _ = env
    s = TaskSearch(FakeApp(ctx))
    s.open_it("page", QGuiApplication.primaryScreen())
    yield s
    s.picker.close()
    s.hide()
    s.deleteLater()


def test_task_search_walks_the_tree_with_right_and_left(search):
    p = search.picker
    assert "Enter opens its page" in p.note.text() and p.note.isVisible()
    p.search.setText("verif")
    key(p, Qt.Key.Key_Right)
    assert labels(p) == ["Verification walkthrough readiness", "Rails need to be painted red", "Update area 3 guard drawings"]
    key(p, Qt.Key.Key_Down)
    assert current(p) == "Update area 3 guard drawings"
    key(p, Qt.Key.Key_Left)
    assert p.list.depth == 0 and current(p) == "Verification walkthrough readiness"
    key(p, Qt.Key.Key_Right)
    key(p, Qt.Key.Key_Return)
    assert search.app.opened == [("page", "T000017")]


def test_task_search_ctrl_enter_does_the_other(search):
    p = search.picker
    p.search.setText("rigging")
    key(p, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert search.app.opened == [("task_view", RIGGING)]


def test_task_search_finds_closed_tasks_marked_as_closed(search, env):
    ctx, _, _ = env
    closed = next(t for t in ctx.model().tasks.values() if t.state == "Closed" and not t.discarded)
    p = search.picker
    p.search.setText(closed.title)
    assert [o.label for o in p.rows() if o.ref == closed.id] == [f"{closed.title} (closed)"]


def test_task_search_searches_everything_when_nothing_matches(search):
    p = search.picker
    p.search.setText("zzzqqq")
    assert labels(p) == ["No task matches. Search everything for “zzzqqq”"]
    key(p, Qt.Key.Key_Return)
    assert search.app.opened == [("page", None)] and search.app.browse.search_box.text() == "zzzqqq"


def test_task_search_before_typing_has_recent_and_no_none(search):
    p = search.picker
    assert labels(p)[0] == "Recent" and "None" not in labels(p) and "Tasks" in labels(p)


# ---- the Timeline's Focus on ----
def _focus_on(view) -> None:
    """The Focus on picker lists only the tasks Focus on can show, Right walks them, and a pick focuses the Timeline."""
    p = view.focus_picker
    assert labels(p)[labels(p).index("Tasks") - 1] == "All projects"  # its None
    assert labels(p)[labels(p).index("Tasks") + 1:] == ["Reactor impeller upgrade", "Verification walkthrough readiness"]  # with open subtasks
    while current(p) != "Reactor impeller upgrade":
        key(p, Qt.Key.Key_Down)
    key(p, Qt.Key.Key_Right)
    assert labels(p) == ["Reactor impeller upgrade", "Installation"] and current(p) == "Installation"  # it has its own; the rest don't
    key(p, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert view.focus == INSTALLATION


def test_focus_on_is_the_picker_of_tasks_with_subtasks(env):
    ctx, _, browse = env
    browse.show_browse()
    browse.set_view("timeline")
    QApplication.processEvents()
    view = browse.timeline
    view.focus_box.click()
    _focus_on(view)
    assert view.focus_box.text() == "Installation" and view.focus_box.toolTip() == "Reactor impeller upgrade › Installation"
    view.focus_box.click()
    p = view.focus_picker
    while current(p) != "All projects":
        key(p, Qt.Key.Key_Down)
    key(p, Qt.Key.Key_Return)
    assert view.focus is None and view.focus_box.text() == "All projects"


def test_the_classic_looks_focus_on_too(qapp, sample_root):
    from docrepo.ui.look import configure
    from docrepo.ui.widgets import DropButton

    conn, root, fs = sample_root
    configure("classic", False)
    try:
        ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
        capture = CaptureWindow(ctx)
        browse = BrowseWindow(ctx, capture)
        browse.show_browse()
        browse.set_view("timeline")
        QApplication.processEvents()
        view = browse.timeline

        def button() -> DropButton:
            return next(b for b in view.findChildren(DropButton) if b.accessibleName() == "Focus on" and b.isVisibleTo(view))

        assert button().text() == "Focus on all projects"
        button().click()
        _focus_on(view)
        assert button().text() == "Focus on Installation"
        capture.deleteLater()
        browse.deleteLater()
    finally:
        configure("new", False)


# ---- the agenda picker ----
def test_the_agenda_picker_finds_tasks_as_the_hash_list_does(env):
    _, capture, _ = env
    assert [o.label for o in capture._agenda_options("plan rigging", [])] == ["Rigging plan"]
    assert "Book the alignment contractor" in [o.label for o in capture._agenda_options("installation book", [])]
    assert "Tyler Nguyen" in [o.label for o in capture._agenda_options("yler", [])]  # a person by any part of a name, as before
