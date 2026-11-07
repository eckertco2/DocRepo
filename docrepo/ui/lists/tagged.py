"""The Tagged labels view, a tagged label's page commands, and the owner's own changes on an item (release 5.79, the tagged
labels plan, decisions 367, 371, 376 and 379). Functions of the browse window ``w``, its tree and its model, as a new list
view is (``DocRepo/CLAUDE.md``); ``BrowseWindow`` only calls them.

- **The view** lists the glossary: each label with its description quiet after it (the list rows' recipe), its aliases
  and how many items mention it. It draws at most ``ROWS``, as 20,000 rows took 8 s, and a bigger glossary starts with
  **Mentioned only** ticked; search finds the rest.
- **A label's page** has Edit…, Import… and Export….
- **On a capture's or document's page,** × removes a label from that item (with Undo), Add back undoes it, and Add puts one
  on by hand, from the glossary or a new one added to it first. Each rewrites the Task.md of the item's tasks.
- **Suggested** (release 5.80, item 107, decision 374): the new tagged labels the tag patterns found, above the glossary,
  the most mentioned first, each with the pattern that found it and where it's seen. A suggested label's page has **Add
  to glossary…** (with a description), **Same as…** (an alias of another label, its mentions moved there) and **Not a
  tag** (removed everywhere and put on Never a tag in settings.json, with Undo). **Patterns…** opens Settings' Tagged
  labels section.
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
from docrepo.ui.tree_view import Line, group_ground

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow

#: The most rows the view draws: 20,000 took 8 s to draw. Search finds the rest.
ROWS = 2000
LINKS = ("taggedrm", "taggedback", "taggedadd")


# ---- the view ----
def rows(w: BrowseWindow) -> tuple[list[tagged.Label], dict[int, int], int]:
    """The glossary's labels the view lists, their counts, and how many more there are. A glossary bigger than the view
    draws starts with Mentioned only ticked."""
    m = w.model()
    tg = m.tagged
    counts = tagged.counts(m) if tg else {}
    glossary = tg.glossary()
    if w.tagged_mentioned is None:
        w.tagged_mentioned = len(glossary) > ROWS
    labels = [lb for lb in glossary if not w.tagged_mentioned or counts.get(lb.id)]
    return labels[:ROWS], counts, max(0, len(labels) - ROWS)


def first(w: BrowseWindow) -> tuple[str, str] | None:
    """The first label the view lists, to select when it opens: the most mentioned suggestion, else the glossary's first."""
    m = w.model()
    sug = tagged.suggestions(m)[:1] if m.tagged else []
    if sug:
        return "tagged", sug[0].label.key
    labels = rows(w)[0][:1]
    return ("tagged", labels[0].key) if labels else None


def _places(w: BrowseWindow, s: tagged.Suggestion) -> str:
    """Where a suggestion is seen, in a few words: its top-level tasks, the most first."""
    m = w.model()
    names = [m.task(t).title for t in s.places[:2]]
    more = len(s.places) - len(names) + (1 if s.unfiled else 0)
    seen = ", ".join(names) or ("not filed yet" if s.unfiled else "")
    return f"in {seen}" + (f" and {more} more" if more and names else "")


def view(w: BrowseWindow) -> None:
    """The Tagged labels view (decision 379's list), with Suggested first (decision 374)."""
    m = w.model()
    tg = m.tagged
    labels, counts, more = rows(w)
    sug = tagged.suggestions(m) if tg else []
    mentioned = sum(1 for lb in tg.glossary() if counts.get(lb.id))
    total = f"{len(tg.glossary()):,} in the glossary, {mentioned:,} mentioned" + (f", {len(sug):,} suggested" if sug else "")
    w._set_head("Tagged labels", "Plant tags found in every capture, email, document and notes page, however their parts are joined. "
                "The glossary is in docs.db.", total if tg else "")
    if tg:
        w._check("Mentioned only", bool(w.tagged_mentioned), lambda on: set_mentioned(w, on), "Only the labels something mentions")
    w._button("Import…", lambda: import_glossary(w))
    w._button("Export…", lambda: export(w), enabled=bool(tg.glossary()), tip="Write the glossary as a CSV to Exports in the data root")
    w._button("Add…", lambda: add(w), tip="Add a tagged label by hand")
    w._button("Patterns…", lambda: show_patterns(w), tip="Tag patterns, Never a tag and the tester, in Settings")
    w.tree.set_columns(["Tagged label", "Aliases", "Items"], [0, 180, 60])
    if not tg:
        w.tree.add_row(None, None, ['<span class="sub">No glossary yet. Import the plant&#8217;s tag list from Excel or CSV: a tagged '
                                    'label, its description and its aliases in each row. Or add tag patterns in Settings, and the tags '
                                    'they find are suggested here.</span>'], selectable=False)
        return
    if sug:  # release 5.80: what the patterns found, waiting for the owner (decision 374)
        w.tree.add_row(None, None, [f'<b>Suggested</b> <span class="sub">{len(sug):,} · found by a tag pattern, not in the glossary: '
                                    'open one to add it, make it an alias or turn it down</span>'], group_ground(), selectable=False, span=True)
        for s in sug[:ROWS]:
            lb = s.label
            context = " · ".join(x for x in (f"From {lb.pattern}", _places(w, s)) if x)
            cell = (esc(lb.label) + ' <span class="new">&nbsp;new&nbsp;</span> ' + f'<span class="sub">{esc(context)}</span>' if LOOK.classic
                    else Line(lb.label, icon="tagged", icon_tip="Tagged label, suggested", chips=(("new", "new"),), context=context))
            w.tree.add_row(None, ("tagged", lb.key), [cell, "", f'<p align="right">{s.items}</p>'],
                           tip=f"{lb.label}: new, found by the {lb.pattern} pattern")
        if len(sug) > ROWS:
            w.tree.add_row(None, None, [f'<span class="sub">And {len(sug) - ROWS:,} more suggested.</span>'], selectable=False)
        w.tree.add_row(None, None, [f'<b>Glossary</b> <span class="sub">{len(tg.glossary()):,}</span>'], group_ground(), selectable=False, span=True)
    for lb in labels:
        # The row recipe (the list rows review): the label, its description quiet after it, as People's aliases are.
        cell = (esc(lb.label) + (f' <span class="sub">{esc(lb.description)}</span>' if lb.description else "") if LOOK.classic
                else Line(lb.label, icon="tagged", icon_tip="Tagged label", context=lb.description))
        w.tree.add_row(None, ("tagged", lb.key), [cell, esc("; ".join(lb.aliases)), f'<p align="right">{counts.get(lb.id, 0)}</p>'],
                       tip=f"{lb.label}: {lb.description}" if lb.description else lb.label)
    if more:
        w.tree.add_row(None, None, [f'<span class="sub">And {more:,} more. Search finds any of them, however it&#8217;s typed.</span>'],
                       selectable=False)
    if not labels and tg.glossary():
        w.tree.add_row(None, None, [f'<span class="sub">Nothing mentions any of the glossary&#8217;s {len(tg.glossary()):,} labels yet. '
                                    'Untick Mentioned only to list them.</span>'], selectable=False)
    elif not labels:
        w.tree.add_row(None, None, ['<span class="sub">No glossary yet: Add to glossary on a suggestion, or Import… the plant&#8217;s '
                                    'tag list.</span>'], selectable=False)


def set_mentioned(w: BrowseWindow, on: bool) -> None:
    w.tagged_mentioned = on
    w.render_list()


# ---- a label's page ----
def actions(w: BrowseWindow, key: str) -> None:
    lb = w.model().tagged.by_key.get(key)
    if lb is not None and lb.status == "suggested":  # release 5.80, item 107
        w._action("Add to glossary…", lambda: accept(w, key), "Make it an ordinary tagged label, with a description", primary=True)
        w._action("Same as…", lambda: same_as(w, key), "Make it an alias of another tagged label, and move its mentions there")
        w._action("Not a tag", lambda: not_a_tag(w, key), "Remove it everywhere and put it on Never a tag, so no pattern suggests it again")
        w._action("Patterns…", lambda: show_patterns(w), "Tag patterns, Never a tag and the tester, in Settings")
        return
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


# ---- a suggested label (release 5.80, item 107, decisions 374 and 375) ----
def choose_label(w: BrowseWindow, names: list[str], label: str) -> str | None:
    """The glossary label a suggestion is the same as: picked or typed. Tests replace it."""
    value, ok = QInputDialog.getItem(w, f"{label} is the same as", f"{label} becomes an alias of this tagged label, and its mentions "
                                     "move there:", names, 0, True)
    return value if ok else None


def accept(w: BrowseWindow, key: str) -> None:
    """Add to glossary: a suggestion becomes an ordinary tagged label, with a description and any aliases."""
    lb = w.model().tagged.by_key[key]
    dialog = TaggedLabelDialog(w, lb.label, "", [], check_aliases=alias_check(w, lb.id), title=f"Add {lb.label} to the glossary")
    if not w.run_dialog(dialog):
        return
    _, description, aliases = dialog.values()

    def change() -> edits.Outcome:
        tagged.accept(w.conn, key, description, aliases)
        out = edits.Outcome(f"{lb.label} is in the glossary now: it's found however it's written, and no longer marked new.")
        write_pages(w, out)
        return out
    w._do(change, ("tagged", key))
    if w.view == "tagged":
        w.select("tagged", key, update_list=True)


def same_as(w: BrowseWindow, key: str) -> None:
    """Same as…: a suggestion becomes an alias of a glossary label, and its mentions move there."""
    tg = w.model().tagged
    lb = tg.by_key[key]
    glossary = tg.glossary()
    if not glossary:
        w.say("There's no glossary label to make it an alias of yet. Import the glossary, or Add to glossary.", error=True)
        return
    value = choose_label(w, [x.label for x in glossary], lb.label)
    if not value or not value.strip():
        return
    target = next((x for x in glossary if x.key == tagged.key_of(value)), None) or tagged.label_named(
        tagged.Tagged({x.id: x for x in glossary}), value)
    if target is None:
        w.say(f"{value.strip()} isn't in the glossary. Pick a tagged label from it.", error=True)
        return

    def change() -> edits.Outcome:
        tagged.same_as(w.conn, key, target.id)
        out = edits.Outcome(f"{lb.label} is an alias of {target.label} now, and its mentions moved there.")
        write_pages(w, out)
        return out
    if w._do(change, ("tagged", target.key)) is not None and w.view == "tagged":
        w.select("tagged", target.key, update_list=True)


def not_a_tag(w: BrowseWindow, key: str) -> None:
    """Not a tag: removed everywhere, and put on Never a tag in settings.json, so no pattern suggests it again. Undo takes
    it off the list, and the patterns find it again."""
    from docrepo.ui.settings_view import save_never

    lb = w.model().tagged.by_key[key]
    before = list(w.ctx.settings.tagged_never)

    def change() -> edits.Outcome:
        tagged.forget(w.conn, key)
        save_never(w.ctx, [*before, lb.label])
        return edits.Outcome("")
    if w._do(change) is None:
        return
    w.sel = first(w) if w.view == "tagged" else w.sel
    w.render_all()

    def undo() -> None:
        w._do(lambda: (save_never(w.ctx, before), edits.Outcome(f"{lb.label} is off Never a tag, and found again."))[1])
    w.say_undo(f"{lb.label} is on Never a tag: removed everywhere, and no pattern suggests it again.", undo)


def show_patterns(w: BrowseWindow) -> None:
    """Settings' Tagged labels section: the patterns, Never a tag and the tester."""
    w.set_view("settings")
    w.settings_view.show_tagged()


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
