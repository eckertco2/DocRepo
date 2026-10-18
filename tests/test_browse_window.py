"""The browse tool, driven offscreen (no window appears) over the sample data, with the real capture window."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import captures, prompts  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import KEY_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    changed: list[list[str]] = []
    context = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW, settings_changed=changed.append)
    context.changed = changed  # type: ignore[attr-defined]
    return context


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.revealed = []
    w.reveal = lambda path: w.revealed.append(path) or True
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    capture.deleteLater()
    w.deleteLater()


def rows(w) -> list:
    return w.tree.keys()


def test_it_opens_on_the_task_tree(browse):
    assert browse.view == "tasks" and browse.sel == ("task", "T000001")
    assert ("task", "T000001") in rows(browse) and ("task", "T000010") in rows(browse)
    nav = {k[1]: browse.nav.items() for k in browse.nav.keys() if k}
    assert "unfiled" in nav and "settings" in nav
    assert "Reactor impeller upgrade" in browse.page.toPlainText()


def test_each_view_selects_its_first_item(browse):
    expected = {"unfiled": ("capture", "C000023"), "due": ("task", "T000019"), "reminders": ("task", "T000016"), "people": ("person", "P001"),
                "labels": ("label", "Line 1"), "docs": ("doc", "D000001"), "agenda": ("task", "T000010")}
    for view, sel in expected.items():
        browse.set_view(view)
        assert browse.sel == sel, view
        if view != "agenda":  # the agenda's own meeting isn't one of its rows
            assert browse.tree.currentItem().data(0, KEY_ROLE) == sel
    browse.set_view("capacity")
    assert not browse.detail.isVisible() and browse.cap_table.rowCount() == 6
    browse.set_view("settings")
    assert browse.middle.currentIndex() == 2 and browse.settings_view.hotkey.text() == "Ctrl+Shift+Space"


def test_opening_a_hidden_task_turns_its_filter_on(browse):
    assert ("task", "T000005") not in rows(browse)  # closed
    browse.go_task("T000005")
    assert browse.tree_filter["closed"] and ("task", "T000005") in rows(browse) and browse.sel == ("task", "T000005")
    browse.go_task("T000004")
    assert browse.tree_filter["parked"]


def test_links_change_the_tab_scope_and_chapters(browse):
    browse.go_task("T000008")
    browse.on_link(QUrl("tab:log"))
    browse.on_link(QUrl("scope:family"))
    browse.on_link(QUrl("chap:T000012"))
    assert (browse.state.tab, browse.state.scope, browse.state.chapters) == ("log", "family", {"T000012"})
    assert "Work started" in browse.page.toPlainText()
    browse.go_task("T000009")  # another task: the scope goes back to With subtasks, the chapters close, the tab stays
    assert (browse.state.tab, browse.state.scope, browse.state.chapters) == ("log", "descendants", set())
    browse.on_link(QUrl("person:P003"))
    assert browse.sel == ("person", "P003")
    browse.on_link(QUrl("label:Line%201"))
    assert browse.sel == ("label", "Line 1")


def test_a_n_and_u_open_the_capture_window_on_the_selected_task(browse):
    browse.go_task("T000008")
    for mode in ("note", "new_task", "update"):
        browse.page.setFocus()
        browse._key(mode)
        assert browse.capture.isVisible() and browse.capture.task == "T000008" and browse.capture.types == {mode}
        browse.capture.hide()
    browse.set_view("people")
    browse.capture_for_selected("update")
    assert "Select a task first" in browse.status.text()


def test_a_saved_capture_shows_in_the_browse_tool(browse):
    browse.go_task("T000008")
    browse.capture_for_selected("new_task")
    browse.capture.title.setText("Order shims for the alignment")
    browse.capture.save()
    new = Model(browse.conn).tasks["T000020"]
    assert new.title == "Order shims for the alignment"
    assert browse.sel == ("task", "T000020") and browse.pin == "T000020" and browse.state.tab == "notes"
    assert ("task", "T000020") in rows(browse) and "Created T000020" in browse.status.text()


def test_filing_an_unfiled_capture(browse):
    browse.set_view("unfiled")
    browse.select("capture", "C000022")
    labels = [b.text() for b in browse.actions.findChildren(QPushButton)]
    assert "File to task" in labels and "Make it a task" in labels
    browse._set_file_to("C000022", "T000018")
    browse.file_capture("C000022")
    assert Model(browse.conn).captures["C000022"].filed_to == "T000018"
    assert ("capture", "C000022") not in rows(browse) and browse.sel == ("capture", "C000022")
    assert browse.status.text() == "Filed C000022 to Update area 3 guard drawings."


def test_make_it_a_task(browse):
    browse.set_view("unfiled")
    browse.select("capture", "C000022")
    browse.open_capture(from_capture="C000022")
    cw = browse.capture
    assert cw.from_capture == "C000022" and cw.types == {"new_task"} and "files C000022 to it" in cw.does.text()
    cw.save()
    m = Model(browse.conn)
    assert m.captures["C000022"].filed_to == "T000020" and m.task("T000020").created_by == "C000022"
    assert browse.sel == ("task", "T000020")


def test_fixing_a_capture(browse, ctx):
    browse.go_capture("C000017")
    browse.start_capture_edit("C000017")
    assert browse.detail_stack.currentIndex() == 1
    browse.edit_content.setPlainText("Vendor drawings came in late. Now due 23 Oct.")
    browse.save_capture_edit()
    assert browse.detail_stack.currentIndex() == 0 and "previous version" in browse.status.text()
    c = Model(browse.conn).captures["C000017"]
    assert captures.read_content(ctx.data_root, c) == "Vendor drawings came in late. Now due 23 Oct."
    assert "1 earlier version kept" in browse.page.toPlainText()


def test_clearing_a_reminder_from_the_list(browse):
    browse.set_view("reminders")
    item = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == ("task", "T000018"))
    button = browse.tree.itemWidget(item, 3)
    assert button.text() == "Clear"
    button.click()
    assert Model(browse.conn).task("T000018").reminder is None
    assert ("task", "T000018") not in rows(browse)


def test_discussed_closes_the_item_and_opens_an_update(browse):
    browse.set_view("agenda")
    item = next(a for a in Model(browse.conn).open_items_for("T000010") if a.subject == "T000001")
    browse.close_agenda_item(item.id, "Discussed")
    cw = browse.capture
    assert cw.isVisible() and cw.task == "T000001" and cw.types == {"update"}
    assert cw.content.toPlainText() == "Discussed at Business team meeting: "
    assert ("task", "T000001") not in [k for k in rows(browse)[:4]]
    assert Model(browse.conn).status_log_of("T000001")[-1].to_value == "Discussed"


def test_copy_as_markdown_and_copy_prompt(browse):
    browse.copy_agenda("T000010")
    assert QGuiApplication.clipboard().text().startswith("## Business team meeting, Tue 13 Oct")
    browse.go_task("T000009")
    browse.summary_type.setCurrentText("General summary")
    browse.copy_prompt("T000009")
    text = QGuiApplication.clipboard().text()
    assert text.startswith(prompts.PREAMBLE) and "Vendor drawings came in late, so the package is now due Oct 23." in text
    assert browse.status.text().startswith("Prompt copied (")


def test_search(browse):
    browse.search_box.setText("crane booking")
    browse._run_search()
    assert browse.view == "search" and rows(browse) == [None, ("capture", "C000013")]
    browse.search_box.clear()
    browse._run_search()
    assert browse.view == "tasks"


def test_show_in_file_explorer(browse, ctx):
    browse.reveal_key(("task", "T000008"))
    browse.go_task("T000001")
    copy = next(f for f in Model(browse.conn).copies if f.task == "T000001")
    browse.on_link(QUrl(f"show:copy:{copy.id}"))
    assert browse.revealed == [ctx.data_root / "Tasks" / "T000008", ctx.data_root / "Tasks" / "T000001" / "Files" / copy.name]


def test_people_and_labels(browse, ctx):
    browse.set_view("people")
    browse.save_person(None, "Dana Kim", ["Dana", "DK"], 36)
    dana = next(p for p in Model(browse.conn).people.values() if p.name == "Dana Kim")
    assert browse.sel == ("person", dana.id) and dana.aliases == ["Dana", "DK"] and dana.hours == 36
    browse.set_person_status(dana.id, "retired")
    assert ("person", dana.id) not in rows(browse)
    browse.set_person_status("P001", "retired")
    assert "can't retire yourself" in browse.status.text()
    browse.set_view("labels")
    browse.save_label("Safety", "Site safety", ["safety", "guard"])
    m = Model(browse.conn)
    assert any(name == "Site safety" for name, _ in m.labels_of("T000002")) and browse.sel == ("label", "Site safety")
    assert "Site safety" in (ctx.data_root / "Tasks" / "T000002" / "Task.md").read_text(encoding="utf-8")


def test_task_edits(browse):
    browse.go_task("T000012")
    browse.save_task_text("T000012", "Rigging plan for the lift", "Mike writes the rigging plan.")
    browse.save_task_labels("T000012", ["Safety", "Lifting"], ["Lifting"], False)
    browse.move_task("T000012", "T000008", "T000001")
    m = Model(browse.conn)
    t = m.task("T000012")
    assert (t.title, t.description, t.labels, t.inherit_labels) == ("Rigging plan for the lift", "Mike writes the rigging plan.",
                                                                    ["Safety", "Lifting"], False)
    assert m.parents_of("T000012") == ["T000001"] and any(lb.name == "Lifting" for lb in m.labels)
    browse.move_task("T000001", None, "T000012")
    assert "under itself" in browse.status.text()


def test_settings(browse, ctx):
    browse.set_view("settings")
    view = browse.settings_view
    rows_before = browse.conn.execute("SELECT count(*) FROM work_calendar").fetchone()[0]
    view.hotkey.setText("Ctrl+Alt+K")
    view.workdays["Fri"].setChecked(False)
    assert view.save() == ["hotkey", "workdays"]
    saved = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert saved["hotkey"] == "Ctrl+Alt+K" and saved["workdays"] == ["Mon", "Tue", "Wed", "Thu"]
    assert ctx.changed == [["hotkey", "workdays"]]
    assert browse.conn.execute("SELECT count(*) FROM work_calendar").fetchone()[0] != rows_before
    view.hotkey.setText("K")
    assert view.save() == [] and view.error.isVisibleTo(view) and "can't be used" in view.error.text()
    view.load()
    view.backup.setText(str(ctx.data_root / "Backups"))
    assert view.save() == [] and "inside the data root" in view.error.text()


def test_setting_up_another_data_root(tmp_path, monkeypatch):
    from docrepo.config import read_location
    from docrepo.ui import settings_view

    monkeypatch.setattr("docrepo.config.CODE_DIR", tmp_path / "code")  # pytest's folder is inside the code folder
    target = tmp_path / "NewData"
    message = settings_view.set_up_data_root(target)
    assert "from its next start" in message and read_location() == target
    assert (target / "System" / "docs.db").exists() and (target / "Config" / "settings.json").exists()
    with pytest.raises(settings_view.SettingsProblem):
        settings_view.set_up_data_root(tmp_path.relative_to(tmp_path.anchor))


def test_the_window_only_hides_when_closed(browse):
    browse.close()
    assert not browse.isVisible()
    browse.show_browse("reminders", "T000018")
    assert browse.isVisible() and browse.view == "reminders" and browse.sel == ("task", "T000018")


def test_the_windows_stay_light_in_dark_mode(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    from docrepo.ui.style import use_light_theme

    use_light_theme(qapp)
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Base).name() == "#ffffff" and palette.color(QPalette.ColorRole.Text).name() == "#1a1f25"
    # The offscreen platform has no colour schemes (Unknown); on Windows this is Light, never Dark.
    assert qapp.styleHints().colorScheme() != Qt.ColorScheme.Dark
