"""One form design (release 5.193, the redesign's decision 868): grey labels 4 px over their fields, a footer with a hairline
and the primary at its right end, Quick edit at one height, explanations in tooltips, and a toggle where a setting applies at
once. Driven offscreen."""
from __future__ import annotations

import os
import types
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit, QPushButton, QToolButton  # noqa: E402

from docrepo import outlook, templates  # noqa: E402
from docrepo.bulk import LabelMatch  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.templates import Library  # noqa: E402
from docrepo.ui import progress_form  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.dialogs import LabelDialog, PersonDialog  # noqa: E402
from docrepo.ui.import_dialog import ImportDialog  # noqa: E402
from docrepo.ui.log_progress import LogProgress  # noqa: E402
from docrepo.ui.look import LOOK, set_hints  # noqa: E402
from docrepo.ui.people_import import PeopleImportDialog  # noqa: E402
from docrepo.ui.quick_edit import QuickEdit  # noqa: E402
from docrepo.ui.settings_view import first_sentence  # noqa: E402
from docrepo.ui.task_forms import BulkEditDialog, LabelMatchDialog, TaskEditDialog  # noqa: E402
from docrepo.ui.templates_view import RowDialog  # noqa: E402
from docrepo.ui.timing_view import TimingDialog  # noqa: E402
from docrepo.ui.tree_import import TextWindow  # noqa: E402
from docrepo.ui.widgets import Toggle, field  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, sample_root):
    conn, root, fs = sample_root
    w = BrowseWindow(AppContext(conn, root, fs, Settings(me="P001"), now=lambda: NOW))
    w.confirm = lambda title, text: True
    w.show_browse()
    yield w
    QApplication.processEvents()
    w.deleteLater()


def forms(browse) -> list:
    """Edit task, Edit selected, Person, Label, a template's row and Timing: every form built through ``dialog_buttons``."""
    m = browse.model()
    top = templates.new_template(browse.conn, "Product trial", NOW, {"leads": ["P001"]})
    templates.add_row(browse.conn, browse.ctx.settings, top, {"title": "Plan the trial", "inherit_labels": True}, NOW)
    return [TaskEditDialog(browse, m, "T000012", browse._label_options, browse._people_options),
            BulkEditDialog(browse, m, ["T000012"], browse._label_options, browse._people_options, lambda e: [], lambda anchor, picked: None),
            PersonDialog(browse, "Dana Kim"), LabelDialog(browse, "Safety", ["safety"]),
            RowDialog(browse, m, None, browse._label_options, browse._people_options, "Add a subtask"),
            TimingDialog(browse, Library(browse.conn), top, browse._workdays())]


def buttons_of(row) -> list:
    return [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget() is not None]


# ---- the footer ----
def test_the_primary_is_last_in_a_forms_footer(browse):
    for d in forms(browse):
        row = buttons_of(d.footer_row)
        assert row[-1] is d.commit_button and row[-2] is d.cancel_button, d.windowTitle()
        assert d.commit_button.isDefault() and d.commit_button.objectName() == "primary"
        assert d.commit_button.minimumWidth() >= 96 and d.cancel_button.minimumWidth() >= 88
        d.deleteLater()


def test_tab_goes_to_the_primary_then_cancel(browse):
    for d in forms(browse):
        d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        d.show()
        QApplication.processEvents()
        assert d.commit_button.nextInFocusChain() is d.cancel_button, d.windowTitle()
        d.hide()
        d.deleteLater()


def test_a_field_is_four_under_its_label(qapp):
    box = field("Title", QLineEdit())
    assert box.layout().spacing() == 4 and box.property("label").objectName() == "fieldLabel"


def test_every_hand_built_footer_ends_in_its_primary(browse):
    """Import, People import, the label's matches and the tree file's window: the footer's last button is the primary, made
    first, so Tab reaches it before Close or Cancel."""
    found = LabelMatch("T000012", ())
    windows = [ImportDialog(browse, browse.ctx), PeopleImportDialog(browse, browse.ctx),
               LabelMatchDialog(browse, browse.model(), "Safety", [found], lambda ids: None),
               TextWindow(browse, "Export: a tree", "A note.", "text", [("Copy", "text", "Copied."), ("Copy edit prompt", "prompt", "Copied.")])]
    for w in windows:
        rows = [lay for lay in w.findChildren(QPushButton) if lay.objectName() == "primary"]
        assert rows, type(w).__name__
        primary = rows[-1]
        row = primary.parentWidget().layout()
        # the primary's row: find the layout that holds it
        holder = next(x for x in _layouts(row) if any(x.itemAt(i).widget() is primary for i in range(x.count())))
        last = [holder.itemAt(i).widget() for i in range(holder.count()) if holder.itemAt(i).widget() is not None][-1]
        assert last is primary, type(w).__name__
        w.deleteLater()


def _layouts(layout):
    yield layout
    for i in range(layout.count()):
        child = layout.itemAt(i).layout()
        if child is not None:
            yield from _layouts(child)


# ---- the toggle ----
def test_a_toggle_flips_by_click_and_by_space(qapp):
    t = Toggle("Show hints")
    t.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    t.show()
    flips: list[bool] = []
    t.toggled.connect(flips.append)
    assert t.isCheckable() and isinstance(t, QCheckBox)
    QTest.mouseClick(t, Qt.MouseButton.LeftButton, pos=QPoint(t.width() - 2, t.height() // 2))  # on its words, not the track
    assert t.isChecked()
    t.setFocus()
    QTest.keyClick(t, Qt.Key.Key_Space)
    assert not t.isChecked() and flips == [True, False]
    assert t.sizeHint().height() >= 20 and t.sizeHint().width() > Toggle.TRACK.width()
    t.grab()
    t.deleteLater()


# ---- Quick edit ----
def test_quick_edit_has_one_height(browse):
    q = QuickEdit(browse.ctx, "T000012")
    q.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    q.show()
    QApplication.processEvents()
    q.box.setText("due fri lead mike")
    QApplication.processEvents()
    for w in [*q.findChildren(QLineEdit), *q.findChildren(QComboBox)]:
        if w.isVisible() and not isinstance(w.parentWidget(), QComboBox):
            assert w.height() == 28, (type(w).__name__, w.objectName(), w.height())
    assert q.save_button.height() == 28
    chips = [b for b in q.findChildren(QToolButton) if b.objectName() == "chip" and b.isVisible()]
    assert chips and all(b.height() == 22 for b in chips), [b.height() for b in chips]
    assert not q.styleSheet() or "quickEdit" not in q.styleSheet()  # its rules are in the token file's lane E block
    q.hide()
    q.deleteLater()


# ---- Log progress ----
@pytest.fixture
def window(qapp, sample_root, monkeypatch):
    conn, root, fs = sample_root
    settings = Settings(me="P001")
    settings.save(fs, root)
    ctx = AppContext(conn, root, fs, settings, now=lambda: NOW)
    app = types.SimpleNamespace(ctx=ctx, progress_logged=lambda done, text, trouble: None)
    w = LogProgress(app)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    monkeypatch.setattr(outlook, "show_draft", lambda draft: True, raising=False)
    yield w
    QApplication.processEvents()
    w.picker.hide()
    w.hide()
    w.deleteLater()
    QApplication.processEvents()


def test_log_progress_says_its_notes_in_tooltips(window):
    window.open_for(None, task="T000012")
    QApplication.processEvents()
    form = window.form
    for note in (form.state_note, form.who_note, form.today_note):
        assert note.text() and not note.isVisibleTo(window)
    assert form.state_note.text() in form.state_box.toolTip()
    assert form.who_note.text() == form.who.toolTip() == form.who_name.toolTip()
    assert form.today_note.text() == form.back.toolTip() == form.today_name.toolTip()
    assert all(name.objectName() == "fieldLabel" for name in (form.state_name, form.who_name, form.today_name))
    # what stops a save is still said by its row (decision 753)
    form.say("back", progress_form.NOT_A_DAY)
    assert form.problems["back"].isVisibleTo(window) and form.problems["back"].text() == progress_form.NOT_A_DAY


# ---- Settings ----
def test_settings_show_hints_is_the_one_toggle(browse):
    view = browse.settings_view
    view.load()
    assert isinstance(view.hints, Toggle) and view.hints.accessibleName() == "Show hints"
    assert not any(isinstance(w, Toggle) for w in (view.meetings_on, view.categories, view.progress_sends))
    assert len(view.findChildren(Toggle)) == 1
    was = LOOK.hints
    view.hints.setChecked(not was)
    assert LOOK.hints is (not was)  # at once, before Save settings
    set_hints(was)


def test_a_settings_row_says_its_first_sentence(browse):
    from docrepo.ui.settings_view import Explain

    view = browse.settings_view
    was = LOOK.hints
    set_hints(False)
    lines = [x for x in view.findChildren(Explain) if ". " in x.what]
    assert lines
    for line in lines:
        assert line.text() == first_sentence(line.what) and line.toolTip() == line.what
    set_hints(True)
    assert all(line.text() == line.what for line in lines)
    set_hints(was)
    assert first_sentence("One. Two.") == "One." and first_sentence("Only one") == "Only one"


def test_each_hotkey_has_its_row(browse):
    view = browse.settings_view
    view.load()
    grid: QGridLayout = view.more_grid
    held = {grid.itemAt(i).widget() for i in range(grid.count())}
    assert all(box in held for box in view.more_hotkeys.values())
    assert view.wheel_hotkeys and all(box in held for box in view.wheel_hotkeys.values())
    names = [grid.itemAt(i).widget().text() for i in range(grid.count()) if isinstance(grid.itemAt(i).widget(), QLabel)]
    assert any(n.endswith("wheel") for n in names) and view.suggest in held
    values = view.values()
    for key in view.more_hotkeys:
        assert key in values, key
    assert set(view.wheel_hotkeys) <= set(values["wheel_hotkeys"])


def test_settings_foot_stays_in_view_with_save_at_the_right(browse):
    view = browse.settings_view
    assert not view.scroll.widget().isAncestorOf(view.save_button)
    assert view.save_button.objectName() != "primary" and view.undo_button.objectName() == "subtle"
    assert view.save_button.nextInFocusChain() is view.undo_button
