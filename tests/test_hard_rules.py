"""The hard rules on files and programs (release 5.87, the review of 2026-11-06, F7): every write, copy, move, new folder
and delete goes through ``safe_fs.py``, and only ``opener.py`` starts another program. The scan reads each module's
syntax tree, as ``test_no_network.py`` does for networking modules, so the rule holds by test and not by inspection."""
from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "docrepo"

#: The modules that may write or launch on their own, and why.
ALLOWED = {
    "safe_fs.py": "the guarded writes themselves",
    "log_setup.py": "the log handler writes its own file, at a path from checked_path",
    "backup.py": "SQLite's backup API writes into the backup folder, at a path from checked_path",
    "opener.py": "Windows' open and File Explorer, for the allow-list only",
}
#: Modules any use of which is a write or a launch.
BANNED_MODULES = ("shutil", "subprocess")
#: Functions of ``os`` that write, delete or launch.
BANNED_OS = ("remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "makedirs", "mkdir", "system",
             "startfile", "popen", "spawnl", "spawnv", "execv", "execl", "truncate", "link", "symlink")
#: Methods of ``Path`` that write whatever their arguments (SafeFS has none of these names).
PATH_ALWAYS = ("touch", "mkdir", "unlink", "rmdir", "write_bytes", "symlink_to", "hardlink_to")
#: Methods of ``Path`` whose name SafeFS or ``str`` shares, told apart by how many arguments they take: Path's
#: ``write_text(data)``, ``rename(target)`` and ``replace(target)`` take one; SafeFS's ``write_text(path, text)`` and
#: ``replace(src, dst)`` take two, ``str.replace`` two or three, and ``date.replace(day=1)`` none.
PATH_ONE_ARG = ("write_text", "rename", "replace")
#: An ``open`` mode that writes: Python's mode letters only, with one that writes.
WRITE_MODE = re.compile(r"[rwxabt+]{1,3}")


def _is_write_mode(node: ast.AST | None) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str) and WRITE_MODE.fullmatch(node.value) is not None
            and bool(set("wax+") & set(node.value)))


def _mode_of(call: ast.Call, position: int) -> ast.AST | None:
    """The mode argument of an ``open`` call: positional at ``position``, or ``mode=``."""
    if len(call.args) > position:
        return call.args[position]
    return next((k.value for k in call.keywords if k.arg == "mode"), None)


def banned_uses(source: str) -> list[str]:
    """The writes and launches that ``source`` makes, each as ``line: what``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            found += [f"{line}: import {a.name}" for a in node.names if a.name.split(".")[0] in BANNED_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in BANNED_MODULES:
                found.append(f"{line}: from {node.module} import")
            elif node.module == "os":
                found += [f"{line}: from os import {a.name}" for a in node.names if a.name in BANNED_OS]
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in BANNED_MODULES:
                found.append(f"{line}: {node.value.id}.{node.attr}")
            elif node.value.id == "os" and node.attr in BANNED_OS:
                found.append(f"{line}: os.{node.attr}")
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open" and _is_write_mode(_mode_of(node, 1)):
            found.append(f"{line}: open(..., write mode)")
        elif isinstance(f, ast.Attribute):
            if f.attr == "open" and _is_write_mode(_mode_of(node, 0)):
                found.append(f"{line}: .open(write mode)")
            elif f.attr in PATH_ALWAYS:
                found.append(f"{line}: .{f.attr}()")
            elif (f.attr in PATH_ONE_ARG and len(node.args) == 1 and not node.keywords
                  and not (isinstance(f.value, ast.Name) and f.value.id == "dataclasses")):  # dataclasses.replace(obj) copies
                found.append(f"{line}: .{f.attr}(one argument)")
            elif f.attr == "write_text" and len(node.args) == 1:  # Path.write_text(data, encoding=...)
                found.append(f"{line}: .write_text(one argument)")
    return found


def test_only_the_allowed_modules_write_or_launch():
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, "found no source files to scan"
    problems = {}
    for f in files:
        rel = f.relative_to(PACKAGE).as_posix()
        if rel in ALLOWED:
            continue
        uses = banned_uses(f.read_text(encoding="utf-8"))
        if uses:
            problems[rel] = uses
    assert problems == {}, "write through SafeFS, and start programs only in opener.py"


def test_the_allowed_modules_are_there():
    """An allowed module that's gone or renamed would leave its entry checking nothing."""
    assert all((PACKAGE / name).exists() for name in ALLOWED)


def test_the_scan_catches_writes_and_launches():
    sample = (
        "import shutil\n"
        "import subprocess as sp\n"
        "from os import remove\n"
        "import os\n"
        "from pathlib import Path\n"
        "shutil.copy('a', 'b')\n"
        "os.startfile('a.pdf')\n"
        "(starter or os.startfile)('a.pdf')\n"
        "os.makedirs('x')\n"
        "open('a.txt', 'w')\n"
        "open('a.txt', mode='ab')\n"
        "Path('a').open('w')\n"
        "Path('a').write_text('words', encoding='utf-8')\n"
        "Path('a').write_bytes(b'x')\n"
        "Path('a').mkdir(parents=True)\n"
        "Path('a').touch()\n"
        "Path('a').unlink()\n"
        "Path('a').rename('b')\n"
        "Path('a').replace(Path('b'))\n"
    )
    found = banned_uses(sample)
    for what in ("import shutil", "import subprocess", "from os import remove", "shutil.copy", "os.startfile", "os.makedirs",
                 "open(..., write mode)", ".open(write mode)", ".write_text(one argument)", ".write_bytes()", ".mkdir()",
                 ".touch()", ".unlink()", ".rename(one argument)", ".replace(one argument)"):
        assert any(f.endswith(what) for f in found), what
    assert sum(f.endswith("os.startfile") for f in found) == 2  # called, or only named


def test_the_scan_allows_reads_and_safe_fs():
    sample = (
        "import os\n"
        "from datetime import date\n"
        "open('a.txt')\n"
        "open('a.txt', 'rb')\n"
        "open('a.txt', encoding='utf-8')\n"
        "fs.write_text(path, 'words')\n"
        "fs.replace(tmp, slot)\n"
        "fs.makedirs(folder)\n"
        "'a-b'.replace('-', ' ')\n"
        "date.today().replace(day=1)\n"
        "os.path.join('a', 'b')\n"
        "os.name\n"
        "buffer.open(mode_flag)\n"
        "panel.open('start')\n"
        "dataclasses.replace(settings)\n"
    )
    assert banned_uses(sample) == []


def test_a_shutil_copy_in_another_module_fails_the_scan():
    """The review's acceptance check: adding a copy anywhere but the allowed modules is caught."""
    source = (PACKAGE / "captures.py").read_text(encoding="utf-8")
    assert banned_uses(source) == []
    assert banned_uses(source + "\nimport shutil\nshutil.copy('a', 'b')\n")
