"""The look as it really comes out (release 5.57). Each check runs in a process of its own, since ``apply_look`` changes the whole
application, and the font and size checks run on Windows' real platform: its theme gives some classes fonts of their own, and the
offscreen platform the other tests use has no such table, so it can't see when the application's font doesn't reach them."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows' own Qt platform")


def run_look(script: str, platform: str) -> dict:
    """Run ``script`` with an application in the new look; it prints its results as JSON."""
    start = ("import json, sys\n"
             "from PySide6.QtWidgets import QApplication\n"
             "from docrepo.ui.style import apply_look\n"
             "app = QApplication([])\n"
             "apply_look(app, 'new', False)\n")
    done = subprocess.run([sys.executable, "-c", start + script], cwd=REPO, env={**os.environ, "QT_QPA_PLATFORM": platform},
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@windows_only
def test_every_class_of_widget_gets_the_body_font():
    """Decisions 1 and 2: rows, tables and menus in the same font and size as the buttons, on the real platform."""
    fonts = run_look("""
from PySide6.QtWidgets import QLineEdit, QListView, QMenu, QMessageBox, QPushButton, QTableWidget, QTreeWidget
out = {}
for w in (QTreeWidget(), QTableWidget(), QListView(), QMenu(), QMessageBox(), QPushButton("x"), QLineEdit()):
    w.ensurePolished()
    out[type(w).__name__] = [w.font().family(), w.font().pointSizeF()]
print(json.dumps(out))
""", "windows")
    assert len({tuple(f) for f in fonts.values()}) == 1, fonts
    assert fonts["QTreeWidget"][1] == 10.5


@windows_only
def test_controls_share_a_height():
    """A row of controls lines up: inputs and buttons are 32 px, icon buttons 28 and one line of a list 28, as the tokens say."""
    sizes = run_look("""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget
from docrepo.ui.tree_view import RowTree
from docrepo.ui.widgets import ChipPicker, DateField
top = QWidget()
top.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
lay = QVBoxLayout(top)
combo = QComboBox()
combo.addItems(["One"])
editable = QComboBox()
editable.setEditable(True)
tool = QToolButton(objectName="iconButton")
only = QPushButton(objectName="iconOnly")
strip = QWidget(objectName="typeStrip")
chips = ChipPicker(lambda text, picked: [], "Agenda")
date = DateField()
tree = RowTree()
tree.set_columns(["Title"], [0])
tree.begin()
tree.add_row(None, ("task", "T1"), ["A row"])
tree.end(0)
named = dict(button=QPushButton("Save"), primary=QPushButton("Save", objectName="primary"), line=QLineEdit("x"), combo=combo, editable=editable,
             spin=QSpinBox(), tool=tool, only=only, strip=strip, chips=chips, date=date, tree=tree)
for w in named.values():
    lay.addWidget(w)
top.show()
for _ in range(5):
    app.processEvents()
out = {name: w.height() for name, w in named.items() if name not in ("tree", "chips", "date")}
out["chips"] = chips.box.height()
out["date"] = date.line.height()
out["row"] = tree.visualItemRect(tree.topLevelItem(0)).height()
print(json.dumps(out))
""", "windows")
    for name in ("button", "primary", "line", "combo", "editable", "spin", "strip", "chips", "date"):
        assert sizes[name] == 32, (name, sizes)
    assert sizes["tool"] == sizes["only"] == 28, sizes
    assert 28 <= sizes["row"] <= 30, sizes  # 28 at most scales: a line of text's height depends a little on the computer's scaling


def test_view_titles_are_semibold_in_a_font_that_shows_it():
    """Under Segoe UI Variable's "Text" style, a weight in a style sheet comes out light at a title's size, so titles name Segoe UI."""
    title = run_look("""
from PySide6.QtWidgets import QLabel
label = QLabel("Timeline", objectName="paneTitle")
label.ensurePolished()
print(json.dumps([label.font().family(), label.font().pointSizeF(), label.font().weight().value]))
""", "offscreen")
    assert title == ["Segoe UI", 15.0, 600]


def test_the_keyboard_shows_focus_and_the_mouse_doesnt():
    """Decision 11: a real Tab puts a ring on every kind of button at 3:1 or more, and a click on one doesn't. A text box keeps its
    accent edge and its height."""
    seen = run_look("""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton, QToolButton, QWidget
from docrepo.ui.icons import icon

def lum(c):
    r, g, b = ((v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4 for v in (c.red(), c.green(), c.blue()))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def strongest(before, after):
    best = {}
    for y in range(before.height()):
        for x in range(before.width()):
            if before.pixel(x, y) != after.pixel(x, y):
                a, b = sorted((lum(QColor(before.pixel(x, y))), lum(QColor(after.pixel(x, y)))), reverse=True)
                r = round((a + 0.05) / (b + 0.05), 2)
                best[r] = best.get(r, 0) + 1
    return max((r for r, n in best.items() if n >= 20), default=0)

def settle():
    for _ in range(4):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

top = QWidget()
top.setObjectName("capture")
row = QHBoxLayout(top)
first = QLineEdit("start")
tool = QToolButton(objectName="iconButton")
tool.setIcon(icon("more"))
controls = dict(primary=QPushButton("Save", objectName="primary"), neutral=QPushButton("Add"), subtle=QPushButton("Note", objectName="subtle"),
                link=QPushButton("Open", objectName="link"), tick=QCheckBox("Tick"), icon=tool)
row.addWidget(first)
for w in controls.values():
    row.addWidget(w)
last = QLineEdit("end")
row.addWidget(last)
top.show()
top.activateWindow()
QTest.qWaitForWindowActive(top)
settle()
rest = {name: w.grab().toImage() for name, w in controls.items()}
line_height = last.height()
first.setFocus()
settle()
out = {}
for name, w in controls.items():
    QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
    settle()
    out[name] = [w.hasFocus(), strongest(rest[name], w.grab().toImage())]
QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
settle()
out["line_focused"] = last.hasFocus()
out["line_same_height"] = last.height() == line_height
out["ring_gone"] = controls["icon"].findChild(QWidget, "focusRing") is None
QTest.mouseClick(controls["neutral"], Qt.MouseButton.LeftButton)
settle()
out["clicked"] = [controls["neutral"].hasFocus(), controls["neutral"].findChild(QWidget, "focusRing") is not None]
print(json.dumps(out))
""", "offscreen")
    for name in ("primary", "neutral", "subtle", "link", "tick", "icon"):
        assert seen[name][0] and seen[name][1] >= 3, (name, seen[name])
    assert seen["line_focused"] and seen["line_same_height"] and seen["ring_gone"]
    assert seen["clicked"] == [True, False]


SAMPLE = """
import tempfile
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt
from docrepo import db
from docrepo.config import Settings, make_safe_fs
from docrepo.sample import load_sample
from docrepo.ui.browse_window import BrowseWindow
from docrepo.ui.capture_window import CaptureWindow
from docrepo.ui.context import AppContext
root = Path(tempfile.mkdtemp())
settings = Settings(me="P001")
fs = make_safe_fs(root, settings)
conn = db.connect(fs, root)
load_sample(conn)
ctx = AppContext(conn, root, fs, settings, now=lambda: datetime(2026, 10, 8, 14, 10), settings_changed=lambda _: None)
capture = CaptureWindow(ctx)
capture.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
browse = BrowseWindow(ctx, capture)
browse.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
browse.show_browse()
def settle():
    for _ in range(8):
        app.processEvents()
"""


@windows_only
def test_the_window_can_snap_to_half_a_1920_screen_on_every_view():
    """The review's stage V2: 1157 px wide at least, because the middle pane held its widest page's minimum. Each view now asks for its own."""
    widths = run_look(SAMPLE + """
from docrepo.views import VIEWS
out = {}
for v in VIEWS:
    browse.set_view(v.id)
    settle()
    out[v.id] = browse.minimumSizeHint().width()
print(json.dumps(out))
""", "windows")
    assert max(widths.values()) <= 960, widths


@windows_only
def test_the_timeline_pages_controls_fit_one_row_and_its_parts_share_the_axis():
    """The review's stage V5: one row of controls at the usual window, not three, and a day in one place all down the page."""
    got = run_look(SAMPLE + """
from datetime import date
browse.set_view("timeline")
browse.resize(1574, 918)  # 82% and 85% of a 1920 by 1080 screen, how it opens
settle()
view = browse.timeline
day = date(2026, 10, 26)
xs = [view.scale.x(w, day) for w in (view.head, view.chart, view.cap_team, view.cap_rows)]
got = {"tools": view.tools.height(), "button": view.plan_button.height(), "xs": xs, "top": view.split.sizes()[0], "bottom": view.split.sizes()[1],
       "right": view.range_box.geometry().right(), "width": view.tools.width()}
view.take_off(view.chart.rows[0].task)  # a what-if (release 5.64): its strip names it, and the row stays one line
settle()
got["whatif"] = view.tools.height()
print(json.dumps(got))
""", "windows")
    assert got["tools"] <= got["button"] + 2 and got["whatif"] <= got["button"] + 2, got
    assert got["right"] >= got["width"] - 2, got  # the range at the row's right end
    assert len(set(got["xs"])) == 1, got
    assert got["top"] >= got["bottom"] * 0.6, got  # the chart keeps its room


@windows_only
def test_the_task_page_is_as_narrow_as_its_pane():
    """It stayed 481 px wide in a 288 px pane, so its words ran off the edge with nothing to show it."""
    got = run_look(SAMPLE + """
browse.resize(960, 700)
browse.set_view("tasks")
browse.go_task("T000001")
settle()
browse.split.setSizes([248, 2000, 0])
settle()
pane = browse.task_pane
print(json.dumps([pane.viewport().width(), pane.widget().width(), browse.detail.width()]))
""", "windows")
    assert got[1] <= got[0] + 1, got


@windows_only
def test_the_forms_fit_without_scrolling():
    """Edit task scrolled at 608 by 724, and New task by 401 px at the capture window's largest."""
    got = run_look(SAMPLE + """
from PySide6.QtWidgets import QScrollArea
dialogs = []
def run_dialog(d):
    dialogs.append(d)
    d.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    d.resize(608, 724)
    d.show()
    return False
browse.run_dialog = run_dialog
browse.set_view("tasks")
browse.go_task("T000001")
browse.edit_task("T000001")
settle()
edit = dialogs[-1].findChild(QScrollArea).verticalScrollBar().maximum()
capture.show_capture(mode="new_task", content="Replace the Line 2 pump seal by Fri 16 Oct. @Mike leads, 6 h. Deadline 30 Oct")
capture.parse()
settle()
new = [a.verticalScrollBar().maximum() for a in capture.findChildren(QScrollArea) if a.isVisibleTo(capture)]
print(json.dumps([edit, new]))
""", "windows")
    assert got[0] == 0, got
    assert max(got[1]) <= 12, got  # a few pixels at most, which depend on the computer's scaling


def test_every_window_gets_docrepos_icon():
    """A window icon and the taskbar's own name for DocRepo (release 5.57), at each size Windows asks for."""
    got = run_look("""
from PySide6.QtWidgets import QWidget
from docrepo import app as docrepo_app
docrepo_app.set_identity(app)
sizes = sorted(s.width() for s in docrepo_app.make_icon().availableSizes())
print(json.dumps([QWidget().windowIcon().isNull(), sizes]))
""", "offscreen")
    assert got[0] is False and got[1][0] == 16 and 32 in got[1] and got[1][-1] == 64

