"""Cross-contract curation audit (GRAPHRAG_PLAN Phase 1, post-scaling).

Folds every curated causal YAML into ONE checklist so curation is mechanical -- resolve 0-signs, reserve a
roadmap name for each planned driver, add convergence where missing -- instead of hunting file by file.
Pure/free: reads the YAMLs + the live silver surface, no network, no spend.

    python -m leviathan.causal.audit                 # writes configs/graphrag/pilot/curation_audit.md
    python -m leviathan.causal.audit --print         # ...and echo an ASCII summary to stdout
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval

_CAUSAL_DIR = cval._CAUSAL_DIR
_OUT = cval._OUT


def audit_contract(c: cs.CausalContract, silver: set[str]) -> dict:
    """The curation items for one contract (all the things a human must resolve before it ships)."""
    zero_signs = [d.id for d in c.drivers if d.sign == "0"]
    zero_inter = [(e.driver_commodity, e.relation) for e in c.inter_commodity if e.sign == "0"]
    available_not_built = [(d.id, d.silver_ref) for d in c.drivers
                           if d.silver_status == "available" and d.silver_ref and d.silver_ref not in silver]
    planned_named = [(d.id, d.silver_ref) for d in c.drivers
                     if d.silver_status == "planned" and d.silver_ref]
    planned_unnamed = [d.id for d in c.drivers if d.silver_status == "planned" and not d.silver_ref]
    by_edge: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for e in c.inter_commodity:                                   # same target+relation carrying opposite signs
        by_edge[(e.driver_commodity, e.relation)].add(e.sign)
    contradictory = [k for k, signs in by_edge.items() if {"+", "-"} <= signs]
    return {"contract": c.contract, "n_drivers": len(c.drivers), "no_convergence": not c.convergence,
            "zero_signs": zero_signs, "zero_inter": zero_inter, "available_not_built": available_not_built,
            "planned_named": planned_named, "planned_unnamed": planned_unnamed,
            "contradictory_inter": contradictory}


def run(paths: list[Path] | None = None, *, silver: set[str] | None = None) -> dict:
    paths = paths if paths is not None else sorted(_CAUSAL_DIR.glob("*.yaml"))
    silver = cval.available_silver() if silver is None else silver
    audits = []
    for p in paths:
        try:
            audits.append(audit_contract(cs.load(p), silver))
        except Exception:  # noqa: BLE001 -- a schema-broken YAML is the validator's job, not the auditor's
            continue
    return {"silver": silver, "audits": audits}


def report(res: dict) -> str:
    audits = res["audits"]
    L = ["# Curation audit - all causal contracts", "",
         f"{len(audits)} contracts; {len(res['silver'])} live silver names.", "",
         "## Per-contract (curation load)", "",
         "| contract | drivers | conv | 0-sign | planned(unnamed) | avail!built | contradict |",
         "|---|---|---|---|---|---|---|"]
    for a in sorted(audits, key=lambda x: x["contract"]):
        L.append(f"| {a['contract']} | {a['n_drivers']} | {'NONE' if a['no_convergence'] else 'ok'} "
                 f"| {len(a['zero_signs'])} | {len(a['planned_unnamed'])} | {len(a['available_not_built'])} "
                 f"| {len(a['contradictory_inter'])} |")

    noconv = [a["contract"] for a in audits if a["no_convergence"]]
    L += ["", "## (1) Contracts with NO convergence - add regimes", "",
          ", ".join(noconv) if noconv else "(none)"]

    named = collections.Counter(ref for a in audits for _id, ref in a["planned_named"])
    L += ["", f"## (2a) Planned instruments already NAMED - unserved refs ({len(named)} distinct, by #contracts)", ""]
    L += [f"- `{ref}` x{n}" for ref, n in named.most_common()] or ["(none)"]

    unnamed = collections.Counter(did for a in audits for did in a["planned_unnamed"])
    L += ["", f"## (2b) Planned drivers MISSING a silver_ref - reserve one canonical name each "
          f"({sum(unnamed.values())} total, {len(unnamed)} distinct)", ""]
    L += [f"- `{did}` x{n}" for did, n in unnamed.most_common()] or ["(none)"]

    L += ["", "## (3) Zero-sign drivers to resolve (+/- or drop)", ""]
    z = [f"- **{a['contract']}**: {', '.join(a['zero_signs'])}"
         + (f"  | inter: {', '.join(f'{t}/{r}' for t, r in a['zero_inter'])}" if a["zero_inter"] else "")
         for a in sorted(audits, key=lambda x: x["contract"]) if a["zero_signs"] or a["zero_inter"]]
    L += z or ["(none)"]

    L += ["", "## (4) 'available' refs NOT in live silver - auto-flip to planned", ""]
    av = [f"- **{a['contract']}**: " + ", ".join(f"{i}({r})" for i, r in a["available_not_built"])
          for a in sorted(audits, key=lambda x: x["contract"]) if a["available_not_built"]]
    L += av or ["(none)"]

    L += ["", "## (5) Contradictory cross-commodity edges (same target+relation, both +/-)", ""]
    cc = [f"- **{a['contract']}**: " + ", ".join(f"{t}/{r}" for t, r in a["contradictory_inter"])
          for a in sorted(audits, key=lambda x: x["contract"]) if a["contradictory_inter"]]
    L += cc or ["(none)"]
    return "\n".join(L)


def summary(res: dict) -> str:
    """A compact ASCII stdout line-set (cp1252-safe) for --print."""
    a = res["audits"]
    noconv = sum(x["no_convergence"] for x in a)
    zero = sum(len(x["zero_signs"]) for x in a)
    unnamed = sum(len(x["planned_unnamed"]) for x in a)
    avail = sum(len(x["available_not_built"]) for x in a)
    contra = sum(len(x["contradictory_inter"]) for x in a)
    return (f"contracts={len(a)} | no_convergence={noconv} | zero_signs={zero} | "
            f"planned_unnamed={unnamed} | available_not_built={avail} | contradictory_edges={contra}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-contract causal curation audit (free).")
    ap.add_argument("--print", dest="echo", action="store_true", help="echo an ASCII summary to stdout")
    args = ap.parse_args()
    res = run()
    _OUT.mkdir(parents=True, exist_ok=True)
    out = _OUT / "curation_audit.md"
    out.write_text(report(res), encoding="utf-8")
    print(f"wrote {out} ({len(res['audits'])} contracts)")
    if args.echo:
        print(summary(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
