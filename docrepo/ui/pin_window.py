"""The pinned capture window (mods log round 3: M0053 and M0054, decisions 53 and 54; M0062 to M0064, decisions 61 to 63).

Pin (F12, the pin button beside Expand, or the Pin hotkey once it's set in Settings) shrinks the capture window to a
small window at the bottom right of its screen, above the taskbar and on top of other windows, for dropping files,
Outlook emails and web links on while finding them in Outlook and File Explorer. It's the same capture, in 320 × 236 px:

- the top line: the task picker (the capture window's own, opened under it) and buttons back to the full window and to
  hide it; the pin mark beside it moves the window;
- the capture types, Note, New task and Update, as small toggles;
- a box with the capture window's own content text (the same document);
- a landing row, which lights up while something is dragged over the window: a box for typing or pasting a file's path
  or a web link (Enter adds it), and a button that adds the email selected in Outlook;
- the description of each file, link or email part added, one at a time, with ‹ and › between them;
- a line for what's been added ("2 files, 1 link added"), or a problem with a drop.

The main hotkey, its open button, F12, or double-clicking its top line bring the full window back. Ctrl+Enter saves;
Esc hides it, keeping the draft. It stays where it's moved to until DocRepo restarts.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget

from docrepo.links import is_link
from docrepo.text import typed_path
from docrepo.ui import tokens
from docrepo.ui.capture_window import ContentEdit, FileEntry, _accept_copy, note_drag, read_drop
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.look import tip
from docrepo.ui.style import style_sheet

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow

#: The pinned window's size (it stays this size, whatever it holds: M0064), and its distance from the screen's edges.
WIDTH, HEIGHT, MARGIN = 320, 236, 16
#: The top line's height: dragging it (outside its buttons) moves the window, and double-clicking it brings the full
#: window back.
HEAD = 32
#: Each row's height, so nothing moves as rows fill and empty.
ROW = 26


def what_was_added(capture: CaptureWindow) -> str:
    """The pinned window's line for what's in the capture: "3 files, 1 email, 1 link added", or that there's nothing yet."""
    files = emails = links = 0
    for e in capture.files:
        if e.src == "outlook":
            emails += 1
        elif e.src != "email":  # an email's attachments, links and pictures count with the email
            if is_link(e.row.path or ""):
                links += 1
            else:
                files += 1
    parts = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((files, "file"), (emails, "email"), (links, "link")) if n]
    return ", ".join(parts) + " added" if parts else "Nothing added yet"


def describable(capture: CaptureWindow) -> list[FileEntry]:
    """The rows that take a description: files, links, and an email's kept attachments, links and pictures."""
    return [e for e in capture.files if e.desc is not None and (e.row.of is None or e.row.keep)]


def two_lines(text: str, metrics, width: int) -> str:
    """``text`` as it fits in two lines ``width`` px wide, cut at a word with "…" when it doesn't."""
    flags = int(Qt.TextFlag.TextWordWrap)
    if metrics.boundingRect(0, 0, width, 10_000, flags, text).height() <= 2 * metrics.lineSpacing():
        return text
    words = text.split()
    while words and metrics.boundingRect(0, 0, width, 10_000, flags, " ".join(words) + "…").height() > 2 * metrics.lineSpacing():
        words.pop()
    return " ".join(words) + "…"


class DropZone(QFrame):
    """The landing row: it lights up while something DocRepo can take is dragged over the window (``over``)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setFixedHeight(ROW + 6)

    def over(self, on: bool) -> None:
        self.setProperty("over", on)
        self.style().unpolish(self)
        self.style().polish(self)


class PinWindow(QWidget):
    """The small window the capture window is pinned as. ``sync`` shows the capture's task, types, files and descriptions."""

    def __init__(self, capture: CaptureWindow) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.capture = capture
        self.setObjectName("pinWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # so the style sheet draws its background and edge
        self.setWindowTitle("DocRepo Capture, pinned")
        self.setStyleSheet(style_sheet())
        self.setAcceptDrops(True)
        self.setFixedSize(WIDTH, HEIGHT)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.setSpacing(4)
        # ---- the top line: the pin mark (it moves the window), the task picker, back to full, hide ----
        head = QHBoxLayout()
        head.setSpacing(2)
        mark = QLabel()
        mark.setPixmap(icon("pin", tokens.colour("text2")).pixmap(icon_size(16)))
        mark.setCursor(Qt.CursorShape.SizeAllCursor)
        mark.setToolTip("Drag to move it")
        head.addWidget(mark)
        self.task_button = QPushButton(objectName="pinTask")
        self.task_button.setIcon(icon("chevron-down"))
        self.task_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # the arrow at the right end
        self.task_button.setFixedHeight(ROW)
        tip(self.task_button, "The task this capture belongs to")
        self.task_button.clicked.connect(lambda _=False: capture._open_picker(self.task_button))
        head.addWidget(self.task_button, 1)
        self.open_button = self._button("expand", "Back to the full capture window", "F12", capture.unpin)
        head.addWidget(self.open_button)
        head.addWidget(self._button("close", "Hide it; the capture stays as a draft", "Esc", capture.hide_pinned))
        lay.addLayout(head)
        # ---- the capture types, small ----
        types = QHBoxLayout()
        types.setSpacing(2)
        self.type_boxes: dict[str, QCheckBox] = {}
        for key, label in (("note", "Note"), ("new_task", "New task"), ("update", "Update")):
            box = QCheckBox(label, objectName="typeToggle")
            box.setProperty("compact", True)
            box.setFixedHeight(ROW - 4)
            box.clicked.connect(lambda checked, k=key: capture.set_type(k, checked))
            self.type_boxes[key] = box
            types.addWidget(box)
        types.addStretch()
        lay.addLayout(types)
        # ---- the content text ----
        self.text = ContentEdit()
        self.text.take_links = True
        self.text.setDocument(capture.content.document())  # the capture window's own text
        self.text.setPlaceholderText("Type a note, or drop files, emails or links")
        self.text.dropped.connect(self._take)
        lay.addWidget(self.text, 1)
        # ---- the landing row: a path or link, typed or pasted; the email selected in Outlook ----
        self.drop = DropZone()
        dl = QHBoxLayout(self.drop)
        dl.setContentsMargins(6, 2, 2, 2)
        dl.setSpacing(2)
        self.path = QLineEdit()
        self.path.setPlaceholderText("Drop here, or type a path or link")
        self.path.setAccessibleName("A file's path or a web link")
        self.path.setAcceptDrops(False)  # a dropped file is added, not typed in
        self.path.setFixedHeight(ROW - 2)
        self.path.returnPressed.connect(self.add_typed)
        dl.addWidget(self.path, 1)
        self.outlook_button = self._button("mail", "Add the email selected in Outlook", "", self._add_outlook)
        dl.addWidget(self.outlook_button)
        lay.addWidget(self.drop)
        # ---- a description, one file at a time ----
        self.desc_row = QWidget()
        self.desc_row.setFixedHeight(ROW)
        rl = QHBoxLayout(self.desc_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self.prev_button = self._button("chevron-left", "The one before", "", lambda: self._step(-1))
        self.desc = QLineEdit()
        self.desc.setFixedHeight(ROW - 2)
        self.desc.textEdited.connect(self._described)
        self.next_button = self._button("chevron-right", "The next one", "", lambda: self._step(1))
        for w in (self.prev_button, self.desc, self.next_button):
            rl.addWidget(w, 1 if w is self.desc else 0)
        lay.addWidget(self.desc_row)
        # ---- what's been added, or a problem ----
        self.status = QLabel(objectName="hint")
        self.status.setFixedHeight(16)
        lay.addWidget(self.status)
        self.message = QLabel(objectName="error")  # two lines at most; the text box gives up the room
        self.message.setWordWrap(True)
        self.message.setFixedHeight(2 * self.message.fontMetrics().lineSpacing() + 2)
        lay.addWidget(self.message)
        self.message.hide()
        for keys, handler in (("Ctrl+Return", capture.save), ("Ctrl+Enter", capture.save), ("Esc", capture.hide_pinned),
                              ("F12", capture.unpin)):
            QShortcut(QKeySequence(keys), self, handler)
        self._index = 0  # which description shows
        self._count = 0  # how many there were at the last sync, to show a new one as it comes
        self._moved: QPoint | None = None  # where it was dragged to, kept until DocRepo restarts
        self._drag_from: QPoint | None = None

    def _button(self, name: str, text: str, key: str, clicked) -> QToolButton:
        button = QToolButton(objectName="iconButton")
        button.setIcon(icon(name))
        button.setIconSize(icon_size(16))
        button.setFixedSize(24, 24)
        button.setAccessibleName(text.split(";")[0])
        tip(button, text, key)
        button.clicked.connect(lambda _=False: clicked())
        return button

    # ---- what it shows ----
    def sync(self) -> None:
        """The capture's task and types, the current file's description, and what's been added."""
        capture = self.capture
        t = capture.ctx.model().tasks.get(capture.task) if capture.task else None
        name = t.title if t else "No task picked"
        self.task_button.setToolTip(f"{name}. The task this capture belongs to")
        self.task_button.setText(self.task_button.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, WIDTH - 120))
        for key, box in self.type_boxes.items():
            box.setChecked(key in capture.types)
        rows = describable(capture)
        if len(rows) > self._count:
            self._index = len(rows) - 1  # the one just added
        self._count = len(rows)
        self._index = max(0, min(self._index, len(rows) - 1))
        self._show_desc(rows)
        self.status.setText(what_was_added(capture))

    def _show_desc(self, rows: list[FileEntry]) -> None:
        self.desc_row.setVisible(bool(rows))
        if not rows:
            return
        e = rows[self._index]
        self.desc.setText(e.desc.text())
        self.desc.setPlaceholderText(f"{e.row.name}: {e.what or 'what is it?'}")
        self.desc.setToolTip(f"{e.row.name} ({self._index + 1} of {len(rows)}). Left empty: {e.desc.placeholderText()}")
        self.desc.setAccessibleName(f"Description of {e.row.name}")
        for button, on in ((self.prev_button, self._index > 0), (self.next_button, self._index < len(rows) - 1)):
            button.setEnabled(on)

    def _step(self, by: int) -> None:
        self._index += by
        self._show_desc(describable(self.capture))
        self.desc.setFocus()

    def _described(self, text: str) -> None:
        """The description typed here is the file's own, in the full window too."""
        rows = describable(self.capture)
        if rows:
            rows[self._index].desc.setText(text)
            self.capture._apply_same_all()

    def show_message(self, text: str) -> None:
        """A problem with something added (a folder, a zip folder's file, an email Outlook wouldn't give), in place of
        what's been added: two lines, cut with "…" when it's longer, and all of it in its tooltip."""
        self.message.setText(two_lines(text, self.message.fontMetrics(), WIDTH - 20))
        self.message.setToolTip(text)
        self.message.setVisible(bool(text))
        self.status.setVisible(not text)

    # ---- adding ----
    def _take(self, kind: str, paths: list[str]) -> None:
        """A drop, here or on its box: as on the full window, then the new file's description, ready to type."""
        before = len(describable(self.capture))
        self.capture.dropped(kind, paths)
        if len(describable(self.capture)) > before:
            self.desc.setFocus()

    def add_typed(self) -> None:
        """Enter in the landing row: a web link, or a file's path (quoted or not), is added as if dropped."""
        text = typed_path(self.path.text())
        if not text:
            return
        before = len(self.capture.files)
        self.capture.dropped("links" if is_link(text) else "files", [text])
        if len(self.capture.files) > before:
            self.path.clear()
            self.desc.setFocus()

    def _add_outlook(self) -> None:
        """The email selected in Outlook (M0063), as Attach does in the full window; a problem shows on the bottom line."""
        self.show_message("")
        before = len(describable(self.capture))
        self.capture.add_outlook()
        self.sync()
        if len(describable(self.capture)) > before:
            self.desc.setFocus()

    def place(self) -> None:
        """At the bottom right of the screen the capture window (or the mouse) is on, or where it was last moved to."""
        if self._moved is not None and any(s.availableGeometry().contains(self._moved) for s in QGuiApplication.screens()):
            self.move(self._moved)
            return
        at = self.capture.geometry().center() if self.capture.isVisible() else QCursor.pos()
        screen = QGuiApplication.screenAt(at) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.x() + area.width() - WIDTH - MARGIN, area.y() + area.height() - HEIGHT - MARGIN)

    # ---- the top line moves it; double-clicking it brings the full window back ----
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < HEAD:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            self._moved = self.pos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.position().y() < HEAD:
            self.capture.unpin()
            return
        super().mouseDoubleClickEvent(event)

    # ---- drops anywhere on it; the landing row lights up ----
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if note_drag("enter", event.mimeData(), links=True):
            _accept_copy(event)
            self.drop.over(True)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData(), links=True)[0]:
            _accept_copy(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop.over(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.drop.over(False)
        note_drag("drop", event.mimeData(), links=True)
        kind, paths = read_drop(event.mimeData(), links=True)
        if kind:
            _accept_copy(event)
            self._take(kind, paths)

    def closeEvent(self, event) -> None:  # noqa: N802 - Alt+F4 hides it; the draft is kept
        event.ignore()
        self.capture.hide_pinned()
