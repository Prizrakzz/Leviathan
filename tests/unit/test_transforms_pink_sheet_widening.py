"""SILVER-F063 -- the Pink Sheet SERIES WIDENING, pinned.

The producer carried 15 of the World Bank workbook's 71 monthly series, and nothing in the pipeline
said so. This suite pins the four things that keep that from happening again:

  1. DISPOSITION -- every one of the 71 measured source headers is either KEPT or REFUSED-with-a-
     reason, exactly once, and the header-drift instrument fires when a 72nd appears.
  2. NAMING -- new columns follow the shipped ``<commodity>_usd_<contract-unit>`` convention, and
     the pre-existing fertilizer(mt)/agricultural(t) split is preserved rather than "fixed".
  3. Z-SCORE TWINS -- every price column has exactly one ``_zscore_5yr`` twin, and the 16 pre-F063
     validity floors are FROZEN byte-for-byte.
  4. FLOORS -- the registry's non-null floors are MEASURED (the numbers are in the comments below,
     with the measurement that produced them), never inferred.

MEASUREMENT PROVENANCE. Every number in this file was measured on 2026-08-20 by running the widened
producer end-to-end over BOTH raw workbooks held in S3
(``raw/production/source=world_bank_pink_sheet/release=2026M05`` and ``release=2026M07``) ->
798 monthly rows, 1960-01..2026-06. The 71 header strings are byte-identical between the two
releases. The pre-F063 36 columns were verified byte-identical against the live
``silver/pink_sheet/part-000.parquet`` under the HEAD producer on the same bronze input.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import pandas as pd
import pytest
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver.pink_sheet import (
    _F063_VALUE_COLUMNS,
    _PRE_F063_COLUMNS,
    _SERIES_RENAME,
    _SERIES_UNIT_SCALE,
    _ZSCORE_VALID_FROM,
    SILVER_COLUMNS,
    build_silver,
)
from leviathan.transforms.raw_to_bronze.world_bank_pink_sheet import (
    _ABSENT_FROM_SOURCE,
    _REFUSED_SERIES,
    _REQUIRED_SERIES,
    _SERIES_PATTERNS,
    _match_columns,
)

# ---------------------------------------------------------------------------
# The 71 series headers of the "Monthly Prices" sheet, MEASURED 2026-08-20 from
# CMO-Historical-Data-Monthly.xlsx, releases 2026M05 and 2026M07 (identical in both).
# Trailing spaces are REAL and are reproduced verbatim -- 'Urea ' and 'Rice, Thai 5% ' both carry one,
# and the refusal table's strip()-comparison exists because of them.
# ---------------------------------------------------------------------------
MEASURED_HEADERS: list[str] = [
    "Crude oil, average", "Crude oil, Brent", "Crude oil, Dubai", "Crude oil, WTI",
    "Coal, Australian", "Coal, South African **", "Natural gas, US", "Natural gas, Europe",
    "Liquefied natural gas, Japan", "Natural gas index", "Cocoa", "Coffee, Arabica",
    "Coffee, Robusta", "Tea, avg 3 auctions", "Tea, Colombo", "Tea, Kolkata", "Tea, Mombasa",
    "Coconut oil", "Groundnuts", "Fish meal", "Groundnut oil **", "Palm oil", "Palm kernel oil",
    "Soybeans", "Soybean oil", "Soybean meal", "Rapeseed oil", "Sunflower oil", "Barley", "Maize",
    "Sorghum", "Rice, Thai 5% ", "Rice, Thai 25% ", "Rice, Thai A.1", "Rice, Viet Namese 5%",
    "Wheat, US SRW", "Wheat, US HRW", "Banana, Europe", "Banana, US", "Orange", "Beef **",
    "Chicken **", "Lamb **", "Shrimps, Mexican", "Sugar, EU", "Sugar, US", "Sugar, world",
    "Tobacco, US import u.v.", "Logs, Cameroon", "Logs, Malaysian", "Sawnwood, Cameroon",
    "Sawnwood, Malaysian", "Plywood", "Cotton, A Index", "Rubber, TSR20 **", "Rubber, RSS3",
    "Phosphate rock", "DAP", "TSP", "Urea ", "Potassium chloride **", "Aluminum",
    "Iron ore, cfr spot", "Copper", "Lead", "Tin", "Nickel", "Zinc", "Gold", "Platinum", "Silver",
]

# The eleven headers the World Bank publishes in ($/kg), measured from row 6 of the same sheet.
MEASURED_KG_HEADERS: frozenset[str] = frozenset({
    "Cocoa", "Coffee, Arabica", "Coffee, Robusta", "Orange", "Beef **", "Chicken **",
    "Sugar, EU", "Sugar, US", "Sugar, world", "Cotton, A Index", "Rubber, RSS3",
})

# Per-column measurement from the widened producer run (798 rows, 1960-01..2026-06):
#   silver column -> (first populated month, non-null count, non-null fraction)
MEASURED_NEW_COVERAGE: dict[str, tuple[str, int, float]] = {
    "coconut_oil_usd_t":      ("1960-01", 798, 1.0000),
    "groundnuts_usd_t":       ("1980-01", 558, 0.6992),
    "groundnut_oil_usd_t":    ("1960-01", 798, 1.0000),
    "palm_kernel_oil_usd_t":  ("1996-01", 366, 0.4586),
    "fish_meal_usd_t":        ("1979-01", 570, 0.7143),
    "sunflower_oil_usd_t":    ("2002-02", 288, 0.3609),
    "barley_usd_t":           ("1960-01", 728, 0.9123),   # DISCONTINUED after 2020-08
    "sorghum_usd_t":          ("1960-01", 728, 0.9123),   # DISCONTINUED after 2020-08
    "orange_usd_t":           ("1960-01", 798, 1.0000),
    "cotton_a_index_usd_t":   ("1960-01", 798, 1.0000),
    "rubber_rss3_usd_t":      ("1960-01", 798, 1.0000),
    "coffee_arabica_usd_t":   ("1960-01", 798, 1.0000),
    "coffee_robusta_usd_t":   ("1960-01", 798, 1.0000),
    "cocoa_usd_t":            ("1960-01", 798, 1.0000),
    "rice_thai_5pct_usd_t":   ("1960-01", 798, 1.0000),
    "maize_usd_t":            ("1960-01", 798, 1.0000),
    "raw_sugar_eu_usd_t":     ("1960-01", 798, 1.0000),
    "raw_sugar_us_usd_t":     ("1960-01", 798, 1.0000),
    "beef_usd_t":             ("1960-01", 798, 1.0000),
    "chicken_usd_t":          ("1960-01", 798, 1.0000),
    "tsp_usd_mt":             ("1960-01", 798, 1.0000),
    "copper_usd_mt":          ("1960-01", 798, 1.0000),
}

# The measured z-twin non-null fractions for the four columns that sit under the uniform 0.5 floor.
# These are the ONLY inputs to the registry's four new min_nonnull_frac_overrides.
MEASURED_SUB_FLOOR: dict[str, float] = {
    "palm_kernel_oil_usd_t":            0.4586,
    "palm_kernel_oil_usd_t_zscore_5yr": 0.4148,
    "sunflower_oil_usd_t":              0.3609,
    "sunflower_oil_usd_t_zscore_5yr":   0.3170,
}

# The 16 pre-F063 z-score validity floors, FROZEN. These were hand-set and follow no single
# derivable rule; re-deriving them would silently move already-published z-scores.
FROZEN_ZSCORE_FLOORS: dict[str, int] = {
    "urea_usd_mt": 1992, "dap_usd_mt": 1967, "potassium_usd_mt": 1980,
    "natural_gas_us_usd_mmbtu": 1979, "natural_gas_eu_usd_mmbtu": 1991,
    "phosphate_rock_usd_mt": 1960, "blended_npk_index": 1967, "brent_crude_usd_bbl": 1960,
    "soybeans_usd_t": 1960, "soybean_oil_usd_t": 1960, "soybean_meal_usd_t": 1960,
    "palm_oil_cpo_usd_t": 1960, "raw_sugar_world_usd_t": 1960, "wheat_us_hrw_usd_t": 1960,
    "wheat_us_srw_usd_t": 1960, "rapeseed_oil_usd_t": 1960,
}


def _bronze(d="2026-01-01", release="2026M07", values=None) -> pd.DataFrame:
    values = values or {}
    return pd.DataFrame([{
        "date": date.fromisoformat(d), "series_name": bn,
        "value_usd": float(values.get(bn, 100.0)),
        "release_ym": release, "source": "world_bank_pink_sheet",
    } for bn in _SERIES_RENAME])


# ===========================================================================
# 1. DISPOSITION -- every measured source header is accounted for, exactly once
# ===========================================================================
class TestDisposition:
    def test_measured_header_census_is_71(self):
        assert len(MEASURED_HEADERS) == 71
        assert len(set(MEASURED_HEADERS)) == 71, "the workbook has no duplicate headers"

    def test_kept_plus_refused_covers_every_header_exactly_once(self):
        """37 kept + 34 refused == the 71 measured headers. No gaps, no double-counting."""
        assert len(_SERIES_PATTERNS) == 37
        assert len(_REFUSED_SERIES) == 34
        assert len(_SERIES_PATTERNS) + len(_REFUSED_SERIES) == len(MEASURED_HEADERS)

        rename = _match_columns(MEASURED_HEADERS, _SERIES_PATTERNS, required=_REQUIRED_SERIES)
        kept_headers = set(rename)
        refused_headers = {h for h in MEASURED_HEADERS if h.strip() in
                           {k.strip() for k in _REFUSED_SERIES}}

        assert len(kept_headers) == 37
        assert len(refused_headers) == 34
        assert kept_headers & refused_headers == set(), "a header is both kept and refused"
        assert kept_headers | refused_headers == set(MEASURED_HEADERS)

    def test_every_refusal_carries_a_written_reason(self):
        for header, reason in _REFUSED_SERIES.items():
            assert isinstance(reason, str) and len(reason) > 20, header
            assert header.strip() in {h.strip() for h in MEASURED_HEADERS}, (
                f"refusing {header!r}, which is not a measured workbook header")

    def test_every_pattern_resolves_to_exactly_one_header(self):
        lowered = [h.lower() for h in MEASURED_HEADERS]
        for pattern, canonical in _SERIES_PATTERNS.items():
            hits = [h for h in lowered if pattern in h]
            assert len(hits) == 1, f"pattern {pattern!r} -> {len(hits)} headers {hits}"

    def test_the_two_absent_targets_really_are_absent_from_the_source(self):
        """copra and olive oil are refused on MEASUREMENT, not opinion."""
        assert set(_ABSENT_FROM_SOURCE) == {"copra", "olive_oil"}
        lowered = " | ".join(MEASURED_HEADERS).lower()
        assert "copra" not in lowered
        assert "olive" not in lowered

    def test_header_drift_instrument_fires_on_a_new_series(self, caplog):
        """A 72nd World Bank series must WARN, not vanish -- the durable fix for the class."""
        with caplog.at_level(logging.WARNING):
            _match_columns(MEASURED_HEADERS + ["Quinoa"], _SERIES_PATTERNS,
                           required=_REQUIRED_SERIES)
        assert "NEITHER kept NOR in the refusal table" in caplog.text
        assert "Quinoa" in caplog.text

    def test_header_drift_instrument_is_silent_on_the_measured_census(self, caplog):
        """No false positives -- otherwise the reader is trained to ignore the warning."""
        with caplog.at_level(logging.WARNING):
            _match_columns(MEASURED_HEADERS, _SERIES_PATTERNS, required=_REQUIRED_SERIES)
        assert "NEITHER kept NOR" not in caplog.text

    def test_double_claimed_header_fails_closed(self):
        """Two patterns resolving to ONE header silently dropped a governed series before F063.

        The rename map is keyed by the original header, so the second pattern overwrote the first.
        At 15 patterns that was luck; at 37 it must be an error.
        """
        patterns = dict(_SERIES_PATTERNS)
        patterns["cocoa"] = "cocoa_usd_kg"          # the real one
        patterns["coco"] = "cocoa_duplicate_usd_kg"  # a second pattern hitting 'Cocoa'
        required = frozenset(patterns.values())
        with pytest.raises(ValueError, match="double_claimed"):
            _match_columns(MEASURED_HEADERS, patterns, required=required)


# ===========================================================================
# 2. NAMING CONVENTION
# ===========================================================================
class TestNamingConvention:
    _AG_UNIT = "_usd_t"
    _NON_AG_UNITS = ("_usd_mt", "_usd_bbl", "_usd_mmbtu")

    def test_every_price_column_is_commodity_underscore_usd_underscore_unit(self):
        for col in _SERIES_RENAME.values():
            assert re.fullmatch(r"[a-z0-9_]+_usd_(t|mt|bbl|mmbtu)", col), col

    def test_new_agricultural_legs_use_the_ag_tonne_suffix(self):
        """The shipped table splits units by class: fertilizer/mineral _usd_mt, agricultural _usd_t.

        That split is a pre-existing inconsistency (both mean tonnes) and is PRESERVED, never
        "corrected" -- renaming a live column is a feature-visible schema regression.
        """
        non_ag = {"tsp_usd_mt", "copper_usd_mt"}
        for col in _F063_VALUE_COLUMNS:
            if col in non_ag:
                assert col.endswith("_usd_mt"), col
            else:
                assert col.endswith(self._AG_UNIT), col

    def test_no_new_column_introduces_a_kg_unit(self):
        """Every $/kg source series is scaled into the table's single agricultural unit."""
        for col in SILVER_COLUMNS:
            assert not col.endswith("_usd_kg"), col

    def test_bronze_names_carry_the_SOURCE_unit_and_silver_the_CONTRACT_unit(self):
        for bronze, silver in _SERIES_RENAME.items():
            if bronze.endswith("_usd_kg"):
                assert silver.endswith("_usd_t"), (bronze, silver)
                assert _SERIES_UNIT_SCALE[silver] == 1000.0

    def test_exactly_the_eleven_measured_kg_series_are_scaled(self):
        assert len(_SERIES_UNIT_SCALE) == len(MEASURED_KG_HEADERS) == 11
        assert set(_SERIES_UNIT_SCALE.values()) == {1000.0}
        kg_bronze = {b for b in _SERIES_RENAME if b.endswith("_usd_kg")}
        assert {_SERIES_RENAME[b] for b in kg_bronze} == set(_SERIES_UNIT_SCALE)

    def test_kg_to_tonne_scaling_is_applied_to_a_new_leg(self):
        df = build_silver([_bronze(values={"cocoa_usd_kg": 3.2, "sugar_eu_usd_kg": 0.5})])
        assert df.iloc[0]["cocoa_usd_t"] == pytest.approx(3200.0)
        assert df.iloc[0]["raw_sugar_eu_usd_t"] == pytest.approx(500.0)

    def test_the_sugar_trio_shares_one_unit_so_the_wedge_is_a_subtraction(self):
        df = build_silver([_bronze(values={
            "sugar_world_usd_kg": 0.40, "sugar_eu_usd_kg": 0.55, "sugar_us_usd_kg": 0.85})])
        row = df.iloc[0]
        assert row["raw_sugar_eu_usd_t"] - row["raw_sugar_world_usd_t"] == pytest.approx(150.0)
        assert row["raw_sugar_us_usd_t"] - row["raw_sugar_world_usd_t"] == pytest.approx(450.0)


# ===========================================================================
# 3. Z-SCORE TWINS + APPEND-ONLY ORDER
# ===========================================================================
class TestZScoreTwinsAndOrder:
    def test_every_price_column_has_exactly_one_zscore_twin(self):
        levels = list(_SERIES_RENAME.values()) + ["blended_npk_index"]
        assert len(levels) == 38
        for col in levels:
            assert f"{col}_zscore_5yr" in SILVER_COLUMNS, col
        twins = [c for c in SILVER_COLUMNS if c.endswith("_zscore_5yr")]
        assert len(twins) == 38
        assert {t[: -len("_zscore_5yr")] for t in twins} == set(levels)

    def test_every_twin_has_a_measured_validity_floor(self):
        levels = set(_SERIES_RENAME.values()) | {"blended_npk_index"}
        assert set(_ZSCORE_VALID_FROM) == levels, "a series has no declared floor"

    def test_the_pre_f063_floors_are_frozen(self):
        """Re-deriving these would silently move already-published z-scores."""
        for col, year in FROZEN_ZSCORE_FLOORS.items():
            assert _ZSCORE_VALID_FROM[col] == year, f"{col} floor moved"

    def test_the_three_measured_flat_prefix_floors(self):
        """Only three F063 series repeat an annual average before monthly data begins.

        MEASURED as the contiguous leading run of calendar years whose 12 values are identical:
        raw_sugar_eu 1960-1963, chicken 1960, tsp 1960-1966. Everything else floors at its first
        populated year.
        """
        assert _ZSCORE_VALID_FROM["raw_sugar_eu_usd_t"] == 1964
        assert _ZSCORE_VALID_FROM["chicken_usd_t"] == 1961
        assert _ZSCORE_VALID_FROM["tsp_usd_mt"] == 1967

    def test_new_floors_never_precede_the_measured_first_populated_year(self):
        for col, (first, _, _) in MEASURED_NEW_COVERAGE.items():
            assert _ZSCORE_VALID_FROM[col] >= int(first[:4]), col

    def test_column_order_is_append_only(self):
        """The 36 shipped columns keep ordinals 0-35 so the Glue migration is ADD, never REPLACE."""
        assert len(_PRE_F063_COLUMNS) == 36
        assert SILVER_COLUMNS[:36] == _PRE_F063_COLUMNS
        assert SILVER_COLUMNS[35] == "latest_release_ym"
        assert len(SILVER_COLUMNS) == 80
        assert len(set(SILVER_COLUMNS)) == 80

    def test_new_values_precede_new_twins_in_the_append_block(self):
        tail = SILVER_COLUMNS[36:]
        assert tail[:22] == _F063_VALUE_COLUMNS
        assert tail[22:] == [f"{c}_zscore_5yr" for c in _F063_VALUE_COLUMNS]

    def test_tsp_is_not_folded_into_the_blended_npk_index(self):
        """Changing the index would rewrite a live published column."""
        df = build_silver([_bronze(values={
            "urea_e_europe_bulk_spot_usd_mt": 300.0, "dap_spot_usd_mt": 600.0,
            "potassium_chloride_std_usd_mt": 300.0, "tsp_usd_mt": 9999.0})])
        assert df.iloc[0]["blended_npk_index"] == pytest.approx(400.0)


# ===========================================================================
# 4. FLOORS -- measured, not invented; and the registry agrees with the producer
# ===========================================================================
class TestRegistryFloorsAreMeasured:
    @pytest.fixture(scope="class")
    def contract(self):
        return load_registry().table("silver_pink_sheet")

    def test_contract_declares_all_eighty_columns_in_producer_order(self, contract):
        assert [c["name"] for c in contract["physical_columns"]] == SILVER_COLUMNS

    def test_value_columns_are_every_column_but_the_four_axis_columns(self, contract):
        axis = {"date", "year", "month", "latest_release_ym"}
        assert set(contract["value_columns"]) == set(SILVER_COLUMNS) - axis
        assert len(contract["value_columns"]) == 76

    def test_exactly_the_measured_sub_floor_columns_carry_an_override(self, contract):
        """A floor override exists ONLY where the MEASURED fraction cannot reach the table floor.

        rapeseed_oil (measured 2026-08-04) plus the two F063 series that start mid-history.
        Everything else stays at the uniform 0.5 -- an unjustified override is a disarmed gate.
        """
        overrides = contract["min_nonnull_frac_overrides"]
        assert set(overrides) == set(MEASURED_SUB_FLOOR) | {
            "rapeseed_oil_usd_t", "rapeseed_oil_usd_t_zscore_5yr"}

    def test_every_override_sits_below_its_measured_fraction(self, contract):
        """Measured-minus-margin: the gate must still catch a REAL coverage regression."""
        overrides = contract["min_nonnull_frac_overrides"]
        for col, measured in MEASURED_SUB_FLOOR.items():
            assert overrides[col] < measured, col
            assert overrides[col] > measured * 0.6, f"{col} floor is so low it gates nothing"

    def test_no_override_hides_a_column_that_clears_the_table_floor(self, contract):
        floor = contract["min_nonnull_frac"]
        assert floor == 0.5
        for col, (_, _, frac) in MEASURED_NEW_COVERAGE.items():
            if frac >= floor:
                assert col not in contract["min_nonnull_frac_overrides"], (
                    f"{col} measures {frac} and needs no override")

    def test_every_override_key_is_a_declared_value_column(self, contract):
        for col in contract["min_nonnull_frac_overrides"]:
            assert col in contract["value_columns"], col

    def test_discontinued_series_pass_the_floor_and_that_is_a_known_limitation(self):
        """barley/sorghum ended 2020-08 but measure 0.9123 -- NO floor can see that staleness.

        Pinned so the next reader does not mistake a passing gate for a live series; the warning
        lives in the numbers card notes instead.
        """
        for col in ("barley_usd_t", "sorghum_usd_t"):
            assert MEASURED_NEW_COVERAGE[col][2] == pytest.approx(0.9123, abs=1e-4)
            assert MEASURED_NEW_COVERAGE[col][2] > 0.5


# ===========================================================================
# 5. Mixed-estate safety -- a pre-F063 bronze release must not break the build
# ===========================================================================
def test_a_pre_f063_bronze_release_still_builds_the_full_contract():
    """Bronze objects written by the 15-series extractor carry none of the new legs."""
    old = _bronze()
    old = old[old["series_name"].isin([
        "urea_e_europe_bulk_spot_usd_mt", "dap_spot_usd_mt", "potassium_chloride_std_usd_mt",
        "natural_gas_us_usd_mmbtu", "natural_gas_europe_usd_mmbtu", "phosphate_rock_usd_mt",
        "crude_oil_brent_usd_bbl", "soybeans_usd_mt", "soybean_oil_usd_mt", "soybean_meal_usd_mt",
        "palm_oil_usd_mt", "sugar_world_usd_kg", "wheat_us_hrw_usd_mt", "wheat_us_srw_usd_mt",
        "rapeseed_oil_usd_mt",
    ])]
    df = build_silver([old])
    assert list(df.columns) == SILVER_COLUMNS
    for col in _F063_VALUE_COLUMNS:
        assert df[col].isna().all(), col
    assert df.iloc[0]["urea_usd_mt"] == pytest.approx(100.0)


def test_a_newer_wide_release_wins_the_dedup_against_an_older_narrow_one():
    """One re-extracted release backfills every new column, because WB restates 1960+ in full."""
    df = build_silver([
        _bronze(release="2026M05", values={"urea_e_europe_bulk_spot_usd_mt": 111.0}),
        _bronze(release="2026M07", values={"urea_e_europe_bulk_spot_usd_mt": 222.0}),
    ])
    assert len(df) == 1
    assert df.iloc[0]["urea_usd_mt"] == pytest.approx(222.0)
    assert df.iloc[0]["latest_release_ym"] == "2026M07"


# ===========================================================================
# 6. Card <-> contract agreement (the GN-1 consumers are documented, not implied)
# ===========================================================================
def test_every_new_column_is_carded_with_a_unit_and_a_named_consumer():
    from leviathan.graphrag.numbers.registry import load_registry as load_numbers_registry

    ts = load_numbers_registry().get("silver_pink_sheet")
    for col in _F063_VALUE_COLUMNS:
        assert col in ts.metrics, f"{col} is physical but not carded"
        m = ts.metrics[col]
        assert m.unit, col
        # every desc attributes the source and names the node/consumer the leg prices
        assert m.desc and "WB" in m.desc, col
        assert len(m.desc) > 40, col
    for col in _F063_VALUE_COLUMNS:
        assert f"{col}_zscore_5yr" in ts.metrics, col


def test_card_notes_retract_the_stale_uncovered_claim():
    """The pre-F063 notes told the agent there were NO corn/coffee/cotton/rice/cocoa columns.

    All five now exist; a card that keeps declining on them is worse than one that never had them.
    """
    from leviathan.graphrag.numbers.registry import load_registry as load_numbers_registry

    notes = load_numbers_registry().get("silver_pink_sheet").notes
    assert "there are NO corn, coffee, cotton, rice or cocoa price" not in notes
    # and the honest replacements are present
    assert "DISCONTINUED" in notes
    assert "olive oil" in notes.lower()
    assert "not exchange settle" in notes.lower() or "NOT exchange settlement" in notes


# ── OPTION A (owner-ratified 2026-08-20): no dispersion -> no z ──────────────────────────────────
def test_a_flat_run_longer_than_the_window_yields_null_z_not_zero():
    """The phosphate-rock class, reconstructed: WB pinned the price at 44.0 for 102 consecutive
    months (1999-03..2007-08), longer than the 60-month window, so 43 rolling windows divided 0/0
    and the published value depended on the numpy build (live held 0.0, a recompute NaN). The
    epsilon guard makes the column deterministic and honest: a constant window has no dispersion,
    so it has no z. MEASURED live change surface at ratification: exactly 43 months, one column
    (2004-02..2007-08); potassium's 138-month run is masked by its history floor but is now
    structurally safe too."""
    import pandas as pd
    from leviathan.transforms.bronze_to_silver import pink_sheet as ps

    n = 130
    dates = pd.date_range("2000-01-01", periods=n, freq="MS")
    flat = pd.Series([44.0] * n)                      # a run longer than the 60-month window
    varying = pd.Series([100.0 + (i % 7) for i in range(n)])
    for series, expect_null_in_run in ((flat, True), (varying, False)):
        roll = series.rolling(ps._ZSCORE_WINDOW, min_periods=ps._ZSCORE_MIN_PERIODS)
        std = roll.std().where(roll.std() > 1e-9)     # the shipped guard's exact form
        z = (series - roll.mean()) / std
        window_full = z.iloc[ps._ZSCORE_WINDOW:]
        if expect_null_in_run:
            assert window_full.isna().all(), "a dispersionless window must yield NULL, never 0.0"
        else:
            assert window_full.notna().all(), "a varying series must be untouched by the guard"
