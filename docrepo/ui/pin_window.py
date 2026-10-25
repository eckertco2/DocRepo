"""The pinned capture window (mods log round 3, M0053 and M0054; decisions 53 and 54).

Pin (F12, the pin button beside Expand, or the Pin hotkey once it's set in Settings) shrinks the capture window to a
small window at the bottom right of its screen, above the taskbar and on top of other windows, for dropping files,
Outlook emails and web links on while finding them in Outlook and File Explorer. It's the same capture: its box shows
the capture window's own content text (the same document), and what's dropped goes into the capture window's files.
The main hotkey, its open button, F12, or double-clicking its top line bring the full window back. Ctrl+Enter saves;
Esc hides it, keeping the draft. Its top line moves it, and it stays where it's put until DocRepo restarts.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from docrepo.links import is_link
from docrepo.ui import tokens
from docrepo.ui.capture_window import ContentEdit, _accept_copy, note_drag, read_drop
from docrepo.ui.icons import icon, icon_size
from docrepo.ui.look import tip
from docrepo.ui.style import style_sheet

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow

#: The pinned window's size, and its distance from the screen's edges.
WIDTH, HEIGHT, MARGIN = 320, 236, 16
#: The top line's height: dragging it moves the window, and double-clicking it brings the full window back.
HEAD = 32


def what_was_added(capture: CaptureWindow) -> str:
    """The pinned window's line for what's in the capture: "3 files, 1 email, 1 link", or that there's nothing yet."""
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


class DropZone(QFrame):
    """Where files, emails and links are dropped. It lights up while something DocRepo can take is dragged over it."""

    def __init__(self, take, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.take = take
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        self.label = QLabel("Drop files, emails or links", objectName="dropLabel")
        self.status = QLabel(objectName="hint")
        for w in (self.label, self.status):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setWordWrap(True)
            lay.addWidget(w)

    def _over(self, on: bool) -> None:
        self.setProperty("over", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if note_drag("enter", event.mimeData(), links=True):
            _accept_copy(event)
            self._over(True)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData(), links=True)[0]:
            _accept_copy(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._over(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._over(False)
        note_drag("drop", event.mimeData(), links=True)
        kind, paths = read_drop(event.mimeData(), links=True)
        if kind:
            _accept_copy(event)
            self.take(kind, paths)


class PinWindow(QWidget):
    """The small window the capture window is pinned as. ``sync`` shows the capture's task and what's been added."""

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
        lay.setContentsMargins(10, 6, 10, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(4)
        mark = QLabel()
        mark.setPixmap(icon("pin", tokens.colour("text2")).pixmap(icon_size(16)))
        head.addWidget(mark)
        self.title = QLabel(objectName="pinTitle")
        self.title.setMinimumWidth(0)
        head.addWidget(self.title, 1)
        self.open_button = self._button("expand", "Back to the full capture window", "F12", capture.unpin)
        head.addWidget(self.open_button)
        head.addWidget(self._button("close", "Hide it; the capture stays as a draft", "Esc", capture.hide_pinned))
        lay.addLayout(head)
        self.text = ContentEdit()
        self.text.take_links = True
        self.text.setDocument(capture.content.document())  # the capture window's own text
        self.text.setPlaceholderText("Type a note, or drop files below")
        self.text.setFixedHeight(84)
        self.text.dropped.connect(capture.dropped)
        lay.addWidget(self.text)
        self.drop = DropZone(capture.dropped)
        lay.addWidget(self.drop, 1)
        self.message = QLabel(objectName="error")
        self.message.setWordWrap(True)
        self.message.hide()
        lay.addWidget(self.message)
        for keys, handler in (("Ctrl+Return", capture.save), ("Ctrl+Enter", capture.save), ("Esc", capture.hide_pinned),
                              ("F12", capture.unpin)):
            QShortcut(QKeySequence(keys), self, handler)
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

    def sync(self) -> None:
        """The capture's task on the top line, and what's been added under the drop zone's words."""
        capture = self.capture
        t = capture.ctx.model().tasks.get(capture.task) if capture.task else None
        name = t.title if t else "No task picked"
        self.title.setToolTip(name)
        self.title.setText(self.title.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, WIDTH - 110))
        self.drop.status.setText(what_was_added(capture))

    def show_message(self, text: str) -> None:
        """A problem with something dropped (a folder, a zip folder's file, an email Outlook wouldn't give)."""
        self.message.setText(text)
        self.message.setVisible(bool(text))

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

    # ---- drops anywhere on it, as on the drop zone ----
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if note_drag("enter", event.mimeData(), links=True):
            _accept_copy(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if read_drop(event.mimeData(), links=True)[0]:
            _accept_copy(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        note_drag("drop", event.mimeData(), links=True)
        kind, paths = read_drop(event.mimeData(), links=True)
        if kind:
            _accept_copy(event)
            self.capture.dropped(kind, paths)

    def closeEvent(self, event) -> None:  # noqa: N802 - Alt+F4 hides it; the draft is kept
        event.ignore()
        self.capture.hide_pinned()
