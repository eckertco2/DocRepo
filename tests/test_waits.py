"""Release 5.139, Log progress and waits (the design workspace's docs/mods/email-progress-plan.md, decisions 580 to 598),
without Qt: what Enter keeps, the wait's words, what ends it, the follow-up as the task's Reminder, Ask for an update's
wait, Waiting on others, schema 26 and the Execution wheel's NE. Every name, address and email here is made up."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from docrepo import ask_update, capacity, conversations, db, edits, lists, msg, progress, tasks, waits, wheels_config
from docrepo.config import Settings
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, SaveError, email_rows, save_capture
from msg_builder import FakeEmail, build

SETTINGS = Settings(me="P001")
AT = datetime(2026, 10, 8, 9, 0)  # a Thursday
TODAY = AT.date()
RIGGING, INSTALLATION = "T000012", "T000008"
ME, PRIYA, MIKE = "P001", "P002", "P004"
GUID = bytes.fromhex("0F1E2D3C4B5A69788796A5B4C3D2E1F0")


@pytest.fixture
def env(data_root, fs):
    c = db.connect(fs, data_root)
    load_sample(c)
    capacity.rebuild_all(c, TODAY, SETTINGS)
    yield c, data_root, fs
    c.close()


def logged(env, line: str = "Asked Mike for the crane vendor's quote", on=(MIKE,), choice: str = "3d", at: datetime = AT,
           email: progress.Email | None = None, task: str = RIGGING) -> progress.Logged:
    conn, root, fs = env
    day = progress.follow_up_day(choice, at.date(), range(5))
    return progress.log_progress(conn, root, fs, SETTINGS, task_id=task, line=line, on=list(on), follow_up=day, at=at, email=email, choice=choice)


def reply(env, sender: str = "Mike Ortiz <mike.ortiz@example.com>", index: bytes | None = None, at: datetime = AT + timedelta(days=1),
          task: str = RIGGING) -> str:
    """An email captured on the task, as a drag would save it."""
    conn, root, fs = env
    e = msg.read(build(FakeEmail(subject="RE: Crane quote", sender=sender, conversation_index=index, message_id=f"<{at:%H%M%S}@example.com>",
                                 sent=at.replace(tzinfo=timezone.utc))))
    return save_capture(conn, root, fs, SETTINGS, CaptureDraft(task=task, types={"note"}, files=email_rows(e)), at).capture_id or ""


def set_reminder(env, day: str | None, task: str = RIGGING) -> None:
    tasks.update_task(env[0], SETTINGS, task, at=AT - timedelta(days=1), via="test", reminder=day)


# ================= what Enter keeps (decisions 586 to 591) =================
def test_a_line_with_nobody_waited_on_is_only_logged(env):
    conn = env[0]
    done = logged(env, line="Called the crane vendor", on=())
    m = Model(conn)
    t = m.task(RIGGING)
    assert t.current_status == "Called the crane vendor" and done.wait is None and done.follow_up is None
    assert waits.current(m, RIGGING) is None and t.reminder is None
    c = m.captures[done.capture]
    assert c.types == ["update"] and c.task == RIGGING


def test_a_wait_starts_with_its_follow_up_as_the_reminder(env):
    conn = env[0]
    done = logged(env)
    m = Model(conn)
    w = waits.current(m, RIGGING)
    assert w is not None and w.on == (MIKE,) and w.line == "Asked Mike for the crane vendor's quote" and w.capture == done.capture
    assert w.follow_up == "2026-10-13" and m.task(RIGGING).reminder == "2026-10-13"  # 3 workdays after Thursday: Tuesday
    assert waits.words(m, w, TODAY) == "waiting on Mike since today · follow up Tue"
    assert waits.row_text(m, RIGGING, TODAY + timedelta(days=1)) == "waiting on Mike · Thu"
    assert waits.tip(m, w, TODAY) == ("Waiting on Mike Ortiz since Thu 8 Oct: Asked Mike for the crane vendor's quote. Follow up Tue 13 Oct.")
    assert any(e.field == waits.FIELD and e.to_value == "Mike Ortiz" for e in m.status if e.task == RIGGING)


def test_a_not_started_task_goes_in_progress(env):
    conn = env[0]
    tid = tasks.create_task(conn, SETTINGS, title="Order the spare seal", at=AT, created_by="test", state="Not started")
    done = logged(env, task=tid, on=())
    assert done.state == "In progress" and Model(conn).task(tid).state == "In progress"


def test_nothing_is_kept_without_a_line_or_on_a_closed_task(env):
    conn = env[0]
    with pytest.raises(SaveError):
        logged(env, line="  ")
    tasks.update_task(conn, SETTINGS, INSTALLATION, at=AT, via="test", state="Closed")
    with pytest.raises(SaveError, match="closed"):
        logged(env, task=INSTALLATION)
    assert Model(conn).waits == []


def test_the_email_is_kept_as_a_progress_t_mail(env):
    conn = env[0]
    index = conversations.new_index(AT, GUID)
    done = logged(env, email=progress.Email("Crane quote", index, "D1", "S1"))
    t = next(x for x in Model(conn).t_mails if x.id == done.t_mail)
    assert (t.kind, t.task, t.conversation) == ("progress", RIGGING, GUID.hex().upper())
    assert waits.current(Model(conn), RIGGING).t_mail == done.t_mail


def test_the_follow_up_choice_is_remembered(env):
    conn = env[0]
    assert progress.last_follow_up(conn) == "3d"
    logged(env, choice="1w")
    assert progress.last_follow_up(conn) == "1w"
    assert progress.follow_up_day("1d", date(2026, 10, 9), range(5)) == date(2026, 10, 12)  # Friday's tomorrow is Monday
    assert progress.follow_up_day("2w", TODAY, range(5)) == date(2026, 10, 22)
    assert progress.follow_up_day("none", TODAY, range(5)) is None


# ================= the reminder (decision 588) =================
def test_an_earlier_reminder_stays_and_the_follow_up_takes_its_place_after(env):
    conn, root, fs = env
    set_reminder(env, "2026-10-09")
    logged(env)  # follow-up Tue 13
    assert Model(conn).task(RIGGING).reminder == "2026-10-09"
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 9, 8, 0))
    assert Model(conn).task(RIGGING).reminder == "2026-10-13"


def test_a_later_reminder_comes_back_after_the_follow_up(env):
    conn, root, fs = env
    set_reminder(env, "2026-10-20")
    logged(env)
    m = Model(conn)
    assert m.task(RIGGING).reminder == "2026-10-13" and waits.current(m, RIGGING).reminder_before == "2026-10-20"
    edits.reminders_to_today(conn, root, fs, SETTINGS, datetime(2026, 10, 13, 8, 0))
    m = Model(conn)
    assert m.task(RIGGING).reminder == "2026-10-20"
    w = waits.current(m, RIGGING)
    assert w.late(date(2026, 10, 13)) and waits.words(m, w, date(2026, 10, 13)) == "no reply from Mike since Thu"


# ================= what ends a wait (decision 581) =================
def test_an_email_from_the_person_waited_on_ends_it_and_its_reminder(env):
    conn = env[0]
    set_reminder(env, "2026-10-20")
    logged(env)
    reply(env)
    m = Model(conn)
    assert waits.current(m, RIGGING) is None and m.waits[-1].ended_by == "reply"
    assert m.task(RIGGING).reminder == "2026-10-20"  # the task's own comes back


def test_an_email_from_someone_else_doesnt(env):
    conn = env[0]
    logged(env)
    reply(env, sender="Ann Example <ann@example.com>")
    assert waits.current(Model(conn), RIGGING) is not None


def test_a_reply_in_its_conversation_ends_it_but_its_own_sent_copy_doesnt(env):
    conn = env[0]
    index = conversations.new_index(AT, GUID)
    logged(env, email=progress.Email("Crane quote", index))
    reply(env, sender="Owner Example <owner@example.com>", index=bytes.fromhex(index))  # the sent copy: the same whole index
    assert waits.current(Model(conn), RIGGING) is not None
    reply(env, sender="Dana Example <dana@example.com>", index=bytes.fromhex(index) + bytes([0x80, 0, 0, 0, 1]))  # Dana answers for Mike
    m = Model(conn)
    assert waits.current(m, RIGGING) is None and m.task(RIGGING).reminder is None


def test_got_it_ends_it_and_takes_its_reminder(env):
    conn = env[0]
    logged(env)
    assert progress.got_it(conn, SETTINGS, RIGGING, AT + timedelta(hours=2))
    m = Model(conn)
    assert waits.current(m, RIGGING) is None and m.waits[-1].ended_by == "got it" and m.task(RIGGING).reminder is None
    assert not progress.got_it(conn, SETTINGS, RIGGING, AT + timedelta(hours=3))


def test_a_newer_log_progress_starts_the_next_wait(env):
    conn = env[0]
    logged(env)
    logged(env, line="Followed up with Mike and Priya", on=(MIKE, PRIYA), choice="1w", at=AT + timedelta(days=5))
    m = Model(conn)
    first, second = m.waits
    assert first.ended_by == "logged again" and waits.current(m, RIGGING) == second
    assert waits.who(m, second) == "Mike and Priya" and m.task(RIGGING).reminder == second.follow_up


def test_closing_the_task_ends_it(env):
    conn = env[0]
    logged(env)
    tasks.update_task(conn, SETTINGS, RIGGING, at=AT, via="test", state="Closed")
    assert waits.current(Model(conn), RIGGING) is None


def test_more_people_read_short():
    m = SimpleModel({"P1": "Dana Ortiz", "P2": "Mike Ortiz", "P3": "Priya Shah"})
    w = waits.Wait(1, "T1", "2026-10-08 09:00:00", "", ("P1", "P2", "P3"), None, None, None, None, None, None)
    assert waits.who(m, w) == "Dana and 2 more" and waits.who(m, w, full=True) == "Dana Ortiz, Mike Ortiz and Priya Shah"
    assert waits.day_words("2026-09-30 09:00:00", TODAY) == "30 Sep"


class SimpleModel:
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    def person_name(self, p: str) -> str:
        return self.names[p]


# ================= where it shows =================
def test_waiting_on_others_lists_a_waiting_task_by_its_follow_up(env):
    conn = env[0]
    tid = tasks.create_task(conn, SETTINGS, title="Seal drawings", at=AT, created_by="test", state="In progress", leads=[ME])
    waiting = next(x for x in lists.LISTS if x.id == "waiting")
    assert tid not in [t.id for t in lists.list_tasks(Model(conn), waiting, TODAY, ME)]
    logged(env, task=tid, choice="1d")
    found = [t.id for t in lists.list_tasks(Model(conn), waiting, TODAY, ME)]
    assert found[0] == tid  # the soonest follow-up first


def test_ask_for_an_update_starts_a_wait_on_the_people_asked(env):
    conn = env[0]
    t_mail = conversations.record_t_mail(conn, RIGGING, ask_update.KIND, "2026-10-08 09:00:00", "", untagged=True)
    assert ask_update.start_wait(conn, SETTINGS, RIGGING, t_mail, AT) is not None
    m = Model(conn)
    w = waits.current(m, RIGGING)
    assert w.on == (MIKE,) and w.line == "Asked Mike for an update" and w.t_mail == t_mail and w.follow_up == "2026-10-13"
    assert m.task(RIGGING).reminder == "2026-10-13"


def test_people_and_task_from_the_email(env):
    conn = env[0]
    m = Model(conn)
    assert progress.people_in(m, "Mike Ortiz <mike.ortiz@example.com>; Owner Example", ME) == [MIKE]
    assert progress.people_in(m, "Someone Else <someone@example.com>", ME) == []
    index = conversations.new_index(AT, GUID)
    logged(env, email=progress.Email("Crane quote", index))
    answer = progress.Email("RE: Crane quote", index + "8000000001")
    assert progress.task_for(Model(conn), answer) == (RIGGING, "from conversation")
    assert progress.task_for(Model(conn), progress.Email("Unrelated", "")) == (None, "")


# ================= schema 26, and the wheel =================
def test_t_mails_take_progress_and_waits_end_only_three_ways(env):
    conn = env[0]
    conn.execute("INSERT INTO t_mails (task, kind, opened) VALUES (?, 'progress', '2026-11-11 09:00:00')", (RIGGING,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO waits (task, since, ended, ended_by) VALUES (?, '2026-11-11', '2026-11-12', 'forgot')", (RIGGING,))
    assert db.SCHEMA_VERSION >= 26


def test_the_execution_wheel_gets_log_progress_once():
    old = wheels_config.DEFAULT_TEXT.replace(wheels_config._NE_SLOTS, wheels_config._OLD_W_SLOT)
    assert old != wheels_config.DEFAULT_TEXT and "progress.log" not in old
    assert wheels_config.progress_slot(old) == wheels_config.DEFAULT_TEXT
    assert wheels_config.progress_slot(wheels_config.DEFAULT_TEXT) == wheels_config.DEFAULT_TEXT
    changed = old.replace('"label": "Find files"', '"label": "Files"')  # a wheel the owner changed stays theirs
    assert wheels_config.progress_slot(changed) == changed


# ================= outlook.py's side, with fake COM objects (decisions 584 and 590) =================
class _Draft:
    Class, Sent = 43, False

    def __init__(self, subject: str = "Crane quote", entry: str = "") -> None:
        self.Subject, self.EntryID, self.ConversationIndex = subject, entry, ""
        self.Parent = SimpleNamespaceLike(StoreID="S1")
        self.events: list[str] = []
        self.inspector = SimpleNamespaceLike(Activate=lambda: self.events.append("activate"))

    def Save(self):  # noqa: N802 - Outlook's name
        self.events.append("save")
        self.EntryID = "D1"

    def Send(self):  # noqa: N802
        self.events.append("send")

    @property
    def GetInspector(self):  # noqa: N802
        return self.inspector

    @property
    def Body(self):  # noqa: N802
        raise AssertionError("Log progress must not read an email's body")


class SimpleNamespaceLike:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


def _outlook_with(monkeypatch, window_class: int, current=None, inline=None):
    from docrepo import outlook

    explorer = SimpleNamespaceLike(ActiveInlineResponse=inline, Activate=lambda: None)
    window = SimpleNamespaceLike(Class=window_class, CurrentItem=current)
    app = SimpleNamespaceLike(ActiveWindow=lambda: window, ActiveExplorer=lambda: explorer, ActiveInspector=lambda: window)
    monkeypatch.setattr(outlook, "outlook_window_open", lambda: True)
    monkeypatch.setattr(outlook, "connect", lambda: (app, "GetActiveObject"))
    return outlook


def test_the_draft_in_its_own_window_is_saved_for_its_place_and_read_without_its_body(monkeypatch):
    d = _Draft()
    outlook = _outlook_with(monkeypatch, 35, current=d)
    found = outlook.front_draft(None)
    assert found is not None and not found.inline and (found.subject, found.entry_id, found.store_id) == ("Crane quote", "D1", "S1")
    assert d.events == ["save"]


def test_an_inline_reply_is_found_in_the_main_window(monkeypatch):
    d = _Draft("RE: Crane quote", entry="D2")
    outlook = _outlook_with(monkeypatch, 34, inline=d)
    found = outlook.front_draft(None)
    assert found is not None and found.inline and found.entry_id == "D2" and d.events == []


def test_no_email_being_written_is_none(monkeypatch):
    outlook = _outlook_with(monkeypatch, 34, inline=None)
    assert outlook.front_draft(None) is None
    sent = _Draft()
    sent.Sent = True
    outlook = _outlook_with(monkeypatch, 35, current=sent)
    assert outlook.front_draft(None) is None


def test_send_holds_it_a_minute_and_an_inline_reply_is_never_sent(monkeypatch):
    d = _Draft(entry="D1")
    outlook = _outlook_with(monkeypatch, 35, current=d)
    found = outlook.front_draft(None)
    outlook.send_draft(found, AT)
    assert d.events == ["send"] and d.DeferredDeliveryTime == AT + timedelta(minutes=1)
    inline = outlook.FrontDraft(_Draft(entry="D2"), True, "RE: x", "", "D2", "S1", None)
    with pytest.raises(outlook.OutlookError):
        outlook.send_draft(inline, AT)
    assert inline.item.events == []
    assert outlook.show_draft(found) and d.events[-1] == "activate"
