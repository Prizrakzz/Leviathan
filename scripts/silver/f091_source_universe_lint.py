#!/usr/bin/env python
"""SILVER-F091 / INV-10: the source-universe lint -- a universe claim owes a WRITTEN refusal.

Every ingest/transform family pins its slice of a source in a module-level literal: a commodity
map, an attribute tuple, a series list. INV-10 reads such a literal as a CLAIM about the source's
universe, and a claim that NARROWS the source owes a written refusal -- the
``_RECORDED_CLASS_EXCLUSIONS`` pattern (``usda_nass_annual.py:242``): documentation-with-a-test,
never control flow. This lint AST-scans the four producer roots and reports, per universe-shaped
literal, ``(family, literal_name, file, cardinality, has_refusal_companion)``.

THE ID. SILVER-F090 is the backfill-runbook package and is SUPERSEDED
(``docs/ops/SILVER_BACKFILL_READINESS_MASTER_PLAN.md``); this lint is minted SILVER-F091 so the
id collision cannot be inherited.

THE FENCE -- STATE IT OR GREEN READS AS COMPLETE
------------------------------------------------
This cut is AWS-FREE and NETWORK-FREE, so it can flag exactly ONE thing: the ABSENCE OF A WRITTEN
REFUSAL. It CANNOT detect UNDER-COVERAGE. The RED verdict INV-10 ultimately wants --
``ingested_count + len(refused) < measured_count`` -- needs ``measured_count`` from the source's
own enumeration, i.e. a network probe, and is DECLARED OUT OF SCOPE for this cut. Three
consequences, stated so nobody reads more into a green run than it holds:

  * ``covered`` means a written refusal EXISTS in the file (or in its ``configs/sources`` entry).
    It is not evidence that the refusal is complete, current, or about the same axis --
    ``usda_psd.py``'s ``_PSD_UNMAPPED_CODES`` disposes of the COMMODITY-CODE axis and says nothing
    about ``_TARGET_ATTRS``, yet both literals in that file read as covered. Per-axis binding needs
    an INV-10 registry field, not an AST scan.
  * The DOCKET is a docket, not a verdict. A family that ingests the FULL universe has nothing to
    refuse and is docketed anyway (``jobs/ingest/fetch_usda_esr.py``, remediated to all 44
    published ESR codes, sits on it). Only ``measured_count`` separates a complete ingest from an
    unwritten narrowing.
  * Coverage is per FILE and a source family is usually two files (a fetcher under ``jobs/ingest``,
    a transform under ``src/leviathan/transforms``), so a family can read covered on its transform
    and sit on the docket for its fetcher -- ``ams_gtr`` and ``eex_freight`` do exactly that. Read
    the docket by FILE, never by family.

Two mechanics that are load-bearing: sources are read ``encoding='utf-8-sig'``
(``bronze_to_silver/usda_psd.py`` and ``jobs/ingest/discover_unica_wayback.py`` carry a BOM and
plain ``ast.parse`` raises on it), and a file that does not PARSE is a REPORTED ``parse_failure``,
never a silent skip -- ``--strict`` exits 3 on one. That is the estate's only structural guard
against a producer file that has stopped compiling.

READ-ONLY + AWS-FREE. Emits reports/silver_readiness/INV10_source_universe/F091_source_universe.{json,md}.

Usage:
    python scripts/silver/f091_source_universe_lint.py            # write the report + print the docket
    python scripts/silver/f091_source_universe_lint.py --strict   # exit 3 if any source fails to parse
    python scripts/silver/f091_source_universe_lint.py --root DIR # scan another checkout (read-only)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

PACKAGE = "SILVER-F091"
INVARIANT = "INV-10"

# The producer roots: every ingest fetcher, every transform, every batch/glue task.
SCAN_ROOTS = ("src/leviathan/transforms", "jobs/ingest", "jobs/batch", "jobs/glue")
# Written refusals also live in config, keyed by FAMILY (configs/sources/cftc_cot.yaml::not_covered).
CONFIG_ROOT = "configs/sources"

OUT_DIR = _REPO / "reports" / "silver_readiness" / "INV10_source_universe"

# A universe CLAIM is a collection; 1- and 2-element literals are flags and bounds, not universes.
MIN_CARDINALITY = 3

# Single-argument wrappers that preserve the wrapped literal's membership.
_WRAPPERS = ("frozenset", "set", "list", "tuple", "dict")

UNIVERSE_NAME = re.compile(
    r"(?i)(map|codes?|slugs?|symbols?|series|commodit|attrs?|attributes?|columns?|target|universe"
    r"|accepted|allowed|metrics?|elements?|markets?|tickers?|contracts?|labels?|params?"
    r"|parameters?|sheets?|valid|known)")
REFUSAL_NAME = re.compile(
    r"(?i)(refus|exclusion|excluded?|unmapped|not_covered|uncovered|unserved|unclaimed|declined?"
    r"|omitted|denied|denylist|deny_list|blocklist|unsupported|out_of_scope|known_missing"
    r"|not_ingested|no_lane)")
# A ``*_REASONS`` enum is the reason VOCABULARY of a decline -- why a row declined, never WHICH
# source members were left out -- so it is not a refusal registry. Counting it would read
# jobs/batch/pattern_records_sweep_task.py (CHAIN_DECLINE_REASONS / CASCADE_DECLINE_REASONS) as
# covered on a refusal it does not hold, and a false GREEN is the one failure this lint cannot
# afford.
REASON_VOCABULARY = re.compile(r"(?i)_reasons?$")
# Prose that already ARGUES about the source universe. TRIAGE ONLY -- see the fence: an argument is
# not a refusal, and a full-universe ingest declares one while owing none.
UNIVERSE_DECLARATION = re.compile(r"(?i)(INV-10|source[- ]universe)")

# Filename affixes that name the JOB, not the source family.
_FAMILY_PREFIXES = ("fetch_", "backfill_", "discover_", "upload_")
_FAMILY_SUFFIXES = ("_task", "_silver", "_job")


def family_of(rel_path: str) -> str:
    """The source family a producer file belongs to, from its filename."""
    stem = Path(rel_path).stem
    for pre in _FAMILY_PREFIXES:
        if stem.startswith(pre):
            stem = stem[len(pre):]
            break
    changed = True
    while changed:
        changed = False
        for suf in _FAMILY_SUFFIXES:
            if stem.endswith(suf) and len(stem) > len(suf):
                stem = stem[: -len(suf)]
                changed = True
    return stem


# ---------------------------------------------------------------------------
# The literal shape: a module-level display whose MEMBERS (dict: whose KEYS) are all constants.
# ---------------------------------------------------------------------------
def _is_static_key(node: ast.AST | None) -> bool:
    """A statically-known dict key: a constant, or a compound key of constants/module sentinels.

    Neither widening is a nicety. ``_RECORDED_CLASS_EXCLUSIONS`` (usda_nass_annual.py:242) -- the
    estate's flagship written refusal -- keys on ``(commodity, class)`` PAIRS, and six of its
    entries carry the ``_ANY_CLASS`` sentinel in the class slot rather than a bare string. A
    constant-only key test drops the whole registry and the lint then reads that file UNCOVERED,
    which is the exact false verdict the non-vacuity pin exists to catch. A ``**`` unpacking (key
    ``None``) is still refused: it is not an enumeration.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts) and all(isinstance(e, (ast.Constant, ast.Name)) for e in node.elts)
    return False


def _cardinality(node: ast.AST, known: dict[str, int]) -> tuple[int | None, bool]:
    """(cardinality, derived) for a literal collection, or (None, False) if the node is not one."""
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        if all(isinstance(e, ast.Constant) for e in node.elts):
            return len(node.elts), False
        return None, False
    if isinstance(node, ast.Dict):
        if all(_is_static_key(k) for k in node.keys):
            return len(node.keys), False
        return None, False
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _WRAPPERS and len(node.args) == 1 and not node.keywords):
        card, _ = _cardinality(node.args[0], known)
        return card, True
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        # A comprehension carries its SOURCE literal's cardinality. Where the comprehension filters
        # (``[c for c in COLS if c.endswith(...)]``), that source count is an UPPER BOUND -- the
        # filter's width is not statically knowable. Reported anyway and deliberately: a filtered
        # comprehension over a universe literal is itself a narrowing, which is exactly what INV-10
        # is looking for.
        if len(node.generators) != 1:
            return None, False
        it = node.generators[0].iter
        if isinstance(it, ast.Name):
            return known.get(it.id), True
        if isinstance(it, ast.Attribute) and isinstance(it.value, ast.Name):
            # X.keys()/X.values() style -- the iterated name still carries the cardinality.
            return known.get(it.value.id), True
        if (isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute)
                and isinstance(it.func.value, ast.Name)):
            return known.get(it.func.value.id), True
        card, _ = _cardinality(it, known)
        return card, True
    return None, False


def _assigned_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def scan_source(text: str, rel_path: str) -> dict:
    """Universe-shaped literals + written refusals in one module. Raises SyntaxError on bad source."""
    tree = ast.parse(text)
    family = family_of(rel_path)
    declares_universe = bool(UNIVERSE_DECLARATION.search(text))
    known: dict[str, int] = {}
    records: list[dict] = []
    refusals: list[dict] = []
    derived = 0
    literals = 0
    for node in tree.body:
        names = _assigned_names(node)
        if not names:
            continue
        value = node.value
        if value is None:
            continue
        card, is_derived = _cardinality(value, known)
        if card is None:
            continue
        for name in names:
            known[name] = card
            # The RAW census counts every module-level collection of universe SHAPE (>= 3 members),
            # whatever it is named; ``records`` below adds the NAME filter on top of it.
            if card >= MIN_CARDINALITY:
                literals += 1
                if is_derived:
                    derived += 1
            # A written refusal counts at any NON-ZERO cardinality: a one-entry exclusion registry
            # is still a written refusal (the MIN_CARDINALITY floor applies to universe CLAIMS
            # only) -- but an EMPTY one is a stub, not a refusal, and counting it would make the
            # hollow `_REFUSED_X = {}` the cheapest ticket off the docket: a false GREEN, the one
            # failure this lint cannot afford (Lane-6 review, major 2 -- proven by construction).
            if card >= 1 and REFUSAL_NAME.search(name) and not REASON_VOCABULARY.search(name):
                refusals.append({"file": rel_path, "name": name, "line": node.lineno,
                                 "cardinality": card})
            if card >= MIN_CARDINALITY and UNIVERSE_NAME.search(name):
                records.append({
                    "family": family,
                    "name": name,
                    "file": rel_path,
                    "line": node.lineno,
                    "cardinality": card,
                    "literal_kind": type(value).__name__.lower(),
                    "universe_declaration": declares_universe,
                    "has_refusal_companion": False,   # filled in by the file-level join
                    "refusal_companion": None,
                })
    return {"records": records, "refusals": refusals, "module_level_literals": literals,
            "derived_collections": derived}


# ---------------------------------------------------------------------------
# The tree scan.
# ---------------------------------------------------------------------------
def _iter_sources(root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in SCAN_ROOTS:
        base = root / rel
        if base.exists():
            out.extend(sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts))
    return out


def _config_refusals(root: Path) -> dict[str, str]:
    """family -> 'configs/sources/<f>.yaml::<key>:' for config-side written refusals."""
    found: dict[str, str] = {}
    base = root / CONFIG_ROOT
    if not base.exists():
        return found
    for p in sorted(base.glob("*.y*ml")):
        try:
            text = p.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            # UnicodeDecodeError caught HERE, symmetrically with the source path's parse_failures:
            # a mis-encoded config must degrade to "no config-side refusal found for this family",
            # never crash the whole lint (Lane-6 review minor).
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key = stripped.split(":", 1)[0].lstrip("- ").strip()
            if key and REFUSAL_NAME.search(key):
                rel = p.relative_to(root).as_posix()
                found.setdefault(p.stem, f"{rel}::{key}:")
                break
    return found


def scan_tree(root: Path | None = None) -> dict:
    root = Path(root) if root is not None else _REPO
    records: list[dict] = []
    refusals: list[dict] = []
    parse_failures: list[dict] = []
    files_scanned = 0
    files_parsed = 0
    module_level_literals = 0
    derived_collections = 0
    # rel path -> module-level collection literals of universe SHAPE, so a caller can re-derive the
    # raw census over any subset of the tree (the pin re-derives it over the COMMITTED files).
    literal_counts_by_file: dict[str, int] = {}

    for path in _iter_sources(root):
        rel = path.relative_to(root).as_posix()
        files_scanned += 1
        # utf-8-sig: usda_psd.py and discover_unica_wayback.py carry a BOM.
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            parse_failures.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            scanned = scan_source(text, rel)
        except SyntaxError as exc:
            # REPORTED, never skipped: a producer that no longer compiles is a finding.
            parse_failures.append({
                "file": rel,
                "error": f"SyntaxError: {exc.msg} (line {exc.lineno}, col {exc.offset})"})
            continue
        files_parsed += 1
        records.extend(scanned["records"])
        refusals.extend(scanned["refusals"])
        module_level_literals += scanned["module_level_literals"]
        derived_collections += scanned["derived_collections"]
        if scanned["module_level_literals"]:
            literal_counts_by_file[rel] = scanned["module_level_literals"]

    config_refusals = _config_refusals(root)

    by_file: dict[str, str] = {}
    for r in refusals:
        by_file.setdefault(
            r["file"], f"{r['file']}::{r['name']} (line {r['line']}, {r['cardinality']} entries)")
    for rec in records:
        companion = by_file.get(rec["file"]) or config_refusals.get(family_of(rec["file"]))
        rec["has_refusal_companion"] = companion is not None
        rec["refusal_companion"] = companion

    universe_files = sorted({r["file"] for r in records})
    covered_files = sorted({r["file"] for r in records if r["has_refusal_companion"]})
    docket = sorted(set(universe_files) - set(covered_files))
    docket_literals = [r for r in records if not r["has_refusal_companion"]]
    docket_declaring = sorted({r["file"] for r in docket_literals if r["universe_declaration"]})

    return {
        "meta": {
            "package": PACKAGE,
            "invariant": INVARIANT,
            "fence": (
                "FENCE (INV-10 first cut): AWS-FREE and NETWORK-FREE. Flags only the ABSENCE OF A "
                "WRITTEN REFUSAL. It CANNOT detect under-coverage: the RED verdict (ingested + "
                "refused < measured) needs measured_count from a source probe and is DECLARED OUT "
                "OF SCOPE for this cut. A green run is NOT a coverage claim."),
            "out_of_scope": [
                "measured_count (the source's own enumeration) -- needs a network probe",
                "the RED verdict: ingested_count + len(refused) < measured_count",
                "AMBER (measured_at staleness) -- there is no measured_at without a probe",
                "INTEGRITY (a refusal reason that is a TODO marker) -- reason TEXT is not read here",
                "AXIS-LEVEL coverage: has_refusal_companion is a FILE-level fact",
                "FAMILY SPLIT: coverage is per file, so a family can be covered on its transform "
                "and docketed on its fetcher",
            ],
            "files_scanned": files_scanned,
            "files_parsed": files_parsed,
            "parse_failures": parse_failures,
            "census": {
                "module_level_literals": module_level_literals,
                "files_with_literals": len(literal_counts_by_file),
                "universe_shaped_literals": len(records),
                "files_with_universe_literals": len(universe_files),
                "derived_collections": derived_collections,
            },
            "coverage": {
                "covered_files": len(covered_files),
                "docket_files": len(docket),
                "docket_literals": len(docket_literals),
                "docket_with_universe_declaration": len(docket_declaring),
                "refusal_registries_in_code": len(by_file),
                "refusal_registries_in_config": len(config_refusals),
            },
        },
        "records": records,
        "literal_counts_by_file": literal_counts_by_file,
        "refusal_registries": sorted(refusals, key=lambda r: (r["file"], r["line"])),
        "refusal_registries_config": sorted(config_refusals.values()),
        "docket": docket,
        "docket_with_universe_declaration": docket_declaring,
    }


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------
def _render_md(result: dict) -> str:
    meta = result["meta"]
    cen, cov = meta["census"], meta["coverage"]
    lines = [
        f"# {PACKAGE} / {INVARIANT} -- source-universe lint (first cut)",
        "",
        f"Scanned **{meta['files_scanned']}** producer sources ({', '.join(SCAN_ROOTS)}); "
        f"parsed **{meta['files_parsed']}**; parse failures: **{len(meta['parse_failures'])}**.",
        "",
        f"Census: **{cen['universe_shaped_literals']}** universe-shaped literals across "
        f"**{cen['files_with_universe_literals']}** files "
        f"(of {cen['module_level_literals']} module-level literals in "
        f"{cen['files_with_literals']} files).",
        "",
        f"Coverage: **{cov['covered_files']}** files carry a written refusal; the DOCKET is "
        f"**{cov['docket_files']}** files / **{cov['docket_literals']}** literals.",
        "",
        "> " + meta["fence"],
        "",
        "## Written refusals in the estate today",
        "",
        "| file | registry | entries |",
        "|---|---|--:|",
    ]
    for r in result["refusal_registries"]:
        lines.append(f"| `{r['file']}` | `{r['name']}` (line {r['line']}) | {r['cardinality']} |")
    for c in result["refusal_registries_config"]:
        lines.append(f"| `{c.split('::')[0]}` | `{c.split('::')[1]}` (config) | -- |")
    lines += [
        "",
        "## The docket -- universe literals with no written refusal",
        "",
        "REPORTED, not failed. Day one is a docket: the lint cannot tell a family that ingests the "
        "FULL universe (nothing to refuse) from one that narrows silently -- that separation needs "
        "the `measured_count` probe declared out of scope above.",
        "",
        "| family | file | literal | cardinality | prose declares a universe |",
        "|---|---|---|--:|:--:|",
    ]
    for r in sorted(result["records"], key=lambda x: (x["file"], x["line"])):
        if r["has_refusal_companion"]:
            continue
        lines.append(
            f"| {r['family']} | `{r['file']}` | `{r['name']}` | {r['cardinality']} | "
            f"{'yes' if r['universe_declaration'] else 'no'} |")
    lines += ["", "## Covered files (a refusal EXISTS -- not a coverage claim)", ""]
    for f in sorted({r["file"] for r in result["records"] if r["has_refusal_companion"]}):
        companion = next(r["refusal_companion"] for r in result["records"] if r["file"] == f
                         and r["has_refusal_companion"])
        lines.append(f"- `{f}` -- {companion}")
    if meta["parse_failures"]:
        lines += ["", "## PARSE FAILURES (a source that does not compile is not linted)", ""]
        for p in meta["parse_failures"]:
            lines.append(f"- `{p['file']}` -- {p['error']}")
    lines.append("")
    return "\n".join(lines)


def run(root: Path | None = None, strict: bool = False, write: bool = True) -> int:
    result = scan_tree(root)
    meta = result["meta"]
    cen, cov = meta["census"], meta["coverage"]
    if write:
        # The report lands in the SCANNED tree, not in this module's repo: OUT_DIR is _REPO-relative
        # only as a default, so `run(root=<other-worktree>, write=True)` does not deposit that
        # tree's report here (Lane-6 review minor).
        out_dir = ((Path(root) if root is not None else _REPO)
                   / "reports" / "silver_readiness" / "INV10_source_universe")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "F091_source_universe.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "F091_source_universe.md").write_text(_render_md(result), encoding="utf-8")

    print(f"{PACKAGE}/{INVARIANT}: {cen['universe_shaped_literals']} universe-shaped literals in "
          f"{cen['files_with_universe_literals']} files; {cov['covered_files']} covered, "
          f"docket {cov['docket_files']} files / {cov['docket_literals']} literals; "
          f"{cov['refusal_registries_in_code']} code + {cov['refusal_registries_in_config']} config "
          f"refusal registries")
    print("FENCE: absence-of-refusal only; under-coverage (RED) needs a measured_count probe "
          "and is OUT OF SCOPE.")
    for f in result["docket"]:
        print(f"  docket: {f}")
    if meta["parse_failures"]:
        print(f"PARSE FAILURES ({len(meta['parse_failures'])}) -- these sources were NOT linted:")
        for p in meta["parse_failures"]:
            print(f"  - {p['file']}: {p['error']}")
        if strict:
            return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SILVER-F091 / INV-10 source-universe lint")
    ap.add_argument("--strict", action="store_true",
                    help="exit 3 if any scanned source fails to parse (the docket never fails)")
    ap.add_argument("--root", default=None,
                    help="scan another checkout instead of this one (read-only)")
    ap.add_argument("--no-write", action="store_true", help="print only; write no report")
    args = ap.parse_args()
    return run(root=Path(args.root) if args.root else None, strict=args.strict,
               write=not args.no_write)


if __name__ == "__main__":
    raise SystemExit(main())
