"""CHAIN ENGINE -- config_check.check_chain_map lint (CHAIN_ENGINE_PLAN sec 2.5, D3; writer B).

The fail-closed chain_map curation gate. POSITIVE: the REAL shipped 7 rows lint clean. NEGATIVE: every check
in sec 2.5 rejects a malformed row -- a fabricated edge, a dead/deferred ref, an uncertified table, a bad
country pin, a finer-grained downstream hop, a node not in the DAG, a contract not loaded, and each cap
(6 contracts/row, 7 rows, 25 total expansions). The S1 case is pinned explicitly: the flagship row expanded
to campinas is REJECTED (campinas has no safrinha->ending_stocks_su_ratio edge)."""
from __future__ import annotations

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import cascade as cq


def _valid_skeleton():
    return {"id": "wheat_area_su",
            "contracts": ["soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt"],
            "hops": [{"node": "area", "ref": "area"},
                     {"node": "ending_stocks", "ref": "psd_ending_stock_su_ratio"}]}


def _lint(monkeypatch, chains) -> list[str]:
    monkeypatch.setattr(cq, "load_chain_map", lambda: chains)
    return cc.check_chain_map()


# ── POSITIVE: the real shipped rows lint clean ───────────────────────────────────────────────────────
def test_real_chain_map_lints_clean():
    cq.load_chain_map.cache_clear()
    errs = cc.check_chain_map()
    assert errs == [], f"real chain_map.yaml must lint clean, got: {errs}"
    cq.load_chain_map.cache_clear()


def test_real_chain_map_is_24_expansions_7_rows():
    cq.load_chain_map.cache_clear()
    rows = cq.load_chain_map()
    assert len(rows) == 7
    assert sum(len(r["contracts"]) for r in rows) == 24        # S1: campinas dropped from the flagship
    cq.load_chain_map.cache_clear()


# ── NEGATIVE: each sec-2.5 check rejects a malformed row ──────────────────────────────────────────────
def test_fabricated_edge_rejected(monkeypatch):
    bad = _valid_skeleton()
    bad["hops"][1]["node"] = "frost"                            # frost.parents does NOT contain `area`
    bad["hops"][1]["ref"] = "frost_event_flag"
    errs = _lint(monkeypatch, [bad])
    assert any("not a real DAG edge" in e or "does not list the prior hop as a parent" in e for e in errs)


def test_s1_campinas_in_flagship_rejected(monkeypatch):
    # THE S1 finding: campinas su_ratio parents = [conab_production_revision, export_pace, ethanol_demand_BR]
    # -- `safrinha` is NOT a parent, so the flagship row expanded to campinas fails the edge lint by design.
    flagship = {"id": "corn_lanina_safrinha_su",
                "contracts": ["corn_cbot", "campinas_corn_reference_bmf"],
                "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                         {"node": "safrinha", "ref": "production", "country": "Brazil"},
                         {"node": "ending_stocks_su_ratio", "ref": "psd_ending_stock_su_ratio"}]}
    errs = _lint(monkeypatch, [flagship])
    assert any("campinas_corn_reference_bmf" in e and "parent" in e for e in errs)


def test_absent_or_deferred_ref_rejected(monkeypatch):
    # load_map() drops deferred rows, so an absent OR deferred ref resolves to None -> the SAME fail-closed
    # "not an ACTIVE cascade_map row" branch (the file has no deferred ref today, so an absent name proves it).
    bad = _valid_skeleton()
    bad["hops"][0]["ref"] = "no_such_ref"
    errs = _lint(monkeypatch, [bad])
    assert any("no_such_ref" in e and "ACTIVE cascade_map row" in e for e in errs)


def test_bad_country_pin_rejected(monkeypatch):
    bad = {"id": "pin_bad", "contracts": ["corn_cbot"],
           "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                    {"node": "safrinha", "ref": "production", "country": "Atlantis"}]}
    errs = _lint(monkeypatch, [bad])
    assert any("Atlantis" in e and "known PSD title" in e for e in errs)


def test_finer_grained_downstream_rejected(monkeypatch):
    # marketing_year (annual) parent -> year_month (sub-annual) child = spread-MY-over-months, the deferred case.
    bad = {"id": "grain_bad", "contracts": ["corn_cbot"],
           "hops": [{"node": "planted_area", "ref": "area"},           # marketing_year
                    {"node": "La_Nina", "ref": "oni_climate"}]}        # year_month (finer) -- but no real edge
    errs = _lint(monkeypatch, [bad])
    assert any("finer-grained" in e for e in errs)


def test_node_not_in_dag_rejected(monkeypatch):
    bad = _valid_skeleton()
    bad["hops"][0]["node"] = "not_a_driver"
    errs = _lint(monkeypatch, [bad])
    assert any("not_a_driver" in e and "not a driver id" in e for e in errs)


def test_contract_not_loaded_rejected(monkeypatch):
    bad = _valid_skeleton()
    bad["contracts"] = ["totally_fake_contract"]
    errs = _lint(monkeypatch, [bad])
    assert any("totally_fake_contract" in e and "not a loaded contract" in e for e in errs)


def test_too_many_contracts_per_row_rejected(monkeypatch):
    bad = _valid_skeleton()
    bad["contracts"] = ["soft_red_winter_wheat_cbot"] * 7             # > 6 (dupes still count against the cap)
    errs = _lint(monkeypatch, [bad])
    assert any("contracts > max" in e for e in errs)


def test_too_many_rows_rejected(monkeypatch):
    rows = [dict(_valid_skeleton(), id=f"r{i}") for i in range(8)]    # 8 > 7
    errs = _lint(monkeypatch, rows)
    assert any("active rows > max" in e for e in errs)


def test_total_expansions_cap_rejected(monkeypatch):
    # 5 rows x 6 contracts = 30 > 25 (each row within the per-row cap, but the TOTAL exceeds).
    six = ["soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt", "hard_red_spring_wheat_mgex",
           "french_wheat_matif", "corn_cbot", "soybeans_cbot"]
    rows = [dict(_valid_skeleton(), id=f"r{i}", contracts=list(six)) for i in range(5)]
    errs = _lint(monkeypatch, rows)
    assert any("total contract expansions > max" in e for e in errs)


def test_too_many_hops_rejected(monkeypatch):
    bad = {"id": "long", "contracts": ["corn_cbot"],
           "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                    {"node": "safrinha", "ref": "production", "country": "Brazil"},
                    {"node": "ending_stocks_su_ratio", "ref": "psd_ending_stock_su_ratio"},
                    {"node": "planted_area", "ref": "area"}]}          # 4 hops > 3
    errs = _lint(monkeypatch, [bad])
    assert any("quantified hops" in e for e in errs)


def test_duplicate_chain_id_rejected(monkeypatch):
    errs = _lint(monkeypatch, [_valid_skeleton(), _valid_skeleton()])
    assert any("duplicate chain id" in e for e in errs)
