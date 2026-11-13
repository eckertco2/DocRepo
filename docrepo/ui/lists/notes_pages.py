"""The task page's notes page: wiring it, loading and saving it, pictures and files dropped on it, its folds, its references, its history and its menu. Methods of ``BrowseWindow``, as a mixin it inherits (release 5.95, the review's F11): moved from
``browse_window.py`` unchanged, so they still use the window's own helpers through ``self``."""
from __future__ import annotations


import json
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from docrepo import all_notes, db, edits, notes_page
from docrepo.dates import long_date, to_date
from docrepo.detail import WIDE_PAGE
from docrepo.safe_fs import WriteRefused
from docrepo.save import SaveError
from docrepo.ui.notes_edit import OLD_DAYS
from docrepo.ui.task_pane import TaskPane


class NotesPages:
    """The task page's notes page: wiring it, loading and saving it, pictures and files dropped on it, its folds, its references, its history and its menu."""


    def _page_width_changed(self) -> None:
        """The pane crossed a width at which a task page lays itself out differently: draw it again."""
        if self.sel and self.sel[0] == "task" and self.detail_stack.currentIndex() == 2:
            self.render_detail(keep_scroll=True)

    # ---- the task page with its notes page (release 5.25) ----
    def wire_notes(self, pane: TaskPane, say: Callable[..., None], open_ref: Callable[[str], None]) -> None:
        """A notes page's signals: for the task page's pane (and, from release 5.37 to 5.97, a Task view's Notes page tab),
        which says things and opens what's clicked in its own window."""
        notes = pane.notes
        pane.say = say
        notes.changed.connect(lambda body: self._save_notes(body, pane))
        notes.open_ref.connect(open_ref)
        notes.open_link.connect(lambda href: self.on_link(QUrl(href)))  # Ctrl+click on a link (release 5.67)
        notes.message.connect(say)
        notes.folds_changed.connect(lambda: self._save_folds(pane))
        # Pictures pasted and files dropped on the page (release 5.27, decisions 124 to 126), and where a picture's file is.
        notes.picture_path = lambda doc: edits.source_of(self.ctx.data_root, self.model(), doc) if doc in self.model().documents else None
        notes.image_pasted.connect(lambda image: self._picture_pasted(image, pane))
        notes.files_dropped.connect(lambda paths: self._files_dropped(paths, pane))
        pane.notes_menu.connect(lambda which: self._notes_menu(which, pane))
        # This page or All notes (release 5.140, the notes consolidation plan's decisions 602 to 605), its links, and
        # Alt+Left back to the All notes a double-click left.
        pane.notes_mode.connect(lambda mode: self._set_notes_mode(mode, pane))
        # Move to task and Bring the lines back (release 5.143, the notes consolidation plan's decision 613).
        notes.move_requested.connect(lambda: self.move_to_task(pane))
        notes.bring_back.connect(lambda key: self.bring_lines_back(pane, key))
        pane.all_notes_link.connect(lambda href: self.on_link(QUrl(href)))
        QShortcut(QKeySequence("Alt+Left"), pane, context=Qt.ShortcutContext.WidgetWithChildrenShortcut, activated=self._back_to_all_notes)
        self._all_notes_from: tuple[str, int] | None = None
        # The outline beside the notes (release 5.113): shown until the owner hides it, then kept so for every task.
        pane.set_outline_on(db.get_state(self.conn, "notes_outline") != "0")
        pane.summary.folded.connect(lambda folded: self._save_summary_folded(folded, pane))

    def note_panes(self) -> list[TaskPane]:
        """Every notes page that's open: the task page's. Until release 5.98 each Task view's Notes page tab had one too."""
        return [self.task_pane]

    def save_open_notes(self) -> None:
        for pane in self.note_panes():
            pane.notes.save_now()

    def _page_changed(self, task_id: str, saved_in: TaskPane) -> None:
        """A page was saved in one window: any other showing it takes it at once, and each Find files reads its records
        again when it next needs them, so a page being typed doesn't redraw them (decision 244)."""
        for pane in self.note_panes():
            if pane is not saved_in and pane.task_id == task_id:
                self.load_notes(task_id, pane)
        for view in self.task_views.values():
            view.stale = True

    def _show_task(self, task_id: str, keep_scroll: bool) -> None:
        """Draw a task's page: its facts and history as HTML, and its notes page in the editor between them."""
        pane = self.task_pane
        scroll = pane.verticalScrollBar().value() if keep_scroll and pane.task_id == task_id else 0
        if pane.task_id != task_id:  # a meeting's notes unfolded, and All notes' window and page, are the task's own (5.140)
            self.state.meeting_open, self.state.notes_only, self.state.notes_weeks = "", "", all_notes.WEEKS
        pages = self.pages()
        width = pane.page_width()
        pane.show_parts(pages.task_parts(task_id, self.state, width), self._page_folds(task_id), width >= WIDE_PAGE)
        self.load_notes(task_id)
        self._show_notes_mode(task_id, pages)
        self.detail_stack.setCurrentIndex(2)
        pane.verticalScrollBar().setValue(scroll)
        if keep_scroll:
            QTimer.singleShot(0, lambda: pane.verticalScrollBar().setValue(scroll))

    # ---- All notes (release 5.140, the notes consolidation plan's decisions 602 to 605 and 609) ----
    def _show_notes_mode(self, task_id: str, pages=None) -> None:
        """The Notes heading's switch, shown when there's more than the page to read, and All notes in the frame when it's
        on for this task (kept with the page's folds, decision 602)."""
        pane = self.task_pane
        more = all_notes.has_more(self.model(), task_id)
        mode = "all" if more and self._page_folds(task_id).get("all_notes") else "page"
        pane.set_mode_switch(more, mode)
        if mode == "all":
            self.draw_all_notes(task_id, pages)
        elif pane.all_mode:
            pane.show_all_notes(None)

    def draw_all_notes(self, task_id: str, pages=None, keep_scroll: bool = False) -> None:
        """All notes in the frame, with its outline: its days, then the pages in it, each narrowing it to that page."""
        pane, m = self.task_pane, self.model()
        scroll = pane.verticalScrollBar().value()
        html, an = (pages or self.pages()).all_notes(task_id, self.state)
        entries: list[tuple[int, int, bool, str]] = []
        targets: list[tuple[str, str]] = []
        for day, _blocks in an.days:
            entries.append((len(targets), 1, True, notes_page.day_title(day)))
            targets.append(("day", day.isoformat()))
        if len(an.pages) > 1 or an.only:
            entries.append((len(targets), 1, True, "Pages"))
            targets.append(("", ""))
            if an.only:
                entries.append((len(targets), 2, False, "Every page"))
                targets.append(("page", ""))
            for x in an.pages:
                entries.append((len(targets), 2, False, "This task" if x == task_id else m.task(x).title))
                targets.append(("page", x))
        current = next((i for i, t in enumerate(targets) if t == ("page", an.only) and an.only), len(an.days) - 1 if an.days else -1)
        pane.show_all_notes(html, entries, targets, current)
        if keep_scroll:
            QTimer.singleShot(0, lambda: pane.verticalScrollBar().setValue(scroll))

    def _set_notes_mode(self, mode: str, pane: TaskPane | None = None) -> None:
        """The switch picked This page or All notes: kept for this task, and the frame drawn again."""
        pane = pane or self.task_pane
        task_id = pane.task_id
        if not task_id:
            return
        self._save_page_fold("all_notes", mode == "all", pane)
        if mode == "all":
            pane.notes.save_now()  # the page's last words, before they're read with the others
            self.draw_all_notes(task_id)
        else:
            pane.show_all_notes(None)
            self.load_notes(task_id, pane)
        pane.set_mode_switch(True, mode)

    def all_notes_link(self, kind: str, rest: str) -> None:
        """All notes' links: Show earlier and Show everything (decision 609), a page from its outline or Every page
        (decision 603), and Edit there or a double-click, which opens a block on its own page (decision 605)."""
        st, pane = self.state, self.task_pane
        if kind == "allnotes":
            if rest == "earlier":
                st.notes_weeks = st.notes_weeks + all_notes.WEEKS if st.notes_weeks else 0
            elif rest == "everything":
                st.notes_weeks = 0
            elif rest.startswith("only:"):
                st.notes_only = rest.removeprefix("only:")
            if pane.task_id:
                self.draw_all_notes(pane.task_id, keep_scroll=not rest.startswith("only:"))
            return
        task_id, _, capture_id = rest.partition(":")
        if task_id not in self.model().tasks:
            return
        here = pane.task_id
        folds = self._page_folds(task_id)
        if folds.get("all_notes"):  # its own page shows the lines (decision 605)
            folds["all_notes"] = False
            self.ctx.keep_state(f"page_folds:{task_id}", json.dumps(folds))
        if here:
            self._all_notes_from = (here, pane.verticalScrollBar().value())
        if task_id == here:
            pane.show_all_notes(None)
            self.load_notes(task_id, pane)
            pane.set_mode_switch(True, "page")
        if capture_id:
            self.go_to_block(task_id, capture_id)
        else:
            self.go_task(task_id)
        if here:
            self.say(f"Alt+Left goes back to {self.model().task(here).title}'s All notes.")

    def _back_to_all_notes(self) -> None:
        """Alt+Left: back to the All notes a double-click or Edit there left, where it was."""
        back, self._all_notes_from = self._all_notes_from, None
        if not back or back[0] not in self.model().tasks:
            return
        task_id, scroll = back
        folds = self._page_folds(task_id)
        folds["all_notes"] = True
        self.ctx.keep_state(f"page_folds:{task_id}", json.dumps(folds))
        self.go_task(task_id)
        if self.task_pane.task_id == task_id and not self.task_pane.all_mode:
            self._show_notes_mode(task_id)
        QTimer.singleShot(0, lambda: self.task_pane.verticalScrollBar().setValue(scroll))

    def load_notes(self, task_id: str, pane: TaskPane | None = None) -> None:
        """Put the task's notes page in the editor. The same task's page stays as it is unless docs.db holds another
        version (a capture added to it, say): then it's shown again, or, with unsaved typing, merged into it."""
        pane = pane or self.task_pane
        notes, m = pane.notes, self.model()
        body, day = m.pages.get(task_id, ""), m.uses_day_headings(task_id)
        if pane.task_id == task_id:
            notes.day_headings = day
            if body == notes.saved_body:
                return
            if notes.dirty:  # two writers: the typing keeps, the new blocks come in
                merged = notes_page.merge(notes.saved_body, notes.page(), body, day)
                notes.set_page(merged, notes.folds(), day)
                notes.saved_body = body
                notes.save_now()
                return
            caret = notes.textCursor().position()
            notes.set_page(body, notes.folds(), day)

            c = notes.textCursor()
            c.setPosition(min(caret, max(0, notes.document().characterCount() - 1)))
            notes.setTextCursor(c)
            return
        if pane.task_id and notes.dirty:
            notes.save_now()  # the page being left keeps its last words
        pane.task_id = task_id
        pane.saved.setText("")
        notes.set_page(body, self._folds_of(task_id), day)
        # Days older than a fortnight folded as the page opens, where the owner asked for it on this task (release 5.86).
        old_days = bool(self._page_folds(task_id).get("old_days"))
        pane.old_days_action.setChecked(old_days)
        if old_days:
            notes.fold_old_days(self.today() - timedelta(days=OLD_DAYS))
        pane.summary.set_folded(db.get_state(self.conn, f"checklist_folded:{task_id}") == "1")

    def _save_notes(self, body: str, pane: TaskPane | None = None) -> None:
        """The notes page saves as it's typed (decision 103): docs.db, the day's version, search and Task.md."""
        pane = pane or self.task_pane
        task_id = pane.task_id
        before = self.model().pages.get(task_id, "") if task_id else ""
        if not task_id or task_id not in self.model().tasks:
            return
        try:
            out = edits.save_page(self.conn, self.ctx.data_root, self.ctx.fs, task_id, body, self._now())
        except (edits.EditError, sqlite3.Error, OSError) as e:
            pane.say(f"The notes weren't saved: {e}", error=True)
            return
        pane.saved.setText(f"Saved {self._now():%H:%M}")
        if out.problems:
            pane.say(" ".join(out.problems), error=True)
        if notes_page.capture_ids(before) != notes_page.capture_ids(body):
            # The Captures tab says what's on the page: its history is drawn again, the editor left as it is.
            self._history_again(task_id)
        self._page_changed(task_id, pane)

    def _history_again(self, task_id: str) -> None:
        """The task page's history drawn again (its Captures tab says what's on the page), the editor left as it is."""
        if self.sel == ("task", task_id):
            parts = self.pages().task_parts(task_id, self.state, self.task_pane.page_width())
            self.task_pane.history.set_content(parts["history_summary"], parts["history"])

    def _picture_pasted(self, image, pane: TaskPane | None = None) -> None:
        """A picture pasted on the notes page (decisions 124, 125 and 127): a PNG in the task's Files folder, kept as a
        capture of the page's, and shown at the caret with an empty line under it for what it shows."""
        from docrepo.ui.rich_edit import png_bytes

        pane = pane or self.task_pane
        task_id = pane.task_id
        if not task_id:
            return
        try:
            capture_id, doc, name = edits.add_page_picture(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id,
                                                           png_bytes(image), self._now())
        except (edits.EditError, SaveError, WriteRefused, OSError, sqlite3.Error) as e:
            pane.say(f"The picture wasn't kept: {e}", error=True)
            return
        pane.notes.insert_item("picture", name, doc)
        pane.notes.save_now()
        self._history_again(task_id)
        pane.say(f"Kept {name} with the task's files, as {capture_id}. Type what it shows on the line under it.")

    def _files_dropped(self, paths: list[str], pane: TaskPane | None = None) -> None:
        """Files dropped on the notes page (decision 126): each kept as a capture of the page's, its original tracked where
        it is, and shown at the caret, a picture as a picture."""
        from docrepo import notes_page as np_

        pane = pane or self.task_pane
        task_id = pane.task_id
        if not task_id:
            return
        kept = []
        for path in paths:
            try:
                capture_id, doc, name = edits.add_page_file(self.conn, self.ctx.data_root, self.ctx.fs, self.ctx.settings, task_id, path,
                                                            self._now())
            except (edits.EditError, SaveError, WriteRefused, OSError, sqlite3.Error) as e:
                pane.say(f"{Path(path).name} wasn't kept: {e}", error=True)
                continue
            picture = name.lower().endswith(np_.PICTURES)
            pane.notes.insert_item("picture" if picture else "attachment", name if picture else f"File: {name}", doc)
            kept.append(name)
        if kept:
            pane.notes.save_now()
            self._history_again(task_id)
            pane.say(f"Added {', '.join(kept)} to the page, each a capture of its own. Type what each is on the line under it.")

    def _page_folds(self, task_id: str) -> dict[str, bool]:
        """Which groups of a task's page are open (release 5.84): "status_log", "history" and each expander's key."""
        try:
            out = json.loads(db.get_state(self.conn, f"page_folds:{task_id}") or "{}")
            return out if isinstance(out, dict) else {}
        except ValueError:
            return {}

    def _save_page_fold(self, key: str, is_open: bool, pane: TaskPane | None = None) -> None:
        task_id = (pane or self.task_pane).task_id
        if task_id:
            folds = self._page_folds(task_id)
            folds[key] = is_open
            self.ctx.keep_state(f"page_folds:{task_id}", json.dumps(folds))

    def _folds_of(self, task_id: str) -> list[str]:
        try:
            return list(json.loads(db.get_state(self.conn, f"notes_folds:{task_id}") or "[]"))
        except ValueError:
            return []

    def _save_folds(self, pane: TaskPane | None = None) -> None:
        """Which headings are folded, kept for each task in docs.db (the data root), as the app writes nowhere else."""
        pane = pane or self.task_pane
        if pane.task_id:
            self.ctx.keep_state(f"notes_folds:{pane.task_id}", json.dumps(pane.notes.folds()))

    def _save_summary_folded(self, folded: bool, pane: TaskPane | None = None) -> None:
        """Whether the Checklist summary is folded, kept for each task in docs.db (decision 121)."""
        pane = pane or self.task_pane
        if pane.task_id:
            self.ctx.keep_state(f"checklist_folded:{pane.task_id}", "1" if folded else "0")

    def open_ref(self, ref: str) -> None:
        if ref.startswith(("moved:", "from:")):  # a pointer line, or a lead line (release 5.143): the other page, at the move
            scheme, _, rest = ref.partition(":")
            pair = notes_page.pair_of(rest)
            if pair:
                self.open_move(pair[0], pair[1], "from" if scheme == "moved" else "moved")
            return
        if ref in self.model().captures:
            self.go_capture(ref)
        elif ref in self.model().documents:
            self.on_link(QUrl(f"doc:{ref}"))
        elif ref in self.model().tasks:  # a task line on a notes page (release 5.83)
            self.go_task(ref)

    # ---- Move to task (release 5.143, the notes consolidation plan's decision 613) ----
    def move_to_task(self, pane: TaskPane | None = None) -> None:
        """Alt+Shift+M or the menu: the lines picked (or the caret's, with its list items) go to a task picked from the #
        list, the page keeping a pointer line where they were; said with Undo."""
        pane = pane or self.task_pane
        task_id, notes = pane.task_id, pane.notes
        if not task_id:
            return
        span = notes.line_span()
        if span is None:
            self.say("Put the caret on the lines to move, or pick them, then Move to task.")
            return
        notes.save_now()
        start, end, lines = span
        raw = notes_page.get(self.conn, task_id).split("\n")
        end = min(end, len(raw))
        expect = raw[start:end]
        if [x.rstrip() for x in expect] != [x.rstrip() for x in lines[:len(expect)]]:
            self.say("The page is still saving. Pick the lines again in a moment.", error=True)
            return
        from docrepo.ui.task_picker import TaskPicker

        def picked(target: str | None) -> None:
            if target:
                self._move_lines(pane, task_id, start, end, target, expect)

        self._picker = TaskPicker(self, self.model, None, keep=lambda t: t != task_id)
        self._picker.picked.connect(picked)
        self._picker.setMinimumWidth(360)
        self._picker.popup(notes.viewport().mapToGlobal(notes.cursorRect().bottomLeft()))

    def _move_lines(self, pane: TaskPane, task_id: str, start: int, end: int, target: str, expect: list[str]) -> None:
        conn, ctx = self.conn, self.ctx
        done = self._do(lambda: edits.move_lines(conn, ctx.data_root, ctx.fs, task_id, start, end, target, self._now(), expect))
        if not isinstance(done, tuple):
            return
        out, moved = done
        self.load_notes(task_id, pane)
        undone: list[bool] = []

        def undo() -> None:
            if not undone:
                undone.append(True)
                self._do(lambda: edits.undo_move_lines(conn, ctx.data_root, ctx.fs, moved, self._now()))
                if pane.task_id == task_id:
                    self.load_notes(task_id, pane)

        self.say_undo(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), undo)

    def bring_lines_back(self, pane: TaskPane | None, key: str) -> None:
        """A pointer line's Bring the lines back: the moved lines back in its place, off the other page."""
        pane = pane or self.task_pane
        task_id = pane.task_id
        if not task_id:
            return
        pane.notes.save_now()
        out = self._do(lambda: edits.bring_lines_back(self.conn, self.ctx.data_root, self.ctx.fs, task_id, key, self._now()))
        if isinstance(out, edits.Outcome):
            self.load_notes(task_id, pane)
            self.say(out.message)

    def open_move(self, task_id: str, key: str, scheme: str) -> None:
        """A pointer's other end: the page the lines went to, at their lead line (``from``), or the page they came from,
        at its pointer (``moved``), on This page."""
        if task_id not in self.model().tasks:
            self.say("That task isn't there any more.", error=True)
            return
        folds = self._page_folds(task_id)
        if folds.get("all_notes"):  # its own page shows the line (5.140's All notes is read only)
            folds["all_notes"] = False
            self.ctx.keep_state(f"page_folds:{task_id}", json.dumps(folds))
        if self.sel != ("task", task_id):
            self.go_task(task_id)
        elif self.task_pane.all_mode:
            self._show_notes_mode(task_id)
        if scheme == "from" and key.startswith("C"):  # a meeting's #task section (decision 614): the item's block there
            if self.task_pane.notes.go_to(key, self._refs_of(key)):
                QTimer.singleShot(0, self.task_pane.scroll_to_caret)
        elif self.task_pane.notes.go_to_key(key, scheme):
            QTimer.singleShot(0, self.task_pane.scroll_to_caret)

    def _refs_of(self, capture_id: str) -> list[str]:
        """A capture's documents: how its block is found on a page when it has no caption (release 5.83)."""
        c = self.model().captures.get(capture_id)
        return list(c.document_ids) if c else []

    def go_to_block(self, task_id: str, capture_id: str) -> None:
        """The Captures tab's On the notes page: the capture's block, unfolded, with the caret on its caption."""
        if self.sel != ("task", task_id):
            self.go_task(task_id)
        if self.task_pane.notes.go_to(capture_id, self._refs_of(capture_id)):
            QTimer.singleShot(0, self.task_pane.scroll_to_caret)
        else:
            self.say(f"{capture_id} isn't on the notes page.")

    def add_again(self, task_id: str, capture_id: str) -> None:
        self.save_open_notes()
        self._do(lambda: edits.add_again(self.conn, self.ctx.data_root, self.ctx.fs, capture_id, task_id, self._now()))
        if self.task_pane.task_id == task_id:
            self.task_pane.notes.go_to(capture_id, self._refs_of(capture_id))
            QTimer.singleShot(0, self.task_pane.scroll_to_caret)

    def _notes_menu(self, which: str, pane: TaskPane | None = None) -> None:
        pane = pane or self.task_pane
        task_id, notes = pane.task_id, pane.notes
        if not task_id:
            return
        if which in ("fold", "unfold"):
            notes.fold_all(which == "fold")
        elif which == "old_days":
            on = pane.old_days_action.isChecked()
            self._save_page_fold("old_days", on, pane)
            n = notes.fold_old_days(self.today() - timedelta(days=OLD_DAYS), on)
            self._save_folds(pane)
            days = f"{n} day{'s' if n != 1 else ''}"
            pane.say(f"Days older than two weeks fold when this page opens: {days} folded now." if on
                     else f"Days older than two weeks stay open on this page: {days} unfolded.")
        elif which == "history":
            self.page_history(task_id, pane)
        elif which == "outline":
            db.set_state(self.conn, "notes_outline", "1" if pane.outline_on else "0")

    def page_history(self, task_id: str, pane: TaskPane | None = None) -> None:
        """Page history (decision 103): the page as it stood at the end of each day it changed, and Restore, which is an
        edit like any other, so the page as it stands now is kept too."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QListWidgetItem

        from docrepo.ui.notes_edit import NotesEdit

        pane = pane or self.task_pane
        self.save_open_notes()
        days = notes_page.versions(self.conn, task_id)
        if not days:
            pane.say("This page has no earlier versions yet.")
            return
        dlg = QDialog(pane.window())
        dlg.setWindowTitle(f"Page history: {self.model().task(task_id).title}")
        dlg.resize(820, 560)
        lay = QHBoxLayout(dlg)
        listing = QListWidget()
        listing.setMaximumWidth(220)
        for day, by_owner in days:
            item = QListWidgetItem(f"{long_date(to_date(day), self.today())}" + ("" if by_owner else " · captures only"))
            item.setData(Qt.ItemDataRole.UserRole, day)
            listing.addItem(item)
        right = QVBoxLayout()
        shown = NotesEdit()
        shown.setReadOnly(True)
        shown.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        shown.setSizePolicy(shown.sizePolicy().horizontalPolicy(), shown.sizePolicy().Policy.Expanding)
        shown.setMinimumHeight(360)
        shown._fit = lambda: None  # the dialog's view scrolls
        buttons = QDialogButtonBox()
        restore = buttons.addButton("Restore this version", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.reject)
        right.addWidget(QLabel("The page as it stood at the end of the day. Restoring it is an edit: today's page is kept too."))
        right.addWidget(shown, 1)
        right.addWidget(buttons)
        lay.addWidget(listing)
        lay.addLayout(right, 1)

        def show(row: int) -> None:
            day = listing.item(row).data(Qt.ItemDataRole.UserRole)
            shown.set_page(notes_page.version(self.conn, task_id, day) or "")

        listing.currentRowChanged.connect(show)
        listing.setCurrentRow(0)
        restore.clicked.connect(dlg.accept)
        self._history_dialog = dlg  # kept, so tests can reach it
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        day = listing.currentItem().data(Qt.ItemDataRole.UserRole)
        body = notes_page.version(self.conn, task_id, day) or ""
        if self._do(lambda: edits.save_page(self.conn, self.ctx.data_root, self.ctx.fs, task_id, body, self._now())):
            pane.say(f"Restored the page as it stood on {long_date(to_date(day), self.today())}.")
