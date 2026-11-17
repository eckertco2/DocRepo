"""A busy task's page, faster (release 5.161, the design workspace's ``docs/mods/busy-page-plan.md``, decisions 738 and 739).

``Stories`` now looks up what each capture did on a task, where each raw text log entry went through the whole status log
and the whole agenda before; each task's Update captures, where each task's updates went through every capture; and each
task's agenda, where each story went through the whole agenda. ``Before`` keeps the code as release 5.155 had it, and
these tests check that the stories, and the pages built from them, are the same line for line: every page of the sample
data, the large made-up project's (``load-sample --large``), and a made-up busy page with updates, agenda items, emails,
files, decisions and follow-ups. Every name and word here is made up.
"""
from __future__ import annotations

import functools
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pytest

from docrepo import db, edits, msg
from docrepo.captures import read_content
from docrepo.dates import short, to_date
from docrepo.detail import PageState, Pages
from docrepo.model import TODAY, Capture, Model, StatusEntry
from docrepo.safe_fs import SafeFS
from docrepo.sample import load_sample, read_sample, write_sample_files
from docrepo.sample_large import add_large_project, project_id
from docrepo.save import CaptureDraft, EmailItem, FileRow, email_rows, save_capture
from docrepo.stories import Event, RawItem, Stories, Update, clip, is_none, list_of, state_words
from msg_builder import FakeEmail, build as build_msg
from notes_example import SETTINGS, build as build_example

DAY = date(2026, 12, 24)


class Before(Stories):
    """Stories as release 5.155 had them, kept here to compare with: ``note_item``, ``updates`` and ``story`` as they were."""

    def updates(self, task_id: str) -> list[Update]:
        t = self.m.task(task_id)
        entries = self.log(task_id)
        groups: list[dict] = []
        for e in entries:
            g = next((x for x in groups if x["at"] == e.at and x["via"] == e.via), None)
            if g is None:
                g = {"at": e.at, "via": e.via, "changes": []}
                groups.append(g)
            g["changes"].append(e)
        for c in self.m.captures.values():
            if c.task == task_id and c.has("update") and not any(g["via"] == c.id for g in groups):
                groups.append({"at": c.saved, "via": c.id, "changes": []})
        groups.sort(key=lambda g: g["at"])

        def first(name: str) -> StatusEntry | None:
            return next((e for e in entries if e.field == name), None)

        first_state, first_status = first("State"), first("Current status")
        state = first_state.from_value if first_state else t.state
        status = ("" if is_none(first_status.from_value) else first_status.from_value) if first_status else t.current_status or ""
        out = []
        for g in groups:
            for e in g["changes"]:
                if e.field == "State":
                    state = e.to_value or ""
                if e.field == "Current status":
                    status = "" if is_none(e.to_value) else e.to_value or ""
            out.append(Update(
                g["at"], g["via"], g["changes"], state or "", status,
                any(e.field == "State" for e in g["changes"]), any(e.field == "Current status" for e in g["changes"]),
                [e for e in g["changes"] if e.field not in ("State", "Current status")],
            ))
        return out

    def story(self, task_id: str) -> list[Event]:
        m, t = self.m, self.m.task(task_id)
        via = t.created_by if self.capture_of(t.created_by) else None
        parents = [p for p in m.parents_of(task_id) if not self.joined_at(task_id, p)]

        def init(name: str, now: str) -> str:
            return self.initial(task_id, name, now)

        recurrence = init("Recurrence", t.recurrence or "")
        deadline_desc = init("Deadline description", t.deadline_desc or "")
        facts = [
            recurrence and f"Repeats {recurrence.lower()}",
            init("Meeting", "Yes" if t.meeting else "") == "Yes" and "Meeting",
            not is_none(init("Lead", self.names(t.leads))) and f"Lead: {init('Lead', self.names(t.leads))}",
            not is_none(init("Assignees", self.names(t.assignees))) and f"Assignees: {init('Assignees', self.names(t.assignees))}",
            init("Due", t.due or "") and f"Due {self.as_date(init('Due', t.due or ''))}",
            init("Deadline", t.deadline or "") and f"Deadline {self.as_date(init('Deadline', t.deadline or ''))}"
            + (f", {deadline_desc}" if deadline_desc else ""),
        ]
        state = init("State", t.state) or t.state
        source = self.capture_of(via)
        how = "import" if t.created_by == "Excel import" else "unfiled" if source and source.filed_to == task_id and source.created_task != task_id else "new"
        events = [Event(self.created_at(task_id), "created", state=state, parents=parents, via=via, text=t.description or "",
                        status=init("Current status", (t.current_status or "") if how == "import" else ""),
                        facts=[x for x in facts if x], how=how)]
        for u in self.updates(task_id):
            before, state = state, u.state
            c = self.capture_of(u.via)
            main = (u.status or "Status cleared.") if u.status_changed else self.gist(c) if c and c.created_task != task_id else ""
            events.append(Event(u.at, "update", state=u.state, state_words=state_words(before, u.state) if u.state_changed else "",
                                main=main, facts=[s for s in (self.field_sentence(e) for e in u.others) if s], via=u.via))
        for k in m.children_of(task_id):
            s = m.task(k)
            joined = self.joined_at(k, task_id)
            verb = "New task under this one" if m.parents_of(k)[0] == task_id and not joined else "Also under this task"
            asg = self.initial(k, "Assignees", self.names(s.assignees))
            due = self.initial(k, "Due", s.due or "")
            who = ", ".join("me" if self._is_me(n) else n for n in list_of(asg))
            note = ", ".join(x for x in (who, not is_none(due) and f"due {short(to_date(due), self.today)}") if x)
            events.append(Event(joined or self.created_at(k), "sub", task=k, verb=verb, note=note))
            st = self.initial(k, "State", s.state) or s.state
            for u in self.updates(k):
                before, st = st, u.state
                if not u.state_changed or not any(x in (u.state, before) for x in ("Closed", "Parked")):
                    continue  # starting work isn't a milestone
                c = self.capture_of(u.via)
                word = "Subtask closed" if u.state == "Closed" else "Subtask parked" if u.state == "Parked" else "Subtask reopened"
                events.append(Event(u.at, "sub", task=k, verb=word,
                                    note=u.status if u.status_changed and u.status else self.gist(c, 140) if c else ""))
        for a in m.agenda:
            if a.target != task_id:
                continue
            events.append(Event(a.added, "sub", task=a.subject, text=a.note, verb="Added to the agenda",
                                note=clip(a.note) if a.subject and a.note else ""))
            if a.closed:
                events.append(Event(a.closed, "sub", task=a.subject, text=a.note,
                                    verb="Taken off the agenda" if a.how == "Removed" else "Discussed"))
        return sorted(events, key=lambda e: (e.at, 0 if e.kind == "created" else 1))

    def note_item(self, c: Capture, task_id: str) -> RawItem:
        content = self.words_of(c)
        sender = re.search(r"^From:\s*(.+)$", content, re.M) if c.source == "outlook_email" else None
        is_update = c.has("update") and c.task == task_id
        kind = (f"Email from {sender.group(1).strip()}" if sender else "Email") if c.source == "outlook_email" \
            else "File" if c.source == "file_path" else "Update" if is_update else "Decision" if c.item == "decision" else "Note"
        said = []
        for e in self.m.status:
            if e.via == c.id and e.task == task_id:
                said.append(state_words(e.from_value or "", e.to_value or "") + "." if e.field == "State"
                            else "New current status." if e.field == "Current status" else self.field_sentence(e))
        for a in self.m.agenda:
            if a.added_by == c.id and a.subject == task_id:
                said.append(self.field_sentence(StatusEntry(task_id, a.added, "Agenda", None, self.m.target_name(a.target), c.id, a.target)))
        update = " ".join(s for s in said if s)
        did = ("Started this task" if c.created_task == task_id
               else ("" if c.source == "typed" else "Update: ") + update if is_update
               else f"Filed {short(to_date(c.filed), self.today)}" if c.filed_to == task_id and c.filed else "")
        docs = tuple((d, self.m.documents[d].name, self.m.documents[d].description or "") for d in c.document_ids if d in self.m.documents)
        notes = self.m.captures.get(c.from_notes) if c.from_notes else None
        held = self.m.capture_tasks(notes) if notes else []
        return RawItem(c.saved, " · ".join(x for x in (kind, did) if x), c.title, c.id, None, self.capture_body(c), c.summary,
                       c.summary_type, "The email" if c.source == "outlook_email" else "The full text", docs, c.formatted,
                       notes.id if notes else None, (self.m.task(held[0]).title if held else notes.id) if notes else "")


def reader(m: Model, root) -> Callable[[str], str]:
    """Captures' content text, each read once, as the browse tool reads it once until its file changes."""
    return functools.cache(lambda cid: read_content(root, m.captures[cid]) or "" if cid in m.captures else "")


def pages_of(m: Model, root, conn, before: bool = False, content_of: Callable[[str], str] | None = None) -> Pages:
    pages = Pages(m, DAY, content_of or reader(m, root), "P001", conn)
    if before:
        pages.stories = Before(m, DAY, pages.stories.content_of, pages.stories.me_name)
    return pages


def states(m: Model, task_id: str) -> list[PageState]:
    """The page as it opens, and with everything shown: each tab, every scope, both orders, every chapter and entry open."""
    family = set(m.scope_ids(task_id, "family"))
    everything = set(m.captures)
    return [PageState(), PageState(order="new"), PageState(tab="log", scope="family", chapters=family, details=True, closed=True),
            PageState(tab="notes", scope="family", order="new", chapters=family, expanded=everything, originals=everything),
            PageState(tab="summaries", scope="ancestors"), PageState(tab="files", scope="self"),
            PageState(conversations=True, decisions=True, meetings=True, notes_weeks=0)]


def assert_same(m: Model, root, conn, task_ids: list[str], every_state: list[str] | None = None) -> int:
    """The stories and the pages of ``task_ids``, before and after, the same; and every capture's raw text log entry on each
    of its tasks. Each page is compared as it opens, narrow and wide; those in ``every_state`` (all of them, when it's None)
    in each of ``states`` too. Returns how many raw text log entries were compared, so a test can say it compared something."""
    content_of = reader(m, root)
    new, old = Stories(m, DAY, content_of, "Me"), Before(m, DAY, content_of, "Me")
    compared = 0
    for t in task_ids:
        assert new.updates(t) == old.updates(t), t
        assert new.story(t) == old.story(t), t
        got = new.raw_items(t)
        assert got == old.raw_items(t), t
        compared += len(got)
    for c in m.captures.values():
        for t in sorted({c.task, c.created_task, c.filed_to, *m.capture_tasks(c)} - {None, ""}):
            if t in m.tasks:
                assert new.note_item(c, t) == old.note_item(c, t), (c.id, t)
    for t in task_ids:
        full = every_state is None or t in every_state
        shown = [(600, PageState(), PageState())] + [(1300, *pair) for pair in zip(states(m, t), states(m, t), strict=True)
                                                    if full or pair[0] == PageState()]
        for width, st_new, st_old in shown:
            after, before = pages_of(m, root, conn, content_of=content_of), pages_of(m, root, conn, True, content_of)
            assert after.task_page(t, st_new, width) == before.task_page(t, st_old, width), (t, st_new)
            assert after.task_parts(t, st_new, width) == before.task_parts(t, st_old, width), (t, st_new)
            assert after.all_notes(t, st_new)[0] == before.all_notes(t, st_old)[0], (t, st_new)
    return compared


# ================= the sample data's pages =================
def test_every_sample_page_is_the_same(sample_root):
    conn, root, _ = sample_root
    m = Model(conn)
    busiest = max(m.tasks, key=lambda t: (len(m.raw_log_of(t)), len(m.descendants_of(t))))
    assert len(m.raw_log_of(busiest)) >= 4 and len(m.descendants_of(busiest)) >= 7
    assert assert_same(m, root, conn, sorted(m.tasks)) >= 20


@pytest.fixture(scope="module")
def large(tmp_path_factory):
    """A data root holding the sample data and the large made-up project (``load-sample --large``), with its files."""
    root = tmp_path_factory.mktemp("busy-large") / "DocRepoData"
    root.mkdir()
    fs = SafeFS([root])
    conn = db.connect(fs, root)
    data = add_large_project(read_sample())
    load_sample(conn, data)
    write_sample_files(conn, root, fs, data)
    yield conn, root
    conn.close()


def test_the_large_project_s_pages_are_the_same(large):
    """The sample's busiest pages: the large project, with 16 subtasks and 300 notes and updates, and each subtask."""
    conn, root = large
    m = Model(conn)
    project = project_id(conn)
    under = m.descendants_of(project)
    assert len(under) >= 16 and len(m.raw_log_of(project)) + sum(len(m.raw_log_of(t)) for t in under) >= 300
    assert assert_same(m, root, conn, [project, *under], every_state=[project]) >= 300


# ================= a made-up busy page =================
def email(subject: str, sender: str, sent: datetime) -> EmailItem:
    return msg.read(build_msg(FakeEmail(subject=subject, sender=sender, body=f"{subject}: the vendor confirms the dates.",
                                        sent=sent.astimezone(), message_id=f"<{sent:%m%d%H%M}@example.com>")))


@pytest.fixture
def busy(sample_root, tmp_path):
    """The notes example's project (two meetings, their follow-ups and a decision), made busy over six weeks: notes typed on
    its page, updates (its state, current status, due date and lead, some formatted), updates putting it on a person's
    agenda, Today and a meeting's, emails, files and links, unfiled captures filed to it, a discarded update, a subtask
    closed and reopened, another parked, and more meeting notes with a decision and a follow-up."""
    conn, root, fs = sample_root

    def save(draft: CaptureDraft, at: datetime) -> str:
        r = save_capture(conn, root, fs, SETTINGS, draft, at)
        return r.capture_id

    ex = build_example(conn, root, fs)
    p = ex.project
    survey = tmp_path / "Fan deck survey.txt"
    survey.write_text("The east cell's panels are cracked.", encoding="utf-8")
    for week in range(6):
        start = datetime(2026, 11, 12, 8, 0) + timedelta(days=7 * week)

        def at(hours: int, start: datetime = start) -> datetime:
            return start + timedelta(hours=hours)

        save(CaptureDraft(content=f"Walked the fan deck with Tom, week {week + 1}. Access is tight on the east side.\n\n"
                                  "The scaffold goes up first, then the survey.", task=p), at(0))
        survey_line = f"**Survey** under way, *week {week + 1}*.\n\n- east cell first\n- west cell after" if week % 2 else f"Survey under way, week {week + 1}."
        save(CaptureDraft(content=survey_line, formatted=bool(week % 2), task=p, types={"note", "update"},
                          update={"state": "In progress", "current_status": f"Week {week + 1}: survey under way."}), at(1))
        save(CaptureDraft(content="The fill media slips a week.", task=p, types={"update"}, update={"due": f"2026-12-{10 + week:02d}"},
                          agenda=["P003"]), at(2))
        save(CaptureDraft(content="For Today and the weekly.", task=p, types={"update"}, agenda=[TODAY, ex.weekly]), at(3))
        save(CaptureDraft(content="", task=p, files=email_rows(email(f"Fill media delivery {week + 1}", "Sam Kowalski", at(4)))[:1]), at(4))
        save(CaptureDraft(content="The survey's notes and the vendor's datasheet.", task=p,
                          files=[FileRow(survey.name, str(survey), "The survey's notes."),
                                 FileRow("Fill media datasheet", f"https://example.com/fill-media-{week}.pdf", "Vendor B's datasheet.")]), at(5))
        save(CaptureDraft(content=f"**Fill media**: vendor B, *week {week + 1}*.\n\n- two quotes in\n- B is faster", formatted=True, task=p), at(6))
        unfiled = save(CaptureDraft(content=f"Fan blade photos from the site, week {week + 1}."), at(7))
        edits.file_capture(conn, root, fs, unfiled, p, at(8))
        mistake = save(CaptureDraft(content="Parked, by mistake.", task=p, types={"update"}, update={"state": "Parked"}), at(9))
        edits.discard_capture(conn, root, fs, mistake, "Saved on the wrong task", at(10))
        save(CaptureDraft(content="Back on it; Mike leads the lift.", task=p, types={"update"},
                          update={"state": "In progress", "leads": ["P004"] if week % 2 else ["P001"]}), at(11))
    save(CaptureDraft(content="Both quotes in; ordered from B.", task=ex.fill, types={"update"}, update={"state": "Closed"}), datetime(2026, 12, 1, 9, 0))
    save(CaptureDraft(content="B can't deliver after all.", task=ex.fill, types={"update"}, update={"state": "In progress"}), datetime(2026, 12, 2, 9, 0))
    save(CaptureDraft(content="Fan blades: cracked root on blade 3.", task=ex.blades, types={"note", "update"},
                      update={"state": "Parked", "current_status": "Waits for the spare blade."}), datetime(2026, 12, 2, 10, 0))
    save(CaptureDraft(content="- **decision, the east cell goes first.\n- Order spare fill packs @Tyler", task=p, meeting=True,
                      meeting_name="Cooling tower weekly 1 Dec"), datetime(2026, 12, 1, 10, 0))
    return conn, root, ex


def test_a_made_up_busy_page_is_the_same(busy):
    conn, root, ex = busy
    m = Model(conn)
    p = ex.project
    leads = [r.lead for r in Stories(m, DAY, lambda cid: read_content(root, m.captures[cid]) or "", "Me").raw_items(p)]
    # It has what a busy page has: updates that changed fields and put it on agendas, emails, files, filed captures.
    assert len(leads) >= 40
    assert any(x.startswith("Update · ") and "agenda" in x for x in leads), leads
    assert any("Added to Today." in x for x in leads) and any("Due date moved to" in x for x in leads)
    assert any(x.startswith("Email from") for x in leads) and any(x.startswith("File") for x in leads)
    assert any(x.startswith("Note · Filed") for x in leads)
    assert any(c.discarded and c.task == p and c.has("update") for c in m.captures.values())
    story = Stories(m, DAY, lambda cid: "", "Me").story(p)
    assert any(e.verb == "Subtask closed" for e in story) and any(e.verb == "Subtask reopened" for e in story)
    assert any(e.verb == "Added to the agenda" for x in (ex.weekly, ex.kickoff) for e in Stories(m, DAY, lambda cid: "", "Me").story(x))
    assert any(c.item == "decision" for c in m.captures.values()) and len(m.children_of(p)) >= 5
    every = [p, *m.descendants_of(p), ex.kickoff, ex.weekly]
    assert assert_same(m, root, conn, every, every_state=[p, ex.weekly]) >= 40
    the_lists_gone_through_a_few_times(conn, root, ex.project)


# ================= the whole lists, gone through a few times (decisions 738 and 739) =================
class Counted(list):
    """A list that counts how many times it's gone through."""

    def __init__(self, items) -> None:
        super().__init__(items)
        self.passes = 0

    def __iter__(self):
        self.passes += 1
        return super().__iter__()


class CountedDict(dict):
    """A dict that counts how many times its values are gone through."""

    passes = 0

    def values(self):
        self.passes += 1
        return super().values()


def counted(conn) -> Model:
    m = Model(conn)
    m.status, m.agenda, m.captures = Counted(m.status), Counted(m.agenda), CountedDict(m.captures)
    return m


def the_lists_gone_through_a_few_times(conn, root, task_id: str) -> None:
    """Before, a busy page went through the whole status log and agenda once for each capture on it, and every capture once
    for each task in its story; now a few times each, however many captures and tasks the page has."""
    m = counted(conn)
    n, tasks = len(m.raw_log_of(task_id)), len(m.scope_ids(task_id, "family"))
    state = PageState(scope="family", chapters=set(m.scope_ids(task_id, "family")))
    pages_of(m, root, conn).task_parts(task_id, state, 1300)
    assert m.status.passes <= 5 and m.agenda.passes <= 10 and m.captures.passes <= 10, (m.status.passes, m.agenda.passes, m.captures.passes)
    old = counted(conn)
    pages_of(old, root, conn, before=True).task_parts(task_id, state, 1300)
    assert old.status.passes > n > 30 and old.agenda.passes > n and old.captures.passes > tasks >= 10
