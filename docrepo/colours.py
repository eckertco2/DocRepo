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
    "base": "#f4f6f8",        # the window's base layer: the sidebar, toolbars, footers
    "content": "#ffffff",     # the content layer: lists, pages, inputs, cards
    "hover": "#eef1f4",
    "pressed": "#e3e7ec",
    "selected": "#dbe8f5",    # a selected row, with the accent bar beside it
    "now": "#eef4fb",         # the current task's row under Now on Today (release 5.177, decision 828): lighter than selected
    "text": "#1a1f25",        # 16.6:1 on white
    "text2": "#5a6571",       # secondary text, 5.9:1 on white
    "disabled": "#87919c",    # disabled controls only
    "stroke": "#e3e6ea",      # cards, dividers, pane edges, an input's outline
    "stroke_strong": "#d6dce3",
    "control": "#7d8793",     # an input's bottom edge, a tick box's outline: 3.6:1 on white
    "accent": "#1d5e98",      # the one accent: primary buttons, links, focus, selection
    "accent_hover": "#174d7d",
    "accent_pressed": "#123e66",
    "on_accent": "#ffffff",
    "info_bg": "#e8f0f8", "info_line": "#9dc0e3",  # the accent's family where nothing is selected: chips, a mention, a drop's overlay; selection keeps "selected"
    "parked": "#585a70", "parked_bg": "#eae8f2",
    "caution": "#9d5d00", "caution_bg": "#fff4ce", "caution_line": "#ead9a4",   # filled from the capture text, warnings
    "critical": "#c42b1c", "critical_bg": "#fde7e9",                           # overdue, over capacity, errors
    "success": "#0f7b0f", "success_bg": "#dff6dd",
    "scroll": "#c3cbd4", "scroll_hover": "#9aa4af",
    # Plant events: their bars, lane and band.
    "event": "#b07a12", "event_bg": "#f7e3b5", "event_ink": "#6e4700",
    # The Timeline's lanes: a small dot beside dark words, never the words' colour or a band of it (the review's decision V4).
    "lane1": "#2a78d6", "lane2": "#eb6834", "lane3": "#1baf7a", "lane4": "#eda100", "lane5": "#e87ba4", "lane6": "#008300", "lane7": "#6250d6", "lane8": "#e34948",
    # Hours a week on the Timeline's bars, light to dark, and the text on each.
    "hour1": "#86b6ef", "hour2": "#5598e7", "hour3": "#256abf", "hour4": "#184f95", "hour5": "#0d366b",
    "hour_ink1": "#0b1b2e", "hour_ink2": "#0b1b2e", "hour_ink3": "#ffffff", "hour_ink4": "#ffffff", "hour_ink5": "#ffffff",
    # The Timeline page (release 5.40): bars' one colour, the team chart's hours within capacity, and a week's load, a cell's
    # steps from under 40% to 125% or more, with the text on the last.
    "bar": "#64788c", "bar_soft": "#9fabb8",
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
    "nest_bar": "#9dc0e3", "unfold_bar": "#d6dce3", "moved_bar": "#7fb7a8",
    # Ticked checklist lines' words (decision 91) and the highlights, as pages and the editor show them (``markup``).
    "ticked": "#5a6571", "mark_yellow": "#fff1a8", "mark_green": "#cdeccd", "mark_pink": "#f8d0e3",
    # DocRepo's own icon, for the tray, the title bars and the taskbar (``app.make_icon``): the same in every theme.
    "brand": "#1d5e98", "brand_ink": "#ffffff",
}
#: The dark theme's values (decision 14): the same names. Not offered yet; release 5.194 settles how dark looks.
DARK = {
    "base": "#202020", "content": "#2b2b2b", "hover": "#333333", "pressed": "#3a3a3a", "selected": "#1f3447", "now": "#1b2a37",
    "text": "#ffffff", "text2": "#c5c5c5", "disabled": "#7a7a7a", "stroke": "#3a3a3a", "stroke_strong": "#454545",
    "control": "#9a9a9a", "accent": "#7cb0e2", "accent_hover": "#93bfe8", "accent_pressed": "#6aa2d8", "on_accent": "#0c1622",
    "info_bg": "#1b2a38", "info_line": "#3d5a75", "parked": "#b9b6d6", "parked_bg": "#2d2b3d",
    "event": "#dca64a", "event_bg": "#3a2e13", "event_ink": "#f0d49a",
    "lane1": "#6fa6e8", "lane2": "#f08a69", "lane3": "#56c2b0", "lane4": "#dca64a", "lane5": "#ee9fbd", "lane6": "#5cbf86", "lane7": "#ad8ee8", "lane8": "#f3968e",
    "hour1": "#1c3a5e", "hour2": "#25507f", "hour3": "#3a70ad", "hour4": "#6699d4", "hour5": "#9cc0ea",
    "hour_ink1": "#ffffff", "hour_ink2": "#ffffff", "hour_ink3": "#ffffff", "hour_ink4": "#0b1b2e", "hour_ink5": "#0b1b2e",
    "bar": "#8fa3b6", "bar_soft": "#5f6f7d",
    "load1": "#343434", "load2": "#454545", "load3": "#6b5220", "load4": "#8a3a32", "load5": "#e8776c", "load5_ink": "#1b1b1b",
    "item_task": "#1f3447", "item_note": "#1c3532", "item_update": "#3a2e13", "item_decision": "#2d2b3d", "item_date": "#26331c", "item_heading": "#333333",
    "ref_task": "#56c2b0", "ref_task_bg": "#1c3532",
    "caution": "#e8b85c", "caution_bg": "#3a2e13", "caution_line": "#5a4720", "critical": "#f3968e", "critical_bg": "#3e1f1c",
    "success": "#82d098", "success_bg": "#1b3323", "scroll": "#555555", "scroll_hover": "#777777",
    "g1": "#6fa6e8", "g2": "#56c2b0", "g3": "#dca64a", "g4": "#ad8ee8",
    "pri_critical": "#f3968e", "pri_high": "#e8b85c", "pri_medium": "#6fa6e8", "pri_parking": "#8a949e",
    "type_doc": "#7fa7e6", "type_sheet": "#5cbf86", "type_slides": "#f08a69", "type_pdf": "#f3968e", "type_picture": "#ad8ee8",
    "type_mail": "#7cb0e2", "type_drawing": "#56c2b0", "type_link": "#a0aab4", "type_other": "#a0aab4",
    "nest_bar": "#3d5a75", "unfold_bar": "#454545", "moved_bar": "#4f8f80",
    "ticked": "#a0aab4", "mark_yellow": "#5a4d12", "mark_green": "#1f4224", "mark_pink": "#4d2438",
    "brand": "#1d5e98", "brand_ink": "#ffffff",
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
