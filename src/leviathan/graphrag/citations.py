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
    was declared unanswerable (judged-30 RCA (a)). Status ABSENT -> the legacy text, unchanged."""
    a = str(asof) if asof else "asof"
    if status in ("not_known", "future_unpublished"):
        return f"(not yet published as of {a})"
    if status in ("no_rows", "record_silent"):
        return "(no matching rows -- scope/coverage gap, not a timing claim)"
    if status == "error":
        return "(lookup error)"
    if status == "declined":
        # a lookup the harness STRUCTURALLY declined, not one that failed or came back empty: the SEAM-C
        # hybrid futures decline (task #144) neuters a curve/named front-month read so no level can be cited
        # as the asked-for quote. The scope note riding the same call carries the WHY to the writer.
        return "(declined -- not servable from this series for this ask)"
    return "(not known at asof)"


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
    kd = rH.get("knowledge_date") or rH.get("data_date")
    # period label: agent calls carry a BARE MY year ("2011" -> render "MY2011"); cascade calls arrive
    # PRE-labeled ("MY2011" / "2010-06-01..2010-09-01") — re-prefixing those minted "MYMY2011" in the
    # Sources footer and fed the judge malformed provenance (P9-AB P0-6).
    per = str(q["period"]) if q.get("period") is not None else None
    if per and not (per.startswith("MY") or ".." in per):
        per = f"MY{per}"
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
    if rows:
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
    locator = {"kind": "number", **{k: q.get(k) for k in ("table", "metric", "commodity", "country", "period", "asof")}}
    if cmonth:
        locator["contract_month"] = cmonth      # the drill-down must re-run the expiry that was quoted
    return Citation(id=f"N{i}", kind="number", label=label, source=src, date=kd,
                    value=(str(value) if value is not None else None), unit=(unit or None),
                    locator=locator, payload={"query": q, "rows": rows[:3]})


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


def unify(evidence_rows: Optional[list[dict]] = None, number_calls: Optional[list[dict]] = None) -> list[Citation]:
    """One numbered citation list spanning document evidence (E1..) and numbers (N1..) for a hybrid answer."""
    cits = [from_evidence(r, i) for i, r in enumerate(evidence_rows or [], 1)]
    cits += [from_number(c, i) for i, c in enumerate(number_calls or [], 1)]
    return cits


def render(cits: list[Citation]) -> str:
    """A citations block for the answer footer (source + knowledge date make the point-in-time provenance visible)."""
    lines = []
    for c in cits:
        tail = f"  [known {c.date}]" if (c.date and c.kind == "number") else (f"  [{c.date}]" if c.date else "")
        lines.append(f"[{c.id}] {c.label}{tail}")
    return "\n".join(lines)
