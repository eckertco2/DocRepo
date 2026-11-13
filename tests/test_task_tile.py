"""The task tile's parts (release 5.138, the design workspace's ``docs/mods/task-tile-plan.md``, decisions 563 to 579):
the title's cut, the days, the marks, depth, the two-parents words and the page's HTML. No Qt, so the fast run has them."""
from __future__ import annotations

from datetime import date

import pytest

from docrepo import agenda, task_tile, waits
from docrepo.model import TODAY as TODAY_TARGET, Model
from docrepo.task_tile import ELLIPSIS, MINUS, days, days_to, fit_title, title_cuts

TODAY = date(2026, 10, 8)
BOOK, INSTALL, VERIFY, CLOSED, PARKED = "T000019", "T000008", "T000002", "T000005", "T000004"
REACTOR, RIGGING, OVERTIME, MONITORING = "T000001", "T000012", "T000015", "T000011"


# ================= the title's cut (decision 565) =================
@pytest.mark.parametrize("title, cuts", [
    ("Rigging plan for the impeller lift. Mike to confirm the crane size with the vendor", ["Rigging plan for the impeller lift"]),
    ("Order spare mechanical seal, the 4-inch cartridge type for P-204A", ["Order spare mechanical seal"]),
    ("Check torque values on the coupling bolts after the alignment run", []),
    ("Review rev. B of the vendor drawings. Comments go back to Priya by Friday", ["Review rev. B of the vendor drawings"]),
    ("Ask J. Smith about the 2.5 m spool. Then book it", ["Ask J. Smith about the 2.5 m spool"]),
    ("Order No. 4 seals; the old ones leak", ["Order No. 4 seals"]),
    ("Is the crane booked? Ask Mike", ["Is the crane booked"]),
    ("Fix pump, then the valve. Then tell Tom", ["Fix pump, then the valve", "Fix pump"]),
])
def test_a_title_is_cut_at_its_first_sentence_then_its_first_clause(title, cuts):
    assert title_cuts(title) == cuts


def test_a_cut_keeps_two_words_at_least():
    assert title_cuts("Done. Then file the report") == []
    assert title_cuts("Pumps, valves and seals") == []


def test_a_comma_after_the_first_sentence_isnt_a_cut():
    assert title_cuts("Fix pump. Then, check it") == ["Fix pump"]


def test_the_title_shows_whole_when_it_fits_else_the_longest_cut_that_fits():
    title = "Fix pump, then the valve. Then tell Tom"
    assert fit_title(title, 100, len) == title
    assert fit_title(title, 30, len) == "Fix pump, then the valve" + ELLIPSIS
    assert fit_title(title, 12, len) == "Fix pump" + ELLIPSIS


def test_a_title_with_no_cut_or_too_long_a_cut_is_cut_at_the_edge():
    assert fit_title("Check torque values on the coupling bolts", 15, len) == "Check torque v" + ELLIPSIS
    assert fit_title("Rigging plan for the impeller lift. Mike to confirm", 10, len) == "Rigging p" + ELLIPSIS


def test_the_edge_can_be_qts_own():
    assert fit_title("Check torque values on the coupling bolts", 15, len, lambda text, room: text[:3] + "~") == "Che~"


def test_a_page_cuts_by_characters():
    assert task_tile.page_title("Rigging plan for the impeller lift. Mike to confirm the crane size with the vendor") == \
        "Rigging plan for the impeller lift" + ELLIPSIS
    assert task_tile.page_title("Short title") == "Short title"


# ================= the days (decision 568) =================
def test_the_nearer_of_due_and_deadline_counts(sample_conn):
    m = Model(sample_conn)
    d = days(m.task(BOOK), TODAY)  # due tomorrow, deadline in 11 days
    assert (d.text, d.kind, d.deadline) == ("1", "soon", False)
    assert d.tip == "Due Fri 9 Oct, tomorrow · Deadline Mon 19 Oct, in 11 days"


def test_a_deadline_on_the_due_day_counts_as_the_deadline(sample_conn):
    d = days(Model(sample_conn).task(INSTALL), TODAY)
    assert (d.text, d.deadline, d.kind) == ("22", True, "")


def test_a_deadline_alone_counts(sample_conn):
    d = days(Model(sample_conn).task(VERIFY), TODAY)
    assert (d.text, d.deadline) == ("23", True)


def test_a_closed_task_shows_none_and_a_parked_one_stays_grey(sample_conn):
    m = Model(sample_conn)
    assert days(m.task(CLOSED), TODAY) is None
    d = days(m.task(PARKED), TODAY)
    assert (d.text, d.kind) == ("99+", "")


@pytest.mark.parametrize("day, text, kind", [
    (date(2026, 10, 5), f"{MINUS}3", "over"), (date(2026, 10, 8), "0", "soon"), (date(2026, 10, 10), "2", "soon"),
    (date(2026, 10, 11), "3", ""), (date(2027, 3, 1), "99+", ""),
])
def test_the_number_and_its_colour(day, text, kind):
    d = days_to(day, TODAY)
    assert (d.text, d.kind) == (text, kind)


def test_a_quiet_number_has_no_colour_however_late():
    assert days_to(date(2026, 10, 1), TODAY, quiet=True).kind == ""


# ================= the marks (decisions 566 and 567) =================
def wait_on(conn, task_id: str, follow_up: date | None) -> None:
    """A wait (release 5.139) on Mike Ortiz, started Monday."""
    waits.start(conn, Model(conn), task_id, at="2026-10-05 09:00:00", line="asked Mike for the crane size", on=["P002"],
                follow_up=follow_up, via="test")


def test_today_agendas_and_a_wait(sample_conn):
    agenda.add_item(sample_conn, subject=RIGGING, target=TODAY_TARGET, note="", added="2026-10-08 08:00:00", added_by="test")
    wait_on(sample_conn, RIGGING, date(2026, 10, 12))
    m = Model(sample_conn)
    marks = task_tile.marks(m, TODAY)
    assert RIGGING in marks.today and REACTOR not in marks.today
    assert marks.agendas[REACTOR] == ("Business team meeting",)
    assert marks.agendas[MONITORING] == (m.person_name("P003"),)
    w = marks.waits[RIGGING]
    assert w.words == f"waiting on {m.person_name('P002').split()[0]} · Mon" and not w.late and "Follow up Mon 12 Oct" in w.tip
    today, on_agenda, wait = task_tile.slots(RIGGING, marks)
    assert today.tip == "On Today" and on_agenda is None and wait.icon == "waiting" and wait.colour == "text2"
    assert task_tile.slots(REACTOR, marks)[1].tip == "On the agenda of Business team meeting"


def test_a_wait_whose_follow_up_day_has_come_is_orange(sample_conn):
    """Decision 567: the hourglass in caution's colour once the wait's follow-up day has come, its words first in its tooltip."""
    wait_on(sample_conn, RIGGING, date(2026, 10, 8))
    w = task_tile.marks(Model(sample_conn), TODAY).waits[RIGGING]
    assert w.late and w.words.startswith("no reply from") and w.tip.startswith("No reply from")
    assert task_tile.slots(RIGGING, task_tile.marks(Model(sample_conn), TODAY))[2].colour == "caution"


def test_a_slot_every_row_would_fill_is_left_out(sample_conn):
    marks = task_tile.marks(Model(sample_conn), TODAY)
    assert len(task_tile.slots(REACTOR, marks)) == 3
    assert len(task_tile.slots(REACTOR, marks, hide=("today",))) == 2
    assert [s is None for s in task_tile.slots(REACTOR, marks, hide=("today",))] == [False, True]


def test_closed_agenda_items_mark_nothing(sample_conn):
    m = Model(sample_conn)
    assert "T000008" not in task_tile.marks(m, TODAY).agendas  # its item was Discussed


def test_names_are_listed_in_words():
    assert task_tile.listed(["A"]) == "A"
    assert task_tile.listed(["A", "B"]) == "A and B"
    assert task_tile.listed(["A", "B", "C"]) == "A, B and C"


# ================= where a task sits (decision 570) =================
def test_depth_counts_the_generations_above_by_its_first_parent(sample_conn):
    m = Model(sample_conn)
    assert task_tile.depth(m, REACTOR) == 0 and task_tile.depth_tip(m, REACTOR) == ""
    assert task_tile.depth(m, RIGGING) == 2
    assert task_tile.depth_tip(m, RIGGING) == "2 levels down: Reactor impeller upgrade › Installation"


def test_two_parents_are_named_and_also_under_names_the_other(sample_conn):
    m = Model(sample_conn)
    assert task_tile.parents_tip(m, OVERTIME) == "Under Q4 cost reduction and Installation"
    assert task_tile.parents_tip(m, OVERTIME, under=INSTALL) == "Also under Q4 cost reduction"
    assert task_tile.parents_tip(m, RIGGING) == ""


def test_a_flat_tile_has_depth_and_a_nested_one_none(sample_conn):
    m = Model(sample_conn)
    assert task_tile.tile(m, RIGGING, TODAY, flat=True).depth == 2
    assert task_tile.tile(m, RIGGING, TODAY).depth == -1


# ================= a whole tile, its tooltip and its HTML =================
def test_the_tooltip_says_in_words_what_the_tile_shows(sample_conn):
    m = Model(sample_conn)
    tip = task_tile.tooltip(task_tile.tile(m, BOOK, TODAY), {"critical": "Critical"})
    assert tip.split("\n")[:4] == ["Book the alignment contractor", "Not started", "Priority: Critical", "Urgent"] or "Urgent" in tip
    assert "Due Fri 9 Oct, tomorrow" in tip


def test_a_page_tile_has_its_circle_link_title_flag_and_days(sample_conn):
    m = Model(sample_conn)
    html = task_tile.html(task_tile.tile(m, BOOK, TODAY), lambda href, text: f'<a href="{href}">{text}</a>')
    assert f'href="state:{BOOK}"' in html and f'href="task:{BOOK}"' in html
    assert 'src="tm:urgent"' in html and ">1</span>" in html
    assert 'class="tile"' in html
    assert "Safety" not in html  # no labels on a tile (decision 569)


def test_a_page_tile_escapes_its_title(sample_conn):
    sample_conn.execute("UPDATE tasks SET title = 'Pump <A> & B' WHERE id = ?", (BOOK,))
    from docrepo.detail import link

    html = task_tile.html(task_tile.tile(Model(sample_conn), BOOK, TODAY), lambda href, text: link(href, text))
    assert "<A>" not in html and "&lt;A&gt;" in html
