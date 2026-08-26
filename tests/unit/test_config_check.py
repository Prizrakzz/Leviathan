"""Driver-slice darkness lint (Phase 7 P2 W2) — hermetic, synthetic, zero-spend.

check_driver_slices() (resolver in evidence.py, registered in config_check.py) makes three assertions in one
pass over the parent-inclusive causal driver set: (a) every DAG id resolves to a slice OR carries a waiver,
(b) every dag_alias RHS id shares a topical token with its target slice (the urea->area law), (c) no id is
routed to 2+ distinct slices. These tests pin each branch on SYNTHETIC fixtures — a tmp causal dir + a tmp
driver_slices.yaml — never real DAG/slice content (that config is private IP). display.all_driver_ids() is
lru_cached and evidence caches the alias map in three plain module globals; BOTH are reset in try/finally in
every test so a synthetic lint never leaks into another test (the register-cache-poisoning discipline).
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import display as dp
from leviathan.graphrag import driver_slices_manifest as dsm
from leviathan.graphrag import evidence as ev


def _wire(monkeypatch, tmp_path, *, causal_yaml: str, driver_yaml: str, mirror: bool = True):
    """Point display at a synthetic causal dir and evidence at a synthetic driver_slices.yaml, caches cleared.
    Caller MUST reset in a finally (see the try/finally in each test).

    G2: check_driver_slices now also lints the TRACKED manifest mirror (driver_slices_manifest), which lives
    beside its source — so a synthetic config gets a synthetic mirror generated from it. `mirror=False`
    leaves it absent, which is itself a hard failure (the tracked-config-went-missing class)."""
    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(causal_yaml, encoding="utf-8")
    monkeypatch.setattr(dp, "_CFG", tmp_path)                 # display globs _CFG/causal/*.yaml
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text(driver_yaml, encoding="utf-8")
    monkeypatch.setattr(ev, "_DRIVER_PATH", drv)
    ev._reset()
    dp.all_driver_ids.cache_clear()
    if mirror:
        dsm.write()                                           # manifest_path() derives from _DRIVER_PATH.parent


def _reset():
    ev._reset()
    dp.all_driver_ids.cache_clear()


def test_clean_config_passes(tmp_path, monkeypatch):
    # exact-name identity + a topically-valid alias + a waivered id + an accented id that folds -> all clean.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: frost\n"                                       # exact-name slice (identity)
        "- id: china_drought\n"                               # aliased to 'drought' (shares 'drought' token)
        "- id: EUR_USD\n"                                     # silver-only cross -> waivered
        "- id: "
        "El_Niño\n"                                           # accented -> folds onto 'el_nino'
    )
    drivers = (
        "drivers:\n"
        "  frost: {category: hazard, terms: [freeze]}\n"
        "  drought: {category: hazard, terms: [dry spell]}\n"
        "  el_nino: {category: teleconnection, terms: [enso]}\n"
        "dag_alias:\n"
        "  drought: [china_drought]\n"
        "  el_nino: [El_Nino]\n"
        "waivers:\n"
        "  EUR_USD: {category: silver_only, note: FX cross}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.check_driver_slices() == []                 # nothing dark, no fuzzy alias, no duplicate
    finally:
        _reset()


def test_dark_unwaivered_id_is_flagged(tmp_path, monkeypatch):
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: frost\n"
        "- id: lonely_dark\n"                                 # no slice, no waiver -> DARK
    )
    drivers = "drivers:\n  frost: {category: hazard, terms: [freeze]}\n"
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        errs = ev.check_driver_slices()
        assert any("dark id lonely_dark" in e for e in errs)
        assert not any("frost" in e for e in errs)            # frost resolves by identity -> not flagged
    finally:
        _reset()


def test_waivered_id_passes(tmp_path, monkeypatch):
    # the same otherwise-dark id, now carrying a waiver -> accounted, not flagged.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: frost\n"
        "- id: EUR_USD\n"
    )
    drivers = (
        "drivers:\n"
        "  frost: {category: hazard, terms: [freeze]}\n"
        "waivers:\n"
        "  EUR_USD: {category: silver_only, note: FX cross has no text slice}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert not any("EUR_USD" in e for e in ev.check_driver_slices())
    finally:
        _reset()


def test_accented_id_passes_post_fold(tmp_path, monkeypatch):
    # El_Nino is byte-dark against the ASCII 'el_nino' slice, but driver_alias()'s fold pass backs it -> the
    # darkness check must NOT flag it (it resolves through backed_dag_ids()).
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: "
        "El_Niño\n"
    )
    drivers = (
        "drivers:\n"
        "  el_nino: {category: teleconnection, terms: [enso]}\n"
        "dag_alias:\n"
        "  el_nino: [El_Nino]\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.check_driver_slices() == []                 # accented id resolves post-fold
    finally:
        _reset()


def test_pure_fuzzy_alias_is_flagged(tmp_path, monkeypatch):
    # urea -> area: a phonetic near-miss with ZERO shared topical token (the class the check exists to catch).
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: urea\n"
    )
    drivers = (
        "drivers:\n"
        "  area: {category: acreage, terms: [planted hectares]}\n"   # no term shares a token with 'urea'
        "dag_alias:\n"
        "  area: [urea]\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        warns = ev.driver_slice_alias_warnings()             # topical-token is an ADVISORY (non-fatal) now
        assert any("urea -> area" in w and "no shared topical token" in w for w in warns)
        assert ev.check_driver_slices() == []                # urea IS backed (on area's RHS) -> no HARD error
    finally:
        _reset()


def test_topical_token_from_terms_widens_the_match(tmp_path, monkeypatch):
    # a slice NAME that shares no token with the id still passes when a `terms` phrase supplies the token
    # (terms are the secondary widening set) — this must NOT be flagged even as an advisory warning.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: hog_herd_demand\n"
    )
    drivers = (
        "drivers:\n"
        "  livestock_feed: {category: demand, terms: [hog inventory, feed ration]}\n"   # 'hog' shared via terms
        "dag_alias:\n"
        "  livestock_feed: [hog_herd_demand]\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.driver_slice_alias_warnings() == []         # 'hog' term token bridges id and slice
        assert ev.check_driver_slices() == []                 # and no hard error either
    finally:
        _reset()


def test_self_alias_not_flagged(tmp_path, monkeypatch):
    # a dag_alias RHS whose id EQUALS its own slice name (export_ban, frost in prod) is a benign no-op
    # (driver_alias setdefault) — NOT a topical-token failure and NOT a duplicate.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: export_ban\n"
    )
    drivers = (
        "drivers:\n"
        "  export_ban: {category: policy, terms: [ban]}\n"
        "dag_alias:\n"
        "  export_ban: [export_ban]\n"                        # self-alias
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.check_driver_slices() == []                 # self-alias produces no error of any kind
    finally:
        _reset()


def test_cross_slice_duplicate_is_flagged(tmp_path, monkeypatch):
    # one id routed to TWO distinct slices = a double-ownership regression -> hard error.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: drought_stress\n"
    )
    drivers = (
        "drivers:\n"
        "  drought: {category: hazard, terms: [dry]}\n"
        "  stress: {category: hazard, terms: [stress]}\n"
        "dag_alias:\n"
        "  drought: [drought_stress]\n"
        "  stress: [drought_stress]\n"                        # same id on a second, distinct slice
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        errs = ev.check_driver_slices()
        assert any("duplicate id drought_stress" in e for e in errs)
    finally:
        _reset()


# ── D5 bare-name sweep (Phase 7 E4) ──────────────────────────────────────────────────────────────────
# bare_name_warnings() flags a commodity node whose OWN matcher misses its bare head-commodity word (the C1
# coffee-bug class: 'arabica coffee' never fires on bare 'coffee'), while suppressing the benign grade-code/
# qualifier/generic-form tokens. Hermetic: synthesize the node set + each node's alias/extra_terms surface
# forms (so match_forms is fully fixture-determined); monkeypatch auto-undoes, no cache to leak.
def _wire_nodes(monkeypatch, node_forms: dict):
    """node_forms = {node_id: {"aliases": [...], "extra_terms": [...]}}. Drives all_nodes() + match_forms()."""
    monkeypatch.setattr(ev, "all_nodes", lambda: sorted(node_forms))
    monkeypatch.setattr(ev, "_aliases", lambda n: list(node_forms.get(n, {}).get("aliases", [])))
    monkeypatch.setattr(ev, "_extra_terms", lambda n: list(node_forms.get(n, {}).get("extra_terms", [])))


def test_bare_name_flags_missing_head_commodity_word(monkeypatch):
    # 'arabica coffee' (the spaced id) + alias 'arabica' never fire on bare 'coffee' -> the real gap; the
    # 'arabica' token DOES fire (via its alias) so only 'coffee' is flagged.
    _wire_nodes(monkeypatch, {"arabica_coffee": {"aliases": ["arabica"], "extra_terms": []}})
    warns = ev.bare_name_warnings()
    assert len(warns) == 1
    assert "arabica_coffee" in warns[0] and "'coffee'" in warns[0]
    assert "extra_terms" in warns[0]                          # message points the reviewer at the one-line fix
    assert warns[0].encode("ascii")                           # ASCII-safe (cp1252 stdout rule)


def test_bare_name_clean_once_head_word_in_extra_terms(monkeypatch):
    # the C1 fix: adding the bare word to extra_terms makes the node's matcher fire -> no warning.
    _wire_nodes(monkeypatch, {"arabica_coffee": {"aliases": ["arabica"], "extra_terms": ["coffee"]}})
    assert ev.bare_name_warnings() == []


def test_bare_name_suppresses_benign_qualifiers_and_forms(monkeypatch):
    # 'raw'/'french'/grade codes are qualifiers and 'oil'/'meal'/'juice' generic co-product forms -- a matcher
    # miss on any of these is NOT a gap and must be suppressed (each covered by another form or bare-generic).
    _wire_nodes(monkeypatch, {
        "raw_sugar":  {"aliases": [], "extra_terms": ["sugar"]},   # 'raw' benign; 'sugar' fires
        "palm_oil":   {"aliases": [], "extra_terms": ["palm"]},    # 'oil' benign; 'palm' fires
        "hrs_wheat":  {"aliases": [], "extra_terms": ["wheat"]},   # 'hrs' grade code benign; 'wheat' fires
        "orange_juice": {"aliases": ["orange"], "extra_terms": []},  # 'juice' benign; 'orange' fires via alias
    })
    assert ev.bare_name_warnings() == []


# ── F-A item O #1: the ALIAS-MASS sweep (vocab-sweep hygiene rider 14) ───────────────────────────────
# A23's register states the gap in one sentence: "bare_name_warnings() structurally CANNOT catch this class
# (it tests only tokens OF the node id) -- a new lint is owed alongside the fixes". This is that lint. It
# compares the EXTRACTION lane (entity_vocabulary `aliases:`) against the ROUTING lane (driver_slices
# `terms:`) for every concept that owns a driver slice, which is the "gas-hub class": the extractor can mint
# an entity the slice matcher can never route. Hermetic -- synthesize both lanes, monkeypatch auto-undoes.
def _wire_alias_lanes(monkeypatch, vocab_aliases: dict, slice_terms: dict):
    from leviathan.graphrag import extract as ex
    monkeypatch.setattr(ex, "_vocab", lambda: {"aliases": vocab_aliases})
    monkeypatch.setattr(ev, "_driver_raw", lambda: {"drivers": {n: {"category": "x", "terms": list(t)}
                                                               for n, t in slice_terms.items()}})
    ev._reset()


def test_alias_mass_flags_the_gas_hub_class(monkeypatch):
    # THE MEASURED INSTANCE, reproduced as a fixture: entity_vocabulary declares the gas HUB roster while the
    # `natural_gas` slice carries only the two generic forms. 'natural gas' is a token-spelling of the id
    # (bare_name's job, skipped here); 'natgas' is the finding. 'Henry Hub'/'TTF' are suppressed as RECORDED
    # refusals -- measured at ONE prop on the full chunk cache, real fix = the Phase-G wb_cmo text-layer
    # repair -- which is what proves a suppression is a written refusal and not a silence.
    try:
        _wire_alias_lanes(monkeypatch,
                          {"natural_gas": ["natural gas", "natgas", "gas prices", "Henry Hub", "TTF"]},
                          {"natural_gas": ["natural gas", "gas prices"]})
        warns = ev.alias_mass_warnings()
        assert len(warns) == 1 and "natgas" in warns[0] and "natural_gas" in warns[0]
        assert "cannot ROUTE" in warns[0] and "_ALIAS_MASS_BENIGN" in warns[0]
        assert warns[0].encode("ascii")                        # ASCII-safe (cp1252 stdout rule)
    finally:
        ev._reset()


def test_alias_mass_clean_once_the_term_lands_and_skips_unowned_concepts(monkeypatch):
    # Two properties in one fixture. (1) THE FIX: adding the form to the slice's terms clears the finding --
    # the lint follows the routing lane, not a hardcoded list. (2) SCOPE: a vocabulary concept that owns NO
    # driver slice is not this lint's class at all (the node side is bare_name_warnings') and must not be
    # reported, or the sweep would flag all ~185 alias keys against 126 slices.
    try:
        _wire_alias_lanes(monkeypatch,
                          {"natural_gas": ["natgas"], "arabica_coffee": ["arabica", "cafe arabica"]},
                          {"natural_gas": ["natural gas", "natgas"]})
        assert ev.alias_mass_warnings() == []
    finally:
        ev._reset()


def test_alias_mass_follows_the_declared_dual_home_map_and_ranks_by_mass(monkeypatch):
    # The estate deliberately names some node/slice pairs differently (fish_meal the node vs
    # marine_protein_fishmeal the slice), so identity alone would miss them; _ALIAS_CONCEPT_SLICE declares
    # the exceptions rather than guessing. Mass is OPTIONAL and never fetched: a caller holding counts passes
    # them and the lines rank, which is the half of "test aliases against corpus mass" a $0 config lint can
    # honestly own -- the corpus half belongs to slice_audit.py.
    try:
        _wire_alias_lanes(monkeypatch,
                          {"fish_meal": ["marine protein"], "frost": ["geada", "cold damage"]},
                          {"marine_protein_fishmeal": ["fishmeal", "fish meal"], "frost": ["frost", "freeze"]})
        warns = ev.alias_mass_warnings()
        assert len(warns) == 3
        assert any("fish_meal" in w and "marine_protein_fishmeal" in w for w in warns)
        ranked = ev.alias_mass_warnings(mass={"geada": 400, "cold damage": 9, "marine protein": 0})
        assert "geada" in ranked[0] and "[400 measured]" in ranked[0]
        assert "marine protein" in ranked[-1]
    finally:
        ev._reset()


def test_config_check_wrapper_delegates(tmp_path, monkeypatch):
    # the thin config_check.check_driver_slices() wrapper must call the evidence resolver (lint and the
    # runtime router agree by construction). Point both at a synthetic dark config and assert the flag surfaces.
    causal = (
        "contract: test_contract\n"
        "drivers:\n"
        "- id: lonely_dark\n"
    )
    drivers = "drivers:\n  frost: {category: hazard, terms: [freeze]}\n"
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert any("dark id lonely_dark" in e for e in cc.check_driver_slices())
    finally:
        _reset()


# -- PRICE_OBSERVABILITY W0.2 -- price/positioning register-fence lint ---------------------------------------
def test_check_register_detector_ships_lexicon():
    # the R2/R8 probe: every banned term + class rule flags, every ag-collision probe stays clean.
    assert cc._check_register_detector() == []


def test_no_engine_ref_flags_and_passes():
    assert cc._check_no_engine_ref({"r1": {"table": "silver_pink_sheet"}}, cc.PRICE_TABLES, "R4", "price")
    assert cc._check_no_engine_ref({"r1": {"table": "silver_cot"}}, cc.POSITIONING_TABLES, "R9", "positioning")
    assert cc._check_no_engine_ref({"r1": {"table": "silver_wasde"}}, cc.PRICE_TABLES, "R4", "price") == []
    assert cc._check_no_engine_ref({}, cc.PRICE_TABLES, "R4", "price") == []


# -- C1 / D1: R9 AS AMENDED -- the positioning CONTEXT/ENGINE split (was a blanket cascade_map ban) ---------
_COT_CONTEXT_ROW = {"table": "silver_cot", "metric": "mm_net", "agg": "latest", "period_type": "date",
                    "leg_mode": "current", "country_rule": "none", "native_unit": "contracts",
                    "narrate_unit": "contracts", "scale": 1}


def _with_cot_map(monkeypatch, row=None):
    from leviathan.graphrag.numbers import cascade as csc
    real = csc.load_map()
    monkeypatch.setattr(csc, "load_map",
                        lambda: {**real, "cot_mm_positioning": row or _COT_CONTEXT_ROW})


def test_positioning_lane_admits_the_ratified_context_shape(monkeypatch):
    # the whole point of D1: the ref EXISTING is no longer a build failure -- only the wrong SHAPE is.
    _with_cot_map(monkeypatch)
    assert cc._check_positioning_lane() == []
    assert cc.check_cot_register() == []                       # R7/R10 still fire and stay clean


@pytest.mark.parametrize("tweak,needle", [
    ({"leg_mode": "era"}, "FORK backbone"),                    # era legs ARE the cross-era fork
    ({"period_type": "marketing_year"}, "marketing-year fork window"),
    ({"metric": "exports_mt"}, "reroute PAIR"),                # the RF-3 fork
    ({"narrate_unit": "flag"}, "REGIME MARKER"),
])
def test_positioning_lane_refuses_every_engine_shape(monkeypatch, tweak, needle):
    _with_cot_map(monkeypatch, {**_COT_CONTEXT_ROW, **tweak})
    errs = cc._check_positioning_lane()
    assert errs and any(needle in e for e in errs), errs
    assert all(e.startswith("R9 cascade_map 'cot_mm_positioning'") for e in errs)


def test_positioning_lane_bans_the_engine_maps_by_NAME(monkeypatch):
    # a hop/leg is an engine position whatever shape the underlying row has, so the chain/complex/
    # transmission half bans the REF NAME, never the row shape.
    from leviathan.graphrag.numbers import cascade as csc
    _with_cot_map(monkeypatch)
    monkeypatch.setattr(csc, "load_chain_map",
                        lambda: [{"id": "c1", "hops": [{"node": "n", "ref": "cot_mm_positioning"}]}])
    errs = cc._check_positioning_lane()
    assert any("chain_map 'c1'" in e and "never a chain hop" in e for e in errs), errs


def test_positioning_lane_pins_the_fenced_set_against_the_engine(monkeypatch):
    # ONE fenced set: cascade cannot import config_check (cycle), so the mirror is pinned at build time.
    from leviathan.graphrag.numbers import cascade as csc
    assert csc.POSITIONING_TABLES == frozenset(cc.POSITIONING_TABLES)
    monkeypatch.setattr(csc, "POSITIONING_TABLES", frozenset({"silver_cot", "silver_drifted"}))
    assert any("R9 drift" in e for e in cc._check_positioning_lane())


def test_r4_price_fence_is_a_split_and_the_non_register_path_still_fails():
    """R4 AS AMENDED (price_context, 2026-08-26) -- the same context/engine split D1 gave R9, five weeks
    later and on its own adjudication. This pin holds the REFUSING half, which is the half that carries
    the doctrine: the probe row is COT-shaped (`metric: mm_net`), so it is not a pink-sheet metric and can
    never be in PRICE_CONTEXT_METRICS -- a row at the price table whose metric is off the register fails
    the build no matter how "context-shaped" the rest of it looks. Both call forms are pinned, because
    both are live: WITHOUT the validator the helper is still the original blanket ban (that default is
    what keeps F047's quarantine reuse byte-identical), and WITH it the refusal is per-row and says why."""
    blanket = cc._check_no_engine_ref({"p": {**_COT_CONTEXT_ROW, "table": "silver_pink_sheet"}},
                                      cc.PRICE_TABLES, "R4", "price")
    assert blanket and "must never feed an engine" in blanket[0]
    split = cc._check_no_engine_ref({"p": {**_COT_CONTEXT_ROW, "table": "silver_pink_sheet"}},
                                    cc.PRICE_TABLES, "R4", "price", allow=cc.price_context_violations)
    assert split and any("PRICE_CONTEXT_METRICS" in e for e in split), split
    assert "mm_net" not in cc.PRICE_CONTEXT_METRICS


def test_price_context_lane_admits_the_ratified_shape_and_refuses_every_other():
    """The ADMITTING half, and each way in that stays shut. The admitted shape is the one the live
    `fishmeal_price_z` row declares; every tweak below names a code path the amendment closes."""
    row = {"table": "silver_pink_sheet", "metric": "fish_meal_usd_t_zscore_5yr", "agg": "latest",
           "period_type": "date", "leg_mode": "current", "country_rule": "none",
           "native_unit": "z", "narrate_unit": "z", "scale": 1}
    assert cc.price_context_violations(row) == []
    for tweak, needle in (({"metric": "maize_usd_t"}, "PRICE_CONTEXT_METRICS"),       # a target benchmark
                          ({"metric": "beef_usd_t"}, "PRICE_CONTEXT_METRICS"),        # an OUTPUT price
                          ({"metric": "rubber_rss3_usd_t_zscore_5yr"}, "PRICE_CONTEXT_METRICS"),  # the
                          # 2026-08-27 refuted admission: a real card z, still out (sign-identity)
                          ({"leg_mode": "era"}, "no as-of replay"),                   # the C-2 objection
                          ({"country_rule": "region"}, "wide and flat"),
                          ({"narrate_unit": "flag"}, "REGIME MARKER")):
        bad = cc.price_context_violations({**row, **tweak})
        assert bad and any(needle in b for b in bad), (tweak, bad)
    # the OMITTED-agg fail-open, closed 2026-08-27 (the hazards sweep's find): the lint used to
    # default an absent agg to 'latest' while _node_specs compiles it as 'series' -- a 365-day
    # collapse over a price history arriving through a default disagreement. Absent agg now REFUSES.
    no_agg = {k: v for k, v in row.items() if k != "agg"}
    bad = cc.price_context_violations(no_agg)
    assert bad and any("must be declared" in b for b in bad), bad
    assert cc.price_context_violations({"table": "silver_pink_sheet"})                 # fail-closed on bare


def test_the_price_context_register_is_input_costs_and_fishmeal_only():
    """The MEMBERSHIP half, pinned as a set rather than trusted to a comment. 20 of the card's 76
    metrics: 9 input-cost levels + fish_meal_usd_t + one z twin each. Every estate-target benchmark is
    OUT, permanently, on self-reference -- a benchmark leg answers a price question about the very
    contract the cascade is explaining."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry().tables.get("silver_pink_sheet")
    assert len(cc.PRICE_CONTEXT_METRICS) == 20
    levels = {m for m in cc.PRICE_CONTEXT_METRICS if not m.endswith("_zscore_5yr")}
    assert len(levels) == 10 and "fish_meal_usd_t" in levels
    assert {f"{m}_zscore_5yr" for m in levels} == cc.PRICE_CONTEXT_METRICS - levels   # twins move together
    for benchmark in ("soybeans_usd_t", "soybean_meal_usd_t", "maize_usd_t", "palm_oil_cpo_usd_t",
                      "wheat_us_hrw_usd_t", "raw_sugar_world_usd_t", "cocoa_usd_t", "cotton_a_index_usd_t",
                      "beef_usd_t", "chicken_usd_t", "copper_usd_mt"):
        assert benchmark not in cc.PRICE_CONTEXT_METRICS
        assert f"{benchmark}_zscore_5yr" not in cc.PRICE_CONTEXT_METRICS
    if reg is not None:                                    # every register member is a REAL card metric
        assert cc.PRICE_CONTEXT_METRICS <= set(reg.metrics)


def test_price_context_lane_bans_the_engine_maps_by_NAME(monkeypatch):
    # the R9 idiom on the price card: a hop is an engine position whatever shape the row has.
    from leviathan.graphrag.numbers import cascade as csc
    if not any((r or {}).get("table") in cc.PRICE_TABLES for r in (csc.load_map() or {}).values()):
        pytest.skip("no private cascade_map in this tree")
    # pinned to a NAMED ref (2026-08-27): with eight pink-sheet rows live, `next(...)` would probe
    # whichever the mapping yields first and silently stop testing a known ref.
    ref = "fishmeal_price_z" if (csc.load_map() or {}).get("fishmeal_price_z") else \
        next(r for r, row in csc.load_map().items() if (row or {}).get("table") in cc.PRICE_TABLES)
    monkeypatch.setattr(csc, "load_chain_map", lambda: [{"id": "c1", "hops": [{"node": "n", "ref": ref}]}])
    errs = cc._check_price_context_lane()
    assert any("chain_map 'c1'" in e and "never a chain hop" in e for e in errs), errs


def test_positioning_corn_no_fork_deck_pin_still_holds_with_the_ref_mapped(monkeypatch):
    """The v4_cascade pin `positioning_corn_no_fork` asserts `cascade_fired: false` on a positioning
    ask, and C1 must not flip it. It does not: the pin declares `cascade_drivers: [cot_mm_positioning]`,
    which is a silver_ref and NOT a corn driver id (corn's driver is `managed_money_positioning`
    CARRYING that ref), so `_driver(...)` returns None and `driver_fireable` is False at that gate --
    before `map_row` is ever consulted. Executed with the ref mapped, which is the only way to know."""
    from leviathan.graphrag.numbers import cascade_census as cen
    _with_cot_map(monkeypatch)
    assert cen.driver_fireable("corn", "cot_mm_positioning") is False
    assert cen.query_realizable({"contract": "corn",
                                 "cascade_drivers": ["cot_mm_positioning"]}) is False
    # ... and the driver id it SHOULD have declared is the one the mapping actually enables.
    assert cen.driver_fireable("corn", "managed_money_positioning") is True


def test_decline_census_vacuous_until_template_registry():
    # R5: the W2.5 numbers-agent template registry does not exist yet -> vacuous pass (printed note, no errors).
    assert cc._check_decline_census() == []


def test_check_price_and_cot_register_green_on_real_config():
    # W0 GATE: both new checks pass on the live config -- nothing registered yet, R4/R9 active and clean.
    assert cc.check_price_register() == []
    assert cc.check_cot_register() == []


# -- SEAM C futures v1.5-lite lint (levels-only card + unit_overrides + whitelisted-and-served gate) ----
def test_check_futures_lite_green_on_real_config():
    # the card exists with the exact levels-only shape, close-only + 12-slug unit_overrides, is
    # WHITELISTED-AND-SERVED (2026-07-23), and every decline template is register-clean.
    assert cc.check_futures_lite() == []


def test_check_futures_lite_flags_whitelist_regression(monkeypatch):
    # post-whitelist the served card must be PRESENT in the loaded registry; if it ever fell back OUT
    # (dropped at load again), the lint must fail closed on the whitelist regression.
    import leviathan.graphrag.numbers.registry as R
    real = R.load_registry()
    dropped = R.NumbersRegistry(tables={k: v for k, v in real.tables.items()
                                        if k != "silver_futures_prices"})
    monkeypatch.setattr(R, "load_registry", lambda path=None: dropped)
    assert any("ABSENT from the SERVED registry" in e for e in cc.check_futures_lite())


# -- SILVER-F047 quarantine (corrected 2026-07-21: engine-leg ban is the REAL fence; no dispatch guard exists) --
def test_quarantine_engine_ref_flagged():
    # a cascade_map ref at a quarantined table must fail the build (the F047 INV-3 rule as lint, not prose)
    errs = cc._check_no_engine_ref(
        {"weather_leg": {"table": "silver_nasa_power"}}, ("silver_nasa_power",), "F047", "quarantined")
    assert errs and "silver_nasa_power" in errs[0]


def test_check_quarantine_green_on_real_config():
    # live cascade_map/complex_map reference no quarantined table (the weather leg reads gold_weather_z)
    assert cc.check_quarantine() == []


def test_nasa_power_quarantine_flag_loaded():
    # the flag survives the extra="forbid" loader (it was silently DROPPED by pydantic before 2026-07-21)
    from leviathan.graphrag.numbers.registry import load_registry
    assert load_registry().get("silver_nasa_power").quarantined is True


def test_nasa_power_excluded_from_pg_mirror():
    # the pg mirror excludes the projection by size; a P1_TABLES edit re-adding it must trip this pin
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "jobs" / "utils" / "load_pg_numbers.py").read_text(
        encoding="utf-8")
    p1 = next(ast.literal_eval(node.value) for node in ast.walk(ast.parse(src))
              if isinstance(node, ast.Assign)
              and any(getattr(t, "id", None) == "P1_TABLES" for t in node.targets))
    assert "silver_nasa_power" not in p1 and "silver_psd" in p1


# -- numbers card-vs-DDL schema pins (the silver_nasa_power COLUMN_NOT_FOUND incident, 2026-07-21) --
def test_numbers_schema_pins_green_on_live_config():
    # every numbers-registry table's referenced columns resolve in its checked-in DDL (nasa_power's DDL
    # was synced to the compacted [commodity, year] + in-file country/region/month layout in the same fix)
    assert cc.check_numbers_schema_pins() == []


def test_numbers_schema_pins_flag_a_missing_column(monkeypatch, tmp_path):
    # a card referencing a column absent from its DDL must fail the build
    import leviathan.graphrag.numbers.registry as R
    live = R.load_registry()
    nasa = live.get("silver_nasa_power").model_copy(update={"country_col": "countryy_typo"})
    reg = R.NumbersRegistry(tables={**live.tables, "silver_nasa_power": nasa})
    monkeypatch.setattr(R, "load_registry", lambda path=None: reg)
    errs = cc.check_numbers_schema_pins()
    assert any("countryy_typo" in e and "silver_nasa_power" in e for e in errs)


# ── G8: the cross-fire class had NO standing detector ──────────────────────────────────────────────────
# check_driver_slices' two hard checks read the dag_alias ID map, so neither can see a TERM substring
# collision; G2's mirror hashes term SETS, so it detects that an edit happened, never that two slices claim
# the same prop. A 20% deterministic sample over all 109 slices found 1,319 props claimed by 2+ slices and
# at least 15 slice pairs cross-claiming MORE than coffee/cereal. This lint REPORTS: deleting a term is a
# routing change and belongs in the artifact-staling bundle, never in a lint.
_CROSS_CAUSAL = "contract: c\ndrivers:\n- id: cereal_rust_complex\n- id: coffee_rust_crop\n"


def test_cross_fire_lint_finds_the_leaf_rust_shape(tmp_path, monkeypatch):
    drivers = (
        "drivers:\n"
        "  cereal_rust_complex: {category: disease, terms: [leaf rust, stripe rust]}\n"
        "  coffee_rust_crop: {category: disease, terms: [coffee leaf rust, ferrugem do cafeeiro]}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=_CROSS_CAUSAL, driver_yaml=drivers)
    try:
        warns = ev.term_collision_warnings()
        assert len(warns) == 1
        assert "cereal_rust_complex:'leaf rust'" in warns[0]
        assert "coffee_rust_crop:'coffee leaf rust'" in warns[0]
        assert ev.check_driver_slices() == []                 # REPORTS ONLY -- never a hard failure
    finally:
        _reset()


def test_cross_fire_lint_ignores_same_slice_and_equal_terms(tmp_path, monkeypatch):
    drivers = (
        "drivers:\n"
        "  cereal_rust_complex: {category: disease, terms: [rust, leaf rust, LEAF RUST]}\n"
        "  coffee_rust_crop: {category: disease, terms: [leaf rust]}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=_CROSS_CAUSAL, driver_yaml=drivers)
    try:
        warns = ev.term_collision_warnings()
        # 'rust' inside the OTHER slice's 'leaf rust' is the only cross-slice proper substring; the
        # same-slice pair and the case-variant duplicate are both skipped (normalization is the matcher's).
        assert len(warns) == 1 and "cereal_rust_complex:'rust'" in warns[0]
        assert "coffee_rust_crop:'leaf rust'" in warns[0]
    finally:
        _reset()


def test_cross_fire_requires_a_word_boundary(tmp_path, monkeypatch):
    # 'india' must NOT collide with 'indiana' -- the same law geography.py's docstring states, and the
    # reason harvest._Matcher escapes and word-bounds every term in the first place.
    drivers = (
        "drivers:\n"
        "  a_slice: {category: x, terms: [india]}\n"
        "  b_slice: {category: x, terms: [indiana corn]}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml="contract: c\ndrivers:\n- id: a_slice\n- id: b_slice\n",
          driver_yaml=drivers)
    try:
        assert ev.term_collision_warnings() == []
    finally:
        _reset()


# ── G7.2: the read-dark census, pinned ─────────────────────────────────────────────────────────────────
def test_a_new_unaccounted_read_dark_slice_is_a_hard_error(tmp_path, monkeypatch):
    causal = "contract: c\ndrivers:\n- id: frost\n"
    drivers = (
        "drivers:\n"
        "  frost: {category: hazard, terms: [freeze]}\n"
        "  orphan_slice: {category: hazard, terms: [nothing reaches me]}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.read_dark_slices() == {"orphan_slice"}
        errs = ev.check_driver_slices()
        assert any("read-dark slice orphan_slice" in e for e in errs)
        assert any("planner._fill can never reach it" in e for e in errs)
    finally:
        _reset()


def test_a_waived_read_dark_slice_is_accounted_for(tmp_path, monkeypatch):
    """D-EI-4's ratified IOD disposition, in miniature: WAIVING is artifact-free AND render-free, where
    REGISTERING would change the render surface on four contracts and carry the artifact bundle's gate."""
    causal = "contract: c\ndrivers:\n- id: frost\n"
    drivers = (
        "drivers:\n"
        "  frost: {category: hazard, terms: [freeze]}\n"
        "  indian_ocean_dipole: {category: weather_regime, terms: [indian ocean dipole]}\n"
        "waivers:\n"
        "  indian_ocean_dipole: {category: deferred, note: honestly-deferred read-path gap}\n"
    )
    _wire(monkeypatch, tmp_path, causal_yaml=causal, driver_yaml=drivers)
    try:
        assert ev.read_dark_slices() == {"indian_ocean_dipole"}
        assert ev.check_driver_slices() == []                 # waived == accounted for, not hidden
        warns = ev.read_dark_slice_warnings()
        assert any("WAIVED (honestly-deferred gaps): indian_ocean_dipole" in w for w in warns)
        assert any("can never render an episode line" in w for w in warns)
    finally:
        _reset()


def test_the_live_pin_still_matches_the_live_wiring():
    """The read-dark slices are PINNED (READ_DARK_SLICES_PIN, 12 as of 2026-08-21) so nobody re-derives a
    subset by hand again -- the deck author had already measured five of them at
    eval_queries_playbooks_v1.yaml:1130-1140. Skipped on a tree with no private causal configs.

    D-CW-3a (2026-08-07): 29 -> 28. `diesel` left the census when driver_slices.yaml aliased the
    previously-waivered DAG id `gasoil_palm_spread` to it. This assertion is the tooth that makes the pin
    follow the wiring in BOTH directions -- check_driver_slices only ADVISES ("shrink the pin") when a
    pinned slice becomes reachable, because an improvement must never fail a build; the equality here is
    what stops the advisory from being ignored until the pin is folklore.

    D-PQ (2026-08-07): 28 -> 26. `urea` and `potash` left the census the only honest way -- by CURATION,
    not by an alias steal. D-CW-3a had measured that no nutrient-specific driver id existed anywhere in
    the 33 DAGs; D-PQ added them (`urea_cost` on the 12 nitrogen-binding corn/wheat/canola boards,
    `potash_cost` on malaysian_crude_palm_oil_cme), so these two lines invert with the diesel line above:
    what was a SKIP is now an unlock. `dap` is the one that stayed, deliberately -- see the pin comment.

    D-EC D8 Wave-1b (2026-08-19): 14 -> 17, carried in the pin ITSELF. The pre-X2 curation batch authored
    four driver slices on measured backing. ONE of them, `benign_growing_conditions`, was WIRED and never
    entered this census -- it took `favorable_rainfall`, the dark blocker driver_slices.yaml's own dag_alias
    header names, an id that was WAIVERED AND UNOWNED, so the wiring CREATED reach (16 contracts) and cost
    no slice anything. That is the D-CW-3a diesel / gasoil_palm_spread shape exactly.

    The other three are read-dark, and the asymmetry is the lesson. `export_levy_duty` (490 props on the
    full chunk cache) and `marine_protein_fishmeal` (2,511) are dark because not one of the 371 real DAG
    driver ids names an export levy/cess or fishmeal at all -- there is NO WIRING TO DO, and retiring them
    is a DAG-authoring act, the post-X2 half of D8.

    `import_quota_trq` (1,201 props, 450 of them claimed by no other policy slice) is dark BY REFUSAL, and
    that refusal is the fact this docstring exists to record. THE WIRING DID NOT HAPPEN. Its one topical
    DAG id, `China_import_quota_VAT`, is OWNED by `tariff`; an id belongs to exactly one slice
    (check_driver_slices leg (b)), so re-owning it would have MOVED reach rather than created it --
    MEASURED at tariff 28 -> 27 contracts, with `raw_sugar` losing its ONLY tariff-owned id, i.e. one live
    board's tariff leg changing what it reads. D-CW-3a had already refused exactly that trade ("an alias
    steal MOVES reach instead of creating it"), and D8 refused it again on the same reasoning. The refusal
    is recorded in full at two sites in configs/graphrag/driver_slices.yaml -- on `tariff`'s dag_alias entry
    and on the slice's own `waivers:` entry -- and THE YAML IS THE AUTHORITY; this pin is the measurement of
    what that authority produced. An earlier revision of this docstring asserted the wiring HAD happened,
    which contradicted the config it was supposed to be pinning.

    All three carry a `waivers:` entry, so `check_driver_slices` is clean and `config_check` exits 0. They
    are now in READ_DARK_SLICES_PIN as well, which is what makes the equality below an EXACT tooth with no
    debt ledger beside it: a FOURTH unaccounted read-dark slice fails here, and so does a pinned name that
    quietly became reachable. Retire any of the three by minting the DAG driver id that reaches it.

    D-EC D15 Wave 1c (2026-08-19): 17 -> 24. The A24 FX roster added THIRTEEN producer-currency slices and
    the split between them is the whole lesson again. SIX were wired in the same change -- ars_fx <- ARS_FX,
    cad_fx <- CAD_FX/usdcad_fx, cny_fx <- CNY/CNY_FX/CNY_USD/usdcny_fx, eur_fx <- EUR_USD/EUR_USD_FX/
    eurusd_fx, zar_fx <- ZAR_FX/rand_FX, vnd_fx <- VND_USD_fx -- and every one of those ids was waived
    silver_only AND owned by no slice, so the wiring CREATED reach (16 board-DAGs across the six) and cost
    no slice a single prop: the favorable_rainfall shape, not the alias-steal shape. Each claimed waiver row
    was DELETED in the same edit, because a waiver asserts "grounded by the observed silver leg, never text"
    and that stops being true the moment a text slice owns the id (the MYR_USD precedent, verbatim).

    The SEVEN below are the export_levy_duty shape, not the import_quota_trq shape: there is NO WIRING TO
    DO. Not one of the 371 real DAG driver ids names the Thai baht, ruble, Turkish lira, Australian dollar,
    hryvnia, Mexican peso or Philippine peso, and they hold real measured mass (thb_fx 338 dark props,
    rub_fx 199, php_fx 72, try_fx 71, aud_fx 62, uah_fx 61, mxn_fx 59). ONE refusal is recorded rather than
    smuggled: `INR_THB_VND_weakness` on rough_rice_cbot would have retired thb_fx, and it is a BASKET id
    covering three currencies -- the exact ground on which D-GD tranche 2 declined to give that board a
    second FX node. Unlike the D8 three, these seven carry NO `waivers:` row: a slice-name waiver was that
    batch's workaround for not owning evidence.py, and Wave 1c does own it, so the pin alone is the record.

    D-EC POST-X2 GRAPH-COMPLETION WAVE (2026-08-21): 24 -> 12, and SIX of the claims above INVERT. Every
    inversion below is a claim this docstring made and the wave has now answered, so the assertions are
    re-cut rather than deleted -- a passing test whose prose still asserts the opposite is the failure mode
    this file exists to prevent (an earlier revision of this very docstring did exactly that).

      * `dap` LEAVES. The D-PQ decline recorded above -- "no honest phosphate mechanism yet" -- is REVERSED
        IN CONFIG by `dap_cost` on kcbt/matif/corn_cbot/canola_ice, and the reversal is STATED: D-PQ's
        "build-up nutrient, never marginal inside 1-4 quarters" is refuted by Pakistan's Rabi DAP offtake
        (-27% 2011, +16% 2012/13) and its chronic N-over-P subsidy skew, its "moves with the nitrogen story"
        is refuted by China's 2022 joint urea+phosphate export suspension, and SILVER-F063 has since
        published the DAP price leg, making this the owner's numbers-without-edge gap.
      * `export_levy_duty`, `import_quota_trq`, `marine_protein_fishmeal` LEAVE -- by MINTING, which is
        exactly what the D8 paragraph above said the post-X2 half would be. The D8 REFUSAL is untouched and
        is still asserted below: `China_import_quota_VAT` was never taken from `tariff`.
      * SIX of the seven FX slices LEAVE (RUB_USD / TRY_USD / THB_USD / AUD_USD / UAH_USD / MXN_USD).
        `php_fx` STAYS: PHP_USD is RESERVED against a `coconut` DAG that does not exist.
      * `cattle_cycle_herd_size` and `natural_rubber` and `real_yields_rates` and
        `sustainable_aviation_fuel` LEAVE, retiring the D-GD "DOUBLE-COUNT REFUSAL" and "NO HOST COMMODITY"
        classes by finding the parent slot and the host board respectively.
      * `wheat_blast` and `barley_yellow_dwarf_virus` leave BY RETIREMENT OF THE SPEC -- they are not wired,
        they are gone, which is why they are asserted here as non-specs rather than as non-pins.
      * FOUR ARRIVE: the B1 destination slices, the WAVE GATE's third legal state ("written down as
        edge-reachable-only"), each with its alternative measured and refused by name.
      * `metals` stays forever and changes CLASS: TERMINALLY CONTEXT, not deferred. Its four acts are
        asserted below because three of them are RESTRAINTS (do not delete the slice, do not mint an id, do
        not add a waiver row) and a restraint that nothing checks is a restraint that erodes."""
    import pytest
    from leviathan.graphrag import display as dp
    if not dp.all_driver_ids():
        pytest.skip("no causal configs in this tree -- the pin is vacuous")
    assert ev.read_dark_slices() == set(ev.READ_DARK_SLICES_PIN)   # exact, both directions, no debt set
    assert "diesel" not in ev.READ_DARK_SLICES_PIN                # D-CW-3a unlock, measured above
    assert not ({"urea", "potash"} & set(ev.READ_DARK_SLICES_PIN))     # D-PQ curation unlock
    # THE OVERTURN, asserted. `dap` was pinned with the comment "D-PQ DECLINE: no honest phosphate mechanism
    # yet"; `dap_cost` is that mechanism, so the line inverts and the comment inverts with it.
    assert "dap" not in ev.READ_DARK_SLICES_PIN            # D-PQ DECLINE REVERSED: dap_cost on 4 boards
    # The D8 three + the two livestock-protein slices: all five leave by MINTING (the post-X2 half D8 named).
    assert not ({"export_levy_duty", "import_quota_trq", "marine_protein_fishmeal",
                 "cattle_cycle_herd_size", "sustainable_aviation_fuel", "natural_rubber",
                 "real_yields_rates"} & set(ev.READ_DARK_SLICES_PIN))
    # D8 WIRED, therefore not read-dark. The equality above already proves it; naming it here is what makes
    # a silent regression (someone deletes the dag_alias line) read as a broken claim rather than a drifted
    # count -- and the last assertion in this test is the REFUSAL, recorded as an assertion:
    # `China_import_quota_VAT` still belongs to `tariff`, so nobody stole it to retire import_quota_trq.
    assert "benign_growing_conditions" not in ev.read_dark_slices()
    # D15 Wave 1c: the six WIRED fx slices and the seven that had nothing to wire to. Named for the same
    # reason as the line above -- deleting a dag_alias row must read as a broken claim, not a drifted count.
    assert not ({"ars_fx", "cad_fx", "cny_fx", "eur_fx", "zar_fx", "vnd_fx"} & ev.read_dark_slices())
    assert not ({"thb_fx", "rub_fx", "try_fx", "aud_fx", "uah_fx", "mxn_fx"} & set(ev.READ_DARK_SLICES_PIN))
    assert "php_fx" in ev.READ_DARK_SLICES_PIN            # PHP_USD is RESERVED; a reserved id is not a node
    # THE TWO RETIREMENTS. Not "not pinned" -- NOT CONFIGURED. wheat_blast's 32/32 props were Indonesia's
    # Ministry of TRADE via the term `MoT` (100% contamination, the `leaf rust` precedent at a higher rate)
    # and its origin geography is absent from all 28 sources; barley_yellow_dwarf_virus measured zero props
    # and was never written to S3 at all. A pin entry for either would name a spec that does not exist.
    assert "wheat_blast" not in ev.driver_specs() and "wheat_blast" not in ev.READ_DARK_SLICES_PIN
    assert ("barley_yellow_dwarf_virus" not in ev.driver_specs()
            and "barley_yellow_dwarf_virus" not in ev.NEVER_WRITTEN_SLICES_PIN)
    # THE FOUR B1 DESTINATION SLICES. Pinned AND read-dark AND configured -- all three, because the pin's
    # third legal state is only honest if the slice actually exists and actually cannot be reached.
    b1 = {"turkey_tmo_imports", "us_export_flow_relation", "mexico_import_demand", "ne_asia_feed_demand"}
    assert b1 <= set(ev.READ_DARK_SLICES_PIN) and b1 <= ev.read_dark_slices() and b1 <= set(ev.driver_specs())
    # ...and the two B1 slices that are NOT here, which is what makes the four a curated set: sea_import_demand
    # took `buyer_tender_demand` (waivered + unowned -> the wiring CREATES reach) and egypt_gasc_tenders is a
    # term extension on a slice that was already DAG-backed.
    assert not ({"sea_import_demand", "egypt_gasc_tenders"} & set(ev.READ_DARK_SLICES_PIN))
    # `metals`: the PERMANENT pin and its three restraints. RICH-and-RETIRED (975 props, 98% single-source
    # wb_cmo); the slice stays because SILVER-F063 wired copper_usd_mt to it and names it the consumer, no
    # DAG id is minted so reach stays 0, and NO waivers row is added -- by the D15 precedent the pin alone is
    # the record. TERMINALLY CONTEXT, not deferred: (a) index co-membership is a publication fact, (b)
    # freight-volume shares are `freight`'s, (c) Section-232 retaliation is `tariff`'s, (d) 'copper' fires on
    # copper FUNGICIDE and 'zinc' on a plant micronutrient.
    assert "metals" in ev.READ_DARK_SLICES_PIN and "metals" in ev.driver_specs()
    assert "metals" not in (ev._driver_raw().get("waivers") or {})
    assert not (ev._driver_raw().get("dag_alias") or {}).get("metals")
    assert ev.slice_for_driver("China_import_quota_VAT") == "tariff", "D-CW-3a: no alias steal for D8"


def _live_slice_reach() -> dict[str, set[str]]:
    """slice -> the set of CONTRACTS that reach it, resolved over the live causal dir the same way the
    planner does: parent-INCLUSIVE ids (a parent-only id is reachable, which is why display.all_driver_ids
    includes them) through evidence.driver_alias(). Live-tree helper; callers skip when there is no
    private causal config."""
    import glob
    import yaml
    alias = ev.driver_alias()
    out: dict[str, set[str]] = {}
    for p in sorted(glob.glob(str(dp._CFG / "causal" / "*.yaml"))):
        doc = yaml.safe_load(open(p, encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("drivers"), list):
            continue
        ids: set[str] = set()
        for d in doc["drivers"]:
            ids.add(d["id"])
            ids.update(d.get("parents") or [])
        for i in ids:
            if i in alias:
                out.setdefault(alias[i], set()).add(doc["contract"])
    return out


def test_dpq_curation_reach_is_what_the_pin_claims():
    """D-PQ DAG curation, the numbers the pin comment and the driver_slices.yaml D-PQ block assert.

    The wave's whole claim is that three stranded/choked slices gained CONTRACT REACH without any other
    slice losing any -- because every id it added is a NEW node, never a re-owned one (one id belongs to
    exactly one slice, so an alias steal moves reach instead of creating it; that is precisely why
    D-CW-3a refused to do this by wiring). Reach is the load-bearing number: read-darkness is binary and
    would still read 'unlocked' if urea reached ONE contract, so the pin equality above cannot catch a
    curation that quietly shrank. Skipped on a tree with no private causal configs.

    RE-CUT 2026-08-21 (D-EC graph-completion wave) FROM COUNT-EQUALITY TO NAMED-MEMBERSHIP + A FLOOR, and
    the reasoning matters because loosening a pin is normally the wrong move. What D-PQ actually claimed was
    never "twelve" -- it was "these twelve boards, and no slice lost anything". A count is a WEAKER
    statement than the membership it summarises: it cannot tell a board swapped for another from a board
    kept, and it breaks on legitimate growth that has nothing to do with D-PQ. This wave produced exactly
    that growth -- the class DAGs for `barley`, `sorghum` and `sunflower_oil` (33 causal yamls -> 36) each
    carry the ordinary fertilizer/macro block, so urea went 12 -> 14, macro 24 -> 27 and fertilizer 15 -> 17
    with no D-PQ decision touched. Naming the members and flooring the count keeps every tooth this test
    had (a shrink, a swap, or a re-owned id all still fail) and stops the file demanding an edit every time
    an unrelated board is authored.

    THE ONE LINE THAT INVERTS: `assert "dap" not in reach`. D-PQ declined a phosphate node and this wave
    REVERSES that decline in config with `dap_cost` on kcbt/matif/corn_cbot/canola_ice, so the assertion is
    re-cut to name the four boards. The decline was recorded in prose here and in the pin comment; the
    reversal is recorded the same way, in the same places, because a refusal that quietly stops being true
    is indistinguishable from a refusal nobody honoured."""
    if not dp.all_driver_ids():
        pytest.skip("no causal configs in this tree -- the reach census is vacuous")
    reach = _live_slice_reach()
    # D-PQ's twelve, by name: corn family 6 + wheat family 4 + canola/rapeseed 2.
    urea_dpq = {"corn", "corn_cbot", "campinas_corn_reference_bmf", "french_maize_matif",
                "south_african_white_maize_jse", "south_african_yellow_maize_jse",
                "french_wheat_matif", "hard_red_spring_wheat_mgex", "hard_red_winter_wheat_kcbt",
                "soft_red_winter_wheat_cbot", "canola_ice", "french_rapeseed_matif"}
    assert urea_dpq <= reach["urea"] and len(reach["urea"]) >= 12
    assert len(reach["potash"]) == 1                   # oil palm only -- the estate's one K-binding crop
    assert "malaysian_crude_palm_oil_cme" in reach["potash"]
    assert len(reach["macro"]) >= 24                   # was 1 (cocoa-only): the 2,121-prop choke point
    assert "cocoa" in reach["macro"]                   # the shape donor keeps its node
    assert len(reach["fertilizer"]) >= 15              # UNCHANGED by D-PQ: all five generic ids stayed put
    # THE D-PQ DECLINE, REVERSED IN CONFIG (see the docstring and the READ_DARK_SLICES_PIN comment for the
    # three grounds and how each was refuted). `dap_cost` parents each board's generic fertilizer node; it
    # mints no phosphate-ORE node, because 'phosphate rock' measured 1 prop and was refused.
    assert {"hard_red_winter_wheat_kcbt", "french_wheat_matif", "corn_cbot", "canola_ice"} <= reach["dap"]


def test_dpq_new_nodes_carry_no_new_cascade_capability():
    """The wave is a NARRATIVE de-choke: it adds no cascade_map row and arms no new quantified leg.

    Two independent proofs, both cheap and both config-only:
      * `pink_sheet_input_costs` is not a cascade_map ref at all -- this wave added no row for it, and
        it still has none. THE PIN'S MEANING MOVED TWICE and both moves are recorded: (1) after the
        price_context amendment (2026-08-26) R4 stopped being a blanket table ban, and the assertion
        narrowed to "the BASKET stays unbound because a ref naming no single (table, metric) pair is
        unbindable by the one-ref-one-pair law"; (2) on 2026-08-27 the sitting this docstring called
        for HAPPENED -- the per-metric split on the DAG side (the mpob precedent): the 83 basket
        carriers across 34 DAGs were re-keyed onto seven metric-specific refs (69 wired legs:
        brent_crude_z, urea_z, natural_gas_us_z/_eu_z, npk_fertilizer_z, dap_z, potash_z) with 14
        retagged planned after adversarial review (wf_b69ce788-4e1). The assertion now guards
        RETIREMENT: the basket name -- a dead MLOps feature family, never an instrument -- must never
        re-enter the map, and the companion sweep below proves it is gone from every DAG too.
      * `fred_fx_macro` (macro_demand) IS a mapped ref, so the guard here is different: every DAG that
        gained a macro_demand node ALREADY carried at least one other fred_fx_macro driver, so the
        contract's fireable-ref set is identical before and after. (The region field is the other half --
        every macro_demand is region 'Global', which region_map lists unresolved, so the leg stays
        qualitative. config_check's cascade_map census enforces that directly.)"""
    import glob
    import yaml
    if not dp.all_driver_ids():
        pytest.skip("no causal configs in this tree")
    rows = cc._load("numbers/cascade_map.yaml") or {}
    assert "pink_sheet_input_costs" not in (rows.get("refs") or rows), "R4: no pink sheet cascade ref"
    for p in sorted(glob.glob(str(dp._CFG / "causal" / "*.yaml"))):
        doc = yaml.safe_load(open(p, encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("drivers"), list):
            continue
        # the 2026-08-27 companion sweep: the retired basket name is gone from every DAG driver
        stale = [d["id"] for d in doc["drivers"] if d.get("silver_ref") == "pink_sheet_input_costs"]
        assert not stale, f"{doc['contract']}: retired basket ref re-entered on {stale}"
        md = [d for d in doc["drivers"] if d["id"] == "macro_demand"]
        if not md:
            continue
        assert md[0]["region"] == "Global", f"{doc['contract']}: macro_demand region must stay unresolved"
        others = [d["id"] for d in doc["drivers"]
                  if d.get("silver_ref") == "fred_fx_macro" and d["id"] != "macro_demand"]
        assert others, f"{doc['contract']}: macro_demand would be a NEW fred_fx_macro carrier"
