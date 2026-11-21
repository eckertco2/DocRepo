"""Motion (release 5.195, the redesign's decision 870): four small animations, each under 150 ms.

- **A popup rising in:** a popup or a floating window (the palette, the task pickers, a popover, Quick edit, a confirmation)
  fades in as it rises the last few pixels to where it was put. Menus aren't touched: Windows animates them itself.
- **The toast sliding** up into place (``ui/toast.py``).
- **A tick drawing:** a checklist line's tick on a notes page wipes in as it's ticked, and a switch's knob (``Toggle``) slides.
- **The drop targets appearing:** the groups a dragged Today row can go to fade in (``DropGroups``).

An animation changes how something arrives, never where it ends or when it can be used: a popup has the keyboard the
moment it shows, a drop target takes a drop before it has faded in, and every value is the one the code set when the
animation ends or is stopped. One switch for all four, **off until DocRepo starts** (``app.run`` calls ``start``), so the
tests and the review harness, which build windows without starting DocRepo, see none; and off when Windows' "Animation
effects" are off. No animation runs on a hidden widget, and each is the child of the widget it moves, so it goes with it.
"""
from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QObject, QTimer, QVariantAnimation
from PySide6.QtWidgets import QWidget

# ---- the timings, as the tokens name sizes: each under 150 ms (decision 870) ----
POPUP_MS = 120      # a popup rising in
TOAST_MS = 140      # the toast sliding up
TICK_MS = 110       # a tick drawing, a switch's knob sliding
DROP_MS = 120       # the drop targets appearing
POPUP_RISE = 6      # how far below its place a popup starts, in px
TOAST_RISE = 12     # how far below its place the toast starts, in px
EASING = QEasingCurve.Type.OutCubic  # quick to start, settling into place
#: Floating windows that stay open for a long while, and so don't rise: the Today panel has its own widening, and the pinned
#: window sits beside the work.
RESTING = frozenset({"todayPanel", "pinWindow"})

_on = [False]
#: The name of the animation on a widget, so a new one replaces the old.
_KEY = "_motion"


def windows_animates() -> bool:
    """Windows' "Animation effects" (SPI_GETCLIENTAREAANIMATION). A test replaces this."""
    from docrepo.ui.wheel_window import animations_on

    return animations_on()


def start() -> None:
    """Turn motion on as DocRepo starts, if Windows animates. Until this is called (in the tests, the harness), it's off."""
    _on[0] = windows_animates()


def set_on(on: bool) -> None:
    """Turn motion on or off (a test's)."""
    _on[0] = on


def on() -> bool:
    """Whether animations run."""
    return _on[0]


def animate(owner: QWidget, key: str, start_value: float, end_value: float, ms: int,
            step: Callable[[float], None], done: Callable[[], None] | None = None) -> QVariantAnimation | None:
    """Run ``step`` from ``start_value`` to ``end_value`` over ``ms``, eased, as ``owner``'s animation called ``key``, then
    ``done``. With motion off or ``owner`` hidden, ``step(end_value)`` and ``done`` at once and no animation. A new one on the
    same key stops the old at its end value first, so nothing is left halfway."""
    stop(owner, key)
    if not on() or not owner.isVisible():
        step(end_value)
        if done is not None:
            done()
        return None
    anim = QVariantAnimation(owner)
    anim.setObjectName(f"{_KEY}:{key}")
    anim.setDuration(ms)
    anim.setStartValue(float(start_value))
    anim.setEndValue(float(end_value))
    anim.setEasingCurve(EASING)

    # The calls live on the owner, and the animation holds the owner only weakly: were the animation the last thing holding
    # a widget, deleting the animation would delete the widget in the middle of its own teardown, which aborts Qt.
    token = object()
    calls = getattr(owner, "_motion_calls", None)
    if calls is None:
        calls = {}
        owner._motion_calls = calls
    calls[key] = (token, step, done)
    ref = weakref.ref(owner)

    def mine() -> tuple | None:
        held = ref()
        entry = None if held is None else getattr(held, "_motion_calls", {}).get(key)
        return entry if entry is not None and entry[0] is token else None

    def finish() -> None:
        entry = mine()
        if entry is not None:
            ref()._motion_calls.pop(key, None)
            if entry[2] is not None:
                entry[2]()

    def tick(value: object) -> None:
        entry = mine()
        if entry is None:
            return
        if not ref().isVisible():  # hidden meanwhile: no frames for nobody; the end value now, and stopped once Qt is out
            entry[1](end_value)    # of this frame (stopping inside its own signal isn't safe)
            finish()
            QTimer.singleShot(0, anim, anim.stop)
            return
        entry[1](float(value))

    anim.valueChanged.connect(tick)
    anim.finished.connect(finish)
    step(float(start_value))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def running(owner: QObject, key: str) -> QVariantAnimation | None:
    """``owner``'s animation called ``key``, while it runs."""
    for found in owner.findChildren(QVariantAnimation, f"{_KEY}:{key}"):  # one that ended may wait to be deleted
        if found.state() == QAbstractAnimation.State.Running:
            return found
    return None


def stop(owner: QObject, key: str) -> None:
    """End ``owner``'s animation called ``key`` at its end value, at once."""
    anim = running(owner, key)
    if anim is not None:
        anim.setCurrentTime(anim.duration())  # its last step: the value the code set
        anim.stop()


# ---- a popup rising in ----
def rises(window: QWidget) -> bool:
    """Whether a window rises in as it shows: a popup that isn't a menu, or a floating window that doesn't stay open."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    if isinstance(window, QMenu) or window.objectName() in RESTING:
        return False
    return window.windowType() == Qt.WindowType.Popup or bool(window.property("floating"))


def rise(window: QWidget) -> None:
    """Fade a window in as it rises ``POPUP_RISE`` px into the place it was put. It has the keyboard from the start; if
    something moves it meanwhile, the rise lets go and leaves it there, fully shown."""
    if not on() or not rises(window):
        return
    from PySide6.QtCore import QPoint

    stop(window, "rise")  # one already on its way ends in its place first, so that's the place read
    place = window.pos()
    state: dict = {"last": None, "left": False}

    def step(t: float) -> None:
        if not state["left"] and state["last"] is not None and window.pos() != state["last"]:
            state["left"] = True  # moved by its own code: that place wins
        if state["left"]:
            window.setWindowOpacity(1.0)
            return
        state["last"] = QPoint(place.x(), place.y() + round(POPUP_RISE * (1 - t)))
        window.move(state["last"])
        window.setWindowOpacity(t)

    animate(window, "rise", 0.0, 1.0, POPUP_MS, step)
