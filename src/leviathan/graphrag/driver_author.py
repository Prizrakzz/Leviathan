"""Opus-authored expansion of the driver-slice map (GraphRAG v2 WS-MS6+). PUBLIC code; the YAML it feeds is IP.

The driver slices (configs/graphrag/driver_slices.yaml) are the cross-cutting nodes — weather, policy, FX,
freight, energy, fertilizer, livestock/feed-demand, positioning, logistics, demand centers — that move our 24
traded ag contracts via cascades/convergence but are NOT contracts themselves. This asks Opus, as a buy-side
commodity strategist, to propose the NET-NEW driver/context nodes a desk watches that we haven't curated yet
(e.g. the livestock complex, ASF/avian-flu demand shocks, ethanol/RFS, CFTC positioning, river-level logistics,
non-contract substitutes). It returns structured proposals; a human curates + merges them into the YAML.

    python -m leviathan.graphrag.driver_author --propose          # gated: one Opus call (~$1-2)
    python -m leviathan.graphrag.driver_author --propose --merge  # also append curated proposals to the YAML
"""
from __future__ import annotations

import argparse

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

_SYSTEM = (
    "You are a senior commodities strategist at a macro hedge fund, advising portfolio managers and quant "
    "researchers who risk capital across the agricultural complex (grains, oilseeds, softs, and the livestock-"
    "feed chain). Your task: enumerate the cross-cutting DRIVER and CONTEXT nodes — NOT the traded contracts "
    "themselves — that a desk monitors and that a knowledge graph must ground with dated evidence, because they "
    "sit UPSTREAM of cascades and convergence in ag prices. Be exhaustive and specific, like the specialist you "
    "are. Cover, where not already listed: weather/climate regimes; biofuel + trade/export policy; FX, ocean "
    "freight, and rates; energy + fertilizer inputs; the LIVESTOCK & FEED-DEMAND complex (live cattle, feeder "
    "cattle, lean hogs, cattle-on-feed, poultry, and demand shocks like African Swine Fever and avian influenza "
    "— the demand side of corn/soymeal/wheat); ethanol/RFS/RINs and SAF; SPECULATIVE POSITIONING (CFTC "
    "Commitments of Traders / managed money — what PMs actually watch); DEMAND CENTERS (China state reserves / "
    "COFCO / auctions, India); LOGISTICS CHOKEPOINTS (Mississippi & Parana river levels, Black Sea corridor, "
    "Panama/Suez); geopolitics/sanctions; and SUBSTITUTION / non-contract commodities (feed-grain and veg-oil "
    "substitution, sunflower oil, barley, sorghum, natural rubber, etc.). For EACH proposal give: a canonical "
    "snake_case name; the PRECISE surface terms a text matcher should fire on (specific, not over-broad — e.g. "
    "'african swine fever'/'asf', not 'disease'; 'managed money'/'commitments of traders', not 'positioning'); "
    "a category; whether it is a first-class 'driver' or low-priority 'context'; a one-line mechanism; and which "
    "of the listed contracts it moves. Prioritize what genuinely moves price for a PM — the second-order links a "
    "generalist would miss. Do NOT propose any of the listed traded contracts, and do NOT repeat drivers already "
    "present. Return ONLY via the propose_drivers tool."
)


def _tool() -> dict:
    s = {"type": "string"}
    return {"name": "propose_drivers",
            "description": "Net-new cross-cutting driver/context nodes for the evidence-routing map.",
            "input_schema": {"type": "object", "properties": {"drivers": {"type": "array", "items": {
                "type": "object", "properties": {
                    "name": s, "category": s,
                    "terms": {"type": "array", "items": s},
                    "priority": {"type": "string", "enum": ["driver", "context"]},
                    "mechanism": s,
                    "moves": {"type": "array", "items": s}},
                "required": ["name", "category", "terms", "priority", "mechanism"]}}},
                "required": ["drivers"]}}


def _user() -> str:
    existing = sorted(ev.driver_specs().keys())
    commodities = ev.all_nodes()
    return ("TRADED CONTRACTS (do NOT propose these; these are the things the drivers MOVE):\n  "
            + ", ".join(commodities)
            + "\n\nDRIVER/CONTEXT NODES ALREADY CURATED (do NOT repeat these):\n  " + ", ".join(existing)
            + "\n\nPropose the NET-NEW driver/context nodes a hedge-fund ag desk watches that are missing above. "
              "Aim for breadth across all the areas in your brief (especially the livestock/feed-demand complex, "
              "positioning, demand centers, logistics, and non-contract substitutes), with precise match terms.")


def propose(client, *, model: str = ex.MODEL) -> list[dict]:
    out, _usage = ex.call_opus(client, _SYSTEM, _user(), model=model, max_tokens=8000, tool=_tool())
    return out.get("drivers", []) if isinstance(out, dict) else []


def to_yaml_fragment(proposals: list[dict]) -> str:
    """Render proposals in the driver_slices.yaml `drivers:` schema (name: {category, [priority], terms})."""
    import yaml
    lines = ["# --- Opus-proposed driver/context nodes (WS-MS6+); REVIEW before merging into driver_slices.yaml ---"]
    for d in proposals:
        spec = {"category": d.get("category", "macro_context"), "terms": [str(t) for t in (d.get("terms") or [])]}
        if d.get("priority") == "context":
            spec["priority"] = "context"
        lines.append(f"  {d['name']}: " + yaml.safe_dump(spec, default_flow_style=True, sort_keys=False).strip()
                     + f"   # {d.get('mechanism','')}  [moves: {', '.join(d.get('moves') or [])}]")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Opus-propose net-new driver/context nodes (gated: one Opus call).")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--merge", action="store_true", help="append the proposed fragment to driver_slices.yaml")
    args = ap.parse_args()
    if not args.propose:
        print("specify --propose (gated: ~$1-2 Opus)")
        return 0
    import anthropic
    from leviathan.common import config
    from leviathan.graphrag import batch_extract as bx
    config.load_env()
    client = anthropic.Anthropic(api_key=bx._api_key())
    proposals = propose(client)
    frag = to_yaml_fragment(proposals)
    print(f"OPUS proposed {len(proposals)} net-new driver/context nodes:\n")
    print(frag)
    out_path = ex._CFG / "driver_slices_proposed.yaml"
    out_path.write_text(frag + "\n", encoding="utf-8")
    print(f"\nwritten to {out_path} for review")
    if args.merge:
        with open(ev._DRIVER_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + frag + "\n")
        print(f"appended to {ev._DRIVER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
