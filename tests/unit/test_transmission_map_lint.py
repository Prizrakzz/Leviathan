"""TRANSMISSION CHAIN -- config_check.check_transmission_map lint (TRANSMISSION_CHAIN_PLAN D1/D3/D5/D6/D9).

check_chain_map's horizontal sibling, same fail-closed discipline. POSITIVE: the SHIPPED map (flagship
PALM->SBO->SBM + pure-vegoil control SBO->PALM->RSO) lints clean, and an absent/all-deferred map no-ops.
NEGATIVE: every check rejects a malformed row -- a pair that is not an ACTIVE (material) RV2 link, a
feed_grain cluster (D3: an isolated deg-1 edge admits ZERO chains), depth > 2, a 1-link degenerate "chain", a
broken hub orientation, a repeated node/pair, vertical-chain ref reuse (D6), a statically dead PSD-unserved
leg, a row the ENGINE LOADER would silently drop, and a missing transmission-scoped cap (D5)."""
from __future__ import annotations

from leviathan.graphrag import complex_map as xcm
from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import cascade as cq

_PALM = "malaysian_crude_palm_oil_cme"
_SBO = "soybean_oil_cbot"
_SBM = "soybean_meal_cbot"
_RSO = "rapeseed_oil_zce"


def _flagship() -> dict:
    return {"id": "xmit_palm_soyoil_meal",
            "links": [{"pair_id": "soyoil_palm_vegoil", "source": _PALM, "target": _SBO, "nature": "divergence"},
                      {"pair_id": "soymeal_soyoil_crush", "source": _SBO, "target": _SBM, "nature": "co_move"}]}


def _control() -> dict:
    return {"id": "xmit_vegoil_triangle",
            "links": [{"pair_id": "soyoil_palm_vegoil", "source": _SBO, "target": _PALM},
                      {"pair_id": "palm_rapeoil_vegoil", "source": _PALM, "target": _RSO}]}


def _lint(monkeypatch, chains, *, cap: int | None = 18) -> list[str]:
    monkeypatch.setattr(cc, "_load_transmission_map", lambda: chains)
    monkeypatch.setattr(cc, "_transmission_cap", lambda: cap)
    return cc.check_transmission_map()


# -- POSITIVE: the shipped map, the fixture shape, and the unbuilt no-op --------------------------------
def test_shipped_transmission_map_lints_clean():
    cq.load_transmission_map.cache_clear()
    errs = cc.check_transmission_map()
    assert errs == [], f"the shipped transmission_map.yaml must lint clean, got: {errs}"
    cq.load_transmission_map.cache_clear()


def test_shipped_map_is_the_two_row_v1_catalog():
    cq.load_transmission_map.cache_clear()
    rows = cq.load_transmission_map()
    assert [r["id"] for r in rows] == ["xmit_palm_soyoil_meal", "xmit_vegoil_triangle"]
    assert all(len(r["links"]) == 2 for r in rows)          # D1 depth cap; never the 22-path census
    cq.load_transmission_map.cache_clear()


def test_curated_v1_catalog_lints_clean(monkeypatch):
    assert _lint(monkeypatch, [_flagship(), _control()]) == []


def test_empty_map_no_ops(monkeypatch):
    # absent file / all rows deferred -> [] -> the lint returns clean WITHOUT even requiring a cap (the engine
    # composes nothing), exactly like check_chain_map on an absent chain_map.
    assert _lint(monkeypatch, [], cap=None) == []


# -- CAP (D5): the horizontal engine owns its OWN budget, never the vertical CHAIN_CAP -----------------
def test_cap_resolves_to_the_engines_own_budget():
    # the lint reads the HORIZONTAL constant, never CHAIN_CAP: a shared counter is exactly what the fold pass
    # dropped (finding 3), so the two chain engines stay budget-independent.
    assert cc._transmission_cap() == cq.TRANSMISSION_CAP > 0


def test_depth_cap_tracks_the_engine_constant(monkeypatch):
    # one source of truth: if the engine ever re-decides the v1 depth, the lint moves with it rather than
    # silently green-lighting a row the composer would reject (or rejecting one it accepts).
    monkeypatch.setattr(cq, "TRANSMISSION_DEPTH_CAP", 1)
    errs = _lint(monkeypatch, [_flagship()])
    assert any("links > max 1" in e for e in errs)


def test_missing_cap_rejected(monkeypatch):
    errs = _lint(monkeypatch, [_flagship()], cap=None)
    assert any("transmission-scoped cap" in e and "own" in e for e in errs)


def test_zero_cap_rejected(monkeypatch):
    assert any("transmission-scoped cap" in e for e in _lint(monkeypatch, [_flagship()], cap=0))


# -- REFS RESOLVE TO ACTIVE RV2 LINKS ------------------------------------------------------------------
def test_unknown_pair_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["pair_id"] = "no_such_pair"
    errs = _lint(monkeypatch, [bad])
    assert any("no_such_pair" in e and "not a complex_map pair" in e for e in errs)


def test_non_material_pair_rejected(monkeypatch):
    # load_complex_map DROPS non-material rows, so a chain naming one can never fire -- statically dead.
    full = xcm.load_complex_map()
    monkeypatch.setattr(xcm, "load_complex_map",
                        lambda: xcm.ComplexMap(pairs=[p for p in full.pairs if p.id != "soymeal_soyoil_crush"]))
    errs = _lint(monkeypatch, [_flagship()])
    assert any("soymeal_soyoil_crush" in e and "NOT material" in e and "statically dead" in e for e in errs)


def test_legs_off_the_pair_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["target"] = _RSO                      # soyoil_palm_vegoil is (SBO, PALM), not (PALM, RSO)
    errs = _lint(monkeypatch, [bad])
    assert any("are not the pair's own slugs" in e for e in errs)


# -- CLUSTER MEMBERSHIP (D3): feed_grain is an ISOLATED edge, never a chain ----------------------------
def test_feed_grain_link_rejected(monkeypatch):
    bad = {"id": "xmit_feed",
           "links": [{"pair_id": "corn_wheat_feed", "source": "corn_cbot", "target": "soft_red_winter_wheat_cbot"},
                     {"pair_id": "soyoil_palm_vegoil", "source": _SBO, "target": _PALM}]}
    errs = _lint(monkeypatch, [bad])
    assert any("corn_wheat_feed" in e and "feed_grain" in e and "ISOLATED" in e for e in errs)


# -- DEPTH + DEGENERACY (D1 / 3.2) ---------------------------------------------------------------------
def test_three_links_rejected(monkeypatch):
    bad = _control()
    bad["links"].append({"pair_id": "soyoil_rapeoil_vegoil", "source": _RSO, "target": _SBO})
    errs = _lint(monkeypatch, [bad])
    assert any("links > max" in e for e in errs)


def test_one_link_chain_rejected(monkeypatch):
    bad = _flagship()
    bad["links"] = bad["links"][:1]
    errs = _lint(monkeypatch, [bad])
    assert any("links < min" in e and "RV2 pair" in e for e in errs)


def test_repeated_pair_in_one_row_rejected(monkeypatch):
    bad = {"id": "xmit_dup",
           "links": [{"pair_id": "soyoil_palm_vegoil", "source": _SBO, "target": _PALM},
                     {"pair_id": "soyoil_palm_vegoil", "source": _PALM, "target": _SBO}]}
    errs = _lint(monkeypatch, [bad])
    assert any("repeats in this chain" in e and "degenerate" in e for e in errs)


def test_repeated_node_rejected(monkeypatch):
    bad = {"id": "xmit_cycle",
           "links": [{"pair_id": "soyoil_palm_vegoil", "source": _SBO, "target": _PALM},
                     {"pair_id": "palm_rapeoil_vegoil", "source": _PALM, "target": _RSO},
                     {"pair_id": "soyoil_rapeoil_vegoil", "source": _RSO, "target": _SBO}]}
    errs = _lint(monkeypatch, [bad])
    assert any("SIMPLE paths" in e for e in errs)


def test_too_many_rows_rejected(monkeypatch):
    rows = [dict(_flagship(), id=f"x{i}") for i in range(3)]          # 3 > 2 (D1 catalog = flagship + control)
    errs = _lint(monkeypatch, rows)
    assert any("active rows > max" in e for e in errs)


def test_duplicate_chain_id_rejected(monkeypatch):
    assert any("duplicate chain id" in e for e in _lint(monkeypatch, [_flagship(), _flagship()]))


# -- COMPOSABILITY: oriented hub + the OPTIONAL focus field --------------------------------------------
def test_declared_focus_disagreeing_with_head_rejected(monkeypatch):
    # `focus:` is optional (the head link's source IS the focus `_xmit_select` first-fires on) -- but a row
    # that declares one must agree, or the row it advertises is not the row that can ever select.
    bad = dict(_flagship(), focus=_SBM)
    errs = _lint(monkeypatch, [bad])
    assert any("head-link source" in e and "!= focus" in e for e in errs)


def test_no_focus_field_is_fine(monkeypatch):
    assert "focus" not in _flagship()                     # the shipped schema carries none
    assert _lint(monkeypatch, [_flagship()]) == []


def test_broken_hub_orientation_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][1] = {"pair_id": "palm_rapeoil_vegoil", "source": _PALM, "target": _RSO}   # hub is SBO, not PALM
    errs = _lint(monkeypatch, [bad])
    assert any("!= the prior link's target" in e for e in errs)


def test_self_link_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][1] = {"pair_id": "soymeal_soyoil_crush", "source": _SBO, "target": _SBO}
    errs = _lint(monkeypatch, [bad])
    assert any("source == target" in e for e in errs)


def test_link_missing_pair_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][1] = {"source": _SBO, "target": _SBM}
    assert any("needs pair_id/source/target" in e for e in _lint(monkeypatch, [bad]))


# -- THE ENGINE-DROP CROSS-CHECK: an inert row must FAIL the build, not vanish -------------------------
def test_row_the_engine_loader_drops_is_reported(monkeypatch):
    # cascade.load_transmission_map DROPS structurally-bad rows fail-closed. Linting its OUTPUT would green
    # the build while the chain silently never composes -- so the lint reads the AUTHORED rows and reports
    # the divergence itself.
    bad = _flagship()
    bad["links"] = bad["links"][:1]                       # 1 link -> _transmission_row_ok False
    assert not cq._transmission_row_ok(bad)
    errs = _lint(monkeypatch, [bad])
    assert any("ENGINE loader DROPS this row" in e and "INERT" in e for e in errs)


def test_bad_nature_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["nature"] = "pass_through"            # and even a VALID nature is a hint, never a gate (D9)
    errs = _lint(monkeypatch, [bad])
    assert any("bad nature" in e and "EXPECTATION hint" in e for e in errs)


# -- NO VERTICAL-CHAIN REF REUSE (D6) ------------------------------------------------------------------
def test_cascade_map_ref_as_pair_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["pair_id"] = "psd_ending_stock_su_ratio"             # a VERTICAL hop's ref, not a pair
    errs = _lint(monkeypatch, [bad])
    assert any("cascade_map REF" in e and "vertical-chain ref reuse" in e for e in errs)


def test_vertical_chain_id_as_pair_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["pair_id"] = "corn_lanina_safrinha_su"               # a chain_map chain id
    errs = _lint(monkeypatch, [bad])
    assert any("VERTICAL chain id" in e and "vertical-chain ref reuse" in e for e in errs)


def test_vertical_hop_keys_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][0]["ref"] = "psd_ending_stock_su_ratio"
    bad["links"][1]["node"] = "La_Nina"
    errs = _lint(monkeypatch, [bad])
    assert any("VERTICAL hop key 'ref'" in e for e in errs)
    assert any("VERTICAL hop key 'node'" in e for e in errs)


def test_row_id_colliding_with_vertical_chain_rejected(monkeypatch):
    bad = dict(_flagship(), id="corn_lanina_safrinha_su")
    errs = _lint(monkeypatch, [bad])
    assert any("collides with a vertical chain_map chain id" in e for e in errs)


# -- STATICALLY DEAD LEGS (the OFFLINE half of the per-pair census, sec 1.3 axes (a)/(b)) --------------
def test_unloaded_leg_rejected(monkeypatch):
    bad = _flagship()
    bad["links"][1]["target"] = "totally_fake_contract"
    errs = _lint(monkeypatch, [bad])
    assert any("totally_fake_contract" in e and "not a loaded contract" in e for e in errs)


def test_psd_unserved_leg_rejected(monkeypatch):
    # cocoa IS a loaded contract but carries NO PSD balance sheet (PSD_UNSERVED_SLUGS), so its World su_ratio
    # can never resolve -- a chain over it is dead on arrival. Injected as a material pair so the leg check,
    # not the pair check, is what rejects it.
    full = xcm.load_complex_map()
    fake = xcm.ComplexPair(id="cocoa_soyoil_fake", pair=("cocoa", _SBO), complex_name="vegoil_substitution",
                           shared_event="x", side_a={"contract": "cocoa", "country_rule": "world"},
                           side_b={"contract": _SBO, "country_rule": "world"}, direction="opposing",
                           focus_rule="query", materiality_tier="material")
    monkeypatch.setattr(xcm, "load_complex_map", lambda: xcm.ComplexMap(pairs=[*full.pairs, fake]))
    row = {"id": "xmit_cocoa",
           "links": [{"pair_id": "cocoa_soyoil_fake", "source": "cocoa", "target": _SBO},
                     {"pair_id": "soymeal_soyoil_crush", "source": _SBO, "target": _SBM}]}
    errs = _lint(monkeypatch, [row])
    assert any("cocoa" in e and "PSD-UNSERVED" in e and "statically dead" in e for e in errs)


def test_non_world_country_rule_rejected(monkeypatch):
    full = xcm.load_complex_map()
    patched = []
    for p in full.pairs:
        if p.id == "soyoil_palm_vegoil":
            p = xcm.ComplexPair(**{**p.__dict__, "side_a": {**p.side_a, "country_rule": "primary"}})
        patched.append(p)
    monkeypatch.setattr(xcm, "load_complex_map", lambda: xcm.ComplexMap(pairs=patched))
    errs = _lint(monkeypatch, [_flagship()])
    assert any("country_rule" in e and "every transmission leg is World" in e for e in errs)
