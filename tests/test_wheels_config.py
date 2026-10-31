"""The wheels' config file (release 5.41, decision 174): comments, checking, and what each problem says."""
from __future__ import annotations

import json

import pytest

from docrepo import wheels_config as wc
from docrepo.safe_fs import SafeFS, WriteRefused
from docrepo.ui.wheel_commands import REGISTRY, SPECS, icon_names

ICONS = icon_names()


def problems(data) -> list[str]:
    with pytest.raises(wc.ConfigError) as e:
        wc.check(data, SPECS, ICONS)
    return e.value.problems


def wheel(slots, **rest) -> dict:
    return {"wheels": [{"id": "capture", "name": "Capture", "slots": slots}], **rest}


# ---- stripping comments ----
def test_line_comments_go_and_strings_stay():
    text = '{ "a": "http://x//y", // a comment\n  "b": "/* no */" }'
    assert json.loads(wc.strip_comments(text)) == {"a": "http://x//y", "b": "/* no */"}


def test_block_comments_go_and_keep_their_line_numbers():
    text = '{\n/* one\ntwo */\n"a": }'
    with pytest.raises(json.JSONDecodeError) as e:
        json.loads(wc.strip_comments(text))
    assert e.value.lineno == 4


def test_trailing_commas_go():
    assert json.loads(wc.strip_comments('{ "a": [1, 2, ], "b": 3, // last\n }')) == {"a": [1, 2], "b": 3}


def test_an_escaped_quote_doesnt_end_a_string():
    assert json.loads(wc.strip_comments(r'{ "a": "say \"hi\" // not a comment" }')) == {"a": 'say "hi" // not a comment'}


# ---- the default file ----
def test_the_default_file_is_the_decided_wheels():
    config = wc.parse(wc.DEFAULT_TEXT, SPECS, ICONS)
    assert [w.id for w in config.wheels] == ["capture", "browse", "execution"]
    assert {d: s.command for d, s in config.wheel("capture").slots.items()} == {
        "N": "capture.new", "E": "capture.selection", "S": "today.new_item", "W": "capture.meeting"}
    assert {d: s.command for d, s in config.wheel("browse").slots.items()} == {
        "N": "browse.view", "E": "search.tasks", "S": "search.files", "W": "search.everything"}
    execution = config.wheel("execution").slots
    assert execution["N"].args == {"view": "today"} and execution["E"].command == "today.panel"
    assert execution["S"].held and not execution["S"].command and execution["W"].command == "task_view.current"
    assert not any(w.eight_way for w in config.wheels)


def test_the_default_file_comments_every_command():
    for command in SPECS:
        assert command in wc.DEFAULT_TEXT, command


def test_timing_defaults_match_the_research_and_the_wheel_draws_at_once():
    t = wc.parse(wc.DEFAULT_TEXT, SPECS, ICONS).timing
    assert (t.tap_ms, t.release_grace_ms, t.draw_ms, t.idle_ms) == (200, 80, 0, 10000) and t.animation_ms <= 100
    assert wc.Timing() == t


def test_task_search_opens_the_task_view_unless_a_slot_says_otherwise():
    """Decision 213 as the owner changed it (release 5.43.1)."""
    assert wc.parse(wc.DEFAULT_TEXT, SPECS, ICONS).wheel("browse").slots["E"].args == {"then": "task_view"}
    slot = wc.check(wheel({"E": {"label": "A", "command": "search.tasks", "args": {"then": "page"}}}), SPECS, ICONS).wheels[0].slots["E"]
    assert slot.args == {"then": "page"}


def test_a_diagonal_item_makes_a_wheel_eight_way():
    config = wc.check(wheel({"N": {"label": "A", "command": "capture.new"}, "NE": {"label": "B", "command": "capture.pin"}}), SPECS, ICONS)
    assert config.wheels[0].eight_way


def test_args_get_their_defaults():
    slot = wc.check(wheel({"N": {"label": "A", "command": "capture.new"}}), SPECS, ICONS).wheels[0].slots["N"]
    assert slot.args == {"mode": None, "blank": True}


def test_any_number_of_wheels():
    data = {"wheels": [{"id": f"w{n}", "name": f"W{n}", "slots": {"N": {"label": "A", "command": "capture.pin"}}} for n in range(6)]}
    assert len(wc.check(data, SPECS, ICONS).wheels) == 6


# ---- problems name the field ----
def test_a_mistyped_command_names_the_field_and_suggests():
    assert problems(wheel({"NE": {"label": "A", "command": "capture.pinn"}})) == [
        "wheels[0].slots.NE.command: capture.pinn isn't a command. Did you mean capture.pin?"]


def test_a_bad_direction():
    assert "isn't a direction" in problems(wheel({"UP": {"label": "A", "command": "capture.pin"}}))[0]


def test_a_missing_label_and_command():
    found = problems(wheel({"N": {"icon": "add"}}))
    assert any(p.startswith("wheels[0].slots.N.label:") for p in found) and any(p.startswith("wheels[0].slots.N.command:") for p in found)


def test_a_misspelt_slot_field_suggests():
    assert "Did you mean label?" in problems(wheel({"N": {"lable": "A", "label": "B", "command": "capture.pin"}}))[0]


def test_an_unknown_icon():
    assert "isn't one of DocRepo's icons" in problems(wheel({"N": {"label": "A", "icon": "nope", "command": "capture.pin"}}))[0]


def test_a_bad_argument_value_lists_the_choices():
    found = problems(wheel({"N": {"label": "A", "command": "browse.view", "args": {"view": "todya"}}}))
    assert "wheels[0].slots.N.args.view" in found[0] and "Did you mean today?" in found[0]


def test_an_unknown_argument():
    assert "capture.pin takes no arguments" in problems(wheel({"N": {"label": "A", "command": "capture.pin", "args": {"x": 1}}}))[0]


def test_a_wrong_typed_argument():
    assert "is true or false" in problems(wheel({"N": {"label": "A", "command": "capture.new", "args": {"blank": "yes"}}}))[0]


def test_two_wheels_with_one_id():
    data = {"wheels": [{"id": "a", "name": "A", "slots": {"N": {"label": "L", "command": "capture.pin"}}},
                       {"id": "a", "name": "B", "slots": {"N": {"label": "L", "command": "capture.pin"}}}]}
    assert "already another wheel's" in problems(data)[0]


def test_a_bad_id():
    assert problems({"wheels": [{"id": "Not OK", "name": "A", "slots": {"N": {"label": "L", "command": "capture.pin"}}}]})[0].startswith("wheels[0].id:")


def test_no_wheels():
    assert problems({"wheels": []})[0].startswith("wheels:")


def test_a_bad_timing():
    assert problems(wheel({"N": {"label": "L", "command": "capture.pin"}}, timing={"tap_ms": "fast"}))[0].startswith("timing.tap_ms:")
    assert "Did you mean tap_ms?" in problems(wheel({"N": {"label": "L", "command": "capture.pin"}}, timing={"tap_mss": 1}))[0]


def test_a_bad_panel_setting():
    assert problems(wheel({"N": {"label": "L", "command": "capture.pin"}}, today_panel={"hover": "yes"}))[0].startswith("today_panel.hover:")


def test_a_held_slot_needs_no_command():
    slot = wc.check(wheel({"S": {"label": "Later", "held": True}}), SPECS, ICONS).wheels[0].slots["S"]
    assert slot.held and slot.command == ""


def test_not_json_says_where():
    with pytest.raises(wc.ConfigError) as e:
        wc.parse('{ "wheels": [ }', SPECS, ICONS)
    assert "line 1" in str(e.value) and "isn't JSON" in str(e.value)


def test_a_config_cannot_name_anything_but_the_registry():
    """A slot can't start a program: only the table's IDs are commands."""
    assert "isn't a command" in problems(wheel({"N": {"label": "A", "command": "notepad.exe"}}))[0]
    assert set(SPECS) == set(REGISTRY)


# ---- the files ----
def test_the_files_are_written_once_and_comments_stay(data_root, fs):
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    path = data_root / wc.CONFIG_FILE
    assert path.read_text(encoding="utf-8") == wc.DEFAULT_TEXT
    json.loads((data_root / wc.SCHEMA_FILE).read_text(encoding="utf-8"))
    path.write_text("// mine\n" + wc.DEFAULT_TEXT, encoding="utf-8")
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    assert path.read_text(encoding="utf-8").startswith("// mine\n")


OLD_TIMING = ('  // draw_ms: the full wheel draws then, so a pick made by then never shows it (0 draws it at once).\r\n'
              '  "timing": { "tap_ms": 150, "draw_ms": 333 },\r\n')


def test_a_file_from_before_draws_the_whole_wheel_at_once_and_keeps_the_rest(data_root, fs):
    """Release 5.43.1: the default alone wouldn't reach a file that already says 333."""
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    path = data_root / wc.CONFIG_FILE
    text = wc.DEFAULT_TEXT.replace('  "timing": { "tap_ms": 200, "release_grace_ms": 80, "draw_ms": 0, "idle_ms": 10000, "animation_ms": 80 },\n', OLD_TIMING)
    path.write_bytes(("// mine\r\n" + text).encode("utf-8"))
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    now = path.read_bytes().decode("utf-8")
    assert now.startswith("// mine\r\n") and '"tap_ms": 150, "draw_ms": 0 },\r\n' in now and "the full wheel draws then" not in now
    assert wc.load(data_root, SPECS, ICONS).timing.draw_ms == 0


def test_a_wait_you_set_yourself_stays(data_root, fs):
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    path = data_root / wc.CONFIG_FILE
    for mine in (OLD_TIMING.replace('"draw_ms": 333', '"draw_ms": 200'), OLD_TIMING.replace("the full wheel draws then", "my own words")):
        path.write_bytes(mine.encode("utf-8"))
        wc.write_defaults(fs, data_root, SPECS, ICONS)
        assert path.read_bytes().decode("utf-8") == mine
    upgraded = wc.draw_at_once(OLD_TIMING).replace('"draw_ms": 0', '"draw_ms": 333')  # back to 333 by hand, after the change
    assert wc.draw_at_once(upgraded) == upgraded


def test_a_config_with_a_byte_order_mark_loads(data_root, fs):
    wc.write_defaults(fs, data_root, SPECS, ICONS)
    (data_root / wc.CONFIG_FILE).write_text(wc.DEFAULT_TEXT, encoding="utf-8-sig")
    assert wc.load(data_root, SPECS, ICONS).wheels


def test_the_schema_lists_the_commands_and_directions():
    schema = wc.schema(SPECS, ICONS)
    item = schema["properties"]["wheels"]["items"]["properties"]["slots"]
    assert sorted(item["properties"]) == sorted(["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
    assert set(item["properties"]["N"]["properties"]["command"]["enum"]) == set(SPECS)


def test_settings_rows_fall_back_on_the_default(data_root, fs):
    assert wc.hotkey_rows(data_root, SPECS, ICONS) == [("capture", "Capture"), ("browse", "Browse"), ("execution", "Execution")]
    fs.write_text(data_root / wc.CONFIG_FILE, '{"wheels":[{"id":"x","name":"X","slots":{"N":{"label":"A","command":"capture.pin"}}}]}')
    assert wc.hotkey_rows(data_root, SPECS, ICONS) == [("x", "X")]


def test_safe_fs_writes_the_new_kinds_and_only_inside_the_data_root(data_root, tmp_path):
    fs = SafeFS([data_root])
    fs.write_text(data_root / "Config" / "a.jsonc", "{}")
    fs.append_text(data_root / "System" / "logs" / "a.csv", "x\r\n")
    fs.append_text(data_root / "System" / "logs" / "a.csv", "y\r\n")
    assert (data_root / "System" / "logs" / "a.csv").read_bytes() == b"x\r\ny\r\n"
    with pytest.raises(WriteRefused):
        fs.append_text(tmp_path / "outside.csv", "x")
    with pytest.raises(WriteRefused):
        fs.append_text(data_root / "a.exe", "x")
