"""Topic headings and the heading list's rows (release 5.156, the design workspace's notes topics plan, decisions 704 to
708), without Qt: a heading's reach and path, matching, the rows of a task and of the rest of its project, their order
and their words. Over the made-up cooling tower project (``notes_example``), with pages written into the model."""
from __future__ import annotations

from datetime import date

import pytest

from docrepo import notes_page, topics
from docrepo.model import Model
from notes_example import build

TODAY = date(2026, 11, 17)

FILL_PAGE = "\n".join([
    "# Tue 3 Nov 2026",
    notes_page.caption_line("Tue 3 Nov 2026 · 9:00 am · New task from the notes of Cooling tower kickoff", "C000901"),
    "# Vendors",
    "Ask Tyler for quotes from two vendors.",
    "# Thu 5 Nov 2026",
    "# Specification",
    "## Fill type",
    "Cross-fluted film fill.",
    "# Tue 10 Nov 2026",
    notes_page.lead_line("Moved from the notes of Cooling tower weekly 10 Nov · Tue 10 Nov", "T000901", "M20261110090000"),
    "# Vendor",
    "## Quotes",
    "Vendor B 18 % under vendor A.",
    "## Lead time",
    "12 weeks from the order.",
    "# Thu 12 Nov 2026",
    "# vendor ",
    "## Lead time",
    "10 weeks for a 5 % premium.",
])


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


@pytest.fixture
def m(sample_root, ex):
    model = Model(sample_root[0])
    model.pages[ex.fill] = FILL_PAGE
    model.pages[ex.project] = "# Mon 2 Nov 2026\n# Schedule\n## Outage window\nTower 2 offline 9 to 20 Mar.\n# Safety\nA standby person."
    model.pages[ex.kickoff] = "# Tue 3 Nov 2026\n# Schedule\n## Outage window\nFrom 6 am.\n# Budget\n410 k."
    model.pages[ex.survey] = "# Wed 11 Nov 2026\n# Findings\nSix planks.\n## Access\nScaffold."
    return model


# ---- a heading's reach and path (decision 708) ----
def test_sections_give_each_topic_heading_its_path_and_day():
    hs = topics.sections(FILL_PAGE, "T1")
    assert [(h.level, h.words, h.path, h.day) for h in hs] == [
        (1, "Vendors", ("Vendors",), date(2026, 11, 3)),
        (1, "Specification", ("Specification",), date(2026, 11, 5)),
        (2, "Fill type", ("Specification", "Fill type"), date(2026, 11, 5)),
        (1, "Vendor", ("Vendor",), date(2026, 11, 10)),
        (2, "Quotes", ("Vendor", "Quotes"), date(2026, 11, 10)),
        (2, "Lead time", ("Vendor", "Lead time"), date(2026, 11, 10)),
        (1, "vendor", ("vendor",), date(2026, 11, 12)),
        (2, "Lead time", ("vendor", "Lead time"), date(2026, 11, 12)),
    ]
    assert all(h.page == "T1" for h in hs)
    assert hs[2].under == "Specification" and hs[0].under == ""
    # n counts every heading line, day headings too: the editor finds the line being typed by it.
    assert [h.n for h in hs] == [1, 3, 4, 6, 7, 8, 10, 11]


def test_a_caption_or_lead_line_ends_a_heading_s_reach():
    page = "\n".join(["# Vendor", "Quotes in.", notes_page.caption_line("Wed 4 Nov 2026 · 2:00 pm · Note", "C000902"),
                      "## Lead time", "12 weeks."])
    hs = topics.sections(page)
    assert [(h.words, h.path, h.day) for h in hs] == [("Vendor", ("Vendor",), None), ("Lead time", ("Lead time",), date(2026, 11, 4))]
    # A level missing from a path is left out of it.
    assert topics.sections("### Deep one")[0].path == ("Deep one",)


def test_day_headings_and_hash_task_lines_are_never_topics():
    page = "# Thu 8 Oct 2026\n#[Installation](T000008)\n\\# not a heading\n# **Budget**\n#"
    assert [h.words for h in topics.sections(page)] == ["Budget"]  # its marks dropped


def test_in_force_is_the_nearest_lower_level_above():
    hs = topics.sections("# Vendor\n## Quotes\n### Vendor B")
    assert topics.in_force(hs, 2) == "Vendor" and topics.in_force(hs, 3) == "Quotes" and topics.in_force(hs, 1) == ""


# ---- matching (decision 706) ----
@pytest.mark.parametrize("typed, ok", [("ven", True), ("VEN", True), ("time lead", True), ("ead", False), ("lead x", False), ("", True)])
def test_words_match_from_the_start_of_a_word_in_any_order(typed, ok):
    assert topics.matches("Lead time (vendor B)", typed) is ok


# ---- the rows (decisions 705 and 707) ----
def test_a_subtask_lists_its_own_headings_then_its_project_s(m, ex):
    got = topics.options(m, ex.fill, 1)
    assert [(r.words, r.times, r.last) for r in got.here] == [
        ("vendor", 2, date(2026, 11, 12)), ("Specification", 1, date(2026, 11, 5)), ("Vendors", 1, date(2026, 11, 3))]
    # Vendor and vendor are one row, spelled as most recently typed; Vendors is another (drift isn't guessed at).
    assert got.elsewhere == "Cooling tower 2 rebuild"
    assert [r.words for r in got.others] == ["Findings", "Budget", "Schedule", "Safety"]  # last used, then by words
    assert all(r.here for r in got.here) and not any(r.here for r in got.others)
    assert [r.times for r in got.others if r.words == "Schedule"] == [2]  # the project's page and the kickoff's


def test_what_s_typed_narrows_the_rows_and_the_starts_come_first(m, ex):
    got = topics.options(m, ex.fill, 1, "s")
    assert [r.words for r in got.here] == ["Specification"]
    assert [r.words for r in got.others] == ["Schedule", "Safety"]
    got = topics.options(m, ex.fill, 1, "ven")
    assert [r.words for r in got.here] == ["vendor", "Vendors"] and got.others == [] and got.elsewhere == ""


def test_a_level_2_list_puts_the_heading_in_force_first(m, ex):
    got = topics.options(m, ex.fill, 2, "", under="Vendor")
    assert [(r.words, r.under) for r in got.here] == [("Lead time", "vendor"), ("Quotes", "Vendor"), ("Fill type", "Specification")]
    assert [(r.words, r.under) for r in got.others] == [("Access", "Findings"), ("Outage window", "Schedule")]
    # Without one, the most recently used first.
    assert [r.words for r in topics.options(m, ex.fill, 2).here] == ["Lead time", "Quotes", "Fill type"]


def test_the_same_words_under_another_heading_are_another_row(m, ex):
    m.pages[ex.crane] = "# Wed 11 Nov 2026\n# Rigging\n## Quotes\nTwo crane quotes."
    got = topics.options(m, ex.fill, 2, "quo")
    assert [(r.words, r.under) for r in got.here] == [("Quotes", "Vendor")]
    assert [(r.words, r.under) for r in got.others] == [("Quotes", "Rigging")]


def test_a_top_level_task_has_one_section(m, ex):
    got = topics.options(m, ex.project, 1)
    assert got.others == [] and got.elsewhere == ""
    assert {r.words for r in got.here} >= {"Schedule", "Safety", "Budget", "Findings", "vendor", "Specification"}


def test_the_box_s_own_headings_count_and_its_page_is_read_from_them(m, ex):
    own = topics.sections("# Thu 19 Nov 2026\n# Delivery\nOrder goes out Fri 20 Nov.")
    got = topics.options(m, ex.fill, 1, "", own=own, own_page=ex.fill)
    assert [r.words for r in got.here] == ["Delivery"]  # docs.db's copy of the page isn't read: the editor's is
    got = topics.options(m, ex.fill, 1, "", own=own)
    assert [r.words for r in got.here][0] == "Delivery" and len(got.here) == 4


def test_no_task_no_rows(m, ex):
    assert topics.options(m, None, 1).rows() == [] and topics.options(m, "T999999", 1).rows() == []
    assert topics.options(m, ex.fill, 0).rows() == [] and topics.options(m, ex.fill, 4).rows() == []


def test_a_discarded_task_s_headings_are_left_out(m, ex, sample_root):
    m.tasks[ex.survey].discarded = True
    assert "Findings" not in [r.words for r in topics.options(m, ex.fill, 1).others]


def test_a_row_s_grey_words():
    r = topics.Row("Lead time", 2, "Vendor", 3, date(2026, 11, 10), True)
    assert topics.sub_text(r, TODAY) == "under Vendor · 3 times · last Tue 10 Nov"
    assert topics.sub_text(topics.Row("Budget", 1, "", 1, date(2025, 12, 1), False), TODAY) == "once · Mon 1 Dec 2025"
    assert topics.sub_text(topics.Row("Budget", 1, "", 2, None, True), TODAY) == "twice"
