"""The icon and the empty states (release 5.196, the redesign's decision 871): DocRepo's own icon, drawn in the accent and
set on the application at every size; and each list view's three empty cases, first use, nothing matching and nothing
left, each with its words and its one button doing its one thing, in light and in dark."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from docrepo import db, edits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import app_icon, empty_state, tokens  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
#: Every list view drawn in the browse tool's list (Priorities, the Timeline and Settings draw their own).
LIST_VIEWS = ("today", "unfiled", "tasks", "due", "reminders", "waiting", "mine", "unplanned", "agenda", "activity", "people",
              "labels", "tagged", "glossaries", "templates", "docs", "discarded")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["light", "dark"])
def theme(request, qapp):
    tokens.use(request.param)
    yield request.param
    tokens.use("light")


def _browse(conn, root, fs, me: str = "") -> BrowseWindow:
    ctx = AppContext(conn, root, fs, Settings(me=me), now=lambda: NOW)
    w = BrowseWindow(ctx, None)
    w.show_browse()
    return w


@pytest.fixture
def empty_root(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    w = _browse(conn, data_root, fs)
    yield w
    w.deleteLater()
    conn.close()


@pytest.fixture
def sample(qapp, sample_root):
    conn, root, fs = sample_root
    w = _browse(conn, root, fs, me="P001")
    yield w
    w.deleteLater()


def state(w: BrowseWindow):
    """The empty state showing in the list, or None."""
    e = w.tree._empty
    return e if e is not None and not e.isHidden() else None


# ---- the icon ----
def test_the_icon_is_drawn_at_every_size_and_set_on_the_application(qapp, theme):
    from docrepo import app as docrepo_app

    icon = app_icon.make_icon()
    sizes = sorted(s.width() for s in icon.availableSizes())
    assert {16, 32, 48} <= set(sizes) and sizes[0] == 16
    for size in (16, 32, 48):
        assert not icon.pixmap(size, size).isNull()
    docrepo_app.set_identity(qapp)
    assert not qapp.windowIcon().isNull() and not QWidget().windowIcon().isNull()


@pytest.mark.parametrize("size", [16, 32, 48])
def test_the_icon_is_the_accent_with_a_white_task_tree_the_same_in_both_themes(qapp, size):
    """At 16 px each part falls on whole pixels: the corner is clear, the square is the accent's indigo, the titles' bars
    are white, the subtasks are indented and a gap parts the rows. The same in light and dark."""
    seen = {}
    for theme in ("light", "dark"):
        tokens.use(theme)
        image = app_icon.draw(size).toImage()

        def at(x: float, y: float, image=image) -> QColor:
            k = size / app_icon.GRID
            return image.pixelColor(int(x * k), int(y * k))

        assert at(0, 0).alpha() == 0  # outside the rounded corner
        assert at(2, 8).name() == "#4a54d1"  # the square, left of the mark
        assert at(8, 4).name() == "#ffffff"  # the parent's title
        assert at(11, 12).name() == "#ffffff"  # the second subtask's
        assert at(4, 4).lightness() > QColor("#4a54d1").lightness()  # the parent's status circle
        assert at(4, 8).name() == "#4a54d1"  # the subtasks are indented: nothing under the parent's circle
        assert at(10, 6).name() == "#4a54d1"  # between the parent's row and the first subtask's
        seen[theme] = image
    tokens.use("light")
    assert seen["light"] == seen["dark"]


# ---- first use ----
def test_on_an_empty_data_root_every_list_view_says_what_it_is_for(empty_root, theme):
    w = empty_root
    for view in LIST_VIEWS:
        w.set_view(view)
        e = state(w)
        assert e is not None and e.empty.case == empty_state.FIRST, view
        words = e.words.text()
        assert words.endswith(".") and "!" not in words and "Oops" not in words, view
        assert not e.icon.isHidden(), view


@pytest.mark.parametrize(("view", "button", "calls"), [
    ("tasks", "New task", ("open_capture", {"mode": "new_task"})),
    ("today", "New task", ("open_capture", {"mode": "new_task"})),
    ("due", "New task", ("open_capture", {"mode": "new_task"})),
    ("unfiled", "New capture", ("open_capture", {})),
    ("activity", "New capture", ("open_capture", {})),
    ("people", "Add person", ("add_person", {})),
    ("labels", "Add label", ("add_label", {})),
])
def test_first_use_offers_the_button_that_makes_the_first_one(empty_root, monkeypatch, view, button, calls):
    w = empty_root
    asked = []
    monkeypatch.setattr(w, calls[0], lambda *a, **k: asked.append(k))
    w.set_view(view)
    e = state(w)
    assert e.button.text() == button and e.button.isVisibleTo(e)
    e.button.click()
    assert asked == [calls[1]]


def test_first_use_with_nothing_to_press_has_no_button(empty_root):
    for view in ("agenda", "docs", "discarded"):
        empty_root.set_view(view)
        e = state(empty_root)
        assert not e.button.isVisibleTo(e), view


def test_the_empty_state_goes_when_there_is_something_to_show(sample):
    for view in ("tasks", "unfiled", "people", "labels", "activity"):
        sample.set_view(view)
        assert sample.tree.shows_a_row() and state(sample) is None, view


# ---- nothing matching ----
def test_find_that_matches_nothing_says_so_and_clear_find_brings_the_rows_back(sample, theme):
    w = sample
    w.set_view("tasks")
    w.open_find()
    w.find_box.setText("zzqqxx")
    w._apply_find()
    e = state(w)
    assert e.empty.case == empty_state.MATCHING and "zzqqxx" in e.words.text() and e.button.text() == "Clear Find"
    e.button.click()
    assert w.find_bar.isHidden() and w.tree.shows_a_row() and state(w) is None


def test_a_filter_that_matches_nothing_says_so_and_clears_from_the_empty_state(sample):
    w = sample
    w.set_view("tasks")
    w._set_filter("labels", ["No such label"])
    e = state(w)
    assert e.empty.case == empty_state.MATCHING and e.button.text() == "Clear filter"
    assert "Labels" in e.words.text()
    e.button.click()
    assert w.tree_filter["labels"] == [] and w.tree.shows_a_row() and state(w) is None


def test_two_filters_say_filters(sample):
    w = sample
    w.set_view("tasks")
    w._set_filter("labels", ["No such label"])
    w._set_filter("urgent", True)
    e = state(w)
    assert e.button.text() == "Clear filters" and e.words.text() == "Nothing here matches the filters."
    e.button.click()
    assert not w.tree_filter["labels"] and not w.tree_filter.get("urgent") and w.tree.shows_a_row()


# ---- nothing left ----
def test_unfiled_says_every_capture_is_filed_once_they_are(sample):
    w = sample
    m = w.model()
    task = next(t.id for t in m.tasks.values() if not t.discarded)
    for c in m.unfiled_captures():
        edits.file_capture(w.conn, w.ctx.data_root, w.ctx.fs, c.id, task, NOW)
    w.set_view("unfiled")
    e = state(w)
    assert e.empty.case == empty_state.LEFT and e.words.text() == "Every capture is filed." and not e.button.isVisibleTo(e)


def test_today_says_everything_is_done_once_it_is(sample):
    w = sample
    edits.add_to_today(w.conn, w.ctx.data_root, w.ctx.fs, None, "Ring the vendor", NOW)
    w.set_view("today")
    assert state(w) is None or state(w).empty.case != empty_state.LEFT or "done" not in state(w).words.text()
    item = w.model().today_items()[0]
    edits.close_agenda_item(w.conn, w.ctx.data_root, w.ctx.fs, item.id, "Done", NOW)
    w.set_view("today")
    e = state(w)
    assert e.empty.case == empty_state.LEFT and e.words.text() == "Everything on Today is done." and not e.button.isVisibleTo(e)


def test_a_list_emptied_by_the_work_says_so_in_its_own_words(sample, monkeypatch):
    from docrepo.ui.lists import tasks as task_lists

    w = sample
    monkeypatch.setattr(task_lists, "list_tree", lambda *a, **k: [])
    for view, words in empty_state.LIST_LEFT.items():
        w.set_view(view)
        e = state(w)
        if e is None:  # a key date's row is the list's row (Overdue and next 7 days)
            assert view == "due" and w.tree.shows_a_row()
            continue
        assert e.empty.case == empty_state.LEFT and e.words.text() == words, view


def test_the_empty_state_sits_below_the_rows_that_show(sample):
    w = sample
    edits.add_to_today(w.conn, w.ctx.data_root, w.ctx.fs, None, "Ring the vendor", NOW)
    edits.close_agenda_item(w.conn, w.ctx.data_root, w.ctx.fs, w.model().today_items()[0].id, "Done", NOW)
    w.set_view("today")
    e = state(w)
    last = max(w.tree.visualItemRect(i).bottom() for i in w.tree.items() if w.tree._in_sight(i))
    assert e.y() > last


def test_the_next_draw_takes_the_empty_state_away(empty_root):
    w = empty_root
    w.set_view("tasks")
    assert state(w) is not None
    w.tree.begin()
    assert state(w) is None and w.tree.wanted_empty is None
    w.tree.end()
