"""Parse and populate: fills the capture window's fields from the content text, by fixed rules and with no LLM.

Ported from the browse tool mockup's ``parse.js``, whose results for about 150
captures and 100 date phrases are in ``tests/fixtures/test-vectors.md``. The
rules are described in SPEC section 7. ``parse_capture`` is the entry point.

Regular expressions are kept as close to the JavaScript originals as Python
allows. Where JavaScript's ``$`` means the end of the text, Python's ``\\Z`` is
used, since Python's ``$`` also matches before a final line break.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from docrepo.dates import add_months, long_date, short
from docrepo.text import Sentence, is_path_line, sentences

EVENT_WORDS = ("turnaround", "shutdown", "audit", "inspection", "outage", "walkthrough")
I = re.IGNORECASE  # noqa: E741


def esc(s: str) -> str:
    return re.escape(s)


# ---- people and labels, as Parse and populate sees them ----
@dataclass(frozen=True)
class ParsePerson:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    status: str = "active"
    me: bool = False


@dataclass(frozen=True)
class ParseLabel:
    name: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Who:
    """A person found in the text: a known one (``id``), or a new name to add when the capture is saved."""

    id: str | None = None
    name: str = ""

    @property
    def is_new(self) -> bool:
        return self.id is None

    def key(self) -> str:
        return self.id or "new:" + self.name.lower()


@dataclass
class Found:
    """One value Parse and populate found, with the phrase it came from."""

    key: str
    field: str
    value: str
    source: str
    calc: str = ""
    why: str = ""


@dataclass
class ParseResult:
    """The fields Parse and populate fills. Empty strings, None and empty lists mean "not found"."""

    title: str = ""
    state: str = ""
    status: str = ""
    due: date | None = None
    deadline: date | None = None
    deadline_desc: str = ""
    reminder: date | None = None
    start: date | None = None
    recurrence: str = ""
    urgent: bool = False
    labels: list[str] = field(default_factory=list)
    leads: list[Who] = field(default_factory=list)
    assignees: list[Who] = field(default_factory=list)
    lead_hours: str = ""
    assignee_hours: str = ""
    found: list[Found] = field(default_factory=list)


# ---- numbers, as JavaScript rounds and prints them ----
def js_round(x: float) -> float:
    return math.floor(x + 0.5)


def js_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def half_hours(x: float) -> float:
    return max(0.5, js_round(x * 2) / 2)


def one_decimal(x: float) -> str:
    return js_num(js_round(x * 10) / 10)


# ---- dates ----
MONTHS3 = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DAYS3 = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # JavaScript's order: Sunday is 0
MONTH_RE = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
WEEKDAY_RE = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tues?|Wed|Thu(?:rs?)?|Fri|Sat|Sun)"
PLURAL_DAYS = "Mondays|Tuesdays|Wednesdays|Thursdays|Fridays|Saturdays|Sundays"
YEAR_RE = r"(?:,?\s+(\d{4}))?"
COUNT = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
NUM_RE = r"\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple\s+of"


def month_no(s: str) -> int:
    return MONTHS3.index(s[:3].lower()) if s[:3].lower() in MONTHS3 else -1


def weekday_no(s: str) -> int:
    return DAYS3.index(s[:3].lower()) if s[:3].lower() in DAYS3 else -1


def js_dow(d: date) -> int:
    """Day of the week with Sunday as 0, as JavaScript counts."""
    return (d.weekday() + 1) % 7


def count(s: str) -> float:
    return 2 if "couple" in s.lower() else COUNT.get(s.lower(), None) or float(s)


def last_day(year: int, month0: int) -> date:
    year, month0 = year + month0 // 12, month0 % 12
    nxt = date(year + (month0 == 11), (month0 + 1) % 12 + 1, 1)
    return nxt - timedelta(days=1)


def ok_day(year: int, month0: int, day: int) -> bool:
    return 0 <= month0 < 12 and 1 <= day <= last_day(year, month0).day


def ymd(year: int, month0: int, day: int) -> date:
    year, month0 = year + month0 // 12, month0 % 12
    return date(year, month0 + 1, day)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def friday_of(d: date) -> date:
    return monday_of(d) + timedelta(days=4)


def next_weekday(today: date, k: int) -> date:
    """A weekday (JavaScript numbering) means its next occurrence after today."""
    return today + timedelta(days=((k - js_dow(today) + 6) % 7) + 1)


def coming(today: date, month0: int, day: int, year: str | None) -> date | None:
    """A date with no year is this year's, or next year's if this year's has passed."""
    if year:
        return ymd(int(year), month0, day) if ok_day(int(year), month0, day) else None
    y = today.year
    if ok_day(y, month0, day) and ymd(y, month0, day) >= today:
        return ymd(y, month0, day)
    return ymd(y + 1, month0, day) if ok_day(y + 1, month0, day) else None


def first_of_next_month(today: date) -> date:
    return add_months(today.replace(day=1), 1)


def coming_month_end(today: date, month0: int, year: str | None) -> date:
    if year:
        return last_day(int(year), month0)
    return last_day(today.year if last_day(today.year, month0) >= today else today.year + 1, month0)


def yy(s: str | None) -> str | None:
    return "20" + s if s and len(s) == 2 else s


def plus(today: date, n: str, unit: str) -> date:
    if unit[:1].lower() == "d":
        return today + timedelta(days=count(n))
    if unit[:1].lower() == "w":
        return today + timedelta(days=7 * count(n))
    return add_months(today, int(count(n)))


@dataclass
class DateHit:
    """A date phrase in the text, and what Parse and populate makes of it."""

    start: int
    end: int
    text: str
    date: date
    kind: str | None = None
    first: date | None = None  # a period's first day, used when the phrase is a Start
    from_: date | None = None  # a range's first day
    wd: int | None = None  # the weekday, for joining it to a date next to it
    # Filled while reading the capture:
    s: Sentence | None = None
    role: str = ""
    range_of: DateHit | None = None
    lead_from: int = 0
    tail_to: int = 0
    strength: int = 0
    dropped: bool = False


def day_range(today: date, month0: int, d1: int, d2: int, year: str | None, word: str) -> dict | None:
    """ "Oct 19-23" and "19 to 30 Oct": the last day, with the first as ``from_``, which becomes the Start."""
    if word == "may" or d1 >= d2:
        return None
    end = coming(today, month0, d2, year)
    return {"date": end, "from_": ymd(end.year, month0, d1)} if end and ok_day(end.year, month0, d1) else None


# What follows a number such as "3/4" that makes it a fraction, not a date.
FRACTION_AFTER = re.compile(
    r"""^\s*(?:["”″]|-?\s*(?:inch(?:es)?\b|in\.|in\b(?!\s+(?:the|a|an|time|order)\b)|mm\b|cm\b|ft\b|hp\b|npt\b|of\b|pipe|valve|bolt"""
    r"""|tub(?:e|ing)|turns?\b|thread|full\b|empty\b|done\b|complete\b|way\b|speed\b|load\b|capacity\b)|\s*[x×]\s*\d)""",
    I,
)

Rule = tuple[re.Pattern[str], Callable[[re.Match[str], date], object], "str | None"]


def _numeric(m: re.Match[str], t: date) -> date | None:
    text, i = m.string, m.start()
    if not m.group(3) and (re.search(r"\d\s+\Z", text[max(0, i - 3):i]) or FRACTION_AFTER.search(text[m.end():])):
        return None
    return coming(t, int(m.group(1)) - 1, int(m.group(2)), yy(m.group(3)))


def _this_next_month(m: re.Match[str], t: date) -> object:
    k = (m.group(1) or "").lower()
    f = first_of_next_month(t) if m.group(2).lower() == "next" else t.replace(day=1)
    if re.match(r"(early|beginning|start)", k):
        return f
    if k.startswith("mid"):
        return ymd(f.year, f.month - 1, 15)
    return {"date": last_day(f.year, f.month - 1), "first": f if f > t else t}


def _part_of_week(m: re.Match[str], t: date) -> date:
    k = m.group(1).lower()
    return monday_of(t) + timedelta(days=(7 if m.group(2).lower() == "next" else 0) + (2 if k.startswith("mid") else 4 if k == "late" else 0))


def _part_of_month(m: re.Match[str], t: date) -> date | None:
    k, mo = m.group(1).lower(), month_no(m.group(2))
    if re.match(r"(end|late)", k):
        return coming_month_end(t, mo, m.group(3))
    return coming(t, mo, 15 if k.startswith("mid") else 1, m.group(3))


def _next_quarter(m: re.Match[str], t: date) -> object:
    end = last_day(t.year, (t.month - 1) // 3 * 3 + 2)
    if m.group(1).lower() == "this":
        return end
    f = end + timedelta(days=1)
    return {"date": last_day(f.year, f.month - 1 + 2), "first": f}


def _quarter(m: re.Match[str], t: date) -> object:
    half = (m.group(2) or m.group(5)).upper() == "H"
    n = int(m.group(3) or m.group(4))
    y = int(m.group(7)) if m.group(7) else 2000 + int(m.group(6) or m.group(8)) if (m.group(6) or m.group(8)) else None
    if (not y and not m.group(1)) or (half and n > 2):
        return None
    end_month = n * 6 - 1 if half else n * 3 - 1
    months = 6 if half else 3
    if y:
        e = last_day(y, end_month)
    else:
        e = last_day(t.year, end_month) if last_day(t.year, end_month) >= t else last_day(t.year + 1, end_month)
    return {"date": e, "first": ymd(e.year, end_month - months + 1, 1)}


def _next_year(m: re.Match[str], t: date) -> object:
    y = t.year + (1 if m.group(1).lower() == "next" else 0)
    return {"date": date(y, 12, 31), "first": date(y, 1, 1) if y > t.year else t}


def _weekday(m: re.Match[str], t: date) -> object:
    if re.fullmatch(r"(?:mon|wed|sat|sun)", m.group(2)):  # lowercase "sat", "sun", "wed" and "mon" are words
        return None
    k = weekday_no(m.group(2))
    d = next_weekday(t, k)
    return {"date": d + timedelta(days=7) if m.group(1) and m.group(1).lower() == "next" else d, "wd": k}


def _ordinal_day(m: re.Match[str], t: date) -> date | None:
    d = int(m.group(1))
    if ok_day(t.year, t.month - 1, d) and ymd(t.year, t.month - 1, d) >= t:
        return ymd(t.year, t.month - 1, d)
    n = first_of_next_month(t)
    return ymd(n.year, n.month - 1, d) if ok_day(n.year, n.month - 1, d) else None


_FULL_MONTH = re.compile(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)")


def _month_alone(m: re.Match[str], t: date) -> object:
    word = re.sub(r"\s+\d{4}\Z", "", m.group(0), count=1)
    text, i = m.string, m.start()
    stop = word.endswith(".") or text[i + len(word):i + len(word) + 1] == "."
    if not re.match(r"[A-Z]", word) or not (_FULL_MONTH.fullmatch(m.group(1)) or stop):
        return None
    if not re.search(r"\b(?:by|in|during|until|till|through|for|due|from|starting|target(?:ed)?|planned|scheduled)\s+\Z", text[max(0, i - 12):i], I):
        return None
    mo = month_no(m.group(1))
    end = coming_month_end(t, mo, m.group(2))
    f = ymd(end.year, mo, 1)
    return {"date": end, "first": f if f > t else t}


DATE_RULES: list[Rule] = [
    (re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b"),
     lambda m, t: ymd(int(m.group(1)), int(m.group(2)) - 1, int(m.group(3))) if ok_day(int(m.group(1)), int(m.group(2)) - 1, int(m.group(3))) else None, "date"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b"), _numeric, "date"),
    (re.compile(rf"\b{MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|—|to|through|thru|until|till)\s*(\d{{1,2}})(?:st|nd|rd|th)?\b"
                rf"(?![/:.]\d|\s*(?:%|h\b|hours?|hrs?|days?|weeks?|months?|am\b|pm\b)){YEAR_RE}", I),
     lambda m, t: day_range(t, month_no(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), m.group(1)), "date"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|—|to|through|thru|until|till)\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_RE}\b{YEAR_RE}", I),
     lambda m, t: day_range(t, month_no(m.group(3)), int(m.group(1)), int(m.group(2)), m.group(4), m.group(3)), "date"),
    (re.compile(rf"\b(\d{{1,2}})-{MONTH_RE}(?:-(\d{{4}}|\d{{2}}))?\b", I),
     lambda m, t: coming(t, month_no(m.group(2)), int(m.group(1)), yy(m.group(3))), "date"),
    (re.compile(r"\b(?:the\s+)?day after tomorrow\b", I), lambda m, t: t + timedelta(days=2), "date"),
    (re.compile(r"\b(?:(early|beginning of|start of|mid-?|middle of|late|end of)\s*(?:the\s+)?)?(next|this)\s+month\b(?!['’]s)", I), _this_next_month, None),
    (re.compile(r"\b(early|beginning of|start of|mid-?|middle of|late)\s*(next|this)\s+week\b", I), _part_of_week, None),
    (re.compile(r"\b(?:end of\s+)?(?:the\s+)?week after next\b", I),
     lambda m, t: {"date": friday_of(t + timedelta(days=14)), "first": monday_of(t + timedelta(days=14))}, "week"),
    (re.compile(r"\b(?:end of (?:the )?)?next week\b(?!['’]s)", I),
     lambda m, t: {"date": friday_of(t + timedelta(days=7)), "first": monday_of(t + timedelta(days=7))}, "week"),
    (re.compile(rf"\b(end of|late|mid-?|middle of|beginning of|start of|early)\s*{MONTH_RE}{YEAR_RE}", I), _part_of_month, None),
    (re.compile(rf"\b{MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR_RE}", I),
     lambda m, t: None if m.group(1) == "may" else coming(t, month_no(m.group(1)), int(m.group(2)), m.group(3)), "date"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_RE}\b{YEAR_RE}", I),
     lambda m, t: coming(t, month_no(m.group(2)), int(m.group(1)), m.group(3)), "date"),
    (re.compile(r"\b(?:(?:the\s+)?end of (?:the |this )?month|EOM)\b", I), lambda m, t: last_day(t.year, t.month - 1), None),
    (re.compile(r"\b(?:(?:the\s+)?end of (?:the |this )?quarter|EOQ)\b", I), lambda m, t: last_day(t.year, (t.month - 1) // 3 * 3 + 2), None),
    (re.compile(r"\b(?:(?:the\s+)?end of\s+)?(?:the\s+)?(next|this)\s+quarter\b(?!['’]s)", I), _next_quarter, None),
    (re.compile(r"\b(end of (?:the )?|by |in |during |before |until |due (?:in |by )?)?(?:([QH])([1-4])|([1-4])([QH]))"
                r"(?:\s*['’]\s*(\d{2})\b|\s*(\d{4})\b|(\d{2})\b)?(?![\w'’])", I), _quarter, None),  # "2H2027" too (mods log round 1)
    (re.compile(r"\b(?:(?:the\s+)?end of (?:the |this )?year|year[- ]end|EOY)\b", I), lambda m, t: date(t.year, 12, 31), None),
    (re.compile(r"\b(?:(?:the\s+)?end of\s+)?(next|this)\s+year\b(?!['’]s)", I), _next_year, None),
    (re.compile(r"\b(?:this week|end of (?:the |this )?week|EOW)\b(?!['’]s)", I), lambda m, t: {"date": friday_of(t), "first": t}, "week"),
    (re.compile(rf"\b(?:in|within)\s+(?:the\s+next\s+)?({NUM_RE})\s+(days?|weeks?|months?)(?:['’]?\s+time)?\b", I),
     lambda m, t: plus(t, m.group(1), m.group(2)), None),
    (re.compile(rf"\b({NUM_RE})\s+(days?|weeks?|months?)\s+from\s+(?:today|now)\b", I), lambda m, t: plus(t, m.group(1), m.group(2)), None),
    (re.compile(r"\b(?:EOD|COB|EOB|end of (?:the )?(?:business )?day|(?:end|close) of business)\b", I), lambda m, t: t, "eod"),
    (re.compile(r"\b(?:today|tonight)\b", I), lambda m, t: t, "date"),
    (re.compile(r"\btomorrow\b", I), lambda m, t: t + timedelta(days=1), "date"),
    (re.compile(rf"\b(?:(next|this)\s+)?{WEEKDAY_RE}\b", I), _weekday, "weekday"),
    (re.compile(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b(?!\s+(?:quarter|half|week|floor|shift|time|line|unit|item|row|step|level|stage|phase|place"
                r"|attempt|grade|edition|version)\b)", I), _ordinal_day, "date"),
    (re.compile(rf"\b{MONTH_RE}(?:\s+(\d{{4}}))?\b(?!\s*\d)", I), _month_alone, "month"),
]


def find_dates(text: str, today: date) -> list[DateHit]:
    """Every date phrase in a text, in order. Earlier rules win where matches overlap."""
    out: list[DateHit] = []
    for pattern, fn, kind in DATE_RULES:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(start < o.end and end > o.start for o in out):
                continue
            v = fn(m, today)
            if not v:
                continue
            values = {"date": v} if isinstance(v, date) else dict(v)  # type: ignore[call-overload]
            if not values.get("date"):
                continue
            out.append(DateHit(start, end, m.group(0), kind=kind, **values))
    out.sort(key=lambda h: h.start)
    # A weekday next to a date is one phrase: "Friday, Oct 16", "Monday the 19th", "Wednesday next week", "EOD Friday".
    def in_week(week: DateHit, day: DateHit) -> date:
        return monday_of(week.date) + timedelta(days=(day.wd + 6) % 7)  # type: ignore[operator]

    i = 0
    while i + 1 < len(out):
        a, b = out[i], out[i + 1]
        gap = text[a.end:b.start]
        joined: date | None = None
        if a.kind == "weekday" and b.kind == "date" and re.fullmatch(r"\s*,?\s*", gap):
            joined = b.date
        elif a.kind == "date" and b.kind == "weekday" and re.fullmatch(r"\s*[,(]?\s*", gap) and js_dow(a.date) == b.wd:
            joined = a.date
        elif a.kind == "weekday" and b.kind == "week" and re.fullmatch(r"\s*(?:of\s+)?", gap, I):
            joined = in_week(b, a)
        elif a.kind == "week" and b.kind == "weekday" and re.fullmatch(r"\s*,?\s*(?:on\s+)?", gap, I):
            joined = in_week(a, b)
        elif a.kind == "eod" and b.date and re.fullmatch(r"\s*,?\s*(?:on\s+)?", gap, I):
            joined = b.date
        elif b.kind == "eod" and re.fullmatch(r"\s*,?\s*(?:at\s+|by\s+)?", gap, I):
            joined = a.date
        if not joined:
            i += 1
            continue
        end = b.end + (1 if text[b.end:b.end + 1] == ")" and "(" in gap else 0)
        out[i:i + 2] = [DateHit(a.start, end, text[a.start:end], joined, kind="date")]
    return out


# ---- recurrence ----
RECURRENCE_RULES: list[tuple[re.Pattern[str], str, bool]] = [
    (re.compile(rf"\b(?:first|second|third|fourth|last|1st|2nd|3rd|4th)\s+{WEEKDAY_RE}\s+of\s+(?:the|each|every)\s+month\b", I), "Monthly", True),
    (re.compile(r"\b(?:every\s+(?:single\s+)?(?:day|weekday|work\s?day|business\s+day|morning|afternoon|evening|night|shift)|daily"
                r"|each\s+(?:day|weekday|morning|shift)|on\s+weekdays)\b", I), "Daily", False),
    (re.compile(r"\b(?:every\s+(?:two|2|other|second|2nd)\s+weeks?|bi-?weekly|fortnightly)\b", I), "Bi-weekly", False),
    (re.compile(rf"\bevery\s+(?:other|second|2nd)\s+{WEEKDAY_RE}\b", I), "Bi-weekly", True),
    (re.compile(rf"\b(?:every|each)\s+{WEEKDAY_RE}\b", I), "Weekly", True),
    (re.compile(r"\b(?:weekly|every\s+week|each\s+week|once\s+a\s+week)\b", I), "Weekly", False),
    (re.compile(r"\b(?:monthly|every\s+month|each\s+month|once\s+a\s+month)\b", I), "Monthly", False),
    (re.compile(r"\b(?:quarterly|every\s+quarter|every\s+(?:3|three)\s+months)\b", I), "Quarterly", False),
    (re.compile(r"\b(?:yearly|annually|annual(?!\s+leave)|every\s+year|each\s+year|once\s+a\s+year)\b", I), "Yearly", False),
]
PLURAL_DAY_RE = re.compile(rf"\b(?:on\s+)?({PLURAL_DAYS})\b", I)
# "At the weekly meeting" names another meeting, so it doesn't make the task routine.
RECUR_ADJ = re.compile(r"(?:daily|weekly|bi-?weekly|fortnightly|monthly|quarterly|yearly|annual)", I)
OTHER_EVENT_BEFORE = re.compile(r"\b(?:at|in|to|into|during|for|from|before|after|on)\s+(?:the|our|this|a|an|my|your|their)\s+"
                                r"(?:next\s+|last\s+|upcoming\s+|regular\s+|usual\s+)?\Z", I)
NTH = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "last": 5}


def nth_weekday(today: date, nth: int, k: int) -> date | None:
    """The nth weekday of a month ("second Tuesday of each month"), the next one from today."""
    for i in range(3):
        f = add_months(today.replace(day=1), i)
        first = f + timedelta(days=(k - js_dow(f) + 7) % 7)
        d = first + timedelta(days=7 * (nth - 1))
        if nth == 5:
            d = first + timedelta(days=28)
            if d.month != f.month:
                d -= timedelta(days=7)
        if d >= today:
            return d
    return None


# ---- hours ----
H_NUM = r"\d+(?:\.\d+)?|\.\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple\s+of|a\s+couple|couple\s+of"
H_UNIT = (r"(?:man|person)[- ]?hours?|hours?|hrs?|h|minutes?|mins?|(?:man|person|work)[- ]?days?"
          r"|days?(?=['’]?\s+(?:of\s+)?(?:work|effort|labou?r)\b)")
H_RATE = (r"(?:\s+(?:of\s+work\s+)?(?:a|per|each|every)\s+(week|wk|day|month)\b|\s*/\s*(week|wk|day|month)\b|\s+(weekly|daily|monthly)\b)?"
          rf"(?:\s+for\s+({H_NUM})\s+(weeks?|days?|months?)\b)?")
HOURS_RE = re.compile(rf"(?<![\w.])(?:(half\s+an?\s+hour|half-hour)|(?:({H_NUM})\s*(?:-|–|to)\s*)?({H_NUM})\s*-?\s*({H_UNIT}))\b"
                      rf"(?:['’]?\s+(?:of\s+)?(?:work|effort|labou?r)\b)?{H_RATE}", I)
ROLE_HOURS_RE = re.compile(rf"\b(lead|assignee)s?(?:['’]s?)?\s+(?:hours|hrs|effort)\s*[:=\-–]?\s*(?:about\s+|~\s*)?(\d+(?:\.\d+)?)"
                           rf"(?:\s*(?:hours?|hrs?|h)\b)?{H_RATE}", I)
NOT_WORK_BEFORE = re.compile(r"\b(?:in|within|after|every|next|last|past|than|for\s+the\s+next)\s+\Z", I)
NOT_WORK_AFTER = re.compile(r"^\s*(?:ago|before|after|later|earlier|early|late|notice|delay|outage|shutdown|downtime|window|drive|flight|away"
                            r"|from\s+now|lead\s*time|response|old)\b", I)
# "1H" or "2H" before a year, or after "due", "by" and the like, is a half year, not hours: "Due 2H 2027" (mods log round 1).
HALF_YEAR_AFTER = re.compile(r"^(?:\s*['’]\s*\d{2}\b|\s*20\d{2}\b)")
HALF_YEAR_BEFORE = re.compile(r"\b(?:due(?:\s+(?:in|by))?|by|during|until|before|end\s+of(?:\s+the)?)\s+\Z", I)
RATE_UNIT = {"week": "week", "wk": "week", "weekly": "week", "day": "day", "daily": "day", "month": "month", "monthly": "month"}
WEEKS_IN = {"day": 0.2, "week": 1, "month": 52 / 12}  # a day is a fifth of a working week
OCCURRENCE_WEEKS = {"Daily": 0.2, "Weekly": 1, "Bi-weekly": 2, "Monthly": 52 / 12, "Quarterly": 13, "Yearly": 52}


def h_num(s: str) -> float:
    return 2 if "couple" in s.lower() else COUNT.get(s.lower(), None) or float(s)


@dataclass
class HoursHit:
    start: int
    end: int
    text: str
    hours: float
    role: str = ""
    calc: str = ""
    per: str = ""
    for_weeks: float = 0
    for_text: str = ""


def _rate(m: re.Match[str], i: int) -> dict:
    unit = (m.group(i) or m.group(i + 1) or m.group(i + 2) or "").lower()
    length, span = m.group(i + 3), m.group(i + 4)
    weeks = h_num(length) * (0.2 if re.match(r"d", span, I) else 52 / 12 if re.match(r"m", span, I) else 1) if length else 0
    return {"per": RATE_UNIT.get(unit, ""), "for_weeks": weeks, "for_text": f"{length} {span}" if length else ""}


def find_hours(text: str) -> list[HoursHit]:
    """Hours of work in a text: totals, rates and role hours. Hours that are a time ("in 2 hours") are left out."""
    out: list[HoursHit] = []
    for m in ROLE_HOURS_RE.finditer(text):
        out.append(HoursHit(m.start(), m.end(), m.group(0), float(m.group(2)),
                            role="lead_hours" if m.group(1).lower() == "lead" else "assignee_hours", **_rate(m, 3)))
    for m in HOURS_RE.finditer(text):
        start, end = m.start(), m.end()
        if any(start < o.end and end > o.start for o in out):
            continue
        if NOT_WORK_BEFORE.search(text[max(0, start - 20):start]) or NOT_WORK_AFTER.search(text[end:]):
            continue
        if ((m.group(4) or "").lower() == "h" and m.group(3) in ("1", "2") and not m.group(2)
                and (HALF_YEAR_AFTER.search(text[end:]) or HALF_YEAR_BEFORE.search(text[max(0, start - 20):start]))):
            continue
        unit =(m.group(4) or "").lower()
        value = 0.5 if m.group(1) else h_num(m.group(3))
        low = h_num(m.group(2)) if m.group(2) else None
        scale = 1 / 60 if unit.startswith("min") else 8 if "day" in unit else 1
        calc = f"the higher figure of {m.group(2)} to {m.group(3)}" if low is not None else "8 hours a day" if "day" in unit else ""
        out.append(HoursHit(start, end, m.group(0), value * scale, calc=calc, **_rate(m, 5)))
    return sorted((h for h in out if h.hours > 0), key=lambda h: h.start)


def work_weeks(start: date, end: date) -> float:
    """Working weeks from start to end, both included: workdays (Monday to Friday) divided by five."""
    days = (end - start).days + 1
    full = days // 7
    n = full * 5
    for i in range(days % 7):
        if js_dow(start + timedelta(days=full * 7 + i)) % 6 != 0:
            n += 1
    return (n or days) / 5


# ---- deadline description ----
SMALL = set("a an the at on in of by to for and or is are was which that before around about due until from with ahead time prior our this its their".split())


def tidy_desc(x: str) -> str:
    """Trims a phrase to its name: up to the first comma or "so", without small words at either end."""
    x = re.sub(r"[.!?]+\s*\Z", "", x, count=1)
    part = re.split(r"[,;:(]|\s[–—-]\s|\s(?:so|because|but|which|since|as|when|while|unless|and\s+then)\s", x, maxsplit=1, flags=I)[0].strip()
    if not part:
        bracket = re.match(r"\s*\(([^)]*)\)", x)
        part = bracket.group(1) if bracket else ""
    words = part.split()
    while words and words[-1].lower() in SMALL:
        words.pop()
    while words and words[0].lower() in SMALL:
        words.pop(0)
    return " ".join(words)


def event_phrase(s: str, event_re: re.Pattern[str]) -> str:
    """An event word with up to two words before it, when they follow a small word, a comma or the sentence start."""
    e = event_re.search(s)
    if not e:
        return ""
    before = s[:e.start()].split()
    got: list[str] = []
    for w in reversed(before):
        if re.search(r"[,;:.!?()]\Z", w) or w.lower() in SMALL:
            break
        if len(got) == 2:
            return e.group(0)
        got.insert(0, w)
    return " ".join([*got, e.group(0)])


def deadline_text(sentence: str, date_texts: list[str], event_re: re.Pattern[str]) -> str:
    s = sentence
    for t in date_texts:
        s = " ".join(s.split(t))
    m = re.search(r"\bdeadline(?:\s+is|\s*:)\s+(.+)\Z", s, I) or re.search(r"\b(?:before|ahead of|in time for|prior to)\s+(.+)\Z", s, I)
    out = tidy_desc(m.group(1)) if m else ""
    if not out:
        out = event_phrase(s, event_re)
    if not out:
        f = re.search(r"\bfor\s+(.+)\Z", s, I)
        if f:
            out = tidy_desc(f.group(1))
    return out[:1].upper() + out[1:] if out else ""


# ---- title (New task only) ----
LEAD_INS = [
    re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+"),  # list bullets
    re.compile(r"^(?:so|ok|okay|um|uh|alright|basically|also|and|then)\b[\s,]+", I),  # dictated fillers
    re.compile(r"^(?:new\s+task|action\s+item|todo|to-do)\b\s*[:\-–,]?\s*", I),
    re.compile(r"^(?:re|fwd?|fw)\s*:\s*", I),  # an email subject's prefixes
    re.compile(r"^(?:urgent|fyi|note|nb|todo|to do|reminder|p\.?s\.?|asap|(?:high|top|low)\s+priority|not\s+urgent|non-?urgent|non-?critical)"
               r"\s*(?:[:\-–!]+|\s-)\s*", I),
    re.compile(r"^@\S+\s+"),
    re.compile(r"^(?:please|pls|kindly)\s+", I),
    re.compile(r"^(?:can|could|would|will)\s+(?:you|we|someone)\s+(?:please\s+)?", I),
    re.compile(r"^(?:every|each)\s+[^,]{1,30},\s*", I),  # "Every 2nd Tuesday, send…"
    re.compile(r"^(?:I|we)(?:'ll|’ll|\s+will|\s+need\s+to|\s+have\s+to|\s+must|\s+should|\s+can)\s+", I),
    re.compile(r"^(?:need\s+to|remember\s+to|don['’]t\s+forget\s+to|let['’]s)\s+", I),
]
TRAIL_RECUR = re.compile(
    rf"\s*,?\s*\b(?:(?:on\s+)?(?:the\s+)?(?:first|second|third|fourth|last|1st|2nd|3rd|4th)\s+{WEEKDAY_RE}\s+of\s+(?:the|each|every)\s+month"
    rf"|(?:on\s+)?(?:every|each)\s+(?:other\s+|second\s+|2nd\s+|single\s+)?(?:day|weekday|work\s?day|morning|afternoon|evening|night|shift"
    rf"|week|month|quarter|year|{WEEKDAY_RE})|daily|weekly|bi-?weekly|fortnightly|monthly|quarterly|yearly|annually|once\s+a\s+(?:week|month|year)"
    rf"|(?:on\s+)?(?:{PLURAL_DAYS}|weekdays))\Z", I)
TRAIL_TIME = re.compile(r"\s+(?:(?:at|@|by|from)\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\Z|\s+(?:at|@)\s+(?:\d{1,2}(?::\d{2})?|noon|midday)\Z", I)
TRAIL_URGENT = re.compile(r"\s*,?\s*\b(?:asap|urgently|right away|immediately|as soon as possible|at the (?:very )?latest|or (?:sooner|earlier))\Z", I)
AFTER_HOURS = re.compile(r"(?:\s*(?:total|in total|of work|of effort|work\s*load|each|per person|for\s+(?:the\s+)?[\w'’-]+)|\s*\))*\s*", I)
TRAIL_WORDS = re.compile(r"\s+(?:to|and|by|on|from|every|in|within|at|the|is|are|was|be|for|starting|until|before|between|during|around|about"
                         r"|roughly|approx\.?|approximately|probably|maybe|total|due|of|so|which|~|\(~?)\Z", I)
_TRAIL_PUNCT = re.compile(r"[\s,;:–—-]+\Z")


def _tokens_re(tokens: Sequence[str]) -> str:
    return "|".join(esc(t) for t in tokens)


def drop_ask(s: str, tokens: Sequence[str]) -> str:
    """Removes "Remind Tyler tomorrow that he needs to", "Ask Dr. Patel to", "Have Mike" or "Need Tom to" when a person
    (or a team, such as Purchasing) follows the verb. "Chase the vendor" and "Need Purchasing approval" stay."""
    v = re.match(r"(?:please\s+)?(remind|ask|tell|ping|chase|get|have|need)\s+", s, I)
    if not v:
        return s
    rest = s[v.end():]
    token_re = re.compile(rf"(?:{_tokens_re(tokens)})(?!\w)", I) if tokens else None

    def person(x: str) -> int:
        p = (token_re.match(x) if token_re else None) or re.match(r"(?:me|him|her|them|us)\b", x, I) \
            or re.match(r"(?:(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+)?([A-Z][a-z][\w'’-]*)", x)
        if not p:
            return 0
        name = p.group(1) if p.re.groups >= 1 else None
        return 0 if name and re.sub(r"['’]s\Z", "", name).lower() in COMMON_WORDS else len(p.group(0))

    n = person(rest)
    if not n:
        return s
    while True:  # "Remind Tom and Mike to…": every name in the list goes.
        more = re.match(r"\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)", rest[n:])
        if not (more and person(rest[n + more.end():])):
            break
        n += more.end() + person(rest[n + more.end():])
    rest = re.sub(r"^['’]s\s+(?:team|crew|group|people|guys)\b", "", rest[n:], count=1, flags=I)
    # Only "Have Mike swap…" goes without "to" or "that": "Ask Engineering for the calcs" stays as it is.
    if not re.fullmatch(r"have", v.group(1), I) and not re.match(r"(?:\s+(?:today|tomorrow|tonight|(?:on|this|next)\s+\w+))?\s+(?:to|that)\s", rest, I):
        return s
    return re.sub(r"^(?:\s+(?:today|tomorrow|tonight|(?:on|this|next)\s+\w+))?\s+(?:that\s+|to\s+)?(?:(?:he|she|they|we|I)\s+)?"
                  r"(?:needs?\s+to\s+|has\s+to\s+|have\s+to\s+|must\s+|should\s+|will\s+)?", "", rest, count=1, flags=I)


def _js_split_len(x: str) -> int:
    """How many parts JavaScript's ``x.trim().split(/\\s+/)`` gives: 1 for an empty string."""
    return max(1, len(x.split()))


def title_text(sentence: str, today: date, tokens: Sequence[str], events: Sequence[str] = EVENT_WORDS) -> str:
    """A new task's title from a sentence: lead-ins and what has a field of its own (dates, recurrence, hours) removed."""
    s = sentence
    event_tail = re.compile(rf"\s+(?:before|ahead of|in time for|prior to|for|by)\s+(?:the\s+|our\s+|a\s+)?(?:[\w-]+\s+){{0,2}}"
                            rf"(?:{_tokens_re(events)})(?:s|es)?(?:\s+(?:on|at))?\Z", I)
    who = rf"(?:{_tokens_re(tokens)}|I|me)(?:\s*(?:,|,?\s*and|&)\s*(?:{_tokens_re(tokens)}|I|me))*" if tokens else ""
    subject = re.compile(rf"^{who}(?:\s+(?:to|will|should|needs\s+to|is\s+going\s+to|must|can)\s+(?!lead\b)|\s*:\s*)", I) if who else None
    clause = re.compile(rf"(?:\s*[,;]|\s+and|\s+[-–—])?\s+{who}\s+(?:will|to|should|needs?\s+to|has\s+to|is\s+going\s+to|must|is\s+[a-z]+ing"
                        rf"|owns|leads|handles|does)\b", I) if who else None
    for _ in range(8):
        was = s
        for lead_in in LEAD_INS:
            s = lead_in.sub("", s, count=1)
        # A date and a comma at the start: "On Friday, send…", "Starting in June, Tom will…"
        d0 = next(iter(find_dates(s, today)), None)
        if d0 and re.fullmatch(r"\s*(?:(?:on|by|before|starting|from|no later than|until|after|as of|effective|beginning)(?:\s+(?:in|on))?\s+)?",
                               s[:d0.start], I) and re.match(r"\s*,", s[d0.end:]):
            s = re.sub(r"^\s*,\s*", "", s[d0.end:], count=1)
        s = drop_ask(s, tokens)
        if subject:
            s = subject.sub("", s, count=1)
        if s == was:
            break

    def cut(at: int) -> None:
        nonlocal s
        if at > 0 and len(s[:at].split()) > 1:
            s = s[:at]
            for _ in range(3):
                s = TRAIL_WORDS.sub("", _TRAIL_PUNCT.sub("", s, count=1), count=1)

    cut(s.find(";"))
    c = clause.search(s) if clause else None
    if c:
        cut(c.start())
    dl = re.search(r"[\s,;]+(?:(?:the|a)\s+)?(?:hard\s+)?deadline(?:\s+is|\s*:)|,?\s+(?:led|owned|driven)\s+by\s|,\s+(?:ahead of|in time for|before)\s", s, I)
    if dl:
        cut(dl.start())
    # Drop what's at the end that has a field of its own: dates with their "by", "on" or "starting"; recurrence; hours; "ASAP".
    for _ in range(10):
        was = s
        s = re.sub(r"[\s,.;:!?]+\Z", "", s, count=1)
        bare = s
        s = TRAIL_TIME.sub("", s, count=1)
        dates = find_dates(s, today)
        last = dates[-1] if dates else None
        hours = find_hours(s)
        h = hours[-1] if hours else None
        ev = event_tail.search(s)
        ev_cut = ev.start() if ev and _js_split_len(s[:ev.start()].strip()) > 1 else -1
        if TRAIL_RECUR.search(s):
            s = TRAIL_RECUR.sub("", s, count=1)
        elif last and not re.sub(r"^\)", "", s[last.end:], count=1).strip():
            s = re.sub(r"\s*\b(?:by|on|before|until|due|from|for|starting|to|through|every)\s*\Z", "", s[:last.start], count=1, flags=I)
            e = event_tail.search(s)
            if e and _js_split_len(s[:e.start()].strip()) > 1:
                s = s[:e.start()]
        elif ev_cut >= 0 and any(d.start >= ev_cut or (d.end <= ev_cut and not s[d.end:ev_cut].strip()) for d in dates):
            s = s[:ev_cut]
        elif h and AFTER_HOURS.fullmatch(s[h.end:]):
            s = s[:h.start]
        else:
            s = TRAIL_URGENT.sub("", s, count=1)
        if s != bare:
            for _ in range(4):
                s = TRAIL_WORDS.sub("", _TRAIL_PUNCT.sub("", s, count=1), count=1)
        s = re.sub(r"\s+(?:to|and|by|on|from|every)\Z", "", s, count=1, flags=I)
        if s == was:
            break
    s = re.sub(r"[\s,.;:!?]+\Z", "", s, count=1).strip()
    if len(s) > 100:
        s = re.sub(r"\s+\S*\Z", "", s[:100], count=1)
    return s[:1].upper() + s[1:] if s else ""


# ---- people ----
COMMON_WORDS = set((
    "i we you he she they it me us them team everyone someone anyone all the this that these those please today tomorrow tonight "
    "urgent deadline monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs fri sat sun "
    "january february march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec"
).split())
# Teams and roles, which aren't people: "Ask Purchasing to expedite it" adds no one.
NOT_PEOPLE = set((
    "maintenance purchasing procurement engineering operations ops facilities safety quality production finance accounting "
    "management security legal logistics shipping receiving stores warehouse planning scheduling reliability environmental admin payroll "
    "contractor contractors vendor vendors supplier suppliers supervisor supervisors manager managers crew shift everybody somebody nobody"
).split())
PERSON_BEFORE = [
    (re.compile(r"\b(?:remind|chase|ask|ping|follow\s+up\s+with)\s+\Z", I), "remind"),
    (re.compile(r"\b(?:leads?|owners?)\s*[:\-–]\s*\Z|\b(?:led|owned|driven)\s+by\s+\Z", I), "lead"),
    (re.compile(r"(?:\bassign(?:ed)?\s+(?:this(?:\s+one)?\s+|it\s+)?to\s*:?\s+|\b(?:give|hand)\s+(?:it\s+|this\s+)?(?:over\s+)?to\s+"
                r"|\bassignees?\s*[:\-–]\s*|\bhave\s+|@)\Z", I), "asg"),
]
PERSON_AFTER = [
    # "Tom is lead", "Tom is the lead", "Tom as lead" (mods log round 1), but not "Tom is lead-certified".
    (re.compile(r"^\s+(?:owns|leads|is\s+leading|is\s+driving|will\s+coordinate|will\s+lead|(?:is|will\s+be|as)\s+(?:the\s+)?lead)\b(?!-)", I), "lead"),
    (re.compile(r"^\s+(?:will|to|should|needs?\s+to|has\s+to|is\s+going\s+to|is\s+(?!going\b)[a-z]+ing|does|handles|covers|takes|completes"
                r"|prepares|drafts|writes|checks|reviews|updates|books|orders|installs|fixes|runs)\b", I), "asg"),
    (re.compile(r"^\s*[:\-–]?\s*(?:about\s+|~\s*)?\d+(?:\.\d+)?\s*(?:hours?|hrs?|h)\b", I), "asg"),  # "Tom 20 hours", "Mike - 6 h"
]
# New names come only from unmistakable phrases. Group 1 is the name, group 2 a possible surname.
NAME_RE = r"(?:(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+)?([A-Za-z][\w'’-]*)(\s+[A-Za-z][\w'’-]*)?"
NEW_NAME_RULES = [
    (re.compile(rf"\bassign(?:ed)?\s+(?:this(?:\s+one)?\s+|it\s+)?to\s*:?\s+{NAME_RE}", I), "asg"),
    (re.compile(rf"\b(?:remind|ask)\s+{NAME_RE}", I), "remind"),
    (re.compile(r"@([A-Za-z][\w'-]*)"), "asg"),
    (re.compile(rf"\b(?:leads?|owners?)\s*[:\-–]\s*{NAME_RE}", I), "lead"),
    (re.compile(rf"\bassignees?\s*[:\-–]\s*{NAME_RE}", I), "asg"),
]
# A name that's also an everyday word counts only when it's capitalized: "Will" and "Mark" are people, "will" and "mark" words.
WORD_NAMES = set("will may mark rob bill pat sue grant frank chase jack art max hope joy faith".split())
# A list of names: words of a name (a surname capitalized), joined by commas, "and" or "&" (mods log round 1).
# Initials in a list are a name too, except teams' and units' initials.
_LIST_ITEM = r"[A-Za-z][\w'’-]*(?:\s+[A-Z][\w'’-]*)?"
NAME_LIST_RE = re.compile(rf"{_LIST_ITEM}(?:\s*(?:,\s*(?:and\s+|&\s*)?|\s+and\s+|\s*&\s*){_LIST_ITEM})+")
LIST_ITEM_RE = re.compile(rf"\b(?!and\b){_LIST_ITEM}")  # "and" joins names; it's never the start of one
LIST_CUE = re.compile(r"^(.*\b(?:each|apiece|per\s+(?:assignee|person|head))\s*[:\-–]\s*)", I)
LIST_CUE_BEFORE = re.compile(r"\b(?:assignees?|each|apiece|per\s+(?:person|head))\b", I)
NOT_INITIALS = set("HR QA QC EHS HSE IT PM OPS PO PR RFQ RFI EOD COB EOW EOM EOY OK NA TBD".split())


def is_name(w: str) -> bool:
    return bool(re.match(r"[A-Z][a-z]", w)) and w.lower() not in COMMON_WORDS and w.lower() not in NOT_PEOPLE


@dataclass
class _Mention:
    id: str | None
    start: int
    end: int
    text: str
    me: bool
    role: str = ""
    source: str = ""
    dir: str = ""


@dataclass
class PeopleFound:
    leads: list[Who] = field(default_factory=list)
    assignees: list[Who] = field(default_factory=list)
    notes: list[tuple[str, Who, str]] = field(default_factory=list)  # (role, who, phrase)
    skipped: list[tuple[str, Who, str]] = field(default_factory=list)


def find_people(text: str, people: Sequence[ParsePerson]) -> PeopleFound:
    """Leads and assignees named in the text: known people by name or alias, and new names from unmistakable phrases."""
    me = next((p for p in people if p.me), None)
    me_id = me.id if me else None
    out = PeopleFound()
    status = {p.id: p.status for p in people}

    def add(role: str, who: Who, source: str) -> None:
        target = out.leads if role == "leads" else out.assignees
        if any(x.key() == who.key() for x in target):
            return
        target.append(who)
        out.notes.append((role, who, source))

    def apply(role: str, who: Who, source: str) -> None:
        if who.id and status.get(who.id) == "retired":  # recognized, so not added as someone new, but not added at all
            if not any(x[1].id == who.id for x in out.skipped):
                out.skipped.append(("leads" if role == "lead" else "assignees", who, source))
            return
        if role == "remind":
            add("assignees", who, source)
            if me_id and who.id != me_id:
                add("leads", Who(me_id), source)
        else:
            add("leads" if role == "lead" else "assignees", who, source)

    # Known people (names and aliases, longest first) and "me". My own name and aliases count as me.
    tokens: list[tuple[str, str]] = []
    for p in people:
        if p.status in ("active", "retired"):
            for t in (p.name, *p.aliases):
                if t and not (p.me and t.lower() == "me"):
                    tokens.append((t, p.id))
    tokens.sort(key=lambda kv: -len(kv[0]))
    mentions: list[_Mention] = []
    if tokens:
        for m in re.finditer(rf"(?<!\w)(?:{'|'.join(esc(t) for t, _ in tokens)})(?!\w)", text, I):
            word = m.group(0)
            if word == word.lower() and word in WORD_NAMES:
                continue
            token, pid = next(kv for kv in tokens if kv[0].lower() == word.lower())
            if re.fullmatch(r"[A-Z]{1,3}", token) and word != token:  # a short alias in capitals counts only in capitals
                continue
            if re.fullmatch(r"(?:PS|NB)", word, I) and re.match(r"\s*:", text[m.end():]) and re.search(r"(?:^|[\n.!?]\s*)\Z", text[:m.start()]):
                continue  # "PS:" opening a sentence is a postscript
            mentions.append(_Mention(pid, m.start(), m.end(), word, pid == me_id))
    if me_id:
        for m in re.finditer(r"\bme\b", text, I):
            mentions.append(_Mention(me_id, m.start(), m.end(), m.group(0), True))
        for m in re.finditer(r"(?:,|\band)\s+I\b(?!['’])", text):  # "Tom and I will…"
            mentions.append(_Mention(me_id, m.end() - 1, m.end(), "I", True))
    mentions.sort(key=lambda mn: mn.start)
    for mn in mentions:
        before, after = text[max(0, mn.start - 40):mn.start], text[mn.end:mn.end + 30]
        for pattern, role in PERSON_BEFORE:
            x = pattern.search(before)
            if x:
                mn.role, mn.source, mn.dir = role, x.group(0) + mn.text, "before"
                break
        else:
            for pattern, role in PERSON_AFTER:
                x = pattern.search(after)
                if x:
                    mn.role, mn.source, mn.dir = role, mn.text + x.group(0), "after"
                    break
            else:
                if re.match(r"\s*:\s", after) and re.search(r"(?:^|[\n.!?;]\s*)\Z", before):  # "Tom: pull the coupling."
                    mn.role, mn.source, mn.dir = "asg", mn.text + ":", "after"

    def joined(a: _Mention, b: _Mention) -> bool:
        return bool(re.fullmatch(r"\s*(?:,|and|&|,\s*and)\s*", text[a.end:b.start], I))

    # "Assign to Tom and Mike" and "Tom and Mike will": a list shares its phrase.
    for a, b in zip(mentions, mentions[1:]):
        if joined(a, b) and a.dir == "before" and not b.role:
            b.role, b.source, b.dir = a.role, a.source + text[a.end:b.end], "before"
    for i in range(len(mentions) - 2, -1, -1):
        a, b = mentions[i], mentions[i + 1]
        if joined(a, b) and b.dir == "after" and not a.role:
            a.role, a.source, a.dir = b.role, text[a.start:b.start] + b.source, "after"
    # A sentence or line that's only a list of names, such as "Priya, Tom, Mike and Tyler.", or the list after "each:" or
    # "per assignee:", names the assignees (mods log round 1). It needs two names or more, and one of them known or an
    # assignee or "each" in the sentence before it, so "Valves, Pumps and Motors." adds no one. Its new names are new people.
    listed_new: list[tuple[str, str]] = []
    prev_seg = ""
    for seg in re.finditer(r"[^.!?;\n]+", text):
        cue = LIST_CUE.match(seg.group(0))
        cut = len(cue.group(1)) if cue else 0
        at, body = seg.start() + cut, seg.group(0)[cut:]
        list_cue = bool(cue) or bool(LIST_CUE_BEFORE.search(prev_seg))
        prev_seg = seg.group(0)
        if not NAME_LIST_RE.fullmatch(body.strip()):
            continue
        items: list[tuple[_Mention | None, str, bool]] = []
        for x in LIST_ITEM_RE.finditer(body):
            mn =next((y for y in mentions if y.start == at + x.start()), None)
            first, *rest = x.group(0).split()
            second = rest[0] if rest else ""
            if re.fullmatch(r"[A-Z]{2,3}", first):
                is_new = mn is None and first not in NOT_INITIALS and not second
            else:
                is_new = mn is None and is_name(first) and (not second or is_name(second))
            items.append((mn, x.group(0), mn is not None or is_new))
        if len(items) < 2 or not all(ok for _, _, ok in items) or not (list_cue or any(mn for mn, _, _ in items)):
            continue
        source = body.strip()
        for mn, name, _ in items:
            if mn is None:
                listed_new.append((name, source))
            elif not mn.role:
                mn.role, mn.source, mn.dir = "asg", source, "list"
    for mn in mentions:
        if mn.role:
            apply(mn.role, Who(mn.id), mn.source)
    for name, source in listed_new:
        apply("asg", Who(name=name), source)
    if me_id:
        for m in re.finditer(r"\bI(?:'ll|’ll|\s+will)\s+lead\b", text):
            add("leads", Who(me_id), m.group(0))
        for m in re.finditer(r"\bI(?:'ll|’ll|\s+will|\s+need\s+to|\s+have\s+to|\s+must|\s+should)\b(?!\s+(?:lead|ask|remind|ping|chase|tell|follow\s+up)\b)", text):
            add("assignees", Who(me_id), m.group(0))
    # "Remind him", "ask her": the person named last before it, or the subject of "X needs to / will / should".
    for m in re.finditer(r"\b(?:remind|chase|ask|ping|follow\s+up\s+with)\s+(?:him|her|them)\b", text, I):
        known = [mn for mn in mentions if not mn.me and mn.end <= m.start()]
        if known:
            apply("remind", Who(known[-1].id), f"{known[-1].text} … {m.group(0)}")
            continue
        subjects = [x for x in re.finditer(r"\b([A-Z][a-z][\w'-]*)\s+(?:needs?\s+to|has\s+to|will|should|is\s+going\s+to)\b", text[:m.start()])
                    if is_name(x.group(1))]
        if subjects:
            apply("remind", Who(name=subjects[-1].group(1)), f"{subjects[-1].group(0)} … {m.group(0)}")
    # Names that aren't on the people list.
    for pattern, role in NEW_NAME_RULES:
        for m in pattern.finditer(text):
            raw = m.group(1)
            surname = m.group(2) if pattern.groups >= 2 else None
            first = re.sub(r"['’]s\Z", "", raw)
            second = (surname or "").strip() if raw == first else ""
            at = m.end() - len(surname or "") - len(raw)
            if any(mn.start == at for mn in mentions) or not is_name(first):
                continue
            full = second and is_name(second)
            name = f"{first} {second}" if full else first
            apply(role, Who(name=name), m.group(0) if full else m.group(0)[:len(m.group(0)) - len(surname or "")])
    # No phrase at all, and exactly one known person named: that person is the assignee.
    if not out.leads and not out.assignees and not out.skipped:
        named = list(dict.fromkeys(mn.id for mn in mentions if not mn.me and status.get(mn.id) != "retired"))
        if len(named) == 1:
            add("assignees", Who(named[0]), next(mn.text for mn in mentions if mn.id == named[0]))
    return out


# ---- quick updates ----
STATE_WORDS = r"not started|in progress|under\s?way|started|re-?opened|parked|on hold|closed|done|completed?|finished"
STATE_PREFIX = re.compile(rf"^\s*({STATE_WORDS})(?:\s*[.:!,]|\s+[-–—])(?=\s|\Z)|^\s*({STATE_WORDS})\s*[.!]?\s*\Z", I)
STATE_NAMES = {"notstarted": "Not started", "inprogress": "In progress", "underway": "In progress", "started": "In progress",
               "reopened": "In progress", "parked": "Parked", "onhold": "Parked", "closed": "Closed", "done": "Closed",
               "complete": "Closed", "completed": "Closed", "finished": "Closed"}


@dataclass(frozen=True)
class QuickUpdate:
    state: str
    prefix: str
    rest: str


def quick_update(content: str) -> QuickUpdate | None:
    """Content text that starts with a state and a full stop, colon or dash ("Closed. Mike confirmed it.") sets the State."""
    m = STATE_PREFIX.match(content)
    if not m:
        return None
    rest = content[m.end():].strip()
    state = STATE_NAMES[re.sub(r"[\s-]+", "", (m.group(1) or m.group(2)).lower())]
    return QuickUpdate(state, m.group(0).strip(), rest[:1].upper() + rest[1:] if rest else "")


def prep_text(s: str) -> str:
    """The content text without file path lines, and an email's header lines left out except its subject."""
    mail = bool(re.search(r"^\s*From:", s, I | re.M) and re.search(r"^\s*(?:Subject|Sent|To):", s, I | re.M))
    lines = []
    for line in s.split("\n"):
        if is_path_line(line):
            continue
        if mail:
            subject = re.match(r"\s*Subject:\s*(.*)", line, I)
            if subject:
                line = subject.group(1)
            elif re.match(r"\s*(?:From|To|Cc|Bcc|Sent|Date|Importance|Attachments?):", line, I):
                line = ""
        lines.append(line)
    return "\n".join(lines)


# ---- the whole parse ----
STRONG = re.compile(r"\bdeadline\b|\bno later than\b|\bhard\s+(?:stop|date|cut-?off)\b|\bat the (?:very )?latest\b", I)
WEAK = re.compile(r"\b(?:must|ahead of|in time for|prior to)\b|\bbefore\s+(?:the|our|a|an)\s+\w", I)
REVISED = re.compile(r"\b(?:now|moved|pushed|slipped|changed|revised|rescheduled|delayed|postponed|extended|new\s+(?:due\s+)?date)\b", I)
BREAK = re.compile(r"[,;]|\s(?:and|but|or|while|whereas)\s", I)
REMIND = re.compile(r"\b(?:remind|reminder|ping|nudge|follow\s+up|check\s+in\s+with)\b", I)
URGENT = re.compile(r"\b(?:urgent(?:ly)?|asap|immediately|right away|as soon as possible|critical(?!\s+path)|(?:high|top|highest)\s+priority)\b", I)
NOT_URGENT = re.compile(r"\b(?:not|no|non|nothing|isn['’]t|wasn['’]t|never|less)\s*-?\s*(?:that\s+|very\s+|too\s+|so\s+)?\Z", I)
#: The order fields are listed in, in what Parse and populate found.
FIELD_ORDER = ("title", "state", "status", "due", "deadline", "deadline_desc", "reminder", "start", "recurrence", "urgent", "labels",
               "leads", "assignees", "lead_hours", "assignee_hours")
UPDATE_KEYS = ("state", "status", "due", "deadline", "deadline_desc")
NEW_TASK_KEYS = tuple(k for k in FIELD_ORDER if k != "status")


@dataclass(frozen=True)
class Known:
    """Values already in the window's fields, used when a rate of hours is turned into a total."""

    start: date | None = None
    due: date | None = None
    deadline: date | None = None
    recurrence: str = ""


def parse_capture(
    content: str, capture_type: str, today: date, people: Sequence[ParsePerson], labels: Sequence[ParseLabel],
    events: Sequence[str] = EVENT_WORDS, known: Known = Known(),
) -> ParseResult:
    """Read the content text and return the values for one capture type, "new_task" or "update".

    ``found`` lists each value with the phrase it came from, for the window to show
    before Save. A new task's description is its content text, so there's none to fill.
    """
    r = ParseResult()
    names = {p.id: p.name for p in people}

    def note(key: str, field_name: str, value: str, source: str, calc: str = "", why: str = "") -> None:
        r.found.append(Found(key, field_name, value, source.strip(), calc, why))

    quick = quick_update(content)
    if quick:
        content = quick.rest
        r.state = quick.state
        note("state", "State", quick.state, quick.prefix)
        if quick.rest:
            r.status = quick.rest
            note("status", "Current status", quick.rest, "the rest of the content text")
    text = prep_text(content).strip()
    sents = sentences(text)
    # An update's first sentence is its Current status (mods log round 1), as a new task's first sentence is its
    # description. A quick update's status, the rest of its text, comes first.
    if capture_type == "update" and not quick and sents:
        r.status = sents[0].text
        note("status", "Current status", r.status, "the first sentence")

    def sentence_at(pos: int) -> Sentence | None:
        return next((s for s in sents if s.start <= pos < s.end), sents[-1] if sents else None)

    event_re = re.compile(rf"\b({_tokens_re(events)})(?:s|es)?\b", I)
    # Hours phrases are blanked out (same length, so positions hold) before recurrence and dates are read.
    hours = find_hours(text)
    scan = text
    for h in hours:
        scan = scan[:h.start] + " " * (h.end - h.start) + scan[h.end:]

    # Recurrence first, so "every Tuesday" isn't read as a due date.
    recur_span: tuple[int, int] | None = None
    recur_day: str | None = None
    recur_nth = 0
    for pattern, name, has_day in RECURRENCE_RULES:
        m = next((x for x in pattern.finditer(scan)
                  if not (RECUR_ADJ.fullmatch(x.group(0)) and OTHER_EVENT_BEFORE.search(scan[max(0, x.start() - 40):x.start()]))), None)
        if not m:
            continue
        r.recurrence = name
        recur_span = (m.start(), m.end())
        note("recurrence", "Recurrence", name, m.group(0))
        if has_day:
            recur_day = m.group(1)
            recur_nth = NTH[m.group(0).split()[0].lower()] if name == "Monthly" else 0
        break
    plural = PLURAL_DAY_RE.search(scan)
    if plural and not r.recurrence:
        r.recurrence = "Weekly"
        note("recurrence", "Recurrence", "Weekly", plural.group(0))
    if plural and not recur_day:
        recur_day = plural.group(1)

    # Dates: "starting X", "from X", "between X and Y" and the first date of "X to Y" are the Start. The first date in a
    # sentence that asks for a reminder is the Reminder. The rest are Due or Deadline.
    dates = [d for d in find_dates(scan, today) if not recur_span or d.end <= recur_span[0] or d.start >= recur_span[1]]
    reminder_sentences: list[Sentence] = []
    candidates: list[DateHit] = []
    reminder_phrase = ""
    for d in dates:
        d.s = sentence_at(d.start)
    for i, d in enumerate(dates):
        s = d.s
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        next_here = nxt is not None and nxt.s is s
        lead = text[max(s.start, d.start - 16):d.start]
        between = text[d.end:nxt.start] if next_here else ""
        to_next = next_here and bool(re.fullmatch(r"\s*(?:to|through|thru|until|till|-|–|—)\s*", between, I)
                                     or (re.search(r"\bbetween\s+\Z", lead, I) and re.fullmatch(r"\s*and\s*", between, I)))
        if to_next or re.search(r"\b(?:starting|starts?|started|from|beginning|begins?|effective|commencing|kick(?:s|ing)?[- ]?off|as\s+of)"
                                r"\s+(?:on\s+|in\s+)?\Z", lead, I):
            d.role = "start"
            if to_next:
                nxt.range_of = d
                if nxt.kind == "weekday":  # "Monday to Friday"
                    while nxt.date < d.date:
                        nxt.date += timedelta(days=7)
            if not r.start:
                r.start = d.first or d.date
                note("start", "Start", long_date(r.start, today), ("" if to_next else lead.strip().split()[-1] + " ") + d.text)
            continue
        if d.from_ and not r.start:
            r.start = d.from_
            note("start", "Start", long_date(d.from_, today), d.text)
        if REMIND.search(s.text) and not any(x is s for x in reminder_sentences):
            reminder_sentences.append(s)
            d.role = "reminder"
            if not r.reminder:
                r.reminder = d.date
                reminder_phrase = d.text
                note("reminder", "Reminder", long_date(d.date, today), d.text)
            continue
        candidates.append(d)

    # Due or Deadline, from the words around each date. A date's lead is the text before it, back to the sentence
    # start or to the comma, "and" or "but" after the date before it; its tail runs on to the next such break.
    def cue(x: str) -> int:
        return 3 if STRONG.search(x) else 2 if WEAK.search(x) or event_re.search(x) else 0

    for i, d in enumerate(dates):
        s = d.s
        prev = dates[i - 1] if i > 0 else None
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        if prev and prev.s is s:
            b = BREAK.search(text[prev.end:d.start])
            d.lead_from = prev.end + b.start() + 1 if b else prev.end
        else:
            d.lead_from = s.start
        if d.range_of:
            d.lead_from = d.range_of.lead_from
        if nxt and nxt.s is s:
            b = BREAK.search(text[d.end:nxt.start])
            d.tail_to = d.end + b.start() if b else d.end
        else:
            d.tail_to = s.end
    in_sentence: dict[int, int] = {}
    for d in candidates:
        in_sentence[id(d.s)] = in_sentence.get(id(d.s), 0) + 1
    for i, d in enumerate(candidates):
        s = d.s
        lead, tail = text[d.lead_from:d.start], text[d.end:d.tail_to]
        lead_cue, tail_cue = cue(lead), cue(tail)
        prev = candidates[i - 1] if i > 0 else None
        if lead_cue == 3 or (tail_cue == 3 and not re.search(r"\bdue\b", lead, I)):
            d.strength = 3
        elif re.search(r"\b(?:due|target)\b", lead, I):
            d.strength = 0
        elif lead_cue or tail_cue:
            d.strength = 2
        else:
            d.strength = 1 if in_sentence.get(id(s)) == 1 and cue(s.text) else 0
        if prev and prev.s is s and REVISED.search(lead):
            if not d.strength and not re.search(r"\bdue\b", lead, I):
                d.strength = prev.strength
            prev.dropped = True
    live = [d for d in candidates if not d.dropped]
    deadline = next((d for k in (3, 2, 1) for d in live if d.strength == k), None)
    due = next((d for d in live if d is not deadline and not d.strength), None) or \
        next((d for d in live if d is not deadline and d.strength < 3), None)
    if deadline:
        s = deadline.s
        r.deadline = deadline.date
        note("deadline", "Deadline", long_date(deadline.date, today), deadline.text)
        r.deadline_desc = deadline_text(s.text, [text[x.start:x.end] for x in dates if x.start >= s.start and x.end <= s.end], event_re)
        if r.deadline_desc:
            note("deadline_desc", "Deadline description", r.deadline_desc, s.text)
    if due:
        r.due = due.date
        lead_word = re.search(r"\b(?:by|on|before|due|until)\s+\Z", text[max(0, due.start - 16):due.start], I)
        note("due", "Due", long_date(due.date, today), (lead_word.group(0) if lead_word else "") + due.text)
    # With no other due date, the reminder date is also the Due: "Remind Tyler tomorrow to book the contractor."
    if r.reminder and not r.due:
        r.due = r.reminder
        note("due", "Due", long_date(r.due, today), reminder_phrase)
    if recur_day and not r.start:
        r.start = (recur_nth and nth_weekday(today, recur_nth, weekday_no(recur_day))) or next_weekday(today, weekday_no(recur_day))
        note("start", "Start", long_date(r.start, today), recur_day)

    # Urgent, unless it's denied: "not urgent", "non-critical". "Critical path" isn't urgent either.
    urgent = next((m for m in URGENT.finditer(text) if not NOT_URGENT.search(text[max(0, m.start() - 20):m.start()])), None)
    if urgent:
        r.urgent = True
        note("urgent", "Urgent", "Yes", urgent.group(0))
    for label in labels:
        for keyword in label.keywords or (label.name,):
            m = re.search(rf"(?<!\w){esc(keyword)}(?:s|es|ing|ed)?(?!\w)", text, I)
            if m:
                r.labels.append(label.name)
                note("labels", "Label", label.name, m.group(0))
                break
    found_people = find_people(text, people)
    r.leads, r.assignees = found_people.leads, found_people.assignees

    def who(w: Who) -> str:
        return names.get(w.id, w.id or "") if w.id else f"{w.name} (new)"

    for role, w, source in found_people.notes:
        note(role, "Lead" if role == "leads" else "Assignee", who(w), source)
    for role, w, source in found_people.skipped:
        note(role, "Lead" if role == "leads" else "Assignee", who(w), source, why=f"Not added: {who(w)} is retired on the people list.")
    tokens = sorted([n for p in people if p.status == "active" for n in (p.name, *p.aliases) if n and n.lower() != "me"]
                    + [w.name for w in (*r.leads, *r.assignees) if w.is_new], key=lambda n: -len(n))

    # The title comes from the first sentence that leaves two words or more, else the first that leaves one.
    pick = one_word = None
    for s in sents:
        t = title_text(s.text, today, tokens, events)
        if t and re.search(r"\s", t):
            pick = (s, t)
            break
        if t and not one_word:
            one_word = (s, t)
    pick = pick or one_word
    if pick:
        r.title = pick[1]
        r.found.insert(0, Found("title", "Title", r.title, pick[0].text))

    _fill_hours(r, text, hours, people, today, known, note)

    keys = UPDATE_KEYS if capture_type == "update" else NEW_TASK_KEYS if capture_type == "new_task" else ()
    empty = ParseResult()
    for key in FIELD_ORDER:
        if key not in keys:
            setattr(r, key, getattr(empty, key))
    r.found = sorted((f for f in r.found if f.key in keys), key=lambda f: FIELD_ORDER.index(f.key))
    return r


def _fill_hours(r: ParseResult, text: str, hours: list[HoursHit], people: Sequence[ParsePerson], today: date, known: Known,
                note: Callable[..., None]) -> None:
    """Hours go to the lead or the assignees by their clause. A rate becomes a total over Start to Due (or over its own
    length) for a one-time task, or the hours in one occurrence for a routine one."""
    def clause_at(pos: int) -> tuple[str, int]:
        a = max(text.rfind(c, 0, pos) for c in ".;!?\n") + 1
        ends = [i for i in (text.find(c, pos) for c in ".;!?\n") if i >= 0]
        return text[a:min(ends) if ends else len(text)], pos - a

    def names_of(ws: list[Who]) -> list[str]:
        out: list[str] = []
        for w in ws:
            p = next((x for x in people if x.id == w.id), None) if w.id else None
            if p:
                out += ["me", "I", *([] if p.name.lower() == "me" else [p.name]), *p.aliases] if p.me else [p.name, *p.aliases]
            else:
                out.append(w.name)
        return [n for n in out if n]

    def where(s: str, ws: list[Who]) -> list[int]:
        return [m.start() for n in names_of(ws) for m in re.finditer(rf"(?<!\w){esc(n)}(?!\w)", s, 0 if n == "I" else I)]

    def role_for(s: str, at: int) -> str:
        if re.search(r"\bfor\s+(?:the\s+)?lead\b|\blead(?:'s)?\s+(?:hours|time|load|effort)\b|\bas\s+(?:the\s+)?lead\b", s, I):
            return "lead_hours"
        if re.search(r"\b(?:for|per)\s+(?:the\s+|each\s+)?assignees?\b|\bassignees?(?:'s|')?\s+(?:hours|time|load|effort)\b", s, I):
            return "assignee_hours"
        lead_at, asg_at = where(s, r.leads), where(s, r.assignees)
        if bool(lead_at) != bool(asg_at):
            return "lead_hours" if lead_at else "assignee_hours"
        if lead_at:
            def before(x: list[int]) -> int:
                return max([-1, *[i for i in x if i < at]])

            def after(x: list[int]) -> int:
                return min([10**9, *[i for i in x if i > at]])

            if before(lead_at) != before(asg_at):
                return "lead_hours" if before(lead_at) > before(asg_at) else "assignee_hours"
            if after(lead_at) != after(asg_at):
                return "lead_hours" if after(lead_at) < after(asg_at) else "assignee_hours"
        if re.search(r"\b(?:lead|leads|leading|owner|owns|driving|oversight|coordinat\w*)\b", s, I):
            return "lead_hours"
        return "assignee_hours" if r.assignees or not r.leads else "lead_hours"

    routine = r.recurrence or known.recurrence
    for h in hours:
        key = h.role or role_for(*clause_at(h.start))
        name = "Lead hours" if key == "lead_hours" else "Assignee hours"
        if getattr(r, key) or any(f.key == key for f in r.found):
            continue
        if not h.per:
            setattr(r, key, one_decimal(h.hours))
            note(key, name, f"{getattr(r, key)} h", h.text, calc=h.calc)
            continue
        per_week = h.hours / WEEKS_IN[h.per]
        if routine:
            setattr(r, key, one_decimal(half_hours(per_week * OCCURRENCE_WEEKS[routine])))
            note(key, name, f"{getattr(r, key)} h", h.text, calc=f"{one_decimal(h.hours)} h a {h.per}, for each {routine.lower()} occurrence")
            continue
        if h.for_weeks:
            setattr(r, key, one_decimal(half_hours(per_week * h.for_weeks)))
            note(key, name, f"{getattr(r, key)} h", h.text, calc=f"{one_decimal(h.hours)} h a {h.per} for {h.for_text}")
            continue
        start = r.start or known.start or today
        end = r.due or r.deadline or known.due or known.deadline
        if not end or end < start:
            note(key, name, f"{one_decimal(h.hours)} h a {h.per}", h.text, why="Not filled: a rate needs a Due date to make a total.")
            continue
        weeks = work_weeks(start, end)
        setattr(r, key, one_decimal(half_hours(per_week * weeks)))
        note(key, name, f"{getattr(r, key)} h", h.text,
             calc=f"{one_decimal(h.hours)} h a {h.per} for {one_decimal(weeks)} weeks, {short(start, today)} to {short(end, today)}")
