"""T-mails from the browse tool and Find files (the knowledge base's stage K8, release B, as release 5.105; KB decisions
35 to 38 and 42; ``../docs/knowledge-base/email-conversations-plan.md`` in the design workspace).

A T-mail is an email DocRepo opens in Outlook from a task, for the owner to write and send:
- **New T-mail**, on the task page's bar: a new email, empty (no subject, no To), tagged only by its conversation index;
- **Reply all** to a captured email: on New T-mail's arrow, to the newest email filed to the task, on each email in Find
  files, and beside each email on a capture's page.

Each is kept in ``t_mails`` with its conversation (``conversations.record_t_mail``), so the replies it gets fill the
capture window's task picker with its task. DocRepo never sends one; the owner does, in Outlook.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu, QWidget

from docrepo import conversations, outlook
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
    why, when the task has none."""
    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    found = conversations.latest_email(browse.model(), task_id)
    if found is None:
        a = menu.addAction(icon("mail"), "Reply all to the latest email")
        a.setEnabled(False)
        a.setToolTip("No email is filed to this task yet")
        return menu
    c, e = found
    a = menu.addAction(icon("mail"), latest_label(c, e), lambda: reply_all(browse, c.id, e.pos, task_id))
    a.setToolTip(f"Reply all in Outlook, as a T-mail of this task. Its capture is {c.id}.")
    return menu
