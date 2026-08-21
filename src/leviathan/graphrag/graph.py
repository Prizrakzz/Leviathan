"""In-memory causal graph over the curated contracts (GRAPHRAG_PLAN v2 Phase 2 — graphdev thin spine).

Loads configs/graphrag/causal/*.yaml into a queryable structure and exposes the deterministic primitives the
answer orchestrator reasons over — cascade fan-in/out (driver.parents), convergence regime firing, inter-
commodity hops, and silver-status resolution against the live registry. Pure + offline: no LLM, no spend.

The cascade direction: `driver.parents` are UPSTREAM causes, so `ancestors(d)` walks toward root causes
("what caused this driver") and `descendants(d)` walks toward effects ("what this driver drives")."""
from __future__ import annotations

from dataclasses import dataclass

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval
from leviathan.graphrag import extract as ex

_CAUSAL_DIR = ex._CFG / "causal"


def load_contracts(paths=None) -> dict[str, cs.CausalContract]:
    """Load the curated YAMLs -> {contract_id: CausalContract} (defaults to all of configs/graphrag/causal/)."""
    paths = paths or sorted(_CAUSAL_DIR.glob("*.yaml"))
    out: dict[str, cs.CausalContract] = {}
    for p in paths:
        c = cs.load(p)
        out[c.contract] = c
    return out


def causal_graph_version(paths=None) -> str:
    """A stable 12-hex content hash of the curated causal YAMLs — the graph's identity for audit and
    reproducibility (which graph produced an answer / an eval). Deterministic from the YAML BYTES, so it's
    independent of the build/image; the same files always hash the same, and any edge/threshold edit
    changes it. Returns 'nograph' if nothing loads. This is the cheap tier of graph versioning; a per-edge
    effective_date + as-of graph loader is deferred (build-plan Phase 6) until a backtest demands it."""
    import hashlib
    paths = paths or sorted(_CAUSAL_DIR.glob("*.yaml"))
    h, any_read = hashlib.sha256(), False
    for p in sorted(paths, key=lambda x: str(x)):
        try:
            data = open(p, "rb").read()                      # read FIRST — a missing file contributes nothing
        except OSError:
            continue
        h.update(str(getattr(p, "name", p)).encode())
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
        any_read = True
    return h.hexdigest()[:12] if any_read else "nograph"


@dataclass
class _Index:
    contract: cs.CausalContract
    by_id: dict[str, cs.Driver]
    children: dict[str, list[str]]       # driver_id -> ids that list it as a parent (reverse of .parents)


def _index(c: cs.CausalContract) -> _Index:
    by_id = {d.id: d for d in c.drivers}
    children: dict[str, list[str]] = {d.id: [] for d in c.drivers}
    for d in c.drivers:
        for p in d.parents:
            if p in children:                # parent validity is guaranteed by the schema, but stay defensive
                children[p].append(d.id)
    return _Index(c, by_id, children)


# ── D-MW-27 (2026-08-12) THE REVERSE INTER-COMMODITY INDEX ───────────────────────────────────────────────────
# A contract's YAML declares who DRIVES it (corn lists wheat: "cheap feed wheat substitutes..."). INVERTING
# that map answers the doctrine's missing direction: for a seed S, WHICH MARKETS S'S SITUATION CASCADES INTO
# (the downstream/consumer direction). The forward map is `cross_links()`; this is its transpose.
#
# THE ALIAS PROBLEM, MEASURED (STEP-0 census, data/dmw_p6_census.json): 65 of the 117 inter_commodity edges
# name a `driver_commodity` string that is NOT a contract id ('soybean_oil' vs soybean_oil_cbot/_dce, 'wheat'
# vs three venue-suffixed wheats), so a NAIVE inversion covers only 52 tracked edges. Alias resolution
# rescues 42 more (52 -> 94).
#
# THE RESOLUTION RULE, EXACT (plan round-3, applied verbatim; the census recorded the literal-prose reading
# beside it and it strands 13 contract-id-valued edges, so the two-step reading below is the ratified one):
#   driver_commodity -> node_for() (the _hier() contract->node map, so a CONTRACT-ID-valued string lands on
#   its node first) -> the INVERTED _hier() map -> the tracked contract-id set -> LEXICOGRAPHIC-FIRST when
#   that set has more than one member, recorded per edge.
# THREE BUCKETS, reported separately so a deck-shrink decision reads a DECOMPOSED number:
#   resolved                     94   the edge inverts to a tracked seed contract
#   unresolvable-no-node         23   the string names no commodity node AT ALL -- unresolvable BY
#                                     CONSTRUCTION, never a census shortfall. Measured classes: wheat (10,
#                                     the largest), sunflower_oil, sorghum, barley, ethanol.
#   unresolvable-no-contract      0   a node with no LOADED contract (empty on the shipped estate)
#
# THE BASE-YAML FENCE (census `deck_eligibility_rule`): `corn` and `soybeans` are BASE yamls, not tradeable
# markets (absent from commodity_hierarchy, no exchange/origin) and they byte-duplicate their _cbot
# variants' inter_commodity sets. They are excluded as FOREIGN TARGETS -- without the fence D-MW-28's paid
# slot can buy a phantom contract block that no desk can trade. The fence is defined RELATIVELY (a loaded
# contract, absent from the hierarchy, whose commodity node is ALSO served by a loaded hierarchy contract)
# so it fires on the real estate and is a no-op on a synthetic graph the hierarchy knows nothing about.
_REV_RESOLVED = "resolved"
# The canonical loaded contract per NODE for cross-market seed resolution, consulted before the
# lexicographic fallback (see the #68 AMENDMENT comment at the resolution site). soybeans_cbot is
# already lexicographic-first on its node -- pinned here anyway so the choice is DECLARED for both
# base-yaml twins rather than one being an accident that happens to agree with the desk.
_CANONICAL_SEED = {"corn": "corn_cbot", "soybeans": "soybeans_cbot"}
_REV_NO_NODE = "unresolvable-no-node"
_REV_NO_CONTRACT = "unresolvable-no-contract"


def _hier_contract_nodes() -> dict:
    """{contract_id: commodity node} straight from evidence's OWN hierarchy loader -- one producer of the
    contract->node fact, never a second parse of commodity_hierarchy.yaml here (the COMPAT-9 drift class).

    LAZY import: `evidence` pulls the harvest/params chain, and `graph` is imported by offline causal
    tooling that must stay light. The direction is verified clean -- evidence does NOT import graph -- so
    this can never cycle. Any failure (public clone with no private config) degrades to an EMPTY map, which
    makes every edge `unresolvable-no-node` and the whole mechanism a no-op: an inversion index may never
    be the thing that kills a load."""
    try:
        from leviathan.graphrag import evidence as ev
        raw = (ev._hier().get("contracts") or {})
        return {k: (v.get("node") or k) for k, v in raw.items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001 — no hierarchy -> no inversion, never a failed load
        return {}


def _invert_inter_commodity(contracts: dict) -> tuple[list, dict, dict, dict]:
    """(resolution_table, index, hier, forward) — the LOAD-TIME inversion, FOUR elements.
    `resolution_table` is one row per inter_commodity edge in the estate (117 today), carrying its bucket,
    its resolved node, the candidate set and the tie-break that picked the seed, so the resolution is
    REVISITABLE from an artifact rather than re-derived. `index` is {seed NODE: [edge rows]} over the
    RESOLVED, TRADEABLE-foreign rows. `hier` is the {contract_id: commodity node} map this same call
    already read -- bound to `self._hier_nodes` and served by the public `contract_node()`, i.e. the
    graph's OWN copy of the contract->node fact, so the walk never re-parses commodity_hierarchy.yaml per
    candidate. `forward` is {declaring contract: [forward_target per declaration index]} -- the SAME
    resolution read in the FORWARD direction, served by `cross_links()` (see its docstring for the defect
    it closes and the measurement).

    T2-1 (2026-08-15, RATIFIED in docs/private/CASCADE_HOME_AND_SMALL_ITEMS_PLAN.md): THE INDEX IS KEYED BY
    `node_for(seed)`, NOT by the tie-break winner. The resolution RULE is untouched -- the same two-step
    alias resolution, the same lexicographic-first tie-break, the same recorded `seed` on every table row --
    only the KEY the index files an edge under changed. Under the old contract key the tie-break funnelled
    every edge of a multi-contract node onto ONE contract id, so `corn_cbot` (the most-routed contract in
    the product) reached ZERO inverted edges while its node `corn` carried 20; keying by node hands all 9
    co-node contracts their node's cascade at zero cost. `_seed_contracts` already de-dupes the walk's seeds
    to distinct commodity NODES, so the NODE was always the runtime seed identity.

    Deterministic: contracts and edges are walked in sorted/declaration order and every candidate set is
    sorted, so the same YAMLs always produce the same table and the same tie-breaks."""
    hier = _hier_contract_nodes()
    by_node: dict[str, list[str]] = {}
    for cid in sorted(hier):
        by_node.setdefault(hier[cid], []).append(cid)
    nodes = set(by_node)

    def _node_of(name: str) -> str:
        return hier.get(name, name)
    # THE BASE-YAML FENCE, relative (see the block comment): loaded, off-hierarchy, and its node is served
    # by a loaded hierarchy contract -> a duplicate of a tradeable sibling, never a market of its own.
    untradeable = {cid for cid in contracts if cid not in hier
                   and any(o != cid and o in hier and hier[o] == _node_of(cid) for o in contracts)}
    # D-EC GRAPH-COMPLETION INTEGRATION (2026-08-21): a loaded causal contract that is neither a hierarchy
    # contract nor a base-yaml twin is a real market of its own — the class DAGs (barley, sorghum,
    # sunflower_oil). The FORWARD branch below already tracks such an edge (`dc in contracts`); admitting the
    # same contracts here as nodes makes the REVERSE index agree — ONE map, read twice, agreeing again
    # (tracked == resolved held at 94/94 before the class DAGs landed, then split 114/103 because this set
    # was hierarchy-only). Guarded on a loaded hierarchy: with no hierarchy at all the whole mechanism stays
    # the documented no-op, and the fence above still keeps the base-yaml pair off the node set.
    if hier:
        for cid in sorted(contracts):
            if cid not in hier and cid not in untradeable:
                by_node.setdefault(_node_of(cid), []).append(cid)
        nodes = set(by_node)
    table: list[dict] = []
    index: dict[str, list[dict]] = {}
    forward: dict[str, list] = {}
    for cid in sorted(contracts):
        for i, e in enumerate(contracts[cid].inter_commodity):
            dc = e.driver_commodity
            node = _node_of(dc)
            cands = list(by_node.get(node) or ())
            tracked = [c for c in cands if c in contracts]
            if node not in nodes:
                bucket, seed, tie = _REV_NO_NODE, None, None
            elif not tracked:
                bucket, seed, tie = _REV_NO_CONTRACT, None, None
            else:
                # D-EC-P0 #68 AMENDMENT (owner word 2026-08-19): the tie between a node's tracked
                # contracts is a PRODUCT choice, not a sort order. The census prose calls the base-yaml
                # pair duplicates OF the CBOT contracts, and a desk analyst saying "corn" means CBOT --
                # under plain lexicographic-first, bare `corn` resolved to campinas_corn_reference_bmf
                # (a Brazilian regional reference) on 16 edges purely because 'campinas' < 'corn_cbot',
                # and 5 anchors measurably lost walk depth. The map names the canonical seed per node;
                # lexicographic-first remains ONLY as the fallback for nodes it does not name.
                canonical = _CANONICAL_SEED.get(node)
                if canonical is not None and canonical in tracked:
                    bucket, seed = _REV_RESOLVED, canonical
                    tie = "single-member" if len(tracked) == 1 else "canonical-twin"
                else:
                    bucket, seed = _REV_RESOLVED, tracked[0]
                    tie = "single-member" if len(tracked) == 1 else "lexicographic-first"
            # D-EC-P0 #68 (2026-08-19) THE FORWARD TARGET -- the contract the WALK hops to, off THIS
            # resolution and no other. A declared id that is itself a loaded, tradeable contract IS its own
            # target (the edge named the market it meant: corn_cbot stays corn_cbot, and a synthetic test
            # graph the hierarchy knows nothing about keeps every hop it had). Everything else -- a bare
            # node name, and the base-yaml pair the fence declares non-tradeable -- takes the resolved
            # seed, tie-break and all. `None` (both unresolvable buckets) means NOT TRAVERSABLE FORWARD.
            fwd = dc if (dc in contracts and dc not in untradeable) else seed
            forward.setdefault(cid, []).append(fwd)
            row = {"declaring_contract": cid, "idx": i, "driver_commodity": dc, "relation": e.relation,
                   "sign": e.sign, "lag": e.lag, "mechanism": e.mechanism, "blurb": e.blurb,
                   "bucket": bucket, "node": (node if node in nodes else None), "candidates": cands,
                   "tracked_candidates": tracked, "seed": seed, "tie_break": tie,
                   "foreign_tradeable": cid not in untradeable, "forward_target": fwd}
            table.append(row)
            if bucket == _REV_RESOLVED and row["foreign_tradeable"]:
                # The INDEX row is `cross_links`' shape with the two ends named: `contract` is the FOREIGN
                # (declaring) market, `seed` the resolved commodity it declared and `seed_node` the NODE the
                # row is FILED under (T2-1). `tracked` is True by construction here -- the index only ever
                # holds loaded, tradeable contracts.
                index.setdefault(_node_of(seed), []).append(
                    {"contract": cid, "seed": seed, "seed_node": _node_of(seed), "idx": i,
                     "driver_commodity": dc,
                     "relation": e.relation, "sign": e.sign, "lag": e.lag, "mechanism": e.mechanism,
                     "blurb": e.blurb, "tracked": True})
    return table, index, hier, forward


@dataclass
class FiredRegime:
    name: str
    direction: str                          # '+' bullish / '-' bearish
    matched: list[str]                      # the active drivers that count toward this regime
    threshold: int                          # requires_any_n_of
    interactions: list[dict]                # the amplifier interactions whose `when` is fully active
    note: str


class CausalGraph:
    """Queryable view over one or more loaded contracts. `silver` (the live feature names) is injected for
    tests; in production it resolves from the feature_spine registry + node_silver_map via validate."""

    def __init__(self, contracts: dict[str, cs.CausalContract], *, silver: set[str] | None = None,
                 version: str | None = None):
        self.contracts = contracts
        self._idx = {k: _index(v) for k, v in contracts.items()}
        self._silver = cval.available_silver() if silver is None else set(silver)
        # graph identity for audit/reproducibility (trace.graph_version, /healthz, eval headers). A
        # production load computes it from the YAML bytes; synthetic test graphs pass 'test' or None.
        self.version = version
        # D-MW-27: the REVERSE inter-commodity index, built ONCE at load time (never per query). It is a
        # pure transpose of data already in memory plus one hierarchy read, so it costs a load, not a turn.
        # D-EC-P0 #68: the SAME build hands back the forward hop targets, so both directions of the
        # inter-commodity map are one resolution with one tie-break, resolved once per load.
        self._rev_table, self._rev_index, self._hier_nodes, self._fwd_targets = \
            _invert_inter_commodity(contracts)

    @classmethod
    def load(cls, paths=None) -> "CausalGraph":
        return cls(load_contracts(paths), version=causal_graph_version(paths))

    def _ix(self, contract: str) -> _Index:
        if contract not in self._idx:
            raise KeyError(f"unknown contract {contract!r}")
        return self._idx[contract]

    # ── cascade ───────────────────────────────────────────────────────────────────────
    def driver(self, contract: str, driver_id: str) -> cs.Driver:
        return self._ix(contract).by_id[driver_id]

    def roots(self, contract: str) -> list[str]:
        """Drivers with no parents — the exogenous roots of the cascade (climate, macro, policy)."""
        return [d.id for d in self.contracts[contract].drivers if not d.parents]

    def ancestors(self, contract: str, driver_id: str) -> list[str]:
        """Transitive upstream causes of a driver (the .parents closure) — 'what caused this'."""
        ix = self._ix(contract)
        seen: set[str] = set()
        stack = list(ix.by_id[driver_id].parents)
        while stack:
            n = stack.pop()
            if n in seen or n not in ix.by_id:
                continue
            seen.add(n)
            stack.extend(ix.by_id[n].parents)
        return sorted(seen)

    def ancestors_by_depth(self, contract: str, driver_id: str) -> dict[str, int]:
        """D-GD (2026-08-08) — `ancestors()` with the CHAIN DEPTH each upstream cause sits at
        (1 = a direct parent, 2 = a grandparent, ...). Same SET as `ancestors()` by construction, and
        test_dgd_closure_reservation pins the parity over all 33 curated DAGs.

        WHY THE DEPTH IS NEEDED AND THE SORTED SET IS NOT: the cascade-closure reservation
        (planner._closure_plan) spends a FIXED, small number of slots, so it must spend them
        NEAREST-PARENT-FIRST — a reservation of 3 then closes the median chain whole (median ancestor
        closure 2, mean 3.58, max 26; docs/private/recon/dgd-walk-admission.md V3) instead of scattering
        alphabetically across a 26-ancestor monster. The depth also rides the per-node admission record
        so the D-GD-3 adjudicator can read WHICH link of a chain each admitted node closed.

        BFS, so a cause reachable by two paths keeps its SHALLOWEST depth. Acyclicity is not assumed:
        `out` terminates any cycle. Pure/offline, same as `ancestors()`."""
        ix = self._ix(contract)
        out: dict[str, int] = {}
        frontier = [p for p in ix.by_id[driver_id].parents if p in ix.by_id]
        depth = 1
        while frontier:
            nxt: list[str] = []
            for n in sorted(frontier):
                if n in out:
                    continue
                out[n] = depth
                nxt.extend(p for p in ix.by_id[n].parents if p in ix.by_id)
            frontier, depth = nxt, depth + 1
        return out

    def descendants(self, contract: str, driver_id: str) -> list[str]:
        """Transitive downstream effects (drivers this one is a parent of) — 'what this drives'."""
        ix = self._ix(contract)
        if driver_id not in ix.by_id:
            raise KeyError(f"{driver_id!r} not in {contract!r}")
        seen: set[str] = set()
        stack = list(ix.children.get(driver_id, []))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(ix.children.get(n, []))
        return sorted(seen)

    def descendants_by_depth(self, contract: str, driver_id: str) -> dict[str, int]:
        """D-MW-15 (iv), 2026-08-11 — `descendants()` with the CASCADE DISTANCE each downstream effect sits
        at, in the NEGATIVE-DEPTH convention: -1 = a direct child, -2 = a grandchild, ... The sign IS the
        direction, so one admission record can carry both legs of the cascade (`ancestors_by_depth` returns
        +1/+2/...) and a reader never has to consult a second field to know which way an edge points.

        SAME SET as `descendants()` by construction — the same reverse-edge index (`_Index.children`), the
        same reachability — and test_dmw_walk pins that parity over all 33 curated DAGs, exactly as
        test_dgd_closure_reservation pins the ancestors BFS. This is the PUBLIC seam the walk's downstream
        admission needs: `_Index.children` is private and reading it from planner.py would put a second
        traversal of the same edges in a second module (the COMPAT-9 duplicate-and-drift class).

        THE HONEST CLAIM ABOUT WHAT IT BUYS (D-MW-15 iv, restated per review): within-contract children are
        ALREADY wave-1 candidates — the walk enqueues every driver of a contract — so downstream admission
        is NOT new reach. It is structural RE-ADMISSION of siblings that tau or the budget dropped, with the
        cascade direction visible in the audit trail. Read the P3-A verdict that way.

        BFS, so an effect reachable by two paths keeps its SHALLOWEST distance. Acyclicity is not assumed:
        `out` terminates any cycle. Pure/offline, same as `descendants()`."""
        ix = self._ix(contract)
        if driver_id not in ix.by_id:
            raise KeyError(f"{driver_id!r} not in {contract!r}")
        out: dict[str, int] = {}
        frontier = [c for c in ix.children.get(driver_id, []) if c in ix.by_id]
        depth = 1
        while frontier:
            nxt: list[str] = []
            for n in sorted(frontier):
                if n in out:
                    continue
                out[n] = -depth
                nxt.extend(c for c in ix.children.get(n, []) if c in ix.by_id)
            frontier, depth = nxt, depth + 1
        return out

    # ── convergence ───────────────────────────────────────────────────────────────────
    def regimes(self, contract: str, active) -> list[FiredRegime]:
        """Which convergence signals fire given a set of active driver ids: a regime fires when at least
        `requires_any_n_of` of its drivers are active; an interaction fires when ALL of its `when` are active."""
        active = set(active)
        fired: list[FiredRegime] = []
        for s in self.contracts[contract].convergence:
            matched = [d for d in s.drivers if d in active]
            if len(matched) >= s.requires_any_n_of:
                ints = [{"when": list(it.when), "effect": it.effect, "note": it.note}
                        for it in s.interactions if set(it.when) <= active]
                fired.append(FiredRegime(s.name, s.direction, matched, s.requires_any_n_of, ints, s.note))
        return fired

    # ── inter-commodity ───────────────────────────────────────────────────────────────
    def cross_links(self, contract: str) -> list[dict]:
        """Inter-commodity edges. `target_contract` is the LOADED CONTRACT the forward walk hops to, and
        `tracked` is simply whether one exists -- a real hop. `driver_commodity` stays the string the YAML
        declared, so display and the mechanism text are untouched.

        D-EC-P0 #68 (2026-08-19) THE DEFECT THIS CLOSES, measured in data/dec_p0/graph_walk.md S4f. `tracked`
        used to be `e.driver_commodity in self.contracts` -- RAW STRING EQUALITY -- while the reverse index
        one screen up resolved the very same edges through the hierarchy. Two readings of one map:

          * 65 of 117 inter-commodity edges were untraversable forward, and 42 of them resolve to a node
            with a loaded contract and were ALREADY resolved on the reverse side. The 42 are the vegoil/meal
            crush complex almost exactly (soybean_oil 14, palm_oil 9, soybean_meal 7, rapeseed_oil 6,
            rapeseed_meal 5, canola 1) -- so the flagship PALM -> SBO -> SBM chain was walkable downstream
            and NOT walkable forward, the direction every serving preset actually runs.
          * 34 of the 52 that DID survive landed on `corn` / `soybeans`, the two base yamls this module's
            own fence classifies as non-tradeable duplicates. Two thirds of the surviving cross-market layer
            was a hop into a market no desk can trade.

        ONE RESOLUTION, NOT TWO: the target is `_invert_inter_commodity`'s own `forward_target` -- the same
        two-step node resolution, the same lexicographic-first tie-break, recorded per edge on the
        resolution table (`rev_cross_link_resolution()[i]['forward_target']`) beside the reverse `seed`. A
        declared id that is a loaded tradeable contract is its own target, so an edge that names the market
        it means keeps it; the base-yaml pair and the bare node names take the resolved contract. Measured
        after: 94 traversable forward edges (52 -> 94, the reverse index's own resolved count), 0 landing on
        a base yaml, and the 23 edges naming no node at all (`wheat`, `sorghum`, `sunflower_oil`, `barley`,
        `ethanol` -- group keys, not nodes) still untracked, which is edge-AUTHORING work, not resolution.

        KeyError on an unknown contract, as before: this is a contract lookup (`rev_cross_links` is the
        index read that must never raise). Rows are fresh dicts."""
        edges = self.contracts[contract].inter_commodity
        # index-aligned by construction: the same loop that built the table appended one target per
        # declared edge, in declaration order, for every loaded contract.
        targets = self._fwd_targets.get(contract) or ()
        return [{"driver_commodity": e.driver_commodity, "relation": e.relation, "sign": e.sign,
                 "mechanism": e.mechanism, "lag": e.lag, "target_contract": t, "tracked": t is not None}
                for e, t in zip(edges, targets)]

    def rev_cross_links(self, commodity: str) -> list[dict]:
        """D-MW-27 — the INVERSE of `cross_links`: the FOREIGN CONTRACTS that declare `commodity` as a
        `driver_commodity`, i.e. THE MARKETS THIS ONE CASCADES INTO. Read off the load-time index, so this
        is a dict lookup, never a traversal.

        Each row is the DECLARING contract plus the declared edge verbatim (`mechanism` is the string
        D-MW-28 scores cos(query, .) against, and it already reads in the right direction: the foreign
        contract wrote it to describe how `commodity` moves IT). `seed` is the resolved commodity that
        DECLARED the edge and `seed_node` the node it is filed under, so a row is self-describing in an
        artifact.

        NEVER RAISES on an unknown/unresolved id -- it returns []. `cross_links` may KeyError because it is
        a contract lookup; this is an index read on the walk's hot path and a routing surprise must never
        kill a turn. Rows are fresh dicts (same idiom as `cross_links`), ordered by declaring contract then
        declaration index -- deterministic.

        NODE-KEYED (T2-1, 2026-08-15, RATIFIED in docs/private/CASCADE_HOME_AND_SMALL_ITEMS_PLAN.md). The
        argument is resolved through `contract_node()` before the lookup, so EVERY contract of a node
        reaches its node's edges. THE DEFECT THIS CLOSES, verbatim from the P6 census
        (`zero_pair_decomposition.FINDING` + `node_keyed_view`): under the old contract key the
        lexicographic-first tie-break funnelled every edge of a multi-contract node onto ONE contract id, so
        `corn_cbot` -- the most-routed contract in the product -- returned ZERO rows while node `corn`
        carried 20 edges, all funnelled to campinas_corn_reference_bmf. Nine contracts gained their node's
        cascade by this re-key at zero cost, with NO change to the resolution rule, the recorded tie-breaks
        or the three buckets. An id that is neither a contract nor a node still returns [] -- `contract_node`
        passes unknowns through unchanged and the index has no such key."""
        return [dict(r) for r in (self._rev_index.get(self.contract_node(commodity)) or ())]

    def contract_node(self, contract: str) -> str:
        """The commodity NODE serving a contract — `evidence.node_for` semantics, read off the map this
        graph already loaded instead of re-parsing the hierarchy YAML per call (D-MW-28 asks this question
        once per candidate on the walk's hot path). Unknown/already-a-node ids return unchanged, which is
        also what makes a SYNTHETIC contract id its own node in a hermetic test — no test-only branch.
        test_dmw_p6 pins the parity against `evidence.node_for` over every loaded contract."""
        return self._hier_nodes.get(contract, contract)

    def rev_cross_link_resolution(self) -> list[dict]:
        """THE RESOLUTION TABLE, queryable: one row per inter_commodity edge with its bucket, resolved node,
        candidate set, tie-break and tradeable-foreign flag. This is the audit surface the STEP-0 census
        pins against -- a resolution nobody can re-read is a resolution nobody can revisit."""
        return [dict(r) for r in self._rev_table]

    def rev_cross_link_buckets(self) -> dict:
        """The THREE-BUCKET decomposition (+ the two fence counters), so a shrink decision reads decomposed
        numbers instead of one 'we got N'. Pinned against data/dmw_p6_census.json.

        `seeds_with_pairs` is `len(self._rev_index)`, i.e. the number of distinct index KEYS -- and since
        T2-1 the key is the commodity NODE, so it counts seed NODES with at least one inverted edge (15 on
        the real estate, the same 15 the P6-era contract-keyed census reported, because the tie-break winner
        was injective onto its node). `contracts_reaching_pairs` is the number the re-key actually MOVED:
        loaded contracts whose node carries edges, 15 -> 24. Both are reported so no reader has to infer
        which population a single 'seeds' number meant."""
        out = {"edges": len(self._rev_table), _REV_RESOLVED: 0, _REV_NO_NODE: 0, _REV_NO_CONTRACT: 0,
               "untradeable_foreign_edges": 0, "seeds_with_pairs": len(self._rev_index),
               "contracts_reaching_pairs": sum(1 for c in self.contracts
                                               if self.contract_node(c) in self._rev_index)}
        for r in self._rev_table:
            out[r["bucket"]] = out.get(r["bucket"], 0) + 1
            if r["bucket"] == _REV_RESOLVED and not r["foreign_tradeable"]:
                out["untradeable_foreign_edges"] += 1
        return out

    # ── silver resolution (the decoupling seam) ───────────────────────────────────────
    def silver_status(self, contract: str, driver_id: str) -> dict:
        """Resolve a driver's silver link: `declared` is the YAML status; `live` is whether the named feature
        actually exists in the registry today (so graphdev runs whether or not MLOps has built it yet)."""
        d = self.driver(contract, driver_id)
        return {"silver_ref": d.silver_ref, "declared": d.silver_status,
                "live": bool(d.silver_ref) and d.silver_ref in self._silver}

    def silver_summary(self, contract: str) -> dict:
        c = self.contracts[contract]
        live = [d.id for d in c.drivers if d.silver_ref and d.silver_ref in self._silver]
        planned = [d.id for d in c.drivers if d.silver_status == "planned"]
        return {"drivers": len(c.drivers), "live": len(live), "planned": len(planned),
                "live_ids": sorted(live), "planned_ids": sorted(planned)}

    # ── per-contract topology (terminal cascade-DAG endpoint, build-plan P1.2) ─────────
    def topology(self, contract: str) -> dict:
        """One contract's cascade DAG as nodes + edges for the interactive terminal view (design §4.2):
        its drivers (with silver_status + confidence), the terminal contract node, fan-in parent edges, and
        inter-commodity hop targets (flagged `tracked` when the target is itself a loaded contract). Pure/
        offline; graph_version-stamped so the frontend can cache per (contract, version). Unknown contract
        raises KeyError -> the route maps it to 404. Firing/active overlay is applied by the route (needs an
        as-of + silver), keeping this method pure of I/O."""
        if contract not in self.contracts:
            raise KeyError(contract)
        from leviathan.graphrag import display as dp  # human node labels (6.3 one-vocab on the map)
        c = self.contracts[contract]
        tgt0 = c.target_metrics[0] if c.target_metrics else "price"
        by_id = self._ix(contract).by_id                          # W1.4: fan-in edges inherit the parent's mechanism
        nodes: dict[str, dict] = {contract: {"id": contract, "kind": "contract", "contract": contract,
                                             "label": dp.node_label(contract, "contract"), "target_metric": tgt0}}
        edges: list[dict] = []
        for d in c.drivers:
            nodes[d.id] = {"id": d.id, "kind": d.type, "contract": contract, "label": dp.node_label(d.id, d.type),
                           "silver_ref": d.silver_ref, "silver_status": d.silver_status, "confidence": d.confidence}
            edges.append({"source": d.id, "target": contract, "edge_type": d.edge_type or "drives",
                          "sign": d.sign, "lag": d.lag, "mechanism": d.mechanism, "blurb": d.blurb,
                          "confidence": d.confidence, "target_metric": d.target_metric or tgt0})
            for p in d.parents:                                      # fan-in: parent driver -> driver
                if p in by_id:
                    # The parent's own blurb/mechanism doubles as the hover text — before W1.4 these
                    # 983 edges (45% of the map) rendered a blank tooltip (the FE binds hover to `mechanism`).
                    edges.append({"source": p, "target": d.id, "edge_type": "drives", "sign": None,
                                  "mechanism": by_id[p].mechanism, "blurb": by_id[p].blurb})
        for e in c.inter_commodity:                                 # cascade hop: contract -> other commodity
            # DELIBERATELY the raw membership test, NOT `cross_links`' resolved `tracked` (D-EC-P0 #68).
            # This flag is the FE's "is this node clickable" -- the node id IS the route parameter, and
            # `soybean_oil` is a commodity node with no /v1/graph document. The walk's traversability and
            # this map's navigability are different questions; resolving here would 404 the click.
            nodes.setdefault(e.driver_commodity, {"id": e.driver_commodity, "kind": "commodity",
                                                  "contract": e.driver_commodity,
                                                  "label": dp.node_label(e.driver_commodity, "commodity"),
                                                  "tracked": e.driver_commodity in self.contracts})
            edges.append({"source": contract, "target": e.driver_commodity, "edge_type": e.relation,
                          "sign": e.sign, "lag": e.lag, "mechanism": e.mechanism, "blurb": e.blurb})
        return {"contract": contract, "graph_version": self.version,
                "nodes": list(nodes.values()), "edges": edges}

    # ── flat export (debug / QA / L2 mermaid substrate) ───────────────────────────────
    def to_edge_list(self) -> list[dict]:
        """Flatten every contract into a canonical edge list — the THREE edge kinds as uniform rows:
        driver->target (the causal prior), parent-driver->driver (fan-in), and contract->inter-commodity node
        (cascade hop). Pure/offline. `sign` on a parent edge is None (the schema stores no sign for the
        parent link — we don't invent one). Feeds debugging, QA, and the L2 graph_to_mermaid renderer."""
        _COLS = ("source", "source_kind", "edge_type", "target", "target_metric", "sign", "lag",
                 "mechanism", "confidence", "silver_ref", "silver_status")
        rows: list[dict] = []

        def _row(**kw):
            rows.append({c: kw.get(c) for c in _COLS})

        for cid, c in self.contracts.items():
            tgt0 = c.target_metrics[0] if c.target_metrics else "price"
            for d in c.drivers:
                _row(source=d.id, source_kind=d.type, edge_type=d.edge_type, target=cid,
                     target_metric=d.target_metric or tgt0, sign=d.sign, lag=d.lag, mechanism=d.mechanism,
                     confidence=d.confidence, silver_ref=d.silver_ref, silver_status=d.silver_status)
                for p in d.parents:                                    # parent-driver -> driver (fan-in)
                    _row(source=p, source_kind="driver", edge_type="drives", target=d.id)
            for e in c.inter_commodity:                                # contract -> inter-commodity node (cascade hop)
                _row(source=cid, source_kind="commodity", edge_type=e.relation, target=e.driver_commodity,
                     sign=e.sign, lag=e.lag, mechanism=e.mechanism)
        return rows


def main() -> int:
    import argparse
    import csv
    import json
    import sys

    ap = argparse.ArgumentParser(description="Causal graph utilities (pure/offline).")
    ap.add_argument("--edge-list", action="store_true", help="print the canonical flat edge list")
    ap.add_argument("--csv", action="store_true", help="with --edge-list: CSV instead of JSONL")
    ap.add_argument("--topology", metavar="CONTRACT",
                    help="print one contract's topology JSON (the /v1/graph payload; FE fixture regen: "
                         "python -m leviathan.graphrag.graph --topology arabica_coffee > graph.arabica.json)")
    args = ap.parse_args()
    g = CausalGraph.load()
    if args.topology:
        print(json.dumps(g.topology(args.topology), indent=2, ensure_ascii=False))
        return 0
    if args.edge_list:
        rows = g.to_edge_list()
        if args.csv and rows:
            w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        else:
            for r in rows:
                print(json.dumps(r))                                   # ensure_ascii -> cp1252-safe stdout
        return 0
    print(f"{len(g.contracts)} contracts, {len(g.to_edge_list())} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
