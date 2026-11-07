"""Tag patterns in the browse tool (release 5.80): Settings' Tagged labels section with the tester and Try on everything,
the Suggested list, and Add to glossary, Same as… and Not a tag, driven offscreen over the sample data with made-up tags."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402
from html import escape as esc  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import tagged  # noqa: E402
from docrepo import tagged_masks as tm  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import CaptureDraft, save_capture  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.lists import tagged as tagged_list  # noqa: E402
from docrepo.ui.settings_view import SettingsProblem, SettingsView, check_tagged, update_settings  # noqa: E402
from docrepo.ui.tree_view import HTML_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)
INSTRUMENT = {"name": "Instrument tag", "mask": "XX[X][X]-####", "space": False}


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


def save(ctx, text, task=None):
    save_capture(ctx.conn, ctx.data_root, ctx.fs, Settings(me="P001"), CaptureDraft(content=text, task=task), NOW)
    return max(Model(ctx.conn).captures)


def with_patterns(ctx, patterns=(INSTRUMENT,), never=()):
    ctx.settings.tagged_patterns, ctx.settings.tagged_never = list(patterns), list(never)
    ctx.settings.save(ctx.fs, ctx.data_root)
    tagged.use_settings(ctx.conn, ctx.settings)


# ---- Settings' Tagged labels section (decisions 372, 373 and 375) ----
def test_the_section_says_what_each_mask_means_and_marks_the_tester_as_typed(ctx):
    tagged.add_label(ctx.conn, "FIC-2210", NOW, "Feed flow controller", ["feed loop"])
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    s = view.tagged
    assert s.rows == [] and not s.none.isHidden()  # DocRepo ships no patterns
    s.example_buttons[2].click()  # XX[X][X]-####, made up
    s.rows[0][0].setText("Instrument tag")
    assert s.rows[0][3].text() == "Such as FT-2041 to FTIC-2041"
    s.add_row("Bad", "XX[X", False)
    assert s.rows[1][3].text() == "A [ isn't closed."
    s.never_box.setText("API*")
    s.try_box.setPlainText("FIC2210 holds; the feed loop; TIC-2216 is new; API-6100 is a standard.")
    s.refresh_now()
    html = s.marked.toHtml()
    assert "FIC2210" in html and "line-through" in html
    assert s.found.text().startswith("Found: FIC-2210, TIC-2216") and "(new, Instrument tag)" in s.found.text()
    assert s.draft() == ([tm.Pattern("Instrument tag", "XX[X][X]-####")], ["API*"])  # the bad mask isn't tried
    s.rows[0][4].click()  # × on the first, then one more: each row keeps a grid row of its own
    s.add_row("Equipment tag", "X[X]-###[X]", False)
    places = [s.grid.getItemPosition(s.grid.indexOf(r[1]))[0] for r in s.rows]
    assert [r[0].text() for r in s.rows] == ["Bad", "Equipment tag"] and len(set(places)) == 2
    view.deleteLater()


def test_try_on_everything_lists_new_labels_and_not_a_tag_fills_never(ctx):
    save(ctx, "API-6100 and TT-2215; API-6100 again.")
    save(ctx, "API-6100 and ABC-1234.")
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    s = view.tagged
    s.add_row("Instrument tag", "XX[X][X]-####", False)
    s.try_everything()
    text = s.tried.toPlainText()
    assert text.startswith("3 new, in 2 items: API-6100 (2), ABC-1234 (1), TT-2215 (1)") and "Not a tag" in text
    assert tagged.read_labels(ctx.conn) == []  # nothing changed
    s._tried_link(QUrl("never:API-6100"))
    assert s.never() == ["API-6100"] and s.tried.toPlainText().startswith("2 new, in 2 items")
    s.rows[0][1].setText("XXX-####")
    assert "The patterns changed" in s.tried.toPlainText()
    view.deleteLater()


def test_save_settings_keeps_the_patterns_and_matches_everything_again(ctx):
    cid = save(ctx, "TIC-2216 reads high.")
    said = []
    view = SettingsView(ctx, said.append, lambda title, text: True)
    view.load()
    view.tagged.add_row("Instrument tag", "XX[X][X]-####", False)
    view.tagged.never_box.setText("api*, ABC123")
    assert set(view.save()) == {"tagged_patterns", "tagged_never"}
    on_disk = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["tagged_patterns"] == [INSTRUMENT] and on_disk["tagged_never"] == ["API*", "ABC123"]
    assert tagged.patterns_state(ctx.conn) == ([tm.Pattern("Instrument tag", "XX[X][X]-####")], ["API*", "ABC123"])
    assert [lb.label for lb, _ in Model(ctx.conn).tagged.item("capture", cid)] == ["TIC-2216"]
    assert "1 new tagged label is on what mentions it, marked new, under Suggested" in said[-1]
    view.deleteLater()


def test_a_mask_or_entry_that_cant_be_used_is_said_and_nothing_is_saved(ctx):
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    view.tagged.add_row("Instrument tag", "XX-##(#)", False)
    assert view.save() == [] and "Instrument tag's mask can't be used" in view.error.text()
    with pytest.raises(SettingsProblem, match="its own name"):
        check_tagged([INSTRUMENT, {**INSTRUMENT, "mask": "XXX-####"}], [])
    with pytest.raises(SettingsProblem, match="Never a tag: .* goes only at the end"):
        check_tagged([], ["A*B"])
    assert check_tagged([{"name": "", "mask": "X-###"}, {"name": "", "mask": ""}], [" api* "]) == {
        "tagged_patterns": [{"name": "X-###", "mask": "X-###", "space": False}], "tagged_never": ["API*"]}
    assert Settings.load(ctx.data_root).tagged_patterns == []
    assert update_settings(ctx, {**view.values(), "tagged_patterns": []}) == []  # unchanged
    view.deleteLater()


# ---- the Tagged labels view's Suggested list and a suggestion's page (decisions 374 and 375) ----
def test_suggested_comes_first_most_mentioned_with_where_its_seen(browse, ctx):
    tagged.add_label(ctx.conn, "V-110", NOW, "Feed surge drum")
    with_patterns(ctx)
    save(ctx, "PDT-4410 reads high, TT-2215 too.", task="T000008")
    save(ctx, "PDT-4410 again.")
    browse.refresh()
    browse.set_view("tagged")
    keys = [k for k in browse.tree.keys() if k]
    assert keys == [("tagged", "PDT4410"), ("tagged", "TT2215"), ("tagged", "V110")] and browse.sel == ("tagged", "PDT4410")
    texts = [str(browse.tree.topLevelItem(i).data(0, HTML_ROLE)) for i in range(browse.tree.topLevelItemCount())]
    assert "Suggested" in texts[0] and "Glossary" in texts[3]
    m = Model(ctx.conn)
    top = m.task(m.chains_of("T000008")[0][0]).title
    assert "From Instrument tag" in texts[1] and f"in {esc(top)} and 1 more" in texts[1]  # its task, and the unfiled capture
    page = browse.page.toPlainText()
    assert "Tagged label · suggested" in page and "New: found by the Instrument tag pattern" in page
    layout = browse.actions_layout
    labels = [layout.itemAt(i).widget().text() for i in range(layout.count()) if layout.itemAt(i).widget()]
    assert {"Add to glossary…", "Same as…", "Not a tag"} <= set(labels) and "Edit…" not in labels


def test_add_to_glossary_through_its_dialog(browse, ctx):
    from docrepo.ui.dialogs import TaggedLabelDialog

    with_patterns(ctx)
    save(ctx, "PDT-4410 reads high.")
    browse.refresh()

    def run(dialog):
        assert isinstance(dialog, TaggedLabelDialog) and dialog.windowTitle() == "Add PDT-4410 to the glossary"
        dialog.description.setText("Filter differential pressure")
        return True
    browse.run_dialog = run
    browse.set_view("tagged")
    tagged_list.accept(browse, "PDT4410")
    lb = browse.model().tagged.by_key["PDT4410"]
    assert lb.status == "glossary" and lb.description == "Filter differential pressure"
    assert "is in the glossary now" in browse.status.text() and browse.sel == ("tagged", "PDT4410")
    assert "Found by the Instrument tag pattern, then added to the glossary" in browse.page.toPlainText()


def test_same_as_moves_its_mentions_to_another_label(browse, ctx, monkeypatch):
    tagged.add_label(ctx.conn, "PDT-4410", NOW, "Filter dP")
    with_patterns(ctx, [{"name": "Two letters", "mask": "XX-####", "space": False}])
    cid = save(ctx, "DP-4410 is the old name.")
    browse.refresh()
    monkeypatch.setattr(tagged_list, "choose_label", lambda w, names, label: "pdt 4410")
    browse.set_view("tagged")
    tagged_list.same_as(browse, "DP4410")
    tg = browse.model().tagged
    assert "DP4410" not in tg.by_key and tg.by_key["PDT4410"].aliases == ("DP-4410",)
    assert [lb.label for lb, _ in tg.item("capture", cid)] == ["PDT-4410"] and browse.sel == ("tagged", "PDT4410")


def test_not_a_tag_removes_it_everywhere_with_undo(browse, ctx):
    with_patterns(ctx)
    cid = save(ctx, "ABC-1234 is a part number.")
    browse.refresh()
    browse.set_view("tagged")
    tagged_list.not_a_tag(browse, "ABC1234")
    assert "ABC1234" not in browse.model().tagged.by_key and Settings.load(ctx.data_root).tagged_never == ["ABC-1234"]
    assert "is on Never a tag" in browse.status.text() and browse._undo is not None
    browse._undo()
    assert Settings.load(ctx.data_root).tagged_never == [] and "ABC1234" in browse.model().tagged.by_key
    assert [lb.label for lb, _ in browse.model().tagged.item("capture", cid)] == ["ABC-1234"]


def test_a_captures_chip_is_marked_new_and_patterns_opens_settings(browse, ctx):
    with_patterns(ctx)
    cid = save(ctx, "PDT-4410 reads high.")
    browse.refresh()
    browse.on_link(QUrl(f"capture:{cid}"))
    page = browse.page.toHtml()
    assert "PDT-4410" in page and "new" in browse.page.toPlainText()
    tagged_list.show_patterns(browse)
    assert browse.view == "settings" and browse.middle.currentWidget() is browse.settings_view
    assert [r[1].text() for r in browse.settings_view.tagged.rows] == ["XX[X][X]-####"]
