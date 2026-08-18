"""GraphRAG Phase 1 config validators — the W3/W5 exit gate, as code.

Public code; it reads the git-ignored ``configs/graphrag/`` IP at runtime. Two checks:

  * **vocab linter** — no surface form is both a node and an edge; arbitration targets resolve
    to real roles; aliases point at real canonical nodes; node/edge name hygiene.
  * **node_silver_map resolver** — every metric's (table, column) actually exists in the silver
    Athena DDLs (``sql/athena/ddl/``), so silver-confirmation (§4.3) isn't hand-wave.

    python -m leviathan.graphrag.config_check        # exits non-zero on any failure
"""
from __future__ import annotations

import os
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
# OUTCOMES_JOIN D-OJ-18 (2026-08-01): `gold_cot_outcomes` -- the J6 COT-keyed outcome card -- is fenced
# from the day the lane exists, not from the day its rows do. This edit is ATOMIC with the same id
# joining `cascade.POSITIONING_TABLES`: the drift pin in `_check_positioning_lane` fails the build if
# only one of the two moves, which is deliberate, and is the cheapest proof the fence grips the new
# table. Fencing it is the point of giving it a separate id at all -- R7b bars a "% move over N days"
# unit from the `silver_cot` card, and the tempting conclusion (serve it from a table outside the set)
# would satisfy R9's letter while vacating the context-shape rule, the never-a-chain-hop ban and the
# never-a-relative-value-leg ban together (skeptic F11).
POSITIONING_TABLES = ("silver_cot", "gold_cot_outcomes")
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
# CAP RE-DECISION 2026-07-25 (user-directed, follows the judged30 3/30 firing-funnel census): the v1
# caps (7/25) were SATURATED by the ratified v1 set, deferring the three El_Nino family rows (SA maize,
# sugar, robusta -- 5 contracts). Raised 7->10 rows / 25->29 expansions to activate exactly that roster;
# the caps re-saturate at the new set by design (the NEXT expansion needs its own re-decision).
_CHAIN_MAX_ROWS = 10
_CHAIN_MAX_EXPANSIONS = 29
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
    have greenlit q6's original undeclared pin (soybean_oil_cbot rolls up TRUE via export/stock/oni/fx).

    C1 item 4(b) (2026-08-01), THE FAIL-OPEN THIS LINT SHIPPED WITH. A declared id that resolves to NO
    driver on the contract read as "not fireable" and therefore silently GREENED every `cascade_fired:
    false` pin -- `driver_fireable` returns False at the `_driver(...) is None` gate, before map_row is
    ever consulted. `positioning_corn_no_fork` declared `cot_mm_positioning`, which is a SILVER_REF and not
    a driver id (corn's driver is `managed_money_positioning`, carrying that ref), and the mis-declaration
    survived for the whole life of the pin. An unresolvable id is now an ERROR: the lint this plan leans on
    as its safety mechanism must not be able to pass by not understanding the question.

    LANE AWARENESS, and it is narrow. The stale-negative arm compares pure TOPOLOGY against an OUTCOME pin,
    which is only a valid comparison on a lane where the cascade engine can run at all. It cannot on
    `expected_intent: numbers_only` -- run_numbers_only calls the agent and never reaches _answer_l2, so
    `cascade_fired` is false there whatever the map holds. Without this, D1's context ref (which makes
    corn's positioning driver topologically fireable) would red a pin that is correct by construction. The
    stale-POSITIVE arm is unaffected: a numbers_only row pinning `cascade_fired: true` is still an error,
    and the more so."""
    from leviathan.graphrag.numbers import cascade_census as cc
    doc = _load("eval_queries_v4_cascade.yaml") or {}
    errs: list[str] = []
    for q in (doc.get("queries") or []):
        exp = q.get("expect") or {}
        if "cascade_fired" not in exp:
            continue
        pin = bool(exp["cascade_fired"])
        contract = q.get("contract") or ""
        for did in (q.get("cascade_drivers") or []):
            if cc._driver(contract, str(did)) is None:
                errs.append(f"pin_realizability {q.get('id')!r} ({contract}): declared cascade_driver "
                            f"{str(did)!r} resolves to NO driver on that contract -- a silver_ref or a "
                            f"typo, not a driver id. driver_fireable returns False at the _driver gate, so "
                            f"the pin would read 'not fireable' for a reason that has nothing to do with "
                            f"the map (C1 4b: the fail-OPEN in this lint)")
        engine_lane = str(q.get("expected_intent") or "") != "numbers_only"
        realizable = cc.query_realizable(q)
        if realizable is None:
            errs.append(f"pin_realizability {q.get('id')!r} ({q.get('contract')}): pins cascade_fired but "
                        f"declares no `cascade_drivers` -- the per-query grounded set is unknown and the "
                        f"contract rollup is not a substitute (fail-closed); declare the driver ids the "
                        f"question grounds")
        elif (not pin) and realizable and not engine_lane:
            pass                    # numbers_only: the engine cannot run, so topology cannot contradict it
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


# W5.0 outlook-fence probes. The A1/A2 partition of detector A is the load-bearing decision of the wave, so
# it is asserted at BUILD TIME rather than trusted to a prompt paragraph -- a prompt-only fence is one
# paraphrase from failing. Every probe below is a real sentence a model could emit on an outlook turn.
_OUTLOOK_A2 = (                                        # EXECUTION/ADVICE -- refused under EVERY register
    "take-profit here", "a stop-loss below 240", "go long soyoil", "buy the dip", "fade the rally",
    "worth fading", "a relative value trade", "at attractive levels", "this is a good level to buy",
    "a good time to buy", "attractive entry", "the entry point is 240", "buying opportunity",
    "coffee is a buy", "a buy at 240", "load up", "accumulate here",
    "size the position at 2% risk", "position sizing of 3 lots", "the risk/reward is 3:1",
    "set your exit level at 300", "scale in below 240", "trim the position into strength",
    "initiate a long here", "you should buy soybeans", "should you buy here",
    "now is the time to buy", "i'd be long here", "we recommend going long",
    # (c) THE CORPUS WRITTEN BY SOMEONE WHO DID NOT READ THE LEXICON (fold-pass 2026-07-30). Every probe
    # above was a verbatim member of `_EXEC_PHRASES`, so the lint only ever proved the regex matched
    # itself. These are the shapes a COMPLETE trade plan actually uses, and a measured run of all seven
    # through the real path returned banned_exec == 0 and served the plan VERBATIM under OUTLOOK.
    "buy at 240", "stop at 218", "first target is 268", "size at 2% of nav",
    "risk 22 points to make 28", "i'd be a buyer here", "we like it here and would add")
_OUTLOOK_A1 = (                                        # VALUATION -- fenced today, PERMITTED under outlook
    "raise the price target", "the spread looks cheap", "undervalued", "overvalued", "mispriced",
    "dislocated", "overdone", "overshot", "fair value", "it screens rich")
_OUTLOOK_C = (                                         # forward-convergence -- fenced under BOTH registers
    "the premium should converge next quarter", "the discount has room to normalize",
    "due for a correction", "mean reversion favors the discount narrowing")
# A COMPLETE derivation: spot anchor cited, episode moves cited, arithmetic shown. Levels are legal here.
_OUTLOOK_DERIVED = (
    "Spot 227.25 EUR/t (Sep-26 settle) [N1]. Three comparable episodes moved +18% / +7% / -3% over 90 "
    "days [E2] -> 268 / 243 / 220; median 243. The 2010 case reversed inside the window.")
# The SAME claim with the derivation removed -- a bare number. Under W5.0 this is a REFUSAL, and it is the
# single probe that proves the gate is about DERIVATION and not about vocabulary.
_OUTLOOK_BARE = "Coffee should reach 268 by year end. We see 243 as the base case."
# (a) FOUR-DIGIT BARE TARGETS, one per quote convention. Every level in the two probes above is 3-digit or
# decimal, which is exactly why the old `\d{1,3}(?:,\d{3})*` token regex passed this lint while being blind
# to soybeans/rough rice (cents ~1000-1800), cocoa (USD/t 2000-12000), MCPO (MYR/t ~3500-4500) and palm
# olein (CNY/t ~7000-9000) -- the MAJORITY of the platform's contracts.
_OUTLOOK_BARE_4D = (
    ("Soybeans should reach 1450 by January.", "1450"),
    ("Cocoa prints 8500 on any further Ivorian shortfall.", "8500"),
    ("Palm olein trades up to 7200 into the seasonal low.", "7200"),
    ("MCPO settles at 4250 once stocks draw.", "4250"),
    ("Rough rice works back to 1,850 on the export ban.", "1,850"),
    ("Coffee holds 1015.5 through the harvest.", "1015.5"))
# (b) A TWO-SECTION probe: a COMPLETE derivation under '## Outlook' beside a BARE level in '## Mechanism'.
# The derivation must not back the other section -- the laundering `outlook_unit`'s own docstring forbids.
_OUTLOOK_CROSS_SECTION = (
    "## Mechanism\nOur fair value is 310.5 on the current balance sheet.\n\n"
    "## Outlook\nSpot 227.25 EUR/t (Sep-26 settle) [N1]. Three episodes moved +18% / +7% / -3% "
    "[E2] -> 268 / 243 / 220; median 243.")


def _check_outlook_fence() -> list[str]:
    """W5.0 derivation gate + the A1/A2 partition, asserted deterministically at build time.

    Four properties, each of which would silently rot if only the prompt enforced it:
      1. A2 execution idioms are refused under BOTH registers (nothing can back an execution instruction).
      2. A1 valuation is fenced by default and PERMITTED under outlook (the relaxation actually happened).
      3. Detector C stays fenced under both (an outlook leans on regimes and buffers, not convergence).
      4. A derived level survives WITH its derivation and is REFUSED without it."""
    from leviathan.graphrag import register as reg
    errs: list[str] = []
    for probe in _OUTLOOK_A2:
        if not reg.exec_leaks(probe):
            errs.append(f"W5 A2: execution probe not detected: {probe!r}")
        for mr in (reg.FENCED, reg.OUTLOOK):
            if probe in reg.sanitize(probe + ". Ending stocks fell [N1].", market_register=mr):
                errs.append(f"W5 A2: execution probe SURVIVED sanitize(market_register={mr!r}): {probe!r}")
    for probe in _OUTLOOK_A1:
        if not reg.register_leaks(probe):
            errs.append(f"W5 A1: valuation probe not detected at all: {probe!r}")
        if probe in reg.sanitize(probe + ".", market_register=reg.FENCED):
            errs.append(f"W5 A1: valuation probe survived the FENCED strip: {probe!r}")
        if probe not in reg.sanitize(probe + " [E1].", market_register=reg.OUTLOOK):
            errs.append(f"W5 A1: valuation probe was NOT released under outlook: {probe!r}")
    for probe in _OUTLOOK_C:
        for mr in (reg.FENCED, reg.OUTLOOK):
            if probe in reg.sanitize(probe + ".", market_register=mr):
                errs.append(f"W5 C: convergence probe survived sanitize(market_register={mr!r}): {probe!r}")
    if not reg.outlook_derivation_ok(_OUTLOOK_DERIVED):
        errs.append("W5 derivation gate: the COMPLETE worked example did not register as derived")
    if "268" not in reg.sanitize(_OUTLOOK_DERIVED, market_register=reg.OUTLOOK):
        errs.append("W5 derivation gate: a level with its derivation shown was WRONGLY stripped")
    if reg.unbacked_level_count(_OUTLOOK_DERIVED):
        errs.append("W5 derivation gate: a fully derived level counted as unbacked")
    if reg.outlook_derivation_ok(_OUTLOOK_BARE):
        errs.append("W5 derivation gate: a BARE level registered as derived (the gate fails OPEN)")
    if "268" in reg.sanitize(_OUTLOOK_BARE, market_register=reg.OUTLOOK):
        errs.append("W5 derivation gate: a BARE level survived the outlook strip -- a refusal was expected")
    if reg.unbacked_level_count(_OUTLOOK_BARE) < 1:
        errs.append("W5 derivation gate: a BARE level was not counted (price_target_backed would false-pass)")
    for probe, level in _OUTLOOK_BARE_4D:              # (a) the 4-digit blind spot, per quote convention
        if not reg.unbacked_level_count(probe):
            errs.append(f"W5 derivation gate: 4-digit bare level NOT counted: {probe!r}")
        if level in reg.sanitize(probe, market_register=reg.OUTLOOK):
            errs.append(f"W5 derivation gate: 4-digit bare level SURVIVED the outlook strip: {probe!r}")
    # (b) a complete derivation under '## Outlook' must NOT back a level minted in another section
    if not reg.outlook_derivation_ok(_OUTLOOK_CROSS_SECTION):
        errs.append("W5 derivation gate: the cross-section probe's '## Outlook' derivation did not register")
    _cross = reg.sanitize(_OUTLOOK_CROSS_SECTION, market_register=reg.OUTLOOK)
    if "310.5" in _cross:
        errs.append("W5 derivation gate: an out-of-unit bare level was LAUNDERED by the '## Outlook' unit")
    if "268" not in _cross:
        errs.append("W5 derivation gate: the in-unit derived level was wrongly stripped")
    if not reg.unbacked_level_count(_OUTLOOK_CROSS_SECTION):
        errs.append("W5 derivation gate: an out-of-unit bare level was not COUNTED (pin would false-pass)")
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
    # W5.0: the A1/A2 partition + the derivation gate, likewise before any flag. The outlook relaxation is
    # only ever as safe as this check -- it is what proves A2 is still refused on the turn where A1 opened.
    errs += _check_outlook_fence()
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
                getattr(ts, "metric_col", None), getattr(ts, "value_col", None), getattr(ts, "unit_col", None),
                # W3.1: the per-expiry price dimensions ride the same card-vs-DDL pin as unit_col -- a
                # renamed contract_month/settle_kind/currency column would otherwise only surface as a
                # live COLUMN_NOT_FOUND (the silver_nasa_power incident this lint was born from).
                getattr(ts, "contract_month_col", None), getattr(ts, "settle_kind_col", None),
                getattr(ts, "currency_col", None)}
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
    """SILVER-F047 -- no engine map may ever reference a quarantined table (TableSpec.quarantined): the
    cascade weather leg moved to gold_weather_z at Phase D-W4 and INV-3 forbids re-adding an engine leg on
    the LIST-storm projection. Build-failing, not prose.

    D-LD TRACK 2 #5 (2026-08-18) RETIRES THIS DOCSTRING'S OLD OPENING CLAUSE ("keeps serving DIRECT agent
    lookups"). `registry.visible_tables` now strips quarantined cards from the agent tool enum, the
    system-prompt cards and the planner family enum, so the model can no longer name one; the card stays
    LOADED, so programmatic `reg.get`/`build_sql` lookups -- and this lint, which reads the loaded registry
    -- are unchanged. This check is unaffected either way: it is about ENGINE MAPS, not visibility."""
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


def _check_positioning_lane() -> list[str]:
    """R9 AS AMENDED (D1, ratified 2026-08-01) -- the context/engine SPLIT, not a blanket ban.

    R9 used to be `_check_no_engine_ref(load_map(), POSITIONING_TABLES, ...)`: ANY cascade_map ref at a
    positioning table failed the build. That conflated two things the registry's own prose already
    distinguished -- positioning narrated past-tense as CONTEXT, and positioning driving a forecast or a
    fork -- and it left `cascade.PACE_TABLES["silver_cot"]` with no door at all. R9 now bans the ENGINE
    lanes precisely and admits the CONTEXT lane, still fail-closed on both halves:

      (a) cascade_map -- a positioning ref is admitted ONLY as the narrow past-tense context leg. The
          shape rule is `cascade.positioning_context_violations` (ONE definition, which the engine's own
          runtime gate reads too), so the lint and the engine can never disagree about what "context"
          means. Every clause of it closes a named fork/regime code path, not a style preference.
      (b) chain_map / complex_map / transmission_map -- no positioning ref, ever. Those maps name a
          cascade_map ref BY NAME, so the ban is on the NAME: a hop or a relative-value leg is an engine
          position whatever shape the underlying row has.

    R4 (pink sheet, :1029), R7 and R10 are UNTOUCHED. What R9 no longer does is fail the build merely
    because the ref exists. NOTE, so a future reader does not read more into this than it says: the
    causal DAGs' positioning drivers are convergence-regime members TODAY (e.g. arabica_coffee's
    `cot_mm_positioning` sits in a `convergence[].drivers` list), and they stay that way -- `graph.regimes`
    fires on ACTIVE DRIVER IDS and never reads any numbers map, so that membership is invisible to R9 in
    both directions. "Never a regime driver" here means the numbers-map REGIME-MARKER lane (a
    `narrate_unit: flag` row), which is the only regime surface a cascade_map ref can occupy."""
    from leviathan.graphrag import complex_map as cxm
    from leviathan.graphrag.numbers import cascade as csc
    errs: list[str] = []
    # ONE fenced set. The engine gate cannot import config_check (a cycle -- cascade's own _PRICE_TABLES
    # note documents why), so the constant is mirrored there and pinned HERE: a table in one and not the other is
    # a build failure, not a silent half-fence. Mirrors orchestrator._positioning_tables' drift pin.
    if frozenset(POSITIONING_TABLES) != csc.POSITIONING_TABLES:
        errs.append(f"R9 drift: config_check.POSITIONING_TABLES {tuple(POSITIONING_TABLES)!r} != "
                    f"cascade.POSITIONING_TABLES {tuple(sorted(csc.POSITIONING_TABLES))!r} -- the build "
                    f"fence and the engine gate must fence the SAME tables")
    cmap = csc.load_map() or {}
    pos_refs = {ref for ref, row in cmap.items() if (row or {}).get("table") in POSITIONING_TABLES}
    for ref in sorted(pos_refs):
        for why in csc.positioning_context_violations(cmap[ref]):
            errs.append(f"R9 cascade_map {ref!r}: positioning is admitted ONLY as a fetched past-tense "
                        f"context leg -- {why}")
    for chain in (csc.load_chain_map() or []):
        for hop in ((chain or {}).get("hops") or []):
            if (hop or {}).get("ref") in pos_refs:
                errs.append(f"R9 chain_map {(chain or {}).get('id')!r}: hop ref {(hop or {}).get('ref')!r} "
                            f"is a positioning ref -- positioning is never a chain hop")
    pos_pairs: set = set()
    for p in cxm.iter_all_pairs():                        # ALL authored pairs, material or not: a parked
        for lbl, side in (("sideA", p.side_a), ("sideB", p.side_b)):   # row must not ship pre-loaded either
            if (side or {}).get("ref") in pos_refs:
                pos_pairs.add(p.id)
                errs.append(f"R9 complex_map {p.id!r}: {lbl} ref {(side or {}).get('ref')!r} is a "
                            f"positioning ref -- positioning is never a relative-value leg")
    for chain in (csc.load_transmission_map() or []):
        for lk in ((chain or {}).get("links") or []):
            if (lk or {}).get("pair_id") in pos_pairs:
                errs.append(f"R9 transmission_map {(chain or {}).get('id')!r}: link pair "
                            f"{(lk or {}).get('pair_id')!r} carries a positioning leg -- positioning is "
                            f"never a transmission hop")
    return errs


# OUTCOMES_JOIN D-OJ-18. The J6 card id, and the ONE unit family admitted on it. Percent only, and the
# omission is deliberate: `move_abs` is a change in the exchange's own price units, and a level in price
# units rendered beside a positioning row is a price quote on the positioning lane -- which is what R4
# fences `silver_pink_sheet` for. The percent move is scale-free and reads as a record; the absolute one
# reads as a quote. If the absolute move is ever wanted here it arrives with its own decision.
_COT_OUTCOME_TABLE = "gold_cot_outcomes"
_COT_OUTCOME_UNITS = frozenset({"%"})


def _raw_card_spec(table_id: str):
    """The card as a `TableSpec`, read from the RAW registry file (or the staged card path), or None.

    NOT `load_registry()`. That call drops every id in `registry.WHITELIST_ABSENT_DEFAULT`, which is
    where a table registered ahead of its producer lives -- so reading the lint's subject through it
    would make the fence disarm the check that guards it (adversarial finding 14). The card's fields
    are what compile into SQL whether or not the id is currently served, so the lint reads the file.
    An unreadable/partial card yields None: this helper never turns a config problem into a crash."""
    try:
        from leviathan.graphrag.numbers.registry import TableSpec
        served = _CFG / "numbers" / "tables.yaml"
        raw = None
        if served.exists():
            doc = yaml.safe_load(served.read_text(encoding="utf-8")) or {}
            raw = (doc.get("tables") or {}).get(table_id)
        if raw is None:
            staged = _CFG / "numbers" / "cards" / f"{table_id}.yaml"
            if staged.exists():
                doc = yaml.safe_load(staged.read_text(encoding="utf-8")) or {}
                raw = (doc.get("tables") or {}).get(table_id)
        if not raw:
            return None
        return TableSpec(id=table_id, **raw)
    except Exception:  # noqa: BLE001 -- an unreadable card is a lint miss, never a build crash
        return None


def _check_cot_outcome_metrics(card, reg, st) -> list[str]:
    """R7b as extended to the J6 card. Vacuous (and says nothing) until the card EXISTS -- read from the
    raw registry file by `_raw_card_spec`, so the whitelist-absent fence cannot blind it."""
    if card is None:
        return []
    errs: list[str] = []
    for mname, m in (card.metrics or {}).items():
        if reg.count_valuation_words(m.desc) or reg.count_flow_words(m.desc):
            errs.append(f"R7 {_COT_OUTCOME_TABLE}.{mname}: metric desc carries a banned "
                        f"valuation/flow word")
        if st.is_banned_name(mname):
            errs.append(f"R7 {_COT_OUTCOME_TABLE}.{mname}: metric name is forward-looking "
                        f"(fit|trend|forecast|project|extrapolat|predict) -- an outcome table is the one "
                        f"surface where a forecast-shaped column would look natural, and it is not")
        if m.unit not in _COT_OUTCOME_UNITS:
            errs.append(f"R7 {_COT_OUTCOME_TABLE}.{mname}: unit {m.unit!r} is not in the admitted set "
                        f"{sorted(_COT_OUTCOME_UNITS)} -- the positioning lane serves the SCALE-FREE "
                        f"move; a change in exchange price units is a quote, which R4 fences")
    return errs


def check_cot_register() -> list[str]:
    """PRICE_OBSERVABILITY W0.2 (the W4 gate) -- positioning-table fence. R9 (AMENDED by D1, see
    `_check_positioning_lane`): a positioning ref may enter cascade_map ONLY as the narrow past-tense
    context leg, and may never enter chain_map / complex_map / transmission_map. R7: silver_cot metric
    descs register-clean AND every metric limited to a dated level/z family (no forward-looking name).
    R10: the suggester's answerable-fundamentals catalog source (server._SUGGEST_METRICS) names no
    positioning-table metric. R7/R10 go NON-VACUOUS once silver_cot is registered.

    R7b-OUTCOMES (OUTCOMES_JOIN D-OJ-18): the J6 card `gold_cot_outcomes` carries a unit R7b's level/z
    families cannot admit, and the whole reason it is a separate card is that R7b is right to refuse a
    "% move over N days" on the silver_cot card. So the unit is admitted BY NAME, on THIS card only, and
    the forward-looking-name ban still applies -- an admitted unit that was never written down is the
    same fail-open in a different costume. Checked BEFORE the silver_cot early return, so it is not
    silently skipped on a build where silver_cot is unregistered."""
    from leviathan.graphrag import register as reg
    from leviathan.graphrag.numbers import stats as st
    from leviathan.graphrag.numbers.registry import load_registry
    errs: list[str] = _check_positioning_lane()
    tables = load_registry().tables
    errs += _check_cot_outcome_metrics(_raw_card_spec(_COT_OUTCOME_TABLE), reg, st)
    cot = tables.get("silver_cot")
    if cot is None:
        return errs   # R7/R10 vacuous until W4 registers silver_cot
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


# PRICE_AND_PLAYBOOKS W1.0 (2026-07-28) -> W3 (2026-07-30) -- silver_futures_eod, the per-delivery-month
# futures EOD table. Structural descendant of check_futures_lite. Clause (c) was the FENCE for all of
# W1.0/W1/W2 (the table had to be whitelist-absent and absent from the served registry, so a whitelist
# flip could never happen by accident -- only by editing the lint and the fence together). At the W3 flip
# it was INVERTED IN PLACE rather than deleted: it now pins the table as SERVED plus the REACHABILITY
# TRIO, because "served" on its own is the weaker claim. A card sitting in the tool enum whose
# delivery-month parameter the SCHEMA never declares answers every December ask with the nearest listed
# expiry, silently; a router whose purpose string never names the curve leaves the capability
# unreachable; a card that stops declaring settle_kind_col lets an ICE session close be cited as an
# official settlement. Those three plus the flip are ONE change, and this clause is what holds them
# together.
#
# The core is the THREE-WAY unit bind, generalized from the v1.5 lesson. The single source is
# leviathan.silver.futures_eod_contracts.CONTRACT_MAP, which is dict[slug, {unit, currency, settle_kind,
# source}] -- RICHER than the card's dict[slug, str] -- so the bind is a PROJECTION equality (UNIT_MAP)
# rather than a dict equality: map-projection == this tracked constant == card unit_overrides.
#
# What is NOT copied from check_futures_lite: its blanket `settle` token ban. That ban exists because the
# yfinance value is NEVER a settlement. Here some sources DO publish a true settlement, so the honest
# check is a VOCABULARY + COHERENCE one on the settle_kind column instead: the four legal values, and the
# 1:1 source -> settle_kind cross-tab the plan's post-ship verification asserts on real data.
_FUTURES_EOD_TABLE = "silver_futures_eod"
_FUTURES_EOD_SETTLE_KINDS: frozenset = frozenset({"settlement", "mark_to_market", "cash_index", "close"})
_FUTURES_EOD_SOURCES: frozenset = frozenset({
    "databento_glbx_mdp3", "databento_ifus_impact", "databento_ifeu_impact",
    "czce", "jse_safex", "cepea", "bursa", "miax", "euronext_matif", "dce",
})
_FUTURES_EOD_CARD_FIELDS: dict = {
    "shape": "wide", "commodity_col": "leviathan_slug", "date_col": "trade_date",
    "date_col_type": "timestamp", "knowledge_semantics": "data_date",
    "knowledge_date_col": "trade_date", "publication_lag_days": 1,
    # period_type is pinned like every other PIT field: it decides the grain rank the cascade/chain
    # lints compare hops on, so an unpinned value could drift to month/annual without failing a build.
    "period_type": "date",
    "grain_cols": ["leviathan_slug", "contract_month", "trade_date"],
    # W3.1 SERVED DIMENSIONS + the physical partition layout. Pinned HERE because this is the ONLY lint
    # that reads the RAW card while the table is registry-fenced: check_numbers_schema_pins iterates
    # load_registry().tables, from which WHITELIST_ABSENT_DEFAULT drops silver_futures_eod, so its
    # card-vs-DDL pin on these columns is INERT until the W3 whitelist flip. Without these five keys an
    # edit that dropped settle_kind_col would leave every lint green while an ICE ohlcv-1d session CLOSE
    # started being cited as an official settlement -- the card's own notes call that label "not
    # decorative". partition_cols/year_col are pinned for the same reason on the other side: they decide
    # whether trade_year compiles as a sargable BOUND or (wrongly) as a static equality that would zero
    # out every historical read.
    "contract_month_col": "contract_month",
    "settle_kind_col": "settle_kind",
    "currency_col": "currency",
    "partition_cols": ["leviathan_slug", "trade_year"],
    "year_col": "trade_year",
}
# The tracked copy of the serving unit contract: 31 contract slugs -> exchange-convention unit string.
# Bound to CONTRACT_MAP and to the card by check_futures_eod (drift any direction fails the build).
_FUTURES_EOD_UNIT_OVERRIDES: dict = {
    "corn_cbot": "US cents/bushel", "soybeans_cbot": "US cents/bushel",
    "soft_red_winter_wheat_cbot": "US cents/bushel", "hard_red_winter_wheat_kcbt": "US cents/bushel",
    # MIAX publishes decimal DOLLARS/bushel (MWEU6 = 7.0250), not CBOT cents (~430) -- a factor of
    # 100. Source-faithful wins and the value is never scaled to fit a prior guess (CAD/t precedent).
    "hard_red_spring_wheat_mgex": "USD/bushel", "soybean_oil_cbot": "US cents/lb",
    "arabica_coffee": "US cents/lb", "cotton": "US cents/lb", "raw_sugar": "US cents/lb",
    "frozen_orange_juice": "US cents/lb", "soybean_meal_cbot": "USD/short ton",
    "cocoa": "USD/metric ton", "robusta_coffee": "USD/metric ton", "white_sugar": "USD/metric ton",
    "rough_rice_cbot": "USD/cwt", "canola_ice": "CAD/t",
    "french_wheat_matif": "EUR/t", "french_maize_matif": "EUR/t", "french_rapeseed_matif": "EUR/t",
    "rapeseed_meal_zce": "CNY/t", "rapeseed_oil_zce": "CNY/t", "palm_olein_dce": "CNY/t",
    "soybean_meal_dce": "CNY/t", "soybean_oil_dce": "CNY/t", "soybeans_no_1_dce": "CNY/t",
    "soybeans_no_2_dce": "CNY/t", "malaysian_crude_palm_oil_cme": "MYR/t",
    "south_african_white_maize_jse": "ZAR/t", "south_african_yellow_maize_jse": "ZAR/t",
    "brazilian_arabica_coffee": "BRL/60-kg bag", "campinas_corn_reference_bmf": "BRL/60-kg bag",
}


def check_futures_eod() -> list[str]:
    """W1.0 per-delivery-month EOD lint (AWS-free, pure). Card shape + settle-only metrics + the THREE-WAY
    unit bind (CONTRACT_MAP projection == tracked constant == card unit_overrides) + the settle_kind /
    source / currency vocabularies + the 31-slug completeness check against configs/commodities/ + the
    SERVED gate state and its REACHABILITY TRIO (W3 flip 2026-07-30: whitelist-present, loaded into the
    served registry, `contract_month` declared in the numbers tool schema describing BOTH forms, the
    dispatch `numbers` purpose naming the term structure / curve, and the card declaring the three served
    dimensions) + the F010 registry contract pins (registered, projection forbidden, registered-partition
    write mode, the declared column order and the four contract-non-null label columns, and NO
    roll/continuous column ever)."""
    from leviathan.graphrag.numbers import registry as R
    from leviathan.silver import futures_eod_contracts as FC
    errs: list[str] = []
    doc = _load("numbers/tables.yaml") or {}
    card = (doc.get("tables") or {}).get(_FUTURES_EOD_TABLE)
    if not card:
        return [f"futures_eod: {_FUTURES_EOD_TABLE} card is absent from numbers/tables.yaml "
                f"(PRICE_AND_PLAYBOOKS W1.0 registers it)"]

    # (a) exact card shape -- the PIT fields the F010 reconcile binds 1:1 against the registry contract.
    for k, want in _FUTURES_EOD_CARD_FIELDS.items():
        if card.get(k) != want:
            errs.append(f"futures_eod: {_FUTURES_EOD_TABLE}.{k} is {card.get(k)!r}, expected {want!r}")
    # levels_only would be WRONG here: a per-expiry series carries no roll splice, so a cross-date delta
    # on one delivery month is legitimate (unlike the continuous flat table).
    if card.get("levels_only"):
        errs.append("futures_eod: levels_only must stay false -- per-delivery-month series carry no roll "
                    "splice, so cross-date reads are legitimate (that guard belongs to the flat table)")

    # (b) settle is the ONLY served metric; unit_overrides == the tracked constant.
    metrics = card.get("metrics") or {}
    if set(metrics) != {"settle"}:
        errs.append(f"futures_eod: metrics must be settle-ONLY (OHLC/volume/open_interest are carried for "
                    f"provenance but NULL by construction on settle-only sources), got {sorted(metrics)}")
    ov = (metrics.get("settle") or {}).get("unit_overrides") or {}
    if ov != _FUTURES_EOD_UNIT_OVERRIDES:
        errs.append(f"futures_eod: settle.unit_overrides {sorted(ov.items())} != the curated 31-slug set "
                    f"{sorted(_FUTURES_EOD_UNIT_OVERRIDES.items())}")

    # (b2) THE THREE-WAY BIND: the SINGLE-SOURCE map's unit projection must equal the tracked constant.
    # With (b) this binds CONTRACT_MAP == _FUTURES_EOD_UNIT_OVERRIDES == card, so the physical `unit`
    # column (written from CONTRACT_MAP) and the serving override can never drift.
    if FC.UNIT_MAP != _FUTURES_EOD_UNIT_OVERRIDES:
        errs.append(f"futures_eod: futures_eod_contracts.UNIT_MAP {sorted(FC.UNIT_MAP.items())} != the "
                    f"curated 31-slug set {sorted(_FUTURES_EOD_UNIT_OVERRIDES.items())} (three-way drift)")

    # (b3) the map covers EXACTLY the registry contract slugs -- what makes "31" auditable rather than
    # aspirational (the set(UNIT_MAP) == set(TICKER_MAP) analogue).
    # NO `if slugs and ...` short-circuit: an absent/emptied configs/commodities/ (a trimmed image, a
    # bad cwd) would make the completeness assertion vanish silently, which is precisely the
    # "aspirational rather than auditable" state it exists to prevent. Empty is an ERROR.
    slugs = {p.stem for p in (_REPO / "configs" / "commodities").glob("*.yaml")}
    if not slugs:
        errs.append(f"futures_eod: configs/commodities/ yielded NO contract yaml under {_REPO} -- the "
                    f"31-slug completeness check cannot run, and silently skipping it is how "
                    f"CONTRACT_MAP drifts from the contract registry")
    elif set(FC.CONTRACT_MAP) != slugs:
        missing = sorted(slugs - set(FC.CONTRACT_MAP))
        extra = sorted(set(FC.CONTRACT_MAP) - slugs)
        errs.append(f"futures_eod: CONTRACT_MAP does not cover exactly the contract registry "
                    f"(missing={missing}, extra={extra})")
    # (b4) vocabularies: settle_kind / source / unit / ISO-4217 currency, per record.
    errs += [f"futures_eod: {e}" for e in FC.lint_map()]
    kinds = {rec["settle_kind"] for rec in FC.CONTRACT_MAP.values()}
    if not kinds <= _FUTURES_EOD_SETTLE_KINDS:
        errs.append(f"futures_eod: settle_kind vocabulary drift {sorted(kinds - _FUTURES_EOD_SETTLE_KINDS)}")
    srcs = {rec["source"] for rec in FC.CONTRACT_MAP.values()}
    if not srcs <= _FUTURES_EOD_SOURCES:
        errs.append(f"futures_eod: source vocabulary drift {sorted(srcs - _FUTURES_EOD_SOURCES)}")
    # a source must map to exactly ONE settle_kind -- the cross-tab the plan's post-ship verification
    # asserts on real rows; enforcing it on the MAP means a mislabeled row can never be authored.
    by_source: dict = {}
    for slug, rec in sorted(FC.CONTRACT_MAP.items()):
        by_source.setdefault(rec["source"], set()).add(rec["settle_kind"])
    for src, ks in sorted(by_source.items()):
        if len(ks) != 1:
            errs.append(f"futures_eod: source {src!r} maps to MULTIPLE settle_kinds {sorted(ks)} -- the "
                        f"source -> settle_kind cross-tab must stay 1:1")
    # cash_index is the ONLY settle_kind that may carry a NULL contract_month, so it must be exactly the
    # CEPEA pair (the instrument_kind discriminator, plan line 121).
    if FC.CASH_INDEX_SLUGS != frozenset({"brazilian_arabica_coffee", "campinas_corn_reference_bmf"}):
        errs.append(f"futures_eod: cash_index slugs {sorted(FC.CASH_INDEX_SLUGS)} != the two CEPEA cash "
                    f"references -- only those rows may carry contract_month IS NULL")

    # (c) THE SERVED STATE + THE REACHABILITY TRIO (W3 flip, 2026-07-30 -- this clause used to pin the
    # inverse). Whitelisted means: NOT in WHITELIST_ABSENT_DEFAULT and PRESENT in the loaded registry
    # (the agent tool enum + system-prompt cards). Re-adding the entry now would force-drop a table whose
    # producers, gates and coverage guard are all live -- a whitelist regression, failed here.
    if _FUTURES_EOD_TABLE in R.WHITELIST_ABSENT_DEFAULT:
        errs.append(f"futures_eod: {_FUTURES_EOD_TABLE} is whitelisted but STILL in "
                    f"registry.WHITELIST_ABSENT_DEFAULT -- it would be force-dropped from serving "
                    f"(whitelist regression; the W3 flip landed 2026-07-30)")
    if _FUTURES_EOD_TABLE not in R.load_registry().tables:
        errs.append(f"futures_eod: {_FUTURES_EOD_TABLE} is whitelisted but ABSENT from the SERVED registry "
                    f"(agent tool enum) -- the card must load once whitelist-absent is cleared")
    else:
        # (c1) THE TOOL SCHEMA declares contract_month. The model can only emit parameters the schema
        # NAMES, so an undeclared delivery month is a SILENT widening: a December ask never carries the
        # month, the whole curve is read, and agg=latest answers with the NEAREST listed expiry -- a
        # number that is not December's, wearing December's label. The description must carry BOTH forms
        # (one 'YYYY-MM' vs a comma-separated curve read) and the never-quote-a-bare-level-as-"the price"
        # rule, because a declared-but-unexplained parameter reintroduces the same miss one level down.
        try:
            from leviathan.graphrag.numbers import agent as _na
            _props = _na.tool_schema(R.load_registry())["input_schema"]["properties"]
        except Exception as exc:  # noqa: BLE001 -- an unreadable tool schema is a lint failure, not a crash
            _props = {}
            errs.append(f"futures_eod: cannot read the numbers tool schema ({exc})")
        if _props and "contract_month" not in _props:
            errs.append(f"futures_eod: {_FUTURES_EOD_TABLE} is SERVED but numbers.agent.tool_schema "
                        f"declares no `contract_month` property -- every named-expiry ask is silently "
                        f"widened to the whole curve and answered with the nearest listed expiry "
                        f"(W3.1 items 1-8 land TOGETHER)")
        elif _props:
            _desc = str((_props.get("contract_month") or {}).get("description") or "")
            for _tok, _why in (("YYYY-MM", "the single-expiry form"),
                               ("comma-separated", "the comma-separated CURVE form"),
                               ("the price", "the never-quote-a-bare-level-as-'the price' rule")):
                if _tok.lower() not in _desc.lower():
                    errs.append(f"futures_eod: the tool schema's contract_month description omits {_tok!r} "
                                f"-- {_why} must be stated, or the parameter is declared but unusable")
        # (c2) THE ROUTER knows the capability exists. dispatch.REGISTRY's `numbers` purpose is the ONLY
        # place the planner learns what the numbers agent can do; while a curve ask was unservable it
        # correctly routed elsewhere, and a purpose that never names the term structure keeps routing it
        # elsewhere forever. family_names() DERIVES the data_families enum from the registry, so the
        # family is asserted (never hardcoded anywhere) as proof the derivation actually tracked the flip.
        try:
            from leviathan.graphrag import dispatch as _dp
            _purpose = next((t.purpose for t in _dp.REGISTRY if t.name == "numbers"), "")
            _fams = _dp.family_names()
        except Exception as exc:  # noqa: BLE001
            _purpose, _fams = "", ()
            errs.append(f"futures_eod: cannot read the dispatch registry ({exc})")
        # ABSENT is an ERROR, not a pass -- the (b3) 'Empty is an ERROR' reasoning applied here. The
        # truthiness short-circuits these two checks used to carry made the leg fail OPEN on REMOVAL and
        # catch only REWORDING: deleting the 'numbers' ToolSpec from dispatch.REGISTRY (purpose -> '') and
        # family_names() returning () both yielded ZERO errors, while the capability they assert is
        # reachable would be exactly as unreachable as a reworded purpose. Proven both directions.
        if not _purpose:
            errs.append("futures_eod: dispatch.REGISTRY carries no ToolSpec('numbers') -- the served "
                        "per-delivery-month capability has no router entry at all (W3.1 item 8)")
        elif not (re.search(r"(?i)term structure", _purpose) and re.search(r"(?i)curve", _purpose)):
            errs.append(f"futures_eod: dispatch ToolSpec('numbers').purpose names neither the term "
                        f"structure nor the curve -- the served per-delivery-month capability is "
                        f"unreachable from the router (W3.1 item 8)")
        if not _fams:
            errs.append("futures_eod: dispatch.family_names() is EMPTY -- the registry-DERIVED family "
                        "enum resolves to nothing, so no data family (futures_eod included) is routable")
        elif "futures_eod" not in _fams:
            errs.append(f"futures_eod: dispatch.family_names() {sorted(_fams)} lacks 'futures_eod' -- the "
                        f"registry-DERIVED family enum did not track the whitelist flip")
        # (c3) THE CARD still declares the three served dimensions. Pinned in (a) as card shape, and again
        # HERE as the third leg of reachability: an expiry label that stops riding the row makes a curve
        # row unattributable, and a dropped settle_kind lets an ICE session close be cited as a settlement.
        _missing_dims = [k for k, want in (("contract_month_col", "contract_month"),
                                           ("settle_kind_col", "settle_kind"),
                                           ("currency_col", "currency")) if card.get(k) != want]
        if _missing_dims:
            errs.append(f"futures_eod: the card is SERVED but does not declare {_missing_dims} -- a served "
                        f"per-expiry row without its expiry / settle_kind / currency label is "
                        f"unattributable (reachability trio, leg 3)")

    # (e) the F010 registry contract: the storm-safe layout + the INV-2 column contract, verbatim.
    _reg_path = _REPO / "configs" / "silver" / "tables" / "silver_futures_eod.yaml"
    try:
        contract = yaml.safe_load(_reg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        contract = {}
        errs.append(f"futures_eod: cannot read the F010 registry contract ({exc})")
    if contract:
        if contract.get("partition_mode") != "registered" or contract.get("projection") != "forbidden":
            errs.append(f"futures_eod: registry must be partition_mode=registered + projection=forbidden "
                        f"(got {contract.get('partition_mode')!r}/{contract.get('projection')!r}) -- "
                        f"projection enumeration IS the Jul-2026 26.8M-LIST / $134 storm class")
        if contract.get("write_mode") != "registered-partition":
            errs.append(f"futures_eod: registry write_mode is {contract.get('write_mode')!r}, expected "
                        f"'registered-partition' (the F013 write-then-verify-then-register path)")
        pks = [pk.get("name") for pk in (contract.get("partition_keys") or [])]
        if pks != ["leviathan_slug", "trade_year"]:
            errs.append(f"futures_eod: registry partition_keys {pks} != ['leviathan_slug', 'trade_year']")
        if any(pk.get("projected") for pk in (contract.get("partition_keys") or [])):
            errs.append("futures_eod: a partition key is marked projected -- NEVER on this table")
        if contract.get("natural_key") != ["leviathan_slug", "contract_month", "trade_date"]:
            errs.append(f"futures_eod: registry natural_key {contract.get('natural_key')} != "
                        f"['leviathan_slug', 'contract_month', 'trade_date'] (the point of the wave)")
        if contract.get("value_columns") != ["settle"]:
            errs.append(f"futures_eod: registry value_columns {contract.get('value_columns')} != ['settle'] "
                        f"-- an OHLC value column would put a non-null floor on a by-construction-null column")
        if contract.get("vintage_retention") != "latest-only":
            errs.append(f"futures_eod: registry vintage_retention is {contract.get('vintage_retention')!r}, "
                        f"expected 'latest-only' (prices do not revise -> latest IS only)")
        cols = {c.get("name"): c for c in (contract.get("physical_columns") or [])}
        # declaration order IS writer order (INV-2) -- pa_schema_from_contract emits it verbatim.
        want_order = ["trade_date", "contract_month", "instrument_kind", "raw_symbol", "settle",
                      "settle_kind", "open", "high", "low", "close", "volume", "open_interest",
                      "unit", "currency", "expiry_date", "source", "dataset"]
        if list(cols) != want_order:
            errs.append(f"futures_eod: registry physical_columns order {list(cols)} != the ratified INV-2 "
                        f"writer order {want_order}")
        # the four contract-non-null labels + trade_date; contract_month is NULLABLE despite being a
        # natural-key member (the CEPEA cash rows) -- the exact pair of facts the generator's
        # nullable_overrides curation exists to express.
        for cn in ("trade_date", "instrument_kind", "settle_kind", "unit", "source"):
            if cn in cols and cols[cn].get("nullable") is not False:
                errs.append(f"futures_eod: registry column {cn!r} must be nullable=false")
        if cols.get("contract_month", {}).get("nullable") is not True:
            errs.append("futures_eod: registry column 'contract_month' must be nullable=true -- it is NULL "
                        "for the two CEPEA cash references (instrument_kind=cash_index)")
        for cn, want_t in (("settle", "float64"), ("trade_date", "timestamp[us]"),
                           ("expiry_date", "timestamp[us]"), ("volume", "int64"),
                           ("open_interest", "int64")):
            if cn in cols and cols[cn].get("target_arrow_type") != want_t:
                errs.append(f"futures_eod: registry column {cn!r} target_arrow_type is "
                            f"{cols[cn].get('target_arrow_type')!r}, expected {want_t!r}")
        # ROLL AND CONTINUOUS STAY OUT OF INGEST (plan lines 143-148). A stored front-month flag IS roll
        # policy; roll policy is a named, versioned QUERY-TIME decision. Fail the build if one appears.
        banned = sorted(c for c in cols
                        if re.search(r"(?i)front_month|roll|log_return|adjusted|continuous", c))
        if banned:
            errs.append(f"futures_eod: registry declares roll/continuous column(s) {banned} -- roll policy "
                        f"is a QUERY-TIME decision (a continuous series is a separate derived "
                        f"gold_futures_continuous with its own roll_policy_version)")
    return errs


# ---------------------------------------------------------------------------------------------
# W2 / D8: the front-month roll rule -- one module, one version, NO inline copies (skeptic F-L)
# ---------------------------------------------------------------------------------------------
# The ONE module allowed to implement the rule. F-L's stated failure mode is three inline copies
# (W2 gate 7, W3.3, the W2b straddle rule), so the fence below is a source scan, not a convention.
_ROLL_RULE_OWNER = "src/leviathan/silver/futures_roll.py"
# Files that may legitimately mention the rule's own tokens: the owner, its unit test, and this
# lint. Everything else must IMPORT leviathan.silver.futures_roll, never re-derive it.
_ROLL_RULE_ALLOWED = frozenset({
    _ROLL_RULE_OWNER,
    "tests/unit/test_futures_roll.py",
    # OUTCOMES_JOIN: the survivor rule's own test file. It PINS the fence (it asserts the token list
    # covers the new rule) and it names the version constant, so it cannot help matching -- the same
    # reason test_futures_roll.py is here. A test file is where a second implementation would be least
    # useful and most visible; the owner-file scan below is what actually stops one.
    "tests/unit/test_outcomes_join.py",
    "src/leviathan/graphrag/config_check.py",
})
# Tokens that only a second IMPLEMENTATION would carry (not a mere mention): a competing version
# constant, a competing rule table, a competing INPUT CONTRACT (which method reads which column -- a
# second copy of THAT drifts silently when DCE moves from delivery-cycle to volume, and it is the kind
# of copy an implementation-only scan misses), or a competing front-month entry point.
_ROLL_RULE_FORBIDDEN_TOKENS = (
    "ROLL_RULE_VERSION =",
    "ROLL_METHOD_BY_SOURCE =",
    "DELIVERY_CYCLES =",
    "METHOD_METRIC_COL =",
    "def front_month(",
    "def _front_month(",
    "def front_month_inputs_present(",
    # OUTCOMES_JOIN J1.b: the SURVIVOR rule is the module's second selection rule and gets the same
    # fence. Item 31 notes this scan would NOT have tripped on a differently-named function, so
    # co-location was a design choice and not a compliance one -- these three tokens make it both. The
    # survival margin is listed because it is HALF THE PIT BOUNDARY (item 46): a second copy of the
    # constant is a second clamp, and the one that drifts loses silently.
    "OUTCOME_CONTRACT_RULE_VERSION =",
    "OUTCOME_SURVIVE_DAYS =",
    "def outcome_contract(",
    "def contract_last_print(",
)
_ROLL_RULE_SCAN_DIRS = ("src", "jobs", "scripts", "tests")


def check_futures_roll() -> list[str]:
    """W2 D8 lint: the named/versioned front-month rule is coherent AND is not re-derived inline.

    Two halves, both load-bearing:
      (a) the rule tables themselves (``futures_roll.lint_roll_rule``): every publication SOURCE in
          CONTRACT_MAP declares a method, the two CEPEA cash references roll by 'none' and nothing
          else does, and every delivery-cycle slug carries a curated listed-month cycle;
      (b) THE FENCE -- a source scan for a SECOND implementation. F-L is not a style complaint: OI
          lives on GLBX only because of the $1.76 statistics buy, so a call site that re-derives
          "front" silently degrades to volume on exactly the flagship contracts, and nothing about
          that is visible in the output."""
    from leviathan.silver import futures_roll as FR
    errs: list[str] = [f"futures_roll: {e}" for e in FR.lint_roll_rule()]

    owner = _REPO / _ROLL_RULE_OWNER
    if not owner.exists():
        errs.append(f"futures_roll: the rule owner {_ROLL_RULE_OWNER} is MISSING -- D8 is the only "
                    f"thing standing between gate 7 / W3.3 / W2b and three divergent inline rules")
        return errs

    for sub in _ROLL_RULE_SCAN_DIRS:
        base = _REPO / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(_REPO).as_posix()
            if rel in _ROLL_RULE_ALLOWED:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:  # noqa: PERF203 -- an unreadable file is not a rule copy
                continue
            hits = sorted({tok for tok in _ROLL_RULE_FORBIDDEN_TOKENS if tok in text})
            if hits:
                errs.append(
                    f"futures_roll: {rel} carries front-month rule token(s) {hits} -- the rule "
                    f"lives ONLY in {_ROLL_RULE_OWNER}; import it (skeptic F-L: three inline copies)"
                )
    return errs


def check_futures_outcomes() -> list[str]:
    """OUTCOMES_JOIN D-OJ-13 -- the `gold_futures_outcomes` card IS the PIT clamp, linted as such
    (AWS-free, pure; the check_futures_roll / check_pace_collapse bind idiom).

    The plan's own doctrine (item 45) is that a leak must be UNREPRESENTABLE IN THE DATA STRUCTURE, and
    in this codebase that structure is a `TableSpec`: `query._guard` compiles from EXACTLY ONE column
    (`TableSpec.knowledge_col()`) and `_pub_lagged_asof` shifts the RHS literal. So the whole clamp is
    two card fields plus one arithmetic identity, and this is where they are pinned:

      * the guard column is the row's READABLE date, never `event_date`. With the column the
        partitioning silently implies (`event_date`, default `data_date` semantics) the compiled guard
        is `event_date <= asof - lag` -- and the ENTIRE forward move of an event ten days before the
        asof is readable.
      * `publication_lag_days == OUTCOME_SURVIVE_DAYS + 1`. `survive_days` is part of the BOUNDARY, not
        only of the selection: Option D chooses the contract by asking whether it still prints five
        sessions past the endpoint, so any asof in [t1+1, t1+5) would admit a row whose
        `contract_month_used` -- and therefore px0, px1 and the whole move -- was chosen with tape the
        reader does not have. Two knobs that are one knob, and this lint is what keeps them so.

    It also fails if the card ever declares a forward-looking metric name: an outcome table is the one
    surface where a `forecast_*` column would look natural."""
    from leviathan.graphrag.numbers import outcomes as OC
    return [f"futures_outcomes: {e}" for e in OC.lint_outcome_card()]


def check_pattern_outcomes() -> list[str]:
    """OUTCOMES_JOIN J5 -- the `gold_pattern_outcomes` card, bound into the build the same way
    `check_futures_outcomes` binds its twin (adversarial finding 14: the lint existed and nothing ran it).

    Same load-bearing pin, same reason: `publication_lag_days == OUTCOME_SURVIVE_DAYS + the tape lag`,
    because the survival margin is half the PIT boundary and the card is the only place it compiles into
    SQL. PLUS the one thing this table alone can get wrong -- it carries a SECOND PIT axis
    (`ledger_written_at`) that `TableSpec.knowledge_col()` cannot express, which is why the id is
    whitelist-fenced out of the agent tool enum and the engine leg applies both axes by hand.

    Vacuous until a card exists at either path (`lint_pattern_outcome_card` returns the absence as its
    own error only once there is something to lint), so a clone without the gitignored configs is not
    red on a file it was never given."""
    from leviathan.graphrag.numbers import pattern_records as PR
    card, source = PR._po_read_card()
    if source == "none":
        return []
    return [f"pattern_outcomes: {e}" for e in PR.lint_pattern_outcome_card(card)]


def check_pace_collapse() -> list[str]:
    """W3.3 item 17 / skeptic F-E: the T2a pace-collapse declarations are coherent AND no PRICE table
    collapses by `sum` / `mean` (AWS-free, pure -- the futures_roll lint_roll_rule + bind idiom).

    F-E is not a style complaint. `_PACE_COLLAPSE` maps a table to an AGGREGATION OVER THE VALUES IN A
    PERIOD, and a per-delivery-month price table is multi-row-per-period by construction: summing
    Dec+Mar+May settles is meaningless, the mean across a curve is a different unnamed series that reads
    as entirely plausible prose, and an UNCOLLAPSED vals[-1]-vals[-2] deltas two EXPIRIES rather than two
    dates -- a direction-inverted number riding a real [N] handle the all-numbers guard validates as
    correct (the class that already shipped once as the ESR '+565' probe). The honest collapse for a
    curve is a SELECTION -- `front_expiry`, keyed on the delivery-month column via the one named
    query-time rule (futures_roll.front_month) -- and this lint is what keeps the two wrong kinds out."""
    from leviathan.graphrag.numbers.cascade import lint_pace_collapse
    return [f"pace_collapse: {e}" for e in lint_pace_collapse()]


def check_question_shapes() -> list[str]:
    """C2 (D3, ratified 2026-08-01): the question-shape -> required-metric table is coherent, doctrine-fenced
    and register-clean. AWS-free and pure (the check_pace_collapse / check_futures_lite bind idiom).

    Five halves, and the middle three are the ones that matter:
      (a) COVERAGE -- the config's shape keys and the agent's detection patterns are the SAME set. A shape
          detected with no requirements records nothing; a shape with requirements and no detector never
          fires. Either way the table would be silently half-live, which is the failure mode the
          `_NONE_TIER_DECLINE` census (R5) exists to prevent for the price templates.
      (b) REALIZABILITY -- every requirement names registered tables and metrics that are actually
          WHITELISTED on at least one of them. An unwhitelisted metric can never be fetched, so its
          requirement would be permanently 'not_attempted' and would read as a dispatch miss forever.
      (c) DOCTRINE, mechanically. R4 is untouched by D1: a LIVE requirement at a PRICE_TABLES table is an
          error, and the pink-sheet spot anchor stays `deferred: true` until R4 is decided on its own
          merits. R9 as amended admits positioning as CONTEXT, so a POSITIONING_TABLES requirement is
          allowed but must SAY SO (`doctrine: r9_context`) -- the fence is then a diff, not a memory.
      (d) THE THREE-CONDITION GUARD, at build time. `agent.SHAPE_DECLINE_STATE` must be reachable from
          EXACTLY ONE executor status, and that status must be the one that means "the query matched no
          data". If 'not_known' or 'error' ever mapped to it, the line would claim data absence where the
          executor only recorded a publication gap or a malformed call -- D3's stated flip condition, and
          the reason the decline is worth having at all.
      (e) REGISTER -- the rendered sentence, through the SAME renderer the reader gets, on all five
          surfaces and under BOTH registers. D3 requires a narrower register than the shipped capability
          framing, so this is censused rather than assumed."""
    from leviathan.graphrag import register as reg
    try:
        from leviathan.graphrag.numbers import agent as na
    except Exception as e:  # noqa: BLE001 -- agent import must never break the lint
        return [f"C2 question_shapes: the numbers agent did not import ({str(e)[:120]})"]
    from leviathan.graphrag.numbers.registry import load_registry

    p = _CFG / "numbers" / "question_shapes.yaml"
    if not p.exists():
        # F10 (adversarial review): this used to print a NOTE and return [] -- a GREEN lint for a silently
        # dead C2 lane. configs/graphrag/ is gitignored, so a fresh clone, CI, or any image built from a
        # clean checkout gets exactly that unless the file is `git add -f`-ed, and "the file vanished" and
        # "the feature is off" were indistinguishable. They are distinguishable now: only an EXPLICIT
        # GRAPHRAG_QUESTION_SHAPES=off buys the vacuous pass.
        if os.environ.get("GRAPHRAG_QUESTION_SHAPES", "").strip().lower() in ("off", "0", "false"):
            print("NOTE question_shapes: GRAPHRAG_QUESTION_SHAPES=off -- the C2 lane is deliberately "
                  "disabled, vacuous pass")
            return []
        return [f"C2 question_shapes: {p} is MISSING. The C2 shape table is a tracked config (it must be "
                f"`git add -f`-ed past .gitignore:49 like cascade_map.yaml); without it agent."
                f"load_shape_table returns {{}}, every question is shapeless and the whole lane is dead "
                f"while this lint reads green. Set GRAPHRAG_QUESTION_SHAPES=off to declare the lane "
                f"deliberately disabled."]
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw = doc.get("shapes") or {}
    live = na.load_shape_table()
    errs: list[str] = []

    # (a) coverage: config keys == detector keys, exactly.
    detected = {s for s, _rx in na._SHAPE_PATTERNS}
    for s in sorted(detected - set(raw)):
        errs.append(f"C2 question_shapes: shape {s!r} is DETECTED by agent._SHAPE_PATTERNS but the table "
                    f"declares no requirement for it -- it would match and record nothing")
    for s in sorted(set(raw) - detected):
        errs.append(f"C2 question_shapes: shape {s!r} is declared in the table but agent._SHAPE_PATTERNS "
                    f"has no detector for it -- it can never fire")

    tables = load_registry().tables
    for shape in sorted(raw):
        spec = raw[shape] or {}
        if not str(spec.get("omission") or "").strip():
            errs.append(f"C2 question_shapes {shape!r}: no `omission` clause -- the decline would state an "
                        f"absence without saying what it costs the answer")
        reqs = spec.get("requires") or []
        if not reqs:
            errs.append(f"C2 question_shapes {shape!r}: no requirements declared")
        seen_ids: set = set()
        for req in reqs:
            req = req or {}
            rid = str(req.get("id") or "")
            if not rid:
                errs.append(f"C2 question_shapes {shape!r}: a requirement carries no id")
                continue
            if rid in seen_ids:
                errs.append(f"C2 question_shapes {shape!r}: duplicate requirement id {rid!r}")
            seen_ids.add(rid)
            deferred = bool(req.get("deferred"))
            if deferred and not str(req.get("deferred_reason") or "").strip():
                errs.append(f"C2 question_shapes {shape}.{rid}: deferred with no `deferred_reason` -- a "
                            f"parked requirement without its doctrine is indistinguishable from a mistake")
            if not str(req.get("subject") or "").strip():
                errs.append(f"C2 question_shapes {shape}.{rid}: no `subject` -- there is no sentence to say")
            rtables = list(req.get("tables") or [])
            rmetrics = list(req.get("metrics") or [])
            if not rtables or not rmetrics:
                errs.append(f"C2 question_shapes {shape}.{rid}: tables/metrics must both be non-empty")
                continue
            # (c) doctrine, before realizability -- a fenced table is an error whether or not it resolves.
            for t in rtables:
                if t in PRICE_TABLES and not deferred:
                    errs.append(f"C2 question_shapes {shape}.{rid}: requires the R4-fenced price table "
                                f"{t!r} -- R4 is UNTOUCHED by D1, so a spot/settle anchor stays "
                                f"`deferred: true` until it is decided on its own merits")
                if t in POSITIONING_TABLES and not deferred and req.get("doctrine") != "r9_context":
                    errs.append(f"C2 question_shapes {shape}.{rid}: requires positioning table {t!r} "
                                f"without `doctrine: r9_context` -- R9 as amended admits positioning ONLY "
                                f"as a past-tense context read, and the row must say so")
            if deferred:
                continue                                   # parked rows are inert; nothing below can fire
            for t in rtables:
                if t not in tables:
                    errs.append(f"C2 question_shapes {shape}.{rid}: table {t!r} is not in the registry")
            # (b) realizability: each metric must be WHITELISTED on at least one of the row's tables.
            for m in rmetrics:
                if not any(m in (tables[t].metrics if t in tables else {}) for t in rtables):
                    errs.append(f"C2 question_shapes {shape}.{rid}: metric {m!r} is whitelisted on none of "
                                f"{sorted(rtables)} -- the requirement could never be satisfied")
            # (b2) CONTEXT_REF RESOLVABILITY (F5). A `context_ref` names the cascade_map row that serves
            # this requirement through the ENGINE lane. Unvalidated it is a dangling pointer: C2 shipped
            # `context_ref: cot_mm_positioning` while cascade_map held no such row, so the config asserted
            # an engine lane that did not exist and nothing said so. Now that is a BUILD error, and the
            # ref's table must be one the requirement actually declares -- a context leg on some other
            # table would satisfy nothing.
            cref = str(req.get("context_ref") or "").strip()
            if cref:
                from leviathan.graphrag.numbers import cascade as _csc
                crow = (_csc.load_map() or {}).get(cref)
                if crow is None:
                    errs.append(f"C2 question_shapes {shape}.{rid}: context_ref {cref!r} is not a live "
                                f"cascade_map ref -- a dangling engine-lane pointer (an unmapped OR "
                                f"`deferred: true` row reads the same to the engine: it never fires)")
                elif (crow or {}).get("table") not in rtables:
                    errs.append(f"C2 question_shapes {shape}.{rid}: context_ref {cref!r} serves table "
                                f"{(crow or {}).get('table')!r}, which the requirement does not declare "
                                f"({sorted(rtables)}) -- the engine lane would satisfy a different ask")

    # (d) the three-condition guard, bound at build time rather than trusted to the docstring.
    origins = sorted(k for k, v in na._STATUS_STATE.items() if v == na.SHAPE_DECLINE_STATE)
    if origins != ["no_rows"]:
        errs.append(f"C2 question_shapes: the decline state {na.SHAPE_DECLINE_STATE!r} is reachable from "
                    f"executor status(es) {origins} -- it must be reachable from 'no_rows' and NOTHING "
                    f"else, or the line claims data absence where _exec recorded a publication gap "
                    f"('not_known'), a coverage decline or a malformed call ('error')")

    # (e) register census, through the live renderer.
    for shape in sorted(live):
        subjects = [str(r.get("subject")) for r in (live[shape].get("requires") or [])
                    if str(r.get("subject") or "").strip()]
        if not subjects:
            continue
        probes = [[s] for s in subjects] + ([subjects] if len(subjects) > 1 else [])
        # F4: the SCOPED form is the one the reader actually gets (shape_decline always supplies scopes),
        # so it is censused too -- both forms, every shape, or the lint would bless a sentence nobody ships.
        for probe_subjects, probe_scopes in ([(ps, None) for ps in probes]
                                             + [(ps, [na.SHAPE_SCOPE_PROBE] * len(ps)) for ps in probes]):
            try:
                sent = na.shape_decline_line(shape, probe_subjects, probe_scopes)
            except Exception as e:  # noqa: BLE001 -- an unrenderable template is itself the failure
                errs.append(f"C2 question_shapes {shape!r}: the decline line did not render ({str(e)[:80]})")
                continue
            if reg.register_leaks(sent):
                errs.append(f"C2 decline census {shape!r}: register leak {reg.register_leaks(sent)!r}")
            if reg.exec_leaks(sent):
                errs.append(f"C2 decline census {shape!r}: execution leak {reg.exec_leaks(sent)!r}")
            if reg.count_valuation_words(sent) or reg.count_flow_words(sent):
                errs.append(f"C2 decline census {shape!r}: valuation/flow vocabulary in the decline line")
            for mr in (reg.FENCED, reg.OUTLOOK):
                if reg._is_banned_sentence(sent, market_register=mr):
                    errs.append(f"C2 decline census {shape!r}: the decline line is BANNED under {mr!r}")
                if sent not in reg.sanitize(sent, market_register=mr):
                    errs.append(f"C2 decline census {shape!r}: the decline line does not survive "
                                f"sanitize(market_register={mr!r}) -- the reader would get a fragment")
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
                        ("futures_lite", check_futures_lite()),
                        ("futures_eod", check_futures_eod()),
                        ("futures_roll", check_futures_roll()),
                        ("futures_outcomes", check_futures_outcomes()),
                        ("pattern_outcomes", check_pattern_outcomes()),
                        ("pace_collapse", check_pace_collapse()),
                        ("question_shapes", check_question_shapes())):
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
    # Advisory (non-fatal): G8 CROSS-FIRE -- one slice's term is a word-boundary substring of another's, so
    # every prop the longer term claims is also claimed by the shorter one ("leaf rust" inside "coffee leaf
    # rust"). Neither of check_driver_slices' hard checks can see this (both read the dag_alias ID map) and
    # the G2 manifest hashes term SETS, so it detects edits, never collisions. Pure config arithmetic over
    # ~638 terms. REPORTS ONLY: deleting a term is a routing change and belongs in the artifact-staling
    # bundle, never in a lint.
    from leviathan.graphrag.evidence import (never_written_slice_warnings, read_dark_slice_warnings,
                                             term_collision_warnings)
    cross = term_collision_warnings()
    if cross:
        print(f"WARN term_cross_fire ({len(cross)} word-boundary term collisions across slices -- "
              f"non-fatal; deletion is a routing change, not a lint's call):")
        for w in cross:
            print(f"  - {w}")
    # Advisory (non-fatal): G7.2 READ-DARK census -- configured slices no REAL DAG id reaches, so
    # planner._fill can never reach them and no episode line can ever render for them.
    for w in read_dark_slice_warnings():
        print(f"NOTE {w}")
    # Advisory (non-fatal): G7.4 NEVER-WRITTEN census -- configured slices with no S3 object at all. A
    # DIFFERENT set from read-darkness, and deliberately advisory: write-darkness is store state, and a
    # config lint that cannot see the store must never fail a build on it.
    for w in never_written_slice_warnings():
        print(f"NOTE {w}")
    # Advisory (non-fatal): un-blurbed edges — hover falls back to mechanism; count-only to keep output sane.
    missing_blurbs = blurb_presence_warnings()
    if missing_blurbs:
        print(f"WARN edge_blurbs ({len(missing_blurbs)} edges have mechanism but no blurb -- hover falls "
              "back to mechanism, non-fatal)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
