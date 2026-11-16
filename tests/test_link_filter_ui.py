"""The email link filter's Settings card and a link row's right-click menu (release 5.146, the design workspace's
docs/mods/email-link-filter-plan.md, decisions 635 to 640), driven offscreen over the sample data with made-up emails."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

from docrepo import layer0  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.layer0 import DEFAULT_DROP  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import EmailItem, FileRow  # noqa: E402
from docrepo.ui import drafts as draft_ui  # noqa: E402
from docrepo.ui import link_filter  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.settings_view import SettingsProblem, SettingsView, check_link_lists, update_settings  # noqa: E402

AT = datetime(2026, 11, 13, 9, 0)
JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZjQ1NzA2%40thread.v2/0"
OPTIONS = "https://teams.microsoft.com/meetingOptions/?organizerId=c0ffee"
SITE = "https://example.sharepoint.com/sites/Line1/Shared%20Documents/Pump%20trial%20plan.docx"
VENDOR = "https://www.norvane.example.com/guards/cg-380/install-guide.pdf"
VENDOR_2 = "https://parts.norvane.example.com/cg-380"


def invitation() -> EmailItem:
    html = "<p>Pump trial review.</p>" + "".join(f'<p><a href="{u}">link</a></p>' for u in (SITE, VENDOR, VENDOR_2, JOIN, OPTIONS))
    return EmailItem(subject="Pump trial review", sender="Dana Example", sent="2026-11-13 08:30", to="Me", body="Pump trial review.", html=html)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp, sample_root):
    conn, root, fs = sample_root
    told: list[list[str]] = []
    c = AppContext(conn, root, fs, Settings(me="P001"), now=lambda: AT, settings_changed=told.append, notify=lambda t, m: None)
    c.told = told
    return c


@pytest.fixture
def window(ctx):
    w = CaptureWindow(ctx)
    w.show_capture(task="T000012")
    yield w
    w.hide()
    w.deleteLater()


def links(w) -> list[tuple[str, bool]]:
    return [(e.row.path, e.keep.isChecked()) for e in w.files if link_filter.is_email_link(e)]


def layer0_text(w) -> str:
    return next(e for e in w.files if e.row.email is not None).layer0.text()


# ---- the Settings card (decisions 635, 637 and 639) ----
def test_the_card_shows_the_lists_and_other_links(ctx):
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    assert view.links_keep.lines() == [] and view.links_drop.lines() == list(DEFAULT_DROP)
    assert view.other_links.currentData() == "keep" and view.other_links.count() == 3
    assert [view.other_links.itemText(i) for i in range(3)] == ["Keep them", "Show them unticked", "Leave them out"]
    assert view.save() == []  # nothing changed, so nothing is written


def test_the_card_saves_tidied_lists_and_restores_defaults(ctx):
    said: list[str] = []
    view = SettingsView(ctx, said.append, lambda title, text: True)
    view.load()
    view.links_keep.box.setPlainText("https://www.Example.SharePoint.com/\n\nintranet.example.com\nintranet.example.com")
    view.links_drop.box.setPlainText("zoom.us")
    view.other_links.setCurrentIndex(view.other_links.findData("untick"))
    assert set(view.save()) == {"links_keep", "links_drop", "other_links"}
    s = ctx.settings
    assert (s.links_keep, s.links_drop, s.other_links) == (["example.sharepoint.com", "intranet.example.com"], ["zoom.us"], "untick")
    assert view.links_keep.lines() == ["example.sharepoint.com", "intranet.example.com"]  # shown as kept
    data = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert data["links_drop"] == ["zoom.us"] and data["other_links"] == "untick"
    assert set(ctx.told[-1]) == {"links_keep", "links_drop", "other_links"}
    view.links_drop.restore.click()
    assert view.links_drop.lines() == list(DEFAULT_DROP)
    view.links_keep.restore.click()
    assert view.links_keep.lines() == []
    view.save()
    data = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert "links_drop" not in data and "links_keep" not in data and ctx.settings.links_drop == list(DEFAULT_DROP)


def test_a_line_that_isnt_a_site_is_refused_with_its_number(ctx):
    view = SettingsView(ctx, lambda text: None, lambda title, text: True)
    view.load()
    view.links_drop.box.setPlainText("zoom.us\n\nmeet.google.com\nthe vendor's site")
    assert view.save() == []
    assert view.error.isVisibleTo(view) and "Never keep, line 4" in view.error.text() and "the vendor's site" in view.error.text()
    assert ctx.settings.links_drop == list(DEFAULT_DROP)
    with pytest.raises(SettingsProblem, match="Always keep, line 1"):
        check_link_lists({"links_keep": ["example.com:8080"]})
    with pytest.raises(SettingsProblem, match="Other links"):
        update_settings(ctx, {"hotkey": ctx.settings.hotkey, "workdays": ctx.settings.workdays, "other_links": "sometimes"})


# ---- the capture window: rows, the line and the menu (decisions 636 to 638 and 640) ----
def test_an_emails_rows_follow_the_lists(window):
    window._add_email(invitation())
    assert links(window) == [(SITE, True), (VENDOR, True), (VENDOR_2, True)]
    assert "Left out: 2 blocked links." in layer0_text(window) and "Right-click a link" in layer0_text(window)


def test_show_them_unticked_and_its_note(ctx, window):
    ctx.settings.other_links = "untick"
    ctx.settings.links_keep = ["example.sharepoint.com"]
    window._add_email(invitation())
    assert links(window) == [(SITE, True), (VENDOR, False), (VENDOR_2, False)]
    notes = [e.note.text() for e in window.files if link_filter.is_email_link(e)]
    assert "Always keep" in notes[0] and "neither list" in notes[1]
    assert "2 unticked rows" in layer0_text(window)


def test_the_menu_names_the_domain_and_never_keep_takes_the_rows_away(ctx, window):
    window._add_email(invitation())
    row = next(e for e in window.files if e.row.path == VENDOR)
    assert row.widget.findChild(QFrame, "fileRow").contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    menu = link_filter.menu_for(window, row)
    texts = [a.text() for a in menu.actions()]
    assert texts == ["Always keep links from norvane.example.com", "Never keep links from norvane.example.com"]
    next(a for a in menu.actions() if a.text().startswith("Never")).trigger()
    # Its site's links go (a subdomain's too), the line counts them, and Settings has it at once.
    assert links(window) == [(SITE, True)]
    assert "Left out: 4 blocked links." in layer0_text(window)
    assert ctx.settings.links_drop[-1] == "norvane.example.com" and ctx.told[-1] == ["links_keep", "links_drop"]
    saved = json.loads((ctx.data_root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert saved["links_drop"][-1] == "norvane.example.com"
    window.save()
    c = Model(ctx.conn).captures[max(Model(ctx.conn).captures)]
    assert c.email_layer_0 == "1 link kept. Left out: 4 blocked links."


def test_always_keep_from_the_menu_ticks_its_sites_rows(ctx, window):
    ctx.settings.other_links = "untick"
    window._add_email(invitation())
    row = next(e for e in window.files if e.row.path == VENDOR_2)
    site = next(e for e in window.files if e.row.path == SITE)
    site.keep.setChecked(True)  # the owner's own tick stays
    next(a for a in link_filter.menu_for(window, row).actions() if a.text().startswith("Always")).trigger()
    # Only its own site: www.norvane.example.com isn't under parts.norvane.example.com.
    assert links(window) == [(SITE, True), (VENDOR, False), (VENDOR_2, True)]
    assert ctx.settings.links_keep == ["parts.norvane.example.com"]
    menu = link_filter.menu_for(window, row)
    assert [a.isEnabled() for a in menu.actions()] == [False, True]  # already on Always keep
    assert "Always keep" in row.note.text()


def test_rows_come_back_when_a_site_leaves_never_keep(ctx, window):
    ctx.settings.links_drop = ["norvane.example.com", *DEFAULT_DROP]
    window._add_email(invitation())
    assert links(window) == [(SITE, True)]
    window._add_email(EmailItem(subject="Second", sender="Ann Example", sent="2026-11-13 08:40", to="Me", body="x",
                                html='<a href="https://example.com/second">s</a>'))
    ctx.settings.links_drop = list(DEFAULT_DROP)
    window.links_changed()
    paths = [e.row.path for e in window.files]
    # Back under their own email, before the second email's rows.
    assert paths == [None, SITE, VENDOR, VENDOR_2, None, "https://example.com/second"]
    assert [window.files_box.indexOf(e.widget) for e in window.files] == sorted(window.files_box.indexOf(e.widget) for e in window.files)


def test_a_link_the_owner_adds_is_never_sorted_and_has_no_menu(ctx, window):
    window._add_file(FileRow("Join", JOIN), "added", focus=False)  # as Attach → A link… adds it
    entry = window.files[-1]
    assert not link_filter.is_email_link(entry)
    assert entry.widget.findChild(QFrame, "fileRow").contextMenuPolicy() != Qt.ContextMenuPolicy.CustomContextMenu
    window.links_changed()
    assert window.files[-1] is entry and entry.row.path == JOIN


def test_a_draft_brought_back_is_sorted_as_the_lists_are_now(ctx, window):
    window._add_email(invitation())
    vendor = next(e for e in window.files if e.row.path == VENDOR_2)
    vendor.desc.setText("Parts page.")
    data, _ = draft_ui.snapshot(window)
    ctx.settings.links_drop = [*DEFAULT_DROP, "norvane.example.com"]
    other = CaptureWindow(ctx)
    try:
        draft_ui.restore_files(other, "D1", data)
        assert [(e.row.path, e.row.description) for e in other.files if link_filter.is_email_link(e)] == [(SITE, "")]
        assert "1 link kept. Left out: 4 blocked links." in layer0_text(other)
        ctx.settings.links_drop = list(DEFAULT_DROP)
        other.files.clear()
        draft_ui.restore_files(other, "D1", data)
        got = {e.row.path: e.desc.text() for e in other.files if link_filter.is_email_link(e)}
        assert got[VENDOR_2] == "Parts page." and got[SITE] == ""
    finally:
        other.deleteLater()


def test_domain_of_a_row(window):
    window._add_email(invitation())
    assert [layer0.domain_of(e.row.path) for e in window.files if link_filter.is_email_link(e)] == [
        "example.sharepoint.com", "norvane.example.com", "parts.norvane.example.com"]
