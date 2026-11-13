"""Release 5.127, today's meetings in the windows, offscreen with a made-up calendar (the cold-eyes plan's decisions 489 to
494): Today's first group, its rows' commands, Link…'s list, the minute tick and F5, Settings → Today, and the Today side
panel's first line. Every subject, place and name here is made up."""
from __future__ import annotations

import html
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402,F401

from docrepo import meetings, outlook  # noqa: E402
from docrepo import wheels_config as wc  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.meetings import FREE, Appointment, TodayCalendar  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui import today_meetings, today_panel  # noqa: E402
from docrepo.ui.browse_window import BrowseWindow  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.tree_view import ACTIONS_ROLE, HTML_ROLE, KEY_ROLE, LINE_ROLE  # noqa: E402

NOW = datetime(2026, 10, 8, 10, 40)
BUSINESS, TOM = "T000010", "P003"


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 8, h, m)


APPTS = [
    Appointment("Contractors on site", datetime(2026, 10, 8), datetime(2026, 10, 9), all_day=True, busy=FREE),
    Appointment("Morning safety huddle", at(7, 30), at(7, 45), "Control room", recurring=True),
    Appointment("Pump trial check-in", at(8, 30), at(9), "Teams"),
    Appointment("Updated: Rigging plan review", at(10, 30), at(11), "Teams"),
    Appointment("Business team meeting", at(11), at(12), "Conf room B", recurring=True),
    Appointment("Lunch", at(12), at(13), busy=FREE),
    Appointment("Tom / Me: weekly 1:1", at(13, 30), at(14), "Tom's office", recurring=True),
    Appointment("", at(15), at(15, 30), private=True),
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def clock():
    return {"now": NOW, "reads": 0, "appts": list(APPTS)}


@pytest.fixture
def ctx(qapp, sample_root, clock):
    conn, root, fs = sample_root

    def read(day):
        clock["reads"] += 1
        answer = clock["appts"]
        if isinstance(answer, Exception):
            raise answer
        return list(answer)

    c = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: clock["now"])
    c.calendar = TodayCalendar(read=read)
    return c


@pytest.fixture
def browse(ctx):
    capture = CaptureWindow(ctx)
    w = BrowseWindow(ctx, capture)
    w.show_browse("today")
    yield w
    w.meetings_timer.stop()
    capture.deleteLater()
    w.deleteLater()


def row_of(browse, title: str):
    return next(i for i in browse.tree.items() if (line := i.data(0, LINE_ROLE)) is not None and line.title == title)


def actions(item) -> dict:
    return {a[0]: a[1] for a in item.data(0, ACTIONS_ROLE).actions}


def html_rows(browse) -> list[str]:
    return [html.unescape(i.data(0, HTML_ROLE) or "") for i in browse.tree.items()]


# ---- the group (decisions 489 and 490) ----
def test_meetings_is_todays_first_group(browse):
    tree = browse.tree
    head = tree.topLevelItem(0)
    assert "<b>Meetings</b>" in head.data(0, HTML_ROLE)
    kids = [head.child(n) for n in range(head.childCount())]
    assert "All day: Contractors on site" in kids[0].data(0, HTML_ROLE)
    assert kids[1].data(0, KEY_ROLE) == today_meetings.EARLIER_KEY and "2 earlier" in kids[1].data(0, HTML_ROLE)
    assert not kids[1].isExpanded() and kids[1].childCount() == 2  # past ones folded
    assert [k.data(0, LINE_ROLE).title for k in kids[2:]] == ["Updated: Rigging plan review", "Business team meeting", "Lunch",
                                                             "Tom / Me: weekly 1:1", "Private appointment"]
    rigging, business, lunch = (row_of(browse, t).data(0, LINE_ROLE) for t in ("Updated: Rigging plan review", "Business team meeting", "Lunch"))
    assert rigging.chips == (("now", "st-ip"),) and business.chips == (("in 20 min", "st-ip"),) and lunch.dim and not lunch.chips
    assert business.context == "Conf room B · Link to its meeting task?"
    assert "11:00–12:00" in row_of(browse, "Business team meeting").data(1, HTML_ROLE)  # the time where a task's date goes
    assert browse.status.text() == ""  # nothing to say when the read worked


def test_the_earlier_fold_stays_as_its_left(browse):
    fold = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == today_meetings.EARLIER_KEY)
    fold.setExpanded(True)
    browse.render_list()
    fold = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == today_meetings.EARLIER_KEY)
    assert fold.isExpanded()


def test_each_rows_commands(browse):
    assert set(actions(row_of(browse, "Business team meeting"))) == {"Link", "Link…"}
    assert list(actions(row_of(browse, "Updated: Rigging plan review"))) == ["Link…", "Make a meeting task"]
    assert row_of(browse, "Private appointment").data(0, ACTIONS_ROLE).actions == []
    meetings.set_link(browse.conn, "Tom / Me: weekly 1:1", TOM, NOW)
    browse.render_list()
    tom = row_of(browse, "Tom / Me: weekly 1:1")
    assert list(actions(tom)) == ["Agenda", "Meeting notes"] and tom.data(0, KEY_ROLE) == ("person", TOM)
    assert tom.data(0, LINE_ROLE).context == "Tom's office · 1 on Tom Becker's agenda"


def test_link_confirms_the_suggestion_with_undo(browse):
    actions(row_of(browse, "Business team meeting"))["Link"]()
    assert meetings.links(browse.conn)["business team meeting"].task == BUSINESS
    row = row_of(browse, "Business team meeting")
    assert row.data(0, KEY_ROLE) == ("task", BUSINESS) and list(actions(row)) == ["Agenda", "Meeting notes"]
    assert row.data(0, LINE_ROLE).context == "Conf room B · 4 on its agenda"
    assert "“Business team meeting” is linked to its meeting task" in browse.status.text() and "Undo" in browse.status.text()
    browse._status_link("undo")
    assert meetings.links(browse.conn) == {} and "Link" in actions(row_of(browse, "Business team meeting"))


def test_link_lists_meetings_and_people_and_a_pick_links(browse, monkeypatch):
    rigging = next(x for x in today_meetings.day_of(browse.ctx)[0].rest if x.appointment.subject.startswith("Updated"))
    picker = today_meetings.pick_link(browse, rigging)
    labels = [r.label for r in picker.rows()]
    assert labels[:2] == ["Meetings", "Business team meeting"] and "People" in labels and "Tom Becker" in labels and "Me" not in labels
    picker.search.setText("tom")
    assert [r.label for r in picker.rows()][0] == "Tom Becker"
    picker.pick(TOM)
    link = meetings.links(browse.conn)["rigging plan review"]  # by its key: "Updated:" set aside
    assert link.person == TOM and link.subject == "Updated: Rigging plan review"
    picker = today_meetings.MeetingPicker(browse, browse.model, "Business team meeting", BUSINESS, "P001")
    picker.popup(browse.mapToGlobal(browse.rect().center()))
    assert [r.label for r in picker.rows()][:2] == ["Suggested", "Business team meeting"]
    picker.close()


def test_make_a_meeting_task_and_meeting_notes(browse):
    actions(row_of(browse, "Updated: Rigging plan review"))["Make a meeting task"]()
    cap = browse.capture
    assert cap.types == {"new_task"} and cap.title.text() == "Updated: Rigging plan review" and cap.n_meeting.isChecked()
    cap.hide()
    meetings.set_link(browse.conn, "Business team meeting", BUSINESS, NOW)
    meetings.set_link(browse.conn, "Tom / Me: weekly 1:1", TOM, NOW)
    browse.render_list()
    actions(row_of(browse, "Business team meeting"))["Meeting notes"]()
    assert cap.meeting_on and cap.task == BUSINESS and cap.meet_name.text() == "Business team meeting 8 Oct"  # today's occurrence
    cap.file_draft()
    actions(row_of(browse, "Tom / Me: weekly 1:1"))["Meeting notes"]()
    assert cap.meeting_on and cap.meet_name.text() == "Tom / Me: weekly 1:1"


def test_agenda_opens_the_task_at_its_agenda_or_the_persons_agenda(browse, qapp):
    meetings.set_link(browse.conn, "Business team meeting", BUSINESS, NOW)
    meetings.set_link(browse.conn, "Tom / Me: weekly 1:1", TOM, NOW)
    browse.render_list()
    actions(row_of(browse, "Business team meeting"))["Agenda"]()
    qapp.processEvents()
    assert browse.sel == ("task", BUSINESS) and browse.view == "today"
    browse.task_pane.header.groups["agenda"].set_open(False)
    assert today_meetings.show_section(browse, "agenda") and browse.task_pane.header.groups["agenda"].is_open
    actions(row_of(browse, "Tom / Me: weekly 1:1"))["Agenda"]()
    assert (browse.view, browse.target) == ("agenda", TOM)


# ---- reading: when, and what's said (decision 493) ----
def test_outlook_not_open_is_a_quiet_line(browse, clock):
    clock["appts"] = outlook.CalendarProblem("closed", "Outlook isn't open.", "finding Outlook", "")
    browse.ctx.calendar.forget()
    browse.render_list()  # closed since the morning's read: that list stays, and says so
    assert any("Outlook isn't open now; this is the list read at 10:40." in h for h in html_rows(browse)) and browse.status.text() == ""
    browse.ctx.calendar = TodayCalendar(read=browse.ctx.calendar.read)  # closed all day
    browse.render_list()
    assert any("Outlook isn't open, so there are no meetings here" in h for h in html_rows(browse)) and browse.status.text() == ""


def test_a_busy_outlook_is_said_once_and_the_list_kept(browse, clock):
    clock["appts"] = outlook.CalendarProblem("busy", "busy", "reading", "0x8001010A")
    clock["now"] = NOW + timedelta(minutes=5)
    browse.render_list()
    assert "Outlook is busy" in browse.status.text() and "read at 10:40" in browse.status.text()
    assert row_of(browse, "Business team meeting") is not None  # the last list, kept
    assert any("this is the list read at 10:40" in h for h in html_rows(browse))
    browse.say("")
    clock["now"] = NOW + timedelta(minutes=10)
    browse.render_list()
    assert browse.status.text() == ""  # said once


def test_read_every_five_minutes_and_on_f5(browse, clock):
    assert clock["reads"] == 1
    browse.render_list()
    clock["now"] = NOW + timedelta(minutes=4)
    today_meetings.tick(browse)
    assert clock["reads"] == 1
    browse.read_again()  # F5
    assert clock["reads"] == 2


def test_the_minute_tick_moves_the_minutes_in_place_and_redraws_when_a_meeting_ends(browse, clock, monkeypatch):
    monkeypatch.setattr(browse, "isVisible", lambda: True)
    business = row_of(browse, "Business team meeting")
    clock["now"] = NOW + timedelta(minutes=1)
    today_meetings.tick(browse)
    assert row_of(browse, "Business team meeting") is business  # the same row, not drawn again
    assert business.data(0, LINE_ROLE).chips == (("in 19 min", "st-ip"),)
    clock["now"] = at(11, 1)  # the review has ended, and the business meeting's under way
    today_meetings.tick(browse)
    fold = next(i for i in browse.tree.items() if i.data(0, KEY_ROLE) == today_meetings.EARLIER_KEY)
    assert "3 earlier" in fold.data(0, HTML_ROLE) and row_of(browse, "Business team meeting").data(0, LINE_ROLE).chips == (("now", "st-ip"),)


def test_the_tick_waits_while_todays_box_is_typed_in(browse, clock, monkeypatch):
    monkeypatch.setattr(browse, "isVisible", lambda: True)
    browse.today_note.setText("Call the vendor")
    clock["now"] = at(11, 1)
    today_meetings.tick(browse)
    assert browse.today_note.text() == "Call the vendor"  # not drawn again under the owner's typing


def test_the_switch_off_reads_nothing_and_shows_nothing(browse, clock):
    browse.ctx.settings.today_meetings = False
    browse.ctx.calendar.forget()
    browse.render_list()
    assert clock["reads"] == 1 and not any("<b>Meetings</b>" in h for h in html_rows(browse))


# ---- Settings → Today (decisions 491 and 494) ----
def test_settings_lists_the_links_with_remove_and_the_switch(browse):
    meetings.set_link(browse.conn, "Tom / Me: weekly 1:1", TOM, NOW)
    browse.set_view("settings")
    view = browse.settings_view
    assert view.meetings_on.isChecked()
    words = [w.text() for w in view.meeting_links.findChildren(QLabel)]
    assert "Tom / Me: weekly 1:1" in words and "Tom Becker (person)" in words
    view.meeting_links.removes["tom / me: weekly 1:1"].click()
    assert meetings.links(browse.conn) == {} and "is no longer linked" in browse.status.text()
    view.meetings_on.setChecked(False)
    view.save()
    assert browse.ctx.settings.today_meetings is False and Settings.load(browse.ctx.data_root).today_meetings is False


# ---- the Today side panel's first line (decision 490) ----
@pytest.fixture
def panel(browse, monkeypatch):
    monkeypatch.setattr(today_panel, "_full_screen_candidates", lambda own: [])
    p = today_panel.TodayPanel(browse.ctx, browse, SimpleNamespace(config=wc.WheelsConfig(wheels=())))
    p.open_panel()
    yield p
    p.close_panel()
    p.deleteLater()


def test_the_panels_first_line_is_the_meeting_under_way_or_next(panel, clock):
    line = panel.meeting_line
    assert panel.list_lay.itemAt(0).widget() is line and line.isVisible()  # first, and at rest too
    assert line.title == "Updated: Rigging plan review" and line.findChild(QLabel, "tpDue").property("days") == "now"
    links = line.findChildren(QPushButton, "tpLink")
    assert [b.text() for b in links] == ["Link…"] and not any(b.isVisible() for b in links)  # its commands once widened
    clock["now"] = at(11, 5)
    panel._tick_meeting()
    line = panel.meeting_line
    assert line.title == "Business team meeting" and line.findChild(QLabel, "tpDue").property("days") == "now"


def test_the_panels_minutes_move_in_place_and_f5_reads_again(panel, browse, clock):
    meetings.set_link(browse.conn, "Updated: Rigging plan review", "T000012", NOW)
    clock["now"] = at(10, 50)
    panel.refresh()
    clock["now"] = at(11, 1)
    panel.refresh()
    line = panel.meeting_line
    assert line.title == "Business team meeting"
    meetings.set_link(browse.conn, "Business team meeting", BUSINESS, NOW)
    panel.refresh()
    line = panel.meeting_line
    assert [b.text() for b in line.findChildren(QPushButton, "tpLink")] == ["Agenda", "Notes"] and line.task_id == BUSINESS
    assert line in panel.drop_targets()  # a file dropped on it goes to its meeting task, as on any task's row
    reads = clock["reads"]
    panel.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier))
    assert clock["reads"] == reads + 1


def test_the_panel_says_when_outlook_isnt_open(panel, clock):
    clock["appts"] = outlook.CalendarProblem("closed", "Outlook isn't open.", "finding Outlook", "")
    panel.ctx.calendar.forget()
    panel.refresh()
    assert panel.meeting_line is not None  # closed since the morning's read: that list stays
    panel.ctx.calendar = TodayCalendar(read=panel.ctx.calendar.read)  # closed all day
    panel.refresh()
    assert panel.meeting_line is None
    assert "Meetings: Outlook isn't open" in [w.text() for w in panel.list_widget.findChildren(QLabel)]


def test_no_model_change_comes_from_drawing(browse):
    before = Model(browse.conn).tasks.keys()
    browse.render_list()
    assert Model(browse.conn).tasks.keys() == before and meetings.links(browse.conn) == {}
