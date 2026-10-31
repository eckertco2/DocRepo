"""The Capture wheel's "Email or file" (release 5.42; ``docs/ui-design/wheel-design.md``, section 5): the pinned window, with
what's selected in the window you were in. Each read hands over exactly as a drop does: files through ``add_paths``, emails
through ``_read_emails``, so each gets its description, Save a copy and Extract boxes, and an email gets layer 0's rows.

Nothing here freezes DocRepo. File Explorer is read on a thread of its own, and only paths come back. Outlook is asked a
simple question on a thread of its own first: while a dialog is open in Outlook that question waits there, and after 3 s the
pinned window says so. Once Outlook answers, even late, the email joins the capture through the mail button's own read.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from docrepo import outlook, selection
from docrepo.selection import Selected, Snapshot

if TYPE_CHECKING:
    from docrepo.ui.capture_window import CaptureWindow

log = logging.getLogger(__name__)

SLOW_MS = 3000
DRAG_IT = "Drag it here."
SLOW_OUTLOOK = "A dialog may be open in Outlook. The email joins this capture once Outlook answers."


class _Answer(QObject):
    """Carries a worker thread's answer back to the window's thread."""

    done = Signal(object)


def off_thread(work: Callable[[], object], done: Callable[[object], None], parent: QObject) -> None:
    """Run ``work`` on a thread of its own, and ``done`` with its answer on this one."""
    answer = _Answer(parent)
    answer.done.connect(lambda result: (done(result), answer.deleteLater()))
    threading.Thread(target=lambda: answer.done.emit(work()), name="DocRepo selection", daemon=True).start()


def outlook_answers() -> object:
    """Ask Outlook something simple. Whatever goes wrong is for the read that follows to report, in its own words."""
    try:
        import pythoncom  # noqa: PLC0415 - only where Windows has it
    except ImportError:
        return None
    pythoncom.CoInitialize()
    try:
        app, _how = outlook.connect()
        app.ActiveWindow()
        del app
    except Exception as e:  # noqa: BLE001 - reported by the read that follows
        log.info("Outlook's first answer: %s", type(e).__name__)
    finally:
        pythoncom.CoUninitialize()
    return None


def capture_selection(capture: CaptureWindow, snap: Snapshot | None) -> None:
    """The pinned window, joined by what's selected. With nothing to read, it opens empty, ready for a drop."""
    if not (capture.pinned and capture.pin_window is not None and capture.pin_window.isVisible()):
        capture.pin()
    pin = capture.pin_window
    pin.show_message("")
    what = selection.plan(snap)
    if not what:
        pin.show_message(DRAG_IT)
        return
    if what == "explorer":
        off_thread(lambda: selection.read_selected(snap), lambda found: _files_arrived(capture, found), capture)
        return
    timer = QTimer(capture, singleShot=True, interval=SLOW_MS)
    timer.timeout.connect(lambda: pin.show_message(SLOW_OUTLOOK))
    timer.start()
    off_thread(outlook_answers, lambda _answer: (timer.stop(), timer.deleteLater(), _read_outlook(capture)), capture)


def _files_arrived(capture: CaptureWindow, found: Selected) -> None:
    pin = capture.pin_window
    if found.paths:
        capture.add_paths(found.paths)
    if pin is not None:
        pin.sync()
        if found.note:
            pin.show_message(found.note)


def _read_outlook(capture: CaptureWindow) -> None:
    """Outlook has answered. A selected attachment comes alone; otherwise the email in front, as the mail button reads it."""
    pin = capture.pin_window
    if pin is not None:
        pin.show_message("")
    row = None
    try:
        row = outlook.selected_attachment_row()
    except Exception as e:  # noqa: BLE001 - then read the email instead
        log.info("Outlook's selected attachment: %s", type(e).__name__)
    if row is not None:
        capture._add_file(row, "email", focus=False)
    else:
        scratch = outlook.copy_path(capture.ctx.fs, capture.ctx.data_root)
        capture._read_emails(lambda: outlook.front_emails(scratch), "adding the email in front in Outlook")
    if pin is not None:
        pin.sync()
