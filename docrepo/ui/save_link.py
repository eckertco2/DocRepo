"""Save or link (release 5.145, the save or link plan's decisions 627 to 633): the two drop zones, and each file row's
**Saved · Linked** switch.

While files from File Explorer are dragged over the capture window, the pinned window or Find files, a cover over the
window shows two zones side by side, each the cover's height: **Save in DocRepo** on the left ("A file of its own, in
the task's Files folder") and **Link** on the right ("DocRepo notes where it is and reads it there"). The zone under the
pointer is lit in the accent colour; the other stays outlined. A file dropped on Save becomes a saved file, a file of
DocRepo's own; one dropped on Link is a linked file, read where it is. A folder isn't copied, so a drag of folders alone
shows Save as not taking them, and a folder dropped there is linked (decision 628). The cover goes when the drag
leaves or drops.

Only drags with a place on disk get the zones (``read_drop``'s "files"): a web link is a link, and an email from Outlook,
an attachment dragged out of an email or a file in a zip folder has no place to link to, so DocRepo's own drop target
(``ui/drop_target.py``) takes it as before, and it's saved.

The switch (decision 630) is in Save a copy's old place on a row: set by the zone the file was dropped on, or by
Attach's Save files… or Link files…, and a click changes it until Save. A folder's and a web link's say Linked, and an
email attachment's Saved, and can't change.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from docrepo.ui.tokens import C

SAVE, LINK = "save", "link"
#: Each zone's title and the line under it (decision 627).
ZONE_WORDS = {SAVE: ("Save in DocRepo", "A file of its own, in the task's Files folder"),
              LINK: ("Link", "DocRepo notes where it is and reads it there")}
#: The Save zone's words while only folders are dragged: they're linked wherever they land (decision 628).
FOLDERS_WORDS = ("Save in DocRepo", "A folder isn't copied: it's linked")
SAVED_TIP = "Saved: a file of its own, in the task's Files folder. DocRepo doesn't go back to where it came from."
LINKED_TIP = "Linked: DocRepo notes where it is and reads it there."


def zone_at(width: int, x: float) -> str:
    """Which zone a point is in: the left half saves, the right half links."""
    return SAVE if x < width / 2 else LINK


def all_folders(paths: list[str]) -> bool:
    """Whether every path is a folder, so the drag has nothing to save. Asked once, as the drag comes in."""
    try:
        return bool(paths) and all(Path(p).is_dir() for p in paths)
    except OSError:
        return False


class SaveLinkZones(QWidget):
    """The cover with the two zones, over ``parent`` below ``top`` px. ``dropped(zone, paths)`` gets a drop's files, after
    the cover has gone. ``compact`` draws it for the pinned window, smaller."""

    def __init__(self, parent: QWidget, dropped: Callable[[str, list[str]], None], top: int = 0, compact: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("saveLinkZones")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.dropped_to = dropped
        self.top = top
        self.lit: str = ""
        self.folders = False
        pad = 4 if compact else 10
        lay = QHBoxLayout(self)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(pad)
        self.zones: dict[str, QFrame] = {}
        self.titles: dict[str, QLabel] = {}
        self.lines: dict[str, QLabel] = {}
        for key in (SAVE, LINK):
            zone = QFrame(objectName="zone")
            zone.setProperty("zone", key)
            zl = QVBoxLayout(zone)
            zl.setContentsMargins(6, 6, 6, 6)
            zl.setSpacing(4 if compact else 6)
            zl.addStretch()
            title, line = QLabel(objectName="zoneTitle"), QLabel(objectName="zoneLine")
            for label in (title, line):
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setWordWrap(True)
                zl.addWidget(label)
            zl.addStretch()
            lay.addWidget(zone, 1)
            self.zones[key], self.titles[key], self.lines[key] = zone, title, line
        size = (11, 8) if compact else (16, 10)  # the title and the line under it, in points
        self.setStyleSheet(
            f"QWidget#saveLinkZones {{ background: {C.content}; }}"
            f"QFrame#zone {{ background: {C.content}; border: 2px dashed {C.control}; border-radius: 8px; }}"
            f"QFrame#zone[lit=\"true\"] {{ background: {C.info_bg}; border: 2px solid {C.accent}; }}"
            # Folders alone: Save doesn't take them, so it never lights, even under the pointer (decision 628).
            f"QFrame#zone[off=\"true\"] {{ background: {C.base}; border: 2px dashed {C.stroke_strong}; }}"
            f"QLabel#zoneTitle {{ font-size: {size[0]}pt; font-weight: 600; color: {C.text}; background: transparent; border: none; }}"
            f"QFrame#zone[lit=\"true\"] QLabel#zoneTitle {{ color: {C.accent}; }}"
            f"QFrame#zone[off=\"true\"] QLabel#zoneTitle {{ color: {C.text2}; }}"
            f"QLabel#zoneLine {{ font-size: {size[1]}pt; color: {C.text2}; background: transparent; border: none; }}")
        self.hide()

    # ---- showing it ----
    def cover(self, paths: list[str]) -> None:
        """Put the zones up for a drag of these paths, neither lit until the pointer is over one."""
        self.folders = all_folders(paths)
        for key in (SAVE, LINK):
            title, line = FOLDERS_WORDS if key == SAVE and self.folders else ZONE_WORDS[key]
            self.titles[key].setText(title)
            self.lines[key].setText(line)
            self.zones[key].setProperty("off", key == SAVE and self.folders)
            self.zones[key].setAccessibleName(f"{title}: {line}")
        parent = self.parentWidget()
        self.setGeometry(0, self.top, parent.width(), max(0, parent.height() - self.top))
        self.light("")
        self.show()
        self.raise_()

    def uncover(self) -> None:
        self.light("")
        self.hide()

    def light(self, zone: str) -> None:
        """Light the zone under the pointer in the accent colour; the other stays outlined."""
        self.lit = zone
        for key, frame in self.zones.items():
            frame.setProperty("lit", key == zone)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
            for label in (self.titles[key], self.lines[key]):
                label.style().unpolish(label)
                label.style().polish(label)

    def zone_at(self, point: QPoint) -> str:
        """The zone at a point of the cover."""
        return zone_at(self.width(), point.x())

    # ---- the drag, once the cover is up ----
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's name
        from docrepo.ui.capture_window import _accept_copy, read_drop

        if read_drop(event.mimeData())[0] == "files":
            _accept_copy(event)
            self.light(self.zone_at(event.position().toPoint()))
        else:
            self.uncover()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        from docrepo.ui.capture_window import _accept_copy

        _accept_copy(event)
        zone = self.zone_at(event.position().toPoint())
        if zone != self.lit:
            self.light(zone)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.uncover()

    def dropEvent(self, event) -> None:  # noqa: N802
        from docrepo.ui.capture_window import _accept_copy, note_drag, read_drop

        note_drag("drop", event.mimeData())
        kind, paths = read_drop(event.mimeData())
        zone = self.zone_at(event.position().toPoint())
        self.uncover()
        if kind == "files":
            _accept_copy(event)
            self.dropped_to(zone, paths)


class SaveLinkSwitch(QWidget):
    """A file row's **Saved · Linked** switch (decision 630): two halves, one checked. ``fixed`` ones can't change: a
    folder's and a web link's say Linked, an email attachment's Saved. ``changed`` follows a click."""

    changed = Signal(bool)

    def __init__(self, saved: bool, fixed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("saveLink")
        self.fixed = fixed
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[bool, QToolButton] = {}
        for on, text, tip in ((True, "Saved", SAVED_TIP), (False, "Linked", LINKED_TIP)):
            b = QToolButton(objectName="seg", text=text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setAccessibleName(f"{text}: {tip.split(': ', 1)[1]}")
            b.setProperty("end", "left" if on else "right")
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[on] = b
        self.buttons[saved].setChecked(True)
        self.group.buttonClicked.connect(lambda _b: self.changed.emit(self.saved()))
        self.setStyleSheet(
            f"QToolButton#seg {{ border: 1px solid {C.control}; background: {C.content}; color: {C.text2}; padding: 1px 8px; }}"
            "QToolButton#seg[end=\"left\"] { border-top-left-radius: 9px; border-bottom-left-radius: 9px; border-right: none; }"
            "QToolButton#seg[end=\"right\"] { border-top-right-radius: 9px; border-bottom-right-radius: 9px; }"
            f"QToolButton#seg:checked {{ background: {C.info_bg}; color: {C.accent}; border-color: {C.accent}; font-weight: 600; }}"
            f"QToolButton#seg:disabled {{ color: {C.text2}; }}"
            f"QToolButton#seg:checked:disabled {{ color: {C.text2}; background: {C.hover}; border-color: {C.stroke_strong}; }}")
        if fixed:
            self.setToolTip(SAVED_TIP if saved else LINKED_TIP)
            for b in self.buttons.values():
                b.setEnabled(False)

    def saved(self) -> bool:
        return self.buttons[True].isChecked()

    def set_saved(self, on: bool) -> None:
        """Set it, as a draft or "Use the first file's…" does; a fixed one stays as it is."""
        if not self.fixed:
            self.buttons[on].setChecked(True)

    def setEnabled(self, on: bool) -> None:  # noqa: N802 - Qt's name: a fixed switch stays as it is
        super().setEnabled(on if not self.fixed else True)
        if self.fixed:
            for b in self.buttons.values():
                b.setEnabled(False)
