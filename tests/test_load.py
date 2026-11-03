"""Capacity's half of the Timeline page (release 5.40): its cells, its tints, the sentence and the team chart's numbers."""
from __future__ import annotations

from datetime import date, timedelta

from docrepo import load
from docrepo.model import Person

TODAY = date(2026, 10, 8)
THIS_WEEK = date(2026, 10, 5)
TOM = Person("P1", "Tom Becker", 40, "active", None)
MIKE = Person("P2", "Mike Ortiz", 32, "active", None)
TODD = Person("P3", "Todd", None, "active", None)
NAMES = {"P1": "Tom Becker", "P2": "Mike Ortiz", "P3": "Todd"}


def week(n: int) -> date:
    return THIS_WEEK + timedelta(days=7 * n)


def test_mondays_cover_a_range_from_any_day():
    assert load.mondays(date(2026, 10, 7), date(2026, 10, 20)) == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]


def test_a_week_is_a_cell_until_its_too_narrow_then_a_month():
    weeks = load.buckets(date(2026, 10, 5), date(2026, 11, 2), 40)
    assert [b.first for b in weeks] == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)]
    assert not weeks[0].month and weeks[0].end == date(2026, 10, 12)
    months = load.buckets(date(2026, 10, 5), date(2026, 12, 7), load.WEEK_MIN_PX - 1)
    assert [len(b.weeks) for b in months] == [4, 5]  # a week belongs to the month its Monday is in
    assert months[0].month and months[0].first == date(2026, 10, 5) and months[0].end == date(2026, 11, 2)
    assert months[1].holds(date(2026, 11, 30)) and not months[1].holds(date(2026, 12, 7))


def test_a_cells_steps():
    assert [load.tint(h, 40) for h in (0, 8, 15.9, 16, 31.9, 32, 40, 40.1, 49.9, 50, 90)] == [
        "", "t1", "t1", "t2", "t2", "t3", "t3", "t4", "t4", "t5", "t5"]
    assert load.tint(5, None) == "none" and load.tint(0, None) == ""


def test_one_number_at_a_time():
    assert load.cell_text(38.2, 40, "pct") == "96%"
    assert load.cell_text(38.2, 40, "hours") == "38"
    assert load.cell_text(38.2, None, "pct") == "38"  # no hours a week to count against
    assert load.cell_text(0, 40, "pct") == ""


def test_a_cells_tooltip_has_the_other_number():
    cells = {"P1": {week(0): {"T1": 30.0, "T2": 8.2}, week(1): {"T1": 10.0}}}
    b = load.Bucket(week(0), week(1), (week(0),))
    assert load.cell_tip(TOM, cells, b, TODAY) == "Tom Becker, week of 5 Oct: 38.2 h of 40 h, 96%"
    assert load.cell_tip(TODD, {"P3": {week(0): {"T1": 6.0}}}, b, TODAY) == "Todd, week of 5 Oct: 6 h (hours a week not set)"
    assert load.cell_tip(MIKE, cells, b, TODAY) == "Mike Ortiz, week of 5 Oct: nothing scheduled"
    month = load.Bucket(week(0), week(2), (week(0), week(1)), True)
    assert load.cell_tip(TOM, cells, month, TODAY) == "Tom Becker, October 2026: 48.2 h. Worst week 5 Oct: 38.2 h, 96%"


def test_a_month_shows_its_worst_week():
    cells = {"P1": {week(0): {"T1": 8.0}, week(1): {"T1": 60.0}, week(2): {"T1": 4.0}}}
    b = load.Bucket(week(0), week(3), (week(0), week(1), week(2)), True)
    assert load.worst_week(cells, "P1", b) == (60.0, week(1))
    assert load.tint(load.worst_week(cells, "P1", b)[0], 40) == "t5"  # a peak isn't averaged away


def test_hours_over_count_even_when_the_teams_total_is_under_its_capacity():
    """Decision 231: spare time elsewhere can't hide one person's overload."""
    cells = {"P1": {week(0): {"T1": 2.0}}, "P2": {week(0): {"T2": 40.0}}, "P3": {week(0): {"T3": 90.0}}}
    team = load.team_week(cells, [TOM, MIKE], week(0))
    assert (team.total, team.over) == (42.0, 8.0) and team.total < load.capacity_of([TOM, MIKE])
    assert load.team_week(cells, [TODD], week(0)).over == 0  # no hours a week set: nothing to be over


def test_the_team_chart_shows_a_months_worst_week():
    cells = {"P2": {week(0): {"T1": 30.0}, week(1): {"T1": 40.0}}, "P1": {week(0): {"T2": 39.0}}}
    b = load.Bucket(week(0), week(2), (week(0), week(1)), True)
    team, at = load.team_bucket(cells, [TOM, MIKE], b)
    assert at == week(1) and (team.total, team.over) == (40.0, 8.0)


def test_the_case_counts_from_this_week():
    """Decision 289: a past week can't be changed."""
    cells = {"P2": {week(-1): {"T1": 99.0}, week(1): {"T1": 40.0}}}
    c = load.case(cells, [TOM, MIKE], [week(-1), week(0), week(1)], TODAY)
    assert c.over_weeks == [week(1)] and c.most == 8.0 and c.by_person == {"P2": 1}


def test_the_sentence():
    def say(cells, weeks):
        return load.sentence(load.case(cells, [TOM, MIKE, TODD], weeks, TODAY), NAMES.get, TODAY)

    # Nobody over, and nothing at all.
    assert say({}, [week(0)]) == ("Nobody is over in this range.", "")
    assert say({"P1": {week(1): {"T1": 20.0}}}, [week(0), week(1)]) == ("Nobody is over in this range.", "Busiest: Tom Becker, 50% in the week of 12 Oct.")
    # One week; weeks in a row; and weeks apart, which name the worst.
    assert say({"P2": {week(1): {"T1": 40.0}}}, [week(1)]) == ("Over in the week of 12 Oct, by 8 h.", "Mike Ortiz 1 week.")
    together = {"P2": {week(0): {"T1": 40.0}, week(1): {"T1": 33.0}}, "P1": {week(1): {"T1": 41.0}}}
    assert say(together, [week(0), week(1)]) == ("Over in 2 weeks, 5 Oct to 18 Oct, by up to 8 h.", "Mike Ortiz 2 weeks, Tom Becker 1.")
    apart = {"P2": {week(0): {"T1": 34.0}, week(30): {"T1": 94.0}}}
    assert say(apart, [week(0), week(30)]) == ("Over in 2 weeks, the worst the week of 3 May 2027, by 62 h.", "Mike Ortiz 2 weeks.")


def test_the_sentence_names_three_people_at_most():
    people = [Person(f"P{i}", f"Person {i}", 10, "active", None) for i in range(5)]
    cells = {p.id: {week(0): {"T1": 20.0}} for p in people}
    lead, who = load.sentence(load.case(cells, people, [week(0)], TODAY), {p.id: p.name for p in people}.get, TODAY)
    assert lead == "Over in the week of 5 Oct, by 50 h."
    assert who == "Person 0 1 week, Person 1 1, Person 2 1 and 2 more."


def test_whats_behind_a_week_biggest_first():
    cells = {"P1": {week(0): {"T1": 6.0, "T2": 30.0}, week(1): {"T1": 1.0}}, "P2": {week(0): {"T3": 10.0}}}
    assert load.cell_tasks(cells, ["P1"], [week(0)]) == [("T2", 30.0), ("T1", 6.0)]
    assert load.cell_tasks(cells, ["P1"], [week(0), week(1)])[1] == ("T1", 7.0)
    assert load.cell_tasks(cells, ["P1", "P2"], [week(0)]) == [("T2", 30.0), ("T3", 10.0), ("T1", 6.0)]


def test_the_weeks_a_bar_adds_to():
    cells = {"P1": {week(0): {"T1": 6.0, "T2": 30.0}, week(1): {"T2": 1.0}}, "P2": {week(0): {"T3": 10.0}}}
    assert load.adds_to(cells, {"T1"}) == {("P1", week(0))}
    assert load.adds_to(cells, {"T2", "T3"}) == {("P1", week(0)), ("P1", week(1)), ("P2", week(0))}
    assert load.adds_to(cells, {"T9"}) == set()
