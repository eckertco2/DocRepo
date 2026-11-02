"""Tree files in the browse tool (releases 5.53 to 5.56; the tree files plan, decisions 264 to 287): the Import window, Copy prompt, Export and
the edit review. ``docrepo/tree_files.py`` does the work, and nothing is made until Import or Apply is pressed.

The review only shows (decision 270), so fixing a row happens in the Templates view, after Import. It settles only what can't be fixed
there: names not on the people list, labels that don't exist, and ties to a parent (decisions 272 and 284).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import markup, tree_files as tf
from docrepo.detail import esc
from docrepo.model import Model
from docrepo.pages import num
from docrepo.tasks import TaskError
from docrepo.templates import plural
from docrepo.ui import tokens
from docrepo.ui.style import page_css, style_sheet
from docrepo.ui.widgets import FormDialog

if TYPE_CHECKING:
    from docrepo.ui.browse_window import BrowseWindow
    from docrepo.ui.context import AppContext

ROW_KEY = Qt.ItemDataRole.UserRole
STEPS = ("<ol style='margin:0'><li><b>Copy prompt</b>, and paste it into Copilot with your notes or a transcript.</li>"
         "<li>Bring back its reply: <b>Paste</b> it, or <b>Choose file</b>.</li>"
         "<li>Check what it found, here. Then <b>Import as template</b>.</li>"
         "<li>Fix anything in the Templates view, and <b>Make tasks</b>. Nothing reaches your lists or Capacity until then.</li></ol>")


def _words(text: str = "", name: str = "") -> QLabel:
    label = QLabel(text, objectName=name)
    label.setWordWrap(True)
    return label


def _list_box(lines: list[str], kind: str) -> QLabel:
    """A red list of problems or an amber list of warnings, each line rich text."""
    colour, back = (tokens.colour("critical"), tokens.colour("critical_bg")) if kind == "bad" else (tokens.colour("caution"), tokens.colour("caution_bg"))
    box = _words("<br>".join(lines))
    box.setStyleSheet(f"QLabel {{ color: {colour}; background: {back}; padding: 8px 12px; border-radius: 6px; }} QLabel a {{ color: {colour}; }}")
    return box


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _copy(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def _scroller(body: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(body)
    return scroll


class _Window(FormDialog):
    """These windows change nothing until their button is pressed, so closing one never asks."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 980, height: int = 760) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.resize(width, height)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(24, 20, 24, 20)
        self.outer.setSpacing(10)

    def changed(self) -> bool:
        return False


class TextWindow(_Window):
    """A long text to copy: the prompt, or an export. It can be selected by hand if the clipboard isn't reachable. ``buttons`` are (words, text, what to say)."""

    def __init__(self, parent: QWidget | None, title: str, note: str, text: str, buttons: list[tuple[str, str, str]], close: str = "Close") -> None:
        super().__init__(parent, title, 820, 680)
        self.note = _words(note, "hint")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.outer.addWidget(self.note)
        self.box = QPlainTextEdit(text)
        self.box.setReadOnly(True)
        self.box.setAccessibleName(title)
        self.box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.outer.addWidget(self.box, 1)
        self.said = _words("", "hint")
        self.said.setTextFormat(Qt.TextFormat.PlainText)
        self.outer.addWidget(self.said)
        row = QHBoxLayout()
        row.addStretch()
        self.copies: list[QPushButton] = []
        for i, (words, what, told) in enumerate(buttons):
            b = QPushButton(words, objectName="primary" if i == len(buttons) - 1 else "")
            b.clicked.connect(lambda _=False, w=what, t=told: self.copy(w, t))
            row.addWidget(b)
            self.copies.append(b)
        back = QPushButton(close)
        back.clicked.connect(lambda _=False: self.reject())
        row.addWidget(back)
        self.outer.addLayout(row)

    def copy(self, text: str, told: str) -> None:
        _copy(text)
        self.said.setText(told)


class TreeImportDialog(_Window):
    """The Import window: choose a file or paste one, see the checks and a review, then Import. An edit file closes it, with ``edit`` set, for the edit review."""

    def __init__(self, parent: QWidget | None, ctx: AppContext) -> None:
        super().__init__(parent, "Import a tree file")
        self.ctx = ctx
        self.run_prompt: Callable[[TextWindow], object] = lambda window: window.exec()  # replaceable, so tests don't open a window
        self.shown_key = ""
        self.reading: tf.Reading | None = None
        self.plan: tf.TreePlan | None = None
        self.edit: tf.EditPlan | None = None
        self.name = ""
        self.tie_boxes: dict[tuple[str, str], QComboBox] = {}
        self.name_boxes: dict[str, QComboBox] = {}
        self.label_boxes: dict[str, QComboBox] = {}
        self.prompt_window: TextWindow | None = None
        tools = QHBoxLayout()
        self.prompt_button = QPushButton("Copy prompt")
        self.prompt_button.setToolTip("The rules, the format, and your people and labels, to paste into an LLM with your notes")
        self.prompt_button.clicked.connect(lambda _=False: self.show_prompt())
        choose = QPushButton("Choose file…")
        choose.clicked.connect(lambda _=False: self._choose())
        self.paste_button = QPushButton("Paste")
        self.paste_button.clicked.connect(lambda _=False: self._show_paste())
        for b in (self.prompt_button, choose, self.paste_button):
            b.setAutoDefault(False)  # Enter goes to Import, not to whichever of these has the focus
            tools.addWidget(b)
        tools.addStretch()
        self.outer.addLayout(tools)
        self.waiting_box = QVBoxLayout()
        self.outer.addLayout(self.waiting_box)
        self.paste_area = QWidget()
        pa = QVBoxLayout(self.paste_area)
        pa.setContentsMargins(0, 0, 0, 0)
        pa.addWidget(QLabel("Paste the LLM's reply", objectName="fieldLabel"))
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(f'{{ "format": "{tf.TREE_FORMAT}", "rows": [ … ] }}')
        self.paste.setAccessibleName("Paste the LLM's reply")
        self.paste.setFixedHeight(150)
        pa.addWidget(self.paste)
        read = QPushButton("Read it", objectName="primary")
        read.setAutoDefault(False)
        read.clicked.connect(lambda _=False: self.load(self.paste.toPlainText(), "a paste"))
        pa.addWidget(read, 0, Qt.AlignmentFlag.AlignLeft)
        self.paste_area.hide()
        self.outer.addWidget(self.paste_area)
        self.body = QWidget(objectName="capture")
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 8, 0)
        self.content.setSpacing(10)
        self.outer.addWidget(_scroller(self.body), 1)
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.outer.addWidget(self.error)
        foot = QHBoxLayout()
        self.hint = _words("", "hint")
        foot.addWidget(self.hint, 1)
        self.questions_button = QPushButton("Copy questions")
        self.questions_button.setToolTip("What was assumed or fit nowhere, for your next talk with the expert")
        self.questions_button.setAutoDefault(False)
        self.questions_button.clicked.connect(lambda _=False: self._copy_questions())
        foot.addWidget(self.questions_button)
        self.commit_button = QPushButton("Import as template", objectName="primary")
        self.commit_button.setDefault(True)
        self.commit_button.clicked.connect(lambda _=False: self.save())
        foot.addWidget(self.commit_button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda _=False: self.reject())
        foot.addWidget(cancel)
        self.outer.addLayout(foot)
        self.tree: QTreeWidget | None = None
        self.detail: QTextBrowser | None = None
        self._show_waiting()
        self._draw()

    # ---- bringing a file in ----
    def _show_waiting(self) -> None:
        """What's waiting in Copilot's folder (release 5.56): a file already imported isn't offered again."""
        _clear(self.waiting_box)
        for w in tf.waiting_files(self.ctx.settings.copilot_folder, self.ctx.data_root):
            row = QHBoxLayout()
            words = QLabel(f"Waiting in Copilot's folder: <b>{esc(w.name)}</b>")
            row.addWidget(words)
            review = QPushButton("Review it")
            review.clicked.connect(lambda _=False, x=w: self.load_file(x.path))
            row.addWidget(review)
            row.addStretch()
            self.waiting_box.addLayout(row)

    def _choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "The tree file or edit file", "", "JSON or text (*.json *.txt *.md);;All files (*)")
        if name:
            self.load_file(Path(name))

    def load_file(self, path: Path) -> None:
        try:
            text = tf.read_file(path)
        except (OSError, ValueError) as e:
            self.fail(str(e) if isinstance(e, ValueError) else f"That file couldn't be read ({type(e).__name__}).")
            return
        self.load(text, path.name)

    def _show_paste(self) -> None:
        self.paste_area.show()
        self.paste.setFocus()

    def load(self, text: str, name: str) -> None:
        """Read a file or a paste, and show what's in it. Nothing is made here."""
        self.fail("")
        self.name, self.plan, self.edit = name or "a paste", None, None
        self.reading = tf.read_text(text)
        data = self.reading.data
        if data is not None and data.get("format") == tf.EDIT_FORMAT:
            self.edit = tf.plan_edit(self.ctx.conn, self.ctx.settings, data, self.ctx.now())
            self.accept()
            return
        if data is not None and data.get("format") == tf.TREE_FORMAT:
            self.plan = tf.check_tree(data, self.ctx.model(), self.ctx.settings.me, tf.template_names(self.ctx.conn))
        elif data is not None:
            self.reading = tf.Reading(problem=tf.format_problem(data))
        self.paste_area.hide()
        self._draw()

    def fail(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    # ---- what the window shows ----
    def can_import(self) -> bool:
        return self.plan is not None and not self.plan.problems

    def _draw(self) -> None:
        _clear(self.content)
        self.tie_boxes, self.name_boxes, self.label_boxes = {}, {}, {}
        self.tree, self.detail = None, None
        can = self.can_import()
        self.commit_button.setEnabled(can)
        self.hint.setText("Nothing is made until you press Import, and a template can be discarded." if can else "A template is made only from a file with no problems.")
        self.questions_button.setVisible(can and bool(self.plan.unplaced or self.plan.assumed_count()))
        if self.reading is None:
            self.content.addWidget(_words(STEPS))
        elif self.reading.problem:
            self.content.addWidget(_list_box([esc(self.reading.problem)], "bad"))
        elif self.plan.problems:
            self._draw_problems()
        else:
            self._draw_review()
        self.content.addStretch()

    def _draw_problems(self) -> None:
        p = self.plan
        self.content.addWidget(QLabel(f"{plural(len(p.problems), 'problem')} to fix first", objectName="heading"))
        self.content.addWidget(_list_box([esc(x.text) for x in p.problems], "bad"))
        if p.warnings:
            self.content.addWidget(_list_box([esc(x.text) for x in p.warnings], "warn"))
        self.content.addWidget(_words("Ask the LLM to fix these and write the file again. Nothing has been made.", "hint"))

    def _draw_review(self) -> None:
        p = self.plan
        parts = [plural(len(p.rows), "row"), plural(p.tie_count(), "tie"), f"{p.assumed_count()} with assumptions"]
        if p.names:
            parts.append(f"{plural(len(p.names), 'name')} to settle")
        summary = QLabel(f"{p.title_of(p.top)} · {' · '.join(parts)}", objectName="heading")
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        self.content.addWidget(summary)
        if self.reading.wrapped:
            self.content.addWidget(_words("The reply had words around the JSON, and DocRepo read only the JSON.", "hint"))
        if p.warnings:
            caution = tokens.colour("caution")
            box = _list_box([f'<a href="{esc(x.key)}" style="color:{caution}">{esc(x.text)}</a>' if x.key else esc(x.text) for x in p.warnings], "warn")
            box.linkActivated.connect(self.select_row)
            self.content.addWidget(box)
        self.content.addWidget(self._review_grid())
        dates = self._dates_note()
        if dates:
            self.content.addWidget(_words(dates, "hint"))
        self._settle_ties()
        self._settle_names()
        self._settle_labels()
        if p.unplaced:
            self.content.addWidget(QLabel(f"Not placed ({len(p.unplaced)})", objectName="heading"))
            lines = _words("<br>".join(f"• {esc(u)}" for u in p.unplaced))
            self.content.addWidget(lines)
        first = next((x.key for x in p.warnings if x.key), p.top)
        self.select_row(first)

    def _dates_note(self) -> str:
        p = self.plan
        if p.to_type:
            names = ", ".join(p.title_of(k) for k in p.to_type)
            return f"Nothing sets a date for {esc(names)}, so Make tasks will ask for it" + (f", along with the anchor's, {esc(p.title_of(p.anchor))}." if p.anchor else ".")
        return f"The anchor is {esc(p.title_of(p.anchor))}: type its date at Make tasks, and the rest follows." if p.anchor else ""

    def _review_grid(self) -> QWidget:
        p = self.plan
        split = QSplitter()
        split.setMinimumHeight(300)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Rows")
        self.tree.setStyleSheet("QTreeView::item:selected { padding: 2px 4px; }")  # a picked row stays where it is
        warned = {x.key for x in p.warnings}
        items: dict[str, QTreeWidgetItem] = {}
        for key, _depth in p.walk():
            x = p.by_key[key]
            parent = p.parent_of(key)
            mark = "⚠" if key in warned else "•" if x.get("assumed") else ""
            item = QTreeWidgetItem([x["title"], tf.row_bits(x), mark])
            item.setData(0, ROW_KEY, key)
            if key in warned:
                item.setToolTip(2, "Has a warning")
            elif x.get("assumed"):
                item.setToolTip(2, "Has assumptions")
            (items[parent].addChild(item) if parent is not None else self.tree.addTopLevelItem(item))
            items[key] = item
        self.tree.expandAll()
        for i in (0, 1, 2):
            self.tree.resizeColumnToContents(i)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), 300))
        self.tree.currentItemChanged.connect(lambda now, _: self._show_row(now.data(0, ROW_KEY)) if now is not None else None)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.document().setDefaultStyleSheet(page_css())
        self.detail.setAccessibleName("The row picked")
        split.addWidget(self.tree)
        split.addWidget(self.detail)
        split.setSizes([400, 500])
        return split

    def select_row(self, key: str) -> None:
        if self.tree is None:
            return
        found = self._find(key)
        if found is not None:
            self.tree.setCurrentItem(found)
            self._show_row(key)

    def _find(self, key: str) -> QTreeWidgetItem | None:
        def look(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, ROW_KEY) == key:
                return item
            for i in range(item.childCount()):
                hit = look(item.child(i))
                if hit is not None:
                    return hit
            return None
        for i in range(self.tree.topLevelItemCount()):
            hit = look(self.tree.topLevelItem(i))
            if hit is not None:
                return hit
        return None

    def _who(self, names: list[str]) -> str:
        m, me = self.ctx.model(), self.ctx.settings.me
        caution = tokens.colour("caution")
        return ", ".join(esc(p.name) if (p := tf.person_named(m, me, n)) else f'<b style="color:{caution}">{esc(n)}</b> (not on the people list)' for n in names)

    def _row_html(self, key: str) -> str:
        p = self.plan
        x, rows, caution = p.by_key[key], [], tokens.colour("caution")
        if p.anchor == key:
            rows.append(("Start", "The anchor: typed at Make tasks"))
        settled = self.settled()
        for f, label in tf.TIE_LABELS.items():
            tie = x.get(f)
            if tie:
                source = tf.settled_source(p, settled, key, f, tie)
                words = tf.tie_sentence(p, {**tie, "source": source}) if source else tf.tie_sentence(p, tie)
                rows.append((label, esc(words) if source else f'<b style="color:{caution}">Left untied:</b> {esc(words)}'))
        if x.get("duration") is not None:
            rows.append(("Duration", plural(int(x["duration"]), "day") + (", through weekends" if x.get("calendar_days") else "")))
        for f, label in (("leads", "Lead"), ("assignees", "Assignees")):
            if x.get(f):
                rows.append((label, self._who(x[f])))
        for f in tf.ALL_HOURS:
            if x.get(f) is not None:
                rows.append(("Lead hours" if f.startswith("lead") else "Assignee hours", tf.hours_words(f, x[f])))
        if x.get("labels"):
            m = self.ctx.model()
            rows.append(("Labels", ", ".join(esc(n) if tf.label_named(m, n) else f'<b style="color:{caution}">{esc(n)}</b> (doesn\'t exist yet)' for n in x["labels"])))
        kinds = [w for w, on in (("Plant event", x.get("plant_event")), ("Meeting", x.get("meeting")), ("Anchor", p.anchor == key)) if on]
        out = [f"<h3 style='margin:0'>{esc(x['title'])}</h3>"]
        if kinds:
            out.append(f"<p class='sub'>{' · '.join(kinds)}</p>")
        out.append("<table cellspacing='0' cellpadding='2'>" + "".join(f"<tr><td class='sub'>{a}&nbsp;&nbsp;</td><td>{b}</td></tr>" for a, b in rows) + "</table>"
                   if rows else "<p class='sub'>Nothing was said about its timing or people.</p>")
        if x.get("description"):
            out.append(f"<p>{esc(x['description'])}</p>")
        for line in (x.get("notes") or "").split("\n"):
            if line.strip():
                box = "☐ " if markup.CHECK.match(line.lstrip("- ")) else ""
                out.append(f"<p style='margin:0'>{box}{esc(markup.CHECK.sub('', line.lstrip('- '), 1) if box else line)}</p>")
        if x.get("quote"):
            out.append(f"<p class='sub'><b>From the notes</b><br>“{esc(x['quote'])}”</p>")
        if x.get("assumed"):
            out.append("<p class='sub'><b>Assumed</b><br>" + "<br>".join(f"• {esc(a)}" for a in x["assumed"]) + "</p>")
        warned = [w.text for w in p.warnings if w.key == key]
        if warned:
            out.append(f"<p style='color:{caution}'>" + "<br>".join(esc(w) for w in warned) + "</p>")
        return "".join(out)

    def _show_row(self, key: str) -> None:
        self.shown_key = key
        if self.detail is not None:
            self.detail.setHtml(self._row_html(key))

    # ---- settling ----
    def _grid(self, heading: str) -> QGridLayout:
        self.content.addWidget(QLabel(heading, objectName="heading"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(2, 1)
        self.content.addLayout(grid)
        return grid

    def _settle_row(self, grid: QGridLayout, at: int, words: str, options: list[tuple[str, str]]) -> QComboBox:
        label = QLabel(words)
        label.setTextFormat(Qt.TextFormat.PlainText)
        box = QComboBox()
        box.setAccessibleName(words)
        box.setMinimumWidth(360)
        for text, value in options:
            box.addItem(text, value)
        grid.addWidget(label, at, 0)
        grid.addWidget(box, at, 1)
        return box

    def _settle_ties(self) -> None:
        p = self.plan
        if not p.parent_ties:
            return
        grid = self._grid("Ties to settle")
        for at, t in enumerate(p.parent_ties):
            options = [(p.title_of(o) + ("" if i else f" (the last in {p.title_of(t.source)})"), o) for i, o in enumerate(t.options)]
            options.append(("Leave it untied, and keep the words in the description", ""))
            box = self._settle_row(grid, at, f"{p.title_of(t.key)}, {tf.TIE_LABELS[t.field_name]}: counts from", options)
            box.currentIndexChanged.connect(lambda _=0: self._show_row(self.shown_key))
            self.tie_boxes[(t.key, t.field_name)] = box

    def _settle_names(self) -> None:
        p = self.plan
        if not p.names:
            return
        grid = self._grid("Names to settle")
        m = self.ctx.model()
        for at, n in enumerate(p.names):
            options = [("Leave blank, keep the name in the description", "")]
            if n.near is not None:
                options.append((f"{n.near.name} (close match)", n.near.id))
            options += [(x.name, x.id) for x in m.active_people() if n.near is None or x.id != n.near.id]
            options.append((f"Add {n.name} as a new person", tf.NEW))
            self.name_boxes[n.name] = self._settle_row(grid, at, f"“{n.name}”", options)

    def _settle_labels(self) -> None:
        p = self.plan
        if not p.labels:
            return
        grid = self._grid("Labels that don't exist yet")
        for at, label in enumerate(p.labels):
            self.label_boxes[label.name] = self._settle_row(grid, at, label.name, [("Leave it out", ""), ("Add this label", tf.NEW)])

    def settled(self) -> tf.Settled:
        return tf.Settled({k: b.currentData() for k, b in self.name_boxes.items()}, {k: b.currentData() for k, b in self.label_boxes.items()},
                          {k: b.currentData() for k, b in self.tie_boxes.items()})

    # ---- the buttons ----
    def show_prompt(self) -> None:
        m = self.ctx.model()
        rule_text = tf.rules(self.ctx.fs, self.ctx.data_root, tf.TREE_RULES_FILE, tf.TREE_RULES)
        text = tf.tree_prompt(m, self.ctx.settings.me, rule_text)
        self.prompt_window = TextWindow(self, "Copy prompt: a tree file", "The rules are yours to edit, in Config\\tree-prompt.md. DocRepo adds the format and your people and labels, "
                                        "so they stay current. Add your notes at the end. DocRepo never calls an LLM: you paste this into one.", text,
                                        [("Copy", text, "Copied the prompt. Paste it into Copilot, and add your notes at the end.")], "Back")
        self.run_prompt(self.prompt_window)

    def _copy_questions(self) -> None:
        _copy(tf.questions(self.plan))
        self.hint.setText("Copied the questions and assumptions, for your next talk with the expert.")

    def save(self) -> None:
        if self.can_import():
            self.accept()


class EditReviewDialog(_Window):
    """An edit file's changes, each with the words it came from, ticked unless nothing asked for it (decision 286). Anything unticked stays as it is.
    What a change on a template reaches folds out under it, as a template's preview lists it (decisions 186 and 188)."""

    def __init__(self, parent: QWidget | None, plan: tf.EditPlan, m: Model, today) -> None:
        super().__init__(parent, f"Edit file: {plan.name}", 820, 720)
        self.plan, self.m, self.today = plan, m, today
        self.ticks: dict[int, QCheckBox] = {}
        self.subs: dict[int, dict[str, QCheckBox]] = {}
        self._reach_words: dict[int, Callable[[], str]] = {}
        self._reach_labels: dict[int, QPushButton] = {}
        self._moves: dict[int, QLabel] = {}
        top = QLabel(plan.counts(), objectName="heading")
        top.setTextFormat(Qt.TextFormat.PlainText)
        self.outer.addWidget(top)
        if plan.stale:
            self.outer.addWidget(_list_box([esc(plan.stale)], "warn"))
        if plan.problems:
            self.outer.addWidget(_list_box([esc(x) for x in plan.problems], "bad"))
            self.outer.addWidget(_words("Ask the LLM to fix these and write the file again. Nothing has changed.", "hint"))
            self.outer.addStretch()
        elif plan.changes:
            body = QWidget(objectName="capture")
            cards = QVBoxLayout(body)
            cards.setContentsMargins(0, 0, 8, 0)
            cards.setSpacing(6)
            for i, c in enumerate(plan.changes):
                cards.addWidget(self._card(i, c))
            if plan.unplaced:
                cards.addWidget(_words("<b>Not placed</b><br>" + "<br>".join(f"• {esc(u)}" for u in plan.unplaced)))
            cards.addStretch()
            self.outer.addWidget(_scroller(body), 1)
        else:
            self.outer.addWidget(_words("Everything in this file is what the tree already says, so there's nothing to change."))
            self.outer.addStretch()
        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        self.outer.addWidget(self.error)
        foot = QHBoxLayout()
        foot.addWidget(_words("Anything unticked stays as it is. A task you untick keeps its value and stops following." if plan.kind == "template"
                              else "Anything unticked stays as it is. Each status log says what changed, from an edit file.", "hint"), 1)
        self.commit_button = QPushButton(objectName="primary")
        self.commit_button.setDefault(True)
        self.commit_button.clicked.connect(lambda _=False: self.save())
        foot.addWidget(self.commit_button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda _=False: self.reject())
        foot.addWidget(cancel)
        self.outer.addLayout(foot)
        self._sync()

    # ---- a change's card ----
    def _headline(self, c: tf.EditChange) -> str:
        if c.kind == "add":
            x = c.row
            bits = [plural(int(x["duration"]), "day")] if x.get("duration") else []
            bits += [", ".join(x["assignees"])] if x.get("assignees") else []
            return f"<span class='sub'>New row</span> <b>{esc(c.title)}</b>" + (f", {esc(', '.join(bits))}" if bits else "")
        if c.kind == "remove":
            if self.plan.kind == "task":
                keep = f" {plural(c.tied_here, 'task')} tied to it keep their dates." if c.tied_here else ""
                return f"<span class='sub'>Discard</span> <b>{esc(c.title)}</b>, with the reason “{tf.TAKEN_OUT}”. Bring back restores it.{esc(keep)}"
            return f"<span class='sub'>Take out</span> <b>{esc(c.title)}</b>"
        old, new = c.old_words(self.m, self.today), c.new_words(self.m, self.today)
        clip = lambda s: s if len(s) <= 90 else s[:90].rsplit(" ", 1)[0] + "…"  # noqa: E731
        return (f"<span style='color:{tokens.colour('text2')}'>{esc(c.title)} · {tf.FIELD_WORDS.get(c.field_name, c.field_name)}</span><br>"
                f"<span style='color:{tokens.colour('text2')}'><s>{esc(clip(old))}</s></span> → <b>{esc(clip(new))}</b>")

    def _card(self, i: int, c: tf.EditChange) -> QFrame:
        card = QFrame(objectName="fileRow")
        grid = QGridLayout(card)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        tick = QCheckBox()
        tick.setChecked(c.ticked)
        tick.setEnabled(not c.blocked)
        tick.setAccessibleName(f"Apply: {c.title}")
        tick.toggled.connect(lambda on, x=c: self._ticked(x, on))
        self.ticks[i] = tick
        grid.addWidget(tick, 0, 0, Qt.AlignmentFlag.AlignTop)
        at = 0
        lines = QVBoxLayout()
        lines.setSpacing(3)
        lines.addWidget(_words(self._headline(c)))
        if c.quote:
            q = _words(f"“{c.quote}”", "hint")
            q.setTextFormat(Qt.TextFormat.PlainText)
            lines.addWidget(q)
        elif not c.blocked:
            lines.addWidget(self._flag("Nothing in what you said asked for this, so it starts unticked."))
        if c.blocked:
            lines.addWidget(self._flag(c.blocked))
        if c.linked:
            lines.addWidget(self._flag("This task will stop following the template for this field."))
        if c.tied:
            lines.addWidget(_words("Its date stays tied, and the gap changes to match.", "hint"))
        reach = self._reach(i, c)
        if reach is not None:
            lines.addWidget(reach)
        if c.moves:
            self._moves[i] = _words("", "hint")
            lines.addWidget(self._moves[i])
        grid.addLayout(lines, at, 1)
        grid.setColumnStretch(1, 1)
        return card

    def _flag(self, text: str) -> QLabel:
        label = _words(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(f"color: {tokens.colour('caution')};")
        return label

    def _ticked(self, c: tf.EditChange, on: bool) -> None:
        c.ticked = on
        self._sync()

    def _reach(self, i: int, c: tf.EditChange) -> QWidget | None:
        """What a change on a template reaches, folded, with a tick for each task or tree."""
        if self.plan.kind != "template" or c.plan is None:
            return None
        if c.kind == "field":
            entries = [(x.task, f"{x.tree}: {', '.join(x.lines)}") for x in [*c.plan.items, *c.plan.moved]]
            fixed = [f"{x.tree}: {x.text}" for x in c.plan.not_changing]
            items = {x.task: x for x in [*c.plan.items, *c.plan.moved]}

            def words() -> str:
                on = [k for k, _ in entries if k not in c.off]
                before, after = sum(items[k].work_before for k in on), sum(items[k].work_after for k in on)
                work = f". Work across them: {num(before)} h → {num(after)} h" if before != after else ""
                return f"Reaches {plural(len(on), 'task')}{work}" + (f". {len(fixed)} not changing" if fixed else "")
        elif c.kind == "add":
            entries = [(x.task, f"{x.title}: {x.closed} of {x.total} closed") for x in c.plan.trees]
            fixed = [f"{x}: closed, so it isn't offered" for x in c.plan.closed_trees]

            def words() -> str:
                return f"Offered to {plural(len([k for k, _ in entries if k not in c.off]), 'open tree')}"
        else:
            entries = [(x.task, f"{x.tree}: not started, nothing on it") for x in c.plan.copies if x.can]
            fixed = [f"{x.tree}: kept, as it's started or has something on it" for x in c.plan.copies if not x.can]

            def words() -> str:
                n = len([k for k, _ in entries if k not in c.off])
                kept = len(entries) - n + len(fixed)
                return f"{n} {'copy' if n == 1 else 'copies'} to discard, {kept} kept without a link"
        if not entries and not fixed:
            return None
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(2)
        fold = QPushButton(objectName="moreLink")
        lay.addWidget(fold, 0, Qt.AlignmentFlag.AlignLeft)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(12, 0, 0, 0)
        il.setSpacing(2)
        self.subs[i] = {}
        for key, text in entries:
            sub = QCheckBox(text.replace("&", "&&"))
            sub.setChecked(key not in c.off)
            sub.toggled.connect(lambda on, k=key, x=c, n=i: self._sub_ticked(x, k, on, n))
            self.subs[i][key] = sub
            il.addWidget(sub)
        for text in fixed:
            line = _words(text, "hint")
            line.setTextFormat(Qt.TextFormat.PlainText)
            il.addWidget(line)
        inner.hide()
        lay.addWidget(inner)
        self._reach_words[i] = words
        self._reach_labels[i] = fold

        def toggle() -> None:
            inner.setVisible(inner.isHidden())
            self._draw_fold(i, inner)
        fold.clicked.connect(lambda _=False: toggle())
        self._draw_fold(i, inner)
        return box

    def _draw_fold(self, i: int, inner: QWidget) -> None:
        self._reach_labels[i].setText(f"{self._reach_words[i]()} {'▸' if inner.isHidden() else '▾'}")
        self._reach_labels[i].setProperty("inner", inner)

    def _sub_ticked(self, c: tf.EditChange, key: str, on: bool, i: int) -> None:
        (c.off.discard if on else c.off.add)(key)
        self._draw_fold(i, self._reach_labels[i].property("inner"))

    # ---- the button ----
    def _sync(self) -> None:
        on = [c for c in self.plan.changes if c.ticked and not c.blocked]
        waiting = tf.waiting_on(self.plan)
        self.commit_button.setText(f"Apply {plural(len(on), 'change')}")
        self.commit_button.setEnabled(bool(on) and not self.plan.problems and not waiting)
        self.error.setText(waiting)
        self.error.setVisible(bool(waiting))
        closing = tf.closing_ids(self.plan)
        for i, c in enumerate(self.plan.changes):
            label = self._moves.get(i)
            if label is not None:  # a task this file closes doesn't move (decision 287)
                moves = [x for x in c.moves if x.task not in closing]
                far = sum(1 for x in moves if x.far)
                head = f"Moves {plural(len(moves), 'tied task')} with it" + (f", {far} in another tree" if far else "")
                label.setText(f"{head}: " + ", ".join(esc(x.title) + (" (another tree)" if x.far else "") for x in moves) if moves else "")
                label.setVisible(bool(moves))

    def save(self) -> None:
        if self.commit_button.isEnabled():
            self.accept()


class TreeFilesPane:
    """Tree files from the browse window: the Templates view's Import… and Export, and a task's Export tree… and Bring back an edit file…."""

    def __init__(self, browse: BrowseWindow) -> None:
        self.w = browse

    def import_tree(self) -> None:
        """The Import window, then the template it made, opened. A file that can't be made stays in the window, saying why."""
        w = self.w
        dialog = TreeImportDialog(w, w.ctx)
        w._tree_import_dialog = dialog  # kept, so tests can reach it
        while w.run_dialog(dialog):
            if dialog.edit is not None:
                self.review_edit(dialog.edit, dialog.reading, dialog.name)
                return
            made: list[int] = []

            def change():
                top, out = tf.import_file(w.conn, w.ctx.data_root, w.ctx.fs, dialog.plan, dialog.settled(), dialog.reading, dialog.name, w._now())
                made.append(top)
                return out
            if w._do(change):
                w.templates.open_row(str(made[0]))
                return
            dialog.fail(w.status.text())

    def review_edit(self, plan: tf.EditPlan, reading: tf.Reading, name: str) -> None:
        """The edit review, then the changes it ticked, all or none, in one transaction."""
        w = self.w
        dialog = EditReviewDialog(w, plan, w.model(), w.today())
        w._edit_review_dialog = dialog  # kept, so tests can reach it
        if not w.run_dialog(dialog):
            return
        kind, subject = plan.kind, plan.id
        out = w._do(lambda: tf.apply_edit(w.conn, w.ctx.data_root, w.ctx.fs, w.ctx.settings, plan, reading, name, w._now()))
        if out and kind == "template":
            lib = w.templates.library()
            w.templates.open_row(str(lib.templates[int(subject)].top))
            w.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))
        elif out and subject in w.model().tasks:
            w.go_task(subject)
            w.say(out.message + (" Problems: " + " ".join(out.problems) if out.problems else ""), bool(out.problems))

    def _export(self, data: Mapping, name: str) -> None:
        """Write it to Exports and the clipboard (decision 278), and show it, with the prompt to change it by talking."""
        w = self.w
        try:
            path = tf.save_export(w.ctx.fs, w.ctx.data_root, data, name, w._now())
            where = f"Saved as {tf.EXPORTS}\\{path.name} in the data root, and copied."
        except (OSError, tf.WriteRefused) as e:
            where = f"It couldn't be saved in {tf.EXPORTS} ({type(e).__name__}), but it's copied."
        text = tf.export_text(data)
        _copy(text)
        rule_text = tf.rules(w.ctx.fs, w.ctx.data_root, tf.EDIT_RULES_FILE, tf.EDIT_RULES)
        prompt = tf.edit_prompt(w.model(), w.ctx.settings.me, rule_text, data)
        dialog = TextWindow(w, f"Export: {name}", f"{where} To change it by talking: Copy edit prompt, paste it into Copilot with what you said, and bring the reply back to Import. Export changes nothing.",
                            text, [("Copy", text, "Copied the exported tree."), ("Copy edit prompt", prompt, "Copied the edit prompt. Add what you said at the end.")])
        w._export_dialog = dialog  # kept, so tests can reach it
        w.run_dialog(dialog)

    def export_template(self, template_id: int) -> None:
        w = self.w
        try:
            data = tf.export_template(w.conn, template_id, w._now())
        except TaskError as e:
            w.say(str(e), error=True)
            return
        self._export(data, w.templates.library().name(template_id))

    def export_task(self, task_id: str) -> None:
        w = self.w
        try:
            data = tf.export_task(w.conn, task_id, w._now())
        except TaskError as e:
            w.say(str(e), error=True)
            return
        self._export(data, w.model().task(task_id).title)
