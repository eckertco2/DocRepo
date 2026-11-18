"""Topic headings and the heading list's rows (release 5.156, the design workspace's notes topics plan, decisions 704 to
708), without Qt: a heading's reach and path, matching, the rows of a task and of the rest of its project, their order
and their words. Over the made-up cooling tower project (``notes_example``), with pages written into the model.

Since release 5.157 (decisions 709 to 717): All notes By meeting and By topic, their bands, occasions, topics and runs,
their outline, and their HTML with files rolled up and By day's lines once, over the same project with topic headings
written to docs.db (``topics_example``)."""
from __future__ import annotations

import re
from datetime import date

import pytest

from docrepo import notes_page, topics
from docrepo.captures import read_content
from docrepo.detail import Pages, PageState, anchored
from docrepo.model import Model
from notes_example import build
from topics_example import FILES, give_topics

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


# ================= All notes grouped (release 5.157, decisions 709 to 717) =================
@pytest.fixture
def grouped(sample_root):
    """The project with topic headings on its pages, in docs.db, and its model."""
    conn, root, fs = sample_root
    example = build(conn, root, fs)
    give_topics(conn, example)
    return Model(conn), example, root


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&#x27;", "'").split())


def titles(m, ids) -> list[str]:
    return [m.task(x).title for x in ids]


# ---- bands and occasions (decision 710) ----
def test_a_band_per_task_in_tree_order_with_meetings_in_their_home_task_s(grouped):
    m, ex, _root = grouped
    scope, bands = topics.band_tasks(m, ex.project)
    assert ex.kickoff in scope and ex.weekly in scope
    assert titles(m, bands) == ["Cooling tower 2 rebuild", "Structural survey of the fan deck", "Fill media order", "Crane for the fan lift",
                                "Rig the east cell first", "Fan blade inspection"]
    assert topics.home_band(m, ex.kickoff, set(bands), set(scope), ex.project) == ex.project  # its home task (610)
    assert topics.above(m, ex.project, ex.rig) == [ex.project, ex.crane] and topics.above(m, ex.project, ex.project) == []
    assert topics.above(m, ex.crane, ex.rig) == [ex.crane]
    assert [b.task for b in topics.occasions(m, ex.project).bands] == bands


def test_by_meeting_lists_each_band_s_occasions_oldest_first(grouped):
    m, ex, _root = grouped
    g = topics.occasions(m, ex.project)
    seen = {b.task: [(o.label, o.day, o.meeting) for o, _blocks in b.occasions] for b in g.bands}
    kickoff, weekly = ("Cooling tower kickoff", date(2026, 11, 3), ex.kickoff), ("Cooling tower weekly 10 Nov", date(2026, 11, 10), ex.weekly)
    # The meetings' own pages are occasions under their home task, after the project's own notes of Mon 2 Nov.
    assert seen[ex.project] == [("Notes", date(2026, 11, 2), ""), kickoff, weekly]
    # A follow-up's block is its meeting's (from_notes), as is an item's; lines typed on the page are the day's notes.
    assert seen[ex.survey] == [kickoff, weekly, ("Notes", date(2026, 11, 11), "")]
    # Lines moved from the weekly's page are the weekly's, under the task they were moved to.
    assert seen[ex.fill] == [kickoff, weekly, ("Notes", date(2026, 11, 12), "")]
    assert seen[ex.rig] == [weekly]


def test_an_email_s_block_is_the_day_s_email(grouped):
    m, ex, _root = grouped
    survey = next(blocks for task, blocks in topics.band_blocks(m, ex.project) if task == ex.survey)
    c = m.captures[survey[0].capture]
    c.item, c.from_notes, c.source = None, None, "outlook_email"
    assert topics.occasion_of(m, survey[0]) == topics.Occasion("Email", date(2026, 11, 3))
    band = next(b for b in topics.by_topic(m, ex.project).bands if b.task == ex.survey)
    assert [(r.occasion.label, r.lines) for r in band.loose][:1] == [("Email", [])]  # one line; its words aren't read


# ---- topics and runs (decisions 708 and 711) ----
def test_by_topic_lists_each_band_s_topics_in_the_order_first_used(grouped):
    m, ex, _root = grouped
    band = {b.task: b for b in topics.by_topic(m, ex.project).bands}
    project = [(t.path, level, band[ex.project].runs_in(t)) for t, level in band[ex.project].ordered()]
    assert project == [(("Schedule",), 1, 2), (("Schedule", "Outage window"), 2, 1), (("Schedule", "Tie-in"), 2, 1),
                       (("Safety",), 1, 2), (("Safety", "Permits"), 2, 1), (("Budget",), 1, 1)]
    fill = band[ex.fill]
    # "Vendors" (drift, typed before the heading list) is a topic of its own; "Vendor" and "vendor " are one, spelled as
    # most recently typed (705).
    assert [(t.path, level) for t, level in fill.ordered()] == [
        (("Vendors",), 1), (("vendor",), 1), (("vendor", "Quotes"), 2), (("vendor", "Lead time"), 2), (("Delivery",), 1)]
    quotes = next(t for t in fill.topics if t.key == ("vendor", "quotes"))
    # Its runs oldest first, each with its occasion: the weekly's moved lines, then a day's notes.
    assert [(r.occasion.label, [x.text for x in r.lines]) for r in quotes.runs] == [
        ("Cooling tower weekly 10 Nov", ["Vendor B 18 % under vendor A."]), ("Notes", ["Vendor B holds its price to 30 Nov."])]
    assert fill.runs_in(next(t for t in fill.topics if t.key == ("vendor",))) == 4


def test_a_topic_heading_s_reach_ends_at_its_block(grouped):
    """Decision 708: the kickoff's "# Budget" doesn't cover the weekly's lines; the lines before a block's first topic
    heading are under none, by occasion."""
    m, ex, _root = grouped
    bands = topics.by_topic(m, ex.project).bands
    band = {b.task: b for b in bands}
    budget = next(t for t in band[ex.project].topics if t.words == "Budget")
    assert [x.text for r in budget.runs for x in r.lines] == ["Approved at 410 k with 10 % contingency."]
    loose = [(r.occasion.label, r.lines[0].text) for r in band[ex.project].loose]
    assert loose[:2] == [("Notes", "Rebuild of cooling tower 2: fill, fan deck and drift eliminators, in the spring outage."),
                         ("Cooling tower kickoff", "Attendees: Priya, Tom, Mike.")]
    assert bands[-1].task == ex.blades and not bands[-1].topics  # a band with only lines under no topic heading still shows


def test_the_outline_follows_the_grouping(grouped):
    m, ex, _root = grouped
    out = topics.outline(m, topics.by_topic(m, ex.project), TODAY)
    assert out[:4] == [topics.Entry(("band", ex.project), 1, "Cooling tower 2 rebuild"),
                       topics.Entry(("anchor", f"topic:{ex.project}:0"), 2, "Schedule", 2),
                       topics.Entry(("anchor", f"topic:{ex.project}:1"), 3, "Outage window", 1),
                       topics.Entry(("anchor", f"topic:{ex.project}:2"), 3, "Tie-in", 1)]
    assert topics.Entry(("anchor", f"loose:{ex.project}"), 2, topics.LOOSE, 3, True) in out
    folded = topics.outline(m, topics.by_topic(m, ex.project), TODAY, {ex.project})
    assert folded[0].target == ("band", ex.project) and folded[1].target == ("band", ex.survey)  # a folded band's rows go
    meetings = topics.outline(m, topics.occasions(m, ex.project), TODAY)
    assert [(e.level, e.words, e.quiet) for e in meetings[:4]] == [
        (1, "Cooling tower 2 rebuild", False), (2, "Notes · Mon 2 Nov", True), (2, "Cooling tower kickoff", False),
        (2, "Cooling tower weekly 10 Nov", False)]


# ---- the HTML (decisions 710, 711, 715 and 716) ----
def pages_of(m, root) -> Pages:
    return Pages(m, TODAY, lambda cid: read_content(root, m.captures[cid]))


def test_by_meeting_draws_bands_and_occasions(grouped):
    m, ex, root = grouped
    html, g = pages_of(m, root).grouped_notes(ex.project, PageState(notes_group="meeting"))
    assert g.group == "meeting"
    text = plain(html)
    assert "Cooling tower 2 rebuild this task" in text and "Cooling tower 2 rebuild › Fill media order" in text
    assert "Cooling tower kickoff · Tue 3 Nov Attendees: Priya, Tom, Mike." in text
    # A task line stays one tile and a pointer line one line (710): their words are in their own bands.
    assert "follow-up, on its page" not in text and "Fill media order · 5 lines moved there" in text
    assert text.count("Vendor B 18 % under vendor A.") == 1
    assert f'name="{topics.band_anchor(ex.fill)}"' in html and f'name="occ:{ex.project}:1"' in html
    assert f'href="notesgo:{ex.fill}:"' in html and 'src="lk:edit"' in html and "Edit there" not in text  # the band's pencil (716)
    assert f'name="block:{ex.kickoff}:{ex.kickoff_notes}"' in html  # a double-click finds the meeting's page
    assert f'href="allnotes:fold:{ex.fill}"' in html


def test_by_topic_draws_topics_runs_and_their_occasions_once(grouped):
    m, ex, root = grouped
    html, _g = pages_of(m, root).grouped_notes(ex.project, PageState(notes_group="topic"))
    text = plain(html)
    assert ("Schedule · 2 runs Outage window · 1 run Cooling tower kickoff · Tue 3 Nov Tower 2 offline 9 to 20 Mar, from 6 am on the 9th. "
            "Tie-in · 1 run Cooling tower weekly 10 Nov · Tue 10 Nov Tie in the new basin heater") in text
    assert "vendor · 4 runs Quotes · 2 runs Cooling tower weekly 10 Nov · Tue 10 Nov Vendor B 18 % under vendor A. Notes · Thu 12 Nov" in text
    assert "Not under a topic heading · 3 runs Notes · Mon 2 Nov Rebuild of cooling tower 2" in text


def test_a_folded_band_is_its_line(grouped):
    m, ex, root = grouped
    html, _g = pages_of(m, root).grouped_notes(ex.project, PageState(notes_group="topic", notes_folded={ex.survey}))
    assert "Findings" not in plain(html) and "Structural survey of the fan deck" in plain(html) and 'src="chev:right"' in html


def test_a_run_of_files_is_one_line(grouped):
    """Decision 715: the survey's five files as one line, four names and "+1 more", each name opening its file with its
    description in its tooltip; the description lines under the pictures and attachments aren't lines of their own."""
    m, ex, root = grouped
    pages = pages_of(m, root)
    html, _g = pages.grouped_notes(ex.project, PageState(notes_group="topic"))
    text = plain(html)
    assert "Deck plank 4.png · Beam 3 bearing.png · Survey report draft.docx · Deck plan rev C.pdf · +1 more" in text
    assert f'href="doc:{FILES[0][0]}" title="{FILES[0][2]}"' in html and 'title="Fan deck photos.zip">+1 more' in html
    assert "Plank 4 split along the grain" not in text and 'src="lk:attach"' in html
    by_day = plain(pages.all_notes(ex.project, PageState())[0])
    assert "+1 more" in by_day and "Section loss at the bearing plate" not in by_day  # in every grouping
    lines = notes_page.lines_of(m.pages[ex.project])
    assert pages.file_run(lines, len(lines) - 1)[0] == [(FILES[5][0], FILES[5][1], FILES[5][2])]  # a file line's words after its name


def test_by_day_names_a_block_once_and_a_block_of_files_is_its_files_line(grouped):
    """Decision 716: a block's line only when its page or what it is changes from the block above, and on each new day;
    715: a block that's only files is one line, its time at its right."""
    m, ex, root = grouped
    m.pages[ex.survey] += "\n" + "\n".join([
        "# Thu 12 Nov 2026", notes_page.caption_line("Thu 12 Nov 2026 · 2:00 pm · Note", "C000001"), "Deck walk-down done.",
        notes_page.caption_line("Thu 12 Nov 2026 · 2:30 pm · Note", "C000002"), "Planks marked.",
        "# Fri 13 Nov 2026", notes_page.caption_line("Fri 13 Nov 2026 · 3:00 pm · Note", "C000004"),
        notes_page.file_line(f"File: {FILES[3][1]}", FILES[3][0])])
    html, _an = pages_of(m, root).all_notes(ex.survey, PageState())
    text = plain(html)
    assert "Thu 12 Nov 2026 This task Note 2:00 pm Deck walk-down done. Planks marked." in text  # the second Note isn't named again
    cell = re.search(r'Deck plan rev C\.pdf</a></td><td valign="top" align="right" class="src">(.*?)</td>', html)
    assert cell and "This task" in cell.group(1) and "3:00 pm" in cell.group(1)  # a new day names its first block again
    assert f'name="block:{ex.survey}:C000002"' in html  # the unnamed block's first line holds its anchor, for a double-click


def test_an_anchor_goes_inside_the_first_paragraph():
    assert anchored('<p class="nl">one</p><p>two</p>', "block:T1:C1") == '<p class="nl"><a name="block:T1:C1"></a>one</p><p>two</p>'
    assert anchored("<p>x</p>", "") == "<p>x</p>"
    assert anchored("", "b").startswith('<p class="nl"')
