"""A navigation wheel's window (release 5.41; ``docs/ui-design/wheel-design.md``, section 2): its drawing and its keys.

Frameless, always on top, with no taskbar entry, translucent, made once at start-up and shown or hidden, so it opens at
once. It takes keys straight away, and the whole wheel shows at once (decision 175 as the owner changed it, release 5.43.1),
unless ``draw_ms`` in the config asks it to wait with only its centre showing, so that a pick made by then never shows it.
The decisions about keys are ``docrepo/wheel.py``'s; this holds only what needs Qt.
"""
from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import tinted
from docrepo.wheel import ARROWS, DIAGONALS, DIGITS, DIRECTIONS, NUMPAD, Session, Step
from docrepo.wheels_config import Slot, Timing, Wheel

SIZE = 380
OUTER, INNER = 184, 60
#: A wedge's angle in Qt's terms: 0 at three o'clock, counter-clockwise.
ANGLE = {"N": 90, "NE": 45, "E": 0, "SE": 315, "S": 270, "SW": 225, "W": 180, "NW": 135}
ARROW_KEYS = {Qt.Key.Key_Up: "U", Qt.Key.Key_Right: "R", Qt.Key.Key_Down: "D", Qt.Key.Key_Left: "L"}
#: The numpad's keys with NumLock off, as digits; with it on they arrive as digits already.
NUMPAD_NAV = {Qt.Key.Key_Up: 8, Qt.Key.Key_PageUp: 9, Qt.Key.Key_Right: 6, Qt.Key.Key_PageDown: 3, Qt.Key.Key_Down: 2,
              Qt.Key.Key_End: 1, Qt.Key.Key_Left: 4, Qt.Key.Key_Home: 7, Qt.Key.Key_Clear: 5}
POLL_MS = 15


@dataclass(frozen=True)
class Pick:
    """What was picked, for the wheel's owner to run and log."""

    wheel: Wheel
    direction: str
    slot: Slot
    how: str  # "arrows" or "numpad"
    drawn: bool
    pick_ms: int


def _high_contrast() -> bool:
    """Windows' high contrast (SPI_GETHIGHCONTRAST, bit HCF_HIGHCONTRASTON)."""
    if os.name != "nt":
        return False

    class HighContrast(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint), ("lpszDefaultScheme", ctypes.c_wchar_p)]

    info = HighContrast()
    info.cbSize = ctypes.sizeof(HighContrast)
    return bool(ctypes.windll.user32.SystemParametersInfoW(0x0042, info.cbSize, ctypes.byref(info), 0) and info.dwFlags & 1)


def animations_on() -> bool:
    """Windows' "Animation effects" (SPI_GETCLIENTAREAANIMATION)."""
    if os.name != "nt":
        return True
    on = ctypes.c_int(1)
    return bool(ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0) and on.value)


def colours() -> dict[str, str]:
    """The wheel's colours: Windows' own under high contrast, otherwise light or dark as Windows is set."""
    if _high_contrast():
        get = ctypes.windll.user32.GetSysColor

        def sys(index: int) -> str:
            v = get(index)
            return f"#{v & 255:02x}{v >> 8 & 255:02x}{v >> 16 & 255:02x}"

        window, text, lit, on_lit, grey = sys(5), sys(8), sys(13), sys(14), sys(17)
        return {"content": window, "base": window, "stroke_strong": text, "text": text, "text2": text, "disabled": grey, "accent": lit, "on_accent": on_lit}
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return tokens.DARK if dark else tokens.LIGHT


class WheelWindow(QWidget):
    """One window, for every wheel. ``on_pick`` runs a pick; ``on_cancel`` is told it closed with nothing picked (and
    whether the keyboard should go back to the window you were in); ``on_palette`` is Ctrl+K's way out."""

    def __init__(self, on_pick: Callable[[Pick], None], on_cancel: Callable[[bool], None], on_palette: Callable[[Wheel], None]) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.on_pick, self.on_cancel, self.on_palette = on_pick, on_cancel, on_palette
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(SIZE, SIZE)
        self.setObjectName("wheel")
        self.clock: Callable[[], int] = lambda: int(time.perf_counter() * 1000)
        #: Whether the hotkey that opened the wheel is still down. None when no hotkey opened it.
        self.hotkey_held: Callable[[], bool] | None = None
        self.wheel: Wheel | None = None
        self.timing = Timing()
        self.session: Session | None = None
        self.numpad: str | None = None  # the numpad digit held, as a direction: numpad keys don't chord
        self.lit: str | None = None
        self.note = ""  # the centre's second line, in place of "Esc cancels"
        self.waiting: str | None = None  # a slot marked confirm, waiting for Enter
        self.ring = 0.0
        self.opened_at = 0
        self._was_active = False
        self._icons: dict[tuple[str, str, float], QPixmap] = {}
        self._draw_timer = QTimer(self, singleShot=True, timeout=self.draw_ring)
        self._idle_timer = QTimer(self, singleShot=True, timeout=lambda: self.cancel(True))
        self._grace_timer = QTimer(self, singleShot=True, timeout=self._grace_over)
        self._poll = QTimer(self, interval=POLL_MS, timeout=self._read_hotkey)
        self._fade = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._fade.valueChanged.connect(self._faded)
        self.winId()  # the window exists from the start, so showing it is quick

    # ---- opening and closing ----
    def prepare(self, wheels: Iterable[Wheel]) -> None:
        """Paint each wheel once, unseen, so its fonts and icons are ready and the first opening is as quick as the rest."""
        if self.session is not None:
            return
        for wheel in wheels:
            self.wheel, self.ring = wheel, 1.0
            self.grab()
        self.wheel, self.ring = None, 0.0

    def open_wheel(self, wheel: Wheel, timing: Timing, centre: QPointF, hotkey_held: Callable[[], bool] | None) -> None:
        """Show ``wheel`` centred at ``centre``: do the least first, because a key pressed before it's in front goes to the
        other program."""
        self.wheel, self.timing, self.hotkey_held = wheel, timing, hotkey_held
        self.opened_at = self.clock()
        self.session = Session(self.opened_at, timing.tap_ms, timing.release_grace_ms)
        if hotkey_held is None:
            self.session.hotkey_down = False  # opened with no hotkey (the palette): it stays until a pick or a cancel
            self.session.tapped = True
        self.lit, self.numpad, self.waiting, self.note = None, None, None, ""
        self._draw_timer.stop()
        self._fade.stop()
        self.ring = 0.0 if timing.draw_ms > 0 else 1.0  # before it's shown, so its first paint has the whole wheel
        self._was_active = False
        self.move(round(centre.x() - SIZE / 2), round(centre.y() - SIZE / 2))
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.setAccessibleName(f"{wheel.name} wheel")
        self._idle_timer.start(timing.idle_ms)
        if timing.draw_ms > 0:
            self._draw_timer.start(timing.draw_ms)
        if hotkey_held is not None:
            self._poll.start()
            self._read_hotkey()  # a tap may already have been released before the wheel was in front
        self.update()

    def draw_ring(self) -> None:
        """The ring, when ``draw_ms`` asked it to wait: fading in unless Windows' animation effects are off."""
        if self.timing.animation_ms > 0 and animations_on():
            self._fade.stop()
            self._fade.setDuration(self.timing.animation_ms)
            self._fade.start()
        else:
            self.ring = 1.0
            self.update()

    def _faded(self, value: float) -> None:
        self.ring = float(value)
        self.update()

    def _stop(self) -> None:
        for t in (self._draw_timer, self._idle_timer, self._grace_timer, self._poll):
            t.stop()
        self._fade.stop()
        self.session = None

    def _close(self) -> None:
        self._stop()
        self.hide()

    def cancel(self, give_back: bool = True) -> None:
        """The keyboard goes back while the wheel still has the foreground, so Windows allows it. Then it hides."""
        if self.session is not None:
            self._stop()
            self.on_cancel(give_back)
            self.hide()

    def is_open(self) -> bool:
        return self.session is not None

    # ---- what the keys do ----
    def _read_hotkey(self) -> None:
        """While a wheel is open, and only then, a short timer reads the hotkey's own keys."""
        if self.session is None or self.hotkey_held is None or self.hotkey_held():
            return
        self._poll.stop()
        self.hotkey_up()

    def hotkey_up(self) -> None:
        if self.session is None:
            return
        answer = self.session.hotkey_up(self.clock())
        if answer == "cancel" and self.numpad is not None:  # a numpad key still down: it commits as it comes up, as an arrow does
            self.session.let_go = True
        elif answer == "cancel":
            self.cancel(True)

    def _shown_direction(self, direction: str | None) -> str | None:
        """On a cross (decision 170), a two-arrow chord selects nothing."""
        if direction in DIAGONALS and self.wheel is not None and not self.wheel.eight_way:
            return None
        return direction

    def _apply(self, step: Step, how: str) -> None:
        self.note = ""
        self.lit = self._shown_direction(step.lit)
        if step.wait is not None:
            self._grace_timer.start(max(1, step.wait))
        if step.commit is not None:
            self._commit(self._shown_direction(step.commit), how)
        elif step.released and self.session is not None and self.session.ended_with_nothing():
            self.cancel(True)
        self.update()

    def _grace_over(self) -> None:
        if self.session is not None:
            self._apply(self.session.tick(self.clock()), "arrows")

    def _commit(self, direction: str | None, how: str) -> None:
        wheel, session = self.wheel, self.session
        if wheel is None or session is None:
            return
        slot = wheel.slots.get(direction) if direction else None
        if slot is None or slot.held:
            self.lit = None
            self.note = "Later" if slot is not None else "Nothing there" if direction else ""
            if session.ended_with_nothing():
                self.cancel(True)
            return
        if slot.confirm and self.waiting != direction:
            self.waiting = direction
            self.lit = direction
            self.note = "Enter to run"
            return
        self._run(direction, slot, how)

    def _run(self, direction: str, slot: Slot, how: str) -> None:
        """The command runs while the wheel still has the foreground, so Windows lets the window it opens come to the front.
        Then the wheel hides, even if the command waits on a dialog."""
        wheel = self.wheel
        drawn = self.ring > 0
        pick_ms = self.clock() - self.opened_at
        self._stop()
        QTimer.singleShot(0, self._hide_unless_open)
        self.on_pick(Pick(wheel, direction, slot, how, drawn, pick_ms))

    def _hide_unless_open(self) -> None:
        if self.session is None:  # the command may have opened a wheel again
            self.hide()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - every key is the wheel's while it's open
        if self.session is None:
            return
        if event.isAutoRepeat():
            return
        self._idle_timer.start(self.timing.idle_ms)
        key = Qt.Key(event.key())
        keypad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
        digit = None
        if keypad:
            digit = NUMPAD_NAV.get(key)
            if digit is None and Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
                digit = key - Qt.Key.Key_0
        if digit == 5:
            self.cancel(True)
        elif digit in NUMPAD:
            self.waiting = None if self.waiting != NUMPAD[digit] else self.waiting
            self.numpad = self._shown_direction(NUMPAD[digit])
            self.lit, self.note = self.numpad, ""
            self.update()
        elif key in ARROW_KEYS and not keypad:
            if self.waiting:
                self.waiting = None
            self._apply(self.session.arrow_down(ARROW_KEYS[key], self.clock()), "arrows")
        elif key == Qt.Key.Key_Escape:
            self.cancel(True)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._enter()
        elif key == Qt.Key.Key_K and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            wheel = self.wheel
            self._close()
            self.on_palette(wheel)
        # Every other key is swallowed: the wheel has the focus, and nothing else should get it.

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self.session is None or event.isAutoRepeat():
            return
        key = Qt.Key(event.key())
        keypad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
        if keypad and self.numpad is not None:
            direction, self.numpad = self.numpad, None
            self._commit(direction, "numpad")
            if self.session is not None and self.session.let_go and self.waiting is None:
                self.cancel(True)  # a hold that's over, on an empty slot
            self.update()
        elif key in ARROW_KEYS and not keypad:
            self._apply(self.session.arrow_up(ARROW_KEYS[key], self.clock()), "arrows")

    def _enter(self) -> None:
        """Enter commits what's lit while an arrow is held, and confirms a slot marked confirm."""
        wheel = self.wheel
        target = self.waiting or self.lit
        if wheel is None or target is None:
            return
        slot = wheel.slots.get(target)
        if slot is None or slot.held:
            self._commit(target, "arrows")
            self.update()
            return
        self._run(target, slot, "arrows")

    def changeEvent(self, event) -> None:  # noqa: N802 - losing the focus cancels
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.session is not None:
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active:
                self.cancel(False)  # you clicked somewhere else: the keyboard's already there

    # ---- drawing ----
    def _icon(self, name: str, colour: str) -> QPixmap:
        key = (name, colour, self.devicePixelRatioF())  # prepare paints on one monitor, and it may open on another
        if key not in self._icons:
            self._icons[key] = tinted(name, colour, 20, key[2])
        return self._icons[key]

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self.wheel is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        c = colours()
        mid = QPointF(SIZE / 2, SIZE / 2)
        if self.ring > 0:
            p.setOpacity(self.ring)
            self._draw_slots(p, c, mid)
            p.setOpacity(1.0)
        self._draw_centre(p, c, mid)
        p.end()

    def _draw_slots(self, p: QPainter, c: dict[str, str], mid: QPointF) -> None:
        wheel = self.wheel
        directions = DIRECTIONS if wheel.eight_way else DIRECTIONS[::2]
        span = 360 / len(directions)
        rim = QColor(c["text"])
        rim.setAlpha(24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rim)
        p.drawEllipse(mid, OUTER + 4, OUTER + 4)
        label_at = (OUTER + INNER) / 2 + (6 if wheel.eight_way else 0)
        width = 96 if wheel.eight_way else 112
        for d in directions:
            slot = wheel.slots.get(d)
            lit = d == self.lit
            usable = slot is not None and not slot.held
            fill = c["accent"] if lit else c["content"] if usable else c["base"]
            p.setPen(QPen(QColor(c["stroke_strong"]), 1))
            p.setBrush(QColor(fill))
            p.drawPath(_wedge(mid, INNER + 4, OUTER, ANGLE[d] - span / 2 + 1.2, span - 2.4))
            if slot is None:
                continue
            ink = c["on_accent"] if lit else c["text"] if usable else c["disabled"]
            quiet = c["on_accent"] if lit else c["text2"] if usable else c["disabled"]
            at = _at(mid, label_at, ANGLE[d])
            top = at.y() - 32
            if slot.icon:
                p.drawPixmap(QPointF(at.x() - 10, top), self._icon(slot.icon, ink))
            p.setPen(QColor(ink))
            p.setFont(_font(tokens.CAPTION + 0.5, bold=lit))
            p.drawText(QRectF(at.x() - width / 2, top + 22, width, 30), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                       slot.label)
            p.setPen(QColor(quiet))
            p.setFont(_font(tokens.CAPTION - 0.5))
            hint = "later" if slot.held else f"{ARROWS[d]}  {DIGITS[d]}"
            p.drawText(QRectF(at.x() - width / 2, top + 50, width, 16), Qt.AlignmentFlag.AlignHCenter, hint)

    def _draw_centre(self, p: QPainter, c: dict[str, str], mid: QPointF) -> None:
        halo = QColor(c["text"])
        halo.setAlpha(36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(mid, INNER + 3, INNER + 3)
        p.setPen(QPen(QColor(c["stroke_strong"]), 1))
        p.setBrush(QColor(c["content"]))
        p.drawEllipse(mid, INNER, INNER)
        p.setPen(QColor(c["text"]))
        p.setFont(_font(tokens.BODY, bold=True))
        box = QRectF(mid.x() - INNER + 6, mid.y() - 24, 2 * INNER - 12, 26)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.wheel.name)
        p.setPen(QColor(c["text2"]))
        p.setFont(_font(tokens.CAPTION - 0.5))
        p.drawText(QRectF(mid.x() - INNER + 6, mid.y() + 2, 2 * INNER - 12, 18), Qt.AlignmentFlag.AlignCenter, self.note or "Esc cancels")


def _font(size: float, bold: bool = False) -> QFont:
    font = QFont()
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def _at(mid: QPointF, radius: float, angle: float) -> QPointF:
    path = QPainterPath()
    path.arcMoveTo(QRectF(mid.x() - radius, mid.y() - radius, 2 * radius, 2 * radius), angle)
    return path.currentPosition()


def _wedge(mid: QPointF, inner: float, outer: float, start: float, span: float) -> QPainterPath:
    box = QRectF(mid.x() - outer, mid.y() - outer, 2 * outer, 2 * outer)
    hole = QRectF(mid.x() - inner, mid.y() - inner, 2 * inner, 2 * inner)
    path = QPainterPath()
    path.arcMoveTo(box, start)
    path.arcTo(box, start, span)
    path.arcTo(hole, start + span, -span)
    path.closeSubpath()
    return path
