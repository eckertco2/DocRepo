"""One word for it, update (release 5.173, the design workspace's docs/mods/one-word-update-plan.md, decisions 811 to 814).

On screen and on the pages, Current status is Latest update (Last update once closed) and the status log is History
(811); what's stored keeps its names, and ``tasks.shown_name`` turns a stored name into the word shown (812); what's typed
still works (813). The last test is a rule, as the hard-rule tests are: the retired words don't come back in the text the
windows show. The sample data is made up."""
from __future__ import annotations

import ast
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from docrepo import excel_import, items, tasks
from docrepo.captures import read_content
from docrepo.config import Settings
from docrepo.detail import PageState
from docrepo.detail import Pages as DetailPages
from docrepo.model import Model
from docrepo.pages import Pages
from docrepo.parse import ParsePerson
from docrepo.save import CaptureDraft, save_capture

TODAY = date(2026, 10, 8)
AT = datetime(2026, 10, 8, 9, 0)
DOCREPO = Path(__file__).resolve().parent.parent / "docrepo"


def stored(conn) -> list[tuple]:
    return conn.execute("SELECT task, at, field, from_value, to_value, via FROM status_log ORDER BY rowid").fetchall()


def test_the_shown_name_of_a_stored_one():
    assert tasks.shown_name("Current status") == "Latest update"
    assert tasks.shown_name("Due") == "Due" and tasks.shown_name("Parents") == "Parents"  # any other is as stored
    assert tasks.FIELD_NAMES["current_status"] == "Current status"  # the name a change is kept under stays


def test_an_old_root_reads_with_the_new_words_and_nothing_is_rewritten(sample_root):
    """The sample data's history was written as any root before this release: a change to the line kept as "Current
    status". Its pages say Latest update and History, and docs.db is as it was."""
    conn, root, fs = sample_root
    before = stored(conn)
    assert any(r[2] == "Current status" for r in before)
    m = Model(conn)
    md = Pages(m, TODAY, AT).task_page(m.task("T000008"))
    assert "## Latest update" in md and "## History" in md and "## Current status" not in md and "## Status log" not in md
    assert "· Latest update: Procedure in review. → Procedure rev 2 approved." in md and "· Current status:" not in md
    page = DetailPages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    html = page.task_page("T000008", PageState())
    assert "Latest update" in html and "Current status" not in html and "Status log" not in html
    assert stored(conn) == before  # nothing in docs.db is rewritten


def test_a_closed_task_says_last_update(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    closed = next(t for t in m.tasks.values() if t.state == "Closed" and t.current_status and not t.collection)
    page = DetailPages(m, TODAY, lambda cid: read_content(root, m.captures[cid]) or "", "P001", conn)
    assert page.status_parts(closed)[0] == "Last update"
    assert page.status_parts(m.task("T000008"))[0] == "Latest update"


def names_of(model: Model) -> items.Names:
    people = [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == "P001") for p in model.people.values()]
    return items.names_of(model, people)


@pytest.mark.parametrize("line", ["#Holiday coverage schedule **status, Waiting on the vendor's quote",
                                  "#Holiday coverage schedule **current status, Waiting on the vendor's quote",
                                  "#Holiday coverage schedule **latest update, Waiting on the vendor's quote", "**update, Waiting on the vendor's quote",
                                  "**u, Waiting on the vendor's quote"])
def test_each_typed_name_sets_the_line(sample_root, line):
    """``**status,`` and ``**current status,`` as before, ``**latest update,`` as the ``**`` list now names it (each a
    field, on a ``#`` task's line, for a task with none yet: a field already filled isn't overwritten), and an update (``**update,``, ``**u,``), whose words become the line (813)."""
    conn, root, fs = sample_root
    save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=f"Called the vendor.\n- {line}", task="T000016", types={"note"}, files=[]), AT)
    m = Model(conn)
    assert m.task("T000016").current_status == "Waiting on the vendor's quote"
    assert any(e.field == "Current status" and e.to_value == "Waiting on the vendor's quote" for e in m.status_log_of("T000016"))


def test_the_star_list_shows_the_new_word(sample_conn):
    names = names_of(Model(sample_conn))
    shown = [(o.value, o.sub) for o in items.star_options("latest", names)]
    assert shown[0] == ("latest update,", "Field: **latest update, Waiting on the vendor's quote")
    assert [o.value for o in items.star_options("status", names)][0] == "latest update,"  # the old name still finds it
    rows = {row[0]: row for row in items.syntax_rows()}
    assert rows["**latest update,"][1:3] == ("**status,, **current status,", "Latest update")
    assert "**status," not in rows and "**update," in rows


@pytest.mark.parametrize("header", ["Current status", "Latest update", "Status update", "Status"])
def test_an_import_takes_the_old_header_and_the_new(header):
    assert excel_import.guess_field(header, ["Waiting on the PO."]) == "current_status"
    assert excel_import.FIELD_NAMES["current_status"] == "Latest update"


#: The retired words (decision 814), as the windows would show them. "Current status" alone is the name a change is
#: stored under, and "current status" and "status update" are typed names an import or ``**`` still reads (813).
RETIRED = ("status log", "status card", "status update", "current status", "final status", "no status yet", "status cleared")
STORED_OR_TYPED = {"Current status", "current status", "status update"}


def shown_strings(path: Path) -> list[tuple[int, str]]:
    """Every string in a module but its docstrings: what a window, a message or a page can say."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_the_retired_words_dont_come_back():
    found = []
    for path in sorted(DOCREPO.rglob("*.py")):
        for line, text in shown_strings(path):
            if text in STORED_OR_TYPED:
                continue
            low = re.sub(r"--[^\n]*|/\*.*?\*/", "", text, flags=re.S).lower()  # an SQL or a stylesheet comment isn't shown
            if any(word in low for word in RETIRED):
                found.append(f"{path.relative_to(DOCREPO.parent)}:{line}: {text[:80]}")
    assert found == []
