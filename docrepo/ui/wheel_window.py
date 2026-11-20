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
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from docrepo.ui import tokens
from docrepo.ui.icons import tinted
from docrepo.wheel import ARROWS, DIAGONALS, DIGITS, DIRECTIONS, NUMPAD, Session, Step
from docrepo.wheels_config import Slot, Timing, Wheel

SIZE = 380
#: The disc and the hub (release 5.190, the redesign's decision 865): one disc inside the window, with room round it for the
#: shadow it paints itself, and a hub 116 px across.
OUTER, INNER = 170, 58
SHADOW = 20  # the room outside the disc: (SIZE / 2) - OUTER
#: The shadows' strength, as alpha out of 255: the disc's, and the hub's, which is smaller.
SHADOW_ALPHA, HUB_SHADOW_ALPHA = 46, 20
#: A label's width at its radius: an eight-way wedge is about 92 px across there, a four-way one wider.
LABEL_WIDTH = {True: 92, False: 112}
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
    """The wheel's colours: Windows' own under high contrast, otherwise light or dark as the colour scheme Qt has says, which
    ``style.apply_look`` sets from the theme (release 5.180), so the wheel follows the theme."""
    if _high_contrast():
        get = ctypes.windll.user32.GetSysColor

        def sys(index: int) -> str:
            v = get(index)
            return f"#{v & 255:02x}{v >> 8 & 255:02x}{v >> 16 & 255:02x}"

        window, text, lit, on_lit, grey = sys(5), sys(8), sys(13), sys(14), sys(17)
        return {"content": window, "base": window, "stroke": text, "stroke_strong": text, "text": text, "text2": text, "text3": text,
                "disabled": grey, "accent": lit, "on_accent": on_lit, "selected": lit, "contrast": "1"}
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return tokens.THEMES["dark" if dark else "light"]


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
        """One disc on a soft shadow, the wedge under the pointer in the selected tint, hairline spokes, then each slot: its
        icon, its label on at most two lines, and its keys (release 5.190, decision 865)."""
        wheel = self.wheel
        directions = DIRECTIONS if wheel.eight_way else DIRECTIONS[::2]
        span = 360 / len(directions)
        contrast = "contrast" in c
        if not contrast:  # the window is translucent and round, so it draws its own shadow: Windows can't
            _shadow(p, c, mid, OUTER, SHADOW, SHADOW_ALPHA, 6)
        p.setPen(QPen(QColor(c["stroke_strong"]), 1))
        p.setBrush(QColor(c["content"]))
        p.drawEllipse(mid, OUTER, OUTER)
        if self.lit in directions:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent"] if contrast else c["selected"]))
            p.drawPath(_wedge(mid, INNER, OUTER, ANGLE[self.lit] - span / 2, span))
        p.setPen(QPen(QColor(c["stroke"]), 1))
        for d in directions:  # a spoke on each boundary between two directions
            edge = ANGLE[d] + span / 2
            p.drawLine(_at(mid, INNER, edge), _at(mid, OUTER, edge))
        label_at = (OUTER + INNER) / 2 + 6
        width = LABEL_WIDTH[wheel.eight_way]
        for d in directions:
            slot = wheel.slots.get(d)
            if slot is None:  # an empty slot is left plain
                continue
            lit = d == self.lit
            usable = not slot.held
            if contrast and lit:
                ink = icon_ink = quiet = c["on_accent"]
            else:
                ink = c["accent"] if lit else c["text"] if usable else c["disabled"]
                icon_ink = c["accent"] if lit else c["text2"] if usable else c["disabled"]
                quiet = c["text3"] if usable else c["disabled"]
            at = _at(mid, label_at, ANGLE[d])
            if slot.icon:
                p.drawPixmap(QPointF(at.x() - 10, at.y() - 30), self._icon(slot.icon, icon_ink))
            font = _label_font(slot.label, width, lit)
            line = QFontMetrics(font).lineSpacing()
            p.setPen(QColor(ink))
            p.setFont(font)
            box = QRectF(at.x() - width / 2, at.y() - 6, width, 2 * line + 2)
            p.drawText(box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                       _two_lines(slot.label, font, width))
            p.setPen(QColor(quiet))
            p.setFont(tokens.ui_font(tokens.LABEL))
            hint = "later" if slot.held else f"{ARROWS[d]}  {DIGITS[d]}"
            p.drawText(QRectF(at.x() - width / 2, box.bottom(), width, 16), Qt.AlignmentFlag.AlignHCenter, hint)

    def _draw_centre(self, p: QPainter, c: dict[str, str], mid: QPointF) -> None:
        """The hub: a disc of its own on a small shadow, the wheel's name, and the note or "Esc cancels"."""
        if "contrast" not in c:
            _shadow(p, c, mid, INNER, 4, HUB_SHADOW_ALPHA, 2)
        p.setPen(QPen(QColor(c["stroke_strong"]), 1))
        p.setBrush(QColor(c["content"]))
        p.drawEllipse(mid, INNER, INNER)
        p.setPen(QColor(c["text"]))
        p.setFont(tokens.ui_font(tokens.VIEW_TITLE, semibold=True))
        box = QRectF(mid.x() - INNER + 6, mid.y() - 24, 2 * INNER - 12, 26)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.wheel.name)
        p.setPen(QColor(c["text3"]))
        p.setFont(tokens.ui_font(tokens.LABEL))
        p.drawText(QRectF(mid.x() - INNER + 6, mid.y() + 2, 2 * INNER - 12, 18), Qt.AlignmentFlag.AlignCenter, self.note or "Esc cancels")


def _shadow(p: QPainter, c: dict[str, str], mid: QPointF, radius: float, spread: float, alpha: int, drop: float) -> None:
    """A soft shadow under a disc: the text's colour at ``alpha`` inside the disc, fading out over ``spread``, ``drop`` lower."""
    centre = QPointF(mid.x(), mid.y() + drop)
    gradient = QRadialGradient(centre, radius + spread)
    dark, clear = QColor(c["text"]), QColor(c["text"])
    dark.setAlpha(alpha)
    clear.setAlpha(0)
    gradient.setColorAt(0.0, dark)
    gradient.setColorAt(radius / (radius + spread), dark)
    gradient.setColorAt(1.0, clear)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawEllipse(centre, radius + spread, radius + spread)


#: The smallest a label goes to fit its two lines.
LABEL_SMALLEST = tokens.LABEL - 1


def _lines(font: QFont, width: float, text: str) -> int:
    fm = QFontMetrics(font)
    height = fm.boundingRect(0, 0, int(width), 1000, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, text).height()
    return round(height / fm.lineSpacing())


def _label_font(text: str, width: float, lit: bool) -> QFont:
    """A slot's label at the caption size, semibold when lit, a half point smaller at a time while it takes more than two
    lines at ``width``, down to ``LABEL_SMALLEST``."""
    size = tokens.CAPTION
    font = tokens.ui_font(size, semibold=lit)
    while _lines(font, width, text) > 2 and size > LABEL_SMALLEST:
        size -= 0.5
        font = tokens.ui_font(size, semibold=lit)
    return font


def _two_lines(text: str, font: QFont, width: float) -> str:
    """The label as it's drawn: whole when it fits two lines, else its second line cut with an ellipsis (one unbroken long
    word at the smallest size; no default wheel's label gets here)."""
    if _lines(font, width, text) <= 2:
        return text
    fm = QFontMetrics(font)
    words, first = text.split(), ""
    for i, word in enumerate(words):
        trial = f"{first} {word}".strip()
        if fm.horizontalAdvance(trial) > width and first:
            rest = " ".join(words[i:])
            return f"{first}\n{fm.elidedText(rest, Qt.TextElideMode.ElideRight, int(width))}"
        first = trial
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, int(2 * width))


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
