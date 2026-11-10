"""The # list in Search everything (release 5.108, decision 414): typing ``#`` in the search box lists tasks, as it does
in the content text, and a pick writes the task's whole name after the ``#``, so the search keeps to that task and what's
under it ("search links #Reactor impeller upgrade", ``docrepo.search.read``).

It's the shared task list (``docrepo/ui/task_list.py``) with its rows, matching and levels: Up and Down move, Right lists a
task's subtasks, Enter or Tab picks, Esc hides it. Closed and parked tasks are listed too, since a search looks in them;
discarded ones aren't.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtWidgets import QLineEdit, QWidget

from docrepo import items
from docrepo.model import Model
from docrepo.ui.items_panel import RefPopup
from docrepo.ui.task_list import subtask_options, task_mark

#: The ``#`` being typed, at the start or after "search" and whatever follows it, up to the cursor.
_TYPING = re.compile(r"^\s*(?:search\b[^#]*)?#([^#]*)$", re.I)
SHOWN = 8


class ScopeList(QObject):
    """Holds the popup for one search box. ``model`` gives the Model as it is now."""

    def __init__(self, box: QLineEdit, model: Callable[[], Model], window: QWidget) -> None:
        super().__init__(box)
        self.box, self.model, self.window = box, model, window
        self.popup = RefPopup(window)
        self.popup.subtasks = lambda task_id: subtask_options(self.model(), task_id, lambda t: not t.discarded)
        self.popup.task_info = lambda task_id: task_mark(self.model(), task_id)
        self.popup.picked.connect(self.pick)
        box.textEdited.connect(lambda _: self.update())
        box.installEventFilter(self)

    def typing(self) -> re.Match | None:
        """The ``#`` word before the cursor, when one is being typed."""
        return _TYPING.match(self.box.text()[:self.box.cursorPosition()])

    def options(self, q: str) -> list[items.Option]:
        m = self.model()
        live = [t for t in m.tasks.values() if not t.discarded]
        if not q.strip():  # "#" alone: the top-level tasks, to walk down from
            return [items.Option(t.title, t.title, ref=t.id) for t in m.top_level() if not t.discarded]
        found = items.task_matches(q, [(t.id, t.title) for t in live], lambda i: items.ancestor_titles(m, i))
        return [items.Option(m.tasks[i].title, m.tasks[i].title, ref=i) for i in found][:SHOWN]

    def update(self) -> None:
        """Show the list for what's typed after the ``#``, or hide it."""
        typed = self.typing()
        options = self.options(typed.group(1)) if typed else []
        if not options:
            self.popup.hide()
            return
        self.popup.show_options(options, self.box.mapTo(self.window, QPoint(0, self.box.height() + 2)))

    def pick(self, option: items.Option) -> None:
        """Write the picked task's name after the ``#``, with a space, ready for the words to find."""
        typed = self.typing()
        self.popup.hide()
        if typed is None:
            return
        text, at = self.box.text(), self.box.cursorPosition()
        start = typed.start(1)
        name = option.value + " "
        self.box.setText(text[:start] + name + text[at:].lstrip())
        self.box.setCursorPosition(start + len(name))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt's name
        if watched is self.box:
            if event.type() == QEvent.Type.KeyPress and self.popup.handle_key(event.key()):
                return True
            if event.type() == QEvent.Type.FocusOut:
                self.popup.hide()
        return super().eventFilter(watched, event)
