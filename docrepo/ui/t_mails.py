"""T-mails from the browse tool and Find files (the knowledge base's stage K8, release B, as release 5.105; KB decisions
35 to 38 and 42; ``../docs/knowledge-base/email-conversations-plan.md`` in the design workspace).

A T-mail is an email DocRepo opens in Outlook from a task, for the owner to write and send:
- **New T-mail**, on the task page's bar: a new email, empty (no subject, no To), tagged only by its conversation index;
- **Reply all** to a captured email: on New T-mail's arrow, to the newest email filed to the task, on each email in Find
  files, and beside each email on a capture's page;
- **Ask for an update** (release 5.125, the cold-eyes plan's decisions 481 to 487): on New T-mail's arrow and on a task
  row's right-click menu in Waiting on others, a new email to the task's assignees and leads with its Subject and words
  filled in above the owner's signature (``docrepo.ask_update``).

Each is kept in ``t_mails`` with its conversation (``conversations.record_t_mail``), so the replies it gets fill the
capture window's task picker with its task. Where Outlook's security guard won't let DocRepo give a new email its
conversation (release 5.141), the T-mail is kept with its draft's place instead, and ``docrepo.sent_watch`` knows it when
it's sent. DocRepo never sends one; the owner does, in Outlook.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu, QWidget

from docrepo import ask_update, conversations, outlook, sent_watch
from docrepo.captures import capture_folder
from docrepo.ui.icons import icon

if TYPE_CHECKING:
    from docrepo.model import Capture, CaptureEmail
    from docrepo.ui.browse_window import BrowseWindow

Say = Callable[[str, bool], None]


def _say(browse: BrowseWindow, say: Say | None) -> Say:
    return say if say is not None else browse.say


def _stamp(browse: BrowseWindow) -> str:
    return browse.ctx.now().strftime("%Y-%m-%d %H:%M:%S")


def _kept(browse: BrowseWindow, say: Say, task_id: str | None, kind: str, opened: outlook.Opened, reply_capture: str | None = None,
          reply_pos: int | None = None) -> None:
    """Keep the T-mail on its task and say what happened."""
    m = browse.model()
    what = "a new T-mail" if kind == "new" else "a Reply all"
    if task_id is None:
        say(f"Opened {what} in Outlook. Its capture isn't filed to a task, so its replies won't find one by themselves.", False)
        return
    title = m.tasks[task_id].title
    if kind == "new" and not conversations.key(opened.index) and opened.entry_id:
        # Outlook's guard refused the index (release 5.141): kept untagged with its draft, known when it's sent.
        kept = conversations.record_t_mail(browse.conn, task_id, kind, _stamp(browse), "", untagged=True)
        if kept is not None:
            sent_watch.keep_draft(browse.conn, kept, opened.entry_id, opened.store_id)
            say(f"Opened a new T-mail from {title} in Outlook. When you send it, DocRepo files it on {title}, and its replies follow.", False)
            browse.ctx.t_mail_opened()
            return
    if conversations.record_t_mail(browse.conn, task_id, kind, _stamp(browse), opened.index, reply_capture, reply_pos) is None:
        say(f"Opened {what} in Outlook, but Outlook gave it no conversation index, so its replies won't find {title} by themselves. "
            "Settings → Troubleshooting report shows why.", True)
        return
    say(f"Opened {what} from {title} in Outlook. When you send it, it's captured on {title}, and so are the replies you capture.", False)
    browse.ctx.t_mail_opened()  # Sent Items is watched for it (release 5.123)


def new_t_mail(browse: BrowseWindow, task_id: str, say: Say | None = None) -> None:
    """New T-mail (decisions 35, 36 and 39): a new, empty email in Outlook, tagged with its conversation for this task."""
    out = _say(browse, say)
    if task_id not in browse.model().tasks:
        return
    try:
        opened = outlook.new_t_mail(browse.ctx.now())
    except outlook.OutlookError as e:
        out(f"New T-mail: {e}", True)
        return
    _kept(browse, out, task_id, "new", opened)


def first_email(c: Capture) -> CaptureEmail | None:
    """The email a capture's row in Find files stands for: the first that Reply all can find, as Open the email opens the
    first."""
    return next((e for e in c.emails if conversations.can_reply(e)), None)


def reply_all(browse: BrowseWindow, capture_id: str, pos: int, task_id: str | None = None, say: Say | None = None) -> None:
    """Reply all to one of a capture's emails (decisions 37, 38 and 42), as a T-mail of the task it was clicked from
    (``task_id``) when the capture is on it, else of the capture's own task."""
    out = _say(browse, say)
    m = browse.model()
    c = m.captures.get(capture_id)
    e = next((e for e in c.emails if e.pos == pos), None) if c is not None else None
    if c is None or e is None or not conversations.can_reply(e):
        out("Reply all: DocRepo has neither the email's place in Outlook nor its saved .msg.", True)
        return
    saved = capture_folder(browse.ctx.data_root, c.id, c.saved) / e.file if e.file else None
    try:
        opened = outlook.reply_all(e.entry_id, e.store_id, saved)
    except outlook.OutlookError as err:
        out(f"Reply all: {err}", True)
        return
    _kept(browse, out, conversations.reply_task(m, c, task_id), "reply", opened, c.id, e.pos)


def latest_label(c: Capture, e: CaptureEmail) -> str:
    """New T-mail's arrow names the email it replies to: its subject, sender and date."""
    subject = (e.subject or "(no subject)").strip()
    if len(subject) > 60:
        subject = subject[:57] + "…"
    return f"Reply all to the latest email: “{subject}”, {e.sender or 'an unknown sender'}, {(e.sent or c.saved)[:10]}"


def latest_menu(browse: BrowseWindow, task_id: str, parent: QWidget | None) -> QMenu:
    """New T-mail's arrow (decision 36): Reply all to the newest email filed to the task, by when it was sent; greyed, saying
    why, when the task has none. Then, since release 5.125, Ask for an update (the cold-eyes plan's decision 481)."""
    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    found = conversations.latest_email(browse.model(), task_id)
    if found is None:
        a = menu.addAction(icon("mail"), "Reply all to the latest email")
        a.setEnabled(False)
        a.setToolTip("No email is filed to this task yet")
    else:
        c, e = found
        a = menu.addAction(icon("mail"), latest_label(c, e), lambda: reply_all(browse, c.id, e.pos, task_id))
        a.setToolTip(f"Reply all in Outlook, as a T-mail of this task. Its capture is {c.id}.")
    add_ask(browse, task_id, menu)
    return menu


# ---- Ask for an update (release 5.125, the cold-eyes plan's decisions 481 to 487) ----
def ask_tip(browse: BrowseWindow, task_id: str) -> str:
    """The command's tooltip: who it would go to, then what it does."""
    ask = ask_update.compose(browse.model(), task_id, browse.ctx.settings.me, browse.today())
    return f"{ask_update.who_line(ask)} {ask_update.TIP}"


def add_ask(browse: BrowseWindow, task_id: str, menu: QMenu) -> None:
    """Ask for an update as a menu's line, with who it would go to in its tooltip: on New T-mail's arrow, and on a task
    row's right-click menu in Waiting on others (decision 481). Not for a closed or discarded task."""
    t = browse.model().tasks.get(task_id)
    if t is None or t.discarded or t.state == "Closed":
        return
    menu.setToolTipsVisible(True)
    a = menu.addAction(icon("mail"), ask_update.LABEL, lambda: ask_for_update(browse, task_id))
    a.setToolTip(ask_tip(browse, task_id))


def ask_for_update(browse: BrowseWindow, task_id: str, say: Say | None = None) -> int | None:
    """Ask for an update (decisions 481 to 486): a new email in Outlook to the task's assignees and leads, with its Subject
    and words filled in above the owner's signature, kept as a T-mail of kind ``ask`` so its reply files itself on the
    task, and so its rows and status card say "asked Mon". Words Outlook wouldn't take go on the clipboard. Returns the
    T-mail's id, or None when nothing was opened. Never sent."""
    out = _say(browse, say)
    m = browse.model()
    if task_id not in m.tasks:
        return None
    title = m.tasks[task_id].title
    ask = ask_update.compose(m, task_id, browse.ctx.settings.me, browse.today())
    try:
        asked = outlook.ask_t_mail(browse.ctx.now(), ask.to, ask.subject, ask.words)
    except outlook.OutlookError as e:
        out(f"{ask_update.LABEL}: {e}", True)
        return None
    kept = conversations.record_t_mail(browse.conn, task_id, ask_update.KIND, _stamp(browse), asked.opened.index, untagged=True)
    ask_update.start_wait(browse.conn, browse.ctx.settings, task_id, kept, browse.ctx.now())  # waiting on them (release 5.139, decision 593)
    browse.refresh()  # its rows and status card say "waiting on Mike since …" now
    lines, trouble = [f"Opened {ask_update.LABEL} on {title} in Outlook. {ask_update.who_line(ask)}"], bool(ask.missing)
    if ask.to and not asked.to_filled:
        lines.append("Outlook didn't take To, so fill it in there.")
        trouble = True
    if not asked.words:
        QGuiApplication.clipboard().setText(ask.words)
        lines.append("Outlook didn't take the words, so they're on the clipboard: paste them above your signature.")
        trouble = True
    by_draft = kept is not None and not conversations.key(asked.opened.index) and bool(asked.opened.entry_id)
    if by_draft:  # Outlook's guard refused the index (release 5.141): known by its draft when it's sent
        sent_watch.keep_draft(browse.conn, kept, asked.opened.entry_id, asked.opened.store_id)
    if kept is not None and (by_draft or conversations.key(asked.opened.index)):
        browse.ctx.t_mail_opened()  # Sent Items is watched for it (release 5.123)
    if conversations.key(asked.opened.index):
        lines.append(f"When you capture the reply, it'll go to {title}.")
    elif by_draft:
        lines.append(f"When you send it, DocRepo files it on {title}, and its reply follows.")
    else:
        lines.append(f"Outlook gave it no conversation index, so the reply won't find {title} by itself. Settings → Troubleshooting report shows why.")
        trouble = True
    out(" ".join(lines), trouble)
    return kept
