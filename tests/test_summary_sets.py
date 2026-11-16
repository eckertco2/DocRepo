"""Release 5.149, saved summary sets (the design workspace's ``docs/mods/summary-sets-plan.md``, decisions 649 to 651): a
pinned combination with a name of its own, kept in Settings beside its key; reading it back, a part gone, renaming, unpinning,
the box's list and matching, and the palette's lines. Every name here is made up. No Qt."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import summary as qs
from docrepo import tagged
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.safe_fs import SafeFS

TODAY = date(2026, 10, 8)
TOM, MIKE, MEETING, RIGGING = "P003", "P004", "T000010", "T000012"
#: The morning meeting, as the owner would pick it: its tag, the two who are there every week, and its agenda.
MORNING = f"tag:P204B + person:{TOM} + person:{MIKE} + agenda:{MEETING}"


def _tag(conn) -> None:
    tagged.add_label(conn, "P-204B", datetime(2026, 10, 1, 9, 0), "Feed pump B")
    conn.execute("UPDATE tasks SET description = 'The seal on P-204B leaks' WHERE id = ?", (RIGGING,))


def builder(conn) -> qs.Builder:
    return qs.Builder(Model(conn), TODAY, "P001", conn)


# ---- keeping a name (decision 649) ----
def test_save_as_pins_the_combination_first_under_its_name():
    out = qs.save_as(["label:Safety"], {}, MORNING, "  Morning   meeting ")
    assert out.pins == [MORNING, "label:Safety"] and out.names == {MORNING: "Morning meeting"} and out.replaced == ""


def test_a_combination_already_pinned_becomes_the_named_pin_where_it_is():
    other_order = f"person:{MIKE} + agenda:{MEETING} + tag:P204B + person:{TOM}"
    out = qs.save_as(["label:Safety", other_order], {}, MORNING, "Morning meeting")
    assert out.pins == ["label:Safety", other_order] and out.names == {other_order: "Morning meeting"}


def test_saving_under_a_name_in_use_replaces_that_set_in_its_place():
    old = f"tag:P204B + person:{TOM}"
    out = qs.save_as(["label:Safety", old], {old: "Morning meeting"}, MORNING, "morning meeting")
    assert out.pins == ["label:Safety", MORNING] and out.names == {MORNING: "morning meeting"} and out.replaced == old


def test_a_name_is_needed_and_kept_short():
    with pytest.raises(ValueError):
        qs.save_as([], {}, MORNING, "   ")
    assert len(qs.save_as([], {}, MORNING, "x" * 100).names[MORNING]) == qs.NAME_MAX


# ---- reading it (decision 650) ----
def test_a_saved_set_shows_its_name_and_counts_its_parts_in_the_order_picked(sample_conn):
    _tag(sample_conn)
    m = Model(sample_conn)
    s = qs.subject_of(m, MORNING, "P001", {MORNING: "Morning meeting"})
    assert s.saved and s.name == "Morning meeting" and s.key == MORNING and s.kind == qs.MANY
    assert s.parts_words == "P-204B + Tom Becker + Mike Ortiz + Business team meeting"
    out = builder(sample_conn).build(s)
    assert out.kind_line == "Saved set · 1 tag · 2 people · 1 agenda" and out.face == "many"
    assert [x.key for x in out.sections][:3] == [f"agenda:{TOM}", f"agenda:{MIKE}", f"agenda:{MEETING}"]
    assert "### Morning meeting: needs a word" in out.markdown or "Morning meeting: nothing open needs a word." in out.markdown  # Copy uses its name
    assert qs.subject_of(m, MORNING, "P001") == qs.combine(s.each())  # without the names, as before


def test_the_same_subjects_in_another_order_are_the_saved_set(sample_conn):
    _tag(sample_conn)
    m = Model(sample_conn)
    picked = qs.combine(qs.subject_of(m, k, "P001") for k in (f"agenda:{MEETING}", f"person:{MIKE}", f"person:{TOM}", "tag:P204B"))
    s = qs.named(picked, {MORNING: "Morning meeting"})
    assert s.saved and s.key == MORNING and s.name == "Morning meeting"
    assert qs.named(qs.subject_of(m, f"person:{TOM}", "P001"), {MORNING: "Morning meeting"}).saved is False


def test_a_part_gone_is_left_out_and_the_set_keeps_its_name_and_key(sample_conn):
    m = Model(sample_conn)
    key = f"person:{TOM} + person:{MIKE} + label:Gone"
    s = qs.subject_of(m, key, "P001", {key: "Morning meeting"})
    assert s.saved and s.key == key and [p.ref for p in s.each()] == [TOM, MIKE]
    assert builder(sample_conn).build(s).kind_line == "Saved set · 2 people · 1 gone"


def test_with_one_part_left_it_keeps_its_name_and_shows_what_is_left(sample_conn):
    m = Model(sample_conn)
    key = f"person:{TOM} + label:Gone"
    s = qs.subject_of(m, key, "P001", {key: "Morning meeting"})
    assert s.saved and s.kind == qs.PERSON and s.ref == TOM and s.name == "Morning meeting" and s.key == key
    assert s.each() == (qs.Subject(qs.PERSON, TOM, "Tom Becker"),)  # its chip is Tom's
    out = builder(sample_conn).build(s)
    assert out.kind_line == "Saved set · 1 person · 1 gone" and out.face == "many" and out.section("agenda") is not None
    assert out.markdown.startswith("## Morning meeting: to raise")
    assert qs.subject_of(m, "label:Gone + label:Also gone", "P001", {"label:Gone + label:Also gone": "Nothing left"}) is None


def test_rename_and_its_refusals():
    names = {MORNING: "Morning meeting", "label:A + label:B": "Weekly"}
    assert qs.rename(names, MORNING, " Shift handover ")[MORNING] == "Shift handover"
    with pytest.raises(ValueError):
        qs.rename(names, MORNING, "weekly")  # another set has it
    with pytest.raises(ValueError):
        qs.rename(names, MORNING, "  ")


def test_unpin_takes_its_name_with_it_in_any_order():
    other_order = f"person:{MIKE} + agenda:{MEETING} + tag:P204B + person:{TOM}"
    out = qs.unpin(["label:Safety", MORNING], {MORNING: "Morning meeting"}, other_order)
    assert out.pins == ["label:Safety"] and out.names == {}
    assert qs.unpin(["label:Safety"], {}, "label:Gone").pins == ["label:Safety"]


# ---- the box (decision 649) ----
def test_the_box_lists_a_saved_set_by_its_name_and_finds_it_by_its_words(sample_conn):
    _tag(sample_conn)
    m = Model(sample_conn)
    names = {MORNING: "Morning meeting"}
    pinned, recent = qs.start_list(m, "P001", [MORNING, "label:Safety"], [MORNING, f"person:{TOM}"], names)
    assert [x.name for x in pinned] == ["Morning meeting", "Safety"] and [x.name for x in recent] == ["Tom Becker"]
    sets = qs.sets_of(m, "P001", [MORNING, "label:Safety"], names)
    assert [x.name for x in qs.matching_sets(sets, "morn")] == ["Morning meeting"]
    assert qs.matching_sets(sets, "meet mo") == sets and qs.matching_sets(sets, "@morn") == [] and qs.matching_sets(sets, "tom") == []
    assert qs.set_named(m, names, " MORNING  meeting", "P001").key == MORNING and qs.set_named(m, names, "Evening") is None


def test_a_saved_sets_count_line_is_its_parts(sample_conn):
    _tag(sample_conn)
    b = builder(sample_conn)
    s = qs.subject_of(b.m, MORNING, "P001", {MORNING: "Morning meeting"})
    assert b.count_line(s) == b.count_line(qs.combine(s.each()))


# ---- Settings (decision 650) ----
def test_settings_keep_names_beside_the_pins_and_leave_them_out_while_empty(tmp_path):
    fs = SafeFS([tmp_path])
    Settings(me="P001", summary_pins=[MORNING], summary_names={MORNING: "Morning meeting"}).save(fs, tmp_path)
    back = Settings.load(tmp_path)
    assert back.summary_names == {MORNING: "Morning meeting"} and back.summary_pins == [MORNING]
    Settings(me="P001", summary_pins=[MORNING]).save(fs, tmp_path)
    assert "summary_names" not in (tmp_path / "Config" / "settings.json").read_text(encoding="utf-8")


def test_settings_leave_out_names_that_are_not_pinned_combinations(tmp_path):
    (tmp_path / "Config").mkdir()
    (tmp_path / "Config" / "settings.json").write_text(
        '{"summary_pins": ["label:A + label:B", "label:C"], "summary_names": {"label:A + label:B": " Weekly  one ", "label:C": "One", '
        '"label:D + label:E": "Not pinned", "label:A + label:F": ""}}', encoding="utf-8")
    assert Settings.load(tmp_path).summary_names == {"label:A + label:B": "Weekly one"}
    (tmp_path / "Config" / "settings.json").write_text('{"summary_names": ["Morning meeting"]}', encoding="utf-8")
    assert Settings.load(tmp_path).summary_names == {}


# ---- the palette (decision 651) ----
def test_the_palettes_lines_are_the_saved_sets_in_the_pins_order():
    names = {"label:A + label:B": "Weekly", MORNING: "Morning meeting"}
    assert qs.saved_sets(names, [MORNING, "label:C", "label:A + label:B"]) == [(MORNING, "Morning meeting"), ("label:A + label:B", "Weekly")]

