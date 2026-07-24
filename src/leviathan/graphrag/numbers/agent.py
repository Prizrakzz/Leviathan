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

from leviathan.graphrag.numbers import pattern_records as PR
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


# ── ESR destination guard DOWNGRADE (ESR_DESTINATION_PLAN W3.4) ────────────────────────────────────────
# Now that silver_esr supports a destination cut (country=<name> -> FAS code IN filter), a NAMED destination
# ask that the model actually SCOPED (passed a country that resolves) is ANSWERED -- the national-total
# decline preface is downgraded to the FALLBACK for the unresolved/national case. A bloc/pseudo code
# (the EU, ...) is served WITH a bloc-aggregate caveat. A destination ask that ran only a NATIONAL ESR
# lookup (no country, or an unresolved name) keeps the honest national-total decline -- byte-identical to
# before for every existing path.
def _esr_call_codes(c: dict) -> Optional[list[str]]:
    """Resolved FAS code(s) for an ESR call's `country`, or None when the call carried no country OR the
    name did not resolve (fail-closed: an unresolved name is treated as NOT destination-scoped)."""
    country = (c.get("query") or {}).get("country")
    if not country:
        return None
    from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations
    codes = load_esr_destinations().resolve_codes(country)
    return codes or None


def _esr_codes_are_bloc(codes: list[str]) -> bool:
    """True if ANY resolved code is a pseudo/bloc/region aggregate (the EU, an FSU residual, ...) -- such a
    scoped read is a bloc aggregate, not a single country, and gets an honest caveat."""
    from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations
    dst = load_esr_destinations()
    return any(dst.is_pseudo(str(c)) for c in codes)


def _esr_bloc_caveat_preface(dest: str) -> str:
    """Reader-facing bloc-aggregate caveat for a scoped read against a bloc/region code (mentor register)."""
    return (f"One note on scope before the number: {dest} is a bloc / regional aggregate in this export-sales "
            f"data, not a single country -- the figure below covers the bloc as reported, and may aggregate "
            f"member destinations.\n\n")


def _esr_bloc_scope_note(dest: str) -> str:
    """Model-facing note on an ESR tool_result scoped to a bloc/region code."""
    return (f"BLOC/REGIONAL AGGREGATE ({dest}) -- this figure is scoped to a bloc/region destination code, not "
            f"a single country; label it as the {dest} bloc aggregate, which may aggregate member destinations.")


# -- ESR destination-BREAKDOWN decline-WITH-aggregate (L3) ---------------------------------------------
# The full-breakdown ask ("give me the destination breakdown of US soybean export sales this year") is
# structurally unsupported -- silver_esr has no wired destination grouping, so a per-buyer GROUP BY cannot
# run. The honest decline of the CUT stands, but declining with ZERO numbers strands the reader when the
# SUPPORTED national aggregate IS available. So the generic-breakdown path ALSO issues the two aggregate
# reads the tool already supports -- the marketing-year total export sales and the prior-marketing-year
# same-metric read (the pace-vs-prior-year comparison) -- and serves them WITH real [N] handles minted
# through the normal lookup path (so the deterministic citation verifier accepts them). A named single
# destination (dest != _ESR_DEST_GENERIC) is UNTOUCHED by all of this -- it keeps the plain preface path.
_ESR_METRICS = ("weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt",
                "changes_1000mt")


def _fmt_esr_num(v) -> Optional[str]:
    """A row value -> a reader magnitude string whose numeric matches the row within the verifier's 1%
    tolerance (comma-grouped integer when near-whole, else one decimal). None on an unparseable value."""
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if abs(f - round(f)) < 0.05:
        return f"{int(round(f)):,}"
    return f"{f:,.1f}"


def _esr_aggregate_legs(esr_query: dict, asof: str, query_fn) -> list[dict]:
    """The two SUPPORTED aggregate ESR reads for the generic destination-breakdown decline: total
    marketing-year export sales (agg=sum over the MY, across all destinations) and the prior-MY
    same-metric read (the pace-vs-prior-year comparison the tool already supports). Commodity + metric +
    marketing year are derived from the ESR lookup the model already ran (a missing/odd period falls back
    to the as-of calendar year; an unrecognized metric falls back to gross_new_sales). Each leg runs
    through the normal query path so its rows carry real provenance. A leg that errors (e.g. no commodity
    to scope the partition) or yields no value is DROPPED -- never fabricated -- so [] means fall back to
    the plain preface decline."""
    commodity = esr_query.get("commodity")
    metric = esr_query.get("metric")
    if metric not in _ESR_METRICS:
        metric = "gross_new_sales_1000mt"
    period = esr_query.get("period")
    try:
        cur_my = int(str(period)[:4]) if period else int(asof[:4])
    except (TypeError, ValueError):
        cur_my = int(asof[:4])
    legs: list[dict] = []
    for my, span in ((cur_my, "current"), (cur_my - 1, "prior")):
        inp = {"table": "silver_esr", "metric": metric, "agg": "sum", "period": str(my)}
        if commodity:
            inp["commodity"] = commodity
        try:
            spec = _forced_spec(asof, inp)
            rows = Q.run(spec, query_fn=query_fn)
        except Exception:  # noqa: BLE001 -- a failed aggregate leg is dropped, not fatal
            continue
        vals = [r for r in rows if r.get("value") not in (None, "")]
        if not vals:
            continue
        legs.append({"query": spec.model_dump(exclude_none=True), "rows": vals, "status": "ok",
                     "esr_pace_span": span})
    return legs


def _esr_aggregate_answer(indexed_legs: list[tuple[int, dict]]) -> Optional[str]:
    """Build the reader-facing decline-WITH-aggregate answer from the aggregate legs and their 1-based [N]
    positions in the calls list. Register-clean, decline-template voice (no mood/valuation words). Returns
    None if neither leg carried a usable magnitude (caller falls back to the plain preface)."""
    by_span = {leg.get("esr_pace_span"): (idx, leg) for idx, leg in indexed_legs}
    cur = by_span.get("current")
    prior = by_span.get("prior")
    cur_num = _fmt_esr_num(cur[1]["rows"][0].get("value")) if cur else None
    if not cur_num:
        return None
    # honesty one-liner (same register as the generic preface: national-only, no per-buyer cut)
    lines = [_esr_destination_preface(_ESR_DEST_GENERIC).strip(),
             f"What I can give you at the national level: total US export sales so far in the marketing "
             f"year were {cur_num} thousand MT [N{cur[0]}]"]
    prior_num = _fmt_esr_num(prior[1]["rows"][0].get("value")) if prior else None
    if prior_num:
        lines[-1] += f", versus {prior_num} thousand MT for the prior marketing year [N{prior[0]}]"
    lines[-1] += " (both are US-wide totals across all buyers)."
    # single-destination capability, offered explicitly
    lines.append("If you have one destination in mind, ask a specific destination, e.g. China, and I'll "
                 "pull the closest supported read with the same national-total caveat noted.")
    return "\n\n".join(lines)


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
    # These three decline a specific EXCHANGE/origin maize series with no governed column. They intentionally do
    # NOT redirect to the (now A3-restored) US WASDE farm price: a MATIF/JSE origin is separated from the US
    # farm-gate figure by currency, freight and quality basis, so naming it as the "nearest proxy" would still
    # mislead. (The config_check R5b census _check_decline_no_dead_metric no longer applies once avg_farm_price
    # is whitelisted; leaving these origin-honest keeps the decline register-clean either way.)
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
    # A3 (2026-07-22): the us_farm_price template is RETIRED. The WASDE US season-average farm price
    # (avg_farm_price) is re-whitelisted and live (silver_wasde rebuilt + promoted), so a US farm-price ask is
    # now SERVED through the numbers lookup, not declined. Its _PRICE_DECLINE_PATTERNS entry is retired too.
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
    # A3 (2026-07-22): the ("us_farm_price", farm-gate/farm-price regex) entry is RETIRED. avg_farm_price is
    # re-whitelisted and live, so a US farm-price ask is SERVED by the numbers lookup -- price_coverage_scope
    # must return None for it (a match here would keep force-declining a now-live series, independent of the
    # registry). No governed pink_sheet series is a "farm price", so nothing else is shadowed by the removal.
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


# -- SEAM C futures-lite LEVELS-ONLY decline guard (ENGINE SEAMS rev-52) --------------------------------
# silver_futures_prices serves a DAILY continuous FRONT-MONTH close (Yahoo quote). It is a roll-spliced series with no
# true vintage, so the ONLY point-in-time-safe read is a single-date agg=latest LEVEL. Four ask classes are
# structurally unservable from it and must decline with an honest, register-clean template rather than let
# the model narrate a change/curve/named-contract number off a splice-contaminated series:
#   * change  -- "how much has corn risen this month" (a windowed move; the roll handoff sits inside it)
#   * curve   -- term structure / calendar carry / contango-backwardation (needs the expiry-by-expiry curve)
#   * named   -- "December corn" (a specific delivery month; only the continuous front-month is served)
# Cloning the ESR/price guard discipline: a FUTURES-covered commodity NAME must co-occur with an explicit
# CLASS cue; ambiguity fails toward None so a plain LEVEL ask ("corn front-month settle on <date>") is
# byte-identical (no preface). The templates below are censused by config_check.check_futures_lite (each
# must pass register_leaks clean) and the keys EXACTLY match _FUTURES_DECLINE_CLASSES. The guard fires on
# PHRASING alone (independent of whether the table is whitelisted), so the honest front-month framing is
# prepended even while the table is whitelist-absent.
FUTURES_DECLINE_TEMPLATES: dict[str, str] = {
    "change": ("the daily futures data I can pull here is the continuous front-month close (a Yahoo "
               "quote) as a point-in-time level, not a windowed move -- it is a roll-spliced series, so a "
               "change measured across dates is not a clean read from it (the handoff between expiries sits "
               "inside the series); I can give the front-month close level on a date, but not how far it "
               "travelled over a period"),
    "curve": ("the daily futures data I can pull here is the continuous FRONT-MONTH close only, not the "
              "term structure -- the curve across delivery months (and the carry between them) needs the "
              "expiry-by-expiry data, which is not in this lookup; I can give the front-month close level on "
              "a date, not a curve read"),
    "named": ("the daily futures data I can pull here is the continuous FRONT-MONTH close only, not "
              "individual delivery months -- a specific expiry (say, December) needs the full "
              "expiry-by-expiry curve, which is not in this lookup; I can give the front-month close level "
              "on a date, not a named-contract quote"),
}
_FUTURES_DECLINE_CLASSES: tuple[str, ...] = ("change", "curve", "named")

# FUTURES-covered commodity surface forms (the 12 contracts a desk names in prose). Longest-first at
# compile so 'soybean oil' wins over 'soybean'. Deliberately broad on the bare head words (wheat/sugar/
# coffee/rice/cotton/cocoa) because the CLASS cue -- not the name -- is what makes an ask futures-specific.
_FUTURES_COMMODITY_TERMS: tuple[str, ...] = (
    "soybean oil", "soybean meal", "soy oil", "soy meal", "soyoil", "soymeal", "bean oil", "bean meal",
    "orange juice", "fcoj", "rough rice", "kc wheat", "kcbt wheat", "hrw wheat", "srw wheat",
    "kansas city wheat", "chicago wheat", "hard red winter wheat", "soft red winter wheat",
    "soybeans", "soybean", "corn", "wheat", "cotton", "sugar", "coffee", "cocoa", "rice")
_FUT_COMMODITY_ALT = "|".join(re.escape(t) for t in sorted(_FUTURES_COMMODITY_TERMS, key=len, reverse=True))
_FUT_COMMODITY = re.compile(r"\b(?:" + _FUT_COMMODITY_ALT + r")\b")

# Volume/fundamental subjects: a change ask ABOUT one of these is NOT a futures-price ask -> fail toward None.
_FUT_VOLUME_NOUN = re.compile(
    r"\b(production|output|acreage|area|planting|yield|harvest|exports?|imports?|shipments?|sales?|demand|"
    r"supply|stocks?|inventor\w+|use|usage|consumption|crush|grind\w*|deliver\w+)\b")

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|march|april|june|july|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|"
          r"nov(?:ember)?|dec(?:ember)?)")   # 'may'/'mar' dropped bare: too homonym-prone; require adjacency below
_FUT_NAMED_PATTERNS = [
    # a delivery month ADJACENT to a futures commodity: "December corn", "corn (for) December",
    # "the December wheat contract", "March soybean futures".
    re.compile(rf"\b{_MONTH}\s+(?:{_FUT_COMMODITY_ALT})\b"),
    re.compile(rf"\b(?:{_FUT_COMMODITY_ALT})\s+(?:for\s+|contract\s+)?{_MONTH}\b"),
    re.compile(rf"\bthe\s+{_MONTH}\s+(?:contract|future|futures|delivery|expiry|expiration)\b"),
    # explicit named-contract vocabulary (needs a futures commodity present, checked separately).
    re.compile(r"\b(?:named contract|specific (?:delivery )?month|specific expir\w+|particular (?:month|expir\w+)|"
               r"which (?:delivery )?month|which contract|what (?:delivery )?month|what expir\w+|"
               r"nearby (?:vs\.?|versus) deferred|back month\w*|deferred (?:month|contract)\w*)\b"),
]
_FUT_CURVE_PATTERNS = [
    re.compile(r"\b(?:term structure|forward curve|futures curve|the curve|price curve|calendar spread\w*|"
               r"contango|backwardation|roll yield|carry between|front[- ]?month (?:vs\.?|versus)|"
               r"nearby (?:vs\.?|versus))\b"),
]
_FUT_CHANGE_VERB = re.compile(
    r"\b(?:risen|rose|rising|rallied|rally|gained|gaining|climbed|climbing|jumped|surged|advanced|"
    r"fallen|fell|falling|dropped|dropping|declined|slid|slipped|sank|plunged|tumbled|retreated|"
    r"moved|move|changed|gone up|gone down|up|down|higher|lower)\b")
_FUT_WINDOW = re.compile(
    r"\b(?:this (?:week|month|quarter|year|session)|ytd|year[- ]to[- ]date|week[- ]to[- ]date|"
    r"month[- ]to[- ]date|today|so far this|over the (?:past|last)|in the (?:past|last)|(?:past|last) "
    r"(?:week|month|quarter|year|few (?:days|weeks|months))|lately|recently|intraday|since \w+|"
    r"year[- ]?on[- ]?year|from a (?:week|month|year) ago)\b")


def futures_scope(question: str) -> Optional[str]:
    """The FUTURES levels-only decline class when the question is UNAMBIGUOUSLY a change / curve / named-
    contract futures ask (a futures-covered commodity name co-occurring with the class cue), else None.
    Ambiguity fails toward None so a plain single-date LEVEL ask is byte-identical (no decline). Priority:
    named-contract, then curve, then change -- a specific-expiry framing is the strongest signal."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    if not _FUT_COMMODITY.search(q):
        return None                                            # no futures commodity named -> never fire
    # named-contract: the month-adjacency patterns already bind a commodity; the explicit-vocabulary
    # pattern (index 3) needs a commodity present (guaranteed above).
    for rx in _FUT_NAMED_PATTERNS:
        if rx.search(q):
            return "named"
    for rx in _FUT_CURVE_PATTERNS:
        if rx.search(q):
            return "curve"
    # change: a directional-move verb WITH a time window, and NOT a volume/fundamental subject (a
    # production/exports/stocks "rose this month" ask is a fundamentals question, not a futures-price one).
    if _FUT_CHANGE_VERB.search(q) and _FUT_WINDOW.search(q) and not _FUT_VOLUME_NOUN.search(q):
        return "change"
    return None


def _futures_decline_preface(cls: str) -> str:
    """Reader-facing honest decline of an unservable futures ask class (mentor register -- no internal
    slugs). PREPENDED deterministically so a change/curve/named-contract read can never pose as served."""
    return f"One limitation to flag before the numbers: {FUTURES_DECLINE_TEMPLATES[cls]}.\n\n"


def _visible_tables(reg: NumbersRegistry) -> list[str]:
    """The registry tables EXPOSED to the agent this call: sorted(reg.tables), MINUS the flag-gated
    pattern-records card when GRAPHRAG_PATTERN_RECORDS is OFF. Read per-call so the kill-switch rollback is
    live; when off the returned list is BYTE-IDENTICAL to the pre-feature sorted(reg.tables) (the card is
    the only new table), so tool_schema + system_prompt are unchanged (plan 7.6 identical-answers smoke)."""
    tables = sorted(reg.tables)
    if PR.PR_TABLE in tables and not PR.pattern_records_on():
        tables = [t for t in tables if t != PR.PR_TABLE]
    return tables


def tool_schema(reg: NumbersRegistry) -> dict:
    """The single tool. `table` is an enum over the registry; asof is DELIBERATELY absent (the harness forces it)."""
    return {
        "name": TOOL_NAME,
        "description": "Look up one observed number (or aggregate) from the point-in-time data lake. "
                       "Always returns values as-known at the fixed as-of date; you cannot change that date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": _visible_tables(reg), "description": "which table"},
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
    visible = _visible_tables(reg)                         # pattern-records card filtered out when flag OFF
    cards = "\n\n".join(_table_card(reg.get(t)) for t in visible)
    # T2B: the observation-register bullet ships ONLY when the gold_pattern_records card is visible (flag on),
    # so with the flag off the ## Conventions block is byte-identical to pre-feature (kill-switch parity --
    # the model is never told about a table it does not have).
    pattern_bullet = PR.AGENT_CONVENTIONS_BULLET if PR.PR_TABLE in visible else ""
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
        "- The USDA WASDE season-average farm price is LIVE as silver_wasde.avg_farm_price: pass the base "
        "commodity (corn, wheat, sorghum, oats, barley, rice, cotton, soybeans) with country='united_states' "
        "and the marketing year as period '2023/24'. Units are per-commodity (corn/wheat/sorghum/oats/barley "
        "$/bu, rice $/cwt, cotton c/lb, soybeans $/bu) and returned on each row. soybean_oil (c/lb) and "
        "soybean_meal ($/s.t.) are US MARKET prices quoted at Decatur, NOT farm-gate -- say so when you cite "
        "them. Current- and future-MY values are USDA PROJECTIONS: attribute them by revision_stamp (actual / "
        "estimate / projection), never as our own forecast, and never present a world benchmark as a farm-gate "
        "price.\n"
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
        + stats_bullet + pattern_bullet +
        "- silver_noaa_oni has NO date column: window months with period_start/period_end as 'YYYY-MM', or use "
        "agg=latest for the most recent month on/before the as-of date.\n"
        "- silver_noaa_iod is the Indian Ocean Dipole (DMI), a GLOBAL monthly climate index -- NO commodity or "
        "country argument. Window months with period_start/period_end as 'YYYY-MM', or agg=latest for the most "
        "recent month on/before the as-of date. Report the DMI (or its 3-month average) in degC + the month. It "
        "is a lagging SST reconstruction whose latest available month can trail the as-of date by many months, "
        "so ALWAYS cite the reading's month and make its age explicit -- staleness must be visible, not hidden; "
        "an agg=latest reading that is months old is stated as such, NEVER as 'the current DMI'. Positive DMI is "
        "the East-Africa/Australia teleconnection. It is an observed climate index, never a price and never a "
        "crop-impact forecast.\n"
        "- silver_conab_coffee is CONAB's Brazilian coffee production surveys (arabica / robusta), survey-"
        "vintage, Brazil only. Pass commodity=arabica_coffee|robusta_coffee and region='brazil' (via the "
        "country field) for the national headline; period = safra_year integer. It reports the latest survey's "
        "production/area/yield as-known at the as-of date -- it does NOT report survey-over-survey revisions "
        "(those are deltas, not levels). For the USDA global coffee balance sheet use silver_psd.\n"
        "- silver_sagis_weekly_exports is SAGIS South-African WEEKLY cumulative grain export PACE, crop = maize "
        "| wheat. prog_exports_mt is season-to-date (CUMULATIVE, running total) in MT -- never delta it against "
        "a weekly ESR flow; pct_of_prior_yr and z_vs_3yr_avg are the producer's pre-computed (no-lookahead) pace-"
        "vs-history, served as stored, never recomputed. agg=latest for the newest week, or window on the week-"
        "ending date with period_start/period_end 'YYYY-MM-DD'. It is a national crop total -- no per-destination "
        "or per-grade cut; if asked for one, say the series is national-total only, never invent a breakdown. It "
        "is a weekly cumulative pace posted a few days after each week's end and can run several weeks stale, so "
        "ALWAYS cite the week-ending date -- staleness must be visible, not hidden. Report the observed cumulative "
        "tonnage / percent / z + the week; NEVER call ahead-of-pace 'bullish' and never forecast the gap closes. "
        "Distinct from US ESR weekly SALES and from SAGIS/CEC production estimates (silver_sagis_cec).\n"
        "- silver_esr supports a DESTINATION cut: for a buyer-scoped ask ('corn sales to China') pass the "
        "destination as `country` (e.g. country='China') to get that destination's export sales; OMIT country "
        "for the US national total across all buyers. Label the figure as that destination (or as the US-wide "
        "total when unscoped); the EU and other blocs are bloc aggregates. An unrecognised destination returns "
        "no rows -- say the figure is unavailable, never present a national total as that destination.\n"
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
    # SEAM-C futures levels-only decline guard: detect a change / curve / named-contract futures ask ONCE, up
    # front. None (the common case) is a no-op -- a plain single-date LEVEL ask is byte-identical. Fires on
    # phrasing alone, so the honest front-month framing is prepended even while futures is whitelist-absent.
    fut_scope = futures_scope(question)
    # T2B pattern-records persistence-history dispatch: detect a persistence question ONCE, up front, and
    # ONLY when the card flag is on -> flag-off never even computes the scope, so the loop is byte-identical
    # to pre-feature. None (the common case, and always when off) is a no-op everywhere below.
    pr_scope = PR.pattern_records_scope(question, contracts=None) if PR.pattern_records_on() else None

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
            if fut_scope:
                # SEAM-C: deterministic decline of an unservable futures ask class (change/curve/named): the
                # front-month-only caveat is PREPENDED regardless of what the model wrote, so a change/curve/
                # named-contract read can never pose as served off the roll-spliced series.
                preface += _futures_decline_preface(fut_scope)
                result["futures_decline_guard"] = fut_scope
            if dest and any(_is_esr_call(c) for c in calls):
                result["esr_destination_guard"] = dest
                if dest == _ESR_DEST_GENERIC:
                    # decline-WITH-aggregate: the per-destination cut is unsupported, but the SUPPORTED
                    # national aggregate (MY total + prior-MY pace) IS served, with real [N] handles minted
                    # through the normal lookup path so the citation verifier accepts them. This REPLACES
                    # the model's prose (which declines to zero numbers) with a deterministic answer.
                    esr_q = next((c.get("query") or {} for c in calls if _is_esr_call(c)), {})
                    legs = _esr_aggregate_legs(esr_q, asof, query_fn)
                    indexed: list[tuple[int, dict]] = []
                    for leg in legs:
                        calls.append(leg)                          # real provenance appended in call order
                        hseq += 1
                        h = f"L{hseq}"
                        leg["handle"] = h
                        _lrows = leg.get("rows") or []
                        handles[h] = {"series": _series_from_rows(_lrows), "kd": _handle_kd(_lrows),
                                      "unit": (_lrows[0].get("unit") if _lrows else None)}
                        indexed.append((len(calls), leg))           # 1-based [N] position in the calls list
                    agg = _esr_aggregate_answer(indexed) if indexed else None
                    if agg:
                        result["answer"] = agg
                        result["esr_aggregate_legs"] = len(indexed)
                        return result
                    # generic breakdown with no available aggregate: the plain national-total decline stands.
                    preface += _esr_destination_preface(dest)
                else:
                    # NAMED destination -- ESR_DESTINATION_PLAN W3.4 DOWNGRADE. If an ESR lookup was actually
                    # SCOPED to the destination (the model passed a country that resolved to a code), the
                    # destination IS served: no national-total decline. A bloc/pseudo code gets a bloc caveat
                    # instead. Only a NATIONAL ESR lookup for the destination ask (no country, or an
                    # unresolved name) keeps the honest national-total decline (byte-identical to before).
                    scoped_call = next((c for c in calls if _is_esr_call(c) and _esr_call_codes(c)), None)
                    if scoped_call is not None:
                        result["esr_destination_served"] = dest
                        # The bloc caveat asserts "the figure below covers the bloc", so it may only ride an ESR
                        # read that ACTUALLY RETURNED a figure. The one bloc in the detection vocabulary is the
                        # EU (code 1), which silver_esr does NOT carry (esr_destinations W0 audit: EU-27 absent
                        # from the data), so a "sales to the EU" ask resolves to code 1 -> IN ('1') -> ZERO rows;
                        # prefacing that empty result with "the figure below covers the bloc" is self-
                        # contradictory. Gate the caveat on rows-returned -> an empty bloc read falls through to
                        # the model's honest no-data narration; a bloc code that DID return rows still gets it.
                        if (scoped_call.get("rows") or []) and _esr_codes_are_bloc(_esr_call_codes(scoped_call) or []):
                            preface += _esr_bloc_caveat_preface(dest)
                    else:
                        preface += _esr_destination_preface(dest)
            if pr_scope:
                # T2B: inject the ledger presence / backfill-base-rate leg as a real [N] handle (the ESR
                # aggregate-leg idiom) and PREPEND the OBSERVATION-register line. The scalar-presence query
                # ALWAYS returns a row (a materialized 0 when a pair has no recorded firing, F8), so the
                # empty-ledger honesty answer cites an injected 0 rather than falling back to a minted streak.
                pr_legs, pr_signal = PR.pattern_records_legs(pr_scope, asof, query_fn)
                indexed_pr = None
                for leg in pr_legs:
                    calls.append(leg)
                    hseq += 1
                    h = f"L{hseq}"
                    leg["handle"] = h
                    _prrows = leg.get("rows") or []
                    handles[h] = {"series": _series_from_rows(_prrows), "kd": _handle_kd(_prrows),
                                  "unit": None}
                    indexed_pr = (len(calls), leg)
                pr_line = PR.pattern_records_answer(pr_scope, indexed_pr, pr_signal)
                if pr_line:
                    preface += pr_line + "\n\n"
                result["pattern_records"] = pr_signal          # surfaced to out['trace'] by run_numbers_only
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
                codes = _esr_call_codes(payload)
                if not codes:                              # national lookup for a destination ask -> national caveat
                    payload["scope_note"] = _esr_scope_note(dest)
                elif _esr_codes_are_bloc(codes) and (payload.get("rows") or []):
                    # scoped to a bloc/region code that RETURNED a figure -> bloc-aggregate note. Gated on rows:
                    # an empty bloc read (e.g. the EU, absent from silver_esr) carries no figure to label as a
                    # bloc aggregate, so the model just narrates the no_rows result honestly.
                    payload["scope_note"] = _esr_bloc_scope_note(dest)
                # scoped to a real single country -> NO scope_note (the value IS that destination's)
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
