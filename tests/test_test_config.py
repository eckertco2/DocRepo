"""The test configuration (release 5.88, the review of 2026-11-06, F10): Qt modules marked ``gui``, a fast run with no Qt,
and a temporary folder per run."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from conftest import TEMP_ROOT, is_gui_module

TESTS = Path(__file__).resolve().parent


def test_gui_modules_are_told_apart(tmp_path):
    cases = {
        "a.py": "import os\nos.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n",
        "b.py": "from docrepo.ui.browse_window import BrowseWindow\n",
        "c.py": "def f():\n    from PySide6.QtWidgets import QApplication\n",
        "d.py": "from docrepo import db\nSAMPLE = 'from PySide6 import QtNetwork'\n",
        "e.py": "import docrepo.uikit_notes\n",
    }
    for name, text in cases.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert {n: is_gui_module(tmp_path / n) for n in cases} == {"a.py": True, "b.py": True, "c.py": True, "d.py": False, "e.py": False}
    assert is_gui_module(TESTS / "test_browse_window.py") and not is_gui_module(TESTS / "test_no_network.py")


def test_this_run_has_a_temporary_folder_of_its_own(tmp_path, request):
    base = Path(request.config.option.basetemp).resolve()
    assert tmp_path.resolve().is_relative_to(base)
    if base.parent == TEMP_ROOT.resolve():
        assert base.name == f"run-{os.getpid()}"


def test_the_fast_run_imports_no_qt(request):
    if " ".join((request.config.option.markexpr or "").split()) != "not gui":
        pytest.skip('only in the fast run, -m "not gui"')
    assert not [m for m in sys.modules if m == "PySide6" or m.startswith(("PySide6.", "docrepo.ui"))]
