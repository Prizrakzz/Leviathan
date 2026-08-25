"""Unified provenance citations — one schema spanning DOCUMENT evidence (chunks) and NUMBERS (silver lookups).

A Citation carries a human `label`, a `source`, a knowledge `date`, and a machine `locator` (the click-target the
UI resolves): for a number, the exact leakage-safe query to re-run as a drill-down; for a document, a pointer to
the source doc. The document locator carries `page`/`char_start`/`char_end`/`offset_kind`/`snippet` SLOTS — the
char/offset fields populate for W2.1 props and drive 6.5 click-to-page (deterministic offsets-first page
recovery, fuzzy snippet-match fallback) — so numbers and page-level document citations render through one path.
"""
from __future__ import annotations

import datetime as _dt
import re
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


# -- PA-10(a) (2026-08-25): THE METRIC RENDERS THROUGH THE ANALYST DISPLAY --------------------------------
# The [N] label is read TWICE and both readers were handed the raw registry slug: the writer's numbers panel
# (`orchestrator._numbers_block`) and the reader's `## Sources` list (`answer._cited_sources_block`). The
# persona forbids exactly that token ("NEVER emit an internal identifier of ANY kind", answer.py:220-222)
# and `register.internal_leaks` COUNTS it (register.py:821-826), so the run-6 census' 69 leaked ids were in
# large part the writer typing back what the panel gave it. ONE MAPPING, NEVER TWO: `numbers.cascade
# ._metric_display` is the analyst path the cascade lines have used since the GN-2 label fold (9ede60ed);
# a second copy of Metric.label resolution is precisely how two lanes come to disagree about what a metric
# is CALLED. The machine identity is untouched in `locator`/`payload`, which is what a drill-down re-runs.
#
# THE ROW'S DECLARED PRINT KIND OUTRANKS THE CARD'S METRIC LABEL, and that guard is not optional. Measured
# on this file's own fixture: `silver_futures_eod.settle` is labeled "settlement price", and that card also
# serves ICE `ohlcv-1d` bars whose `settle_kind` is `close` -- rendering the label there would mint
# "settlement price ... (session close)", the ICE mislabel `eval._SETTLE_MISLABEL_RX` exists to CONVICT.
# So when a row declares its own print kind and the card's label asserts a DIFFERENT one, the row wins and
# the metric renders exactly as it does today. Keyed on the kind TOKEN, not the phrase, so a label that
# names the row's OWN kind ("settlement price" on a settlement row) is kept and an unrelated label
# ("open interest") is never suppressed.
_KIND_RX = {
    "settlement": re.compile(r"settl", re.I),
    "close": re.compile(r"\bclose\b|\bclosing price\b", re.I),   # never "closing stocks" -- not a print kind
    "cash_index": re.compile(r"cash index", re.I),
    "mark_to_market": re.compile(r"mark[- ]to[- ]market", re.I),
}


def _kind_conflict(display: str, row: dict) -> bool:
    """True when `display` asserts a print kind OTHER than the one this row declares."""
    kind = str((row or {}).get("settle_kind") or "").strip()
    if not kind or not display:
        return False
    return any(rx.search(display) for k, rx in _KIND_RX.items() if k != kind)


def _metric_display_name(table: str, metric, row: Optional[dict] = None) -> str:
    """The ANALYST name for a metric on a citation label -- `_metric_unit`'s twin, and a DELEGATION.

    Lazy import (the `_series_truncated` / `_zero_aggregate` discipline: this module keeps no import-time
    dependency on the numbers stack), and ANY failure returns the slug -- today's rendering to the byte,
    never a raise. An unlabeled metric also returns the slug: the fence tightens family-by-family exactly
    as labels land, which is `register._labeled_metric_slugs`' own stated rule."""
    if not metric:
        return str(metric or "")
    try:
        from leviathan.graphrag.numbers.cascade import _metric_display
        disp = _metric_display({"table": table, "metric": metric}) or str(metric)
    except Exception:  # noqa: BLE001 -- an unregistered table's label must render, never raise
        return str(metric)
    if disp == str(metric):
        # PA-10d (2026-08-25): the DERIVED variants (_delta/_pct/_era_diff, minted by the cascade's
        # delta legs) carry no label of their own, so the raw id reached the menu line beside a labeled
        # base ("000ha_delta" in the re-judge residual-leak census). Resolve the BASE metric's label and
        # qualify it in plain language; an unlabeled BASE still renders the slug (the family-by-family
        # tightening rule, unchanged).
        for suf, word in (("_era_diff", "era difference"), ("_delta", "change"), ("_pct", "% change")):
            if str(metric).endswith(suf):
                try:
                    base = _metric_display({"table": table, "metric": str(metric)[: -len(suf)]})
                except Exception:  # noqa: BLE001
                    base = None
                if base and base != str(metric)[: -len(suf)]:
                    disp = f"{base} ({word})"
                break
    return str(metric) if _kind_conflict(disp, row or {}) else disp


def _contract_display(slug) -> str:
    """The analyst name for a contract slug on a citation label ("south_african_white_maize_jse" ->
    "JSE white maize") -- the re-judge residual-leak census was 100% this column. Lazy import, any
    failure returns the input unchanged (today's rendering to the byte). The machine identity stays in
    `locator`/`payload`, the same address-vs-display doctrine as the metric twin above."""
    if not slug:
        return str(slug or "")
    try:
        from leviathan.graphrag import display as _dp
        return _dp._contract_label(str(slug)) or str(slug)
    except Exception:  # noqa: BLE001
        return str(slug)


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
    then knowledge_date, then contract_month). The series query (numbers.query._total_order) sorts rows
    ASCENDING, so the FRESHEST observation is max() over this key — computed rather than trusting rows[-1]
    so an engine-arbitrary sample can never headline the oldest print (judged-30 RCA (b)).

    T1-5 (CASCADE_HOME_AND_SMALL_ITEMS) CLOSES X3, THE DEFERRED TERM `query._total_order` NAMES BY NAME
    ("there is already a second, INCOMPLETE copy in `citations._row_order_key` (it omits `contract_month`,
    X3, deferred-and-named)"). WHY IT MATTERS AND WHERE: on a CURVE read -- a per-expiry price table
    returning many rows for ONE trading session -- every row ties on `data_date`, on `year`/`month`, on
    `period` and on `knowledge_date`, so the key was CONSTANT across the whole result and `max()` returned
    `rows[0]`: whichever expiry the engine happened to hand back first. That is the same Athena-vs-pg
    arbitrariness `_total_order` exists to remove, surviving in the one copy of the key that had drifted.

    THE POSITION IS THE SQL's, NOT A NEW CHOICE. `query._order_aliases` ranks `contract_month` AFTER
    `knowledge_date` and AHEAD of `unit`; `unit` is not in this key at all, so the SQL's position for the
    term is the tail, exactly where it is appended here.

    THE BEHAVIOR CHANGE, PINNED RATHER THAN DESCRIBED (tests/unit/test_citations_row_order.py): 'YYYY-MM'
    sorts lexically == chronologically, so the curve's expiries now sort ASCENDING with the NEAREST
    delivery month FIRST and the FURTHEST LAST -- and `max()` therefore headlines THE FURTHEST-DATED
    EXPIRY of the session, deterministically and identically on both backends. It is the row the series
    SQL's own ORDER BY puts last, which is the property that makes the headline reproducible; it is NOT
    the front month, and a caller that wants the front month has `agg='front_expiry'`, which selects one
    row before this key is ever consulted. A row carrying no `contract_month` contributes "" and every
    non-curve read is byte-identical."""
    def _i(x) -> int:
        try:
            return int(x)
        except (TypeError, ValueError):
            return -1
    return (str(r.get("data_date") or ""), _i(r.get("year")), _i(r.get("month")),
            str(r.get("period") or ""), str(r.get("knowledge_date") or ""),
            str(r.get("contract_month") or ""))


def _parse_date(s) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


# ══ D-HP G1 REMEDIATION-2 R2-b (2026-08-14) -- "OK + ALL-BLANK VALUES" IS AN ABSENCE, EVERYWHERE ═══════
#
# THE MEASURED DEFECT (G1 decision-1 r3, clause (2), row `dv_sub_ddg_floor` on inv3). A numbers read came
# back `status: 'ok'`, `row_count: 1`, `rows: [{'value': ''}]`. Three consumers disagreed about what that
# is, and every one of them defaulted to "a row, therefore a figure":
#   * `from_number` took its `elif rows:` branch and rendered `... ars_usd = ` -- a menu line ending in a
#     bare "=" with nothing behind it, in BOTH the prompt panel and the reader's `## Sources` list;
#   * `orchestrator._numbers_block`'s empty-read directive is gated on the ROWS LIST being empty, so it
#     did not fire at all on that turn -- the writer was never told the read produced nothing;
#   * `answer._number_handle_value` DID read it correctly (`Citation.value == ''` -> None) and removed the
#     handle, so the only place the truth was known was the last one, after the model had already cited it.
# The r2 diagnosis was honest about its own population (55 of 55 events sat under four empty STATUSES);
# this shape simply was not in it. It is the same family, one branch short.
#
# THE FIX IS ONE PREDICATE WITH ONE PRODUCER, `is_empty_read`, delegated and never copied -- the
# `_series_truncated` / `_is_zero_esr_aggregate` discipline exactly, and for the same reason: the prompt
# directive, the menu label and the resolver's charge must not be able to disagree about which reads are
# in the class. It is ARM-SYMMETRIC BY CONSTRUCTION (it is a truth fix on the SHIPPED numbers menu, which
# both arms and the live product read; the control arm carried the identical defect on r3 inv1 [N30]), and
# every turn whose reads all carry a value is BYTE-IDENTICAL because the predicate is false on all of them.
#
# A NUMERIC ZERO IS NOT BLANK, and that distinction is the whole safety of the predicate: `0`, `0.0` and
# `"0"` are MEASURED quantities and must keep rendering as figures. Only `None`, `""` and whitespace are
# blank -- which is why the test is written against `is None` / `str(...).strip()` and never against
# truthiness (`0 or ""` is `""`, and a truthiness test would erase every measured zero on the estate).
def _value_blank(row) -> bool:
    """True when a returned row carries NO value at all (None / empty / whitespace). A numeric 0 is a
    VALUE and reads False here."""
    if not isinstance(row, dict):
        return True
    v = row.get("value")
    return v is None or (isinstance(v, str) and not v.strip())


def values_all_blank(rows) -> bool:
    """True when rows came back AND not one of them carries a value. False on an empty list (that is the
    ZERO-ROW class, which already has its own branch and its own label)."""
    rows = rows or []
    if not isinstance(rows, (list, tuple)):
        return False               # a malformed record is NOT an absence -- see `is_empty_read`'s note
    return bool(rows) and all(_value_blank(r) for r in rows)


def is_empty_read(call) -> bool:
    """THE ONE PRODUCER for "this numbers read produced no value at all" -- zero rows OR rows that are all
    blank. Read by `from_number` (the label), `orchestrator._numbers_block` (the directive) and
    `answer._addresses_empty_row` (the charge), so the three can never disagree.

    A MALFORMED RECORD IS NOT AN ABSENCE. `rows` that is neither a list nor a tuple reads False, so a
    garbage record keeps whatever charge it carries today rather than being promoted into a class that
    exists to describe a read the estate actually served."""
    if not isinstance(call, dict):
        return False
    rows = call.get("rows") or []
    if not isinstance(rows, (list, tuple)):
        return False
    return (not rows) or values_all_blank(rows)


# The sentinel `status` `from_number` hands `_empty_label` for the blank-value shape. It is NOT a status any
# numbers agent emits (the agent said `ok`, and truthfully -- the query ran): it is this module's own name
# for "rows came back, none of them carry a value", so the taxonomy stays status-driven and every existing
# branch is reached by exactly the statuses it was reached by before.
BLANK_VALUE_STATUS = "__blank_value__"


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
    if status == BLANK_VALUE_STATUS:
        # D-HP G1 REMEDIATION-2 R2-b (2026-08-14). THE THIRD EMPTY SHAPE, and it had no branch here at all:
        # a read that comes back status `ok` with rows, EVERY one of which carries an EMPTY value. The
        # measured row is r3 inv3 `dv_sub_ddg_floor` [N1] -- silver_fred_fx ars_usd, status `ok`,
        # row_count 1, `rows=[{value: ''}]` -- which took the `elif rows:` branch below and rendered as
        # `... ars_usd = ` : a numbered menu line ending in a bare "=" with NOTHING behind it. The writer
        # cited it, exactly as it had cited the marked shapes, and the resolver charged the handle.
        # It is not a timing claim and it is not "no matching rows" (a row DID come back), so it gets its
        # own parenthetical under the SAME marker prefix every other branch carries -- the prefix is what
        # `_numbers_block`'s directive and every existing membership assertion key on.
        return f"NO ROWS RETURNED (the returned row carries no value at all -- blank field as of {a})"
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
    # PA-10(a): the metric is spoken in the ANALYST's name on every branch below, from ONE resolution.
    # All three branches render `{src} {metric} {scope} = ...`, so a display name on the value-bearing
    # branch alone would have the same call's empty read and its zero-aggregate read naming the metric
    # differently in one footer -- the drift this file refuses everywhere else (`_period_label`'s "MYMY").
    mdisp = _metric_display_name(table, metric, rH)
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
    # T1-4 (CASCADE_HOME_AND_SMALL_ITEMS): THE SPREAD STAT'S TWO LEGS, WHICH NOTHING READ.
    # `numbers.agent._stat_calls` writes `near_month` / `far_month` onto a spread row precisely BECAUSE a
    # difference between two contracts can never carry a single `contract_month` (the card's own rule: never
    # attach a delivery month to a row that has none). This function read `contract_month` and nothing else,
    # so a carry figure reached the reader's `## Sources` list with NO delivery months at all -- "stats
    # spread corn_cbot = 12.5 spread", a number whose entire meaning is WHICH TWO EXPIRIES it spans.
    # BOTH LABELS OR NEITHER, AND NEVER A GUESS FROM A PARTIAL PAIR. A spread naming one leg is not a
    # narrower fact, it is a WRONG one -- the reader would read the named month as the figure's delivery,
    # which is exactly the single-month semantics the stat row refuses to claim. Identical legs are refused
    # for the same reason: that row is not a spread and this label would assert a span that is not there.
    _near = str(rH.get("near_month") or "").strip()
    _far = str(rH.get("far_month") or "").strip()
    legs = f"{_near}->{_far}" if (_near and _far and _near != _far) else ""
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
    # `cmonth` wins when a row carries one: it is the row's OWN declared expiry, and a row carrying both a
    # contract_month and a leg pair would be a producer defect this label must not paper over. A row with
    # neither renders exactly as it did before T1-4 -- the anti-vacuity property the spread pin asserts.
    _delivery = (f"delivery {cmonth}" if cmonth else (f"delivery {legs}" if legs else None))
    # G4c(iii): THE Z-SCORE'S WINDOW AND ITS SERIES, WHICH NOTHING READ -- T1-4's defect on the other
    # axis. `numbers.agent._stat_calls` writes `z_window` / `z_series` onto a zscore row for exactly
    # the reason it writes near_month/far_month onto a spread row: the figure's entire meaning is HOW
    # MANY points it was ranked against and WHICH series those points came from, and neither reached
    # `## Sources`. BOTH LABELS OR NEITHER, AND NEVER A GUESS FROM A PARTIAL PAIR -- a window with no
    # series names a length with no subject, and a series with no window asserts the whole history,
    # which after the declared-window narrowing is exactly the claim that would be false. A row
    # carrying neither renders EXACTLY as it does today: the anti-vacuity property the pin asserts.
    _zw = str(rH.get("z_window") or "").strip()
    _zs = str(rH.get("z_series") or "").strip()
    _zspan = f"vs {_zw} points of {_zs}" if (_zw and _zs) else ""
    scope = " ".join(x for x in (_contract_display(q.get("commodity")), geo, per, _delivery, _zspan) if x)
    # D-HP G1 REMEDIATION-2 R2-b: the blank-value read is routed to the ABSENCE branch BEFORE either
    # rows-bearing branch can claim it. `_blank` is false on every read that carries a value, so both
    # branches below are byte-identical on every such turn.
    _blank = values_all_blank(rows)
    if rows and not _blank and _zero_aggregate(call):
        # D-PQ EMPTY-2: the collapsed-aggregate class renders the MARKER, exactly as the zero-ROW class
        # does. `value` and `unit` are withheld for the same reason EMPTY-1 withholds them: a unit with no
        # value behind it reads as a quantity whose digits are missing, and `answer._number_handle_value`
        # reads `Citation.value` -- leaving "0.0" there would let a stand-in [N] handle splice a measured
        # zero into the prose, which is the assertion this whole class exists to refuse. The row set is
        # untouched in `payload`/`locator`, so the drill-down still re-runs the real read.
        label = f"{src} {mdisp} {scope} = {_ZERO_AGG_LABEL}".strip()
        value, unit = None, None
    elif rows and not _blank:
        label = f"{src} {mdisp} {scope} = {_fmt(value)} {unit}".strip()
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
        # ══ PA-8(a) (2026-08-25): THE ABUNDANCE MARKER -- HOW MANY ROWS THIS CALL ACTUALLY SERVED ════════
        # This line headlines `max(rows, _row_order_key)` and says NOTHING about the other rows, so a
        # 24-month MPOB stock series and a single latest read render as the same one-line panel entry.
        # The measured cost is `gn2_mpob_stock_build` ("walk me through the stocks month by month"),
        # 2/5 ON ALL THREE SEATS: the agent held the monthly series and the writer, reading this panel,
        # was told there was one number. The same class is recorded further down this file -- 35 served
        # WASDE rows shown as one line and scored as fabrication -- and the CYCLE-5 fix threaded `stated=`
        # into the READER's footer only; `orchestrator._numbers_block` still calls `unify(None, calls)`,
        # because the panel is built BEFORE the prose exists and there is nothing yet to match rows to.
        # So the panel states the COUNT. The markers beside it (TRUNCATED, NO ROWS RETURNED, the
        # zero-aggregate label) already cover every scarcity class; this is the missing ABUNDANCE one.
        #
        # FACT ONLY, NO IMPERATIVE (the split pinned in test_citations.py, and restated below): the same
        # string renders into the reader's `## Sources` list, so what lives here is provenance a reader is
        # entitled to -- how many observations back this line and which one is displayed.
        # NOTHING ABOUT WHICH ROWS ARE SERVED CHANGES -- `rows` is the call's own served set, `payload`
        # still carries rows[:3], and the drill-down still re-runs the same read.
        _trunc = _series_truncated(call)
        if len(rows) > 1:
            # THE SPAN RIDES ONLY WHEN THE ROWS ACTUALLY SPAN SOMETHING, and never opposite a TRUNCATED
            # marker, which states its own: one span per line, from whichever marker owns it.
            # `_covered_span` collapses to a single date when every row carries the same one, and 35 rows
            # of ONE WASDE vintage (the motivating serve below -- 35 marketing years, one release date)
            # would then read as a one-day series, the opposite of what the reader must take from it.
            _sspan = "" if _trunc else _covered_span(rows)
            label += (f" [{len(rows)} rows served"
                      + (f", covering {_sspan}" if ".." in _sspan else "")
                      + "; newest shown]")
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
        if _trunc:
            _span = _covered_span(rows)
            _cap = q.get("limit")
            label += (" [TRUNCATED at the "
                      + (f"{_cap}-row cap" if _cap else "row cap")   # a fixture call may carry no limit
                      + ": NEWEST slice only"
                      + (f", covering {_span}" if _span else "")
                      + " -- not the complete record]")
    else:
        _st = BLANK_VALUE_STATUS if _blank else status
        label = f"{src} {mdisp} {scope} = {_empty_label(_st, asof)}".strip()
        # D-HP G1 REMEDIATION-2 R2-b: the blank-value read gives up its VALUE too, for the same reason the
        # zero-row and zero-aggregate classes give up theirs -- `answer._number_handle_value` reads
        # `Citation.value`, and leaving `''` there left the ONE consumer that had it right depending on a
        # string test rather than on the class. `payload`/`locator` keep the real row set, so the
        # drill-down still re-runs the read that produced the blank.
        value = None
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
# CYCLE-6 (2026-08-08), the reader-precision arm's OWN fence -- see `_row_matches_value`. An identity claim
# must be at least twice as tight as `verify._num_matches`' 1% BACKING tolerance, or a 1-significant-digit
# restatement ("about 4") would bin a whole neighbourhood of rows (4.15 / 4.24 / 4.4 all round to 4 at d=0)
# and mint a footer line for each. Rounding, never binning -- on this lane the binning refusal needs a
# relative floor because d=0 alone does not supply one.
_EXTRA_REL_TOL = 0.005
# A row whose own CARD says it is denominated in percent. `orchestrator._stated_values` fences percent-marked
# numerals out of the extras predicate wholesale (correction (B): "down 2.1% year on year" minted a
# `MY1994/95 = 2.1 $/bu` PRICE row), but that fence over-reaches in exactly one direction: when the row the
# numeral names IS a percentage, a percent sign is the correct unit for it, not a category error. Measured
# on gate-3 dcw pass1 `dcw_macro_on_soy`: the served `silver_cot.mm_pct_oi = 15.7316` (unit "pct of OI
# (signed)") was stated as "15.7%" and faced the reader with no footer row at all. The un-fence is per CALL
# and reads only card-declared facts (the metric name and the registry unit), so the motivating fabrication
# is still refused by construction -- `avg_farm_price` carries neither token.
_PCT_UNIT_RX = re.compile(r"(?:\A|[\s(/])(?:%|pct|percent)", re.I)
_PCT_METRIC_RX = re.compile(r"(?:\A|_)pct(?:_|\Z)|percent", re.I)


def _percent_typed(call: dict, unit: str | None) -> bool:
    """True when THIS call's rows are percentages by the card's own declaration."""
    metric = str(((call or {}).get("query") or {}).get("metric") or "")
    return bool(_PCT_UNIT_RX.search(unit or "") or _PCT_METRIC_RX.search(metric))


def _float_decimals(v: float) -> int:
    """Decimal places a stated magnitude was written to, recovered from the float's SHORTEST repr.
    `orchestrator._stated_values` hands its consumers parsed floats, so unlike `verify._token_decimals`
    this cannot see a written trailing zero ('0.20' arrives as 0.2 -> 1 place). That direction is safe:
    fewer places = a WIDER rounding window = more candidate rows, and the relative fence below is what
    bounds the width. Scientific-notation reprs (1e+21) carry no fractional part and read as 0."""
    s = repr(float(v))
    if "e" in s or "E" in s or "." not in s:
        return 0
    return len(s.split(".", 1)[1].rstrip("0"))


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
    an omitted extra row, never an invented one.

    CYCLE-6 (2026-08-08) READER-PRECISION ARM, the footer twin of `verify._reader_precision_match`. The
    2-dp equality above is itself a rounding test, but only at ONE fixed precision, and it therefore misses
    every figure a reader restated more COARSELY than 2 places. Measured on gate-3 covenant `ab_cmp_coffee`:
        row  silver_conab_coffee.production_thousand_bags MY2026 = 35763.1
        prose                                                      "35,763"   (a correct 0-dp round)
        round(35763, 2) = 35763.0  !=  round(35763.1, 2) = 35763.1  -> no match, no footer row
    So the arm accepts when the row is the stated numeral rounded at the numeral's own written precision
    -- AND the relative gap is inside `_EXTRA_REL_TOL`. THE RELATIVE FENCE IS THE BINNING REFUSAL AND IT IS
    NOT OPTIONAL HERE: the verifier's arm can only ever convert strip->keep, while this one MINTS A LINE,
    so a bare d=0 window (+-0.5) would let "about 4" claim identity with 4.15, 4.24 AND 4.4 off one 35-row
    WASDE serve -- three invented rows from one vague numeral. 35763 vs 35763.1 is 3e-6 relative and
    passes; 4 vs 4.4 is 10% and is refused. The two arms stay deliberately different for the same reason
    correction (B) made them different: backing and identity are different questions.

    CYCLE-6 REVIEW (2026-08-08), LOW 9: this is now a THIN VIEW on `_matcher`, which is what production
    actually runs (`_match_candidates` compiles the predicate once per magnitude list). It is kept as the
    named statement of the rule -- and pinned equivalent to the compiled form -- rather than deleted."""
    return _matcher(_stated_magnitudes(stated))(rv)


def _matcher(mags: list[float]):
    """`_row_matches_value` COMPILED ONCE for a magnitude list, as a `value -> bool` closure. Same
    predicate, same two arms, same order; what changes is that the 2-dp bucket becomes a set lookup and
    the reader-precision arm bisects a sorted index instead of rescanning every stated magnitude per row.
    Built because the completion pass walks EVERY served row of EVERY call and the estate serves 5000-row
    windows: the linear form cost 13.7 s on the worst case measured, which a live turn cannot pay."""
    import bisect
    exact = {round(abs(float(m)), _EXTRA_DP) for m in mags}
    ms = sorted(abs(float(m)) for m in mags)
    # the widest reader-precision window any of these magnitudes can open (d=0 -> +-0.5); the bisect only
    # has to consider magnitudes inside it, and each is then tested by the full two-clause rule
    span = max((0.5 * 10.0 ** (-_float_decimals(m)) for m in ms), default=0.0)

    def _hit(rv) -> bool:
        try:
            v = abs(float(str(rv).replace(",", "")))
        except (TypeError, ValueError):
            return False
        if round(v, _EXTRA_DP) in exact:
            return True
        if not v or not ms:
            return False
        lo = bisect.bisect_left(ms, v - span)
        for s in ms[lo:bisect.bisect_right(ms, v + span)]:
            gap = abs(v - s)
            if gap <= 0.5 * 10.0 ** (-_float_decimals(s)) and gap <= _EXTRA_REL_TOL * v:
                return True
        return False
    return _hit


def row_period(call: dict, r: dict):
    """The ROW's own period identity, then the query's as the fallback: a tall vintage table surfaces
    `period` per row (silver_wasde -> marketing_year), a wide one may only carry the query scope.
    CYCLE-6: lifted to module scope UNCHANGED so the hybrid-lane completion pass and `_cited_sources_block`
    key their de-dup on the identical (value, period) pair the extras pass has always used -- two readings
    of "which row is this" is how a de-dup silently stops de-duping."""
    q = (call or {}).get("query") or {}
    return r.get("period") if (r or {}).get("period") not in (None, "") else q.get("period")


def row_key(call: dict, r: dict) -> tuple:
    """The de-dup identity of one served row as the footer states it: (value, period label)."""
    return (str((r or {}).get("value")), str(_period_label(row_period(call, r))))


def headline_row(call: dict) -> dict:
    """The row `from_number` headlines for this call ({} when it serves none) -- the SAME selector, so the
    completion pass can never mistake the line already on the page for a missing one."""
    rows = (call or {}).get("rows") or []
    return max(rows, key=_row_order_key) if rows else {}


def _call_magnitudes(call: dict, stated) -> list[float]:
    """The stated magnitudes THIS call's rows may be minted against: the percent-fenced list, plus the
    percent-marked numerals when the call is itself percent-denominated (see `_percent_typed`).

    CYCLE-6 REVIEW (2026-08-08), MAJOR 5 -- TWO CONDITIONS, NOT ONE. The un-fence originally read only the
    CALL's type, so one percent-denominated call turned EVERY percent numeral in the whole answer into a
    candidate name for its rows: "Managed money holds 15.7% of open interest, down 2.1% on the week" minted
    `mm_pct_oi = 2.1` from a week-on-week CHANGE -- correction (B)'s own fabrication class, restored for
    exactly the table family where percent numerals are densest. The numeral must now ALSO read as a LEVEL
    by its own syntax (`orchestrator._percent_is_level`), which is what `.percent_level` carries. Reading
    `percent_level` STRICTLY (no fallback to `.percent`) is deliberate: an object that carries the old
    annotation and not the new one gets no un-fence at all, i.e. the pre-cycle-6 refusal.
    THIS ALSO NARROWS THE numbers_only LANE (`extra_number_citations` calls here): `.percent_level` is a
    subset of `.percent`, so that lane can only ever mint FEWER extra rows than it did -- never more."""
    mags = _stated_magnitudes(stated)
    if _percent_typed(call, _metric_unit(((call or {}).get("query") or {}).get("table", ""),
                                         ((call or {}).get("query") or {}).get("metric", ""),
                                         ((call or {}).get("query") or {}).get("commodity"))):
        for p in (getattr(stated, "percent_level", ()) or ()):
            try:
                mags.append(abs(float(p)))
            except (TypeError, ValueError):
                continue
    return mags


def _match_candidates(call: dict, mags: list[float], *, seen: set, skip: dict | None,
                      limit: int = _MAX_EXTRA_ROWS, rowhit=None) -> list[dict]:
    """The served rows of ONE call whose value the prose states, ranked NEWEST-first and capped at `limit`.
    `seen` is MUTATED (the caller decides how wide the de-dup horizon is -- one call for the numbers_only
    extras, the whole footer for the hybrid completion pass); `skip` is the row already on the page.

    CORRECTION (A) lives here: candidates are ranked NEWEST-first and the cap is applied to THAT ranking.
    `_matcher` is what makes this affordable on a 5000-row truncated serve -- the naive form re-derived the
    percent fence and rescanned every stated magnitude PER ROW (measured: 13.7 s on a 30-call x 5000-row
    x 60-magnitude worst case, i.e. a live turn's whole latency budget spent in the footer).

    CYCLE-7 (2026-08-08): `rowhit` lets a caller supply its OWN row predicate while keeping the ranking,
    the cap and the de-dup horizon byte-identical. Only the hybrid completion pass passes one (it asks a
    strictly narrower question than the numbers_only extras -- see `_mint_matcher`); `rowhit=None` is the
    cycle-5 lane, unchanged to the byte."""
    hit = _matcher(mags) if rowhit is None else None
    # FILTER BEFORE SORTING, and that ordering is a measured cost, not a style choice: `_row_order_key`
    # builds a 5-tuple per row, so sorting a 5000-row serve to then keep at most six of them spent 1.5 s
    # of the 1.6 s the pass took. The value test is a set lookup; the sort now runs over the survivors.
    # Semantics are untouched -- filter-then-rank-then-cap selects exactly what rank-then-filter-then-cap
    # selected, because the cap is applied to the same ranking either way.
    matched = [r for r in (call.get("rows") or [])
               if r is not skip and (r or {}).get("value") not in (None, "")
               and (rowhit(r) if hit is None else hit(r.get("value")))]
    cands: list[dict] = []
    for r in sorted(matched, key=_row_order_key, reverse=True):
        if len(cands) >= limit:
            break
        key = row_key(call, r)
        if key in seen:
            continue                              # one MY on two vintages is ONE fact to a reader
        seen.add(key)
        cands.append(r)
    return cands


def _mint_row_citations(call: dict, i: int, rows: list[dict]) -> list[Citation]:
    """Render already-selected rows ASCENDING as letter-suffixed siblings of call `i`, so the reader still
    reads a chronological footer under whatever ranking selected them."""
    out: list[Citation] = []
    q = call.get("query", {}) or {}
    table, metric = q.get("table", ""), q.get("metric", "")
    src = _source_label(table)
    for r in sorted(rows, key=_row_order_key):
        val = (r or {}).get("value")
        per = _period_label(row_period(call, r))
        unit = r.get("unit") or _metric_unit(table, metric, q.get("commodity"))
        geo = q.get("country") or (str(r.get("country")).strip() if r.get("country") else None)
        scope = " ".join(x for x in (q.get("commodity"), geo, per) if x)
        # PA-10(a): the extras are LETTER-SUFFIXED siblings of the headline (N1b, N1c...) rendered into the
        # same footer block, so they speak the metric in the same analyst name -- per ROW, since the row is
        # what declares this line's print kind.
        label = f"{src} {_metric_display_name(table, metric, r)} {scope} = {_fmt(val)} {unit}".strip()
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


def extra_number_citations(call: dict, i: int, stated: Optional[list[float]]) -> list[Citation]:
    """The additional [N{i}b..] rows a call owes the reader: every SERVED row, other than the headline,
    whose value the prose states. Empty (the common case) -> the footer is byte-identical.

    The label is the headline's shape with the ROW's own period substituted and the row's estimate role
    appended, so the two lines read as siblings of one lookup rather than as two lookups. `estimate_role`
    is rendered ONLY here: putting it on the headline would rewrite every existing footer in the estate,
    and the polarity pin (prose states the headline only -> byte-identical output) is the thing that keeps
    this whole pass auditable."""
    rows = call.get("rows") or []
    # `len(rows) < 2` is the whole entry fence and it subsumes more than it looks: a zero-row read has no
    # value to cite, a single-row read IS its headline, and the EMPTY-2 collapsed-zero ESR aggregate is
    # single-row BY DEFINITION (`agent._is_zero_esr_aggregate` requires exactly one row), so the class that
    # must assert no value can never reach this pass.
    if not stated or len(rows) < 2 or call.get("status") not in (None, "ok"):
        return []
    mags = _call_magnitudes(call, stated)         # percent-numerals dropped once, not once per row
    if not mags:
        return []
    rH = headline_row(call)
    # SEEDED WITH THE HEADLINE'S OWN (value, period): a vintage table legitimately serves the same MY on two
    # releases, and the headline is already on the page -- re-rendering it as an extra is a duplicate footer
    # line, not a second fact.
    return _mint_row_citations(call, i, _match_candidates(call, mags, seen={row_key(call, rH)}, skip=rH))


# ══ CYCLE-6 (2026-08-08) FOOTER-COMPLETION: THE SAME HOLE, ON THE HYBRID LANE ═════════════════════════
#
# THE MEASURED FAILURE (gate-3, both probe decks). CYCLE-4 made the reader's PROSE the Sources authority and
# CYCLE-5 made a SERVED ROW citable in its own right -- but cycle-5's producer is only ever reached from
# `orchestrator.run_numbers_only` (through `unify(stated=...)`). On the HYBRID lane a served value can
# therefore face the reader with no footer row at all, two ways, and gate-3 shipped both:
#   (i) THE MODEL STATES IT WITH NO MARKER. dcw pass2 `dcw_gas_nitrogen_squeeze`: "European natural gas as
#       of June 2026 stood at 15.17 USD/mmbtu, with a 5-year z-score of -0.30632 sigma" -- no [N], hence no
#       prose index, hence (by cycle-4's own rule) no footer row, while the record's served_rows carries
#       natural_gas_eu_usd_mmbtu = 15.17 @ 2026-06-01 and its z-score row beside it. Same shape: dcw pass1
#       `dcw_macro_on_soy` (mm_net 160,479 / mm_pct_oi 15.7% / soybean_oil 1,765 / soybean_meal 425) and
#       covenant `ab_cmp_coffee` (35,763 / 1,486,837 / 24.0531).
#  (ii) THE VERIFIER STRIPS THE ONLY MARKER-BEARING SENTENCES for a row (the CYCLE-6 FIX-B class), and the
#       footer drops the row with them -- the reader is left with a figure in a surviving sentence and
#       nothing to check it against.
#
# THE RULE IS CYCLE-4's, EXTENDED ONE STEP, NOT LOOSENED: the FINAL prose is the authority in BOTH
# directions -- an index the prose carries gets its row (HANDLE-4), and a VALUE the prose states gets its
# row too. The join key changes from the handle to the value, which is exactly the join cycle-5 already
# ratified for the other lane; the predicate is cycle-5's own tight one (`_row_matches_value`: scale 1.0,
# 2 dp, percent-fenced, now also correct-at-the-reader's-precision).
#
# FOUR REFUSALS, each one a class this must never resurrect:
#   * a DECLINED / errored call and a ZERO-AGGREGATE refusal ("NO REPORTED FIGURE") mint nothing -- those
#     calls exist to assert the ABSENCE of a figure, and a value-keyed footer row would contradict the very
#     line `from_number` renders for them;
#   * only the FINAL body counts. A value the verifier stripped away must not summon a row: the caller
#     passes the post-strip, post-tidy prose, so a footer row can only ever appear beside surviving text;
#   * NO DOUBLE MINT. The de-dup `seen` is seeded with EVERY row already on the page -- the [N] headline
#     rows the prose still cites, and the extras from any earlier pass -- so a value already footed once
#     (a 30-row window carrying the same print as its own `latest` call, the commonest shape in the deck)
#     is never footed twice;
#   * the per-call cap and the newest-first ranking are cycle-5's, unchanged (blocker-1 discipline) -- and
#     a WHOLE-FOOTER cap sits above them, because a hybrid turn carries many calls where the numbers_only
#     lane carries one. Measured on a 30-call x 5000-row worst case the per-call cap alone let the pass
#     mint 91 rows: a footer nobody reads is a footer that hides the rows that mattered. The global cap
#     is applied to a GLOBAL newest-first ranking, so what survives is the freshest evidence on the page,
#     not whichever call happened to be looked up first.
#
# LANE IDEMPOTENCY, DECIDED EXPLICITLY: the two passes are ONE MECHANISM PER LANE and cannot overlap.
# `run_numbers_only` builds its footer through `unify(stated=...)` + `render` and never calls
# `_cited_sources_block`; the hybrid bodies build theirs through `_cited_sources_block` and never pass
# `stated` to `unify`. The shared `seen` horizon makes the pair idempotent ANYWAY -- running both over one
# footer mints each (value, period) exactly once -- so the disjointness is a fact, not a load-bearing
# assumption.
_MAX_COMPLETION_ROWS = 12

# ══ CYCLE-7 (2026-08-08) THE IDENTITY GATE ON THE COMPLETION MINT ═════════════════════════════════════
#
# GATE-4 CONFIRMED FIX A HEALED ITS THREE MOTIVATING FIXTURES AND MEASURED WHAT IT COST: 11 both-pass rows
# in which a REAL served number, correctly rendered, was attached to a prose numeral that is semantically
# not about it -- a UREA z-score naming a DROUGHT z row, a FARM PRICE naming a z-score, an ONI TEMPERATURE
# naming a z-score, a LAG HORIZON and a LIST MARKER and a RANGE ENDPOINT each naming a measured row. Plus
# the covenant's own instance of the class: one "0.90 z" sprayed into FIVE distinct drought rows.
#
# ONE MEASUREMENT DECIDED THE SHAPE OF THE FIX. Cycle-5's numbers_only extras -- the SAME predicate on the
# SAME kind of data -- produced ZERO over-mints across all five runs, and the difference between the two
# lanes is not the matcher, it is the SCOPE: the extras pass only ever runs on a call the answer is already
# citing, so its rows are siblings of a row the reader can see. The hybrid pass ran on every call on the
# turn. So the completion pass is RE-SCOPED TO THE SAME PLACE, and the match is asked as the identity
# question it actually is:
#
#   (1) PER CALL, AND ONLY AN ESTABLISHED ONE. A row may be minted only from a call whose `[N{i}]` marker
#       the reader still sees -- the call is in context, its headline row is on the page, and the minted
#       row is a sibling of that row. An UNCITED call mints nothing at all.
#   (2) SIGN-EXACT. Magnitude-insensitivity is a BACKING policy (`verify._num_matches`' own rationale: a
#       prose verb carries the direction). It was never an identity policy, and gate-4 shipped four rows
#       that read the opposite direction of the numeral that named them.
#   (3) THE NUMERAL MUST BE UNCLAIMED. A numeral standing beside a handle that already answers for it has
#       its row; a SECOND row for it is over-minting by construction (7 of the 11).
#   (4) NON-DATA NUMERAL SHAPES MINT NOTHING (list markers, range endpoints, lag horizons, quarter labels,
#       ordinals) -- decided in `orchestrator._mint_numerals`, deterministic shapes every one.
#   (5) A d=0 INTEGER NEVER NAMES A NON-INTEGER ROW ("1" cannot be `1.0044 z`).
#   (6) THE UNITS MUST NOT CONTRADICT. A numeral the prose wrote in degC does not name a row denominated
#       in z; a numeral behind a currency symbol does not name a z-score. Both were shipped.
#   (7) THE 2-dp BUCKET IS AN INDEX, NOT AN ARM (CYCLE-8). Every candidate faces the reader-precision
#       WINDOW, bucket hit or not. The relative ceiling of rule (5) stays scoped to d=0, where it is the
#       only thing bounding a flat +-0.5 -- above d=0 the reader's own written precision is the bound, and
#       promoting the ceiling there refused correctly-rounded z restatements. See `_mint_matcher`.
#   (8) ONE ROW PER (STATED VALUE, CALL) (CYCLE-8). A numeral names one fact, not a fan of neighbours --
#       see `prose_completion_citations`. Rules (7) and (8) both fire on gate-5's five-row FX spray.
#
# THE RESIDUAL IS STATED, NOT HIDDEN. Rule (1) gives up the shape FIX A was born for -- a whole call the
# answer never marks, whose values the prose states (gate-3 `dcw_gas_nitrogen_squeeze` pass2, and the
# `dcw_macro_on_soy` and `dcw_farm_price_vintage` shapes with it). That is deliberate and it is the safe
# polarity: a missing bonus row costs a reader one line of context, a wrong-attribution row is a lie with
# a citation on it. The gas class is ALSO covered from the other side -- cycle-6's verify amendment keeps
# the marker-bearing sentences alive, which is what actually healed the gas unlock at gate-4 (the P1 probe
# holds on BOTH passes), and the completion pass was never what fixed it.
# (`_MINT_REL_TOL`, cycle-7's alias for `_EXTRA_REL_TOL` on this lane, is GONE as of the cycle-8 review:
# above d=0 the reader's WRITTEN PRECISION is the bound and a second, tighter relative clause on top of it
# refused correctly-rounded restatements -- see BLOCKER 1 in `_mint_matcher`. Nothing else read it.)
# RULE (5), AND WHY IT IS A CEILING RATHER THAN THE FLAT BAN THE GATE-4 WRITE-UP PROPOSED. "A d=0 integer
# never names a non-integer row" refuses `1 -> 1.0044 z`, which is the measured defect -- and it ALSO
# refuses `35,763 -> 35763.1`, which is the CONAB row cycle-6's reader-precision arm was built for and the
# one shape on this lane that provably needed it. The two are not the same claim and the arithmetic says so
# by a factor of ~1,500: 1 vs 1.0044 is 4.4e-3 relative, 35763 vs 35763.1 is 2.8e-6. A numeral written with
# NO decimals has a half-unit window of +-0.5 whatever its magnitude, so on this arm the relative ceiling
# is the ONLY thing bounding it, and 0.5% is far too loose there -- it is a window that says nothing about
# a small number and everything about a large one. At 1e-4 the measured over-mints go (1 -> 1.0044,
# 1 -> -1.00019, "about 26" -> 26.2459) and every measured 0-dp restatement of a real figure stays
# (35,763 / 1,486,837 / 115,000,000). An EXACT integer row is unaffected: its gap is zero.
_MINT_D0_REL_TOL = 1e-4
# The unit CATEGORIES an identity claim may not cross. Read off the LEADING token of each side, so a
# sloppy tail ("degC in mid-2021") classifies on 'degC' and a unit this table does not know classifies as
# nothing at all -- and an unknown on EITHER side never refuses. Fail-open by construction: this fence can
# only ever remove a row cycle-6 would have minted, never add one.
_UNIT_CLASSES = (
    ("pct", re.compile(r"\A(?:%|pct|percent|percentage|bps|basis points?)\b", re.I)),
    ("temp", re.compile(r"\A(?:°\s*[CF]|deg\s*[CF]|degrees?)\b", re.I)),
    ("z", re.compile(r"\A(?:z|sigma|std|stdev)\b", re.I)),
    ("price", re.compile(r"\A(?:usd|eur|cny|brl|myr|cents?|c/|\$|€|£)\b", re.I)),
    ("mass", re.compile(r"\A(?:mt|kt|mmt|t|tonnes?|tons?|kg|lb|lbs|bu|bushels?|bags?)\b", re.I)),
    ("area", re.compile(r"\A(?:ha|hectares?|acres?)\b", re.I)),
)


def _unit_class(u) -> str | None:
    """The coarse category of a unit string, or None when this table does not name it."""
    s = str(u or "").strip().lstrip("/ ")
    for name, rx in _UNIT_CLASSES:
        if rx.match(s):
            return name
    return None


def _mint_candidates(call: dict, stated, unit: str) -> list:
    """The numerals THIS call's rows may be minted from: `stated.mint`, less the CLAIMED ones (rule (3):
    a numeral a handle already answers for has its row) and less the percent-marked ones, plus the percent
    LEVELS back when the call is itself percent-denominated -- exactly `_call_magnitudes`' fence
    (correction (B) + cycle-6 review MAJOR 5), asked per numeral instead of per magnitude.

    A `stated` that carries no `.mint` annotation (a plain list, every direct/legacy caller, every fixture
    that hand-builds one) yields NOTHING here: cycle-7's gate needs sign, precision, unit and claimed-ness,
    and a bare magnitude can supply none of them. The refusal direction is the safe one."""
    lvl = _percent_typed(call, unit)
    return [n for n in (getattr(stated, "mint", ()) or ())
            if not n.claimed and (not n.percent or (lvl and n.percent_level))]


def _mint_bucket(x: float) -> tuple[bool, float]:
    """CYCLE-7-AMEND (2026-08-08) -- the exact bucket's key, SIGN-CARRYING.

    `round(x, _EXTRA_DP)` alone is NOT sign-exact in the near-zero band: every |x| < 0.005 collapses to
    +-0.0, and `round(-0.0, 2) == round(0.0, 2)` is True, so a bucket hit short-circuited before any sign
    test could run and a prose "-0.0012 z" minted a "0.0041 z" row. The covenant serves exactly this band
    (`ab_mech_frost` drought_z = -0.00851709 z), so rule (2) was false on precisely the rows that need it.

    IDENTICAL OUTSIDE THE BAND: for any pair that does not round to zero, `round(x, 2) == round(y, 2)` iff
    the signs agree AND the magnitudes bucket together, so keying on (is_negative, magnitude) changes
    nothing a 2-dp key already decided. ZERO STAYS SIGN-NEUTRAL -- `-0.0 < 0` is False in Python, so a true
    zero and a negative zero share one key, which is the right reading (a zero has no direction) and is
    what `_hit`'s own `if not v` refusal already assumes.

    The magnitude collision WITHIN one sign in that band is not addressed here and is not new: 0.0012 and
    0.0041 still share a bucket, exactly as 2-dp equality has always meant they do."""
    return (x < 0, round(abs(x), _EXTRA_DP))


def _mint_matcher(nums: list, unit: str):
    """`row -> bool` for the completion lane: the row's value IS the thing one of `nums` names. Carries
    `.which(row) -> numeral | None`, the same decision returning WHICH numeral claimed the row (rule (7)
    below needs the claimant, not just the verdict).

    Same reader-precision window under the same relative ceiling as `_matcher`, read on SIGNED values, plus
    the integer and unit fences. The 2-dp bucket is an INDEX here, not an arm -- see CYCLE-8 below. Indexed
    for the same measured reason as `_matcher` -- the pass walks every served row of every established call
    and the estate serves 5000-row windows, so a per-row rescan of every numeral is a latency budget, not a
    predicate.

    CYCLE-8 (2026-08-08) RULE (7) -- THE 2-dp BUCKET NO LONGER BYPASSES THE PRECISION GATE.
    Cycle-7 wrote the two arms as `bucket-equal OR (window AND ceiling)`, so a bucket hit SHORT-CIRCUITED
    both the reader-precision window and the relative ceiling. Measured on gate-5 covenant
    `ab_enum_cotton_china`: the prose stated ONE value, `3.2651` (4 written decimals), and the footer minted
    FIVE letter-suffixed FX rows off it -- 3.2666 / 3.2733 / 3.2743 / 3.2675 / 3.2705, every one of them a
    DIFFERENT day's fix. All five round to 3.27 at 2 dp, so the bucket matched all five; the reader's own
    precision says a 4-dp figure claims identity only within +-0.00005, and the largest gap here is 0.0092
    -- 184x the window. The bucket is a coarse INDEX over a reader who wrote finely, and reading it as a
    verdict inverted the precision incentive the cycle-6 review already ruled on for this lane.
    The predicate is now the reader-precision WINDOW always: `gap <= half-unit-at-the-numeral's-decimals`.
    That is what the second clause already said for non-bucket hits, so nothing that passed it changes;
    what goes is the class that passed NEITHER and rode the bucket. `_mint_bucket` survives as the
    candidate index it always physically was (and keeps its sign-carrying key -- see its own note).

    CYCLE-8 REVIEW (2026-08-08) BLOCKER 1 -- THE RELATIVE CEILING IS SCOPED BACK TO d=0, WHERE IT BELONGS.
    Rule (7) as first written ALSO promoted the relative ceiling to an always-on clause, and that destroyed
    correctly-rounded sub-unit restatements. MEASURED: prose "a z-score of -0.20 [N12]" against the served
    `urea_usd_mt_zscore_5yr = -0.19515863509764528`. The reader wrote 2 dp, so the half-unit window is
    +-0.005 and the gap 0.004841 is INSIDE it -- this IS the row -- but 0.005 * |v| is 0.000976 and the
    ceiling refused it. Same shape on the gas z (-0.31 <- -0.3063197) and the potash z (-0.36 <- -0.3563389).
    For ANY |v| < 1 written to 2 dp the ceiling is strictly tighter than the reader's own precision, so
    correct rounding stops being sufficient -- and the z-score / small-percent band is this estate's
    dominant numeral shape. A matcher-level sweep of both gates: 54 identity matches kept, 14 LOST, 5 of the
    14 legitimate 2-dp z restatements.
    THE CEILING CONTRIBUTED NOTHING TO THE DEFECT IT WAS ADDED FOR. The WINDOW clause alone refuses 9/9 of
    the cotton FX spray AND the `dcw_macro_on_soy` BRL spray (gaps 0.0002-0.0092 against a 0.00005 window,
    4x-184x over). The ceiling refuses none of them the window does not already. It is pure collateral.
    So: the window is checked ALWAYS, and `_MINT_D0_REL_TOL` is checked ONLY at `decimals == 0` -- which is
    exactly what rule (5)'s own note says the ceiling is for (a 0-dp numeral has a flat +-0.5 window that
    bounds nothing, so the relative arm is the only thing bounding it there). The CONAB control
    `35,763 <- 35763.1` is a d=0 hit and keeps both clauses; `1 <- 1.0044` still refuses on the ceiling."""
    import bisect
    exact: dict[tuple[bool, float], list] = {}
    for n in nums:
        exact.setdefault(_mint_bucket(n.value), []).append(n)
    ms = sorted(nums, key=lambda n: n.value)
    keys = [n.value for n in ms]
    span = max((0.5 * 10.0 ** (-n.decimals) for n in ms), default=0.0)
    rcls = _unit_class(unit)

    def _which(r):
        try:
            v = float(str((r or {}).get("value")).replace(",", ""))
        except (TypeError, ValueError):
            return None
        if not v:
            return None                           # a 0.0 row: `_stated_values` floors magnitudes at 0.001,
                                                  # so nothing can name it, and `_zero_aggregate` already
                                                  # refuses the class whose point is to assert no figure
        rc = _unit_class((r or {}).get("unit")) or rcls
        cands = list(exact.get(_mint_bucket(v), ()))     # CYCLE-7-AMEND: sign-carrying key, see `_mint_bucket`
        cands += ms[bisect.bisect_left(keys, v - span):bisect.bisect_right(keys, v + span)]
        for n in cands:
            gap = abs(v - n.value)                # SIGNED, so a direction flip never reaches the window
            if gap > 0.5 * 10.0 ** (-n.decimals):
                continue                          # CYCLE-8 rule (7): the WINDOW always, bucket hit or not
            if n.decimals == 0 and gap > _MINT_D0_REL_TOL * abs(v):
                continue                          # rule (5): the ceiling bounds the UNBOUNDED d=0 window
            pc = _unit_class(n.unit)
            if pc and rc and pc != rc:
                continue                          # rule (6): a degC numeral does not name a z row
            return n
        return None

    def _hit(r) -> bool:
        return _which(r) is not None
    _hit.which = _which
    return _hit


def prose_completion_citations(number_calls: list | None, stated, *, seen: set,
                               cited: set) -> list[Citation]:
    """Every row the FINAL prose earns on an ESTABLISHED call that the footer does not already carry.

    `seen` is the whole footer's (value, period) horizon and is MUTATED. `cited` = the 1-based indices whose
    `[N{i}]` headline the reader still sees; CYCLE-7 makes that set the ENTRY FENCE (rule (1) above), so
    every minted row is a sibling of a row already on the page and an uncited call mints nothing.

    Never raises on one bad call: a malformed record is skipped, not fatal (a footer must never be the
    thing that breaks an answer)."""
    calls = number_calls or []
    if not stated or not calls:
        return []
    picked: list[tuple[int, dict]] = []
    hits: dict[int, object] = {}
    for i, call in enumerate(calls, 1):
        try:
            if i not in cited:
                continue                          # CYCLE-7 rule (1): the call must be established in context
            if not isinstance(call, dict) or not (call.get("rows") or []):
                continue
            if call.get("status") not in (None, "ok") or _zero_aggregate(call):
                continue                          # the classes whose whole point is to assert NO figure
            q = call.get("query") or {}
            unit = _metric_unit(q.get("table", ""), q.get("metric", ""), q.get("commodity"))
            nums = _mint_candidates(call, stated, unit)
            if not nums:
                continue
            rH = headline_row(call)
            seen.add(row_key(call, rH))           # the line already on the page is not a missing one
            hits[i] = _mint_matcher(nums, unit)
            picked += [(i, r) for r in _match_candidates(
                call, [], seen=seen, skip=rH, rowhit=hits[i])]
        except Exception:  # noqa: BLE001
            continue
    # GLOBAL newest-first ranking, then the whole-footer cap, then render grouped by call in index order
    # so the ids stay ascending and each call's suffixes stay contiguous (b, c, d ...).
    #
    # CYCLE-8 (2026-08-08) RULE (8) -- ONE ROW PER (STATED VALUE, CALL). A numeral names ONE fact. Gate-5's
    # covenant `ab_enum_cotton_china` minted FIVE rows from ONE stated 3.2651 (see `_mint_matcher`'s rule
    # (7) note) -- and even with rule (7) closing that particular spray on precision, the SHAPE is the
    # defect: a footer that answers one numeral with a fan of near-neighbours is asserting five identities
    # for one claim. The collapse runs on the RANKED list, so the row that survives is the NEWEST the
    # numeral names -- the same ranking correction (A) already established -- and it runs BEFORE the
    # whole-footer cap, so a spray can no longer crowd out other calls' legitimate rows.
    # THE FARM-PRICE VINTAGE SHAPE IS UNTOUCHED BY CONSTRUCTION: `dcw_farm_price_vintage` mints
    # 4.55 / 4.24 / 4.15 off THREE DIFFERENT stated values, which are three different keys.
    keep: list[tuple[int, dict]] = []
    claimed: set[tuple[int, float]] = set()
    for i, r in sorted(picked, key=lambda t: _row_order_key(t[1]), reverse=True):
        if len(keep) >= _MAX_COMPLETION_ROWS:
            break
        h = hits.get(i)                           # `.get`, not `[]`: this loop sits outside the per-call
        n = h.which(r) if h is not None else None  # try/except and a footer must never break an answer
        if n is None or (i, n.value) in claimed:  # `which` re-asks the SAME predicate `rowhit` just ran
            continue
        claimed.add((i, n.value))
        keep.append((i, r))
    out: list[Citation] = []
    for i, call in enumerate(calls, 1):
        rows = [r for j, r in keep if j == i]
        if rows:
            try:
                out += _mint_row_citations(call, i, rows)
            except Exception:  # noqa: BLE001
                continue
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
    # carry char_start/char_end/offset_kind ('exact'|'exact_ws'|'block'|'none') -- copied through so 6.5
    # click-to-page can resolve the source PDF page DETERMINISTICALLY (offsets-first) instead of
    # fuzzy-matching the snippet. 'exact_ws' is an exact span recovered through the text layer's line breaks
    # (evidence_batch._locate_span): it addresses full_text identically to 'exact' and every consumer that
    # only distinguishes "has an offset" from 'none' needs no change.
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
