"""E1 darkness census (Phase 7 P2.0 / W0.5) — the P2 exit-gate DENOMINATOR.

The P2 plan hangs on three audit numbers that had NO committed source artifact: 269/353 DAG driver
ids resolve to no evidence slice (76.2% dark), an "~84 aliasable" ceiling, and an "~58 strict-orphan"
slice count. This module RE-DERIVES them from configs, statically, so the exit-gate delta (dark 269 ->
<= |waivers|) is measured against a receipt instead of a memory. Run it BEFORE E1a/E1b (the baseline)
and AFTER (the ROI); the per-reason table is the ROI receipt the E0 turn-delta could never be (the
turn store is ~3 turns — adversarial-teardown correction #4).

STATIC-FIRST + ZERO-LLM + ZERO-ATHENA: every number is a pure function of the causal DAGs
(`display.all_driver_ids()`, the parent-inclusive frozenset) + `driver_slices.yaml` (the `drivers:`
block and the `dag_alias:` inversion, read through `evidence`) + the on-disk driver slice record counts.
No graph load, no model, no silver query.

Two censuses, cross-checked:

  per-id   -- for every DAG driver id: is it backed (`ev.backed_dag_ids()`), which slice does it route
              to (`ev.slice_for_driver`), and WHY is it dark — `unbacked` (no alias/identity entry at
              all) is the E1a-fixable class; `exact`/`alias` are the two BACKED sub-reasons (mirrors the
              unbacked_id/no_slice vocabulary of e0_harness.dark_legs). Plus the D1 signal: how many dark
              ids would resolve after ACCENT-FOLDING (NFKD -> strip combining marks) — El_Nino/La_Nina
              are byte-disjoint from their ASCII slice names and 100% dark today (correction #8).
  per-slice -- for every driver slice (a `drivers:` spec name UNION an on-disk drivers/<name>.jsonl):
              how many DAG ids point here (the identity + dag_alias inversion), how many props it holds
              (its record count), and whether it is CONSUMED (>=1 id AND >=1 prop). Orphans (not
              consumed) split into retire candidates (props but nothing routes to them — dead corpus) and
              keep candidates (ids route here but the slice is empty — an E1b build target).

LIST-storm discipline (the July incident, project memory): in S3 mode the per-slice record counts come
from ONE `list_objects_v2` LIST of the drivers/ prefix to enumerate + one GET per existing slice via
`ev.load_index` — never a per-slice HEAD/existence probe.

    python -m leviathan.graphrag.e1_census                 # census -> configs/graphrag/eval/, + S3 eval/ copy
    python -m leviathan.graphrag.e1_census --local-only    # skip the S3 upload (still reads EVIDENCE_S3 slices)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from leviathan.graphrag import display as dp
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

# fold() lives in evidence.py (the D1 accent-fold signal) and is re-exported here — driver_alias()'s
# accent-fold registration and this census's fold_recoverable metric MUST share one implementation. The
# import direction is forced: e1_census already imports evidence, so evidence importing e1_census would
# cycle; the helper therefore has to live in evidence and be re-imported here.
from leviathan.graphrag.evidence import fold  # noqa: F401 — re-exported for id_census + the test suite

_OUT = ex._CFG / "eval"


# ── per-id census ───────────────────────────────────────────────────────────────────────────────────
def id_census(all_ids, backed: set, slice_for) -> list[dict]:
    """One record per DAG driver id, sorted for a stable report:
      backed  -- id in backed_dag_ids()
      slice   -- slice_for_driver(id) (None when dark)
      reason  -- 'exact' (slice name IS the id) | 'alias' (dag_alias entry) | 'unbacked' (no entry) —
                 exact/alias are the two BACKED sub-reasons; unbacked is the E1a-fixable dark class
      fold_recoverable -- True iff dark today but its accent-folded form IS backed (the D1 unlock)
    An accent-folded id that is ALSO already backed (ASCII id that happens to fold to itself) is not
    counted as fold_recoverable — the flag is the NET new resolution accent-folding would buy."""
    out: list[dict] = []
    for did in sorted(all_ids):
        sl = slice_for(did)
        is_backed = did in backed
        if not is_backed:
            reason = "unbacked"
        elif sl == did:
            reason = "exact"                                   # slice name is the id itself (identity)
        else:
            reason = "alias"                                   # resolved via a curated dag_alias entry
        folded = fold(did)
        fold_recoverable = (not is_backed) and folded != did and folded in backed
        out.append({"id": did, "backed": is_backed, "slice": sl, "reason": reason,
                    "fold_recoverable": fold_recoverable})
    return out


def id_totals(recs: list[dict]) -> dict:
    """Roll the per-id records into the exit-gate headline: n_ids / n_backed / n_dark, the reason split,
    and the count of dark ids that accent-folding alone would recover (the aliasable-via-fold ceiling)."""
    by_reason: dict[str, int] = {}
    for r in recs:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    n_ids = len(recs)
    n_backed = sum(1 for r in recs if r["backed"])
    return {"n_ids": n_ids, "n_backed": n_backed, "n_dark": n_ids - n_backed,
            "by_reason": by_reason, "n_fold_recoverable": sum(1 for r in recs if r["fold_recoverable"])}


# ── per-slice census ────────────────────────────────────────────────────────────────────────────────
def _slice_names_on_disk() -> set[str]:
    """The drivers/<name> slice files that physically exist — ONE drivers/ LIST in S3 mode (never a
    per-slice existence probe: the July LIST-storm discipline), a single glob locally. Returned WITHOUT
    the drivers/ prefix or the .jsonl suffix, to match the `driver_specs()` keys."""
    base = ev._evid_s3()
    if base:
        import boto3
        bkt, prefix = ev._parse_s3(base.rstrip("/") + "/drivers/")
        out: set[str] = set()
        for p in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
            out |= {o["Key"][len(prefix):][:-6] for o in p.get("Contents", [])
                    if o["Key"].endswith(".jsonl") and "/" not in o["Key"][len(prefix):]}
        return out
    d = ev._EVID_DIR / "drivers"
    return {p.stem for p in d.glob("*.jsonl")} if d.exists() else set()


def slice_census(alias_map: dict, all_ids, spec_names, disk_names: set[str]) -> list[dict]:
    """One record per driver slice (a `drivers:` spec name UNION an on-disk drivers/<name>.jsonl):
      n_dag_ids  -- how many REAL DAG ids route here, from the {dag_id -> slice} alias_map inversion
      n_routed_props -- record count of drivers/<slice>.jsonl (load_index ONCE per slice; 0 if no file)
      consumed   -- n_dag_ids >= 1 AND n_routed_props >= 1
      orphan     -- not consumed; sub-typed for the retire/keep list:
                      retire -- props but no id routes here (dead corpus — an E2 reroute/retire candidate)
                      keep   -- ids route here but the slice is empty (an E1b build target — never retire)
                      empty  -- neither (a declared spec with no file and no routed id — inert)
    load_index is called ONLY for slices with a file on disk (spec-only names with no file skip the GET).

    The inversion is intersected with `all_ids` (the causal DAG set): `driver_alias()` self-maps EVERY
    slice name to itself for identity resolution, but a slice named after no real DAG node (a pure-corpus
    slice) must NOT count its own identity self-entry as a consumer — else no spec-named slice could ever
    be a retire orphan. Only a slice whose name IS a DAG id, or that a dag_alias entry targets, counts."""
    real = set(all_ids)
    inv: dict[str, int] = {}                                   # slice_name -> count of REAL dag ids pointing here
    for dag_id, slice_name in alias_map.items():
        if dag_id in real:
            inv[slice_name] = inv.get(slice_name, 0) + 1
    out: list[dict] = []
    for name in sorted(set(spec_names) | disk_names):
        n_ids = inv.get(name, 0)
        n_props = len(ev.load_index(f"drivers/{name}")) if name in disk_names else 0
        consumed = n_ids >= 1 and n_props >= 1
        if consumed:
            orphan_kind = None
        elif n_props >= 1:
            orphan_kind = "retire"                             # corpus with nothing routing to it
        elif n_ids >= 1:
            orphan_kind = "keep"                               # routed but empty -> build, don't retire
        else:
            orphan_kind = "empty"
        out.append({"slice": name, "n_dag_ids": n_ids, "n_routed_props": n_props,
                    "consumed": consumed, "orphan_kind": orphan_kind})
    return out


def slice_totals(recs: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    for r in recs:
        if r["orphan_kind"]:
            by_kind[r["orphan_kind"]] = by_kind.get(r["orphan_kind"], 0) + 1
    return {"n_slices": len(recs), "n_consumed": sum(1 for r in recs if r["consumed"]),
            "n_orphan": sum(1 for r in recs if not r["consumed"]), "orphan_by_kind": by_kind}


# ── assembly ────────────────────────────────────────────────────────────────────────────────────────
def census() -> dict:
    """The full machine-readable census artifact. Pure function of the live configs — read the alias map
    ONCE (`driver_alias()`) and reuse it for both the id and the slice pass so the two agree by construction."""
    alias_map = ev.driver_alias()                             # {dag_id -> slice_name}; identity + dag_alias
    backed = set(alias_map.keys())                            # == ev.backed_dag_ids(); reuse the one read
    all_ids = dp.all_driver_ids()
    ids = id_census(all_ids, backed, ev.slice_for_driver)
    slices = slice_census(alias_map, all_ids, ev.driver_specs().keys(), _slice_names_on_disk())
    return {"census": "E1_darkness", "basis": "as_of_current_config",
            "id_totals": id_totals(ids), "slice_totals": slice_totals(slices),
            "ids": ids, "slices": slices}


def _md(doc: dict) -> str:
    """ASCII-only markdown report (advisory convention: configs/graphrag/eval/*.md, coverage.py precedent).
    Lists the retire/keep orphan slices and the dark, fold-recoverable ids explicitly — those are the E2 /
    E1a work items the census exists to name."""
    it, st = doc["id_totals"], doc["slice_totals"]
    dark_pct = 100.0 * it["n_dark"] / max(1, it["n_ids"])
    L = ["# E1 darkness census (as-of-current-config)", "",
         "Static, zero-LLM, zero-Athena re-derivation of the P2 exit-gate denominator. Run before and "
         "after E1a/E1b; the `n_dark` delta is the ROI receipt.", "",
         "## DAG driver ids", "",
         f"- **ids:** {it['n_ids']} | **backed:** {it['n_backed']} | "
         f"**dark:** {it['n_dark']} ({dark_pct:.1f}%)",
         f"- reason split: {it['by_reason']}",
         f"- **accent-fold recoverable (D1 unlock):** {it['n_fold_recoverable']} dark ids resolve after "
         "NFKD accent-folding", "",
         "| id | backed | reason | slice | fold-recoverable |", "|---|--|--|--|--|"]
    for r in doc["ids"]:
        L.append(f"| {r['id']} | {'y' if r['backed'] else 'n'} | {r['reason']} | {r['slice'] or '-'} "
                 f"| {'y' if r['fold_recoverable'] else ''} |")

    L += ["", "## Driver slices", "",
          f"- **slices:** {st['n_slices']} | **consumed:** {st['n_consumed']} | "
          f"**orphan:** {st['n_orphan']}",
          f"- orphan split: {st['orphan_by_kind']} "
          "(retire = props but no id routes here; keep = routed but empty -> build, never retire)", "",
          "| slice | #dag_ids | #props | consumed | orphan |", "|---|--|--|--|--|"]
    for r in doc["slices"]:
        L.append(f"| {r['slice']} | {r['n_dag_ids']} | {r['n_routed_props']} | "
                 f"{'y' if r['consumed'] else 'n'} | {r['orphan_kind'] or ''} |")

    retire = [r["slice"] for r in doc["slices"] if r["orphan_kind"] == "retire"]
    keep = [r["slice"] for r in doc["slices"] if r["orphan_kind"] == "keep"]
    fold_ids = [r["id"] for r in doc["ids"] if r["fold_recoverable"]]
    L += ["", "## Work items (advisory — curation-gated)", "",
          f"- **retire candidates** (dead corpus): {', '.join(retire) or 'none'}",
          f"- **keep candidates** (routed but empty -> E1b build): {', '.join(keep) or 'none'}",
          f"- **accent-fold unlocks** (E1a D1): {', '.join(fold_ids) or 'none'}"]
    return "\n".join(L)


def _summary_lines(doc: dict) -> list[str]:
    """Compact ASCII stdout summary (Windows cp1252 console — no unicode). The headline numbers only."""
    it, st = doc["id_totals"], doc["slice_totals"]
    dark_pct = 100.0 * it["n_dark"] / max(1, it["n_ids"])
    return [f"ids {it['n_ids']} | backed {it['n_backed']} | dark {it['n_dark']} ({dark_pct:.1f}%) "
            f"| fold-recoverable {it['n_fold_recoverable']}",
            f"reasons {it['by_reason']}",
            f"slices {st['n_slices']} | consumed {st['n_consumed']} | orphan {st['n_orphan']} "
            f"{st['orphan_by_kind']}"]


def write(doc: dict, *, upload: bool = True) -> Path:
    """Write e1_census.md + e1_census.json to configs/graphrag/eval/ and — when EVIDENCE_S3 is set and
    `upload` — a copy of BOTH to <EVIDENCE_S3>/eval/ (mirrors eval._write_baseline). Returns the md path.
    Fixed filenames (not run-stamped): the census is a snapshot to diff before/after, not an append log."""
    _OUT.mkdir(parents=True, exist_ok=True)
    md_path = _OUT / "e1_census.md"
    json_path = _OUT / "e1_census.json"
    md_path.write_text(_md(doc), encoding="utf-8")
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if upload:
        s3uri = ev._evid_s3()
        if s3uri:
            import boto3
            s3 = boto3.client("s3")
            for p in (md_path, json_path):
                b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/{p.name}")
                s3.put_object(Bucket=b, Key=k, Body=p.read_bytes())
                print(f"  census -> s3://{b}/{k}")
    return md_path


def main() -> int:  # pragma: no cover — CLI glue; census()/write() are unit-tested
    import argparse

    from leviathan.common import config
    ap = argparse.ArgumentParser(description="E1 darkness census (static, zero-LLM, $0)")
    ap.add_argument("--local-only", action="store_true", help="skip the S3 eval/ upload (still reads slices)")
    args = ap.parse_args()
    config.load_env()
    doc = census()
    md_path = write(doc, upload=not args.local_only)
    for line in _summary_lines(doc):
        print(line)
    print(f"census -> {md_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
