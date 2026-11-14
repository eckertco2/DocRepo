"""The email link filter in the capture window (release 5.146, the design workspace's ``docs/mods/email-link-filter-plan.md``,
decisions 638 and 640).

An email's link row has a right-click menu, **Always keep links from zoom.us** and **Never keep links from zoom.us**, naming
the link's domain without ``www.``. The domain goes on that list in Settings at once (and off the other), and the window's
rows follow (``follow``): a link now on Never keep goes, and its email's layer 0 line counts it; a link whose list changed
starts as its new list starts it; a link no longer left out gets its row back, under its email's. ``follow`` also runs when
Settings' lists are saved while the window holds an email. Only an email's links: a link the owner adds is never sorted.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from docrepo import layer0
from docrepo.save import FileRow

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow, FileEntry
    from docrepo.ui.context import AppContext

log = logging.getLogger(__name__)

#: The two lists, by the rule each gives a link: its name in the menu.
LISTS = {"keep": "Always keep", "drop": "Never keep"}


def rules(c: CaptureWindow) -> layer0.LinkRules:
    """Settings' link lists, as layer 0 uses them in this window."""
    return layer0.LinkRules.of(c.ctx.settings)


def is_email_link(entry: FileEntry) -> bool:
    """An email's link row, the rows the lists sort."""
    return entry.row.of is not None and entry.row.part is not None and entry.row.part.kind == "link"


def menu_for(c: CaptureWindow, entry: FileEntry) -> QMenu:
    """The link row's right-click menu: Always keep links from its domain, Never keep links from it. The list that already
    names the domain has its entry greyed."""
    menu = QMenu(c)
    domain = layer0.domain_of(entry.row.path or "")
    s = c.ctx.settings
    for which, name in LISTS.items():
        on = {x.lower() for x in (s.links_keep if which == "keep" else s.links_drop)}
        action = menu.addAction(f"{name} links from {domain}")
        action.setEnabled(bool(domain) and domain.lower() not in on)
        action.setToolTip(f"Puts {domain} on {name} in Settings, and this window's rows follow")
        action.triggered.connect(lambda _=False, w=which: put_on(c, domain, w))
    return menu


def show_menu(c: CaptureWindow, entry: FileEntry, at: QPoint) -> None:
    menu_for(c, entry).exec(at)


def save_lists(ctx: AppContext, keep: list[str], drop: list[str]) -> None:
    """Always keep and Never keep as given, saved to settings.json at once, and said to the app (Settings' boxes follow)."""
    ctx.settings.links_keep, ctx.settings.links_drop = keep, drop
    ctx.settings.save(ctx.fs, ctx.data_root)
    log.info("settings changed: links_keep, links_drop")
    ctx.settings_changed(["links_keep", "links_drop"])


def put_on(c: CaptureWindow, domain: str, which: str) -> None:
    """The menu's choice: ``domain`` on Always keep ("keep") or Never keep ("drop"), and the rows follow."""
    s = c.ctx.settings
    keep, drop = layer0.put_on(s.links_keep, s.links_drop, domain, which)
    save_lists(c.ctx, keep, drop)
    follow(c)


def follow(c: CaptureWindow) -> None:
    """Each email's link rows as Settings' lists sort its links now: a row whose link is now left out goes, a row whose list
    (or Other links) changed how it starts starts that way (a tick the owner gave it stays otherwise), and a link no longer
    left out gets a row under its email's last."""
    r = rules(c)
    changed = False
    for own in [e for e in c.files if e.row.email is not None]:
        email = own.row.email
        fresh = {p.url: p for p in layer0.find(email, r).parts if p.kind == "link"}
        for e in [e for e in c.files if e.row.of is email and is_email_link(e)]:
            p = fresh.pop(e.row.path or "", None)
            if p is None:
                c._remove_file(e, from_content=False)
                changed = True
            elif (p.rule, p.keep) != (e.row.part.rule, e.row.part.keep):  # its list, or Other links, changed how it starts
                e.row.part = p
                if e.keep is not None:
                    e.keep.setChecked(p.keep)  # its toggled signal sets the row's keep
                e.row.keep = p.keep
                if e.note is not None:
                    e.note.setText(c._file_note(e.row, e.doc, True))
                changed = True
        for p in fresh.values():  # links no longer left out: under the email's last row
            last = [e for e in c.files if e is own or e.row.of is email][-1]
            c._add_file(FileRow(p.name, p.url, part=p, of=email, keep=p.keep), "email", focus=False)
            added = c.files.pop()
            c.files.insert(c.files.index(last) + 1, added)
            c.files_box.removeWidget(added.widget)
            c.files_box.insertWidget(c.files_box.indexOf(last.widget) + 1, added.widget)
            changed = True
    if changed:
        c._apply_same_all()
    c._show_layer0()
    c.refresh()
