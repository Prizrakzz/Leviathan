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
    python -m leviathan.graphrag.e1_census --diff          # W1.3 gate: diff vs the newest archived BEFORE-copy
    python -m leviathan.graphrag.e1_census --diff --baseline configs/graphrag/eval/e1_census_<ts>.json

W1.3 STANDING GATE (the P2 overwrite lesson, banked): the census writes FIXED filenames so it can be
diffed before/after, but a fixed-filename rerun clobbers the BEFORE artifact. `write()` therefore copies
any existing e1_census.json to a timestamped e1_census_<UTC>.json (local + S3 eval/) BEFORE it overwrites,
and `--diff` re-derives the CURRENT census and compares it to a prior copy (a `--baseline` path, else the
newest archive) — exiting NONZERO on a stranding regression (a consumed->orphan transition or a grown
retire count). The rebuild/load wrappers wire this diff in as an opt-in gate.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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


def _archive_stamp() -> str:
    """UTC filename stamp for the BEFORE-overwrite archive copy (e.g. 20260707T134512Z). Zero-padded and
    lexically sortable so the newest archive is `max()`/`sorted()[-1]` without parsing the timestamp back."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_s3_prior(s3uri: str, stamp: str) -> None:  # pragma: no cover — needs live S3 (boto)
    """Copy the prior remote eval/e1_census.json to eval/e1_census_<stamp>.json BEFORE write() overwrites it,
    so the S3 BEFORE-snapshot survives the fixed-filename rerun too. ONE head_object existence probe + one
    server-side copy_object (never a LIST): skips silently on the first upload (no prior remote copy)."""
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client("s3")
    b, live_key = ev._parse_s3(s3uri.rstrip("/") + "/eval/e1_census.json")
    _, arch_key = ev._parse_s3(s3uri.rstrip("/") + f"/eval/e1_census_{stamp}.json")
    try:
        s3.head_object(Bucket=b, Key=live_key)
    except ClientError:
        return                                                 # no prior remote copy -> nothing to archive
    s3.copy_object(Bucket=b, CopySource={"Bucket": b, "Key": live_key}, Key=arch_key)
    print(f"  census archive -> s3://{b}/{arch_key}")


def write(doc: dict, *, upload: bool = True, archive: bool = True) -> Path:
    """Write e1_census.md + e1_census.json to configs/graphrag/eval/ and — when EVIDENCE_S3 is set and
    `upload` — a copy of BOTH to <EVIDENCE_S3>/eval/ (mirrors eval._write_baseline). Returns the md path.
    Fixed filenames (not run-stamped): the census is a snapshot to diff before/after, not an append log.

    W1.3 archive-before-overwrite (default on): when `archive` and a prior e1_census.json already exists,
    copy it to a timestamped e1_census_<UTC>.json (local, and — under `upload` — the remote copy via
    copy_object) BEFORE the overwrite, so a BEFORE snapshot is never lost (the P2 overwrite lesson). The
    primary artifacts (e1_census.{md,json}) stay byte-identical to the pre-archive behaviour; the archive
    is purely additive. `archive=False` restores the exact old overwrite-only path for callers that want it."""
    _OUT.mkdir(parents=True, exist_ok=True)
    md_path = _OUT / "e1_census.md"
    json_path = _OUT / "e1_census.json"
    if archive:
        stamp = _archive_stamp()
        if json_path.exists():                                 # local BEFORE-copy (byte-for-byte of the prior)
            (_OUT / f"e1_census_{stamp}.json").write_bytes(json_path.read_bytes())
        if upload:
            s3uri = ev._evid_s3()
            if s3uri:
                _archive_s3_prior(s3uri, stamp)
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


# ── W1.3 standing gate: --diff + baseline resolution ──────────────────────────────────────────────────
def diff_census(baseline: dict, current: dict) -> dict:
    """Delta between two census artifacts (current - baseline) for the regression gate. Pure function of two
    census dicts (the shape `census()` returns) — no config/IO — so both the CLI and the wrappers share one
    verdict. Reports the headline deltas and the TWO stranding-regression signals the doctrine watches:

      d_dark / d_consumed / d_retire -- signed (current - baseline) deltas on the headline counts
      by_reason_delta                -- {reason: signed delta} across the union of both reason maps
      consumed_to_orphan             -- sorted slices that were CONSUMED in baseline but are orphan now AND
                                        still present (a slice reachable-and-fed that lost its evidence/route)
      regressed                      -- True iff consumed_to_orphan is non-empty OR the retire count grew;
                                        these are the fail conditions (a slice went dark, or dead corpus grew)

    A slice that vanished entirely from `current` is NOT a consumed->orphan transition (rename/retire is a
    curation act, not a silent stranding); the gate only fires on a slice that is still declared but slipped."""
    bi, ci = baseline["id_totals"], current["id_totals"]
    bs, cs = baseline["slice_totals"], current["slice_totals"]
    b_retire = bs.get("orphan_by_kind", {}).get("retire", 0)
    c_retire = cs.get("orphan_by_kind", {}).get("retire", 0)
    b_by = {r["slice"]: r for r in baseline.get("slices", [])}
    c_by = {r["slice"]: r for r in current.get("slices", [])}
    consumed_to_orphan = sorted(
        name for name, br in b_by.items()
        if br.get("consumed") and name in c_by and not c_by[name].get("consumed"))
    reasons = set(bi.get("by_reason", {})) | set(ci.get("by_reason", {}))
    by_reason_delta = {r: ci.get("by_reason", {}).get(r, 0) - bi.get("by_reason", {}).get(r, 0)
                       for r in sorted(reasons)}
    regressed = bool(consumed_to_orphan) or c_retire > b_retire
    return {
        "d_dark": ci["n_dark"] - bi["n_dark"],
        "d_consumed": cs["n_consumed"] - bs["n_consumed"],
        "d_retire": c_retire - b_retire,
        "by_reason_delta": by_reason_delta,
        "n_dark": {"baseline": bi["n_dark"], "current": ci["n_dark"]},
        "n_consumed": {"baseline": bs["n_consumed"], "current": cs["n_consumed"]},
        "orphan_by_kind": {"baseline": bs.get("orphan_by_kind", {}),
                           "current": cs.get("orphan_by_kind", {})},
        "consumed_to_orphan": consumed_to_orphan,
        "regressed": regressed,
    }


def _diff_lines(d: dict) -> list[str]:
    """Compact ASCII stdout summary of a census diff (cp1252 console safe — no unicode). Names the regressing
    slices/counts and ends with the VERDICT the exit code mirrors."""
    def sgn(n: int) -> str:
        return f"+{n}" if n > 0 else str(n)
    lines = [
        f"n_dark {d['n_dark']['baseline']} -> {d['n_dark']['current']} ({sgn(d['d_dark'])})",
        f"n_consumed {d['n_consumed']['baseline']} -> {d['n_consumed']['current']} ({sgn(d['d_consumed'])})",
        f"retire {d['orphan_by_kind']['baseline'].get('retire', 0)} -> "
        f"{d['orphan_by_kind']['current'].get('retire', 0)} ({sgn(d['d_retire'])})",
        f"by_reason_delta {d['by_reason_delta']}",
    ]
    if d["consumed_to_orphan"]:
        lines.append("REGRESSION consumed->orphan: " + ", ".join(d["consumed_to_orphan"]))
    if d["d_retire"] > 0:
        lines.append(f"REGRESSION retire count grew by {d['d_retire']}")
    lines.append("VERDICT " + ("REGRESSED (exit 1)" if d["regressed"] else "ok (exit 0)"))
    return lines


def run_diff(current: dict, baseline: dict) -> tuple[int, list[str]]:
    """Compute the diff + render its ASCII lines + decide the exit code (1 on regression, else 0). The
    wrappers read the exit code to fail a rebuild/load on a stranding regression; the lines are for stdout."""
    d = diff_census(baseline, current)
    return (1 if d["regressed"] else 0), _diff_lines(d)


def _newest_archive() -> Path | None:
    """The most recent LOCAL e1_census_<UTC>.json archive in _OUT (the default --diff baseline). The stamp is
    zero-padded UTC, so lexical sort == chronological — `sorted()[-1]` is the newest without parsing dates."""
    if not _OUT.exists():
        return None
    archives = sorted(_OUT.glob("e1_census_*.json"))
    return archives[-1] if archives else None


def _newest_s3_archive() -> tuple[dict, str] | None:  # pragma: no cover — needs live S3 (boto)
    """Container-side fallback baseline: the newest eval/e1_census_<UTC>.json archive under EVIDENCE_S3.
    ONE list_objects_v2 of the eval/ prefix + one GET of the newest key — LIST-safe (a single prefix LIST,
    never a per-key probe; the July LIST-storm discipline). Returns (census_dict, s3_uri) or None."""
    s3uri = ev._evid_s3()
    if not s3uri:
        return None
    import boto3
    s3 = boto3.client("s3")
    b, prefix = ev._parse_s3(s3uri.rstrip("/") + "/eval/")
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
        for o in page.get("Contents") or []:
            name = o["Key"][len(prefix):]
            if name.startswith("e1_census_") and name.endswith(".json") and "/" not in name:
                keys.append(o["Key"])
    if not keys:
        return None
    newest = max(keys)                                         # zero-padded UTC stamp sorts == chronological
    body = s3.get_object(Bucket=b, Key=newest)["Body"].read()
    return json.loads(body.decode("utf-8")), f"s3://{b}/{newest}"


def load_baseline(explicit: str | None = None) -> tuple[dict | None, str]:
    """Resolve the --diff baseline census dict + a human label. Priority: an explicit --baseline path, then
    the newest LOCAL archive, then (S3 mode) the newest eval/ S3 archive. Returns (None, reason) when nothing
    resolves — the caller decides whether a missing baseline is a soft skip (first run) or a hard stop."""
    if explicit:
        p = Path(explicit)
        if not p.exists():
            return None, f"--baseline {explicit} not found"
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    local = _newest_archive()
    if local is not None:
        return json.loads(local.read_text(encoding="utf-8")), str(local)
    remote = _newest_s3_archive()
    if remote is not None:
        return remote
    return None, "no baseline (no --baseline, no local archive, no S3 eval/ archive)"


def main() -> int:  # pragma: no cover — CLI glue; census()/write() are unit-tested
    import argparse

    from leviathan.common import config
    ap = argparse.ArgumentParser(description="E1 darkness census (static, zero-LLM, $0)")
    ap.add_argument("--local-only", action="store_true", help="skip the S3 eval/ upload (still reads slices)")
    ap.add_argument("--diff", action="store_true",
                    help="W1.3 gate: re-derive the CURRENT census and diff it against a prior copy; exit "
                         "NONZERO on a stranding regression (consumed->orphan transition or retire growth). "
                         "Does NOT write/archive (a read-only gate).")
    ap.add_argument("--baseline", default=None, metavar="PATH",
                    help="--diff only: the prior e1_census.json to diff against (default: newest archived copy, "
                         "then the newest S3 eval/ archive)")
    args = ap.parse_args()
    config.load_env()

    if args.diff:
        baseline, label = load_baseline(args.baseline)
        if baseline is None:
            print(f"census --diff: {label}; skipping the gate (nothing to compare)")
            return 0                                           # no prior -> soft skip (first run), not a regression
        current = census()
        code, lines = run_diff(current, baseline)
        for line in lines:
            print(line)
        print(f"census --diff baseline -> {label}")
        return code

    doc = census()
    md_path = write(doc, upload=not args.local_only)
    for line in _summary_lines(doc):
        print(line)
    print(f"census -> {md_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
