"""Release 5.131, the quick summary's model (the design workspace's ``docs/mods/quick-summary-plan.md``, decisions 517 to 539):
the subjects and the box's matching, the attention order and quiet, a person's, an agenda's and a label's summary, emails
from or to a person, what's changed, Copy, the agenda's edits, the answer, and the settings. Every name and email here is
made up. No Qt."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo import agenda, edits, msg, summary as qs
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.save import CaptureDraft, SaveError, answer_text, email_rows, save_answer, save_capture
from msg_builder import FakeEmail, build

SETTINGS = Settings(me="P001")  # the sample's owner, named "Me"
TODAY = date(2026, 10, 8)
NOW = datetime(2026, 10, 8, 14, 30)
TOM, MIKE, PRIYA = "P003", "P004", "P002"
MEETING, REACTOR, INSTALLATION, MONITORING, RIGGING, ALIGNMENT = "T000010", "T000001", "T000008", "T000011", "T000012", "T000019"


def builder(conn, today: date = TODAY, quiet_days: int = 21) -> qs.Builder:
    return qs.Builder(Model(conn), today, "P001", conn, quiet_days)


def summary_of(conn, key: str, today: date = TODAY, more=()) -> qs.Summary:
    b = builder(conn, today)
    s = qs.subject_of(b.m, key, "P001")
    assert s is not None
    return b.build(s, more)


# ---- subjects and the box (decisions 519 and 520) ----
def test_subjects_are_people_agendas_and_labels_without_the_owner(sample_conn):
    m = Model(sample_conn)
    subs = qs.subjects(m, "P001")
    keys = [s.key for s in subs]
    assert "person:P001" not in keys and "person:P004" in keys
    assert "agenda:T000010" in keys  # the open meeting
    assert {"label:Safety", "label:Line 1"} <= set(keys)
    assert all(not k.startswith("agenda:P") for k in keys)  # a person's agenda is their summary's, not an agenda of its own
    assert qs.subject_of(m, "person:P001", "P001") is None  # the owner
    assert qs.subject_of(m, "agenda:T000005", "P001") is None  # closed, and nothing on its agenda
    assert qs.subject_of(m, "label:Nothing", "P001") is None


def test_the_box_matches_from_the_start_of_a_word_and_at_keeps_to_people(sample_conn):
    m = Model(sample_conn)
    subs = qs.subjects(m, "P001")
    names = lambda q: [s.name for s in qs.matches(m, subs, q)]  # noqa: E731
    assert names("mi") == ["Mike Ortiz"]
    assert names("orti") == ["Mike Ortiz"]
    assert names("busi") == ["Business team meeting"]
    assert names("saf") == ["Safety"]
    assert set(names("@t")) == {"Tom Becker", "Tyler Nguyen", "Todd"}  # @ keeps to people; Thomas is Tom's alias
    assert names("michael") == ["Mike Ortiz"]  # an alias
    assert names("meeting team") == ["Business team meeting"]  # words in any order
    assert names("zzz") == []


def test_start_list_is_pinned_then_recent_once_each_and_nothing_gone(sample_conn):
    m = Model(sample_conn)
    pinned, recent = qs.start_list(m, "P001", ["agenda:T000010", "person:P004"], ["label:Safety", "person:P001", "person:P004", "label:Gone", "person:P003"])
    assert [s.key for s in pinned] == ["agenda:T000010", "person:P004"]
    assert [s.key for s in recent] == ["label:Safety", "person:P003"]  # the owner, a pinned one and a gone one left out
    assert qs.remember(["a", "b", "c"], "b") == ["b", "a", "c"]
    assert len(qs.remember([f"k{i}" for i in range(20)], "new")) == qs.RECENT_KEEP


def test_count_lines_say_what_waits(sample_conn):
    b = builder(sample_conn)
    assert b.count_line(qs.subject_of(b.m, "person:P003", "P001")) == "1 to raise · 2 with you"
    assert b.count_line(qs.subject_of(b.m, "agenda:T000010", "P001")) == "4 to raise"
    assert b.count_line(qs.subject_of(b.m, "label:Safety", "P001")) == "5 open"


# ---- the attention order and quiet (decisions 523 and 524) ----
def test_attention_order_is_late_then_urgent_or_critical_then_by_date(sample_conn):
    sample_conn.execute("UPDATE tasks SET priority = 'critical' WHERE id = ?", (MONITORING,))
    m = Model(sample_conn)
    today = date(2026, 10, 15)
    ids = ["T000017", MONITORING, RIGGING, ALIGNMENT, "T000016", "T000009"]
    order = [t.id for t in qs.attention(m, ids, today)]
    # Late first (alignment 9 Oct, rigging 14 Oct), then Critical (the monitoring plan, 23 Oct), then by date, no date last.
    assert order == [ALIGNMENT, RIGGING, MONITORING, "T000017", "T000009", "T000016"]


def test_quiet_after_the_settings_days_in_grey(sample_conn):
    late = date(2026, 12, 1)
    b = builder(sample_conn, late)
    t = b.m.task(RIGGING)
    assert b.quiet(t) >= 21
    assert "quiet" in b.task_row(t) and 'class="routine"' in b.task_row(t)  # grey, never red (decision 524)
    assert builder(sample_conn, TODAY).quiet(t) == 0
    assert qs.Builder(Model(sample_conn), late, "P001", sample_conn, quiet_days=400).quiet(t) == 0


def test_a_rows_date_is_red_when_late_and_amber_within_two_days(sample_conn):
    b = builder(sample_conn, date(2026, 10, 12))
    assert b.when(b.m.task(ALIGNMENT))[:2] == ("3 d late", "over")
    assert b.when(b.m.task(RIGGING))[1] == "caution"  # 14 Oct, in 2 days
    assert b.when(b.m.task("T000009"))[1] == "rel"
    assert b.when(b.m.task("T000016"))[:2] == ("No date", "faint")


# ---- a person (decisions 525 and 529) ----
def test_a_persons_summary_leads_with_their_agenda_then_who_acts(sample_conn):
    s = summary_of(sample_conn, "person:P003")
    assert [x.key for x in s.sections][:2] == ["agenda", "waiting_on"]
    ag = s.section("agenda")
    assert ag.add_to == TOM and len(ag.agenda) == 1
    row = ag.agenda[0]
    assert row.task == MONITORING and row.question.startswith("Ask Tom whether the monitoring plan")
    assert row.about.startswith("Draft monitoring plan")
    waiting = s.section("waiting_on")
    assert waiting.title == "Waiting on Tom"
    assert "Installation" in waiting.body and "Reactor impeller upgrade" in waiting.body
    assert "Draft monitoring plan" not in waiting.body  # on the agenda, so not listed again
    assert s.chips[0].kind == "raise" and s.chips[0].text == "1 to raise"
    assert ("Last talked", "Not on record") in s.facts
    assert s.kind_line == "Person · Planner · Maintenance"


def test_waiting_on_you_is_what_they_lead_and_you_do(sample_conn):
    s = summary_of(sample_conn, "person:P002")  # Priya leads the monitoring plan and the meeting; the owner is on neither as assignee
    b = builder(sample_conn)
    on, you, other = b.person_lists(PRIYA)
    assert MONITORING in other and MEETING not in (*on, *you, *other)  # a meeting is an agenda, not work
    sample_conn.execute("INSERT INTO task_people (task, person, role) VALUES (?, 'P001', 'assignee')", (MONITORING,))
    on, you, other = builder(sample_conn).person_lists(PRIYA)
    assert MONITORING in you
    s = summary_of(sample_conn, "person:P002")
    assert s.section("waiting_you").title == "Priya's waiting on you"
    assert s.section("other") is None or MONITORING not in s.section("other").body


def test_other_work_is_folded_with_its_counts(sample_conn):
    s = summary_of(sample_conn, "person:P004")
    other = s.section("other")
    assert other.folded and other.title == "Mike's other work"
    assert "Rigging plan" in other.body and other.extra  # "none due this week" or its counts


def test_last_talked_is_the_last_discussed_on_their_agenda(sample_conn):
    item = agenda.add_item(sample_conn, subject=None, target=TOM, note="Gearbox spares", added="2026-10-02 09:00:00", added_by="test")
    agenda.close_item(sample_conn, item, how="Discussed", closed="2026-10-05 10:00:00", closed_by="test")
    s = summary_of(sample_conn, "person:P003")
    assert ("Last talked", "Mon 5 Oct · 3 d") in s.facts
    changed = s.section("changed")
    assert changed is None or changed.extra == "since Mon 5 Oct, when you last talked"


def test_nothing_to_raise_is_said_in_the_headline(sample_conn):
    s = summary_of(sample_conn, "person:P004")
    assert s.chips[0].kind == "calm" and s.chips[0].text == "Nothing to raise with Mike"


# ---- an agenda ----
def test_an_agendas_items_put_late_or_urgent_first_then_the_oldest(sample_conn):
    sample_conn.execute("UPDATE tasks SET urgent = 1 WHERE id = 'T000016'")
    s = summary_of(sample_conn, "agenda:T000010")
    rows = s.section("agenda").agenda
    assert rows[0].task == "T000016" and rows[0].urgent  # urgent first
    assert [r.task for r in rows[1:]] == [REACTOR, "T000015", None]  # then the oldest first; the note added last
    assert rows[-1].about.startswith("A note · waiting")
    assert ("Last discussed", "Tue 6 Oct") in s.facts and ("Next", "Tue 13 Oct") in s.facts
    disc = s.section("discussed")
    assert disc.folded and "crane booking" in disc.body
    assert s.kind_line.startswith("Agenda · Meeting")


# ---- a label (decision 532) ----
def test_a_label_puts_where_they_stand_first(sample_conn):
    sample_conn.execute("UPDATE tasks SET priority = 'high' WHERE id = 'T000017'")
    s = summary_of(sample_conn, "label:Safety")
    assert [x.key for x in s.sections][:3] == ["where", "need", "rest"]
    where = s.section("where")
    assert 'src="stack:' in where.body and 'src="spark:' in where.body and "Verification walkthrough readiness" in where.body
    need = s.section("need")
    assert "Book the alignment contractor" in need.body and "Rails need to be painted red" in need.body
    assert s.section("rest").folded
    assert s.chips[0].text == "5 open in 3 projects"
    assert s.markdown.startswith("Safety: 5 open in 3 projects.") and "Focus:" in s.markdown


def test_a_parent_label_groups_by_its_sublabels(sample_conn):
    sample_conn.execute("INSERT INTO labels (name, status) VALUES ('Plant', 'active')")
    pid = sample_conn.execute("SELECT id FROM labels WHERE name = 'Plant'").fetchone()[0]
    sample_conn.execute("UPDATE labels SET parent = ? WHERE name IN ('Line 1', 'Line 2')", (pid,))
    s = summary_of(sample_conn, "label:Plant")
    assert "Line 1" in s.section("where").body and s.section("where").extra == "by label, split by priority"
    assert "labels under it" in s.kind_line


def test_the_trend_counts_what_was_open_each_week(sample_conn):
    b = builder(sample_conn)
    trend = b.trend(b.label_task_ids("Safety"))
    assert len(trend) == qs.TREND_WEEKS and trend[-1] >= 5 and trend[0] <= trend[-1]


# ---- emails (decision 530) ----
def _email(conn, root, fs, sender: str, to: str, subject: str, task: str | None, at: datetime) -> str:
    e = msg.read(build(FakeEmail(subject=subject, sender=sender, to=to, body="Made up.", sent=at.astimezone())))
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(content="", task=task, files=email_rows(e)[:1]), at)
    assert r.capture_id
    return r.capture_id


def test_a_persons_emails_are_from_them_or_to_them(sample_root):
    conn, root, fs = sample_root
    _email(conn, root, fs, "Mike Ortiz", "Me", "Crane booking", RIGGING, datetime(2026, 10, 6, 9, 0))
    _email(conn, root, fs, "Me", "Mike Ortiz; Tom Becker", "Lift drawings", INSTALLATION, datetime(2026, 10, 7, 9, 0))
    _email(conn, root, fs, "Tyler Nguyen", "Me", "Seal quote", None, datetime(2026, 10, 7, 10, 0))
    s = summary_of(conn, "person:P004")
    emails = s.section("emails")
    assert emails.count == "2"
    assert "Crane booking" in emails.body and "Lift drawings" in emails.body and "Seal quote" not in emails.body
    assert emails.body.index("Lift drawings") < emails.body.index("Crane booking")  # the newest first
    assert "your turn" in emails.body  # Mike wrote the crane booking's newest
    assert "↗ Rigging plan" in emails.body and "You wrote last" in emails.body


def test_a_labels_emails_are_on_its_tasks(sample_root):
    conn, root, fs = sample_root
    _email(conn, root, fs, "Tyler Nguyen", "Me", "Alignment dates", ALIGNMENT, datetime(2026, 10, 7, 9, 0))
    assert "Alignment dates" in summary_of(conn, "label:Safety").section("emails").body


def test_five_emails_then_show_ten(sample_root):
    conn, root, fs = sample_root
    for i in range(7):
        _email(conn, root, fs, "Mike Ortiz", "Me", f"Subject {i}", RIGGING, datetime(2026, 10, 1 + i, 9, 0))
    s = summary_of(conn, "person:P004")
    assert s.section("emails").body.count("ft:mail") == 5 and "Show 7" in s.section("emails").body
    assert summary_of(conn, "person:P004", more={"emails"}).section("emails").body.count("ft:mail") == 7


# ---- what's changed (decision 531) ----
def test_whats_changed_counts_then_one_line_per_task(sample_conn):
    s = summary_of(sample_conn, "label:Line 1")
    changed = s.section("changed")
    assert changed.title == "What's changed" and changed.extra == "since Tue 8 Sep"
    assert changed.action == (qs.activity_href(s.subject, date(2026, 9, 8)), "Show in Activity")
    assert changed.body.count('href="task:') <= qs.CHANGED_TASKS
    assert "new" in changed.body and "updates" in changed.body


def test_the_activity_link_names_the_subject_and_the_day(sample_conn):
    s = qs.Subject(qs.LABEL, "Line 1", "Line 1")
    href = qs.activity_href(s, date(2026, 9, 8))
    assert qs.activity_window(href) == ("label", "Line 1", date(2026, 9, 8))
    assert qs.activity_window("activity:nope:x:2026-01-01") is None
    assert qs.activity_window("task:T000001") is None


# ---- Copy (decision 533) ----
def test_copy_is_tick_boxes_in_the_windows_order_then_what_needs_a_word(sample_conn):
    s = summary_of(sample_conn, "person:P003", date(2026, 10, 29))
    assert s.markdown.startswith("## Tom Becker: to raise\n\n- [ ] Ask Tom whether the monitoring plan")
    assert "### Needs a word" in s.markdown and "Installation" in s.markdown  # due 30 Oct, tomorrow
    assert "<ul>" in s.html and "☐" in s.html


# ---- the agenda's edits and the answer (decisions 526 and 527) ----
def test_adding_to_an_agenda_from_the_summary(sample_root):
    conn, root, fs = sample_root
    out = edits.add_agenda_item(conn, root, fs, TOM, None, "  Ask about   the gearbox  ", NOW)
    assert out.message == "Added to Tom Becker's agenda as a note."
    a = Model(conn).open_items_for(TOM)[-1]
    assert a.note == "Ask about the gearbox" and a.added_by == edits.SUMMARY and a.subject is None
    out = edits.add_agenda_item(conn, root, fs, TOM, RIGGING, "Crane quote?", NOW)
    assert out.message == "Added to Tom Becker's agenda, on Rigging plan."
    assert edits.add_agenda_item(conn, root, fs, TOM, RIGGING, "again", NOW).message == "Rigging plan is on that agenda already."


def test_discussed_then_undone(sample_root):
    conn, root, fs = sample_root
    item = Model(conn).open_items_for(TOM)[0].id
    edits.discuss_agenda_item(conn, root, fs, item, NOW)
    a = next(x for x in Model(conn).agenda if x.id == item)
    assert a.how == "Discussed" and a.closed_by == edits.SUMMARY
    edits.reopen_agenda_item(conn, root, fs, item, NOW)
    assert any(x.id == item for x in Model(conn).open_items_for(TOM))


def test_an_answer_lands_on_the_items_task(sample_root):
    conn, root, fs = sample_root
    item = Model(conn).open_items_for(TOM)[0]
    assert answer_text(Model(conn), item, " It should,  yes. ").startswith('Tom Becker, on "Ask Tom whether the monitoring plan')
    r = save_answer(conn, root, fs, SETTINGS, item.id, "It should, yes.", NOW)
    assert r.noted_on == MONITORING  # a note on its task, on its notes page, as the capture window saves one
    assert "It should, yes." in Model(conn).pages[MONITORING]


def test_a_note_items_answer_goes_on_the_meeting_or_to_unfiled(sample_root):
    conn, root, fs = sample_root
    note_on_meeting = next(a for a in Model(conn).open_items_for(MEETING) if a.subject is None)
    r = save_answer(conn, root, fs, SETTINGS, note_on_meeting.id, "Not yet: by Friday.", NOW)
    assert r.noted_on == MEETING
    on_person = agenda.add_item(conn, subject=None, target=TOM, note="Saturday call-out?", added="2026-10-08 09:00:00", added_by="test")
    r = save_answer(conn, root, fs, SETTINGS, on_person, "His crew can.", NOW)
    c = Model(conn).captures[r.capture_id]
    assert Model(conn).is_unfiled(c)
    with pytest.raises(SaveError):
        save_answer(conn, root, fs, SETTINGS, on_person, "   ", NOW)


# ---- settings (decisions 524 and 534) ----
def test_settings_keep_pins_recents_and_quiet_days(tmp_path, fs):
    s = Settings(me="P001", summary_pins=["agenda:T000010"], summary_recent=["person:P004"], quiet_days=30)
    fs_root = SafeFSRoot(tmp_path)
    s.save(fs_root.fs, tmp_path)
    back = Settings.load(tmp_path)
    assert back.summary_pins == ["agenda:T000010"] and back.summary_recent == ["person:P004"] and back.quiet_days == 30
    Settings(me="P001").save(fs_root.fs, tmp_path)
    text = (tmp_path / "Config" / "settings.json").read_text(encoding="utf-8")
    assert "summary_pins" not in text and "summary_recent" not in text and "quiet_days" not in text  # the default isn't written


def test_settings_leave_out_bad_pins_and_quiet_days(tmp_path):
    (tmp_path / "Config").mkdir()
    (tmp_path / "Config" / "settings.json").write_text('{"summary_pins": "person:P004", "summary_recent": [1, 2], "quiet_days": 0}', encoding="utf-8")
    s = Settings.load(tmp_path)
    assert s.summary_pins == [] and s.summary_recent == [] and s.quiet_days == 21


class SafeFSRoot:
    def __init__(self, root) -> None:
        from docrepo.safe_fs import SafeFS

        self.fs = SafeFS([root])


# ---- tagged labels and several together (decisions 555 to 562) ----
def _tag(conn) -> None:
    from docrepo import tagged

    tagged.add_label(conn, "P-204B", datetime(2026, 10, 1, 9, 0), "Feed pump B")
    conn.execute("UPDATE tasks SET description = 'The seal on P-204B leaks' WHERE id = ?", (RIGGING,))


def test_a_tagged_label_is_a_subject(sample_conn):
    _tag(sample_conn)
    m = Model(sample_conn)
    s = qs.subject_of(m, "tag:P204B", "P001")
    assert s == qs.Subject(qs.TAG, "P204B", "P-204B")
    assert [x.key for x in qs.matches(m, qs.subjects(m, "P001"), "p204")] == ["tag:P204B"]  # however it's typed
    out = builder(sample_conn).build(s)
    assert out.kind_line == "Tagged label · Feed pump B" and out.face == "tag"
    assert "Rigging plan" in out.text() and builder(sample_conn).count_line(s) == "1 open"


def test_combine_keeps_each_once_and_round_trips(sample_conn):
    m = Model(sample_conn)
    mike, safety = qs.subject_of(m, "person:P004"), qs.subject_of(m, "label:Safety")
    both = qs.combine([mike, safety, mike])
    assert both.kind == qs.MANY and both.key == "person:P004 + label:Safety" and both.name == "Mike Ortiz + Safety"
    assert qs.subject_of(m, both.key, "P001") == both
    assert qs.subject_of(m, "person:P004 + label:Gone", "P001") == mike  # a part that's gone is left out
    assert qs.combine([]) is None and qs.combine([mike]) == mike
    assert qs.combine([both, qs.subject_of(m, "person:P003")]).each()[-1].ref == TOM


def test_either_within_a_kind_and_both_across_kinds(sample_conn):
    b = builder(sample_conn)
    m = b.m
    union = b.chosen_tasks(qs.subject_of(m, "label:Safety + label:Profitability", "P001"))
    assert set(b.label_task_ids("Safety")) | set(b.label_task_ids("Profitability")) == set(union)
    mike_line1 = b.chosen_tasks(qs.subject_of(m, "person:P004 + label:Line 1", "P001"))
    assert RIGGING in mike_line1 and "T000018" not in mike_line1  # rigging is Line 1's (inherited); the guard drawings are Safety's
    mike_safety = b.chosen_tasks(qs.subject_of(m, "person:P004 + label:Safety", "P001"))
    assert "T000018" in mike_safety and RIGGING not in mike_safety
    assert b.chosen_tasks(qs.subject_of(m, "agenda:T000010 + person:P003", "P001")) == b.chosen_tasks(qs.subject_of(m, "person:P003", "P001"))
    assert b.chosen_tasks(qs.subject_of(m, "agenda:T000010", "P001")) is None  # agendas narrow nothing


def test_two_people_get_each_agenda_and_rows_that_name_them(sample_conn):
    s = summary_of(sample_conn, "person:P003 + person:P004")
    assert [x.key for x in s.sections][:2] == ["agenda:P003", "agenda:P004"]
    assert s.section("agenda:P003").title == "Tom's agenda" and s.section("agenda:P003").add_to == TOM
    body = (s.section("need") or s.section("rest")).body + (s.section("rest").body if s.section("rest") else "")
    assert "Tom" in body and "Mike" in body
    assert s.kind_line == "Together · 2 people" and s.face == "many"


def test_an_agenda_isnt_narrowed_by_a_label(sample_conn):
    s = summary_of(sample_conn, "person:P003 + label:Profitability")
    rows = s.section("agenda:P003").agenda
    assert rows and rows[0].task == MONITORING  # on Tom's agenda, though the monitoring plan isn't Profitability's
    assert s.section("waiting_on") is None and s.section("other") is None or MONITORING not in (s.section("other").body if s.section("other") else "")


def test_a_combinations_emails_follow_its_kinds(sample_root):
    conn, root, fs = sample_root
    _email(conn, root, fs, "Mike Ortiz", "Me", "Crane booking", RIGGING, datetime(2026, 10, 6, 9, 0))
    _email(conn, root, fs, "Mike Ortiz", "Me", "Guard drawings", "T000018", datetime(2026, 10, 7, 9, 0))
    with_label = summary_of(conn, "person:P004 + label:Line 1").section("emails").body
    assert "Crane booking" in with_label and "Guard drawings" not in with_label  # on the tasks both choose
    people_only = summary_of(conn, "person:P004 + person:P003").section("emails").body
    assert "Crane booking" in people_only and "Guard drawings" in people_only  # from or to either


def test_copy_names_each_agenda_then_what_needs_a_word(sample_conn):
    s = summary_of(sample_conn, "person:P003 + agenda:T000010", date(2026, 10, 29))
    assert s.markdown.startswith("## Tom's agenda: to raise\n\n- [ ] Ask Tom whether")
    assert "## Business team meeting: to raise" in s.markdown and "needs a word" in s.markdown
    b = builder(sample_conn)
    assert b.count_line(qs.subject_of(b.m, "person:P003 + agenda:T000010", "P001")) == "5 to raise · 3 open"  # Tom has three open tasks, his other work too
