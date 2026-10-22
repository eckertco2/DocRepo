"""Email layer 0 (mods log round 1, M0005, M0024): an email's attachments, links and pictures, each a row of its own."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import layer0  # noqa: E402
from docrepo.captures import capture_folder  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.save import Attachment, CaptureDraft, EmailItem, email_rows, save_capture  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402

AT = datetime(2026, 10, 8, 14, 10)
SETTINGS = Settings(me="P001")
CHECKLIST = "https://example.sharepoint.com/sites/Line1/Shared%20Documents/Guard%20install%20checklist.docx"
GUIDE = "https://norvane.example.com/guards/cg-380/install-guide.pdf"
SAFE = ("https://nam02.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.sharepoint.com%2Fsites%2FLine1%2FShared%2520Documents"
        "%2FGuard%2520install%2520checklist.docx&data=05%7C02%7C%7Cc0ffee%7C&reserved=0")
HTML = (f'<p>The guard ships on 14 Oct. Install guide: <a href="{GUIDE}">here</a>. Checklist: <a href="{SAFE.replace("&", "&amp;")}">checklist</a>.'
        f' Questions to <a href="mailto:orders@norvane.example.com">orders</a> or <a href="tel:+15550100">call</a>.'
        f' Guide again: <a href="{GUIDE}">guide</a>. <a href="#top">Top</a></p>'
        '<p><img src="cid:image001.jpg@01DC4A2B.5F3E1D20" alt="The guard"></p><p>Regards<br><img src="CID:<image002.png@01DC4A2B.5F3E1D20>"></p>')


def write(data: bytes):
    return lambda path: Path(path).write_bytes(data)


def sample_email() -> EmailItem:
    """A made-up vendor email: two attachments, links (one in Safe Links, one twice, an address, a phone number, a place
    in the email), a photo in the body, a small logo in the signature, and a hidden attachment the body doesn't show."""
    return EmailItem(
        subject="Revised coupling guard delivery", sender="Norvane Pumps (vendor)", sent="2026-10-08 09:30", to="Me",
        body="The guard ships on 14 Oct.", html=HTML, save_msg=write(b"MSG"),
        attachments=[
            Attachment("Coupling guard drawing rev C.pdf", write(b"Mounting: four M12 holes"), size=421_888),
            Attachment("Packing list 4471.xlsx", write(b"xlsx"), size=38_912),
            Attachment("image001.jpg", write(b"jpg"), size=190_464, content_id="image001.jpg@01DC4A2B.5F3E1D20", hidden=True),
            Attachment("image002.png", write(b"png"), size=4_096, content_id="<image002.png@01DC4A2B.5F3E1D20>", hidden=True),
            Attachment("image003.png", write(b"png"), size=2_000, content_id="image003.png@01DC4A2B.5F3E1D20", hidden=True),
        ])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_body_is_read_as_data():
    hrefs, cids = layer0.read_body(HTML)
    assert hrefs == [GUIDE, SAFE, "mailto:orders@norvane.example.com", "tel:+15550100", GUIDE, "#top"]
    assert cids == ["image001.jpg@01dc4a2b.5f3e1d20", "image002.png@01dc4a2b.5f3e1d20"]
    assert layer0.read_body("<p><a href='https://example.com/a'>a</a><img src='cid:x'") == (["https://example.com/a"], [])  # cut short
    assert layer0.unwrap(SAFE) == (CHECKLIST, True) and layer0.unwrap(GUIDE) == (GUIDE, False)


def test_what_layer_0_finds():
    found = layer0.find(sample_email())
    assert [(p.kind, p.name, p.keep) for p in found.parts] == [
        ("attachment", "Coupling guard drawing rev C.pdf", True), ("attachment", "Packing list 4471.xlsx", True),
        ("link", "install-guide.pdf", True), ("link", "Guard install checklist.docx", True),
        ("picture", "image001.jpg", True), ("picture", "image002.png", False)]
    link = found.parts[3]
    assert (link.url, link.safe) == (CHECKLIST, True)
    assert found.parts[5].small and not found.parts[4].small
    # Left out: the address, the phone number and the place in the email, the repeated guide, and image003 (hidden, not in the body).
    assert (found.addresses, found.other, found.repeats, found.hidden) == (1, 2, 1, 1)
    assert layer0.line(found, ["attachment", "attachment", "link", "link", "picture"], 1) == (
        "2 attachments, 2 links and 1 picture kept. Left out: 1 email address, 1 repeated link, 2 other links, 1 hidden attachment and 1 unticked row.")
    assert layer0.line(layer0.Found(()), [], 0) == "Nothing kept."
    assert (layer0.size_text(421_888), layer0.size_text(2_516_582)) == ("412 KB", "2.4 MB")


def test_saving_an_email_with_its_parts(sample_root):
    conn, root, fs = sample_root
    rows = email_rows(sample_email())
    assert rows[0].email and not rows[0].described and [r.keep for r in rows[1:]] == [True, True, True, True, True, False]
    for r, text in zip(rows[1:], ("Drawing.", "Packing list.", "Install guide.", "Checklist.", "Photo of the guard.", "")):
        r.description, r.save_a_copy, r.extract = text, True, True
    rows[3].keep = False  # leave the install guide out
    r = save_capture(conn, root, fs, SETTINGS, CaptureDraft(task="T000008", types={"note"}, files=rows), AT)
    m = Model(conn)
    c = m.captures[r.capture_id]
    docs = [m.documents[d.document] for d in c.documents]
    assert [(d.name, d.description, d.original, d.capture) for d in docs] == [
        ("Coupling guard drawing rev C.pdf", "Drawing.", None, c.id), ("Packing list 4471.xlsx", "Packing list.", None, c.id),
        ("Guard install checklist.docx", "Checklist.", CHECKLIST, None), ("image001.jpg", "Photo of the guard.", None, c.id)]
    # A picture has no Extract information, and a link neither that nor a saved copy.
    assert [(d.save_a_copy, d.extract) for d in c.documents] == [(True, True), (True, True), (False, False), (True, False)]
    assert c.attachments == ["Coupling guard drawing rev C.pdf", "Packing list 4471.xlsx", "image001.jpg"]
    folder = capture_folder(root, c.id, c.saved)
    assert sorted(p.name for p in (folder / "attachments").iterdir()) == ["Coupling guard drawing rev C.pdf", "Packing list 4471.xlsx", "image001.jpg"]
    assert (folder / "email.msg").read_bytes() == b"MSG"
    assert c.email_layer_0 == ("2 attachments, 1 link and 1 picture kept. Left out: 1 email address, 1 repeated link, 2 other links, "
                               "1 hidden attachment and 2 unticked rows.")
    assert f'email_layer_0: "{c.email_layer_0}"' in (folder / "capture.md").read_text(encoding="utf-8")


def test_the_capture_window_shows_each_part(qapp, sample_root):
    conn, root, fs = sample_root
    w = CaptureWindow(AppContext(conn, root, fs, SETTINGS, notify=lambda t, m: None, now=lambda: AT))
    w.show_capture(task="T000008")
    try:
        email = sample_email()
        w._add_email(email)
        email_entry, *parts = w.files
        assert email_entry.desc is None and "Email layer 0" in email_entry.layer0.text()
        assert [(e.row.name, e.keep.isChecked(), e.desc.isEnabled()) for e in parts] == [
            ("Coupling guard drawing rev C.pdf", True, True), ("Packing list 4471.xlsx", True, True), ("install-guide.pdf", True, True),
            ("Guard install checklist.docx", True, True), ("image001.jpg", True, True), ("image002.png", False, False)]
        assert parts[2].copy.isHidden() and parts[4].extract.isHidden() and not parts[4].copy.isHidden()
        assert w.focusWidget() is parts[0].desc and w.same_all.isVisibleTo(w)
        parts[2].keep.setChecked(False)
        assert not parts[2].desc.isEnabled() and "2 unticked rows" in email_entry.layer0.text()
        w.same_all.setChecked(True)
        parts[0].desc.setText("From the vendor.")
        rows = w._file_rows()
        assert {r.description for r in rows if r.described} == {"From the vendor."}
        w.save()
        c = Model(conn).captures["C000026"]
        assert len(c.documents) == 4 and "1 link" in c.email_layer_0
        w._add_email(sample_email())
        w._remove_file(w.files[0])  # removing the email removes its parts
        assert w.files == []
    finally:
        w.deleteLater()
