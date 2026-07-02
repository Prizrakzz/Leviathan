"""Unified provenance citations — one schema spanning DOCUMENT evidence (chunks) and NUMBERS (silver lookups).

A Citation carries a human `label`, a `source`, a knowledge `date`, and a machine `locator` (the click-target the
UI resolves): for a number, the exact leakage-safe query to re-run as a drill-down; for a document, a pointer to
the source doc. The document locator already carries `page`/`char_start`/`snippet` SLOTS — null today, auto-filled
when the page-citation recovery lands — so numbers and page-level document citations render through one path.
"""
from __future__ import annotations

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
    return table.replace("silver_", "").replace("_", " ").upper()      # silver_noaa_oni -> NOAA ONI


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


def from_number(call: dict, i: int) -> Citation:
    """Build a Citation from a numbers-agent call record ({query, rows})."""
    q = call.get("query", {})
    rows = call.get("rows") or []
    r0 = rows[0] if rows else {}
    table, metric = q.get("table", ""), q.get("metric", "")
    src = _source_label(table)
    value = r0.get("value")
    unit = r0.get("unit") or _metric_unit(table, metric)
    kd = r0.get("knowledge_date") or r0.get("data_date")
    scope = " ".join(x for x in (q.get("commodity"), q.get("country"),
                                 (f"MY{q['period']}" if q.get("period") else None)) if x)
    if rows:
        label = f"{src} {metric} {scope} = {_fmt(value)} {unit}".strip()
    else:
        label = f"{src} {metric} {scope} = (not known at asof)".strip()
    locator = {"kind": "number", **{k: q.get(k) for k in ("table", "metric", "commodity", "country", "period", "asof")}}
    return Citation(id=f"N{i}", kind="number", label=label, source=src, date=kd,
                    value=(str(value) if value is not None else None), unit=(unit or None),
                    locator=locator, payload={"query": q, "rows": rows[:3]})


def from_evidence(row: dict, i: int) -> Citation:
    """Build a Citation from a retrieve() evidence row. page/char/snippet are forward-compatible slots (null until
    the page-citation recovery populates them) so document citations become click-to-page with no schema change."""
    src, sk, date = row.get("source", ""), row.get("source_key", ""), row.get("date")
    text = row.get("text") or ""
    snippet = text[:140] + ("..." if len(text) > 140 else "")
    label = f"{src} ({date}): {snippet}"
    locator = {"kind": "doc", "source_key": sk, "page": row.get("page"),
               "char_start": row.get("char_start"), "snippet": row.get("snippet")}
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
