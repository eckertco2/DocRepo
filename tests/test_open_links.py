"""Links that open, a task's links in one place, and a reference field's link (release 5.67, round 6's items 87, 88 and
90, decisions 314 to 317, 320 and 323, from the approved mock). Made-up addresses only; nothing is really opened: a
stand-in takes what would be handed to the browser."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
import re  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import quote  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from docrepo import opener, pins  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.detail import PageState  # noqa: E402
from docrepo.detail import Pages as DetailPages  # noqa: E402
from docrepo.links import check_link_template, reference_link  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.pages import Pages as MdPages  # noqa: E402
from docrepo.save import CaptureDraft, FileRow, save_capture  # noqa: E402
from docrepo.task_links import addresses_in, links_of  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.notes_edit import NotesEdit  # noqa: E402

INSTALLATION = "T000008"
SP = "https://example.sharepoint.com/sites/Plant/Shared%20Documents/"
LIFT = SP + "Lift%20study%20rev%20B.pdf"
FORM = "https://forms.example.com/crane/booking?id=7"
TEAMS = "https://teams.example.com/l/message/19:abc/1696"
TORQUE = "https://example.sharepoint.com/sites/Plant/SitePages/Torque.aspx"
LINKS = {"Change record": "https://changes.example.com/record/{}"}


# ---- opening a link (decision 314) ----
def test_only_a_checked_web_link_is_handed_to_the_browser():
    handed: list[str] = []
    assert opener.start_link(LIFT, handed.append) is None and handed == [LIFT]
    assert opener.start_link("https://example.com/page.", handed.append) is None and handed[-1] == "https://example.com/page"
    for bad in ("mailto:someone@example.com", "file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "C:\\Docs\\a.pdf",
                "https://example.com/a b", "", "msteams:/l/message/1"):
        assert opener.start_link(bad, handed.append) == "DocRepo opens only web links (http or https).", bad
    assert "name or password" in opener.start_link("https://user:secret@example.com/", handed.append)
    assert len(handed) == 2

    def refuses(_address: str) -> None:
        raise OSError("no browser")

    assert opener.start_link(LIFT, refuses) == "Windows couldn't hand the link to your browser (OSError)."


def test_only_opener_hands_anything_to_windows_open():
    """Release 5.67's rule: a link is handed over only through opener.py, and nothing uses Qt's or Python's browser openers."""
    src = Path(__file__).resolve().parent.parent / "docrepo"
    for f in src.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "QDesktopServices" not in text and "openUrl(" not in text, f
        if f.name != "opener.py":
            assert "startfile(" not in text, f


# ---- a reference field's link (decision 320) ----
def test_a_reference_fields_link():
    assert reference_link("https://changes.example.com/record/{}", "4471") == "https://changes.example.com/record/4471"
    assert reference_link("https://changes.example.com/view?id={}&tab=1", " 4471 ") == "https://changes.example.com/view?id=4471&tab=1"
    assert reference_link("https://changes.example.com/record/", "4471") == "https://changes.example.com/record/4471"
    assert reference_link("https://changes.example.com/record/{}", "A/12 3") == "https://changes.example.com/record/A%2F12%203"
    assert reference_link("https://changes.example.com/record/{}", "") == "" and reference_link("", "4471") == ""
    assert check_link_template("") == "" and check_link_template("https://changes.example.com/record/{}") == ""
    assert check_link_template("changes.example.com/{}") == "starts with http:// or https://"
    assert check_link_template("https://x.example.com/{}/{}") == "has {} once at most"
    assert check_link_template("https://changes example.com/{}") == "is a web address with no spaces"


def test_settings_keep_link_addresses(data_root, fs):
    from docrepo.config import SETTINGS_FILE

    s = Settings(reference_fields=["Change record"])
    s.save(fs, data_root)
    assert "reference_links" not in json.loads((data_root / SETTINGS_FILE).read_text(encoding="utf-8"))  # only once set
    s.reference_links = dict(LINKS)
    s.save(fs, data_root)
    again = Settings.load(data_root)
    assert again.reference_links == LINKS and again.reference_link("Change record", "4471") == "https://changes.example.com/record/4471"
    assert again.reference_link("Permit no.", "9") == ""
    (data_root / SETTINGS_FILE).write_text(json.dumps({"reference_links": ["not", "names"]}), encoding="utf-8")
    assert Settings.load(data_root).reference_links == {}  # left out, with a warning, rather than refusing to start


# ---- a task's links (decisions 316, 317 and 323) ----
def _save(env, at: str, content: str = "", files: list[FileRow] | None = None):
    conn, root, fs = env
    return save_capture(conn, root, fs, Settings(me="P001"), CaptureDraft(content=content, task=INSTALLATION, files=files or []),
                        datetime.fromisoformat(at))


@pytest.fixture
def linked(sample_root, tmp_path):
    """Installation with three links, a folder, an address in a note and a change record number, as the mock has them."""
    conn, root, fs = sample_root
    folder = tmp_path / "Drawings"
    folder.mkdir()
    _save(sample_root, "2026-10-02 09:40", "Installation drawings folder.", [FileRow("Drawings", str(folder) + "\\", "The drawings.")])
    _save(sample_root, "2026-10-05 11:12", "Crane vendor's lift study.", [FileRow("Lift study rev B.pdf", LIFT, "The lift study.")])
    _save(sample_root, "2026-10-06 15:30", "Booking form for the crane.", [FileRow("Crane booking form", FORM, "Books the crane.")])
    _save(sample_root, "2026-10-07 16:45", f"Torque values for the coupling bolts are in {TORQUE}, section 4.")
    _save(sample_root, "2026-10-07 17:02", "Crane timing agreed.", [FileRow("Teams thread: crane timing", TEAMS, "Where it was agreed.")])
    m = Model(conn)
    lift = next(d.id for d in m.documents.values() if d.original == LIFT)
    pins.set_pinned(conn, INSTALLATION, lift, True)
    conn.execute("INSERT INTO task_references (task, name, value) VALUES (?, ?, ?)", (INSTALLATION, "Change record", "4471"))
    conn.commit()
    return conn, root, fs, folder


def test_a_tasks_links_in_their_order(linked):
    conn, _, _, folder = linked
    m = Model(conn)
    xs = links_of(m, INSTALLATION, LINKS)
    assert [(x.kind, x.name) for x in xs] == [
        ("reference", "Change record 4471"), ("link", "Lift study rev B.pdf"), ("link", "Teams thread: crane timing"),
        ("link", "Crane booking form"), ("folder", "Drawings"), ("text", "Torque.aspx")]
    assert xs[0].address == "https://changes.example.com/record/4471" and xs[1].pinned and not xs[2].pinned
    assert xs[4].address == str(folder) + "\\" and xs[4].where == "Folder" and xs[4].opens.startswith("Opens in File Explorer: ")
    assert xs[5].address == TORQUE and xs[5].where == "In a note · example.sharepoint.com"  # its full stop and comma aren't the address's
    assert [x.kind for x in links_of(m, INSTALLATION)] == ["link", "link", "link", "folder", "text"]  # no link address: no reference link
    assert addresses_in("See https://example.com/a.\n[Spec](document:D000001)\nhttps://example.com/b") == ["https://example.com/a"]


def test_the_task_page_shows_them(linked):
    conn, root, _, _ = linked
    m = Model(conn)
    pages = DetailPages(m, datetime(2026, 10, 8).date(), lambda c: "", "P001", conn, reference_links=LINKS)
    for width in (600, 900):  # under When and Who, or in the rail
        page = pages.task_page(INSTALLATION, PageState(), width, "top")
        assert '<p class="sec">Links <span class="sub">6</span></p>' in page
        assert 'href="openurl:' + quote("https://changes.example.com/record/4471", safe="") + '"' in page
        lift = next(d.id for d in m.documents.values() if d.original == LIFT)
        assert f'href="opendoc:{lift}"' in page and 'src="lk:pin"' in page and 'title="Opens in your browser: ' + LIFT + '"' in page
        assert page.count('src="lk:') == 6  # five rows' marks and a pin
        assert "Torque.aspx" not in page  # the sixth isn't shown
        assert re.search(r'href="taskviewlinks:T000008"[^>]*>Show link files in the Task view</a>', page)  # decision 323: not all are files
    details = pages.task_page(INSTALLATION, PageState(details=True), 600, "top")
    assert ">4471</a>" in details and "Copy link" in details and "copyref:Change%20record" in details
    plain = DetailPages(m, datetime(2026, 10, 8).date(), lambda c: "", "P001", conn)
    assert "Add a link" in plain.task_page(INSTALLATION, PageState(details=True), 600, "top")  # no link address yet


def test_all_n_links_when_they_are_all_files(sample_root):
    for i in range(6):
        _save(sample_root, f"2026-10-0{i + 1} 09:00", f"Link {i}.", [FileRow(f"Page {i}", f"https://example.com/p{i}", "A page.")])
    conn = sample_root[0]
    page = DetailPages(Model(conn), datetime(2026, 10, 8).date(), lambda c: "", "P001", conn).task_page(INSTALLATION, PageState(), 600, "top")
    assert re.search(r'href="taskviewlinks:T000008"[^>]*>All 6 links</a>', page)


def test_task_md_has_them(linked):
    conn = linked[0]
    md = MdPages(Model(conn), datetime(2026, 10, 8).date(), datetime(2026, 10, 8, 9, 0), LINKS).task_page(Model(conn).task(INSTALLATION))
    assert "| Change record | [4471](https://changes.example.com/record/4471) |" in md
    links = md.split("## Links\n\n", 1)[1].split("\n\n", 1)[0].split("\n")
    assert links[0] == "- [Change record 4471](https://changes.example.com/record/4471)" and links[1] == f"- [Lift study rev B.pdf]({LIFT})"
    assert links[4].startswith("- [Drawings](file:///") and links[5] == f"- [Torque.aspx]({TORQUE})"


# ---- in the browse tool (decision 315) ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(qapp, linked):
    conn, root, fs, _ = linked
    settings = Settings(me="P001", reference_fields=["Change record"], reference_links=dict(LINKS))
    ctx = AppContext(conn, root, fs, settings, now=lambda: datetime(2026, 10, 8, 14, 10))
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.handed, w.revealed = [], []
    w.link_starter = w.handed.append
    w.reveal = lambda path: w.revealed.append(path) or True
    w.show_browse()
    yield w
    for view in list(w.task_views.values()):
        view.close()
    capture.deleteLater()
    w.deleteLater()


def test_the_page_opens_and_copies(browse, linked):
    conn, _, _, folder = linked
    m = Model(conn)
    lift = next(d.id for d in m.documents.values() if d.original == LIFT)
    drawings = next(d.id for d in m.documents.values() if d.name == "Drawings")
    browse.go_task(INSTALLATION)
    browse.on_link(QUrl(f"opendoc:{lift}"))
    assert browse.handed == [LIFT] and "Opened Lift study rev B.pdf in your browser." in browse.status.text()  # %20 kept exactly
    assert pins.uses_of(conn, [lift])[0][2] == "open"
    browse.on_link(QUrl("openurl:" + quote("https://changes.example.com/record/4471", safe="")))
    assert browse.handed[-1] == "https://changes.example.com/record/4471"
    browse.on_link(QUrl(f"opendoc:{drawings}"))
    assert browse.revealed == [Path(str(folder) + "\\")] and len(browse.handed) == 2
    browse.on_link(QUrl("copyaddr:" + quote(LIFT, safe="")))
    assert QGuiApplication.clipboard().text() == LIFT
    browse.on_link(QUrl("openurl:" + quote("mailto:someone@example.com", safe="")))
    assert len(browse.handed) == 2 and "only web links" in browse.status.text()


def test_all_links_opens_the_task_view_on_links(browse):
    browse.go_task(INSTALLATION)
    browse.on_link(QUrl(f"taskviewlinks:{INSTALLATION}"))
    view = browse.task_views[INSTALLATION]
    assert view.filters.types == {"link"}
    shown = [r for r in view.shown_records()] if hasattr(view, "shown_records") else None
    if shown is not None:
        assert {r.type for r in shown if r.kind == "file"} == {"link"}


def test_a_links_page_and_its_row_open_it(browse, linked):
    conn = linked[0]
    lift = next(d.id for d in Model(conn).documents.values() if d.original == LIFT)
    browse.on_link(QUrl(f"doc:{lift}"))
    buttons = [b for b in browse.actions.findChildren(QPushButton) if b.isVisible()]
    assert [b.text() for b in buttons] == ["Open link", "Copy link"]
    buttons[0].click()
    assert browse.handed == [LIFT]
    browse.reveal_key(("doc", lift))  # a double-click on its row in Documents
    assert browse.handed == [LIFT, LIFT] and browse.revealed == []


def test_the_task_views_enter_opens_a_link(browse, linked):
    conn = linked[0]
    browse.open_task_view(INSTALLATION, file_type="link")
    view = browse.task_views[INSTALLATION]
    record = next(r for r in view.records if r.type == "link" and r.path == LIFT)
    assert view._actions_for(record)[0][:2] == ("Open link", "open")
    view.file_action("open", record)
    assert browse.handed == [LIFT] and "Opened Lift study rev B.pdf in your browser." in view.foot.text()
    view.file_action("copylink", record)
    assert QGuiApplication.clipboard().text() == LIFT and browse.handed == [LIFT]


def test_settings_reference_fields_with_links(browse, ctx_settings=None):
    view = browse.settings_view
    view.load()
    assert view.references.names() == ["Change record"] and view.references.links() == LINKS
    name, address, made, _ = view.references.rows[0]
    assert made.text() == "https://changes.example.com/record/1234"
    address.setText("changes.example.com/record/{}")
    assert made.text() == "Needs an address that starts with http:// or https://"
    assert view.save() == [] and "link address needs to be one that starts with http://" in view.error.text()
    address.setText("https://changes.example.com/view?id={}")
    assert "reference_links" in view.save()
    assert browse.ctx.settings.reference_links == {"Change record": "https://changes.example.com/view?id={}"}
    view.references.add_row("Permit no.", "")
    assert "reference_fields" in view.save() and browse.ctx.settings.reference_fields == ["Change record", "Permit no."]
    assert browse.ctx.settings.reference_links == {"Change record": "https://changes.example.com/view?id={}"}


def test_edit_tasks_reference_box_opens_its_page(browse):
    from docrepo.ui.task_forms import TaskEditDialog

    m = browse.model()
    dialog = TaskEditDialog(browse, m, INSTALLATION, browse._label_options, browse._people_options, reference_fields=["Change record"],
                            reference_links=LINKS, open_link=browse.open_address)
    try:
        box, button = dialog.references["Change record"], dialog.reference_opens["Change record"]
        assert box.text() == "4471" and button.isEnabled() and button.toolTip().endswith("/record/4471")
        box.setText("")
        assert not button.isEnabled() and button.toolTip() == "Type its number first"
        box.setText("4480")
        button.click()
        assert browse.handed[-1] == "https://changes.example.com/record/4480"
    finally:
        dialog.deleteLater()


# ---- the notes page: addresses underlined, Ctrl+click opens (decision 315) ----
def test_the_notes_page_underlines_addresses_and_ctrl_click_opens_one(qapp):
    page = NotesEdit()
    page.resize(700, 300)
    page.setPlainText(f"Torque values are in {TORQUE}, section 4.\nNo address here.")
    page.show()
    page.mark_addresses()
    marks = page.extraSelections()
    assert len(marks) == 1 and marks[0].cursor.selectedText() == TORQUE and marks[0].format.fontUnderline()
    # Ctrl+click in the middle of the address
    c = page.textCursor()
    c.setPosition(len("Torque values are in ") + 10)
    at = page.cursorRect(c).center()
    assert page.address_at(at) == TORQUE
    got: list[str] = []
    page.open_link.connect(got.append)
    plain: list[str] = []
    page.open_ref.connect(plain.append)
    for kind, mods in ((QEvent.Type.MouseButtonPress, Qt.KeyboardModifier.ControlModifier), (QEvent.Type.MouseButtonRelease, Qt.KeyboardModifier.ControlModifier)):
        QApplication.sendEvent(page.viewport(), QMouseEvent(kind, QPointF(at), QPointF(page.viewport().mapToGlobal(at)), Qt.MouseButton.LeftButton,
                                                            Qt.MouseButton.LeftButton, mods))
    assert got == ["openurl:" + quote(TORQUE, safe="")] and plain == []
    c.setPosition(len(f"Torque values are in {TORQUE}, section 4.\nNo add"))
    assert page.address_at(page.cursorRect(c).center()) is None
    page.deleteLater()
