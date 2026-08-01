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
from datetime import datetime, timezone
from pathlib import Path

from leviathan.graphrag import display as dp
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

# fold() lives in evidence.py (the D1 accent-fold signal) and is re-exported here — driver_alias()'s
# accent-fold registration and this census's fold_recoverable metric MUST share one implementation. The
# import direction is forced: e1_census already imports evidence, so evidence importing e1_census would
# cycle; the helper therefore has to live in evidence and be re-imported here.
from leviathan.graphrag.evidence import (
    fold,  # noqa: F401 — re-exported for id_census + the test suite
)

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


# ── era (facet-thinness) helpers ──────────────────────────────────────────────────────────────────────
# A thick slice hollow in a historical era is what the analogue engine cannot serve. The era histogram is
# derived from the SAME load_index records slice_census already loads (ZERO new S3 GETs). event_date (the
# date the prop is ABOUT) is preferred over date (publication) for the bucket; unparseable / future years
# fall to "undated" -- a data-quality note, never an era gap (so undated never triggers thin_eras).
_ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")
_REAL_ERAS = _ERAS[:5]                                         # the five datable eras (undated excluded)
THICK_MIN = 100                                               # only slices with >= this many props are judged
THIN_MAX = 10                                                 # a real era below this in a thick slice = a gap


def _era_of(rec: dict) -> str:
    """Bucket one prop record by era. event_date first, else date; unparseable or year > 2026 -> 'undated'."""
    raw = rec.get("event_date") or rec.get("date")
    try:
        year = int(str(raw)[:4])
    except (TypeError, ValueError):
        return "undated"
    if year < 1990:
        return "pre1990"
    if year <= 1999:
        return "1990s"
    if year <= 2009:
        return "2000s"
    if year <= 2017:
        return "2010_17"
    if year <= 2026:
        return "2018_26"
    return "undated"                                          # future year -> data-quality note, not an era


def _era_hist(recs: list[dict]) -> dict:
    """Per-era record count over loaded props; ALL SIX era keys explicit (zero-count eras included)."""
    h = {e: 0 for e in _ERAS}
    for rec in recs:
        h[_era_of(rec)] += 1
    return h


def _thin_eras(n_props: int, hist: dict) -> list[str]:
    """Thickness-gated gap flag: [] unless the slice is thick (>= THICK_MIN props); else the REAL eras
    (undated excluded) below THIN_MAX, in chronological order. A small slice being sparse is not a gap."""
    if n_props < THICK_MIN:
        return []
    return [e for e in _REAL_ERAS if hist[e] < THIN_MAX]


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
        recs = ev.load_index(f"drivers/{name}") if name in disk_names else []  # the ONE GET per slice
        n_props = len(recs)
        era_hist = _era_hist(recs)                            # derived from the SAME load -- no extra GET
        thin_eras = _thin_eras(n_props, era_hist)             # [] unless the slice is thick (>= THICK_MIN)
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
                    "consumed": consumed, "orphan_kind": orphan_kind,
                    "era_hist": era_hist, "thin_eras": thin_eras})
    return out


def slice_totals(recs: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    for r in recs:
        if r["orphan_kind"]:
            by_kind[r["orphan_kind"]] = by_kind.get(r["orphan_kind"], 0) + 1
    return {"n_slices": len(recs), "n_consumed": sum(1 for r in recs if r["consumed"]),
            "n_orphan": sum(1 for r in recs if not r["consumed"]), "orphan_by_kind": by_kind,
            "n_thick_with_thin_eras": sum(1 for r in recs if r.get("thin_eras"))}


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
          "(retire = props but no id routes here; keep = routed but empty -> build, never retire)",
          f"- **thick slices with historical-era gaps:** {st.get('n_thick_with_thin_eras', 0)} "
          "(see Facet thinness below)", "",
          "| slice | #dag_ids | #props | consumed | orphan |", "|---|--|--|--|--|"]
    for r in doc["slices"]:
        L.append(f"| {r['slice']} | {r['n_dag_ids']} | {r['n_routed_props']} | "
                 f"{'y' if r['consumed'] else 'n'} | {r['orphan_kind'] or ''} |")

    # Facet thinness: thick slices (>= THICK_MIN props) that are hollow (< THIN_MAX) in >=1 REAL era -- the
    # analogue-serving gaps. undated is never a thin era (data-quality note), so it is a display column only.
    thin = [r for r in doc["slices"] if r.get("thin_eras")]
    L += ["", "## Facet thinness (thick slices with historical-era gaps)", "",
          f"- gate: THICK_MIN={THICK_MIN} props to be judged, THIN_MAX={THIN_MAX} props per real era "
          "(undated excluded -- a data-quality note, not an era gap)", ""]
    if thin:
        L += ["| slice | #props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated | thin eras |",
              "|---|--|--|--|--|--|--|--|--|"]
        for r in thin:
            h = r["era_hist"]
            L.append(f"| {r['slice']} | {r['n_routed_props']} | {h['pre1990']} | {h['1990s']} | "
                     f"{h['2000s']} | {h['2010_17']} | {h['2018_26']} | {h['undated']} | "
                     f"{', '.join(r['thin_eras'])} |")
    else:
        L.append("- none (no thick slice has a sub-threshold real era)")

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
# G3b(1) -- THE POPULATION-DELTA FAIL CONDITION. Before this, `--census-gate` was population-blind and
# arming it shipped a false sense of coverage: `consumed = n_ids >= 1 and n_props >= 1` (:197) stays True
# whatever the count does, and the verdict at :391 failed ONLY on a consumed->orphan transition or a grown
# retire count. RECEIPT: the live 2026-07-09 census records `coffee_rust_crop n_routed_props=505,
# n_dag_ids=1, consumed=True`; the file on S3 today holds 20 props. The armed gate would have passed that
# 96% wipe silently, and it would have passed all 40 shrinking slices at the 2026-07-20 promote. The
# per-slice n_routed_props was ALREADY in the artifact (:206-208) -- only the verdict ignored it.
#
# Both lines are FIRST TRIP LINES (D-EI-7's calibration, same 10% as the write-path guard so the two agree):
POP_DROP_REFUSE = 0.10        # fractional drop in a slice's n_routed_props that fails the gate
POP_DROP_MIN_ABS = 5          # ... and it must also be >= this many props, so 10 -> 9 on a tiny slice is
#                               noise, not a regression. coffee_rust_crop was -485; `metals` was -263.


def population_drops(baseline: dict, current: dict) -> list[dict]:
    """Slices present in BOTH censuses whose n_routed_props fell past both trip lines. Pure function of two
    census dicts. A slice that VANISHED is not counted here (rename/retire is a curation act -- the same
    doctrine diff_census already applies to consumed->orphan)."""
    b_by = {r["slice"]: r for r in baseline.get("slices", [])}
    out = []
    for r in current.get("slices", []):
        b = b_by.get(r["slice"])
        if not b:
            continue
        before, after = int(b.get("n_routed_props") or 0), int(r.get("n_routed_props") or 0)
        lost = before - after
        if before <= 0 or lost < POP_DROP_MIN_ABS:
            continue
        frac = lost / before
        if frac >= POP_DROP_REFUSE:
            out.append({"slice": r["slice"], "before": before, "after": after,
                        "lost": lost, "frac": round(frac, 4)})
    return sorted(out, key=lambda d: (-d["lost"], d["slice"]))


def diff_census(baseline: dict, current: dict) -> dict:
    """Delta between two census artifacts (current - baseline) for the regression gate. Pure function of two
    census dicts (the shape `census()` returns) — no config/IO — so both the CLI and the wrappers share one
    verdict. Reports the headline deltas and the TWO stranding-regression signals the doctrine watches:

      d_dark / d_consumed / d_retire -- signed (current - baseline) deltas on the headline counts
      by_reason_delta                -- {reason: signed delta} across the union of both reason maps
      consumed_to_orphan             -- sorted slices that were CONSUMED in baseline but are orphan now AND
                                        still present (a slice reachable-and-fed that lost its evidence/route)
      population_drops               -- G3b: slices whose n_routed_props fell >= POP_DROP_REFUSE and
                                        >= POP_DROP_MIN_ABS props (the leg that makes the gate see a wipe)
      regressed                      -- True iff consumed_to_orphan is non-empty OR the retire count grew OR
                                        any slice's population dropped past the trip lines

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
    drops = population_drops(baseline, current)
    regressed = bool(consumed_to_orphan) or c_retire > b_retire or bool(drops)
    return {
        "population_drops": drops,
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


# ── G8 item 1: the TERM census (dead terms + the cross-claim matrix) ───────────────────────────────────────
def term_census(*, sample: int | None = None) -> dict:
    """G8 item 1 (F13) -- the corpus-wide term census: which driver TERMS claim nothing, and which props are
    claimed by more than one slice. READ-ONLY over the chunks/ doc-cache; writes no slice, embeds nothing,
    calls no model, costs no Haiku.

    WHY IT IS HERE AND NOT IN A SCRATCHPAD. G8 asked for two artifact-free items. Item 2
    (`evidence.term_collision_warnings`, the STATIC config-vs-config detector) landed; item 1 -- "run it at
    full corpus, write the cross-claim matrix and the dead-term list beside the E1 census" -- did not, and
    the numbers standing in for it (310 of 638 terms dead, 1,319 multiply-claimed props) came from a 20%
    sample in a session scratchpad with no committed harness. A screening result with no standing baseline
    reads exactly like a measurement, which is the class of confusion this whole wave exists to remove. The
    static lint by construction cannot produce either number: it compares terms to terms and never touches a
    prop.

    WHAT IT MEASURES, per driver term:
      * `n_props` -- props in the cache whose text matches this term on a word boundary, under the SAME
        normalization harvest._Matcher applies (ex._normalize: NFKD -> ASCII, casefold, collapse ws/_/-), so
        an accent or case difference never manufactures a dead term. `n_props == 0` is a DEAD term: it is in
        the routing vocabulary, it is in the manifest mirror's digest, and it claims nothing.
      * per slice, how many of its props ONLY that slice claims (`n_props_sole`) versus how many at least one
        other slice also claims -- the cross-claim matrix, keyed by the unordered slice pair.

    COST/SPEED. One pass over the cache. Per prop the text is normalized ONCE, then each term is screened by
    a plain substring test before its word-boundary regex is compiled/run at all -- 638 substring tests are
    microseconds; 638 regexes per prop would not be. `sample` takes the first N cached documents (sorted, so
    a sample is reproducible) for a screening run; None is the full corpus, which is what a BASELINE needs.

    Returns the document; `write_term_census` persists it beside the other eval artifacts."""
    import re as _re

    from leviathan.graphrag import evidence_batch as eb
    specs = ev.driver_specs()
    # (normalized term, original term, slice) -- same normalization as _Matcher, same skip of 1-char forms.
    terms: list[tuple[str, str, str]] = []
    for name in sorted(specs):
        for t in (specs[name].get("terms") or []):
            nf = ex._normalize(str(t))
            if nf and len(nf) > 1:
                terms.append((nf, str(t), name))
    rxs = [_re.compile(r"\b" + _re.escape(nf) + r"\b") for nf, _, _ in terms]
    hits = [0] * len(terms)
    slice_props: dict[str, int] = {n: 0 for n in specs}
    slice_sole: dict[str, int] = {n: 0 for n in specs}
    pairs: dict[str, int] = {}
    n_props = n_multi = 0

    hashes = sorted(eb._cached_hashes())
    if sample:
        hashes = hashes[:sample]
    for h in hashes:
        for p in ev.load_index(f"chunks/{h}"):
            text_nf = ex._normalize(p.get("text") or "")
            if not text_nf:
                continue
            n_props += 1
            claimed: set[str] = set()
            for i, (nf, _orig, sl) in enumerate(terms):
                if nf in text_nf and rxs[i].search(text_nf):    # substring screen, THEN the boundary regex
                    hits[i] += 1
                    claimed.add(sl)
            for sl in claimed:
                slice_props[sl] += 1
            if len(claimed) == 1:
                slice_sole[next(iter(claimed))] += 1
            elif len(claimed) > 1:
                n_multi += 1
                ordered = sorted(claimed)
                for a in range(len(ordered)):
                    for b in range(a + 1, len(ordered)):
                        key = f"{ordered[a]}|{ordered[b]}"
                        pairs[key] = pairs.get(key, 0) + 1

    per_term = [{"slice": sl, "term": orig, "n_props": hits[i]}
                for i, (_nf, orig, sl) in enumerate(terms)]
    dead = sorted(((t["slice"], t["term"]) for t in per_term if t["n_props"] == 0))
    return {
        "census": "term_census", "version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": {"n_docs": len(hashes), "n_props": n_props, "sample": sample,
                  "n_slices": len(specs), "n_terms": len(terms)},
        "dead_terms": [{"slice": s, "term": t} for s, t in dead],
        "n_dead_terms": len(dead),
        "per_term": sorted(per_term, key=lambda r: (r["n_props"], r["slice"], r["term"])),
        "n_multi_claimed_props": n_multi,
        "cross_claim_matrix": dict(sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))),
        "per_slice": {n: {"n_props_claimed": slice_props[n], "n_props_sole": slice_sole[n]}
                      for n in sorted(specs)},
        # Stated so a reader never infers routing intent from a count: multi-label routing is DESIGNED
        # (driver_slices_for returns every matching slice). A pair in this matrix is a routing FACT, not a
        # defect; deleting a term is a population change and therefore a Wave-R act, never a census's call.
        "note": ("multi-label routing is by design -- a cross-claim pair is a fact to review, not an error. "
                 "A dead term claims nothing in the CHUNKED corpus; it may still be live vocabulary for a "
                 "corpus that has not been chunked (60.1% of the corpus has not, per D-EI-6)."),
    }


def write_term_census(doc: dict, *, upload: bool = True) -> Path:
    """Persist a term census beside the other eval artifacts, UTC-stamped so a rerun never overwrites the
    prior baseline (the census BEFORE-overwrite lesson). Local always; <EVIDENCE_S3>/eval/ when set."""
    _OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = _OUT / f"term_census_{stamp}.json"
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    base = ev._evid_s3()
    if upload and base:
        import boto3
        b, k = ev._parse_s3(base.rstrip("/") + f"/eval/{out.name}")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=json.dumps(doc).encode("utf-8"))
    return out


def _term_census_lines(doc: dict) -> list[str]:
    """ASCII stdout summary (cp1252-safe console law)."""
    sc = doc["scope"]
    top = list(doc["cross_claim_matrix"].items())[:10]
    lines = [f"term-census: {sc['n_terms']} terms across {sc['n_slices']} slices over {sc['n_props']} props "
             f"in {sc['n_docs']} cached docs" + (f" (SAMPLE of {sc['sample']} docs)" if sc["sample"] else ""),
             f"  dead terms (claim 0 props): {doc['n_dead_terms']} of {sc['n_terms']}",
             f"  multiply-claimed props: {doc['n_multi_claimed_props']} of {sc['n_props']}"]
    for k, v in top:
        lines.append(f"  cross-claim {k}: {v} props")
    return lines


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
    for drop in d.get("population_drops") or []:
        lines.append(f"REGRESSION population {drop['slice']}: {drop['before']} -> {drop['after']} props "
                     f"(-{drop['lost']}, {drop['frac'] * 100:.1f}%)")
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


def _read_explicit_baseline(explicit: str) -> dict:
    """Read an explicit --baseline that is EITHER a local path OR an s3:// URI.

    G3b(2) -- the s3:// form is what makes the flag usable at all in the container. `configs/graphrag/eval/`
    is in `.dockerignore`, so no local archive exists in-image; and a shadow-prefix rebuild resolves its
    fallback under `<EVIDENCE_S3>/eval/`, which for `graphrag_evidence/shadow_ndw/` does not exist (that
    prefix holds only chunks/, drivers/ and the 24 top-level .jsonl). Both fallbacks therefore return None
    and the gate prints "skipping". The only working baseline for a shadow rebuild is an explicit pointer at
    the LIVE census, which lives on S3 -- so the flag has to accept one. Raises FileNotFoundError when it
    does not resolve; an EXPLICIT baseline that cannot be read is never a soft skip."""
    if str(explicit).startswith("s3://"):
        import boto3
        from botocore.exceptions import ClientError
        b, k = ev._parse_s3(str(explicit))
        try:
            body = boto3.client("s3").get_object(Bucket=b, Key=k)["Body"].read()
        except ClientError as exc:                             # pragma: no cover -- needs live S3
            raise FileNotFoundError(f"--baseline {explicit} not readable: {exc}") from exc
        return json.loads(body.decode("utf-8"))
    p = Path(explicit)
    if not p.exists():
        raise FileNotFoundError(f"--baseline {explicit} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_baseline(explicit: str | None = None) -> tuple[dict | None, str, bool]:
    """(baseline_dict | None, label, hard) — the baseline resolver the gates should use.

    `hard` is True when an EXPLICIT baseline was named and could not be read. That case must FAIL the gate,
    not skip it: a gate whose baseline silently evaporates is exactly the "armed and inert" shape G3b exists
    to remove. A missing baseline with NO explicit pointer stays a soft skip (a genuine first run).

    Priority: explicit (local path or s3:// URI) -> newest LOCAL archive -> newest S3 eval/ archive."""
    if explicit:
        try:
            return _read_explicit_baseline(explicit), str(explicit), False
        except (FileNotFoundError, OSError, ValueError) as exc:
            return None, f"{exc}", True
    local = _newest_archive()
    if local is not None:
        return json.loads(local.read_text(encoding="utf-8")), str(local), False
    remote = _newest_s3_archive()
    if remote is not None:
        return remote[0], remote[1], False
    return None, "no baseline (no --baseline, no local archive, no S3 eval/ archive)", False


def load_baseline(explicit: str | None = None) -> tuple[dict | None, str]:
    """Back-compatible 2-tuple wrapper over resolve_baseline() — same priority, same labels. Callers that
    must distinguish "no baseline at all" (soft skip) from "the baseline you NAMED is gone" (hard fail)
    should call resolve_baseline() directly."""
    doc, label, _hard = resolve_baseline(explicit)
    return doc, label


def main() -> int:  # pragma: no cover — CLI glue; census()/write() are unit-tested
    import argparse

    from leviathan.common import config
    ap = argparse.ArgumentParser(description="E1 darkness census (static, zero-LLM, $0)")
    ap.add_argument("--local-only", action="store_true", help="skip the S3 eval/ upload (still reads slices)")
    ap.add_argument("--diff", action="store_true",
                    help="W1.3 gate: re-derive the CURRENT census and diff it against a prior copy; exit "
                         "NONZERO on a stranding regression (consumed->orphan transition or retire growth). "
                         "Does NOT write/archive (a read-only gate).")
    ap.add_argument("--baseline", default=None, metavar="PATH_OR_S3URI",
                    help="--diff only: the prior e1_census.json to diff against -- a local path OR an "
                         "s3://bucket/key URI (the container has no local archive: configs/graphrag/eval/ is "
                         "in .dockerignore). Default: newest archived copy, then the newest S3 eval/ archive. "
                         "A baseline named here that cannot be read FAILS the gate; it is never skipped.")
    ap.add_argument("--term-census", action="store_true",
                    help="G8 item 1 (F13): READ-ONLY term census over the chunks/ doc-cache -- the DEAD-TERM "
                         "list (terms claiming zero props) and the CROSS-CLAIM matrix (props claimed by 2+ "
                         "slices), written to eval/term_census_<UTC>.json. Writes no slice, embeds nothing, "
                         "calls no model. This is the standing baseline the 310-dead / 1,319-multiply-claimed "
                         "screening numbers never had.")
    ap.add_argument("--term-census-sample", type=int, default=None, metavar="N",
                    help="--term-census only: screen the first N cached docs (sorted, reproducible) instead "
                         "of the full corpus. A sample is a SCREENING result, never a baseline.")
    args = ap.parse_args()
    config.load_env()

    if args.term_census:
        doc = term_census(sample=args.term_census_sample)
        path = write_term_census(doc, upload=not args.local_only)
        for line in _term_census_lines(doc):
            print(line)
        print(f"term-census -> {path}")
        return 0

    if args.diff:
        baseline, label, hard = resolve_baseline(args.baseline)
        if baseline is None and hard:                          # an EXPLICIT baseline that vanished is a failure
            print(f"census --diff: {label} -- REFUSING to pass a gate with no baseline you asked for")
            return 1
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
