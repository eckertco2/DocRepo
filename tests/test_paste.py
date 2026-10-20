"""Pasted lists keep their bullets (mods log round 1, M0022). The HTML is shaped like what OneNote, Word and Outlook
put on the clipboard, with made-up text."""
from __future__ import annotations

from docrepo.paste import bullets_to_dashes, has_list, html_to_text

# OneNote nests a sub-list's <ul> straight inside the outer <ul>, and its plain text has no bullets.
ONENOTE = """<html><head><meta name=Generator content="Microsoft OneNote 15"><style>p {margin:0}</style></head>
<body lang=en-US style='font-family:Calibri;font-size:11.0pt'>
<!--StartFragment-->
<p style='margin:0in;font-family:Calibri;font-size:11.0pt'>Pump 7 walkdown</p>
<ul type=disc style='direction:ltr;unicode-bidi:embed;margin-top:0in;margin-bottom:0in'>
 <li style='margin-top:0;margin-bottom:0;vertical-align:middle'><span style='font-family:Calibri'>Check the coupling&nbsp;guard</span></li>
 <ul type=circle style='direction:ltr;unicode-bidi:embed;margin-top:0in;margin-bottom:0in'>
  <li style='margin-top:0;margin-bottom:0'><span>Bolts torqued</span></li>
  <li style='margin-top:0;margin-bottom:0'><span>Paint touched up</span></li>
 </ul>
 <li style='margin-top:0;margin-bottom:0'><span>Book the alignment</span></li>
</ul>
<p style='margin:0in'>&nbsp;</p>
<ol type=1 style='margin-top:0in;margin-bottom:0in'>
 <li value=1 style='margin-top:0'><span>Isolate</span></li>
 <li style='margin-top:0'><span>Drain</span></li>
</ol>
<!--EndFragment-->
</body></html>"""

# Word and Outlook: list paragraphs with mso-list, the bullet in a hidden span between <![if !supportLists]> and <![endif]>.
WORD = """<html><body>
<p class=MsoListParagraphCxSpFirst style='text-indent:-.25in;mso-list:l0 level1 lfo1'><![if !supportLists]><span
style='font-family:Symbol'><span style='mso-list:Ignore'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp;
</span></span></span><![endif]>Order the seal kit</p>
<p class=MsoListParagraphCxSpMiddle style='margin-left:1.0in;text-indent:-.25in;mso-list:l0 level2 lfo1'><![if !supportLists]><span
style='font-family:"Courier New"'><span style='mso-list:Ignore'>o<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;
</span></span></span><![endif]>Two spares</p>
<p class=MsoListParagraphCxSpLast style='text-indent:-.25in;mso-list:l1 level1 lfo2'><!--[if !supportLists]--><span
style='mso-list:Ignore'>1.<span>&nbsp;&nbsp;</span></span><!--[endif]-->Confirm the price</p>
<p class=MsoNormal>Thanks</p>
</body></html>"""


def test_a_onenote_list_keeps_its_bullets_and_levels():
    assert has_list(ONENOTE)
    assert html_to_text(ONENOTE) == ("Pump 7 walkdown\n- Check the coupling guard\n  - Bolts torqued\n  - Paint touched up\n"
                                     "- Book the alignment\n\n1. Isolate\n2. Drain")


def test_a_word_or_outlook_list_keeps_its_bullets_and_numbers():
    assert has_list(WORD)
    assert html_to_text(WORD) == "- Order the seal kit\n  - Two spares\n1. Confirm the price\nThanks"


def test_html_without_a_list_is_left_to_the_plain_text():
    assert not has_list("<p>Just a line</p><p>And another</p>")


def test_bullet_characters_in_plain_text_become_dashes():
    assert bullets_to_dashes("Walkdown\n•\tGuard\n\t•\tBolts\no\tPaint\n· Drain\nonly a word") == (
        "Walkdown\n- Guard\n  - Bolts\n- Paint\n- Drain\nonly a word")
