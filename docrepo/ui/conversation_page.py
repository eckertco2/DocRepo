"""A conversation's page in the browse tool, and the Email conversations section's links (release 5.122; the design
workspace's ``docs/mods/email-section-plan.md``, decisions 455 to 463). Functions of the browse window ``w``, as a new
page's commands are (``DocRepo/CLAUDE.md``); ``BrowseWindow`` only calls them.

- **The section's links:** a conversation's subject (``conv:<task>/<conversation>``) opens its page; New T-mail at the
  section's right (``tmail:<task>``) is the task page's New T-mail.
- **The page** is selected as ``("conversation", "<task>/<conversation>")``: the task it was opened from, for its way
  back and for the T-mails it opens, and the conversation (``email_conversations.find``). Its bar: **Open in Outlook**
  (the newest email) and **Reply all** to it; its first line goes back to the task.
- **Open in Outlook** (decision 460): the email itself, found by its place in Outlook and shown; when Outlook can't find
  it there, or isn't open, its saved ``.msg``, through ``opener.start`` as Find files' Open the email. Nothing changes in
  Outlook.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from docrepo import email_conversations, opener, outlook
from docrepo.captures import capture_folder
from docrepo.ui import t_mails

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

KIND = "conversation"
LINKS = ("conv", "outlook", "tmail")
#: What starts a saved .msg (``os.startfile`` when None); the tests put a fake here.
STARTER: Callable[[str], None] | None = None


def split(item: str) -> tuple[str, str]:
    """A selection's task and conversation: "T000001/ABC…" is ("T000001", "ABC…")."""
    task_id, _, conversation_id = item.partition("/")
    return task_id, conversation_id


def exists(w: BrowseWindow, item: str) -> bool:
    return email_conversations.find(w.model(), split(item)[1]) is not None


def go(w: BrowseWindow, task_id: str, conversation_id: str) -> None:
    """Open a conversation's page from a task's Email conversations (decision 459)."""
    if email_conversations.find(w.model(), conversation_id) is None:
        w.say("That conversation isn't here any more.", True)
        return
    w.select(KIND, f"{task_id}/{conversation_id}")


def page(w: BrowseWindow, item: str) -> str:
    task_id, conversation_id = split(item)
    return w.pages().conversation_page(task_id, conversation_id, w.state)


def _newest(w: BrowseWindow, item: str) -> email_conversations.Email | None:
    """The newest email of the page's conversation that Open in Outlook and Reply all can find."""
    cv = email_conversations.find(w.model(), split(item)[1])
    return next((e for e in reversed(cv.emails) if e.can_open), None) if cv is not None else None


def actions(w: BrowseWindow, item: str) -> None:
    """The page's bar: Open in Outlook and Reply all, for the newest email. The way back to the task is the page's first line."""
    task_id, _ = split(item)
    e = _newest(w, item)
    tip = "The newest email in Outlook: what it quotes is the conversation before it"
    w._action("Open in Outlook", (lambda: open_email(w, e.capture, e.pos)) if e else None,
              tip if e else "DocRepo has neither its place in Outlook nor its saved .msg", e is not None, primary=True, icon_name="mail")
    w._action("Reply all", (lambda: t_mails.reply_all(w, e.capture, e.pos, task_id if task_id in w.model().tasks else None)) if e else None,
              "Reply all to the newest email in Outlook, as a T-mail: its replies come back to the task", e is not None)


def open_email(w: BrowseWindow, capture_id: str, pos: int) -> None:
    """Open in Outlook (decision 460): the email by its place in Outlook, else its saved .msg."""
    m = w.model()
    c = m.captures.get(capture_id)
    e = next((x for x in c.emails if x.pos == pos), None) if c is not None else None
    if c is None or e is None:
        w.say("Open in Outlook: that email isn't here any more.", True)
        return
    saved = capture_folder(w.ctx.data_root, c.id, c.saved) / e.file if e.file else None
    problem = ""
    if e.entry_id:
        try:
            if outlook.show_email(e.entry_id, e.store_id):
                w.say(f"Opened “{e.subject or '(no subject)'}” in Outlook.")
                return
        except outlook.OutlookError as err:
            problem = str(err)
    if saved is None or not saved.is_file():
        w.say(problem or "Open in Outlook: DocRepo has neither this email's place in Outlook nor its saved .msg.", True)
        return
    failed = opener.start(str(saved), STARTER)
    if failed:
        w.say(f"Open in Outlook: {failed}", True)
        return
    w.say(f"Opened the saved copy of “{e.subject or '(no subject)'}” in Outlook." if e.entry_id else
          f"Opened “{e.subject or '(no subject)'}” in Outlook, from its saved .msg.")


def on_link(w: BrowseWindow, kind: str, rest: str) -> None:
    """The section's and the page's own links."""
    if kind == "conv":
        task_id, conversation_id = split(rest)
        go(w, task_id, conversation_id)
    elif kind == "tmail":
        t_mails.new_t_mail(w, rest)
    elif kind == "outlook":
        capture_id, _, pos = rest.rpartition(":")
        if capture_id and pos.lstrip("-").isdigit():
            open_email(w, capture_id, int(pos))


def reply_task(w: BrowseWindow) -> str | None:
    """The task a Reply all on a conversation's page is a T-mail of: the one the page was opened from."""
    s = w.sel
    if s and s[0] == KIND:
        task_id = split(s[1])[0]
        return task_id if task_id in w.model().tasks else None
    return None
