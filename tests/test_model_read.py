"""Reading docs.db, faster (release 5.160, the design workspace's ``docs/mods/model-read-plan.md``, decisions 733 to 736): a
Model reads the tagged labels' mentions only when something first asks for them (733), and a page that shows a few
items' tags reads only theirs (734), with the same contents as the read of every mention with the Model had before.
Every tag, task and word here is made up."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from docrepo import db, pages, search, summary, tagged
from docrepo import tagged_import as ti
from docrepo.config import Settings
from docrepo.detail import PageState
from docrepo.detail import Pages as BrowsePages
from docrepo.model import Model
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample, read_sample, write_sample_files
from docrepo.sample_scale import add_scale_extras, add_years
from docrepo.save import CaptureDraft, save_capture
from docrepo.tagged import Mention, Tagged

AT = datetime(2026, 10, 8, 9, 0)
TODAY = AT.date()
TAGS = ("Tag,Description,Aliases\nV-110,Feed surge drum,feed drum; D-10\nR-101,Reactor 1,\nP-204A,Charge pump A,\n"
        "P-204B,Charge pump B,\nXV-1001,Feed isolation valve,\nTIC-2216,Jacket temperature,\n")


def eager(conn: sqlite3.Connection) -> tuple[list[Mention], dict[tuple[str, str], dict[str, str]]]:
    """Every mention and the owner's own changes, read as ``tagged.load`` read them with each Model before release 5.160."""
    mentions = [Mention(r["kind"], r["id"], r["label"], r["how"], r["n"], json.loads(r["written"]))
                for r in conn.execute("SELECT * FROM tagged_mentions ORDER BY kind, id")]
    choices: dict[tuple[str, str], dict[str, str]] = {}
    for r in conn.execute("SELECT kind, id, key, choice FROM tagged_choices"):
        choices.setdefault((r["kind"], r["id"]), {})[r["key"]] = r["choice"]
    return mentions, choices


def eager_model(conn: sqlite3.Connection) -> Model:
    """A Model whose tagged labels are as the eager read had them, every mention in hand: what a lazily read one must equal."""
    m = Model(conn)
    mentions, choices = eager(conn)
    m.tagged = Tagged(m.tagged.labels, mentions, choices)
    return m


def newest(conn: sqlite3.Connection) -> str:
    """The capture saved last."""
    return conn.execute("SELECT id FROM captures ORDER BY saved DESC, rowid DESC LIMIT 1").fetchone()[0]


def items_of(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every capture, document and notes page: those with a mention and those without."""
    m = Model(conn)
    return ([("capture", c) for c in m.captures] + [("document", d) for d in m.documents] + [("page", t) for t in m.pages]
            + [("capture", "C999999")])


@pytest.fixture
def tagged_sample(sample_root):
    """The sample data with a made-up glossary, a notes page and a capture that mention its tags, and the owner's own
    changes."""
    conn, root, fs = sample_root
    path = root.parent / "tags.csv"
    path.write_text(TAGS, encoding="utf-8")
    rows = ti.read_rows(path)
    header = ti.guess_header(rows)
    ti.run_import(conn, ti.preview(conn, rows, ti.Plan(header, ti.propose(rows, header))), "tags.csv", AT)
    for text, task in (("Seal faces for P-204A/B are late. V110 alarmed twice; the feed drum is full.", "T000008"),
                       ("XV-1001 closes on high level, and TIC-2216 reads high on R-101.", None)):
        save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=text, task=task), datetime(2026, 10, 8, 15, 0))
    cid = newest(conn)
    tagged.choose(conn, "capture", cid, "R101", "removed", AT)
    tagged.choose(conn, "document", "D000002", "V110", "added", AT)
    return conn, root, fs


@pytest.fixture(scope="module")
def small_scale(tmp_path_factory) -> sqlite3.Connection:
    """A fiftieth of a year of the scale generator's made-up work (``sample_scale``), with its glossary and the mentions
    the search index's rebuild finds: many items, many tags."""
    folder = tmp_path_factory.mktemp("small-scale")
    root = folder / "DocRepoData"
    root.mkdir()
    fs = SafeFS([root])
    data = add_years(read_sample(), 1, scale=0.02)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOCALAPPDATA", str(folder / "localappdata"))
        conn = db.connect(fs, root)
        load_sample(conn, data)
        add_scale_extras(conn, data)
        write_sample_files(conn, root, fs, data)
        search.rebuild(conn, root)
    first, second = conn.execute("SELECT kind, id, label FROM tagged_mentions WHERE kind != 'page' ORDER BY kind, id LIMIT 2").fetchall()
    key = conn.execute("SELECT key FROM tagged_labels WHERE id = ?", (first["label"],)).fetchone()[0]
    tagged.choose(conn, first["kind"], first["id"], key, "removed", AT)
    unsaid = conn.execute("SELECT key FROM tagged_labels WHERE id NOT IN (SELECT label FROM tagged_mentions WHERE kind = ? AND id = ?) "
                          "ORDER BY id LIMIT 1", (second["kind"], second["id"])).fetchone()[0]
    tagged.choose(conn, second["kind"], second["id"], unsaid, "added", AT)
    yield conn
    conn.close()


@pytest.fixture(params=["sample", "scale"])
def root_with_tags(request) -> sqlite3.Connection:
    if request.param == "sample":
        return request.getfixturevalue("tagged_sample")[0]
    return request.getfixturevalue("small_scale")


# ---- decision 733: read when something asks ----
def test_a_model_reads_the_glossary_and_no_mention(tagged_sample):
    conn, _, _ = tagged_sample
    m = Model(conn)
    tg = m.tagged
    assert tg and not tg.loaded
    assert {lb.id: lb for lb in tagged.read_labels(conn)} == tg.labels and tg.by_key["V110"].label == "V-110"
    assert [h.written for h in tg.finder().find("V110 and the feed drum")] == ["V110", "feed drum"]
    assert tg.choices == eager(conn)[1]
    assert pages.tagged_counts(tg) == "6 in the glossary" and not tg.loaded  # Contents.md's line needs only the glossary
    assert tg.mentions == eager(conn)[0] and tg.loaded


def test_read_lazily_the_mentions_are_those_the_eager_read_had(root_with_tags):
    conn = root_with_tags
    mentions, choices = eager(conn)
    assert len(mentions) > 5
    for touch in ("mentions", "by_item", "by_label"):
        tg = Model(conn).tagged
        getattr(tg, touch)
        assert tg.loaded
        assert tg.mentions == mentions and tg.choices == choices
        old = Tagged(tg.labels, mentions, choices)
        assert tg.by_item == old.by_item and tg.by_label == old.by_label
    assert tagged.load(conn, lazily=False).loaded and tagged.load(conn, lazily=False).mentions == mentions


def test_a_model_with_no_glossary_reads_nothing_more():
    conn = db.connect_memory()
    load_sample(conn)
    tg = Model(conn).tagged
    assert not tg and tg.loaded and tg.mentions == [] and tg.item("capture", "C000001") == []
    conn.close()


# ---- decision 734: a few items' mentions ----
def test_each_items_tags_read_alone_are_as_the_full_read_has_them(root_with_tags):
    conn = root_with_tags
    full = eager_model(conn).tagged
    lazy = Model(conn).tagged
    keys = items_of(conn)
    for kind, item_id in keys:
        assert lazy.item(kind, item_id) == full.item(kind, item_id), (kind, item_id)
        assert lazy.removed(kind, item_id) == full.removed(kind, item_id)
    assert lazy.loaded == (len(keys) > tagged.SOME_MOST)


def test_items_read_together_are_as_the_full_read_has_them(root_with_tags):
    conn = root_with_tags
    full = eager_model(conn).tagged
    lazy = Model(conn).tagged
    keys = items_of(conn)
    lazy.read_items(keys[::-1])  # in any order, and across several queries
    assert not lazy.loaded or len(keys) > tagged.SOME_MOST
    assert [lazy.item(*k) for k in keys] == [full.item(*k) for k in keys]


def test_items_are_read_in_parts_of_a_few_hundred(root_with_tags, monkeypatch):
    conn = root_with_tags
    monkeypatch.setattr(tagged, "_IN_MOST", 3)
    full = eager_model(conn).tagged
    lazy = Model(conn).tagged
    keys = items_of(conn)[:40]
    lazy.read_items(keys)
    assert [lazy.item(*k) for k in keys] == [full.item(*k) for k in keys]


def test_past_some_most_items_every_mention_is_read_at_once(tagged_sample, monkeypatch):
    conn, _, _ = tagged_sample
    monkeypatch.setattr(tagged, "SOME_MOST", 2)
    full = eager_model(conn).tagged
    lazy = Model(conn).tagged
    keys = items_of(conn)
    lazy.read_items(keys[:2])
    assert not lazy.loaded
    lazy.read_items(keys[2:3])
    assert lazy.loaded and lazy.mentions == full.mentions
    assert [lazy.item(*k) for k in keys] == [full.item(*k) for k in keys]


def test_a_tasks_tags_read_only_its_items(root_with_tags):
    conn = root_with_tags
    full = eager_model(conn)
    lazy = Model(conn)
    some = 0
    for t in full.tasks:
        want = tagged.task_tags(full, t)
        assert tagged.task_tags(lazy, t) == want, t
        some += bool(want)
    assert some
    assert not lazy.tagged.loaded or len(items_of(conn)) > tagged.SOME_MOST


# ---- every view that shows tags still shows them ----
def test_task_md_and_contents_md_show_the_same_tags(tagged_sample):
    conn, _, _ = tagged_sample
    full, lazy = eager_model(conn), Model(conn)
    before, after = pages.Pages(full, TODAY, AT), pages.Pages(lazy, TODAY, AT)
    shown = 0
    for t in full.tasks.values():
        page = after.task_page(lazy.task(t.id))
        assert page == before.task_page(t), t.id
        shown += any(line.startswith("| Tagged labels |") and "V-110" in line for line in page.splitlines())
    assert shown and not lazy.tagged.loaded
    assert after.contents_page() == before.contents_page() and "Tagged labels: 6 in the glossary" in after.contents_page()
    assert pages.tagged_page(lazy.tagged, "2026-10-08 09:00") == pages.tagged_page(full.tagged, "2026-10-08 09:00")
    assert not lazy.tagged.loaded


def test_the_browse_tools_pages_show_the_same_tags(tagged_sample):
    conn, _, _ = tagged_sample
    full, lazy = eager_model(conn), Model(conn)
    before = BrowsePages(full, TODAY, lambda c: "", conn=conn)
    after = BrowsePages(lazy, TODAY, lambda c: "", conn=conn)
    open_ = PageState(details=True)  # the record unfolded, with its Tagged labels row
    assert after.task_page("T000008", open_) == before.task_page("T000008", open_)
    assert "Tagged labels" in after.task_page("T000008", open_) and "V-110" in after.task_page("T000008", open_)
    cid = newest(conn)
    assert after.capture_page(cid, "") == before.capture_page(cid, "") and "XV-1001" in after.capture_page(cid, "")
    assert after.document_page("D000002") == before.document_page("D000002")
    assert not lazy.tagged.loaded  # one task's, one capture's and one document's tags: only theirs were read
    for key in ("V110", "R101", "XV1001"):
        assert after.tagged_page(key) == before.tagged_page(key)  # a label's page reads them all
    assert lazy.tagged.loaded


def test_the_tagged_labels_view_search_and_the_quick_summary_count_the_same(tagged_sample):
    conn, _, _ = tagged_sample
    full = eager_model(conn)
    assert tagged.counts(Model(conn)) == tagged.counts(full) and tagged.counts(full)
    assert tagged.suggestions(Model(conn)) == tagged.suggestions(full)
    for lb in full.tagged.labels.values():
        assert tagged.uses_of(Model(conn), lb) == tagged.uses_of(full, lb)
    for query in ("tag:V-110", "tag:P-204A", "feed drum", "XV-1001"):
        got = [(r.group, r.kind, r.id, r.title) for r in search.search(conn, Model(conn), query, TODAY)]
        assert got == [(r.group, r.kind, r.id, r.title) for r in search.search(conn, full, query, TODAY)], query
    assert search.search(conn, Model(conn), "tag:V-110", TODAY)
    for key in ("V110", "TIC2216"):
        assert summary.Builder(Model(conn), TODAY, "P001", conn).tag_task_ids(key) == summary.Builder(full, TODAY, "P001", conn).tag_task_ids(key)
    assert summary.Builder(Model(conn), TODAY, "P001", conn).tag_task_ids("V110")


# ---- the page writes ----
def test_a_changes_pages_read_only_their_tasks_items_and_every_page_reads_all(tagged_sample):
    conn, root, fs = tagged_sample
    m = Model(conn)
    pages.write_pages(m, root, fs, TODAY, AT, ["T000008", "T000001"])
    assert not m.tagged.loaded
    md = (root / "Tasks" / "T000008" / "Task.md").read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("| Tagged labels |") and "V-110 Feed surge drum (" in line for line in md)
    pages.write_pages(m, root, fs, TODAY, AT)
    assert m.tagged.loaded


# ---- read later (the plan's question of a Model kept long) ----
def test_a_model_read_before_a_change_shows_only_its_own_items(tagged_sample):
    """The mentions are read from docs.db when they're asked for. A Model kept past a change sees that change's mentions
    of its own items, and passes over the items it doesn't have, never an error."""
    conn, root, fs = tagged_sample
    old = Model(conn)
    lb = old.tagged.by_key["XV1001"]
    uses = {(u.kind, u.id) for u in tagged.uses_of(eager_model(conn), lb)}
    assert ("page", "T000008") not in uses
    for task in (None, "T000008"):  # a new capture, and a note on a task's notes page
        save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content="XV-1001 tested again.", task=task), datetime(2026, 10, 8, 16, 0))
    (new,) = set(Model(conn).captures) - set(old.captures)
    got = {(u.kind, u.id) for u in tagged.uses_of(old, lb)}
    assert ("capture", new) not in got  # not the old Model's capture, so left out
    assert got == uses | {("page", "T000008")}  # the old Model's notes page, which now mentions it
    assert ("capture", new) in {(u.kind, u.id) for u in tagged.uses_of(Model(conn), lb)}
    assert tagged.counts(old)[lb.id] == len(got)
