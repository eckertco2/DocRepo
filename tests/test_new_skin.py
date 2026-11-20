"""The new skin (release 5.181, the redesign's decisions 842 to 849 and 858): the values, the scales, and what the five lanes
after it rely on in the token file (the redesign plan's section 5a)."""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo.ui import tokens  # noqa: E402

LANES = (("A", "the shell"), ("B", "the lists"), ("C", "the pages"), ("D", "the floating windows"), ("E", "planning views and forms"))
#: Every scale the lanes name in a template (section 5a).
SCALES = ("radius_s", "radius", "radius_l", "radius_xl", "page_title", "view_title", "section", "body", "notes", "caption", "label")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_scales_have_the_plans_numbers():
    """Section 3's sizes: four corners for today's nine (decision 845) and the type range (decision 849)."""
    assert (tokens.RADIUS_S, tokens.RADIUS, tokens.RADIUS_L, tokens.RADIUS_XL) == (6, 8, 10, 12)
    assert (tokens.PAGE_TITLE, tokens.VIEW_TITLE, tokens.SECTION, tokens.BODY, tokens.NOTES, tokens.CAPTION, tokens.LABEL) == (
        19, 11.5, 10, 10.5, 11, 9.5, 9)
    assert (tokens.CONTROL, tokens.FIELD, tokens.TREE_ROW, tokens.LIST_ROW) == (32, 34, 28, 32)  # rows are lane B's (5.183)


def test_the_new_colours_are_in_both_themes():
    for name in ("sunken", "field", "nav_selected", "text3", "accent_fill"):
        assert re.fullmatch(r"#[0-9a-f]{6}", tokens.LIGHT[name]) and re.fullmatch(r"#[0-9a-f]{6}", tokens.DARK[name]), name
    assert (tokens.LIGHT["base"], tokens.LIGHT["accent"], tokens.DARK["content"]) == ("#f6f6f7", "#4a54d1", "#1b1b1e")


def test_both_templates_take_every_scale_by_name_and_end_with_the_lanes_sections():
    """Five lane builders each write only between their own two lines, in the style sheet and in the pages' CSS, and name a size
    by its scale, never as a number (section 5a)."""
    import re

    for template in (tokens._QSS.template, tokens._CSS.template):
        tail = template[template.index("/* ---- lane A"):]
        # what a lane writes between its own two lines is its own (release 5.182 on): the lines and their order stay
        tail = re.sub(r"(/\* ---- lane (\w) \([^)]*\) ---- \*/\n).*?(/\* ---- end lane \2 ---- \*/)", r"\1\n\3", tail, flags=re.S)
        want = "\n".join(f"/* ---- lane {k} ({name}) ---- */\n\n/* ---- end lane {k} ---- */\n" for k, name in LANES)
        assert tail == want
    for name in SCALES:
        assert name in tokens._SIZES, name
    for out in (tokens.qss(), tokens.css()):
        assert "$" not in out
    # a lane's rule naming a scale comes out as the number
    lane = tokens._QSS.template.replace("/* ---- end lane B ---- */", "QFrame#x { border-radius: ${radius_s}px; font-size: ${label}pt; }\n/* ---- end lane B ---- */")
    from string import Template
    out = Template(lane).substitute(tokens.active(), **tokens._SIZES, arrow="", tick="", marker="", branch_closed="", branch_open="",
                                    chev_left="", chev_right="")
    assert f"QFrame#x {{ border-radius: {tokens.RADIUS_S}px; font-size: {tokens.LABEL}pt; }}" in out


def test_the_controls_rules(qapp):
    """Decisions 847 and 848: the secondary button a soft fill with no edge, the primary the accent's fill, the quiet one grey
    words; a field one even edge at 8 px and the accent's edge with the keyboard in it."""
    q = tokens.qss()
    c = tokens.colour
    assert f"QPushButton {{ background: {c('hover')}; color: {c('text')}; border: 1px solid transparent; border-radius: {tokens.RADIUS}px;" in q
    assert f"QPushButton#primary {{ background: {c('accent_fill')}; color: {c('on_accent')};" in q
    assert f"QPushButton#subtle, QToolButton#subtle {{ background: transparent; border: 1px solid transparent; color: {c('text2')}; }}" in q
    assert f"border: 1px solid {c('stroke_strong')}; border-radius: {tokens.RADIUS}px;" in q
    assert f"QDateEdit:focus {{ border: 2px solid {c('accent')};" in q
    assert f"QCheckBox::indicator:checked {{ background: {c('accent_fill')};" in q
    assert f"QFrame#statusCard {{ background: {c('sunken')}; border: none; border-radius: {tokens.RADIUS_L}px; }}" in q
    assert f"QFrame#prCol {{ background: {c('sunken')};" in q
    # links that are commands are grey (decision 844); the pages' links stay the accent
    assert f"QPushButton#link, QPushButton#moreLink, QPushButton#rowLink {{ background: transparent; border: none; color: {c('text2')};" in q
    assert f"a {{ color: {c('accent')}; text-decoration: none; }}" in tokens.css()


def test_a_state_is_coloured_as_well_as_shaped(qapp):
    """Decision 858: not started grey, in progress the accent, parked violet, closed green, in every recipe for a state's mark."""
    from docrepo.ui import state_menu, task_tile

    want = {"Not started": "text3", "In progress": "accent", "Parked": "parked", "Closed": "success"}
    for state, colour in want.items():
        assert task_tile.STATE_ICONS[state][1] == colour
        assert state_menu.MARKS[state][1] == colour
    assert f".st-cl {{ color: {tokens.colour('success')}; background-color: {tokens.colour('success_bg')}; }}" in tokens.css()


def test_popups_ask_windows_for_its_full_round_corners():
    from docrepo.ui import look

    assert (look.DWMWCP_ROUND, look.DWMWCP_ROUNDSMALL) == (2, 3)
