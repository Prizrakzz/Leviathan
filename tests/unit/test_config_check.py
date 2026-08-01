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


def test_r4_pink_sheet_fence_is_untouched_by_the_r9_amendment():
    # D1 moved R9 ONLY. The price fence stays a blanket engine ban, and R4 must still be the thing
    # that refuses a pink-sheet ref no matter how "context-shaped" the row looks.
    assert cc._check_no_engine_ref({"p": {**_COT_CONTEXT_ROW, "table": "silver_pink_sheet"}},
                                   cc.PRICE_TABLES, "R4", "price")


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
    """The 29 read-dark slices are PINNED (READ_DARK_SLICES_PIN) so nobody re-derives a subset by hand
    again -- the deck author had already measured five of them at eval_queries_playbooks_v1.yaml:1130-1140.
    Skipped on a tree with no private causal configs."""
    import pytest
    from leviathan.graphrag import display as dp
    if not dp.all_driver_ids():
        pytest.skip("no causal configs in this tree -- the pin is vacuous")
    assert ev.read_dark_slices() == set(ev.READ_DARK_SLICES_PIN)
