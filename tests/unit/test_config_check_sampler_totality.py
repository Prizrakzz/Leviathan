"""SAMPLER TOTALITY -- the pins for census B4/P4 (2026-09-22).

THE CLASS THIS CLOSES, in the order it was paid for:
  * 2026-09-09 -- silver_nass_annual and silver_nass_crop_progress: no SAMPLE_COMMODITY entry, both
    PROJECTED on ``commodity``, so every leg raised "requires commodity (partition column)", each
    was booked as a spec-invalid SKIP BEFORE the compare counter, and the run returned 0 with
    ``## verdict: 0/0 exact-match``. Green, and proving nothing.
  * 2026-09-15 -- silver_wap_table01_revisions: the SPEC-INVALID-PANEL guard added after the first
    RCA caught it, which is better -- but it caught it INSIDE the blocking gate, so the WAP family
    lost three fires (09-12/13/14) and silver sat frozen at release_month 2026-07.
  * 2026-09-22 -- silver_fgis and the three fnc cards, by the same mechanism, with fgis's canonical
    tip stuck at 2026-08-30 and fnc's gate red on every fire.
Three RCAs, three one-row fixes, and SEVENTEEN mirrored tables still waiting: P1_TABLES had 39
members against 22 sampler entries when this was measured.

So the fix is a LINT, and this deck is the lint's own fence. Every test here fails on HEAD, where
``config_check.check_sampler_totality`` does not exist.

AWS-free: config reads plus the real ``build_sql`` string compiler.
"""
from __future__ import annotations

import importlib

import pytest
from leviathan.graphrag import config_check

parity = importlib.import_module("jobs.utils.numbers_parity")
loader = importlib.import_module("jobs.utils.load_pg_numbers")


def test_the_live_configuration_is_total():
    """The state the change leaves the estate in: every mirrored table is sampled or declared."""
    errs = config_check.check_sampler_totality()
    assert errs == [], "\n".join(errs)


def test_the_lint_is_wired_into_config_check_main():
    """A lint whose only caller is its own deck lets an image built from a config edit ship with the
    estate red -- the reason ``metric_lags`` had to be wired on 2026-09-16 after it shipped. Assert
    the roster entry exists, and that it is at the TAIL (the append-never-insert law this file keeps
    for its own roster)."""
    import inspect
    src = inspect.getsource(config_check.main)
    assert '("sampler_totality", check_sampler_totality())' in src
    assert src.index('("sampler_totality"') > src.index('("metric_lags"'), "append at the tail"


def test_the_lint_binds__it_reports_every_unsampled_mirrored_table(monkeypatch):
    """THE BINDING PROOF, replayed against HEAD's own sampler. With the 22-entry dict and no
    exemptions -- exactly the configuration that was live this morning -- the lint must name all
    seventeen unsampled tables plus the one whose entry compiles nothing. 18 errors, measured."""
    head_22 = {k: v for k, v in list(parity.SAMPLE_COMMODITY.items())
               if k not in _THE_SEVENTEEN}
    assert len(head_22) == 22, "the HEAD sampler had exactly 22 entries"
    monkeypatch.setattr(parity, "SAMPLE_COMMODITY", head_22)
    monkeypatch.setattr(parity, "SAMPLER_EXEMPT", {})
    errs = config_check.check_sampler_totality()
    named = {t for t in loader.P1_TABLES if any(f" {t} " in e for e in errs)}
    assert _THE_SEVENTEEN <= named, f"unreported: {sorted(_THE_SEVENTEEN - named)}"
    # ...and gold_pattern_records, whose entry EXISTS at HEAD and compiles nothing (the card
    # declares `metrics: {}` on purpose). A dict row is not coverage.
    assert any("gold_pattern_records" in e and "NOT ONE" in e for e in errs)
    assert len(errs) == 18, errs


def test_an_entry_that_compiles_nothing_is_not_coverage(monkeypatch):
    """The silver_wap_table01_revisions shape: an entry that EXISTS but whose every leg raises. A
    presence test would have passed it; only the real compiler catches it. Replayed by setting WAP's
    sample back to the None it effectively had before 2026-09-15 -- the card's three metrics all
    carry ``unit_overrides``, so query.py's DP-1 guard raises on every commodity-less leg."""
    broken = dict(parity.SAMPLE_COMMODITY)
    broken["silver_wap_table01_revisions"] = None
    monkeypatch.setattr(parity, "SAMPLE_COMMODITY", broken)
    errs = config_check.check_sampler_totality()
    assert any("silver_wap_table01_revisions" in e and "NOT ONE" in e for e in errs), errs


def test_an_exemption_must_carry_a_reason(monkeypatch):
    monkeypatch.setattr(parity, "SAMPLER_EXEMPT", {"silver_psd": "   "})
    errs = config_check.check_sampler_totality()
    assert any("silver_psd" in e and "empty" in e for e in errs), errs


def test_an_exemption_retires_itself_when_its_reason_expires(monkeypatch):
    """CLAUSE 3, and the reason a waiver here can never become decoration. silver_psd is sampled and
    compiles; declaring it exempt must go RED telling whoever did it to delete the line. A waiver
    that can outlive its reason is how a hole stops being watched."""
    monkeypatch.setattr(parity, "SAMPLER_EXEMPT",
                        {"silver_psd": "a reason that is no longer true"})
    errs = config_check.check_sampler_totality()
    assert any("silver_psd" in e and "expired" in e for e in errs), errs


def test_the_one_live_exemption_is_the_aggregation_only_card():
    """gold_pattern_records is MIRRORED, has carried a sampler entry since 2026-07-24, and its card
    declares ``metrics: {}`` ON PURPOSE -- so its value panel has compared NOTHING for as long as it
    has been in the mirror, silently, while the entry read as coverage. It is recorded rather than
    fixed here because the fix is a card change and this lane does not edit cards."""
    assert set(parity.SAMPLER_EXEMPT) == {"gold_pattern_records"}
    assert parity.SAMPLER_EXEMPT["gold_pattern_records"].strip()
    from leviathan.graphrag.numbers.registry import load_registry
    assert not load_registry().get("gold_pattern_records").metrics


def test_the_lint_fails_closed_when_its_own_input_is_unreadable(monkeypatch):
    """An unreadable roster is NOT "no tables to check". A fence whose input was never measured is
    the 2026-08-18 class this estate keeps paying for, so the lint reports RED rather than passing
    on an empty set."""
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name.startswith("jobs.utils"):
            raise ImportError("simulated: jobs/ not on sys.path")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    monkeypatch.delitem(__import__("sys").modules, "jobs.utils.numbers_parity", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "jobs.utils.load_pg_numbers", raising=False)
    errs = config_check.check_sampler_totality()
    assert len(errs) == 1 and "cannot read the mirror roster" in errs[0]


@pytest.mark.parametrize("tid,expected", [
    ("silver_fgis", "corn_cbot"),
    ("silver_fnc_colombia_monthly", "arabica_coffee"),
    ("silver_fnc_colombia_exports_port_type", "arabica_coffee"),
    ("silver_fnc_colombia_area_department", "arabica_coffee"),
    ("silver_nass_citrus", "all_orange"),
    ("silver_sagis_weekly_deliveries", "maize"),
    ("silver_minagro_grain_exports", "corn"),
    ("gold_futures_spreads", "kc_chi"),
    ("silver_mpoc_stock_comparison", "palm_oil"),
])
def test_the_new_samples_are_the_measured_values_not_contract_slugs(tid, expected):
    """Presence is not validity. Each of these commodity columns holds something that is NOT a
    contract slug -- a SAGIS crop label, a NASS crop, a spread id, an oil type, a MINAGRO crop --
    and the gold_weather_z weather-R3 trap is exactly what happens when a plausible-looking slug is
    written instead: 30 of 30 queries vacuous, 0 rows == 0 rows, a passing gate. These values were
    read off the data before they landed."""
    assert parity.SAMPLE_COMMODITY[tid] == expected


def test_the_commodity_less_cards_declare_none_rather_than_being_absent():
    """Seven of the seventeen have NO commodity column, so ``None`` is the only correct value. They
    are WRITTEN OUT rather than left absent precisely so the lint can tell "declared commodity-less"
    from "nobody has looked at this table yet" -- the distinction whose absence cost three RCAs."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    commodity_less = {"gold_board_crush", "silver_mpoc_trade_stats_monthly", "silver_food_cpi",
                      "silver_mpoc_exports_by_country", "silver_unica_biweekly_season_history",
                      "silver_unica_corn_ethanol", "silver_unica_monthly_ethanol_sales"}
    for tid in commodity_less:
        assert reg.get(tid).commodity_col is None, f"{tid} grew a commodity axis -- re-sample it"
        assert tid in parity.SAMPLE_COMMODITY and parity.SAMPLE_COMMODITY[tid] is None


_THE_SEVENTEEN = {
    "gold_board_crush", "gold_futures_spreads", "silver_mpoc_stock_comparison", "silver_fgis",
    "silver_fnc_colombia_monthly", "silver_fnc_colombia_exports_port_type", "silver_nass_citrus",
    "silver_mpoc_trade_stats_monthly", "silver_sagis_weekly_deliveries",
    "silver_ams_cotton_quality", "silver_food_cpi", "silver_fnc_colombia_area_department",
    "silver_mpoc_exports_by_country", "silver_unica_biweekly_season_history",
    "silver_unica_corn_ethanol", "silver_unica_monthly_ethanol_sales",
    "silver_minagro_grain_exports",
}


def test_the_mirror_and_the_sampler_agree_on_the_whole_roster():
    """The arithmetic the census had to do by hand: 39 mirrored tables, and after this change every
    one of them is either sampled or declared exempt."""
    mirrored = set(loader.P1_TABLES)
    assert len(loader.P1_TABLES) == len(mirrored) == 39
    covered = set(parity.SAMPLE_COMMODITY) | set(parity.SAMPLER_EXEMPT)
    assert mirrored <= covered, f"uncovered: {sorted(mirrored - covered)}"
    assert _THE_SEVENTEEN <= set(parity.SAMPLE_COMMODITY)
