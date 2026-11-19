"""The workspace (release 5.152; the design workspace's ``docs/mods/workspace-view-plan.md``, decisions 663 to 670, 678 to
687 and 698 to 702): the task page laid out for doing the work, in the browse window beside the places (682), in the list's
and the page's room. It's a way of showing the task page, not a window of its own (663).

- **Work on it** (W) opens it from a selected task, a tile's right-click menu and the task page's bar; a double-click or
  Enter on a Today row opens it too (667). Esc, or Task page, goes back where it came from, with the task picked there; a
  place picked in the sidebar leaves it for that place (682).
- **The head and the bar** (666): back, the task's name and facts, then Note, Update, Log progress…, New T-mail, Meeting
  notes, Find files and, opened from Today while the task is on it, Done for today, which keeps you here (687). Its end
  has a place for the agent buttons to come, which shows nothing until there's one. Picking a subtask makes the bar act on
  it, saying so (684).
- **The chain** (664, 686): the project down to this task, then its subtasks. A click on a parent reads its notes in the
  middle (668), a click on a subtask edits its notes in place (684); a double-click works on it.
- **The middle** (664, 678, 681, 683 and 701): the status card with the quick entry bar, the notes with the chain's
  outline, and Dates. **The resources** (664, 679, 680, 685): a search box over Links, Files, Email conversations, Meetings
  and Decisions of the task picked, everything under it and every task above it (700).

What's shown is ``docrepo.workspace``'s; the widgets are ``docrepo.ui.workspace_parts``. Notes are the task page's own:
the middle column is a ``TaskPane``, wired as the task page's is (``NotesPages.wire_notes``).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget

from docrepo import all_notes, edits, meeting_rows, notes_page, progress, task_tile, topics, waits
from docrepo import workspace as ws
from docrepo.dates import days_words, long_date, short, to_date
from docrepo.detail import PageState, esc, link
from docrepo.model import TODAY
from docrepo.safe_fs import WriteRefused
from docrepo.save import CaptureDraft, SaveError, save_capture
from docrepo.tasks import TaskError
from docrepo.ui import tokens
from docrepo.ui.front import bring_to_front
from docrepo.ui.icons import icon
from docrepo.ui.lists.notes_pages import grouped_outline
from docrepo.ui.look import LOOK
from docrepo.ui.page_view import PageView
from docrepo.ui.progress_form import ProgressForm, guarded, said_after
from docrepo.ui.style import page_css
from docrepo.ui.workspace_parts import (RESOURCES_WIDTH, CardFacts, ChainCard, ChainColumn, DatesView, StatusCard,
                                        WorkPane, search_box, status_line)

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: The command's name, on menus and the task page's bar.
WORK_ON_IT = "Work on it"
WORK_TIP = "Its workspace: the chain of tasks above it, its notes and theirs, its dates and resources, to do the work (W)"


def _style() -> str:
    t = tokens.colour
    return (f"QWidget#workspace {{ background: {t('content')}; }}"
            f"QWidget#wsHead, QWidget#wsBar {{ background: {t('content')}; }}"
            f"QWidget#wsBar {{ border-bottom: 1px solid {t('stroke')}; }}"
            f"QScrollArea#wsChain, QWidget#wsChainInner, QWidget#wsResources {{ background: {t('base')}; }}"
            f"QScrollArea#wsChain {{ border-right: 1px solid {t('stroke')}; }}"
            f"QWidget#wsResources {{ border-left: 1px solid {t('stroke')}; }}"
            f"QLabel#wsCaption {{ color: {t('text2')}; padding-top: 6px; }}"
            f"QLabel#wsKicker {{ color: {t('accent')}; }}"
            f"QFrame#wsChainCard {{ background: {t('content')}; border: 1px solid {t('stroke')}; border-radius: 6px; }}"
            f"QFrame#wsChainCard:hover {{ border-color: {t('stroke_strong')}; }}"
            f"QFrame#wsChainCard[picked=\"true\"] {{ background: {t('selected')}; border-color: {t('accent')}; }}"
            f"QLabel#wsStatus {{ color: {t('text2')}; }}"
            f"QLabel#wsThis {{ color: {t('accent')}; }}"
            f"QLabel#wsNote {{ color: {t('accent')}; }}"
            f"QLabel#wsBanner {{ background: {t('info_bg')}; border-radius: 4px; padding: 7px 10px; margin-bottom: 6px; }}"
            f"QLabel#wsOn {{ color: {t('accent')}; background: {t('info_bg')}; border-radius: 10px; padding: 2px 9px; }}"
            f"QFrame#wsAgents {{ border: 1px dashed {t('stroke_strong')}; border-radius: 4px; }}"
            f"QPushButton#wsLink {{ color: {t('accent')}; border: none; background: transparent; padding: 0; text-align: left; }}"
            f"QPushButton#wsLink:hover {{ text-decoration: underline; }}"
            f"QPushButton#wsDay {{ color: {t('text')}; border: none; background: transparent; padding: 2px 0; text-align: left; }}"
            f"QPushButton#wsDay:hover {{ color: {t('accent')}; text-decoration: underline; }}")


class Workspace(QWidget):
    """The workspace in the browse window (``browse.workspace``). ``here`` is the task it's the workspace of; ``picked``
    the task picked in the chain (``here`` until another is); ``meeting`` a meeting whose notes are read in the middle."""

    def __init__(self, browse: BrowseWindow) -> None:
        super().__init__(objectName="workspace")
        self.browse = browse
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if not LOOK.classic:
            self.setStyleSheet(_style())
        self.here = ""
        self.picked = ""
        self.meeting = ""
        self.origin = TODAY
        self.from_today = False
        #: All notes' window, in the middle (release 5.140's own, kept for the workspace).
        self.state = PageState(order="new")
        self.mode = "page"
        self.folded: set[str] = set()
        self.show_earlier = False
        self.show_closed = False
        self.editing = ""
        #: Where Edit there left it, for Alt+Left back: (here, picked, origin, from_today).
        self.came_from: tuple[str, str, str, bool] | None = None
        self._found: tuple[tuple, dict] | None = None
        self._sizes: list[int] | None = None
        #: The browse window as it was before the workspace maximised it (release 5.165, decision 771): whether it was
        #: maximised, and its size and place, restored when the workspace goes.
        self._window: tuple[bool, QRect] | None = None
        self._rows: dict[str, ws.DateRow] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_head())
        lay.addWidget(self._build_bar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.chain = ChainColumn()
        self.chain.picked.connect(self.pick)
        self.chain.opened.connect(self._work_on)
        self.chain.menu.connect(self._tile_menu)
        self.chain.state_clicked.connect(lambda task_id, at: browse.popup_state_menu(task_id, at))
        self.chain.link.connect(self.on_link)
        body.addWidget(self.chain)
        body.addWidget(self._build_middle(), 1)
        body.addWidget(self._build_resources())
        lay.addLayout(body, 1)
        QShortcut(QKeySequence("Alt+Left"), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut, activated=self.back)

    # ---- building ----
    def _build_head(self) -> QWidget:
        head = QWidget(objectName="wsHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 16, 4)
        hl.setSpacing(12)
        self.back_button = QPushButton("Today", objectName="subtle")
        self.back_button.setIcon(icon("chevron-left"))
        self.back_button.setToolTip("Back to Today, with the task picked there (Esc)")
        self.back_button.clicked.connect(self.close_to_origin)
        names = QVBoxLayout()
        names.setSpacing(0)
        kicker = QLabel("WORKSPACE", objectName="wsKicker")
        kicker.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        self.title = QLabel(objectName="paneTitle")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(kicker)
        names.addWidget(self.title)
        self.facts = QLabel(objectName="hint")
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        self.facts.linkActivated.connect(self.on_link)
        self.page_button = QPushButton("Task page", objectName="subtle")
        self.page_button.setIcon(icon("open"))
        self.page_button.setToolTip("Its task page, beside the list it was opened from")
        self.page_button.clicked.connect(self.close_to_origin)
        hl.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addLayout(names)
        hl.addWidget(self.facts, 1, Qt.AlignmentFlag.AlignBottom)
        hl.addWidget(self.page_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    def _build_bar(self) -> QWidget:
        bar = QWidget(objectName="wsBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.bar = QHBoxLayout(bar)
        self.bar.setContentsMargins(12, 2, 12, 6)
        self.bar.setSpacing(2)
        self.on_label = QLabel(objectName="wsOn")
        self.on_label.setFont(tokens.ui_font(tokens.CAPTION))
        self.on_label.hide()
        self.bar.addWidget(self.on_label)
        self.buttons: dict[str, QPushButton] = {}
        b = self.browse
        for key, label, name, tip, do in (
                ("note", "Note", "note", "A note on its notes page (N)", lambda: b.open_capture(task=self.acting, mode="note")),
                ("update", "Update", "update", "Its state, latest update, dates and more (U)", lambda: b.open_capture(task=self.acting, mode="update")),
                ("progress", "Log progress…", "waiting", "A line of what you did, who you're waiting on and when to follow up",
                 lambda: b.ctx.log_progress(self.acting)),
                ("tmail", "New T-mail", "mail", "A new email in Outlook, tagged so its replies come back to the task. You write and send it.",
                 self._new_t_mail),
                ("meeting", "Discussion or meeting", "people", "Notes of a discussion or meeting on it, with its agenda beside them (M)",
                 lambda: b.open_capture(task=self.acting, meeting=True)),
                ("find", "Find files", "search", "Search, preview and open its files (O)", lambda: b.open_task_view(self.acting))):
            btn = QPushButton(label, objectName="subtle")
            if not LOOK.classic:
                btn.setIcon(icon(name))
            btn.setToolTip(tip)
            btn.clicked.connect(do)
            self.bar.addWidget(btn)
            self.buttons[key] = btn
            if key == "tmail":
                more = QToolButton(objectName="subtle")
                more.setIcon(icon("chevron-down"))
                more.setToolTip("More T-mails: Reply all to the latest email filed to the task, or Ask for an update")
                more.setAccessibleName("More T-mails")
                more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                self._tmail_menu = QMenu(more)
                self._tmail_menu.aboutToShow.connect(self._fill_tmail_menu)
                more.setMenu(self._tmail_menu)
                self.bar.addWidget(more)
        line = QFrame(objectName="divider")
        line.setFrameShape(QFrame.Shape.VLine)
        self.bar.addWidget(line)
        done = QPushButton("Done for today", objectName="subtle")
        if not LOOK.classic:
            done.setIcon(icon("tick"))
        done.setToolTip("Off Today as done; you stay here, and Esc goes back to Today, where it's under Done for today")
        done.clicked.connect(self.done_for_today)
        self.bar.addWidget(done)
        self.buttons["done"] = done
        # The agent buttons' place (decision 666): at the bar's end, showing nothing until there's an agent button.
        self.agents = QFrame(objectName="wsAgents")
        QHBoxLayout(self.agents).setContentsMargins(4, 0, 4, 0)
        self.agents.hide()
        self.bar.addWidget(self.agents)
        self.bar.addStretch()
        more = QToolButton(objectName="iconOnly")
        more.setIcon(icon("more"))
        more.setAccessibleName("More")
        more.setToolTip("More: the task page, Edit task, Add to and its folder")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more = QMenu(more)
        self._more.aboutToShow.connect(self._fill_more)
        more.setMenu(self._more)
        self.bar.addWidget(more)
        return bar

    def _build_middle(self) -> QWidget:
        css = page_css()
        self.pane = WorkPane(css, 14 if LOOK.classic else 22)
        b = self.browse
        b.wire_notes(self.pane, b.say, b.open_ref, back=False)
        # This page or All notes, All notes' links and the outline's places are the workspace's own (683).
        self.pane.notes_mode.disconnect()
        self.pane.notes_mode.connect(self.set_mode)
        self.pane.notes_group.disconnect()  # All notes' Group strip (release 5.157), kept as the task page keeps it
        self.pane.notes_group.connect(self.set_group)
        self.pane.all_notes_link.disconnect()
        self.pane.all_notes_link.connect(self.on_link)
        self.pane.all_view.anchorClicked.connect(lambda url: self.on_link(url.toString()))
        self.pane.place_picked.connect(self.go_place)
        self.pane.banner_link.connect(self.on_link)
        self.card = StatusCard(css)
        self.card.link.connect(self.on_link)
        self.card.entered.connect(self.quick_entry)
        self.card.state_clicked.connect(lambda at: b.popup_state_menu(self.acting, at))
        self.card.later_clicked.connect(self._later)
        self.card.add_clicked.connect(lambda: b.add_to_today(self.acting))
        # Release 5.175 (decision 764): More opens the card into Log progress's form, its line the card's box.
        self.card_form = ProgressForm(b.ctx, self.card, line=self.card.box)
        self.card.place_form(self.card_form)
        self.card_form.submit.connect(lambda: self.quick_entry(self.card.box.text(), False))
        self.card_form.changed.connect(lambda: self.card_form.render(self.browse.model()))
        self.card.more_toggled.connect(self._card_more)
        self.pane.card_slot.layout().addWidget(self.card)
        self.dates = DatesView()
        self.dates.day_clicked.connect(self._edit_day)
        self.dates.day_typed.connect(self._day_typed)
        self.dates.day_left.connect(self._day_left)
        self.dates.row_menu.connect(self._date_menu)
        self.dates.earlier.connect(self._toggle_earlier)
        self.dates.add.connect(self.add_key_date)
        self.dates.link.connect(self.on_link)
        self.pane.dates_slot.layout().addWidget(self.dates)
        return self.pane

    def _build_resources(self) -> QWidget:
        box = QWidget(objectName="wsResources")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setFixedWidth(RESOURCES_WIDTH)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 12, 6, 0)
        bl.setSpacing(6)
        cap = QLabel("RESOURCES", objectName="wsCaption")
        cap.setFont(tokens.ui_font(tokens.CAPTION, semibold=True))
        self.search = search_box()
        self.search.textChanged.connect(lambda _: self.draw_resources())
        self.search.installEventFilter(self)
        self.scope = QLabel(objectName="hint")
        self.scope.setWordWrap(True)
        self.scope.setTextFormat(Qt.TextFormat.RichText)
        self.scope.linkActivated.connect(self.on_link)
        self.resources = PageView()
        self.resources.setObjectName("wsResourcesPage")
        self.resources.setOpenLinks(False)
        self.resources.setOpenExternalLinks(False)
        self.resources.document().setDefaultStyleSheet(page_css())
        self.resources.document().setDocumentMargin(2)
        self.resources.setFrameShape(QFrame.Shape.NoFrame)
        self.resources.anchorClicked.connect(lambda url: self.on_link(url.toString()))
        for w in (cap, self.search, self.scope):
            bl.addWidget(w)
        bl.addWidget(self.resources, 1)
        return box

    # ---- what's where ----
    @property
    def acting(self) -> str:
        """The task the bar and the quick entry act on: the task picked when it's this task or one under it (684), else this
        task (a parent picked is read only, 668)."""
        m = self.browse.model()
        if self.picked and self.picked in m.tasks and (self.picked == self.here or self.picked in ws.under(m, self.here)):
            return self.picked
        return self.here

    def reading(self) -> str:
        """The page read in place: a meeting's, or a parent's picked in the chain; "" while a page is edited."""
        if self.meeting:
            return self.meeting
        m = self.browse.model()
        return self.picked if self.picked and self.picked != self.here and self.picked in ws.above(m, self.here) else ""

    def origin_name(self) -> str:
        from docrepo.views import VIEWS

        return next((v.label for v in VIEWS if v.id == self.origin), "the list")

    # ---- drawing ----
    def render(self) -> None:
        """Draw it all again from the model, keeping what's typed, the scroll and what's picked."""
        b = self.browse
        m = b.model()
        if self.here not in m.tasks or m.task(self.here).discarded:
            leave(b)
            b.render_all()
            return
        if self.picked not in m.tasks or m.task(self.picked).discarded:
            self.picked = self.here
        if self.meeting and self.meeting not in m.tasks:
            self.meeting = ""
        b.sel = ("task", self.acting)
        pages = b.pages()
        today = b.today()
        self._draw_head(m)
        self._draw_bar(m, today)
        self._draw_chain(m, pages, today)
        self._draw_middle(m, pages, today)
        self._found = None
        self.draw_resources()

    def _draw_head(self, m) -> None:
        t = m.task(self.here)
        self.title.setText(t.title)
        self.title.setToolTip(t.id)
        self.back_button.setText(self.origin_name())
        self.back_button.setToolTip(f"Back to {self.origin_name()}, with the task picked there (Esc)")
        today = self.browse.today()
        parts = [f'<a href="state:{t.id}" style="text-decoration: none">{esc(t.state)}</a>']
        if t.due:
            parts.append(f"Due {esc(long_date(to_date(t.due), today))}, {esc(days_words(to_date(t.due), today))}")
        people = [m.person_name(p) for p in dict.fromkeys([*t.leads, *t.assignees])]
        if people:
            parts.append(esc(", ".join(people)))
        self.facts.setText(" &nbsp;·&nbsp; ".join(parts))

    def _draw_bar(self, m, today) -> None:
        acting = self.acting
        on = acting != self.here
        self.on_label.setText(f"↳ On {m.task(acting).title}" if on else "")
        self.on_label.setToolTip("The bar and the quick entry act on the subtask whose notes are being edited; Alt+Left comes back to this task's")
        self.on_label.setVisible(on)
        t = m.task(acting)
        closed = t.state == "Closed"
        self.buttons["progress"].setEnabled(not closed)
        self.buttons["meeting"].setVisible(True)
        self.buttons["done"].setVisible(self.from_today and ws.today_item(m, self.here) is not None)

    def _draw_chain(self, m, pages, today) -> None:
        col = self.chain
        col.clear()
        c = ws.chain(m, self.here)
        marks = task_tile.marks(m, today)
        col.add_caption("UP THE CHAIN")
        for n, path in enumerate(c.paths):
            if c.caption(n):
                col.add_caption(c.caption(n))
            for depth, tid in enumerate(path):
                t = m.task(tid)
                since = pages.status_since(t)
                card = ChainCard(task_tile.tile(m, tid, today, marks, hide=("today",)),
                                 status=status_line(t.current_status, short(to_date(since), today) if since else ""),
                                 picked=tid == self.picked and not self.meeting)
                col.add_card(card, depth)
        if c.caption(len(c.paths)):
            col.add_caption(c.caption(len(c.paths)))
        w = waits.current(m, self.here)
        here = ChainCard(task_tile.tile(m, self.here, today, marks, hide=("today", "wait")), this=True,
                         note=waits.words(m, w, today) if w is not None else "", picked=self.picked == self.here and not self.meeting)
        col.add_card(here, max(len(p) for p in c.paths) if c.paths else 0)
        kids = ws.subtasks(m, self.here)
        open_n = sum(1 for k in kids if m.task(k).state != "Closed")
        if kids or m.task(self.here).state != "Closed":
            col.add_caption(f"SUBTASKS   {open_n} of {len(kids)} open" if kids else "SUBTASKS",
                            link(f"new:{self.here}", "New task", "A new task under this one (T)"))
        closed = [k for k in kids if m.task(k).state == "Closed"]
        for k in kids:
            if m.task(k).state == "Closed" and not self.show_closed:
                continue
            col.add_card(ChainCard(task_tile.tile(m, k, today, marks), picked=k == self.picked and not self.meeting, compact=True))
        if closed:
            col.add_link(link("wsclosed:", "Hide closed" if self.show_closed else f"Show {len(closed)} closed"))
        col.finish()

    def _card_facts(self, m, pages, task_id: str, today) -> CardFacts:
        t = m.task(task_id)
        name, when, age, body = pages.status_parts(t)
        wait, wait_tip, late = pages.wait_parts(t)
        log = pages.stories.story(task_id)
        log_html = pages.story_list(log, lambda e: pages.log_item(e), self.state) if log else ""
        whose = "" if task_id == self.here else (
            f'<a href="wspick:{esc(task_id)}" style="text-decoration: none">{esc(t.title)}</a> ·')
        editable = task_id == self.acting and not t.discarded
        on_today = ws.today_item(m, task_id) is not None
        done = ws.done_today(m, task_id, today)
        return CardFacts(whose=whose, name=name, when=when, when_tip=f"The latest update was written {age}" if age else "",
                         wait=wait, wait_tip=wait_tip, late=bool(late),
                         body=body if editable else body.split('<br><span class="sub">')[0],
                         log=log_html, changes=f"{len(log)} change{'s' if len(log) != 1 else ''}" if log else "",
                         entry=editable, title=t.title, state=t.state, later=on_today and not done, add=not on_today and not done)

    def _draw_middle(self, m, pages, today) -> None:
        pane = self.pane
        reading = self.reading()
        acting = self.acting
        if self.meeting:
            mt = m.task(self.meeting)
            said = ws.meeting_words(pages, self.meeting, self.picked) or ws.meeting_words(pages, self.meeting, self.here)
            day = meeting_rows.rows(m, self.picked)
            when = next((r.day for r in day if r.meeting == self.meeting), "")
            self.card.show_facts(CardFacts(whose=f"{esc(mt.title)} ·", name="Meeting", when=short(to_date(when), today) if when else "",
                                           body=f'<p class="stext">{esc(said) or "Its notes, read here."}</p>'))
        else:
            self.card.show_facts(self._card_facts(m, pages, self.picked, today))
            self._card_follows(m)
        # The heading's words, the switch and the banner.
        has_more = self.picked == self.here and not self.meeting and all_notes.has_more(m, self.here)
        mode = self.mode if has_more else "page"
        self.state.notes_group = self.browse.notes_group_of(self.here)
        pane.set_mode_switch(has_more, mode, self.state.notes_group)
        if self.meeting:
            pane.of_label.setText(f"of {m.task(self.meeting).title}, read only")
            pane.set_banner(ws.banner_html(f"<b>{esc(m.task(self.meeting).title)}</b>: its notes, read only.",
                                           extra=link(f"task:{self.meeting}", "Open its notes", "Its own page, where they're edited")))
        elif reading:
            pane.of_label.setText(f"of {m.task(reading).title}, read only")
            pane.set_banner(ws.banner_html(f"↑ <b>{esc(m.task(reading).title)}</b>, above this task: its notes, read only."))
        elif acting != self.here:
            pane.of_label.setText(f"of {m.task(acting).title}")
            pane.set_banner(ws.banner_html(f"↳ <b>{esc(m.task(acting).title)}</b>, under this task: you're editing its notes here."))
        else:
            pane.of_label.setText("")
            pane.set_banner("")
        # The notes: read in place, All notes, or the page being edited, each with the chain's outline.
        pages_in = ws.outline_pages(m, self.here, acting if acting != self.here else None)
        if self.meeting and self.meeting not in pages_in:
            pages_in.append(self.meeting)
        if reading:
            html, places = ws.read_html(pages, reading)
            self._show_html(m, pages_in, reading, html, [("anchor", p.anchor, p.level, p.day, p.text) for p in places])
        elif mode == "all" and self.state.notes_group != "day":  # By meeting or By topic (release 5.157)
            html, g = pages.grouped_notes(self.here, self.state)
            entries, targets, counts = grouped_outline(m, g, today, self.state.notes_folded)
            places = [(*target, level + 1, quiet, words) for target, (_n, level, quiet, words) in zip(targets, entries, strict=True)]
            self._show_html(m, pages_in, self.here, html, places, counts)
        elif mode == "all":
            html, an = pages.all_notes(self.here, self.state)
            places = [("anchor", f"day:{day.isoformat()}", 2, True, notes_page.day_title(day)) for day, _blocks in an.days]
            self._show_html(m, pages_in, self.here, html, places)
        else:
            if pane.all_mode:
                pane.show_all_notes(None)
            self._frame_outline(m, pages_in, acting)
            self.browse.load_notes(acting, pane)
        # Dates.
        rows = ws.dates(m, self.picked, today)
        self._rows = {r.key: r for r in rows}
        if self.editing not in self._rows:
            self.editing = ""
        whose = "of this task, its parents and its subtasks" if self.picked == self.here else f"of {m.task(self.picked).title}, above it and under it"
        self.dates.show_rows(rows, today, show_earlier=self.show_earlier, editing=self.editing, words=whose,
                             cell=lambda r: self._date_cell(m, r), shown_when=lambda r: long_date(r.day, today))
        self.dates.add_button.setVisible(not reading and m.task(acting).state != "Closed")
        if self.dates.box is not None:
            QTimer.singleShot(0, lambda: self.dates.box.setFocus() if self.dates.box is not None else None)

    def _date_cell(self, m, row: ws.DateRow) -> str:
        """A date's words: a task's own date (its Due, its Reminder, a meeting) is its title, marked ↑ when it's above the
        task picked and ↳ when it's under; anything else (a key date, a follow-up) is its words with whose it is."""
        title = m.task(row.task).title
        if row.words != title:
            return esc(row.words) + ws.whose_chip(m, row.task, self.picked, [])
        if row.task == self.picked:
            return esc(title)
        arrow = "↑" if row.task in ws.above(m, self.picked) else "↳"
        return f'<a href="wspick:{esc(row.task)}" style="text-decoration: none"><span style="color: {tokens.colour("text2")}">{arrow}</span> {esc(title)}</a>'

    def _outline_parts(self, m, pages_in: list[str], shown: str) -> tuple[list, list]:
        """The outline's entries before and after the page shown (``shown``), as (place, level, day, words)."""
        before, after, seen = [], [], False
        for p in pages_in:
            if p == shown:
                seen = True
                continue
            for e in ws.page_entries(m, p):
                (after if seen else before).append((("page", e.page, e.heading), e.level, e.day, e.text))
        after.append((("dates",), 1, False, "Dates"))
        return before, after

    def _frame_outline(self, m, pages_in: list[str], acting: str) -> None:
        before, after = self._outline_parts(m, pages_in, acting)
        places: dict[int, tuple] = {}
        n = -2

        def number(items):
            nonlocal n
            out = []
            for place, level, day, text in items:
                places[n] = place
                out.append((n, level, day, text))
                n -= 1
            return out

        b = number(before)
        title = number([(("top",), 1, False, m.task(acting).title)])[0]
        a = number(after)
        self.pane.places = places
        self.pane.outline.set_frame(b, title, a)

    def _show_html(self, m, pages_in: list[str], shown: str, html: str, places: list[tuple], counts: dict[int, int] | None = None) -> None:
        """Notes read in place or All notes in the middle, with the chain's outline round its ``places`` ((kind, key,
        level, day, words): an anchor, or since release 5.157 a band, whose click folds it); ``counts`` by place."""
        before, after = self._outline_parts(m, pages_in, shown)
        entries, targets, shown_counts = [], [], {}
        for place, level, day, text in before:
            entries.append((len(targets), level, day, text))
            targets.append(place)
        current = len(targets)
        entries.append((len(targets), 1, False, m.task(shown).title))
        targets.append(("top",))
        for n, (kind, anchor, level, day, text) in enumerate(places):
            if counts and n in counts:
                shown_counts[len(targets)] = counts[n]
            entries.append((len(targets), level, day, text))
            targets.append((kind, anchor))
        for place, level, day, text in after:
            entries.append((len(targets), level, day, text))
            targets.append(place)
        self.pane.show_all_notes(html, entries, targets, current, shown_counts)

    def draw_resources(self) -> None:
        b = self.browse
        m = b.model()
        if self.here not in m.tasks:
            return
        key = (id(m), self.picked)
        if self._found is None or self._found[0] != key:
            self._found = (key, ws.resources(b.pages(), self.picked))
        found = self._found[1]
        back = f' {link("wsback:", "Back to this task", "Alt+Left")}' if self.picked != self.here else ""
        self.scope.setText(esc(ws.scope_words(m, self.here, self.picked)) + back)
        bar = self.resources.verticalScrollBar()
        y = bar.value()
        self.resources.setHtml(ws.resources_html(m, found, self.picked, self.search.text(), self.folded))
        QTimer.singleShot(0, lambda: bar.setValue(y))

    # ---- picking ----
    def pick(self, task_id: str) -> None:
        """A click in the chain (664): a parent's notes read in the middle, a subtask's edited there (684), this task back.
        The resources and Dates gather what's picked (700)."""
        m = self.browse.model()
        if task_id not in m.tasks:
            return
        self.pane.notes.save_now()
        self.picked, self.meeting, self.editing = task_id, "", ""
        self.render()
        if task_id != self.here:
            self.browse.say(f"{'Reading' if task_id in ws.above(m, self.here) else 'Editing'} {m.task(task_id).title}'s notes here. "
                            "Alt+Left comes back to this task's.")

    def back(self) -> None:
        """Alt+Left, or Back to this task's notes: this task picked again."""
        if self.picked != self.here or self.meeting:
            self.pick(self.here)

    def go_place(self, place: tuple) -> None:
        """An outline entry that isn't a heading of the page shown: another page's (its notes picked, then its heading), Dates,
        or the shown page's top."""
        kind = place[0]
        if kind == "dates":
            self.pane.scroll_to(self.dates)
        elif kind == "band":  # All notes By meeting or By topic: a band folds or unfolds, and stays in view (713)
            self.state.notes_folded ^= {place[1]}
            self.render()
            QTimer.singleShot(0, lambda: self.pane.scroll_to_anchor(topics.band_anchor(place[1])))
        elif kind == "top":
            self.pane.scroll_to(self.pane.notes_head)
        elif kind == "page":
            task_id, heading = place[1], place[2]
            if task_id != self.picked or self.meeting:
                if task_id == self.here and self.mode == "all":
                    self.set_mode("page")
                self.pick(task_id)
            QTimer.singleShot(0, lambda: self._to_heading(task_id, heading))

    def _to_heading(self, task_id: str, heading: int) -> None:
        if heading < 0:
            self.pane.scroll_to(self.pane.notes_head)
            return
        if self.pane.all_mode:
            body = self.browse.model().pages.get(task_id, "")
            hs = ws.headings(body)
            if heading < len(hs):
                text = hs[heading][2]
                n = next((i for i, (_n, _l, _d, words) in enumerate(self.pane.all_outline.entries()) if words == text), None)
                if n is not None:
                    self.pane._all_picked(n)
            return
        outline = self.pane.notes.outline()
        if heading < len(outline):
            self.pane.jump_to(outline[heading][0])

    def set_mode(self, mode: str) -> None:
        """This page or All notes (release 5.140), for this task; kept as its task page keeps it."""
        self.pane.notes.save_now()
        self.mode = mode
        self.browse._save_page_fold("all_notes", mode == "all", self.pane)
        self.render()

    def set_group(self, group: str) -> None:
        """All notes By day, By meeting or By topic (release 5.157, decision 709), for this task; kept as its task page
        keeps it."""
        if group not in topics.GROUPS:
            return
        folds = self.browse._page_folds(self.here)
        folds["notes_group"] = group
        self.browse.ctx.keep_state(f"page_folds:{self.here}", json.dumps(folds))
        self.render()

    # ---- the quick entry bar (678, 701 and 702) ----
    def quick_entry(self, text: str, note: bool) -> None:
        if self.card.more_open and not note:  # opened into Log progress's form: Enter logs it all (decision 764)
            self._log_card()
            return
        line = " ".join(text.split())
        if not line:
            return
        (self._keep_note if note else self._keep_update)(self.acting, line)
        self.card.box.clear()

    # ---- the card opened into Log progress's form (release 5.175, decisions 763 and 764) ----
    def _card_more(self, on: bool) -> None:
        """More, or Less: opened, the form starts as Log progress opens on the task, keeping the words typed."""
        if on:
            self.card_form.reset(self.acting, [], keep_line=True)
            self.card_form.render(self.browse.model())

    def _card_follows(self, m) -> None:
        """Another task acted on while the card is open: the form follows it, as it would open on that task."""
        if self.card.more_open and self.card_form.task != self.acting:
            self.card_form.reset(self.acting, [], keep_line=True)
        if self.card.more_open:
            self.card_form.render(m)

    def _log_card(self) -> None:
        """Enter in the opened card: the same log Log progress keeps (``progress.log_progress``, with the form's values), for
        the workspace's task, with no email. Said in the status line; the card closes, as the window does."""
        b, form, task = self.browse, self.card_form, self.acting
        stopped = form.check()
        if stopped is not None:
            form.say(*stopped)
            form.focus(stopped[0])
            return

        def stop(key: str, words: str) -> None:
            key = key if key in form.problems else "content"
            form.say(key, words)
            form.focus(key)

        values = form.values()
        done = guarded(lambda: progress.log_progress(b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings, task_id=task, at=b._now(),
                                                     **values), task, stop)
        if done is None:
            return
        self.card.box.clear()
        self.card.set_more(False)
        b.ctx.today_changed()
        b.refresh()
        said = said_after(b.model(), done, values["state"], b.today())
        b.say(f"{said} Done for today." if done.done_today and not done.back else said)

    def _keep_update(self, task_id: str, line: str) -> None:
        """Enter: an Update capture on the task, its words the current status, with Undo (678)."""
        b = self.browse
        old = b.model().task(task_id).current_status
        draft = CaptureDraft(content=line, task=task_id, types={"update"}, update={"current_status": line})
        try:
            result = save_capture(b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings, draft, b._now())
        except (SaveError, TaskError, WriteRefused, OSError, sqlite3.Error, ValueError) as e:
            b.say(f"The update wasn't kept: {e}", error=True)
            return
        b.ctx.today_changed()
        b.refresh()
        capture = result.capture_id

        def undo() -> None:
            def both():
                if capture:
                    edits.discard_capture(b.conn, b.ctx.data_root, b.ctx.fs, capture, "undone", b._now())
                return edits.change_task(b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings, task_id, b._now(), current_status=old)
            if b._do(both):
                b.say("The update is undone: the latest update is as it was, and its capture is in the Discarded view.")

        b.say_undo(f"Kept as an update on {b.model().task(task_id).title}: its latest update now.", undo)

    def _keep_note(self, task_id: str, line: str) -> None:
        """Shift+Enter: the line on the task's notes under today's day, the status as it was, with Undo (701)."""
        b = self.browse
        b.save_open_notes()
        today = b.today()
        before = b.model().pages.get(task_id, "")
        after = ws.note_page(before, line, today)
        out = b._do(lambda: edits.save_page(b.conn, b.ctx.data_root, b.ctx.fs, task_id, after, b._now()))
        if out is None:
            return

        def undo() -> None:
            now = b.model().pages.get(task_id, "")
            back = before if now == after else ws.without_note(now, line, today)
            if b._do(lambda: edits.save_page(b.conn, b.ctx.data_root, b.ctx.fs, task_id, back, b._now())):
                b.say("The note is off the page again.")

        b.say_undo(f"Noted on {b.model().task(task_id).title}'s notes, under {long_date(today, today)}.", undo)

    def _later(self, at: QPoint) -> None:
        m = self.browse.model()
        item = ws.today_item(m, self.acting)
        self.browse.later_menu(self.acting, item.id if item is not None else None, at)

    def done_for_today(self) -> None:
        """Done for today (666, 687): off Today as done, and the workspace stays; Esc goes back to Today."""
        item = ws.today_item(self.browse.model(), self.here)
        if item is not None:
            self.browse.close_today_item(item.id, "Done")

    # ---- Dates (681, 698 and 699) ----
    def _edit_day(self, key: str) -> None:
        self.editing = key
        self._draw_dates_only()

    def _day_left(self) -> None:
        self.editing = ""
        self._draw_dates_only()

    def _draw_dates_only(self) -> None:
        b = self.browse
        self._draw_middle_dates(b.model(), b.today())

    def _draw_middle_dates(self, m, today) -> None:
        rows = list(self._rows.values())
        whose = "of this task, its parents and its subtasks" if self.picked == self.here else f"of {m.task(self.picked).title}, above it and under it"
        self.dates.show_rows(rows, today, show_earlier=self.show_earlier, editing=self.editing, words=whose,
                             cell=lambda r: self._date_cell(m, r), shown_when=lambda r: long_date(r.day, today))
        if self.dates.box is not None:
            self.dates.box.setFocus()

    def _toggle_earlier(self) -> None:
        self.show_earlier = not self.show_earlier
        self._draw_dates_only()

    def _day_typed(self, key: str, text: str) -> None:
        b = self.browse
        row = self._rows.get(key)
        if row is None:
            return
        day = ws.read_day(text, b.today(), b._workdays())
        if day is None:
            b.say(f'"{text.strip()}" isn\'t a day: try tomorrow, fri, 24 nov, or +3 for three workdays.', error=True)
            return
        self.editing = ""
        if day == row.day:
            self._draw_dates_only()
            return
        self.change_day(row, day)

    def change_day(self, row: ws.DateRow, day) -> None:
        """A day changed in Dates, with Undo: the same call back to the old day."""
        b = self.browse
        args = (b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings)
        out = b._do(lambda: ws.change_day(*args, row, day, b._now(), b.model()))
        if out is None:
            return
        moved = replace(row, day=day)
        words = f"{row.kind} of {b.model().task(row.task).title}: {long_date(day, b.today())}."

        def undo() -> None:
            if b._do(lambda: ws.change_day(*args, moved, row.day, b._now(), b.model())):
                b.say(f"{row.kind} of {b.model().task(row.task).title} is back on {long_date(row.day, b.today())}.")

        b.say_undo(words + (f" {out.moved}" if getattr(out, "moved", "") else ""), undo)

    def _date_menu(self, key: str, at: QPoint) -> None:
        b = self.browse
        row = self._rows.get(key)
        if row is None:
            return
        menu = QMenu(self)
        if row.field:
            menu.addAction("Change the day…", lambda: self._edit_day(key))
        if row.key_date is not None:
            menu.addAction(icon("tick"), "Done", lambda: self._key_date_done(row))
            menu.addAction("Take it off", lambda: self._take_off(row))
        menu.addSeparator()
        menu.addAction("Quick edit…", lambda: b.quick_edit(row.task, QRect(QCursor.pos(), QSize(1, 1))))
        menu.addAction(f"Open {task_tile.page_title(b.model().task(row.task).title, 40)}", lambda: b.go_task(row.task))
        b.run_menu(menu, at)
        menu.deleteLater()

    def _key_date_done(self, row: ws.DateRow) -> None:
        b = self.browse
        out = b._do(lambda: ws.key_date_done(b.conn, b.ctx.data_root, b.ctx.fs, row, True, b._now()))
        if out is not None:
            b.say_undo(out.message, lambda: b._do(lambda: ws.key_date_done(b.conn, b.ctx.data_root, b.ctx.fs, row, False, b._now())))

    def _take_off(self, row: ws.DateRow) -> None:
        b = self.browse
        args = (b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings)
        held: list = []

        def go():
            out, rows = ws.take_off(*args, row, b._now())
            held[:] = rows
            return out

        if b._do(go) is not None:
            b.say_undo(f"Took the key date {row.words} off {b.model().task(row.task).title}.",
                       lambda: b._do(lambda: ws.put_back(*args, row.task, held, b._now())))

    def add_key_date(self) -> None:
        """Add a key date (681): a day in words and what it is, on the task being edited."""
        b = self.browse
        task_id = self.acting
        text = b.ask_text("Add a key date", f"A key date on {b.model().task(task_id).title}: a day in words and what it is, "
                          "such as 24 nov Base plate drawing, or +3 Datasheet", "")
        if not text or not text.strip():
            return
        read = ws.read_key_date(text, b.today(), b._workdays())
        if read is None:
            b.say(f'"{text.strip()}" has no day in it: try 24 nov Base plate drawing, or +3 Datasheet.', error=True)
            return
        day, what = read
        b._do(lambda: ws.add_key_date(b.conn, b.ctx.data_root, b.ctx.fs, b.ctx.settings, task_id, day, what or "A key date", b._now()))

    # ---- menus ----
    def _new_t_mail(self) -> None:
        from docrepo.ui import t_mails

        t_mails.new_t_mail(self.browse, self.acting)

    def _fill_tmail_menu(self) -> None:
        from docrepo.ui import t_mails

        self._tmail_menu.clear()
        menu = t_mails.latest_menu(self.browse, self.acting, self)
        for a in menu.actions():
            self._tmail_menu.addAction(a)
        self._held_menu = menu

    def _fill_more(self) -> None:
        from docrepo.ui import task_menus

        b = self.browse
        menu = self._more
        menu.clear()
        menu.addAction(icon("open"), "Task page", self.close_to_origin)
        menu.addAction(icon("edit"), "Edit task…\tE", lambda: b.edit_task(self.acting))
        menu.addMenu(task_menus.add_to_menu(b, self.acting, menu))
        menu.addAction(icon("folder"), "Open folder", lambda: b.reveal(b.ctx.data_root / "Tasks" / self.acting))

    def _tile_menu(self, task_id: str, at: QPoint) -> None:
        from docrepo.ui import task_tile as tile_ui

        menu = tile_ui.tile_menu(self.browse, task_id, self)
        if menu is not None:
            self.browse.run_menu(menu, at)
            menu.deleteLater()

    def _work_on(self, task_id: str) -> None:
        """A double-click on a tile in the chain works on that task: its own workspace (684)."""
        if task_id != self.here:
            open_workspace(self.browse, task_id, self.from_today, origin=self.origin)

    # ---- links ----
    def on_link(self, href: str) -> None:
        """The workspace's own links first; the rest are the browse window's, as on the task page."""
        kind, _, rest = href.partition(":")
        b = self.browse
        if kind == "wsback":
            self.back()
        elif kind == "wspick":
            m = b.model()
            if rest in m.tasks and (rest in ws.gathered(m, self.here) or rest in ws.under(m, self.picked)):
                self.pick(rest)
            else:
                b.go_task(rest)
        elif kind == "wsmeet":  # a meeting's notes read in place (685)
            if rest not in b.model().tasks:
                return
            self.pane.notes.save_now()
            self.meeting = rest
            self.render()
            b.say(f"Reading the notes of {b.model().task(rest).title} in place. Alt+Left comes back to this task's notes.")
        elif kind == "wsfold":
            self.folded.symmetric_difference_update({rest})
            self.draw_resources()
        elif kind == "wsclosed":
            self.show_closed = not self.show_closed
            self._draw_chain(b.model(), b.pages(), b.today())
        elif kind == "notesgo":  # Edit there (668): that page at those lines; Alt+Left comes back
            task_id, _, capture = rest.partition(":")
            if task_id not in b.model().tasks:
                return
            self.came_from = (self.here, self.picked, self.origin, self.from_today)
            title = b.model().task(self.here).title
            leave(b)
            if capture:
                b.go_to_block(task_id, capture)
            else:
                b.go_task(task_id)
            self.came_from = (self.here, self.picked, self.origin, self.from_today)
            b.say(f"Editing {b.model().task(task_id).title}'s notes on its own page. Alt+Left goes back to the workspace of {title}.")
        elif kind == "allnotes":
            if rest.startswith("fold:"):  # a band's fold (release 5.157, decision 713)
                self.state.notes_folded ^= {rest.removeprefix("fold:")}
            elif rest == "earlier":
                self.state.notes_weeks = self.state.notes_weeks + all_notes.WEEKS if self.state.notes_weeks else 0
            elif rest == "everything":
                self.state.notes_weeks = 0
            elif rest.startswith("only:"):
                self.state.notes_only = rest.removeprefix("only:")
            self.render()
        elif kind == "new":
            b.open_capture(task=rest, mode="new_task")
        else:
            b.on_link(QUrl(href))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        """Esc in the search box clears it (679), and only then goes back."""
        if watched is self.search and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.search.text():
            self.search.clear()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, e) -> None:  # noqa: N802 - Qt's name
        if e.key() == Qt.Key.Key_Escape:
            e.accept()
            if self.editing:
                self._day_left()
            else:
                self.close_to_origin()
            return
        super().keyPressEvent(e)

    def close_to_origin(self) -> None:
        """Esc, the back button or Task page: back to the view it came from, with the task picked there (687)."""
        b = self.browse
        here = self.here
        leave(b)
        b.view = self.origin
        b.select("task", here, update_list=True)
        b.tree.setFocus()

    def text(self) -> str:
        """What it shows, as words, for the tests."""
        parts = [self.title.text(), self.facts.text(), self.chain.text(), self.card.name.text(), self.card.body.toPlainText(),
                 self.pane.of_label.text(), self.pane.banner.text(), self.pane.text(), self.resources.toPlainText()]
        parts += [f"{r.day} {r.kind} {r.words}" for r, _ in self.dates.shown.values()]
        return "\n".join(x for x in parts if x)


# ---- the browse window's side ----
def is_open(browse: BrowseWindow) -> bool:
    w = getattr(browse, "workspace", None)
    return w is not None and not w.isHidden()


def ensure(browse: BrowseWindow) -> Workspace:
    w = getattr(browse, "workspace", None)
    if w is None:
        w = Workspace(browse)
        w.hide()
        browse.split.addWidget(w)
        browse.split.setStretchFactor(browse.split.indexOf(w), 1)
        browse.workspace = w
    return w


def open_workspace(browse: BrowseWindow, task_id: str, from_today: bool | None = None, origin: str | None = None) -> None:
    """Work on it (663): the task's workspace in the list's and the page's room, beside the places (682)."""
    m = browse.model()
    t = m.tasks.get(task_id)
    if t is None or t.discarded:
        return
    if not browse.isVisible():
        browse.show_browse()
    browse.save_open_notes()
    w = ensure(browse)
    was_open = is_open(browse)
    if not was_open:
        w.origin = origin or browse.view
        w._sizes = browse.split.sizes()
    elif origin:
        w.origin = origin
    w.from_today = (w.origin == TODAY) if from_today is None else from_today
    w.here = w.picked = task_id
    w.meeting = w.editing = ""
    w.came_from = None
    w.show_earlier = w.show_closed = False
    w.state = PageState(order="new")
    w.mode = "all" if browse._page_folds(task_id).get("all_notes") else "page"
    w.search.blockSignals(True)
    w.search.clear()
    w.search.blockSignals(False)
    _show(browse, w)
    w.render()
    w.pane.verticalScrollBar().setValue(0)
    _to_front(browse, w)
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    browse.say(f"{ws.gathered_words(m, task_id)} Esc goes back to {w.origin_name()}.")


def _to_front(browse: BrowseWindow, w: Workspace) -> None:
    """The workspace's window maximised, restored if it was minimised, and in front with the keyboard (release 5.165,
    decision 771): Qt calls a minimised window, or one behind another program, visible, so showing it isn't enough.
    What it was before is kept, for ``leave`` to restore."""
    if w._window is None:
        w._window = (bool(browse.windowState() & Qt.WindowState.WindowMaximized), QRect(browse.normalGeometry()))
    browse.setWindowState((browse.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowMaximized)
    bring_to_front(browse)


def _show(browse: BrowseWindow, w: Workspace) -> None:
    browse.middle.hide()
    browse.detail.hide()
    w.show()
    sizes = browse.split.sizes()
    i = browse.split.indexOf(w)
    total = sum(sizes)
    nav = sizes[0] if browse.nav.isVisible() else 0
    sizes = [nav] + [0] * (len(sizes) - 1)
    sizes[i] = max(400, total - nav)
    browse.split.setSizes(sizes)


def leave(browse: BrowseWindow) -> None:
    """The workspace goes, its notes kept; the list and the page come back as they were. Nothing's drawn: the caller does."""
    if not is_open(browse):
        return
    w = browse.workspace
    w.pane.notes.save_now()
    w.hide()
    browse.middle.show()
    browse.detail.show()
    if w._sizes:
        browse.split.setSizes(w._sizes)
    if w._window is not None:  # the size and place the browse window had before (decision 771)
        was_maximised, geometry = w._window
        w._window = None
        if not was_maximised:
            browse.setWindowState(browse.windowState() & ~Qt.WindowState.WindowMaximized)
            if geometry.isValid():
                browse.setGeometry(geometry)


def render(browse: BrowseWindow) -> None:
    browse.workspace.render()


def work_key(browse: BrowseWindow) -> None:
    """W: the selected task's workspace."""
    if browse._typing():
        return
    if browse.sel and browse.sel[0] == "task":
        open_workspace(browse, browse.sel[1])


def open_row(browse: BrowseWindow, task_id: str) -> None:
    """A task row's double-click or Enter: as Settings' Open a task in says, its workspace or its page, and the other with
    Shift (release 5.174, decision 815, in place of 667's Today only and 572's page)."""
    from docrepo.ui import task_open

    task_open.open_task(browse, task_id, other=task_open.shift_held())


def come_back(browse: BrowseWindow) -> bool:
    """Alt+Left on the page Edit there opened: back to the workspace it left, as it was (668)."""
    w = getattr(browse, "workspace", None)
    if w is None or w.came_from is None or is_open(browse):
        return False
    here, picked, origin, from_today = w.came_from
    if here not in browse.model().tasks:
        w.came_from = None
        return False
    browse.save_open_notes()
    w.came_from = None
    w._sizes = browse.split.sizes()
    w.here, w.picked, w.origin, w.from_today = here, picked, origin, from_today
    w.meeting = w.editing = ""
    _show(browse, w)
    w.render()
    _to_front(browse, w)
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    browse.say(f"Back in the workspace of {browse.model().task(here).title}.")
    return True
