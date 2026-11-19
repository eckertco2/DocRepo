"""Urgency within a priority (release 5.176, the design workspace's ``docs/mods/urgency-plan.md``, decisions 820 to 822),
driven offscreen over the sample data: a band in two halves in the Today view and the side panel, the hairline between them
only when there are two, a drag kept to its half, the bins' ten targets, and a drop's words with Undo. Made-up tasks: three
in High, one of them ticked Urgent and one due tomorrow."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from docrepo import edits, priorities  # noqa: E402
from docrepo.model import TODAY_BANDS, Model  # noqa: E402
from docrepo.ui import today_bins  # noqa: E402
from docrepo.ui.lists.today import RULE_TIP  # noqa: E402
from docrepo.ui.tree_view import RULE_ROLE  # noqa: E402

from test_today_order_ui import panel_row, rows_in_order, row_drop, show_today, today_row, wide  # noqa: E402
import test_today_priority_ui as shared  # noqa: E402

NOW = shared.NOW
qapp, app, panel = shared.qapp, shared.app, shared.panel  # the fixtures, shared


def put(app) -> dict[str, int]:
    """High: Rigging plan (not urgent), the guard drawings (ticked Urgent) and the alignment contractor (due tomorrow), added
    in that order."""
    c = app.ctx
    c.conn.execute("UPDATE tasks SET urgent = 0, due = '2026-11-30', deadline = NULL WHERE id = 'T000012'")
    c.conn.execute("UPDATE tasks SET urgent = 1, due = '2026-11-30', deadline = NULL WHERE id = 'T000018'")
    c.conn.execute("UPDATE tasks SET urgent = 0, due = '2026-10-09', deadline = NULL WHERE id = 'T000019'")
    for t in ("T000012", "T000018", "T000019"):
        priorities.place(c.conn, t, "high", None, at=NOW, via=priorities.VIA)
        edits.add_to_today(c.conn, c.data_root, c.fs, t, "", NOW)
    app.browse.refresh(render=False)
    if app.panel is not None:
        app.panel.refresh()
    by = {a.subject: a.id for a in Model(c.conn).today_items()}
    return {"plain": by["T000012"], "ticked": by["T000018"], "soon": by["T000019"]}


def part_point(bins: today_bins.Bins, target: tuple[str, bool]) -> QPoint:
    rect = dict(bins.parts())[target]
    return bins.mapTo(bins.parentWidget(), rect.center())


def test_the_view_puts_the_urgent_first_with_a_hairline(app):
    i = put(app)
    browse = show_today(app)
    tree = browse.tree
    assert rows_in_order(tree)[-3:] == [i["ticked"], i["soon"], i["plain"]]  # decision 820
    rule = today_row(tree, i["plain"])
    assert rule.data(0, RULE_ROLE) == today_bins.colour_of("high").name() and RULE_TIP in rule.toolTip(0)
    assert not today_row(tree, i["ticked"]).data(0, RULE_ROLE) and not today_row(tree, i["soon"]).data(0, RULE_ROLE)
    assert "Urgent: due Fri 9 Oct" in today_row(tree, i["soon"]).toolTip(0)  # why, by its date (decision 821)
    # One half only: no hairline.
    app.ctx.conn.execute("UPDATE tasks SET urgent = 0, due = '2026-11-30' WHERE id IN ('T000018', 'T000019')")
    browse.refresh()
    QApplication.processEvents()
    assert not any(today_row(browse.tree, x).data(0, RULE_ROLE) for x in i.values())


def test_a_drag_in_the_view_stays_in_its_half(app):
    i = put(app)
    browse = show_today(app)
    row_drop(browse, i["plain"], i["ticked"], "before")  # across the hairline: refused
    assert rows_in_order(browse.tree)[-3:] == [i["ticked"], i["soon"], i["plain"]]
    row_drop(browse, i["soon"], i["ticked"], "before")  # inside the urgent half
    assert rows_in_order(browse.tree)[-3:] == [i["soon"], i["ticked"], i["plain"]]


def test_the_bins_ten_targets_and_a_drop_on_the_urgent_part_with_undo(app):
    i = put(app)
    browse = show_today(app)
    tree = browse.tree
    own, counts, own_urgent = browse._today_bins_for(("today", i["plain"]))
    assert (own, own_urgent) == ("high", False)
    tree._bins.open_for(own, counts, tree.viewport().rect(), own_urgent)
    bins = tree._bins
    targets = {t for t, _r in bins.parts()}
    assert len(targets) == 10 and targets == {(b, u) for b in TODAY_BANDS for u in (True, False)}
    found = {t: bins.bin_at(tree.viewport().mapToGlobal(bins.mapTo(tree.viewport(), dict(bins.parts())[t].center()))) for t in targets}
    assert found[("high", False)] is None and found[("high", True)] == ("high", True)  # its own part no target, the other one
    assert all(found[t] == t for t in targets if t != ("high", False))
    tree._bins.close_bins()
    assert browse.bin_today(i["plain"], "high", urgent=True)  # its band's urgent part: ticked, the priority kept
    m = Model(app.ctx.conn)
    assert m.task("T000012").urgent and m.task("T000012").priority == "high"
    assert "Rigging plan: High, urgent." in browse.status.text() and "Undo" in browse.status.text()
    browse._status_link("undo")
    assert not Model(app.ctx.conn).task("T000012").urgent
    assert rows_in_order(browse.tree)[-3:] == [i["ticked"], i["soon"], i["plain"]]


def test_the_panel_in_two_halves_with_its_hairline_and_bins(app, panel, monkeypatch):
    i = put(app)
    panel.hover.contract()
    panel.refresh()
    rows = {r.item_id: r for r in panel.rows}
    assert [r.item_id for r in panel.rows] == [i["ticked"], i["soon"], i["plain"]]
    assert rows[i["plain"]].rule and not rows[i["ticked"]].rule and not rows[i["soon"]].rule  # at rest too, in no row's height
    height = rows[i["ticked"]].sizeHint().height()
    assert rows[i["plain"]].sizeHint().height() == height
    wide(panel)
    lines = {name: tip for name, _do, tip in panel._move_lines(panel_row(panel, i["plain"]))}
    assert lines == {}  # alone in its half: nowhere to move
    lines = {name: tip for name, _do, tip in panel._move_lines(panel_row(panel, i["soon"]))}
    assert set(lines) == {"Move to top"} and "the urgent tasks" in lines["Move to top"]
    panel._open_bins(panel_row(panel, i["soon"]))
    assert (panel.bins.own, panel.bins.own_urgent) == ("high", True)
    at = panel.mapToGlobal(part_point(panel.bins, ("high", True)))
    assert panel.bins.bin_at(at) is None and panel.bins.bin_at(panel.mapToGlobal(part_point(panel.bins, ("high", False)))) == ("high", False)
    panel.bins.close_bins()
    panel.bin_item(i["soon"], ("medium", False))  # its date keeps it first
    assert panel.note_label.text() == "Book the alignment contractor: Medium. Still first: it's due Fri 9 Oct."
    assert Model(app.ctx.conn).task("T000019").priority == "medium"


def test_the_keyboards_order_is_the_shown_order(app, panel):
    """Up and Down walk the rows as drawn, which ``views.today_order`` drew (decision 820)."""
    i = put(app)
    wide(panel)
    panel._move_cursor(0)
    assert panel.rows[panel.cursor].item_id == i["ticked"]
    panel._move_cursor(2)
    assert panel.rows[panel.cursor].item_id == i["plain"]
