"""The email link filter (release 5.146, the design workspace's docs/mods/email-link-filter-plan.md, decisions 635 to 640):
Settings' Always keep and Never keep, and Other links, as email layer 0 uses them. Every address here is made up, apart from
the meeting services Never keep starts with."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from docrepo import capacity, conversations, db, layer0, sent_watch
from docrepo.captures import capture_folder
from docrepo.config import Settings, make_safe_fs
from docrepo.layer0 import DEFAULT_DROP, LinkRules, rule_for
from docrepo.model import Model
from docrepo.sample import load_sample
from docrepo.save import CaptureDraft, EmailItem, email_layer0_line, email_rows, save_capture

AT = datetime(2026, 11, 13, 9, 0)
JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZjQ1NzA2%40thread.v2/0?context=%7b%22Tid%22%3a%22c0ffee%22%7d"
OPTIONS = "https://teams.microsoft.com/meetingOptions/?organizerId=c0ffee&tenantId=c0ffee&threadId=19_meeting"
DIAL_IN = "https://dialin.teams.microsoft.com/9f1e2d3c?id=555010"
HELP = "https://aka.ms/JoinTeamsMeeting?omkt=en-US"
ZOOM = "https://acme.zoom.us/j/5550104477?pwd=abc"
SITE = "https://example.sharepoint.com/sites/Line1/Shared%20Documents/Pump%20trial%20plan.docx"
VENDOR = "https://norvane.example.com/guards/cg-380/install-guide.pdf"
SAFE_ZOOM = "https://nam02.safelinks.protection.outlook.com/?url=https%3A%2F%2Facme.zoom.us%2Fj%2F5550104477&data=05%7C02&reserved=0"


def invitation() -> EmailItem:
    """A made-up meeting invitation: the plan on SharePoint, a vendor's guide, and the four links a Teams invitation
    carries, one of them twice, with an address and Zoom behind Safe Links."""
    links = [SITE, VENDOR, JOIN, OPTIONS, DIAL_IN, HELP, JOIN, SAFE_ZOOM.replace("&", "&amp;"), "mailto:dana@example.com"]
    html = "<p>Pump trial review.</p>" + "".join(f'<p><a href="{u}">link</a></p>' for u in links)
    return EmailItem(subject="Pump trial review", sender="Dana Example", sent="2026-11-13 08:30", to="Me",
                     body=f"Pump trial review.\nJoin the meeting <{JOIN}>", html=html)


# ---- rule_for (decisions 635 and 636) ----
def test_a_domain_covers_its_subdomains_and_nothing_else():
    rules = LinkRules(drop=("zoom.us",))
    assert rule_for("https://zoom.us/j/1", rules) == "drop"
    assert rule_for("https://acme.zoom.us/j/1", rules) == "drop"
    assert rule_for("https://a.b.zoom.us/", rules) == "drop"
    assert rule_for("https://notzoom.us/j/1", rules) == ""
    assert rule_for("https://zoom.us.example.com/", rules) == ""
    assert rule_for("https://zoom.usa.example/", rules) == ""


def test_a_path_entry_covers_only_addresses_that_start_with_it():
    rules = LinkRules(drop=("teams.microsoft.com/l/meetup-join",))
    assert rule_for(JOIN, rules) == "drop"
    assert rule_for("https://teams.microsoft.com/l/meetup-join", rules) == "drop"
    assert rule_for("https://teams.microsoft.com/l/channel/19%3a", rules) == ""
    assert rule_for("https://teams.microsoft.com/", rules) == ""
    assert rule_for("https://example.com/l/meetup-join", rules) == ""


def test_case_scheme_and_www_dont_matter():
    rules = LinkRules(keep=("WWW.Example.SharePoint.com/Sites/LINE1",), drop=("https://www.zoom.us/",))
    assert rule_for("https://example.sharepoint.com/sites/line1/x.docx", rules) == "keep"
    assert rule_for("HTTPS://EXAMPLE.SHAREPOINT.COM/SITES/Line1/x.docx", rules) == "keep"
    assert rule_for("http://www.example.sharepoint.com/sites/Line1", rules) == "keep"
    assert rule_for("https://WWW.ZOOM.US/j/1", rules) == "drop"
    assert rule_for(OPTIONS, LinkRules(drop=("teams.microsoft.com/meetingoptions",))) == "drop"  # the path's case too
    assert layer0.tidy_entry("HTTPS://www.Zoom.US/") == "zoom.us"
    assert layer0.tidy_entry(" *.Example.com/Sites/Team ") == "example.com/Sites/Team"


def test_safe_links_are_unwrapped_first():
    assert rule_for(SAFE_ZOOM, LinkRules(drop=("zoom.us",))) == "drop"
    assert rule_for(SAFE_ZOOM, LinkRules(drop=("safelinks.protection.outlook.com",))) == ""
    assert layer0.domain_of(SAFE_ZOOM) == "acme.zoom.us" and layer0.domain_of("https://www.example.com/a") == "example.com"


def test_the_longer_entry_wins_and_a_tie_goes_to_never_keep():
    rules = LinkRules(keep=("microsoft.com",), drop=("teams.microsoft.com/l/meetup-join",))
    assert rule_for(JOIN, rules) == "drop"
    assert rule_for("https://teams.microsoft.com/l/channel/1", rules) == "keep"
    assert rule_for("https://learn.microsoft.com/a", rules) == "keep"
    rules = LinkRules(keep=("teams.microsoft.com/l/meetup-join/19",), drop=("teams.microsoft.com/l/meetup-join",))
    assert rule_for(JOIN, rules) == "keep"
    assert rule_for(JOIN, LinkRules(keep=("zoom.us", "microsoft.com"), drop=("microsoft.com",))) == "drop"  # the same entry
    assert rule_for("https://a.example.com/abcd", LinkRules(keep=("example.com/abcd",), drop=("a.example.com",))) == "keep"  # 16 to 13
    assert rule_for("https://ab.example.com/a", LinkRules(keep=("example.com/a",), drop=("ab.example.com",))) == "drop"  # 13 to 14


def test_an_exact_tie_of_different_entries_goes_to_never_keep():
    # Both 13 characters: a.example.com, and example.com/a with its slash.
    rules = LinkRules(keep=("example.com/a",), drop=("a.example.com",))
    assert rule_for("https://a.example.com/a", rules) == "drop"


def test_a_line_that_isnt_a_site_is_refused_with_its_number():
    assert layer0.entry_problem("zoom.us") == "" and layer0.entry_problem("teams.microsoft.com/l/meetup-join") == ""
    for bad in ("zoom", "zoom us", "10.0.0.1", "example.com:8080", "-x.example.com", "mailto:dana@example.com", "file://server/share",
                "example.com/a b", "https://"):
        assert layer0.entry_problem(bad), bad
    assert layer0.list_problem(["zoom.us", "", "teams.microsoft.com/meet", "not a site"]) == (4, "not a site", "it isn't a domain")
    assert layer0.list_problem(["zoom.us", " "]) is None
    assert layer0.tidy_list(["Zoom.us", "", "https://zoom.us/", "webex.com"]) == ["zoom.us", "webex.com"]


def test_an_entry_that_cant_be_used_matches_nothing():
    assert rule_for("https://zoom.us/j/1", LinkRules(drop=("zoom", "not a site"))) == ""


def test_never_keeps_start_holds_the_meeting_links():
    rules = LinkRules(drop=DEFAULT_DROP)
    for url in (JOIN, OPTIONS, DIAL_IN, HELP, ZOOM, "https://teams.microsoft.com/meet/2468?p=abc", "https://teams.live.com/meet/9e1",
                "https://meet.google.com/abc-defg-hij", "https://acme.webex.com/acme/j.php?MTID=m1", "https://global.gotomeeting.com/join/55501"):
        assert rule_for(url, rules) == "drop", url
    for url in (SITE, VENDOR, "https://teams.microsoft.com/l/channel/19%3a", "https://aka.ms/other"):
        assert rule_for(url, rules) == "", url
    assert all(not layer0.entry_problem(e) for e in DEFAULT_DROP)


def test_put_on_takes_the_site_off_the_other_list():
    keep, drop = layer0.put_on(["example.com"], ["zoom.us"], "Example.com", "drop")
    assert (keep, drop) == ([], ["zoom.us", "example.com"])
    keep, drop = layer0.put_on(keep, drop, "zoom.us", "keep")
    assert (keep, drop) == (["zoom.us"], ["example.com"])
    assert layer0.put_on(["zoom.us"], [], "ZOOM.US", "keep") == (["zoom.us"], [])


# ---- layer 0's rows and line, for each Other links choice (decisions 636, 637 and 640) ----
def kinds(rows):
    return [(r.part.url, r.keep) for r in rows[1:]]


def test_without_lists_every_web_link_is_kept_as_before():
    found = layer0.find(invitation())
    assert [p.url for p in found.parts] == [SITE, VENDOR, JOIN, OPTIONS, DIAL_IN, HELP, layer0.unwrap(SAFE_ZOOM)[0]]
    assert (found.blocked, found.left, found.repeats, found.addresses) == (0, 0, 1, 1)


def test_keep_them_keeps_links_on_neither_list():
    rules = LinkRules(drop=DEFAULT_DROP)
    rows = email_rows(invitation(), rules)
    assert kinds(rows) == [(SITE, True), (VENDOR, True)]
    assert [r.part.rule for r in rows[1:]] == ["other", "other"]
    assert email_layer0_line(rows[0].email, rows, rules) == ("2 links kept. Left out: 1 email address, 1 repeated link and "
                                                             "5 blocked links.")


def test_show_them_unticked_starts_links_on_neither_list_unticked():
    rules = LinkRules(keep=("example.sharepoint.com",), drop=DEFAULT_DROP, other="untick")
    rows = email_rows(invitation(), rules)
    assert kinds(rows) == [(SITE, True), (VENDOR, False)]
    assert [r.part.rule for r in rows[1:]] == ["keep", "other"]
    assert email_layer0_line(rows[0].email, rows, rules) == ("1 link kept. Left out: 1 email address, 1 repeated link, 5 blocked links "
                                                             "and 1 unticked row.")


def test_leave_them_out_counts_them_as_other_links():
    rules = LinkRules(keep=("example.sharepoint.com",), drop=DEFAULT_DROP, other="leave")
    rows = email_rows(invitation(), rules)
    assert kinds(rows) == [(SITE, True)]
    found = layer0.find(invitation(), rules)
    assert (found.blocked, found.left) == (5, 1)
    assert email_layer0_line(rows[0].email, rows, rules) == ("1 link kept. Left out: 1 email address, 1 repeated link, 5 blocked links "
                                                             "and 1 other link.")


def test_only_web_links_are_sorted_and_attachments_stay():
    from docrepo.save import Attachment

    email = invitation()
    email.attachments = [Attachment("Trial plan.pdf", lambda p: None, size=40_000)]
    rows = email_rows(email, LinkRules(drop=("example.sharepoint.com", "norvane.example.com"), other="leave"))
    assert [(r.part.kind, r.name) for r in rows[1:]] == [("attachment", "Trial plan.pdf")]


def test_a_plain_text_email_is_sorted_too():
    email = EmailItem(subject="Call", sender="Dana Example", sent="2026-11-13 08:30", to="Me",
                      body=f"Join <{JOIN}> or see the plan <{SITE}>.")
    rows = email_rows(email, LinkRules(drop=DEFAULT_DROP))
    assert kinds(rows) == [(SITE, True)]


# ---- Settings (decisions 635 and 639) ----
def test_the_lists_are_left_out_of_settings_json_at_their_start(tmp_path):
    root = tmp_path / "DocRepoData"
    fs = make_safe_fs(root, Settings())
    s = Settings(me="P001")
    assert s.links_keep == [] and s.links_drop == list(DEFAULT_DROP) and s.other_links == "keep"
    s.save(fs, root)
    data = json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert not {"links_keep", "links_drop", "other_links"} & set(data)
    assert Settings.load(root).links_drop == list(DEFAULT_DROP)  # an existing data root gets the same start


def test_changed_lists_are_written_and_read_back(tmp_path):
    root = tmp_path / "DocRepoData"
    fs = make_safe_fs(root, Settings())
    Settings(links_keep=["example.sharepoint.com"], links_drop=[], other_links="untick").save(fs, root)
    data = json.loads((root / "Config" / "settings.json").read_text(encoding="utf-8"))
    assert (data["links_keep"], data["links_drop"], data["other_links"]) == (["example.sharepoint.com"], [], "untick")
    s = Settings.load(root)
    assert (s.links_keep, s.links_drop, s.other_links) == (["example.sharepoint.com"], [], "untick")  # an emptied list stays empty


def test_settings_json_is_checked_on_load(tmp_path, caplog):
    root = tmp_path / "DocRepoData"
    (root / "Config").mkdir(parents=True)
    (root / "Config" / "settings.json").write_text(json.dumps({
        "links_keep": "example.com", "links_drop": ["Zoom.us", "not a site", "https://www.webex.com/"], "other_links": "sometimes"}),
        encoding="utf-8")
    s = Settings.load(root)
    assert (s.links_keep, s.links_drop, s.other_links) == ([], ["zoom.us", "webex.com"], "keep")
    assert "links_keep" in caplog.text and "other_links" in caplog.text and "Leaving 1 entries out of links_drop" in caplog.text


# ---- a T-mail's sent copy, captured with no window (decision 640) ----
@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), Settings(me="P001"))
    yield conn, data_root, fs
    conn.close()


def test_a_sent_copy_is_captured_without_its_blocked_links(env):
    conn, root, fs = env
    settings = Settings(me="P001")
    t_id = conversations.record_t_mail(conn, "T000012", "new", AT.strftime("%Y-%m-%d %H:%M:%S"), "01" + "AB" * 21)
    t = next(t for t in Model(conn).t_mails if t.id == t_id)
    got = sent_watch.save_sent(conn, root, fs, settings, t, invitation(), AT)
    assert got is not None
    m = Model(conn)
    c = m.captures[got.capture]
    assert [m.documents[d.document].original for d in c.documents] == [SITE, VENDOR]
    assert c.email_layer_0 == "2 links kept. Left out: 1 email address, 1 repeated link and 5 blocked links."
    # Only the rows change: the email's text keeps its links in the content text.
    assert JOIN in (capture_folder(root, c.id, c.saved) / "capture.md").read_text(encoding="utf-8")


def test_a_capture_saved_with_settings_lists_counts_its_blocked_links(env):
    conn, root, fs = env
    settings = Settings(me="P001", other_links="leave", links_keep=["example.sharepoint.com"])
    rules = LinkRules.of(settings)
    r = save_capture(conn, root, fs, settings, CaptureDraft(task="T000012", types={"note"}, files=email_rows(invitation(), rules)), AT)
    c = Model(conn).captures[r.capture_id]
    assert c.email_layer_0 == "1 link kept. Left out: 1 email address, 1 repeated link, 5 blocked links and 1 other link."
