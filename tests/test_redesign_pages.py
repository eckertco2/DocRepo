"""The redesign's lane C, the pages (the design workspace's ``docs/mods/redesign-lane-c-plan.md``), driven offscreen over the
sample data and the workspace's made-up work. Release 5.185 (the task page and the workspace, decision 859): the status
card's commands as buttons, flat subtask rows, one left edge, and the workspace with no style sheet of its own, its labels
in sentence case, Dates in a panel of its own and the task page's card."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from docrepo import detail, edits  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui import tokens  # noqa: E402
from docrepo.ui import workspace as workspace_ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.task_pane import PAGE_EDGE  # noqa: E402
from workspace_example import AT, make  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qapp, sample_root):
    """The browse window over the sample, with the workspace's made-up work: its crane task waits on Mike, and is on Today."""
    conn, root, fs = sample_root
    work = make(conn, root, fs)
    edits.add_to_today(conn, root, fs, work.crane, "", AT)
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1500, 900)
    yield w, work
    if getattr(w, "workspace", None) is not None:
        w.workspace.pane.notes.save_now()
    capture.deleteLater()
    w.deleteLater()


def settle() -> None:
    for _ in range(5):
        QApplication.processEvents()


def task_page(w, task_id: str):
    w.set_view("tasks")
    w.go_task(task_id)
    settle()
    return w.task_pane


def rule(sheet: str, selector: str) -> str:
    """The body of the last rule in ``sheet`` that begins with ``selector``."""
    found = re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", sheet)
    assert found, selector
    return found[-1]


# ---- the task page ----
def test_the_status_cards_commands_are_buttons(setup):
    w, work = setup
    header = task_page(w, "T000008").header
    assert [b.text() for b in header.actions.buttons] == ["Log progress…"] and header.actions.isVisibleTo(header)
    assert "Log progress…" in header.text() and "Log progress…" not in header.status_body.toPlainText()
    asked: list[str] = []
    header.status_body.anchorClicked.connect(lambda url: asked.append(url.toString()))
    w.ctx.log_progress = lambda task_id, *a, **k: None  # what the address opens is test_log_progress_ui's
    header.actions.buttons[0].click()
    assert asked == ["progress:T000008"]
    waiting = task_page(w, work.crane).header  # it waits on Mike: Got it first
    assert [b.text() for b in waiting.actions.buttons] == ["Got it", "Log progress…"]


def test_subtask_rows_are_flat(setup):
    w, _ = setup
    parts = w.pages().task_parts("T000008", detail.PageState())
    assert parts["subtasks"].startswith(detail.ROWS)
    tile = rule(tokens.css(), ".tile")
    assert "border-top" in tile and "background-color" not in tile


def test_the_page_keeps_one_left_edge(setup):
    w, _ = setup
    pane = task_page(w, "T000008")
    w.split.setSizes([248, 900, 0])
    settle()
    inner = pane.widget()
    head = pane.header.head
    head_x = head.mapTo(inner, QPoint(round(head.document().documentMargin()), 0)).x() + head.viewportMargins().left()
    section = next(g for g in pane.header.groups.values() if g.isVisible())
    b = section.button
    words_x = b.mapTo(inner, QPoint(0, 0)).x() + b.iconSize().width() + 2 + 4  # the chevron, then the icon's gap and padding
    notes_x = pane.title.mapTo(inner, QPoint(0, 0)).x()
    assert pane._margin == PAGE_EDGE
    assert abs(notes_x - PAGE_EDGE) <= 1 and abs(head_x - PAGE_EDGE) <= 1, (head_x, notes_x)
    assert abs(words_x - PAGE_EDGE) <= 4, words_x  # the chevron hangs in the margin (HANG)


# ---- the workspace ----
def opened(w, task_id: str):
    workspace_ui.open_workspace(w, task_id)
    settle()
    return w.workspace


def test_the_workspace_has_no_style_sheet_of_its_own(setup):
    w, work = setup
    ws = opened(w, work.crane)
    assert ws.styleSheet() == "" and "QFrame#wsChainCard" in tokens.qss()


def test_the_workspaces_labels_are_in_sentence_case(setup):
    w, work = setup
    ws = opened(w, work.crane)
    shouting = [lb.text() for lb in ws.findChildren(QLabel)
                if len(re.sub(r"[^A-Za-z]", "", lb.text())) > 3 and lb.text() == lb.text().upper() and "<" not in lb.text()]
    assert shouting == []
    assert "This task" in ws.chain.text() and "Up the chain" in ws.chain.captions() and "Subtasks" in ws.chain.captions()


def test_dates_has_a_frame_of_its_own(setup):
    w, work = setup
    ws = opened(w, work.crane)
    assert ws.dates.frame.objectName() == "wsDatesFrame"
    kinds = {r.kind: parts["kind"].property("kind") for r, parts in ws.dates.shown.values()}
    assert kinds.get("Key date", "") == "" and all(not p["when"].styleSheet() and not p["kind"].styleSheet() for _, p in ws.dates.shown.values())


def test_the_workspaces_card_has_the_task_pages_commands(setup):
    w, work = setup
    ws = opened(w, work.crane)
    assert [b.text() for b in ws.card.actions.buttons] == ["Got it", "Log progress…"]
    assert "Log progress…" in ws.text() and "Log progress…" not in ws.card.body.toPlainText()
    asked: list[str] = []
    ws.card.link.disconnect()
    ws.card.link.connect(asked.append)
    ws.card.actions.buttons[-1].click()
    assert asked == [f"progress:{work.crane}"]
    ws.card.link.disconnect()
    ws.card.link.connect(ws.on_link)
    ws.pick(work.project)  # a parent picked in the chain is read only: no commands
    settle()
    assert ws.card.actions.buttons == [] and not ws.card.actions.isVisibleTo(ws.card)
