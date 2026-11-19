"""Notes, Summary and Transcript: the capture window's tabs in Discussions and meetings (release 5.170, the design
workspace's ``docs/mods/discussions-plan.md``, decisions 795 to 797).

Outside the mode it's the content text's editor alone, as it always was. In the mode a tab strip comes over it:

- **Notes** is the editor, the only one read for operators, so the agenda and the item cards beside it follow Notes alone.
- **Summary** holds the capture window's own Summary box (``captures.summary``), with the summary type, moved here from
  the folded lower part, and moved back when the mode goes (decision 796).
- **Transcript** is a plain text box (no operator colouring): pasted as plain text, kept on Save as ``transcript.md`` in
  the meeting's Files, never in docs.db's rows or on the notes page (decision 797).

A tab with text in it has a dot after its name. Alt+1, 2 and 3 move between them (Ctrl+1 is the checklist key and
Ctrl+Alt+1 to 3 make headings in the editor, so those stay).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QBoxLayout, QPlainTextEdit, QStackedWidget, QTabBar, QVBoxLayout, QWidget

NOTES, SUMMARY, TRANSCRIPT = 0, 1, 2
NAMES = ("Notes", "Summary", "Transcript")
KEYS = ("Alt+1", "Alt+2", "Alt+3")
DOT = " •"
TRANSCRIPT_HINT = ("Paste the transcript here. It's kept whole, as transcript.md in the meeting's files: nothing in it makes "
                   "an item, and it isn't put on the notes page.")


class MeetingTabs(QWidget):
    """The editor, and in Discussions and meetings the Summary and Transcript tabs beside it."""

    def __init__(self, editor: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.bar = QTabBar(objectName="meetingTabs")
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for name, key in zip(NAMES, KEYS):
            i = self.bar.addTab(name)
            self.bar.setTabToolTip(i, f"{name} ({key})")
        self.bar.currentChanged.connect(self._show)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.stack = QStackedWidget()
        self.stack.addWidget(editor)
        self.summary_page = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_page)
        self.summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_layout.setSpacing(6)
        self.stack.addWidget(self.summary_page)
        self.transcript = QPlainTextEdit()
        self.transcript.setObjectName("transcript")
        self.transcript.setPlaceholderText(TRANSCRIPT_HINT)
        self.transcript.setAccessibleName("Transcript")
        self.transcript.textChanged.connect(self.mark)
        self.stack.addWidget(self.transcript)
        lay.addWidget(self.stack, 1)
        self.on = False
        self._summary: QWidget | None = None
        self._home: tuple[QBoxLayout, int] | None = None
        self._summary_box: QPlainTextEdit | None = None
        for i, key in enumerate(KEYS):
            QShortcut(QKeySequence(key), self, lambda i=i: self.go(i) if self.on else None,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def set_on(self, on: bool, summary: QWidget, summary_box: QPlainTextEdit, home: QBoxLayout) -> None:
        """Into the mode or out of it: the Summary field (``summary``, holding ``summary_box``) moves to its tab, and back to
        its place in ``home`` when the mode goes."""
        if on == self.on:
            return
        self.on = on
        if self._summary_box is None:
            self._summary_box = summary_box
            summary_box.textChanged.connect(self.mark)
        if on:
            self._home = (home, home.indexOf(summary))
            self._was_hidden = summary.isHidden()  # outside the mode it shows once Add a summary is clicked
            self._height = summary_box.height() if summary_box.minimumHeight() == summary_box.maximumHeight() else None
            summary_box.setMinimumHeight(120)  # the tab's whole height, where outside the mode it's a few lines
            summary_box.setMaximumHeight(16_777_215)
            self.summary_layout.addWidget(summary, 1)
            summary.show()
        else:
            if self._home is not None:
                layout, at = self._home
                layout.insertWidget(max(0, at), summary)
            if getattr(self, "_height", None):
                summary_box.setFixedHeight(self._height)
            summary.setVisible(not getattr(self, "_was_hidden", True) or bool(summary_box.toPlainText().strip()))
            self.go(NOTES)
        self.bar.setVisible(on)
        self.mark()

    def go(self, i: int) -> None:
        """Show a tab, with the keyboard in it."""
        self.bar.setCurrentIndex(i)
        self._show(i)
        target = {SUMMARY: self._summary_box, TRANSCRIPT: self.transcript}.get(i) or self.stack.widget(NOTES)
        target.setFocus()

    def current(self) -> int:
        return self.stack.currentIndex()

    def _show(self, i: int) -> None:
        self.stack.setCurrentIndex(i)

    def mark(self) -> None:
        """A dot after the name of Summary and Transcript while they hold text."""
        texts = {SUMMARY: self._summary_box.toPlainText() if self._summary_box else "", TRANSCRIPT: self.transcript.toPlainText()}
        for i, text in texts.items():
            self.bar.setTabText(i, NAMES[i] + (DOT if text.strip() else ""))

    def transcript_text(self) -> str:
        """The transcript, while the mode is on; "" outside it."""
        return self.transcript.toPlainText() if self.on else ""

    def clear(self) -> None:
        self.transcript.clear()
