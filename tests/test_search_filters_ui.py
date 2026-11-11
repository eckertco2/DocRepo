"""Release 5.121 (decisions 447 to 454): Search everything with File search's filters, in the browse window. Driven offscreen
over the sample data; ``test_search.py`` has what the filters read and keep, without Qt."""
from __future__ import annotations

import html
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import search  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE, KEY_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    ctx = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW)
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    w.resize(1440, 900)
    yield w
    capture.deleteLater()
    w.deleteLater()


def run(browse, text: str) -> None:
    browse.search_box.setText(text)
    browse._run_search()


def lines(browse) -> list[str]:
    """The rows that aren't results: the hints, the group headings and the notes."""
    t = browse.tree
    return [html.unescape(t.topLevelItem(i).data(0, HTML_ROLE) or "") for i in range(t.topLevelItemCount()) if t.topLevelItem(i).data(0, KEY_ROLE) is None]


def keys(browse) -> list:
    t = browse.tree
    return [t.topLevelItem(i).data(0, KEY_ROLE) for i in range(t.topLevelItemCount()) if t.topLevelItem(i).data(0, KEY_ROLE)]


def test_the_heading_names_the_filters(browse):
    """Decision 453: "Search PDF files in Reactor impeller upgrade: datasheet", with the count after it."""
    title = browse.model().task("T000001").title
    run(browse, f"type:pdf #{title} datasheet")
    assert browse.view == "search"
    assert browse.pane_title.text().startswith(f"Search PDF files in {title}: datasheet")
    assert ("doc", "D000001") in keys(browse)  # the PDF, and its saved copy, whose row opens its task
    assert all(k == ("doc", "D000001") or k == ("task", "T000001") for k in keys(browse))
    run(browse, "from:zzzqqq")
    assert any("No email's sender has “zzzqqq” in it." in x for x in lines(browse))


def test_a_hint_while_a_filter_is_typed(browse):
    """Decision 452: what a filter takes, on a line above the results; one that names nothing lists nothing."""
    run(browse, "crane type:ex")
    assert "type:ex isn't a kind yet." in lines(browse)[0]
    assert keys(browse)  # the words alone are searched meanwhile
    run(browse, "type:xyz crane")
    assert "type:xyz" in lines(browse)[0] and not keys(browse)


def test_the_old_words_say_they_went(browse):
    """Decision 454: "search excel files …" is words now, and a search that starts so and finds nothing says so."""
    run(browse, "search excel files pump")
    assert not keys(browse) and any("went in release 5.121" in x for x in lines(browse))
    assert search.OLD_WAY.startswith("“search excel files …”")
