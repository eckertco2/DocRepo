"""The Glossaries view and a glossary's page (release 5.171; the design workspace's ``docs/mods/glossaries-plan.md``,
decisions 804 to 806). Functions of the browse window ``w``, as a new list view is (``DocRepo/CLAUDE.md``);
``BrowseWindow`` only calls them.

- **The view**, beside Tagged labels, lists the glossaries: each with its columns, its count of rows and the day it was
  imported, and **Import…**.
- **A glossary picked** shows its rows as a table on its page, at most ``glossaries.SHOWN``, narrowed by the **Find in
  rows** box over the list: a row stays when every word typed is somewhere in it, in any column.
- **Its page's commands:** **Import again…** (a new file's rows, after a preview that counts what's added, gone and
  changed), **Rename…** and **Remove…** (after a confirm that says how many rows go).

Each change writes the glossary's page, ``Views\\Glossaries\\<name>.md``, and Contents.md's line to it (decision 806). The
Model never reads a glossary: this module asks docs.db through ``docrepo.glossaries``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLineEdit

from docrepo import edits, glossaries, pages
from docrepo.detail import esc, fields_table, none_text
from docrepo.markup import page_title
from docrepo.model import Model
from docrepo.safe_fs import WriteRefused
from docrepo.ui.tree_view import Line

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

KIND = "glossary"
#: How long after a key the picked glossary's rows are narrowed again, in ms.
TYPING_MS = 200


def _find(w: BrowseWindow) -> str:
    return getattr(w, "glossary_find", "")


def exists(w: BrowseWindow, item: str) -> bool:
    return item.isdigit() and glossaries.get(w.conn, int(item)) is not None


def first(w: BrowseWindow) -> tuple[str, str] | None:
    listed = glossaries.all_glossaries(w.conn)
    return (KIND, str(listed[0].id)) if listed else None


# ---- the view ----
def view(w: BrowseWindow) -> None:
    """The Glossaries view (decision 804): the glossaries, Import… and the box that narrows the picked one's rows."""
    listed = glossaries.all_glossaries(w.conn)
    total = f"{len(listed)} glossar{'ies' if len(listed) != 1 else 'y'}, {sum(g.rows for g in listed):,} rows" if listed else ""
    w._set_head("Glossaries", "Tables you imported whole from a sheet, every column kept: equipment, instruments, acronyms. "
                "They're kept in docs.db, and each has a page in Views\\Glossaries for agents.", total)
    w._button("Import…", lambda: import_new(w), tip="Import a glossary from Excel or CSV")
    box = QLineEdit(_find(w))
    box.setPlaceholderText("Find in rows: every word, any column")
    box.setAccessibleName("Find in the picked glossary's rows")
    box.setClearButtonEnabled(True)
    box.setMinimumWidth(240)
    timer = QTimer(box, singleShot=True, interval=TYPING_MS)
    timer.timeout.connect(lambda: set_find(w, box.text()))
    box.textChanged.connect(lambda _: timer.start())
    w.glossary_box = box
    w._filter_widget(box)
    w.tree.set_columns(["Glossary", "Rows", "Tag column"], [0, 80, 140])
    if not listed:
        w.tree.add_row(None, None, ['<span class="sub">No glossaries yet. Import… a table from Excel or CSV: an equipment list, an '
                                    'instrument list, anything in rows. Every column is kept.</span>'], selectable=False)
        return
    for g in listed:
        context = f"{len(g.columns)} column{'s' if len(g.columns) != 1 else ''} · imported {g.imported[:10]}"
        cell = Line(g.name, icon="tagged", icon_tip="Glossary", context=context)
        w.tree.add_row(None, (KIND, str(g.id)), [cell, f'<p align="right">{g.rows:,}</p>', esc(g.tag_name) or none_text("None")],
                       tip=f"{g.name}: {', '.join(g.columns)}")


def set_find(w: BrowseWindow, text: str) -> None:
    """Narrow the picked glossary's rows to those with every word typed (decision 804)."""
    w.glossary_find = text
    if w.sel and w.sel[0] == KIND:
        w.render_detail()


# ---- a glossary's page ----
def actions(w: BrowseWindow, item: str) -> None:
    w._action("Import again…", lambda: import_again(w, int(item)), "Replace its rows with a new file's, after a preview", primary=True)
    w._action("Rename…", lambda: rename(w, int(item)), "Give the glossary another name", icon_name="edit")
    w._action("Remove…", lambda: remove(w, int(item)), "Remove the glossary and its rows; the backups and dump keep them")


def page(w: BrowseWindow, item: str) -> str:
    """A glossary's page: its facts, then its rows as a table, narrowed by the box (decision 804)."""
    g = glossaries.get(w.conn, int(item))
    if g is None:
        return '<p class="note">That glossary isn\'t there any more.</p>'
    find = _find(w)
    rows, total = glossaries.rows_of(w.conn, g.id, find)
    facts = [("Columns", esc(", ".join(g.columns))), ("Rows", f"{g.rows:,}"),
             ("Tag column", esc(g.tag_name) if g.tag_name else none_text("None: no column of tags")),
             ("Imported", f"{esc(g.imported[:10])}" + (f" · from {esc(g.source)}" if g.source else "")),
             ("Page", f"Views\\Glossaries\\{esc(pages.page_names(glossaries.all_glossaries(w.conn))[g.id])} in the data root")]
    if find.strip():
        said = f"{total:,} row{'s' if total != 1 else ''} with “{esc(find.strip())}”" + (f", the first {len(rows):,} shown" if total > len(rows) else "")
    else:
        said = f"{total:,} row{'s' if total != 1 else ''}" + (f", the first {len(rows):,} shown: Find in rows narrows them" if total > len(rows) else "")
    tag = g.tag_column
    head = "".join(f'<td class="k"><b>{esc(c)}</b></td>' for c in g.columns)
    body = "".join("<tr>" + "".join(f"<td valign='top'>{'<b>' if i == tag else ''}{esc(r[i] if i < len(r) else '')}{'</b>' if i == tag else ''}</td>"
                                    for i in range(len(g.columns))) + "</tr>" for r in rows)
    table = f'<table cellspacing="0" cellpadding="3"><tr>{head}</tr>{body}</table>' if rows else '<p class="note">No row has every word.</p>'
    return f'<p class="crumbs">Glossary</p>{page_title(esc(g.name))}{fields_table(facts)}<p class="sec">{said}</p>{table}'


# ---- the changes ----
def _write_pages(w: BrowseWindow, out: edits.Outcome, glossary_id: int | None, all_pages: bool = False) -> None:
    """The glossary's page, and Contents.md's line (decision 806); every Task.md too after the tag list changed."""
    now = w._now()
    try:
        if glossary_id is not None:
            pages.write_glossary_page(w.conn, w.ctx.data_root, w.ctx.fs, glossary_id)
        pages.write_pages(Model(w.conn), w.ctx.data_root, w.ctx.fs, now.date(), now, None if all_pages else [])
    except (OSError, WriteRefused) as e:
        out.problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")


def _after(w: BrowseWindow, out: edits.Outcome, sel: tuple[str, str] | None) -> None:
    w.refresh(render=False)
    w.view = "glossaries"
    w.sel = sel
    w.render_all()
    w.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))


def _run_import(w: BrowseWindow, against: glossaries.Glossary | None) -> None:
    from docrepo.ui.glossary_import_dialog import GlossaryImportDialog

    dialog = GlossaryImportDialog(w, w.ctx, against)
    if not (w.run_dialog(dialog) and dialog.outcome):
        return
    out = edits.Outcome(dialog.outcome)
    _write_pages(w, out, dialog.glossary_id, all_pages=dialog.tags_changed)
    _after(w, out, (KIND, str(dialog.glossary_id)) if dialog.glossary_id is not None else None)


def import_new(w: BrowseWindow) -> None:
    """Import… (decision 804)."""
    _run_import(w, None)


def import_again(w: BrowseWindow, glossary_id: int) -> None:
    """Import again… (decision 804): the glossary's rows from a new file, after a preview that counts the changes."""
    g = glossaries.get(w.conn, glossary_id)
    if g is not None:
        _run_import(w, g)


def rename(w: BrowseWindow, glossary_id: int) -> None:
    """Rename…: the glossary's new page is written, and its old one says where it went."""
    g = glossaries.get(w.conn, glossary_id)
    if g is None:
        return
    text = w.ask_text("Rename the glossary", "Its name:", g.name)
    if text is None or glossaries.tidy_name(text) == g.name:
        return
    old_file = pages.page_names(glossaries.all_glossaries(w.conn))[g.id]
    try:
        name = glossaries.rename(w.conn, g.id, text)
    except glossaries.GlossaryError as e:
        w.say(str(e), error=True)
        return
    out = edits.Outcome(f"Renamed {g.name} to {name}.")
    _write_pages(w, out, g.id)
    new_file = pages.page_names(glossaries.all_glossaries(w.conn))[g.id]
    if new_file != old_file:
        try:
            pages.write_gone_page(w.ctx.data_root, w.ctx.fs, old_file, g.name,
                                  f"This glossary was renamed {name}: its page is [{name}]({pages.rel_link([], [new_file])}).")
        except (OSError, WriteRefused) as e:
            out.problems.append(f"The old page couldn't be updated ({type(e).__name__}).")
    _after(w, out, (KIND, str(g.id)))


def remove(w: BrowseWindow, glossary_id: int) -> None:
    """Remove…, after a confirm that says how many rows go (decision 804). Its page stays, saying it was removed."""
    g = glossaries.get(w.conn, glossary_id)
    if g is None:
        return
    if not w.confirm("Remove the glossary", f"Remove {g.name} and its {g.rows:,} rows from DocRepo? The backups and the dump "
                     "command keep the old ones. Nothing else changes: the tag list keeps any tags imported from it."):
        return
    file_name = pages.page_names(glossaries.all_glossaries(w.conn))[g.id]
    n = glossaries.remove(w.conn, g.id)
    out = edits.Outcome(f"Removed {g.name} and its {n:,} rows.")
    try:
        pages.write_gone_page(w.ctx.data_root, w.ctx.fs, file_name, g.name,
                              f"The owner removed this glossary on {w._now().date().isoformat()}. The backups of docs.db keep its rows.")
    except (OSError, WriteRefused) as e:
        out.problems.append(f"Its page couldn't be updated ({type(e).__name__}).")
    _write_pages(w, out, None)
    _after(w, out, first(w))
