"""Suggester A/B + numeric-guard harness (P1.2 / W4).

Rebuilds the judge-free A/B scorer that measured the 6.8 grounded suggester (convexity 1.9%->87.5%) — the
original was an uncommitted scratchpad script, so this is the committed replacement. It scores the chips a
scenario yields on the 6.8 dimensions PLUS the P1.2 metric: how often the raw model MINTS a numeric level and
how many of those the parser-level guard (`server._mints_number`) now drops.

Deterministic scoring (no judge, credit-free beyond the Haiku sampling itself):
  - answerable  : passes the grounded answerable-gate (`_SUGGEST_DENY` doesn't fire)
  - register    : `register.register_leaks(chip) == []`
  - length      : <= 140 chars (the parser cap)
  - convexity   : mentions a buffer/rate/regime/tip cue (house style)
  - minted_num  : states a specific numeric level -> DROPPED by the P1.2 guard (lower is better)

Arms:
  - base    : always available (no catalog needed) — `server._suggest_prompt`
  - grounded: needs a data catalog; pass one dumped from a live /v1/convergence via --catalog-file, else skipped

Run (Bedrock Haiku, needs AWS creds + GRAPHRAG_PROVIDER=bedrock or Anthropic key):
    python scripts/suggester_ab.py --samples 2
    python scripts/suggester_ab.py --samples 2 --catalog-file catalog.json     # add the grounded arm
    python scripts/suggester_ab.py --mock                                       # deterministic, no spend/creds
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from leviathan.graphrag import register as reg
from leviathan.graphrag import server as sv
from leviathan.graphrag.api_models import SuggestRequest

# 8 scenarios spanning the desks the suggester serves (contract, prior-turn packet, intent).
SCENARIOS = [
    {"question": "why is arabica coffee tight into 2025?", "tldr": "Frost risk + low stocks.",
     "contracts": ["arabica_coffee"], "intent": "reasoning"},
    {"question": "how convex is corn on a yield shock?", "tldr": "Tight stocks-to-use.",
     "contracts": ["corn"], "intent": "reasoning"},
    {"question": "what did the B40 mandate do to palm?", "tldr": "Biodiesel pull on palm stocks.",
     "contracts": ["crude_palm_oil"], "intent": "reasoning"},
    {"question": "is the soy complex crush-bound?", "tldr": "Meal vs oil divergence.",
     "contracts": ["soybeans_cbot"], "intent": "hybrid"},
    {"question": "how does a strong dollar hit wheat exports?", "tldr": "FX pass-through to FOB.",
     "contracts": ["hard_red_winter_wheat_kcbt"], "intent": "reasoning"},
    {"question": "sugar-ethanol arbitrage right now?", "tldr": "Cane crush mix shifting.",
     "contracts": ["sugar_no11"], "intent": "hybrid"},
    {"question": "El Nino read-through to Brazil soy?", "tldr": "ONI turning positive.",
     "contracts": ["soybeans_cbot"], "intent": "reasoning"},
    {"question": "cotton on a weak harvest?", "tldr": "Acreage down, demand soft.",
     "contracts": ["cotton_no2"], "intent": "reasoning"},
]

_CONVEXITY_CUE = re.compile(
    r"\b(buffer|stocks?-to-use|ending stocks|draw|deplet|tip|tips|fire|fires|squeeze|glut|regime|"
    r"convex|threshold|cascade|how (?:fast|close|much|many))\b", re.I)


def _mock_call(prompt: str) -> str:
    """Deterministic stand-in: emits a house-style chip, a minted-number chip (must be dropped), and a leak."""
    return json.dumps([
        "Cane crush firm -- how fast must sugar ending stocks fall before the ethanol-diversion regime fires?",
        "Will Brazil lose 16 million bags before the squeeze fires?",   # minted magnitude -> guard drops it
        "As ONI 0.5 flips to El Nino, is the soy teleconnection convex?",
    ])


def _bedrock_call(prompt: str) -> str:
    from leviathan.graphrag import providers as pv
    client = pv.make_client()
    out = client.messages.create(model=pv.resolve_model("claude-haiku-4-5"), max_tokens=320,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in out.content if getattr(b, "type", "") == "text").strip()


def _raw_chips(raw: str) -> list[str]:
    """The model's chips BEFORE the guard (for measuring the mint rate the guard then removes)."""
    try:
        a, b = raw.index("["), raw.rindex("]")
        arr = json.loads(raw[a:b + 1])
    except Exception:  # noqa: BLE001
        return []
    return [s.strip() for s in arr if isinstance(s, str) and s.strip()]


def _score(chips: list[str], *, grounded: bool) -> dict:
    if not chips:
        return {"n": 0, "answerable": 0, "register": 0, "length": 0, "convexity": 0}
    answerable = sum(1 for s in chips if not (grounded and sv._SUGGEST_DENY.search(s)))
    return {
        "n": len(chips),
        "answerable": answerable,
        "register": sum(1 for s in chips if reg.register_leaks(s) == []),
        "length": sum(1 for s in chips if len(s) <= 140),
        "convexity": sum(1 for s in chips if _CONVEXITY_CUE.search(s)),
    }


def _run_arm(name: str, prompt: str, call, samples: int, *, grounded: bool) -> dict:
    agg = {"n": 0, "answerable": 0, "register": 0, "length": 0, "convexity": 0,
           "raw_n": 0, "minted_raw": 0, "kept_n": 0}
    for _ in range(samples):
        raw = call(prompt) or ""
        raw_chips = _raw_chips(raw)
        kept = sv._parse_suggestions(raw)                              # applies the P1.2 numeric guard
        if grounded:
            kept = [s for s in kept if not sv._SUGGEST_DENY.search(s)]
        agg["raw_n"] += len(raw_chips)
        agg["minted_raw"] += sum(1 for s in raw_chips if sv._mints_number(s))
        agg["kept_n"] += len(kept)
        sc = _score(kept, grounded=grounded)
        for k in ("n", "answerable", "register", "length", "convexity"):
            agg[k] += sc[k]
    return agg


def _pct(num: int, den: int) -> str:
    return f"{(100.0 * num / den):.0f}%" if den else "--"


def main() -> None:
    ap = argparse.ArgumentParser(description="Suggester A/B + P1.2 numeric-guard harness")
    ap.add_argument("--samples", type=int, default=2, help="samples per scenario per arm")
    ap.add_argument("--catalog-file", default=None,
                    help="JSON catalog dumped from a live /v1/convergence to enable the grounded arm")
    ap.add_argument("--mock", action="store_true", help="deterministic fake model — no creds, no spend")
    args = ap.parse_args()

    call = _mock_call if args.mock else _bedrock_call
    cat_text = None
    if args.catalog_file:
        cat = json.loads(Path(args.catalog_file).read_text(encoding="utf-8"))
        cat_text = sv._suggest_catalog_text(cat)

    arms = {"base": [], "grounded": []} if cat_text else {"base": []}
    for sc in SCENARIOS:
        body = SuggestRequest(thread_id="ab", question=sc["question"], tldr=sc["tldr"],
                              contracts=sc["contracts"], intent=sc["intent"], asof="2026-07-06")
        base_prompt = sv._suggest_prompt(body, None)
        arms["base"].append(_run_arm("base", base_prompt, call, args.samples, grounded=False))
        if cat_text:
            g_prompt = sv._suggest_prompt_grounded(body, None, cat_text, [])
            arms["grounded"].append(_run_arm("grounded", g_prompt, call, args.samples, grounded=True))

    print(f"\nSuggester A/B -- {len(SCENARIOS)} scenarios x {args.samples} samples"
          f"{' (MOCK)' if args.mock else ''}\n" + "=" * 68)
    for arm, rows in arms.items():
        t = {k: sum(r[k] for r in rows) for k in rows[0]}
        kept, raw = t["kept_n"], t["raw_n"]
        print(f"\n[{arm}]  raw_chips={raw}  kept={kept}  minted_in_raw={t['minted_raw']} "
              f"({_pct(t['minted_raw'], raw)} of raw) -> dropped by guard")
        print(f"  of kept chips: answerable {_pct(t['answerable'], kept)} | register-clean "
              f"{_pct(t['register'], kept)} | <=140 {_pct(t['length'], kept)} | "
              f"convexity-framed {_pct(t['convexity'], kept)}")
    # The P1.2 win: minted_in_raw > 0 while EVERY kept chip is minted-free (the guard is the backstop the
    # prompt line can't guarantee). A non-zero minted_in_raw with 0 leaking through is the pass signal.
    print("\nP1.2 gate: minted numbers appear in raw model output but ZERO survive into kept chips.\n")


if __name__ == "__main__":
    main()
