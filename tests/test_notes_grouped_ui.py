"""Release 5.157 in the browse window, offscreen (the design workspace's notes topics plan, decisions 709 to 717): All
notes' Group strip, kept per task; By meeting and By topic in the frame with the outline following the grouping, its
counts, a band folded from the outline or its line, a double-click finding its block, and the workspace's middle column.
``test_topics.py`` has the rest, without Qt. Made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import db  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_outline import COUNT  # noqa: E402
from notes_example import SETTINGS, build  # noqa: E402
from topics_example import give_topics  # noqa: E402

NOW = datetime(2026, 11, 17, 9, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    conn, root, fs = sample_root
    ex = build(conn, root, fs)
    give_topics(conn, ex, NOW)
    ctx = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    w.resize(1440, 900)
    yield w, ex
    capture.deleteLater()


def folds(w, task_id: str) -> dict:
    return json.loads(db.get_state(w.conn, f"page_folds:{task_id}") or "{}")


def all_notes_on(w, task_id: str):
    w.go_task(task_id)
    QApplication.processEvents()
    pane = w.task_pane
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    return pane


def words(pane) -> list[tuple[int, str]]:
    return [(level, text) for _n, level, _day, text in pane.all_outline.entries()]


def test_the_strip_shows_in_all_notes_and_is_kept_per_task(setup):
    w, ex = setup
    w.go_task(ex.project)
    QApplication.processEvents()
    pane = w.task_pane
    assert not pane.mode_strip.isHidden() and pane.group_box.isHidden()  # This page: no Group strip (709)
    pane.mode_buttons["all"].click()
    QApplication.processEvents()
    assert not pane.group_box.isHidden() and pane.group_buttons["day"].isChecked()
    pane.group_buttons["topic"].click()
    QApplication.processEvents()
    assert folds(w, ex.project)["notes_group"] == "topic" and pane.group_buttons["topic"].isChecked()
    assert "Schedule · 2 runs" in pane.all_view.toPlainText()
    w.go_task(ex.survey)  # the survey has nothing under it but its page and no task line: no switch, no strip
    QApplication.processEvents()
    assert pane.group_box.isHidden()
    w.go_task(ex.project)
    QApplication.processEvents()
    assert pane.all_mode and pane.group_buttons["topic"].isChecked() and "Schedule · 2 runs" in pane.all_view.toPlainText()
    pane.mode_buttons["page"].click()
    QApplication.processEvents()
    assert pane.group_box.isHidden() and not pane.all_mode


def test_a_narrow_pane_puts_the_strip_on_a_line_of_its_own(setup):
    """The Notes heading with both strips is wider than a narrow pane: the Group strip goes under it, with the format bar,
    so the heading's line is no wider than without it (offscreen's fonts are wider than Windows', so the widths aren't
    compared with the pane's here; ``test_real_look`` does that for This page)."""
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    w.resize(960, 700)
    w.split.setSizes([248, 2000, 0])  # the detail pane as narrow as it goes (test_real_look's)
    for _ in range(5):
        QApplication.processEvents()
    # Since release 5.185 the This page or All notes switch goes there too, first, so the heading fits with the page's wider edge.
    assert pane.bar_row is not None and pane.bar_lines() == [pane.mode_strip, pane.group_box, pane.format_bar]  # a line each since 5.186
    assert pane.head_row.indexOf(pane.group_box) == -1 and pane.head_row.indexOf(pane.mode_strip) == -1
    w.resize(2000, 900)
    w.split.setSizes([248, 200, 1550])
    for _ in range(5):
        QApplication.processEvents()
    assert pane.bar_row is None and pane.head_row.indexOf(pane.group_box) == pane.head_row.indexOf(pane.saved) - 1
    assert pane.head_row.indexOf(pane.mode_strip) == pane.head_row.indexOf(pane.title) + 2  # back after the title, as it was
    pane.mode_buttons["page"].click()  # This page: no Group strip on either line
    QApplication.processEvents()
    assert pane.group_box.isHidden()


def test_the_outline_follows_the_grouping(setup):
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    assert words(pane)[:3] == [(1, "Mon 2 Nov 2026"), (1, "Tue 3 Nov 2026"), (1, "Tue 10 Nov 2026")]  # By day's days, as before
    pane.group_buttons["meeting"].click()
    QApplication.processEvents()
    assert words(pane)[:4] == [(1, "Cooling tower 2 rebuild"), (2, "Notes · Mon 2 Nov"), (2, "Cooling tower kickoff"), (2, "Cooling tower weekly 10 Nov")]
    text = pane.all_view.toPlainText()
    assert "Cooling tower kickoff · Tue 3 Nov" in text and "follow-up, on its page" not in text
    pane.group_buttons["topic"].click()
    QApplication.processEvents()
    assert words(pane)[:3] == [(1, "Cooling tower 2 rebuild"), (2, "Schedule"), (3, "Outage window")]
    counts = {pane.all_outline.item(i).text(): pane.all_outline.item(i).data(COUNT) for i in range(pane.all_outline.count())}
    assert counts["Schedule"] == 2 and counts["Cooling tower 2 rebuild"] is None and counts["vendor"] == 4  # a topic's runs (713)


def test_a_band_folds_from_the_outline_and_from_its_line(setup):
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    pane.group_buttons["topic"].click()
    QApplication.processEvents()
    n = next(i for i, t in enumerate(pane._all_targets) if t == ("band", ex.survey))
    pane._all_picked(n)
    QApplication.processEvents()
    assert w.state.notes_folded == {ex.survey} and "Findings" not in pane.all_view.toPlainText()
    assert "Findings" not in [text for _level, text in words(pane)]  # its rows go from the outline too
    w.on_link(QUrl(f"allnotes:fold:{ex.survey}"))  # the chevron on its line
    QApplication.processEvents()
    assert w.state.notes_folded == set() and "Findings" in pane.all_view.toPlainText()
    w.go_task(ex.fill)
    w.go_task(ex.project)
    QApplication.processEvents()
    assert w.state.notes_folded == set()  # each task's own, for the visit


def test_an_outline_row_goes_to_its_topic(setup):
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    pane.group_buttons["topic"].click()
    QApplication.processEvents()
    n = next(i for i, t in enumerate(pane._all_targets) if t == ("anchor", f"topic:{ex.fill}:1"))
    assert pane.all_view.anchor_top(f"topic:{ex.fill}:1") is not None
    pane._all_picked(n)
    QApplication.processEvents()
    assert pane.all_outline.current == n


def test_a_double_click_finds_its_block_by_topic(setup):
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    pane.group_buttons["topic"].click()
    QApplication.processEvents()
    view = pane.all_view
    doc = view.document()
    b = doc.begin()
    while b.isValid() and "Vendor B holds its price" not in b.text():
        b = b.next()
    found = view.block_at(doc.documentLayout().blockBoundingRect(b).center().toPoint())
    assert found is not None and found[0] == ex.fill and found[1] == ""  # typed on its page: no capture
    b = doc.begin()
    while b.isValid() and not b.text().startswith("Tower 2 offline"):
        b = b.next()
    assert view.block_at(doc.documentLayout().blockBoundingRect(b).center().toPoint()) == (ex.kickoff, ex.kickoff_notes)


def test_the_workspace_has_the_strip_and_keeps_the_task_s_choice(setup):
    w, ex = setup
    pane = all_notes_on(w, ex.project)
    pane.group_buttons["meeting"].click()
    QApplication.processEvents()
    workspace_ui.open_workspace(w, ex.project)
    QApplication.processEvents()
    ws = w.workspace
    assert ws.pane.all_mode and not ws.pane.group_box.isHidden() and ws.pane.group_buttons["meeting"].isChecked()
    assert "Cooling tower kickoff · Tue 3 Nov" in ws.pane.all_view.toPlainText()
    ws.pane.group_buttons["topic"].click()
    QApplication.processEvents()
    assert folds(w, ex.project)["notes_group"] == "topic" and "Schedule · 2 runs" in ws.pane.all_view.toPlainText()
    n = next(i for i, t in enumerate(ws.pane._all_targets) if t == ("band", ex.survey))
    ws.pane._all_picked(n)
    QApplication.processEvents()
    assert ws.state.notes_folded == {ex.survey} and "Findings" not in ws.pane.all_view.toPlainText()
