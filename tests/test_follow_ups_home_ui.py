"""Release 5.142 in the windows, offscreen (the design workspace's notes consolidation plan, decisions 610 and 612): the
capture window's cards saying where Meeting notes' follow-ups go, and Tidy's preview, move and Undo from the browse window.
``test_follow_ups_home.py`` has the rest, without Qt. Made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import items, tasks  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import tidy_follow_ups  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import where_text  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402

NOW = datetime(2026, 11, 13, 9, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    ex = build(conn, root, fs)
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    yield w, capture, ex
    capture.deleteLater()


def test_the_cards_say_where_follow_ups_go(setup):
    w, capture, ex = setup
    names = capture.names()
    reading = items.read("- Rake the basin @Tom\n#Crane for the fan lift\n- @Mike check the hook", names, NOW.date(), home=True)
    first, second = (it for it in reading.items if it.kind == "task")
    assert where_text(first, "Cooling tower weekly 13 Nov", names, reading, "Cooling tower 2 rebuild") == "Cooling tower 2 rebuild"
    assert where_text(second, "Cooling tower weekly 13 Nov", names, reading, "Cooling tower 2 rebuild") == "Crane for the fan lift"
    assert where_text(first, "Cooling tower weekly 13 Nov", names, reading) == "Cooling tower weekly 13 Nov"  # outside Meeting notes, as before
    capture.task = ex.project
    capture.meeting_on = True
    assert capture._follow_up_home_name() == "Cooling tower 2 rebuild"
    capture.meeting_on = False
    assert capture._follow_up_home_name() is None


def test_tidy_from_the_browse_window_with_undo(setup):
    w, _capture, ex = setup
    conn = w.conn
    at = datetime(2026, 11, 10, 10, 0)
    for task in (ex.survey, ex.fill, ex.crane):
        tasks.set_parents(conn, task, [ex.kickoff], at=at, via="test")
    w.refresh()
    seen = []

    def accept(dialog) -> bool:
        seen.append([dialog.rows.item(i).text() for i in range(dialog.rows.count())])
        dialog.rows.item(2).setCheckState(Qt.CheckState.Unchecked)  # leave the crane
        return True

    w.run_dialog = accept
    w.go_task(ex.kickoff)
    QApplication.processEvents()
    assert tidy_follow_ups.run(w, ex.kickoff)
    assert seen[0][0] == "Structural survey of the fan deck: out of Cooling tower kickoff, under Cooling tower 2 rebuild"
    m = Model(conn)
    assert m.parents_of(ex.survey) == [ex.project] and m.parents_of(ex.crane) == [ex.kickoff]
    assert "Moved 2 follow-ups out of Cooling tower kickoff." in w.said[-1][0] and w._undo is not None
    w._undo()
    QApplication.processEvents()
    assert Model(conn).parents_of(ex.survey) == [ex.kickoff]
    w.run_dialog = lambda dialog: False
    assert not tidy_follow_ups.run(w, ex.project)  # cancelled: nothing moves
    assert Model(conn).parents_of(ex.fill) == [ex.kickoff]
