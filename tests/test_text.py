"""Sentences and capture titles."""
from __future__ import annotations

from docrepo.text import capture_title, first_sentence, plain_text, sentences


def test_sentences_skip_abbreviations():
    text = "Ask Dr. Patel to sign. Order the seal by Oct. 19 for the outage. Ping Tyler N. about it."
    assert [s.text for s in sentences(text)] == ["Ask Dr. Patel to sign.", "Order the seal by Oct. 19 for the outage.", "Ping Tyler N. about it."]
    assert [s.text for s in sentences("Approx. 20 guards. Done")] == ["Approx. 20 guards.", "Done"]


def test_a_line_break_ends_a_sentence():
    assert [s.text for s in sentences("Todo:\nOrder the seal\n\nCheck it")] == ["Todo:", "Order the seal", "Check it"]


def test_plain_text_leaves_out_email_headers_and_paths():
    content = "From: Calder Steam Services\nSubject: Quote\n\nQuote attached.\n\\\\fileserver\\eng\\quote.pdf\nC:\\Docs\\a.pdf"
    assert plain_text(content) == "Quote attached."


def test_first_sentence_is_cut_at_a_word():
    long = "Install " + "the new guard rails " * 10 + "today."
    title = first_sentence(long)
    assert title.endswith("…") and len(title) <= 101 and not title[:-1].endswith(" ")
    assert first_sentence("Rails need painting. Soon.") == "Rails need painting"


def test_capture_titles():
    assert capture_title("outlook_email", "From: Calder\nSubject: Steam trap survey quote\n\nHi.", "Quote.pdf", "C1") == "Steam trap survey quote"
    assert capture_title("typed", "Check the lockout points. Then the guards.", None, "C2") == "Check the lockout points"
    assert capture_title("file_path", "\\\\fileserver\\eng\\Walkthrough checklist.xlsx", "Walkthrough checklist.xlsx", "C3") == "Walkthrough checklist.xlsx"
    assert capture_title("typed", "", None, "C4") == "C4"
