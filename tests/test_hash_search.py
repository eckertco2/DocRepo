"""The @ and # lists' search past a space (release 5.74, round 7's item 91, decisions 324 to 326): every word typed after
the sign narrows the list, matching the start of any word of a name in any order, or of a name on a task's path; a space
after a whole name that nothing else goes on from closes it, and a pick doesn't open it again. Made-up names."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import capacity, db, items, prompts, tasks  # noqa: E402
from docrepo.config import Settings  # noqa: E402
from docrepo.parse import ParsePerson  # noqa: E402
from docrepo.sample import load_sample  # noqa: E402
from docrepo.ui.capture_window import CaptureWindow  # noqa: E402
from docrepo.ui.context import AppContext  # noqa: E402
from docrepo.ui.items_panel import _OPTION  # noqa: E402

NOW = datetime(2026, 10, 8, 14, 10)


# ---- what's being typed ----
def test_a_space_keeps_the_word_going():
    assert items.typing("#Pump ") == items.Typing("#", "Pump ", 0)
    assert items.typing("see #seal pump ") == items.Typing("#", "seal pump ", 4)
    assert items.typing("@Ana Lo") == items.Typing("@", "Ana Lo", 0)


def test_a_heading_two_spaces_and_too_much_end_it():
    assert items.typing("# ") is None  # "# " starts a heading
    assert items.typing("#Pump  ") is None  # two spaces: the words are over
    assert items.typing("#a b c d e f g h") is not None and items.typing("#a b c d e f g h i") is None  # eight words at most
    assert items.typing("#" + "x" * items.TYPING_LIMIT) is not None and items.typing("#" + "x" * (items.TYPING_LIMIT + 1)) is None


# ---- matching, over a small made-up tree ----
@dataclass
class Task:
    id: str
    title: str


@dataclass
class Tree:
    """As much of a Model as the lists use: the tasks, each one's parents, and the top-level ones."""

    tasks: dict[str, Task]
    parents: dict[str, list[str]] = field(default_factory=dict)

    def ancestors_of(self, task_id: str) -> list[str]:
        out = []
        for p in self.parents.get(task_id, []):
            out += [p, *self.ancestors_of(p)]
        return out

    def top_level(self) -> list[Task]:
        return [t for t in self.tasks.values() if not self.parents.get(t.id)]


def names(*titles: tuple[str, str, str | None], people: tuple[tuple[str, tuple[str, ...]], ...] = ()) -> items.Names:
    tree = Tree({i: Task(i, t) for i, t, _ in titles}, {i: [p] for i, _, p in titles if p})
    return items.Names([ParsePerson(f"P{n:03d}", name, tuple(aliases)) for n, (name, aliases) in enumerate(people, 1)],
                       [items.RefTask(i, t) for i, t, _ in titles], model=tree)


def listed(text: str, n: items.Names) -> list[str]:
    t = items.typing(text)
    return [o.label for o in items.options(t, n)] if t else []


PUMPS = names(("T1", "Installation", None), ("T2", "Pump", "T1"), ("T3", "Commissioning", None), ("T4", "Pump", "T3"),
              ("T5", "Pump station", None), ("T6", "Replace pump seals", "T1"), ("T7", "Valve", None), ("T8", "Check valve seat", "T3"))


def test_after_a_space_it_goes_on_searching():
    """The memo's complaint: "#Pump " closed the list, and "#Pump s" found only names that start "Pump s"."""
    assert listed("#Pump ", PUMPS) == ["Pump", "Pump", "Pump station", "Replace pump seals"]
    assert listed("#Pump s", PUMPS) == ["Pump station", "Replace pump seals"]


def test_words_match_anywhere_in_any_order():
    assert listed("#seal pump", PUMPS) == ["Replace pump seals"]
    assert listed("#seat check", PUMPS) == ["Check valve seat"]
    assert listed("#rep sea", PUMPS) == ["Replace pump seals"]
    assert listed("#pump seals r", PUMPS) == ["Replace pump seals"] and listed("#pump seals p", PUMPS) == []  # each word a word of its own


def test_the_path_tells_two_tasks_of_one_name_apart():
    t = items.typing("#install pump")
    assert [o.ref for o in items.options(t, PUMPS)] == ["T2", "T6"]  # the Pump under Installation, and the seals under it too
    t = items.typing("#commis pump")
    assert [o.ref for o in items.options(t, PUMPS)] == ["T4"]


def test_a_path_match_needs_a_word_of_the_tasks_own_name():
    assert listed("#installation", PUMPS) == ["Installation"]  # not everything under it


def test_the_ranking():
    """Decision 326: the whole name, then names that start with what's typed, then names with every word, then path matches."""
    n = names(("T1", "Seal kit", None), ("T2", "Check the seal", None), ("T3", "Seal", None), ("T4", "Gaskets", "T2"))
    assert listed("#seal", n) == ["Seal", "Seal kit", "Check the seal"]


def test_a_finished_name_closes_the_list():
    assert listed("#Valve ", PUMPS) == []  # nothing goes on from "Valve ", though "Check valve seat" has the word
    assert listed("#Valve s", PUMPS) == ["Check valve seat"]
    assert listed("#Pump station ", PUMPS) == []


def test_more_than_eight():
    n = names(*((f"T{i}", f"Order part {i}", None) for i in range(1, 12)))
    assert len(listed("#order part", n)) == 8


def test_people_too():
    n = names(people=(("Ana Lopez", ("Ana",)), ("Tom Becker", ())))
    assert [o.value for o in items.options(items.typing("@lopez"), n)][:1] == ["Ana Lopez"]
    assert [o.value for o in items.options(items.typing("@Ana "), n)][:1] == ["Ana Lopez"]  # "Ana Lopez" goes on from "Ana "
    assert [o.value for o in items.options(items.typing("@becker t"), n)][:1] == ["Tom Becker"]
    assert items.options(items.typing("@Ana Lopez "), n) == []  # the whole name: finished
    assert items.options(items.typing("@Tom get the report"), n) == []


# ---- in the capture window, over the sample data ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, data_root, fs):
    conn = db.connect(fs, data_root)
    load_sample(conn)
    settings = Settings(me="P001")
    capacity.rebuild_all(conn, NOW.date(), settings)
    prompts.write_defaults(fs, data_root)
    ctx = AppContext(conn, data_root, fs, settings, notify=lambda t, m: None, now=lambda: NOW)
    w = CaptureWindow(ctx)
    w.resize(900, 700)
    w.show_capture()
    yield w
    QApplication.processEvents()
    w._items_timer.stop()
    w.hide()
    w.deleteLater()
    conn.close()


def type_in(w: CaptureWindow, text: str) -> None:
    w.content.setFocus()
    QApplication.processEvents()
    w.content.insertPlainText(text)


def shown(w: CaptureWindow) -> list[str]:
    p = w.ref_popup
    return [p.item(i).data(_OPTION).label for i in range(p.count())] if p.isVisible() else []


def test_the_list_stays_open_past_a_space(window):
    type_in(window, "Talked about #Rigging ")
    assert shown(window) == ["Rigging plan"]
    type_in(window, "pl")
    assert shown(window) == ["Rigging plan"]


def test_any_order_and_the_path_in_the_window(window):
    type_in(window, "#plan rigging")
    assert shown(window) == ["Rigging plan"]
    window.content.clear()
    type_in(window, "#installation book")
    assert shown(window) == ["Book the alignment contractor"]


def test_a_finished_name_and_a_sentence_close_it(window):
    type_in(window, "#Installation ")
    assert shown(window) == []
    window.content.clear()
    type_in(window, "#Rigging plan is ready")
    assert shown(window) == []


def test_a_pick_doesnt_open_it_again(window):
    """With "Rigging plan review" there too, the picked "Rigging plan " would list it again: it doesn't, until you type on."""
    tasks.create_task(window.ctx.conn, window.ctx.settings, title="Rigging plan review", at=NOW, created_by="Browse tool", parents=["T000008"])
    window._names = None
    type_in(window, "#Rigging pl")
    assert shown(window) == ["Rigging plan", "Rigging plan review"]
    window._pick_ref(window.ref_popup.item(0).data(_OPTION))
    assert window.content.toPlainText() == "#Rigging plan " and shown(window) == []
    type_in(window, "rev")  # "r" alone would also find "Rigging plan" through "Reactor" on its path
    assert shown(window) == ["Rigging plan review"]
