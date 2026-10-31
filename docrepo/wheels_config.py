"""The wheels' config file (release 5.41; ``docs/ui-design/wheel-design.md``, decision 174).

``Config/wheels.jsonc`` in the data root: JSON with ``//`` comments, since comments are the point of a file you edit by
hand and no YAML package is approved. DocRepo strips them itself, minding strings, and writes the file only when it isn't
there, so your comments stay. (One exception, ``draw_at_once``: release 5.43.1 changes one old value and its comment.)
Beside it, ``wheels.schema.json`` lets VS Code check it as you type.

A slot can name only a command in the registry (``docrepo/ui/wheel_commands.py``), so a config can't start a program, and
captured content can never become a command. Every problem names its field and what's allowed; ``load`` raises
``ConfigError`` with them all, and the caller keeps the last good config.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from docrepo.safe_fs import SafeFS
from docrepo.wheel import DIAGONALS, DIRECTIONS

CONFIG_FILE = Path("Config") / "wheels.jsonc"
SCHEMA_FILE = Path("Config") / "wheels.schema.json"
_WHEEL_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class ConfigError(Exception):
    """The file can't be used. ``problems`` names each bad field and what's allowed."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Arg:
    """One argument a command takes: its choices, or ``kind`` "bool"; and its default."""

    name: str
    default: Any
    choices: tuple[str, ...] = ()
    kind: str = "choice"  # "choice" or "bool"

    def problem(self, value: Any) -> str | None:
        if self.kind == "bool":
            return None if isinstance(value, bool) else "is true or false"
        return None if value in self.choices else f"is one of {', '.join(self.choices)}"


@dataclass(frozen=True)
class CommandSpec:
    """What a slot may name: an ID, a title, and its typed arguments. What it runs is the registry's."""

    id: str
    title: str
    args: tuple[Arg, ...] = ()


@dataclass(frozen=True)
class Slot:
    """One place on a wheel. ``held`` keeps a place for something that's coming: greyed, labelled "later", doing nothing."""

    label: str
    icon: str = ""
    command: str = ""
    args: Mapping[str, Any] = field(default_factory=dict)
    confirm: bool = False
    held: bool = False


@dataclass(frozen=True)
class Wheel:
    id: str
    name: str
    slots: Mapping[str, Slot]

    @property
    def eight_way(self) -> bool:
        """Decision 170: a wheel with only cardinal items is a cross, and a two-arrow chord there selects nothing."""
        return any(d in self.slots for d in DIAGONALS)


@dataclass(frozen=True)
class Timing:
    """Every timing constant, in ms. The research's section 5 justifies each default, but ``draw_ms``: the research's 333
    held the ring back, and the owner wants the whole wheel at once (decision 175 as changed, release 5.43.1)."""

    tap_ms: int = 200
    release_grace_ms: int = 80
    draw_ms: int = 0
    idle_ms: int = 10_000
    animation_ms: int = 80


@dataclass(frozen=True)
class PanelSettings:
    """The Today side panel's widths and timings (release 5.43). ``hover_ms`` None means Windows' own hover time."""

    rest_width: int = 180
    hover_width: int = 320
    detail_width: int = 420
    hover: bool = True
    hover_ms: int | None = None
    inner_edge_hover_ms: int = 700
    contract_ms: int = 1500
    hide_on_full_screen: bool = True
    exclude_from_capture: bool = False


@dataclass(frozen=True)
class WheelsConfig:
    wheels: tuple[Wheel, ...]
    timing: Timing = Timing()
    today_panel: PanelSettings = PanelSettings()

    def wheel(self, wheel_id: str) -> Wheel | None:
        return next((w for w in self.wheels if w.id == wheel_id), None)


# ---- reading ----
def strip_comments(text: str) -> str:
    """JSON from a file with ``//`` and ``/* */`` comments and trailing commas, minding strings. Newlines stay, so the
    line numbers in a JSON error are the file's."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            chunk = text[i:] if j < 0 else text[i:j + 2]
            out.append("\n" * chunk.count("\n"))
            i = n if j < 0 else j + 2
        elif c in "}]":
            k = len(out) - 1  # a trailing comma before the bracket goes
            while k >= 0 and not out[k].strip():
                k -= 1
            if k >= 0 and out[k] == ",":
                out[k] = ""
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _did_you_mean(word: Any, options: Iterable[str]) -> str:
    close = get_close_matches(str(word), list(options), n=1, cutoff=0.6)
    return f" Did you mean {close[0]}?" if close else ""


def _check_slot(where: str, data: Any, registry: Mapping[str, CommandSpec], icons: set[str], problems: list[str]) -> Slot | None:
    if not isinstance(data, dict):
        problems.append(f"{where}: a slot is an object with a label and a command.")
        return None
    allowed = ("label", "icon", "command", "args", "confirm", "held")
    for key in data:
        if key not in allowed:
            problems.append(f"{where}.{key}: a slot has {', '.join(allowed)}.{_did_you_mean(key, allowed)}")
    label = data.get("label")
    if not isinstance(label, str) or not label.strip():
        problems.append(f"{where}.label: every slot needs a label, as text.")
        label = ""
    icon = data.get("icon", "")
    if icon and icon not in icons:
        problems.append(f"{where}.icon: {icon} isn't one of DocRepo's icons.{_did_you_mean(icon, icons)}")
        icon = ""
    for flag in ("held", "confirm"):
        if flag in data and not isinstance(data[flag], bool):
            problems.append(f"{where}.{flag}: is true or false.")
    if data.get("held") is True:
        return Slot(str(label), str(icon), held=True)
    command = data.get("command")
    if not isinstance(command, str) or not command:
        problems.append(f"{where}.command: every slot needs a command, or \"held\": true to keep the place for later.")
        return None
    spec = registry.get(command)
    if spec is None:
        problems.append(f"{where}.command: {command} isn't a command.{_did_you_mean(command, registry)}")
        return None
    args = data.get("args", {})
    if not isinstance(args, dict):
        problems.append(f"{where}.args: arguments are an object, such as {{ \"view\": \"today\" }}.")
        return None
    known = {a.name: a for a in spec.args}
    for name, value in args.items():
        arg = known.get(name)
        if arg is None:
            takes = f"takes {', '.join(known)}" if known else "takes no arguments"
            problems.append(f"{where}.args.{name}: {command} {takes}.{_did_you_mean(name, known)}")
        elif (why := arg.problem(value)) is not None:
            problems.append(f"{where}.args.{name}: {value} isn't allowed; it {why}.{_did_you_mean(value, arg.choices)}")
    return Slot(str(label), str(icon), command, {**{a.name: a.default for a in spec.args}, **args}, data.get("confirm") is True)


def _check_numbers(where: str, data: Any, kind: type, problems: list[str], least: int = 0) -> Any:
    """A ``Timing`` or ``PanelSettings`` from its object in the file, with its defaults for what's left out."""
    if data is None:
        return kind()
    if not isinstance(data, dict):
        problems.append(f"{where}: is an object.")
        return kind()
    names = {f.name: f for f in fields(kind)}
    values: dict[str, Any] = {}
    for key, value in data.items():
        if key not in names:
            problems.append(f"{where}.{key}: isn't a setting. It has {', '.join(names)}.{_did_you_mean(key, names)}")
            continue
        default = names[key].default
        if isinstance(default, bool):
            if not isinstance(value, bool):
                problems.append(f"{where}.{key}: is true or false.")
                continue
        elif value is None and default is None:
            pass
        elif isinstance(value, bool) or not isinstance(value, int) or value < least:
            problems.append(f"{where}.{key}: is a whole number, {least} or more.")
            continue
        values[key] = value
    return kind(**values)


def check(data: Any, registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> WheelsConfig:
    """A config from the parsed file. Raises ConfigError naming every bad field."""
    problems: list[str] = []
    icon_names = set(icons)
    if not isinstance(data, dict):
        raise ConfigError(["The file holds one JSON object, with \"wheels\" in it."])
    allowed = ("$schema", "wheels", "timing", "today_panel")
    for key in data:
        if key not in allowed:
            problems.append(f"{key}: the file has {', '.join(allowed[1:])}.{_did_you_mean(key, allowed)}")
    raw = data.get("wheels")
    if not isinstance(raw, list) or not raw:
        raise ConfigError([*problems, "wheels: is a list of wheels, with at least one."])
    wheels: list[Wheel] = []
    seen: set[str] = set()
    for i, w in enumerate(raw):
        where = f"wheels[{i}]"
        if not isinstance(w, dict):
            problems.append(f"{where}: a wheel is an object with an id, a name and slots.")
            continue
        for key in w:
            if key not in ("id", "name", "slots"):
                problems.append(f"{where}.{key}: a wheel has id, name and slots.{_did_you_mean(key, ('id', 'name', 'slots'))}")
        wheel_id = w.get("id")
        if not isinstance(wheel_id, str) or not _WHEEL_ID.match(wheel_id):
            problems.append(f"{where}.id: is lower case letters, digits, - and _, such as \"capture\". It's the key in Settings' hotkeys.")
            wheel_id = f"wheel{i}"
        elif wheel_id in seen:
            problems.append(f"{where}.id: {wheel_id} is already another wheel's. Give each wheel its own.")
        seen.add(wheel_id)
        name = w.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{where}.name: every wheel needs a name, as text.")
            name = wheel_id
        slots_in = w.get("slots")
        if not isinstance(slots_in, dict) or not slots_in:
            problems.append(f"{where}.slots: is an object keyed by direction: {', '.join(DIRECTIONS)}.")
            continue
        slots: dict[str, Slot] = {}
        for d, s in slots_in.items():
            if d not in DIRECTIONS:
                problems.append(f"{where}.slots.{d}: isn't a direction. Use {', '.join(DIRECTIONS)}.")
                continue
            slot = _check_slot(f"{where}.slots.{d}", s, registry, icon_names, problems)
            if slot is not None:
                slots[d] = slot
        wheels.append(Wheel(wheel_id, name.strip(), slots))
    timing = _check_numbers("timing", data.get("timing"), Timing, problems)
    panel = _check_numbers("today_panel", data.get("today_panel"), PanelSettings, problems, least=1)
    if problems:
        raise ConfigError(problems)
    return WheelsConfig(tuple(wheels), timing, panel)


def parse(text: str, registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> WheelsConfig:
    """A config from the file's text. Raises ConfigError."""
    try:
        data = json.loads(strip_comments(text))
    except ValueError as e:
        line = f"line {e.lineno}, column {e.colno}" if isinstance(e, json.JSONDecodeError) else "somewhere"
        reason = e.msg if isinstance(e, json.JSONDecodeError) else str(e)
        raise ConfigError([f"{CONFIG_FILE.name}, {line}: this isn't JSON: {reason}. Check for a missing comma or quote."]) from e
    return check(data, registry, icons)


def load(data_root: Path, registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> WheelsConfig:
    """The config file's contents. Raises ConfigError, including when it can't be read."""
    try:
        text = (data_root / CONFIG_FILE).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError([f"{CONFIG_FILE.name} can't be read: {type(e).__name__}."]) from e
    return parse(text, registry, icons)


def schema(registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> dict[str, Any]:
    """The JSON schema VS Code checks the file against, from the same table DocRepo checks it with."""
    def slot_for(spec: CommandSpec) -> dict[str, Any]:
        args = {a.name: {"type": "boolean"} if a.kind == "bool" else {"enum": list(a.choices)} for a in spec.args}
        return {"if": {"properties": {"command": {"const": spec.id}}, "required": ["command"]},
                "then": {"properties": {"args": {"type": "object", "properties": args, "additionalProperties": False}}}}

    slot = {
        "type": "object", "required": ["label"], "additionalProperties": False,
        "properties": {
            "label": {"type": "string", "minLength": 1, "description": "What the wheel shows."},
            "icon": {"enum": sorted(icons), "description": "One of DocRepo's own icons."},
            "command": {"enum": sorted(registry), "markdownEnumDescriptions": [registry[k].title for k in sorted(registry)]},
            "args": {"type": "object"},
            "confirm": {"type": "boolean", "description": "Only lights up, and asks for Enter before it runs."},
            "held": {"type": "boolean", "description": "Keeps the place for later: greyed, and doing nothing."},
        },
        "anyOf": [{"required": ["command"]}, {"required": ["held"]}],
        "allOf": [slot_for(spec) for spec in registry.values()],
    }

    def numbers(kind: type) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for f in fields(kind):
            props[f.name] = {"type": "boolean"} if isinstance(f.default, bool) else {"type": ["integer", "null"] if f.default is None else "integer", "minimum": 0}
        return {"type": "object", "properties": props, "additionalProperties": False}

    return {
        "$schema": "http://json-schema.org/draft-07/schema#", "title": "DocRepo's wheels", "type": "object",
        "required": ["wheels"], "additionalProperties": False,
        "properties": {
            "$schema": {"type": "string"},
            "wheels": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["id", "name", "slots"], "additionalProperties": False,
                "properties": {"id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]*$"}, "name": {"type": "string", "minLength": 1},
                               "slots": {"type": "object", "minProperties": 1, "additionalProperties": False,
                                         "properties": {d: slot for d in DIRECTIONS}}},
            }},
            "timing": numbers(Timing),
            "today_panel": numbers(PanelSettings),
        },
    }


#: The file DocRepo writes the first time, with a comment on every command.
DEFAULT_TEXT = """\
// DocRepo's navigation wheels. Edit this file and save it: DocRepo checks it and reloads it at once. If something's wrong, a
// notification names the field, and the last good wheels stay in use. DocRepo never writes this file again, so your comments stay.
//
// Each wheel gets a hotkey in Settings, under its id. A slot goes under a direction: N, NE, E, SE, S, SW, W or NW. Using only
// N, E, S and W keeps the wheel a cross, and a two-arrow chord there selects nothing. Adding a diagonal makes it 8-way, and
// nothing that was there moves. A slot has a label, and:
//   "icon"     one of DocRepo's icons (wheels.schema.json lists them; VS Code offers them as you type)
//   "command"  one of the commands below, with its "args"
//   "confirm"  true: the slot only lights up, and asks for Enter before it runs
//   "held"     true: keeps the place for later, greyed and doing nothing
{
  "$schema": "./wheels.schema.json",
  "wheels": [
    {
      "id": "capture",
      "name": "Capture",
      "slots": {
        // capture.new: the capture window, truly blank; a draft is set aside, and comes back when you save or close this one.
        //   args: "mode" is note, new_task or update; "blank": false opens on the draft instead.
        "N": { "label": "Blank capture", "icon": "add", "command": "capture.new" },
        // capture.selection: the pinned window, with the email or file selected in the window you were in.
        "E": { "label": "Email or file", "icon": "mail", "command": "capture.selection" },
        // today.new_item: a quick task on Today.
        "S": { "label": "Today item", "icon": "sun", "command": "today.new_item" },
        // capture.meeting: meeting notes.
        "W": { "label": "Meeting", "icon": "people", "command": "capture.meeting" }
        // capture.pin: the plain pinned window, on no wheel by default. To use it, add a comma after the line above, and:
        // "NE": { "label": "Pinned", "icon": "pin", "command": "capture.pin" }
      }
    },
    {
      "id": "browse",
      "name": "Browse",
      "slots": {
        // browse.view: the browse tool on a view. "view" is any of its views: today, tasks, agenda, activity, priorities and so on.
        "N": { "label": "Task tree", "icon": "tasks", "command": "browse.view", "args": { "view": "tasks" } },
        // search.tasks: task search. "then" is what Enter opens: task_view, or page (the task's page in the browse tool); Ctrl+Enter opens the other.
        "E": { "label": "Task search", "icon": "task", "command": "search.tasks" },
        // search.files: file search, across every task's files and saved emails.
        "S": { "label": "File search", "icon": "file", "command": "search.files" },
        // search.everything: the browse tool, with the cursor in Search everything.
        "W": { "label": "Search everything", "icon": "search", "command": "search.everything" }
      }
    },
    {
      "id": "execution",
      "name": "Execution",
      "slots": {
        "N": { "label": "Today", "icon": "sun", "command": "browse.view", "args": { "view": "today" } },
        // today.panel: the Today side panel. "do" is toggle, open or close.
        "E": { "label": "Today panel", "icon": "sidebar", "command": "today.panel" },
        // The agent window's place, for when it comes.
        "S": { "label": "Agent window", "held": true },
        // task_view.current: the Task view of the task selected in the browse tool, or of the last Task view opened.
        "W": { "label": "Task view", "icon": "open", "command": "task_view.current" }
      }
    }
  ],
  // Times are in ms. tap_ms: a hotkey up by then leaves the wheel open. release_grace_ms: a diagonal's second key has this long.
  // draw_ms: 0 shows the whole wheel at once. Above that, only its centre shows until then, so a pick made by then never shows the rest.
  // idle_ms: an untouched wheel closes then. animation_ms: that later ring's fade in, and the panel's widening (0 for none; none when Windows' animation effects are off).
  "timing": { "tap_ms": 200, "release_grace_ms": 80, "draw_ms": 0, "idle_ms": 10000, "animation_ms": 80 },
  // The Today side panel. hover_ms: null uses Windows' own hover time (0.4 s). inner_edge_hover_ms: on an edge between monitors.
  // exclude_from_capture: keeps it out of screen shares, and so out of screenshots and compliance recordings too. Ask IT first.
  "today_panel": { "rest_width": 180, "hover_width": 320, "detail_width": 420, "hover": true, "hover_ms": null,
                   "inner_edge_hover_ms": 700, "contract_ms": 1500, "hide_on_full_screen": true, "exclude_from_capture": false }
}
"""


#: What releases 5.41 to 5.43 wrote about ``draw_ms``.
_OLD_DRAW_COMMENT = "// draw_ms: the full wheel draws then, so a pick made by then never shows it (0 draws it at once)."
_OLD_DRAW_VALUE = '"draw_ms": 333'
_DRAW_COMMENT = "// draw_ms: 0 shows the whole wheel at once. Above that, only its centre shows until then, so a pick made by then never shows the rest."


def draw_at_once(text: str) -> str:
    """Release 5.43.1: a file that still has the old value beside the old comment shows the whole wheel at once. The old
    comment goes with it, so a 333 you set yourself afterwards stays, and every other line is left as it was."""
    if _OLD_DRAW_COMMENT in text and _OLD_DRAW_VALUE in text:
        return text.replace(_OLD_DRAW_COMMENT, _DRAW_COMMENT).replace(_OLD_DRAW_VALUE, '"draw_ms": 0')
    return text


def write_defaults(fs: SafeFS, data_root: Path, registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> None:
    """The config file, if there isn't one, and always the schema beside it, which is DocRepo's own."""
    path = data_root / CONFIG_FILE
    if not path.exists():
        fs.write_text(path, DEFAULT_TEXT)
    else:
        try:
            text = path.read_bytes().decode("utf-8-sig")  # as bytes, so its line endings stay
        except (OSError, UnicodeDecodeError):
            text = ""  # loading it says what's wrong
        if draw_at_once(text) != text:
            fs.write_text(path, draw_at_once(text))
    fs.write_text(data_root / SCHEMA_FILE, json.dumps(schema(registry, icons), indent=1) + "\n")


def hotkey_rows(data_root: Path, registry: Mapping[str, CommandSpec], icons: Iterable[str]) -> list[tuple[str, str]]:
    """Each wheel's (id, name) for Settings' hotkey boxes: the file's, or the default's when it can't be used."""
    try:
        config = load(data_root, registry, icons)
    except ConfigError:
        config = parse(DEFAULT_TEXT, registry, icons)
    return [(w.id, w.name) for w in config.wheels]
