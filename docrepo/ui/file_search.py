"""File search (release 5.42, decision 214): a small window of its own, with a box, the Task view's painted list and a preview,
searching as you type across every task's files and saved emails.

Names and descriptions answer on the keystroke; the extracted text follows on a worker thread as typing pauses, with the
lines that matched in the preview. Each row says which task it's on. Enter opens (through ``docrepo/opener.py`` and its
allow-list), Ctrl+Enter shows it in File Explorer, Ctrl+Shift+C copies the path, and Tab goes to its task's page. If nothing
matches, what was typed carries to Search everything.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from docrepo import file_search, finder, opener, overview
from docrepo import task_view_pages as pages
from docrepo.captures import capture_folder
from docrepo.overview import Record
from docrepo.search import extracted_text
from docrepo.ui import tokens
from docrepo.ui.result_list import ResultList, Row
from docrepo.ui.style import page_css, style_sheet

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 720, 520
SECOND_TIER_MS = 250
SHOWN = 200


class _Answer(QObject):
    done = Signal(int, object)
    opened = Signal(str, str)


class FileSearch(QWidget):
    """One window per DocRepo, kept and brought back."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.app, self.ctx, self.browse = app, app.ctx, app.browse
        self.setObjectName("browse")
        self.setStyleSheet(style_sheet())
        self.setWindowTitle("File search")
        self.resize(WIDTH, HEIGHT)
        #: Opens a file in its own program. Tests replace it.
        self.starter = None
        self.exists = Path.exists
        self.records: list[Record] = []
        self.filters = finder.Filters()
        self.query = ""
        self.texts: dict[str, str] | None = None
        self.folded_texts: dict[str, str] = {}
        self.second: tuple[str, list[finder.Hit]] | None = None
        self._token = 0
        self._answer = _Answer(self)
        self._answer.done.connect(self._second_done)
        self._answer.opened.connect(self._opened)
        self._threads: list[threading.Thread] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QWidget(objectName="toolbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Search every task's files and saved emails. type:pdf, from:name and after:date narrow it")
        self.box.setClearButtonEnabled(True)
        self.box.textChanged.connect(self._typed)
        self.box.installEventFilter(self)
        tl.addWidget(self.box)
        lay.addWidget(top)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = ResultList(self.ctx.now().date())
        self.list.chosen.connect(lambda _row: self.show_preview())
        self.list.activated_row.connect(lambda row: self.act("open", row))
        self.list.action.connect(lambda row, name: self.act(name, row))
        split.addWidget(self.list)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        self.preview.document().setDefaultStyleSheet(page_css())
        sl.addWidget(self.preview, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(8, 6, 8, 6)
        self.open_button = QPushButton("Open", objectName="primary")
        self.open_button.setToolTip("Enter: in its own program")
        self.open_button.clicked.connect(lambda: self.act("open"))
        self.show_button = QPushButton("Show in File Explorer")
        self.show_button.setToolTip("Ctrl+Enter")
        self.show_button.clicked.connect(lambda: self.act("show"))
        self.task_button = QPushButton("Its task")
        self.task_button.setToolTip("Tab: its page in the browse tool")
        self.task_button.clicked.connect(lambda: self.act("task"))
        for b in (self.open_button, self.show_button, self.task_button):
            buttons.addWidget(b)
        buttons.addStretch()
        sl.addLayout(buttons)
        split.addWidget(side)
        split.setSizes([WIDTH * 55 // 100, WIDTH * 45 // 100])
        lay.addWidget(split, 1)
        self.foot = QLabel(objectName="hint")
        self.foot.setContentsMargins(12, 4, 12, 6)
        lay.addWidget(self.foot)
        self._second_timer = QTimer(self, singleShot=True, interval=SECOND_TIER_MS, timeout=self._start_second)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, lambda: self.act("copy"))
        QShortcut(QKeySequence("Ctrl+W"), self, self.hide)

    # ---- opening ----
    def open_it(self, screen) -> None:
        """Read what's there now, and show the window at the centre of the monitor, with the cursor in the box."""
        self.load()
        area = screen.availableGeometry()
        self.move(area.x() + (area.width() - self.width()) // 2, area.y() + (area.height() - self.height()) // 3)
        self.show()
        self.raise_()
        self.activateWindow()
        self.box.setFocus()
        self.box.selectAll()

    def load(self) -> None:
        self.records = file_search.records(self.ctx.conn, self.ctx.model(), self.ctx.data_root)
        self.texts = None
        self.second = None
        self.refresh()

    def _load_texts(self) -> None:
        """Each file's extracted text, from the search index, read once per opening."""
        if self.texts is None:
            self.texts = overview.file_texts(self.ctx.conn, self.ctx.model(), [r.id for r in self.records if r.kind == "file"])
            self.folded_texts = {k: overview.fold(v) for k, v in self.texts.items()}

    # ---- searching ----
    def _typed(self, text: str) -> None:
        senders = sorted({r.sender for r in self.records if r.sender})
        typed = finder.take_filters(text, self.filters, [], senders, self.ctx.now().date())
        if typed.changed:
            self.box.blockSignals(True)
            self.box.setText(typed.rest)
            self.box.blockSignals(False)
        self.query = self.box.text()
        self.second = None
        self._second_timer.stop()
        if finder.terms(self.query)[0]:
            self._second_timer.start()
        self.refresh()
        if typed.hint:
            self.foot.setText(typed.hint)

    def _start_second(self) -> None:
        """The second tier: the files' extracted text, on a worker thread. Only one answer is ever used: the latest."""
        words, neg = finder.terms(self.query)
        if not words:
            return
        self._load_texts()
        candidates = [r for r in self.records if r.kind == "file" and self.filters.keep(r)]
        texts, query = self.folded_texts, self.query
        self._token += 1
        token, answer = self._token, self._answer

        def work() -> None:
            try:
                answer.done.emit(token, (query, finder.find(candidates, words, neg, texts=texts)))
            except Exception as e:  # noqa: BLE001 - reported in the log; the first tier's rows stay
                answer.done.emit(token, e)

        thread = threading.Thread(target=work, name="DocRepo file search", daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()

    def _second_done(self, token: int, result: object) -> None:
        if isinstance(result, Exception):
            log.warning("file search: searching the files' text failed: %s", type(result).__name__)
            return
        query, hits = result
        if token == self._token and query == self.query:
            self.second = (query, hits)
            self.refresh(keep=True)

    def wait_for_second(self, timeout: float = 5.0) -> None:
        """For tests: run the second tier now and wait for it."""
        self._second_timer.stop()
        self._start_second()
        for t in self._threads:
            t.join(timeout)
        QGuiApplication.processEvents()

    def refresh(self, keep: bool = False) -> None:
        m = self.ctx.model()
        words, neg = finder.terms(self.query)
        current = self.list.current()
        was = self.list.rows[current].record.id if keep and 0 <= current < len(self.list.rows) and self.list.rows[current].record else None
        if words:
            hits = finder.find(self.records, words, neg, keep=self.filters.keep)
            second = self.second[1] if self.second and self.second[0] == self.query else []
            all_hits = [*hits, *second]
            rows = [self._row(m, h.record, words, h) for h in all_hits[:SHOWN]]
            total = len(all_hits)
        else:
            kept = [r for r in self.records if self.filters.keep(r)]
            rows = [self._row(m, r, [], None) for r in kept[:SHOWN]]
            total = len(kept)
        if not rows:
            rows = [Row("empty", label=f"Nothing matches “{self.query}”. Enter searches everything for it." if self.query else "No files or saved emails yet.")]
        choose = next((i for i, r in enumerate(rows) if r.record is not None and r.record.id == was), None)
        if choose is None:
            choose = next((i for i, r in enumerate(rows) if r.choosable), None)
        self.list.set_rows(rows, choose)
        self.foot.setText((f"{total} of {len(self.records)}" if words or self.filters.count() else f"{len(self.records)} files and emails") + " · Enter opens · Ctrl+Enter shows it in File Explorer · Tab goes to its task")
        self.show_preview()

    def _row(self, m, r: Record, words: list[str], hit: finder.Hit | None) -> Row:
        snippet = ""
        if hit is not None and hit.in_text:
            snippet = finder.snippet(self.text_of(r), words)
        return Row("item", record=r, words=list(words), slips=hit.slips if hit else (), in_text=bool(hit and hit.in_text), snippet=snippet,
                   where=file_search.task_title(m, r))

    def text_of(self, r: Record) -> str:
        if r.kind != "file":
            return r.text
        if self.texts is not None and r.id in self.texts:
            return self.texts[r.id]
        return extracted_text(self.ctx.data_root, r.id)

    def current_record(self) -> Record | None:
        i = self.list.current()
        return self.list.rows[i].record if 0 <= i < len(self.list.rows) else None

    def show_preview(self) -> None:
        i = self.list.current()
        row = self.list.rows[i] if 0 <= i < len(self.list.rows) else None
        r = row.record if row else None
        words, _ = finder.terms(self.query)
        today = self.ctx.now().date()
        self.preview.setHtml(pages.preview(self.ctx.model(), r, today, words, row.slips if row else (), self.text_of(r) if r and r.kind == "file" else ""))
        self.open_button.setEnabled(r is not None)
        self.task_button.setEnabled(r is not None)
        self.show_button.setEnabled(r is not None and r.kind == "file" and r.type != "link")

    # ---- acting ----
    def _email_file(self, r: Record) -> str:
        c = self.ctx.model().captures.get(r.capture)
        if c is None:
            return ""
        path = capture_folder(self.ctx.data_root, c.id, c.saved) / "email.msg"
        return str(path) if path.is_file() else ""

    def act(self, name: str, row: int | None = None) -> None:
        if row is not None:
            self.list.choose(row)
        r = self.current_record()
        if r is None:
            if name == "open" and self.query:
                self.search_everything()
            return
        if name == "task":
            self.hide()
            self.app.show_browse(None, r.task)
        elif name == "copy":
            QGuiApplication.clipboard().setText(opener.copy_text([r.path]) if r.path else "")
            self.foot.setText(f"Copied the path of {r.title}.")
        elif name == "show" and r.kind == "file" and r.type != "link":
            self._show(r)
        elif name in ("open", "show"):
            self._open(r)

    def _show(self, r: Record, reason: str = "") -> None:
        found = self.browse.reveal(Path(r.path))
        if found is False:
            self.foot.setText(f"{r.title} isn't at {opener.folder_of(r.path)} any more. File Explorer shows the nearest folder that's there.")
        else:
            self.foot.setText(reason or f"Showed {r.title} in File Explorer.")

    def _open(self, r: Record) -> None:
        """What Open does for this record, as the Task view has it: a link is copied, an attachment shown, a document or an
        email started on a worker thread, so a slow LAN drive never freezes the window."""
        p = opener.plan(r, self._email_file)
        if p.action == "copy_link":
            QGuiApplication.clipboard().setText(p.path.strip())
            self.foot.setText(f"Copied the link to {r.title}. DocRepo never opens links: paste it into your browser.")
        elif p.action == "show":
            self._show(r, p.reason)
        elif p.action == "capture":
            self.foot.setText(p.reason)
            self.hide()
            self.app.show_browse()
            self.browse.go_capture(p.path)
        else:
            path, starter, exists, answer = p.path, self.starter, self.exists, self._answer

            def work() -> None:
                answer.opened.emit(r.title, opener.start(path, starter, exists) or "")

            self.foot.setText(f"Opening {r.title}…")
            thread = threading.Thread(target=work, name="DocRepo open", daemon=True)
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
            thread.start()

    def _opened(self, title: str, error: str) -> None:
        self.foot.setText(error or f"Opened {title}.")

    def search_everything(self) -> None:
        text = self.query
        self.hide()
        self.app.show_browse()
        self.browse.search_box.setText(text)
        self.browse.search_box.setFocus()

    # ---- keys ----
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.box and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                self._move(key)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.act("show" if event.modifiers() & Qt.KeyboardModifier.ControlModifier else "open")
                return True
            if key == Qt.Key.Key_Tab:
                self.act("task")
                return True
            if key == Qt.Key.Key_Escape:
                if self.box.text():
                    self.box.clear()
                else:
                    self.hide()
                return True
        return super().eventFilter(watched, event)

    def _move(self, key: int) -> None:
        rows = self.list.choosable()
        if not rows:
            return
        now = self.list.current()
        at = rows.index(now) if now in rows else 0
        step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 8, Qt.Key.Key_PageUp: -8}[Qt.Key(key)]
        self.list.choose(rows[max(0, min(len(rows) - 1, at + step))])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - closing only hides it
        event.ignore()
        self.hide()
