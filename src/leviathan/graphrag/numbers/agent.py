"""Numbers SQL agent — the LLM that turns a question into typed NumberQuery lookups (Phase 3).

The model NEVER writes SQL and NEVER chooses the as-of date. It's given the registry (a cached system prompt)
and one tool, ``lookup_number``, whose schema mirrors NumberQuery MINUS asof. The agent fills table/metric/
scope; the loop injects the caller's fixed ``asof`` and runs it through the deterministic leakage-safe builder.
So point-in-time correctness is a property of the harness, not of prompt discipline — the agent literally has no
lever to see the future. Returns the model's answer plus the exact (query, rows) provenance behind every number.
"""
from __future__ import annotations

import datetime as _dt
import functools
import json
import os
import re
from typing import Optional

from leviathan.graphrag import params as _pr
from leviathan.graphrag.numbers import pattern_records as PR
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import stats as ST
from leviathan.graphrag.numbers.registry import NumbersRegistry, TableSpec, load_registry
from leviathan.graphrag.numbers.registry import (
    visible_tables as _visible,  # D-CW-1d: ONE visibility rule
)

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


# -- D-PQ EMPTY-1: AN EMPTY READ IS AN ABSENCE OF DATA, NEVER A MEASURED ZERO -------------------------
#
# THE MEASURED FAILURE (dcw_probe_v1 row `dcw_esr_china_corn`, 2026-08-07). One export-sales lookup, one
# collapsed aggregate row, and the shipped answer read: "China has bought **0.0 thousand MT (0 MT) of corn**
# out of the US during marketing year 2025/26 ... This represents no actual shipments of US corn to China
# so far this marketing year." A quantity was asserted as fact and then EDITORIALISED into a market claim.
#
# TWO SEPARATE HAZARDS, TWO SEPARATE NOTES, because they are genuinely different failures:
#   (1) THE EMPTY READ. `_exec` already classifies zero usable rows (no_rows / not_known), and the citation
#       label already says so -- but nothing on the payload the MODEL reads forbids stating a figure for it,
#       and "no rows" is one short inferential step from "the quantity is zero". `_NO_ROWS_NOTE` closes that
#       step by name. Deterministic: it is keyed on `not vals`, which is a property of the result set.
#   (2) THE ZERO AGGREGATE. `_agg` compiles `SELECT sum(value) ... ` and collapses every extra away, so a
#       window with no reported weeks and a window whose weeks all reported zero arrive as the SAME single
#       unlabelled row. On this table those two states are not the same fact and the second is not a
#       purchase claim. Fenced to silver_esr, to agg='sum' and to the UNSIGNED metrics on purpose: a 0.0
#       z-score, a 0 basis, a 0 change on any other card is a real observation and must not be caveated --
#       and neither is a signed ESR net change that cancelled to zero (see `_ESR_UNSIGNED_METRICS`).
_NO_ROWS_NOTE = (
    "NO ROWS RETURNED ({why}): this lookup produced no value at all. State plainly that the record "
    "carries no figure for this scope and do NOT assert any number for it -- not a level, not a change, "
    "and NOT zero. An empty read is an absence of data, never a measured value of 0.")
_NO_ROWS_WHY = {"no_rows": "scope/coverage gap, not a timing claim",
                "record_silent": "scope/coverage gap, not a timing claim",
                "not_known": "not yet published at this as-of",
                "future_unpublished": "not yet published at this as-of",
                "error": "the lookup failed"}
_ESR_ZERO_AGG_NOTE = (
    "The export-sales aggregate above summed to EXACTLY 0 over the requested window. On this table a zero "
    "sum is produced equally by weeks that reported zero and by a window that carries no reported weeks at "
    "all -- the aggregate collapses the week rows, so the two are indistinguishable from this result. Say "
    "the record shows no reported {metric} for that scope and stop there: do NOT state it as a measured "
    "quantity of zero, and do NOT characterise it as 'no purchases', 'no shipments' or 'nothing bought'.")


def _no_rows_note(status: str) -> str:
    return _NO_ROWS_NOTE.format(why=_NO_ROWS_WHY.get(str(status or ""), "no value was returned"))


# THE SIGNEDNESS + AGG FENCE (cycle-3 review). `_exec` drops NULL-valued rows BEFORE this check runs, so
# a 0.0 that reaches it ALWAYS means real week rows summed to exactly zero -- the "no reported weeks at
# all" half of the ambiguity arrives as a NULL and is already routed to `_NO_ROWS_NOTE`. Two consequences,
# and they narrow the caveat rather than widen it:
#   * agg='sum' ONLY. mean/max/min are not the collapse the note describes -- a mean of 0, a max of 0, a
#     min of 0 are real observations OF THE ROWS THAT CAME BACK, and telling the model there is "no
#     reported figure" for them is false.
#   * UNSIGNED METRICS ONLY. `changes_1000mt` is the card's own "net change in outstanding sales": it is
#     SIGNED, and a busy window whose bookings and cancellations offset sums to exactly 0. That is a
#     measured net of zero, not an absence, and caveating it would delete a true reading. The remaining
#     three ESR metrics are quantities that cannot go negative, so a zero sum there is still the
#     indistinguishable state the note is about.
# The card (`numbers/tables.yaml`, silver_esr `metrics:`) carries unit and description but expresses no
# signedness, so the unsigned set is named HERE, beside the rule that reads it, with the card's metric ids.
_ESR_UNSIGNED_METRICS = ("weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt")


def _is_zero_esr_aggregate(payload: dict) -> bool:
    """A silver_esr UNSIGNED-metric SUM that came back as a single row valued exactly 0 (hazard (2))."""
    q = (payload or {}).get("query") or {}
    if q.get("table") != "silver_esr" or str(q.get("agg") or "") != "sum":
        return False
    if str(q.get("metric") or "") not in _ESR_UNSIGNED_METRICS:
        return False
    rows = (payload or {}).get("rows") or []
    if len(rows) != 1:
        return False
    try:
        return float(str((rows[0] or {}).get("value")).replace(",", "")) == 0.0
    except (TypeError, ValueError):
        return False


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


def _esr_aggregate_legs(esr_query: dict, asof: str, query_fn, *,
                        futures_newest_first: bool | str = False) -> list[dict]:
    """The two SUPPORTED aggregate ESR reads for the generic destination-breakdown decline: total
    marketing-year export sales (agg=sum over the MY, across all destinations) and the prior-MY
    same-metric read (the pace-vs-prior-year comparison the tool already supports). Commodity + metric +
    marketing year are derived from the ESR lookup the model already ran (a missing/odd period falls back
    to the as-of calendar year; an unrecognized metric falls back to gross_new_sales). Each leg runs
    through the normal query path so its rows carry real provenance. A leg that errors (e.g. no commodity
    to scope the partition) or yields no value is DROPPED -- never fabricated -- so [] means fall back to
    the plain preface decline.

    `futures_newest_first` is the FUTURES_READPATH S1 canary (D-FR-10), threaded from
    `answer._futures_newest_first_on()` via answer_numbers -- NEVER an os.environ read here. Both legs
    below are agg='sum' on silver_esr, so `_newest_first_applies` is False for either spec whatever the
    flag says; it is threaded anyway because these are Q.run calls on the numbers lane and the doctrine
    is that the seam reaches every one of them, not only the ones that can move today."""
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
            rows = Q.run(spec, query_fn=query_fn, futures_newest_first=futures_newest_first)
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

# -- U2: the compute_stat GUARD templates, REGISTERED so they are linted rather than trusted -----------
# These are the model-facing reason strings the two-handle stat guard hands back (see _dispatch_stat).
# They are NOT SEAM-C classes and must never enter FUTURES_DECLINE_TEMPLATES: that dict's keys are bound
# equal to _FUTURES_DECLINE_CLASSES by config_check AND by test_futures_lite, and every one of its
# templates must contain "front-month" -- neither is true of a unit-compatibility refusal.
#
# WHY A DICT AND NOT AN f-STRING AT THE CALL SITE (D-FR-14 exit (1)): an arbitrary string built inside
# _dispatch_stat is enumerated by NOTHING. config_check's futures_lite census iterates
# FUTURES_DECLINE_TEMPLATES by name, and the C2 census iterates question SHAPES; a call-site f-string is
# in neither, so a register leak in prose the model then narrates would be invisible to a green
# config_check. Declared here, ONE census line covers it by construction.
#
# HANDOFF, STATED SO IT IS NOT DISCOVERED: the census line itself lives in
# src/leviathan/graphrag/config_check.py (beside the FUTURES_DECLINE_TEMPLATES loop at check_futures_lite)
# and is OUT of this lane's files. Until it lands, these strings are linted by the pins in
# tests/unit/test_numbers_stats.py ONLY, and 6.1's "config_check full run" row does not yet count as U2
# evidence. The strings are held to the same bar the futures templates are: register_leaks / exec_leaks /
# count_valuation_words / count_flow_words clean under BOTH registers, sanitize()-stable, and never the
# word "settle".
STAT_DECLINE_TEMPLATES: dict[str, str] = {
    "unit_mismatch": ST.UNIT_MISMATCH_DECLINE,
    "unit_unknown": ST.UNIT_UNKNOWN_DECLINE,
    "empty_series": ST.EMPTY_SERIES_DECLINE,
}
# The trace key U3 puts on answer_numbers' return when the unit guard fires. Named once so the engine,
# the tests and (when it is wired) the orchestrator's fixed key tuple cannot drift.
UNIT_MISMATCH_TRACE_KEY = "unit_mismatch_guard"

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


# -- SEAM C on the HYBRID lane: the same decline where the agent's prose is thrown away (task #144) -----
# The preface above lands in THIS function's return dict -- which is exactly what run_hybrid discards: that
# path consumes `calls`, never `answer` (the _stamp_scope precedent above). So a curve/named futures ask
# that routed hybrid reached the reasoner as a bare front-month LEVEL and was narrated as the asked-for
# quote (newcap-30 ncap_fut_corn_curve_decline: 449.5 served for "December corn ... and the curve"). Only
# the two STRUCTURALLY unservable classes are neutered here: no agg, no date and no window makes a term
# structure or a specific expiry appear in a continuous front-month series, so the level is not a partial
# answer -- it is a different number wearing the ask's label. `change` is DELIBERATELY excluded: there the
# level IS the partial serve the template itself offers ("I can give the front-month close level on a date,
# but not how far it travelled"), and the levels_only build_sql guard already rejects the windowed read.
FUTURES_TABLE = "silver_futures_prices"
FUTURES_UNSERVABLE_CLASSES: frozenset[str] = frozenset({"curve", "named"})


def futures_hybrid_decline(cls: Optional[str], calls: list[dict]) -> tuple[list[dict], str]:
    """(calls, preface) for the hybrid lane. A curve/named ask has every EXECUTED futures lookup NEUTERED --
    rows dropped, status 'declined', the verbatim class template stamped as the scope_note the synthesis
    prompt states -- so no front-month level can be minted, prompted or cited as the curve/named quote; the
    preface rides back for a deterministic prepend (never prompt discipline). Every other class (None and
    the servable 'change'/level asks) returns the SAME list object and an empty preface: byte-identical."""
    if cls not in FUTURES_UNSERVABLE_CLASSES or futures_eod_served(calls):
        return calls, ""
    note = FUTURES_DECLINE_TEMPLATES[cls]
    out: list[dict] = []
    for c in (calls or []):
        # A COVERAGE-ROUTED call is EXEMPT (2026-07-31). The W3.2 guard REWRITES a pre-coverage
        # per-expiry ask into a continuous LEVEL -- whose table is silver_futures_prices, exactly what
        # this loop neuters. On a curve/named-phrased pre-coverage ask the two collided: the rewritten
        # level was dropped, its status flipped to 'declined', and its scope_note (the coverage
        # provenance sentence the reader NEEDS -- "from the roll-spliced continuous series; a
        # per-contract curve does not exist before <floor>") was OVERWRITTEN with the SEAM-C template.
        # run_hybrid then prepended "the figure below is from the roll-spliced continuous series" to an
        # answer with no figure below it. The neuter's #144 intent is intact: it exists so no BARE
        # front-month level is minted for a curve ask, and a coverage-routed level is not bare -- it is
        # labelled, provenance-carrying, and IS the legacy route's whole point. The SEAM-C preface still
        # rides back, so the reader keeps the honest "this is the continuous front month" framing.
        if isinstance(c, dict) and not c.get("coverage_route") \
                and ((c.get("query") or {}).get("table")) == FUTURES_TABLE:
            out.append({**c, "rows": [], "status": "declined", "scope_note": note})
        else:
            out.append(c)
    return out, _futures_decline_preface(cls)


# -- W3.2 COVERAGE-AWARE ROUTING for the per-delivery-month EOD table -----------------------------------
# silver_futures_eod was whitelisted 2026-07-30, and a whitelisted table answers whatever window it is
# handed -- including one that begins BEFORE its first per-contract row exists. This is the guard that
# makes the flip safe. The measured floors live in ONE place (leviathan.silver.futures_eod_contracts.
# PRICE_COVERAGE_START -- min(trade_date) per slug over the canonical bytes, not the plan's per-source
# prose) and the verdict comes from ONE function, ``covers()``, which is CALLED here and never
# re-derived (the futures_roll F-L discipline applied to coverage):
#
#   serve     -- the whole window sits on or after the floor: the per-expiry table answers it, untouched.
#   legacy    -- the whole window predates the floor: no per-contract record exists at all, so the only
#                honest number is a LEVEL from the roll-spliced continuous card, carrying the provenance
#                sentence VERBATIM. The lookup is REWRITTEN rather than declined -- the reader gets a
#                real number, labelled as what it is.
#   straddle  -- the window crosses the floor: DECLINE. Splicing a per-expiry series onto a roll-spliced
#                continuous one produces a series that means neither thing, and the join is invisible in
#                the output (the same class of error as an event-study magnitude measured across a roll).
#   uncovered -- the contract has no floor at all (a venue whose canonical bytes never landed), or its
#                pre-coverage era has no legacy level either (the continuous card carries 12 of the 31
#                contracts): DECLINE. coverage_start_for() RAISES rather than defaulting, so a missing
#                entry can never be read as "covered since forever".
#
# The decline is VERBATIM and lands in BOTH lanes: the payload's scope_note (which is what the hybrid
# reasoner consumes -- it never reads the agent's prose, defect #144) and a deterministic preface on the
# finished answer. Every other table returns ("serve", None) before any of this runs, so the guard is a
# no-op -- byte-identical -- everywhere else.
FUTURES_EOD_TABLE = "silver_futures_eod"
FUTURES_EOD_COVERAGE_TEMPLATES: dict[str, str] = {
    "straddle": ("the window asked about crosses the date the per-delivery-month record begins "
                 "({floor}) -- before that date only the roll-spliced continuous series exists here, and "
                 "reading one window across that join would give a series that is neither of them; I can "
                 "read a window sitting entirely on or after {floor} from the per-delivery-month data, or "
                 "a level from the continuous series for a window entirely before it, but not one that "
                 "spans the two"),
    "uncovered": ("there is no per-delivery-month record for that contract here at all, so there is no "
                  "named-expiry level and no curve to read for it -- nothing below should be read as "
                  "that contract's own delivery-month price"),
    # FLOOR-AWARE TWIN (owner word 2026-08-20; the defect was pre-existing since W3.2 and went
    # conspicuous when the D-PR-24 MATIF flip minted a two-week-old floor). futures_eod_route reaches
    # 'uncovered' by TWO paths: coverage_start_for RAISED (no record anywhere -- DCE, Bursa; floor is
    # None; "at all" is TRUE and the text above stays byte-identical for it), or covers() said 'legacy'
    # but the retiring continuous card does not serve the slug (rapeseed ZCE pair, both JSE boards,
    # MIAX HRSW, the three MATIF slugs; floor is KNOWN and "at all" was a lie the engine told while
    # holding the date in its hand). The template key is selected inside
    # futures_eod_coverage_template; the ROUTE name stays 'uncovered' everywhere.
    "uncovered_floored": ("there is no per-delivery-month record for that contract here before "
                          "{floor} -- the record begins on that date, and no continuous series stands "
                          "in for the earlier period, so there is no named-expiry level and no curve "
                          "to read for that period -- nothing below should be read as that contract's "
                          "own delivery-month price"),
}
FUTURES_EOD_COVERAGE_CLASSES: tuple[str, ...] = ("straddle", "uncovered")


def _cov_date(text, *, end: bool):
    """'YYYY-MM-DD' (or a bare 'YYYY-MM', widened to the month's first/last day) -> a date; None when the
    value is missing or unparseable. None is never treated as "covered" -- the callers fail closed."""
    t = str(text or "").strip()[:10]
    if not t:
        return None
    try:
        if len(t) == 7:                                  # 'YYYY-MM' -- the month-card form, tolerated
            y, m = int(t[:4]), int(t[5:7])
            if not end:
                return _dt.date(y, m, 1)
            nxt = _dt.date(y + 1, 1, 1) if m == 12 else _dt.date(y, m + 1, 1)
            return nxt - _dt.timedelta(days=1)
        return _dt.date.fromisoformat(t)
    except (TypeError, ValueError):
        return None


def futures_eod_window(spec) -> Optional[tuple]:
    """(lo, hi) -- the date window a silver_futures_eod lookup actually reads, or None when the as-of is
    unreadable.

    period_start/period_end when given; otherwise the read is a POINT at the as-of (a latest-value read
    returns the newest row on or before it). An absent period_start with a period_end present is a point
    at period_end, NOT an open-ended history: that is the ambiguity-fails-toward-not-firing discipline
    every other guard in this file follows -- the question named no pre-coverage era, and a read that
    simply starts at the table's own first row splices nothing onto anything. `hi` is capped at the
    as-of, because the leakage guard caps it anyway and a coverage verdict must describe the read that
    will actually run.

    ABSENT and UNPARSEABLE are kept apart on purpose. Absent means "no bound was asked for" and narrows
    to a point; a bound that was SUPPLIED but cannot be read returns None, which the caller turns into a
    decline. Collapsing the two would make a malformed period_start ('2005-1-3') look like an unwindowed
    latest read and quietly route a pre-coverage question to 'serve'."""
    asof = _cov_date(getattr(spec, "asof", None), end=True)
    if asof is None:
        return None
    ps_raw = str(getattr(spec, "period_start", None) or "").strip()
    pe_raw = str(getattr(spec, "period_end", None) or "").strip()
    pe = _cov_date(pe_raw, end=True) if pe_raw else None
    ps = _cov_date(ps_raw, end=False) if ps_raw else None
    if (pe_raw and pe is None) or (ps_raw and ps is None):
        return None                                      # a supplied-but-unreadable bound -> fail closed
    hi = min(pe or asof, asof)
    lo = ps or hi
    return (min(lo, hi), hi)


def _ym_bounds(ask_win: tuple) -> tuple:
    """(first day of the start month, last day of the end month) for an asked_month_window YYYYMM pair."""
    s, e = int(ask_win[0]), int(ask_win[1])
    lo = _dt.date(s // 100, s % 100, 1)
    ey, em = e // 100, e % 100
    nxt = _dt.date(ey + 1, 1, 1) if em == 12 else _dt.date(ey, em + 1, 1)
    return (lo, nxt - _dt.timedelta(days=1))


def futures_eod_read_window(spec, floor=None, ask_win: Optional[tuple] = None) -> Optional[tuple]:
    """The window the coverage verdict is taken on -- futures_eod_window(spec), NARROWED to the era the
    QUESTION names when the model expressed no window at all and that era ends before the table's floor.

    THE REACH GAP this closes (2026-07-31). futures_eod_window collapses an absent period_start/period_end
    to a POINT at the harness as-of, so with serving's as-of = today "what was corn trading at back in May
    2005", emitted as {commodity: corn_cbot, agg: latest}, routed 'serve', compiled real SQL and returned
    TODAY's nearest-expiry settle carrying no coverage stamp and no preface. That is precisely the failure
    _legacy_level_spec was written to prevent -- "a 2005 question at today's as-of returns TODAY's level
    wearing 2005's label" -- reachable on the serve path, where nothing equivalent existed. The guard was
    driven by the window the model EXPRESSED, never by the era the question NAMED.

    The rule is deliberately narrow and fails toward today's behaviour in every ambiguous direction:
      * a model-EXPRESSED window wins outright (it is the read that will actually run);
      * an ask naming no month (asked_month_window -> None) changes nothing;
      * an era that REACHES the floor changes nothing -- only an era ending strictly before the first
        per-contract row is unambiguously pre-coverage, and only then is the point read overridden.
    ``hi`` is capped at the as-of exactly as futures_eod_window caps it, so the narrowed window still
    describes a read the leakage guard would permit."""
    win = futures_eod_window(spec)
    if win is None or ask_win is None or floor is None:
        return win
    if str(getattr(spec, "period_start", None) or "").strip() or \
            str(getattr(spec, "period_end", None) or "").strip():
        return win                                       # the model expressed the window -> that IS the read
    lo, hi = _ym_bounds(ask_win)
    if hi >= floor:                                      # the named era reaches coverage -> point read stands
        return win
    asof = _cov_date(getattr(spec, "asof", None), end=True)
    if asof is not None and hi > asof:
        hi = asof
    return (min(lo, hi), hi)


def _legacy_serves(slug: str, reg: Optional[NumbersRegistry] = None) -> bool:
    """True when the retiring continuous card can serve `slug` at all. Its unit_overrides ARE its served
    set (12 of the 31 contracts), so a pre-coverage ask for a CZCE / JSE / CEPEA / MATIF contract has no
    legacy level to fall back on and must DECLINE instead of quietly answering with nothing."""
    try:
        ts = (reg or load_registry()).get(FUTURES_TABLE)
    except Exception:  # noqa: BLE001 -- an absent/disabled continuous card means no legacy lane, not a crash
        return False
    m = (ts.metrics or {}).get("close")
    return bool(m and slug in (m.unit_overrides or {}))


def futures_eod_route(spec, reg: Optional[NumbersRegistry] = None,
                      ask_win: Optional[tuple] = None) -> tuple:
    """(route, floor_iso) for ONE lookup: 'serve' | 'legacy' | 'straddle' | 'uncovered'.

    Every table other than silver_futures_eod -- and a commodity-less lookup, which build_sql's own
    unit_overrides / partition guards already refuse -- returns ('serve', None) before any coverage work
    happens, so this is a no-op for the rest of the registry.

    ``ask_win`` is answer_numbers' asked_month_window(question) -- the era the QUESTION names. It only
    ever narrows an UNWINDOWED read whose named era ends before the floor; see futures_eod_read_window."""
    if getattr(spec, "table", None) != FUTURES_EOD_TABLE:
        return ("serve", None)
    slug = str(getattr(spec, "commodity", None) or "").strip()
    if not slug:
        return ("serve", None)
    from leviathan.silver import futures_eod_contracts as FC
    try:
        floor = FC.coverage_start_for(slug)
    except ValueError:                                   # no measured floor -> NOT SERVED, never permissive
        return ("uncovered", None)
    win = futures_eod_read_window(spec, floor, ask_win)
    if win is None:                                      # an unreadable as-of cannot be routed -> decline
        return ("uncovered", floor.isoformat())
    route = FC.covers(slug, win[0], win[1])
    if route == "legacy" and not _legacy_serves(slug, reg):
        return ("uncovered", floor.isoformat())
    return (route, floor.isoformat())


def _legacy_level_spec(spec, hi) -> "Q.NumberQuery":
    """The continuous-card LEVEL that answers a PRE-COVERAGE ask, built from the declined per-expiry one.

    Two deliberate rewrites. (1) The table/metric become the roll-spliced continuous close and any
    contract_month is DROPPED -- there is no delivery month to attach, and the recorded query must not
    imply one. (2) The as-of is narrowed to the END of the window asked about (never raised: it is
    min(window end, harness as-of), and the window's own hi is already capped at the as-of). Narrowing an
    as-of can only ever REMOVE rows, so it is PIT-safe by construction; it is also the only lever
    available, because the continuous card is levels_only -- build_sql RAISES on any windowed read, so a
    2005 question answered at today's as-of would otherwise come back with today's level wearing 2005's
    label. The provenance sentence rides the payload either way."""
    asof = _cov_date(getattr(spec, "asof", None), end=True)
    eff = min(hi, asof) if asof is not None else hi
    return Q.NumberQuery(table=FUTURES_TABLE, metric="close", asof=eff.isoformat(),
                         commodity=spec.commodity, agg="latest")


def futures_eod_legacy_provenance(floor_iso: Optional[str]) -> str:
    """The VERBATIM provenance sentence a pre-coverage LEVEL must carry (plan W3.2). It states both
    halves at once: which series the number is from, and the date before which no per-contract curve
    exists -- so the level can never be read as an expiry's settle."""
    return (f"from the roll-spliced continuous series; a per-contract curve does not exist before "
            f"{floor_iso}")


def futures_eod_coverage_template(route: str, floor_iso: Optional[str]) -> str:
    """The verbatim decline text for a straddling window / an uncovered contract.

    'uncovered' picks its text by whether a floor is KNOWN (see the template comment): floor present ->
    the floored twin that names the date the record begins; floor None -> the original "at all" text,
    byte-identical to W3.2, because for a venue with no record anywhere it is simply true."""
    if route == "uncovered" and floor_iso:
        return FUTURES_EOD_COVERAGE_TEMPLATES["uncovered_floored"].format(floor=floor_iso)
    t = FUTURES_EOD_COVERAGE_TEMPLATES[route]
    return t.format(floor=floor_iso) if floor_iso else t


def futures_eod_coverage_note(route: str, floor_iso: Optional[str]) -> str:
    """The MODEL-facing note stamped on the payload itself -- the half of the guard that survives the
    hybrid lane, which consumes `calls` and throws the agent's prose away (defect #144)."""
    if route == "legacy":
        return ("COVERAGE ROUTE -- this number is " + futures_eod_legacy_provenance(floor_iso) + ". "
                "State it as a level on its own date; never as a named delivery month, a specific "
                "expiry's settlement, or a curve read.")
    if route in FUTURES_EOD_COVERAGE_CLASSES:
        return "COVERAGE DECLINE -- " + futures_eod_coverage_template(route, floor_iso) + "."
    return ""


def futures_eod_coverage_preface(route: str, floor_iso: Optional[str]) -> str:
    """Reader-facing line (mentor register -- no internal slugs), PREPENDED deterministically so a
    pre-coverage level can never pose as a delivery-month quote and a straddling window can never be
    answered at all."""
    if route == "legacy":
        return ("One provenance note before the numbers: the figure below is "
                + futures_eod_legacy_provenance(floor_iso) + ". Read it as a level on its own date, not "
                "as a specific delivery month.\n\n")
    if route in FUTURES_EOD_COVERAGE_CLASSES:
        return ("One limitation to flag before the numbers: "
                + futures_eod_coverage_template(route, floor_iso) + ".\n\n")
    return ""


def _is_eod_call(c: dict) -> bool:
    return isinstance(c, dict) and ((c.get("query") or {}).get("table")) == FUTURES_EOD_TABLE


def futures_eod_served(calls: Optional[list]) -> bool:
    """True when a per-delivery-month lookup actually RETURNED rows this turn.

    This is what keeps the flip coherent. FUTURES_DECLINE_TEMPLATES say the curve / a named expiry is
    "not in this lookup" -- true of the continuous card, and FALSE the moment silver_futures_eod serves
    the same ask. Without this escape a served curve would arrive under a verbatim caveat denying it
    exists. The escape is deliberately narrow: a coverage-routed (legacy / declined) EOD call has NOT
    served the curve, so those turns keep the honest continuous-card caveat."""
    for c in (calls or []):
        if _is_eod_call(c) and (c.get("status") == "ok") and (c.get("rows") or []):
            return True
    return False


def futures_eod_seam_c_muted(calls: Optional[list], reg: Optional[NumbersRegistry] = None) -> bool:
    """True when the SEAM-C continuous-card caveat must be SUPPRESSED because the fallback it OFFERS does
    not exist.

    Every FUTURES_DECLINE_TEMPLATE ends by offering the continuous front-month level ("I can give the
    front-month close level on a date, not a curve read"). On an UNCOVERED venue that offer is false: the
    retiring card serves 12 of the 31 contracts, so for palm_olein_dce / the rest of the unlanded browser
    slugs the reader was told a fallback is available that would raise if asked for -- stacked
    immediately in front of the coverage decline saying there is no record for that contract AT ALL. The
    coverage template alone is the honest, complete statement. Narrow by construction: only an
    'uncovered' route on a slug the continuous card cannot serve mutes anything; a covered turn, a
    straddle, a legacy rewrite and every non-futures turn are byte-identical.

    NOTE THE TEST THIS PREDICATE IS NOT (D-PR-24 answer flip, 2026-08-20): the condition is 'the
    continuous card cannot serve this slug', NEVER 'this slug has no floor'. The three euronext_matif
    slugs gained a floor of 2026-08-06 and are STILL outside the continuous card's 12 unit_overrides, so
    a PRE-floor MATIF ask routes 'uncovered' and still mutes here -- correctly, because the offer is
    still one the engine cannot keep. A POST-floor MATIF ask routes 'serve' and never reaches this
    function at all; futures_eod_served is what skips SEAM-C there."""
    for c in (calls or []):
        if isinstance(c, dict) and c.get("coverage_route") == "uncovered":
            slug = str(((c.get("query") or {}).get("commodity")) or "").strip()
            if slug and not _legacy_serves(slug, reg):
                return True
    return False


def futures_eod_coverage_guard(calls: Optional[list]) -> Optional[tuple]:
    """(route, floor_iso) of the FIRST coverage-routed lookup in `calls`, else None. The verdict rides
    the CALLS (stamped in answer_numbers' executor), which is why both lanes can read it."""
    for c in (calls or []):
        r = (c or {}).get("coverage_route") if isinstance(c, dict) else None
        if r and r != "serve":
            return (r, c.get("coverage_floor"))
    return None


# -- year_month PERIOD-SCOPING honesty guard (task #142) ------------------------------------------------
# The month-grained cards (silver_noaa_iod, silver_noaa_oni, gold_weather_z) are as-of-guarded on
# (year*100 + month) <= asof_ym, so an UNSCOPED lookup answers "the newest month on or before the as-of
# date" -- NOT "the month you named". The judged newcap30 row ncap_iod_1997_analog is exactly that miss:
# "the DMI in October 1997" as-of 1998-06-01 ran unscoped, the guard returned the June-1998 row, and the
# answer then invented a "not yet published / lagging reconstruction" story for a month that sat in the
# lake the whole time. Two teeth, cloning the ESR/price guard discipline:
#   (a) the OFFENDING tool_result is stamped with the mismatch + the exact re-scoped call to issue (the
#       loop still has call budget, so a stamped turn can repair itself), and
#   (b) when the turn ENDS with no month-grained lookup having landed INSIDE the named window, a
#       reader-facing period-mismatch line is PREPENDED and `period_mismatch_guard` rides the trace.
# The inside-the-window escape is what keeps a legitimate two-month ask ("how does the latest reading
# compare with October 1997?") unflagged: once the named month is actually resolved, (b) is a no-op.
# Detection is conservative -- a MONTH NAME must sit adjacent to a 4-digit year, and a month-year that is
# really a DATE ("1 June 1998") or the AS-OF framing ("as of June 2026") is excluded -- so a plain "what
# is the latest DMI reading" ask is byte-identical (no note, no preface, no trace key).
_MONTH_NUMS: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12}
_MONTH_LABELS = ("January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December")
# Longest-first so 'march' wins over 'mar' and 'sept' over 'sep'. The 4-digit year is REQUIRED (it is what
# makes a bare 'may'/'march' unambiguously a month rather than a verb or a farm-march noun).
_MONTH_YEAR_RX = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_NUMS, key=len, reverse=True)) + r")\.?[\s\-/]+(?:of\s+)?((?:19|20)\d{2})\b")
# A month-year that is really a full DATE ('1 June 1998', 'as at June 2026') is the POINT-IN-TIME framing,
# which the harness already fixes -- never the period the question is about. ('June 1, 1998' cannot match
# _MONTH_YEAR_RX at all: the day sits between the month and the year.)
_DATE_PREFIX_RX = re.compile(r"(?:\b\d{1,2}(?:st|nd|rd|th)?\s+|\bas[\s-]?of\s+|\bas\s+at\s+|\bdated\s+)$")


def asked_month_window(question: str) -> Optional[tuple[int, int]]:
    """(start_ym, end_ym) as YYYYMM ints for the historical month(s) the question NAMES, else None. One
    named month gives a degenerate window; several give min..max (a span ask, e.g. 'October 1997 through
    February 1998'). Ambiguity fails toward None -- an ask that names no month never reaches the guard."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    yms: list[int] = []
    for m in _MONTH_YEAR_RX.finditer(q):
        if _DATE_PREFIX_RX.search(q[:m.start()]):
            continue                                   # '1 June 1998' / 'as of June 2026' -> a date, not the ask
        yms.append(int(m.group(2)) * 100 + _MONTH_NUMS[m.group(1)])
    return (min(yms), max(yms)) if yms else None


def _ym_label(ym: int) -> str:
    return f"{_MONTH_LABELS[(ym % 100) - 1]} {ym // 100}"


def _window_label(win: tuple[int, int]) -> str:
    return _ym_label(win[0]) if win[0] == win[1] else f"{_ym_label(win[0])} to {_ym_label(win[1])}"


def _ym_iso(ym: int) -> str:
    return f"{ym // 100:04d}-{ym % 100:02d}"                  # the 'YYYY-MM' period_start/period_end form


def _row_ym(row: dict) -> Optional[int]:
    """A month-grained row's OWN (year, month) as a YYYYMM int -- every year_month card surfaces both as
    self-identifying extras (query._extras). None when either cell is missing or unparseable."""
    try:
        y, mo = int(str((row or {}).get("year")).strip()), int(str((row or {}).get("month")).strip())
    except (TypeError, ValueError):
        return None
    return y * 100 + mo if 1 <= mo <= 12 else None


def _is_month_grain_call(c: dict, reg: NumbersRegistry) -> bool:
    """True when the call hit a card whose as-of guard is month-grained (year_month semantics)."""
    tbl = (c.get("query") or {}).get("table")
    if not tbl:
        return False
    try:
        return reg.get(tbl).knowledge_semantics == "year_month"
    except KeyError:                                          # unregistered table -> not month-grained
        return False


def period_mismatch_ym(win: tuple[int, int], calls: list, reg: NumbersRegistry) -> Optional[int]:
    """The YYYYMM of the FIRST month-grained row that landed OUTSIDE the named window, or None when either
    no such row exists OR some month-grained lookup DID land inside it (the named month was resolved, so
    there is nothing to flag)."""
    off: Optional[int] = None
    for c in calls:
        if not _is_month_grain_call(c, reg):
            continue
        for ym in (_row_ym(r) for r in (c.get("rows") or [])):
            if ym is None:
                continue
            if win[0] <= ym <= win[1]:
                return None                                   # asked month resolved -> guard is a no-op
            if off is None:
                off = ym
    return off


def _period_mismatch_scope_note(win: tuple[int, int], row_ym: int) -> str:
    """Model-facing note stamped on a month-grained tool_result whose row is NOT the month the question
    named. Carries the exact re-scoped call, and bans the publication-lag story outright."""
    return (f"PERIOD MISMATCH -- this row is {_ym_label(row_ym)}; the question named {_window_label(win)}. "
            f"An unscoped monthly lookup returns the latest month on or before the as-of date, not the month "
            f"asked about. To read the month asked about, call {TOOL_NAME} again for the same metric with "
            f"period_start='{_ym_iso(win[0])}' and period_end='{_ym_iso(win[1])}'. NEVER present this row as "
            f"if it were that month, and NEVER explain the asked month as not-yet-published, lagging, or "
            f"unavailable -- an unscoped lookup simply did not request it.")


def _period_mismatch_preface(win: tuple[int, int], row_ym: int) -> str:
    """Reader-facing period-mismatch line (mentor register -- no internal slugs). PREPENDED deterministically
    so a different month can never pose as the month asked about, and so the miss is named as what it is (a
    scoping miss) instead of being dressed up as a publication gap."""
    return (f"One scope note before the numbers: the lookup returned {_ym_label(row_ym)}, not "
            f"{_window_label(win)} -- it was not scoped to the month asked about, so it came back with the "
            f"most recent month on or before the as-of date. Read the figure below as the "
            f"{_ym_label(row_ym)} reading. Nothing here means the {_window_label(win)} figure is missing or "
            f"unpublished.\n\n")


# -- C2 question-shape -> required-metric table + the honest decline line (D3, ratified 2026-08-01) -----
# The SIXTH member of the "detect the question shape ONCE, up front" family above. The other five each ask
# "is this ask servable?"; this one asks the question none of them do -- "for a question of THIS shape, which
# observed metric does an honest answer require?" -- and it answers INDEPENDENTLY of what the model chose to
# look up. That independence is the whole point: finding 2.4(a) measured the agent's discretion as
# ANTI-CORRELATED with the ask (silver_cot reached on the two execution-BAIT rows and on none of the three
# pure positioning rows), so a record derived from the calls the model happened to make cannot see the miss.
#
# It dispatches NOTHING. It records what the shape required and what the turn did with it, and on exactly one
# of those outcomes it emits a deterministic decline. See configs/graphrag/numbers/question_shapes.yaml for
# the table itself, the doctrine gates and the register rule; config_check.check_question_shapes is the lint.


@functools.lru_cache(maxsize=1)
def load_shape_table() -> dict:
    """{shape: {omission, requires: [{id, subject, tables, metrics, ...}]}} from question_shapes.yaml.
    lru_cached (the cascade.load_map idiom). A requirement flagged `deferred: true` is DROPPED here and is
    therefore inert everywhere below -- the same mechanism cascade_map uses to park a row that exists on
    paper but is not doctrine-cleared to fire (today: the outlook shape's R4-fenced spot anchor)."""
    import yaml

    from leviathan.graphrag import extract as ex  # ex._CFG = configs/graphrag (registry convention)
    p = ex._CFG / "numbers" / "question_shapes.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    out: dict = {}
    for shape, spec in ((doc or {}).get("shapes") or {}).items():
        live = [r for r in ((spec or {}).get("requires") or []) if not (r or {}).get("deferred")]
        out[shape] = {**(spec or {}), "requires": live}
    return out


# F4 (adversarial review, 2026-08-01): the state a 'no_rows' read is DOWNGRADED to when the query that
# produced it could not have matched a row under ANY data -- see _scope_resolves. It is deliberately NOT
# in _STATUS_STATE: no executor status maps to it, so the build-time one-status bind on the decline state
# (config_check.check_question_shapes half (d)) is unchanged.
SHAPE_SCOPE_UNRESOLVED = "scope_unresolved"
# The requirement states, in PRECEDENCE order -- which is the only ordering that matters here. A requirement
# can be probed by several calls; it takes the FIRST state in this tuple that any of them produced. 'served'
# leads deliberately: one row anywhere outranks an empty read elsewhere, so a decline can never contradict a
# figure the same turn is about to print. 'empty' outranks 'scope_unresolved' for the same reason in the
# other direction: one CORRECTLY scoped empty read is a real absence, whatever else the model mis-keyed.
_SHAPE_STATES: tuple[str, ...] = ("served", "empty", SHAPE_SCOPE_UNRESOLVED, "not_known", "declined",
                                  "error", "not_attempted")
# _exec's own status taxonomy -> the requirement state. _exec is the ONLY writer of those strings, which is
# what makes condition (c) of D3 structural rather than conventional: nothing else in this module can mint
# 'no_rows', so nothing else can mint a decline.
#   ok         -> the lookup returned at least one non-null value.
#   no_rows    -> "the query matched no data" for a data_date/year_month/ingest table. THE decline state.
#   not_known  -> the VINTAGE tables' empty result, which _exec assigns without distinguishing "not yet
#                 published at the as-of" from "scope mismatch". "The record holds no X" is a claim the
#                 executor never made there, so it is NOT a decline (D3's wrong-decline flip condition).
#   declined   -> a coverage decline (silver_futures_eod); that class owns its own reader-facing template.
#   error      -> a malformed/failed call. Finding 2.4(b) measured this at 21 of 24 calls on one table; an
#                 error is not data absence and must never be narrated as any.
SHAPE_DECLINE_STATE = "empty"
_STATUS_STATE: dict[str, str] = {"ok": "served", "no_rows": SHAPE_DECLINE_STATE, "not_known": "not_known",
                                 "declined": "declined", "error": "error"}

SHAPE_DECLINE_LEAD = "One limitation to flag before the numbers: "
# The canonical SCOPE phrase the build-time register census and the standing corpus render with, so the
# scoped form of every decline sentence is linted and pinned exactly like the unscoped one was.
SHAPE_SCOPE_PROBE = "CBOT corn over 2026-01-01..2026-07-31"

# Detection, in PRIORITY order (first match wins -- one shape per turn, the futures_scope precedent). Each
# pattern is deliberately narrow on the vocabulary that makes the ask THAT shape; a question matching none of
# them is shapeless and every line below is a no-op, so an unmatched turn is byte-identical to pre-C2.
_SHAPE_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # positioning: the DATA words for a managed-money read. 'open interest' is deliberately absent -- it is
    # a market-wide figure and the requirement's metric list excludes it, so detecting on it would demand a
    # managed-money row for a question that never asked for one.
    ("positioning", re.compile(
        r"\b(?:managed[- ]money|commitments? of traders|cot report|cot data|\bcot\b|"
        r"net long|net short|net length|spec(?:ulative)?\s+length|positioning|"
        r"(?:funds?|specs?|speculators?)\s+(?:are\s+|were\s+|have\s+|remain\w*\s+)?(?:net\s+)?(?:long|short))\b")),
    # seasonality: the ENSO/oscillation names and the moisture vocabulary a seasonal ask is made of.
    ("seasonality", re.compile(
        # The n-tilde is written as a \u escape, not a literal: this file is ASCII-only, and "El Nino"
        # reaches us both ways (the FE posts NFC, a desk analyst types the ASCII form).
        r"\b(?:seasonal|seasonality|seasonally|el\s*ni(?:n|\u00f1)o|la\s*ni(?:n|\u00f1)a|enso|oni|"
        r"southern oscillation|drought|dryness|monsoon|rainfall|precipitation)\b")),
    # pace: a RATE-of-programme ask, never a stock or a total. 'export sales' is the ESR card's own name.
    ("pace", re.compile(
        r"\b(?:export pace|sales pace|shipment pace|shipping pace|pace of (?:exports?|sales|shipments)|"
        r"export sales|weekly sales|outstanding sales|export commitments?|export programme|export program|"
        r"(?:ahead of|behind|running against)\s+(?:last year|the (?:five|5)[- ]year))\b")),
    # outlook: FORWARD framing, plus the s/u metric named outright (the judge named it on 37 of 58 rows).
    # The bare balance-sheet nouns -- 'ending stocks', 'carryout', 'balance sheet' -- are DELIBERATELY
    # absent: "what were Argentina corn ending stocks in 2019" is a historical LEVEL ask that the ordinary
    # lookup path serves, and demanding a stocks-to-use anchor of it would record a miss that is not one.
    # Measured while authoring, 2026-08-01 -- the first draft of this pattern fired on exactly that ask.
    ("outlook", re.compile(
        r"\b(?:outlook|forecast|how high|how low|price target|upside|downside|"
        r"stocks[- ]to[- ]use|stocks to use|"
        r"where\s+(?:do|does|will|would|could|might|are)\s+(?:prices?|it|the market|things))\b")),
)


def question_shape_scope(question: str) -> Optional[str]:
    """The question's SHAPE (positioning / seasonality / pace / outlook), or None when it has none. First
    match in _SHAPE_PATTERNS order wins -- a positioning ask that also says 'outlook' is a positioning ask,
    because the more specific vocabulary is the one that names a required metric. None (the common case) is
    a no-op everywhere below."""
    q = re.sub(r"\s+", " ", (question or "").lower())
    for shape, rx in _SHAPE_PATTERNS:
        if rx.search(q):
            return shape
    return None


@functools.lru_cache(maxsize=1)
def _slug_keyed_tables() -> frozenset[str]:
    """Registry tables whose commodity column is `leviathan_slug`, i.e. whose vocabulary is CONTRACT slugs
    (silver_cot, silver_psd). tables.yaml:699 records the consequence in as many words: a bare base name
    ('corn') matches ZERO rows. Deliberately NOT every table with a commodity column -- gold_weather_z and
    silver_mpob key on a different vocabulary this module cannot enumerate offline, and a validator that
    guesses would manufacture the false downgrade it exists to prevent."""
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        return frozenset(t for t, s in load_registry().tables.items()
                         if getattr(s, "commodity_col", None) == "leviathan_slug")
    except Exception:  # noqa: BLE001 -- a registry problem must never break the agent loop
        return frozenset()


@functools.lru_cache(maxsize=1)
def _contract_slugs() -> frozenset[str]:
    """The CONTRACT-slug vocabulary the rest of the stack already carries (evidence hierarchy contracts):
    corn_cbot, soybean_oil_cbot, arabica_coffee, ... Note 'corn' and 'soybeans' are NOT members -- they are
    causal-DAG contract ids that cascade._scope aliases to `*_cbot` before it ever queries."""
    try:
        from leviathan.graphrag import evidence as ev
        return frozenset(str(k) for k in ((ev._hier().get("contracts") or {})))
    except Exception:  # noqa: BLE001 -- no hierarchy -> _scope_resolves fails closed (see below)
        return frozenset()


def _scope_resolves(table, commodity) -> bool:
    """Could this query have matched a row AT ALL, given how the table is keyed? F4 (adversarial review).

    `_exec` assigns 'no_rows' to every non-vintage empty result, and its own comment says that means "the
    query matched no data (filter/scope mismatch OR a lake gap)". C2 promoted that into a reader-facing
    assertion about THE RECORD, and the acute case is the exact table C2 targets: silver_cot's
    commodity_col is `leviathan_slug`, so a model that passes 'corn' instead of 'corn_cbot' gets 'no_rows'
    while 12 slugs of weekly data sit in the table -- D3's stated flip condition ("a wrong decline")
    reachable through the front door. A query whose commodity cannot key the table is therefore NOT
    evidence of absence; the requirement is downgraded to SHAPE_SCOPE_UNRESOLVED and no line is emitted.

    FAIL-CLOSED means NO DECLINE, in every uncertainty: an unknown table, a missing commodity on a
    slug-keyed table, or an unavailable vocabulary all return False. A wrong decline is worse than silence
    (D3), so the untrusted branch is always the quiet one."""
    tid = str(table or "")
    if not tid:
        return False
    if tid not in _slug_keyed_tables():
        return True                       # not slug-keyed: nothing this function can honestly claim
    com = str(commodity or "").strip()
    if not com:
        return False                      # a per-contract table read with NO contract never scoped the ask
    slugs = _contract_slugs()
    return bool(slugs) and com in slugs


def _scope_phrase(q: dict | None) -> str:
    """What the query ACTUALLY asked for, as a reader-facing noun phrase -- 'CBOT corn over
    2011-01-01..2012-06-30', 'the 2026-07-31 as-of'. F4(c): the decline names its own scope, so the
    sentence is a statement about a NAMED read rather than about 'the record' in the abstract.

    The commodity renders through display._contract_label ('corn_cbot' -> 'CBOT corn') rather than raw:
    reg.sanitize would rewrite the slug on the way out anyway, and rendering it pre-rewritten keeps the
    build-time 'survives sanitize' census meaningful. Never returns '' -- the as-of is always present
    (the harness forces it), so there is always something true to name."""
    q = q or {}
    com = str(q.get("commodity") or "").strip()
    label = ""
    if com:
        try:
            from leviathan.graphrag import display as dp
            label = dp._contract_label(com) or com.replace("_", " ")
        except Exception:  # noqa: BLE001 -- a label lookup must degrade, never break a decline
            label = com.replace("_", " ")
    per = str(q.get("period") or "").strip()
    p0, p1 = str(q.get("period_start") or "").strip(), str(q.get("period_end") or "").strip()
    window = per or (f"{p0}..{p1}" if p0 and p1 else (p0 or p1))
    asof = str(q.get("asof") or "").strip()
    if label and window:
        return f"{label} over {window}"
    if label:
        return f"{label} as of {asof}" if asof else label
    if window:
        return f"the {window} window"
    return f"the {asof} as-of" if asof else "that window"


def _shape_requirement_probe(req: dict, calls: Optional[list]) -> tuple[str, str]:
    """(this requirement's state, the SCOPE PHRASE of the call that decided it). Matching is TABLE-first:
      * table matches AND metric is one the requirement accepts -> _exec's status decides;
      * table matches, status 'error', ANY metric (including none at all) -> 'error'. Finding 2.4(b): a
        malformed tool call carries the model's RAW input as its query, so the metric key can be missing
        entirely. That is still an ATTEMPT at the table, and reading it as 'never attempted' would hide the
        one class that is 87.5% of the calls on silver_futures_prices;
      * anything else -> not this requirement's business.
    A 'no_rows' whose query could not have keyed the table is DOWNGRADED to SHAPE_SCOPE_UNRESOLVED (F4).
    'not_attempted' when nothing matched, which is the miss state (2.3 #1) the whole plan is about."""
    tables = set(req.get("tables") or ())
    metrics = set(req.get("metrics") or ())
    seen: dict[str, str] = {}                      # state -> scope phrase of the FIRST call that produced it
    for c in (calls or []):
        if not isinstance(c, dict):
            continue
        q = c.get("query") or {}
        if not isinstance(q, dict) or q.get("table") not in tables:
            continue
        status = str(c.get("status") or "")
        if status == "error":
            seen.setdefault("error", _scope_phrase(q))
        elif q.get("metric") in metrics:
            st = _STATUS_STATE.get(status, "error")
            if st == SHAPE_DECLINE_STATE and not _scope_resolves(q.get("table"), q.get("commodity")):
                st = SHAPE_SCOPE_UNRESOLVED
            seen.setdefault(st, _scope_phrase(q))
    for state in _SHAPE_STATES:
        if state in seen:
            return state, seen[state]
    return "not_attempted", ""


def _shape_requirement_state(req: dict, calls: Optional[list]) -> str:
    """This requirement's state across every executed call (the state half of _shape_requirement_probe)."""
    return _shape_requirement_probe(req, calls)[0]


def shape_requirement_states(shape: Optional[str], calls: Optional[list]) -> dict[str, str]:
    """{requirement id: state} for the matched shape -- the record the four miss states (section 2.3) need
    and that no counter emits today. Empty dict when the question had no shape."""
    spec = load_shape_table().get(shape or "") or {}
    return {str(r.get("id")): _shape_requirement_state(r, calls) for r in (spec.get("requires") or [])}


def _join_subjects(subjects: list[str], scopes: Optional[list[str]] = None) -> str:
    """'no A', 'no A and no B', 'no A, no B and no C' -- each subject carries its OWN 'no' so the sentence
    stays a statement about the RECORD rather than about a list. With `scopes` (F4) each subject also
    carries its OWN 'for <what was queried>', because two requirements are two different reads and one
    shared window clause would mis-state at least one of them."""
    if scopes:
        parts = [f"no {s} for {sc}" if sc else f"no {s}" for s, sc in zip(subjects, scopes)]
    else:
        parts = [f"no {s}" for s in subjects]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def shape_decline_line(shape: str, subjects: list[str], scopes: Optional[list[str]] = None) -> str:
    """The deterministic decline SENTENCE (no trailing blank line). D3(iii): data-absence phrasing about the
    record, never an effort narrative -- there is no 'we looked', no 'I tried', no 'could not find'. The
    register census in config_check.check_question_shapes runs this exact renderer, so what is linted is the
    string the reader gets.

    `scopes` (F4, parallel to `subjects`) names WHAT WAS QUERIED for each absence -- the contract, the
    window, the as-of. The runtime path ALWAYS supplies it (shape_decline builds it from the empty call
    itself), so the bare 'for that window' form below survives only for the build-time census and the
    standing corpus, which render both forms. The reader is never told "the record holds no X" about a
    scope nobody named."""
    omission = str((load_shape_table().get(shape) or {}).get("omission") or "").strip()
    body = _join_subjects(subjects, scopes)
    line = f"{SHAPE_DECLINE_LEAD}the record holds {body}"
    if not scopes:
        line += " for that window"
    return f"{line}, {omission}." if omission else f"{line}."


def shape_decline(shape: Optional[str], calls: Optional[list]) -> tuple[str, list[str], dict[str, str]]:
    """(preface, declined requirement ids, per-requirement states) -- the WHOLE of C2's reader-facing half,
    as one pure function of (shape, calls) so the D3 guard is testable in isolation.

    The three conditions of D3 are the three lines of this function and nothing else can satisfy them: the
    shape must have matched (else `spec` is empty), the requirement must be declared (else it is not in
    `states`), and its state must be SHAPE_DECLINE_STATE -- which only _exec's 'no_rows' produces. A wrong
    decline (claiming absence where the data exists) is therefore not a discipline question: there is no
    path through this function that reaches the preface without a recorded empty fetch.

    F4 adds the FOURTH condition, and it is what makes the sentence's claim match the fetch's evidence:
    the empty fetch must have been SCOPED to something the table can key (_scope_resolves), and the
    rendered line NAMES that scope. An empty read under a key the table never serves ('corn' where
    silver_cot holds 'corn_cbot') is not a fact about the record and no longer produces a line."""
    spec = load_shape_table().get(shape or "") or {}
    probes = {str(r.get("id")): _shape_requirement_probe(r, calls) for r in (spec.get("requires") or [])}
    states = {rid: st for rid, (st, _scope) in probes.items()}
    declined = [str(r.get("id")) for r in (spec.get("requires") or [])
                if states.get(str(r.get("id"))) == SHAPE_DECLINE_STATE]
    if not declined:
        return "", [], states
    pairs = [(str(r.get("subject")), probes[str(r.get("id"))][1])
             for r in (spec.get("requires") or [])
             if str(r.get("id")) in declined and (r.get("subject") or "").strip()]
    if not pairs:                                      # a requirement with no subject has no sentence to say
        return "", [], states
    subjects = [s for s, _sc in pairs]
    scopes = [sc for _s, sc in pairs]
    return shape_decline_line(str(shape), subjects, scopes) + "\n\n", declined, states


# -- F14 / R8: DECLINE-REGISTER SUPPRESS-ON-OVERLAP (ratified 2026-08-01, wave-plan addendum 2) ---------
# Two decline REGISTERS can co-occur in one answer preface: C2's question-shape line beside a legacy
# template -- the R5 price-coverage decline (DECLINE_TEMPLATES), the SEAM-C futures levels-only decline
# (FUTURES_DECLINE_TEMPLATES), the ESR destination decline, the W3.2 coverage decline. The reader then
# gets two "One limitation to flag before the numbers:" sentences stacked in front of one answer, each
# refusing a different thing.
#
# RATIFIED AS SUPPRESS-ON-OVERLAP: when any OTHER decline template already fired for the turn, the C2
# line stays silent -- one preface, one decline. The RECONCILE alternative (harmonize the wordings into a
# single sentence) was REJECTED at ratification because it re-pins strings the R5 / futures-lite censuses
# and the judged decks assert verbatim, forcing a re-measurement for a wording harmonization. Nothing in
# this change touches the TEXT of any template, C2's included.
#
# The test is the SHARED LEAD, which is what makes it structural rather than a list to maintain: every
# reader-facing DECLINE in this module opens with SHAPE_DECLINE_LEAD verbatim (_esr_destination_preface,
# _price_decline_preface, _futures_decline_preface, futures_eod_coverage_preface's decline classes), and
# every non-decline preface deliberately does not -- the period-mismatch line ("One scope note before the
# numbers: "), the ESR bloc caveat ("One note on scope before the number: "), the W3.2 legacy-provenance
# note ("One provenance note before the numbers: ") and the pattern-records observation line. That split
# is the right one to suppress on: a scope / provenance / bloc note is a statement ABOUT a figure the
# turn is serving, not a second refusal, so a turn carrying one still gets its C2 decline. The two-sided
# census in tests/unit/test_decline_overlap.py pins both halves, so a future decline template that
# invents its own lead fails there rather than silently re-opening the double preface.
def other_decline_fired(preface: Optional[str]) -> bool:
    """True when a decline template OTHER than C2's has already landed in this turn's preface (F14/R8)."""
    return SHAPE_DECLINE_LEAD in (preface or "")


def _visible_tables(reg: NumbersRegistry) -> list[str]:
    """The registry tables EXPOSED to the agent this call: sorted(reg.tables), MINUS the flag-gated
    pattern-records card when GRAPHRAG_PATTERN_RECORDS is OFF. Read per-call so the kill-switch rollback is
    live; when off the returned list is BYTE-IDENTICAL to the pre-feature sorted(reg.tables) (the card is
    the only new table), so tool_schema + system_prompt are unchanged (plan 7.6 identical-answers smoke).

    D-CW-1d: the RULE itself now lives in ``registry.visible_tables`` and this is a thin wrapper over it --
    ``dispatch.family_names()`` derives the planner's family enum from the SAME function, so the router can
    no longer emit a family whose card the agent cannot see (the census's gold_pattern_records enum leak).
    Kept as a module-local name because every call site in this module (tool_schema, system_prompt,
    _families_line) reads it and the tests pin it here."""
    return _visible(reg)


# B1: MIRRORS dispatch._FAMILY_PREFIX -- the family enum is DERIVED by stripping this prefix off every
# registered table id, so resolving a family back to its table means undoing exactly that substitution. The
# two patterns are pinned equal by a unit test rather than imported, so the numbers agent keeps no dependency
# on the planner module (the enum is registry-derived on both sides; the planner is not its owner).
_FAMILY_PREFIX = re.compile(r"^(?:silver|gold|bronze)_")


def _families_line(reg: NumbersRegistry, families) -> str:
    """B1 steering hint: the planner's `data_families` as ONE line of the user turn, or "" when there is
    nothing honest to say.

    The family enum is registry-derived (silver_cot -> cot), so this generalizes to every registered family
    with nothing hardcoded -- and it is resolved back to the TABLE ID the agent's own tool enum uses, because
    a hint naming something the model cannot pass to `lookup_number` is worse than no hint. Resolved against
    _visible_tables, not reg.tables: the same kill-switch parity the system prompt keeps, so the model is
    never steered at a card it does not have.

    A HINT, not an instruction to produce a number: it moves a probability, and the plan says so. The closing
    clause exists because the failure mode of steering is a fabricated row -- an agent told a family is
    'implicated' can read that as 'a value must exist'. Unknown/garbage families resolve to nothing and the
    line disappears, so a mis-plumbed enum degrades to today's turn rather than to a lie."""
    if not families:
        return ""
    by_family: dict[str, str] = {}
    for tid in _visible_tables(reg):
        by_family.setdefault(_FAMILY_PREFIX.sub("", str(tid)).strip(), str(tid))
    named: list[str] = []
    for f in (families or []):
        t = by_family.get(str(f).strip())
        if t and t not in named:
            named.append(t)
    if not named:
        return ""
    return ("\n\nROUTING HINT (from the routing planner, about WHERE TO LOOK -- not evidence, and not a "
            "claim that a row exists): these observed-data families were flagged as implicated in this "
            "question: " + ", ".join(named) + ". Look them up unless the question makes them irrelevant. "
            "A lookup that returns no_rows or not_known is reported as such; never invent a figure to "
            "satisfy the hint.")


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
                # D-PQ FIX-3 (D-CW-4 R4): "per the table's period format" left the ONE rule that actually
                # decides whether a marketing-year read returns rows unstated at the only place the model
                # reads before choosing a value. The measured failure: an ESR destination leg queried
                # market_year 2026 at a mid-2026 as-of and got no_rows, because the marketing year in
                # progress is 2025/26 -- keyed 2025. A wrong year is INDISTINGUISHABLE from an absence at
                # the row level, so the model reported "no data" for a series that is fully populated.
                "period": {"type": "string", "description":
                           "the table's period value -- a calendar year, or a MARKETING YEAR. THE SPELLING "
                           "IS PER CARD (some marketing-year tables want a single year like '2025', "
                           "others a split label like '2025/26' -- the card says which), but WHICH "
                           "marketing year you mean is the same rule everywhere: it is named by the year "
                           "it STARTS. MY 2025/26 is '2025' (or '2025/26'), never '2026'. A date belongs "
                           "to the marketing year that STARTED on or before it -- US corn and soybeans "
                           "start Sep 1, US wheat starts Jun 1 -- so in the FIRST HALF of a calendar year "
                           "the marketing year in progress is the PREVIOUS one: at an as-of in mid-2026 "
                           "the current US corn/soybean marketing year is 2025/26, keyed 2025. Passing "
                           "'2026' there asks for a crop year that has not opened and returns NO ROWS. "
                           "When unsure OMIT this and window with period_start / period_end instead -- a "
                           "wrong period reads as 'no data' and you cannot tell it apart from a real "
                           "absence, so never report one as the other."},
                "period_start": {"type": "string", "description": "YYYY-MM-DD window start (date-grained tables)"},
                "period_end": {"type": "string", "description": "YYYY-MM-DD window end (date-grained tables)"},
                # W3.1 item 2 -- the DELIVERY-MONTH dimension, declared the day silver_futures_eod was
                # whitelisted. The model can only emit parameters the schema NAMES: while this was absent
                # a "December corn" ask simply never named an expiry, was widened to the whole curve, and
                # agg=latest answered it with the NEAREST LISTED expiry -- a number that is not December's,
                # wearing December's label. Both forms are described because they are the two different
                # reads: ONE month is a named-contract level, SEVERAL are a term-structure/curve read at a
                # single as-of.
                "contract_month": {"type": "string", "description":
                                   "delivery month(s) of a per-expiry futures table (silver_futures_eod). "
                                   "One month as 'YYYY-MM' (e.g. '2026-12') reads THAT contract; a "
                                   "comma-separated list ('2026-12,2027-03,2027-05') reads the CURVE "
                                   "across those expiries at one as-of, one row per expiry. Omit only if "
                                   "the question is not about a particular delivery month -- an omitted "
                                   "month returns every listed expiry in the window, and a latest-value "
                                   "read then returns the NEAREST listed expiry, which is NOT 'the front "
                                   "month' and NOT 'the price'. Never quote a bare level as 'the price': "
                                   "say which expiry it is (every row carries its own contract_month, "
                                   "settle_kind and currency), or read several and describe the curve."},
                # The default is 'latest' and it was previously UNDESCRIBED, which is how the curve read
                # above stayed unreachable in practice: 'latest' means the newest observation, and on a
                # per-expiry table with delivery months NAMED that is the newest session FOR EACH named
                # expiry (one row per expiry). Said plainly here so the curve form is callable as written.
                # D-PQ A' -- `front_expiry` is THE EXCHANGE-SETTLE ANCHOR, and it is declared here because
                # the model can only emit what the schema NAMES. While it was absent, "what did CBOT corn
                # settle at" had exactly two reachable answers: name an expiry (which the asker had not),
                # or read the whole curve and quote the NEAREST LISTED one as "the price". The named,
                # versioned front-month rule has existed since W2 and the cascade has called it since W3.3;
                # this is the same rule, reachable from a lookup.
                "agg": {"type": "string",
                        "enum": ["latest", "series", "sum", "mean", "max", "min", "front_expiry"],
                        "default": "latest",
                        "description": "how to read the window. 'latest' = the newest observation on or "
                                       "before the as-of -- on a per-expiry futures table with "
                                       "contract_month(s) named it returns the newest session FOR EACH "
                                       "named expiry (that is the curve at one as-of, one row per "
                                       "expiry); 'series' = every observation in the window, oldest -> "
                                       "newest; sum/mean/max/min collapse the window to one number; "
                                       # A-prime review, STYLE 2: the GUARD is card-driven (a card must
                                       # declare roll_input_cols + contract_month_col), not a hardcoded
                                       # table name -- so the description says WHICH KIND of card rather
                                       # than naming the one that qualifies today, which would drift on
                                       # the second per-expiry card while still reading as authoritative.
                                       "'front_expiry' (per-expiry exchange-settle cards -- today that "
                                       "is silver_futures_eod) = THE FRONT-MONTH "
                                       "EXCHANGE SETTLE -- the newest session on or before the as-of, "
                                       "with the front delivery month chosen by the house's one named, "
                                       "versioned roll rule. Use it for 'what is corn trading at' / "
                                       "'where did CBOT wheat settle' when the question names no delivery "
                                       "month: it returns ONE row carrying its own contract_month, "
                                       "settle_kind, currency and unit, so say which expiry and which "
                                       "kind of print it is. It takes NO contract_month (it SELECTS one) "
                                       "and NO period_start/period_end (it is one session's level, never "
                                       "a front-month series -- that would splice across the roll). If it "
                                       "returns nothing, the rule could not be run for that contract: say "
                                       "so, or name a delivery month -- never fall back to another "
                                       "table's price and call it the futures level."},
                # D-CW-1c -- the twelfth NumberQuery field, and the only one the schema never declared.
                # The model can only emit what the schema NAMES, so while this was absent EVERY series read
                # ran at the 5000 cap with no way to say otherwise: a daily card asked for "the full
                # history" came back truncated, and the truncation is silent at the row level (a capped
                # series looks exactly like a short one). Declared here so a long read is a DELIBERATE
                # window rather than an accident of the default.
                #
                # D-PQ FIX-1/FIX-2 (D-CW-4 R3). Declaring the knob had a cost the census did not price:
                # the model reached for SMALL caps as a way to keep a read cheap, and the compiler was
                # still ASCENDING, so `limit=1` on a monthly card served a Nov-2019 print as "the same
                # month". Two things changed. (a) The ORDER is fixed at the compiler (the serving lanes
                # resolve newest-first by default now, answer._series_newest_first_on), so the "NEWEST
                # ones" sentence below is TRUE rather than aspirational. (b) The description now says
                # plainly that lowering the cap is not a way to spend less -- which is the reading that
                # produced the narrow single-table calls, and the same reading that made a multi-leg
                # margin read look expensive enough to skip. Prompt-side; the probe re-run adjudicates.
                "limit": {"type": "integer", "default": 5000, "minimum": 1, "maximum": 5000,
                          "description":
                          "maximum number of rows a 'series' read returns (default 5000, the cap; you may "
                          "lower it, never raise it -- a larger value is clamped back to 5000). A window "
                          "with MORE observations than this is TRUNCATED, and the rows kept are the "
                          "NEWEST ones in the window (the series is read newest-first for exactly that "
                          "reason and handed back to you oldest -> newest). So a small limit on a long "
                          "card means 'the last N observations', not 'the first N'. LEAVE IT ALONE unless "
                          "you specifically want the last N observations: it is not a cost lever, it does "
                          "not make a lookup cheaper or an answer shorter, and it is never a substitute "
                          "for a second lookup -- a question whose legs live on several tables wants "
                          "several full reads, not one narrowed one. Two rules: (1) pin "
                          "the window you actually want with period_start / period_end rather than "
                          "leaning on the cap -- a daily card holds ~250 rows per year, a weekly one ~52; "
                          "(2) never describe a truncated read as the complete record -- if the rows you "
                          "got start later than the history you asked about, say so, or re-read a "
                          "narrower window."},
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
                # D-AM-17: the spread arm is SCHEMA-ENFORCED named-expiry. The model can only pass what the
                # schema declares, so two required-by-the-stat month names here are what make "never a
                # front-month inference" a structural property instead of a prompt instruction.
                "near_month": {"type": "string", "description":
                               "for `spread` ONLY: the NEARBY delivery month, spelled exactly as the rows "
                               "carry it ('YYYY-MM'). Both legs must be NAMED -- this lookup stores no "
                               "front-month flag and no open interest, so a spread whose legs you did not "
                               "name is refused, never guessed at from the nearest listed expiry."},
                "far_month": {"type": "string", "description":
                              "for `spread` ONLY: the DEFERRED delivery month ('YYYY-MM'). The computed "
                              "figure is far minus near, over ONE curve read at a single as-of (agg="
                              "'latest' with BOTH months in contract_month); rows spanning several "
                              "sessions are refused, because then neither leg is a single figure."},
            },
            "required": ["stat", "series_handle"],
        },
    }


def _series_axis(rows: list) -> tuple[list[float], list[str]]:
    """D-AM-17: the handle's numeric series AND its parallel delivery-month label axis, built in ONE pass so
    the drop rule is written once. `stats.spread` selects its two legs BY NAME from the label axis, so a
    label list assembled by a second loop over the same rows would silently misalign the moment the two
    loops disagreed about a droppable cell -- and a misaligned spread subtracts the wrong two contracts
    while looking exactly like a right answer. `contract_month` is query._extras' alias (that module mints
    it; this only reads it) and is "" for every card that has no delivery month at all."""
    vals: list[float] = []
    exps: list[str] = []
    for r in rows or []:
        v = (r or {}).get("value")
        if v is None or isinstance(v, bool):
            continue
        try:
            f = float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
        vals.append(f)
        exps.append(str((r or {}).get("contract_month") or "").strip())
    return vals, exps


def _series_from_rows(rows: list) -> list[float]:
    """The numeric series a handle exposes: the value cell of each row that coerces to a finite number
    (chronological -- the loop appends rows oldest -> newest). Non-numeric / null cells are dropped."""
    return _series_axis(rows)[0]


def _handle_kd(rows: list) -> Optional[str]:
    """The latest knowledge/data date across a handle's rows -- the stat INHERITS it (PIT is a property of the
    input rows, never re-derived)."""
    ds = [d for r in (rows or []) for d in ((r or {}).get("knowledge_date"), (r or {}).get("data_date")) if d]
    return max(ds) if ds else None


# D-AM-17: the per-row labels a stat's injected [N] row INHERITS from the rows it was computed over.
# tables.yaml:954-963 is doctrine for the price card and it cuts BOTH ways: "every row comes back carrying
# its own contract_month, settle_kind and currency -- state them with the number, never a bare figure" AND
# "never attach a delivery month to a row that has none". A stat row minted {value, unit, knowledge_date}
# is the first half's failure -- a derived price figure with no expiry and no provenance kind on it, which
# is precisely the bare level the card forbids quoting. So the labels ride the injected row, but ONLY when
# they are UNAMBIGUOUS across the source rows (exactly one distinct non-empty value): a curve read spans
# many expiries, its derived figure has no single delivery month, and picking one would be the second
# half's failure. `currency` is deliberately NOT lifted here -- it is the deferred X2 item (D-FR-6), and
# lifting it as a side effect of this change would silently widen the unit guard's inputs.
_STAT_ROW_LABELS = ("contract_month", "settle_kind")


def _handle_labels(rows: list) -> dict:
    """The unambiguous subset of _STAT_ROW_LABELS across `rows` -- absent (not blank, not guessed) whenever
    the rows disagree, or do not carry the label at all."""
    out: dict = {}
    for k in _STAT_ROW_LABELS:
        seen = {str((r or {}).get(k) or "").strip() for r in (rows or [])}
        seen.discard("")
        if len(seen) == 1:
            out[k] = seen.pop()
    return out


# S4 (D-AM-17): the stats whose answer is a claim about the TIME axis of the rows -- a positional walk
# (streak / window_change / yoy_delta) or a rank inside "its own history" (percentile / zscore). On an
# INTERLEAVED read the first three are wrong by the expiry multiplicity (21 rows of a 13-expiry curve is
# ~1.6 sessions, not 21 trading days) and the last two rank a value inside a pool that mixes 13 delivery
# months with 22 sessions, which is not that value's own history. THREE ARE DELIBERATELY OUT, and it is
# not an oversight: `extrema` is order-independent and its min/max IS a true high and low of rows actually
# read; `spread` is a CURVE statistic whose own named-expiry refusals already reject an interleaved read
# (each named month lands on more than one row); `revision_count` walks the VINTAGE axis, which no
# per-expiry price card has, so an interleaved shape cannot reach it.
_TIME_AXIS_STATS = frozenset({"streak", "window_change", "percentile", "zscore", "yoy_delta"})


_FUTURES_Z_TABLES = frozenset({"silver_futures_eod"})


def _z_window(requested, src_table, n_points=None):
    """G4c(i): the DECLARED z window for a futures series -- callers may narrow it, never silently widen.

    `serving.stats.futures_z.window_sessions` (params.yaml, one block below silverleg's PSD
    window_years and FX window_days) is the default when a caller names no window and the
    ceiling when it names a bigger one. It is never silent: `_stat_calls` stamps the effective
    window on the injected [N] row and `citations.from_number` renders it, so a narrowed window is
    a fact the reader can see. Non-futures series return `requested` untouched -- None keeps
    stats.zscore's own 'all of history' semantics, byte-identical to pre-G4c.

    THE LEN CLAMP (review FATAL, wf_6906ea5b): stats.zscore treats a NON-None window as a
    REQUIRED history depth (stats.py declines when len(hist) < window, and only truncates
    after that check) -- so injecting a bare 250 where the caller passed None would convert
    'all of history' into a hard 250-point requirement, and every shorter-than-250 futures
    handle (a model-emitted `limit`, a period-scoped ask, a thinly-listed month) would flip
    from computing to declining. The default arm therefore clamps to the series length: the
    z ranks against ALL available points up to the declared ceiling, the row stamps the
    honest effective window, and stats' own MIN_ZSCORE_N floor still declines genuinely
    thin series. An EXPLICIT `requested` keeps stats' require-this-depth contract untouched
    (asking for a 200-point rank over 120 points is honestly refused, as before G4c)."""
    if src_table not in _FUTURES_Z_TABLES:
        return requested
    ceiling = int(_pr.get("serving.stats.futures_z.window_sessions", 250))
    if requested is not None:
        return min(int(requested), ceiling)
    return ceiling if n_points is None else min(ceiling, int(n_points))


def _dispatch_stat(stat: str, inp: dict, handles: dict) -> dict:
    """Resolve the referenced turn-scoped handles and run ONE stats function. Returns the stats contract dict
    (declined or not). RAISES KeyError for an unknown/cross-turn handle (the caller turns it into a refusal)."""
    sh = inp.get("series_handle")
    vh = inp.get("value_handle")
    for h in (sh, vh):
        if h is not None and h not in handles:
            raise KeyError(h)
    # -- U1 THE UNIT-COMPATIBILITY GUARD (FUTURES_READPATH D-FR-4..8). ---------------------------------
    # THIS is the only function in the module that resolves BOTH handles, which is why the guard sits
    # here and not in _exec_stat (which would have to duplicate the resolution). It fires ONLY on a
    # two-handle stat -- `value_handle is not None` -- because a one-handle stat has nothing to compare
    # a unit against; the trigger deliberately says nothing about the OUTPUT unit, since _STAT_UNIT
    # below overwrites percentile's and zscore's unit to "percentile"/"sigma" before anything downstream
    # can see the inputs disagreed.
    #
    # ORDERING IS LOAD-BEARING, NOT COSMETIC: emptiness is checked BEFORE units. A lookup that returned
    # no rows mints {"series": [], "unit": None} (the mint at the bottom of the loop reads rows[0]), and
    # a COVERAGE-DECLINED silver_futures_eod read returns exactly `"rows": []` -- i.e. this shape arrives
    # on the very path this wave exists to fix. Under the three-state rule known-vs-None declines, so a
    # unit-first order would hand the model "quoted in different units (US cents/bushel against None)"
    # as the explanation for an EMPTY READ, and the model would narrate it. Emptiness first also upgrades
    # today's behaviour: an empty value handle currently raises IndexError inside _val() and is classed
    # `status: "error"`, which _STATUS_STATE routes to a different C2 state than `declined`.
    #
    # The refusal routes through stats' own _decline contract (via ST.unit_decline / ST.empty_series_decline)
    # so it reaches the model as `status: "declined"` with NO [N] row injected, and mints no preface: the
    # *_preface register is census-pinned and joining it would silence the C2 question-shape line on every
    # co-occurring turn. `n` is the SERIES handle's own length -- the sample the stat WOULD have run over --
    # never a fabricated 0 a reader could mistake for "no data".
    if vh is not None:
        _sh_series = handles[sh].get("series") or []
        _n = len(_sh_series)
        if not _sh_series:
            return ST.empty_series_decline(stat, _n, "history series")
        if not (handles[vh].get("series") or []):
            return ST.empty_series_decline(stat, _n, "series being compared against that history")
        _ua, _ub = handles[sh].get("unit"), handles[vh].get("unit")
        if not ST.unit_compatible(_ua, _ub):
            return ST.unit_decline(stat, _n, _ua, _ub)
    # -- S4 THE CURVE-AS-CALENDAR GUARD (D-AM-17). --------------------------------------------------
    # The discriminator and its reason string are query.py's, unchanged and uncopied -- this is only the
    # seam that finally CALLS them: they shipped with zero production callers, so an interleaved read (many
    # delivery months AND many sessions) has until now been walked positionally with no signal anywhere in
    # the result. `shape` is measured at the lookup mint and carried on the handle; a handle without one
    # (a chained stat result, a post-answer leg) reads as an empty shape and computes exactly as before,
    # which is what keeps every pre-wave path byte-identical. `n` follows the unit guard's convention: the
    # series handle's OWN length, the sample the stat WOULD have run over -- never a fabricated 0.
    if stat in _TIME_AXIS_STATS:
        _shape = handles[sh].get("shape") or {}
        if Q.curve_as_calendar(_shape):
            return ST.curve_as_calendar_decline(stat, len(handles[sh].get("series") or []),
                                                Q.curve_as_calendar_reason(_shape))
    series = handles[sh]["series"]

    def _val():
        return handles[vh]["series"][-1] if vh is not None else (series[-1] if series else None)

    if stat == "streak":
        return ST.streak(series, inp.get("direction"))
    if stat == "percentile":
        return ST.percentile(_val(), series)
    if stat == "zscore":
        return ST.zscore(_val(), series,
                         window=_z_window(inp.get("window"), handles[sh].get("src_table"),
                                          len(series)))
    if stat == "window_change":
        return ST.window_change(series, inp.get("t1"), inp.get("t2"))
    if stat == "revision_count":
        return ST.revision_count(series, inp.get("direction"))
    if stat == "extrema":
        return ST.extrema(series)
    if stat == "yoy_delta":
        p = inp.get("periods")
        return ST.yoy_delta(series, periods=1 if p is None else p)
    if stat == "spread":
        # The label axis rides the handle beside the numeric one (_series_axis builds both in one pass).
        # A handle that never had one -- a chained stat result, an ESR/pattern-records leg -- arrives as []
        # and stats.spread REFUSES it in the same breath as a cash reference: no delivery months, no two
        # legs to difference. That is why "the handle is not a single-as-of curve" needs no second shape
        # verdict here; the label axis IS the evidence, and it names what came back.
        return ST.spread(series, handles[sh].get("expiries") or [],
                         inp.get("near_month"), inp.get("far_month"))
    raise ValueError(f"unknown stat {stat!r}")   # unreachable: the enum + STAT_NAMES gate this upstream


def _stat_provenance(stat: str, inp: dict, handles: dict) -> dict:
    """{stat, params, input_handles} stamped onto every injected stat [N] row so the guard + citations carry
    the exact derivation (which handles, which scalar params)."""
    params = {k: inp[k] for k in ("direction", "window", "t1", "t2", "periods", "value_handle",
                                  "near_month", "far_month")
              if inp.get(k) is not None}
    ins = [h for h in (inp.get("series_handle"), inp.get("value_handle")) if h]
    return {"stat": stat, "params": params, "input_handles": ins}


# The result of a percentile/streak/z-score is NOT in the series' unit -- it is its own kind of quantity. Only
# the magnitude-preserving stats (window/YoY change, extrema) inherit the series unit.
# D-AM-17 puts `spread` on the SYNTHETIC side, and that is the level-vs-delta hole D-FR-17(ii) named being
# fenced for the one stat added since: a spread is a DIFFERENCE between two contracts, and inheriting the
# raw price unit would make it known-vs-known-EQUAL against a distribution of price LEVELS -- so a carry of
# +12.5 would rank inside a pool of ~430 levels and compute a 0th percentile, exactly the wrong number the
# unit guard exists to refuse. With its own kind-label the chained handle is known-vs-known-DIFFERENT and
# the guard declines. The physical unit is not lost to the reader: it stays on the two source rows the
# spread was computed over, and the injected row names both legs (see _stat_calls).
_STAT_UNIT = {"streak": "consecutive periods", "revision_count": "consecutive revisions",
              "percentile": "percentile", "zscore": "sigma", "spread": "spread"}


def _stat_calls(stat: str, res: dict, prov: dict, series_unit: Optional[str], kd: Optional[str],
                labels: Optional[dict] = None, src_table: Optional[str] = None,
                src_metric: Optional[str] = None) -> list[dict]:
    """Turn a SUCCESSFUL stats result into one (or, for extrema, two) synthetic lookup call(s) -- each an
    [N] row carrying the computed value so the all-numbers guard value-checks it. A decline injects nothing.

    `labels` is the unambiguous expiry/settle-kind pair inherited from the source rows (_handle_labels):
    absent for every card that carries no such column, so those rows are byte-identical to pre-D-AM-17."""
    unit = _STAT_UNIT.get(stat, series_unit)
    lab = dict(labels or {})
    if stat == "spread":
        # A spread spans TWO delivery months, so it can never carry a single `contract_month` (the card's
        # own rule: never attach a delivery month to a row that has none). It names both legs instead,
        # under their own keys -- writing a pair into the `contract_month` alias would put a non-month
        # string in the one field every downstream expiry reader parses as a month.
        lab["near_month"], lab["far_month"] = res.get("near"), res.get("far")
    if stat == "zscore":
        # G4c(iii), T1-4's shape applied to the z row. A carry figure with no delivery months was a
        # number whose meaning was missing; a sigma with no WINDOW and no SERIES is the same defect
        # in the other axis -- "compute_stat zscore corn_cbot = 2.1 sigma" is unauditable and
        # unreproducible. `res["window"]` is stats.zscore's OWN field (stats.py:313 defaults it to
        # n), so the row can never imply a window that was not used, including after `_z_window`
        # narrows a caller's ask. BOTH OR NEITHER: a window with no series names a length with no
        # subject; a series with no window implies the whole history. Written under their own keys,
        # never into `contract_month`, which every downstream expiry reader parses as a month.
        lab["z_window"] = res.get("window")
        lab["z_series"] = ".".join(x for x in (src_table or "", src_metric or "") if x) or None
    def _row(val, metric):
        q = {"table": STATS_TOOL_NAME, "metric": metric}
        return {"query": q, "rows": [{"value": val, "unit": unit, "knowledge_date": kd, **lab}],
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
        # D-AM-17 KILL-SWITCH PARITY: the spread arm's steering rides the SAME `stats_on` string as the
        # tool schema's `spread` enum member and its near_month/far_month properties, so the model is
        # never told about an arm it does not have -- and never has one it was not told how to call.
        "- A CARRY or CALENDAR SPREAD between two delivery months is that same kind of request, not "
        "arithmetic you do: look up the CURVE at one as-of (agg='latest' with BOTH months in "
        "contract_month), then REQUEST compute_stat with stat='spread' and near_month / far_month NAMED. "
        "The difference (far minus near) comes back as an observed [N] figure. You must name BOTH legs -- "
        "there is no front month in this lookup (no front-month flag, no open interest), so a spread is "
        "refused rather than guessed, and a read spanning several sessions is refused too.\n"
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
        "- silver_cot is CFTC MANAGED-MONEY positioning (weekly, per contract slug): silver_cot.open_interest, "
        "silver_cot.mm_long/.mm_short/.mm_net/.mm_spread [contracts], silver_cot.mm_pct_oi (SIGNED net percent "
        "of OI; negative = net short), and silver_cot.mm_net_z_3yr / .mm_pct_oi_z_3yr (sigma vs a 3-yr mean). "
        "Positioning is HISTORICAL CONTEXT "
        "ONLY -- report observed levels + z + the report date in PAST tense; NEVER forecast a squeeze, never "
        "say positioning will unwind or must revert, and never let it drive a price call or a cascade fork. It "
        "is lag-published (about 6 days) and can be several weeks stale, so ALWAYS cite the report date -- "
        "staleness must be visible, not hidden.\n"
        + stats_bullet + pattern_bullet +
        # GENERAL month-grain rule (task #142). The IOD bullet below already carries it; this states it ONCE
        # for every month-grained card (oni + iod + gold_weather_z) so the named-month discipline is not a
        # per-card accident. It is prompt-side discipline only -- the deterministic period-mismatch guard
        # (agent.py, _period_mismatch_scope_note / _period_mismatch_preface) is the enforcement.
        "- MONTH-GRAINED tables (silver_noaa_oni, silver_noaa_iod, gold_weather_z) are identified by year + "
        "month, and their as-of guard is month-grained: agg=latest returns the newest month ON OR BEFORE the "
        "as-of date, which is the WRONG row whenever the question names a particular month. When the question "
        "names a historical month or span ('the DMI in October 1997', 'heat stress over June-August 2012'), "
        "the lookup MUST carry period_start AND period_end as 'YYYY-MM' for exactly that month or span -- "
        "agg=latest is only for 'the newest reading'. If a returned row's year+month is not the month asked "
        "about, say so plainly ('the lookup returned June 1998, not October 1997') and re-run it scoped to "
        "that month; NEVER explain the difference as a publication lag, a reconstruction delay, or the month "
        "being unpublished or unavailable -- an unscoped lookup simply did not request that month.\n"
        "- silver_noaa_oni has NO date column: window months with period_start/period_end as 'YYYY-MM', or use "
        "agg=latest for the most recent month on/before the as-of date.\n"
        "- silver_noaa_iod is the Indian Ocean Dipole (DMI), a GLOBAL monthly climate index -- NO commodity or "
        "country argument. Window months with period_start/period_end as 'YYYY-MM' for a named historical month "
        "or span (agg=latest answers 'the newest reading', never 'that month'), or agg=latest for the most "
        "recent month on/before the as-of date. Report the DMI (or its 3-month average) in degC + the month; "
        "values are SST anomalies against a fixed 1991-2020 climatology (NOAA CPC, ERSSTv5). It is a LIVE "
        "monthly series published about 30-45 days after each month ends (45-day freshness SLA), so its newest "
        "month normally trails the as-of date by roughly one month: ALWAYS cite the reading's own month -- "
        "staleness must be visible, not hidden; a dated reading is stated with its month, NEVER as 'the current "
        "DMI'. That publication lag is the normal cadence, NOT a gap: never report a month as unavailable or "
        "unpublished when the lookup simply was not scoped to it. Positive DMI is the East-Africa/Australia "
        "teleconnection. It is an observed climate index, never a price and never a crop-impact forecast.\n"
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
        # D-PQ FIX-2b (2026-08-07) -- THE MARGIN/CRUSH MULTI-LEG CUE, MOVED TO THE SEAM THAT BINDS.
        # FIX-2's first attempt put this cue in `dispatch.ToolSpec.when_to_use`, on the hypothesis that the
        # row was being routed away from numbers. THE RE-RUN FALSIFIED THAT HYPOTHESIS, and the falsifier is
        # structural rather than statistical: `dcw_us_ethanol_margin` routed HYBRID in both arms, and
        # `orchestrator.run_hybrid` runs `answer_numbers` UNCONDITIONALLY on that lane -- so no wording in
        # the router's registry block could have been the cause, and no wording there can be the cure. The
        # agent itself was handed the question and emitted ZERO tool calls (6 lookups BEFORE the wave, 0 in
        # both wired arms). NEW HYPOTHESIS, stated so the next probe can falsify it too: the loss is the B1
        # ROUTING HINT going quiet. Where the planner names families the agent looks them up; where it names
        # none the line disappears, and a question phrased as PRESSURE/ECONOMICS rather than as a figure has
        # nothing in this prompt telling the agent that a margin is made of observed series at all -- every
        # bullet above is a per-table convention, and margins are the one shape that lives ACROSS tables.
        # So the cue goes here, unconditionally, where it does not depend on the planner having spoken.
        # (The planner-side half is the data_families rule in dispatch.PLANNER_SYS; the two are belt and
        # braces, and this one is the belt.)
        "- A MARGIN, CRUSH, GRIND or PROCESSING-ECONOMICS question ('how much pressure is the ethanol grind "
        "under', 'are crush margins squeezing demand') IS a numbers question, and its legs live on SEVERAL "
        "tables -- so look up ALL of them rather than treating the question as commentary: (a) the INPUT "
        "cost from silver_pink_sheet (natural_gas_us_usd_mmbtu / natural_gas_eu_usd_mmbtu for a grind, the "
        "oil and meal series for a crush -- each with its own *_zscore_5yr metric beside it), (b) the USE "
        "line from silver_wasde (domestic_total, the ethanol/crush use line, ending_stocks) for the "
        "quantity flowing through the plant, and (c) the OUTPUT or FEEDSTOCK price from silver_futures_eod "
        "(agg='front_expiry' when the question names no delivery month). There is no margin metric and no "
        "margin table anywhere in this registry: state the observed LEGS with their units and dates and let "
        "the reader combine them -- never compute, estimate or assert a margin level yourself, and never "
        "answer 'the record does not carry a margin figure' without having looked up the legs that do "
        "exist.\n"
        # D-PQ FIX-4 (2026-08-07) -- THE FULL-HISTORY SUPERLATIVE. Measured on dcw_probe_v1 row 11
        # (`dcw_full_record_range`): a corn settle series came back AT the 5000-row cap, the engine stamped
        # the truncation correctly, and the answer still opened "the full-history trading range on record
        # for CBOT corn sits between 371.5 and 528.5" with no date span anywhere in the sentence. The stamp
        # was right and unread -- it reached `format_provenance` and the eval report but not the synthesis
        # prompt. That thread is now closed on the render side (citations.from_number appends the
        # annotation + the covered span to the [N] label); this bullet is the rule the annotation asks the
        # model to follow, stated once, for every series card rather than per-table.
        "- A read that comes back AT its row cap is NOT the complete history, and its [N] line says so and "
        "names the span it DOES cover. When you see that annotation you have exactly two honest options: "
        "state the covered span with the figure ('the widest range in the 2019-2026 window on record here "
        "is ...'), or drop the superlative. NEVER write 'full history', 'the full record', 'all-time', "
        "'ever', 'on record' or 'the widest ever' over a truncated read -- and never over ANY read whose "
        "own rows do not reach back to the start of the history you are claiming. If the question asked "
        "for the whole history, re-read it WINDOWED (period_start / period_end) rather than raising the "
        "cap, and if you cannot, say plainly which window you actually have.\n"
        "- Each returned row is self-identifying (it carries its own period / year / month) — read those to confirm "
        "which observation each number is; results are chronological, so use agg=latest (not the first row) for "
        "the most recent value.\n\n"
        f"## Tables\n{cards}"
    )


LIMIT_CEILING = int(Q.NumberQuery.model_fields["limit"].default)   # 5000 -- derived, never a second copy


def _clamp_limit(v) -> int:
    """D-CW-1c: a model-supplied `limit` may only NARROW the read. Declaring the field in the tool schema
    hands the model a knob on the SCAN SURFACE, and the one direction that is never safe is up: the 5000 cap
    is what bounds a series read's bytes, and the S3 LIST-storm work (Jul-2026, $134) closed exactly this
    surface. So the ceiling is the field's own default -- read from the model, never re-typed -- and anything
    above it, below 1, or not an integer at all (a float, a string, None) collapses back to the default.
    Clamping rather than raising is deliberate: a too-large limit is a mis-sized request, not a leakage or
    attribution error, and refusing the whole lookup over it would cost a real answer."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return LIMIT_CEILING
    return LIMIT_CEILING if n > LIMIT_CEILING or n < 1 else n


def _forced_spec(asof: str, inp: dict) -> Q.NumberQuery:
    """Build a NumberQuery from the model's tool input, FORCING asof (drop any asof the model tried to pass)
    and CLAMPING limit to the cap (D-CW-1c -- the field is model-emittable now, and only downward)."""
    data = {k: v for k, v in inp.items() if k != "asof"}
    if "limit" in data:
        data["limit"] = _clamp_limit(data["limit"])
    return Q.NumberQuery(asof=asof, **data)


# -- D-PQ SCHEMA-1: the SPEC-VALIDATION error, said in words the model can act on --------------------────
# THE MEASURED FAILURE (dcw_probe_v1 row `dcw_nass_conditions_split`, 2026-08-07): EIGHT of sixteen
# lookups on one turn failed with the raw pydantic dump
#   "1 validation error for NumberQuery\nmetric\n  Field required [type=missing, input_value={'asof': ...
# The tool schema ALREADY declares `required: [table, metric]` -- this is not a missing fence, it is a
# fence whose refusal text taught the model nothing. `metric` is the ONE field a five-metric card invites
# you to leave off ("give me Iowa's conditions" names a state, not a column), the model burned half its
# six-call budget rediscovering that, and the retries then landed with no budget left to re-scope.
#
# The remedy is the one the ESR / period-mismatch scope notes already use on this loop: say WHAT was
# omitted, WHAT the legal values are, and WHAT the next call should look like -- on the payload the model
# reads, while it still has call budget to repair itself. Nothing about the fence moves: `metric` stays
# required, an invalid call still returns status='error' and cites nothing.
_ONE_METRIC_RULE = ("ONE lookup = ONE metric. A card with several metrics needs one call per metric "
                    "(and one call per scope value), never a call that omits `metric` to sweep them.")


# -- D-PQ CLASS-1: the CARD-LEVEL commodity class fence -----------------------------------------------
#
# THE MEASURED LEAK, TWICE. `silver_nass_crop_progress` is USDA NASS: six US contract slugs, US states,
# nothing else. The fence for that was PROSE in the card's `notes` ("THIS TABLE IS THE UNITED STATES AND
# NOTHING ELSE"), and prose fences move the leak rather than close it -- v2 put a US condition on a
# french_wheat ask, v3 put one on a rough-rice / India-monsoon row. A rule the model can read is a rule the
# model can also not read.
#
# WHAT IS FENCEABLE HERE, EXACTLY, AND WHAT IS NOT. This seam sees the SPEC and the REGISTRY and nothing
# else, so it can enforce exactly one thing deterministically: SLUG MEMBERSHIP -- is the commodity this
# lookup names one of the values the card declares it serves? That is a closed-set test on card-declared
# data and it cannot wobble run to run.
#
# WHAT REMAINS BEHAVIOURAL, STATED PLAINLY SO NOBODY LATER MISTAKES THIS FOR THE WHOLE FIX: whether the
# queried commodity matches the ROW'S OWN CONTRACT (the v3 shape -- a legal slug, wrong question) is NOT
# decidable here. `answer_numbers` is handed a QUESTION and an as-of; it is never handed the routed
# contract, and it cannot be: on the hybrid lane it runs in a worker thread CONCURRENTLY with the walk that
# does the routing (orchestrator.run_hybrid), so at lookup time the answer's contract set does not yet
# exist. `families` is a HINT, not a scope. Closing that half means threading routing into the numbers
# lane -- a real plumbing change with its own ordering risk -- and until it is done, a corn-conditions
# lookup on a rice question is refused only if `corn_cbot` is off this card, which it is not.
class CommodityOffCard(ValueError):
    """A lookup naming a commodity the card does not serve (D-PQ CLASS-1). Its message is the remedy."""


def _check_commodity_class(spec, reg: NumbersRegistry) -> None:
    """RAISE `CommodityOffCard` when the spec names a commodity outside the card's declared closed set.
    A card WITHOUT a declaration (`commodity_values` empty) gets no fence and no behaviour change --
    opt-in by declaration, so the count of fenced cards is a property of the registry, not of this
    function, and is deliberately not restated here."""
    cid = str(getattr(spec, "commodity", "") or "").strip()
    tid = str(getattr(spec, "table", "") or "").strip()
    if not cid or not tid:
        return
    try:
        allowed = list(reg.get(tid).commodity_values or [])
    except Exception:  # noqa: BLE001 -- an unknown table is the OTHER fence's business, not this one
        return
    if not allowed or cid in allowed:
        return
    raise CommodityOffCard(
        f"lookup REFUSED -- {tid} does not serve commodity {cid!r}. This card serves exactly these and "
        f"nothing else: {', '.join(allowed)}. It is a CLOSED set, not a default: there is no row for "
        f"{cid!r} here and no neighbouring commodity on this card stands in for it. Either re-issue the "
        f"call with one of the listed values (and say out loud, in the answer, which commodity and which "
        f"geography the figure belongs to), or find another table -- do NOT substitute a different "
        f"commodity's number for the one that was asked about. Nothing was queried.")


class PeriodRequiredOffCard(ValueError):
    """A period-less lookup on a card that declares period_required (D-LD wf_31e951c7 FATAL).

    The WAP class: every release prints MULTIPLE period rows side by side (the prior crop's
    preliminary beside the current crop's projection), so a period-less agg=latest is not a
    default -- it is a WRONG-CROP answer (the tiebreak picks the LOWEST period). The message
    is the remedy, the CommodityOffCard idiom on the period axis."""


def _check_period_required(spec, reg: NumbersRegistry) -> None:
    """RAISE `PeriodRequiredOffCard` when the card declares period_required and the spec has no period.
    No declaration (every card but WAP today) -> no fence, no behaviour."""
    tid = str(getattr(spec, "table", "") or "").strip()
    if not tid or str(getattr(spec, "period", "") or "").strip():
        return
    try:
        ts = reg.get(tid)
    except Exception:  # noqa: BLE001 -- an unknown table is the OTHER fence's business, not this one
        return
    if not getattr(ts, "period_required", False):
        return
    raise PeriodRequiredOffCard(
        f"lookup REFUSED -- {tid} requires a period and none was given. Every release on this card "
        f"carries MULTIPLE marketing-year rows side by side (the prior crop's near-final estimate "
        f"beside the current crop's projection), so a period-less read does not have a sensible "
        f"default: it silently returns the WRONG CROP'S number. Re-issue the call naming the period "
        f"in the exact spelling the card's notes state, and say in the answer which marketing year "
        f"the figure belongs to. Nothing was queried.")


def _spec_error(inp: dict, exc: Exception, reg: NumbersRegistry) -> str:
    """A model-actionable message for a rejected tool input. Falls back to the raw exception text for any
    failure that is not a missing/blank required field, so nothing is ever swallowed."""
    if isinstance(exc, (CommodityOffCard, PeriodRequiredOffCard)):
        return str(exc)          # D-PQ CLASS-1: the message IS the remedy -- never truncated, never re-worded
    missing = [f for f in ("table", "metric") if not str((inp or {}).get(f) or "").strip()]
    if not missing:
        return str(exc)[:200]
    parts = [f"lookup REJECTED -- required field(s) omitted: {', '.join(missing)}. " + _ONE_METRIC_RULE]
    tid = str((inp or {}).get("table") or "").strip()
    if "metric" in missing and tid:
        try:
            names = sorted(reg.get(tid).metrics)
        except Exception:  # noqa: BLE001 -- an unknown table is the other half of `missing`
            names = []
        if names:
            parts.append(f"{tid} serves these metrics, and you must name exactly one: {', '.join(names)}.")
    parts.append("Re-issue the call with the field filled in; nothing was queried.")
    return " ".join(parts)


def tables_queried(calls: list) -> list[str]:
    """D-LD Sitting-A (Lens C, LIST B "UNMEASURABLE-USAGE"): WHICH CARDS THIS TURN ACTUALLY TOUCHED.

    THE HOLE THIS CLOSES. Every lit card was unmeasurable in production: `Leviathan/Serving` carries no
    `table`/`card`/`metric_id` dimension anywhere in its 43 metric names, `tracekeys` declared no table
    key, and the numbers stack prints nothing per lookup -- so the only per-table record in the estate was
    `eval.py`'s offline per-answer artifact. "Which cards do users actually hit" was answerable from
    evals and from nowhere else. The call list has carried the answer all along; nobody lifted it.

    DERIVED, NEVER STAMPED PER LOOKUP: the ONE producer is the finished `calls` list (the same list every
    citation, footer and [N] handle is built from), so this can never disagree with the provenance the
    reader sees. Sorted + de-duplicated -> a stable set, not a call-order log; a card read four times
    appears once, because the question this answers is REACH, not volume (`MsNumbers` is the lane's
    volume metric and it is undimensioned by table on purpose).

    `compute_stat` IS EXCLUDED, and it is the only exclusion. `_stat_calls` mints synthetic [N] rows whose
    `query.table` is the STATS TOOL NAME rather than a card id (agent.py `_row`) -- a pseudo-table that is
    in no registry, has no card, and would otherwise appear in a per-table usage census as the most-read
    "table" in the estate. Everything else counts, INCLUDING declined/errored/no_rows lookups: a card the
    agent reached for and got nothing from is a card that was queried, and dropping those would make the
    census read cleanest exactly where serving is most broken."""
    seen: set[str] = set()
    for c in (calls or []):
        tid = str((((c or {}).get("query") or {}).get("table") or "")).strip()
        if tid and tid != STATS_TOOL_NAME:
            seen.add(tid)
    return sorted(seen)


def answer_numbers(question: str, asof: str, *, client=None, model: str = HAIKU, reg: Optional[NumbersRegistry] = None,
                   query_fn=None, max_calls: int = 6, max_tokens: int = 1500, on_call=None,
                   families: Optional[list] = None, futures_newest_first: bool | str = False) -> dict:
    """Run the agent loop. `client` = an anthropic.Anthropic (real = billed); `query_fn(sql)->rows` overrides Athena
    (tests). Returns {answer, calls:[{query, rows}]} — calls carry the exact provenance behind every number.
    `on_call(n_calls, table)` (default None = byte-identical) fires after each executed lookup — the SSE
    progress hook (5.6 W5); errors are swallowed.

    `families` (B1, default None = byte-identical) are the planner's data_families: a steering HINT appended
    to the user turn naming which observed-data tables were flagged as implicated. The orchestrator reads the
    kill-switch and passes the list or nothing — this function reads no environment for it, so the engine is
    gated by the ARGUMENT and a mis-plumbed enable can never steer an unasked turn.

    `futures_newest_first` (FUTURES_READPATH S1, D-FR-10) follows the SAME contract, for the same reason:
    the env is read at ONE seam, `answer._futures_newest_first_on()`, and the orchestrator threads the bool
    down to both of this lane's entry points (run_numbers_only and run_hybrid's worker thread). This
    function reads no environment for it either, so a mis-plumbed enable cannot flip the read shape on a
    turn nobody asked for. DEFAULT FALSE -> every Q.run below compiles the byte-identical ASC total order,
    which is the rollback. It reaches all THREE reads on this lane: the executor's main lookup, the W3.2
    legacy-level rewrite beside it, and the ESR aggregate legs."""
    # D-AM-5's seat seam, THIRD instance (2026-08-23, the A/B seat wave's lever): env fills the DEFAULT
    # only, exactly like GRAPHRAG_SYNTH_MODEL (answer.py:8766) and GRAPHRAG_DISPATCH_MODEL (dispatch.py:662)
    # -- an explicit caller model always wins, env unset is byte-identical. The docstring's no-env doctrine
    # above covers READ-SHAPE flags (families / futures_newest_first), where a mis-plumbed enable changes
    # what a turn LOOKS AT; the model SEAT changes who reads it, and the estate's two existing seat seams
    # both live in-module. Rollback = unset one var, no deploy.
    if model == HAIKU:
        model = os.environ.get("GRAPHRAG_NUMBERS_MODEL") or model
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
    # B1: the hint rides the USER turn, never the system block -- `system` carries cache_control ephemeral and
    # is byte-stable per (registry, flags), so a per-turn families line there would invalidate the prompt cache
    # on every turn. QUESTION stays last (the recency slot it has always held); absent families -> the string
    # is byte-identical to pre-B1.
    convo: list[dict] = [{"role": "user", "content": f"As-of date (fixed): {asof}"
                                                     + _families_line(reg, families)
                                                     + f"\n\nQuestion: {question}"}]
    calls: list[dict] = []
    # W3.5 turn-scoped handle registry: {handle -> {series, kd, unit}}. A lookup mints a handle the model can
    # feed to compute_stat; the registry lives for THIS turn only, so a cross-turn handle can never resolve.
    handles: dict[str, dict] = {}
    hseq = 0
    # U3: every unit-guard FIRE this turn, as "<unit a> vs <unit b>" labels. Turn-scoped like `handles`
    # because the guard fires deep inside the tool loop while the result dict is built only on the final
    # (text) response. Stays [] on every turn the guard does not fire, and an empty list is never written
    # onto the result -- so a matched-unit turn is byte-identical and the key's PRESENCE means a fire.
    unit_guard_fires: list[str] = []
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
    # year_month period-scoping guard: the historical month/span the question NAMES, resolved ONCE up front.
    # None (the common case -- no named month) is a no-op everywhere below, so a 'latest reading' ask is
    # byte-identical. When set it arms BOTH teeth: the per-payload mismatch note and the closing preface.
    ask_win = asked_month_window(question)
    if ask_win and ask_win[0] > Q._asof_ym(asof):
        # The whole named window sits AFTER the as-of month, so the month is genuinely not knowable here --
        # the not-yet-published explanation this guard exists to ban is the CORRECT one. Disarm (the leakage
        # guard's own month grain decides, so the two can never drift).
        ask_win = None
    # T2B pattern-records persistence-history dispatch: detect a persistence question ONCE, up front, and
    # ONLY when the card flag is on -> flag-off never even computes the scope, so the loop is byte-identical
    # to pre-feature. None (the common case, and always when off) is a no-op everywhere below.
    pr_scope = PR.pattern_records_scope(question, contracts=None) if PR.pattern_records_on() else None
    # C2 question-shape scope: which observed metric an honest answer to THIS shape of question requires,
    # resolved ONCE up front and independently of what the model looks up. None (a shapeless ask) is a no-op
    # everywhere below. It dispatches nothing -- the verdict is taken against the finished call list.
    shape = question_shape_scope(question)

    for _ in range(max_calls):
        def _one():
            return client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          tools=tools, messages=convo)
        resp = pv.with_retry(_one) if pv else _one()
        uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not uses:
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
            result: dict = {"answer": text, "calls": calls}
            if unit_guard_fires:
                # U3: the unit guard's refusal is MODEL-FACING ONLY -- it never enters `calls`, so it
                # reaches no citation and no reader directly. This key is therefore the only way to see
                # that it fired at all. NOT YET WIRED END-TO-END: it stays numbers-lane-local until it is
                # added to the fixed whitelist tuples in orchestrator.py (numbers_only + both hybrid
                # sites) and to eval.py's row projection -- the same trap documented for
                # `shape_decline_suppressed` below. Those four files are outside this lane; until they
                # move, this key is observable on answer_numbers' own return and nowhere else.
                result[UNIT_MISMATCH_TRACE_KEY] = list(unit_guard_fires)
            preface = ""
            if ask_win:
                # year_month period-scoping guard, closing tooth: the question NAMED a month and no
                # month-grained lookup ever landed in it, yet one came back with a different month. State the
                # mismatch plainly, FIRST -- it re-labels every monthly figure that follows. (Placed ahead of
                # the ESR generic-breakdown branch, which can REPLACE the answer and return early; the two
                # are structurally disjoint -- silver_esr is vintage-semantics, never year_month.)
                off_ym = period_mismatch_ym(ask_win, calls, reg)
                if off_ym is not None:
                    preface += _period_mismatch_preface(ask_win, off_ym)
                    result["period_mismatch_guard"] = _ym_iso(ask_win[0]) if ask_win[0] == ask_win[1] else \
                        f"{_ym_iso(ask_win[0])}..{_ym_iso(ask_win[1])}"
            if price_scope:
                # deterministic decline of an uncovered price series: the caveat is PREPENDED regardless of
                # what the model wrote, so an uncaveated proxy can never pose as the asked-for series.
                preface += _price_decline_preface(price_scope)
                result["price_decline_guard"] = price_scope
            if fut_scope and not futures_eod_served(calls) and not futures_eod_seam_c_muted(calls, reg):
                # SEAM-C: deterministic decline of an unservable futures ask class (change/curve/named): the
                # front-month-only caveat is PREPENDED regardless of what the model wrote, so a change/curve/
                # named-contract read can never pose as served off the roll-spliced series.
                # W3 flip (2026-07-30): SKIPPED when the per-delivery-month table actually served rows this
                # turn. The templates say the curve / a named expiry is "not in this lookup" -- true of the
                # continuous card, false once silver_futures_eod answers the same ask -- so prepending it to
                # a served curve would be a verbatim denial of the number underneath it.
                # 2026-07-31: ALSO skipped on an UNCOVERED venue with no continuous-card fallback -- the
                # template's closing offer ("I can give the front-month close level on a date") is a
                # promise the engine cannot keep there. See futures_eod_seam_c_muted.
                preface += _futures_decline_preface(fut_scope)
                result["futures_decline_guard"] = fut_scope
            _cov = futures_eod_coverage_guard(calls)
            if _cov:
                # W3.2: the coverage verdict was decided per-lookup (before any SQL compiled) and stamped on
                # the payload; here it becomes the reader-facing half. A straddling window or an uncovered
                # contract declines VERBATIM; a pre-coverage window states which series its level came from.
                preface += futures_eod_coverage_preface(*_cov)
                result["futures_coverage_guard"] = _cov[0]
            if dest and any(_is_esr_call(c) for c in calls):
                result["esr_destination_guard"] = dest
                if dest == _ESR_DEST_GENERIC:
                    # decline-WITH-aggregate: the per-destination cut is unsupported, but the SUPPORTED
                    # national aggregate (MY total + prior-MY pace) IS served, with real [N] handles minted
                    # through the normal lookup path so the citation verifier accepts them. This REPLACES
                    # the model's prose (which declines to zero numbers) with a deterministic answer.
                    esr_q = next((c.get("query") or {} for c in calls if _is_esr_call(c)), {})
                    legs = _esr_aggregate_legs(esr_q, asof, query_fn,
                                               futures_newest_first=futures_newest_first)
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
                        # D-LD Sitting-A: taken AFTER the aggregate legs were appended -- this early
                        # return is the one path that grows `calls` and then leaves immediately.
                        result["tables_queried"] = tables_queried(calls)
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
            if shape:
                # C2 (D3): the shape verdict, taken LAST and against the FINAL call list -- the ESR aggregate
                # and pattern-records branches above append real legs, and a decline that could not see them
                # would be exactly the wrong decline D3 forbids. (The ESR generic-breakdown branch REPLACES
                # the answer and returns early, so a turn that served the national aggregate never reaches
                # here: it served the number, so there is nothing to decline.) The states ride the result
                # whether or not a line was emitted -- the never-fetched miss (2.3 #1) is the one this plan
                # is about, and it is silent by construction.
                shape_preface, shape_declined, shape_states = shape_decline(shape, calls)
                result["question_shape"] = shape
                result["shape_metric_states"] = shape_states
                if shape_declined:
                    # THE VERDICT RIDES WHETHER OR NOT THE LINE RENDERED (R8 fold, 2026-08-02). R8's first
                    # cut read `shape_decline_guard` as a RENDER RECEIPT and dropped it on the suppressed
                    # turn. It is not one, and the code base says so in two places: orchestrator.py:302-307
                    # ("the shape RECORD is lane-independent ... Only the reader-facing DECLINE PREFACE is
                    # numbers_only-only ... the record must not be, or the miss states are unobservable on
                    # the very lane 2.4(a) measured them on") and eval.py:1160-1163 ("without this line the
                    # four miss states are unreadable from any artifact"). Dropping it therefore did not
                    # move a fact from one key to another -- it DELETED the C2 miss from every artifact on
                    # exactly the overlap turns, worst on HYBRID, where the C2 line is discarded before a
                    # reader ever sees it and the record was the only observable half in the first place.
                    # The two keys now split the two questions cleanly:
                    #   shape_decline_guard      -- WHAT THE SHAPE VERDICT WAS (lane-independent record,
                    #                               carried onto the trace by both orchestrator lanes and
                    #                               into eval's row projection). Present exactly when the
                    #                               C2 register declined, which is what it meant pre-R8,
                    #                               so no corpus count of C2 misses shifts under R8.
                    #   shape_decline_suppressed -- WHETHER THE LINE WAS WITHHELD as a duplicate refusal.
                    # NOTE FOR THE TRACE OWNERS: `shape_decline_suppressed` is numbers-lane-local until it
                    # is added to the three fixed key tuples in orchestrator.py (:100, :308, :339) and
                    # eval.py's row projection (:1166); until then the guard is what makes the miss
                    # observable and the suppression is visible only on answer_numbers' own return.
                    result["shape_decline_guard"] = shape_declined
                    if other_decline_fired(preface):
                        # F14 / R8 SUPPRESS-ON-OVERLAP. A legacy decline template already refused something
                        # in this preface; C2's line would be a SECOND refusal in the same register, stacked
                        # in front of the same answer. The legacy line wins (it is already written, and it
                        # names the ask the reader actually made), and the shape verdict survives as a
                        # RECORD only -- the guard above, plus this key naming the withheld line.
                        result["shape_decline_suppressed"] = shape_declined
                    else:
                        preface += shape_preface
            if preface:
                result["answer"] = (preface + text).strip()
            # D-LD Sitting-A: the per-turn usage census, taken at the LAST possible moment. The ESR
            # aggregate legs and the pattern-records legs above APPEND to `calls`, so a stamp beside the
            # result dict's construction would under-report exactly the deterministic legs the engine
            # injected on the turns where the model's own lookups were not enough.
            result["tables_queried"] = tables_queried(calls)
            return result
        convo.append({"role": "assistant", "content": resp.content})

        def _exec(b) -> dict:
            """One tool call -> its payload. Self-contained error taxonomy so a bad lookup never kills the
            loop OR its batch-mates."""
            try:
                try:
                    spec = _forced_spec(asof, dict(b.input))
                    _check_commodity_class(spec, reg)      # D-PQ CLASS-1: the card's own closed slug set
                    _check_period_required(spec, reg)      # D-LD: the WAP wrong-crop fence (period axis)
                except Exception as ve:  # noqa: BLE001 -- D-PQ SCHEMA-1: a REJECTED SPEC, said actionably
                    # Separated from the outer handler because the two failures are different things and
                    # the model must be able to tell them apart: this one means "your call was malformed,
                    # fix it and re-issue" (nothing was queried, the loop still has budget), while the outer
                    # one means "the lookup ran and the data access failed". NOT truncated to 200 like the
                    # outer path -- the whole point is that the remedy reaches the model intact.
                    return {"query": dict(b.input), "error": _spec_error(dict(b.input), ve, reg),
                            "rows": [], "status": "error"}
                # W3.2 COVERAGE ROUTING (silver_futures_eod only; ('serve', None) for every other table,
                # so this is byte-identical elsewhere). A straddling window or an uncovered contract is
                # DECLINED here -- before any SQL is compiled -- with the verbatim template stamped on the
                # payload the hybrid reasoner reads. A pre-coverage window is REWRITTEN to a level from
                # the retiring continuous card, carrying the provenance sentence.
                # ask_win (the era the QUESTION names) is passed so the guard REACHES an unwindowed
                # pre-coverage ask -- "what was corn trading at back in May 2005" emitted with no
                # period bounds, which otherwise routed 'serve' and returned TODAY's nearest expiry
                # wearing 2005's label. See futures_eod_read_window.
                _route, _floor = futures_eod_route(spec, reg, ask_win)
                if _route in FUTURES_EOD_COVERAGE_CLASSES:
                    return {"query": spec.model_dump(exclude_none=True), "rows": [], "status": "declined",
                            "scope_note": futures_eod_coverage_note(_route, _floor),
                            "coverage_route": _route, "coverage_floor": _floor}
                if _route == "legacy":
                    # the SAME window the verdict was taken on (era-narrowed when the question named an
                    # era the model never expressed) -- so the legacy level lands in the era ASKED
                    # ABOUT, not at the harness as-of.
                    _win = futures_eod_read_window(spec, _cov_date(_floor, end=False), ask_win)
                    legacy = _legacy_level_spec(spec, _win[1])
                    _lrows = [r for r in Q.run(legacy, query_fn=query_fn,
                                               futures_newest_first=futures_newest_first)
                              if r.get("value") not in (None, "")]
                    return {"query": legacy.model_dump(exclude_none=True), "rows": _lrows,
                            "status": "ok" if _lrows else "no_rows",
                            "scope_note": futures_eod_coverage_note(_route, _floor),
                            "coverage_route": _route, "coverage_floor": _floor}
                rows = Q.run(spec, query_fn=query_fn, futures_newest_first=futures_newest_first)
                # D-OJ-8 -- THE ENGINE-SIDE TRUNCATION SENTINEL, taken at the row count THE QUERY
                # RETURNED. The render-side `series_truncated` can only count the rows that survive the
                # null drop below, so a read that came back AT the cap and contained nulls arrives under
                # the cap and the warning is silently lost. Stamped here, before anything is dropped,
                # the sentinel is exact. Scoped to `agg='series'` for the reason that function states:
                # `agg='latest'` compiles `... DESC LIMIT 1` and cannot truncate, and the named-month
                # curve branch dedups per expiry and lands far under the cap -- an unscoped sentinel
                # would mark every latest read as truncated.
                _lim = int(getattr(spec, "limit", 0) or 0)
                _trunc = (str(getattr(spec, "agg", None) or "latest") == "series"
                          and _lim > 0 and len(rows) >= _lim)
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
                payload = {"query": spec.model_dump(exclude_none=True), "rows": vals, "status": status,
                           "truncated": _trunc}
                # D-PQ EMPTY-1, hazards (1) and (2). Stamped HERE, on the payload the model reads while it
                # still has call budget, and APPENDED so the ESR/period notes `_stamp_scope` adds next can
                # never overwrite them. The two are mutually exclusive by construction (one needs zero
                # rows, the other needs exactly one valued row).
                if not vals:
                    payload["scope_note"] = _no_rows_note(status)
                elif _is_zero_esr_aggregate(payload):
                    payload["scope_note"] = _ESR_ZERO_AGG_NOTE.format(
                        metric=str(getattr(spec, "metric", "") or "figure"))
                # D-PQ A': an EMPTY front-expiry read is not a plain lake gap -- the selection declines
                # (cash reference, missing activity metric, nothing eligible) exactly where running the
                # named rule honestly is impossible. Without the reason on the payload the model sees a
                # bare no_rows and the recorded failure mode is precisely what it does next: reach for
                # another table's price and call it the futures level. Query.run does not raise for this
                # (an honest absence is not an error), so the reason rides here.
                if not vals and str(getattr(spec, "agg", "") or "") == Q.FRONT_EXPIRY_AGG:
                    # APPENDED to the D-PQ EMPTY-1 marker above, never over it: this note says WHY the rule
                    # could not run, the marker says there is no number here. Both are true and the
                    # `_stamp_scope` seam below uses the same append discipline for the same reason.
                    _prior = payload.get("scope_note")
                    payload["scope_note"] = (f"{_prior} {Q.FRONT_EXPIRY_DECLINE}" if _prior
                                             else Q.FRONT_EXPIRY_DECLINE)
                return payload
            except Exception as e:  # noqa: BLE001 — a bad lookup must not kill the loop
                return {"query": dict(b.input), "error": str(e)[:200], "rows": [], "status": "error"}

        def _stamp_scope(payload: dict) -> dict:
            """Destination-scoped ask hitting the destination-blind export-sales table: tell the MODEL the
            value is a national total (defense-in-depth next to the deterministic answer preface — the
            hybrid path consumes calls, not the agent's prose, so the note must ride the payload)."""
            if dest and _is_esr_call(payload):
                codes = _esr_call_codes(payload)
                if not codes:                              # national lookup for a destination ask -> national caveat
                    # D-PQ EMPTY-1: APPEND, never overwrite -- `_exec` may already have stamped the
                    # NO ROWS RETURNED marker or the zero-aggregate caveat on this same payload, and both
                    # of those are about whether a number exists at all, which outranks a scope caveat.
                    _p = payload.get("scope_note")
                    payload["scope_note"] = (f"{_p} {_esr_scope_note(dest)}" if _p else _esr_scope_note(dest))
                elif _esr_codes_are_bloc(codes) and (payload.get("rows") or []):
                    # scoped to a bloc/region code that RETURNED a figure -> bloc-aggregate note. Gated on rows:
                    # an empty bloc read (e.g. the EU, absent from silver_esr) carries no figure to label as a
                    # bloc aggregate, so the model just narrates the no_rows result honestly.
                    _p = payload.get("scope_note")                       # D-PQ EMPTY-1: append, see above
                    payload["scope_note"] = (f"{_p} {_esr_bloc_scope_note(dest)}" if _p
                                             else _esr_bloc_scope_note(dest))
                # scoped to a real single country -> NO scope_note (the value IS that destination's)
            if ask_win and _is_month_grain_call(payload, reg):
                # Month-grained card answering a NAMED-month ask with a row from a different month: tell the
                # MODEL, on the offending result itself, WHICH month came back and how to re-scope (the loop
                # still has call budget, so a stamped turn can repair itself). The ESR note above cannot
                # collide (silver_esr is vintage-semantics, never year_month), but append rather than
                # overwrite so a future card carrying both stays honest about both. The year_month gate is
                # what keeps silver_nasa_power out of this — it is date-semantics, yet its year/month
                # PARTITIONS surface the same self-identifying extras a row-level month check reads.
                off = next((ym for ym in (_row_ym(r) for r in (payload.get("rows") or []))
                            if ym is not None and not (ask_win[0] <= ym <= ask_win[1])), None)
                if off is not None:
                    note = _period_mismatch_scope_note(ask_win, off)
                    prior = payload.get("scope_note")
                    payload["scope_note"] = f"{prior} {note}" if prior else note
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
                if res.get("guard") == ST.UNIT_GUARD:
                    # U3: record the FIRE (with both units) so the guard is observable in an artifact.
                    # Only the unit condition rides this key -- an EMPTY read is a coverage gap and
                    # counting it here would inflate every unit-mismatch census.
                    unit_guard_fires.append(str(res.get("units")))
                return ({**res, "status": "declined"}, [])
            prov = _stat_provenance(stat, inp, handles)
            # G4c review fold (wf_6906ea5b, minor): ONE window per receipt. provenance.params
            # carries the model's REQUEST; after a clamp the same tool result would ship
            # `window: 250` beside `provenance.params.window: 5000` -- a contradictory receipt
            # inside an auditability bundle. The effective window (stats.zscore's own res
            # field) overwrites the requested one so every surface answers "taken over how
            # many points" identically.
            if stat == "zscore" and res.get("window") is not None:
                prov.setdefault("params", {})["window"] = res["window"]
            sh = handles.get(inp.get("series_handle")) or {}
            injected = _stat_calls(stat, res, prov, sh.get("unit"), sh.get("kd"), sh.get("labels"),
                                   sh.get("src_table"), sh.get("src_metric"))
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
                                  "unit": injected[0]["rows"][0].get("unit"),
                                  # D-AM-17: the labels inherited above ride the CHAINED handle too, so a
                                  # stat of a stat keeps saying which expiry it came from. No `shape` and
                                  # no `expiries`: a derived figure is not a curve read, so S4 lets it
                                  # compute (an empty shape is never interleaved) and `spread` refuses it.
                                  "labels": _handle_labels(injected[0]["rows"])}
            elif name == TOOL_NAME:
                content = _stamp_scope(payload_by_id[b.id])
                calls.append(content)
                hseq += 1                                          # mint the lookup's turn-scoped handle
                h = f"L{hseq}"
                content["handle"] = h
                _rows = content.get("rows") or []
                # D-AM-17 (S4 + the label carry): the shape verdict is MEASURED HERE, at the mint, on the
                # rows the lookup actually returned -- the one place both counts exist. Deferring it to
                # dispatch time would mean re-deriving it per stat call from a handle that had already
                # discarded the rows, which is precisely how the multiplicity got lost in the first place.
                _vals, _exps = _series_axis(_rows)
                # G4c(iii): the SOURCE IDENTITY, stamped where both halves exist. A sigma's meaning
                # is "how far from normal, for WHICH series" -- the handle carried the numbers and
                # threw away the subject, so the citation had no way to name it. Read off the
                # recorded query, never guessed from the rows.
                _srcq = content.get("query") or {}
                handles[h] = {"series": _vals, "kd": _handle_kd(_rows),
                              "unit": (_rows[0].get("unit") if _rows else None),
                              "expiries": _exps, "shape": Q.series_shape(_rows),
                              "labels": _handle_labels(_rows),
                              "src_table": (_srcq.get("table") or None),
                              "src_metric": (_srcq.get("metric") or None)}
            else:                                                  # unknown tool (or stats off) -> honest error
                content = {"status": "error", "error": f"unknown tool {name!r}"}
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(content)[:6000]})
            if on_call is not None:
                try:
                    on_call(len(calls), (content.get("query") or {}).get("table") or content.get("stat"))
                except Exception:  # noqa: BLE001 — progress reporting can never fail a lookup
                    pass
        convo.append({"role": "user", "content": results})
    # D-LD Sitting-A: the budget-exhausted return is a REAL turn with real lookups behind it, so the usage
    # census rides it too -- otherwise the BUSIEST turns are precisely the ones missing from the read.
    return {"answer": "(stopped: max tool calls reached)", "calls": calls,
            "tables_queried": tables_queried(calls)}


# --- J3: DATED ROW RENDERING (OUTCOMES_JOIN_PLAN items 54-60a, 91) ----------------------------------
# THE DEFECT. A silver_futures_eod series read renders as `settle=511.75@? (latest of 5000 rows)` -- a
# price with NO date on it. Root cause: the renderers read the `period` key, and that card never emits one.
# `query._extras` surfaces `data_date` only when `date_col != knowledge_date_col`, and `period` only when
# `period_col` is set AND differs from both; silver_futures_eod is `date_col == knowledge_date_col ==
# trade_date` with `period_col` unset, so the ONLY date alias it can ever carry is `knowledge_date` -- and
# it carries it on every row. This is a RENDER defect, not a data defect: for this table the data axis and
# the knowledge axis ARE the same physical column by ratified design (`knowledge_semantics: data_date`,
# `publication_lag_days: 1`). There is no second date to project. Nothing is missing; the renderers looked
# in the wrong slot.
#
# WHY THE FIX IS NOT IN query.py. Relaxing `_extras` to emit `data_date` when the two columns are equal
# hands SEVEN tables a new alias, and `data_date` sits FIRST in `_total_order`'s priority list -- so the
# ORDER BY changes on all seven, which changes the pg-vs-Athena row sample under LIMIT, the exact
# divergence `_total_order` exists to pin, mid-parity-soak. Declaring `period_col: trade_date` is a
# guaranteed no-op (query.py excludes a period_col equal to date_col/knowledge_date_col) that would also
# start failing config_check.check_futures_eod's card-drift clauses. Both rejected with measured reasons
# (plan item 58); query.py is deliberately untouched by this fix, and nothing here reads or writes SQL.
#
# TWO ORDERS, ON PURPOSE -- this is the part that is easy to get wrong (plan item 56a).
#   * PERIOD/OBSERVATION slots (`_num_line`'s `@`, `_row_line`'s `period=`) take
#     `period or data_date or knowledge_date`  -> `row_date_label` / `row_date_token`.
#   * KNOWLEDGE slots (a provenance line's "when was this known", `Citation.date` and the
#     "latest available X; as-of Y" staleness clause at citations.py:110-125) take
#     `knowledge_date or data_date`            -> `row_known_label`.
# The two orders agree on every card in the registry today and stop agreeing the moment a card separates
# the axes -- which is exactly what the outcomes table will do (`period_col: event_date`,
# `knowledge_date_col: endpoint_date`). Under the knowledge-first order a judge panel would print the
# ENDPOINT date in a slot labelled `period`, beside a `known=` saying something else; under the
# period-first order a provenance line would print the EVENT date where a PIT reader is checking the
# publication date. Neither slot may borrow the other's order.
#
# THE LABEL IS PART OF THE FIX, IN BOTH SLOTS. A date rendered bare -- or worse, rendered under `period=`
# when it is not a period -- is a date the reader and the model can narrate as something it is not:
# "settle 511.75, published 2026-07-27" turns an exchange SESSION date into a publication date, and the PIT
# clamp then reads as satisfied when it is not. Every date these helpers emit therefore names the axis it
# actually came from, resolved to the CARD'S OWN physical column (`trade_date=2026-07-27`,
# `report_date=2025-12-30`, `written_at=2026-01-05`, `date=2026-07-27`), and says `period=` only when the
# row genuinely carries a period.
#
# REACH (re-derived card by card against `query._extras`, plan item 57): eleven of nineteen cards emit no
# `period`; this dates EIGHT of them -- six via `knowledge_date` (silver_futures_eod, silver_futures_prices,
# silver_cot, silver_mpob, silver_pink_sheet, silver_sagis_weekly_exports) and two via `data_date`
# (silver_nasa_power, silver_fred_fx). The other three (silver_noaa_oni, silver_noaa_iod, gold_weather_z)
# are `year_month` cards carrying only year_col/month_col and NO date_col at all, so `_extras` emits
# neither alias and NO date fallback can reach them: they keep rendering `?`. That is a KNOWN, pinned
# residue, not an unnoticed miss -- dating them wants a separate `year*100+month` render, out of scope here.
ROW_DATE_ALIASES = ("period", "data_date", "knowledge_date")     # PERIOD-semantics order (plan item 56a)
ROW_KNOWN_ALIASES = ("knowledge_date", "data_date")              # KNOWLEDGE-semantics order (citations.py:110)


def _axis_col(table: Optional[str], axis: str) -> str:
    """The card's own physical column name behind a date alias -- `knowledge_date` -> `trade_date` for
    silver_futures_eod, `written_at` for gold_pattern_records, `date` for silver_fred_fx. Read straight off
    the (already lru_cached) registry rather than re-cached here: a second cache layer would go stale
    against the GRAPHRAG_NUMBERS_DISABLE kill-switch, which drops whole tables from `load_registry().tables`.
    An unknown table or a registry failure degrades to the ALIAS name, which is cosmetic-only -- the date
    still renders, still labelled, just with the generic axis name."""
    try:
        ts = load_registry().tables.get(str(table or ""))
    except Exception:  # noqa: BLE001 -- a registry problem must never break a render
        return axis
    if ts is None:
        return axis
    col = ts.knowledge_date_col if axis == "knowledge_date" else ts.date_col
    return str(col) if col else axis


def _first_alias(row, aliases) -> Optional[str]:
    for a in aliases:
        v = (row or {}).get(a)
        if v not in (None, ""):
            return a
    return None


def row_date_axis(row) -> Optional[str]:
    """Which alias this row can be dated by, in PERIOD-semantics order -- or None when it carries none.
    None is a real answer, not a failure: the three `year_month` cards genuinely have no date to render."""
    return _first_alias(row, ROW_DATE_ALIASES)


def row_date(row) -> Optional[str]:
    """The row's OWN observation value -- the period when it has one, else the date it was observed on.
    The bare value, unlabelled: prefer `row_date_label` anywhere a reader will see it."""
    a = row_date_axis(row)
    return None if a is None else str((row or {}).get(a))


def row_date_label(row, table: Optional[str] = None, *, missing: str = "?") -> str:
    """PERIOD-slot render, always labelled: `period=2023/24`, `trade_date=2026-07-27`, `date=2026-07-27`.
    A row with no date at all renders `period=?` -- byte-identical to the legacy
    `period={r.get('period','?')}` render, so the three year_month cards keep exactly the shape they have
    today and the residue stays visible (plan item 60(iv))."""
    axis = row_date_axis(row)
    if axis is None:
        return f"period={missing}"
    if axis == "period":
        return f"period={(row or {}).get('period')}"
    return f"{_axis_col(table, axis)}={(row or {}).get(axis)}"


def row_date_token(row, table: Optional[str] = None, *, missing: str = "?") -> str:
    """The `@`-slot token, for renders shaped `metric=<value>@<token>`: `settle=511.75@trade_date=2026-07-27`
    instead of `settle=511.75@?`. Labelled for the same reason `row_date_label` is -- an `@2026-07-27` on a
    settle is exactly the bare date the PIT reader mistakes for a publication date.

    TWO DIFFERENCES FROM `row_date_label`, and both exist to keep plan item 60(ii)'s byte-identity:
      * a row with no date at all yields a bare `?`, so a silver_noaa_oni read still renders `@?`;
      * a row carrying a real PERIOD yields the BARE period value (`@2023/24`), never `@period=2023/24`.
        The legacy `_num_line` render was `f"{value}@{row.get('period','?')}"`, so labelling the period
        axis here changed the render of EVERY period-bearing card -- which item 60(ii) forbids, and
        which the label buys nothing anyway: `2023/24` is not a date a reader can mistake for a
        publication date. The label is for the DATE axes, which had no token at all before J3."""
    axis = row_date_axis(row)
    if axis is None:
        return missing
    if axis == "period":
        return f"{(row or {}).get('period')}"
    return row_date_label(row, table)


def row_known_label(row, table: Optional[str] = None) -> Optional[str]:
    """KNOWLEDGE-slot render, always labelled: `trade_date=2026-07-27`, `written_at=2026-01-05`,
    `release_date=2025-12-30`. Mirrors citations.py:110's `knowledge_date or data_date` order because it
    answers WHEN THIS WAS KNOWN -- never the period-first order, which would answer a different question in
    the same slot the moment a card splits its axes. None when the row carries neither alias, so a caller
    omits the bracket entirely rather than printing an empty one."""
    axis = _first_alias(row, ROW_KNOWN_ALIASES)
    return None if axis is None else f"{_axis_col(table, axis)}={(row or {}).get(axis)}"


def series_truncated(call) -> bool:
    """J3b (plan items 61-64): did this read come back at its own row cap, so part of the asked-for window
    was silently discarded? As written, the series/default branch compiled `ORDER BY <total order> LIMIT
    <limit>` -- ASCENDING, no DESC -- so an unwindowed per-slug read of corn_cbot (49,255 rows) kept the
    OLDEST 5,000 and dropped ~44,000 newer ones, and a renderer that headlined "the latest" was
    honest-looking and wrong.

    WHICH END IS LOST HAS MOVED; WHETHER SOMETHING IS LOST HAS NOT (D-PQ FIX-1). The serving lanes now
    resolve the newest-first scope ON by default (`answer._series_newest_first_on`), so a capped read keeps
    the NEWEST rows and loses the EARLY end of the window instead. This predicate is unchanged and stays
    exactly as load-bearing: the read is still not the complete history, the answer must still say so, and
    the standing remedy is still WINDOWING. Only the RENDERED SENTENCE moved (`format_provenance`,
    `eval._num_line`) -- pointing a reader at the wrong missing end is its own defect.

    SCOPED TO `agg='series'`, which is the sharpening the skeptic pass confirmed and this must not overstate:
    `agg='latest'` compiles `ORDER BY <order> DESC, ... LIMIT 1` and cannot truncate, and the named-month
    curve branch dedups through `ROW_NUMBER() PARTITION BY contract_month` and returns one row per expiry,
    far under the cap. This is a real but BOUNDED defect, not a universal one.

    THE ENGINE STAMP WINS WHERE IT EXISTS (D-OJ-8). `_exec` now records `truncated` at the row count the
    QUERY returned, before null-valued rows are dropped; this function reads that stamp first and falls
    back to counting the surviving rows only for calls minted elsewhere (cascade's synthetic records,
    fixtures, citation payloads). The fallback is ONE-SIDED and deliberately so: a read that truncated at
    the cap AND contained nulls arrives under the cap, so the fallback returns False -- a missed warning,
    never a false one. The standing remedy stays WINDOWING the read (`period_start`/`period_end`), never
    raising the cap -- raising it re-opens the scan surface the S3 LIST-storm work closed."""
    stamp = (call or {}).get("truncated")
    if stamp is not None:
        return bool(stamp)
    q = (call or {}).get("query") or {}
    if str(q.get("agg") or "latest") != "series":
        return False
    lim = q.get("limit")
    try:
        lim = int(lim)
    except (TypeError, ValueError):
        return False
    return lim > 0 and len((call or {}).get("rows") or []) >= lim


def to_citations(calls: list[dict], evidence_rows: Optional[list[dict]] = None):
    """Unified Citation objects (numbers + optional document evidence) — the Phase-4 provenance seam that the
    synthesizer/UI consumes. See leviathan.graphrag.citations."""
    from leviathan.graphrag import citations as C
    return C.unify(evidence_rows, calls)


def format_provenance(calls: list[dict]) -> list[str]:
    """One human citation per executed lookup — for the synthesizer / UI.

    J3, ONE change, render-only: the bracketed date is LABELLED with the card's own column
    (`[trade_date=2026-07-27]`, never a bare `[2026-07-27]`). This is a KNOWLEDGE slot, so it keeps
    citations.py:110's `knowledge_date or data_date` order and only stops being a date a reader can mistake
    for a publication date on a card -- like silver_futures_eod -- where the knowledge axis IS the trading
    session. J3b: when the read came back at its row cap the line says so instead of implying the value is
    current (the engine stamp from `_exec`, via `series_truncated`).

    WHAT IS DELIBERATELY *NOT* CHANGED HERE, and it is a real defect left standing on purpose: the
    headline row is still `rows[0]`. A series arrives chronological ASCENDING, so `rows[0]` is the OLDEST
    print -- the judged-30 RCA (b) class, already fixed in `citations.from_number`. Picking by chronology
    here would be a VALUE change (a different displayed number on every multi-row call) on every card, and
    J3 is scoped to RENDER (plan item 56: `eval._num_line` + `_row_line`). Changing a displayed value
    mid-parity-soak, inside a render fix, is how an unrelated regression gets attributed to the wrong
    wave. It belongs in its own item with its own soak (adversarial finding 10)."""
    out = []
    for c in calls:
        q = c.get("query", {})
        rows = c.get("rows") or []
        head = rows[0] if rows else {}
        val = (head.get("value") if rows else
               "(lookup error)" if c.get("status") == "error" else
               "(no matching data)" if c.get("status") == "no_rows" else "(not known at asof)")
        scope = "/".join(str(q.get(k)) for k in ("commodity", "country", "period") if q.get(k))
        line = f"{q.get('table')}.{q.get('metric')} {scope} = {val}"
        known = row_known_label(head, q.get("table")) if rows else None
        if known:
            line += f" [{known}]"
        if series_truncated(c):
            # D-PQ FIX-1: the serving lanes compile newest-first by default, so a capped read keeps the
            # NEWEST rows and loses the EARLY end of the window. The old wording ("OLDEST rows kept, so
            # this is NOT the latest print") is now the exact inverse of the truth and would have a reader
            # discount a current print as stale.
            line += (f" (row cap {q.get('limit')} reached -- NEWEST rows kept, so the EARLY end of the "
                     f"window is missing; not the complete history)")
        out.append(line)
    return out
