"""Numbers SQL agent — the LLM that turns a question into typed NumberQuery lookups (Phase 3).

The model NEVER writes SQL and NEVER chooses the as-of date. It's given the registry (a cached system prompt)
and one tool, ``lookup_number``, whose schema mirrors NumberQuery MINUS asof. The agent fills table/metric/
scope; the loop injects the caller's fixed ``asof`` and runs it through the deterministic leakage-safe builder.
So point-in-time correctness is a property of the harness, not of prompt discipline — the agent literally has no
lever to see the future. Returns the model's answer plus the exact (query, rows) provenance behind every number.
"""
from __future__ import annotations

import json
from typing import Optional

from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import NumbersRegistry, TableSpec, load_registry

HAIKU = "claude-haiku-4-5"                                 # cheap + mechanical; the agent just selects table/metric/scope
TOOL_NAME = "lookup_number"


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
                "period": {"type": "string", "description": "marketing year or year (per the table's period format)"},
                "period_start": {"type": "string", "description": "YYYY-MM-DD window start (date-grained tables)"},
                "period_end": {"type": "string", "description": "YYYY-MM-DD window end (date-grained tables)"},
                "agg": {"type": "string", "enum": ["latest", "series", "sum", "mean", "max", "min"],
                        "default": "latest"},
            },
            "required": ["table", "metric"],
        },
    }


def _table_card(ts: TableSpec) -> str:
    ident = ", ".join(x for x in (
        f"commodity={ts.commodity_col}" if ts.commodity_col else "",
        f"country={ts.country_col}" if ts.country_col else "",
        f"period={ts.period_col}({ts.period_type})" if ts.period_col else "",
        "date-windowed" if ts.date_col and not ts.period_col else "") if x)
    metrics = ", ".join(f"{k} [{v.unit}]" if v.unit else k for k, v in ts.metrics.items())
    return (f"### {ts.id} ({ts.knowledge_semantics})\n{ts.description.strip()}\n"
            f"identify by: {ident or 'n/a'}\nmetrics: {metrics}\n{('note: ' + ts.notes.strip()) if ts.notes else ''}")


def system_prompt(reg: NumbersRegistry) -> str:
    cards = "\n\n".join(_table_card(reg.get(t)) for t in sorted(reg.tables))
    return (
        "You are a data-lookup agent for an agricultural-commodity desk. Answer ONLY with numbers you actually "
        "retrieve via the lookup_number tool from the tables below — never invent or recall a figure. Every value "
        "is returned as-known at a fixed as-of date you cannot change (point-in-time correct). Call the tool as "
        "many times as needed (different tables/metrics/scopes), then give a short factual answer that states each "
        "number with its unit and its knowledge_date (when it was published). A tool_result has a `status`: "
        "`ok` (use the value), `not_known` (empty AND the value was genuinely not yet published at the as-of date "
        "— say so plainly), or `error` (the lookup FAILED for a data-access reason — say the figure is UNAVAILABLE "
        "due to a lookup error; do NOT claim it was 'not known at the as-of date'). Do not reason beyond the numbers.\n\n"
        "## Conventions\n"
        "- `commodity` is the exact CONTRACT SLUG, e.g. corn_cbot, soybeans_cbot, soybean_oil_cbot, "
        "hard_red_winter_wheat_kcbt, hard_red_spring_wheat_mgex, soft_red_winter_wheat_cbot, french_wheat_matif, "
        "malaysian_crude_palm_oil_cme, arabica_coffee, cotton, raw_sugar, cocoa — use the suffixed form, not 'corn'.\n"
        "- A marketing year is its START year as an INTEGER: the 2023/24 marketing year is 2023 (not 2024). "
        "For silver_wasde, period is the string '2023/24'.\n"
        "- silver_noaa_oni has NO date column: window months with period_start/period_end as 'YYYY-MM', or use "
        "agg=latest for the most recent month on/before the as-of date.\n"
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
                   query_fn=None, max_calls: int = 6, max_tokens: int = 1500) -> dict:
    """Run the agent loop. `client` = an anthropic.Anthropic (real = billed); `query_fn(sql)->rows` overrides Athena
    (tests). Returns {answer, calls:[{query, rows}]} — calls carry the exact provenance behind every number."""
    reg = reg or load_registry()
    if client is None:
        import anthropic
        from leviathan.graphrag import batch_extract as bx
        client = anthropic.Anthropic(api_key=bx._api_key())
    tools = [tool_schema(reg)]
    system = [{"type": "text", "text": system_prompt(reg), "cache_control": {"type": "ephemeral"}}]  # cached
    convo: list[dict] = [{"role": "user", "content": f"As-of date (fixed): {asof}\n\nQuestion: {question}"}]
    calls: list[dict] = []

    for _ in range(max_calls):
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=convo)
        uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not uses:
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
            return {"answer": text.strip(), "calls": calls}
        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in uses:
            try:
                spec = _forced_spec(asof, dict(b.input))
                rows = Q.run(spec, query_fn=query_fn)
                # DISTINGUISH: empty-with-no-error = genuinely not known at asof (point-in-time); an EXCEPTION is a
                # lookup FAILURE (data-access), which must NEVER be reported as "not known at asof".
                payload = {"query": spec.model_dump(exclude_none=True), "rows": rows,
                           "status": "ok" if rows else "not_known"}
            except Exception as e:  # noqa: BLE001 — a bad lookup must not kill the loop
                payload = {"query": dict(b.input), "error": str(e)[:200], "rows": [], "status": "error"}
            calls.append(payload)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(payload)[:6000]})
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
               "(lookup error)" if c.get("status") == "error" else "(not known at asof)")
        kd = rows[0].get("knowledge_date") or rows[0].get("data_date") if rows else ""
        scope = "/".join(str(q.get(k)) for k in ("commodity", "country", "period") if q.get(k))
        out.append(f"{q.get('table')}.{q.get('metric')} {scope} = {val}" + (f" [{kd}]" if kd else ""))
    return out
