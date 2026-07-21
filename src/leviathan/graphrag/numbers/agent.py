"""Numbers SQL agent — the LLM that turns a question into typed NumberQuery lookups (Phase 3).

The model NEVER writes SQL and NEVER chooses the as-of date. It's given the registry (a cached system prompt)
and one tool, ``lookup_number``, whose schema mirrors NumberQuery MINUS asof. The agent fills table/metric/
scope; the loop injects the caller's fixed ``asof`` and runs it through the deterministic leakage-safe builder.
So point-in-time correctness is a property of the harness, not of prompt discipline — the agent literally has no
lever to see the future. Returns the model's answer plus the exact (query, rows) provenance behind every number.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import stats as ST
from leviathan.graphrag.numbers.registry import NumbersRegistry, TableSpec, load_registry

HAIKU = "claude-haiku-4-5"                                 # cheap + mechanical; the agent just selects table/metric/scope
TOOL_NAME = "lookup_number"
STATS_TOOL_NAME = "compute_stat"                           # W3.5 deterministic stats tool belt (enum-locked)


def _stats_tool_on() -> bool:
    """Kill-switch GRAPHRAG_STATS_TOOL (default ON). OFF removes compute_stat from BOTH the tool schema and the
    system prompt -- byte-identical to the pre-W3.5 agent (no stats bullet, no tool, no handles minted). Any
    value other than an explicit off/0/false leaves it on (fail-safe-on: the belt is descriptive-only + fenced)."""
    return os.environ.get("GRAPHRAG_STATS_TOOL", "on").strip().lower() not in ("off", "0", "false", "no")

# ── ESR destination-scope honesty guard ──────────────────────────────────────────────────────────────
# silver_esr carries per-DESTINATION rows, but the registered query shape has NO destination filter (the
# country column is a raw unmapped FAS code — tables.yaml: "destination filtering is deferred"). A
# destination-scoped ask ("how are corn sales to China pacing?") would otherwise get a NATIONAL total
# presented as if it answered the question — silently wrong. Until the FAS code mapping ships, this guard
# deterministically detects a named BUYER/destination in the question and, when an ESR lookup actually ran:
#   (a) stamps a scope_note on the ESR tool_result so the model knows the value is a national total, and
#   (b) prepends a reader-facing caveat to the final answer — the decline never depends on prompt discipline.
# Detection is deliberately conservative: it fires only on explicit BUYER-directional phrasings ("sales to
# China", "Chinese purchases", "bookings by Egypt"), never on a bare country mention, and "from <country>"
# purchase phrasings are excluded as seller-ambiguous — an ambiguous ask fails toward NOT-destination-scoped
# so national questions are never degraded (byte-identical path when the guard does not fire). The United
# States is the REPORTER in ESR and is deliberately absent from the destination vocabulary.
_ESR_DESTINATIONS: list[tuple[str, list[str], list[str]]] = [
    # (display name, country-name forms, demonym/adjective forms) — the major weekly-export-sales buyers.
    ("China", ["china"], ["chinese"]),
    ("Mexico", ["mexico"], ["mexican"]),
    ("Japan", ["japan"], ["japanese"]),
    ("South Korea", ["south korea", "korea"], ["south korean", "korean"]),
    ("Taiwan", ["taiwan"], ["taiwanese"]),
    ("Egypt", ["egypt"], ["egyptian"]),
    ("the Philippines", ["the philippines", "philippines"], ["philippine", "filipino"]),
    ("Vietnam", ["vietnam", "viet nam"], ["vietnamese"]),
    ("Indonesia", ["indonesia"], ["indonesian"]),
    ("Colombia", ["colombia"], ["colombian"]),
    ("Nigeria", ["nigeria"], ["nigerian"]),
    ("Bangladesh", ["bangladesh"], ["bangladeshi"]),
    ("Pakistan", ["pakistan"], ["pakistani"]),
    ("Thailand", ["thailand"], ["thai"]),
    ("Turkey", ["turkey", "turkiye"], ["turkish"]),
    ("Canada", ["canada"], ["canadian"]),
    ("the European Union", ["the european union", "european union", "the eu", "eu"], []),
    ("Spain", ["spain"], ["spanish"]),
    ("Italy", ["italy"], ["italian"]),
    ("the Netherlands", ["the netherlands", "netherlands"], ["dutch"]),
    ("Germany", ["germany"], ["german"]),
    ("the United Kingdom", ["the united kingdom", "united kingdom", "the uk", "uk", "britain"], ["british"]),
    ("Saudi Arabia", ["saudi arabia"], ["saudi"]),
    ("Iraq", ["iraq"], ["iraqi"]),
    ("Algeria", ["algeria"], ["algerian"]),
    ("Morocco", ["morocco"], ["moroccan"]),
    ("India", ["india"], ["indian"]),
    ("Malaysia", ["malaysia"], ["malaysian"]),
    ("Guatemala", ["guatemala"], ["guatemalan"]),
    ("Honduras", ["honduras"], ["honduran"]),
    ("the Dominican Republic", ["the dominican republic", "dominican republic"], ["dominican"]),
    ("Peru", ["peru"], ["peruvian"]),
    ("Chile", ["chile"], ["chilean"]),
    ("Venezuela", ["venezuela"], ["venezuelan"]),
    ("Cuba", ["cuba"], ["cuban"]),
    ("Brazil", ["brazil"], ["brazilian"]),
    ("Argentina", ["argentina"], ["argentine", "argentinian"]),
    ("unknown destinations", ["unknown destinations", "unknown destination"], []),
]
_DEST_DISPLAY: dict[str, str] = {t: disp for disp, names, dems in _ESR_DESTINATIONS for t in names + dems}

# "turkey" the bird: "turkey demand", "feed demand from turkey producers" are POULTRY asks, not Türkiye.
# The homonym stays valid in unambiguous directional positions ("sales to Turkey", "purchases by Turkey")
# but is excluded where the bare word sits in subject/from position.
_HOMONYMS: tuple[str, ...] = ("turkey",)


def _dest_alt(*, demonyms: bool, exclude: tuple[str, ...] = ()) -> str:
    """Alternation over destination terms, longest-first so 'south korea' wins over 'korea'."""
    terms = [t for _, names, dems in _ESR_DESTINATIONS for t in (names + dems if demonyms else names)]
    terms = [t for t in terms if t not in exclude]
    return "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))


_SALES_WORDS = r"(?:sales?|exports?|shipments?|bookings?|commitments?|purchases?|business|sold|shipped|booked|committed|movement)"
_BUYER_NOUNS = r"(?:purchases?|buying|buys|bookings?|cancellations?|orders|demand|imports?|commitments?)"
# Comparison idioms make "to <country>" NATIONAL ("sales compared to Brazil", "close to China's pace") —
# such words may not fill the gap before to/into, so those asks fail toward None.
_NOT_COMPARISON = r"(?!(?:compares?|compared|comparable|relative|close|closer|similar|equivalent|identical|versus)\b)"
# Seller-side words may not sit between a demonym and a buyer noun: "Brazilian export commitments" is
# Brazil-as-SELLER, not a buyer ask.
_NOT_SELLER = r"(?!(?:exports?|sales?|shipments?|selling)\b)"
_DEST_PATTERNS = [
    # "corn sales to China", "shipments of wheat into Vietnam" — a sales word, a short non-comparison gap,
    # then to/into + name.
    re.compile(rf"\b{_SALES_WORDS}\s+(?:{_NOT_COMPARISON}[\w'-]+\s+){{0,2}}?"
               rf"(?:to|into)\s+(?:the\s+)?({_dest_alt(demonyms=False)})\b"),
    # "Chinese purchases", "Egypt's wheat bookings", "Japanese buying" — demonym/name owning a buyer noun,
    # allowing a short non-seller gap (the commodity usually sits between: "China's corn purchases").
    re.compile(rf"\b({_dest_alt(demonyms=True, exclude=_HOMONYMS)})(?:'s)?\s+"
               rf"(?:{_NOT_SELLER}[\w'-]+\s+){{0,2}}?{_BUYER_NOUNS}\b"),
    # "China booked/bought/cancelled" — the destination as the buying subject.
    re.compile(rf"\b({_dest_alt(demonyms=False, exclude=_HOMONYMS)})\s+(?:has\s+|have\s+|had\s+)?"
               rf"(?:bought|booked|purchased|cancell?ed)\b"),
    # "purchases by Egypt", "cancellations by China" — buyer nouns with an explicit by-agent ('from' is
    # excluded: "purchases from X" reads seller-side).
    re.compile(rf"\b{_BUYER_NOUNS}\s+by\s+(?:the\s+)?({_dest_alt(demonyms=False)})\b"),
    # "demand from China", "cancellations from China", "buying out of Egypt" — these nouns are buyer-side
    # even with 'from' (a buyer cancels/books/orders; 'purchases from X' stays excluded as seller-side).
    re.compile(rf"\b(?:demand|buying|interest|cancellations?|bookings?|orders)\s+(?:from|out\s+of)\s+"
               rf"(?:the\s+)?({_dest_alt(demonyms=False, exclude=_HOMONYMS)})\b"),
]

# Destination-BREAKDOWN asks name no single buyer but are equally unanswerable from the destination-blind
# registration ("which countries are buying?", "top buyers", "sales by destination") — same honesty guard,
# generic wording.
_ESR_DEST_GENERIC = "individual destinations"
_GENERIC_DEST_PATTERNS = [
    re.compile(r"\b(?:by|per)\s+(?:destination|buyer|country)\b"),
    re.compile(r"\bwhich\s+(?:countries|destinations|buyers)\b"),
    re.compile(r"\b(?:top|biggest|largest|main|major)\s+(?:buyers?|destinations?)\b"),
    re.compile(r"\bwho(?:'s|\s+is|\s+are)?\s+(?:buying|booking|bought|booked)\b"),
    re.compile(r"\bdestination\s+(?:breakdown|mix|detail)\b"),
]


def esr_destination_scope(question: str) -> Optional[str]:
    """Display name of the named BUYER/destination when the question is UNAMBIGUOUSLY destination-scoped
    (explicit directional phrasing), the _ESR_DEST_GENERIC sentinel for a per-destination BREAKDOWN ask,
    else None — ambiguity fails toward None so national asks never degrade."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    for rx in _DEST_PATTERNS:
        m = rx.search(q)
        if m:
            return _DEST_DISPLAY[m.group(1)]
    for rx in _GENERIC_DEST_PATTERNS:
        if rx.search(q):
            return _ESR_DEST_GENERIC
    return None


def _esr_scope_note(dest: str) -> str:
    """Model-facing note stamped on an ESR tool_result for a destination-scoped ask."""
    if dest == _ESR_DEST_GENERIC:
        return ("NATIONAL TOTAL across ALL destinations — this lookup cannot break sales out by "
                "buyer/destination, so a per-destination breakdown is unavailable. If you state this figure, "
                "label it clearly as the US-wide total, never as a destination breakdown.")
    return (f"NATIONAL TOTAL across ALL destinations — this lookup cannot filter by buyer/destination, so a "
            f"{dest}-specific cut is unavailable. If you state this figure, label it clearly as the US-wide "
            f"total, never as a {dest} number.")


def _esr_destination_preface(dest: str) -> str:
    """Reader-facing honest decline of the destination cut (mentor register — no internal names/slugs)."""
    if dest == _ESR_DEST_GENERIC:
        return ("One limitation to flag before the numbers: the weekly US export sales data I can pull here "
                "is the national total across all buyers — a breakdown by individual destination isn't "
                "available from this lookup yet. Any figure below is the US-wide total, not a per-buyer "
                "view.\n\n")
    return (f"One limitation to flag before the numbers: the weekly US export sales data I can pull here is "
            f"the national total across all buyers — a breakdown for {dest} specifically isn't available from "
            f"this lookup yet. Any figure below is the US-wide total, not specific to {dest}.\n\n")


def _is_esr_call(c: dict) -> bool:
    return (c.get("query") or {}).get("table") == "silver_esr"


# -- R5 price-coverage decline guard (PRICE_OBSERVABILITY W2.5) ----------------------------------------
# silver_pink_sheet carries a FIXED set of governed price columns. Several commodities a pro desk asks
# about by name have NO column (NONE-tier): robusta coffee, white/refined sugar, MATIF (EU) milling wheat
# and maize, JSE/SAFEX South-African white and yellow maize, and rapeseed MEAL. Cloning the ESR
# destination guard: when a question is UNAMBIGUOUSLY a PRICE ask for one of these, we PREPEND a
# reader-facing caveat that names the nearest governed proxy WITH its basis caveat -- so the decline
# never depends on prompt discipline. Detection is conservative: a NONE-tier NAME must co-occur with
# PRICE-INTENT phrasing; ambiguity (a bare mention, or no price intent) fails toward None so a covered
# ask (palm / soy oil / US HRW wheat / raw sugar) is byte-identical (the guard never fires on it). The
# templates below are censused by config_check.check_price_register R5 (they must pass register_leaks
# clean) and the keys EXACTLY match config_check._NONE_TIER_DECLINE.
DECLINE_TEMPLATES: dict[str, str] = {
    # robusta template wording is fixed by the plan (S2.F7 -- the raw WB workbook DOES carry robusta, so a
    # false-scarcity claim is banned; the honest framing is "not in our GOVERNED columns", candidate add).
    "robusta": ("no robusta series is in our governed price columns (the raw source is retained -- a "
                "candidate column add); arabica (KC) is not a substitute -- the arabica-robusta spread is "
                "itself the story"),
    "white_sugar": ("no white (refined) sugar series is in our governed price columns; the raw-sugar world "
                    "benchmark we do carry is a different product, and the white-raw premium (the refining "
                    "differential) is exactly what it leaves out"),
    "french_wheat_matif": ("no MATIF (EU milling) wheat series is in our governed price columns; the US hard- "
                           "and soft-red-winter wheat benchmarks we carry are a different origin, separated by "
                           "currency, freight and milling-quality basis"),
    # F3 (PRICE_OBSERVABILITY W3.6 amendment): these three no longer name "the US survey-based farm price" as
    # the nearest governed proxy -- that series (avg_farm_price) was EXCLUDED from serving by the W3.0 probe
    # gate (tables.yaml:99-105), so pointing readers at it shipped a caveat naming a series that is not live.
    # They now decline WITHOUT a dead proxy; the farm-price ask itself declines via us_farm_price below. The
    # config_check R5b census (_check_decline_no_dead_metric) fails if any of these re-acquires a farm-price
    # reference while avg_farm_price stays unwhitelisted.
    "french_maize_matif": ("no MATIF (EU) maize series is in our governed price columns, and there is no world "
                           "maize price benchmark in the governed set at all -- no governed maize price proxy is "
                           "available here"),
    "jse_white_maize": ("no JSE/SAFEX South-African white-maize series is in our governed price columns, and no "
                        "governed maize price proxy of comparable origin is available here"),
    "jse_yellow_maize": ("no JSE/SAFEX South-African yellow-maize series is in our governed price columns, and no "
                         "governed maize price proxy of comparable origin is available here"),
    "rapeseed_meal_zce": ("no rapeseed-meal series is in our governed price columns; we carry rapeseed OIL and "
                          "soybean meal, but neither is a rapeseed-meal price -- the oil-versus-meal split and "
                          "the rape-versus-soy protein basis separate them"),
    # F1 (PRICE_OBSERVABILITY W3.6 amendment): the WASDE US survey-based farm price (avg_farm_price) is
    # label-dead after its 2011 vintage and EXCLUDED from serving (tables.yaml:99-105). A bare US farm-price
    # ask therefore has NO governed answer and must DECLINE deterministically -- this is the honesty row's
    # teeth (numbers_mismatched is vacuous when the agent looks up zero rows, so the decline guard, not the
    # verifier, enforces "state the governed series is not live"). No world benchmark may pose as a farm price.
    "us_farm_price": ("no governed US farm-gate price series is live right now: the survey-based farm price we "
                      "used to carry went label-dead after its 2011 vintage (a source-label change; restoration "
                      "is pending), so I cannot give you a current farm-gate figure, and a world benchmark is a "
                      "different basis, not a farm-gate price"),
}

# Conservative price-INTENT vocabulary (F2): each token must be a genuine VALUATION signal, not a generic
# quantity/logistics word. Deliberately NARROW so a non-price mention of a NONE-tier name fails toward None:
#   - bare "level(s)" is DROPPED (production/inventory/stock LEVELS are volume, not price; "price level(s)"
#     is still caught by "price");
#   - bare "how much" is DROPPED ("how much robusta was exported/produced" is volume; "how much does X cost"
#     still fires via cost/worth/per-tonne);
#   - "trade/trades/traded/trading" must be followed by a price-context word (trading AT/around/higher/...),
#     so "trading houses/desks/firms" (merchants) does NOT fire;
#   - "basis" excludes "basis risk" (operational risk, not the cash-futures basis).
_PRICE_INTENT = re.compile(
    r"\b(?:price|prices|priced|pricing|quote[sd]?|worth|cost|costs|"
    r"benchmark|per\s+(?:tonne|ton|mt|bushel)|\$\s*/?\s*(?:mt|t|bbl|bu)|spread|premium|discount|"
    r"basis(?!\s+risk)|"
    r"trad(?:e|es|ed|ing)\s+(?:at|around|near|above|below|higher|lower|up|down|flat))\b")
# One (display name, compiled name-pattern) per NONE-tier commodity, checked in priority order. Each
# pattern is deliberately narrow so a COVERED ask never matches: "white sugar" excludes bare "sugar" and
# "raw sugar"; "rapeseed meal" excludes covered "rapeseed oil"; the maize/wheat patterns require an
# EXCHANGE/origin qualifier (matif/euronext/jse/safex/south african/eu/european/french) so a generic
# corn/wheat ask (routed to WASDE farm price) is untouched. In particular "milling wheat" (F2: also a
# global quality grade, milling vs feed) fires french_wheat_matif ONLY with such an EU/MATIF qualifier --
# a bare "us milling wheat price" is a COVERED wheat_us_hrw/srw ask and must not degrade.
_PRICE_DECLINE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("jse_white_maize", re.compile(r"\b(?:jse|safex|south[ -]?african|s\.?a\.?)\b[\w %'-]*?\bwhite\s+maize\b"
                                   r"|\bwhite\s+maize\b[\w %'-]*?\b(?:jse|safex|south[ -]?african)\b")),
    ("jse_yellow_maize", re.compile(r"\b(?:jse|safex|south[ -]?african|s\.?a\.?)\b[\w %'-]*?\byellow\s+maize\b"
                                    r"|\byellow\s+maize\b[\w %'-]*?\b(?:jse|safex|south[ -]?african)\b")),
    ("french_wheat_matif", re.compile(r"\b(?:matif|euronext)\b[\w %'-]*?\bwheat\b"
                                      r"|\bwheat\b[\w %'-]*?\b(?:matif|euronext)\b"
                                      r"|\b(?:matif|euronext|eu|european|french|france)\b[\w %'-]*?\bmilling\s+wheat\b"
                                      r"|\bmilling\s+wheat\b[\w %'-]*?\b(?:matif|euronext|eu|european|french|france)\b")),
    ("french_maize_matif", re.compile(r"\b(?:matif|euronext)\b[\w %'-]*?\b(?:maize|corn)\b"
                                      r"|\b(?:maize|corn)\b[\w %'-]*?\b(?:matif|euronext)\b")),
    ("white_sugar", re.compile(r"\b(?:white|refined)\s+sugar\b|\blondon\s+(?:no\.?\s*5\s+)?sugar\b")),
    ("rapeseed_meal_zce", re.compile(r"\brape(?:seed)?\s*meal\b|\bcanola\s+meal\b")),
    ("robusta", re.compile(r"\brobusta\b")),
    # F1: a US farm-gate price ask (no exchange/origin qualifier). avg_farm_price is fenced out of serving, so
    # every farm-price ask now declines. Checked LAST so an exchange-qualified maize/wheat farm-price mention
    # (e.g. a JSE/MATIF ask that also says "farm") still resolves to its exchange decline first. No governed
    # series is a "farm price", so this can never shadow a covered pink_sheet ask.
    ("us_farm_price", re.compile(r"\bfarm[ -]?gate\b|\bfarm\s+price\b")),
]


def price_coverage_scope(question: str) -> Optional[str]:
    """The NONE-tier decline key when the question is UNAMBIGUOUSLY a PRICE ask for a commodity with no
    governed silver_pink_sheet column, else None. A NONE-tier NAME must co-occur with price-intent
    phrasing; ambiguity fails toward None so a covered ask (or a non-price mention) is byte-identical."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    if not _PRICE_INTENT.search(q):
        return None                                            # no price intent -> never fire (fail toward None)
    for name, rx in _PRICE_DECLINE_PATTERNS:
        if rx.search(q):
            return name
    return None


def _price_decline_preface(name: str) -> str:
    """Reader-facing honest decline of an uncovered price series (mentor register -- no internal slugs).
    PREPENDED deterministically so an uncaveated proxy can never pose as the asked-for series."""
    return f"One limitation to flag before the numbers: {DECLINE_TEMPLATES[name]}.\n\n"


def tool_schema(reg: NumbersRegistry) -> dict:
    """The single tool. `table` is an enum over the registry; asof is DELIBERATELY absent (the harness forces it)."""
    return {
        "name": TOOL_NAME,
        "description": "Look up one observed number (or aggregate) from the point-in-time data lake. "
                       "Always returns values as-known at the fixed as-of date; you cannot change that date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": sorted(reg.tables), "description": "which table"},
                "metric": {"type": "string", "description": "a metric listed for that table"},
                "commodity": {"type": "string", "description": "commodity/contract slug, if the table is per-commodity"},
                "country": {"type": "string", "description": "country, if the table is per-country"},
                "region": {"type": "string", "description": "station-region for weather tables (e.g. us_corn_iowa); "
                                                            "omit to use the commodity's primary region"},
                "period": {"type": "string", "description": "marketing year or year (per the table's period format)"},
                "period_start": {"type": "string", "description": "YYYY-MM-DD window start (date-grained tables)"},
                "period_end": {"type": "string", "description": "YYYY-MM-DD window end (date-grained tables)"},
                "agg": {"type": "string", "enum": ["latest", "series", "sum", "mean", "max", "min"],
                        "default": "latest"},
            },
            "required": ["table", "metric"],
        },
    }


# ── W3.5 deterministic stats tool belt ────────────────────────────────────────────────────────────────
# ONE enum-locked tool. The model does NOT do arithmetic: it REQUESTS a descriptive statistic by name over
# lookup HANDLES it already fetched THIS turn, and the code COMPUTES it (leviathan.graphrag.numbers.stats).
# The result is injected as an [N] row into `calls` -- carrying provenance {stat, params, input_handles} --
# so the all-numbers guard (orchestrator._verify_numbers_answer) value-checks it exactly like any observed
# number. Handles are TURN-SCOPED: only a handle minted by a lookup THIS turn resolves; a cross-turn handle
# (or any unknown id) is REFUSED (the agent cannot reach a prior turn's rows -- PIT is inherited from the
# rows the handle points at, never re-argued). The enum is stats.STAT_REGISTRY, whose names are lint-fenced
# against fit|trend|forecast|project|extrapolat|predict -- a projection tool is a forbidden forward statement
# wearing a math costume.
def stats_tool_schema() -> dict:
    return {
        "name": STATS_TOOL_NAME,
        "description": (
            "Compute ONE deterministic descriptive statistic over rows you ALREADY looked up THIS turn. You do "
            "NOT do the arithmetic -- you REQUEST it by naming the statistic and the lookup handle(s) that hold "
            "the numbers, and the result comes back as an observed [N] figure you then state in plain past/"
            "present tense. `series_handle`/`value_handle` are the `handle` field on a prior lookup_number "
            "result FROM THIS TURN; a handle from a different turn, or an unknown one, is refused. Never "
            "forecast, extrapolate, or fit a trend -- these are DESCRIPTIVE history only."),
        "input_schema": {
            "type": "object",
            "properties": {
                "stat": {"type": "string", "enum": sorted(ST.STAT_NAMES),
                         "description": "which statistic to compute"},
                "series_handle": {"type": "string", "description": "handle of a prior lookup whose returned "
                                  "rows form the series/history, oldest -> newest (agg=series lookups)"},
                "value_handle": {"type": "string", "description": "handle of a prior lookup whose latest value "
                                 "is the point scored (percentile/zscore); omit to score series_handle's last point"},
                "direction": {"type": "string", "enum": list(ST.DIRECTIONS),
                              "description": "for streak / revision_count"},
                "window": {"type": "integer", "description": "trailing window length for zscore"},
                "t1": {"type": "integer", "description": "start index for window_change (0-based; negatives allowed)"},
                "t2": {"type": "integer", "description": "end index for window_change"},
                "periods": {"type": "integer", "description": "lookback periods for yoy_delta (12 for monthly YoY)"},
            },
            "required": ["stat", "series_handle"],
        },
    }


def _series_from_rows(rows: list) -> list[float]:
    """The numeric series a handle exposes: the value cell of each row that coerces to a finite number
    (chronological -- the loop appends rows oldest -> newest). Non-numeric / null cells are dropped."""
    out: list[float] = []
    for r in rows or []:
        v = (r or {}).get("value")
        if v is None or isinstance(v, bool):
            continue
        try:
            out.append(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return out


def _handle_kd(rows: list) -> Optional[str]:
    """The latest knowledge/data date across a handle's rows -- the stat INHERITS it (PIT is a property of the
    input rows, never re-derived)."""
    ds = [d for r in (rows or []) for d in ((r or {}).get("knowledge_date"), (r or {}).get("data_date")) if d]
    return max(ds) if ds else None


def _dispatch_stat(stat: str, inp: dict, handles: dict) -> dict:
    """Resolve the referenced turn-scoped handles and run ONE stats function. Returns the stats contract dict
    (declined or not). RAISES KeyError for an unknown/cross-turn handle (the caller turns it into a refusal)."""
    sh = inp.get("series_handle")
    vh = inp.get("value_handle")
    for h in (sh, vh):
        if h is not None and h not in handles:
            raise KeyError(h)
    series = handles[sh]["series"]

    def _val():
        return handles[vh]["series"][-1] if vh is not None else (series[-1] if series else None)

    if stat == "streak":
        return ST.streak(series, inp.get("direction"))
    if stat == "percentile":
        return ST.percentile(_val(), series)
    if stat == "zscore":
        return ST.zscore(_val(), series, window=inp.get("window"))
    if stat == "window_change":
        return ST.window_change(series, inp.get("t1"), inp.get("t2"))
    if stat == "revision_count":
        return ST.revision_count(series, inp.get("direction"))
    if stat == "extrema":
        return ST.extrema(series)
    if stat == "yoy_delta":
        p = inp.get("periods")
        return ST.yoy_delta(series, periods=1 if p is None else p)
    raise ValueError(f"unknown stat {stat!r}")   # unreachable: the enum + STAT_NAMES gate this upstream


def _stat_provenance(stat: str, inp: dict, handles: dict) -> dict:
    """{stat, params, input_handles} stamped onto every injected stat [N] row so the guard + citations carry
    the exact derivation (which handles, which scalar params)."""
    params = {k: inp[k] for k in ("direction", "window", "t1", "t2", "periods", "value_handle")
              if inp.get(k) is not None}
    ins = [h for h in (inp.get("series_handle"), inp.get("value_handle")) if h]
    return {"stat": stat, "params": params, "input_handles": ins}


# The result of a percentile/streak/z-score is NOT in the series' unit -- it is its own kind of quantity. Only
# the magnitude-preserving stats (window/YoY change, extrema) inherit the series unit.
_STAT_UNIT = {"streak": "consecutive periods", "revision_count": "consecutive revisions",
              "percentile": "percentile", "zscore": "sigma"}


def _stat_calls(stat: str, res: dict, prov: dict, series_unit: Optional[str], kd: Optional[str]) -> list[dict]:
    """Turn a SUCCESSFUL stats result into one (or, for extrema, two) synthetic lookup call(s) -- each an
    [N] row carrying the computed value so the all-numbers guard value-checks it. A decline injects nothing."""
    unit = _STAT_UNIT.get(stat, series_unit)
    def _row(val, metric):
        q = {"table": STATS_TOOL_NAME, "metric": metric}
        return {"query": q, "rows": [{"value": val, "unit": unit, "knowledge_date": kd}],
                "status": "ok", "stat_provenance": prov}
    if stat == "extrema":
        return [_row(res["min"], "extrema_min"), _row(res["max"], "extrema_max")]
    return [_row(res["value"], stat)]


def _table_card(ts: TableSpec) -> str:
    ident = ", ".join(x for x in (
        f"commodity={ts.commodity_col}" if ts.commodity_col else "",
        f"country={ts.country_col}" if ts.country_col else "",
        f"period={ts.period_col}({ts.period_type})" if ts.period_col else "",
        "date-windowed" if ts.date_col and not ts.period_col else "") if x)
    metrics = ", ".join(f"{k} [{v.unit}]" if v.unit else k for k, v in ts.metrics.items())
    return (f"### {ts.id} ({ts.knowledge_semantics})\n{ts.description.strip()}\n"
            f"identify by: {ident or 'n/a'}\nmetrics: {metrics}\n{('note: ' + ts.notes.strip()) if ts.notes else ''}")


def system_prompt(reg: NumbersRegistry, stats_tool: Optional[bool] = None) -> str:
    cards = "\n\n".join(_table_card(reg.get(t)) for t in sorted(reg.tables))
    stats_on = _stats_tool_on() if stats_tool is None else stats_tool
    # The stats bullet ships ONLY when compute_stat is in the schema (kill-switch parity: off removes the tool
    # AND its steering, so the model is never told about a tool it does not have).
    stats_bullet = (
        "- To state a PERCENTILE, STREAK, Z-SCORE, or window/year-over-year CHANGE over figures you have "
        "looked up, do NOT do the arithmetic yourself -- REQUEST it with the compute_stat tool, naming the "
        "statistic and the lookup handle(s) that hold the numbers (each lookup_number result carries a "
        "`handle`). The computed figure comes back as an observed [N] value; state it in plain past/present "
        "tense (e.g. 'the latest reading sits in the 96th percentile of its own history [N]', 'a third "
        "consecutive downward revision [N]'). Percentile / streak / z-score vocabulary is servable ONLY "
        "through the tool, and only over history -- never as a forecast, trend-fit, or extrapolation.\n"
        if stats_on else "")
    return (
        "You are a data-lookup agent for an agricultural-commodity desk. Answer ONLY with numbers you actually "
        "retrieve via the lookup_number tool from the tables below — never invent or recall a figure. Every value "
        "is returned as-known at a fixed as-of date you cannot change (point-in-time correct). Call the tool as "
        "many times as needed (different tables/metrics/scopes), then give a short factual answer that states each "
        "number with its unit and its knowledge_date (when it was published). A tool_result has a `status`: "
        "`ok` (use the value); `not_known` (vintage tables only — the value was genuinely not yet published at "
        "the as-of date; say so plainly); `no_rows` (the query matched NO data — a filter/scope mismatch or a "
        "gap in the lake; say the figure is UNAVAILABLE from this lookup and that the scope may not have "
        "matched — NEVER claim it was 'not yet published' or 'not known at the as-of date'); or `error` (the "
        "lookup FAILED for a data-access reason — say the figure is UNAVAILABLE due to a lookup error, and do "
        "NOT claim it was 'not known at the as-of date'). Do not reason beyond the numbers.\n\n"
        "## Conventions\n"
        "- `commodity` is the exact CONTRACT SLUG, e.g. corn_cbot, soybeans_cbot, soybean_oil_cbot, "
        "hard_red_winter_wheat_kcbt, hard_red_spring_wheat_mgex, soft_red_winter_wheat_cbot, french_wheat_matif, "
        "malaysian_crude_palm_oil_cme, arabica_coffee, cotton, raw_sugar, cocoa — use the suffixed form, not 'corn'.\n"
        "- A marketing year is its START year as an INTEGER: the 2023/24 marketing year is 2023 (not 2024). "
        "For silver_wasde, period is the string '2023/24'.\n"
        "- silver_icco_cocoa is a SINGLE-COMMODITY WORLD cocoa balance sheet (annual): omit commodity and "
        "country; the word 'cocoa' routes to it via the table card alone. period is the cocoa marketing year "
        "as a string '2024/25'. Its su_ratio is ICCO's ANNUAL stocks-to-grindings ratio (end_stocks_kt / "
        "grindings_kt) -- report it as 'cocoa stocks-to-use (ICCO annual)' and NEVER conflate it with the "
        "PSD-World su_ratio.\n"
        "- silver_mpob is MONTHLY Malaysian palm-oil fundamentals under commodity='malaysian_crude_palm_oil_cme' "
        "(the only value); for the USDA ANNUAL palm balance sheet use silver_psd instead. Its su_ratio is a "
        "MONTHLY closing-stocks/exports ratio, distinct from the PSD annual stocks-to-use.\n"
        "- silver_sagis_cec `commodity` is a SAGIS crop code -- total_maize, white_maize, yellow_maize, wheat, "
        "soybeans, sunflower_seed, sorghum, barley, canola, oats, dry_beans, groundnuts -- South Africa ONLY; "
        "`country` selects the reporting scope (total | commercial | developing), so pass country='total' for "
        "the national headline estimate. For an explicitly South-African maize ask, prefer silver_sagis_cec "
        "(the SA national statutory authority) over silver_psd's USDA South-Africa corn estimate.\n"
        "- NO governed US farm-gate price series is live: the WASDE avg_farm_price series is label-dead after "
        "its 2011-08-11 release (source label change; restoration pending), so it is NOT queryable. If asked "
        "for a US farm price, say plainly that the governed series is not yet restored -- NEVER improvise one "
        "from memory, and never present a world benchmark as a farm-gate price without naming the basis "
        "difference.\n"
        "- silver_pink_sheet is the World Bank Pink Sheet of MONTHLY WORLD BENCHMARK price averages in US "
        "dollars: it has NO commodity/country arguments -- the METRIC NAME IS the series (e.g. "
        "palm_oil_cpo_usd_t, soybean_oil_usd_t, urea_usd_mt, brent_crude_usd_bbl). State the month + unit + "
        "'WB monthly average'; these are monthly averages, NOT exchange settles, and world benchmarks, NOT US "
        "farm-gate prices. Its input-cost series (fertilizers, natural gas, Brent) are "
        "relevant context for ANY contract's cost side. It carries NO corn, coffee, cotton, rice or cocoa price "
        "column -- if asked for one, say plainly it is not in the governed price series rather than substituting "
        "a different one.\n"
        "- State prices, premiums, discounts, and spreads as an observed level + date + historical percentile, "
        "in PAST or PRESENT tense. NEVER characterize a level as cheap, rich, or attractive; never forecast that "
        "a spread narrows, normalizes, or corrects; never give timing.\n"
        "- silver_cot is CFTC MANAGED-MONEY positioning (weekly, per contract slug): open_interest, "
        "mm_long/mm_short/mm_net/mm_spread [contracts], mm_pct_oi (SIGNED net percent of OI; negative = net "
        "short), and mm_net_z_3yr / mm_pct_oi_z_3yr (sigma vs a 3-yr mean). Positioning is HISTORICAL CONTEXT "
        "ONLY -- report observed levels + z + the report date in PAST tense; NEVER forecast a squeeze, never "
        "say positioning will unwind or must revert, and never let it drive a price call or a cascade fork. It "
        "is lag-published (about 6 days) and can be several weeks stale, so ALWAYS cite the report date -- "
        "staleness must be visible, not hidden.\n"
        + stats_bullet +
        "- silver_noaa_oni has NO date column: window months with period_start/period_end as 'YYYY-MM', or use "
        "agg=latest for the most recent month on/before the as-of date.\n"
        "- silver_nasa_power is per STATION-REGION: each lookup reads ONE region (defaults to the commodity's "
        "primary growing region, e.g. us_corn_iowa for corn_cbot). The result is that station's value, not a "
        "belt-wide total — state the region when you report the number.\n"
        "- Each returned row is self-identifying (it carries its own period / year / month) — read those to confirm "
        "which observation each number is; results are chronological, so use agg=latest (not the first row) for "
        "the most recent value.\n\n"
        f"## Tables\n{cards}"
    )


def _forced_spec(asof: str, inp: dict) -> Q.NumberQuery:
    """Build a NumberQuery from the model's tool input, FORCING asof (drop any asof the model tried to pass)."""
    data = {k: v for k, v in inp.items() if k != "asof"}
    return Q.NumberQuery(asof=asof, **data)


def answer_numbers(question: str, asof: str, *, client=None, model: str = HAIKU, reg: Optional[NumbersRegistry] = None,
                   query_fn=None, max_calls: int = 6, max_tokens: int = 1500, on_call=None) -> dict:
    """Run the agent loop. `client` = an anthropic.Anthropic (real = billed); `query_fn(sql)->rows` overrides Athena
    (tests). Returns {answer, calls:[{query, rows}]} — calls carry the exact provenance behind every number.
    `on_call(n_calls, table)` (default None = byte-identical) fires after each executed lookup — the SSE
    progress hook (5.6 W5); errors are swallowed."""
    reg = reg or load_registry()
    if client is None:                             # real serving path -> provider-routed + retried
        from leviathan.graphrag import providers as pv
        client = pv.make_client()
        model = pv.resolve_model(model)
    else:
        pv = None                                  # injected fake (tests): no provider, no backoff
    stats_on = _stats_tool_on()
    tools = [tool_schema(reg)] + ([stats_tool_schema()] if stats_on else [])   # kill-switch removes the tool
    system = [{"type": "text", "text": system_prompt(reg, stats_tool=stats_on),
               "cache_control": {"type": "ephemeral"}}]                        # cached; prompt matches the schema
    convo: list[dict] = [{"role": "user", "content": f"As-of date (fixed): {asof}\n\nQuestion: {question}"}]
    calls: list[dict] = []
    # W3.5 turn-scoped handle registry: {handle -> {series, kd, unit}}. A lookup mints a handle the model can
    # feed to compute_stat; the registry lives for THIS turn only, so a cross-turn handle can never resolve.
    handles: dict[str, dict] = {}
    hseq = 0
    # ESR destination-scope honesty guard: detect a named buyer/destination ONCE, up front. Only applied
    # when an ESR lookup actually executes — a destination-worded question that never touches export
    # sales stays byte-identical. None (the common case) is a no-op everywhere below.
    dest = esr_destination_scope(question)
    # Price-coverage decline guard: detect a NONE-tier PRICE ask (no governed pink_sheet column) ONCE, up
    # front. None (the common case) is a no-op everywhere below -- a covered/non-price ask is byte-identical.
    price_scope = price_coverage_scope(question)

    for _ in range(max_calls):
        def _one():
            return client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          tools=tools, messages=convo)
        resp = pv.with_retry(_one) if pv else _one()
        uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not uses:
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
            result: dict = {"answer": text, "calls": calls}
            preface = ""
            if price_scope:
                # deterministic decline of an uncovered price series: the caveat is PREPENDED regardless of
                # what the model wrote, so an uncaveated proxy can never pose as the asked-for series.
                preface += _price_decline_preface(price_scope)
                result["price_decline_guard"] = price_scope
            if dest and any(_is_esr_call(c) for c in calls):
                # deterministic decline of the destination cut: the caveat is PREPENDED regardless of what
                # the model wrote, so an uncaveated national number can never pose as a destination answer.
                preface += _esr_destination_preface(dest)
                result["esr_destination_guard"] = dest
            if preface:
                result["answer"] = (preface + text).strip()
            return result
        convo.append({"role": "assistant", "content": resp.content})

        def _exec(b) -> dict:
            """One tool call -> its payload. Self-contained error taxonomy so a bad lookup never kills the
            loop OR its batch-mates."""
            try:
                spec = _forced_spec(asof, dict(b.input))
                rows = Q.run(spec, query_fn=query_fn)
                # An aggregate over zero matched rows returns ONE row with a NULL value (the July-3 eval's
                # b_weather_2012: country='us' matched no partition, sum() -> [{'value': None}], and the
                # null sailed through as status=ok). Null-valued rows are never usable values.
                vals = [r for r in rows if r.get("value") not in (None, "")]
                if vals:
                    status = "ok"
                else:
                    # "Not yet published at the as-of" is a VINTAGE-ONLY determination (release_date > asof).
                    # For data_date/ingest/year_month tables an empty result means the query matched no data
                    # (filter/scope mismatch or a lake gap) — a different, weaker claim the answer must make
                    # honestly instead of inventing a publication-timing story.
                    try:
                        ksem = reg.get(spec.table).knowledge_semantics if spec.table else ""
                    except KeyError:
                        ksem = ""
                    status = "not_known" if ksem == "vintage" else "no_rows"
                return {"query": spec.model_dump(exclude_none=True), "rows": vals, "status": status}
            except Exception as e:  # noqa: BLE001 — a bad lookup must not kill the loop
                return {"query": dict(b.input), "error": str(e)[:200], "rows": [], "status": "error"}

        def _stamp_scope(payload: dict) -> dict:
            """Destination-scoped ask hitting the destination-blind export-sales table: tell the MODEL the
            value is a national total (defense-in-depth next to the deterministic answer preface — the
            hybrid path consumes calls, not the agent's prose, so the note must ride the payload)."""
            if dest and _is_esr_call(payload):
                payload["scope_note"] = _esr_scope_note(dest)
            return payload

        def _exec_stat(b) -> tuple[dict, list[dict]]:
            """A compute_stat tool call -> (tool_result payload for the model, synthetic [N] calls to inject).
            Enum-locked (STAT_NAMES), turn-scoped handles (an unknown/cross-turn handle is REFUSED), honest
            declines inject nothing. The code COMPUTES; the model only narrates."""
            inp = dict(getattr(b, "input", {}) or {})
            stat = inp.get("stat")
            if stat not in ST.STAT_NAMES:                          # enum fence (belt + the schema enum)
                return ({"stat": stat, "declined": True, "status": "error",
                         "error": f"unknown stat {stat!r}; allowed: {sorted(ST.STAT_NAMES)}"}, [])
            try:
                res = _dispatch_stat(stat, inp, handles)
            except KeyError as ke:                                 # cross-turn / unknown handle -> REFUSE
                return ({"stat": stat, "declined": True, "status": "error",
                         "error": f"unknown handle {ke.args[0]!r} -- handles are turn-scoped; reference a "
                                  f"lookup_number result FROM THIS TURN"}, [])
            except Exception as e:  # noqa: BLE001 — a bad stat request must not kill the loop
                return ({"stat": stat, "declined": True, "status": "error", "error": str(e)[:200]}, [])
            if res.get("declined"):                                # honest decline: no value row minted
                return ({**res, "status": "declined"}, [])
            prov = _stat_provenance(stat, inp, handles)
            sh = handles.get(inp.get("series_handle")) or {}
            injected = _stat_calls(stat, res, prov, sh.get("unit"), sh.get("kd"))
            payload = {**res, "status": "ok", "provenance": prov,
                       "note": "This is now an injected observed figure -- state it with its unit and stay "
                               "descriptive (no forecast/extrapolation)."}
            return (payload, injected)

        # The tool_use blocks within ONE model response are independent LOOKUPS run concurrently at Athena's
        # ~3.5s/query floor (pool.map preserves order so calls/results/ids stay aligned; boto3 is thread-safe).
        # compute_stat calls are instant + pure, and must see the handles that lookups mint -- so lookups run
        # first (concurrently), then the whole batch is assembled in tool_use ORDER, minting a handle per
        # lookup as it lands and dispatching each stat against the handles registered so far.
        lookup_uses = [b for b in uses if getattr(b, "name", TOOL_NAME) == TOOL_NAME]
        payload_by_id: dict[str, dict] = {}
        if len(lookup_uses) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(4, len(lookup_uses))) as pool:
                for b, p in zip(lookup_uses, pool.map(_exec, lookup_uses)):
                    payload_by_id[b.id] = p
        elif lookup_uses:
            payload_by_id[lookup_uses[0].id] = _exec(lookup_uses[0])

        results = []
        for b in uses:
            name = getattr(b, "name", TOOL_NAME)
            if name == STATS_TOOL_NAME and stats_on:
                content, injected = _exec_stat(b)
                for p in injected:
                    calls.append(p)
                if injected:                                       # mint a chaining handle for the stat result
                    hseq += 1
                    h = f"L{hseq}"
                    content["handle"] = h
                    handles[h] = {"series": [v for p in injected for v in _series_from_rows(p["rows"])],
                                  "kd": injected[0]["rows"][0].get("knowledge_date"),
                                  "unit": injected[0]["rows"][0].get("unit")}
            elif name == TOOL_NAME:
                content = _stamp_scope(payload_by_id[b.id])
                calls.append(content)
                hseq += 1                                          # mint the lookup's turn-scoped handle
                h = f"L{hseq}"
                content["handle"] = h
                _rows = content.get("rows") or []
                handles[h] = {"series": _series_from_rows(_rows), "kd": _handle_kd(_rows),
                              "unit": (_rows[0].get("unit") if _rows else None)}
            else:                                                  # unknown tool (or stats off) -> honest error
                content = {"status": "error", "error": f"unknown tool {name!r}"}
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(content)[:6000]})
            if on_call is not None:
                try:
                    on_call(len(calls), (content.get("query") or {}).get("table") or content.get("stat"))
                except Exception:  # noqa: BLE001 — progress reporting can never fail a lookup
                    pass
        convo.append({"role": "user", "content": results})
    return {"answer": "(stopped: max tool calls reached)", "calls": calls}


def to_citations(calls: list[dict], evidence_rows: Optional[list[dict]] = None):
    """Unified Citation objects (numbers + optional document evidence) — the Phase-4 provenance seam that the
    synthesizer/UI consumes. See leviathan.graphrag.citations."""
    from leviathan.graphrag import citations as C
    return C.unify(evidence_rows, calls)


def format_provenance(calls: list[dict]) -> list[str]:
    """One human citation per executed lookup — for the synthesizer / UI."""
    out = []
    for c in calls:
        q = c.get("query", {})
        rows = c.get("rows") or []
        val = (rows[0].get("value") if rows else
               "(lookup error)" if c.get("status") == "error" else
               "(no matching data)" if c.get("status") == "no_rows" else "(not known at asof)")
        kd = rows[0].get("knowledge_date") or rows[0].get("data_date") if rows else ""
        scope = "/".join(str(q.get(k)) for k in ("commodity", "country", "period") if q.get(k))
        out.append(f"{q.get('table')}.{q.get('metric')} {scope} = {val}" + (f" [{kd}]" if kd else ""))
    return out
