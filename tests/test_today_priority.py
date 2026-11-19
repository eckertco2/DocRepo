"""Today in priority order (release 5.154, the design workspace's ``docs/mods/today-priority-plan.md``, decisions 688 to
694), without Qt: the bands and the owner's order within each, moves kept to a band, a bin's drop setting the priority and
the place, a note with Not ranked, a new item at the end of its band, Contents.md in band order, and the width widened."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from docrepo import agenda, edits, panel_rules, priorities, views
from docrepo.model import TODAY, TODAY_BANDS, Model

AT = datetime(2026, 10, 8, 15, 20)


def ids(conn: sqlite3.Connection) -> list[int]:
    return [a.id for a in Model(conn).today_items()]


def add(conn, subject=None, note="", added="2026-10-08 09:00:00") -> int:
    return agenda.add_item(conn, subject=subject, target=TODAY, note=note, added=added, added_by="Browse tool")


def rank(conn, task_id: str, bucket: str) -> None:
    priorities.place(conn, task_id, bucket, None, at=AT, via=priorities.VIA)


@pytest.fixture
def today(sample_conn):
    """Five made-up items, added in this order: a Medium task, a note, a task not ranked, a High task and a Parking lot one."""
    conn = sample_conn
    rank(conn, "T000019", "medium")
    rank(conn, "T000016", "high")
    rank(conn, "T000018", "parking")
    medium = add(conn, "T000019", added="2026-10-05 08:05:00")
    note = add(conn, note="Sign the overtime sheets", added="2026-10-08 07:50:00")
    plain = add(conn, "T000012", added="2026-10-08 08:00:00")
    high = add(conn, "T000016", added="2026-10-08 08:30:00")
    parked = add(conn, "T000018", added="2026-10-08 08:40:00")
    return conn, {"medium": medium, "note": note, "plain": plain, "high": high, "parking": parked}


def test_today_is_in_priority_bands_with_the_owners_order_inside(today):
    conn, i = today
    assert ids(conn) == [i["high"], i["medium"], i["note"], i["plain"], i["parking"]]  # decision 688; the note with Not ranked (692)
    bands = views.today_bands(Model(conn))
    assert [(key, name, [a.id for a in items]) for key, name, items in bands] == [
        ("high", "High", [i["high"]]), ("medium", "Medium", [i["medium"]]), ("", "Not ranked", [i["note"], i["plain"]]),
        ("parking", "Parking lot", [i["parking"]])]
    assert TODAY_BANDS.index("") == 3  # Not ranked where a Low would be (decision 693)
    assert views.today_bands(Model(conn)) and views.today_groups(Model(conn), AT.date())[0][0] == "Today"


def test_moves_keep_to_the_band(today, data_root, fs):
    conn, i = today
    plain, note = i["plain"], i["note"]
    out = edits.move_today_item(conn, data_root, fs, plain, AT, to="top")
    assert ids(conn) == [i["high"], i["medium"], plain, note, i["parking"]]  # the top of Not ranked, not of Today (689)
    assert out.message == "Rigging plan: moved to the top of Not ranked."
    assert edits.move_today_item(conn, data_root, fs, plain, AT, to="up").message == ""  # at its band's top: nothing
    assert edits.move_today_item(conn, data_root, fs, note, AT, to="down").message == ""
    edits.move_today_item(conn, data_root, fs, plain, AT, to="down")
    assert ids(conn) == [i["high"], i["medium"], note, plain, i["parking"]]
    with pytest.raises(edits.EditError, match="within its band, Not ranked"):
        edits.move_today_item(conn, data_root, fs, plain, AT, beside=(i["high"], "before"))
    edits.move_today_item(conn, data_root, fs, plain, AT, beside=(note, "before"))
    assert ids(conn) == [i["high"], i["medium"], plain, note, i["parking"]]


def test_the_order_kept_is_the_order_shown(today, data_root, fs):
    """A move first gives every open item its place in the order shown, bands and all, so pos and the list agree."""
    conn, i = today
    edits.move_today_item(conn, data_root, fs, i["plain"], AT, to="top")
    assert agenda.order_of(conn) == ids(conn)


def test_a_drop_on_a_bin_sets_the_priority_and_goes_to_the_end_of_the_band(today, data_root, fs):
    conn, i = today
    out = edits.today_bin(conn, data_root, fs, i["plain"], "high", AT)
    m = Model(conn)
    assert m.task("T000012").priority == "high" and out.message == "Rigging plan: High. Its history says so."
    assert ids(conn) == [i["high"], i["plain"], i["medium"], i["note"], i["parking"]]  # the end of High (decision 691)
    line = [e for e in m.status_log_of("T000012") if e.field == priorities.FIELD][-1]
    assert (line.from_value, line.to_value, line.via) == (None, "High", edits.TODAY_BINS)
    assert priorities.bucket_ids(m, "high")[-1] == "T000012"  # the end of its bucket on the Priorities board too


def test_a_bin_into_an_empty_band_and_back_to_not_ranked(today, data_root, fs):
    conn, i = today
    edits.today_bin(conn, data_root, fs, i["medium"], "critical", AT)
    assert ids(conn)[0] == i["medium"] and Model(conn).task("T000019").priority == "critical"
    edits.today_bin(conn, data_root, fs, i["medium"], "", AT)  # Not ranked takes the priority off
    assert Model(conn).task("T000019").priority is None
    # The end of Not ranked's urgent half (release 5.176, decision 822): the alignment contractor is ticked Urgent and due
    # tomorrow, so it's first there; before 5.176, the end of Not ranked.
    assert ids(conn) == [i["high"], i["medium"], i["note"], i["plain"], i["parking"]]


def test_a_bin_of_its_own_band_and_a_note_change_nothing(today, data_root, fs):
    conn, i = today
    before = ids(conn)
    assert edits.today_bin(conn, data_root, fs, i["high"], "high", AT).message == ""
    with pytest.raises(edits.EditError, match="A note has no priority"):
        edits.today_bin(conn, data_root, fs, i["note"], "high", AT)
    with pytest.raises(edits.EditError, match="Today's bins are"):
        edits.today_bin(conn, data_root, fs, i["plain"], "low", AT)  # no Low (decision 693)
    assert ids(conn) == before


def test_a_new_item_goes_to_the_end_of_its_band(today, data_root, fs):
    conn, i = today
    edits.move_today_item(conn, data_root, fs, i["plain"], AT, to="top")  # the list has places now
    rank(conn, "T000008", "high")
    new = add(conn, "T000008")
    assert ids(conn) == [i["high"], new, i["medium"], i["plain"], i["note"], i["parking"]]


def test_contents_lists_today_in_band_order(today, data_root, fs):
    conn, i = today
    edits.today_bin(conn, data_root, fs, i["plain"], "critical", AT)
    text = (data_root / "Contents.md").read_text(encoding="utf-8")
    today_part = text[text.index("Today"):]
    assert today_part.index("Rigging plan") < today_part.index("Holiday coverage schedule") < today_part.index("Book the alignment contractor")


# ---- the width widened (decision 694) ----
def test_the_width_widened_has_its_limits():
    assert panel_rules.wide_limits(180, 1920) == (260, 1280)
    assert panel_rules.wide_limits(900, 1200) == (980, 980)  # never less than the narrowest
    assert panel_rules.dragged_wide("right", 320, -100, 260, 1280) == 420  # on the right, dragging left widens it
    assert panel_rules.dragged_wide("left", 320, -100, 260, 1280) == 260
    assert panel_rules.dragged_wide("right", 320, -5000, 260, 1280) == 1280


def test_the_width_widened_kept_or_the_configs():
    assert panel_rules.wide_width(None, 320, 1920) == 320
    assert panel_rules.wide_width("", 320, 1920) == 320
    assert panel_rules.wide_width("rubbish", 320, 1920) == 320
    assert panel_rules.wide_width("480", 320, 1920) == 480
    assert panel_rules.wide_width("4000", 320, 1920) == 1280  # two thirds of the screen at most
    assert panel_rules.wide_width("50", 320, 1920) == panel_rules.MIN_REST_WIDTH + panel_rules.WIDE_OVER_REST
