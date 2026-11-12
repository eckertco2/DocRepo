"""The registry of what a wheel's slot may name (releases 5.41 to 5.43; ``docs/ui-design/wheel-design.md``, decision 174).

One table: an ID, a title, typed arguments with their choices and defaults, and what it runs. A slot can name nothing else,
so a config can't start a program, and captured content can never become a command. It also feeds the Ctrl+K palette.
A command runs on the app (``docrepo.app.CaptureApp``). The agent window, when it comes, is one more row here, as the quick
summary (release 5.131) was.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrepo.views import RETIRED_VIEWS, VIEWS
from docrepo.wheels_config import Arg, CommandSpec

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

ICON_DIR = Path(__file__).resolve().parent / "icons"


def icon_names() -> set[str]:
    """The icons a slot may name: DocRepo's own."""
    return {p.stem for p in ICON_DIR.glob("*.svg")}


@dataclass(frozen=True)
class Registered:
    """A command: what a slot may say about it, and what it runs. ``gives_back``: it opens no window of its own, so the
    keyboard goes back to the window you were in."""

    spec: CommandSpec
    run: Callable[[CaptureApp, Mapping[str, Any]], None]
    gives_back: bool = False


def _capture_new(app: CaptureApp, args: Mapping[str, Any]) -> None:
    """An empty capture window: a capture open with something in it goes to Drafts first (release 5.77, decision 337).
    With "blank" false, the open capture stays, with that type checked."""
    if args["blank"]:
        app.window.open_blank(args["mode"])
    else:
        app.window.show_capture(mode=args["mode"], keep=True)


def _capture_pin(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.window.pin()


def _capture_selection(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.wheels.capture_selection()


def _capture_meeting(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.window.show_capture(meeting=True)


def _today_new_item(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    """Ctrl+Shift+D's command, not a way of its own (release 5.99, the consolidation plan's decision 393)."""
    app.window.open_quick_task()


def _today_panel(app: CaptureApp, args: Mapping[str, Any]) -> None:
    app.wheels.today_panel(args["do"])


def _browse_view(app: CaptureApp, args: Mapping[str, Any]) -> None:
    app.show_browse(args["view"])


def _search_tasks(app: CaptureApp, args: Mapping[str, Any]) -> None:
    app.wheels.task_search(args["then"])


def _search_files(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.wheels.file_search()


def _search_everything(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.show_browse()
    app.browse.search_box.setFocus()
    app.browse.search_box.selectAll()


def _summary_open(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    """The quick summary (release 5.131, the quick summary plan's decision 517): its window, with the cursor in its box."""
    app.wheels.quick_summary()


def _find_files_current(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    """Find files for the task selected in the browse tool, or else the last one opened; with neither, task search, and
    picking a task opens its Find files. Its old name, task_view.current, still works (``wheels_config.RENAMED``)."""
    task = app.browse.current_task_for_view()
    if task:
        app.browse.open_task_view(task)
    else:
        app.wheels.task_search("find_files")


_ROWS = (
    Registered(CommandSpec("capture.new", "The capture window, blank", (Arg("mode", None, ("note", "new_task", "update")), Arg("blank", True, kind="bool"))), _capture_new),
    Registered(CommandSpec("capture.pin", "The pinned window"), _capture_pin),
    Registered(CommandSpec("capture.selection", "The pinned window with the current email or file"), _capture_selection),
    Registered(CommandSpec("capture.meeting", "Meeting notes"), _capture_meeting),
    Registered(CommandSpec("today.new_item", "A quick task on Today (Ctrl+Shift+D's command)"), _today_new_item),
    Registered(CommandSpec("today.panel", "The Today side panel", (Arg("do", "toggle", ("toggle", "open", "close")),)), _today_panel, gives_back=True),
    # A view that's gone (release 5.97: urgent) is still allowed, and leads where it went: the task tree, Urgent only.
    Registered(CommandSpec("browse.view", "The browse tool on a view", (Arg("view", "tasks", (*(v.id for v in VIEWS), *RETIRED_VIEWS)),)), _browse_view),
    Registered(CommandSpec("search.tasks", "Task search", (Arg("then", "find_files", ("find_files", "page"), renamed=(("task_view", "find_files"),)),)),
               _search_tasks),
    Registered(CommandSpec("search.files", "File search"), _search_files),
    Registered(CommandSpec("search.everything", "Search everything"), _search_everything),
    Registered(CommandSpec("find_files.current", "Find files for the current task"), _find_files_current),
    Registered(CommandSpec("summary.open", "The quick summary"), _summary_open),
)
REGISTRY: dict[str, Registered] = {r.spec.id: r for r in _ROWS}
SPECS: dict[str, CommandSpec] = {r.spec.id: r.spec for r in _ROWS}
