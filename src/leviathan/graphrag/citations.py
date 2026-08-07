"""Unified provenance citations — one schema spanning DOCUMENT evidence (chunks) and NUMBERS (silver lookups).

A Citation carries a human `label`, a `source`, a knowledge `date`, and a machine `locator` (the click-target the
UI resolves): for a number, the exact leakage-safe query to re-run as a drill-down; for a document, a pointer to
the source doc. The document locator carries `page`/`char_start`/`char_end`/`offset_kind`/`snippet` SLOTS — the
char/offset fields populate for W2.1 props and drive 6.5 click-to-page (deterministic offsets-first page
recovery, fuzzy snippet-match fallback) — so numbers and page-level document citations render through one path.
"""
from __future__ import annotations

import datetime as _dt
from typing import Literal, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    id: str                                   # short handle used inline, e.g. N1 / E2
    kind: Literal["number", "evidence"]
    label: str                                # one-line human rendering
    source: str                               # PSD / usda_gain_wheat / ...
    date: Optional[str] = None                # when it was KNOWN (knowledge_date for numbers, doc date for evidence)
    value: Optional[str] = None               # numbers only
    unit: Optional[str] = None
    locator: dict = {}                        # machine click-target (see module docstring)
    payload: dict = {}                        # kind-specific extras (query+rows, or source_key+text)


def _source_label(table: str) -> str:
    """Official label for a silver table — delegates to the display registry (6.1) so the number
    citation, the sources footer, and the lint agree on one name; falls back to the legacy
    strip-'silver_'+upper for an unmapped table."""
    from leviathan.graphrag import display as dp
    return dp.table_label(table)


def _fmt(v) -> str:
    try:
        f = float(v)
        return f"{f:,.0f}" if abs(f) >= 1000 else f"{f:g}"
    except (TypeError, ValueError):
        return str(v)


def _metric_unit(table: str, metric: str, commodity: Optional[str] = None) -> str:
    """The card's declared unit for a metric.

    D-PQ RENDER-1: `unit_overrides` is consulted FIRST when the caller knows the commodity. A metric whose
    source carries no governed unit (silver_futures_eod.settle, silver_wasde.avg_farm_price) declares NO
    `unit:` at all -- only the per-commodity override map -- so the old `m.unit` read returned "" for exactly
    the cards where a unitless number is least attributable (ten currencies, no conversion layer anywhere).
    `Q.run` normally stamps `r["unit"]` post-fetch and the row wins, but any call minted OUTSIDE `run()`
    (agg-shaped rows, cascade fixtures, a persisted citation payload) reaches here with no row unit, and the
    citation then rendered bare. Commodity-less callers keep the old behaviour exactly."""
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        m = load_registry().get(table).metrics.get(metric)
        if not m:
            return ""
        ov = getattr(m, "unit_overrides", None) or {}
        if commodity and ov.get(commodity):
            return ov[commodity]
        return m.unit or ""
    except Exception:  # noqa: BLE001 — registry missing/table unknown -> no unit, never fatal
        return ""


# -- D-PQ RENDER-2: the per-expiry PRICE row's self-identifying labels --------------------------------
# A `silver_futures_eod` row carries its own contract_month, settle_kind and currency BY RATIFIED DESIGN
# (the card declares all three columns "because a curve row without its expiry label is unattributable,
# since every row of a multi-expiry read carries the same slug and the same trade date"). The MODEL never
# saw any of it: the hybrid synthesis prompt is `orchestrator._numbers_block` -> `citations.render` ->
# `Citation.label`, and the label was built from the QUERY's scope only (commodity/country/period). On an
# `agg='front_expiry'` read the delivery month is not in the query AT ALL -- the rule SELECTS it -- so the
# one read whose entire point is "which expiry IS the market" handed the writer a bare number. Measured
# 2026-08-07 (dpq_probe_v1 row 1): the anchor served the right settle and the answer quoted it with no
# delivery month and no unit; `expiry_labeled` and `unit_present` both failed on a CORRECT read.
#
# The labels are rendered from the ROW, never from the query, for the same reason the card puts them
# there: the query may name no expiry and still get one back.
_SETTLE_KIND_WORDS = {
    # Plain-English renderings the writer can quote verbatim. Deliberately matched to
    # `eval._SETTLE_KIND_PHRASES` so the panel hands the model the exact vocabulary the honesty pin reads,
    # and deliberately NOT "official exchange settlement" for anything but a true `settlement` row --
    # that phrase is the ICE mislabel `eval._SETTLE_MISLABEL_RX` exists to convict.
    "settlement": "exchange settlement",
    "close": "session close",
    "cash_index": "cash index",
    "mark_to_market": "mark-to-market",
}


def _print_kind(row: dict) -> str:
    kind = str((row or {}).get("settle_kind") or "").strip()
    return _SETTLE_KIND_WORDS.get(kind, kind)


def _row_date_text(r: dict) -> str:
    """The observation's own date, in `_row_order_key`'s priority. "" when the row carries none."""
    for a in ("data_date", "knowledge_date"):
        v = (r or {}).get(a)
        if v not in (None, ""):
            return str(v)[:10]
    p = (r or {}).get("period")
    return str(p) if p not in (None, "") else ""


# -- CYCLE-5 (2026-08-07) VINTAGE-1: the AS-KNOWN stamp for a row that carries no date COLUMN ----------
# MEASURED (gate-2 of the D-CW/D-PQ probe, both passes): 29/74 and 35/86 footer [N] rows rendered with NO
# `[known ...]` tail at all, and the SAME families both times. Two distinct causes, and only one of them
# lives here:
#   (a) a SYNTHETIC row minted by the cascade (`_delta_call`/`_pace_synth`/`_price_call`) that simply never
#       copied its source row's date -- fixed at those mint sites, where the date exists;
#   (b) a REAL fetched row from a table whose card declares `knowledge_semantics: year_month` and NO date
#       column at all (silver_noaa_oni, silver_noaa_iod, gold_weather_z). `query._extras` cannot surface a
#       `knowledge_date`/`data_date` alias that the table does not have, so `rH.get(...)` was correctly
#       None and the tail was correctly omitted -- and the reader got an undated climate reading.
# THIS IS THE (b) HALF. The row DOES carry its own observation identity: `year` and `month` are surfaced
# aliases (`_extras`), and those cards' as-of rule is literally `(year*100 + month) <= asof year-month`,
# i.e. THE SERVING CONTRACT ALREADY TREATS THE MONTH AS THE KNOWLEDGE GRAIN. So the stamp is derived from
# the row's own columns, never from `asof` and never from today.
# RENDERED AS 'YYYY-MM', NOT AS A SYNTHESISED DAY, and that is deliberate in two directions: a day this
# source does not publish would be an invention, and `_parse_date` rejects the month form -- so the
# `(latest available X; as-of Y)` staleness clause stays OFF for these rows. That is the one-sided
# direction this file already prefers everywhere (a missed warning, never a false one).
_YM_MONTHS = frozenset(str(i) for i in range(1, 13))


def _row_known_date(r: dict) -> Optional[str]:
    """The row's own as-known stamp: `knowledge_date`, else `data_date`, else its (year, month) identity as
    'YYYY-MM'. None when the row carries none of the three -- the pre-CYCLE-5 behaviour, byte for byte, for
    every row that already had a date."""
    for a in ("knowledge_date", "data_date"):
        v = (r or {}).get(a)
        if v not in (None, ""):
            return v
    y, m = (r or {}).get("year"), (r or {}).get("month")
    if y in (None, "") or m in (None, ""):
        return None
    try:                                          # a year_month card's aliases arrive as ints OR as strings
        yi, mi = int(str(y).strip()), int(str(m).strip())
    except (TypeError, ValueError):
        return None
    if not (1900 <= yi <= 2200) or str(mi) not in _YM_MONTHS:
        return None                               # not a calendar month -> not a date, so say nothing
    return f"{yi:04d}-{mi:02d}"


def _series_truncated(call: dict) -> bool:
    """DELEGATES to `numbers.agent.series_truncated` -- never a second copy of the rule (the engine stamp
    beats the row count, and only `agg='series'` can truncate). Imported lazily so citations.py keeps no
    import-time dependency on the numbers stack; any failure reads as 'not truncated', which is the
    one-sided direction the predicate itself already documents (a missed warning, never a false one)."""
    try:
        from leviathan.graphrag.numbers.agent import series_truncated
        return bool(series_truncated(call))
    except Exception:  # noqa: BLE001
        return False


def _covered_span(rows: list[dict]) -> str:
    """The span the RETURNED rows actually cover, as 'first..last' (or one date when they share it). "" when
    no row carries a date -- then the caller states the truncation without inventing a span."""
    ds = sorted({d for d in (_row_date_text(r) for r in (rows or [])) if d})
    if not ds:
        return ""
    return ds[0] if len(ds) == 1 else f"{ds[0]}..{ds[-1]}"


def _row_order_key(r: dict) -> tuple:
    """Chronology key mirroring the series SQL's total order (data_date, then year/month, then period,
    then knowledge_date). The series query (numbers.query._total_order) sorts rows ASCENDING, so the
    FRESHEST observation is max() over this key — computed rather than trusting rows[-1] so an
    engine-arbitrary sample can never headline the oldest print (judged-30 RCA (b))."""
    def _i(x) -> int:
        try:
            return int(x)
        except (TypeError, ValueError):
            return -1
    return (str(r.get("data_date") or ""), _i(r.get("year")), _i(r.get("month")),
            str(r.get("period") or ""), str(r.get("knowledge_date") or ""))


def _parse_date(s) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _empty_label(status: Optional[str], asof: Optional[str]) -> str:
    """Status-aware label for a zero-row lookup — preserve the agent's taxonomy so the synthesizer can
    tell a coverage gap (answerable elsewhere) from a vintage-timing gap (genuinely not yet published)
    from a lookup failure. Erasing this to one flat '(not known at asof)' made a June-2026-scoped COT
    window (empty because silver_cot ends 2025-12-30) read as a timing claim and the whole question
    was declared unanswerable (judged-30 RCA (a)). Status ABSENT -> the legacy text, unchanged.

    D-PQ EMPTY-1 (2026-08-07, dcw_probe_v1 row `dcw_esr_china_corn`): every branch is now PREFIXED with
    the literal marker `NO ROWS RETURNED`, and the parentheticals are untouched underneath it (so every
    existing assertion, which tests membership of the reason text, still holds). The taxonomy was already
    correct and already reader-safe; what it lacked was a phrase that says THERE IS NO NUMBER HERE loudly
    enough that the writer cannot read the line as an invitation to state one -- the measured failure being
    an export-sales read narrated as a factual `0.0 thousand MT (0 MT)` with the editorial "this represents
    no actual shipments" on top. The marker is a FACT about the read, not a directive, so it is safe in the
    reader-facing `## Sources` list as well as in the prompt panel (the citations.py:110 render split). The
    directive half lives in orchestrator._numbers_block, prompt-side only."""
    a = str(asof) if asof else "asof"
    if status in ("not_known", "future_unpublished"):
        return f"NO ROWS RETURNED (not yet published as of {a})"
    if status in ("no_rows", "record_silent"):
        return "NO ROWS RETURNED (no matching rows -- scope/coverage gap, not a timing claim)"
    if status == "error":
        return "NO ROWS RETURNED (lookup error)"
    if status == "declined":
        # a lookup the harness STRUCTURALLY declined, not one that failed or came back empty: the SEAM-C
        # hybrid futures decline (task #144) neuters a curve/named front-month read so no level can be cited
        # as the asked-for quote. The scope note riding the same call carries the WHY to the writer.
        return "NO ROWS RETURNED (declined -- not servable from this series for this ask)"
    return "NO ROWS RETURNED (not known at asof)"


# D-PQ EMPTY-2 (2026-08-07, dcw_probe_v1 row `dcw_esr_china_corn`, SECOND cycle). EMPTY-1 closed the
# ZERO-ROW half: `_empty_label` marks it and the unit is withheld. The ZERO-AGGREGATE half was closed only
# on the PROMPT side (`agent._ESR_ZERO_AGG_NOTE`), and the measured result is a split answer: the prose
# refused correctly ("no reported weekly shipments ... the table carries no data rows for that scope") while
# the reader's own `## Sources` line under it still read
#     [N1] USDA FAS Export Sales (ESR) weekly_exports_1000mt CBOT corn China MY2025 = 0 1000 MT
# -- a citation asserting the exact measured quantity the prose had just declined to assert, in the one
# place a reader goes to check the prose. A zero-sum on this table is produced equally by weeks that
# reported zero and by a window with no reported weeks; the aggregate collapses them, so `= 0 1000 MT` is
# not a fact the record supports.
#
# THE RULE IS `agent._is_zero_esr_aggregate`, DELEGATED, NEVER COPIED -- the `_series_truncated` discipline
# exactly: one producer for the class, so the prompt caveat and the reader's citation can never disagree
# about which reads are in it. Lazy import; any failure reads as "not a zero aggregate", the one-sided
# direction that can only ever miss a caveat, never invent one.
_ZERO_AGG_LABEL = ("NO REPORTED FIGURE (the window's rows sum to exactly 0, which this table produces "
                   "equally for weeks reporting zero and for a window with no reported weeks -- not a "
                   "measured quantity of zero)")


def _zero_aggregate(call: dict) -> bool:
    try:
        from leviathan.graphrag.numbers.agent import _is_zero_esr_aggregate
        return bool(_is_zero_esr_aggregate(call))
    except Exception:  # noqa: BLE001
        return False


def _period_label(period) -> Optional[str]:
    """The reader-facing period token for a scope string, or None.

    Agent calls carry a BARE MY year ("2011" -> render "MY2011"); cascade calls arrive PRE-labeled
    ("MY2011" / "2010-06-01..2010-09-01") -- re-prefixing those minted "MYMY2011" in the Sources footer and
    fed the judge malformed provenance (P9-AB P0-6). CYCLE-5: lifted out of `from_number` UNCHANGED so the
    per-row extra citations (FOOTER-1) label a row's own period through the SAME rule -- a second copy is
    exactly how the "MYMY" class was born."""
    per = str(period) if period is not None else None
    if per and not (per.startswith("MY") or ".." in per):
        per = f"MY{per}"
    return per


def from_number(call: dict, i: int) -> Citation:
    """Build a Citation from a numbers-agent call record ({query, rows, status})."""
    q = call.get("query", {})
    rows = call.get("rows") or []
    status = call.get("status")
    # headline = the LATEST observation, not rows[0]: a series (agg=series/default) arrives chronological
    # ASCENDING, so rows[0] is the OLDEST print — surfacing it headlined a stale 2023 value as if current
    # (judged-30 RCA (b)). The full `rows` order is untouched (payload keeps rows[:3] as before).
    rH = max(rows, key=_row_order_key) if rows else {}
    table, metric = q.get("table", ""), q.get("metric", "")
    src = _source_label(table)
    asof = q.get("asof")
    value = rH.get("value")
    unit = rH.get("unit") or _metric_unit(table, metric, q.get("commodity"))
    kd = _row_known_date(rH)                  # CYCLE-5 VINTAGE-1: ...falling back to the row's (year, month)
    per = _period_label(q.get("period"))
    # D-PQ RENDER-2: the DELIVERY MONTH rides the scope, and it comes off the ROW. On agg='front_expiry'
    # the query names no expiry (the rule selects one), so a query-only scope is silent on the single fact
    # that makes the number attributable.
    cmonth = str(rH.get("contract_month") or "").strip()
    # D-PQ RENDER-2b, the same defect on the GEO axis. The row's `country` extra is the geography the value
    # actually came from; the query's is what was ASKED for, and on a free-axis card
    # (silver_nass_crop_progress repurposes country as the US STATE) an unscoped read returns ONE arbitrary
    # state and the label then said nothing at all -- "a state number wearing a national label", the exact
    # failure that card's own notes warn about. Query first (it is what the drill-down re-runs).
    #
    # THE FALLBACK IS FENCED TO A UNANIMOUS ROW SET, AND THAT FENCE IS THE WHOLE SAFETY OF IT. `_extras`
    # emits a `country` alias for EVERY card with a country_col, so an UNSCOPED multi-geography read (an
    # ESR national total spans every destination code) returns rows that disagree -- and the headline row
    # `rH` is one of them. Borrowing its geo there would stamp one destination's name on a national
    # aggregate, which is precisely the ESR destination-scope mislabel the agent's own guard exists to
    # refuse. So: name the geo only when every returned row carries the SAME one; otherwise stay silent
    # and leave the label exactly as it renders today.
    #
    # FIX-CYCLE-2 REVIEW BLOCKER: unanimity is TRIVIALLY satisfied by the default agg='latest'
    # (LIMIT 1) read -- one row always agrees with itself -- so an UNSCOPED ESR latest read stamped
    # a single buyer's name on the national leg, beside the scope note saying the opposite. The
    # honest discriminator is SEMANTIC, not arithmetic: a destination-coded table (country_name_ref
    # set -- its country axis enumerates buyers of ONE national flow) must never borrow row geo the
    # query did not ask for. Free-axis cards (NASS states, MPOC per-country stocks) keep the
    # fallback: there, the row's geo IS the fact's geography.
    def _dest_coded(tbl: str) -> bool:
        try:
            from leviathan.graphrag.numbers import registry as _reg
            spec = _reg.load_registry().tables.get(tbl)
            return bool(spec is not None and getattr(spec, "country_name_ref", None))
        except Exception:  # noqa: BLE001 -- a registry hiccup must fail SILENT (no label), never loud
            return True
    _geos = {str(r.get("country")).strip() for r in rows if str(r.get("country") or "").strip()}
    geo = q.get("country") or (None if _dest_coded(table)
                               else (next(iter(_geos)) if len(_geos) == 1 else None))
    scope = " ".join(x for x in (q.get("commodity"), geo, per,
                                 (f"delivery {cmonth}" if cmonth else None)) if x)
    if rows and _zero_aggregate(call):
        # D-PQ EMPTY-2: the collapsed-aggregate class renders the MARKER, exactly as the zero-ROW class
        # does. `value` and `unit` are withheld for the same reason EMPTY-1 withholds them: a unit with no
        # value behind it reads as a quantity whose digits are missing, and `answer._number_handle_value`
        # reads `Citation.value` -- leaving "0.0" there would let a stand-in [N] handle splice a measured
        # zero into the prose, which is the assertion this whole class exists to refuse. The row set is
        # untouched in `payload`/`locator`, so the drill-down still re-runs the real read.
        label = f"{src} {metric} {scope} = {_ZERO_AGG_LABEL}".strip()
        value, unit = None, None
    elif rows:
        label = f"{src} {metric} {scope} = {_fmt(value)} {unit}".strip()
        # D-PQ RENDER-2, second half: WHAT KIND OF PRINT this is, plus the row's own currency. Both are
        # card-declared columns and neither was reaching the writer. The currency is appended only when it
        # is not already inside the unit string (US cents/bushel already says USD; CNY/t already says CNY),
        # so a governed unit is never doubled up.
        _kind = _print_kind(rH)
        _ccy = str(rH.get("currency") or "").strip()
        _tags = [t for t in (_kind, (_ccy if _ccy and _ccy.lower() not in (unit or "").lower() else "")) if t]
        if _tags:
            label += " (" + ", ".join(_tags) + ")"
        # staleness affordance (RCA (c)): when the freshest knowable date trails the asof by more than
        # ~30 days, give the synthesizer a clean 'latest available X; as-of Y' to STATE instead of
        # conflating the two dates and reading as fabrication. Terse by design — one clause, no prose.
        _hd, _ad = _parse_date(kd), _parse_date(asof)
        if _hd and _ad and (_ad - _hd).days > 30:
            label += f" (latest available {str(kd)[:10]}; as-of {asof})"
        # D-PQ RENDER-3 -- THE TRUNCATION ANNOTATION, THREADED TO THE WRITER. `agent.series_truncated` has
        # existed since J3b and `format_provenance` / `eval._num_line` both render it; the SYNTHESIS PROMPT
        # never did, because it is built from these labels. Measured 2026-08-07 (dcw_probe_v1 row 11,
        # dcw_full_record_range): a 5000-row-capped corn read was sold to the reader as "the full-history
        # trading range on record", with no date span, off a window whose EARLY end had been discarded.
        # The span is the remedy the card already prescribes ("never describe a truncated read as the
        # complete record -- if the rows you got start later than the history you asked about, say so"):
        # state what IS covered, or drop the superlative.
        #
        # FACT ONLY, NO IMPERATIVE, AND THAT SPLIT IS LOAD-BEARING. This label is rendered TWICE by two
        # readers: `orchestrator._numbers_block` builds the model's prompt panel from it, and
        # `answer._cited_sources_block` puts it verbatim in the READER's `## Sources` list. A directive
        # ("do not call it full history") is correct for the first and is register leakage in the second,
        # so the directive lives in the prompt-only SCOPE-NOTE channel (`_numbers_block`) and what stays
        # here is the provenance a reader is entitled to see anyway: this is a slice, and here is its span.
        if _series_truncated(call):
            _span = _covered_span(rows)
            _cap = q.get("limit")
            label += (" [TRUNCATED at the "
                      + (f"{_cap}-row cap" if _cap else "row cap")   # a fixture call may carry no limit
                      + ": NEWEST slice only"
                      + (f", covering {_span}" if _span else "")
                      + " -- not the complete record]")
    else:
        label = f"{src} {metric} {scope} = {_empty_label(status, asof)}".strip()
        # D-PQ EMPTY-1: an empty read carries NO UNIT either. A unit with no value behind it is the
        # affordance half of a number -- "= NO ROWS RETURNED (...) 1000 MT" reads as a quantity whose
        # digits happen to be missing, and the measured failure was a reader handed exactly that shape as
        # "0.0 thousand MT (0 MT)". `eval`'s unit_present pin already gates on `value is not None`
        # (NEWCAP TRIAGE 2026-07-24), so no scorer loses a signal; the drill-down re-runs off the locator.
        unit = None
    locator = {"kind": "number", **{k: q.get(k) for k in ("table", "metric", "commodity", "country", "period", "asof")}}
    if cmonth:
        locator["contract_month"] = cmonth      # the drill-down must re-run the expiry that was quoted
    return Citation(id=f"N{i}", kind="number", label=label, source=src, date=kd,
                    value=(str(value) if value is not None else None), unit=(unit or None),
                    locator=locator, payload={"query": q, "rows": rows[:3]})


# ══ CYCLE-5 (2026-08-07) FOOTER-1: ONE CITATION PER CALL IS NOT ONE CITATION PER STATED FACT ═══════════
#
# THE MEASURED FAILURE (gate-2 row `dcw_farm_price_vintage`, BOTH passes). The answer said "$4.15/bu for
# MY2025/26 (estimate)" and "$4.24/bu for MY2024/25 (actual)". The reader's whole `## Sources` block was:
#     [N1] USDA WASDE avg_farm_price corn united_states = 4.4 $/bu  [known 2026-07-10]
# The adjudicator scored it as fabrication. IT WAS NOT. A direct Athena read of `leviathan_dev.silver_wasde`
# proved the 2026-07-10 release carries exactly those rows -- MY2024/25 actual 4.24, MY2025/26 estimate
# 4.15, MY2026/27 projection 4.4 -- and the agent's own lookup SERVED all 35 of them under [N1]. The prose
# was grounded and correctly attributed; the FOOTER was the thing that lied by omission, because
# `from_number` renders exactly one line per call and that line headlines `max(rows, _row_order_key)`.
#
# THE PRINCIPLE IS CYCLE-4's, RESTATED FOR THIS LANE: THE PROSE IS THE AUTHORITY. `_cited_sources_block`
# already builds the hybrid lane's `## Sources` off what the reader can still SEE (D-PQ HANDLE-4). The
# numbers_only lane has no handle namespace to walk, so the join is made on VALUES instead: a served row
# whose value the prose STATES gets its own footer line, labeled with the facts that make it checkable --
# its own period, its own estimate role, its own vintage.
#
# THE MATCH IS THE VERIFIER'S OWN, PER ROW. `orchestrator._verify_numbers_answer` already extracts the
# answer's stated magnitudes (scrubbing dates / marketing years / [N] handles / prose date forms) and
# matches them against the POOLED row values with `verify._num_matches` (exact-or-1% at any common
# reporting scale). Running that same extractor and that same predicate one row at a time is what turns
# "some row backs this figure" into "THIS row backs this figure" -- no new rule, no second opinion about
# what counts as a stated number, and by construction nothing here can ever contradict the caution banner.
#
# BOUNDED AND ID-STABLE, both load-bearing:
#   * the headline citation is emitted FIRST and UNCHANGED (`from_number`), so a prose that states only the
#     headline renders today's footer byte for byte;
#   * extras carry a LETTER-SUFFIXED id (N1b, N1c, ...) -- the shape `verify._HANDLE` already parses
#     (`\[(?P<kind>[NE]?)(?P<idx>\d+)(?:[a-z])?\]`) -- so they consume NO index and every later call keeps
#     the number the model's prose cites. A new integer per extra row would silently renumber the answer;
#   * <=6 extras per call, de-duped on (value, period): a 35-row serve must not become a 35-row footer, and
#     the same MY arriving on two vintages is one fact to a reader.
#
# ══ FIX-CYCLE-2 (2026-08-07) CORRECTIONS -- two measured inversions of the intent above ═══════════════
#
# (A) THE CAP TOOK THE OLDEST MATCHES (review blocker 1). The loop walked `sorted(rows, _row_order_key)`
#     ASCENDING and stopped at 6, so on the motivating 35-row `dcw_farm_price_vintage` serve six 1990s/2000s
#     marketing years whose prints happened to land near the stated figure filled the cap first and the two
#     rows the whole pass exists to surface -- MY2024/25 and MY2025/26 -- never minted. The adjudicator
#     would have been shown six wrong-decade rows presented as the backing for the prose: the defect
#     INVERTED, not fixed. CANDIDATES ARE NOW RANKED NEWEST-FIRST AND THE CAP IS APPLIED TO THAT RANKING;
#     what survives is then RENDERED ascending, so the reader still reads a chronological footer.
#
# (B) `verify._num_matches` WAS THE WRONG PREDICATE HERE (review blocker 2). It is the right question for
#     "is this figure backed by SOME row" -- deliberately unit-blind and rescale-tolerant (1e2/1e3/1e6/1e9
#     in BOTH directions), so "31.4 million" backs 31400000 and "36.4%" backs 0.3636. An EXTRA FOOTER ROW
#     IS NOT A BACKING CLAIM, IT IS A CLAIM OF IDENTITY: it asserts THIS row, with THIS period and THIS
#     estimate role, is the thing the prose named. Under the rescale arms two demonstrated fabrications
#     minted on the builder's own fixture -- prose "down 2.1% year on year" minted
#     `MY1994/95 = 2.1 $/bu (actual)` (a percentage manufacturing a price citation), and "near 250 cents
#     per bushel" minted `MY2002/03 = 2.5 $/bu`. THE EXTRAS PREDICATE IS NOW SCALE-1.0 EQUALITY AT 2 dp,
#     and the numerals the prose wore a PERCENT sign on are excluded outright (orchestrator._stated_values
#     records them; see `_stated_magnitudes`). The delegation discipline is intact where it belongs: the
#     CAUTION BANNER still runs `_num_matches` over the pooled values and is untouched, so nothing about
#     "is the prose backed" has a second opinion. What changed is a strictly NARROWER question with a
#     strictly one-sided failure mode -- a missed extra row (today's behaviour) rather than an invented one.
_MAX_EXTRA_ROWS = 6
_EXTRA_SUFFIXES = "bcdefghijklmnopqrstuvwxyz"
_EXTRA_DP = 2


def _stated_magnitudes(stated) -> list[float]:
    """The stated magnitudes an EXTRA row may be minted against: `stated`, less any numeral the prose wore
    a percent sign on. `orchestrator._stated_values` returns a list SUBCLASS carrying that subset on
    `.percent`; a plain list (every direct/legacy caller, every fixture) carries none and is used whole."""
    pct = set()
    for p in (getattr(stated, "percent", ()) or ()):
        try:
            pct.add(round(abs(float(p)), _EXTRA_DP))
        except (TypeError, ValueError):
            continue
    out = []
    for s in (stated or []):
        try:
            v = abs(float(s))
        except (TypeError, ValueError):
            continue
        if round(v, _EXTRA_DP) in pct:
            continue
        out.append(v)
    return out


def _row_matches_value(rv, stated) -> bool:
    """True when the prose states THIS row's value at scale 1.0, to 2 decimal places. See correction (B):
    an extra footer row is a claim of identity, so no rescale arm and no unit bridge. MAGNITUDE-insensitive
    to sign only, the one concession the estate's numerals demand (`_num_matches`' own rationale: a prose
    verb carries the direction, an injected delta row carries the minus). Any failure reads as NO match --
    an omitted extra row, never an invented one."""
    try:
        v = abs(float(str(rv).replace(",", "")))
    except (TypeError, ValueError):
        return False
    tv = round(v, _EXTRA_DP)
    return any(round(s, _EXTRA_DP) == tv for s in _stated_magnitudes(stated))


def extra_number_citations(call: dict, i: int, stated: Optional[list[float]]) -> list[Citation]:
    """The additional [N{i}b..] rows a call owes the reader: every SERVED row, other than the headline,
    whose value the prose states. Empty (the common case) -> the footer is byte-identical.

    The label is the headline's shape with the ROW's own period substituted and the row's estimate role
    appended, so the two lines read as siblings of one lookup rather than as two lookups. `estimate_role`
    is rendered ONLY here: putting it on the headline would rewrite every existing footer in the estate,
    and the polarity pin (prose states the headline only -> byte-identical output) is the thing that keeps
    this whole pass auditable."""
    out: list[Citation] = []
    rows = call.get("rows") or []
    # `len(rows) < 2` is the whole entry fence and it subsumes more than it looks: a zero-row read has no
    # value to cite, a single-row read IS its headline, and the EMPTY-2 collapsed-zero ESR aggregate is
    # single-row BY DEFINITION (`agent._is_zero_esr_aggregate` requires exactly one row), so the class that
    # must assert no value can never reach this pass.
    if not stated or len(rows) < 2 or call.get("status") not in (None, "ok"):
        return out
    q = call.get("query", {}) or {}
    table, metric = q.get("table", ""), q.get("metric", "")
    src = _source_label(table)
    rH = max(rows, key=_row_order_key)
    mags = _stated_magnitudes(stated)             # percent-numerals dropped once, not once per row
    if not mags:
        return out

    def _row_period(r: dict):
        # the ROW's own period identity, then the query's as the fallback: a tall vintage table surfaces
        # `period` per row (silver_wasde -> marketing_year), a wide one may only carry the query scope.
        return r.get("period") if (r or {}).get("period") not in (None, "") else q.get("period")
    # SEEDED WITH THE HEADLINE'S OWN (value, period): a vintage table legitimately serves the same MY on two
    # releases, and the headline is already on the page -- re-rendering it as an extra is a duplicate footer
    # line, not a second fact.
    seen: set[tuple] = {(str(rH.get("value")), str(_period_label(_row_period(rH))))}
    # CORRECTION (A): rank NEWEST-first, cap that ranking, render the survivors ascending.
    cands: list[dict] = []
    for r in sorted(rows, key=_row_order_key, reverse=True):
        if len(cands) >= _MAX_EXTRA_ROWS:
            break
        if r is rH:
            continue
        val = (r or {}).get("value")
        if val in (None, "") or not _row_matches_value(val, mags):
            continue
        key = (str(val), str(_period_label(_row_period(r))))
        if key in seen:
            continue                              # one MY on two vintages is ONE fact to a reader
        seen.add(key)
        cands.append(r)
    for r in sorted(cands, key=_row_order_key):
        val = (r or {}).get("value")
        per = _period_label(_row_period(r))
        unit = r.get("unit") or _metric_unit(table, metric, q.get("commodity"))
        geo = q.get("country") or (str(r.get("country")).strip() if r.get("country") else None)
        scope = " ".join(x for x in (q.get("commodity"), geo, per) if x)
        label = f"{src} {metric} {scope} = {_fmt(val)} {unit}".strip()
        tags = [t for t in (str(r.get("revision_stamp") or "").strip(), _print_kind(r)) if t]
        if tags:
            label += " (" + ", ".join(tags) + ")"
        loc = {"kind": "number",
               **{k: q.get(k) for k in ("table", "metric", "commodity", "country", "asof")},
               "period": (r.get("period") if r.get("period") not in (None, "") else q.get("period"))}
        out.append(Citation(id=f"N{i}{_EXTRA_SUFFIXES[len(out)]}", kind="number", label=label, source=src,
                            date=_row_known_date(r), value=str(val), unit=(unit or None),
                            locator=loc, payload={"query": {**q, "period": loc["period"]}, "rows": [r]}))
    return out


def from_evidence(row: dict, i: int) -> Citation:
    """Build a Citation from a retrieve() evidence row. page/char/snippet are forward-compatible slots (null until
    the page-citation recovery populates them) so document citations become click-to-page with no schema change."""
    # source stays the RAW id here so the machine citation list stays join-keyed to `evidence` rows (the
    # receipts drawer partitions by source|date); official display names are applied where the text is
    # SHOWN (structured.sources + the cited-sources footer). 6.4 gives the drawer official names via source_key.
    src, sk, date = row.get("source", ""), row.get("source_key", ""), row.get("date")
    text = row.get("text") or ""
    snippet = text[:140] + ("..." if len(text) > 140 else "")
    label = f"{src} ({date}): {snippet}"
    # snippet (140-char) rides the locator so a durable turn keeps a click-to-hover receipt after the full
    # evidence text is trimmed off the persisted payload (6.4). page/char stay null for old props; W2.1 props
    # carry char_start/char_end/offset_kind ('exact'|'block'|'none') -- copied through so 6.5 click-to-page can
    # resolve the source PDF page DETERMINISTICALLY (offsets-first) instead of fuzzy-matching the snippet.
    locator = {"kind": "doc", "source_key": sk, "page": row.get("page"),
               "char_start": row.get("char_start"), "char_end": row.get("char_end"),
               "offset_kind": row.get("offset_kind"), "snippet": snippet}
    return Citation(id=f"E{i}", kind="evidence", label=label, source=src, date=date,
                    locator=locator, payload={"source_key": sk, "text": text})


def unify(evidence_rows: Optional[list[dict]] = None, number_calls: Optional[list[dict]] = None,
          stated: Optional[list[float]] = None) -> list[Citation]:
    """One numbered citation list spanning document evidence (E1..) and numbers (N1..) for a hybrid answer.

    CYCLE-5 FOOTER-1: `stated` = the magnitudes the ANSWER states (orchestrator._stated_values). When it is
    passed, each call's headline citation is followed by the extra rows that back the prose's other stated
    figures, BEFORE the next call's citation -- so [N] indexing stays ascending and every existing index
    keeps its meaning. Omitted (every other caller, and every turn whose prose states only headlines) ->
    the list is byte-identical to the pre-CYCLE-5 one."""
    cits = [from_evidence(r, i) for i, r in enumerate(evidence_rows or [], 1)]
    for i, c in enumerate(number_calls or [], 1):
        cits.append(from_number(c, i))
        if stated:
            cits += extra_number_citations(c, i, stated)
    return cits


def render(cits: list[Citation]) -> str:
    """A citations block for the answer footer (source + knowledge date make the point-in-time provenance visible)."""
    lines = []
    for c in cits:
        tail = f"  [known {c.date}]" if (c.date and c.kind == "number") else (f"  [{c.date}]" if c.date else "")
        lines.append(f"[{c.id}] {c.label}{tail}")
    return "\n".join(lines)
