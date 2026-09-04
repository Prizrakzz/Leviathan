"""SILVER-C001 prerequisite (Attack 3 #4): numbers_parity must cover gold_weather_z with a real sample
commodity and lift the [:4] metric cap for TALL tables (or BF-W1's rebuild target passes vacuously).

AWS-free: only inspects the module's static config + the metric-selection expression."""
from __future__ import annotations

import importlib

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
    fan_year = int(mid[:4])
    assert all("%04d-%02d" % (fan_year, m) in cal for m in range(1, 13)), (
        "the banked calendar must cover every month of %d for this premise to be measurable"
        % fan_year
    )
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
    assert any(d <= mid for d in dates) and any(d > mid for d in dates), (
        f"the mid-fan as-of {mid} must sit STRICTLY inside MY{my}'s vintage span {dates[0]}..{dates[-1]}"
    )
    assert all(d <= settled for d in dates), f"the settled as-of {settled} must be past the whole fan"
    # ...and the two as-ofs must therefore select DIFFERENT vintages of the same cell.
    assert max(d for d in dates if d <= mid) != max(d for d in dates if d <= settled)


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
