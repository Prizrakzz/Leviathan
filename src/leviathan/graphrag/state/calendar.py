"""THE FORWARD RELEASE CALENDAR -- STATE ENGINE DESIGN sec 5.2 (D7), plus APPENDIX B DELTA PASS 1's
five corrections, which S0 wrote into ``configs/graphrag/numbers/release_calendar.yaml`` and which this
module is the only consumer of. Sitting S3.

WHAT THIS MODULE IS. ``next_release(table, asof)`` -- PURE CALENDAR ARITHMETIC over the RULE, and
nothing else. It reads no clock (the ``cascade._cw_first_of_months`` discipline, :7538): every answer is
a function of the as-of it is handed, so a fixture and a serving turn compute the same window and a
HISTORICAL as-of cannot leak a date the record did not know.

FOUR PROPERTIES, each a decision:

  1. **A RULE PRINTS A WINDOW, NEVER A TIME** (owner decision 4). Six publishers state a clock time and
     the config records none of them in a rule value; a windowed rule returns two ISO dates and the
     watch row says "between" them, never a point it cannot know.
  2. **NO EXPLICIT FUTURE DATE RIDES IN V1** (sec 5.2). The config carries rules only, so there is no
     hand-declared future list for a historical as-of to leak. ``published_date`` is the one kind that
     names a date at the publisher, and this module deliberately COMPUTES NOTHING for it.
  3. **A SOURCE WITH NO RULE IS A ROW THAT SAYS SO.** A table in ``uncalendared:``, or in neither map,
     declines ``no_calendar_rule`` and the watch row prints the design's own sentence. Absence is
     stated; it is never a missing line.
  4. **FIRST BUSINESS DAY NAMES A WEEK, NOT A DAY.** NASS and FGIS publish on "the first business day of
     each week" and the estate holds no holiday calendar for either publisher (proved live: Labor Day
     moved the 2026-09-08 FGIS report off Monday). A rule that named a Monday would be wrong several
     times a year, so the row names the WEEK and says "on its first business day".

ONE MAPPING ONTO THE CLOSED WATCH VOCABULARY IS DECLARED DRIFT, not a widening. Sec 6.7's ``watch:``
enum was written before S0 added the ``published_date`` rule kind, so it has no word for "the publisher
states its own next date and follows no rule this board can compute". That case declines
``rule_unverified`` -- the word for "this source's rule cannot be turned into a date here" -- and the
returned record carries ``verified`` separately so a row can still say whether the RULE was read off the
publisher. No word is invented; the drift is named here and in the S3 report.
"""
from __future__ import annotations

import datetime as _dt
import functools
from dataclasses import dataclass
from typing import Optional

import yaml

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag

_REL = ("numbers", "release_calendar.yaml")

#: The closed rule kinds. The config declares the same list under ``rule_kinds`` and ``state/lint.py``
#: fails on any other value; this tuple is what the CONSUMER knows how to compute, and
#: :func:`check_rule_kinds` asserts the two agree so a config kind nobody implements cannot ship green.
RULE_KINDS: tuple = ("monthly_window", "weekly_dow", "first_business_day", "daily_sessions",
                     "published_date")

_DOW: dict = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

#: The words each kind prints, keyed so the sentence is a LITERAL rather than a format built at the
#: call site. Every one is letters plus ISO dates.
KIND_WORDS: dict = {
    "monthly_window": "scheduled between {opens} and {closes} by the publisher's own window",
    "weekly_dow": "scheduled for {date}, the publisher's own weekday",
    "first_business_day": "scheduled in the week beginning {week_of}, on that week's first business day",
    "daily_sessions": "on the next session; the venue calendar is not read here, so no day is named",
}

#: The same sentence WITHOUT the dates, for a consumer that prints them itself. An SB-W row's shape is
#: "{what} -- {ISO}" (sec 6.2), so a `what` built from :data:`KIND_WORDS` printed every date twice:
#: "scheduled between 2026-10-01 and 2026-10-05 by the publisher's own window -- 2026-10-01 to
#: 2026-10-05". The dated sentence stays -- a caller that renders no tail still needs it -- and the
#: watch producer reads this one.
RULE_WORDS: dict = {
    "monthly_window": "scheduled inside the publisher's own monthly window, on these dates",
    "weekly_dow": "scheduled on the publisher's own weekday",
    "first_business_day": "scheduled on the first business day of the week beginning",
    "daily_sessions": "on the next session; the venue calendar is not read here, so no day is named",
}


@dataclass(frozen=True)
class Release:
    """ONE table's next scheduled print, or the named reason there is none.

    ``opens`` / ``closes`` / ``date`` / ``week_of`` are ISO strings or None; ``dates`` is what an SB-W
    row prints after its dash, and it is EMPTY on a decline and on ``daily_sessions`` -- the two cases
    where naming a date would be a claim the estate cannot back."""

    table: str
    source: str = ""
    kind: str = ""
    opens: Optional[str] = None
    closes: Optional[str] = None
    date: Optional[str] = None
    week_of: Optional[str] = None
    words: str = ""
    rule_words: str = ""          # :data:`RULE_WORDS` -- the same sentence with its dates left to the
    #                               caller, so an SB-W row does not print them in both halves
    dates: str = ""
    verified: bool = False
    declined: Optional[str] = None

    @property
    def fired(self) -> bool:
        return self.declined is None


@functools.lru_cache(maxsize=1)
def load_release_calendar() -> dict:
    """The raw document (lru_cached, the registry convention). One reader for the whole package."""
    p = ex._CFG.joinpath(*_REL)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def table_sources() -> dict:
    """``{table: source_id}`` over ``sources[*].tables``. The config's own lint already fails when a
    card appears in two sources or in both ``sources`` and ``uncalendared``, so this map is total and
    unambiguous by the time it is read here."""
    out: dict = {}
    for sid, src in (load_release_calendar().get("sources") or {}).items():
        for t in ((src or {}).get("tables") or ()):
            out[str(t)] = str(sid)
    return out


@functools.lru_cache(maxsize=1)
def uncalendared() -> dict:
    """``{table: the declared reason no rule exists}``. A DECLARED absence, which is why the watch row
    can say so plainly instead of falling through a lookup."""
    return dict(load_release_calendar().get("uncalendared") or {})


def check_rule_kinds() -> list:
    """Every ``rule.kind`` in the config is one this module computes, and every kind the config declares
    under ``rule_kinds`` is in :data:`RULE_KINDS`. Empty == clean.

    IT IS A CONSUMER-SIDE LINT and it earns its place: S0's config declares the enum, but a kind nobody
    implemented would pass that lint and then decline at serve time with a word about the RULE when the
    real fact is about the READER. This clause makes that a build failure."""
    errs: list = []
    doc = load_release_calendar()
    declared = tuple(doc.get("rule_kinds") or ())
    for k in declared:
        if k not in RULE_KINDS:
            errs.append(f"release_calendar declares rule kind {k!r}, which state/calendar.py does not "
                        f"compute; the closed set here is {RULE_KINDS}")
    for sid, src in (doc.get("sources") or {}).items():
        kind = ((src or {}).get("rule") or {}).get("kind")
        if kind not in RULE_KINDS:
            errs.append(f"release_calendar source {sid!r} declares rule kind {kind!r}, outside "
                        f"{RULE_KINDS}")
    return errs


# ---------------------------------------------------------------------------------------------------
# the arithmetic -- no clock, no locale, no holiday table
# ---------------------------------------------------------------------------------------------------
def _date(iso: Optional[str]) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return None


def _first_of_next_month(d: _dt.date) -> _dt.date:
    return _dt.date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)


def _monthly_window(a: _dt.date, day_min: int, day_max: int) -> tuple:
    """The next window whose CLOSE is on or after the as-of, with its OPEN never behind the as-of. The
    config caps every declared day at 28, so a window exists in every month -- ``state/lint.py`` pins
    that -- and the only clamp needed is the one below.

    THE OPEN IS CLAMPED BECAUSE AN SB-W ROW CALLS THIS "THE NEXT SCHEDULED PRINT". Inside the
    publisher's own window the honest statement is "between today and the close", not "between a day
    that has passed and the close": ``next_release('silver_wasde', '2026-09-11')`` returned
    2026-09-09..2026-09-12, and a forward row that names a date already gone is a claim about the past
    wearing a future's clothes -- the same reason :func:`_next_dow` is strict."""
    lo, hi = max(1, int(day_min)), max(1, int(day_max))
    opens, closes = _dt.date(a.year, a.month, lo), _dt.date(a.year, a.month, hi)
    if a > closes:
        nxt = _first_of_next_month(a)
        opens, closes = _dt.date(nxt.year, nxt.month, lo), _dt.date(nxt.year, nxt.month, hi)
    return max(opens, a), closes


def _next_dow(a: _dt.date, dow: int) -> _dt.date:
    """The next occurrence of ``dow`` STRICTLY after the as-of. Strictly, because on the print day
    itself the estate cannot know whether the print has landed, and naming today as a forward date
    would be a claim about the past wearing a future's clothes."""
    delta = (int(dow) - a.weekday()) % 7
    return a + _dt.timedelta(days=(7 if delta == 0 else delta))


def _next_week_start(a: _dt.date) -> _dt.date:
    """The Monday of the NEXT week. Same reason as above and one more: without a holiday calendar the
    estate cannot know whether THIS week's first business day has already printed, so it names the next
    week -- which can only understate how soon the next print is, never overstate it."""
    return a - _dt.timedelta(days=a.weekday()) + _dt.timedelta(days=7)


def _in_season(d: _dt.date, season_from: Optional[str], season_to: Optional[str]) -> bool:
    if not season_from or not season_to:
        return True
    return str(season_from) <= f"{d.month:02d}-{d.day:02d}" <= str(season_to)


def _season_start(year: int, season_from: str) -> _dt.date:
    m, dd = str(season_from).split("-")
    return _dt.date(year, int(m), int(dd))


# ---------------------------------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------------------------------
def next_release(table: str, asof: str, *, doc: Optional[dict] = None) -> Release:
    """The next scheduled print for ONE card, from the RULE alone (sec 5.2).

    ``doc`` overrides the loaded config so a deterministic bar can hand this function a two-source
    document and grade the arithmetic without touching the estate's own calendar -- the injection
    discipline the whole package runs on.

    THE FIVE KINDS, and what each may print:
      * ``monthly_window`` -- two ISO dates and the word "between";
      * ``weekly_dow`` -- one ISO date, strictly after the as-of;
      * ``first_business_day`` -- the WEEK's Monday, and the sentence names the week, not the day;
      * ``daily_sessions`` -- no date at all: "on the next session";
      * ``published_date`` -- nothing is computed, and the row says the publisher states its own date.
    """
    table = str(table or "")
    d = doc if doc is not None else load_release_calendar()
    if doc is None:
        srcs, unc = table_sources(), uncalendared()
    else:
        srcs = {str(t): str(sid) for sid, s in (d.get("sources") or {}).items()
                for t in ((s or {}).get("tables") or ())}
        unc = dict(d.get("uncalendared") or {})
    a = _date(asof)
    if a is None:
        return Release(table=table, declined="no_calendar_rule",
                       words="the as-of this row was handed is not a date, so no window is computed")
    if table in unc or table not in srcs:
        return Release(table=table, declined="no_calendar_rule",
                       words="no release rule is declared for this series")

    sid = srcs[table]
    src = ((d.get("sources") or {}).get(sid)) or {}
    rule = src.get("rule") or {}
    kind = str(rule.get("kind") or "")
    verified = bool(src.get("verified_against"))

    if kind == "monthly_window":
        opens, closes = _monthly_window(a, rule.get("day_min", 1), rule.get("day_max", 28))
        return Release(table=table, source=sid, kind=kind, opens=opens.isoformat(),
                       closes=closes.isoformat(), verified=verified,
                       words=KIND_WORDS[kind].format(opens=opens.isoformat(),
                                                     closes=closes.isoformat()),
                       rule_words=RULE_WORDS[kind],
                       dates=f"{opens.isoformat()} to {closes.isoformat()}")
    if kind == "weekly_dow":
        dow = _DOW.get(str(rule.get("dow") or "").upper())
        if dow is None:
            return Release(table=table, source=sid, kind=kind, declined="no_calendar_rule",
                           words="no release rule is declared for this series")
        nxt = _next_dow(a, dow)
        return Release(table=table, source=sid, kind=kind, date=nxt.isoformat(), verified=verified,
                       words=KIND_WORDS[kind].format(date=nxt.isoformat()),
                       rule_words=RULE_WORDS[kind], dates=nxt.isoformat())
    if kind == "first_business_day":
        wk = _next_week_start(a)
        sf, stq = rule.get("season_from"), rule.get("season_to")
        if sf and stq and not _in_season(wk, sf, stq):
            year = wk.year if f"{wk.month:02d}-{wk.day:02d}" < str(sf) else wk.year + 1
            start = _season_start(year, sf)
            wk = start + _dt.timedelta(days=(7 - start.weekday()) % 7)
        return Release(table=table, source=sid, kind=kind, week_of=wk.isoformat(), verified=verified,
                       words=KIND_WORDS[kind].format(week_of=wk.isoformat()),
                       rule_words=RULE_WORDS[kind], dates=wk.isoformat())
    if kind == "daily_sessions":
        return Release(table=table, source=sid, kind=kind, verified=verified,
                       words=KIND_WORDS[kind], rule_words=RULE_WORDS[kind], dates="")
    if kind == "published_date":
        return Release(table=table, source=sid, kind=kind, verified=verified,
                       declined="rule_unverified",
                       words="the publisher states its next date rather than following a rule this "
                             "board can compute")
    return Release(table=table, source=sid, kind=kind, declined="no_calendar_rule",
                   words="no release rule is declared for this series")
