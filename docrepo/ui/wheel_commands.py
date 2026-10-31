"""The registry of what a wheel's slot may name (releases 5.41 to 5.43; ``docs/ui-design/wheel-design.md``, decision 174).

One table: an ID, a title, typed arguments with their choices and defaults, and what it runs. A slot can name nothing else,
so a config can't start a program, and captured content can never become a command. It also feeds the Ctrl+K palette.
A command runs on the app (``docrepo.app.CaptureApp``). The agent window, when it comes, is one more row here.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docrepo.views import VIEWS
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
    if args["blank"]:
        app.window.open_blank(args["mode"])
    else:
        app.window.show_capture(mode=args["mode"])


def _capture_pin(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.window.pin()


def _capture_selection(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.wheels.capture_selection()


def _capture_meeting(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.window.show_capture(meeting=True)


def _today_new_item(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    app.window.open_with_hotkey("today")


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


def _task_view_current(app: CaptureApp, _args: Mapping[str, Any]) -> None:
    """The task selected in the browse tool, or else the last Task view opened; with neither, task search, and picking a
    task opens its Task view."""
    task = app.browse.current_task_for_view()
    if task:
        app.browse.open_task_view(task)
    else:
        app.wheels.task_search("task_view")


_ROWS = (
    Registered(CommandSpec("capture.new", "The capture window, blank", (Arg("mode", None, ("note", "new_task", "update")), Arg("blank", True, kind="bool"))), _capture_new),
    Registered(CommandSpec("capture.pin", "The pinned window"), _capture_pin),
    Registered(CommandSpec("capture.selection", "The pinned window with the current email or file"), _capture_selection),
    Registered(CommandSpec("capture.meeting", "Meeting notes"), _capture_meeting),
    Registered(CommandSpec("today.new_item", "A quick task on Today"), _today_new_item),
    Registered(CommandSpec("today.panel", "The Today side panel", (Arg("do", "toggle", ("toggle", "open", "close")),)), _today_panel, gives_back=True),
    Registered(CommandSpec("browse.view", "The browse tool on a view", (Arg("view", "tasks", tuple(v.id for v in VIEWS)),)), _browse_view),
    Registered(CommandSpec("search.tasks", "Task search", (Arg("then", "task_view", ("task_view", "page")),)), _search_tasks),
    Registered(CommandSpec("search.files", "File search"), _search_files),
    Registered(CommandSpec("search.everything", "Search everything"), _search_everything),
    Registered(CommandSpec("task_view.current", "The current task's Task view"), _task_view_current),
)
REGISTRY: dict[str, Registered] = {r.spec.id: r for r in _ROWS}
SPECS: dict[str, CommandSpec] = {r.spec.id: r.spec for r in _ROWS}
