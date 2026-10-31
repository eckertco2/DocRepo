"""The Capture wheel's "Email or file", task search and file search (release 5.42): what to read from a snapshot, with fakes for
Outlook and the Shell, and the two search windows, driven offscreen over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from docrepo import capacity, db, file_search, hotkey, outlook, overview, prompts, search, selection  # noqa: E402
from docrepo.app import CaptureApp  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.sample import load_sample, write_sample_files  # noqa: E402
from docrepo.selection import Selected, Snapshot  # noqa: E402
from docrepo.ui import selection_capture  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


# ---- what a snapshot is ----
@pytest.mark.parametrize(("window_class", "program", "kind"), [
    ("CabinetWClass", "explorer.exe", "explorer"),
    ("ExploreWClass", "explorer.exe", "explorer"),
    ("Progman", "explorer.exe", "desktop"),
    ("WorkerW", "explorer.exe", "desktop"),
    ("rctrl_renwnd32", "outlook.exe", "outlook"),
    ("rctrl_renwnd32", "other.exe", ""),  # new Outlook isn't this program
    ("Chrome_WidgetWin_1", "chrome.exe", ""),
    ("", "", ""),
])
def test_what_kind_of_window(window_class, program, kind):
    assert Snapshot(1, 1, window_class, 5, program).kind == kind


def test_nothing_to_read_with_no_window_or_one_thats_gone(monkeypatch):
    assert selection.plan(None) == ""
    assert selection.plan(Snapshot()) == ""
    monkeypatch.setattr(selection, "still_there", lambda s: False)
    assert selection.plan(Snapshot(1, 1, "CabinetWClass", 5, "explorer.exe")) == ""


def test_what_to_read_by_window(monkeypatch):
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    assert selection.plan(Snapshot(1, 1, "CabinetWClass", 5, "explorer.exe")) == "explorer"
    assert selection.plan(Snapshot(1, 1, "Progman", 5, "explorer.exe")) == "explorer"
    assert selection.plan(Snapshot(1, 1, "rctrl_renwnd32", 5, "outlook.exe")) == "outlook"
    assert selection.plan(Snapshot(1, 1, "Notepad", 5, "notepad.exe")) == ""


# ---- File Explorer, with a fake Shell ----
class Item:
    def __init__(self, name, path="", on_disk=True):
        self.Name, self.Path, self.IsFileSystem = name, path, on_disk


class Items(list):
    pass


class Document:
    def __init__(self, items):
        self._items = items

    def SelectedItems(self):  # noqa: N802 - the Shell's name
        return Items(self._items)


class Window:
    def __init__(self, hwnd, items, tab=0):
        self.HWND, self.Document, self.tab = hwnd, Document(items), tab


class Windows(list):
    def FindWindowSW(self, *_args):  # noqa: N802 - the Shell's name
        return self[0]


class Shell:
    def __init__(self, *windows):
        self._windows = Windows(windows)

    def Windows(self):  # noqa: N802 - the Shell's name
        return self._windows


EXPLORER = Snapshot(10, 10, "CabinetWClass", 5, "explorer.exe", tab=77)


def test_explorer_gives_the_selected_paths():
    shell = Shell(Window(9, [Item("no.txt", r"C:\x\no.txt")]), Window(10, [Item("a.txt", r"C:\x\a.txt"), Item("b.txt", r"C:\x\b.txt")]))
    found = selection.read_explorer(shell, EXPLORER, lambda w: w.tab)
    assert found.paths == [r"C:\x\a.txt", r"C:\x\b.txt"] and not found.note


def test_windows_11_tabs_are_told_apart_by_their_own_window():
    """Every tab of one window reports the same HWND: the stored front tab decides."""
    shell = Shell(Window(10, [Item("back.txt", r"C:\x\back.txt")], tab=55), Window(10, [Item("front.txt", r"C:\x\front.txt")], tab=77))
    assert selection.read_explorer(shell, EXPLORER, lambda w: w.tab).paths == [r"C:\x\front.txt"]


def test_nothing_selected_says_so():
    found = selection.read_explorer(Shell(Window(10, [])), EXPLORER, lambda w: 0)
    assert not found.paths and "Nothing is selected in File Explorer" in found.note


def test_items_not_on_disk_are_left_out_and_named():
    found = selection.read_explorer(Shell(Window(10, [Item("Recycle Bin", "::{645FF040}", on_disk=False), Item("a.txt", r"C:\x\a.txt")])), EXPLORER, lambda w: 0)
    assert found.paths == [r"C:\x\a.txt"] and "Recycle Bin isn't" in found.note.replace("isn't files", "isn't")


def test_the_desktop_is_read_too():
    found = selection.read_explorer(Shell(Window(0, [Item("d.txt", r"C:\d\d.txt")])), Snapshot(1, 1, "Progman", 5, "explorer.exe"))
    assert found.paths == [r"C:\d\d.txt"]


def test_a_window_that_has_gone_from_the_shell_says_so():
    assert "couldn't find" in selection.read_explorer(Shell(Window(9, [])), EXPLORER, lambda w: 0).note


# ---- Outlook, with fakes ----
class Mail:
    Class = outlook.OL_MAIL
    Subject = "A selected email"
    SenderName = "Sam Sample"
    SenderEmailAddress = "sam@example.com"
    To = "Me"
    CC = ""
    Body = "The body"
    HTMLBody = ""
    ReceivedTime = "2026-10-08 09:00:00"
    SentOn = "2026-10-08 09:00:00"
    EntryID = "E1"
    ConversationID = "C1"
    Parent = None
    Attachments = type("NoAttachments", (), {"Count": 0})()

    def __init__(self, subject="A selected email", received="2026-10-08 09:00:00"):
        self.Subject = subject
        self.ReceivedTime = received


class Collection:
    def __init__(self, *items):
        self._items = items
        self.Count = len(items)

    def Item(self, n):  # noqa: N802 - Outlook's name
        return self._items[n - 1]


class Explorer:
    Class = 34

    def __init__(self, selection_=None, attachments=None):
        self.Selection = selection_ or Collection()
        self.AttachmentSelection = attachments or Collection()


class Inspector:
    Class = outlook.OL_INSPECTOR

    def __init__(self, item):
        self.CurrentItem = item


class Outlook:
    def __init__(self, window):
        self.window = window

    def ActiveWindow(self):  # noqa: N802 - Outlook's name
        return self.window

    def ActiveExplorer(self):  # noqa: N802 - Outlook's name
        return self.window if isinstance(self.window, Explorer) else Explorer()


def fake_outlook(monkeypatch, window):
    monkeypatch.setattr(outlook, "connect", lambda: (Outlook(window), "fake"))


def test_an_email_open_in_its_own_window_is_the_one_read(monkeypatch):
    fake_outlook(monkeypatch, Inspector(Mail("The open one")))
    assert [e.subject for e in outlook.front_emails()] == ["The open one"]


def test_otherwise_the_main_windows_selection_is_read(monkeypatch):
    fake_outlook(monkeypatch, Explorer(Collection(Mail("One"), Mail("Two"))))
    assert [e.subject for e in outlook.front_emails()] == ["One", "Two"]


def test_a_conversation_header_gives_its_newest_email(monkeypatch):
    class Header:
        def GetItems(self):  # noqa: N802 - Outlook's name
            return Collection(Mail("Older", "2026-10-01"), Mail("Newest", "2026-10-07"))

    class Headers(Collection):
        def GetSelection(self, _kind):  # noqa: N802 - Outlook's name
            return Collection(Header())

    fake_outlook(monkeypatch, Explorer(Headers()))
    assert [e.subject for e in outlook.front_emails()] == ["Newest"]


def test_nothing_selected_is_outlooks_usual_message(monkeypatch):
    fake_outlook(monkeypatch, Explorer())
    with pytest.raises(outlook.OutlookError, match="No email is selected"):
        outlook.front_emails()


def test_a_selected_attachment_comes_alone_and_a_new_row(monkeypatch):
    class Attached:
        FileName = "pump curve.pdf"
        Size = 2048
        saved = []

        def SaveAsFile(self, path):  # noqa: N802 - Outlook's name
            self.saved.append(path)

    fake_outlook(monkeypatch, Explorer(attachments=Collection(Attached())))
    row = outlook.selected_attachment_row()
    assert row.name == "pump curve.pdf" and row.path is None and row.part.kind == "attachment"


def test_no_attachment_selected_means_the_email(monkeypatch):
    fake_outlook(monkeypatch, Explorer())
    assert outlook.selected_attachment_row() is None
    fake_outlook(monkeypatch, Inspector(Mail()))
    assert outlook.selected_attachment_row() is None


# ---- the windows ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(qapp, data_root, fs, monkeypatch):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    write_sample_files(conn, data_root, fs)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    search.rebuild(conn, data_root)
    ctx = AppContext(conn, data_root, fs, settings, now=lambda: NOW)
    monkeypatch.setattr(hotkey, "register", lambda *a: True)
    monkeypatch.setattr(hotkey, "unregister", lambda *a: None)
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda *a, **k: None)
    monkeypatch.setattr(selection_capture, "off_thread", lambda work, done, parent: done(work()))
    a = CaptureApp(qapp, ctx)
    yield a
    for w in (a.wheels.window, a.window, a.browse, a.wheels._file_search, a.wheels._task_search):
        if w is not None:
            w.hide()
    if a.window.pin_window is not None:
        a.window.pin_window.hide()
    a.tray.hide()
    qapp.removeNativeEventFilter(a.filter)
    conn.close()


def test_with_nothing_to_read_the_pinned_window_opens_saying_drag_it_here(app):
    app.window.capture_selection(Snapshot(1, 1, "Notepad", 5, "notepad.exe"))
    assert app.window.pinned and app.window.pin_window.isVisible()
    assert selection_capture.DRAG_IT in app.window.pin_window.message.text()


def test_files_selected_arrive_as_a_drop_does(app, monkeypatch, tmp_path):
    f = tmp_path / "selected.txt"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    monkeypatch.setattr(selection, "read_selected", lambda s: Selected(paths=[str(f)]))
    app.window.capture_selection(EXPLORER)
    assert [e.row.name for e in app.window.files] == ["selected.txt"] and app.window.pinned


def test_a_note_from_explorer_shows_in_the_pinned_window(app, monkeypatch):
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    monkeypatch.setattr(selection, "read_selected", lambda s: Selected(note="Nothing is selected in File Explorer."))
    app.window.capture_selection(EXPLORER)
    assert "Nothing is selected" in app.window.pin_window.message.text()


def test_they_join_a_draft_already_there(app, monkeypatch, tmp_path):
    f, g = tmp_path / "one.txt", tmp_path / "two.txt"
    f.write_text("x", encoding="utf-8")
    g.write_text("x", encoding="utf-8")
    app.window.show_capture()
    app.window.add_paths([str(f)])
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    monkeypatch.setattr(selection, "read_selected", lambda s: Selected(paths=[str(g)]))
    app.window.capture_selection(EXPLORER)
    assert [e.row.name for e in app.window.files] == ["one.txt", "two.txt"]


def test_outlooks_email_joins_through_the_mail_buttons_read(app, monkeypatch):
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    monkeypatch.setattr(selection_capture, "outlook_answers", lambda: None)
    monkeypatch.setattr(outlook, "selected_attachment_row", lambda: None)
    from docrepo.save import EmailItem

    email = EmailItem(subject="From Outlook", sender="Sam", sent="2026-10-08 09:00:00", to="", body="Hi")
    monkeypatch.setattr(outlook, "front_emails", lambda scratch=None: [email])
    app.window.capture_selection(Snapshot(1, 1, "rctrl_renwnd32", 5, "outlook.exe"))
    assert any(e.row.email is email for e in app.window.files)


def test_a_slow_outlook_says_a_dialog_may_be_open_and_the_answer_still_joins(app, monkeypatch, qapp):
    monkeypatch.setattr(selection, "still_there", lambda s: True)
    monkeypatch.setattr(selection_capture, "SLOW_MS", 1)
    answered = []
    monkeypatch.setattr(selection_capture, "off_thread", lambda work, done, parent: answered.append(done))
    read = []
    monkeypatch.setattr(selection_capture, "_read_outlook", lambda capture: read.append(capture))
    app.window.capture_selection(Snapshot(1, 1, "rctrl_renwnd32", 5, "outlook.exe"))
    deadline = time.time() + 2
    while selection_capture.SLOW_OUTLOOK[:20] not in app.window.pin_window.message.toolTip() + app.window.pin_window.message.text() and time.time() < deadline:
        qapp.processEvents()
    assert "dialog" in app.window.pin_window.message.text()
    answered[0](None)
    assert read == [app.window]


def test_off_thread_answers_on_the_windows_thread(qapp):
    """Only paths cross back; the answer arrives where the windows live."""
    import threading

    import importlib

    module = importlib.import_module("docrepo.ui.selection_capture")
    real = module.__dict__["off_thread"]
    from PySide6.QtCore import QObject

    parent = QObject()
    seen = []
    worker = []
    real(lambda: worker.append(threading.current_thread()) or "paths", lambda answer: seen.append((answer, threading.current_thread())), parent)
    deadline = time.time() + 3
    while not seen and time.time() < deadline:
        qapp.processEvents()
    assert seen and seen[0][0] == "paths" and seen[0][1] is threading.main_thread()
    assert worker[0] is not threading.main_thread()


def test_reading_explorer_for_real_never_raises_with_no_window():
    """On a thread of its own, as it always runs: it starts and ends COM on the thread it's on."""
    import threading

    answers = []
    thread = threading.Thread(target=lambda: answers.append(selection.read_selected(Snapshot(123456, 123456, "CabinetWClass", 5, "explorer.exe"))))
    thread.start()
    thread.join(20)
    assert isinstance(answers[0], Selected) and not answers[0].paths


# ---- task search ----
def test_task_search_opens_and_enter_opens_the_page(app, monkeypatch):
    app.wheels.task_search("page")
    s = app.wheels._task_search
    assert s.picker.isVisible() and "Enter opens its page" in s.picker.hint
    s.picker.search.setText("impeller")
    assert any(a.data() for a in s.picker.actions())
    s.picker._pick_first()
    QApplication.processEvents()
    assert app.browse.isVisible() and app.browse.sel and app.browse.sel[0] == "task"
    assert not s.isVisible()


def test_closing_task_search_gives_the_keyboard_back_and_a_pick_doesnt(app, monkeypatch):
    given = []
    monkeypatch.setattr(app.wheels, "give_back", lambda: given.append(True))
    app.wheels.task_search("page")
    s = app.wheels._task_search
    s.picker.close()
    QApplication.processEvents()
    assert given == [True] and not s.isVisible()
    app.wheels.task_search("page")
    s.picker.pick("T000008")
    QApplication.processEvents()
    assert given == [True] and not s.isVisible()


def test_the_browse_wheels_task_search_opens_the_task_view_and_ctrl_its_page(app, monkeypatch):
    """Decision 213 as the owner changed it (release 5.43.1): not the task tree."""
    slot = app.wheels.config.wheel("browse").slots["E"]
    app.wheels.run(slot.command, slot.args)
    s = app.wheels._task_search
    assert "Enter opens its Task view" in s.picker.hint
    s.picker.pick("T000008")
    QApplication.processEvents()
    view = app.browse.task_views["T000008"]
    assert view.isVisible() and not app.browse.isVisible() and not s.isVisible()
    view.hide()
    app.wheels.run(slot.command, slot.args)
    monkeypatch.setattr(QGuiApplication, "keyboardModifiers", staticmethod(lambda: Qt.KeyboardModifier.ControlModifier))
    s.picker.pick("T000002")
    assert app.browse.isVisible() and app.browse.sel == ("task", "T000002")
    assert "T000002" not in app.browse.task_views


def test_ctrl_enter_opens_the_task_view(app, monkeypatch):
    app.wheels.task_search("page")
    s = app.wheels._task_search
    monkeypatch.setattr(QGuiApplication, "keyboardModifiers", staticmethod(lambda: Qt.KeyboardModifier.ControlModifier))
    s.picker.pick("T000008")
    assert "T000008" in app.browse.task_views
    app.browse.task_views["T000008"].hide()


def test_it_finds_closed_tasks_marked_as_closed(app):
    closed = next(t for t in app.ctx.model().tasks.values() if t.state == "Closed" and not t.discarded)
    app.wheels.task_search("page")
    s = app.wheels._task_search
    s.picker.search.setText(closed.title[:12])
    texts = [a.text() for a in s.picker.actions() if a.data() == closed.id]
    assert texts and "(closed)" in texts[0]
    s.picker.close()


def test_a_parents_picker_still_hides_closed_tasks(app):
    from docrepo.ui.task_picker import TaskPicker

    closed = next(t for t in app.ctx.model().tasks.values() if t.state == "Closed" and not t.discarded)
    p = TaskPicker(None, app.ctx.model)
    p._opening()
    p.search.setText(closed.title[:12])
    assert not any(a.data() == closed.id for a in p.actions())


def test_no_match_offers_search_everything_with_what_was_typed(app):
    app.wheels.task_search("page")
    s = app.wheels._task_search
    s.picker.search.setText("zzzqqq")
    assert any("Search everything for “zzzqqq”" in a.text() for a in s.picker.actions())
    s.picker._pick_first()
    assert app.browse.isVisible() and app.browse.search_box.text() == "zzzqqq"


def test_the_execution_wheels_task_view_with_nothing_current_opens_task_search(app):
    app.browse.sel = None
    app.wheels.run("task_view.current", {})
    assert app.wheels._task_search.then == "task_view"
    app.wheels._task_search.picker.pick("T000008")
    assert "T000008" in app.browse.task_views
    app.browse.task_views["T000008"].hide()


# ---- file search ----
def test_records_are_files_and_emails_each_once(app):
    records = file_search.records(app.ctx.conn, app.ctx.model(), app.ctx.data_root)
    assert records and {r.kind for r in records} <= {"file", "email"}
    keys = [(r.kind, r.id) for r in records]
    assert len(keys) == len(set(keys))
    assert [r.at for r in records] == sorted((r.at for r in records), reverse=True)


def test_a_file_on_two_top_level_tasks_is_one_row(app, monkeypatch):
    m = app.ctx.model()
    tops = m.top_level()
    real = overview.build

    def twice(model, root, task, texts):
        records = real(model, root, task, texts)
        return records if records else real(model, root, tops[0].id, texts)

    monkeypatch.setattr(overview, "build", twice)
    records = file_search.records(app.ctx.conn, m, app.ctx.data_root)
    keys = [(r.kind, r.id) for r in records]
    assert len(keys) == len(set(keys))


@pytest.fixture
def files(app, qapp):
    app.wheels.snapshot = None
    app.wheels.file_search()
    return app.wheels._file_search


def test_file_search_lists_everything_and_says_each_rows_task(app, files):
    items = [r for r in files.list.rows if r.kind == "item"]
    assert items and all(r.where for r in items)
    assert files.list.delegate.second_line(items[0]).startswith(items[0].where)
    assert files.isVisible() and "files and emails" in files.foot.text()


def test_it_searches_names_at_once(app, files):
    target = next(r for r in files.records if r.kind == "file")
    word = target.title.split(".")[0].split()[0]
    files.box.setText(word)
    assert any(r.record is target or (r.record and r.record.id == target.id) for r in files.list.rows)


def test_then_the_files_text_on_a_worker_thread(app, files):
    with_text = {k: v for k, v in overview.file_texts(app.ctx.conn, app.ctx.model(), [r.id for r in files.records if r.kind == "file"]).items() if v.strip()}
    assert with_text
    doc, text = next(iter(with_text.items()))
    word = next(w for w in text.split() if len(w) > 5 and w.isalpha())
    files.box.setText(word)
    files.wait_for_second()
    assert any(r.record and r.record.id == doc for r in files.list.rows)


def test_typed_filters_narrow_it(app, files):
    files.box.setText("type:pdf ")
    assert files.filters.types == {"pdf"}
    assert all(r.record.type == "pdf" for r in files.list.rows if r.record)
    files.filters.clear()


def test_nothing_matches_carries_to_search_everything(app, files):
    files.box.setText("zzzqqq")
    assert [r.kind for r in files.list.rows] == ["empty"]
    files.act("open")
    assert app.browse.search_box.text() == "zzzqqq" and not files.isVisible()


def test_enter_opens_through_the_allow_list(app, files, qapp):
    started = []
    files.starter = started.append
    files.exists = lambda p: True
    pdf = next((r for r in files.records if r.kind == "file" and r.type != "link" and r.source != "Email attachment"), None)
    assert pdf is not None
    row = next(i for i, r in enumerate(files.list.rows) if r.record is pdf or (r.record and r.record.id == pdf.id))
    files.act("open", row)
    for t in files._threads:
        t.join(3)
    qapp.processEvents()
    assert started == [pdf.path]


def test_tab_goes_to_its_task(app, files):
    files.list.choose(files.list.choosable()[0])
    r = files.current_record()
    files.act("task")
    assert app.browse.isVisible() and app.browse.sel == ("task", r.task) and not files.isVisible()


def test_ctrl_shift_c_copies_the_path(app, files):
    r = next(x for x in files.records if x.kind == "file")
    row = next(i for i, x in enumerate(files.list.rows) if x.record and x.record.id == r.id)
    files.list.choose(row)
    files.act("copy")
    assert QGuiApplication.clipboard().text().strip('"') == r.path or r.path in QGuiApplication.clipboard().text()


def test_esc_clears_then_closes(app, files):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    files.box.setText("pump")
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    files.eventFilter(files.box, event)
    assert files.box.text() == "" and files.isVisible()
    files.eventFilter(files.box, event)
    assert not files.isVisible()
