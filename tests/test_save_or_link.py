"""Save or link (release 5.145, the save or link plan's decisions 627 to 634), without Qt: an email's attachments always
saved, a saved file a file of its own, a linked file read where it is, an unfiled capture's saved files in its own folder
until it's filed, and the words lists, pages and search use for them. The examples are made up."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from docrepo import capacity, db, detail, edits, finder, save, search
from docrepo.captures import capture_folder, copy_name, file_of, files_taken
from docrepo.config import Settings
from docrepo.layer0 import Part
from docrepo.model import Model
from docrepo.pages import Pages
from docrepo.sample import load_sample
from docrepo.save import Attachment, CaptureDraft, EmailItem, FileRow, email_rows, save_capture

AT = datetime(2026, 11, 13, 9, 30)
DAY = "2026-11-13"
SETTINGS = Settings(me="P001")
INSTALLATION = "T000008"


@pytest.fixture
def env(data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    capacity.rebuild_all(conn, AT.date(), SETTINGS)
    yield conn, data_root, fs
    conn.close()


def saved(env, draft: CaptureDraft, at: datetime = AT):
    conn, root, fs = env
    return save_capture(conn, root, fs, SETTINGS, draft, at)


def share(tmp_path: Path, name: str, text: str) -> Path:
    """A made-up file where it already lives, as on a LAN share."""
    path = tmp_path / "share" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def files_folder(root: Path, task: str) -> Path:
    return root / "Tasks" / task / "Files"


# ---- decision 629: an email's attachments are always saved ----
def test_an_emails_attachments_go_into_the_tasks_files_folder_with_no_tick(env):
    conn, root, _ = env
    email = EmailItem("Pump curve and seal drawing", "Norvane Pumps (vendor)", "2026-11-12 16:02", "Me", "Both attached.",
                      attachments=[Attachment("Pump curve.txt", data=b"Design point 38 kW"), Attachment("Seal drawing.txt", data=b"Seal: 4 x M12")],
                      msg_bytes=b"MSG")
    rows = email_rows(email)
    assert [r.save_a_copy for r in rows[1:]] == [False, False]  # nothing ticked, as the window would leave them
    r = saved(env, CaptureDraft(task=INSTALLATION, types={"note"}, files=rows))
    m = Model(conn)
    c = m.captures[r.capture_id]
    folder = capture_folder(root, c.id, c.saved)
    assert (files_folder(root, INSTALLATION) / f"{DAY} Pump curve.txt").read_bytes() == b"Design point 38 kW"
    assert (files_folder(root, INSTALLATION) / f"{DAY} Seal drawing.txt").read_text(encoding="utf-8") == "Seal: 4 x M12"
    assert (folder / "email.msg").read_bytes() == b"MSG" and not (folder / "attachments").exists()  # the .msg is the record
    assert [d.save_a_copy for d in c.documents] == [True, True]
    seal = next(d for d in c.document_ids if m.documents[d].name == "Seal drawing.txt")
    assert (root / "Documents" / seal / "extracted.txt").read_text(encoding="utf-8") == "Seal: 4 x M12"
    # One file each on the task, listed as a saved file; Task.md links to it there.
    kinds = [(f.kind, f.name) for f in m.files_of(INSTALLATION) if f.document in c.document_ids]
    assert kinds == [("Saved file", f"{DAY} Pump curve.txt"), ("Saved file", f"{DAY} Seal drawing.txt")]
    assert f"- Saved file: [{DAY} Seal drawing.txt](Files/{DAY}%20Seal%20drawing.txt)" in Pages(m, AT.date(), AT).task_page(m.task(INSTALLATION))
    assert not r.problems


def test_an_attachment_dragged_out_of_an_email_is_saved_and_a_pasted_picture_stays(env):
    """A file a program handed over has no place on disk to link to (decision 628); a picture stays with its capture."""
    conn, root, fs = env
    handed = FileRow("Lift plan.txt", part=Part("attachment", "Lift plan.txt", Attachment("Lift plan.txt", data=b"Lift plan, made up"), size=18))
    png = b"\x89PNG\r\n\x1a\n made up"
    picture = FileRow("Picture.png", part=Part("picture", "Picture.png", Attachment("Picture.png", save=lambda t: fs.write_picture(t, png)),
                                               size=len(png), pasted=True), save_a_copy=True)
    r = saved(env, CaptureDraft(content="From the site.", task=INSTALLATION, types={"note"}, files=[handed, picture]))
    m = Model(conn)
    c = m.captures[r.capture_id]
    assert [d.save_a_copy for d in c.documents] == [True, False]
    assert (files_folder(root, INSTALLATION) / f"{DAY} Lift plan.txt").read_bytes() == b"Lift plan, made up"
    assert (capture_folder(root, c.id, c.saved) / "attachments" / "Picture.png").exists()  # shown on the notes page
    assert [f.name for f in m.copies if f.from_capture == c.id] == [f"{DAY} Lift plan.txt"]


# ---- decisions 630 and 631: a saved file is a file of its own; a linked file is read where it is ----
def test_a_saved_files_text_is_read_from_the_file_written(env, tmp_path, monkeypatch):
    conn, root, _ = env
    original = share(tmp_path, "Pump curve.txt", "Design point 38 kW")
    read_from = []
    real = save.extract_text
    monkeypatch.setattr(save, "extract_text", lambda path, cap: read_from.append(Path(path)) or real(path, cap))
    r = saved(env, CaptureDraft(task=INSTALLATION, types={"note"}, files=[FileRow("Pump curve.txt", str(original), "The vendor's curve.", save_a_copy=True)]))
    m = Model(conn)
    doc = m.captures[r.capture_id].document_ids[0]
    kept = files_folder(root, INSTALLATION) / f"{DAY} Pump curve.txt"
    assert read_from == [kept] and kept.read_text(encoding="utf-8") == "Design point 38 kW"
    assert m.documents[doc].original == str(original)  # where it came from, a fact on its page
    assert file_of(root, m, doc) == kept == edits.source_of(root, m, doc)  # that file is the document from now on
    original.write_text("Changed where it was", encoding="utf-8")
    assert kept.read_text(encoding="utf-8") == "Design point 38 kW"  # DocRepo doesn't go back to the original
    page = detail.Pages(m, AT.date(), lambda _: "").document_page(doc)
    assert "Saved file" in page and f"Tasks\\{INSTALLATION}\\Files\\{DAY} Pump curve.txt" in page
    assert "Came from" in page and str(original) in page and "Linked" not in page


def test_a_linked_file_is_read_where_it_is(env, tmp_path, monkeypatch):
    conn, root, _ = env
    original = share(tmp_path, "Seal kit spec.txt", "Seal kit 4471")
    read_from = []
    real = save.extract_text
    monkeypatch.setattr(save, "extract_text", lambda path, cap: read_from.append(Path(path)) or real(path, cap))
    r = saved(env, CaptureDraft(task=INSTALLATION, types={"note"}, files=[FileRow("Seal kit spec.txt", str(original), "The spec.")]))
    m = Model(conn)
    doc = m.captures[r.capture_id].document_ids[0]
    assert read_from == [original] and not any(f.document == doc for f in m.copies)
    assert not files_folder(root, INSTALLATION).joinpath(f"{DAY} Seal kit spec.txt").exists()
    assert file_of(root, m, doc) == original
    assert [(f.kind, f.name) for f in m.files_of(INSTALLATION) if f.document == doc] == [("Linked file", "Seal kit spec.txt")]
    page = detail.Pages(m, AT.date(), lambda _: "")
    assert "Read where it is" in page.document_page(doc) and "Came from" not in page.document_page(doc)
    files = page.files_body(m.task(INSTALLATION), m.files_of(INSTALLATION))
    assert 'src="lk:link"' in files and "Linked: read where it is" in files  # the link mark, and its tooltip
    assert f"- Linked file: `{original}` · {doc}" in Pages(m, AT.date(), AT).task_page(m.task(INSTALLATION))


def test_folders_and_links_are_always_linked(env, tmp_path):
    conn, root, _ = env
    drawings = tmp_path / "Drawings"
    drawings.mkdir()
    rows = [FileRow("Drawings", f"{drawings}\\", save_a_copy=True), FileRow("Crane booking", "https://example.com/crane-booking", save_a_copy=True)]
    r = saved(env, CaptureDraft(task=INSTALLATION, types={"note"}, files=rows))
    c = Model(conn).captures[r.capture_id]
    assert [d.save_a_copy for d in c.documents] == [False, False] and not any(f.from_capture == c.id for f in Model(conn).copies)


def test_a_saved_file_takes_a_name_no_file_in_the_folder_has(env, tmp_path):
    """A file in the Files folder with no saved file's record (such as a picture pasted on the notes page): a new saved
    file's name steers round it, as copying never overwrites."""
    conn, root, fs = env
    fs.write_text(files_folder(root, INSTALLATION) / f"{DAY} Site notes.txt", "Already there")
    assert f"{DAY} Site notes.txt" in files_taken(conn, root, INSTALLATION)
    assert copy_name(DAY, "Site notes.txt", files_taken(conn, root, INSTALLATION)) == f"{DAY} Site notes (2).txt"
    notes = share(tmp_path, "Site notes.txt", "Walkdown notes")
    r = saved(env, CaptureDraft(task=INSTALLATION, types={"note"}, files=[FileRow("Site notes.txt", str(notes), save_a_copy=True)]))
    assert not r.problems and (files_folder(root, INSTALLATION) / f"{DAY} Site notes (2).txt").read_text(encoding="utf-8") == "Walkdown notes"


# ---- decision 631: an unfiled capture's saved files are in its own folder until it's filed ----
def test_an_unfiled_capture_keeps_its_saved_files_then_filing_moves_them(env, tmp_path):
    conn, root, fs = env
    original = share(tmp_path, "Pump curve.txt", "Design point 38 kW")
    email = EmailItem("Seal kit quote", "Norvane Pumps (vendor)", "2026-11-12 09:10", "Me", "Quote attached.",
                      attachments=[Attachment("Quote 4471.txt", data=b"Seal kit: 4471")], msg_bytes=b"MSG")
    rows = [FileRow("Pump curve.txt", str(original), "The curve.", save_a_copy=True), *email_rows(email)]
    r = saved(env, CaptureDraft(content="For later.", files=rows))
    m = Model(conn)
    c = m.captures[r.capture_id]
    assert m.is_unfiled(c)
    folder = capture_folder(root, c.id, c.saved)
    held, quote = folder / "Files" / f"{DAY} Pump curve.txt", folder / "attachments" / "Quote 4471.txt"
    assert held.read_text(encoding="utf-8") == "Design point 38 kW" and quote.read_bytes() == b"Seal kit: 4471"
    curve, quote_doc = c.document_ids
    assert file_of(root, m, curve) == held and file_of(root, m, quote_doc) == quote
    original.unlink()  # nothing depends on the original staying put
    out = edits.file_capture(conn, root, fs, c.id, INSTALLATION, AT)
    assert "2 saved files put in its Files folder" in out.message and not out.problems
    m = Model(conn)
    files = files_folder(root, INSTALLATION)
    assert (files / f"{DAY} Pump curve.txt").read_text(encoding="utf-8") == "Design point 38 kW"
    assert (files / f"{DAY} Quote 4471.txt").read_bytes() == b"Seal kit: 4471"
    assert not held.exists() and not quote.exists() and (folder / "email.msg").exists()  # moved: one file each; the .msg stays
    assert file_of(root, m, curve) == files / f"{DAY} Pump curve.txt" and file_of(root, m, quote_doc) == files / f"{DAY} Quote 4471.txt"


def test_make_it_a_task_files_the_saved_files_too(env, tmp_path):
    conn, root, _ = env
    original = share(tmp_path, "Rigging sketch.txt", "Two-point lift")
    r = saved(env, CaptureDraft(content="Rigging for the impeller lift.", files=[FileRow("Rigging sketch.txt", str(original), save_a_copy=True)]))
    made = saved(env, CaptureDraft(content="Rigging for the impeller lift.", task=INSTALLATION, types={"new_task"}, from_capture=r.capture_id))
    assert (files_folder(root, made.created_task) / f"{DAY} Rigging sketch.txt").read_text(encoding="utf-8") == "Two-point lift"
    assert not (capture_folder(root, r.capture_id, Model(conn).captures[r.capture_id].saved) / "Files" / f"{DAY} Rigging sketch.txt").exists()


# ---- decision 634: nothing to convert ----
def test_old_records_read_as_saved_and_linked_files(env, tmp_path):
    """The sample's saved copy is a saved file, its tracked original a linked file where it isn't saved, and an attachment
    from before stays in its capture's folder, where its document points. An old unfiled capture whose Save a copy waited
    for filing is copied from where the file is, as before."""
    conn, root, fs = env
    m = Model(conn)
    assert [(f.kind, f.name) for f in m.files_of(INSTALLATION)][:2] == [
        ("Saved file", "2026-09-22 Installation procedure.docx"), ("Old version", "2026-09-22 Installation procedure (replaced 2026-10-05).docx")]
    assert "Linked file" not in [f.kind for f in m.files_of(INSTALLATION) if f.document == "D000002"]  # each file once
    attachment = m.documents["D000001"]
    c = m.captures[attachment.capture]
    assert m.saved_of("D000001") and file_of(root, m, "D000001").parent == files_folder(root, m.saved_of("D000001")[0].task)
    # An old unfiled capture: its document was a tracked original with Save a copy ticked, its copy waiting.
    original = share(tmp_path, "Old report.txt", "Made-up report")
    r = saved(env, CaptureDraft(content="Old.", files=[FileRow("Old report.txt", str(original), save_a_copy=True)]))
    folder = capture_folder(root, r.capture_id, Model(conn).captures[r.capture_id].saved) / "Files"
    (folder / f"{DAY} Old report.txt").unlink()  # as before release 5.145, nothing was kept in the capture's folder
    folder.rmdir()
    assert file_of(root, Model(conn), Model(conn).captures[r.capture_id].document_ids[0]) == original
    out = edits.file_capture(conn, root, fs, r.capture_id, INSTALLATION, AT)
    assert not out.problems and (files_folder(root, INSTALLATION) / f"{DAY} Old report.txt").read_text(encoding="utf-8") == "Made-up report"
    assert original.exists()  # copied, never moved from outside the data root
    assert c.id  # the sample's attachment capture is still there


# ---- the source words in search and Find files (decision 631) ----
def test_saved_and_linked_are_the_source_words(env):
    assert finder.SOURCE_WORDS["saved"] == finder.SOURCE_WORDS["copy"] == "Saved file"
    assert finder.SOURCE_WORDS["linked"] == finder.SOURCE_WORDS["original"] == "Linked file"
    assert "Saved file" in search.GROUPS and "Saved copy" not in search.GROUPS
    conn, root, _ = env
    scope, words = search.read("from:linked procedure", Model(conn), AT.date())
    assert scope.sources == {"Linked file"} and words == "procedure"
    assert search.read("from:saved curve", Model(conn), AT.date())[0].sources == {"Saved file"}
