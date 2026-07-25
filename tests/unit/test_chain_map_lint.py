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


def test_real_chain_map_is_29_expansions_10_rows():
    # CAP RE-DECISION 2026-07-25: the three El_Nino family rows activated (SA maize, sugar, robusta);
    # 7 rows/24 expansions -> 10/29, caps re-saturated by design.
    cq.load_chain_map.cache_clear()
    rows = cq.load_chain_map()
    assert len(rows) == 10
    assert sum(len(r["contracts"]) for r in rows) == 29
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
    rows = [dict(_valid_skeleton(), id=f"r{i}") for i in range(11)]   # 11 > 10 (cap re-decision 2026-07-25)
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


# ── STATIC ANCHORABILITY (minideck RCA 2026-07-24): an ALL-waiver-dark row can never derive a window ──────
# A waivered driver id has no text slice, so it never carries dated evidence. The runtime now survives a dark
# ROOT via the downstream-anchor fallback, but a row whose EVERY hop node is waived is dead on arrival -- it
# would silently skip and let a DIFFERENT-mechanism focus row fire into the question (the wheat skeleton fired
# enso_drought into an acreage ask). That is a config error, not a runtime surprise. Hermetic: the waivers
# read is redirected at evidence._DRIVER_PATH so the assertion never rides the shipped file's contents.
def _waivers_file(tmp_path, names) -> object:
    p = tmp_path / "driver_slices.yaml"
    p.write_text("waivers:\n" + "".join(f"  {n}: {{category: deferred, note: \"test\"}}\n" for n in names),
                 encoding="utf-8")
    return p


def _redirect_waivers(monkeypatch, tmp_path, names) -> None:
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "_DRIVER_PATH", _waivers_file(tmp_path, names))


def test_every_hop_node_waiver_dark_rejected(monkeypatch, tmp_path):
    _redirect_waivers(monkeypatch, tmp_path, ["area", "ending_stocks"])
    errs = _lint(monkeypatch, [_valid_skeleton()])
    assert any("wheat_area_su" in e and "statically unanchorable" in e for e in errs)


def test_one_non_waived_hop_keeps_the_row_anchorable(monkeypatch, tmp_path):
    # the REAL shipped shape: `area` IS waived, `ending_stocks` is NOT -> the downstream fallback can anchor
    # it, so the row must lint CLEAN (the lint must not regress the skeleton it exists to protect).
    _redirect_waivers(monkeypatch, tmp_path, ["area"])
    assert _lint(monkeypatch, [_valid_skeleton()]) == []


def test_waiver_match_is_accent_folded(monkeypatch, tmp_path):
    # both sides fold (sec 3.2): an ASCII waiver key covers the ACCENTED DAG id. Only the anchorability
    # error is asserted -- this row's other lint checks are exercised by the cases above.
    _redirect_waivers(monkeypatch, tmp_path, ["La_Nina", "drought"])
    dark = {"id": "accent_dark", "contracts": ["corn_cbot"],
            "hops": [{"node": "La_Niña", "ref": "oni_climate"},
                     {"node": "drought", "ref": "drought_z"}]}
    errs = _lint(monkeypatch, [dark])
    assert any("accent_dark" in e and "statically unanchorable" in e for e in errs)


def test_real_chain_map_has_no_unanchorable_row():
    # the boundary the shipped map sits on: wheat_area_su roots on the WAIVED `area` and is still legal,
    # because its `ending_stocks` hop supplies the fallback anchor.
    cq.load_chain_map.cache_clear()
    assert not any("statically unanchorable" in e for e in cc.check_chain_map())
    cq.load_chain_map.cache_clear()


# ── FAMILY ROSTER content pin (sec 1.1 table, the oni_climate x gold_weather_z release) ───────────────────
# The 4 family rows are the coverage half of v1 (17 of the 24 expansions, 14 distinct contracts across 4
# complexes). Pinned by SHAPE, not by count alone: an edit that silently repoints a family hop's ref or drops
# a contract still lints clean, so the roster itself is the assertion. Growing the roster is a v1.1 act (sec
# 1.1: "everything else in the REALIZABLE 32 waits for v1.1") -- this test is the tripwire that says so.
_FAMILY = {
    "enso_flash_drought": (["corn_cbot", "soybeans_cbot", "campinas_corn_reference_bmf", "soybeans_no_2_dce",
                            "soybean_oil_dce", "soybean_meal_dce"],
                           [("La_Nina", "oni_climate"), ("flash_drought", "drought_z")]),
    "enso_drought": (["arabica_coffee", "brazilian_arabica_coffee", "hard_red_winter_wheat_kcbt",
                      "soft_red_winter_wheat_cbot", "campinas_corn_reference_bmf", "soybeans_no_1_dce"],
                     [("La_Nina", "oni_climate"), ("drought", "drought_z")]),
    "enso_frost": (["arabica_coffee", "brazilian_arabica_coffee"],
                   [("La_Nina", "oni_climate"), ("frost", "frost_event_flag")]),
    "enso_prairie_drought": (["canola_ice", "rapeseed_oil_zce", "rapeseed_meal_zce"],
                             [("La_Nina", "oni_climate"), ("prairie_drought", "drought_z")]),
}


def test_family_rows_shape_pinned():
    cq.load_chain_map.cache_clear()
    rows = {r["id"]: r for r in cq.load_chain_map()}
    assert set(_FAMILY) <= set(rows), f"family rows missing from chain_map: {set(_FAMILY) - set(rows)}"
    for cid, (contracts, hops) in _FAMILY.items():
        row = rows[cid]
        assert row["contracts"] == contracts, f"{cid} roster drifted: {row['contracts']}"
        assert [(h["node"], h["ref"]) for h in row["hops"]] == hops, f"{cid} hops drifted: {row['hops']}"
        assert row.get("terminal") == "price"                       # prose terminal, never a futures fetch (D6)
    assert sum(len(c) for c, _ in _FAMILY.values()) == 17           # family half of the 24 expansions
    cq.load_chain_map.cache_clear()


def test_every_family_hop2_region_resolves():
    # THE family curation rule (sec 2.5 / 3.2): hop 2 picks the SINGLE-region weather driver per contract, never
    # the compound-region one (`drought` on corn_cbot is 'US_Midwest;Argentina;Brazil' -> unresolvable -> the
    # chain would decline whole, every turn). Asserted on the SHIPPED rows; check 6 of the lint enforces it
    # structurally for any future row.
    from leviathan.graphrag.graph import CausalGraph
    graph = CausalGraph.load()
    resolve = (cq.load_region_map() or {}).get("resolve") or {}
    cq.load_chain_map.cache_clear()
    rows = {r["id"]: r for r in cq.load_chain_map()}
    for cid in _FAMILY:
        hop2 = rows[cid]["hops"][1]
        for cslug in rows[cid]["contracts"]:
            did = cq._chain_driver_id(graph, cslug, hop2["node"])
            tok = (graph.driver(cslug, did).region or "").strip()
            assert tok in resolve, f"{cid}/{cslug}: hop-2 region {tok!r} does not resolve"
    cq.load_chain_map.cache_clear()


# ── STATIC SERVABILITY (check 6): the _scope SKIP_NODE class -- a hop that can never resolve a scope ───────
def test_region_unservable_hop_rejected(monkeypatch):
    # frozen_orange_juice IS a real enso_frost shape (La_Nina -> frost, frost_event_flag) -- every other check
    # passes; ONLY its region token 'Florida_US / Sao_Paulo_Brazil' is compound, so the chain would decline
    # `error` on every turn while the lint stayed green.
    bad = {"id": "enso_frost", "contracts": ["arabica_coffee", "frozen_orange_juice"],
           "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                    {"node": "frost", "ref": "frost_event_flag"}]}
    errs = _lint(monkeypatch, [bad])
    assert any("frozen_orange_juice" in e and "statically unservable" in e for e in errs)
    assert not any("arabica_coffee" in e for e in errs)              # the resolvable half stays clean


def test_psd_unserved_contract_hop_rejected(monkeypatch):
    # the second SKIP_NODE cause: frozen_orange_juice is in PSD_UNSERVED_SLUGS, so a silver_psd hop has no
    # series to read (its `ending_stocks` node DOES carry the psd ref and DOES list `frost` as a parent).
    bad = {"id": "fcoj_frost_su", "contracts": ["frozen_orange_juice"],
           "hops": [{"node": "frost", "ref": "frost_event_flag"},
                    {"node": "ending_stocks", "ref": "psd_ending_stock_su_ratio"}]}
    errs = _lint(monkeypatch, [bad])
    assert any("declared-unserved PSD slug" in e for e in errs)


def test_resolvable_region_hop_stays_clean(monkeypatch):
    # the shipped family shape must NOT trip check 6: US_Midwest resolves, so the row lints clean.
    ok = {"id": "enso_flash_drought", "contracts": ["corn_cbot", "soybeans_cbot"],
          "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                   {"node": "flash_drought", "ref": "drought_z"}]}
    assert _lint(monkeypatch, [ok]) == []


def test_real_chain_map_has_no_unservable_row():
    cq.load_chain_map.cache_clear()
    assert not any("statically unservable" in e for e in cc.check_chain_map())
    cq.load_chain_map.cache_clear()


# ── v1.1 FAMILY EXPANSION: the AUTHORED-but-DEFERRED roster ───────────────────────────────────────────────
# The three rows that make the five remaining ENSO-eligible contracts chain-eligible. They ship INERT because
# the v1 set saturates the ratified guard (7/7 rows, 24/25 expansions) and each needs a NEW row slot -- each
# roots on El_Nino (every shipped family row roots on La_Nina) with a contract-specific hop-2 node, so no
# shipped row can carry them. Pinned by SHAPE here so a later cap re-decision flips on exactly what was
# authored and verified, not a drifted row: `deferred: true` rows are invisible to load_chain_map AND to the
# lint, which is precisely why they need their own tripwire.
_V11_DEFERRED = {
    "enso_sa_maize_drought": (["south_african_white_maize_jse", "south_african_yellow_maize_jse"],
                              [("El_Nino", "oni_climate"), ("drought", "drought_z")]),
    "enso_monsoon_sugar": (["raw_sugar", "white_sugar"],
                           [("El_Nino", "oni_climate"), ("monsoon_weak", "drought_z")]),
    "enso_robusta_drought": (["robusta_coffee"],
                             [("El_Nino", "oni_climate"), ("Vietnam_drought", "drought_z")]),
}


def _raw_chains() -> list:
    """chain_map.yaml INCLUDING the deferred rows (load_chain_map drops them by contract)."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG / "numbers" / "chain_map.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("chains") or []


def test_v11_rows_are_active():
    # CAP RE-DECISION 2026-07-25: deferred:true deleted from all three rows; the loader now serves them.
    raw = {r["id"]: r for r in _raw_chains()}
    assert set(_V11_DEFERRED) <= set(raw), f"v1.1 rows missing: {set(_V11_DEFERRED) - set(raw)}"
    for cid in _V11_DEFERRED:
        assert "deferred" not in raw[cid], f"{cid} still carries deferred -- the activation edit regressed"
    cq.load_chain_map.cache_clear()
    active = {r["id"] for r in cq.load_chain_map()}
    assert set(_V11_DEFERRED) <= active                            # the loader serves them: chain-eligible
    cq.load_chain_map.cache_clear()


def test_v11_rows_shape_pinned():
    raw = {r["id"]: r for r in _raw_chains()}
    for cid, (contracts, hops) in _V11_DEFERRED.items():
        row = raw[cid]
        assert row["contracts"] == contracts, f"{cid} roster drifted: {row['contracts']}"
        assert [(h["node"], h["ref"]) for h in row["hops"]] == hops, f"{cid} hops drifted: {row['hops']}"
        assert row.get("terminal") == "price"                      # prose terminal, never a futures fetch (D6)
    assert sum(len(c) for c, _ in _V11_DEFERRED.values()) == 5     # +5 distinct contracts: 16 covered -> 21


def test_v11_rows_lint_clean_standalone(monkeypatch):
    # the whole point of authoring them now: every sec-2.5 check ALREADY passes (real DAG edges accent-folded,
    # active refs, certified tables, no finer-grained downstream hop, a live non-waived hop, and check 6's
    # single-region token resolving for every contract). Only the caps stand between here and active.
    raw = {r["id"]: r for r in _raw_chains()}
    for cid in _V11_DEFERRED:
        row = {k: v for k, v in raw[cid].items() if k != "deferred"}
        assert _lint(monkeypatch, [row]) == [], f"{cid} does not lint clean standalone"


def test_v11_caps_resaturated_next_expansion_needs_its_own_redecision(monkeypatch):
    # CAP RE-DECISION 2026-07-25: 7->10 rows / 25->29 expansions activated exactly the three-row roster,
    # and the caps re-saturate at the new set BY DESIGN -- one more row (or expansion) trips the guard, so
    # the next growth act is forced through the same deliberate re-decision this one went through.
    cq.load_chain_map.cache_clear()
    active = cq.load_chain_map()
    cq.load_chain_map.cache_clear()
    assert len(active) == 10 == cc._CHAIN_MAX_ROWS
    assert sum(len(r["contracts"]) for r in active) == 29 == cc._CHAIN_MAX_EXPANSIONS
    assert _lint(monkeypatch, active) == []                        # the active roster fits exactly
    one_more = active + [dict(active[-1], id="one_row_too_many")]
    errs = _lint(monkeypatch, one_more)
    assert any("active rows > max" in e for e in errs)
