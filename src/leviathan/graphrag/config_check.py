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

# PRICE_OBSERVABILITY W0.2: tables-of-interest for the register fence lint. These live HERE (no registry-schema
# creep). PRICE_TABLES/POSITIONING_TABLES must never feed an engine (R4/R9). silver_wasde is NOT a price table --
# it carries fundamentals cascade legitimately consumes; the avg_farm_price price-leg is a section-6 follow-on,
# fenced at the metric level, not here.
PRICE_TABLES = ("silver_pink_sheet",)
POSITIONING_TABLES = ("silver_cot",)
# The curated avg_farm_price coverage set. PRICE_OBSERVABILITY A3 re-whitelist (2026-07-22): after the
# silver_wasde rebuild + promote (canonical CERTIFIED, 373 releases 1995+, pg parity PASS) the probes resolved
# the provisional set to the 10 commodities with a live, unit-clean farm/market price. R1 BINDS -- the metric's
# unit_overrides keys must EQUAL this set exactly (drift either way fails the build), so this set + the
# tables.yaml unit_overrides map move together. (soybean_oil/soybean_meal are Decatur US MARKET prices, carried
# under the same metric with a market-price desc; cotton spans the u_s_cotton -> united_states region split.)
_FARM_PRICE_COMMODITIES: frozenset = frozenset({"corn", "wheat", "sorghum", "oats", "barley", "rice",
                                                "cotton", "soybeans", "soybean_oil", "soybean_meal"})
# NONE-tier decline names (R5 census). Every one must own a decline template that passes register_leaks clean.
# A3 (2026-07-22): us_farm_price is REMOVED -- avg_farm_price is re-whitelisted and live, so a US farm-price ask
# is now SERVED, not declined (its us_farm_price template + _PRICE_DECLINE_PATTERNS entry retired in agent.py).
_NONE_TIER_DECLINE = ("robusta", "white_sugar", "french_wheat_matif", "french_maize_matif",
                      "jse_white_maize", "jse_yellow_maize", "rapeseed_meal_zce")
# R2/R8 detector probes: one banned sentence per term + per class rule (must FLAG), the Lane B windowed probes,
# and the ag-collision must-NOT-flag battery. Green in W0 by construction -- this tests the detector, not tables.
_DETECTOR_FLAG = (
    "raise the price target", "take-profit here", "a stop-loss below", "go long soyoil", "buy the dip",
    "fade the rally", "worth fading", "the spread looks cheap", "a relative value trade", "undervalued",
    "overvalued", "mispriced", "dislocated", "overdone", "overshot", "at attractive levels", "fair value",
    "it screens rich", "squeeze potential", "a pain trade", "forced liquidation", "capitulation",
    "shorts would need to chase", "a crowded long", "one-sided positioning", "offside", "a coiled spring",
    "dry powder", "stretched positioning", "if funds cover",
    "the discount has room to normalize", "spreads this wide rarely persist",
    "due for a correction", "mean reversion favors the discount narrowing",
    "the premium should converge next quarter", "this premium is unsustainable")
_DETECTOR_LANE_B = ("Is palm cheap vs soyoil?", "positioning looks stretched", "the book is crowded")
_DETECTOR_CLEAN = (
    "the spread narrowed in 2016", "the premium averaged $250 [N1]", "stocks are rich relative to use",
    "the crop is vulnerable to frost", "a crowded export lineup", "short crop", "long-term outlook")


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


# CHAIN ENGINE expansion guard (CHAIN_ENGINE_PLAN sec 2.5, S3 fold): the AUTHORED bound -- max 6 contracts per
# row, max 7 rows, total expansions <= 25 (v1 actual: 24 after the S1 campinas drop). Subject to D1 as proposed.
_CHAIN_MAX_CONTRACTS_PER_ROW = 6
_CHAIN_MAX_ROWS = 7
_CHAIN_MAX_EXPANSIONS = 25
_CHAIN_MAX_HOPS = 3


def check_chain_map() -> list[str]:
    """CHAIN ENGINE (D3): the fail-closed chain_map.yaml lint. The curated-chain discipline as code -- the engine
    walks ONLY these chains, so a malformed row must fail the BUILD, never firing a fabricated path at serve time.
    Every check (sec 2.5), fail-closed like its cascade_map sibling:

      1. every `contracts[]` entry is a LOADED contract; every `node` exists in that contract's DAG (ACCENT-FOLDED
         both sides -- the ENSO root is accented `La_Niña` in 8/14 v1 DAGs, ASCII `La_Nina` in the chain_map; a
         literal match would leave accented-contract roots unmatched while the lint stayed green).
      2. every consecutive (parent->child) hop pair is a REAL DAG edge: child.parents contains the parent id,
         accent-folded (the SAME fold the engine runs at match time, cascade._accent_fold).
      3. every `ref` is an ACTIVE cascade_map row (load_map drops deferred); no hop's table is in the census
         UNCERTIFIED set; every `country:` PIN is a known PSD title post-_PSD_COUNTRY_FOLD.
      4. grain-direction (sec 2.2(3), S5): no hop finer-grained than its parent (year_month/date rank 0 <
         marketing_year rank 1) -- a MY->year_month step (spread an MY over months) is the deferred hard case.
      5. caps: <=3 quantified hops/row; <=6 contracts/row; <=7 rows; <=25 total contract expansions.
      6. static servability (the `_scope` SKIP_NODE class, PER CONTRACT): a country_rule=region hop whose
         driver region TOKEN does not resolve in region_map, or a silver_psd hop on a PSD_UNSERVED_SLUGS
         contract, makes `_chain_resolve_hop` return None -> the engine declines the WHOLE chain (reason
         `error`) on EVERY turn, silently and forever. Same defect class as the all-hops-waiver-dark check:
         a statically dead row is a config error, not a runtime surprise. This is what keeps the family
         curation rule ("pick the SINGLE-region weather node, never the compound-region one" -- sec 2.5 /
         3.2) enforced at BUILD time when the roster grows.
    """
    from leviathan.graphrag.graph import CausalGraph
    from leviathan.graphrag.numbers.cascade import (_GRAIN_RANK, _PSD_COUNTRY_FOLD, PSD_SLUG_ALIAS,
                                                    PSD_UNSERVED_SLUGS, _accent_fold, load_chain_map, load_map,
                                                    load_region_map)
    from leviathan.graphrag.numbers.cascade_census import UNCERTIFIED_TABLES as _uncertified
    errs: list[str] = []
    try:
        chains = load_chain_map()
    except Exception as exc:  # noqa: BLE001 -- a malformed chain_map must fail the build, not crash lint silently
        return [f"chain_map: failed to parse ({exc})"]
    if not chains:
        return errs                                     # no file / all-deferred -> the chain engine no-ops (OK)
    graph = CausalGraph.load()
    loaded = frozenset(graph.contracts.keys())
    refs = load_map() or {}
    # known PSD surface-form titles = the curated region_map resolve country set + the fold targets (offline
    # proxy for the live DISTINCT-title probe -- the lint is AWS-free).
    resolve = (load_region_map() or {}).get("resolve") or {}
    known_titles = {(v or {}).get("country") for v in resolve.values() if (v or {}).get("country")}
    known_titles |= set(_PSD_COUNTRY_FOLD.values())
    # per-contract accent-folded driver -> parents (accent-folded) index, built once; plus the driver's own
    # region TOKEN (the country_rule=region resolution input -- the static-unservability lint below).
    dag: dict = {}
    region_tok: dict = {}
    for cslug, c in graph.contracts.items():
        dag[cslug] = {_accent_fold(d.id): {_accent_fold(p) for p in (d.parents or [])} for d in c.drivers}
        region_tok[cslug] = {_accent_fold(d.id): (d.region or "") for d in c.drivers}

    if len(chains) > _CHAIN_MAX_ROWS:
        errs.append(f"chain_map: {len(chains)} active rows > max {_CHAIN_MAX_ROWS} (expansion guard, sec 2.5)")
    total_expansions = 0
    seen_ids: set = set()
    _waived_folds = None                                 # lazy one-shot driver_slices waivers read (anchorability lint)
    for ch in chains:
        cid = (ch or {}).get("id") or "<no-id>"
        if cid in seen_ids:
            errs.append(f"chain_map {cid!r}: duplicate chain id")
        seen_ids.add(cid)
        contracts = (ch or {}).get("contracts") or []
        hops = (ch or {}).get("hops") or []
        if not contracts:
            errs.append(f"chain_map {cid!r}: no contracts")
        if not hops:
            errs.append(f"chain_map {cid!r}: no hops")
        if len(contracts) > _CHAIN_MAX_CONTRACTS_PER_ROW:
            errs.append(f"chain_map {cid!r}: {len(contracts)} contracts > max "
                        f"{_CHAIN_MAX_CONTRACTS_PER_ROW}/row (sec 2.5)")
        if len(hops) > _CHAIN_MAX_HOPS:
            errs.append(f"chain_map {cid!r}: {len(hops)} hops > max {_CHAIN_MAX_HOPS} quantified hops (sec 2.5)")
        total_expansions += len(contracts)
        # ── static anchorability (minideck RCA 2026-07-24): a waiver-dark node has no evidence slice, so it
        # can never yield an anchor window. The runtime survives a dark ROOT via the downstream-anchor
        # fallback (cascade.py), but a chain whose EVERY hop node is waived is statically dead -- it would
        # silently skip and let a DIFFERENT-mechanism row fire into the question (the wheat skeleton fired
        # enso_drought into an acreage ask). All-dark = config error, not a runtime surprise.
        if hops:
            if _waived_folds is None:                    # hoisted: one driver_slices read per lint run, not per row
                from leviathan.graphrag import evidence as _ev
                import yaml as _yaml
                try:
                    _waived_folds = {_accent_fold(k) for k in
                                     ((_yaml.safe_load(_ev._DRIVER_PATH.read_text(encoding="utf-8")) or {})
                                      .get("waivers") or {})}
                except OSError:
                    _waived_folds = set()
            hop_folds = {_accent_fold((hp or {}).get("node")) for hp in hops}
            if hop_folds and hop_folds <= _waived_folds:
                errs.append(f"chain_map {cid!r}: EVERY hop node is waiver-dark in driver_slices.yaml -- the "
                            f"chain can never derive an anchor window (statically unanchorable)")
        # ── ref + pin + grain checks are contract-independent (per hop) ──
        prev_rank = None
        for i, hop in enumerate(hops):
            ref = (hop or {}).get("ref")
            row = refs.get(ref)
            if row is None:
                errs.append(f"chain_map {cid!r} hop {i} (node {(hop or {}).get('node')!r}): ref {ref!r} is not "
                            f"an ACTIVE cascade_map row (absent or deferred)")
                prev_rank = None
                continue
            if row.get("table") in _uncertified:
                errs.append(f"chain_map {cid!r} hop {i}: ref {ref!r} table {row.get('table')!r} is in the census "
                            f"UNCERTIFIED set -- a chain hop must read a certified table")
            pin = (hop or {}).get("country")
            if pin is not None:
                folded = _PSD_COUNTRY_FOLD.get(pin, pin)
                if folded not in known_titles:
                    errs.append(f"chain_map {cid!r} hop {i}: country pin {pin!r} (fold {folded!r}) is not a known "
                                f"PSD title (curated region_map country set)")
            rank = _GRAIN_RANK.get(row.get("period_type"), 0)
            if prev_rank is not None and rank < prev_rank:
                errs.append(f"chain_map {cid!r} hop {i} (ref {ref!r}, {row.get('period_type')!r}): finer-grained "
                            f"than its parent -- a downstream hop may not be sub-annual under an annual parent "
                            f"(sec 2.2(3))")
            prev_rank = rank
        # ── node-existence + edge checks are PER CONTRACT (accent-folded) ──
        for cslug in contracts:
            if cslug not in loaded:
                errs.append(f"chain_map {cid!r}: contract {cslug!r} is not a loaded contract")
                continue
            drivers = dag.get(cslug, {})
            prev_fold = None
            for i, hop in enumerate(hops):
                node = (hop or {}).get("node")
                nf = _accent_fold(node)
                if nf not in drivers:
                    errs.append(f"chain_map {cid!r}/{cslug}: node {node!r} is not a driver id in that DAG")
                    prev_fold = None
                    continue
                if prev_fold is not None and prev_fold not in drivers.get(nf, set()):
                    errs.append(f"chain_map {cid!r}/{cslug}: hop {i} {node!r} does not list the prior hop as a "
                                f"parent -- (parent->child) is NOT a real DAG edge (accent-folded)")
                prev_fold = nf
                # ── static unservability (the _scope SKIP_NODE class, same shape as the waiver lint above):
                # a hop whose scope cannot resolve returns None from _chain_resolve_hop, and the engine
                # declines the WHOLE chain (reason `error`) EVERY time -- silently, forever. The two
                # statically-decidable SKIP_NODE causes (cascade._scope):
                #   * country_rule=region + a driver region TOKEN that is not in region_map.resolve (the
                #     compound/prose tokens: 'US_Midwest;Argentina;Brazil', 'Brazil CS / India'). The
                #     family rows already pick the SINGLE-region weather node per contract (sec 2.5 /
                #     3.2); this makes that curation rule fail the BUILD instead of the serve.
                #   * silver_psd + a contract in PSD_UNSERVED_SLUGS (declared-absent PSD series).
                # silver_fred_fx additionally needs a currency on the resolved entry (no country column).
                hrow = refs.get((hop or {}).get("ref"))
                if hrow is None:
                    continue                                  # already reported by the per-hop ref check
                table = hrow.get("table")
                if table == "silver_psd" and PSD_SLUG_ALIAS.get(cslug, cslug) in PSD_UNSERVED_SLUGS:
                    errs.append(f"chain_map {cid!r}/{cslug}: hop {i} ref {(hop or {}).get('ref')!r} reads "
                                f"silver_psd, but {cslug!r} is a declared-unserved PSD slug -- the hop can "
                                f"never resolve a scope (statically unservable)")
                elif hrow.get("country_rule") == "region":
                    tok = (region_tok.get(cslug, {}).get(nf) or "").strip()
                    entry = resolve.get(tok)
                    if not entry:
                        errs.append(f"chain_map {cid!r}/{cslug}: hop {i} {node!r} is country_rule=region but its "
                                    f"region token {tok!r} does not resolve in region_map -- the hop can never "
                                    f"resolve a country (statically unservable)")
                    elif table == "silver_fred_fx" and not entry.get("currency"):
                        errs.append(f"chain_map {cid!r}/{cslug}: hop {i} {node!r} resolves region {tok!r} with NO "
                                    f"currency -- silver_fred_fx has no country column (statically unservable)")
    if total_expansions > _CHAIN_MAX_EXPANSIONS:
        errs.append(f"chain_map: {total_expansions} total contract expansions > max {_CHAIN_MAX_EXPANSIONS} "
                    f"(expansion guard, sec 2.5)")
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


# TRANSMISSION CHAIN caps (TRANSMISSION_CHAIN_PLAN D1/D3/D5). The horizontal engine's v1 universe is DELIBERATELY
# tiny: 2 curated rows (flagship PALM->SBO->SBM + pure-vegoil control SBO->PALM->RSO), depth 2 links, and the
# two clusters the D-universe admits. The 22-path census is the COMBINATORIAL count, never the catalog (sec 1.2:
# auto-enumeration IS path minting) -- these bounds are what keeps the curation honest at build time.
_XMIT_MAX_ROWS = 2
_XMIT_MAX_LINKS = 2
_XMIT_MIN_LINKS = 2                                  # a 1-link "chain" IS an RV2 pair -> `degenerate` (3.2)
_XMIT_CLUSTERS = frozenset({"vegoil_substitution", "soy_crush"})   # D3: feed_grain is an ISOLATED edge, never a chain
_XMIT_NATURES = frozenset({"divergence", "co_move"})               # D9: an EXPECTATION hint, never a gate
_XMIT_CAP_PARAM = "serving.cascade.transmission.cap"


def _load_transmission_map() -> list:
    """The AUTHORED `configs/graphrag/numbers/transmission_map.yaml` `chains:` rows (FILE ORDER preserved; only
    `deferred: true` dropped) -- deliberately NOT `cascade.load_transmission_map()`'s output.

    That loader is fail-closed by DROPPING any row failing `_transmission_row_ok`, so linting its output would
    silently green-light exactly the drift this lint exists to catch: the row would vanish from serving instead
    of failing the build. The lint reads the file, re-derives the structural verdict itself, and cross-checks
    the engine's own predicate so a DROPPED row is REPORTED (an inert chain is a config error, not a runtime
    surprise -- the check_chain_map static-anchorability lesson). Missing file -> [] -> the lint no-ops."""
    p = _CFG / "numbers" / "transmission_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return [c for c in ((doc or {}).get("chains") or []) if not (c or {}).get("deferred")]


def _transmission_cap():
    """The horizontal engine's OWN net-fetch budget (D5), or None when nothing declares one. Resolution order:
    the composer-lane constant `cascade.TRANSMISSION_CAP` (the CHAIN_CAP sibling), then the params path.
    NEVER the vertical CHAIN_CAP: the caps stay ENGINE-INDEPENDENT (non-goals; the combined chain_family
    counter was DROPPED, fold-pass finding 3), so reading the vertical budget here would re-introduce exactly
    the shared counter the plan rejected."""
    from leviathan.graphrag import params as _pr
    from leviathan.graphrag.numbers import cascade as _casc
    cap = getattr(_casc, "TRANSMISSION_CAP", None)
    if cap is None:
        cap = _pr.get(_XMIT_CAP_PARAM, None)
    try:
        return int(cap) if cap is not None else None
    except (TypeError, ValueError):
        return None


def check_transmission_map() -> list[str]:
    """TRANSMISSION CHAIN (D1/D3/D5/D6/D9): the fail-closed transmission_map.yaml lint -- check_chain_map's
    horizontal sibling. The engine composes ONLY these curated chains (never the 22-path census), so a
    malformed row must fail the BUILD rather than compose a fabricated read-across at serve time.

    Row schema (cascade.load_transmission_map's contract)::

        chains:
          - id: xmit_palm_soyoil_meal              # unique; NEVER a vertical chain_map id (D6)
            links:                                 # ordered, 2 links in v1 (D1 depth cap)
              - {pair_id: soyoil_palm_vegoil,   source: malaysian_crude_palm_oil_cme,
                 target: soybean_oil_cbot,  nature: divergence}
              - {pair_id: soymeal_soyoil_crush, source: soybean_oil_cbot,
                 target: soybean_meal_cbot, nature: co_move}

    There is no `focus:` field -- the HEAD link's source IS the focus the composer first-fires on
    (`_xmit_select`); an optional `focus:` is accepted but must agree with it.

    Checks (all fail-closed):

      1. SCHEMA: unique row id; 2 links (>=2 or the "chain" is just an RV2 pair -> `degenerate`, 3.2; <=
         cascade.TRANSMISSION_DEPTH_CAP by D1); each link carries pair_id/source/target; `nature`, when
         present, is one of {divergence, co_move} -- an EXPECTATION HINT the composer may not force (D9: the
         OBSERVED per-window sign decides the fork, fold-pass finding 1).
      2. REFS RESOLVE TO ACTIVE RV2 LINKS: each `pair_id` is a MATERIAL complex_map row (load_complex_map
         drops non-material, so a contextual/excluded pair can never fire -> a chain naming one is statically
         dead); the link's {source, target} EQUAL that pair's two slugs and both sides are
         `country_rule: world` -- the `_xc_sides_ok` runtime guard restated as config lint.
      3. CLUSTER MEMBERSHIP: every link's pair sits in the D-universe {vegoil_substitution, soy_crush}. D3
         fences feed_grain BY DESIGN -- corn_wheat_feed is a deg-1 isolated edge admitting ZERO multi-edge
         paths, so a feed chain is unbuildable, not merely deferred.
      4. COMPOSABILITY: consecutive links share EXACTLY one node and it is oriented (link i target == link
         i+1 source); source != target; no repeated node (the census walks SIMPLE paths); no repeated pair
         in one row (two identical links collapse -> `degenerate`, 3.2).
      5. NO VERTICAL-CHAIN REF REUSE (D6): a transmission row id may not collide with a vertical chain_map
         chain id, a link may not carry the vertical hop's `ref:`/`node:` keys, and its `pair_id` may not
         name a cascade_map ref or a vertical chain id. The two engines share ONLY the decline vocabulary
         (3.2); sharing a ref/id surface would blur the T2b ledger's engine attribution.
      6. STATICALLY DEAD: a leg that is not a loaded contract, or is in PSD_UNSERVED_SLUGS (cocoa/FCOJ carry no
         PSD balance sheet) can never yield the World su_ratio both legs need -> the chain is dead on arrival.
         This is the OFFLINE half of the per-pair census (axes (a)/(b), sec 1.3); the era-disjoint + World-synth
         axes need pg and stay with `pair_realizable` at runtime -- this lint is AWS-free by construction.
         The same class covers a row the ENGINE LOADER would DROP (`cascade._transmission_row_ok`): silently
         inert at serve time is a config error, not a runtime surprise.
      7. CAP PRESENT (D5): the horizontal engine must own a transmission-scoped budget
         (`cascade.TRANSMISSION_CAP` / `serving.cascade.transmission.cap`), positive. NOT the vertical
         CHAIN_CAP and not a shared counter (fold-pass finding 3).

    Missing/all-deferred map -> [] rows -> the lint no-ops (the engine composes nothing), exactly like
    check_chain_map on an absent chain_map.
    """
    from leviathan.graphrag import complex_map as xcm
    from leviathan.graphrag.graph import CausalGraph
    from leviathan.graphrag.numbers import cascade as _casc
    from leviathan.graphrag.numbers.cascade import PSD_SLUG_ALIAS, PSD_UNSERVED_SLUGS, load_chain_map, load_map
    errs: list[str] = []
    try:
        chains = _load_transmission_map()
    except Exception as exc:  # noqa: BLE001 -- a malformed map must fail the build, not crash lint silently
        return [f"transmission_map: failed to parse ({exc})"]
    if not chains:
        return errs                              # no file / all-deferred -> the transmission engine no-ops (OK)
    try:
        cmap = xcm.load_complex_map()
        material = {p.id: p for p in (getattr(cmap, "pairs", None) or [])}
        authored = {p.id: p for p in xcm.iter_all_pairs()}
    except Exception as exc:  # noqa: BLE001
        return [f"transmission_map: complex_map unavailable ({exc}) -- every link is unverifiable, fail closed"]
    loaded = frozenset(CausalGraph.load().contracts.keys())
    refs = load_map() or {}
    vertical_ids = {(c or {}).get("id") for c in (load_chain_map() or [])}
    depth_cap = int(getattr(_casc, "TRANSMISSION_DEPTH_CAP", _XMIT_MAX_LINKS))
    row_ok = getattr(_casc, "_transmission_row_ok", None)

    cap = _transmission_cap()
    if cap is None or cap <= 0:
        errs.append(f"transmission_map: no transmission-scoped cap ({_XMIT_CAP_PARAM} / cascade.TRANSMISSION_CAP) "
                    f"-- the horizontal engine must own its OWN net-fetch budget (D5); it may NOT decrement the "
                    f"vertical CHAIN_CAP (no shared counter)")
    if len(chains) > _XMIT_MAX_ROWS:
        errs.append(f"transmission_map: {len(chains)} active rows > max {_XMIT_MAX_ROWS} (D1 v1 catalog = "
                    f"flagship + control; the 22-path census is NOT the catalog)")
    seen_ids: set = set()
    for ch in chains:
        cid = (ch or {}).get("id") or "<no-id>"
        if cid in seen_ids:
            errs.append(f"transmission_map {cid!r}: duplicate chain id")
        seen_ids.add(cid)
        if cid in vertical_ids:
            errs.append(f"transmission_map {cid!r}: id collides with a vertical chain_map chain id (D6) -- the "
                        f"two engines' trace keys and ledger rows must disambiguate by id")
        focus = (ch or {}).get("focus")          # OPTIONAL: the head link's source IS the focus (`_xmit_select`)
        links = (ch or {}).get("links") or []
        if len(links) < _XMIT_MIN_LINKS:
            errs.append(f"transmission_map {cid!r}: {len(links)} links < min {_XMIT_MIN_LINKS} -- a 1-link chain "
                        f"IS an RV2 pair, which the pair engine already serves (`degenerate`, 3.2)")
        if len(links) > depth_cap:
            errs.append(f"transmission_map {cid!r}: {len(links)} links > max {depth_cap} (D1 depth cap; "
                        f"3-4 link paths are deferred)")
        # The row the ENGINE LOADER would silently DROP is a config error, not a runtime surprise: it would be
        # inert at serve time (never composing, never declining, no trace) with the build still green.
        if row_ok is not None and not row_ok(ch):
            errs.append(f"transmission_map {cid!r}: the ENGINE loader DROPS this row "
                        f"(cascade._transmission_row_ok fail-closed) -- it would be silently INERT at serve "
                        f"time, never composing and never declining; fix the row, never ship a dead chain")
        seen_pairs: set = set()
        nodes_seen: list = []
        prev_target = None
        for i, lk in enumerate(links):
            pid = (lk or {}).get("pair_id")
            src, tgt = (lk or {}).get("source"), (lk or {}).get("target")
            # 5. vertical-shape reuse (D6): a transmission link names an RV2 PAIR, never a cascade_map ref/DAG node.
            for key in ("ref", "node"):
                if (lk or {}).get(key) is not None:
                    errs.append(f"transmission_map {cid!r} link {i}: carries the VERTICAL hop key {key!r} -- a "
                                f"transmission link names a complex_map `pair_id`, never a cascade_map ref/DAG "
                                f"node (D6, engines stay independent)")
            if pid in refs:
                errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} is a cascade_map REF, not a "
                            f"complex_map pair -- vertical-chain ref reuse (D6)")
            if pid in vertical_ids:
                errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} is a VERTICAL chain id, not a "
                            f"complex_map pair -- vertical-chain ref reuse (D6)")
            if not pid or not src or not tgt:
                errs.append(f"transmission_map {cid!r} link {i}: needs pair_id/source/target (got "
                            f"{pid!r}/{src!r}/{tgt!r})")
                prev_target = None
                continue
            if src == tgt:
                errs.append(f"transmission_map {cid!r} link {i}: source == target ({src!r}) -- a link compares "
                            f"TWO commodities' World balance sheets, so a self-link is a vacuous fork")
            nature = (lk or {}).get("nature")
            if nature is not None and nature not in _XMIT_NATURES:
                errs.append(f"transmission_map {cid!r} link {i}: bad nature {nature!r} "
                            f"({'|'.join(sorted(_XMIT_NATURES))}) -- and it is an EXPECTATION hint only (D9), "
                            f"never a gate on the observed sign")
            if pid in seen_pairs:
                errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} repeats in this chain -- the two "
                            f"links collapse to one identity (`degenerate`, 3.2)")
            seen_pairs.add(pid)
            # 4. composability: oriented hub + simple path (+ the optional focus field agreeing with the head)
            if i == 0:
                if focus and src != focus:
                    errs.append(f"transmission_map {cid!r}: head-link source {src!r} != focus {focus!r} (D1) -- "
                                f"the composer first-fires on the HEAD link's source, so the declared focus "
                                f"would never select this row")
                nodes_seen.append(src)
            elif prev_target is not None and src != prev_target:
                errs.append(f"transmission_map {cid!r} link {i}: source {src!r} != the prior link's target "
                            f"{prev_target!r} -- consecutive links must share EXACTLY one node, oriented (D1)")
            if tgt in nodes_seen:
                errs.append(f"transmission_map {cid!r} link {i}: node {tgt!r} repeats -- the path census walks "
                            f"SIMPLE paths (no repeated node)")
            nodes_seen.append(tgt)
            prev_target = tgt
            # 2. the pair resolves to an ACTIVE (material) RV2 link, and the legs match it
            pair = material.get(pid)
            if pair is None:
                if pid in authored:
                    errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} is authored but NOT material "
                                f"(tier {authored[pid].materiality_tier!r}) -- load_complex_map drops it, so the "
                                f"link can never fire (statically dead)")
                else:
                    errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} is not a complex_map pair")
                continue
            if {src, tgt} != set(pair.pair):
                errs.append(f"transmission_map {cid!r} link {i}: legs {{{src!r}, {tgt!r}}} are not the pair's own "
                            f"slugs {set(pair.pair)!r} -- `_xc_sides_ok` would decline the whole fork")
            for side, sd in (("sideA", pair.side_a), ("sideB", pair.side_b)):
                if (sd or {}).get("country_rule") != "world":
                    errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} {side}.country_rule "
                                f"{(sd or {}).get('country_rule')!r} -- every transmission leg is World "
                                f"(the both-World guard has no analogue to relax)")
            # 3. cluster membership (the D-universe)
            if pair.complex_name not in _XMIT_CLUSTERS:
                errs.append(f"transmission_map {cid!r} link {i}: pair_id {pid!r} is complex "
                            f"{pair.complex_name!r}, outside the v1 universe "
                            f"{sorted(_XMIT_CLUSTERS)} -- feed_grain is an ISOLATED single edge (D3): it admits "
                            f"ZERO multi-edge paths, so a chain over it is unbuildable, not merely deferred")
            # 6. statically dead legs (the OFFLINE half of the per-pair census, sec 1.3 axes (a)/(b))
            for slug in (src, tgt):
                if slug not in loaded:
                    errs.append(f"transmission_map {cid!r} link {i}: leg {slug!r} is not a loaded contract "
                                f"(statically dead)")
                elif PSD_SLUG_ALIAS.get(slug, slug) in PSD_UNSERVED_SLUGS:
                    errs.append(f"transmission_map {cid!r} link {i}: leg {slug!r} is PSD-UNSERVED -- no balance "
                                f"sheet, so its World su_ratio can never resolve (statically dead)")
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


def _check_register_detector() -> list[str]:
    from leviathan.graphrag import register as reg
    errs: list[str] = []
    for probe in _DETECTOR_FLAG:
        if not (reg.register_leaks(probe) or reg.count_valuation_words(probe) or reg.count_flow_words(probe)):
            errs.append(f"R2/R8 detector: banned probe not flagged: {probe!r}")
    for probe in _DETECTOR_LANE_B:
        if not reg.lane_b_hits(probe):
            errs.append(f"R2/R8 Lane B: windowed probe not flagged: {probe!r}")
    for probe in _DETECTOR_CLEAN:
        if reg.register_leaks(probe) or reg.count_valuation_words(probe) or reg.count_flow_words(probe):
            errs.append(f"R2/R8 detector: honest probe FALSE-flagged: {probe!r}")
    return errs


def _check_no_engine_ref(cmap, tables, rule: str, label: str) -> list[str]:
    """R4/R9: no cascade_map ref may point at a fenced table. complex_map sides carry cascade refs (side.ref),
    so they inherit this check for free -- a price/positioning leg can never resolve through the engine map."""
    errs: list[str] = []
    for ref, row in (cmap or {}).items():
        if (row or {}).get("table") in tables:
            errs.append(f"{rule} cascade_map {ref!r}: {label} table {row.get('table')!r} must never feed an engine")
    return errs


def _check_decline_census() -> list[str]:
    """R5: every NONE-tier name owns a decline template that passes register_leaks. The template registry is a
    W2.5 numbers-agent artifact; census it once the attribute exists, else vacuous-pass with a printed note."""
    from leviathan.graphrag import register as reg
    try:
        from leviathan.graphrag.numbers import agent as na
    except Exception:  # noqa: BLE001 -- agent import must never break the lint
        na = None
    templates = getattr(na, "DECLINE_TEMPLATES", None) if na is not None else None
    if not templates:
        print("NOTE price_register R5: decline-template registry not built yet (W2.5) -- vacuous pass")
        return []
    errs: list[str] = []
    for name in _NONE_TIER_DECLINE:
        t = templates.get(name)
        if not t:
            errs.append(f"R5 decline census: no decline template for NONE-tier {name!r}")
        elif reg.register_leaks(str(t)):
            errs.append(f"R5 decline census: template for {name!r} carries a register leak")
    return errs


def _check_decline_no_dead_metric() -> list[str]:
    """R5b (F3): no decline template may point readers at a metric fenced OUT of serving. Concretely -- while
    avg_farm_price is NOT whitelisted in silver_wasde, no template EXCEPT us_farm_price (which exists precisely
    to DECLINE the farm price) may present a 'farm price'/'farm-gate' proxy. That drift shipped three maize
    templates naming 'the US survey-based farm price' as the nearest governed proxy after W3.0 removed it. When
    avg_farm_price is restored (re-whitelisted) the references become legitimate again and this passes."""
    from leviathan.graphrag.numbers.registry import load_registry
    try:
        from leviathan.graphrag.numbers import agent as na
    except Exception:  # noqa: BLE001 -- agent import must never break the lint
        na = None
    templates = getattr(na, "DECLINE_TEMPLATES", None) if na is not None else None
    if not templates:
        return []
    wasde = load_registry().tables.get("silver_wasde")
    if wasde is not None and "avg_farm_price" in wasde.metrics:
        return []                                   # restored -> proxy references are legitimate again
    rx = re.compile(r"farm[ -]?gate|farm\s+price", re.I)
    errs: list[str] = []
    for name, t in templates.items():
        if name == "us_farm_price":
            continue                                # the one template that legitimately DECLINES the farm price
        if rx.search(str(t)):
            errs.append(f"R5b decline census: template {name!r} references the fenced US farm price while "
                        f"avg_farm_price is not whitelisted (F3 drift -- repoint or remove the reference)")
    return errs


def check_price_register() -> list[str]:
    """PRICE_OBSERVABILITY W0.2 -- the register fence lint (AWS-free, pure). R1 unit/override discipline
    (conditional on registration -- vacuous today), R2/R8 detector probe (green now by construction), R3 wasde
    provenance (conditional -- vacuous today), R4 no PRICE_TABLE feeds an engine (active now), R5 decline census
    (vacuous until the W2.5 template registry exists)."""
    from leviathan.graphrag.numbers.cascade import load_map
    from leviathan.graphrag.numbers.registry import load_registry
    errs: list[str] = []
    tables = load_registry().tables
    # R1: pink_sheet metrics declare a unit; unit_overrides only on a commodity_col table + curated-set equality.
    ps = tables.get("silver_pink_sheet")
    if ps is not None:
        for mname, m in ps.metrics.items():
            if not (m.unit or "").strip():
                errs.append(f"R1 silver_pink_sheet.{mname}: metric declares no unit")
    for tid, ts in tables.items():
        for mname, m in ts.metrics.items():
            ov = getattr(m, "unit_overrides", None)
            if not ov:
                continue
            if not ts.commodity_col:
                errs.append(f"R1 {tid}.{mname}: unit_overrides on a table with no commodity_col")
            if tid == "silver_wasde" and mname == "avg_farm_price" and set(ov) != _FARM_PRICE_COMMODITIES:
                errs.append(f"R1 silver_wasde.avg_farm_price: unit_overrides keys {sorted(ov)} != "
                            f"curated coverage {sorted(_FARM_PRICE_COMMODITIES)}")
    # R2/R8: the lexicon provably ships before any flag.
    errs += _check_register_detector()
    # R3: avg_farm_price (once whitelisted) demands estimate_role-first vintage_tiebreak + provenance_col.
    wasde = tables.get("silver_wasde")
    if wasde is not None and "avg_farm_price" in wasde.metrics and getattr(
            wasde.metrics["avg_farm_price"], "unit_overrides", None):
        # estimate_role-first: the FIRST vintage_tiebreak term ranks on the estimate_role column with a role
        # priority list (actual < estimate < projection) so the most-settled figure wins any tie. (role_order
        # holds the priority VALUES; the column is t.col -- the earlier `t.role_order[:1] == ['estimate_role']`
        # was a W0 coding slip, vacuous until avg_farm_price was whitelisted and now corrected.)
        tb0 = wasde.vintage_tiebreak[0] if wasde.vintage_tiebreak else None
        if not (tb0 and tb0.col == "estimate_role" and tb0.role_order):
            errs.append("R3 silver_wasde: avg_farm_price whitelisted but no estimate_role-first vintage_tiebreak")
        if getattr(wasde, "provenance_col", None) != "estimate_role":
            errs.append("R3 silver_wasde: avg_farm_price whitelisted but provenance_col != 'estimate_role'")
    # R4: price tables never feed an engine (complex_map inherits via its cascade refs).
    errs += _check_no_engine_ref(load_map(), PRICE_TABLES, "R4", "price")
    # R5: decline census.
    errs += _check_decline_census()
    # R5b (F3): no decline template points at the fenced farm-price metric while it is unwhitelisted.
    errs += _check_decline_no_dead_metric()
    return errs


def check_numbers_schema_pins() -> list[str]:
    """Card-vs-DDL column pins for EVERY numbers-registry table (AWS-free; the node_silver_map pattern).
    Born from the silver_nasa_power incident (2026-07-21): the BF-W1 compaction moved country/region/month
    in-file, the rebuilt Glue catalog never declared them, and NO gate compared the numbers card against a
    schema artifact (contract_check's INV-3 exclusion left nasa_power probe-less) -- every weather lookup
    died COLUMN_NOT_FOUND for weeks. This lint pins each card's referenced columns against the checked-in
    sql/athena/ddl/<table>.sql so card-vs-DDL drift fails the build; tables without a DDL file skip with a
    printed note (never a silent pass)."""
    from leviathan.graphrag.numbers.registry import load_registry
    errs: list[str] = []
    for tid, ts in load_registry().tables.items():
        ddl = _DDL / f"{(ts.athena_table or tid)}.sql"
        if not ddl.exists():
            print(f"NOTE numbers_schema_pins: no DDL file for {tid} -- skipped")
            continue
        text = ddl.read_text(encoding="utf-8")
        refs = {ts.commodity_col, ts.country_col, ts.period_col, ts.date_col, ts.knowledge_date_col,
                ts.year_col, ts.month_col, ts.provenance_col, ts.vintage_partition_col,
                getattr(ts, "metric_col", None), getattr(ts, "value_col", None), getattr(ts, "unit_col", None)}
        if ts.shape == "wide":
            refs |= set(ts.metrics)
        for col in sorted(c for c in refs if c):
            if not re.search(rf"\b{re.escape(col)}\b", text):
                errs.append(f"numbers_schema_pins {tid}: card references column {col!r} absent from {ddl.name}")
    return errs


def check_esr_destinations() -> list[str]:
    """ESR_DESTINATION_PLAN W0/§5.1: the FAS destination code<->name reference lints clean -- strict
    (extra='forbid') schema parse, global alias uniqueness, pseudo<->kind consistency, and EVERY display
    name in agent._ESR_DESTINATIONS resolves to a code (the guard vocabulary is fully served, else a
    destination we claim to detect cannot be filtered). AWS-free; the S3 double-count / missing-code probe
    is a separate in-VPC gate whose verdict is pinned into the YAML audit block."""
    from leviathan.graphrag.numbers.esr_destinations import lint_reference
    return lint_reference()


def check_quarantine() -> list[str]:
    """SILVER-F047 -- a quarantined table (TableSpec.quarantined) keeps serving DIRECT agent lookups (raw
    daily weather has no gold replacement; gold_weather_z serves anomalies, not observations), but no engine
    map may ever reference it: the cascade weather leg moved to gold_weather_z at Phase D-W4 and INV-3
    forbids re-adding an engine leg on the LIST-storm projection. Build-failing, not prose."""
    from leviathan.graphrag.numbers.cascade import load_map
    from leviathan.graphrag.numbers.registry import load_registry
    q = tuple(tid for tid, ts in load_registry().tables.items() if getattr(ts, "quarantined", False))
    if not q:
        return []
    return _check_no_engine_ref(load_map(), q, "F047", "quarantined")


# R7: a POSITIONING metric must be a DATED LEVEL or a Z-SCORE -- never a forecast/percentile-projection family.
# Level units are the raw position/OI counts + the signed pct-of-OI; z families carry a sigma/z-score unit. A
# metric outside these families (or a forward-looking name) means positioning is being served as something
# other than observed history, which the ratified fence forbids.
_COT_LEVEL_UNITS = frozenset({"contracts", "pct of OI (signed)"})


def _is_cot_z_unit(unit: str) -> bool:
    u = (unit or "").strip().lower()
    return "sigma" in u or "z-score" in u or "zscore" in u or u.endswith(" z")


def _suggest_catalog_metric_text() -> "str | None":
    """The suggester's advertised ANSWERABLE-FUNDAMENTALS catalog string (server._SUGGEST_METRICS), read by
    AST (no heavyweight server import): the enumerated source of metrics the grounded suggester may propose.
    None when the module/constant is absent (R10 then prints a skip note -- never a silent pass)."""
    import ast
    src = Path(__file__).with_name("server.py")
    if not src.exists():
        return None
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- an unparseable server.py is surfaced as a skip, not a crash
        return None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_SUGGEST_METRICS"):
            try:
                v = ast.literal_eval(node.value)
                return v if isinstance(v, str) else None
            except Exception:  # noqa: BLE001
                return None
    return None


def check_cot_register() -> list[str]:
    """PRICE_OBSERVABILITY W0.2 (the W4 gate) -- positioning-table fence. R9: no engine ref points at a
    POSITIONING_TABLE (active now). R7: silver_cot metric descs register-clean AND every metric limited to a
    dated level/z family (no forward-looking name). R10: the suggester's answerable-fundamentals catalog
    source (server._SUGGEST_METRICS) names no positioning-table metric. R7/R10 go NON-VACUOUS once silver_cot
    is registered."""
    from leviathan.graphrag.numbers import stats as st
    from leviathan.graphrag.numbers.cascade import load_map
    from leviathan.graphrag.numbers.registry import load_registry
    errs: list[str] = _check_no_engine_ref(load_map(), POSITIONING_TABLES, "R9", "positioning")
    tables = load_registry().tables
    cot = tables.get("silver_cot")
    if cot is None:
        return errs   # R7/R10 vacuous until W4 registers silver_cot
    from leviathan.graphrag import register as reg
    # R7a: desc register-cleanliness (a metric desc must carry no valuation/flow word).
    for mname, m in cot.metrics.items():
        if reg.count_valuation_words(m.desc) or reg.count_flow_words(m.desc):
            errs.append(f"R7 silver_cot.{mname}: metric desc carries a banned valuation/flow word")
        # R7b: metric limited to a dated LEVEL or Z family, and no forward-looking name.
        if st.is_banned_name(mname):
            errs.append(f"R7 silver_cot.{mname}: metric name is forward-looking "
                        f"(fit|trend|forecast|project|extrapolat|predict) -- positioning is history only")
        if not (m.unit in _COT_LEVEL_UNITS or _is_cot_z_unit(m.unit)):
            errs.append(f"R7 silver_cot.{mname}: unit {m.unit!r} is neither a dated level nor a z-score "
                        f"family -- positioning metrics are limited to observed levels + z-scores")
    # R10: the suggester grounds answerable questions on _SUGGEST_METRICS (its catalog source); a positioning
    # table's metric must never appear there (positioning is a driver LANE, never a suggestible numbers source).
    cat = _suggest_catalog_metric_text()
    if cat is None:
        print("NOTE cot_register R10: suggester catalog source (_SUGGEST_METRICS) not found -- skipped")
    else:
        low = cat.lower()
        for tid in POSITIONING_TABLES:
            pt = tables.get(tid)
            for mname in (pt.metrics if pt else {}):
                for form in (mname.lower(), mname.replace("_", " ").lower()):
                    if form and form in low:
                        errs.append(f"R10 suggester catalog: positioning metric {tid}.{mname!r} appears in "
                                    f"the suggester's answerable-fundamentals catalog -- positioning must "
                                    f"never be a suggestible source")
                        break
        for tok in ("managed money", "managed-money", "net long", "net short", "positioning"):
            if tok in low:
                errs.append(f"R10 suggester catalog: positioning vocabulary {tok!r} in _SUGGEST_METRICS -- "
                            f"positioning is a driver LANE, not a suggestible numbers source")
    return errs


def check_stats_registry() -> list[str]:
    """PRICE_OBSERVABILITY W3.5 -- the descriptive-only stats fence, as a build gate. The stats tool belt is
    enum-locked to stats.STAT_REGISTRY; any registered name matching fit|trend|forecast|project|extrapolat|
    predict is a projection tool wearing a math costume (R3's forbidden forward statement) and FAILS the
    build. Imports the live registry so a smuggled name is caught here, not just by the module's import-time
    assertion."""
    from leviathan.graphrag.numbers import stats as st
    errs: list[str] = []
    for name in st.STAT_REGISTRY:
        if st.is_banned_name(name):
            errs.append(f"stats_registry: registered stat {name!r} matches the forward-looking ban "
                        f"(fit|trend|forecast|project|extrapolat|predict) -- descriptive history only")
    return errs


# SEAM C (ENGINE SEAMS rev-52) -- futures v1.5-lite (Option A, levels-only). The card lives in
# configs/graphrag/numbers/tables.yaml and, as of 2026-07-23, is WHITELISTED for serving (removed from
# registry.WHITELIST_ABSENT_DEFAULT), so it now LOADS into the served registry. This dedicated lint reads the
# RAW card (authoritative for the card's shape regardless of load-time drops) and asserts (a) it exists with
# the exact levels-only shape, (b) close is the ONLY metric and its unit_overrides cover exactly the 12 slugs
# with the exact exchange-unit strings, (c) the whitelist state is INTENTIONAL (the table is NOT in
# WHITELIST_ABSENT_DEFAULT and IS present in the served registry -- the agent tool enum), and (d) every
# futures decline template is register-clean and the class set matches the agent's guard.
_FUTURES_TABLE = "silver_futures_prices"
_FUTURES_UNIT_OVERRIDES: dict = {
    "corn_cbot": "US cents/bushel", "soybeans_cbot": "US cents/bushel",
    "soft_red_winter_wheat_cbot": "US cents/bushel", "hard_red_winter_wheat_kcbt": "US cents/bushel",
    "soybean_oil_cbot": "US cents/lb", "arabica_coffee": "US cents/lb", "cotton": "US cents/lb",
    "raw_sugar": "US cents/lb", "frozen_orange_juice": "US cents/lb",
    "soybean_meal_cbot": "USD/short ton", "cocoa": "USD/metric ton", "rough_rice_cbot": "USD/cwt",
}
_FUTURES_CARD_FIELDS: dict = {
    "shape": "wide", "commodity_col": "leviathan_slug", "date_col": "date", "date_col_type": "timestamp",
    "knowledge_semantics": "data_date", "knowledge_date_col": "date", "publication_lag_days": 1,
    "levels_only": True,
}


def check_futures_lite() -> list[str]:
    """SEAM-C futures-lite lint (AWS-free, pure). Card-shape + close-only + unit_overrides completeness +
    WHITELISTED-AND-SERVED gate state + decline-template register-cleanliness. Reads the RAW tables.yaml (the
    authoritative source for the card's shape); post-whitelist (2026-07-23) the card also loads into the
    served registry, which block (c) now asserts. FUTURES v1.5 (2026-07-23): block (b2) binds the transform
    UNIT_MAP three-way with the card + the tracked constant, and block (e) pins the registry unit column /
    schema_version 2 / versioned roll policy (both places) / the W4.2 provenance label. FIX-LEG 2026-07-24:
    block (e2) + the template scan additionally REJECT any 'settle' framing outside the verbatim honest
    label (the value is a Yahoo quote of the close, never an official settlement)."""
    from leviathan.graphrag import register as reg
    from leviathan.graphrag.numbers import registry as R
    errs: list[str] = []
    doc = _load("numbers/tables.yaml") or {}
    card = (doc.get("tables") or {}).get(_FUTURES_TABLE)
    if not card:
        return [f"futures_lite: {_FUTURES_TABLE} card is absent from numbers/tables.yaml (SEAM C registers it)"]
    # (a) exact levels-only card shape.
    for k, want in _FUTURES_CARD_FIELDS.items():
        if card.get(k) != want:
            errs.append(f"futures_lite: {_FUTURES_TABLE}.{k} is {card.get(k)!r}, expected {want!r}")
    # (b) close is the ONLY whitelisted metric; unit_overrides EXACTLY the 12 slugs with the exact strings.
    metrics = card.get("metrics") or {}
    if set(metrics) != {"close"}:
        errs.append(f"futures_lite: metrics must be close-ONLY (OHLC/volume/derived excluded), got "
                    f"{sorted(metrics)}")
    ov = (metrics.get("close") or {}).get("unit_overrides") or {}
    if ov != _FUTURES_UNIT_OVERRIDES:
        errs.append(f"futures_lite: close.unit_overrides {sorted(ov.items())} != the curated 12-slug set "
                    f"{sorted(_FUTURES_UNIT_OVERRIDES.items())}")
    # (b2) FUTURES v1.5 W1.2 three-way: the transform's SINGLE-SOURCE UNIT_MAP (the authority the physical
    # silver `unit` column is written from) must equal the curated set -- with (b) this binds card ==
    # _FUTURES_UNIT_OVERRIDES == UNIT_MAP, so the physical column and the serving override can never drift
    # (D2 KEEP: unit_overrides stays the serving contract, redundant-but-consistent BY THIS LINT).
    try:
        from leviathan.transforms.raw_to_bronze.yfinance_futures import UNIT_MAP as _unit_map
    except Exception as exc:  # noqa: BLE001 -- a transform import error must surface as a lint failure
        errs.append(f"futures_lite: cannot import the transform UNIT_MAP (single-source unit map): {exc}")
    else:
        if _unit_map != _FUTURES_UNIT_OVERRIDES:
            errs.append(f"futures_lite: transform UNIT_MAP {sorted(_unit_map.items())} != the curated "
                        f"12-slug set {sorted(_FUTURES_UNIT_OVERRIDES.items())} (three-way drift)")
    # (c) whitelist state is intentional: SERVED (whitelisted 2026-07-23) -- removed from WHITELIST_ABSENT_DEFAULT
    # and present in the loaded registry (the agent tool enum + system-prompt cards).
    if _FUTURES_TABLE in R.WHITELIST_ABSENT_DEFAULT:
        errs.append(f"futures_lite: {_FUTURES_TABLE} is whitelisted but STILL in registry.WHITELIST_ABSENT_DEFAULT "
                    f"-- it would be force-dropped from serving (whitelist regression)")
    if _FUTURES_TABLE not in R.load_registry().tables:
        errs.append(f"futures_lite: {_FUTURES_TABLE} is whitelisted but ABSENT from the SERVED registry (agent "
                    f"tool enum) -- the card must load once whitelist-absent is cleared")
    # (d) decline templates register-clean + class set matches the agent's guard.
    try:
        from leviathan.graphrag.numbers import agent as na
    except Exception:  # noqa: BLE001 -- agent import must never break the lint
        na = None
    templates = getattr(na, "FUTURES_DECLINE_TEMPLATES", None) if na is not None else None
    classes = getattr(na, "_FUTURES_DECLINE_CLASSES", ()) if na is not None else ()
    if not templates:
        errs.append("futures_lite: numbers/agent.py FUTURES_DECLINE_TEMPLATES is missing")
    else:
        if set(templates) != set(classes):
            errs.append(f"futures_lite: template keys {sorted(templates)} != decline classes {sorted(classes)}")
        for name, t in templates.items():
            if reg.register_leaks(str(t)) or reg.count_valuation_words(str(t)) or reg.count_flow_words(str(t)):
                errs.append(f"futures_lite: decline template {name!r} carries a register leak")
            # FIX-LEG 2026-07-24 (W4.2 coherence): the served decline prose must never CALL the value a
            # settle -- it is a Yahoo quote of the close, not an official settlement.
            if re.search(r"(?i)settle", str(t)):
                errs.append(f"futures_lite: decline template {name!r} calls the value a settle -- the "
                            f"served value is the front-month close (Yahoo quote), never a settlement")
    # (e) FUTURES v1.5 (2026-07-23): the F010 registry contract carries the additive physical `unit`
    # column + the schema_version 2 bump + the VERSIONED roll-splice policy (provenance.roll_policy),
    # and the card notes carry BOTH the same versioned roll-policy note (W2.2 both-places invariant)
    # and the W4.2/D4a provenance label a served futures [N] must be framed with.
    _reg_path = _REPO / "configs" / "silver" / "tables" / "silver_futures_prices.yaml"
    try:
        contract = yaml.safe_load(_reg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        contract = {}
        errs.append(f"futures_lite: cannot read the F010 registry contract ({exc})")
    if contract:
        cols = {c.get("name"): c for c in (contract.get("physical_columns") or [])}
        ucol = cols.get("unit")
        if not ucol:
            errs.append("futures_lite: registry contract lacks the physical `unit` column (v1.5 W1.1 widen)")
        elif not (ucol.get("glue_type") == "string" and ucol.get("target_arrow_type") == "string"
                  and ucol.get("nullable") is True):
            errs.append(f"futures_lite: registry `unit` column shape drifted: {ucol!r} (want string/string/nullable)")
        if contract.get("schema_version") != 2:
            errs.append(f"futures_lite: registry schema_version is {contract.get('schema_version')!r}, "
                        f"expected 2 (the additive v1.5 unit-widen bump)")
        rp = (contract.get("provenance") or {}).get("roll_policy") or {}
        if rp.get("roll_policy_version") != 1 or "vendor-undocumented" not in str(rp.get("policy") or ""):
            errs.append("futures_lite: registry provenance.roll_policy must carry roll_policy_version=1 and "
                        "the vendor-undocumented splice characterization (W2.2)")
    card_notes = str(card.get("notes") or "")
    if "roll_policy_version: 1" not in card_notes:
        errs.append("futures_lite: card notes must carry the versioned roll-splice policy "
                    "('roll_policy_version: 1') mirroring registry provenance.roll_policy (W2.2)")
    card_text = f"{card.get('description') or ''} {card_notes}"
    if "Yahoo Finance continuous front-month close (not official exchange settlement)" not in card_text:
        errs.append("futures_lite: card text must carry the verbatim provenance label 'Yahoo Finance "
                    "continuous front-month close (not official exchange settlement)' (W4.2, D4a)")
    # (e2) FIX-LEG 2026-07-24: the card must never CALL the served value a settle. The only permitted
    # 'settle*' token in the model-facing fields (description / grain / close.desc / notes) is the one
    # inside the verbatim W4.2 honest label itself -- the positive substring check above let
    # 'front-month settle' prose sit beside the not-a-settlement label (self-contradiction); this
    # negative check closes that gap.
    _honest_label = "Yahoo Finance continuous front-month close (not official exchange settlement)"
    model_text = " ".join((
        str(card.get("description") or ""), str(card.get("grain") or ""),
        str((metrics.get("close") or {}).get("desc") or ""), card_notes,
    )).replace(_honest_label, " ")
    if re.search(r"(?i)settle", model_text):
        errs.append("futures_lite: card text still calls the served value a settle outside the honest "
                    "provenance label -- reword to 'close (Yahoo quote)' (W4.2: the value is a Yahoo "
                    "quote, never an official settlement)")
    return errs


def main() -> int:
    failures = 0
    for label, errs in (("vocab", lint_vocab()), ("node_silver_map", check_node_silver_map()),
                        ("hierarchy", check_hierarchy()), ("geography", check_geography()),
                        ("display_names", check_display_names()),
                        ("display_vocab", check_display_vocab()),
                        ("cascade_map", check_cascade_map()),
                        ("chain_map", check_chain_map()),
                        ("complex_map", check_complex_map()),
                        ("transmission_map", check_transmission_map()),
                        ("pin_realizability", check_pin_realizability()),
                        ("driver_slices", check_driver_slices()),
                        ("edge_blurbs", check_edge_blurbs()),
                        ("price_register", check_price_register()),
                        ("quarantine", check_quarantine()),
                        ("numbers_schema_pins", check_numbers_schema_pins()),
                        ("esr_destinations", check_esr_destinations()),
                        ("cot_register", check_cot_register()),
                        ("stats_registry", check_stats_registry()),
                        ("futures_lite", check_futures_lite())):
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
