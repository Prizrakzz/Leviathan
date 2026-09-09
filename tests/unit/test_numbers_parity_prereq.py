"""SILVER-C001 prerequisite (Attack 3 #4): numbers_parity must cover gold_weather_z with a real sample
commodity and lift the [:4] metric cap for TALL tables (or BF-W1's rebuild target passes vacuously).

AWS-free: only inspects the module's static config + the metric-selection expression."""
from __future__ import annotations

import importlib

import pytest

from leviathan.graphrag.numbers.registry import load_registry

parity = importlib.import_module("jobs.utils.numbers_parity")


def test_gold_weather_z_has_a_valid_sample_commodity():
    assert "gold_weather_z" in parity.SAMPLE_COMMODITY
    commodity = parity.SAMPLE_COMMODITY["gold_weather_z"]
    assert commodity, "gold_weather_z sample commodity must be non-empty (else the panel is vacuous)"
    # weather-R3 (2026-07-17) went red on exactly this: the sample said base-name 'corn' but the gold
    # task's 'all' mode keys by CONTRACT slug (discovered from silver/weather partitions) -> 30/30
    # queries vacuous. Presence is not validity; pin the contract form.
    assert commodity == "corn_cbot", (
        "gold_weather_z is keyed by contract slug (gold/weather_z/<contract>.parquet); "
        "a base-name sample makes the parity panel vacuous"
    )
    # it must be in the default parity table set (so a plain run exercises it)
    default_tables = set(parity.SAMPLE_COMMODITY)
    assert "gold_weather_z" in default_tables


def test_tall_table_metric_cap_is_lifted_in_source():
    """main() must select ALL metrics for a tall table and keep the [:4] cap only for wide tables -- assert
    against the ACTUAL module source (not a re-implementation), so a regression that drops the shape branch
    is caught. gold_weather_z (tall, 5 metrics) is the table BF-W1 rebuilds."""
    import inspect
    src = inspect.getsource(parity.main)
    # the fixed expression: tall -> full metric list, wide -> capped at [:4].
    assert 'ts.shape == "tall"' in src, "the tall-vs-wide metric-cap branch is missing from main()"
    assert "list(ts.metrics)[:4]" in src, "the [:4] cap for wide tables should remain"
    # and the raw uncapped loop `for metric in list(ts.metrics)[:4]:` must NOT survive unbranched
    assert "for metric in list(ts.metrics)[:4]:" not in src

    reg = load_registry()
    gz = reg.get("gold_weather_z")
    assert gz.shape == "tall" and len(gz.metrics) >= 5   # >4 -> the cap would have hidden metric #5


# ---- WIRING-W1 fold: float32-accumulation tolerance is sum-leg-only and tight ----

def test_sum_tolerant_eq_accepts_float32_accumulation_delta():
    from jobs.utils.numbers_parity import _sum_tolerant_eq
    assert _sum_tolerant_eq([("69140.06", "")], [("69140.08", "")])          # observed live delta
    assert _sum_tolerant_eq([("0.0", "d"), ("1.5", "d")], [("0.0", "d"), ("1.5", "d")])


def test_sum_tolerant_eq_rejects_real_divergence():
    from jobs.utils.numbers_parity import _sum_tolerant_eq
    assert not _sum_tolerant_eq([("69140.06", "")], [("69145.00", "")])      # beyond rel tol
    assert not _sum_tolerant_eq([("1.0", "2026-01-01")], [("1.0", "2026-01-08")])  # date drift
    assert not _sum_tolerant_eq([("1.0", "")], [("1.0", ""), ("2.0", "")])   # row-set drift
    assert not _sum_tolerant_eq([("abc", "")], [("abd", "")])                # non-numeric mismatch


# ---- PROJECTION WAVE Lane 3 / D-8: the silver_psd_attributes entry + its vintage-fan cell ----
#
# The Lane-3 flip's one open instrument item. Two separate things are pinned and must not be conflated:
# (1) the SAMPLE_COMMODITY entry that makes the 20-metric TALL panel non-vacuous, and (2) the CELL leg --
# one pinned (slug, country, attribute, market_year) read at three as-ofs -- which is the only leg that
# puts this card's as-of ROW_NUMBER collapse INSIDE the compared projection. Everything here is offline:
# the SQL is asserted from the string build_sql emits, and the vintage dates from the PRODUCER's own
# formula, so a drifted spelling or a re-shaped order fails in CI rather than at the next in-VPC run.

_PSD_ATTR = "silver_psd_attributes"


def test_psd_attributes_sample_commodity_is_the_card_s_own_contract_slug():
    assert _PSD_ATTR in parity.SAMPLE_COMMODITY, "no entry -> the panel is vacuous the first time it runs"
    commodity = parity.SAMPLE_COMMODITY[_PSD_ATTR]
    # A base name ('soybeans') matches ZERO rows: commodity_col is leviathan_slug, filled from the same
    # producer map silver_psd's corn_cbot sample comes from. That is the gold_weather_z weather-R3 trap.
    assert commodity == "soybeans_cbot"
    reg = load_registry()
    assert _PSD_ATTR in reg.tables, "registered but whitelist-fenced -> the leg would SKIP-FENCED"
    ts = reg.get(_PSD_ATTR)
    assert commodity in ts.commodity_values, (
        "the sample slug must be one the CARD declares -- the card generates commodity_values from "
        "_PSD_COMMODITY_TO_SLUGS, so a slug dropped there is a table serving rows its own fence refuses"
    )
    assert ts.shape == "tall" and len(ts.metrics) > 4     # tall -> main() lifts the [:4] metric cap
    assert _PSD_ATTR in parity.PG_MIRROR_TABLES, (
        "served but unmirrored -> SKIP-UNMIRRORED is a report line, NOT a mismatch, so the gate would "
        "stay green while the mirror rotted"
    )


def test_psd_attributes_cell_metric_is_declared_single_unit_and_not_the_multi_unit_one():
    ts = load_registry().get(_PSD_ATTR)
    m = ts.metrics.get(parity.PSD_ATTR_CELL_METRIC)
    assert m is not None, "the cell metric must be a DECLARED metric -- load_pg_numbers filters the tall "\
                          "mirror to the declared roster, so an undeclared attribute has no pg side at all"
    # Byte-exact USDA spelling, and ONE unit: two rows of this cell can never be different quantities.
    assert parity.PSD_ATTR_CELL_METRIC == "Crush"
    assert getattr(m, "unit", None) == "1000 MT"
    # The refusal, written: 'Domestic Consumption' is the card's one MULTI-UNIT metric (1000 MT /
    # 1000 MT CWE / 1000 60 KG BAGS / MT) and is therefore not a byte-stable parity cell.
    assert parity.PSD_ATTR_CELL_METRIC != "Domestic Consumption"
    assert not ts.metrics["Domestic Consumption"].unit, (
        "the multi-unit metric declares NO card-level unit on purpose -- the row's unit column governs, "
        "which is exactly what makes it unfit as a parity cell"
    )


def test_psd_attributes_vintage_cells_span_the_fan_by_the_producer_s_own_clock():
    """P23 RE-ANCHOR (2026-09-04, lane E): the '13 distinct dates, no tie' premise
    is RE-DERIVED on the honest axis from the test's own banked calendar, never
    assumed from a formula.

    What the premise WAS: release_date was a FUNCTION of (market_year, month_code)
    -- the retired rotation emitted '<cal_year>-<cal_month>-10', injective in
    month_code at a fixed market year, so thirteen month codes gave thirteen dates
    by construction and the latest-vintage ROW_NUMBER had nothing to break.

    What it IS now: a marketing year's vintages are the releases that TOUCHED it,
    each dated from its own (Calendar_Year, Month) stamp. Twelve calendar months of
    one year still resolve to twelve distinct registered WASDE days, and
    month_code 0 still anchors to 1 January of the MARKETING year -- so the
    thirteen-distinct property survives, but it is now a property of the CALENDAR
    and it has to be measured against one rather than derived from arithmetic.
    That is the whole point of re-anchoring rather than deleting: this is the
    premise the psd_attributes card's 'no vintage_tiebreak' ruling rests on.
    """
    import json
    from pathlib import Path

    import pandas as pd
    from leviathan.transforms.bronze_to_silver.usda_psd import (
        _PSD_COMMODITY_TO_SLUGS,
        _compute_psd_release_dates,
    )

    cal = {
        k: int(v) for k, v in
        json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "wasde"
                    / "release_calendar.json").read_text(encoding="ascii"))["calendar"].items()
    }

    cells = parity.PSD_ATTR_VINTAGE_CELLS
    assert 2 <= len(cells) <= 3
    years = {my for my, _ in cells}
    assert any(int(my) < 2005 for my in years), (
        "one leg must sit in the month_code-0 era (MY1960-2004, the pre-WASDE-tracking mass the card "
        "measures at 389,283 rows) or the pre-2005 half of the vintage fan is never compared"
    )
    # ...and two legs must share ONE modern market year at DIFFERENT as-ofs, or the fan never MOVES.
    modern = [(my, asof) for my, asof in cells if int(my) >= 2005]
    assert len({my for my, _ in modern}) == 1 and len({asof for _, asof in modern}) == 2

    code = next(c for c, slugs in _PSD_COMMODITY_TO_SLUGS.items()
                if parity.PSD_ATTR_CELL_COMMODITY in slugs)
    my = int(modern[0][0])
    mid, settled = sorted(asof for _, asof in modern)
    # The fan a mid-fan as-of has to sit INSIDE: the twelve monthly releases of the
    # calendar year the as-ofs straddle, plus the month_code-0 anchor. The calendar
    # year is READ FROM THE AS-OFS, not assumed to equal the marketing year -- that
    # assumption is exactly what the retired rotation baked in.
    # THE CALENDAR PROPERTY (thirteen distinct dates, no tie) is measured at the LAST FULLY
    # REGISTERED calendar year at or before the mid as-of: the current year is only registered
    # through its newest WASDE, and a synthetic frame stamped past that month would RAISE (the
    # clock refuses a stamp newer than the calendar), not measure anything. The REAL fan the two
    # as-ofs straddle is asserted separately below, from the banked measurement of this cell.
    fan_year = max(y for y in range(2006, int(mid[:4]) + 1)
                   if all("%04d-%02d" % (y, m) in cal for m in range(1, 13)))
    frame = pd.DataFrame({
        "commodity_code": [code] * 13,
        "month_code":     list(range(13)),
        "market_year":    [my] * 13,
        "calendar_year":  [fan_year] * 13,
    })
    dates = sorted(_compute_psd_release_dates(frame, calendar=cal))
    # NO TIE for the latest-vintage ROW_NUMBER to break -- this card declares no
    # vintage_tiebreak. Twelve registered WASDE days of one calendar year are
    # distinct from each other, and market_year-01-01 is a day no real stamp can
    # produce (registered days over 2006+ are 8..14).
    assert len(set(dates)) == 13
    assert dates.count("%04d-01-01" % my) == 1
    # THE REAL FAN, from the banked measurement of this cell on the first honest-clock canonical
    # object (R7b, 2026-09-04): every leg must return rows (an EMPTY leg matches vacuously on both
    # backends -- the hazard the retired pairs fell into), and the two modern as-ofs must select
    # DIFFERENT real vintages of the same cell, or the fan never MOVES.
    banked = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "psd"
                         / "vintage_cell_20260904.json").read_text(encoding="ascii"))
    assert banked["commodity"] == parity.PSD_ATTR_CELL_COMMODITY
    assert banked["attribute"] == parity.PSD_ATTR_CELL_METRIC
    real = banked["vintages"]
    for my_s, asof in cells:
        assert any(v <= asof for v in real[my_s]), (
            f"leg MY{my_s} @{asof} would return NO rows: this cell's honest vintages are {real[my_s]}")
    mod_v = real[str(my)]
    assert max(v for v in mod_v if v <= mid) != max(v for v in mod_v if v <= settled), (
        f"the two modern as-ofs {mid} / {settled} select the SAME real vintage of MY{my} ({mod_v})")


def test_psd_attributes_cell_compiles_to_one_deterministically_ordered_row():
    from leviathan.graphrag.numbers import query as Q
    for my, asof in parity.PSD_ATTR_VINTAGE_CELLS:
        spec = dict(table=_PSD_ATTR, metric=parity.PSD_ATTR_CELL_METRIC, asof=asof,
                    commodity=parity.PSD_ATTR_CELL_COMMODITY, country=parity.PSD_ATTR_CELL_COUNTRY,
                    period=my, limit=50)
        sql = Q.build_sql(Q.NumberQuery(agg="series", **spec))
        # every axis of the cell pinned -> _rn = 1 leaves exactly ONE row per market_year
        assert f"leviathan_slug = '{parity.PSD_ATTR_CELL_COMMODITY}'" in sql
        assert f"country = '{parity.PSD_ATTR_CELL_COUNTRY}'" in sql
        assert f"attribute = '{parity.PSD_ATTR_CELL_METRIC}'" in sql
        assert f"market_year = {int(my)}" in sql          # period_sql_type int -> UNQUOTED literal
        assert f"CAST(release_date AS varchar) <= '{asof}'" in sql
        # the as-of machinery itself: the tall fallback partition, because the card declares no grain_cols
        assert ("ROW_NUMBER() OVER (PARTITION BY leviathan_slug, country, market_year, attribute "
                "ORDER BY release_date DESC)") in sql
        # a STRICT total order -- period is unique per surviving row, so neither backend can pick a
        # different row under the LIMIT (the Athena-vs-pg divergence class _total_order exists to close)
        assert "ORDER BY period, country, metric, knowledge_date, unit, value LIMIT 50" in sql
        # DOCUMENTED, not assumed: this card has no date_col, so agg=latest falls past the vintage
        # branch's `and order` into the same series arm and compiles the BYTE-IDENTICAL string. Both
        # aggs still run in the gate -- the day a date_col is declared here the two arms diverge, and
        # this assertion is what makes that a visible decision rather than a silent one.
        assert Q.build_sql(Q.NumberQuery(agg="latest", **spec)) == sql


def test_psd_attributes_cell_leg_repeats_the_fence_and_mirror_guards():
    """The cell leg sits OUTSIDE the table loop, hence outside its SKIP-FENCED / SKIP-UNMIRRORED
    branches. Without its own guards a re-armed Lane-3 whitelist entry (or a table dropped from
    P1_TABLES) would make every cell leg a MISMATCH -- the whole gate red for a table nobody serves."""
    import inspect
    src = inspect.getsource(parity.main)
    assert 'if _PSD_ATTR in tables and _PSD_ATTR in reg.tables and _PSD_ATTR in PG_MIRROR_TABLES:' in src
    # and the loop's own guards, which protect the NEXT table registered ahead of its mirror, survive
    assert "SKIP-FENCED" in src and "SKIP-UNMIRRORED" in src


# ---- NASS GATE RCA (2026-09-09): the VACUOUS half of the usda_nass gate ----
#
# THE MEASURED FINDING. Both usda_nass tables have been served AND mirrored (load_pg_numbers
# P1_TABLES) for as long as they have been wired, and both are PROJECTED on `commodity`
# (partition_cols [commodity, year]) -- but NEITHER had a SAMPLE_COMMODITY entry. With commodity
# None, query.build_sql raises "table {id} requires commodity (partition column)" for EVERY leg;
# _cmp books each as `- SKIP ... spec invalid` BEFORE `compared[tid]` increments, so the EMPTY-PANEL
# guard -- which only looks at tables that compared something -- never saw either table, `mismatches`
# stayed empty and main() returned 0 on `## verdict: 0/0 exact-match`. Green while proving nothing,
# which is the 2026-08-18 class exactly: a fence whose input was never measured.
#
# Two things are pinned below and must not be conflated: (1) the SAMPLE_COMMODITY entries, which turn
# the two panels from 0 legs into real ones, and (2) the SPEC-INVALID-PANEL guard, which is the
# ESTATE-WIDE half -- any table whose spec stops building (a dropped sample, a renamed partition
# column, a region rule that no longer admits the grid) would otherwise pass the same way. Everything
# here is offline: no Athena, no pg, only build_sql's string and the pure guard function.

_NASS = ("silver_nass_annual", "silver_nass_crop_progress")


def _leg_grid(ts):
    """main()'s OWN leg grid for one table: the tall/wide metric cap x ASOFS x AGGS. Derived from the
    module's constants rather than hard-coded, so a change to either shows up here as a count."""
    metrics = list(ts.metrics) if ts.shape == "tall" else list(ts.metrics)[:4]
    return [(m, asof, agg) for m in metrics for asof in parity.ASOFS for agg in parity.AGGS]


def test_both_nass_tables_have_a_sample_commodity_that_actually_builds():
    from leviathan.graphrag.numbers import query as Q

    reg = load_registry()
    built_total = 0
    for tid in _NASS:
        assert tid in parity.SAMPLE_COMMODITY, f"no entry -> every {tid} leg SKIPs and the panel is vacuous"
        commodity = parity.SAMPLE_COMMODITY[tid]
        # CONTRACT SLUG, not a base name: commodity_col is the partition `commodity`, filled from the
        # producer's slug map. 'corn' matches zero rows -- the gold_weather_z weather-R3 trap.
        assert commodity == "corn_cbot"
        assert tid in reg.tables, "fenced out of the registry -> the leg would SKIP-FENCED, not compare"
        ts = reg.get(tid)
        assert commodity in ts.commodity_values, "the sample must be a slug the CARD declares"
        assert tid in parity.PG_MIRROR_TABLES, (
            "served but unmirrored -> SKIP-UNMIRRORED is a report line, NOT a mismatch, so the gate "
            "would stay green while the mirror rotted")
        grid = _leg_grid(ts)
        # THE DEFECT, first: with no sample every single leg is unbuildable, and the exception is the
        # exact one the RCA read out of query.py.
        for metric, asof, agg in grid:
            with pytest.raises(ValueError, match="requires commodity"):
                Q.build_sql(Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=None,
                                          agg=agg, limit=50))
        # ...and with the sample, every leg compiles to real SQL that filters the partition.
        for metric, asof, agg in grid:
            sql = Q.build_sql(Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=commodity,
                                            agg=agg, limit=50))
            assert f"commodity = '{commodity}'" in sql and f"leviathan_dev.{tid}" in sql
        built_total += len(grid)
    # MEASURED 2026-09-09, offline: 24 + 24 legs. NOTE the RCA predicted 24 + 30 -- it multiplied
    # crop_progress's FULL five-metric roster and missed that main() caps a WIDE table at [:4]. The
    # honest number is 24, and the correction is worth more than the round figure: `pct_harvested`,
    # metric #5 on that card, is the one column D-SG G1-5 gave a SEASON floor to and it is never
    # compared by parity at all. That is a real hole, but it is the wide-cap's, not this fix's --
    # DOCKETED rather than widened here, because lifting the cap changes every wide panel's cost.
    assert built_total == 48, built_total
    cp = reg.get("silver_nass_crop_progress")
    assert cp.shape == "wide" and len(cp.metrics) == 5 and len(_leg_grid(cp)) == 24
    assert "pct_harvested" == list(cp.metrics)[4]      # the metric the cap hides, named on purpose


def test_an_all_skip_table_is_a_mismatch_not_a_pass():
    """THE ESTATE-WIDE GUARD. A table whose every leg is spec-invalid compared NOTHING, so it must
    block the flip exactly like a mismatch -- otherwise a broken instrument reads as a passing gate.

    The fixture table is not invented: it is the two nass cards in the state they were actually in,
    driven through the REAL build_sql with the sample removed, so the skip counts fed to the guard
    are measured rather than asserted."""
    from leviathan.graphrag.numbers import query as Q

    reg = load_registry()
    spec_invalid: dict[str, int] = {}
    for tid in _NASS:
        for metric, asof, agg in _leg_grid(reg.get(tid)):
            try:                                   # this is _cmp's own try/except, verbatim in shape
                Q.build_sql(Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=None,
                                          agg=agg, limit=50))
            except Exception:                      # noqa: BLE001 - the SKIP arm
                spec_invalid[tid] = spec_invalid.get(tid, 0) + 1
    assert spec_invalid == {"silver_nass_annual": 24, "silver_nass_crop_progress": 24}
    # HEAD's state: nothing compared, nothing non-empty -> the old code produced ZERO mismatches
    # and main() returned 0 on "## verdict: 0/0 exact-match".
    out = parity.vacuity_mismatches(compared={}, nonempty={}, spec_invalid=spec_invalid)
    assert len(out) == 2, out
    for tid, line in zip(_NASS, sorted(out)):
        assert line.startswith(f"SPEC-INVALID-PANEL {tid}: all 24 legs unbuildable (spec invalid)")
        assert "proves nothing" in line            # a MISMATCH -> "FAIL - do NOT flip"


def test_the_guard_is_silent_when_the_table_actually_compared_something():
    """The other half of fail-closed: a table with a few legitimately-unbuildable legs BESIDE real
    compares is untouched. A guard that fired on any skip would make every region-fenced card red."""
    assert parity.vacuity_mismatches(compared={"t": 6}, nonempty={"t": 6},
                                     spec_invalid={"t": 2}) == []
    # ...and the EMPTY-PANEL guard it sits beside still fires on its own case.
    empty = parity.vacuity_mismatches(compared={"t": 6}, nonempty={}, spec_invalid={})
    assert len(empty) == 1 and empty[0].startswith("EMPTY-PANEL t: all 6 compared queries")
    # both at once, both reported -- they are different failures of the same panel.
    both = parity.vacuity_mismatches(compared={"a": 6}, nonempty={}, spec_invalid={"b": 3})
    assert len(both) == 2 and {s.split()[0] for s in both} == {"EMPTY-PANEL", "SPEC-INVALID-PANEL"}


def test_main_feeds_the_guard_and_books_every_spec_invalid_skip():
    """The WIRING, asserted against the real source: a guard nothing calls is worse than no guard.
    _cmp must tally the skip it prints, and main() must run both guards into `mismatches`."""
    import inspect
    src = inspect.getsource(parity.main)
    assert "spec_invalid[tid] = spec_invalid.get(tid, 0) + 1" in src, (
        "the spec-invalid SKIP must be COUNTED where it is printed, or the guard sees nothing")
    assert "mismatches += vacuity_mismatches(compared, nonempty, spec_invalid)" in src
    # the counter has to be booked before _cmp returns on the build failure, i.e. inside the except
    # arm that emits the SKIP line -- not after the compare.
    skip_at = src.index("spec invalid ({e})")
    assert 0 < src.index("spec_invalid[tid]") - skip_at < 200
