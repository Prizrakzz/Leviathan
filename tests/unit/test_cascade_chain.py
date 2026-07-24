"""CHAIN ENGINE v1 -- hermetic unit tests (CHAIN_ENGINE_PLAN.md secs 2-4).

Two layers:
  * FIXTURE tests drive cq._chain_legs / cq.quantify(chain=True) with hand-built subgraphs + a
    SQL-text-keyed stub qfn (the test_cascade convention). Every hop rides the REAL fetch_window ->
    Q.run -> build_sql path (so an unresolvable slug/metric would surface as a real status), then the
    stub returns rows by table/metric substring.
  * LIVE-SHAPED tests drive the REAL an.answer -> _answer_l2 -> the cq.quantify seam with the
    omit-when-off `chain` kwarg (the P4 pace lesson: fixture tests passed while live wiring was dark).
    An ACCENTED-contract root (La_Nina) fixture must FIRE through selection (gate-1 accent pin, S2).

Coverage: loader schema (deferred filter + file-absent -> []); the PSD su_ratio hop-resolver + the
explicit per-hop country PIN (2.1); anchor-window monthly-x-annual alignment + the downstream-only grain
rule (2.2); the degenerate-hop guard collapse-then-decline-if-<2 (2.3); accent-fold on selection AND
per-hop lookups (3.2); CHAIN_CAP reuse-before-fetch cap-atomic (3.4); dark-hop kills the chain +
reasoned-decline enum (4.1/5.2); byte-identical flag-off serialization.
"""
from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag.numbers import cascade as cq

ASOF = "2011-06-01"
NINA = "La_Niña"                                              # the ACCENTED ENSO id (8/14 v1 DAGs; S2)


# ── builders ───────────────────────────────────────────────────────────────────────────────────────
def _drv(nid, ref, *, parents=(), region=None, typ="climate_driver"):
    return cs.Driver(id=nid, type=typ, sign="+", mechanism="m", silver_ref=ref,
                     silver_status="available", region=region, parents=list(parents))


def _graph(contract, drivers):
    return g.CausalGraph({contract: cs.CausalContract(contract=contract, aliases=[contract], drivers=drivers)},
                         silver=set())


def _evnode(contract, nid, ref, dates, *, region=None):
    ev = [{"date": d, "source": "usda_gain", "source_key": f"k{i}", "text": "t", "event_date": None}
          for i, d in enumerate(dates)]
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": region}, evidence=ev)


def _sg(seeds, nodes):
    return SimpleNamespace(seeds=seeds, nodes=nodes, trace={}, fired_regimes=[])


def _h(sql: str) -> int:
    return int(hashlib.md5(sql.encode("utf-8")).hexdigest()[:6], 16)


def _qfn_factory(*, dark_metric=None, seen=None):
    """SQL-text-keyed stub: deterministic-but-distinct-per-SQL values (so within-hop deltas exist), routed
    by table/metric substring. `dark_metric` returns [] for that metric (a dark hop). `seen` collects SQL."""
    def qfn(sql):
        if seen is not None:
            seen.append(sql)
        s = sql.lower()
        if dark_metric and dark_metric in s:
            return []
        if "su_ratio" in s:                                        # ratio -> pre-scaled x100 to '%'
            return [{"value": str(round(0.20 + (_h(sql) % 30) / 100.0, 4)), "release_date": "2011-05-09"}]
        if "area_harvested" in s:
            return [{"value": str(30000 + _h(sql) % 900), "release_date": "2011-05-09"}]
        if "production_mt" in s:
            return [{"value": str(50000000 + _h(sql) % 900000), "release_date": "2011-05-09"}]
        if "exports_mt" in s or "imports_mt" in s:
            return [{"value": str(20000000 + _h(sql) % 900000), "release_date": "2011-05-09"}]
        if "noaa_oni" in s or "oni_anom" in s:
            return [{"value": str(round(0.5 + (_h(sql) % 20) / 10.0, 3)), "year": 2010, "month": 11}]
        if "drought_z" in s:                                       # gold_weather_z year_month hop (dated)
            return [{"value": str(round((_h(sql) % 30) / 10.0 - 1.5, 3)), "year": 2010, "month": 9}]
        return [{"value": "1.0"}]
    return qfn


def _cm(monkeypatch, chains):
    monkeypatch.setattr(cq, "load_chain_map", lambda: chains)


# ── loader schema (D3 loader half; content + lint are writer B) ──────────────────────────────────────
def test_load_chain_map_absent_file_is_empty(monkeypatch, tmp_path):
    from leviathan.graphrag import extract as ex
    monkeypatch.setattr(ex, "_CFG", tmp_path)                      # no numbers/chain_map.yaml here
    cq.load_chain_map.cache_clear()
    assert cq.load_chain_map() == []
    cq.load_chain_map.cache_clear()


def test_load_chain_map_parses_and_drops_deferred(monkeypatch, tmp_path):
    from leviathan.graphrag import extract as ex
    (tmp_path / "numbers").mkdir()
    (tmp_path / "numbers" / "chain_map.yaml").write_text(
        "chains:\n"
        "  - {id: live_row, contracts: [wheat], hops: [{node: area, ref: area}]}\n"
        "  - {id: off_row, deferred: true, contracts: [corn], hops: []}\n", encoding="utf-8")
    monkeypatch.setattr(ex, "_CFG", tmp_path)
    cq.load_chain_map.cache_clear()
    rows = cq.load_chain_map()
    assert [r["id"] for r in rows] == ["live_row"]                 # file order; deferred dropped (inert)
    cq.load_chain_map.cache_clear()


# ── the resolver fires a 2-hop chain (skeleton: MY root -> MY su_ratio, both silver_psd) ─────────────
def _skeleton_graph():
    return _graph("wheat", [_drv("area", "area"),
                            _drv("ending_stocks", "psd_ending_stock_su_ratio", parents=["area"])])


def _skeleton_chain():
    return [{"id": "wheat_area_su", "contracts": ["wheat"],
             "hops": [{"node": "area", "ref": "area"},
                      {"node": "ending_stocks", "ref": "psd_ending_stock_su_ratio"}]}]


def test_chain_fires_two_hops_injects_rows_and_writes_trace(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "united_states")
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    sg = _sg(["wheat"], [root])
    calls = []
    lines, fired, decline = cq._chain_legs(sg, _skeleton_graph(), [], [], _qfn_factory(), ASOF, "2010", calls)
    assert decline is None and fired is not None
    assert fired["chain_id"] == "wheat_area_su" and fired["contract"] == "wheat"
    assert [hp["node"] for hp in fired["hops"]] == ["area", "ending_stocks"]     # DAG names, chain order
    assert fired["n_rows"] == len(calls) > 0                       # every handle rides a real injected row
    assert any(ln.startswith("QUANTIFIED CHAIN") for ln in lines)  # the no-conclusion marker
    assert any("chain hop 1/2" in ln for ln in lines) and any("chain hop 2/2" in ln for ln in lines)
    # sec 2.2 anchor-window PROOF: hop 2 is a SYNTHETIC node with NO evidence of its own -- it fired ONLY
    # because it re-expressed the ROOT's window (had it re-derived from its own [] evidence it would decline).
    su_hop = fired["hops"][1]
    assert su_hop["table"] == "silver_psd" and su_hop["metric"] == "su_ratio"
    assert su_hop["country"] == "United States"                    # primary rule (no pin), real _primary_title


def test_chain_handles_continue_the_turn_count(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    calls = [{"query": {}, "rows": [{"value": "1"}], "status": "ok"}] * 3   # 3 prior handles this turn
    lines, fired, _d = cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [],
                                      _qfn_factory(), ASOF, "2010", calls)
    assert fired is not None
    first = next(ln for ln in lines if ln.startswith("- [N"))
    assert first.startswith("- [N4]")                              # base = len(calls) == 3 -> first is [N4]


# ── the explicit per-hop country PIN (2.1): safrinha-class geography overrides the ref default ───────
def test_country_pin_overrides_ref_default(monkeypatch):
    chain = [{"id": "corn_flag", "contracts": ["corn"],
              "hops": [{"node": NINA, "ref": "oni_climate"},
                       {"node": "safrinha", "ref": "production", "country": "Brazil"},
                       {"node": "ending_stocks_su_ratio", "ref": "psd_ending_stock_su_ratio"}]}]
    _cm(monkeypatch, chain)
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "united_states")
    graph = _graph("corn", [_drv(NINA, "oni_climate"),
                            _drv("safrinha", "production", parents=[NINA], region="US_Midwest"),
                            _drv("ending_stocks_su_ratio", "psd_ending_stock_su_ratio", parents=["safrinha"])])
    root = _evnode("corn", "La_Nina", "oni_climate", ["2010-09-05", "2010-10-10"])   # ASCII walk id; ONE episode
    _lines, fired, decline = cq._chain_legs(_sg(["corn"], [root]), graph, [], [], _qfn_factory(), ASOF,
                                            "2010", [])
    assert decline is None and fired is not None and len(fired["hops"]) == 3
    prod = fired["hops"][1]
    assert prod["metric"] == "production_mt" and prod["country"] == "Brazil"   # PIN wins over primary=US
    assert fired["hops"][2]["country"] == "United States"         # su_ratio: no pin -> primary


# ── accent-fold on BOTH selection AND per-hop lookups (3.2, S2) ──────────────────────────────────────
def test_accent_folded_root_and_region_hop_resolve(monkeypatch):
    # walk id + chain_map name differ ONLY by accent; the region hop reads the DAG driver's region token.
    chain = [{"id": "enso_import", "contracts": ["corn"],
              "hops": [{"node": "La_Nina", "ref": "oni_climate"},          # ASCII in chain_map
                       {"node": "china_import", "ref": "import"}]}]        # region-ruled silver_psd hop
    _cm(monkeypatch, chain)
    graph = _graph("corn", [_drv(NINA, "oni_climate"),                     # ACCENTED in the DAG
                            _drv("china_import", "import", parents=[NINA], region="China")])
    root = _evnode("corn", NINA, "oni_climate", ["2010-08-05", "2010-11-20"])   # ACCENTED walk id
    _lines, fired, decline = cq._chain_legs(_sg(["corn"], [root]), graph, [], [], _qfn_factory(), ASOF,
                                            "2010", [])
    assert decline is None and fired is not None                  # accent-fold bridged La_Nina<->La_Nina root
    imp = fired["hops"][1]
    assert imp["metric"] == "imports_mt" and imp["country"] == "China"     # region token -> region_map -> China


# ── SELECTION among same-root focus rows: grounded-hop COVERAGE beats file order (the shadowing FIX) ──
# On the REAL 7-row map, enso_drought (2-hop, row 4) and the coffee CONTROL (3-hop, row 7) BOTH match
# arabica_coffee and BOTH root on La_Nina. A file-order-only pick let the 2-hop shadow the 3-hop -> the deck's
# chain_coffee_control_pos min_chain_hops_cited:3 was unsatisfiable. These pin coverage-first selection, with
# the SHORTER row FIRST in file order so it would win any file-order tie -- the exact shadowing geometry.
def _coffee_graph():
    return _graph("arabica_coffee", [
        _drv(NINA, "oni_climate"),
        _drv("drought", "drought_z", parents=[NINA], region="US_Midwest"),
        _drv("psd_ending_stock_su_ratio", "psd_ending_stock_su_ratio", parents=["drought"], typ="fundamental")])


def _coffee_chains():
    return [{"id": "enso_drought", "contracts": ["arabica_coffee"],                 # 2-hop, FILE-ORDER FIRST
             "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                      {"node": "drought", "ref": "drought_z"}]},
            {"id": "coffee_lanina_drought_su", "contracts": ["arabica_coffee"],      # 3-hop CONTROL, LATER
             "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                      {"node": "drought", "ref": "drought_z"},
                      {"node": "psd_ending_stock_su_ratio", "ref": "psd_ending_stock_su_ratio"}]}]


def test_selection_full_mechanism_reaches_deeper_chain(monkeypatch):
    # the question NAMED La_Nina -> drought -> su: all three hop nodes grounded THIS walk. Coverage(control)=3 >
    # coverage(enso_drought)=2, so the 3-hop CONTROL is selected despite the 2-hop sitting first in file order.
    _cm(monkeypatch, _coffee_chains())
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "brazil")
    nodes = [_evnode("arabica_coffee", NINA, "oni_climate", ["2010-09-05", "2010-10-10"]),
             _evnode("arabica_coffee", "drought", "drought_z", ["2010-09-20"], region="US_Midwest"),
             _evnode("arabica_coffee", "psd_ending_stock_su_ratio", "psd_ending_stock_su_ratio", ["2011-05-01"])]
    _l, fired, decline = cq._chain_legs(_sg(["arabica_coffee"], nodes), _coffee_graph(), [], [],
                                        _qfn_factory(), ASOF, "2010", [])
    assert decline is None and fired is not None
    assert fired["chain_id"] == "coffee_lanina_drought_su"                          # coverage BEAT file order
    assert len([hp for hp in fired["hops"] if "collapsed_into" not in hp]) == 3     # the su terminal is present


def test_selection_shorter_mechanism_keeps_file_order_shorter_chain(monkeypatch):
    # only La_Nina + drought grounded (su NOT named): both tie at coverage 2 -> FILE ORDER wins -> the 2-hop
    # enso_drought fires, NOT the deeper control. Proves the fix is coverage-first, not "always pick longest".
    _cm(monkeypatch, _coffee_chains())
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "brazil")
    nodes = [_evnode("arabica_coffee", NINA, "oni_climate", ["2010-09-05", "2010-10-10"]),
             _evnode("arabica_coffee", "drought", "drought_z", ["2010-09-20"], region="US_Midwest")]
    _l, fired, decline = cq._chain_legs(_sg(["arabica_coffee"], nodes), _coffee_graph(), [], [],
                                        _qfn_factory(), ASOF, "2010", [])
    assert decline is None and fired is not None
    assert fired["chain_id"] == "enso_drought"                                      # coverage tie -> file order
    assert len([hp for hp in fired["hops"] if "collapsed_into" not in hp]) == 2


# ── the downstream-only grain rule (2.2(3), S5): a MY root admitted; a MY->month step declined ───────
def test_annual_root_admitted(monkeypatch):
    # skeleton root `area` is a marketing_year (annual) ref -> admitted by the folded grain rule.
    _cm(monkeypatch, _skeleton_chain())
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    _l, fired, decline = cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [],
                                        _qfn_factory(), ASOF, "2010", [])
    assert fired is not None and decline is None


def test_finer_than_parent_hop_declines(monkeypatch):
    # MY (annual) root -> year_month (sub-annual) descendant = spread-an-MY-over-months, the DEFERRED shape.
    chain = [{"id": "bad_grain", "contracts": ["corn"],
              "hops": [{"node": "production", "ref": "production"},        # marketing_year root
                       {"node": NINA, "ref": "oni_climate"}]}]             # year_month descendant (finer)
    _cm(monkeypatch, chain)
    graph = _graph("corn", [_drv("production", "production"), _drv(NINA, "oni_climate", parents=["production"])])
    root = _evnode("corn", "production", "production", ["2010-08-05", "2010-11-20"])
    _l, fired, decline = cq._chain_legs(_sg(["corn"], [root]), graph, [], [], _qfn_factory(), ASOF, "2010", [])
    assert fired is None and decline["reason"] == "error" and decline["hop"] == 1


# ── the degenerate-hop guard (2.3): collapse consecutive identical; decline-if-<2 ───────────────────
def test_degenerate_two_identical_hops_declines(monkeypatch):
    chain = [{"id": "degen", "contracts": ["wheat"],
              "hops": [{"node": "exp_a", "ref": "export"}, {"node": "exp_b", "ref": "export"}]}]
    _cm(monkeypatch, chain)
    graph = _graph("wheat", [_drv("exp_a", "export", region="US"),
                             _drv("exp_b", "export", parents=["exp_a"], region="US")])
    root = _evnode("wheat", "exp_a", "export", ["2010-08-05", "2010-11-20"], region="US")
    calls = []
    _l, fired, decline = cq._chain_legs(_sg(["wheat"], [root]), graph, [], [], _qfn_factory(), ASOF,
                                        "2010", calls)
    assert fired is None and decline["reason"] == "degenerate" and not calls   # <2 distinct -> just a node


def test_collapse_then_fire_records_the_collapsed_hop(monkeypatch):
    # hop1 distinct, hops 2 & 3 identical -> collapse to ONE quantified series; 2 distinct remain -> FIRES.
    chain = [{"id": "collapse", "contracts": ["corn"],
              "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                       {"node": "exp_a", "ref": "export", "country": "United States"},
                       {"node": "exp_b", "ref": "export", "country": "United States"}]}]
    _cm(monkeypatch, chain)
    graph = _graph("corn", [_drv(NINA, "oni_climate"),
                            _drv("exp_a", "export", parents=[NINA], region="US"),
                            _drv("exp_b", "export", parents=["exp_a"], region="US")])
    root = _evnode("corn", "La_Nina", "oni_climate", ["2010-08-05", "2010-11-20"])
    _l, fired, decline = cq._chain_legs(_sg(["corn"], [root]), graph, [], [], _qfn_factory(), ASOF, "2010", [])
    assert decline is None and fired is not None
    collapsed = [hp for hp in fired["hops"] if "collapsed_into" in hp]
    assert collapsed and collapsed[0]["hop"] == 2 and collapsed[0]["collapsed_into"] == 1
    merged = next(hp for hp in fired["hops"] if hp.get("hop") == 1)
    assert "exp_a / exp_b" in merged["node"]                       # both DAG names on the one observed series


# ── a dark hop kills the chain (4.1); a declined chain injects ZERO rows (honest ledger) ─────────────
def test_dark_hop_declines_whole_and_injects_nothing(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    calls = []
    _l, fired, decline = cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [],
                                        _qfn_factory(dark_metric="su_ratio"), ASOF, "2010", calls)
    assert fired is None and decline["reason"] == "hop_dark" and decline["hop"] == 1 and not calls


# ── CHAIN_CAP: cap-atomic decline; reuse-before-fetch (3.4) ──────────────────────────────────────────
def test_cap_atomic_declines_whole(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())
    monkeypatch.setattr(cq, "CHAIN_CAP", 1)                        # any 2-hop chain nets > 1 fetch
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    calls = []
    _l, fired, decline = cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [],
                                        _qfn_factory(), ASOF, "2010", calls)
    assert fired is None and decline["reason"] == "cap" and decline["net"] > 1 and not calls


def test_reuse_before_fetch_no_duplicate_sql(monkeypatch):
    # Drive quantify(chain=True): the ROOT node is a per-node group already fetched into `records`; the chain
    # root hop must CONSUME those records, never re-fire their SQL (reuse-before-fetch, cap-free).
    _cm(monkeypatch, _skeleton_chain())
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "united_states")
    seen = []
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    block, _t, _r = cq.quantify(_sg(["wheat"], [root]), _skeleton_graph(), qfn=_qfn_factory(seen=seen),
                                asof=ASOF, near="2010", extra_number_calls=[], chain=True)
    assert block and "QUANTIFIED CHAIN" in block
    assert len(seen) == len(set(seen))                            # reuse fired -> the root SQL never repeats


# ── attempted-but-declined telemetry (5.2): root_not_grounded / no-match ─────────────────────────────
def test_root_not_grounded_declines(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())
    sg = _sg(["wheat"], [_evnode("wheat", "something_else", "export", ["2010-08-05"])])   # root absent
    _l, fired, decline = cq._chain_legs(sg, _skeleton_graph(), [], [], _qfn_factory(), ASOF, "2010", [])
    assert fired is None and decline == {"chain_id": "wheat_area_su", "reason": "root_not_grounded"}


def test_no_focus_match_is_zero_trace(monkeypatch):
    _cm(monkeypatch, [{"id": "soy_only", "contracts": ["soybeans"],
                       "hops": [{"node": "area", "ref": "area"}]}])
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    out = cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [], _qfn_factory(), ASOF, "2010", [])
    assert out == ([], None, None)                                # no attempt -> both trace keys absent, zero cost


def test_empty_chain_map_is_zero_trace(monkeypatch):
    _cm(monkeypatch, [])
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    assert cq._chain_legs(_sg(["wheat"], [root]), _skeleton_graph(), [], [], _qfn_factory(), ASOF, "2010",
                          []) == ([], None, None)


# ── flag-off byte-identity serialization (quantify chain=False == chain omitted) ────────────────────
def test_flag_off_byte_identical_serialization(monkeypatch):
    _cm(monkeypatch, _skeleton_chain())                           # even WITH a matching chain present...
    monkeypatch.setattr("leviathan.graphrag.silverleg._primary_country", lambda c: "united_states")
    root = _evnode("wheat", "area", "area", ["2010-08-05", "2010-11-20"])
    qfn = _qfn_factory()
    callsA, callsB = [], []
    outA = cq.quantify(_sg(["wheat"], [root]), _skeleton_graph(), qfn=qfn, asof=ASOF, near="2010",
                       extra_number_calls=callsA)                 # chain kwarg OMITTED (default False)
    sgB = _sg(["wheat"], [root])
    outB = cq.quantify(sgB, _skeleton_graph(), qfn=qfn, asof=ASOF, near="2010",
                       extra_number_calls=callsB, chain=False)    # chain=False explicit
    assert outA == outB and callsA == callsB                      # byte-identical block + trace + injected rows
    assert "quantify_chain" not in sgB.trace and "quantify_chain_decline" not in sgB.trace
