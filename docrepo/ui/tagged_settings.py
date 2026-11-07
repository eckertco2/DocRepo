"""Settings' Tagged labels section (release 5.80; the tagged labels plan, items 106 and 107, decisions 372, 373 and 375), a
form of its own as new forms are (``DocRepo/CLAUDE.md``):

- **Tag patterns:** a row for each, its name, its mask and Allow a space (off by default), with a made-up example of
  what the mask means, or why it can't be used, worked out as it's typed. Add a pattern, or start from a made-up
  example: DocRepo ships none, as they're the plant's own conventions.
- **Never a tag:** whole tags, or starts with *, separated by commas, that no pattern makes a tagged label.
- **Try it** (decision 373): a box to paste text into, which marks what's found as it's typed, coloured by how: a
  glossary label, an alias, or new from a named pattern, with what's on Never a tag struck through.
- **Try on everything:** the patterns as they stand in the form, run over everything DocRepo holds from the kept words,
  before they're saved, the most frequent new labels first, each with Not a tag, which puts it on Never a tag here.

Nothing is kept until Save settings, which writes settings.json and matches everything again (``settings_view``).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from html import escape as esc
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docrepo import tagged
from docrepo import tagged_masks as masks
from docrepo.ui import tokens

#: How long after a key the tester marks the text again, in ms, so pasting a long text doesn't lag.
TYPING_MS = 150
#: The most new labels Try on everything lists; the rest are counted.
TRIED_SHOWN = 30
#: How each kind of hit is marked in the tester: a token for its background, and its words in the legend.
HOW = {
    "label": ("success_bg", "glossary label"), "alias": ("info_bg", "alias"), "pair": ("info_bg", "alias"),
    "word": ("info_bg", "word alias"), "new": ("caution_bg", "new, from a pattern"), "never": ("", "Never a tag"),
}


def mono() -> QFont:
    font = QFont("Cascadia Mono")
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def marked(text: str, hits: list[tagged.Hit]) -> str:
    """The tester's text as HTML, each hit marked in its colour (``HOW``), and one on Never a tag struck through."""
    out, at = [], 0
    for h in hits:
        if h.start < at:
            continue
        out.append(esc(text[at:h.start]))
        part = esc(text[h.start:h.end])
        if h.how == "never":
            out.append(f'<span style="color:{tokens.colour("text2")}; text-decoration:line-through">{part}</span>')
        else:
            line = "; text-decoration:underline" if h.how == "word" else ""
            out.append(f'<span style="background-color:{tokens.colour(HOW[h.how][0])}{line}">{part}</span>')
        at = h.end
    out.append(esc(text[at:]))
    return "".join(out).replace("\n", "<br>")


def legend() -> str:
    swatch = lambda key, words: f'<span style="background-color:{tokens.colour(key)}">&nbsp;{words}&nbsp;</span>'  # noqa: E731
    return " ".join([swatch("success_bg", "glossary label"), swatch("info_bg", "alias"),
                     f'<span style="background-color:{tokens.colour("info_bg")}; text-decoration:underline">&nbsp;word alias&nbsp;</span>',
                     swatch("caution_bg", "new, from a pattern"),
                     f'<span style="color:{tokens.colour("text2")}; text-decoration:line-through">Never a tag</span>'])


def found_line(hits: list[tagged.Hit], names: dict[int, str]) -> str:
    """What the tester found, each once: a label's name, and a new one with its pattern's name."""
    seen: dict[str, str] = {}
    for h in hits:
        if h.how == "never":
            continue
        if h.how == "new":
            seen.setdefault(h.key, f"{esc(h.spelled)} <span style='color:{tokens.colour('text2')}'>(new, {esc(h.pattern)})</span>")
        elif h.label in names:
            seen.setdefault(tagged.key_of(names[h.label]), esc(names[h.label]))
    return "Found: " + ", ".join(seen.values()) if seen else "Nothing found."


def split_never(text: str) -> list[str]:
    """Never a tag as typed: separated by commas, semicolons or new lines."""
    return [x.strip() for x in re.split(r"[,;\n]", text) if x.strip()]


class TaggedSettings(QWidget):
    """The section. ``glossary`` gives the glossary's labels for the tester; ``try_all`` runs Try on everything with the
    patterns and Never a tag as they stand (``tagged.try_everything``)."""

    def __init__(self, glossary: Callable[[], list[tagged.Label]],
                 try_all: Callable[[list[masks.Pattern], list[str]], tuple[list[tagged.Tried], int]]) -> None:
        super().__init__()
        self.glossary, self.try_all = glossary, try_all
        self._labels: list[tagged.Label] | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(8)
        self._build_patterns(lay)
        self._build_never(lay)
        self._build_tester(lay)
        self._timer = QTimer(self, singleShot=True, interval=TYPING_MS)
        self._timer.timeout.connect(self.refresh_now)

    # ---- the patterns ----
    def _build_patterns(self, lay: QVBoxLayout) -> None:
        lay.addWidget(QLabel("Tag patterns", objectName="fieldLabel"))
        intro = QLabel("A glossary label is found however its parts are joined, with nothing to set here. A pattern finds tags "
                       "that aren't in the glossary yet: each one found is put on what mentions it at once, marked new, and waits "
                       "under Suggested in the Tagged labels view. They're your plant's conventions, kept in settings.json in the "
                       "data root.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        box = QWidget()
        self.grid = QGridLayout(box)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        for col, words in enumerate(("Name", "Mask", "", "Means")):
            self.grid.addWidget(QLabel(words, objectName="hint"), 0, col)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 2)
        self.none = QLabel("No patterns. DocRepo ships none: they're your plant's conventions. Start from an example below.", objectName="hint")
        self.grid.addWidget(self.none, 1, 0, 1, 5)
        lay.addWidget(box)
        self.rows: list[tuple[QLineEdit, QLineEdit, QCheckBox, QLabel, QToolButton]] = []
        self._grid_row = 1  # the grid's last row used (1 is No patterns): a removed row's place isn't used again
        add = QPushButton("Add a pattern")
        add.clicked.connect(lambda: self.add_row("", "", False, focus="mask"))
        examples = QHBoxLayout()
        examples.setSpacing(6)
        examples.addWidget(add)
        examples.addWidget(QLabel("Start from an example:", objectName="hint"))
        self.example_buttons: list[QToolButton] = []
        for mask, means in masks.EXAMPLES:
            b = QToolButton(text=mask)
            b.setFont(mono())
            b.setToolTip(f"{mask}: {means}. Made up: change it to your own convention.")
            b.setAccessibleName(f"Start from the example {mask}")
            b.clicked.connect(lambda _=False, m=mask: self.add_row("", m, False, focus="name"))
            examples.addWidget(b)
            self.example_buttons.append(b)
        examples.addStretch()
        lay.addLayout(examples)
        help_ = QLabel("<code>X</code> a capital letter · <code>#</code> a digit · <code>*</code> either · <code>[ ]</code> optional · "
                       "<code>' '</code> itself, as in <code>'XV'-####</code> · a hyphen, underscore or space: where a new label's "
                       "spelling has it. Marks are never needed in the text: <code>XXX###</code> finds FIC221, FIC-221 and FIC_221, "
                       "and spells each FIC221. <b>Space</b> lets a space stand between any of its parts too, which is where false "
                       "tags such as API 610 come from.", objectName="hint")
        help_.setWordWrap(True)
        help_.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(help_)

    def add_row(self, name: str, mask: str, space: bool, focus: str = "") -> None:
        n = len(self.rows) + 1
        name_box, mask_box = QLineEdit(name), QLineEdit(mask)
        name_box.setPlaceholderText("Such as Instrument tag")
        name_box.setAccessibleName(f"Pattern {n}'s name")
        mask_box.setPlaceholderText("Such as XX[X]-####")
        mask_box.setAccessibleName(f"Pattern {n}'s mask")
        mask_box.setFont(mono())
        space_box = QCheckBox("Space")
        space_box.setChecked(space)
        space_box.setToolTip("Allow a space between any of its parts. Off by default: API 610 and for 100 are where false tags come from.")
        space_box.setAccessibleName(f"Allow a space in pattern {n}")
        means = QLabel(objectName="hint")
        means.setWordWrap(True)
        remove = QToolButton(text="×")
        remove.setAccessibleName(f"Remove pattern {n}")
        remove.setToolTip("Remove this pattern. The new labels only it found go when you save.")
        row = (name_box, mask_box, space_box, means, remove)
        remove.clicked.connect(lambda: self.remove_row(row))
        for w in (name_box, mask_box):
            w.textChanged.connect(self.changed)
        space_box.toggled.connect(self.changed)
        self.rows.append(row)
        self._grid_row += 1
        for col, w in enumerate(row):
            self.grid.addWidget(w, self._grid_row, col)
        self.none.setVisible(not self.rows)
        self.show_means(row)
        if focus:
            (name_box if focus == "name" else mask_box).setFocus()
        self.changed()

    def remove_row(self, row) -> None:
        self.rows.remove(row)
        for w in row:
            w.deleteLater()
        self.none.setVisible(not self.rows)
        self.changed()

    def show_means(self, row) -> None:
        mask = row[1].text().strip()
        if not mask:
            row[3].setText("Type a mask")
            return
        try:
            row[3].setText(f"Such as {masks.examples(mask)}")
            row[3].setStyleSheet("")
        except masks.MaskError as e:
            row[3].setText(str(e))
            row[3].setStyleSheet(f"color: {tokens.colour('critical')}")

    # ---- Never a tag ----
    def _build_never(self, lay: QVBoxLayout) -> None:
        lay.addSpacing(8)
        lay.addWidget(QLabel("Never a tag", objectName="fieldLabel"))
        note = QLabel("Whole tags, or starts with *, that no pattern makes a tagged label, separated by commas: ABC123, API*. Not a "
                      "tag adds to it. A glossary label is always found.", objectName="hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.never_box = QLineEdit()
        self.never_box.setFont(mono())
        self.never_box.setPlaceholderText("Such as ABC123, API*, ISO*")
        self.never_box.setAccessibleName("Never a tag")
        self.never_box.textChanged.connect(self.changed)
        lay.addWidget(self.never_box)

    # ---- the tester and Try on everything (decision 373) ----
    def _build_tester(self, lay: QVBoxLayout) -> None:
        lay.addSpacing(8)
        lay.addWidget(QLabel("Try it", objectName="fieldLabel"))
        self.try_box = QPlainTextEdit()
        self.try_box.setPlaceholderText("Paste or type some text, such as: Seal faces for P-204A/B are late, and FIC-221 reads high.")
        self.try_box.setAccessibleName("Text to try the glossary and patterns on")
        self.try_box.setFixedHeight(72)
        self.try_box.textChanged.connect(lambda: self._timer.start())
        lay.addWidget(self.try_box)
        self.marked = QTextBrowser()
        self.marked.setAccessibleName("What's found in the text")
        self.marked.setFixedHeight(84)
        lay.addWidget(self.marked)
        self.found = QLabel(objectName="hint")
        self.found.setWordWrap(True)
        self.found.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.found)
        key = QLabel(legend(), objectName="hint")
        key.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(key)
        row = QHBoxLayout()
        self.try_button = QPushButton("Try on everything")
        self.try_button.setToolTip("Runs the patterns as they stand here over every capture, email, document, notes page and task, "
                                   "before you save. Nothing is changed.")
        self.try_button.clicked.connect(self.try_everything)
        row.addWidget(self.try_button)
        note = QLabel("The patterns as they stand here, over everything DocRepo holds, before you save.", objectName="hint")
        row.addWidget(note, 1)
        lay.addLayout(row)
        self.tried = QTextBrowser()
        self.tried.setOpenLinks(False)
        self.tried.setAccessibleName("What Try on everything found")
        self.tried.anchorClicked.connect(self._tried_link)
        self.tried.setFixedHeight(160)
        self.tried.hide()
        lay.addWidget(self.tried)

    # ---- filling and reading ----
    def set(self, patterns: list[dict], never: list[str]) -> None:
        """Fill the form from settings.json's values."""
        for row in list(self.rows):
            for w in row:
                w.deleteLater()
        self.rows = []
        for p in masks.patterns_of(patterns):
            self.add_row(p.name, p.mask, p.space)
        self.none.setVisible(not self.rows)
        self.never_box.blockSignals(True)
        self.never_box.setText(", ".join(never))
        self.never_box.blockSignals(False)
        self._labels = None  # read the glossary again
        self.tried.hide()
        self.refresh_now()

    def patterns(self) -> list[dict]:
        """The patterns as typed, for Save settings to check: each row with a name or a mask."""
        return [{"name": r[0].text().strip(), "mask": r[1].text().strip(), "space": r[2].isChecked()} for r in self.rows
                if r[0].text().strip() or r[1].text().strip()]

    def never(self) -> list[str]:
        return split_never(self.never_box.text())

    def draft(self) -> tuple[list[masks.Pattern], list[str]]:
        """The patterns that can be used as they stand, and Never a tag, for the tester and Try on everything."""
        usable = []
        for p in self.patterns():
            try:
                masks.parse(p["mask"])
            except masks.MaskError:
                continue
            usable.append(masks.Pattern(p["name"] or p["mask"], p["mask"], p["space"]))
        return usable, masks.never_of(self.never())

    def changed(self) -> None:
        """A pattern or Never a tag changed: what each mask means at once, the tester after a moment, and Try on
        everything's list is out of date."""
        for row in self.rows:
            self.show_means(row)
        if not self.tried.isHidden():
            self.tried.setHtml(f'<p style="color:{tokens.colour("text2")}">The patterns changed. Try on everything again.</p>')
        self._timer.start()

    def labels(self) -> list[tagged.Label]:
        if self._labels is None:
            self._labels = self.glossary()
        return self._labels

    def refresh_now(self) -> None:
        """Mark the tester's text with what the glossary and the patterns as they stand find there."""
        text = self.try_box.toPlainText()
        patterns, never = self.draft()
        labels = self.labels()
        hits = tagged.tester(labels, patterns, never, text) if text.strip() else []
        self.marked.setHtml(marked(text, hits) if text.strip() else f'<span style="color:{tokens.colour("text2")}">Paste or type some text.</span>')
        self.found.setText(found_line(hits, {lb.id: lb.label for lb in labels}) if text.strip() else "")

    def try_everything(self) -> None:
        patterns, never = self.draft()
        if not patterns:
            self.tried.setHtml(f'<p style="color:{tokens.colour("text2")}">Add a pattern first: a glossary label needs none.</p>')
            self.tried.show()
            return
        found, items = self.try_all(patterns, never)
        self.tried.show()
        if not found:
            self.tried.setHtml("<p>The patterns make no new tagged labels in what DocRepo holds.</p>")
            return
        head = ", ".join(f"{esc(t.label)} ({t.items:,})" for t in found[:5]) + ("…" if len(found) > 5 else "")
        lines = [f"<p><b>{len(found):,} new</b>, in {items:,} item{'s' if items != 1 else ''}: {head}</p>"]
        for t in found[:TRIED_SHOWN]:
            lines.append(f'<p style="margin:0"><code>{esc(t.label)}</code> <span style="color:{tokens.colour("text2")}">{t.items:,} · '
                         f'{esc(t.pattern)} · as {esc(", ".join(t.written[:4]))}</span> &nbsp;<a href="never:{quote(t.label, safe="")}">Not a tag</a></p>')
        if len(found) > TRIED_SHOWN:
            lines.append(f'<p style="color:{tokens.colour("text2")}">And {len(found) - TRIED_SHOWN:,} more.</p>')
        self.tried.setHtml("".join(lines))

    def _tried_link(self, url: QUrl) -> None:
        text = url.toString()
        if text.startswith("never:"):
            self.not_a_tag(unquote(text[len("never:"):]))

    def not_a_tag(self, label: str) -> None:
        """Put a label Try on everything found on Never a tag here (saved with the rest), and try again."""
        have = self.never()
        if label.upper() not in (x.upper() for x in have):
            self.never_box.setText(", ".join([*have, label.upper()]))
        self.refresh_now()
        self.try_everything()
