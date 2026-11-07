"""The Tagged labels view, a tagged label's page commands, and the owner's own changes on an item (release 5.79, the tagged
labels plan, decisions 367, 371, 376 and 379). Functions of the browse window ``w``, its tree and its model, as a new list
view is (``DocRepo/CLAUDE.md``); ``BrowseWindow`` only calls them.

- **The view** lists the glossary: each label with its description quiet after it (the list rows' recipe), its aliases
  and how many items mention it. It draws at most ``ROWS``, as 20,000 rows took 8 s, and a bigger glossary starts with
  **Mentioned only** ticked; search finds the rest.
- **A label's page** has Edit…, Import… and Export….
- **On a capture's or document's page,** × removes a label from that item (with Undo), Add back undoes it, and Add puts one
  on by hand, from the glossary or a new one added to it first. Each rewrites the Task.md of the item's tasks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import unquote

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QInputDialog

from docrepo import edits, tagged
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.safe_fs import WriteRefused
from docrepo.ui.dialogs import TaggedLabelDialog
from docrepo.ui.look import LOOK
from docrepo.ui.tree_view import Line

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: The most rows the view draws: 20,000 took 8 s to draw. Search finds the rest.
ROWS = 2000
LINKS = ("taggedrm", "taggedback", "taggedadd")


# ---- the view ----
def rows(w: BrowseWindow) -> tuple[list[tagged.Label], dict[int, int], int]:
    """The labels the view lists, their counts, and how many more there are. A glossary bigger than the view draws starts
    with Mentioned only ticked."""
    m = w.model()
    tg = m.tagged
    counts = tagged.counts(m) if tg else {}
    if w.tagged_mentioned is None:
        w.tagged_mentioned = len(tg.labels) > ROWS
    labels = [lb for lb in tg.sorted_labels() if not w.tagged_mentioned or counts.get(lb.id)]
    return labels[:ROWS], counts, max(0, len(labels) - ROWS)


def first(w: BrowseWindow) -> tuple[str, str] | None:
    """The first label the view lists, to select when it opens."""
    labels = rows(w)[0][:1]
    return ("tagged", labels[0].key) if labels else None


def view(w: BrowseWindow) -> None:
    """The Tagged labels view (decision 379's list)."""
    tg = w.model().tagged
    labels, counts, more = rows(w)
    mentioned = sum(1 for n in counts.values() if n)
    w._set_head("Tagged labels", "Plant tags found in every capture, email, document and notes page, however their parts are joined. "
                "The glossary is in docs.db.", f"{len(tg.labels):,} in the glossary, {mentioned:,} mentioned" if tg else "")
    if tg:
        w._check("Mentioned only", bool(w.tagged_mentioned), lambda on: set_mentioned(w, on), "Only the labels something mentions")
    w._button("Import…", lambda: import_glossary(w))
    w._button("Export…", lambda: export(w), enabled=bool(tg), tip="Write the glossary as a CSV to Exports in the data root")
    w._button("Add…", lambda: add(w), tip="Add a tagged label by hand")
    w.tree.set_columns(["Tagged label", "Aliases", "Items"], [0, 180, 60])
    if not tg:
        w.tree.add_row(None, None, ['<span class="sub">No glossary yet. Import the plant&#8217;s tag list from Excel or CSV: a tagged '
                                    'label, its description and its aliases in each row.</span>'], selectable=False)
        return
    for lb in labels:
        # The row recipe (the list rows review): the label, its description quiet after it, as People's aliases are.
        cell = (esc(lb.label) + (f' <span class="sub">{esc(lb.description)}</span>' if lb.description else "") if LOOK.classic
                else Line(lb.label, icon="tagged", icon_tip="Tagged label", context=lb.description))
        w.tree.add_row(None, ("tagged", lb.key), [cell, esc("; ".join(lb.aliases)), f'<p align="right">{counts.get(lb.id, 0)}</p>'],
                       tip=f"{lb.label}: {lb.description}" if lb.description else lb.label)
    if more:
        w.tree.add_row(None, None, [f'<span class="sub">And {more:,} more. Search finds any of them, however it&#8217;s typed.</span>'],
                       selectable=False)
    if not labels:
        w.tree.add_row(None, None, [f'<span class="sub">Nothing mentions any of the glossary&#8217;s {len(tg.labels):,} labels yet. '
                                    'Untick Mentioned only to list them.</span>'], selectable=False)


def set_mentioned(w: BrowseWindow, on: bool) -> None:
    w.tagged_mentioned = on
    w.render_list()


# ---- a label's page ----
def actions(w: BrowseWindow, key: str) -> None:
    w._action("Edit…", lambda: edit(w, key), "Change its description and aliases", icon_name="edit")
    w._action("Import…", lambda: import_glossary(w), "Import the glossary from Excel or CSV")
    w._action("Export…", lambda: export(w), "Write the glossary as a CSV to Exports in the data root")


def write_pages(w: BrowseWindow, out: edits.Outcome, task_ids: list[str] | None = None) -> None:
    """Write Task.md again, whose Tagged labels row a change to the glossary or an item's choices changes."""
    from docrepo.pages import write_pages as write

    now = w._now()
    try:
        write(Model(w.conn), w.ctx.data_root, w.ctx.fs, now.date(), now, task_ids)
    except OSError as e:
        out.problems.append(f"The generated pages weren't all updated ({type(e).__name__}).")


def import_glossary(w: BrowseWindow) -> None:
    """Import the glossary from Excel or CSV (decision 371)."""
    from docrepo.ui.tagged_import_dialog import TaggedImportDialog

    dialog = TaggedImportDialog(w, w.ctx)
    if not (w.run_dialog(dialog) and dialog.outcome):
        return
    out = edits.Outcome(dialog.outcome)
    write_pages(w, out)
    w.refresh(render=False)
    w.view = "tagged"
    w.tagged_mentioned = None  # the glossary's size may have changed
    w.sel = first(w)
    w.render_all()
    w.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))


def export(w: BrowseWindow) -> None:
    """Write the glossary as a CSV to Exports in the data root, and copy it (decision 371)."""
    from docrepo import tagged_import

    text = tagged_import.export_csv(w.conn)
    n = text.count("\n") - 1
    QGuiApplication.clipboard().setText(text)
    try:
        path = tagged_import.save_export(w.ctx.fs, w.ctx.data_root, text, w._now())
    except (OSError, WriteRefused) as e:
        w.say(f"The export couldn't be saved in Exports ({type(e).__name__}), but it's copied: {n} tagged labels.", error=True)
        return
    w.say(f"Saved {n} tagged labels as Exports\\{path.name} in the data root, and copied them.")


def alias_check(w: BrowseWindow, label_id: int | None):
    return lambda _label, aliases: tagged.check_aliases(tagged.read_labels(w.conn), label_id, aliases)


def edit(w: BrowseWindow, key: str) -> None:
    """A tagged label's description and aliases (decision 379)."""
    lb = w.model().tagged.by_key[key]
    dialog = TaggedLabelDialog(w, lb.label, lb.description, list(lb.aliases), check_aliases=alias_check(w, lb.id))
    if not w.run_dialog(dialog):
        return
    _, description, aliases = dialog.values()

    def change() -> edits.Outcome:
        tagged.edit_label(w.conn, lb.id, description, aliases)
        out = edits.Outcome(f"Saved {lb.label}. Everything is matched again, with its aliases.")
        write_pages(w, out)
        return out
    w._do(change, ("tagged", key))


def add(w: BrowseWindow, label: str = "") -> str | None:
    """Add a tagged label to the glossary by hand. Returns its key, or None."""
    dialog = TaggedLabelDialog(w, label, new=True, check_aliases=alias_check(w, None))
    if not w.run_dialog(dialog):
        return None
    name, description, aliases = dialog.values()

    def change() -> edits.Outcome:
        tagged.add_label(w.conn, name, w._now(), description, aliases)
        out = edits.Outcome(f"Added {name} to the glossary, and matched everything again.")
        write_pages(w, out)
        return out
    if w._do(change) is None:
        return None
    key = tagged.key_of(name)
    if w.view == "tagged":
        w.select("tagged", key, update_list=True)
    return key


# ---- the owner's own changes on a capture or document (decision 376) ----
def pick(w: BrowseWindow, names: list[str]) -> str | None:
    """A tagged label to add by hand: picked from the glossary, or typed. ``w.pick_tagged`` calls this; tests replace it."""
    value, ok = QInputDialog.getItem(w, "Add a tagged label", "A tagged label from the glossary, or a new one:", names, 0, True)
    return value if ok else None


def _item_tasks(w: BrowseWindow, kind: str, item_id: str) -> list[str]:
    m = w.model()
    return m.capture_tasks(m.captures[item_id]) if kind == "capture" else m.document_holders(item_id)


def on_link(w: BrowseWindow, kind: str, rest: str) -> None:
    """× on a chip, Add back, or Add. Kept apart from what's found, so reading the text again never undoes them."""
    if kind == "taggedadd":
        item_kind, item_id = rest.split(":", 1)
        add_to(w, item_kind, item_id)
        return
    item_kind, item_id, key = rest.split(":", 2)
    key = unquote(key)
    lb = w.model().tagged.by_key.get(key)
    if lb is None:
        return
    what = "capture" if item_kind == "capture" else "document"

    def put(choice: str | None) -> edits.Outcome:
        tagged.choose(w.conn, item_kind, item_id, key, choice, w._now())
        out = edits.Outcome("")
        write_pages(w, out, _item_tasks(w, item_kind, item_id))
        return out
    if kind == "taggedrm":
        if w._do(lambda: put("removed"), w.sel) is not None:
            w.say_undo(f"Removed {lb.label} from this {what}. It stays removed when its text is read again.",
                       lambda: w._do(lambda: put(None), w.sel))
    elif w._do(lambda: put(None), w.sel) is not None:
        w.say(f"Added {lb.label} back to this {what}.")


def add_to(w: BrowseWindow, item_kind: str, item_id: str) -> None:
    """Add a tagged label to a capture or document by hand: one from the glossary, or a new one added to it first."""
    tg = w.model().tagged
    value = w.pick_tagged([lb.label for lb in tg.sorted_labels()])
    if not value or not value.strip():
        return
    key = tagged.key_of(value)
    if key not in tg.by_key:
        if not w.confirm("Add to the glossary", f"{value.strip()} isn't in the glossary. Add it, then put it on this "
                                                f"{'capture' if item_kind == 'capture' else 'document'}?"):
            return
        key = add(w, value.strip())
        if key is None:
            return

    def change() -> edits.Outcome:
        tagged.choose(w.conn, item_kind, item_id, key, "added", w._now())
        lb = w.model().tagged.by_key.get(key)
        out = edits.Outcome(f"Added {lb.label if lb else value} by hand.")
        write_pages(w, out, _item_tasks(w, item_kind, item_id))
        return out
    w._do(change, ("capture" if item_kind == "capture" else "doc", item_id))
