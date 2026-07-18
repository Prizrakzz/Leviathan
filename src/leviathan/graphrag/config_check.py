"""GraphRAG Phase 1 config validators — the W3/W5 exit gate, as code.

Public code; it reads the git-ignored ``configs/graphrag/`` IP at runtime. Two checks:

  * **vocab linter** — no surface form is both a node and an edge; arbitration targets resolve
    to real roles; aliases point at real canonical nodes; node/edge name hygiene.
  * **node_silver_map resolver** — every metric's (table, column) actually exists in the silver
    Athena DDLs (``sql/athena/ddl/``), so silver-confirmation (§4.3) isn't hand-wave.

    python -m leviathan.graphrag.config_check        # exits non-zero on any failure
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_CFG = _REPO / "configs" / "graphrag"
_DDL = _REPO / "sql" / "athena" / "ddl"


def _load(name: str) -> dict:
    return yaml.safe_load((_CFG / name).read_text(encoding="utf-8"))


def lint_vocab() -> list[str]:
    v = _load("entity_vocabulary.yaml")
    errs: list[str] = []
    node_terms = {t for terms in v.get("nodes", {}).values() if terms for t in terms}
    edge_terms = set(v.get("edges", {}).keys())

    both = node_terms & edge_terms
    if both:
        errs.append(f"terms are BOTH node and edge (arbitration violation): {sorted(both)}")

    for surface, rule in (v.get("arbitration") or {}).items():
        role, canon = rule.get("role"), rule.get("canonical")
        if role not in ("node", "edge"):
            errs.append(f"arbitration[{surface}]: role must be node|edge, got {role!r}")
        if role == "node" and canon not in node_terms:
            errs.append(f"arbitration[{surface}] → node {canon!r} not in any node list")
        if role == "edge" and canon not in edge_terms:
            errs.append(f"arbitration[{surface}] → edge {canon!r} not in edges")

    for canon, al in (v.get("aliases") or {}).items():
        if canon not in node_terms:
            errs.append(f"aliases: canonical {canon!r} is not a defined node")
        # An alias surface form must NOT itself be a node term — that's an identity collision
        # (e.g. `canola` listed as a commodity node AND an alias of `rapeseed`; or a distinct
        # sub-region listed as an alias of its parent). Such a term has two canonical identities.
        for surface in (al or []):
            if surface in node_terms and surface != canon:
                errs.append(f"aliases[{canon}]: {surface!r} is also a node term "
                            f"(alias collides with a canonical node — pick one identity)")

    for vn, rule in (v.get("verb_normalization") or {}).items():
        if rule.get("edge") not in edge_terms:
            errs.append(f"verb_normalization[{vn}] → edge {rule.get('edge')!r} not in edges")

    return errs


def check_node_silver_map() -> list[str]:
    m = _load("node_silver_map.yaml")
    errs: list[str] = []
    for metric, spec in m.get("metrics", {}).items():
        if spec.get("derived"):
            continue
        table, col = spec.get("table"), spec.get("column")
        ddl = _DDL / f"{table}.sql"
        if not ddl.exists():
            errs.append(f"metric {metric}: DDL {table}.sql not found")
            continue
        text = ddl.read_text(encoding="utf-8")
        if not re.search(rf"\b{re.escape(col)}\b", text):
            errs.append(f"metric {metric}: column {col!r} not in {table}.sql")
        aoc = spec.get("as_of_column")
        if spec.get("as_of_supported") and aoc and not re.search(rf"\b{re.escape(aoc)}\b", text):
            errs.append(f"metric {metric}: as_of_column {aoc!r} not in {table}.sql")
    return errs


def check_hierarchy() -> list[str]:
    """Commodity hierarchy integrity — every contract maps to a real node, full slug coverage,
    group/complex members real, legacy canonicals still resolve. Delegates to the resolver itself
    so config-lint and the runtime expander agree by construction."""
    from leviathan.graphrag.hierarchy import coverage_check
    return coverage_check()


def check_geography() -> list[str]:
    """Geography routing index integrity (5.8) — every curated contract/driver/region/origin id is real.
    Delegates to the resolver so lint and the runtime router agree by construction."""
    from leviathan.graphrag.geography import check_geography as _cg
    return _cg()


def check_display_names() -> list[str]:
    """Display-name registry integrity (6.1) — every convergence regime has a curated label (so no raw
    internal id can leak to the reader). Delegates to the resolver so lint and the runtime sanitizer
    agree by construction."""
    from leviathan.graphrag.display import check_display_names as _cd
    return _cd()


def check_display_vocab() -> list[str]:
    """Display-vocab lint (P9-A) — no curated regime label / _dir_suffix output carries a banned mood word
    (bullish/bearish). The only guard on the gitignored display_names.yaml after the mentor-voice relabel."""
    from leviathan.graphrag.display import check_display_vocab as _cv
    return _cv()


def check_cascade_map() -> list[str]:
    """P9-B: every ACTIVE cascade_map ref maps to a real table.metric; period_type in the enum; scale numeric
    and narrate_unit set when scale != 1; and NO active row points at a known-uncertified/empty table.
    load_map() already drops `deferred: true` rows, so any table seen here is meant to be live — an ESR row
    that lint-passes on table+metric existence would still return record_silent on an empty source; this
    empty-set check is the offline half of the guard, the Phase-D live probe is the runtime half."""
    from leviathan.graphrag.numbers.cascade import load_map
    from leviathan.graphrag.numbers.cascade_census import UNCERTIFIED_TABLES as _uncertified
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    errs: list[str] = []
    for ref, row in (load_map() or {}).items():
        ts = None
        try:
            ts = reg.get(row.get("table"))
        except Exception:  # noqa: BLE001
            errs.append(f"cascade_map {ref!r}: unknown table {row.get('table')!r}")
        if row.get("table") in _uncertified:
            errs.append(f"cascade_map {ref!r}: table {row.get('table')!r} is uncertified/empty "
                        f"(0 rows in the source certification) — mark `deferred: true` until a live probe passes")
        if ts and row.get("metric") not in ts.metrics:
            errs.append(f"cascade_map {ref!r}: metric {row.get('metric')!r} not in {row.get('table')!r}")
        if row.get("period_type") not in ("date", "marketing_year", "year_month"):
            errs.append(f"cascade_map {ref!r}: bad period_type {row.get('period_type')!r}")
        if float(row.get("scale", 1) or 1) != 1 and not row.get("narrate_unit"):
            errs.append(f"cascade_map {ref!r}: scale != 1 requires narrate_unit")
        if row.get("country_rule") not in (None, "primary", "none", "region"):
            errs.append(f"cascade_map {ref!r}: bad country_rule {row.get('country_rule')!r}")
    errs += _check_region_map(reg)
    return errs


def _check_region_map(reg) -> list[str]:
    """RF-2 region_map lint: (a) every resolve entry carries a non-empty country and any currency points at
    a REAL silver_fred_fx column (<currency>_usd); (b) no token sits in BOTH resolve and unresolved; (c) the
    census — every region token on a driver whose ACTIVE map row is country_rule=region either resolves or
    is explicitly unresolved (the E4 alias/waiver census precedent: unmapped tokens fail the build, they
    never silently mislabel a country at serve time)."""
    from leviathan.graphrag.numbers.cascade import load_map, load_region_map
    errs: list[str] = []
    rmap = load_region_map() or {}
    resolve = rmap.get("resolve") or {}
    unresolved = set(rmap.get("unresolved") or [])
    fx_metrics: set = set()
    try:
        fx_metrics = set(reg.get("silver_fred_fx").metrics)
    except Exception:  # noqa: BLE001 — surfaced below only if a currency is actually declared
        pass
    for tok, entry in resolve.items():
        country = (entry or {}).get("country")
        if not country or not isinstance(country, str):
            errs.append(f"region_map resolve[{tok!r}]: missing/empty country")
        cur = (entry or {}).get("currency")
        if cur and f"{cur}_usd" not in fx_metrics:
            errs.append(f"region_map resolve[{tok!r}]: currency {cur!r} -> {cur}_usd is not a "
                        f"silver_fred_fx column")
        if tok in unresolved:
            errs.append(f"region_map: token {tok!r} is in BOTH resolve and unresolved")
    region_ruled = {ref for ref, row in (load_map() or {}).items()
                    if (row or {}).get("country_rule") == "region"}
    if not region_ruled:
        return errs
    from leviathan.causal import blurb as bl
    from leviathan.causal import schema as cs
    for p in sorted(bl._CAUSAL_DIR.glob("*.yaml")):
        c = cs.load(p)
        for d in c.drivers:
            if d.silver_ref in region_ruled and d.region and d.region not in resolve \
                    and d.region not in unresolved:
                errs.append(f"region_map census: {c.contract}/{d.id} region {d.region!r} "
                            f"(ref {d.silver_ref!r}) neither resolves nor is listed unresolved")
    return errs


def check_complex_map() -> list[str]:
    """RV-W0: reroute-v2 complex_map integrity (mirrors check_cascade_map). Validates EVERY authored
    pair (material or not -- iter_all_pairs, so the loader's inert-drop can't hide a malformed row):

      1. both `pair` slugs are LOADED contracts (graph.contracts), and each `sideX.contract` matches
         its ordered slot -- a shorthand/typo fails closed here rather than silently never firing.
      2. each `sideX.ref` names a real (non-deferred) cascade_map ref -> table/metric/scale/period
         inherit and the metric-in-registry lint covers a v2 leg for free.
      3. SAME-PSD-CODE ban (B1): code(legA) != code(legB) across the 13 PSD commodity_code sheets
         (inverted usda_psd._PSD_COMMODITY_TO_SLUGS) -- two slugs under one code resolve to a
         byte-identical su_ratio row => a vacuous fork. HARD error. A leg with NO PSD sheet is also an
         error (it can never carry a su_ratio-World row).
      4. `materiality_tier` in {material, contextual, excluded}; `direction` in {opposing, co_moving}.
      5. `country_rule` == "world" on BOTH sides -- the only accepted v1 value (Recipe-B World total-use).
      6. `shared_event` corresponds to a real driver id present in the DAG OR a real inter_commodity
         relation between the two contracts (resolved BARE->slug, engine F2) -- so the mechanism stays
         curated in the causal YAML. A naive slug==slug edge match is unsatisfiable for 6 of 7 pairs
         (edge targets are bare names), hence the resolver on both sides of the join.
    """
    from leviathan.graphrag import complex_map as xcm
    from leviathan.graphrag.graph import CausalGraph
    from leviathan.graphrag.numbers.cascade import load_map
    from leviathan.transforms.bronze_to_silver.usda_psd import _PSD_COMMODITY_TO_SLUGS

    errs: list[str] = []
    try:
        pairs = xcm.iter_all_pairs()
    except Exception as exc:  # noqa: BLE001 — a malformed pair shape must fail the build, not crash lint silently
        return [f"complex_map: failed to parse ({exc})"]
    graph = CausalGraph.load()
    loaded = frozenset(graph.contracts.keys())
    refs = load_map() or {}
    slug_to_code = {s: code for code, slugs in _PSD_COMMODITY_TO_SLUGS.items() for s in slugs}
    all_driver_ids = {d.id for c in graph.contracts.values() for d in c.drivers}

    def _edge_between(a: str, b: str) -> bool:
        for src, dst in ((a, b), (b, a)):
            c = graph.contracts.get(src)
            if not c:
                continue
            for e in c.inter_commodity:
                if resolve := xcm.resolve_bare_commodity(e.driver_commodity, loaded):
                    if resolve == dst:
                        return True
        return False

    for p in pairs:
        pid = p.id or "<no-id>"
        a, b = p.pair
        # 1. both loaded + side/slot consistency
        for slug in (a, b):
            if slug not in loaded:
                errs.append(f"complex_map {pid!r}: pair slug {slug!r} is not a loaded contract")
        if (p.side_a.get("contract") or a) != a:
            errs.append(f"complex_map {pid!r}: sideA.contract {p.side_a.get('contract')!r} != pair[0] {a!r}")
        if (p.side_b.get("contract") or b) != b:
            errs.append(f"complex_map {pid!r}: sideB.contract {p.side_b.get('contract')!r} != pair[1] {b!r}")
        # 2. refs resolve by name
        for side, sd in (("sideA", p.side_a), ("sideB", p.side_b)):
            ref = sd.get("ref")
            if ref not in refs:
                errs.append(f"complex_map {pid!r}: {side}.ref {ref!r} is not a live cascade_map ref")
        # 3. same-PSD-code ban (B1)
        ca, cb = slug_to_code.get(a), slug_to_code.get(b)
        if ca is None:
            errs.append(f"complex_map {pid!r}: leg {a!r} maps to no PSD commodity_code (no su_ratio sheet)")
        if cb is None:
            errs.append(f"complex_map {pid!r}: leg {b!r} maps to no PSD commodity_code (no su_ratio sheet)")
        if ca is not None and cb is not None and ca == cb:
            errs.append(f"complex_map {pid!r}: same-PSD-code ban (B1) -- {a!r} and {b!r} both map to "
                        f"code {ca} => byte-identical su_ratio row, vacuous fork")
        # 4. enums
        if p.materiality_tier not in ("material", "contextual", "excluded"):
            errs.append(f"complex_map {pid!r}: bad materiality_tier {p.materiality_tier!r}")
        if p.direction not in ("opposing", "co_moving"):
            errs.append(f"complex_map {pid!r}: bad direction {p.direction!r} (opposing|co_moving)")
        # 5. country_rule world-only (v1)
        for side, sd in (("sideA", p.side_a), ("sideB", p.side_b)):
            if sd.get("country_rule") != "world":
                errs.append(f"complex_map {pid!r}: {side}.country_rule {sd.get('country_rule')!r} "
                            f"-- only 'world' is accepted for v1")
        # 6. shared_event resolvable (driver id OR curated inter_commodity edge between the two contracts)
        if p.shared_event not in all_driver_ids and not _edge_between(a, b):
            errs.append(f"complex_map {pid!r}: shared_event {p.shared_event!r} is neither a DAG driver id "
                        f"nor a curated inter_commodity relation between {a!r} and {b!r}")
    return errs


def check_pin_realizability() -> list[str]:
    """P9-W2.3: PER-QUERY (never per-contract) cascade-pin lint. Every v4 eval query pinning
    `cascade_fired` asserts an OUTCOME; this proves the pin matches the query's own realizability BEFORE an
    eval run can waste itself on it. Per-query is load-bearing: a contract rollup would compute
    `can_any_leg_fire(soybean_oil_cbot)=TRUE` and FAIL to flag q6 -- the biodiesel QUESTION grounds only
    unmapped flag/z refs + a driverless consumption leg, so its per-query realizability is FALSE even though
    the contract CAN fire on export/stock/oni/fx. Reuses cascade_census.query_realizable (the census's own
    topology, so lint and census agree by construction; NO pg -- this is the pure map/DAG half):

      * `cascade_fired:true` while per-query realizability is FALSE -> ERROR (the q6 false-positive class),
      * `cascade_fired:false` while the query's OWN legs structurally CAN fire -> ERROR (a stale-negative pin;
        pins follow census truth in BOTH directions).

    Every cascade_fired-pinned query MUST declare `cascade_drivers: [...]` (the driver ids the question
    grounds). FAIL-CLOSED: with no declaration query_realizable returns None and the
    lint ERRORS -- the contract-rollup fallback it replaced was exactly the granularity hole that would
    have greenlit q6's original undeclared pin (soybean_oil_cbot rolls up TRUE via export/stock/oni/fx)."""
    from leviathan.graphrag.numbers import cascade_census as cc
    doc = _load("eval_queries_v4_cascade.yaml") or {}
    errs: list[str] = []
    for q in (doc.get("queries") or []):
        exp = q.get("expect") or {}
        if "cascade_fired" not in exp:
            continue
        pin = bool(exp["cascade_fired"])
        realizable = cc.query_realizable(q)
        if realizable is None:
            errs.append(f"pin_realizability {q.get('id')!r} ({q.get('contract')}): pins cascade_fired but "
                        f"declares no `cascade_drivers` -- the per-query grounded set is unknown and the "
                        f"contract rollup is not a substitute (fail-closed); declare the driver ids the "
                        f"question grounds")
        elif pin and not realizable:
            errs.append(f"pin_realizability {q.get('id')!r} ({q.get('contract')}): pins cascade_fired:true "
                        f"but no grounded leg is realizable per-query (unmapped refs / unresolved regions) "
                        f"-- re-pin to false + a qualitative-mechanism assertion")
        elif (not pin) and realizable:
            errs.append(f"pin_realizability {q.get('id')!r} ({q.get('contract')}): pins cascade_fired:false "
                        f"but the query's own legs structurally CAN fire (stale-negative pin) -- re-pin to true")
    return errs


def check_driver_slices() -> list[str]:
    """Driver-slice darkness lint (7-P2 W2) — every causal DAG driver id resolves to an evidence slice or
    carries a waiver (hard), and no id is double-owned (hard). Topical-token drift is a separate advisory
    (driver_slice_alias_warnings, printed as WARN, never fatal). Delegates to the evidence resolver so lint
    and the runtime slice router agree by construction."""
    from leviathan.graphrag.evidence import check_driver_slices as _cds
    return _cds()


def check_edge_blurbs() -> list[str]:
    """Blurb word-cap lint (P8-P1 W1.5) — a set blurb must be <=MAX_WORDS (hard; over-length means either a
    truncated draft or hand-edit drift). MISSING blurbs are a WARN, not an error: the rollout is gated/partial
    by design (over-limit drafts are skipped at apply and fall back to mechanism on hover)."""
    from leviathan.causal import blurb as bl
    from leviathan.causal import schema as cs
    errs = []
    for p in sorted(bl._CAUSAL_DIR.glob("*.yaml")):
        c = cs.load(p)
        for d in c.drivers:
            if d.blurb and len(d.blurb.split()) > bl.MAX_WORDS:
                errs.append(f"{c.contract}/{d.id}: blurb is {len(d.blurb.split())} words (>{bl.MAX_WORDS})")
        for e in c.inter_commodity:
            if e.blurb and len(e.blurb.split()) > bl.MAX_WORDS:
                errs.append(f"{c.contract}->{e.driver_commodity}: blurb is {len(e.blurb.split())} words "
                            f"(>{bl.MAX_WORDS})")
    return errs


def blurb_presence_warnings() -> list[str]:
    """Advisory: edges with mechanism but no blurb (the hover falls back to mechanism — works, just longer)."""
    from leviathan.causal import blurb as bl
    return [f"{t['contract']}/{t['id']} ({t['kind']})" for t in bl._targets()]


def main() -> int:
    failures = 0
    for label, errs in (("vocab", lint_vocab()), ("node_silver_map", check_node_silver_map()),
                        ("hierarchy", check_hierarchy()), ("geography", check_geography()),
                        ("display_names", check_display_names()),
                        ("display_vocab", check_display_vocab()),
                        ("cascade_map", check_cascade_map()),
                        ("complex_map", check_complex_map()),
                        ("pin_realizability", check_pin_realizability()),
                        ("driver_slices", check_driver_slices()),
                        ("edge_blurbs", check_edge_blurbs())):
        if errs:
            failures += len(errs)
            print(f"FAIL {label}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"PASS {label}")
    # Advisory (non-fatal): topical-token near-misses a human reviews but that never fail the build.
    from leviathan.graphrag.evidence import bare_name_warnings, driver_slice_alias_warnings
    warns = driver_slice_alias_warnings()
    if warns:
        print(f"WARN driver_slices ({len(warns)} topical near-misses — human-reviewed aliases, non-fatal):")
        for w in warns:
            print(f"  - {w}")
    # Advisory (non-fatal): a commodity node whose matcher misses its own bare head-commodity word (the C1
    # coffee-bug class) — caught by lint, not by a billed shadow rebuild. Fix = one extra_terms line.
    bare = bare_name_warnings()
    if bare:
        print(f"WARN bare_name ({len(bare)} nodes miss their own head-commodity word -- non-fatal):")
        for w in bare:
            print(f"  - {w}")
    # Advisory (non-fatal): un-blurbed edges — hover falls back to mechanism; count-only to keep output sane.
    missing_blurbs = blurb_presence_warnings()
    if missing_blurbs:
        print(f"WARN edge_blurbs ({len(missing_blurbs)} edges have mechanism but no blurb -- hover falls "
              "back to mechanism, non-fatal)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
