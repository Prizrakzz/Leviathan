"""Stage B — probe the cheap Bedrock extraction candidates (DeepSeek / Qwen / Kimi).

Read-only-ish (tiny invokes ≈ cents). Answers the three questions that gate the model bake-off:
  B1  ACCESS    — can this account actually Converse with the model? (listing != entitlement)
  B2  TOOL MODE — does it support FORCED tool use, only AUTO tools, or neither (→ JSON-mode fallback)?
  B3  PRICE     — per-1M input/output token price (AWS Price List API, best-effort).
Writes configs/graphrag/pilot/bedrock_probe.md and prints a shortlist of the 2 best cost-quality picks.

    python scripts/probe_bedrock_extract.py
"""
from __future__ import annotations

import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

_OUT = Path(__file__).resolve().parents[1] / "configs" / "graphrag" / "pilot"

# (modelId, region) — our data is us-east-1; qwen3-235b is us-west-2 only (the bigger Qwen, optional).
CANDIDATES = [
    ("deepseek.v3.2", "us-east-1", "non-reasoning, fast"),
    ("qwen.qwen3-32b-v1:0", "us-east-1", "small, multilingual"),
    ("moonshotai.kimi-k2.5", "us-east-1", "strong agentic/tool use"),
    ("qwen.qwen3-235b-a22b-2507-v1:0", "us-west-2", "bigger Qwen (cross-region)"),
]

# per-1M (input, output) USD fallback from aws.amazon.com/bedrock/pricing (fetched 2026-06; region-listed).
# Used when the Price List API returns nothing (brittle for new models). Sonnet 4.6 baseline = (3.00, 15.00).
_PRICE_FALLBACK = {
    "deepseek.v3.2": (0.62, 1.85),
    "qwen.qwen3-32b": (0.1545, 0.618),       # listed AP-Sydney; us-east-1 comparable
    "qwen.qwen3-235b": (0.2266, 0.9064),
    "moonshotai.kimi-k2.5": (0.60, 3.00),
}

# a minimal emit_extraction-shaped tool, to test structured/forced output
_TOOL = {"toolSpec": {"name": "emit", "description": "Emit a tiny structured extraction.",
                      "inputSchema": {"json": {"type": "object",
                                               "properties": {"entity": {"type": "string"},
                                                              "metric": {"type": "string"}},
                                               "required": ["entity"]}}}}


def _converse(rt, mid, **kw):
    return rt.converse(modelId=mid, inferenceConfig={"maxTokens": 64, "temperature": 0}, **kw)


def b1_access(rt, mid) -> tuple[str, str]:
    """Return (status, note). status in {ok, denied, error}."""
    try:
        r = _converse(rt, mid, messages=[{"role": "user", "content": [{"text": "Reply with one word: OK."}]}])
        txt = "".join(b.get("text", "") for b in r["output"]["message"]["content"])[:40]
        return "ok", txt.strip().replace("\n", " ")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        return ("denied" if "AccessDenied" in code else "error"), code or str(e)[:60]
    except Exception as e:  # noqa: BLE001
        return "error", f"{type(e).__name__}: {str(e)[:50]}"


def b2_tool_mode(rt, mid) -> str:
    """forced | auto | json — the strongest structured mode the model accepts via Converse."""
    msg = [{"role": "user", "content": [{"text": "Call emit with entity='soybeans', metric='yield'."}]}]
    for label, choice in (("forced", {"tool": {"name": "emit"}}), ("auto", {"auto": {}})):
        try:
            r = _converse(rt, mid, messages=msg, toolConfig={"tools": [_TOOL], "toolChoice": choice})
            if any("toolUse" in b for b in r["output"]["message"]["content"]):
                return label
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if "AccessDenied" in code:
                return "n/a (no access)"
            continue
        except Exception:  # noqa: BLE001
            continue
    return "json (no tool support)"


def b3_price(region: str) -> dict[str, tuple[float, float]]:
    """Best-effort per-1M (input, output) USD from the AWS Price List API. Returns {modelId_substr: (in,out)}.
    The Price List API is brittle for new models — anything missing is filled from the pricing page by hand."""
    out: dict[str, tuple[float, float]] = {}
    try:
        p = boto3.client("pricing", region_name="us-east-1")  # Price List endpoint lives in us-east-1
        paginator = p.get_paginator("get_products")
        kw = dict(ServiceCode="AmazonBedrock",
                  Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}])
        by_model: dict[str, dict[str, float]] = {}
        for page in paginator.paginate(**kw):
            for s in page.get("PriceList", []):
                d = json.loads(s)
                attr = d.get("product", {}).get("attributes", {})
                model = (attr.get("model") or attr.get("titanModel") or "").lower()
                usaget = (attr.get("usagetype") or "").lower()
                if not any(k in model for k in ("deepseek", "qwen", "kimi", "moonshot")):
                    continue
                # pull the unit price
                for term in d.get("terms", {}).get("OnDemand", {}).values():
                    for dim in term.get("priceDimensions", {}).values():
                        usd = float(dim.get("pricePerUnit", {}).get("USD", 0) or 0)
                        if usd <= 0:
                            continue
                        slot = by_model.setdefault(model, {})
                        if "input" in usaget or "input" in dim.get("description", "").lower():
                            slot["in"] = usd * 1_000_000
                        elif "output" in usaget or "output" in dim.get("description", "").lower():
                            slot["out"] = usd * 1_000_000
        for model, v in by_model.items():
            if "in" in v or "out" in v:
                out[model] = (v.get("in", 0.0), v.get("out", 0.0))
    except Exception as e:  # noqa: BLE001
        print(f"  [b3] price lookup unavailable ({type(e).__name__}); fill from pricing page.")
    return out


def main() -> int:
    rows = []
    price_cache: dict[str, dict] = {}
    for mid, region, note in CANDIDATES:
        print(f"== {mid} ({region}) ==", flush=True)
        rt = boto3.client("bedrock-runtime", region_name=region)
        access, amsg = b1_access(rt, mid)
        tool = b2_tool_mode(rt, mid) if access == "ok" else "—"
        if region not in price_cache:
            price_cache[region] = b3_price(region)
        price = next((v for k, v in price_cache[region].items() if k.split(".")[0] in mid or k in mid), None)
        if price is None:  # Price List API empty → fall back to the dated pricing-page table
            price = next((v for k, v in _PRICE_FALLBACK.items() if k in mid), None)
        ptxt = f"${price[0]:.2f}/${price[1]:.2f}" if price else "TBD (pricing page)"
        print(f"   access={access} ({amsg}) | tool={tool} | price={ptxt}", flush=True)
        rows.append((mid, region, note, access, tool, ptxt, amsg))

    _OUT.mkdir(parents=True, exist_ok=True)
    L = ["# Bedrock extraction-model probe (Stage B)",
         "\nSonnet 4.6 baseline = $3.00/$15.00 per 1M in/out. Goal: a model ~3–10x cheaper that still does"
         " clean structured extraction (forced tool or JSON-mode).\n",
         "| model | region | access | tool-mode | $in/$out per 1M | note |",
         "|---|---|---|---|---|---|"]
    for mid, region, note, access, tool, ptxt, _ in rows:
        mark = {"ok": "✅", "denied": "⛔", "error": "⚠️"}.get(access, access)
        L.append(f"| `{mid}` | {region} | {mark} | {tool} | {ptxt} | {note} |")
    usable = [r for r in rows if r[3] == "ok"]
    L += [f"\n**Usable (access ✅): {len(usable)}/{len(rows)}.** Next: shortlist the 2 best cost-quality and"
          " run the Stage-C bake-off (each finalist vs Sonnet on the cleaned pipeline, sync+multithreaded,"
          " scoring cascade/chain quality + schema-adherence + $/doc).",
          "Errors/denied → request model access in the Bedrock console (Model access) and re-probe."]
    (_OUT / "bedrock_probe.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nwrote {_OUT / 'bedrock_probe.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
