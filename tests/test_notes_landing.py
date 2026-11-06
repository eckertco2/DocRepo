"""Where typed text lands on a notes page (release 5.94, the review of 2026-11-06, F13, the rule taken on 2026-11-06): at
the end of the page, under the note's heading only when the page's last heading has its words."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, notes_page, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

DAY = date(2026, 11, 6)
PAGE = "\n".join(["# Seals", "Ordered from the vendor.", "# Crane", "Booked for Tuesday."])


def test_a_heading_matching_one_mid_page_goes_at_the_end():
    page, under, landed = notes_page.place_note_where(PAGE, ["# Seals", "Arrived today."], DAY)
    assert page.split("\n") == ["# Seals", "Ordered from the vendor.", "# Crane", "Booked for Tuesday.", "# Seals", "Arrived today."]
    assert under == ["Seals"] and landed == [notes_page.Landing("Seals", "end", True)]


def test_a_heading_matching_the_last_goes_under_it():
    page, under, landed = notes_page.place_note_where(PAGE, ["# crane", "Lift plan signed."], DAY)
    assert page.split("\n") == ["# Seals", "Ordered from the vendor.", "# Crane", "Booked for Tuesday.", "Lift plan signed."]
    assert under == ["Crane"] and landed == [notes_page.Landing("Crane", "under")]


def test_a_heading_the_page_hasnt_goes_at_the_end_too():
    page, _, landed = notes_page.place_note_where(PAGE, ["## Rigging", "Slings tested."], DAY)
    assert page.endswith("Booked for Tuesday.\n## Rigging\nSlings tested.") and landed == [notes_page.Landing("Rigging", "end", False)]


def test_lines_under_no_heading_still_go_under_the_day():
    page, under, landed = notes_page.place_note_where(PAGE, ["Called the vendor."], DAY)
    assert under == ["Fri 6 Nov 2026"] and landed == [] and page.endswith("Called the vendor.")


# ---- the footer's sentence ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, DAY, settings)
    prompts.write_defaults(fs, data_root)
    notes_page.put(conn, "T000008", PAGE, datetime(2026, 11, 6, 9, 0), by_owner=True)
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: datetime(2026, 11, 6, 10, 0))
    w = CaptureWindow(ctx)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w.hide()
    w.deleteLater()
    conn.close()


def test_the_footer_says_at_the_end_when_the_match_is_higher_up(window):
    window.set_task("T000008")
    window.content.set_value("# Seals\nArrived today.", True)  # a heading is formatted text
    window.read_items()
    assert "Save adds this at the end of <b>Installation</b>'s notes (a <b>Seals</b> heading is higher up)." in window.does.text()


def test_the_footer_says_under_the_last_heading(window):
    window.set_task("T000008")
    window.content.set_value("# Crane\nLift plan signed.", True)
    window.read_items()
    assert "Save adds this to the notes of <b>Installation</b>, under <b>Crane</b>, the last heading there." in window.does.text()


def test_the_footer_for_text_under_no_heading_is_as_it_was(window):
    window.set_task("T000008")
    window.content.setPlainText("Called the vendor.")
    window.read_items()
    assert "adds this to the notes of <b>Installation</b>, under <b>Fri 6 Nov 2026</b>" in window.does.text()
