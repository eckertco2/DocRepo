"""Release 5.124 in the browse window, offscreen (the design workspace's ``docs/mods/cold-eyes-plan.md``, section 3): the
task page's Decisions section in its place, its Copy on the clipboard, Show all, and ``type:decision`` in Search
everything. ``test_decisions.py`` has the rest, without Qt. Every decision here is made up."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.task_header import GROUPS, OPEN_BY_DEFAULT  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 9, 9, 0)
SETTINGS = Settings(me="P001")
REACTOR, VERIFY, INSTALLATION, BUSINESS = "T000001", "T000002", "T000008", "T000010"
NOTES = """#Reactor impeller upgrade
- **decision, we go with the 50 t crane. It's cheaper than two lifts.
#Rigging plan **decision, lift on the 20th."""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    c = AppContext(conn, root, fs, SETTINGS, now=lambda: NOW)
    save_capture(conn, root, fs, SETTINGS, CaptureDraft(content=NOTES, task=BUSINESS, meeting=True), datetime(2026, 10, 8, 14, 10))
    return c


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.said = []
    w.say = lambda text, error=False: w.said.append((text, error))
    w.show_browse()
    w.resize(1440, 900)
    yield w
    for view in list(w.task_views.values()):
        view.deleteLater()
    capture.deleteLater()
    w.deleteLater()


def test_the_section_comes_after_subtasks_open(browse):
    keys = [k for k, _ in GROUPS]
    assert keys.index("subtasks") + 1 == keys.index("decisions") == keys.index("emails") - 1 and "decisions" in OPEN_BY_DEFAULT
    browse.go_task(REACTOR)
    QApplication.processEvents()
    header = browse.task_pane.header
    g = header.groups["decisions"]
    assert g.present and g.is_open and not g.isHidden()
    lay = header.layout()
    order = [lay.indexOf(header.groups[k]) for k in ("subtasks", "decisions", "emails")]
    assert order == sorted(order)
    words = " ".join(g.text().replace("￼", " ").split())
    assert words.startswith("Decisions 2 Copy We go with the 50 t crane.") and "Lift on the 20th. ↗ Rigging plan in Business team meeting, 8 Oct" in words
    browse.go_task(VERIFY)
    assert not browse.task_pane.header.groups["decisions"].present


def test_copy_puts_the_register_on_the_clipboard(browse):
    browse.go_task(REACTOR)
    browse.on_link(QUrl(f"copydecisions:{REACTOR}"))
    data = QGuiApplication.clipboard().mimeData()
    assert data.hasHtml() and "<table" in data.html() and "Business team meeting, 8 Oct" in data.html()
    assert data.text().splitlines()[:3] == ["| Date | Decision | Task | Where |", "|---|---|---|---|",
                                            "| 2026-10-08 | We go with the 50 t crane. It's cheaper than two lifts. | Reactor impeller upgrade | Business team meeting, 8 Oct |"]
    assert browse.said[-1] == ("Copied the decision register: 2 decisions, as a table.", False)


def test_show_all_and_a_click_opens_its_capture(browse, ctx):
    for n in range(5):
        save_capture(ctx.conn, ctx.data_root, ctx.fs, SETTINGS, CaptureDraft(content=f"**decision, option {n}.", task=INSTALLATION),
                     datetime(2026, 10, 1 + n, 9, 0))
    browse.go_task(REACTOR)
    assert "Show all 7 decisions" in " ".join(browse.task_pane.header.groups["decisions"].text().split())
    browse.on_link(QUrl("fold:decisions"))
    assert browse.state.decisions and "Show fewer" in browse.task_pane.header.groups["decisions"].text()
    newest = next(c for c in browse.model().captures.values() if c.item == "decision" and c.title == "Option 4")
    browse.on_link(QUrl(f"capture:{newest.id}"))
    assert browse.sel == ("capture", newest.id)


def test_type_decision_in_search_everything(browse):
    browse.search_box.setText("type:decision")
    browse._run_search()
    assert browse.view == "search" and browse.pane_title.text().startswith("Search Decisions&nbsp;")
    t = browse.tree
    rows = [t.topLevelItem(i) for i in range(t.topLevelItemCount())]
    found = [r for r in rows if r.data(0, KEY_ROLE)]
    assert [r.data(0, LINE_ROLE).title for r in found] == ["We go with the 50 t crane", "Lift on the 20th"]
    line = found[1].data(0, LINE_ROLE)
    assert (line.icon, line.icon_tip) == ("decision", "Decision") and line.second == "Rigging plan · in Business team meeting, 8 Oct"
    assert ["<b>Decisions</b>" in (r.data(0, HTML_ROLE) or "") for r in rows if not r.data(0, KEY_ROLE)] == [True]  # its group's heading
