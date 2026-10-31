"""Key dates from text and the capture window (release 5.31, the key dates plan, items 57 and 60; since release 5.38 a
``**key date,`` line, read as ``test_quick_input.py`` checks): saved onto its task, and New task's and Update's Key dates rows."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import captures, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, NewTaskFields, save_capture  # noqa: E402
from docrepo.tasks import KeyDateRow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

AT = datetime(2026, 10, 8, 9, 30)
SETTINGS = Settings(me="P001")


def key_dates_of(conn, task_id: str) -> list[tuple]:
    return [(kd.start, kd.end, kd.description, kd.plant, kd.deadline) for kd in Model(conn).key_dates_of(task_id)]


def test_saving_adds_each_date_line_to_its_task(sample_root):
    conn, root, fs = sample_root
    content = ("Walkdown with Tom.\n**key date, Dec 1 to 5 trial execution window, plant activity.\n"
               "**key date, by Nov 25 prep done, deadline, #Rigging plan.\n**key date, trial planning period.")
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=content, task="T000008"), AT)
    assert key_dates_of(conn, "T000008") == [("2026-12-01", "2026-12-05", "Trial execution window", True, False)]
    assert key_dates_of(conn, "T000012") == [(None, "2026-11-25", "Prep done", False, True)]  # its # task's
    assert r.made.get("date") == 2 and "Made 2 key dates from its items." in r.message  # the one with no date isn't made
    log = conn.execute("SELECT field, via FROM status_log WHERE task = 'T000008' AND field = 'Key date'").fetchall()
    assert [tuple(x) for x in log] == [("Key date", r.capture_id)]  # logged as the notes'
    c = Model(conn).captures[r.capture_id]
    assert "**key date, Dec 1 to 5 trial execution window, plant activity." in captures.read_content(root, c)  # the notes keep the line
    assert not any(x.item == "date" for x in Model(conn).captures.values())  # no capture of its own


def test_an_unticked_card_adds_nothing_and_a_changed_title_is_its_description(sample_root):
    conn, root, fs = sample_root
    content = "Notes.\n**key date, on Nov 2 pump test.\n**key date, by Nov 9 seal check."
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=content, task="T000008",
                                                         item_overrides={"0": {"off": True}, "1": {"title": "Seal check, both pumps"}}), AT)
    assert key_dates_of(conn, "T000008") == [(None, "2026-11-09", "Seal check, both pumps", False, False)]


def test_a_new_task_takes_its_rows_and_its_date_lines(sample_root):
    conn, root, fs = sample_root
    draft = CaptureDraft(content="New product trial 1\n**key date, by Nov 25 target for trial preparations.", types={"new_task"},
                         new_task=NewTaskFields(title="New product trial 1", key_dates=[
                             KeyDateRow("2026-10-12", None, "Trial planning period"),
                             KeyDateRow("2026-12-01", "2026-12-05", "Trial execution window", plant=True)]))
    r = save_capture(conn, root, fs, SETTINGS, draft, AT)
    assert key_dates_of(conn, r.created_task) == [("2026-10-12", None, "Trial planning period", False, False),
                                                  ("2026-12-01", "2026-12-05", "Trial execution window", True, False),
                                                  (None, "2026-11-25", "Target for trial preparations", False, False)]
    vias = {x["via"] for x in conn.execute("SELECT via FROM status_log WHERE task = ? AND field = 'Key date'", (r.created_task,))}
    assert vias == {r.capture_id}


def test_an_update_changes_the_task_s_rows(sample_root):
    conn, root, fs = sample_root
    tasks.set_key_dates(conn, "T000008", [KeyDateRow(None, "2026-11-25", "Prep"), KeyDateRow("2026-12-01", "2026-12-05", "Run")],
                        at=AT, via="Browse tool")
    rows = tasks.key_date_rows(conn, "T000008")
    rows[0].done = True
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="", task="T000008", types={"update"}, update_key_dates=[rows[0]]), AT)
    assert [c.field for c in r.changes] == ["Key date done", "Key date"]  # Prep done, Run taken off
    assert [(kd.description, bool(kd.done)) for kd in Model(conn).key_dates_of("T000008")] == [("Prep", True)]


# ---- the capture window's rows ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: AT)
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()


def test_new_task_s_rows_in_the_window(window):
    window.set_type("new_task", True)
    window.title.setText("New product trial 1")
    ed = window.n_keydates
    assert ed.body.isHidden() and ed.rows() == []  # folded until there's one
    ed.toggle.click()
    assert not ed.body.isHidden() and len(ed.lines) == 1
    line = ed.lines[0]
    line.description.setText("Trial execution window")
    line.start.set_value("2026-12-01")
    line.end.set_value("2026-12-05")
    line.plant.setChecked(True)
    ed.add_row()  # a blank row is left out
    assert window.draft().new_task.key_dates == [KeyDateRow("2026-12-01", "2026-12-05", "Trial execution window", True, False, False, None)]
    assert ed.toggle.text().startswith("Key dates (1)")
    line.end.set_value("2026-11-20")  # before its start: Save stops and says so
    assert not window._check_fields()


def test_update_s_rows_start_as_the_task_s_own(window, sample_root):
    conn = sample_root[0]
    tasks.set_key_dates(conn, "T000008", [KeyDateRow(None, "2026-11-25", "Prep")], at=AT, via="Browse tool")
    window.set_task("T000008")
    window.set_type("update", True)
    window.prefill()
    ed = window.u_keydates
    assert [x.description for x in ed.rows()] == ["Prep"] and not ed.body.isHidden()
    assert window.update_key_dates() is None  # unchanged: nothing to log
    ed.lines[0].done.setChecked(True)
    window.refresh()
    assert window.update_key_dates()[0].done and "key dates" in window.changes_label.text()
    assert window.draft().update_key_dates[0].done
