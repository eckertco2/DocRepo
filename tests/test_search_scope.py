"""The # list in Search everything (release 5.108, decision 414): typing # lists tasks, and a pick writes the task's name.
Offscreen, over the sample data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget  # noqa: E402

from docrepo import search  # noqa: E402
from docrepo.model import Model  # noqa: E402
from docrepo.ui.search_scope import ScopeList  # noqa: E402

RIGGING = "T000012"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, sample_root):
    conn, _, _ = sample_root
    window = QWidget()
    window.resize(900, 600)
    box = QLineEdit(window)
    scope = ScopeList(box, lambda: Model(conn), window)
    window.show()
    yield conn, box, scope
    window.close()


def typed(box, scope, text):
    box.setText(text)
    box.setCursorPosition(len(text))
    scope.update()


def key(box, k):
    QApplication.sendEvent(box, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def test_hash_lists_tasks_and_a_pick_writes_the_name(env):
    conn, box, scope = env
    m = Model(conn)
    title = m.task(RIGGING).title
    typed(box, scope, "type:links #")
    assert scope.popup.isVisible()
    assert [o.ref for o in scope.popup.rows()] == [t.id for t in m.top_level() if not t.discarded]
    typed(box, scope, f"type:links #{title.split()[0].lower()}")
    assert RIGGING in [o.ref for o in scope.popup.rows()]
    scope.pick(next(o for o in scope.popup.rows() if o.ref == RIGGING))
    assert box.text() == f"type:links #{title} " and not scope.popup.isVisible()
    assert box.cursorPosition() == len(box.text())
    # What it wrote is read as that task, and the words go on after it.
    read, rest = search.read(box.text() + "crane", m)
    assert read.name == f"Links in {title}" and rest == "crane"
    typed(box, scope, box.text() + "crane")
    assert not scope.popup.isVisible()


def test_its_keys_and_where_it_stays_shut(env):
    conn, box, scope = env
    m = Model(conn)
    typed(box, scope, "#")
    assert scope.popup.isVisible()  # a # may start the search on its own
    first = scope.popup.rows()[0]
    key(box, Qt.Key.Key_Return)
    assert box.text() == f"#{first.value} " and not scope.popup.isVisible()
    typed(box, scope, "#")
    key(box, Qt.Key.Key_Escape)  # Esc hides the list, and leaves what's typed
    assert not scope.popup.isVisible() and box.text() == "#"
    for text in ("crane", "type:links crane", "pump #2", "search #zzzqqq"):  # 5.108's "search" went (release 5.121)
        typed(box, scope, text)
        assert not scope.popup.isVisible(), text
    assert m.task(RIGGING).title  # the sample data's task is there
