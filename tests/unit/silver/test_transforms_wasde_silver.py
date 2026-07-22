"""SILVER-F033 / F034 / F036 -- the WASDE bronze->silver transform.

Golden-fixture + property tests for the LANE M silver producer. AWS-free, pure, no network -- runs
under the F002 isolation guard. Covers:

  * F033 structural marketing-year / status / projection-month parse (a bare month never leaks into
    ``region``); region classification + the distinct-value-pollution gate (calibrated on distinct
    pollution + low row prevalence, NOT a 50%-of-rows floor); stable source_table_id; the 19-term
    attribute vocabulary; quarantine (not silent filter);
  * F034 no drop/keep-last (divergent keys raise); revisions within the stable logical series with
    release-sequence + gap; the commodity marketing-year calendar with no June fallback; the single
    deterministic current-release estimate; deprecated is_final_or_latest + is_source_final;
  * F036 the INV-2 arrow schema built from the registry contract.
"""
from __future__ import annotations

import pytest

from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver import usda_wasde_silver as W


# ---------------------------------------------------------------------------
# F033 -- structural marketing-year / status / projection-month parse.
# ---------------------------------------------------------------------------
def test_parse_my_status_month_structural():
    assert W.parse_marketing_year_status("2026/27 (Proj.) May") == ("2026/27", "projection", "May")
    assert W.parse_marketing_year_status("2008/09 (Est.)") == ("2008/09", "estimate", "")
    assert W.parse_marketing_year_status("2009/2010") == ("2009/10", "actual", "")


def test_bare_month_and_region_are_not_marketing_years():
    # the exact defect F033 closes: a bare month / a region name is NOT a marketing year, so it can
    # never be mis-parsed into one -- and, conversely, the month inside a year header is captured as
    # projection_month, never leaked into region.
    assert W.parse_marketing_year_status("May") is None
    assert W.parse_marketing_year_status("Argentina") is None
    assert W.parse_marketing_year_status("World 3/") is None


def test_estimate_role_vocabulary():
    assert W.estimate_role_from_status("Proj.") == W.ROLE_PROJECTION
    assert W.estimate_role_from_status("(Est.)") == W.ROLE_ESTIMATE
    assert W.estimate_role_from_status("") == W.ROLE_ACTUAL
    assert set(W.ESTIMATE_ROLES) == {"projection", "estimate", "actual"}


# ---------------------------------------------------------------------------
# F033 -- region classification.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,cls", [
    ("United States", W.REGION_CLEAN),
    ("World", W.REGION_CLEAN),
    ("eu_27", W.REGION_CLEAN),           # a legit digit-bearing scope is NOT junk
    ("fsu_12", W.REGION_CLEAN),
    ("Major Exporters", W.REGION_CLEAN),
    ("May", W.REGION_MONTH_NAME),        # year-header leak
    ("February", W.REGION_MONTH_NAME),
    # bare month ABBREVIATIONS = two-vintage projection column headers leaked into the
    # region axis (scanned-era continuation tables; 1989-03-09 WasdeKeyConflict canary)
    ("Mar", W.REGION_MONTH_NAME),
    ("Mar.", W.REGION_MONTH_NAME),
    ("Feb", W.REGION_MONTH_NAME),
    # month token + projection/estimate MARKER = a two-vintage column header leaked into
    # the region axis (scanned-era World S&U continuation tables; 1994-10-12 'Sep Proj'
    # WasdeKeyConflict canary). The rule is general across all 12 months x {proj, est}.
    ("Sep. Proj", W.REGION_MONTH_NAME),
    ("Sep Proj", W.REGION_MONTH_NAME),
    ("Aug Proj", W.REGION_MONTH_NAME),
    ("Feb Est", W.REGION_MONTH_NAME),
    ("May Proj", W.REGION_MONTH_NAME),
    ("September Projection", W.REGION_MONTH_NAME),
    # bare roman-numeral OCR / column-index fragments (scanned-era continuation tables;
    # 1994-07-12 'II' WasdeKeyConflict canary, raw forms 'II *' / 'III' / 'IV *').
    ("II *", W.REGION_ROMAN_NUMERAL),
    ("III", W.REGION_ROMAN_NUMERAL),
    ("IV *", W.REGION_ROMAN_NUMERAL),
    ("ii", W.REGION_ROMAN_NUMERAL),
    ("vi", W.REGION_ROMAN_NUMERAL),
    ("ix", W.REGION_ROMAN_NUMERAL),
    ("february_0_30_4_58_0_62", W.REGION_NUMERIC_CONCAT),
    ("i", W.REGION_SINGLE_CHAR),          # single-char roman stays single_char (v / x too)
    ("v", W.REGION_SINGLE_CHAR),
    ("1234", W.REGION_PURE_NUMERIC),
    ("item", W.REGION_HEADER_LEAK),
    ("", W.REGION_EMPTY),
    # real scopes that STRUCTURALLY resemble the new junk rules MUST stay clean (no false
    # quarantine): a multi-token region is not a month+marker header, and no real region is
    # a bare roman numeral.
    ("Other Europe", W.REGION_CLEAN),
    ("Selected Exporters", W.REGION_CLEAN),
    ("European Union 27", W.REGION_CLEAN),
])
def test_classify_region(raw, cls):
    assert W.classify_region(raw) == cls


def test_normalize_region_scopes():
    assert W.normalize_region("United States") == "united_states"
    assert W.normalize_region("European Union 27") == "european_union_27"
    assert W.normalize_region("World 3/") == "world"


# ---------------------------------------------------------------------------
# F033 -- region-pollution gate: distinct pollution + LOW row prevalence, NOT a 50%-of-rows floor.
# ---------------------------------------------------------------------------
def test_region_gate_fires_on_distinct_pollution_not_row_majority():
    # 96 clean rows over 3 legit scopes + 4 rows spread over 4 DISTINCT junk tokens.
    regions = (["united_states"] * 40 + ["world"] * 30 + ["brazil"] * 26
               + ["May", "february_0_30_4_58_0_62", "i", "9999"])
    census = W.region_pollution_census(regions)
    assert census.total_rows == 100
    # distinct pollution is high (4 of 7 distinct tokens malformed) ...
    assert census.malformed_distinct == 4
    assert census.distinct_pollution_fraction > 0.5
    # ... while row prevalence is low (4/100), exactly the recon's shape.
    assert census.malformed_rows == 4
    assert census.row_prevalence_fraction == pytest.approx(0.04)
    # the gate FIRES on distinct pollution even though rows-junk is only 4% (a 50%-of-rows floor
    # would never trip here -- the C-WRONG-6 calibration the plan mandates).
    gate = W.region_cleanliness_gate("silver_wasde", regions)
    assert gate, "distinct-pollution gate must fire"
    assert any(g.kind == W.KIND_REGION_POLLUTED for g in gate)


def test_region_gate_green_on_clean_axis():
    regions = ["united_states"] * 50 + ["world"] * 50
    assert W.region_cleanliness_gate("silver_wasde", regions) == []


# ---------------------------------------------------------------------------
# F033 -- stable source_table_id + commodity derivation.
# ---------------------------------------------------------------------------
def test_source_table_id_stable_and_footnote_free():
    a = W.source_table_id("World Wheat Supply and Use 1/ (Million Metric Tons)")
    b = W.source_table_id("World Wheat Supply and Use 1/ (Million Metric Tons)")
    assert a == b == "world_wheat_supply_and_use"


def test_derive_commodity_table_type():
    assert W.derive_commodity_table_type("World Soybean Meal Supply and Use") == ("soybean_meal", "world")
    assert W.derive_commodity_table_type("U.S. Wheat Supply and Use") == ("wheat", "us")
    assert W.derive_commodity_table_type("Narrative page about policy") is None


# ---------------------------------------------------------------------------
# F033 -- attribute vocabulary (the 19-term INV-1 set).
# ---------------------------------------------------------------------------
def test_attribute_vocabulary_is_the_19_terms():
    assert len(W.WASDE_ATTRIBUTES) == 19
    assert W.normalize_attribute("Ending Stocks") == "ending_stocks"
    assert W.normalize_attribute("Total Use") == "total_use"
    assert W.normalize_attribute("Yield per Harvested") == "yield"
    # a non-canonical historical line ('trade') is quarantined, never silently renamed.
    assert W.normalize_attribute("trade") is None
    for a in W.WASDE_ATTRIBUTES:
        assert W.normalize_attribute(a) == a


# ---------------------------------------------------------------------------
# F034 -- the marketing-year calendar (NO June fallback).
# ---------------------------------------------------------------------------
def test_marketing_year_calendar_no_june_fallback():
    from datetime import date
    assert W.marketing_year_end_date("wheat", "2009/10") == date(2010, 5, 31)
    assert W.marketing_year_end_date("corn", "2024/25") == date(2025, 8, 31)
    # an unsupported commodity does NOT get a June (or any) fallback -> None (caller quarantines).
    assert W.marketing_year_end_date("unobtanium", "2024/25") is None


def test_months_to_marketing_year_end():
    assert W.months_to_marketing_year_end("2024-06-12", "corn", "2024/25") == 14
    assert W.months_to_marketing_year_end("2024-06-12", "unobtanium", "2024/25") is None


# ---------------------------------------------------------------------------
# F034 -- conflict resolution (NO drop/keep-last).
# ---------------------------------------------------------------------------
def _row(**kw):
    base = dict(release_date="2024-06-12", source_table_id="world_wheat_supply_and_use",
                commodity="wheat", region="world", marketing_year="2024/25", attribute="ending_stocks",
                unit="Million Metric Tons", estimate_role="projection", projection_month="", estimate=1.0)
    base.update(kw)
    return base


def test_resolve_conflicts_dedupes_identical_but_raises_on_divergent():
    # identical duplicate (repeated PDF page) collapses to one.
    assert len(W.resolve_conflicts([_row(estimate=5.0), _row(estimate=5.0)])) == 1
    # divergent estimate on the same natural key is a real ambiguity -> raise (never keep-last).
    with pytest.raises(W.WasdeKeyConflict):
        W.resolve_conflicts([_row(estimate=5.0), _row(estimate=7.0)])


# ---------------------------------------------------------------------------
# F034 -- revisions within the stable logical series.
# ---------------------------------------------------------------------------
def test_compute_revisions_threads_series_across_releases():
    r1 = _row(release_date="2024-05-10", estimate=100.0)
    state = W.compute_revisions([r1])
    assert r1["is_first_estimate"] is True and r1["revision"] is None and r1["release_sequence"] == 1

    r2 = _row(release_date="2024-06-12", estimate=105.0)
    W.compute_revisions([r2], state)
    assert r2["is_first_estimate"] is False
    assert r2["prior_release_date"] == "2024-05-10"
    assert r2["prior_estimate"] == 100.0
    assert r2["revision"] == 5.0
    assert r2["revision_direction"] == "up"
    assert r2["revision_gap_days"] == 33
    assert r2["release_sequence"] == 2


def test_revisions_never_cross_series():
    # different attribute == a different series; no revision linkage.
    r1 = _row(release_date="2024-05-10", attribute="production", estimate=100.0)
    state = W.compute_revisions([r1])
    r2 = _row(release_date="2024-06-12", attribute="ending_stocks", estimate=5.0)
    W.compute_revisions([r2], state)
    assert r2["is_first_estimate"] is True and r2["prior_estimate"] is None


# ---------------------------------------------------------------------------
# F034 -- the whole build.
# ---------------------------------------------------------------------------
def _bronze(region, attribute, market_year, status="", value=1.0,
            table_name="World Wheat Supply and Use 1/ (Million Metric Tons)",
            release_date="2024-06-12", projection_month=""):
    return dict(release_date=release_date, table_name=table_name, region=region,
                market_year=market_year, status=status, projection_month=projection_month,
                attribute=attribute, value=value, unit="Million Metric Tons")


def test_build_quarantines_junk_and_keeps_the_axis_clean():
    rows = [
        _bronze("United States", "Ending Stocks", "2024/25", status="Proj.", value=10.0),
        _bronze("World", "Production", "2024/25", status="Proj.", value=800.0),
        _bronze("May", "Ending Stocks", "2024/25", value=1.0),                 # month-leak region
        _bronze("february_0_30_4_58_0_62", "Production", "2024/25", value=2.0),  # numeric concat
        _bronze("United States", "trade", "2024/25", value=3.0),                # unknown attribute
        _bronze("United States", "Ending Stocks", "2024/25", status="Proj.",
                table_name="Narrative policy page", value=4.0),                 # unmapped commodity
    ]
    res = W.build_silver_frame(rows)
    # only the two clean rows survive; the rest are quarantined with typed reasons.
    assert len(res.rows) == 2
    reasons = {q.reason for q in res.quarantined}
    assert reasons == {"malformed_region", "unknown_attribute", "unmapped_commodity"}
    # the SILVER output region axis is clean -> the region gate is green.
    assert res.region_gate == []
    assert all(W.is_clean_region(r["region"]) for r in res.rows)


def test_build_preserves_all_displayed_estimates_and_marks_one_current():
    rows = [
        _bronze("United States", "Ending Stocks", "2023/24", status="Est.", value=9.0),   # prior yr
        _bronze("United States", "Ending Stocks", "2024/25", status="Proj.", value=10.0),  # current yr
    ]
    res = W.build_silver_frame(rows)
    assert len(res.rows) == 2                            # BOTH displayed estimates survive
    by_my = {r["marketing_year"]: r for r in res.rows}
    assert by_my["2023/24"]["estimate_role"] == "estimate"
    assert by_my["2024/25"]["estimate_role"] == "projection"
    # exactly one current-release estimate, deterministically the latest MY.
    current = [r for r in res.rows if r["is_current_release_estimate"]]
    assert len(current) == 1 and current[0]["marketing_year"] == "2024/25"
    # is_projection tracks the role; is_final_or_latest is deprecated (never set).
    assert by_my["2024/25"]["is_projection"] is True
    assert all(r["is_final_or_latest"] is None for r in res.rows)
    # is_source_final only for the settled actual-role rows (none here; both carry a marker).
    assert by_my["2023/24"]["is_source_final"] is None


def test_build_is_deterministic():
    rows = [
        _bronze("United States", "Ending Stocks", "2024/25", status="Proj.", value=10.0),
        _bronze("World", "Production", "2024/25", status="Proj.", value=800.0),
    ]
    a = W.build_silver_frame(rows).rows
    b = W.build_silver_frame(rows).rows
    assert a == b


def test_build_marketing_year_end_date_populated():
    # table_name is a WHEAT table -> marketing year ends 31 May of the end year (no June fallback).
    res = W.build_silver_frame([_bronze("World", "Ending Stocks", "2024/25", status="Proj.")])
    assert res.rows[0]["marketing_year_end_date"] == "2025-05-31"


# ---------------------------------------------------------------------------
# F034 -- latest-state view replaces the deprecated is_final_or_latest flag.
# ---------------------------------------------------------------------------
def test_latest_state_view_picks_latest_release():
    rows = [
        _row(release_date="2024-05-10", estimate=100.0),
        _row(release_date="2024-06-12", estimate=105.0),
    ]
    latest = W.latest_state_view(rows)
    assert len(latest) == 1 and latest[0]["release_date"] == "2024-06-12"


# ---------------------------------------------------------------------------
# F036 -- the INV-2 arrow schema from the registry contract.
# ---------------------------------------------------------------------------
def test_arrow_schema_matches_registry_inv2_targets():
    import pyarrow as pa

    contract = load_registry().table("silver_wasde")
    schema = W.arrow_schema_from_contract(contract)
    by = {f.name: f.type for f in schema}
    # the int64 fix + the new typed columns are pinned explicitly (never first-file inferred).
    assert by["months_to_marketing_year_end"] == pa.int64()
    assert by["release_sequence"] == pa.int64()
    assert by["revision_gap_days"] == pa.int64()
    assert by["is_projection"] == pa.bool_()
    assert by["is_current_release_estimate"] == pa.bool_()
    assert by["estimate"] == pa.float64()
    assert by["source_table_id"] == pa.string()
    assert by["release_date"] == pa.string()   # partition key carried in-file


def test_to_arrow_table_casts_rows_to_the_contract():
    import pyarrow as pa

    contract = load_registry().table("silver_wasde")
    res = W.build_silver_frame([_bronze("World", "Ending Stocks", "2024/25", status="Proj.", value=7.5)])
    table = W.to_arrow_table(res.rows, contract)
    assert table.schema.field("months_to_marketing_year_end").type == pa.int64()
    assert table.schema.field("is_projection").type == pa.bool_()
    assert table.column("estimate").to_pylist() == [7.5]
    assert table.column("estimate_role").to_pylist() == ["projection"]
    assert table.num_rows == 1


# ---------------------------------------------------------------------------
# WASDE-restoration W2 -- range-era price-band columns (value_low / value_high).
# ---------------------------------------------------------------------------
def _bronze_band(region, attribute, market_year, *, value, value_low=None, value_high=None,
                 status="Proj.", table_name="U.S. Wheat Supply and Use (Million Metric Tons)",
                 release_date="2024-06-12"):
    return dict(release_date=release_date, table_name=table_name, region=region,
                market_year=market_year, status=status, projection_month="", attribute=attribute,
                value=value, unit="dollars per bushel", value_low=value_low, value_high=value_high)


def test_stage_one_threads_value_low_high_range_and_null_for_point():
    # A range-era price ("7.00 - 8.20" -> midpoint 7.60, bounds kept) AND a plain point value in ONE
    # release. The producer carries value_low/value_high additively: populated for the range row, NULL
    # for the point row (estimate always carries the midpoint / the point value).
    rows = [
        _bronze_band("United States", "Avg. Farm Price", "2024/25", value=7.60,
                     value_low=7.00, value_high=8.20),
        _bronze_band("United States", "Ending Stocks", "2024/25", value=540.0),   # point -> null band
    ]
    res = W.build_silver_frame(rows)
    by = {r["attribute"]: r for r in res.rows}
    assert by["avg_farm_price"]["value_low"] == 7.00 and by["avg_farm_price"]["value_high"] == 8.20
    assert by["avg_farm_price"]["estimate"] == 7.60                       # midpoint stays in estimate
    assert by["ending_stocks"]["value_low"] is None and by["ending_stocks"]["value_high"] is None
    # both columns are declared on every finalized row (additive, order-stable).
    assert "value_low" in res.rows[0] and "value_high" in res.rows[0]


def test_value_low_high_in_arrow_writer_schema_float64():
    import pyarrow as pa

    contract = load_registry().table("silver_wasde")
    schema = W.arrow_schema_from_contract(contract)
    by = {f.name: f.type for f in schema}
    # hidden-schema in the CATALOG, but the WRITER schema (keyed on target_arrow_type) DOES carry them
    # as float64 -> the F034 producer physically emits the price bands into the parquet.
    assert by["value_low"] == pa.float64() and by["value_high"] == pa.float64()
    res = W.build_silver_frame([_bronze_band("United States", "Avg. Farm Price", "2024/25",
                                             value=7.6, value_low=7.0, value_high=8.2)])
    table = W.to_arrow_table(res.rows, contract)
    assert table.column("value_low").to_pylist() == [7.0]
    assert table.column("value_high").to_pylist() == [8.2]
