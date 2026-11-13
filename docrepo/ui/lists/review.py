"""The Review view (release 5.128, the weekly review: the design workspace's ``docs/mods/cold-eyes-plan.md``, section 6,
decisions 496 to 503). Functions of the browse window ``w``, its tree and its model, as a new list view is
(``DocRepo/CLAUDE.md``); ``BrowseWindow`` only calls them. ``docrepo/review.py`` works out what each step holds.

- **One step at a time** (decision 497), each drawn by the code that draws its list: Unfiled by ``_unfiled_view``, Overdue
  and next 7 days and Waiting on others by ``_list_view`` (without its Sort, Group by and Select, Waiting on others the
  longest wait first), each with its rows' own commands (Waiting on others' right-click menu has Ask for an update, release
  5.125). Projects due for review, Gone quiet and No next step are drawn as the lists' rows are.
- **Where you are:** the pane's title says "Step 3 of 7 · Waiting on others · 8"; **Back** and **Next** (Alt+Left and
  Alt+Right) move between steps, passing over empty ones, which the status line names; a step emptied while it's open says
  so in a line and stays until Next.
- **Projects due for review** (step 4): each project's row, then what's happened on it since its last review, as the
  Activity view's lines. Its page, on the right, has its status card, its open subtasks and its next date. Its row has
  **Mark reviewed** (R, with Undo), **Update**, **Park**, **Close** and **Review every…**; its page has Mark reviewed first.
- **Done** (step 7): what the review did, and **Plan next week**, which opens Priorities. **Make this week's report** comes
  with the status report (release 5.129, decision 504), not before.
- **Today's line** (decision 502): on the review day, until a review is finished, Today's first row is "Weekly review",
  with Start (or Carry on).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QMenu, QPushButton

from docrepo import activity, edits, review
from docrepo.dates import long_date, short, to_date
from docrepo.detail import esc
from docrepo.tasks import REVIEW_WEEKS, review_every_words
from docrepo.ui import tokens
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.ui.lists.common import _cols
from docrepo.ui.state_menu import open_below
from docrepo.ui.tree_view import Line, group_ground, tint
from docrepo.views import LIST_IDS, VIEW_IDS, full_path, list_tree, pruned_tree

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

VIEW = "review"


# ---- the review in hand ----
def session(w: BrowseWindow) -> review.Session:
    from docrepo import db

    return review.read_session(db.get_state(w.ctx.conn, review.KEY))


def keep(w: BrowseWindow, s: review.Session) -> None:
    w.ctx.keep_state(review.KEY, s.to_json())


def have(w: BrowseWindow) -> dict[str, int]:
    st = w.ctx.settings
    return review.counts(w.model(), w.today(), st.me, st.review_weeks, st.quiet_days, session(w).started)


def enter(w: BrowseWindow) -> None:
    """The view opened: the review in hand carries on at its step, or a new one starts at the first step that holds
    something, the status line naming the empty ones it passed over."""
    s, fresh = review.begin(session(w), w._now())
    if fresh:
        counts = have(w)
        if not counts["unfiled"]:
            s.step, skipped = review.step_after(0, counts)
            passed = review.passed_line([0, *skipped])
            if s.step == len(review.STEPS) - 1:  # nothing anywhere: the review is done as it starts
                s = review.finish(s, w._now())
                w.say(f"{passed} Nothing to review.")
            elif passed:
                w.say(f"{passed} The review starts at {review.STEPS[s.step].name}.")
    keep(w, s)


def go(w: BrowseWindow, back: bool = False) -> None:
    """Next or Back: the next step that holds something, saying what it passed over. Reaching Done finishes the review."""
    if w.view != VIEW:
        return
    s = session(w)
    counts = have(w)
    if back and s.step == 0 or not back and s.step == len(review.STEPS) - 1:
        return
    s.step, skipped = review.step_after(s.step, counts, back)
    if s.step == len(review.STEPS) - 1:
        s = review.finish(s, w._now())
    keep(w, s)
    w.sel = None
    w.close_find()
    w._select_first()
    w.render_all()
    passed = review.passed_line(skipped)
    if passed:
        w.say(f"{passed} On to {review.STEPS[s.step].name}." if not back else f"{passed} Back to {review.STEPS[s.step].name}.")
    w.ctx.today_changed()  # Today's line goes once the review is done


def step_id(w: BrowseWindow) -> str:
    return review.STEPS[session(w).step].id


def first(w: BrowseWindow) -> tuple[str, str] | None:
    """What the step selects when it opens: its first capture or task."""
    m, today, st = w.model(), w.today(), w.ctx.settings
    sid = step_id(w)
    if sid == "unfiled":
        caps = m.unfiled_captures()
        return ("capture", caps[-1].id) if caps else None
    if sid == "due":
        ts = w._matching(LIST_IDS[sid])
        return ("task", ts[0].id) if ts else None
    if sid == "waiting":  # the longest wait, first in the step's order
        nodes = review.longest_first(m, list_tree(m, LIST_IDS[sid], today, st.me))
        hit = next((n for n in review.walk(nodes) if n.match), None)
        return ("task", hit.id) if hit else None
    if sid == "projects":
        due = review.due_for_review(m, today, st.review_weeks)
        return ("task", due[0].id) if due else None
    if sid == "quiet":
        quiet = _quiet(w)
        return ("task", max(quiet, key=lambda x: quiet[x])) if quiet else None
    if sid == "nonext":
        ts = review.no_next_step(m, today)
        return ("task", ts[0].id) if ts else None
    return None


# ---- the view ----
def view(w: BrowseWindow) -> None:
    """The step in hand: its bar (Back, Next and what to do), its list, and the line saying where you are."""
    s = session(w)
    if s.started is None:  # opened without set_view, such as after a restart on this view
        enter(w)
        s = session(w)
    counts = have(w)
    step = review.STEPS[s.step]
    _bar(w, s.step, counts)
    {"unfiled": lambda: w._unfiled_view(), "due": lambda: w._list_view("due", controls=False),
     "waiting": lambda: w._list_view("waiting", controls=False, order=review.longest_first, extra=lambda tid: _waited(w, tid)),
     "projects": lambda: _projects(w), "quiet": lambda: _quiet_step(w), "nonext": lambda: _no_next_step(w),
     "done": lambda: _done(w, s)}[step.id]()
    w.tree.set_density(*{"projects": (tokens.LIST_ROW, True), "unfiled": (tokens.LIST_ROW, False), "done": (tokens.LIST_ROW, False)}
                       .get(step.id, (tokens.TREE_ROW, False)))
    w._set_head("Review", VIEW_IDS[VIEW].note, review.place_line(s.step, counts[step.id]))


def _bar(w: BrowseWindow, index: int, counts: dict[str, int]) -> None:
    """Back, Next (naming the step it goes to) and what to do in this step."""
    back_to, _ = review.step_after(index, counts, back=True)
    on_to, _ = review.step_after(index, counts)
    back = QPushButton("Back")
    if not LOOK.classic:
        back.setIcon(icon("chevron-left"))
    back.setEnabled(index > 0)
    back.setToolTip(f"Back to {review.STEPS[back_to].name} (Alt+Left)" if index > 0 else "This is the first step")
    back.clicked.connect(lambda _=False: go(w, back=True))
    w._filter_widget(back)
    last = index == len(review.STEPS) - 1
    # Neutral, as a page's main command is: New capture stays the window's one accent button (the visual review's decision V2).
    nxt = QPushButton("Finish" if on_to == len(review.STEPS) - 1 else f"Next: {review.STEPS[on_to].name}", objectName="primary" if LOOK.classic else "")
    if not LOOK.classic:
        nxt.setIcon(icon("chevron-right"))
        nxt.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # the arrow after the words
    nxt.setToolTip("Finish the review: what it did, and Plan next week (Alt+Right)" if on_to == len(review.STEPS) - 1
                   else f"On to {review.STEPS[on_to].name} (Alt+Right). Empty steps are passed over.")
    nxt.clicked.connect(lambda _=False: go(w))
    w._filter_widget(nxt)
    hint = QLabel(review.step_hint(review.STEPS[index], w.ctx.settings.quiet_days), objectName="paneNote")
    hint.setTextFormat(Qt.TextFormat.PlainText)
    w._filter_widget(hint)
    for b in (back, nxt, hint):  # shown once they're in the bar, which shows only when something in it is
        b.setVisible(b is not nxt or not last)


def _waited(w: BrowseWindow, task_id: str) -> tuple[str, ...]:
    """Step 3's quiet words: how long since the task last changed, from two days on."""
    n = review.waited_days(w.model(), task_id, w.today())
    return (f"no change for {n} d",) if n >= 2 else ()


def _empty_line(w: BrowseWindow, text: str) -> None:
    w.tree.add_row(None, None, [f'<span class="sub">{esc(text)}</span>'], selectable=False, span=True)


# ---- step 4: projects due for review ----
def _reviewed_words(t, today) -> str:
    return f"reviewed {short(to_date(t.reviewed), today)}" if t.reviewed else "not reviewed yet"


def _projects(w: BrowseWindow) -> None:
    m, today, st = w.model(), w.today(), w.ctx.settings
    w._set_head("Projects due for review")
    w.tree.set_columns(["Title", "When"], [0, 96])
    due = review.due_for_review(m, today, st.review_weeks)
    if not due:
        _empty_line(w, "No project is due for review.")
        return
    starts = {t.id: review.since(t, today, review.interval(m, t, st.review_weeks)) for t in due}
    lines = activity.Activity(m, today).lines(to_date(min(starts.values())), today)
    w._act_lines = {x.key: x for x in lines}
    order = review.tree_order(m)
    for g, t in enumerate(due):
        group = review.since_group(m, lines, t, starts[t.id], order)
        n = len(group.lines)
        cells = w._task_cells(t.id, 0, muted=(_reviewed_words(t, today), f"{n} thing{'s' if n != 1 else ''} since" if n else "nothing since"))
        cells = [cells[0], cells[-1]]  # the title and its date: the lines under it have their time in the same column
        top = w.tree.add_row(None, ("task", t.id), cells, tint(g, 0), tip=full_path(m, t.id))
        w.tree.set_actions(top, project_actions(w, t.id))
        if group.lines:
            w._activity_rows(m, today, group, top)
        else:
            day = long_date(to_date(starts[t.id]), today)
            words = f"Nothing has happened on it since its last review, {day}." if t.reviewed else f"Nothing has happened on it since {day}."
            w.tree.add_row(top, None, [f'<span class="sub">{esc(words)}</span>', ""], selectable=False, span=True)
        top.setExpanded(True)


def project_actions(w: BrowseWindow, task_id: str) -> list[tuple[str, Callable[[], None], str]]:
    """Step 4's commands on a project's row (decision 497): Mark reviewed (R), Update, Park, Close and Review every…."""
    return [("Mark reviewed", lambda: mark_reviewed(w, task_id), "Reviewed: off this step until its interval comes round (R)"),
            ("Update", lambda: w.open_capture(task=task_id, mode="update"), "Update its status, state or dates in the capture window (U)"),
            ("Park", lambda: w.set_state(task_id, "Parked"), "Park it: off the lists and the review until you take it up again"),
            ("Close", lambda: close(w, task_id), "Close it; with open subtasks, they close too, after asking"),
            ("Review every…", lambda: review_every_menu(w, task_id), "How often it comes up for review: every 1, 2 or 4 weeks, or never")]


def mark_reviewed(w: BrowseWindow, task_id: str | None = None) -> None:
    """Mark reviewed (R): the selected task, in step 4, with Undo for ten seconds."""
    task_id = task_id or (w.sel[1] if w.sel and w.sel[0] == "task" else None)
    if w.view != VIEW or step_id(w) != "projects":
        w.say("R marks a project reviewed in the Review view's step 4, Projects due for review.")
        return
    m = w.model()
    if not task_id or task_id not in m.tasks:
        w.say("Select a project first.")
        return
    was = m.task(task_id).reviewed
    due = [t.id for t in review.due_for_review(m, w.today(), w.ctx.settings.review_weeks)]
    after = due[due.index(task_id) + 1] if task_id in due and due.index(task_id) + 1 < len(due) else None
    out = w._do(lambda: edits.mark_reviewed(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, task_id, w._now()),
                ("task", after) if after else None)
    if out is None:
        return
    if after is None:
        w._select_first()
        w.render_all()

    def undo() -> None:
        w._do(lambda: edits.set_reviewed(w.conn, w.ctx.data_root, w.ctx.fs, task_id, was, w._now()), ("task", task_id))

    w.say_undo(out.message, undo)


def close(w: BrowseWindow, task_id: str) -> None:
    """Close, from step 4: the project and, after asking, its open subtasks, so nothing is left open under a closed project."""
    m = w.model()
    below = open_below(m, task_id)
    if below:
        words = f"Close all {len(below) + 1}"
        if not w.confirm(words, f"{m.task(task_id).title} has {len(below)} open subtask{'s' if len(below) != 1 else ''}. "
                                f"Close {'them' if len(below) != 1 else 'it'} too?"):
            return
    w.set_state(task_id, "Closed", branch=bool(below))


def review_every_menu(w: BrowseWindow, task_id: str) -> None:
    """Review every…: the project's own interval, or Settings' (decision 499)."""
    m = w.model()
    t = m.task(task_id)
    default = review_every_words(w.ctx.settings.review_weeks) or ""
    menu = QMenu(w)
    for weeks, words in ((None, f"As Settings has it ({default.lower()})"), *((n, review_every_words(n)) for n in (*REVIEW_WEEKS, 0))):
        a = menu.addAction(words or "", lambda n=weeks: set_review_every(w, task_id, n))
        a.setCheckable(True)
        a.setChecked(t.review_every == weeks)
    w.run_menu(menu, QCursor.pos())
    menu.deleteLater()


def set_review_every(w: BrowseWindow, task_id: str, weeks: int | None) -> None:
    w._do(lambda: edits.change_task(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, task_id, w._now(), review_every=weeks), w.sel)


# ---- steps 5 and 6 ----
def _quiet(w: BrowseWindow) -> dict[str, int]:
    m, today, st = w.model(), w.today(), w.ctx.settings
    return review.gone_quiet(m, today, st.quiet_days, review.looked_at(m, today, st.review_weeks, session(w).started))


def _tree_step(w: BrowseWindow, ids: dict[str, int], words: Callable[[str], tuple[str, ...]], empty: str) -> None:
    """A step drawn as the lists are: each task under its parents, dimmed for context."""
    m = w.model()
    w.tree.set_columns(*_cols(["Title", "State", "Due"]))
    nodes = pruned_tree(m, lambda x: x in ids, lambda x: -max((ids.get(y, 0) for y in (x, *m.descendants_of(x))), default=0))

    def row(n):
        if not n.match:
            return w._task_cells(n.id, n.depth, context=True), full_path(m, n.id)
        return w._task_cells(n.id, n.depth, muted=words(n.id)), full_path(m, n.id)

    w._add_nodes(nodes, row=row)
    if not nodes:
        _empty_line(w, empty)


def _quiet_step(w: BrowseWindow) -> None:
    w._set_head("Gone quiet")
    quiet = _quiet(w)
    _tree_step(w, quiet, lambda tid: (f"quiet {quiet[tid]} d",), "Nothing has gone quiet.")


def _no_next_step(w: BrowseWindow) -> None:
    w._set_head("No next step")
    ts = review.no_next_step(w.model(), w.today())
    _tree_step(w, {t.id: 1 for t in ts}, lambda tid: (), "Every open project has a next step.")


# ---- step 7: Done ----
#: Each step's icon on Done's rows: the sidebar's for the lists, and the marks the steps' rows use.
STEP_ICONS = {"unfiled": "unfiled", "due": "due", "waiting": "waiting", "projects": "review", "quiet": "timing", "nonext": "unplanned"}


def _done(w: BrowseWindow, s: review.Session) -> None:
    """Done: what the review did (decision 497's "filed 4, reviewed 6, asked 2"), what's still there, each with Go back,
    and Plan next week, which opens Priorities. Make this week's report comes with release 5.129."""
    w._set_head("Done")
    w.tree.set_columns(["Done"], [0])
    m, today = w.model(), w.today()
    started = s.started or ""
    when = (f"since you started it at {started[11:16]}" + ("" if to_date(started) == today else f" on {long_date(to_date(started), today)}")) if started else ""
    grey = group_ground()
    head = w.tree.add_row(None, None, [f"<b>This review</b> <span class=\"sub\">{esc(when)}</span>"], grey, selectable=False, span=True)
    w.tree.add_row(head, None, [Line(review.did_line(review.did(m, started)), icon="review", icon_colour="accent", icon_tip="What it did")],
                   selectable=False)
    head.setExpanded(True)
    left = have(w)
    still = [(i, x) for i, x in enumerate(review.STEPS[:-1]) if left[x.id]]
    if still:
        head = w.tree.add_row(None, None, ["<b>Still there</b>"], grey, selectable=False, span=True)
        for i, x in still:
            item = w.tree.add_row(head, None, [Line(x.name, icon=STEP_ICONS.get(x.id, "task"), icon_tip=x.name, context=str(left[x.id]))],
                                  selectable=False)
            w.tree.set_actions(item, [("Go back", lambda i=i: goto(w, i), f"Back to step {i + 1}, {x.name}")])
        head.setExpanded(True)
    plan = QPushButton("Plan next week", objectName="primary" if LOOK.classic else "")
    plan.setToolTip("Open Priorities, to rank next week's work")
    plan.clicked.connect(lambda _=False: w.set_view("priorities"))
    w.filters_layout.insert_widget(1, plan)  # after Back, before the step's line
    plan.show()


def goto(w: BrowseWindow, index: int) -> None:
    """A step, from Done's Go back: the review stays finished."""
    s = session(w)
    s.step = index
    keep(w, s)
    w.sel = None
    w._select_first()
    w.render_all()


# ---- the task page in step 4 ----
def page_actions(w: BrowseWindow, task_id: str) -> None:
    """Mark reviewed first on the page's bar, for a project in step 4 (decision 497)."""
    if step_id(w) != "projects":
        return
    m = w.model()
    if task_id in m.tasks and review.is_due(m, m.task(task_id), w.today(), w.ctx.settings.review_weeks):
        w._action("Mark reviewed", lambda: mark_reviewed(w, task_id), "Reviewed: off this step until its interval comes round",
                  primary=True, icon_name="review", key="R")


# ---- Today's line (decision 502) ----
def today_row(w: BrowseWindow, grey) -> None:
    """On the review day, until a review is finished: "Weekly review" first on Today, with Start, or Carry on for one in hand."""
    s = session(w)
    today = w.today()
    if not review.offer_today(s, today, w.ctx.settings.review_day):
        return
    carry = review.in_hand(s, today)
    st = w.ctx.settings
    counts = review.counts(w.model(), today, st.me, st.review_weeks, st.quiet_days, s.started)
    asks = [f"{counts['unfiled']} unfiled" if counts["unfiled"] else "", f"{counts['projects']} project{'s' if counts['projects'] != 1 else ''} to review"
            if counts["projects"] else "", f"{counts['quiet']} gone quiet" if counts["quiet"] else ""]
    context = (f"carry on at step {s.step + 1}, {review.STEPS[s.step].name}" if carry else "") or " · ".join(x for x in asks if x)
    line = Line("Weekly review", icon="review", icon_colour="accent", icon_tip="Review", context=context, strong=True)
    item = w.tree.add_row(None, None, [line, *([""] if LOOK.classic else []), ""], grey, selectable=False,
                          tip=f"It's {st.review_day}, your review day: a step at a time through what needs a look.")
    w.tree.set_actions(item, [("Carry on" if carry else "Start", lambda: w.set_view(VIEW),
                               "Open Review where you left it" if carry else "Open Review at its first step")])
