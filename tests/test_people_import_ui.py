"""Import people… in the browse tool (release 5.151, decisions 658 to 662), driven offscreen over the sample data, with made-up
people and example.com addresses."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import people_import as ui  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.people_import import PeopleImportDialog  # noqa: E402

NOW = datetime(2026, 11, 15, 9, 30)
LIST = ("Name,Email,Role,Group,Phone\n"
        "Lena Fischer,lena.fischer@example.com,Lead planner,Maintenance,555-0100\n"
        "Tom Becker,tom.becker@example.com,Lead planner,Maintenance,555-0101\n"
        "Priya Shah,priya.shah@example.com,Reliability engineer,Engineering,555-0102\n"
        "Omar Haddad,omar.haddad.example.com,Inspector,,555-0103\n"
        "Todd,todd.brandt@example.com,Electrician,Maintenance,555-0104\n")


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


@pytest.fixture
def dialog(ctx):
    d = PeopleImportDialog(None, ctx)
    yield d
    d.deleteLater()


def csv_file(tmp_path, text=LIST, name="people.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def shown(d: PeopleImportDialog) -> list[tuple[str, str, str, str, bool | None]]:
    """Each line as the list shows it: kind, row, name, what changes, and its tick (None when it can't be ticked)."""
    out = []
    for i in range(d.lines.topLevelItemCount()):
        item = d.lines.topLevelItem(i)
        tick = item.checkState(ui.TICK) == Qt.CheckState.Checked if item.flags() & Qt.ItemFlag.ItemIsUserCheckable else None
        out.append((item.text(ui.KIND), item.text(ui.ROW), item.text(ui.NAME_COLUMN), item.text(ui.WHAT), tick))
    return out


def test_the_window_shows_each_row_with_what_it_does(dialog, tmp_path):
    dialog.load(csv_file(tmp_path))
    assert dialog.columns.text() == "Read: Name, Email, Role, Group. Left alone: Phone."
    assert shown(dialog) == [
        ("New", "2", "Lena Fischer", "lena.fischer@example.com · Lead planner · Maintenance", True),
        ("Update", "3", "Tom Becker", "Role: Planner → Lead planner", True),
        ("Same", "4", "Priya Shah", "Nothing to change", None),
        ("Problem", "5", "Omar Haddad", "“omar.haddad.example.com” isn't an email address.", None),
        ("Update", "6", "Todd", "Email filled in: todd.brandt@example.com · Role filled in: Electrician · Group filled in: Maintenance", True),
    ]
    assert dialog.summary.text() == "5 rows: 1 new, 2 updates, 1 the same, 1 problem."
    assert dialog.ticked_words.text() == "3 ticked to add or update" and dialog.import_button.isEnabled()
    assert not dialog.sheet.isVisible() and not dialog.cut.isVisible() and not dialog.error.isVisible()


def test_unticking_leaves_a_line_out(dialog, tmp_path, ctx):
    dialog.load(csv_file(tmp_path))
    dialog.set_ticked(3, False)
    assert dialog.ticked_words.text() == "2 ticked to add or update"
    dialog.set_ticked(4, True)  # Same can't be ticked
    assert dialog.ticked_words.text() == "2 ticked to add or update"
    dialog.import_now()
    assert dialog.outcome == "1 person added, 1 updated, 1 already the same, 2 left out."
    m = Model(ctx.conn)
    assert m.people["P003"].role == "Planner" and m.people["P006"].email == "todd.brandt@example.com"
    assert any(p.name == "Lena Fischer" for p in m.people.values())


def test_nothing_ticked_imports_nothing(dialog, tmp_path):
    dialog.load(csv_file(tmp_path))
    for row in (2, 3, 6):
        dialog.set_ticked(row, False)
    assert not dialog.import_button.isEnabled() and dialog.ticked_words.text() == "0 ticked to add or update"
    dialog.import_now()
    assert dialog.outcome == ""


def test_a_file_without_a_name_column_says_so(dialog, tmp_path):
    dialog.load(csv_file(tmp_path, "Full name,Email\nLena Fischer,lena.fischer@example.com\n"))
    assert dialog.error.isVisibleTo(dialog) and "no Name column" in dialog.error.text()
    assert dialog.lines.topLevelItemCount() == 0 and not dialog.import_button.isEnabled()
    dialog.load(tmp_path / "people.txt")
    assert "isn't a .csv or an .xlsx" in dialog.error.text()


def test_an_xlsx_with_several_sheets_has_its_sheet_picked(dialog, tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Contacts"
    book.active.append(["Name", "Email"])
    book.active.append(["Lena Fischer", "lena.fischer@example.com"])
    other = book.create_sheet("Contractors")
    other.append(["Name", "Role"])
    other.append(["Omar Haddad", "Inspector"])
    other.append(["Dana Kowalski", "Welder"])
    path = tmp_path / "people.xlsx"
    book.save(path)
    dialog.load(path)
    assert dialog.sheet.isVisibleTo(dialog) and dialog.sheet.currentText() == "Contacts"
    assert [x[2] for x in shown(dialog)] == ["Lena Fischer"]
    dialog.sheet.setCurrentIndex(1)
    assert [x[2] for x in shown(dialog)] == ["Omar Haddad", "Dana Kowalski"] and dialog.columns.text() == "Read: Name, Role."


def test_more_than_5000_rows_says_only_the_first_are_read(dialog, tmp_path):
    rows = "".join(f"Person {i},p{i}@example.com\n" for i in range(5001))
    dialog.load(csv_file(tmp_path, "Name,Email\n" + rows))
    assert dialog.cut.isVisibleTo(dialog) and dialog.lines.topLevelItemCount() == 5000


@pytest.mark.parametrize("view", ["people", "labels", "tagged", "templates", "activity", "mine"])
def test_a_bar_made_only_of_new_widgets_shows(browse, qapp, view):
    """Found in building: a filter bar whose widgets were all just added read as empty and was hidden (since release 5.61), so
    the People view had no Add person, nor Import people…, to click."""
    browse.set_view(view)
    qapp.processEvents()
    # Since release 5.184 a view's buttons are commands on the header's row, each showing or listed under More.
    head = browse.head
    assert head.commands() or head.display_button.isVisibleTo(browse)  # Assigned to me has no command: Sort and Select
    assert all(b.isVisibleTo(browse) or b in head.folded() for b in head.commands())
    assert not head.folded() or head.more_button.isVisibleTo(browse)


def test_import_people_from_the_people_view(browse, tmp_path, qapp):
    browse.set_view("people")
    qapp.processEvents()
    button = next(b for b in browse.head.commands() if b.text() == ui.NAME)
    assert {"Add person", ui.NAME} <= {b.text() for b in browse.head.commands()}  # on the row, or under More (release 5.184)
    path = csv_file(tmp_path)

    def run(d):
        assert isinstance(d, PeopleImportDialog)
        d.load(path)
        d.import_now()
        return True
    browse.run_dialog = run
    button.click()
    assert browse.status.text() == "1 person added, 2 updated, 1 already the same, 1 left out."
    assert browse.view == "people"
    names = [browse.model().people[k[1]].name for k in browse.tree.keys() if k and k[0] == "person"]
    assert "Lena Fischer" in names
    tom = browse.model().people["P003"]
    assert tom.role == "Lead planner"


def test_the_palette_has_import_people(browse, tmp_path):
    browse.set_view("tasks")
    command = next(c for c in browse.palette_commands() if c.label == ui.NAME)
    browse.run_dialog = lambda d: (d.load(csv_file(tmp_path, "Name\nLena Fischer\n")), d.import_now(), True)[-1]
    command.run()
    assert browse.view == "people" and browse.status.text() == "1 person added, 0 updated."
