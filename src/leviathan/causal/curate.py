"""Semi-automated curation pass over the curated causal YAMLs (GRAPHRAG_PLAN Phase 1, post-scaling).

The audit (audit.py) lists the curation load; this APPLIES the mechanical part across all 33 contracts in
one idempotent, auditable pass, leaving only genuine judgment calls for a human:

  (C1) flip silver_status 'available' -> 'planned' where the ref isn't in the live silver surface.
  (C2) reserve a canonical silver_ref for every planned driver missing one. Same driver id -> same slug
       everywhere (so a feature built once serves every contract that names it). suffix by type:
       event/policy/marker -> '_flag', else '_z'. This deduped slug set IS the MLOps feature roadmap.
  (C3) resolve a sign:'0' driver by BORROWING the modal non-zero sign that same driver id carries across
       the other contracts (drought is '+' in 20 places -> fix the lone '0'). If no sibling signs it, it
       stays '0' and is reported as a residual for human review (we never silently drop a driver).

Judgment residuals it does NOT touch (reported for hand-fix): contracts with no convergence, contradictory
cross edges, inter-commodity sign:'0', and untracked dropped endpoints. Re-runnable; the YAMLs are
reproducible from the saved raw.json, so mutating them in place is safe.

    python -m leviathan.causal.curate                 # DRY-RUN: print the changelog, write nothing
    python -m leviathan.causal.curate --apply         # write the curated YAMLs + the roadmap + residual report
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval
from leviathan.graphrag import extract as ex

_CAUSAL_DIR = cval._CAUSAL_DIR
_OUT = cval._OUT
_EVENTISH = {"policy_event", "state_marker", "hazard"}     # -> '_flag'; measures (climate/weather/instrument) -> '_z'


def sign_map(contracts: list[cs.CausalContract]) -> dict[str, str]:
    """driver id -> its modal NON-zero sign across all contracts (the sibling-borrow source for 0-signs)."""
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for c in contracts:
        for d in c.drivers:
            if d.sign in ("+", "-"):
                votes[d.id][d.sign] += 1
    return {k: v.most_common(1)[0][0] for k, v in votes.items() if v}


def reserve_name(driver: cs.Driver) -> str:
    """A canonical silver_ref slug for a planned driver that lacks one (deterministic from id+type).
    Accent-strip + lowercase only -- NOT singularized (so 'basis'->basis_z, not basi_z; 'excess_rain'
    stays excess, 'freight_logistics' stays logistics)."""
    base = re.sub(r"[^a-z0-9]+", "_", ex._normalize(driver.id).lower()).strip("_")
    suffix = "_flag" if driver.type in _EVENTISH else "_z"
    return base + suffix


def curate_contract(c: cs.CausalContract, signs: dict[str, str], silver: set[str]) -> tuple[cs.CausalContract, dict]:
    """Apply C1-C3 to one contract. Returns (curated, changelog)."""
    flips, named, borrowed, residual_zero = [], [], [], []
    for d in c.drivers:
        if d.silver_status == "available" and d.silver_ref and d.silver_ref not in silver:   # C1
            d.silver_status = "planned"
            flips.append(d.id)
        if d.silver_status == "planned" and not d.silver_ref:                                 # C2
            d.silver_ref = reserve_name(d)
            named.append((d.id, d.silver_ref))
        if d.sign == "0":                                                                     # C3
            borrow = signs.get(d.id)
            if borrow:
                d.sign = borrow
                borrowed.append((d.id, borrow))
            else:
                residual_zero.append(d.id)
    c2 = cs.CausalContract.model_validate(c.model_dump())  # revalidate the mutated contract
    return c2, {"contract": c.contract, "flips": flips, "named": named,
                "borrowed": borrowed, "residual_zero": residual_zero,
                "no_convergence": not c.convergence,
                "zero_inter": [(e.driver_commodity, e.relation) for e in c.inter_commodity if e.sign == "0"]}


def run(paths: list[Path] | None = None, *, apply: bool = False) -> dict:
    paths = paths if paths is not None else sorted(_CAUSAL_DIR.glob("*.yaml"))
    silver = cval.available_silver()
    loaded = [(p, cs.load(p)) for p in paths]
    signs = sign_map([c for _p, c in loaded])
    logs, roadmap = [], {}
    for p, c in loaded:
        c2, log = curate_contract(c, signs, silver)
        logs.append(log)
        for _id, ref in log["named"]:
            roadmap.setdefault(ref, set()).add(c.contract)
        if apply:
            cs.dump(c2, p)
    return {"signs": signs, "logs": logs, "roadmap": roadmap, "silver": silver}


def report(res: dict) -> str:
    logs = res["logs"]
    tot = lambda k: sum(len(x[k]) for x in logs)  # noqa: E731
    L = ["# Curation pass - changelog", "",
         f"{len(logs)} contracts. available->planned flips: {tot('flips')} | "
         f"names reserved: {tot('named')} | 0-signs borrowed: {tot('borrowed')} | "
         f"0-signs UNRESOLVED: {tot('residual_zero')}.", "",
         "## Residuals for human review", "",
         "### Contracts with NO convergence (add regimes)",
         ", ".join(x["contract"] for x in logs if x["no_convergence"]) or "(none)", "",
         "### Drivers still sign:0 after sibling-borrow (assign +/- or drop)"]
    L += [f"- **{x['contract']}**: {', '.join(x['residual_zero'])}"
          for x in logs if x["residual_zero"]] or ["(none)"]
    L += ["", "### Inter-commodity edges with sign:0 (hand-resolve)"]
    L += [f"- **{x['contract']}**: {', '.join(f'{t}/{r}' for t, r in x['zero_inter'])}"
          for x in logs if x["zero_inter"]] or ["(none)"]
    L += ["", f"## MLOps feature roadmap ({len(res['roadmap'])} reserved + named features)", ""]
    for ref in sorted(res["roadmap"], key=lambda r: (-len(res["roadmap"][r]), r)):
        L.append(f"- `{ref}` <- {len(res['roadmap'][ref])} contract(s)")
    return "\n".join(L)


def summary(res: dict) -> str:
    logs = res["logs"]
    tot = lambda k: sum(len(x[k]) for x in logs)  # noqa: E731
    return (f"contracts={len(logs)} flips={tot('flips')} names_reserved={tot('named')} "
            f"signs_borrowed={tot('borrowed')} signs_unresolved={tot('residual_zero')} "
            f"roadmap_features={len(res['roadmap'])}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Semi-automated causal curation pass (C1-C3).")
    ap.add_argument("--apply", action="store_true", help="write the curated YAMLs (default: dry-run)")
    args = ap.parse_args()
    res = run(apply=args.apply)
    if args.apply:
        _OUT.mkdir(parents=True, exist_ok=True)
        (_OUT / "curation_pass.md").write_text(report(res), encoding="utf-8")
        print(f"APPLIED. wrote curated YAMLs + {_OUT / 'curation_pass.md'}")
    else:
        print("DRY-RUN (no writes). Re-run with --apply to write.")
    print(summary(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
