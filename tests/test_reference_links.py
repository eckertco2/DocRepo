"""A reference field's link address typed with no http:// or https:// (release 5.134, decision 546): a server's name and a
/ take http:// in front, as a browser's address bar reads them, and www. takes https://. Anything else is still refused.
The addresses are made up."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from docrepo.config import Settings
from docrepo.links import check_link_template, full_template, reference_link
from docrepo.model import Model
from docrepo.opener import start_link
from docrepo.pages import Pages
from docrepo.task_links import links_of

INSTALLATION = "T000008"
REFUSED = "starts with http://, https:// or a server's name and a /"


@pytest.mark.parametrize(("typed", "full"), [
    ("intranet/record?", "http://intranet/record?"),
    ("  intranet/record?id={}&tab=1 ", "http://intranet/record?id={}&tab=1"),
    ("records.example.com/view/", "http://records.example.com/view/"),
    ("intranet:8080/record/", "http://intranet:8080/record/"),
    ("intranet?record=", "http://intranet?record="),
    ("www.example.com/record/", "https://www.example.com/record/"),  # as Add link reads www.
    ("https://records.example.com/{}", "https://records.example.com/{}"),  # one with http:// or https:// is as it was
    ("HTTP://intranet/record?", "HTTP://intranet/record?"),
    ("", ""),
])
def test_an_address_gets_its_http(typed, full):
    assert full_template(typed) == full
    assert check_link_template(typed) == ""


def test_the_value_goes_at_the_end_or_at_its_braces():
    assert reference_link("intranet/record?", "4471") == "http://intranet/record?4471"
    assert reference_link("intranet/record?id={}&tab=1", " 4471 ") == "http://intranet/record?id=4471&tab=1"
    assert reference_link("records.example.com/view/{}", "A/12 3") == "http://records.example.com/view/A%2F12%203"
    assert reference_link("www.example.com/record/", "9") == "https://www.example.com/record/9"
    assert reference_link("intranet/record?", "") == ""


@pytest.mark.parametrize("typed", [
    "intranet",  # no / after the name: nowhere for a value to go
    "intranet record?",  # a space
    "mailto:records@example.com?subject={}",
    "javascript:alert(1)//",
    "file:///C:/records/{}",
    "C:/records/{}",
    "C:\\records\\{}",
    "\\\\server\\records\\{}",
    "ftp://records.example.com/{}",
    "/record/{}",
    "-intranet/record?",
])
def test_anything_else_is_still_refused(typed):
    assert check_link_template(typed) == REFUSED
    assert reference_link(typed, "4471") == ""


def test_settings_keep_it_as_typed_and_link_it_whole(data_root, fs):
    s = Settings(reference_fields=["Change record"], reference_links={"Change record": "intranet/record?"})
    s.save(fs, data_root)
    again = Settings.load(data_root)
    assert again.reference_links == {"Change record": "intranet/record?"}  # what was typed stays what's shown
    assert again.reference_link("Change record", "4471") == "http://intranet/record?4471"


def test_the_link_opens_on_a_click():
    handed: list[str] = []
    assert start_link(reference_link("intranet/record?", "4471"), starter=handed.append) is None
    assert handed == ["http://intranet/record?4471"]


def test_the_task_page_and_task_md_link_it(sample_conn):
    sample_conn.execute("INSERT INTO task_references (task, name, value) VALUES (?, ?, ?)", (INSTALLATION, "Change record", "4471"))
    sample_conn.commit()
    m = Model(sample_conn)
    links = {"Change record": "intranet/record?"}
    first = links_of(m, INSTALLATION, links)[0]
    assert (first.kind, first.name, first.address) == ("reference", "Change record 4471", "http://intranet/record?4471")
    md = Pages(m, date(2026, 10, 8), datetime(2026, 10, 8, 9, 0), links).task_page(m.task(INSTALLATION))
    assert "| Change record | [4471](http://intranet/record?4471) |" in md
