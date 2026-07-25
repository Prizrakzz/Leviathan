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


def _metric_unit(table: str, metric: str) -> str:
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        m = load_registry().get(table).metrics.get(metric)
        return m.unit if m else ""
    except Exception:  # noqa: BLE001 — registry missing/table unknown -> no unit, never fatal
        return ""


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
    unit = rH.get("unit") or _metric_unit(table, metric)
    kd = rH.get("knowledge_date") or rH.get("data_date")
    # period label: agent calls carry a BARE MY year ("2011" -> render "MY2011"); cascade calls arrive
    # PRE-labeled ("MY2011" / "2010-06-01..2010-09-01") — re-prefixing those minted "MYMY2011" in the
    # Sources footer and fed the judge malformed provenance (P9-AB P0-6).
    per = str(q["period"]) if q.get("period") is not None else None
    if per and not (per.startswith("MY") or ".." in per):
        per = f"MY{per}"
    scope = " ".join(x for x in (q.get("commodity"), q.get("country"), per) if x)
    if rows:
        label = f"{src} {metric} {scope} = {_fmt(value)} {unit}".strip()
        # staleness affordance (RCA (c)): when the freshest knowable date trails the asof by more than
        # ~30 days, give the synthesizer a clean 'latest available X; as-of Y' to STATE instead of
        # conflating the two dates and reading as fabrication. Terse by design — one clause, no prose.
        _hd, _ad = _parse_date(kd), _parse_date(asof)
        if _hd and _ad and (_ad - _hd).days > 30:
            label += f" (latest available {str(kd)[:10]}; as-of {asof})"
    else:
        label = f"{src} {metric} {scope} = {_empty_label(status, asof)}".strip()
    locator = {"kind": "number", **{k: q.get(k) for k in ("table", "metric", "commodity", "country", "period", "asof")}}
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
