"""E4 sizing report (Phase 7 P3 / W0.3) -- rank doc FAMILIES by heavy-pass recall value.

Static, zero-LLM, zero-Athena. The G16 gate has ONE hard question -- 'is the E4 heavy pass worth a
~$200-400 Anthropic top-up, and if so spent WHERE?' -- and the master plan's answer is a dollars-to-value
table: doc families ordered by how many thin/empty driver slices each would fill, each with a block-count
estimate a human multiplies by the $0.002-0.007/block Haiku-batch band (the `--fill --dry-run` band at
`evidence_batch.py` :414). This module BUILDS that table from measurement, joining two artifacts that
already exist so it adds no new spend and no new S3 traffic:

  * the E1 darkness census (`e1_census.py`) -- per-slice `n_routed_props` / `n_dag_ids` / `orphan_kind`.
    A slice a DAG id routes to but that holds < `--thin` props is a recall gap the heavy pass can close.
  * the coverage matrix (`coverage.node_source_matrix()`) -- the per-(driver-slice x source) prop/doc
    cells from routing the WHOLE 1285-doc chunks/ cache through the driver matchers. `report()` truncates
    drivers to the top-15 and applies its 500-prop flag to COMMODITY nodes ONLY, so E3 consumes the `drv`
    matrix DIRECTLY (never the .md) and applies its own per-driver-slice thinness threshold.

The recall-win target set is the plan's prioritization made precise: a slice worth filling has a DAG id
routing to it (`n_dag_ids >= 1`) AND fewer than `--thin` props -- i.e. the wired-but-inert 'keep' orphans
(0 props, wiring done, zero evidence -- the cheapest wins) UNION the thin CONSUMED slices. Retire/empty
orphans (`n_dag_ids == 0`) are excluded: no id reaches them, so filling them buys ZERO recall. A source
'would fill' a target when it contributes >= 1 prop to that slice in the current cache; a family's
`thin_slice_yield` is the count of distinct target slices it feeds, and that yield is the ranking key.

`est_blocks` is a DERIVABLE PROXY, not a quote: it is the routed-prop count, and propositions-per-block
is > 1, so it over-counts the true Haiku-batch block count -- a conservative upper bound for the dollar
band. The exact number comes from the `--fill --dry-run` at W3.1; this table sets the PRIORITY and the
ballpark. A keep-orphan whose CURRENT cache already routes props (`free_rebuild_win`) is cheaper still --
a `rebuild_slices` pass fills it for $0, no heavy pass needed.

LIST-storm discipline (the July $134 incident, project memory): the ONLY S3 read is the single chunks/
enumeration `coverage.node_source_matrix()` already performs (one LIST + 1285 cached GETs) -- this module
adds NO per-doc / per-prop S3. Everything else is arithmetic over the two in-memory artifacts.

    python -m leviathan.graphrag.e3_sizing                 # -> configs/graphrag/eval/e3_sizing.{md,json} + S3 eval/
    python -m leviathan.graphrag.e3_sizing --thin 150      # widen the thin cut
    python -m leviathan.graphrag.e3_sizing --local-only    # skip the S3 eval/ upload (still routes the cache)
"""
from __future__ import annotations

import json
from pathlib import Path

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

_OUT = ex._CFG / "eval"
_DEFAULT_THIN = 100                                        # props; a routed slice below this is a recall gap
_COST_LO, _COST_HI = 0.002, 0.007                          # $/block Haiku batch band (evidence_batch.py :414)


# ── coverage-cell accessors ───────────────────────────────────────────────────────────────────────────
def _cell_props(cell) -> int:
    """props from a coverage cell `[prop_count, {doc_keys}]` (tolerates a bare int in a synthetic stub)."""
    if isinstance(cell, (list, tuple)):
        return int(cell[0])
    return int(cell)


def _cell_docs(cell) -> set:
    """doc-key set from a coverage cell; empty when a stub carried only a count."""
    if isinstance(cell, (list, tuple)) and len(cell) > 1 and cell[1] is not None:
        return set(cell[1])
    return set()


# ── target selection (census side) ──────────────────────────────────────────────────────────────────
def is_thin(slice_rec: dict, thin: int) -> bool:
    """A slice is thin when its on-disk routed-prop count is below the threshold (task (a): pure count)."""
    return slice_rec.get("n_routed_props", 0) < thin


def keep_orphans(slices: list[dict]) -> list[dict]:
    """The wired-but-inert 'keep' slices: a DAG id routes here (`n_dag_ids >= 1`) but ZERO props on disk
    (`n_routed_props == 0`). Wiring is already done, so any evidence added is pure recall -- the cheapest
    E4 wins (census-live this is 8 slices / 17 ids). Sorted by n_dag_ids desc (more ids reached == more
    recall per fill), then name for a stable report."""
    ks = [s for s in slices if s.get("n_dag_ids", 0) >= 1 and s.get("n_routed_props", 0) == 0]
    return sorted(ks, key=lambda s: (-s.get("n_dag_ids", 0), s["slice"]))


def fillable_targets(slices: list[dict], thin: int) -> list[dict]:
    """Slices whose recall the heavy pass can actually RAISE: a DAG id routes here AND props < thin.
    = keep-orphans (0 props) UNION thin CONSUMED slices. Retire/empty orphans (`n_dag_ids == 0`) are
    excluded -- no id reaches them, so filling them buys zero recall. Each record is annotated with
    `kind` ('keep' | 'thin_consumed'). Keep-orphans sort first (highest recall per dollar), then by
    n_dag_ids desc / props asc / name."""
    out: list[dict] = []
    for s in slices:
        if s.get("n_dag_ids", 0) >= 1 and is_thin(s, thin):
            kind = "keep" if s.get("n_routed_props", 0) == 0 else "thin_consumed"
            out.append({"slice": s["slice"], "n_dag_ids": s.get("n_dag_ids", 0),
                        "n_routed_props": s.get("n_routed_props", 0), "kind": kind})
    return sorted(out, key=lambda r: (r["kind"] != "keep", -r["n_dag_ids"], r["n_routed_props"], r["slice"]))


# ── family yield (coverage side) ──────────────────────────────────────────────────────────────────────
def family_yield(targets: list[dict], drv: dict) -> list[dict]:
    """Rank doc FAMILIES (coverage `source` labels) by thin-slice yield -- how many of the `targets` each
    source would fill. A source fills a target when it contributes >= 1 prop to that slice in the coverage
    `drv` matrix (`{slice: {source: [prop_count, {doc_keys}]}}`). One record per source:
        family            -- the source label (== doc family)
        thin_slice_yield  -- count of distinct target slices it feeds (the ranking key)
        slices            -- those slice names, sorted
        est_blocks        -- total props the source routes into the targets; a DERIVABLE PROXY for the
                             heavy-pass block count (props/block > 1 -> a conservative upper bound for the
                             $ band; refine at the --fill --dry-run, W3.1)
        n_docs            -- distinct cache docs of this source that touch the targets (deduped by union)
        est_cost_lo/hi    -- est_blocks * the $0.002-0.007/block band
    Ranked by yield desc, then est_blocks desc, then family name (deterministic)."""
    fam: dict[str, dict] = {}
    for t in targets:
        cells = drv.get(t["slice"]) or {}
        for src, cell in cells.items():
            props = _cell_props(cell)
            if props <= 0:
                continue
            f = fam.setdefault(src, {"slices": set(), "est_blocks": 0, "docs": set()})
            f["slices"].add(t["slice"])
            f["est_blocks"] += props
            f["docs"] |= _cell_docs(cell)
    out: list[dict] = []
    for src, f in fam.items():
        blk = f["est_blocks"]
        out.append({"family": src, "thin_slice_yield": len(f["slices"]), "slices": sorted(f["slices"]),
                    "est_blocks": blk, "n_docs": len(f["docs"]),
                    "est_cost_lo": round(blk * _COST_LO, 2), "est_cost_hi": round(blk * _COST_HI, 2)})
    return sorted(out, key=lambda r: (-r["thin_slice_yield"], -r["est_blocks"], r["family"]))


def _keep_orphan_detail(kos: list[dict], drv: dict) -> list[dict]:
    """Annotate each keep-orphan with the sources whose CURRENT-cache props route to it, plus the total
    cache-routable prop count. `free_rebuild_win` (cache_props > 0) means a `rebuild_slices` pass fills
    the slice with ZERO E4 spend -- the on-disk slice is merely stale / never built. cache_props == 0
    means it genuinely needs new docs the heavy pass must fetch."""
    out: list[dict] = []
    for s in kos:
        cells = drv.get(s["slice"]) or {}
        fams = sorted(((src, _cell_props(c)) for src, c in cells.items() if _cell_props(c) > 0),
                      key=lambda kv: (-kv[1], kv[0]))
        cache_props = sum(p for _, p in fams)
        out.append({"slice": s["slice"], "n_dag_ids": s.get("n_dag_ids", 0),
                    "cache_routable_props": cache_props, "free_rebuild_win": cache_props > 0,
                    "families": [{"family": src, "props": p} for src, p in fams]})
    return out


# ── assembly ────────────────────────────────────────────────────────────────────────────────────────
def sizing(census_doc: dict, drv: dict, *, thin: int = _DEFAULT_THIN) -> dict:
    """Join the census `slices[]` with the coverage `drv` matrix into the ranked E4 sizing artifact.
    Pure arithmetic over the two artifacts -- no S3, no LLM. `census_doc` is the e1_census.json structure
    (or the live `ec.census()` dict, identical shape); `drv` is `coverage.node_source_matrix()[1]`."""
    slices = census_doc.get("slices", [])
    kos = keep_orphans(slices)
    targets = fillable_targets(slices, thin)
    families = family_yield(targets, drv)
    ko_detail = _keep_orphan_detail(kos, drv)
    est_total = sum(f["est_blocks"] for f in families)
    n_thin_consumed = sum(1 for t in targets if t["kind"] == "thin_consumed")
    return {
        "report": "E3_sizing",
        "basis": "e1_census.slices x coverage.node_source_matrix (static, zero-LLM)",
        "thin_threshold": thin,
        "cost_band_per_block": [_COST_LO, _COST_HI],
        "totals": {
            "n_fillable_targets": len(targets),
            "n_keep_orphans": len(kos),
            "n_thin_consumed": n_thin_consumed,
            "n_families_ranked": len(families),
            "est_blocks_total": est_total,
            "est_cost_lo": round(est_total * _COST_LO, 2),
            "est_cost_hi": round(est_total * _COST_HI, 2),
        },
        "keep_orphans": ko_detail,
        "targets": targets,
        "families": families,
    }


# ── rendering ───────────────────────────────────────────────────────────────────────────────────────
def _md(doc: dict) -> str:
    """ASCII-only markdown report (advisory convention: configs/graphrag/eval/*.md, coverage/e1_census
    precedent). Leads with the keep-orphans (cheapest wins), then the ranked doc-family table (the G16
    dollars-to-value table), then the per-target detail."""
    t = doc["totals"]
    lo, hi = doc["cost_band_per_block"]
    L = ["# E4 sizing report -- doc families ranked by heavy-pass recall value", "",
         "Static, zero-LLM join of the E1 darkness census (`e1_census`) and the coverage matrix "
         "(`coverage.node_source_matrix`). Ranks doc FAMILIES by how many thin/empty driver slices each "
         "would fill, with a rough block-count estimate for the G16 dollars-to-value decision. The EXACT "
         "spend comes from the `--fill --dry-run` at W3.1; this table sets the PRIORITY and the ballpark.", "",
         f"- **thin threshold:** < {doc['thin_threshold']} routed props",
         f"- **fillable targets** (a DAG id routes here AND props < thin): {t['n_fillable_targets']} "
         f"({t['n_keep_orphans']} keep-orphans + {t['n_thin_consumed']} thin-consumed)",
         f"- **doc families ranked:** {t['n_families_ranked']}",
         f"- **est blocks (prop-count proxy):** {t['est_blocks_total']} -> "
         f"${t['est_cost_lo']:.2f}-{t['est_cost_hi']:.2f} at the ${lo}-{hi}/block Haiku-batch band", ""]

    # ── keep-orphans: the cheapest recall wins ───────────────────────────────────
    L += ["## Keep-orphans -- the cheapest recall wins (wiring done, zero evidence)", "",
          "`free rebuild?` = the current chunks/ cache already routes props here, so a `rebuild_slices` "
          "pass fills the slice with ZERO E4 spend (the on-disk slice is stale / never built). `cache=0` "
          "means it genuinely needs new docs the heavy pass must fetch.", "",
          "| slice | #dag_ids | cache-routable props | free rebuild? | top families (props) |",
          "|---|--|--|--|---|"]
    for k in doc["keep_orphans"]:
        top = ", ".join(f"{f['family']}:{f['props']}" for f in k["families"][:3]) or "-"
        L.append(f"| {k['slice']} | {k['n_dag_ids']} | {k['cache_routable_props']} | "
                 f"{'y' if k['free_rebuild_win'] else 'n'} | {top} |")

    # ── ranked doc families (the G16 table) ──────────────────────────────────────
    L += ["", "## Doc families ranked by thin-slice yield", "",
          "| rank | family | thin-slice yield | est blocks | est $ (lo-hi) | #docs | slices filled |",
          "|--|---|--|--|--|--|---|"]
    for i, f in enumerate(doc["families"], 1):
        sl = ", ".join(f["slices"][:6]) + (" ..." if len(f["slices"]) > 6 else "")
        L.append(f"| {i} | {f['family']} | {f['thin_slice_yield']} | {f['est_blocks']} | "
                 f"${f['est_cost_lo']:.2f}-{f['est_cost_hi']:.2f} | {f['n_docs']} | {sl or '-'} |")

    # ── per-target detail ────────────────────────────────────────────────────────
    L += ["", "## Fillable targets (keep-orphans + thin consumed)", "",
          "| slice | kind | #dag_ids | #props |", "|---|--|--|--|"]
    for tg in doc["targets"]:
        L.append(f"| {tg['slice']} | {tg['kind']} | {tg['n_dag_ids']} | {tg['n_routed_props']} |")

    # ── how to read it ───────────────────────────────────────────────────────────
    L += ["", "## How to read this (G16)", "",
          "1. Fund the keep-orphans first -- `free rebuild=y` costs $0 (just re-run rebuild_slices); the "
          "`n` rows are the highest-value heavy-pass targets (ids already reach them, they just have no "
          "evidence).",
          "2. Then walk the family ranking: each row's thin-slice yield is the RECALL it buys; est blocks "
          f"x the ${lo}-{hi} band is the rough spend. Refine with `--fill --dry-run` (W3.1) before "
          "committing dollars.",
          "3. est blocks is a proxy (routed propositions; props/block > 1, so it upper-bounds the true "
          "block count) -- treat the dollar figures as a ceiling, not a quote."]
    return "\n".join(L)


def _summary_lines(doc: dict) -> list[str]:
    """Compact ASCII stdout summary (Windows cp1252 console -- no unicode). Headline numbers only."""
    t = doc["totals"]
    top = doc["families"][:5]
    return [
        f"e3-sizing: thin<{doc['thin_threshold']} -> {t['n_fillable_targets']} fillable targets "
        f"({t['n_keep_orphans']} keep-orphans + {t['n_thin_consumed']} thin-consumed) over "
        f"{t['n_families_ranked']} families",
        "top families by thin-slice yield: "
        + (", ".join(f"{f['family']}={f['thin_slice_yield']}" for f in top) or "none"),
        f"est E4 blocks ~{t['est_blocks_total']} (prop proxy) -> "
        f"${t['est_cost_lo']:.2f}-{t['est_cost_hi']:.2f} at ${_COST_LO}-{_COST_HI}/block",
    ]


def write(doc: dict, *, upload: bool = True) -> Path:
    """Write e3_sizing.md + e3_sizing.json to configs/graphrag/eval/ and -- when EVIDENCE_S3 is set and
    `upload` -- a copy of BOTH to <EVIDENCE_S3>/eval/ (mirrors e1_census.write). Returns the md path.
    Fixed filenames: the sizing report is a snapshot to hand G16, not an append log."""
    _OUT.mkdir(parents=True, exist_ok=True)
    md_path = _OUT / "e3_sizing.md"
    json_path = _OUT / "e3_sizing.json"
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
                print(f"  e3-sizing -> s3://{b}/{k}")
    return md_path


def _load_census() -> dict:
    """The census the sizing joins against: prefer the on-disk e1_census.json (the artifact W0.1 wrote --
    run e1_census FIRST, per the plan sequencing); fall back to a live `ec.census()` build when it is
    absent so a fresh checkout still works. Both are the identical structure -- census() is exactly what
    serializes to the json."""
    p = _OUT / "e1_census.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    from leviathan.graphrag import e1_census as ec
    return ec.census()


def main() -> int:  # pragma: no cover -- CLI glue; sizing()/write() are unit-tested
    import argparse

    from leviathan.common import config
    from leviathan.graphrag import coverage as cov
    ap = argparse.ArgumentParser(description="E4 sizing report (static, zero-LLM, $0)")
    ap.add_argument("--thin", type=int, default=_DEFAULT_THIN,
                    help=f"routed-prop threshold below which a routed slice is a recall gap "
                         f"(default {_DEFAULT_THIN})")
    ap.add_argument("--local-only", action="store_true", help="skip the S3 eval/ upload")
    args = ap.parse_args()
    config.load_env()
    census_doc = _load_census()
    _comm, drv, _ndocs = cov.node_source_matrix()             # the ONE chunks/ LIST -- no new S3 traffic
    doc = sizing(census_doc, drv, thin=args.thin)
    md_path = write(doc, upload=not args.local_only)
    for line in _summary_lines(doc):
        print(line)
    print(f"e3-sizing -> {md_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
