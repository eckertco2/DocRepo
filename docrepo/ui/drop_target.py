"""DocRepo's own drop target, for emails dragged from Outlook (the knowledge base's phase 0, decision 22; release 5.33).

An email dragged out of Outlook carries a full copy of itself, the copy File Explorer saves as a .msg file when an
email is dropped on the desktop: a list of file names (``FileGroupDescriptorW``) and each file's contents
(``FileContents``), an email's as a storage object. Qt asks for the contents as a block of memory, which Outlook
doesn't give, so DocRepo takes such drags itself, through pywin32's OLE calls. Outlook's object model isn't asked, so
its security guard never comes into it. Attachments dragged from an open email, and files inside a zip folder, come
the same way, as a name and its bytes.

Qt keeps its own drop target on each top-level window, for files, links and text. DocRepo's is on a ``DropOverlay``:
a child with a window handle of its own, which covers the capture window or the pinned window while a drag with a
file but no path on disk (``read_drop``'s "outlook" or "virtual") is over it. Windows then hands the drag to it. It
hides when the drag leaves or drops. Everything is copied into memory during the drop, and handled after the drop has
finished, so Outlook is never called back while its drag is still running. What a drop held is noted for the
troubleshooting report (``diagnose.note_drop``): format names, counts, forms and sizes, never content.
"""
from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget

from docrepo import diagnose, msg

try:
    import pythoncom
except ImportError:  # not Windows, or no pywin32: DropOverlay says it isn't available
    pythoncom = None

log = logging.getLogger(__name__)

DESCRIPTOR = "FileGroupDescriptorW"
CONTENTS = "FileContents"
DROPEFFECT_NONE, DROPEFFECT_COPY = 0, 1
#: A FILEGROUPDESCRIPTORW entry: flags, then the file's attributes at 36, its size at 64 and 68, its name at 72.
ENTRY, NAME_AT, NAME_BYTES = 592, 72, 520
EMAIL_TEXT = "Drop here: DocRepo keeps the email whole, as Outlook hands it over"
FILE_TEXT = "Drop here: DocRepo keeps the file as the program holding it hands it over"
FD_ATTRIBUTES, FD_FILESIZE, DIRECTORY = 0x04, 0x40, 0x10


@dataclass
class Dropped:
    """One file a program handed over in a drag: its name as given, its bytes, and whether it's an email (a .msg)."""

    name: str
    data: bytes
    email: bool = False


@dataclass
class DropRead:
    """What a drop held: its files, whether Outlook made the drag (its own formats), and its formats' names."""

    items: list[Dropped] = field(default_factory=list)
    outlook: bool = False
    formats: list[str] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)  # how each file came: storage, stream or memory
    problems: list[str] = field(default_factory=list)


def descriptors(raw: bytes) -> list[tuple[str, int | None, bool]]:
    """A FILEGROUPDESCRIPTORW's files: each name, its size when given, and whether it's a folder."""
    if len(raw) < 4:
        return []
    count = struct.unpack_from("<I", raw)[0]
    out = []
    for n in range(count):
        at = 4 + n * ENTRY
        if at + ENTRY > len(raw):
            break
        flags = struct.unpack_from("<I", raw, at)[0]
        attributes = struct.unpack_from("<I", raw, at + 36)[0]
        high, low = struct.unpack_from("<II", raw, at + 64)
        name = raw[at + NAME_AT:at + NAME_AT + NAME_BYTES].decode("utf-16-le", errors="replace").split("\0", 1)[0]
        out.append((name, (high << 32 | low) if flags & FD_FILESIZE else None, bool(flags & FD_ATTRIBUTES and attributes & DIRECTORY)))
    return out


def _format_names(obj) -> list[str]:
    import win32clipboard
    names = []
    try:
        for fe in obj.EnumFormatEtc(1):  # DATADIR_GET
            try:
                names.append(win32clipboard.GetClipboardFormatName(fe[0]))
            except Exception:  # noqa: BLE001 - a standard format has no registered name
                names.append(f"#{fe[0]}")
    except Exception:  # noqa: BLE001 - a drag that won't list its formats
        pass
    return names


def storage_bytes(storage) -> bytes:
    """A storage object's contents as a compound file's bytes, copied in memory: a .msg, as File Explorer would save it."""
    from win32com import storagecon as sc
    lock = pythoncom.CreateILockBytesOnHGlobal(None, True)
    copy = pythoncom.StgCreateDocfileOnILockBytes(lock, sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE | sc.STGM_CREATE, 0)
    storage.CopyTo(None, None, copy)
    copy.Commit(0)
    del copy
    return lock.ReadAt(0, lock.Stat(0)[2])


def _stream_bytes(stream) -> bytes:
    out = b""
    while True:
        chunk = stream.Read(1 << 20)
        if not chunk:
            return out
        out += chunk


def can_take(obj) -> bool:
    """Whether a drag carries files with contents, which this drop target takes."""
    names = set(_format_names(obj))
    return DESCRIPTOR in names and CONTENTS in names


def read(obj) -> DropRead:
    """Copy everything a drag's files hold into memory, during the drop. A file that can't be read is a problem, not
    the end: the rest are still taken."""
    import win32clipboard
    out = DropRead(formats=_format_names(obj))
    out.outlook = any("RenPrivate" in f for f in out.formats)
    descriptor = win32clipboard.RegisterClipboardFormat(DESCRIPTOR)
    contents = win32clipboard.RegisterClipboardFormat(CONTENTS)
    try:
        raw = obj.GetData((descriptor, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)).data
    except Exception as e:  # noqa: BLE001
        out.problems.append(f"its list of files couldn't be read ({type(e).__name__})")
        return out
    for index, (name, size, folder) in enumerate(descriptors(raw)):
        if folder:
            continue
        try:
            medium = obj.GetData((contents, None, pythoncom.DVASPECT_CONTENT, index,
                                  pythoncom.TYMED_ISTORAGE | pythoncom.TYMED_ISTREAM | pythoncom.TYMED_HGLOBAL))
            if medium.tymed == pythoncom.TYMED_ISTORAGE:
                data, form = storage_bytes(medium.data), "storage"
            elif medium.tymed == pythoncom.TYMED_ISTREAM:
                data, form = _stream_bytes(medium.data), "stream"
            else:
                data, form = bytes(medium.data), "memory"
                if size is not None:
                    data = data[:size]  # a block of memory can be longer than the file
        except Exception as e:  # noqa: BLE001 - pywin32 raises com_error, and Outlook can refuse one file
            out.problems.append(f"file {index + 1} couldn't be read ({type(e).__name__})")
            continue
        out.forms.append(form)
        out.items.append(Dropped(name, data, email=name.lower().endswith(".msg") and msg.is_msg(data)))
    return out


class DropTarget:
    """The OLE drop target (``IDropTarget``), as a pywin32 COM object. ``dropped`` gets what a drop held, after the drop."""

    _com_interfaces_ = [pythoncom.IID_IDropTarget] if pythoncom else []
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]

    def __init__(self, dropped: Callable[[DropRead], None], left: Callable[[], None]) -> None:
        self.dropped = dropped
        self.left = left
        self.ok = False

    def DragEnter(self, obj, keys, point, effect) -> int:  # noqa: N802 - OLE's names
        try:
            self.ok = can_take(obj)
        except Exception:  # noqa: BLE001 - an exception must never reach OLE
            self.ok = False
        return DROPEFFECT_COPY if self.ok else DROPEFFECT_NONE

    def DragOver(self, keys, point, effect) -> int:  # noqa: N802
        return DROPEFFECT_COPY if self.ok else DROPEFFECT_NONE

    def DragLeave(self) -> None:  # noqa: N802
        self.left()

    def Drop(self, obj, keys, point, effect) -> int:  # noqa: N802
        self.left()
        try:
            found = read(obj)
        except Exception as e:  # noqa: BLE001
            found = DropRead(problems=[f"the drop couldn't be read ({type(e).__name__})"])
        diagnose.note_drop(found.formats, found.outlook, found.forms, [len(x.data) for x in found.items], found.problems)
        QTimer.singleShot(0, lambda: self.dropped(found))  # after the drop: Outlook's drag is over by then
        return DROPEFFECT_COPY if found.items else DROPEFFECT_NONE


class DropOverlay(QLabel):
    """A cover over ``parent`` with DocRepo's own drop target, shown while a drag of files with no path on disk (an
    Outlook email, an attachment, a file in a zip folder) is over the window. ``available`` is False when the drop
    target couldn't be set up (not Windows, or no pywin32): the window then takes such drags as before."""

    def __init__(self, parent: QWidget, dropped: Callable[[DropRead], None]) -> None:
        super().__init__(EMAIL_TEXT, parent)
        self.setObjectName("dropOverlay")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet("QLabel#dropOverlay { background: #e8f0f8; border: 2px dashed #1d5e98; border-radius: 8px; color: #1d5e98; "
                           "font-weight: 600; padding: 12px; }")
        self.hide()
        self._watch = QTimer(self)
        self._watch.setInterval(400)
        self._watch.timeout.connect(self._still_dragging)
        self.target = None
        self.hwnd = 0
        self.available = False
        try:
            from PySide6.QtCore import QCoreApplication
            from win32com.server.util import wrap
            # Only this cover gets a window handle of its own; the widgets beside it stay drawn by their window.
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            self.target = wrap(DropTarget(dropped, self.uncover), pythoncom.IID_IDropTarget)
            self.hwnd = int(self.winId())
            pythoncom.RegisterDragDrop(self.hwnd, self.target)
            self.available = True
        except Exception as e:  # noqa: BLE001 - the window still works, with Qt's drops only
            log.warning("DocRepo's own drop target isn't available: %s", type(e).__name__)

    def cover(self, email: bool = True) -> None:
        """Cover the window, so the drag goes to DocRepo's own drop target, saying what it keeps: an email from Outlook,
        or a file another program holds. The cover goes when the drag leaves it or drops, or, should the drag end before
        reaching it, once no mouse button is held."""
        if not self.available:
            return
        self.setText(EMAIL_TEXT if email else FILE_TEXT)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._watch.start()

    def uncover(self) -> None:
        self._watch.stop()
        self.hide()

    def _still_dragging(self) -> None:
        import ctypes
        if not any(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000 for key in (0x01, 0x02)):  # VK_LBUTTON, VK_RBUTTON
            self.uncover()

    def release(self) -> None:
        """Take the drop target off its window handle, when the window goes."""
        if self.available:
            try:
                pythoncom.RevokeDragDrop(self.hwnd)
            except Exception:  # noqa: BLE001
                pass
            self.available = False
