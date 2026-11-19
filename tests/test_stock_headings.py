"""Stock headings (release 5.169, the design workspace's stock headings plan, decisions 788 to 793), without Qt: the
setting's check and defaults, the heading list's Stock headings group (on a task with no notes, with some, and with no
task; a stock heading already on the page isn't offered twice; the order with something typed), and the agents' page,
written once per change, with Contents.md's line to it. Over the made-up cooling tower project (``notes_example``)."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from docrepo import stock_headings, topics
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.pages import CONTENTS_FILE, STOCK_PAGE, write_pages, write_stock_page
from docrepo.stock_headings import DEFAULTS, StockHeading
from notes_example import build

NOW = datetime(2026, 11, 18, 9, 0)
STOCK = list(DEFAULTS) + [StockHeading("Risks", 2, "What could go wrong, and what's being done about it.")]


@pytest.fixture
def ex(sample_root):
    conn, root, fs = sample_root
    return build(conn, root, fs)


@pytest.fixture
def m(sample_root, ex):
    model = Model(sample_root[0])
    model.pages[ex.fill] = "# Tue 3 Nov 2026\n# Background\nOld fill sagging.\n# Vendor\n## Quotes\nTwo quotes."
    model.pages[ex.project] = "# Mon 2 Nov 2026\n# Schedule\nTower 2 offline 9 to 20 Mar."
    return model


# ---- the setting (decision 788) ----
def test_four_ship_at_level_1_and_are_written_only_once_changed(data_root, fs):
    s = Settings()
    assert [(h.name, h.level) for h in s.stock()] == [("Background", 1), ("Path forward", 1), ("Decisions", 1), ("Open questions", 1)]
    assert all(h.description for h in s.stock())
    s.save(fs, data_root)
    file = data_root / "Config" / "settings.json"
    assert "stock_headings" not in json.loads(file.read_text(encoding="utf-8"))
    s.stock_headings = [{"name": "Risks", "level": 2, "description": "What could go wrong."}]
    s.save(fs, data_root)
    assert json.loads(file.read_text(encoding="utf-8"))["stock_headings"] == [{"name": "Risks", "level": 2, "description": "What could go wrong."}]
    assert Settings.load(data_root).stock() == [StockHeading("Risks", 2, "What could go wrong.")]
    s.stock_headings = []  # an emptied list stays empty
    s.save(fs, data_root)
    assert Settings.load(data_root).stock_headings == []


def test_settings_json_s_list_is_checked_on_load(data_root, fs):
    file = data_root / "Config" / "settings.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"stock_headings": [
        {"name": "  Path   forward ", "level": 1, "description": "Next steps,\n in order."},
        {"name": "path forward", "level": 1, "description": "a second at its level"},
        {"name": "Path forward", "level": 2, "description": "the same words at another level is another"},
        {"name": "", "level": 1}, {"name": "Deep", "level": 4}, {"name": "Flag", "level": True}, "Background",
        {"name": "#Hashed", "level": 1}, {"name": "No words"}]}), encoding="utf-8")
    assert Settings.load(data_root).stock() == [StockHeading("Path forward", 1, "Next steps, in order."),
                                                StockHeading("Path forward", 2, "the same words at another level is another"),
                                                StockHeading("No words", 1, "")]
    file.write_text(json.dumps({"stock_headings": "Background"}), encoding="utf-8")
    assert Settings.load(data_root).stock() == list(DEFAULTS)  # not a list: the defaults


def test_the_card_s_rows_are_checked_for_save():
    rows = [{"name": " Risks ", "level": 2, "description": " What could go wrong. "}, {"name": "", "level": 1, "description": ""}]
    assert stock_headings.check(rows) == [{"name": "Risks", "level": 2, "description": "What could go wrong."}]
    with pytest.raises(ValueError, match="needs a name"):
        stock_headings.check([{"name": "", "level": 1, "description": "Words with no name"}])
    with pytest.raises(ValueError, match="two stock headings called risks at level 1"):
        stock_headings.check([{"name": "Risks", "level": 1}, {"name": "risks", "level": 1}])
    with pytest.raises(ValueError, match="level is 1, 2 or 3"):
        stock_headings.check([{"name": "Risks", "level": 5}])


# ---- the heading list (decision 789) ----
def test_a_task_with_no_notes_lists_every_stock_heading_at_its_level(m, ex):
    m.pages[ex.fill] = ""  # nothing in its project has one either
    got = topics.options(m, ex.crane, 1, stock=STOCK)
    assert [r.words for r in got.stock] == ["Background", "Path forward", "Decisions", "Open questions"]
    assert all(r.stock and r.times == 0 and r.about for r in got.stock)
    assert topics.sub_text(got.stock[1], date(2026, 11, 18)) == "What happens next, in order, and who does each step."
    assert [r.words for r in topics.options(m, ex.crane, 2, stock=STOCK).stock] == ["Risks"]
    assert topics.options(m, ex.crane, 3, stock=STOCK).stock == []


def test_one_the_page_has_is_listed_with_the_task_s_own_not_twice(m, ex):
    got = topics.options(m, ex.fill, 1, stock=STOCK)
    assert [r.words for r in got.here] == ["Background", "Vendor"]
    assert got.here[0].about == "Why this task exists, and what was known when it started." and not got.here[0].stock
    assert got.here[1].about == ""
    assert [r.words for r in got.stock] == ["Path forward", "Decisions", "Open questions"]
    assert [r.words for r in got.rows()].count("Background") == 1


def test_one_used_elsewhere_in_the_project_is_listed_there_not_twice(m, ex):
    m.pages[ex.survey] = "# Wed 11 Nov 2026\n# decisions\nScaffold first."
    got = topics.options(m, ex.fill, 1, stock=STOCK)
    assert [(r.words, r.about) for r in got.others if r.words == "decisions"] == [("decisions", "What was decided, when, and by whom.")]
    assert "Decisions" not in [r.words for r in got.stock]


def test_with_no_task_only_the_stock_headings_less_the_box_s_own(m, ex):
    own = topics.sections("# Background\nWhy.\n# Notes")
    got = topics.options(m, None, 1, own=own, stock=STOCK)
    assert got.here == [] and got.others == []
    assert [r.words for r in got.stock] == ["Path forward", "Decisions", "Open questions"]
    assert topics.options(m, None, 1).rows() == []  # with no stock headings, nothing, as before


def test_what_s_typed_narrows_them_and_the_starts_come_first(m, ex):
    stock = [StockHeading("Open questions", 1, "a"), StockHeading("Questions for the vendor", 1, "b")]
    assert [r.words for r in topics.options(m, ex.crane, 1, "quest", stock=stock).stock] == ["Questions for the vendor", "Open questions"]
    assert [r.words for r in topics.options(m, ex.crane, 1, "op", stock=STOCK).stock] == ["Open questions"]
    assert topics.options(m, ex.crane, 1, "zzz", stock=STOCK).stock == []


# ---- the page for agents (decision 792) ----
def test_the_page_says_what_they_are_and_lists_each():
    text = stock_headings.page(STOCK)
    assert text.startswith("# Stock headings\n")
    assert "kept as data" in text and "not instructions" in text
    assert "| Path forward | 1 | What happens next, in order, and who does each step. |" in text
    assert "| Risks | 2 | What could go wrong, and what's being done about it. |" in text
    assert "no stock headings" in stock_headings.page([])
    assert "a \\| b" in stock_headings.page([StockHeading("Pipes", 1, "a | b")])


def test_the_page_is_written_once_per_change(data_root, fs):
    path = data_root.joinpath(*STOCK_PAGE)
    assert write_stock_page(data_root, fs, DEFAULTS) is True and path.exists()
    assert write_stock_page(data_root, fs, DEFAULTS) is False
    assert write_stock_page(data_root, fs, STOCK) is True
    assert "Risks" in path.read_text(encoding="utf-8")
    assert write_stock_page(data_root, fs, STOCK) is False


def test_write_pages_writes_it_and_contents_points_to_it(sample_conn, data_root, fs):
    model = Model(sample_conn)
    write_pages(model, data_root, fs, NOW.date(), NOW, task_ids=[])
    assert "| Open questions | 1 |" in data_root.joinpath(*STOCK_PAGE).read_text(encoding="utf-8")
    contents = (data_root / CONTENTS_FILE).read_text(encoding="utf-8")
    assert ("Stock headings: Background, Path forward, Decisions and Open questions. What belongs under each is in "
            "[Views\\Stock headings.md](Views/Stock%20headings.md).") in contents
    s = Settings.load(data_root)
    s.stock_headings = []
    s.save(fs, data_root)
    write_pages(model, data_root, fs, NOW.date(), NOW, task_ids=[])
    assert "Stock headings:" not in (data_root / CONTENTS_FILE).read_text(encoding="utf-8")
    assert "no stock headings" in data_root.joinpath(*STOCK_PAGE).read_text(encoding="utf-8")
