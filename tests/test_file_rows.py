"""How a file is listed (release 5.114, the file rows review's decisions 427 to 434): ``docrepo.file_rows`` and the tidy
snippets of ``docrepo.text.snip``, without Qt. The lists that draw them are tested in ``test_file_rows_ui.py``."""
from __future__ import annotations

from datetime import date

from docrepo import detail, finder, search
from docrepo.file_rows import (GROUP_NAMES, dated_name, doc_places, folder_of, place_words, type_colour, type_icon, type_name,
                               without_title)
from docrepo.model import Model
from docrepo.text import snip


def test_each_type_has_one_icon_and_colour():
    """Decision 427: every list draws a type the same way; one with no mark of its own is Other's."""
    assert (type_icon("pdf"), type_colour("pdf"), type_name("pdf")) == ("type-pdf", "type_pdf", "PDF")
    assert (type_icon("sheet"), type_colour("sheet")) == ("type-sheet", "type_sheet")
    assert (type_icon("folder"), type_colour("folder"), type_name("folder")) == ("folder", "type_other", "Folder")
    assert (type_icon("visio"), type_colour("visio"), type_name("visio")) == ("type-other", "type_other", "Other")


def test_a_document_knows_its_tasks_and_the_day_it_came(sample_conn):
    m = Model(sample_conn)
    places = doc_places(m)
    assert places["D000001"].tasks == ["T000001"] and places["D000001"].added.startswith("2026-09-10")
    assert place_words(m, places["D000001"]) == "Reactor impeller upgrade"
    assert place_words(m, places["D000002"]).endswith(" and 1 more")
    assert place_words(m, places["D000003"]) == "Not filed yet" and place_words(m, None) == "Not filed yet"


def test_a_saved_copy_shows_its_name_without_its_day():
    """Decision 429: the day it was saved is at the row's end, so it isn't the start of its name too."""
    assert dated_name("2026-08-03 Tie-in list rev A.xlsx") == ("2026-08-03", "Tie-in list rev A.xlsx")
    assert dated_name("Tie-in list rev A.xlsx") == ("", "Tie-in list rev A.xlsx")
    assert dated_name("2026-08 notes.docx") == ("", "2026-08 notes.docx")


def test_the_preview_says_the_folder_not_the_whole_path():
    """Decision 432: the name is the preview's title already."""
    assert folder_of(r"\\fileserver\eng\Line 2\Tie-in list rev D.xlsx") == "\\\\fileserver\\eng\\Line 2\\"
    assert folder_of("C:/Plant/Pump.pdf") == "C:/Plant/"
    assert folder_of("https://example.sharepoint.com/sites/Plant/Pump.pdf") == "https://example.sharepoint.com/sites/Plant/Pump.pdf"
    assert folder_of("Pump.pdf") == "Pump.pdf" and folder_of("") == ""


def test_a_snippet_leaves_out_its_rows_own_title():
    """Decision 430: an email's text often starts with its subject, which is the row's first line."""
    assert without_title("…Re: pump curve rev C Rev C attached.", "Re: pump curve rev C") == "Rev C attached."
    assert without_title("Norvane Pumps · VFD datasheet rev A · Attached the VFD…", "VFD datasheet rev A") == "Norvane Pumps · Attached the VFD…"
    assert without_title("…the new pump skid.", "Tie-in sketch") == "…the new pump skid."
    assert without_title("", "Anything") == ""


def test_search_headings_are_plural():
    assert set(GROUP_NAMES) == set(search.GROUPS) and GROUP_NAMES["Person"] == "People" and GROUP_NAMES["Saved copy"] == "Saved copies"


def test_a_snippet_is_words_not_an_emails_headers():
    """Decision 433: no addresses, no "From:" or "Subject:", and it starts and ends at a word."""
    text = "Sent: Wed 7 Oct From: Dana Kim <dana@example.com> Subject: Re: seal flush plan The pump seal arrives on Tuesday."
    assert snip(text, text.index("seal"), 200, 200) == "Wed 7 Oct · Dana Kim · Re: seal flush plan The pump seal arrives on Tuesday."
    long = "words " * 20 + "the impeller arrives " + "more words " * 20
    out = snip(long, long.index("impeller"), 20, 60)
    assert out.startswith("…") and out.endswith("…") and "impeller" in out
    assert out[1:].split()[0] in ("words", "the") and not out[:-1].endswith(" ")  # whole words at both ends
    assert snip("x" * 30 + ". Control narrative for the pump.", 50, 20, 100).startswith("…Control")  # no stray full stop


def test_both_searches_share_the_tidy_snippet():
    text = "From: Dana <dana@example.com> Subject: Pump curve. The new pump curve is attached."
    assert "<" not in search.snippet(text, ["curve"]) and "Subject:" not in finder.snippet(text, ["curve"])
    assert search.snippet("a" * 100 + " needle " + "b" * 200, ["needle"]).startswith("…aaaa")  # no space near: cut as before


def test_the_files_group_lists_files_as_rows(sample_conn):
    """Decision 429: a type mark, the name as text with no saved day before it, the day at the end, Find files after."""
    m = Model(sample_conn)
    pages = detail.Pages(m, date(2026, 10, 8), lambda _: "")
    t = m.task("T000001")
    html = pages.files_body(t, m.files_of("T000001"))
    assert 'src="ft:pdf"' in html and ">Impeller datasheet rev B.pdf<" in html and ">2026-09-10 Impeller" not in html
    assert "10 Sep" in html and html.index("ft:pdf") < html.index("Find files")
    # The saved copy and the attachment have one name, so each says which it is; a file alone wouldn't.
    assert "saved copy" in html and "email attachment" in html
    one = pages.files_body(t, m.files_of("T000001")[:1])
    assert "saved copy" not in one and "Saved copy" not in one.split("title=")[0]
    some = pages.files_body(t, m.files_of("T000001"), limit=1)
    assert "Show all 2 in Find files" in some
    assert pages.files_body(t, []) == '<p class="note">No files yet.</p>'
