"""The design tokens' colours (``docrepo.ui.tokens`` has the rest: type, sizes, the palette and the style sheets).

They're kept here, outside ``docrepo.ui``, so the pages' HTML made without Qt (``detail``, ``markup``) names them too,
and the fast run still imports no Qt. Release 5.180 (the redesign's decision 841) made them answer from a theme: ``use``
sets the active set, light or dark, and ``colour``, ``C``, ``active`` and the live tables answer from it when they're
read, so a theme set at start-up reaches everything drawn after it. ``docrepo.ui.tokens`` re-exports all of this.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

# ---- colour (decisions 8, 9, 11 to 13; contrast checked against WCAG 2.2 AA) ----
LIGHT = {
    # Release 5.181 (the redesign's decisions 842 and 843, its plan's section 3): hue-free greys and an indigo accent.
    "base": "#f6f6f7",        # the frame: the sidebar, the top bar, footers
    "content": "#ffffff",     # the surface: lists, pages, inputs, cards
    "sunken": "#f4f4f6",      # panels inside the surface, soft buttons, the type strip
    "field": "#ebebee",       # a field set on the frame (the search box)
    "hover": "#f0f0f2",       # under the pointer, and the secondary button's fill
    "pressed": "#e6e6ea",
    "nav_selected": "#e8e8eb",  # the sidebar's open view
    "selected": "#edeefa",    # a selected row: the accent's tint
    "now": "#f4f5fd",         # the current task's row under Now on Today (release 5.177, decision 828): lighter than selected
    "text": "#18181b",        # 17.7:1 on white
    "text2": "#5c5c66",       # descriptions and commands, 6.6:1 on white
    "text3": "#74747e",       # facts, the names of facts, dates and counts, 4.6:1 on white
    "disabled": "#a1a1aa",    # disabled controls only
    "stroke": "#ececef",      # the one hairline: cards, dividers, pane edges
    "stroke_strong": "#dedee3",  # a field's even edge (decision 848)
    "control": "#b9b9c2",     # a tick box's edge
    "accent": "#4a54d1",      # the accent as ink (decision 844's six jobs): focus, the open view's icon, in progress, links
    "accent_fill": "#4a54d1",  # the accent as a fill: the primary button, a ticked box; white on it is 6.0:1
    "accent_hover": "#414ab8",
    "accent_pressed": "#3a42a3",
    "on_accent": "#ffffff",
    "info_bg": "#edeefa", "info_line": "#c9cdf3",  # the accent's family where nothing is selected: chips, a mention, a drop's overlay
    "parked": "#6b5fa8", "parked_bg": "#efedf7",
    "caution": "#a85a00", "caution_bg": "#fdf1dc", "caution_line": "#f1d9a8",   # filled from the capture text, warnings
    "critical": "#c9302c", "critical_bg": "#fdecea",                           # overdue, over capacity, errors
    "success": "#177a3a", "success_bg": "#e3f4e8",
    "scroll": "#cfcfd6", "scroll_hover": "#a9a9b3",
    # Plant events: their bars, lane and band.
    "event": "#b07a12", "event_bg": "#f7e3b5", "event_ink": "#6e4700",
    # The Timeline's lanes: a small dot beside dark words, never the words' colour or a band of it (the review's decision V4).
    "lane1": "#2a78d6", "lane2": "#eb6834", "lane3": "#1baf7a", "lane4": "#eda100", "lane5": "#e87ba4", "lane6": "#008300", "lane7": "#6250d6", "lane8": "#e34948",
    # Hours a week on the Timeline's bars, light to dark, and the text on each.
    "hour1": "#86b6ef", "hour2": "#5598e7", "hour3": "#256abf", "hour4": "#184f95", "hour5": "#0d366b",
    "hour_ink1": "#0b1b2e", "hour_ink2": "#0b1b2e", "hour_ink3": "#ffffff", "hour_ink4": "#ffffff", "hour_ink5": "#ffffff",
    # The Timeline page (release 5.40): bars' one colour, the team chart's hours within capacity, and a week's load, a cell's
    # steps from under 40% to 125% or more, with the text on the last.
    "bar": "#6e6e7a", "bar_soft": "#a6a6b0",
    "load1": "#f4f4f5", "load2": "#e1e2e3", "load3": "#f7d894", "load4": "#e6a6a0", "load5": "#b3261a", "load5_ink": "#ffffff",
    # The capture window's item cards, each kind's edge, and its references.
    "item_task": "#e3ecf7", "item_note": "#e0f1ee", "item_update": "#f6ecd8", "item_decision": "#ece6f6", "item_date": "#e8f0dc", "item_heading": "#e9edf1",
    "ref_task": "#22706a", "ref_task_bg": "#d6eeea",
    # Categories: the top-level tasks' colours (decision 9), as marks, never as text.
    "g1": "#3b78c4", "g2": "#2e9483", "g3": "#c08419", "g4": "#8460c2",
    # Priorities (release 5.81): a task row's left edge, as marks, never as text, each 3:1 or more on white and on hover.
    "pri_critical": "#c42b1c", "pri_high": "#c27400", "pri_medium": "#3b78c4", "pri_parking": "#7f8b98",
    # File types (the Task view, release 5.34): their icons' colours only, never text's, each 3:1 or more on white.
    "type_doc": "#2b579a", "type_sheet": "#217346", "type_slides": "#c43e1c", "type_pdf": "#b30b00", "type_picture": "#8460c2",
    "type_mail": "#1d5e98", "type_drawing": "#2e9483", "type_link": "#5a6571", "type_other": "#5a6571",
    # Colours that were written as numbers outside the tokens until release 5.180 (decision 841), at the values they had.
    # The bars beside a follow-up's lines in its meeting's notes, a meeting's unfolded notes and moved lines (``detail``).
    "nest_bar": "#c9cdf3", "unfold_bar": "#dedee3", "moved_bar": "#7fb7a8",  # info_line's and stroke_strong's values since 5.181
    # Ticked checklist lines' words (decision 91) and the highlights, as pages and the editor show them (``markup``).
    "ticked": "#5c5c66", "mark_yellow": "#fff1a8", "mark_green": "#cdeccd", "mark_pink": "#f8d0e3",
    # DocRepo's own icon, for the tray, the title bars and the taskbar (``app.make_icon``): the same in every theme.
    "brand": "#1d5e98", "brand_ink": "#ffffff",
    # Lane D, release 5.187 (decision 863): a confirmation's doing button for what can't be undone, filled as the primary is.
    "critical_fill": "#c9302c", "critical_hover": "#b32a27", "critical_pressed": "#9e2522",
}
#: The dark theme's values (decision 14): the same names. Not offered yet; release 5.194 settles how dark looks.
DARK = {
    "base": "#141416", "content": "#1b1b1e", "sunken": "#232327", "field": "#222226", "hover": "#26262b", "pressed": "#2e2e34",
    "nav_selected": "#2a2a30", "selected": "#262a4f", "now": "#20223a",
    "text": "#ececef", "text2": "#a3a3ad", "text3": "#82828c", "disabled": "#5f5f68", "stroke": "#28282d", "stroke_strong": "#38383f",
    "control": "#55555e", "accent": "#8f97f7", "accent_fill": "#5760dd", "accent_hover": "#6670e4", "accent_pressed": "#4d56cf", "on_accent": "#ffffff",
    "info_bg": "#262a4f", "info_line": "#3d4380", "parked": "#b3a8e6", "parked_bg": "#2d2b3d",
    "event": "#dca64a", "event_bg": "#3a2e13", "event_ink": "#f0d49a",
    "lane1": "#6fa6e8", "lane2": "#f08a69", "lane3": "#56c2b0", "lane4": "#dca64a", "lane5": "#ee9fbd", "lane6": "#5cbf86", "lane7": "#ad8ee8", "lane8": "#f3968e",
    "hour1": "#1c3a5e", "hour2": "#25507f", "hour3": "#3a70ad", "hour4": "#6699d4", "hour5": "#9cc0ea",
    "hour_ink1": "#ffffff", "hour_ink2": "#ffffff", "hour_ink3": "#ffffff", "hour_ink4": "#0b1b2e", "hour_ink5": "#0b1b2e",
    "bar": "#8e8e9a", "bar_soft": "#5c5c66",
    "load1": "#343434", "load2": "#454545", "load3": "#6b5220", "load4": "#8a3a32", "load5": "#e8776c", "load5_ink": "#1b1b1b",
    "item_task": "#1f3447", "item_note": "#1c3532", "item_update": "#3a2e13", "item_decision": "#2d2b3d", "item_date": "#26331c", "item_heading": "#333333",
    "ref_task": "#56c2b0", "ref_task_bg": "#1c3532",
    "caution": "#e5b25d", "caution_bg": "#3a2e13", "caution_line": "#5a4720", "critical": "#f0857d", "critical_bg": "#3e1f1c",
    "success": "#6fcf8e", "success_bg": "#1b3323", "scroll": "#4a4a52", "scroll_hover": "#6a6a74",
    "g1": "#6fa6e8", "g2": "#56c2b0", "g3": "#dca64a", "g4": "#ad8ee8",
    "pri_critical": "#f3968e", "pri_high": "#e8b85c", "pri_medium": "#6fa6e8", "pri_parking": "#8a949e",
    "type_doc": "#7fa7e6", "type_sheet": "#5cbf86", "type_slides": "#f08a69", "type_pdf": "#f3968e", "type_picture": "#ad8ee8",
    "type_mail": "#7cb0e2", "type_drawing": "#56c2b0", "type_link": "#a0aab4", "type_other": "#a0aab4",
    "nest_bar": "#3d4380", "unfold_bar": "#38383f", "moved_bar": "#4f8f80",
    "ticked": "#a3a3ad", "mark_yellow": "#5a4d12", "mark_green": "#1f4224", "mark_pink": "#4d2438",
    "brand": "#1d5e98", "brand_ink": "#ffffff",
    # Lane D, release 5.187: the danger button's fill, dark enough for white words (6.5 to 1), as accent_fill is.
    "critical_fill": "#b8372f", "critical_hover": "#c4453c", "critical_pressed": "#a3302a",
}

#: The themes by name.
THEMES: dict[str, dict[str, str]] = {"light": LIGHT, "dark": DARK}
_active = ["light"]


def use(theme_name: str) -> None:
    """Make ``theme_name`` ("light" or "dark") the active set of colours. Anything else is refused."""
    if theme_name not in THEMES:
        raise ValueError(f"There's no theme called {theme_name!r}: DocRepo's themes are {' and '.join(THEMES)}")
    _active[0] = theme_name


def theme() -> str:
    """The active theme's name."""
    return _active[0]


def active() -> dict[str, str]:
    """The active theme's colours, by name (read them, don't change them)."""
    return THEMES[_active[0]]


def colour(name: str) -> str:
    """A colour token's value in the active theme, as #rrggbb."""
    return THEMES[_active[0]][name]


class _Named:
    """The colours by name, for f-strings: ``{C.text2}``, in the active theme."""

    def __getattr__(self, name: str) -> str:
        try:
            return THEMES[_active[0]][name]
        except KeyError:
            raise AttributeError(name) from None


C = _Named()


def _resolve(value: str | tuple[str, ...]) -> str | tuple[str, ...]:
    return colour(value) if isinstance(value, str) else tuple(colour(v) for v in value)


class LiveMap(Mapping):
    """A table of token names (or tuples of them) that answers with the active theme's colours when it's read, so a
    module's table of colours, made when it's imported, follows a theme set after that."""

    def __init__(self, names: Mapping[str, str | tuple[str, ...]]) -> None:
        self.names = dict(names)

    def __getitem__(self, key: str) -> str | tuple[str, ...]:
        return _resolve(self.names[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def __len__(self) -> int:
        return len(self.names)


class LiveList(Sequence):
    """A list of token names that answers with the active theme's colours when it's read."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = tuple(names)

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        if isinstance(index, slice):
            return tuple(colour(n) for n in self.names[index])
        return colour(self.names[index])

    def __len__(self) -> int:
        return len(self.names)
