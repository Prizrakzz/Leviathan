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

from leviathan.graphrag import config_check as cc
from leviathan.graphrag import display as dp
from leviathan.graphrag import evidence as ev


def _wire(monkeypatch, tmp_path, *, causal_yaml: str, driver_yaml: str):
    """Point display at a synthetic causal dir and evidence at a synthetic driver_slices.yaml, caches cleared.
    Caller MUST reset in a finally (see the try/finally in each test)."""
    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(causal_yaml, encoding="utf-8")
    monkeypatch.setattr(dp, "_CFG", tmp_path)                 # display globs _CFG/causal/*.yaml
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text(driver_yaml, encoding="utf-8")
    monkeypatch.setattr(ev, "_DRIVER_PATH", drv)
    ev._reset()
    dp.all_driver_ids.cache_clear()


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
