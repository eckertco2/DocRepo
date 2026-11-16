"""The tagged labels page (release 5.153; the design workspace's ``docs/mods/tagged-labels-page-plan.md``, decisions 671
to 677): ``Views\\Tagged labels.md``, Contents.md's line, Task.md's names, and the import's column guesses. The tags are
made up."""
from __future__ import annotations

import time
from datetime import datetime

from docrepo import db, pages, tagged
from docrepo import tagged_import as ti
from docrepo.model import Model
from docrepo.pages import TAGGED_PAGE, write_pages, write_tagged_page
from docrepo.tagged import Label, Tagged

AT = datetime(2026, 10, 8, 9, 0)


def page_of(root) -> str:
    return root.joinpath(*TAGGED_PAGE).read_text(encoding="utf-8")


def add(conn, label: str, description: str = "", aliases=()) -> int:
    return tagged.add_label(conn, label, AT, description, aliases)


def suggest(conn, label: str) -> None:
    """A suggested label, as a tag pattern gives one its row (release 5.80)."""
    conn.execute("INSERT INTO tagged_labels (label, key, status, came, pattern, added) VALUES (?, ?, 'suggested', 'pattern', 'Pumps', ?)",
                 (label, tagged.key_of(label), AT.isoformat()))
    tagged.glossary_changed(conn)


def test_each_tag_is_one_line_with_its_name_and_every_way_it_is_written(sample_root):
    conn, root, fs = sample_root
    add(conn, "V-110", "Feed surge drum", ["feed drum", "D-10"])
    write_pages(Model(conn), root, fs, AT.date(), AT)
    page = page_of(root)
    assert page.startswith("# Tagged labels\n\n> Generated from docs.db on 2026-10-08 09:00.")
    assert "| Tag | Name | Also found as |" in page
    assert "| V-110 | Feed surge drum | V110, V 110, feed drum, D-10, D10 |" in page  # a short tag has no spaced form
    assert "kept as data" in page  # decision 677
    assert "1 in the glossary." in page


def test_the_page_is_in_natural_order_under_each_tags_letters(sample_root):
    conn, root, fs = sample_root
    for label in ("P-10", "V-2", "P-2", "22-PT-101A", "FIC-2210"):
        add(conn, label, f"{label} name")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    lines = [x for x in page_of(root).splitlines() if x.startswith("## ") or x.startswith("| ") and "name |" in x]
    assert lines == ["## FIC", "| FIC-2210 | FIC-2210 name | FIC2210, FIC 2210 |",
                     "## P", "| P-2 | P-2 name | P2 |", "| P-10 | P-10 name | P10 |",
                     "## PT", "| 22-PT-101A | 22-PT-101A name | 22PT101A, 22 PT 101A |",
                     "## V", "| V-2 | V-2 name | V2 |"]


def test_a_tag_with_no_name_and_a_name_with_a_pipe_or_line_break(sample_root):
    conn, root, fs = sample_root
    add(conn, "XV-1001")
    add(conn, "E-12", "Exchanger | shell\nside")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    page = page_of(root)
    assert "| XV-1001 | (no name) | XV1001, XV 1001 |" in page
    assert "| E-12 | Exchanger \\| shell side | E12 |" in page


def test_suggested_tags_have_their_own_section_and_no_counts_anywhere(sample_root):
    conn, root, fs = sample_root
    add(conn, "P-204A", "Charge pump A")
    suggest(conn, "P-999")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    page = page_of(root)
    assert "1 in the glossary, 1 new." in page
    head = page.index("## Found in the text, not in the glossary")
    assert page.index("| P-204A | Charge pump A |") < head < page.index("| P-999 | (new, no name yet) | P999, P 999 |")
    assert "(1)" not in page and "Mentioned" not in page  # decision 672: no counts, so it changes only with the glossary


def test_it_is_written_once_per_glossary_version(sample_root):
    conn, root, fs = sample_root
    add(conn, "R-101", "Reactor 1")
    assert write_tagged_page(Model(conn), root, fs, AT) is True
    # Another Model of the same version, as each save makes: the page isn't worked out or read again.
    assert write_tagged_page(Model(conn), root, fs, datetime(2026, 10, 8, 10, 0)) is False
    assert "on 2026-10-08 09:00." in page_of(root)
    lb = next(x for x in Model(conn).tagged.labels.values() if x.label == "R-101")
    tagged.edit_label(conn, lb.id, "Reactor 1, the first stage", [])
    assert write_tagged_page(Model(conn), root, fs, AT) is True
    assert "| R-101 | Reactor 1, the first stage | R101, R 101 |" in page_of(root)


def test_a_page_deleted_by_hand_is_written_again(sample_root):
    conn, root, fs = sample_root
    add(conn, "R-101", "Reactor 1")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    root.joinpath(*TAGGED_PAGE).unlink()
    write_pages(Model(conn), root, fs, AT.date(), AT)
    assert "| R-101 | Reactor 1 |" in page_of(root)


def test_no_glossary_no_page_and_an_emptied_one_says_so(sample_root):
    conn, root, fs = sample_root
    write_pages(Model(conn), root, fs, AT.date(), AT)
    assert not root.joinpath(*TAGGED_PAGE).exists()
    assert "Tagged labels:" not in (root / "Contents.md").read_text(encoding="utf-8")
    suggest(conn, "P-999")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    assert "| P-999 |" in page_of(root)
    with db.transaction(conn):
        conn.execute("DELETE FROM tagged_labels")
        tagged.glossary_changed(conn)
    write_pages(Model(conn), root, fs, AT.date(), AT)
    assert "The glossary is empty" in page_of(root) and "| P-999 |" not in page_of(root)


def test_contents_points_to_the_page(sample_root):
    conn, root, fs = sample_root
    add(conn, "R-101", "Reactor 1")
    suggest(conn, "P-999")
    write_pages(Model(conn), root, fs, AT.date(), AT)
    contents = (root / "Contents.md").read_text(encoding="utf-8")
    assert "Tagged labels: 1 in the glossary, 1 new. Look a tag up in [Views\\Tagged labels.md](Views/Tagged%20labels.md)." in contents
    assert contents.index("Tagged labels:") < contents.index("## Open tasks")


def test_a_task_pages_tags_have_their_names():
    lb = Label(1, "P-204A", "P204A", "Charge pump A\n(spare)")
    assert pages._tag_words(lb, 3) == "P-204A Charge pump A (spare) (3)"
    assert pages._tag_words(Label(2, "P-999", "P999", status="suggested"), 1) == "P-999 (1)"


def test_found_as_and_letters():
    assert tagged.found_as(Label(1, "V-110", "V110", aliases=("V110", "feed drum", "D-10"))) == ["V110", "V 110", "feed drum", "D-10", "D10"]
    assert tagged.found_as(Label(1, "R101", "R101")) == []
    assert [tagged.letters_of(x) for x in ("FIC-2210", "22-PT-101A", "v-110", "2210")] == ["FIC", "PT", "V", "Other"]


def rows_of(text: str) -> list[list[str]]:
    return [line.split(",") for line in text.strip().split("\n")]


def test_the_import_finds_the_name_column():
    rows = rows_of("Tag Number,Equipment Name,Area\nV-110,Feed surge drum,Area 2\nR-101,Reactor 1,Area 1")
    assert ti.propose(rows, 0) == ["label", "description", "skip"]
    rows = rows_of("Tag Name,Description\nV-110,Feed surge drum")
    assert ti.propose(rows, 0) == ["label", "description"]
    rows = rows_of("Name,Tag\nFeed surge drum,V-110\nReactor 1,R-101")
    assert ti.propose(rows, 0) == ["description", "label"]
    # 5.79's own headers are read as they were.
    rows = rows_of("Tagged label,Tagged label description,Tagged label aliases\nV-110,Feed surge drum,feed drum")
    assert ti.propose(rows, 0) == ["label", "description", "aliases"]


def test_the_tag_column_is_found_by_its_cells():
    # Two headers say "tag": the one whose cells are tags wins.
    rows = rows_of("Equipment,Tag\nFeed surge drum,V-110\nReactor,R-101\nCharge pump,P-204A")
    assert ti.propose(rows, 0) == ["skip", "label"]
    # No header says: the column of tags, when at least half its cells are tags.
    rows = rows_of("Area,Code,Notes\nArea 2,V-110,old\nArea 1,R-101,\nArea 2,P-204A,spare")
    assert ti.propose(rows, 0) == ["skip", "label", "skip"]
    # No column of tags: the first, as before.
    rows = rows_of("Area,Notes\nNorth,old\nSouth,new")
    assert ti.propose(rows, 0) == ["label", "skip"]


def test_twenty_thousand_tags_make_their_page_quickly():
    labels = {i: Label(i, f"P-{i}A", f"P{i}A", f"Pump {i} A", (f"pump {i}",)) for i in range(1, 20_001)}
    tg = Tagged(labels)
    started = time.perf_counter()
    text = pages.tagged_page(tg, "2026-10-08 09:00")
    took = time.perf_counter() - started
    assert text.count("\n| P-") == 20_000 and "| P-20000A | Pump 20000 A | P20000A, P 20000A, pump 20000 |" in text
    assert took < 3.0, f"{took:.2f} s"  # 0.3 s on the personal computer
    started = time.perf_counter()
    pages.tagged_page(tg, "2026-10-08 10:00")
    assert time.perf_counter() - started < took  # the body is kept with its version
