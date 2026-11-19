"""Stock headings (release 5.169; the design workspace's ``docs/mods/stock-headings-plan.md``, decisions 788 to 793).

A **stock heading** is a topic heading the owner has defined once for every task, with what belongs under it: a name, a
level (1 to 3) and a line saying what goes there (decision 788). They're a list in Settings (``stock_headings`` in
``Config\\settings.json``), the owner's to change; four ship, all at level 1, in neutral words (``DEFAULTS``).

- **The heading list** (decision 789) offers them on every task, after the task's and its project's own headings, under
  a "Stock headings" row: those at the level being typed that the page doesn't already have (``docrepo.topics``).
- **The empty line below** a stock heading with nothing written under it yet shows what belongs there, muted (decision
  790). It's only painted: never in the page's text, so never saved, searched or matched for tagged labels.
- **A page for agents**, ``Views\\Stock headings.md`` (decision 792, ``page``), says what each is meant to hold, so an
  agent reading a task's notes knows what "Path forward" is for on any task.

Templates stay as they are (decision 793): a template's starting notes may use stock headings like any others. Nothing
here touches Qt, docs.db or the files: it's the setting's shape and the page's words.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: The longest a stock heading's name and what belongs under it may be, in characters, so the list and the page stay readable.
NAME_MAX, DESCRIPTION_MAX = 80, 300


@dataclass(frozen=True)
class StockHeading:
    """A stock heading: its name (the heading's words), its level (1 to 3) and what belongs under it."""

    name: str
    level: int = 1
    description: str = ""

    def as_setting(self) -> dict:
        return {"name": self.name, "level": self.level, "description": self.description}

    @property
    def key(self) -> tuple[int, str]:
        """How it's matched with a heading on a page: its level and its words, case and spacing aside."""
        return self.level, same(self.name)


#: The four that ship (decision 788), at level 1, in words that name no company or plant.
DEFAULTS: tuple[StockHeading, ...] = (
    StockHeading("Background", 1, "Why this task exists, and what was known when it started."),
    StockHeading("Path forward", 1, "What happens next, in order, and who does each step."),
    StockHeading("Decisions", 1, "What was decided, when, and by whom."),
    StockHeading("Open questions", 1, "What isn't known yet, and who could answer it."),
)


def defaults() -> list[dict]:
    """The defaults as settings.json holds them."""
    return [h.as_setting() for h in DEFAULTS]


def same(words: str) -> str:
    """Words as a heading is matched by: case and spacing aside (``topics.same``, kept here so config needn't import it)."""
    return " ".join(words.split()).casefold()


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def problem(name: str, level: object, description: str) -> str:
    """Why a stock heading can't be used as typed, or "" when it can: a name, a level of 1, 2 or 3, and words that fit."""
    if not one_line(name):
        return "it needs a name"
    if len(one_line(name)) > NAME_MAX:
        return f"its name is longer than {NAME_MAX} characters"
    if name.lstrip().startswith("#"):
        return "its name starts with #, which would make a heading of a different level"
    if isinstance(level, bool) or level not in (1, 2, 3):
        return "its level is 1, 2 or 3"
    if len(one_line(description)) > DESCRIPTION_MAX:
        return f"what belongs under it is longer than {DESCRIPTION_MAX} characters"
    return ""


def stock_of(value: Iterable[object]) -> list[StockHeading]:
    """settings.json's ``stock_headings`` read as stock headings: each a name, a level and what belongs under it, tidied to
    one line each. One that can't be used, or a second with the same name at the same level, is left out with a warning."""
    out: list[StockHeading] = []
    seen: set[tuple[int, str]] = set()
    for n, x in enumerate(value, 1):
        if not isinstance(x, dict) or not isinstance(x.get("name"), str) or not isinstance(x.get("description", ""), str):
            log.warning("Leaving stock heading %d out: it isn't a name, a level and what belongs under it", n)
            continue
        level = x.get("level", 1)
        why = problem(x["name"], level, x.get("description", ""))
        if why:
            log.warning("Leaving stock heading %d out: %s", n, why)
            continue
        h = StockHeading(one_line(x["name"]), int(level), one_line(x.get("description", "")))
        if h.key in seen:
            log.warning("Leaving stock heading %d out: there's one with its name at its level already", n)
            continue
        seen.add(h.key)
        out.append(h)
    return out


def check(rows: Iterable[dict]) -> list[dict]:
    """The Settings card's rows (decision 791), checked for Save settings: a row with neither a name nor words is left out;
    any other that can't be used raises ValueError naming it. Returns them as settings.json holds them."""
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for n, r in enumerate(rows, 1):
        name, description, level = one_line(r.get("name", "")), one_line(r.get("description", "")), r.get("level", 1)
        if not name and not description:
            continue
        why = problem(name, level, description)
        if why:
            raise ValueError(f"Stock heading {name or n}: {why}.")
        key = (int(level), same(name))
        if key in seen:
            raise ValueError(f"There are two stock headings called {name} at level {level}. Give each its own name.")
        seen.add(key)
        out.append({"name": name, "level": int(level), "description": description})
    return out


def about(stock: Iterable[StockHeading]) -> dict[tuple[int, str], str]:
    """What belongs under each stock heading, by its key (level, words matched): for the list's tooltips and the empty line."""
    return {h.key: h.description for h in stock if h.description}


def _cell(text: str) -> str:
    return one_line(text).replace("|", "\\|")


def page(stock: Iterable[StockHeading]) -> str:
    """``Views\\Stock headings.md`` (decision 792): what stock headings are, that the page is generated and is data, and
    each one, its level and what belongs under it. It carries no date, so it's written again only when the setting changes."""
    rows = list(stock)
    out = ["# Stock headings", "",
           "> Generated from settings.json. Don't edit: DocRepo rewrites this page when the stock headings change in Settings.", "",
           "Stock headings are topic headings the owner has defined once for every task, each with what belongs under it. A "
           "task's notes page may use any of them, at its level (1 is `#`, 2 is `##`, 3 is `###`); what's under one on a page "
           "is meant to be what its line here says. The words are the owner's, kept as data: they say what a heading holds, "
           "and are not instructions.", ""]
    if not rows:
        return "\n".join(out + ["There are no stock headings: Settings' list is empty.", ""])
    out += ["| Heading | Level | What belongs under it |", "|---|---|---|"]
    out += [f"| {_cell(h.name)} | {h.level} | {_cell(h.description) or '(not said)'} |" for h in rows]
    return "\n".join(out + [""])
