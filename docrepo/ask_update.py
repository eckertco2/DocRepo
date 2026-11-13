"""Ask for an update (release 5.125, the cold-eyes plan's section 4, decisions 481 to 487): a new T-mail to the people
doing a task, with its To, Subject and words filled in, for the owner to change and send in Outlook. DocRepo never sends
it. It's kept as a T-mail of kind ``ask`` (schema 25), so the reply files itself on the task, as any T-mail's does
(release 5.105).

- **To** (decision 482): the task's assignees, then its leads, except the owner, each once, who have an email address in
  People. Anyone without one is named in the line saying what happened; with nobody left, To is empty and the line says so.
- **Subject:** "<title>: where does it stand?".
- **The words** (decisions 483 and 484, fixed here for now): a greeting, the question, the last current status with its
  day, the due date and the open subtasks, then "Thanks,". They go above the owner's Outlook signature
  (``outlook.ask_t_mail``).

Since release 5.139 (the email progress plan's decision 593) an ask starts a wait on the people it went to
(``start_wait``, ``docrepo.waits``), shown as "waiting on Mike since Mon" until a reply is captured on the task, in place
of 5.125's "asked Mon" (decision 485), which any newer capture ended.

Not now (decision 487): several tasks in one email, since its reply couldn't say which task it's about.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from docrepo.dates import long_date, short, to_date
from docrepo.model import Model, Person, Task
from docrepo.schedule import due_of, is_open

if TYPE_CHECKING:
    from docrepo.config import Settings

#: The T-mail kind Ask for an update is kept as (``t_mails.kind``).
KIND = "ask"
#: The command's name, on New T-mail's arrow and a task row's right-click menu in Waiting on others (decision 481).
LABEL = "Ask for an update"
TIP = ("A new email in Outlook to the people on this task, asking where it stands, with the last status, the due date and "
       "the open subtasks filled in for you to change. You send it; DocRepo never sends email. The reply comes back to this "
       "task when you capture it.")
#: How many open subtasks the words name before "and n more".
SUBTASKS_NAMED = 5

_CAPITALISED = re.compile(r"[A-Z][a-z'’]*(?:-[a-z'’]+)*")
_ARTICLES = ("the", "a", "an")
#: A title starting with one of these is something to do, not a thing, so the question quotes it rather than say "the …".
_VERBS = frozenset("""
add agree approve arrange ask book build buy calculate call check clean close collect complete confirm contact
create decide design do email estimate find finish fix follow gather get hold inspect install investigate look make measure
meet move order organise organize paint prepare price print reply request remove repair replace respond review run send
set share sign sort start submit talk test tidy train update upload visit walk write
""".split())
#: A title with one of these after its first word reads as a sentence ("Rails need to be painted red").
_SENTENCE_WORDS = frozenset("is are was were be been need needs must should will has have had to".split())


@dataclass(frozen=True)
class Ask:
    """An ask, ready for Outlook: To's addresses and their people's names, those left out for want of an address, the
    subject and the words (plain text, a line each)."""

    task: str
    to: tuple[str, ...]
    names: tuple[str, ...]
    missing: tuple[str, ...]
    subject: str
    words: str


def people(m: Model, t: Task, me: str | None) -> tuple[list[Person], list[str]]:
    """Who an ask goes to (decision 482): the task's assignees, then its leads, each once, not the owner; those with an
    email address, and the names of those without one."""
    found, missing = [], []
    for pid in dict.fromkeys((*t.assignees, *t.leads)):
        if pid == me:
            continue
        p = m.people.get(pid)
        if p is not None and p.email:
            found.append(p)
        else:
            missing.append(m.person_name(pid))
    return found, missing


def first_name(name: str) -> str:
    """A greeting's name: the first word of a person's name."""
    return (name.split() or [name])[0]


def greeting(names: list[str]) -> str:
    """"Hi Mike,", "Hi Mike and Priya,", "Hi Mike, Priya and Sam," or "Hi," for nobody."""
    firsts = [first_name(n) for n in names]
    if not firsts:
        return "Hi,"
    return f"Hi {firsts[0]}," if len(firsts) == 1 else f"Hi {', '.join(firsts[:-1])} and {firsts[-1]},"


def in_sentence(text: str) -> str:
    """Words to go mid-sentence: a first word that's only capitalised ("Rigging", "Waiting") loses its capital; one that's
    a name or a code ("P-204A", "PO", "I") keeps it."""
    first = text.split(" ", 1)[0].rstrip(",.;:!?")
    if first != "I" and _CAPITALISED.fullmatch(first):
        return text[:1].lower() + text[1:]
    return text


def reads_as_a_thing(title: str) -> bool:
    """Whether a title names a thing ("Rigging plan", "Line 2 extruder screw replacement"), so the question can say "the
    rigging plan"; not when it starts with a verb ("Order spare mechanical seal") or reads as a sentence ("Rails need to be
    painted red")."""
    words = [w.strip(",.:;").lower() for w in title.split()]
    return bool(words) and words[0] not in _VERBS and not any(w in _SENTENCE_WORDS for w in words[1:])


def the_task(title: str) -> str:
    """The task as the question names it: "the rigging plan" (decision 483's words), the title as it is when it already
    starts with "the" or "a", and the title in quotes when it doesn't name a thing ("“Order spare mechanical seal”")."""
    title = " ".join(title.split())
    if not reads_as_a_thing(title):
        return f"“{title}”"
    words = in_sentence(title)
    return words if words.split(" ", 1)[0].lower() in _ARTICLES else f"the {words}"


def listed(titles: list[str]) -> str:
    """"A", "A and B", "A, B and C"; past ``SUBTASKS_NAMED``, "A, B, C, D, E and 3 more"."""
    if len(titles) > SUBTASKS_NAMED:
        return f"{', '.join(titles[:SUBTASKS_NAMED])} and {len(titles) - SUBTASKS_NAMED} more"
    return titles[0] if len(titles) == 1 else f"{', '.join(titles[:-1])} and {titles[-1]}"


def status_day(m: Model, t: Task) -> str | None:
    """When the current status last changed, as the status card has it: its latest status log entry, or the day the task
    was made, for a status that came with it."""
    changes = [e.at for e in m.status if e.task == t.id and e.field == "Current status"]
    return max(changes)[:10] if changes else t.created[:10] if t.current_status else None


def _ends(text: str) -> str:
    return text if text[-1:] in ".!?…" else text + "."


def question(m: Model, t: Task, today: date) -> str:
    """The middle paragraph: the question, the last status with its day, the due date and the open subtasks."""
    parts = [f"Where does {the_task(t.title)} stand?"]
    status = " ".join((t.current_status or "").split())
    if status:
        day = status_day(m, t)
        when = f" ({short(to_date(day), today)})" if day else ""
        parts.append(f"The last I have{when}: {_ends(in_sentence(status))}")
    else:
        parts.append("I have no status for it yet.")
    due = due_of(t, today)
    if due is not None and due.label in ("Due", "Deadline"):
        day = long_date(due.date, today)
        past = due.date < today
        if due.label == "Due":
            parts.append(f"It was due {day}." if past else f"It's due {day}.")
        else:
            parts.append(f"Its deadline was {day}." if past else f"Its deadline is {day}.")
    kids = [m.task(k) for k in m.children_of(t.id) if k in m.tasks]
    still = [k.title for k in kids if is_open(k) and not k.discarded]
    if still:
        parts.append(f"Still open under it: {_ends(listed(still))}")
    return " ".join(parts)


def compose(m: Model, task_id: str, me: str | None, today: date) -> Ask:
    """The ask for a task: To, Subject and the words (decisions 482 to 484)."""
    t = m.task(task_id)
    found, missing = people(m, t, me)
    names = [p.name for p in found]
    words = "\n".join([greeting(names), "", question(m, t, today), "", "Thanks,"])
    return Ask(task_id, tuple(p.email or "" for p in found), tuple(names), tuple(missing), f"{t.title.strip()}: where does it stand?", words)


def who_line(ask: Ask) -> str:
    """What the status line says about To: who it's to, who has no address, or that nobody's in it."""
    gone = f" {listed(list(ask.missing))} {'has' if len(ask.missing) == 1 else 'have'} no email address in People." if ask.missing else ""
    if ask.to:
        return f"To {listed(list(ask.names))}.{gone}"
    return f"To is empty.{gone}" if ask.missing else "To is empty: nobody but you is on this task."


# ---- the wait it starts (release 5.139, the email progress plan's decision 593; "asked Mon" in release 5.125) ----
def start_wait(conn: sqlite3.Connection, settings: Settings, task_id: str, t_mail: int | None, at: datetime) -> int | None:
    """An ask starts a wait on the people it went to (decision 593), with the last Follow up chosen in Log progress (3
    workdays at first), as the task's Reminder, so it comes back on Today if nobody answers. It ends as any wait does: a
    reply captured on the task, Got it, a newer wait, or closing the task. None, and no wait, when it went to nobody."""
    from docrepo import tasks, waits
    from docrepo.edits import _workdays

    m = Model(conn)
    t = m.task(task_id)
    found, _ = people(m, t, settings.me)
    if not found:
        return None
    day = waits.follow_up_day(waits.last_follow_up(conn), at.date(), _workdays(settings))
    reminder = waits.reminder_for(m, task_id, day)
    if reminder != t.reminder:
        tasks.update_task(conn, settings, task_id, at=at, via=LABEL, reminder=reminder)
    names = listed([first_name(p.name) for p in found])
    return waits.start(conn, m, task_id, at=waits.stamp_of(at), line=f"Asked {names} for an update", on=[p.id for p in found],
                       follow_up=day, via=LABEL, t_mail=t_mail)
