"""One read of docs.db for a change, in the browse tool (release 5.163, the design workspace's ``docs/mods/one-read-plan.md``,
decisions 746 and 747): with a task's page showing, a state change from a row's state menu, its Undo, Edit task's save,
Quick edit's save and a few of the other changes each read docs.db once, after the change, and the windows drawn after it
read nothing more, as the Model it read is kept as the shared one. Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
IMPELLER, INSTALLATION, RIGGING, ALIGNMENT = "T000001", "T000008", "T000012", "T000019"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    """The browse tool on Today, with Installation's page showing."""
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW), None)
    w.show_browse("today")
    w.resize(1600, 900)
    w.sel = ("task", INSTALLATION)
    w.render_all()
    QApplication.processEvents()
    yield w
    if w.quick_window is not None:
        w.quick_window.close()
    for view in list(w.task_views.values()):
        view.close()
    w.deleteLater()


def reads(monkeypatch) -> list[int]:
    """Each Model read from docs.db from now on."""
    import docrepo.model as model_module

    loads: list[int] = []
    init = model_module.Model.__init__
    monkeypatch.setattr(model_module.Model, "__init__", lambda self, c: (loads.append(1), init(self, c))[1])
    return loads


def drawn(monkeypatch, w: BrowseWindow) -> list[str]:
    calls: list[str] = []
    for name in ("render_list", "render_detail"):
        was = getattr(w, name)
        monkeypatch.setattr(w, name, lambda *a, _was=was, _name=name, **k: (calls.append(_name), _was(*a, **k))[1])
    return calls


def kept(w: BrowseWindow) -> bool:
    """The shared Model is the one read after the change: docs.db is as it read it, so asking for it reads nothing."""
    m = w.ctx.model()
    return m.read_at == edits.read_now(w.conn) and w.ctx.model() is m


def test_a_state_change_reads_docs_db_once_and_its_undo_once(browse, monkeypatch):
    loads, calls = reads(monkeypatch), drawn(monkeypatch, browse)
    assert browse.set_state(INSTALLATION, "Parked")
    assert len(loads) == 1 and kept(browse) and len(loads) == 1
    assert {"render_list", "render_detail"} <= set(calls)  # the list and the page drawn again, from the kept Model
    assert browse.model().task(INSTALLATION).state == "Parked" and Model(browse.conn).task(INSTALLATION).state == "Parked"
    loads.clear()
    browse._status_link("undo")
    assert len(loads) == 1 and kept(browse) and len(loads) == 1
    assert browse.model().task(INSTALLATION).state == "In progress" == Model(browse.conn).task(INSTALLATION).state
    assert browse.status.text() == "Set back. The status log keeps both changes."
    log = [(e.field, e.from_value, e.to_value) for e in Model(browse.conn).status_log_of(INSTALLATION) if e.field == "State"]
    assert log[-2:] == [("State", "In progress", "Parked"), ("State", "Parked", "In progress")]


def test_a_branch_closed_from_its_row_reads_once(browse, monkeypatch):
    loads = reads(monkeypatch)
    assert browse.set_state(INSTALLATION, "Closed", branch=True)
    assert len(loads) == 1 and kept(browse)
    m = browse.model()
    assert m.task(INSTALLATION).state == "Closed" and m.task(RIGGING).state == "Closed"
    loads.clear()
    browse._status_link("undo")  # the whole branch back, as one change
    assert len(loads) == 1 and kept(browse) and browse.model().task(RIGGING).state == "In progress"


def test_edit_tasks_save_reads_docs_db_once(browse, monkeypatch):
    """Asking what the move would reach is a change made and rolled back, which leaves the shared Model as it is
    (``AppContext.rolled_back``), so the save is handed it and reads docs.db once, after."""
    def save(dialog) -> bool:
        dialog.due.set_value("2026-11-06")
        return True

    browse.run_dialog = save
    loads = reads(monkeypatch)
    browse.edit_task(INSTALLATION)
    assert len(loads) == 1 and kept(browse)
    assert browse.model().task(INSTALLATION).due == "2026-11-06" == Model(browse.conn).task(INSTALLATION).due
    assert browse.status.text().startswith("1 change in the status log.")


def test_quick_edits_save_reads_docs_db_once(browse, monkeypatch):
    browse.quick_edit(INSTALLATION, QRect(400, 300, 120, 20))
    QApplication.processEvents()
    w = browse.quick_window
    w.dates["due"].set_value("2026-11-06")
    w.dates["due"].edited.emit()
    QApplication.processEvents()
    loads, calls = reads(monkeypatch), drawn(monkeypatch, browse)
    w.save()
    QApplication.processEvents()
    assert not w.isVisible() and len(loads) == 1 and kept(browse)
    assert "render_detail" in calls  # the browse tool drawn again on the saved task, from the kept Model
    assert browse.model().task(INSTALLATION).due == "2026-11-06" == Model(browse.conn).task(INSTALLATION).due


def test_the_other_changes_through_do_read_docs_db_once(browse, monkeypatch):
    loads = reads(monkeypatch)
    browse.add_to_today(RIGGING)  # D
    assert len(loads) == 1 and kept(browse) and RIGGING in {a.subject for a in browse.model().today_items()}
    item = next(a.id for a in browse.model().today_items() if a.subject == RIGGING)
    loads.clear()
    browse.close_today_item(item, "Removed")  # Remove, on Today
    assert len(loads) == 1 and kept(browse) and RIGGING not in {a.subject for a in browse.model().today_items()}
    loads.clear()
    browse._status_link("undo")  # back on Today
    assert len(loads) == 1 and kept(browse) and RIGGING in {a.subject for a in browse.model().today_items()}
    loads.clear()
    browse.clear_reminder(ALIGNMENT, "Today")
    assert len(loads) == 1 and kept(browse) and browse.model().task(ALIGNMENT).reminder is None
    loads.clear()
    browse.do_later(RIGGING, day=date(2026, 10, 13), item_id=item)  # Later, off Today
    assert len(loads) == 1 and kept(browse) and browse.model().task(RIGGING).reminder == "2026-10-13"
    loads.clear()
    browse._status_link("undo")
    assert len(loads) == 1 and kept(browse) and browse.model().task(RIGGING).reminder is None


def test_a_model_handed_back_isnt_kept_after_another_write(browse):
    """``AppContext.keep`` refuses a Model read before a later write, or on another connection."""
    c = browse.ctx
    out = edits.add_to_today(c.conn, c.data_root, c.fs, RIGGING, "", NOW, c.model())
    assert out.model is not None
    edits.add_to_today(c.conn, c.data_root, c.fs, IMPELLER, "", NOW)  # a write after it was read
    assert not c.keep(out.model) and c.model() is not out.model
    assert {RIGGING, IMPELLER} <= {a.subject for a in c.model().today_items()}


def test_asking_what_a_move_reaches_leaves_the_shared_model(browse):
    """``AppContext.rolled_back`` keeps the shared Model through a change made and rolled back, and its ``read_at`` with it,
    so the change after it is handed that Model (``edits.model_now``) rather than read docs.db again."""
    c = browse.ctx
    m = c.model()
    followed = c.rolled_back(lambda: edits.edit_moves(c.conn, c.settings, INSTALLATION, NOW, due="2026-11-06"))
    assert isinstance(followed, list) and c.model() is m
    assert m.read_at == edits.read_now(c.conn) and edits.model_now(c.conn, m) is m
    assert Model(c.conn).task(INSTALLATION).due == m.task(INSTALLATION).due != "2026-11-06"  # nothing kept
