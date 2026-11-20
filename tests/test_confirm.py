"""DocRepo's own confirmation (release 5.187, the redesign's decision 863): a title, a sentence, an optional box and two
buttons named by what they do, with the safe answer on Enter and Esc. Driven offscreen; ``confirm.run`` is replaced, so no
window waits."""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from docrepo.ui import confirm  # noqa: E402

UI = Path(__file__).resolve().parent.parent / "docrepo" / "ui"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pressing(key=None, button: str = "", words: str = ""):
    """A ``run`` that shows the dialog offscreen, types ``words`` into its box, then presses ``key`` where the keyboard is (or
    clicks ``button``, "go" or "stay"), and answers as the dialog closed."""
    seen: list[confirm.Confirm] = []

    def run(box: confirm.Confirm) -> bool:
        seen.append(box)
        box.show()
        target = box.box if box.box is not None else box.stay
        if words:
            box.box.clear()
            QTest.keyClicks(box.box, words)
        if button:
            getattr(box, button).click()
        else:
            QTest.keyClick(target, key)
        answer = box.result() == QDialog.DialogCode.Accepted
        box.close()
        return answer

    return run, seen


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape])
def test_enter_and_esc_give_the_safe_answer(qapp, monkeypatch, key):
    run, seen = pressing(key)
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask(None, "Remove this glossary?", "It leaves DocRepo.", "Remove glossary", "Keep it", danger=True) is False
    box = seen[0]
    assert box.stay.isDefault() and not box.go.isDefault()
    assert (box.title_label.text(), box.text_label.text()) == ("Remove this glossary?", "It leaves DocRepo.")


def test_only_the_doing_button_does_it(qapp, monkeypatch):
    run, _seen = pressing(button="go")
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask(None, "Change the data root?", "From the next start.", "Change data root", "Keep this one") is True
    run, _seen = pressing(button="stay")
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask(None, "Change the data root?", "From the next start.", "Change data root", "Keep this one") is False


def test_a_box_gives_what_was_typed_on_enter_and_nothing_on_esc(qapp, monkeypatch):
    run, seen = pressing(Qt.Key.Key_Return, words="Duplicate of T000002")
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask_text(None, "Discard this task?", "Why?", "No longer needed", yes="Discard task", danger=True) == "Duplicate of T000002"
    box = seen[0]
    assert box.go.isDefault() and box.focusWidget() is box.box
    run, _seen = pressing(Qt.Key.Key_Escape)
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask_text(None, "Add link", "A web link.", "https://example.com", yes="Add link") is None


def test_the_box_starts_with_its_value(qapp, monkeypatch):
    run, _seen = pressing(button="go")
    monkeypatch.setattr(confirm, "run", run)
    assert confirm.ask_text(None, "Save as", "A name for the set.", "Morning meeting", yes="Save") == "Morning meeting"


def test_a_danger_question_fills_its_button_in_red(qapp):
    danger = confirm.Confirm(None, "Delete this what-if?", "It goes.", confirm.Verbs("Delete what-if", "Keep it", True))
    plain = confirm.Confirm(None, "Detach from its template?", "Its values stay.", confirm.Verbs("Detach", "Keep it attached"))
    assert danger.go.objectName() == "danger" and plain.go.objectName() == "primary"
    assert danger.property("floating") and danger.objectName() == "confirm"
    assert danger.box is None and danger.typed() == ""
    danger.deleteLater()
    plain.deleteLater()


@pytest.mark.parametrize(("title", "yes", "no", "danger"), [
    ("Close without saving?", "Close without saving", "Keep editing", True),
    ("Take its block off the notes page?", "Take it off the page", "Leave it on the page", False),
    ("Remove this glossary?", "Remove glossary", "Keep it", True),
    ("Close all 4?", "Close all 4", "Cancel", False),
    ("Close all 12?", "Close all 12", "Cancel", False),
    ("Add it to the tag list?", "Add to the tag list", "Cancel", False),
    ("Change the data root?", "Change data root", "Keep this one", False),
    ("Detach from its template?", "Detach", "Keep it attached", False),
    ("Delete this what-if?", "Delete what-if", "Keep it", True),
    ("Discard this task?", "Discard task", "Keep it", True),
    ("Discard this capture?", "Discard capture", "Keep it", True),
    ("Discard this template?", "Discard template", "Keep it", True),
    ("Rename the glossary", "Rename the glossary", "Cancel", False),
])
def test_the_words_on_each_questions_buttons(title, yes, no, danger):
    assert confirm.verbs(title, "") == confirm.Verbs(yes, no, danger)


def test_ask_for_takes_the_tables_words(qapp, monkeypatch):
    seen = []
    monkeypatch.setattr(confirm, "run", lambda box: seen.append((box.go.text(), box.stay.text(), box.go.objectName())) or True)
    assert confirm.ask_for(None, "Discard this task?", "Why?") is True
    assert seen == [("Discard task", "Keep it", "danger")]


def test_no_stock_message_box_is_left_in_the_windows():
    """No module in ``docrepo/ui`` builds Qt's stock message box, and its text box only where a pick from a list needs one
    (Later's day, the tagged labels' two picks), which ``Confirm`` can't be. ``tokens.py`` names the class once, for its font."""
    for path in UI.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "tokens.py":
            text = text.replace('"QMessageBox", ', "")
        assert "QMessageBox" not in text, path.name
        if path.relative_to(UI).as_posix() not in ("lists/today.py", "lists/tagged.py"):
            assert not re.search(r"\bQInputDialog\b", text), path.name
