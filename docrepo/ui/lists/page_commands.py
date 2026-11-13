"""Each page's commands in the command bar (a task's, a capture's, a document's, a person's, a label's), the page's links, and the page's menu. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


from collections.abc import Callable
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QMenu,
)

from docrepo import edits, prompts, task_commands
from docrepo.captures import capture_md_path
from docrepo.detail import SCOPE_NAMES
from docrepo.links import is_folder, is_link
from docrepo.schedule import is_open
from docrepo.ui import conversation_page, decision_register, t_mails, task_menus
from docrepo.ui.lists import review as review_list
from docrepo.ui.icons import icon
from docrepo.ui.look import LOOK
from docrepo.views import full_path


class PageCommands:
    """Each page's commands in the command bar (a task's, a capture's, a document's, a person's, a label's), the page's links, and the page's menu."""


    # ---- the task page's actions ----
    def _task_actions(self, task_id: str) -> None:
        """The task page's command bar (release 5.21, decision 68): Note, Update, Meeting notes for an open meeting, New
        T-mail with Reply all to the latest email on its arrow (release 5.105), Add to (Today and the agendas), Edit, and
        More at the row's end. Add to and Edit are the menus every task row has too, from
        one list each (release 5.98, decision 392); Find files opens from the Files group and O (decision 389)."""
        m, t = self.model(), self.model().task(task_id)
        if t.discarded:
            self._action("Bring back", lambda: self.bring_back_task(task_id), "Restore it as it was: back in the task tree, the lists and search",
                         primary=True)
            self._action("Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / task_id), f"Open Tasks\\{task_id} in File Explorer")
            return
        menu_key = "   " if LOOK.classic else "\t"  # a menu's key column; the Classic look puts the key after the label
        if self.view == "review":  # the weekly review's step 4 (release 5.128): Mark reviewed first
            review_list.page_actions(self, task_id)
        self._action("Note", lambda: self.open_capture(task=task_id, mode="note"), "Add a note to this task's notes page", icon_name="note", key="N")
        self._action("Update", lambda: self.open_capture(task=task_id, mode="update"), "Update this task: its state, status, dates and more",
                     icon_name="update", key="U")
        if t.meeting and is_open(t):  # release 5.8
            self._action("Meeting notes", lambda: self.open_capture(task=task_id, meeting=True),
                         "Take this meeting's notes, with its agenda beside them", icon_name="people", key="M")
        # New T-mail (the knowledge base's stage K8, release B, as release 5.105, decision 36): one click opens a new email
        # in Outlook tagged for this task; its arrow has Reply all to the task's latest email, and since release 5.125 Ask
        # for an update (the cold-eyes plan's decision 481).
        self._split_action("New T-mail", lambda: t_mails.new_t_mail(self, task_id),
                           "A new email in Outlook, empty, tagged so its replies come back to this task when you capture them. "
                           "You write and send it; DocRepo never sends email.",
                           t_mails.latest_menu(self, task_id, self),
                           "More T-mails: Reply all to the latest email filed to this task, or Ask for an update",
                           icon_name="mail")
        self._action(task_commands.ADD_TO, tip="Put it on Today (D) or an agenda", menu=task_menus.add_to_menu(self, task_id, self),
                     icon_name="agenda", key="A")
        # Edit is a split button (decision 392, the mock's, the owner's choice of 2026-11-07): Edit task, and a chevron
        # for the rest of the Edit menu.
        self._split_action(task_commands.EDIT, lambda: self.edit_task(task_id), "Edit task: every field on one page",
                           task_menus.edit_menu(self, task_id, self), "More ways to edit: Move…, Put under…, Also put under…, Remove from under… and Discard…",
                           icon_name="edit", key="E")
        # More: New task under this one, the agenda, Copy (release 5.9: its people's email addresses, M0031, and each reference field,
        # M0034), Copy prompt for each summary type, and the folder.
        more = QMenu(self)
        more.addAction(icon("add"), f"New task under this one{menu_key}T", lambda: self.open_capture(task=task_id, mode="new_task"))
        if self.pages().has_agenda(t):
            more.addAction(icon("agenda"), "Open agenda", lambda: self.show_agenda(task_id))
        copy = QMenu("Copy", more)
        copy.setIcon(icon("copy"))
        people_ids = [*t.leads, *t.assignees]
        if any(m.people[p].email for p in people_ids if p in m.people):
            copy.addAction("Emails of its lead and assignees", lambda: self.copy_emails(people_ids))
        for name, value in t.references.items():
            copy.addAction(f"{name} {value}", lambda n=name: self.copy_reference(task_id, n))
        if copy.actions():
            more.addMenu(copy)
        self.summary_type = QComboBox()
        self.summary_type.setAccessibleName("Summary type")
        self._summary_types = prompts.load_summary_types(self.ctx.data_root)
        self.summary_type.addItems([st.name for st in self._summary_types])
        prompt = more.addMenu(icon("copy"), "Copy prompt")
        for i, st in enumerate(self._summary_types):
            prompt.addAction(st.name, lambda n=i: (self.summary_type.setCurrentIndex(n), self.copy_prompt(task_id)))
        more.addAction(icon("templates"), "Save as template…", lambda: self.templates.save_as(task_id))
        more.addAction(icon("templates"), "Apply template…", lambda: self.templates.apply([task_id]))
        more.addAction("Export tree…", lambda: self.tree_files.export_task(task_id))
        more.addAction("Bring back an edit file…", self.tree_files.import_tree)
        if task_id in m.origins:
            more.addAction("Detach from template…", lambda: self.templates.detach(task_id))
        more.addAction(icon("folder"), "Open folder", lambda: self.reveal(self.ctx.data_root / "Tasks" / task_id))
        b = self._action("More" if LOOK.classic else "", tip="More: New task under this one, Open agenda, Copy, Copy prompt, Save as template, Export tree and Open folder", menu=more,
                         icon_name="more")
        b.setAccessibleName("More")
        b.setProperty("flowEnd", True)  # at the row's end
        if not LOOK.classic:
            b.setObjectName("iconOnly")
            b.setProperty("menu", False)
            b.style().unpolish(b)
            b.style().polish(b)

    def _capture_actions(self, capture_id: str) -> None:
        m = self.model()
        c = m.captures[capture_id]
        if c.discarded:
            self._action("Bring back", lambda: self.bring_back_capture(capture_id), "Restore it to its tasks' logs and search", primary=True)
            self._action("Show in File Explorer", lambda: self.reveal(capture_md_path(self.ctx.data_root, c)))
            return
        readable = self._capture_text(capture_id) is not None
        self._action("Edit", lambda: self.start_capture_edit(capture_id), "Fix its title or summary", readable)
        self._action("Show in File Explorer", lambda: self.reveal(capture_md_path(self.ctx.data_root, c)))
        self._action("Discard…", lambda: self.discard_capture(capture_id), "Hide a capture saved by mistake. Its folder stays.")
        if m.is_unfiled(c):
            picked = self.file_to.get(capture_id)
            text = full_path(m, picked) if picked in m.tasks else "Pick a task"
            pick = self._action(text, tip="Pick the task to file this capture to", drop=True)
            pick.clicked.connect(lambda: self._pick_task(pick, lambda tid: self._set_file_to(capture_id, tid), None))
            self._action("File to task", lambda: self.file_capture(capture_id), "File this capture to the picked task", picked in m.tasks, primary=True)
            self._action("Make it a task", lambda: self.open_capture(from_capture=capture_id), "Create a task from this capture, and file it there")

    def _doc_actions(self, document_id: str) -> None:
        m = self.model()
        if is_link(m.documents[document_id].original):  # Open link since release 5.67 (decision 315)
            self._action("Open link", lambda: self.open_document_link(document_id), "Open it in your default browser", primary=True)
            self._action("Copy link", lambda: self.copy_link(document_id), "Copy the address")
            return
        if is_folder(m.documents[document_id].original):  # release 5.66
            self._action("Show in File Explorer", lambda: self.open_document_link(document_id), "Open the folder in File Explorer", primary=True)
            return
        source = edits.source_of(self.ctx.data_root, m, document_id)
        self._action("Show in File Explorer", lambda: self.reveal(source) if source else None, "Show the original", source is not None)
        text = self.ctx.data_root / "Documents" / document_id / "extracted.txt"
        self._action("Show extracted text", lambda: self.reveal(text), "Show its extracted.txt", text.exists())

    def _person_actions(self, person_id: str) -> None:
        p = self.model().people[person_id]
        self._action("Edit…", lambda: self.edit_person(person_id))
        if p.email:
            self._action("Copy email", lambda: self.copy_emails([person_id]), "Copy their address. DocRepo never sends email.")
        if p.status == "active":
            self._action("Retire", lambda: self.set_person_status(person_id, "retired"), "Hide this person from pickers and lists. Nothing is deleted.",
                         person_id != self.ctx.settings.me)
        else:
            self._action("Make active", lambda: self.set_person_status(person_id, "active"))
        if self.model().open_items_for(person_id):
            self._action("Open agenda", lambda: self.show_agenda(person_id))

    def _label_actions(self, name: str) -> None:
        label = next(lb for lb in self.model().labels if lb.name == name)
        self._action("Edit…", lambda: self.edit_label(name))
        self._action("Find matching tasks…", lambda: self.find_label_tasks(name),
                     "List the open tasks that mention its keywords but don't have it, to add it to those you tick")
        if label.status == "active":
            self._action("Retire", lambda: self.set_label_status(name, "retired"), "Hide this label from pickers. Its tasks keep it.")
        else:
            self._action("Make active", lambda: self.set_label_status(name, "active"))

    # ---- links on a page ----
    def on_link(self, url: QUrl) -> None:
        kind, _, rest = url.toString().partition(":")
        st = self.state
        if kind == "state":  # the task page's state (release 5.76, decision 361): its menu, at the pointer
            self.popup_state_menu(rest, QCursor.pos())
            return
        if kind == "task":
            self.go_task(rest)
        elif kind == "capture":
            self.go_capture(rest)
        elif kind == "replyall":  # an email's Reply all on its capture's page (release 5.105)
            capture_id, _, pos = rest.rpartition(":")
            if capture_id and pos.isdigit():  # on a conversation's page, a T-mail of the task it was opened from (5.122)
                t_mails.reply_all(self, capture_id, int(pos), conversation_page.reply_task(self))
        elif kind in conversation_page.LINKS:  # Email conversations and a conversation's page (release 5.122)
            conversation_page.on_link(self, kind, rest)
        elif kind == decision_register.LINK:  # the Decisions section's Copy (release 5.124, decision 479)
            decision_register.copy(self, rest)
        elif kind == "meetrow":  # a meeting's row in Meetings, unfolded or folded (release 5.140, decision 607)
            st.meeting_open = "" if st.meeting_open == rest else rest
            self.render_detail(keep_scroll=True)
        elif kind == "meetingnotes":  # the Meetings section's Meeting notes (decision 607)
            self.open_capture(task=rest, meeting=True)
        elif kind in ("allnotes", "notesgo"):  # All notes' links (release 5.140, decisions 603, 605 and 609)
            self.all_notes_link(kind, rest)
        elif kind == "doc":
            self.view = "docs"
            self.select("doc", rest, update_list=True)
        elif kind == "person":
            self.select("person", rest, update_list=True)
        elif kind == "label":
            self.select("label", unquote(rest), update_list=True)
        elif kind == "tagged":  # a tagged label (release 5.79): its page, in the Tagged labels view
            self.view = "tagged"
            self.select("tagged", unquote(rest), update_list=True)
        elif kind in ("taggedrm", "taggedback", "taggedadd"):  # the owner's own changes on an item (decision 376)
            from docrepo.ui.lists import tagged as tagged_list

            tagged_list.on_link(self, kind, rest)
        elif kind == "tplrow":  # release 5.44
            self.templates.open_row(rest)
        elif kind == "tpltiming":  # release 5.51
            self.templates.timing(int(rest))
        elif kind == "agenda":
            self.show_agenda(rest)
        elif kind == "summary":  # a person's, a label's or an agenda's quick summary (release 5.131)
            self.ctx.open_summary(unquote(rest))
        elif kind == "show":
            self.reveal_key(tuple(rest.split(":", 1)))
        elif kind == "copylink":
            self.copy_link(rest)
        # Links open, on a click (release 5.67, round 6's decisions 314 to 316): a link or folder document, an address
        # (a reference field's link, or one in a note's words), its Copy, Find files' links, and Settings.
        elif kind == "opendoc":
            self.open_document_link(rest)
        elif kind == "openurl":
            self.open_address(unquote(rest))
        elif kind == "copyaddr":
            QGuiApplication.clipboard().setText(unquote(rest))
            self.say("Copied the path." if is_folder(unquote(rest)) else "Copied the link.")
        elif kind == "taskviewlinks":
            self.open_task_view(rest, file_type="link")
        elif kind == "settings":
            self.set_view("settings")
        elif kind == "taskview":  # the Files group's Find files (decision 166; the Task view until release 5.98)
            self.open_task_view(rest)
        elif kind in ("tab", "scope", "order"):
            setattr(st, kind, rest)
            if kind == "tab" and rest in ("log", "files"):  # since release 5.84 these are groups of the page, not tabs
                if rest == "log":
                    self.task_pane.header.set_log_open(True, emit=True)
                else:
                    self.task_pane.header.groups["files"].set_open(True, emit=True)
            self.render_detail(keep_scroll=kind != "tab")
        elif kind in ("chap", "more", "orig"):
            group = {"chap": st.chapters, "more": st.expanded, "orig": st.originals}[kind]
            group.symmetric_difference_update({rest})
            self.render_detail(keep_scroll=True)
        elif kind == "chapall":
            st.chapters = set(self.model().tasks) if rest == "open" else set()
            self.render_detail(keep_scroll=True)
        # The task page's own (release 5.21): Details, the whole description and the closed subtasks, the history's scope
        # and order menus, New task under this one, Add one (an update), a reference field's Copy, and the task's folder.
        elif kind == "fold" and rest in ("details", "desc", "closed", "conversations", "decisions", "meetings"):
            setattr(st, rest, not getattr(st, rest))
            if rest == "details":  # since release 5.84 Details is a group of the page; the link opens it
                self.task_pane.header.groups["details"].set_open(st.details, emit=True)
            self.render_detail(keep_scroll=True)
        elif kind == "menu":
            self._page_menu(rest)
        elif kind == "new":
            self.open_capture(task=rest, mode="new_task")
        elif kind == "update":
            self.open_capture(task=rest, mode="update")
        elif kind == "progress" and rest in self.model().tasks:  # the status card's Log progress… (release 5.139, decision 583)
            self.ctx.log_progress(rest)
        elif kind == "gotit" and rest in self.model().tasks:  # the status card's Got it (decision 581)
            self.got_it(rest)
        elif kind == "copyref" and self.sel and self.sel[0] == "task":
            self.copy_reference(self.sel[1], unquote(rest))
        elif kind == "folder" and rest in self.model().tasks:
            self.reveal(self.ctx.data_root / "Tasks" / rest)
        # The Captures tab (release 5.25): a capture's block on the notes page, or Add it again (decision 109).
        elif kind == "kd" and ":" in rest:  # a key date on the task page (release 5.31)
            action, _, key = rest.partition(":")
            if action == "subtask":
                self.key_date_subtask(int(key))
            else:
                self.key_date_done(int(key), action == "done")
        elif kind in ("goto", "readd") and ":" in rest:
            task_id, capture_id = rest.split(":", 1)
            (self.go_to_block if kind == "goto" else self.add_again)(task_id, capture_id)

    def got_it(self, task_id: str) -> None:
        """Got it (release 5.139, decision 581): the task's wait ends by the owner's word, and the follow-up it set goes."""
        from docrepo import progress

        title = self.model().task(task_id).title
        if progress.got_it(self.conn, self.ctx.settings, task_id, self.ctx.now()):
            self.say(f"{title} isn't waiting any more; its follow-up is gone.", False)
            self.ctx.today_changed()
            self.refresh()

    def _page_menu(self, which: str) -> None:
        """The task page's history menus: which tasks' entries it shows, with Open all and Close all chapters, and the
        order (release 5.21)."""
        st, menu = self.state, QMenu(self)

        def pick(name: str, value: str) -> Callable[[], None]:
            return lambda: (setattr(st, name, value), self.render_detail(keep_scroll=True))

        if which == "scope":
            for key, label in SCOPE_NAMES.items():
                act = menu.addAction(label, pick("scope", key))
                act.setCheckable(True)
                act.setChecked(st.scope == key)
            menu.addSeparator()
            menu.addAction("Open all chapters", lambda: self.on_link(QUrl("chapall:open")))
            menu.addAction("Close all chapters", lambda: self.on_link(QUrl("chapall:close")))
        elif which == "order":
            for key, label in (("old", "Oldest first"), ("new", "Newest first")):
                act = menu.addAction(label, pick("order", key))
                act.setCheckable(True)
                act.setChecked(st.order == key)
        else:
            return
        self._menu = menu  # kept, so it stays open and tests can read it
        menu.popup(QCursor.pos())
