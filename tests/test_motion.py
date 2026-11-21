"""Motion (release 5.195, the redesign's decision 870): one switch, off under the tests and the harness and when Windows'
animation effects are off; four animations, each ending at the value the code set, none delaying a key or a drop, none
running on a hidden widget or outliving it.

Each animation's clock is driven here (``run_out``: ``setCurrentTime`` in steps, as Qt's animation timer does), not waited
for: in a long run Qt's queue can hold seconds of other tests' leftovers, and a test must read the end, never a frame."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QVBoxLayout, QWidget  # noqa: E402

from docrepo.ui import motion  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def moving(qapp):
    """Motion on for one test, and off again after it, as every other test finds it."""
    motion.set_on(True)
    yield
    motion.set_on(False)


def run_out(owner, key: str, upto: float = 1.0) -> list[float]:
    """Drive ``owner``'s running animation ``key`` through its frames to ``upto`` (1 is its end), as Qt's timer would, then
    deliver what it posted to itself (its stop, its deletion), and nothing of anyone else's. The values its frames had."""
    anim = motion.running(owner, key)
    assert anim is not None
    frames = []
    anim.valueChanged.connect(lambda v: frames.append(float(v)))
    for i in range(1, 9):
        if anim.state() != QAbstractAnimation.State.Running or i / 8 > upto:
            break
        anim.setCurrentTime(round(anim.duration() * i / 8))
    QApplication.sendPostedEvents(anim, QEvent.Type.MetaCall)
    return frames


def test_the_switch_is_off_until_docrepo_starts_and_follows_windows(monkeypatch):
    assert motion.on() is False  # the tests and the harness never call start()
    for windows in (True, False):
        monkeypatch.setattr(motion, "windows_animates", lambda w=windows: w)
        motion.start()
        assert motion.on() is windows
    motion.set_on(False)


def test_every_timing_is_under_150_ms():
    assert all(0 < ms < 150 for ms in (motion.POPUP_MS, motion.TOAST_MS, motion.TICK_MS, motion.DROP_MS))


def test_with_motion_off_a_step_jumps_to_its_end_with_no_animation(qapp):
    w = QWidget()
    w.show()
    seen, done = [], []
    assert motion.animate(w, "x", 0.0, 1.0, 100, seen.append, lambda: done.append(True)) is None
    assert seen == [1.0] and done == [True] and motion.running(w, "x") is None
    w.close()


def test_an_animation_ends_at_its_end_value_and_stop_jumps_there(qapp, moving):
    w = QWidget()
    w.show()
    seen: list[float] = []
    done: list[bool] = []
    assert motion.animate(w, "x", 0.0, 1.0, 100, seen.append, lambda: done.append(True)) is not None
    assert seen == [0.0] and motion.running(w, "x") is not None and not done
    run_out(w, "x")
    assert 0.0 < seen[1] < seen[2] < 1.0  # eased frames on the way
    assert seen[-1] == 1.0 and done == [True] and motion.running(w, "x") is None
    seen.clear()
    done.clear()
    motion.animate(w, "x", 0.0, 1.0, 100, seen.append, lambda: done.append(True))
    run_out(w, "x", upto=0.4)
    motion.stop(w, "x")
    assert seen[-1] == 1.0 and done == [True] and motion.running(w, "x") is None
    motion.animate(w, "x", 0.0, 1.0, 100, seen.append)
    motion.animate(w, "x", 0.0, 1.0, 100, seen.append)  # a new one on the key: the old ends first, at its end
    assert seen[-2:] == [1.0, 0.0] and len(w.findChildren(QAbstractAnimation)) >= 1
    run_out(w, "x")
    assert seen[-1] == 1.0
    w.close()


def test_no_animation_runs_on_a_hidden_widget_or_outlives_it(qapp, moving):
    hidden = QWidget()
    seen: list[float] = []
    assert motion.animate(hidden, "x", 0.0, 1.0, 100, seen.append) is None and seen == [1.0]
    w = QWidget()
    w.show()
    seen.clear()
    motion.animate(w, "x", 0.0, 1.0, 100, seen.append)
    w.hide()
    run_out(w, "x", upto=0.25)
    assert seen[-1] == 1.0 and motion.running(w, "x") is None  # hidden meanwhile: the end, and stopped
    gone = QWidget()
    gone.show()
    anim = motion.animate(gone, "x", 0.0, 1.0, 100, lambda _t: None)
    assert anim is not None
    gone.deleteLater()
    QApplication.sendPostedEvents(gone, QEvent.Type.DeferredDelete)  # it goes, and its animation with it
    with pytest.raises(RuntimeError):
        anim.state()


def test_a_popup_rises_into_its_place_and_takes_a_key_at_once(qapp, moving):
    popup = QWidget(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
    box = QLineEdit()
    QVBoxLayout(popup).addWidget(box)
    popup.move(200, 150)
    popup.show()
    box.setFocus()
    motion.rise(popup)
    assert motion.running(popup, "rise") is not None and popup.pos() != QPoint(200, 150)
    QTest.keyClicks(box, "abc")  # the first keys land at once
    assert box.text() == "abc"
    run_out(popup, "rise")
    assert popup.pos() == QPoint(200, 150) and popup.windowOpacity() == 1.0
    popup.close()


def test_what_rises_popups_and_floating_windows_not_menus_or_resting_ones(qapp):
    assert motion.rises(QWidget(None, Qt.WindowType.Popup))
    assert not motion.rises(QMenu())
    floating = QWidget()
    floating.setProperty("floating", True)
    assert motion.rises(floating)
    floating.setObjectName("todayPanel")
    assert not motion.rises(floating) and not motion.rises(QWidget())


def test_a_rise_lets_go_when_its_window_is_moved(qapp, moving):
    popup = QWidget(None, Qt.WindowType.Popup)
    popup.move(200, 150)
    popup.show()
    motion.rise(popup)
    run_out(popup, "rise", upto=0.25)
    popup.move(400, 300)  # placed again by its own code
    run_out(popup, "rise")
    assert popup.pos() == QPoint(400, 300) and popup.windowOpacity() == 1.0
    popup.close()


def test_the_toast_slides_into_its_place(qapp, moving):
    from docrepo.ui.toast import Toast

    window = QWidget()
    window.resize(800, 500)
    window.show()
    toast = Toast(window)
    toast.say("Moved under Installation.", undo=True)
    assert motion.running(toast, "slide") is not None and toast.offers_undo()  # its Undo is there from the start
    run_out(toast, "slide")
    rest = toast.pos()
    toast.place()
    assert toast.pos() == rest and motion.running(toast, "slide") is None
    toast.dismiss()
    toast.say("Again")
    toast.dismiss()  # mid-slide: hidden, nothing left running
    assert toast.isHidden() and motion.running(toast, "slide") is None
    window.close()


def test_a_switch_s_knob_slides_and_rests_as_checked_says(qapp, moving):
    from docrepo.ui.widgets import Toggle

    t = Toggle("Show hints")
    t.show()
    t.setChecked(True)
    assert t.isChecked() and t.knob is not None  # on at once; only its knob is on its way
    run_out(t, "knob")
    assert t.knob is None
    t.close()


def test_a_ticked_line_draws_its_tick_and_ends_drawn(qapp, moving):
    from docrepo.ui.rich_edit import MARKER, RichEdit

    edit = RichEdit()
    edit.show()
    edit.setPlainText("Order the seal")
    edit._make_check(edit.document().firstBlock())
    block = edit.document().firstBlock()
    edit.toggle_tick(block)
    assert block.blockFormat().marker() == MARKER.Checked  # ticked at once
    assert edit._tick_drawing is not None and edit._tick_drawing[0] == block.blockNumber()
    run_out(edit, "tick")
    assert edit._tick_drawing is None
    edit.close()


def test_the_drop_targets_fade_in_and_take_a_drop_from_the_start(qapp, moving):
    from docrepo.ui.today_bins import DropGroups, make_group

    parent = QWidget()
    parent.resize(400, 300)
    parent.show()
    bins = DropGroups(parent)
    group = make_group("high", QRect(0, 0, 300, 24), QRect(240, 2, 50, 20), [], [QRect(0, 24, 300, 28)], 1)
    bins.open_for("medium", {"high": 1}, QRect(0, 0, 400, 300), groups=[group])
    assert bins.reveal < 1.0
    assert bins.bin_at(bins.mapToGlobal(QPoint(100, 12))) == ("high", False)  # a drop lands before it has faded in
    run_out(bins, "reveal")
    assert bins.reveal == 1.0
    bins.close_bins()
    bins.open_for("medium", {}, QRect(0, 0, 400, 300), groups=[group])
    bins.close_bins()
    assert motion.running(bins, "reveal") is None and bins.reveal == 1.0
    parent.close()
