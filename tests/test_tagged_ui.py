"""Tagged labels in the browse tool and the Task view (release 5.79), driven offscreen over the sample data, with made-up tags."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import finder, tagged  # noqa: E402
from docrepo import tagged_import as ti  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.lists import tagged as tagged_list  # noqa: E402
from docrepo.ui.tagged_import_dialog import TaggedImportDialog  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
TAGS = "Tag No.,Service,Other names\nR-101,Reactor 1,reactor one\nV-110,Feed surge drum,feed drum\nP-204A,Charge pump A,\n"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    return AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW, settings_changed=lambda _: None)


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def import_through_the_form(w, tmp_path, text=TAGS):
    path = tmp_path / "tags.csv"
    path.write_text(text, encoding="utf-8")

    def run(dialog):
        if isinstance(dialog, TaggedImportDialog):
            dialog.load(path)
            assert dialog.fields() == ["label", "description", "aliases"]
            assert "3 to add" in dialog.preview.toPlainText() and dialog.import_button.isEnabled()
            dialog.import_now()
            return True
        return False
    w.run_dialog = run
    tagged_list.import_glossary(w)


def test_the_view_starts_empty_and_import_fills_it(browse, tmp_path, ctx):
    browse.set_view("tagged")
    assert [k for k in browse.tree.keys() if k] == [] and browse.sel is None
    import_through_the_form(browse, tmp_path)
    assert browse.view == "tagged" and browse.tree.keys() == [("tagged", "P204A"), ("tagged", "R101"), ("tagged", "V110")]
    assert browse.sel == ("tagged", "P204A") and "Imported tags.csv: 3 added" in browse.status.text()
    browse.select("tagged", "R101")
    page = browse.page.toPlainText()
    assert "Reactor 1" in page and "D000002" in page and "R-101" in page
    # Task.md has the row now, for the task that holds the document.
    holder = browse.model().document_holders("D000002")[0]
    assert "| Tagged labels | R-101 (1) |" in (ctx.data_root / "Tasks" / holder / "Task.md").read_text(encoding="utf-8")


def test_a_documents_chip_removes_and_puts_back_with_undo(browse, tmp_path):
    import_through_the_form(browse, tmp_path)
    browse.on_link(QUrl("doc:D000002"))
    assert "R-101" in browse.page.toPlainText()
    browse.on_link(QUrl("taggedrm:document:D000002:R101"))
    assert "Removed by you: R-101" in browse.page.toPlainText() and browse._undo is not None
    browse._undo()
    assert "Removed by you" not in browse.page.toPlainText()
    browse.on_link(QUrl("taggedrm:document:D000002:R101"))
    browse.on_link(QUrl("taggedback:document:D000002:R101"))
    assert "Removed by you" not in browse.page.toPlainText()


def test_add_by_hand_from_the_glossary_or_new(browse, tmp_path):
    import_through_the_form(browse, tmp_path)
    browse.on_link(QUrl("doc:D000002"))
    browse.pick_tagged = lambda names: "v110"
    browse.on_link(QUrl("taggedadd:document:D000002"))
    assert [lb.label for lb, x in browse.model().tagged.item("document", "D000002")] == ["R-101", "V-110"]
    # One that isn't in the glossary yet is added to it first, with its own dialog.
    browse.pick_tagged = lambda names: "XV-1001"
    browse.run_dialog = lambda dialog: True
    browse.on_link(QUrl("taggedadd:document:D000002"))
    assert "XV-1001" in [lb.label for lb, _ in browse.model().tagged.item("document", "D000002")]
    assert browse.model().tagged.by_key["XV1001"].came == "hand"


def test_edit_a_label_and_a_chip_opens_its_page(browse, tmp_path):
    import_through_the_form(browse, tmp_path)
    from docrepo.ui.dialogs import TaggedLabelDialog

    def run(dialog):
        assert isinstance(dialog, TaggedLabelDialog)
        dialog.aliases.setText("feed drum; old drum")
        dialog.description.setText("Feed surge drum (vessel)")
        return True
    browse.run_dialog = run
    tagged_list.edit(browse, "V110")
    lb = browse.model().tagged.by_key["V110"]
    assert lb.aliases == ("feed drum", "old drum") and lb.description == "Feed surge drum (vessel)"
    browse.set_view("tasks")
    browse.on_link(QUrl("tagged:V110"))
    assert browse.view == "tagged" and browse.sel == ("tagged", "V110")


def test_a_bad_alias_is_said_and_saves_nothing(browse, tmp_path):
    import_through_the_form(browse, tmp_path)
    from docrepo.ui.dialogs import TaggedLabelDialog

    dialog = TaggedLabelDialog(browse, "V-110", "", ["feed drum"], check_aliases=tagged_list.alias_check(browse, browse.model().tagged.by_key["V110"].id))
    dialog.aliases.setText("R-101; 110")
    dialog.save()
    assert not dialog.result() and "R-101's already" in dialog.error.text() and "only digits" in dialog.error.text()


def test_export_saves_in_exports_and_copies(browse, tmp_path, ctx):
    import_through_the_form(browse, tmp_path)
    tagged_list.export(browse)
    (path,) = (ctx.data_root / "Exports").glob("*Tagged labels.csv")
    assert "R-101,Reactor 1,reactor one" in path.read_text(encoding="utf-8-sig")
    assert "Saved 3 tagged labels as Exports\\" in browse.status.text()
    assert QApplication.clipboard().text().startswith("Tagged label,Tagged label description,Tagged label aliases")


def test_search_lists_the_label_first(browse, tmp_path):
    import_through_the_form(browse, tmp_path)
    browse.query, browse.view = "r101", "search"
    browse.render_list()
    assert [k for k in browse.tree.keys() if k] == [("tagged", "R101"), ("doc", "D000002")]  # under their groups' headings


def test_the_task_views_tag_filter(ctx, tmp_path):
    path = tmp_path / "tags.csv"
    path.write_text(TAGS, encoding="utf-8")
    rows = ti.read_rows(path)
    ti.run_import(ctx.conn, ti.preview(ctx.conn, rows, ti.Plan(0, ti.propose(rows, 0))), "tags.csv", NOW)
    from docrepo.model import Model

    m = Model(ctx.conn)
    f = finder.Filters()
    typed = finder.take_filters("tag:r101 coupling", f, [], [], NOW.date(), tag=lambda v: getattr(tagged.label_named(m.tagged, v), "key", None))
    assert f.tagged == {"R101"} and typed.rest == "coupling"
    assert finder.take_filters("tag:nothing9 x", finder.Filters(), [], [], NOW.date(), tag=lambda v: None).rest == "tag:nothing9 x"
    assert finder.HINTS["tag"].startswith("Type a tagged label")


def test_a_big_glossary_lists_what_is_mentioned_and_says_how_many_more(browse, tmp_path, monkeypatch):
    monkeypatch.setattr(tagged_list, "ROWS", 2)
    import_through_the_form(browse, tmp_path)
    assert browse.tagged_mentioned is True  # three labels, more than the view draws: Mentioned only starts ticked
    assert [k for k in browse.tree.keys() if k] == [("tagged", "R101")]  # the only one something mentions
    tagged_list.set_mentioned(browse, False)
    assert [k for k in browse.tree.keys() if k] == [("tagged", "P204A"), ("tagged", "R101")]
    from docrepo.ui.tree_view import HTML_ROLE

    texts = [str(browse.tree.topLevelItem(i).data(0, HTML_ROLE)) for i in range(browse.tree.topLevelItemCount())]
    assert any("And 1 more. Search finds any of them" in t for t in texts)
