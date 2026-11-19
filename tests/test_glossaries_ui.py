"""Glossaries in the browse tool (release 5.171, the design workspace's glossaries plan, decisions 804 to 806), driven
offscreen over the sample data with a made-up equipment list: the view beside Tagged labels, Import… through the form
with every column kept and the tag column guessed, Add these to the tag list too, a glossary's page with Find in rows,
Import again's preview, Rename and Remove, and the pages they write."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import glossaries  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.pages import CONTENTS_FILE, GLOSSARY_DIR  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.glossary_import_dialog import GlossaryImportDialog  # noqa: E402
from docrepo.ui.lists import glossaries as glossary_list  # noqa: E402
from docrepo.views import VIEW_IDS  # noqa: E402

NOW = datetime(2026, 11, 18, 21, 30)
SHEET = ("Line,Tag No.,Description,Service,Area\n"
         "Line 2,P-204A,Reactor feed pump A,Feed,North\n"
         "Line 2,P-204B,Reactor feed pump B,Feed,North\n"
         "Line 1,V-110,Knock-out drum,,South\n")


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


def import_through_the_form(w, path, to_tags: bool = False):
    seen: dict[str, str] = {}

    def run(dialog):
        assert isinstance(dialog, GlossaryImportDialog)
        dialog.load(path)
        seen["name"] = dialog.name.text()
        seen["tag"] = dialog.tag.currentText()
        seen["preview"] = dialog.preview.toPlainText()
        if to_tags:
            dialog.to_tags.setChecked(True)
            seen["description"] = dialog.description.currentText()
            seen["tags"] = dialog.preview.toPlainText()
        assert dialog.import_button.isEnabled()
        dialog.import_now()
        return True
    w.run_dialog = run
    return seen


def test_the_view_is_beside_tagged_labels_and_starts_empty(browse):
    assert VIEW_IDS["glossaries"].section == "Manage"
    ids = [v.id for v in __import__("docrepo.views", fromlist=["VIEWS"]).VIEWS]
    assert ids.index("glossaries") == ids.index("tagged") + 1
    browse.set_view("glossaries")
    QApplication.processEvents()
    assert browse.view == "glossaries" and glossary_list.first(browse) is None
    assert browse.glossary_box.placeholderText().startswith("Find in rows")


def test_import_keeps_every_column_and_writes_its_page(browse, ctx, tmp_path):
    path = tmp_path / "Equipment.csv"
    path.write_text(SHEET, encoding="utf-8")
    seen = import_through_the_form(browse, path)
    browse.set_view("glossaries")
    glossary_list.import_new(browse)
    assert seen["name"] == "Equipment" and seen["tag"] == "Tag No."
    assert "3 rows in 5 columns, the tags in Tag No." in seen["preview"]
    g = glossaries.all_glossaries(ctx.conn)[0]
    assert g.columns == ("Line", "Tag No.", "Description", "Service", "Area") and g.rows == 3
    assert browse.sel == ("glossary", str(g.id))
    html = browse.page.toPlainText()
    assert "Equipment" in html and "Reactor feed pump A" in html and "Knock-out drum" in html
    page = ctx.data_root.joinpath(*GLOSSARY_DIR, "Equipment.md").read_text(encoding="utf-8")
    assert "| Line 2 | P-204A | Reactor feed pump A | Feed | North |" in page
    assert "[Equipment](Views/Glossaries/Equipment.md) (3 rows)" in (ctx.data_root / CONTENTS_FILE).read_text(encoding="utf-8")


def test_find_in_rows_narrows_the_picked_glossary(browse, tmp_path):
    path = tmp_path / "Equipment.csv"
    path.write_text(SHEET, encoding="utf-8")
    import_through_the_form(browse, path)
    glossary_list.import_new(browse)
    glossary_list.set_find(browse, "pump b")
    text = browse.page.toPlainText()
    assert "Reactor feed pump B" in text and "Reactor feed pump A" not in text and "1 row with" in text
    glossary_list.set_find(browse, "")
    assert "Reactor feed pump A" in browse.page.toPlainText()


def test_add_these_to_the_tag_list_too(browse, ctx, tmp_path):
    path = tmp_path / "Equipment.csv"
    path.write_text(SHEET, encoding="utf-8")
    seen = import_through_the_form(browse, path, to_tags=True)
    glossary_list.import_new(browse)
    assert seen["description"] == "Description" and "The tag list" in seen["tags"] and "3 to add" in seen["tags"]
    m = browse.model()
    assert m.tagged.by_key["V110"].description == "Knock-out drum"
    html = browse.pages().tagged_page("P204A")
    assert "In Equipment" in html and "North" in html


def test_import_again_rename_and_remove(browse, ctx, tmp_path):
    path = tmp_path / "Equipment.csv"
    path.write_text(SHEET, encoding="utf-8")
    import_through_the_form(browse, path)
    glossary_list.import_new(browse)
    gid = glossaries.all_glossaries(ctx.conn)[0].id
    again = tmp_path / "Equipment 2.csv"
    again.write_text(SHEET.replace("Knock-out drum", "Knock-out drum relined") + "Line 3,K-401,Air compressor,Utility,East\n", encoding="utf-8")
    seen = import_through_the_form(browse, again)
    glossary_list.import_again(browse, gid)
    assert seen["name"] == "Equipment" and "1 added · 0 gone · 1 changed · 2 as they were" in seen["preview"]
    assert glossaries.get(ctx.conn, gid).rows == 4
    browse.ask_text = lambda title, label, text: "Rotating equipment"
    glossary_list.rename(browse, gid)
    assert glossaries.get(ctx.conn, gid).name == "Rotating equipment"
    folder = ctx.data_root.joinpath(*GLOSSARY_DIR)
    assert "K-401" in (folder / "Rotating equipment.md").read_text(encoding="utf-8")
    assert "renamed Rotating equipment" in (folder / "Equipment.md").read_text(encoding="utf-8")
    asked: list[str] = []
    browse.confirm = lambda title, text: asked.append(text) or True
    glossary_list.remove(browse, gid)
    assert "its 4 rows" in asked[0]
    assert glossaries.get(ctx.conn, gid) is None
    assert "removed this glossary" in (folder / "Rotating equipment.md").read_text(encoding="utf-8")
    assert "Glossaries:" not in (ctx.data_root / CONTENTS_FILE).read_text(encoding="utf-8")


def test_a_failed_import_leaves_nothing(browse, ctx, tmp_path):
    path = tmp_path / "Empty.csv"
    path.write_text("Tag,Description\n", encoding="utf-8")
    dialog = GlossaryImportDialog(browse, ctx)
    dialog.load(path)
    assert not dialog.import_button.isEnabled() and "no rows" in dialog.error.text()
    dialog.import_now()
    assert glossaries.all_glossaries(ctx.conn) == [] and dialog.outcome == ""
    dialog.deleteLater()
