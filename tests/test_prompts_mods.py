"""Summary types, Copy prompt and the mods log."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from conftest import example_block

from docrepo import mods, prompts
from docrepo.model import Model


def test_default_summary_types_are_written_once(data_root, fs):
    assert len(prompts.write_defaults(fs, data_root)) == 4
    path = data_root / "Config" / "prompts" / "email-summary.md"
    assert path.read_text(encoding="utf-8") == example_block("Config/prompts/email-summary.md")
    path.write_text(path.read_text(encoding="utf-8").replace("Summarize", "Briefly summarize"), encoding="utf-8")
    assert prompts.write_defaults(fs, data_root) == []
    types = prompts.load_summary_types(data_root)
    assert [t.name for t in types] == ["Ancestor context", "Email extraction and summary", "General summary",
                                       "Report high-level summary and topic overview"]
    assert types[1].body.startswith("Briefly summarize") and types[0].fields == ("summary_log", "status_log", "events", "file_list")


def test_a_broken_summary_type_is_skipped(data_root, fs):
    fs.write_text(data_root / "Config" / "prompts" / "bad.md", "---\nname: Bad\nfields: [everything]\n---\nHi\n")
    assert prompts.load_summary_types(data_root) == []


def test_capture_prompt(sample_conn):
    st = prompts.DEFAULTS[2]  # report overview: raw text and file text
    blocks = prompts.capture_blocks(st, Model(sample_conn), "Rev 2 of the procedure.", [("Procedure.docx", "7.4 Laser-align")], "T000008")
    text = prompts.prompt_text(st, blocks)
    assert text.startswith(prompts.PREAMBLE + "\n\n## What to do\nGive a five-line summary")
    assert "## This capture\n<<<\nRev 2 of the procedure.\n>>>\n" in text and "## Text of Procedure.docx\n<<<\n7.4 Laser-align\n>>>" in text


def test_ancestor_context_covers_every_task_above(sample_conn):
    blocks = prompts.task_blocks(prompts.DEFAULTS[3], Model(sample_conn), "T000012")
    labels = [label for label, _ in blocks]
    assert "Event, Installation" in labels and any(label.startswith("Status change, Installation") for label in labels)
    assert any(label.startswith("Summary, Installation") for label in labels) and "Files, Reactor impeller upgrade" in labels


def test_mods_log_matches_the_example(data_root, fs):
    mods.add_entry(fs, data_root, "Capture window", "Open the task picker with the last task I saved to already highlighted.", datetime(2026, 10, 5, 8, 12))
    mods.add_entry(fs, data_root, "Parse and populate", '"End of October" wasn\'t picked up as the deadline. Add month-end phrases.', datetime(2026, 10, 7, 16, 47))
    mods.add_entry(fs, data_root, "Browse tool", "Add an Urgent filter to the task tree.", datetime(2026, 10, 8, 9, 2))
    mods.mark_done(fs, data_root, "M0001", date(2026, 10, 7))
    assert (data_root / "Mods" / "mods-log.md").read_text(encoding="utf-8") == example_block("Mods/mods-log.md")
    entries = mods.read_log(data_root)
    assert [(e.id, e.done) for e in entries] == [("M0001", "2026-10-07"), ("M0002", None), ("M0003", None)]
    assert mods.log_text(data_root) == example_block("Mods/mods-log.md")


def test_copy_open_leaves_out_done_entries(data_root, fs):
    """Mods log round 4 (M0066): Copy open copies only the entries not marked done, under the log's title and intro."""
    for i, area in enumerate(("Capture window", "Browse tool", "General")):
        mods.add_entry(fs, data_root, area, f"Change {i + 1}.", datetime(2026, 10, 8, 9, i))
    mods.mark_done(fs, data_root, "M0002", date(2026, 10, 9))
    mods.edit_entry(fs, data_root, "M0003", "General", "Change 3, reworded.", date(2026, 10, 9))
    text = mods.log_text(data_root, open_only=True)
    assert text.startswith(mods.TITLE + "\n\n" + mods.INTRO + "\n")
    assert "## M0001 · 2026-10-08 09:00 · Capture window · open" in text
    assert "## M0003 · 2026-10-08 09:02 · General · open · edited 2026-10-09\n\nChange 3, reworded." in text
    assert "M0002" not in text and "Change 2." not in text
    assert "M0002 · 2026-10-08 09:01 · Browse tool · done 2026-10-09" in mods.log_text(data_root)


def test_mods_log_checks_its_input(data_root, fs):
    with pytest.raises(ValueError):
        mods.add_entry(fs, data_root, "General", "  ", datetime(2026, 10, 8))
    with pytest.raises(ValueError):
        mods.add_entry(fs, data_root, "Somewhere", "x", datetime(2026, 10, 8))
    with pytest.raises(ValueError):
        mods.mark_done(fs, data_root, "M0009", date(2026, 10, 8))


def test_editing_a_mods_log_entry(data_root, fs):
    """Mods log round 2 (M0047): an entry's note and area can be replaced; its heading then says when it was edited."""
    mods.add_entry(fs, data_root, "Capture window", "Make the window wider.", datetime(2026, 10, 8, 9, 0))
    mods.add_entry(fs, data_root, "Browse tool", "Add an Urgent filter.", datetime(2026, 10, 8, 9, 5))
    entry = mods.edit_entry(fs, data_root, "M0001", "General", "Make the window wider, so the found list fits beside the text.", date(2026, 10, 9))
    assert (entry.id, entry.at, entry.edited) == ("M0001", "2026-10-08 09:00", "2026-10-09")
    text = (data_root / "Mods" / "mods-log.md").read_text(encoding="utf-8")
    assert "## M0001 · 2026-10-08 09:00 · General · open · edited 2026-10-09\n\nMake the window wider, so the found list fits beside the text.\n" in text
    mods.mark_done(fs, data_root, "M0001", date(2026, 10, 10))
    first, second = mods.read_log(data_root)
    assert (first.done, first.edited, first.area, second.edited) == ("2026-10-10", "2026-10-09", "General", None)
    assert "## M0001 · 2026-10-08 09:00 · General · done 2026-10-10 · edited 2026-10-09" in mods.log_text(data_root)
    # Saving it unchanged changes nothing, not even the edited day.
    mods.edit_entry(fs, data_root, "M0002", "Browse tool", "Add an Urgent filter.", date(2026, 10, 11))
    assert mods.read_log(data_root)[1].edited is None
    for bad in (("M0002", "General", " "), ("M0002", "Somewhere", "x"), ("M0009", "General", "x")):
        with pytest.raises(ValueError):
            mods.edit_entry(fs, data_root, *bad, date(2026, 10, 11))
