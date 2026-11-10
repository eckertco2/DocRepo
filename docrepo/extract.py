"""Pulling the plain text out of a file, for search and for the differences in document versions.

Files are only ever opened to read. The text is cut at ``extracted_text_cap_chars``
(settings.json). A file DocRepo can't read is still recorded; its status says why.
This isn't Extract, the later processing into the knowledge base.
"""
from __future__ import annotations

import hashlib
import logging
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".ini"}
#: What each kind of file is read with, for the help text and SPEC.
READERS = {".pdf": "pypdf", ".docx": "python-docx", ".pptx": "zipfile", ".xlsx": "openpyxl", ".xlsm": "openpyxl", ".eml": "email"}


@dataclass(frozen=True)
class Extracted:
    """A file's text and how it went: ok, partial (cut at the limit), none (no text found or not a kind DocRepo reads) or error."""

    text: str
    status: str
    note: str = ""


@dataclass(frozen=True)
class FileInfo:
    size: int
    modified: str
    sha256: str


def file_info(path: Path) -> FileInfo:
    """A file's size, modified time and SHA-256, for noticing later that it changed."""
    stat = path.stat()
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return FileInfo(stat.st_size, datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"), digest.hexdigest())


def decode(data: bytes) -> str:
    """Text from bytes: UTF-8 (with or without a BOM), UTF-16 with a BOM, or else Windows-1252."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def _docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts).strip()


# ---- .pptx, read with the standard library ----
# A .pptx is a zip of XML parts. Reading it here, rather than with python-pptx, keeps out python-pptx's
# dependencies, Pillow among them, whose bundled licenses a company scan flagged.
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
#: The largest XML part read from a .pptx, so a file built to unpack to gigabytes is refused.
MAX_PART_BYTES = 64 * 1024 * 1024


def _has(z: zipfile.ZipFile, name: str) -> bool:
    try:
        z.getinfo(name)
    except KeyError:
        return False
    return True


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    """An XML part of the zip. A part with a DTD is refused: Office never writes one, and it's how entity tricks work."""
    if z.getinfo(name).file_size > MAX_PART_BYTES:
        raise ValueError(f"{name} is too big to read")
    data = z.read(name)
    if b"<!DOCTYPE" in data:
        raise ValueError(f"{name} has a DTD")
    return ET.fromstring(data)  # noqa: S314 - the document's own XML, read for its words only, with a DTD refused above; defusedxml isn't an approved package


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """A part's relationships: their IDs, each with its type and the name of the part it points to."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if not _has(z, rels_name):
        return {}
    out = {}
    for rel in _xml(z, rels_name).iter(f"{_REL}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id", "")] = (rel.get("Type", ""), full)
    return out


def _text_body(body: ET.Element | None) -> str:
    """A text box's text: a line for each paragraph, and a line break inside one kept as a new line."""
    if body is None:
        return ""
    lines = []
    for paragraph in body.iter(f"{_A}p"):
        bits = [(el.text or "") if el.tag == f"{_A}t" else "\n" for el in paragraph.iter() if el.tag in (f"{_A}t", f"{_A}br")]
        lines.append("".join(bits))
    return "\n".join(lines)


def _shapes(tree: ET.Element, parts: list[str]) -> None:
    """The text of a slide's shapes, in order: text boxes, tables row by row, and the shapes inside groups."""
    for shape in tree:
        if shape.tag == f"{_P}sp":
            parts.append(_text_body(shape.find(f"{_P}txBody")))
        elif shape.tag == f"{_P}grpSp":
            _shapes(shape, parts)
        elif shape.tag == f"{_P}graphicFrame":
            for row in shape.iter(f"{_A}tr"):
                parts.append(" | ".join(_text_body(cell.find(f"{_A}txBody")).strip() for cell in row.iter(f"{_A}tc")))


def _notes(z: zipfile.ZipFile, part: str) -> str:
    """A notes page's speaker notes: the text of its body placeholder."""
    for shape in _xml(z, part).iter(f"{_P}sp"):
        placeholder = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
        if placeholder is not None and placeholder.get("type") == "body":
            return _text_body(shape.find(f"{_P}txBody")).strip()
    return ""


def _pptx_slides(path: Path) -> list[tuple[int, list[str]]]:
    """Each slide in the deck's order: its number and its lines of text, its speaker notes last as "Notes: …"."""
    out: list[tuple[int, list[str]]] = []
    with zipfile.ZipFile(path) as z:
        main = next((t for kind, t in _rels(z, "").values() if kind.endswith("/officeDocument")), "ppt/presentation.xml")
        slides = _rels(z, main)
        for number, slide_id in enumerate(_xml(z, main).iter(f"{_P}sldId"), 1):
            part = slides.get(slide_id.get(f"{_R}id", ""), ("", ""))[1]
            if not _has(z, part):
                continue
            parts: list[str] = []
            tree = _xml(z, part).find(f"{_P}cSld/{_P}spTree")
            if tree is not None:
                _shapes(tree, parts)
            notes = next((t for kind, t in _rels(z, part).values() if kind.endswith("/notesSlide") and _has(z, t)), None)
            if notes and (text := _notes(z, notes)):
                parts.append(f"Notes: {text}")
            out.append((number, [p for p in parts if p]))
    return out


def _pptx(path: Path) -> str:
    """Each slide's text in the deck's order, under "Slide 1" and so on, then its speaker notes as "Notes: …"."""
    return "\n".join(line for number, parts in _pptx_slides(path) for line in (f"Slide {number}", *parts)).strip()


def _xlsx(path: Path, cap: int) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    size = 0
    try:
        for sheet in workbook.worksheets:
            parts.append(f"Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = ["" if v is None else str(v) for v in row]
                if any(values):
                    line = " | ".join(values).rstrip(" |")
                    parts.append(line)
                    size += len(line) + 1
                if size > cap:  # big sheets stop early; the text is cut at the cap anyway
                    return "\n".join(parts)
    finally:
        workbook.close()
    return "\n".join(parts).strip()


def _eml(path: Path) -> str:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    head = [f"{k}: {message[k]}" for k in ("From", "To", "Date", "Subject") if message[k]]
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    return "\n".join(head) + "\n\n" + text.strip()


def extract_text(path: Path, cap: int) -> Extracted:
    """The plain text of a file, read-only. Never raises: a failure comes back with status "error"."""
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            text = decode(path.read_bytes())
        elif suffix == ".pdf":
            text = _pdf(path)
        elif suffix == ".docx":
            text = _docx(path)
        elif suffix == ".pptx":
            text = _pptx(path)
        elif suffix in (".xlsx", ".xlsm"):
            text = _xlsx(path, cap)
        elif suffix == ".eml":
            text = _eml(path)
        else:
            return Extracted("", "none", f"DocRepo doesn't read {suffix or 'extensionless'} files")
    except Exception as e:  # noqa: BLE001 - a bad file must never stop a save
        log.warning("Couldn't read the text of %s: %s", path.name, type(e).__name__)
        return Extracted("", "error", f"couldn't read it ({type(e).__name__})")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        note = "no text found; it may be a scanned document" if suffix == ".pdf" else "no text found"
        return Extracted("", "none", note)
    if len(text) > cap:
        return Extracted(text[:cap], "partial", f"cut at {cap} characters")
    return Extracted(text, "ok")


# ---- a file's text by section (release 5.107, consultants) ----
# What a consultant's corpus is made of: a Word document by heading, with its tables kept as tables, a deck by slide and
# a PDF by page. Nothing is cut at the text limit here: a manual is wanted whole.
#: A table longer than this is printed in parts, each a section of its own, so a reference points at a few rows.
TABLE_PART_ROWS = 40
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s+\S.{0,90}$")


@dataclass(frozen=True)
class Section:
    """One part of a file: where it is (``s4``, ``slide-7``, ``page-12``), its heading and depth, its text as Markdown,
    and how many tables are in it."""

    anchor: str
    heading: str
    level: int
    text: str
    tables: int = 0


def _w_text(element: ET.Element) -> str:
    """The words of a Word paragraph, read from its XML: tabs and line breaks as spaces. The words of a text box, of a
    table inside it, of a field's code and of tracked deletions are left out."""
    bits: list[str] = []

    def walk(el: ET.Element) -> None:
        for child in el:
            if child.tag == f"{_W}t":
                bits.append(child.text or "")
            elif child.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
                bits.append(" ")
            elif child.tag == f"{_W}noBreakHyphen":
                bits.append("-")
            elif isinstance(child.tag, str) and not child.tag.endswith(("}txbxContent", "}Fallback", "}instrText", "}delText", "}del", "}tbl")):
                walk(child)

    walk(element)
    return " ".join("".join(bits).split())


def _w_boxes(element: ET.Element) -> list[str]:
    """The words of the text boxes anchored in a paragraph, each paragraph of a box a line. A box Word wrote twice (for
    older versions) is read once."""
    out: list[str] = []
    for box in element.iter(f"{_W}txbxContent"):
        for p in box.iter(f"{_W}p"):
            text = _w_text(p)
            if text and text not in out:
                out.append(text)
    return out


def _w_children(element: ET.Element, tag: str) -> list[ET.Element]:
    """A table's rows, or a row's cells: its own, through any wrapper Word puts round them (a content control), and not
    those of a table inside it."""
    out: list[ET.Element] = []
    for child in element:
        if child.tag == tag:
            out.append(child)
        elif isinstance(child.tag, str) and child.tag not in (f"{_W}tbl", f"{_W}tc", f"{_W}tr"):
            out += _w_children(child, tag)
    return out


def _w_rows(tbl: ET.Element) -> list[list[str]]:
    """A Word table's rows, each cell's paragraphs joined with " / ", and a table inside a cell as its cells in brackets."""
    rows = []
    for tr in _w_children(tbl, f"{_W}tr"):
        cells = []
        for tc in _w_children(tr, f"{_W}tc"):
            parts = []
            for child in tc.iter(f"{_W}p", f"{_W}tbl"):
                if _w_inside(tc, child):
                    continue
                if child.tag == f"{_W}p":
                    parts += [t for t in (_w_text(child), *_w_boxes(child)) if t]
                else:
                    parts.append("[" + "; ".join(", ".join(c for c in row if c) for row in _w_rows(child)) + "]")
            cells.append(" / ".join(parts))
        if any(cells):
            rows.append(cells)
    return rows


def _w_inside(cell: ET.Element, element: ET.Element) -> bool:
    """True for a paragraph or table that sits inside a table or a text box within the cell, so it's read with that."""
    parent = element.getparent()
    while parent is not None and parent is not cell:
        if parent.tag in (f"{_W}tbl", f"{_W}txbxContent"):
            return True
        parent = parent.getparent()
    return False


def _md_table(rows: list[list[str]], head: list[str] | None = None) -> list[str]:
    """Rows as a Markdown table, the first row (or ``head``) its header."""
    first, rest = (head, rows) if head is not None else (rows[0], rows[1:])
    width = max(len(r) for r in (first, *rest))

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells + [""] * (width - len(cells))) + " |"

    return [line(first), "|" + "---|" * width, *[line(r) for r in rest]]


def _heading_level(paragraph) -> int:
    """A Word paragraph's heading level by its style, or the style that one is based on: Title and Heading 1 are 1.
    0 when it isn't a heading."""
    style, depth = paragraph.style, 0
    while style is not None and depth < 6:
        name = (style.name or "").strip().lower()
        if name == "title":
            return 1
        found = re.match(r"heading\s*(\d)$", name)
        if found:
            return max(1, int(found.group(1)))
        style, depth = style.base_style, depth + 1
    return 0


def _looks_like_heading(paragraph, text: str) -> int:
    """For a document with no heading styles: a short line numbered like a heading ("3.2 Start-up"), or one all in bold.
    Its level, or 0."""
    if not text or len(text) > 100 or text.endswith((".", ":", ";", ",")):
        return 0
    if _NUMBERED.match(text):
        return min(6, text.split()[0].rstrip(".").count(".") + 1)
    runs = [r for r in paragraph.runs if r.text.strip()]
    return 2 if runs and all(r.bold for r in runs) else 0


def _docx_sections(path: Path) -> list[Section]:
    import docx
    from docx.table import Table

    document = docx.Document(str(path))
    blocks = list(document.iter_inner_content())
    styled = any(not isinstance(b, Table) and _heading_level(b) for b in blocks)
    out: list[Section] = []
    heading, level = "", 1
    lines: list[str] = []
    tables = 0
    resume = ""

    def close() -> None:
        nonlocal lines, tables
        if heading or any(line.strip() for line in lines):
            out.append(Section(f"s{len(out) + 1}", heading, level, "\n".join(lines).strip(), tables))
        lines, tables = [], 0

    for block in blocks:
        if isinstance(block, Table):
            rows = _w_rows(block._tbl)
            if not rows:
                continue
            if len(rows) <= TABLE_PART_ROWS + 1:
                lines += ["", *_md_table(rows), ""]
                tables += 1
                continue
            # A long table: its rows in parts, each a section under this one, with the header row again.
            close()
            parent, parent_level, body = heading, level, rows[1:]
            for start in range(0, len(body), TABLE_PART_ROWS):
                part = body[start:start + TABLE_PART_ROWS]
                heading, level = f"{parent or 'Table'}: table rows {start + 1} to {start + len(part)}", min(6, parent_level + 1)
                lines, tables = _md_table(part, rows[0]), 1
                close()
            heading, level, resume = "", parent_level, parent
            continue
        text = _w_text(block._p)
        boxes = _w_boxes(block._p)
        found = _heading_level(block) if styled else _looks_like_heading(block, text)
        if found and text:
            close()
            heading, level, resume = text, found, ""
            text = ""
        if (text or boxes) and resume and not heading:  # what follows a long table is still its section
            heading = f"{resume} (continued)"
        if text:
            lines.append(text)
        lines += boxes
    close()
    return out


def _pdf_sections(path: Path, layout: bool = False) -> list[Section]:
    """A PDF by page, each page headed by the bookmarks that start on it. ``layout`` keeps the page's columns where they
    are, which can keep a table's rows together."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    titles: dict[int, list[str]] = {}

    def walk(items: list) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                number = reader.get_destination_page_number(item)
            except Exception:  # noqa: BLE001, S112 - a bookmark that leads nowhere is skipped
                continue
            if number is not None and item.title:
                titles.setdefault(number, []).append(" ".join(str(item.title).split()))

    try:
        walk(reader.outline)
    except Exception as e:  # noqa: BLE001 - bookmarks are a help, never needed
        log.warning("Couldn't read the bookmarks of %s: %s", path.name, type(e).__name__)
    out = []
    for i, page in enumerate(reader.pages):
        text = ""
        if layout:
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except Exception as e:  # noqa: BLE001 - the plain reading below is the fallback
                log.warning("Couldn't read page %d of %s with its layout: %s", i + 1, path.name, type(e).__name__)
        if not text.strip():
            text = page.extract_text() or ""
        names = "; ".join(titles.get(i, [])[:4])
        out.append(Section(f"page-{i + 1}", f"Page {i + 1}" + (f": {names}" if names else ""), 1, text.strip()))
    return out


def sections_of(path: Path, pdf_layout: bool = False) -> list[Section]:
    """A file's text by section, read-only. It raises what the reader raises. A kind with no sections of its own comes
    back as one section, and a kind DocRepo doesn't read as none."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx_sections(path)
    if suffix == ".pptx":
        return [Section(f"slide-{n}", f"Slide {n}" + (f": {parts[0].splitlines()[0][:100]}" if parts else ""), 1, "\n".join(parts))
                for n, parts in _pptx_slides(path)]
    if suffix == ".pdf":
        return _pdf_sections(path, pdf_layout)
    if suffix in TEXT_SUFFIXES:
        text = decode(path.read_bytes())
    elif suffix in (".xlsx", ".xlsm"):
        text = _xlsx(path, 10**9)
    elif suffix == ".eml":
        text = _eml(path)
    else:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return [Section("s1", "", 1, text)] if text else []


def to_unc(path: str) -> str:
    """A path on a mapped network drive (H:\\x) as its network path (\\\\server\\share\\x), so it survives drive-letter changes.

    Asks Windows which share the letter is mapped to; nothing is sent over the network.
    """
    drive = os.path.splitdrive(path)[0]
    if os.name != "nt" or len(drive) != 2 or drive[1] != ":":
        return path
    import ctypes
    from ctypes import wintypes

    if ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") != 4:  # DRIVE_REMOTE
        return path
    buffer = ctypes.create_unicode_buffer(1024)
    length = wintypes.DWORD(len(buffer))
    if ctypes.windll.mpr.WNetGetConnectionW(drive, buffer, ctypes.byref(length)) != 0:
        return path
    return buffer.value.rstrip("\\") + path[2:]
