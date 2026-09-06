"""Unit tests for the ESR bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
The transform function is called with pre-built DataFrames that mimic what the
bronze Parquet loader returns from real S3 data (probe-verified 2026-05-24).

Actual bronze schema (11 cols):
  commodity_code (Int16), country_code (Int16), week_ending_date (date),
  outstanding_sales (float32), weekly_exports (float32),
  gross_new_sales (float32), unit_id (Int16), changes (float32),
  as_of_date (str), ingest_date (str), source (str)

Silver adds: commodity_name (str), market_year (Int16)
Silver renames quantity cols with _1000mt suffix and renames unit_id → source_unit_id.
"""
from __future__ import annotations

import datetime
import logging

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver import usda_esr as T
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

from jobs.ingest import fetch_usda_esr as F

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MARKET_YEAR = 2024


def _make_bronze_df(**overrides) -> pd.DataFrame:
    """Return a minimal two-row bronze ESR DataFrame."""
    data = {
        "commodity_code":   pd.array([401, 401], dtype="Int16"),
        "country_code":     pd.array([1220, 351], dtype="Int16"),
        "week_ending_date": [datetime.date(2024, 9, 12), datetime.date(2024, 9, 19)],
        "outstanding_sales": pd.array([50000.0, 120000.0], dtype="float32"),
        "weekly_exports":    pd.array([25000.0, 60000.0], dtype="float32"),
        "gross_new_sales":   pd.array([30000.0, 80000.0], dtype="float32"),
        "changes":           pd.array([0.0, 500.0], dtype="float32"),
        "unit_id":           pd.array([1, 1], dtype="Int16"),
        "as_of_date":        ["20260524", "20260524"],
        "ingest_date":       ["2026-05-24", "2026-05-24"],
        "source":            ["usda_esr", "usda_esr"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_dataframe(self) -> None:
        df = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert isinstance(df, pd.DataFrame)

    def test_row_count_preserved(self) -> None:
        bronze = _make_bronze_df()
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert len(silver) == len(bronze)

    def test_commodity_name_corn(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert (silver["commodity_name"] == "corn_cbot").all()

    def test_market_year_column_added(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "market_year" in silver.columns
        assert (silver["market_year"] == MARKET_YEAR).all()

    def test_unit_conversion_weekly_exports(self) -> None:
        """25,000 MT ÷ 1000 = 25.0 (1000 MT)."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "weekly_exports_1000mt" in silver.columns
        assert abs(float(silver["weekly_exports_1000mt"].iloc[0]) - 25.0) < 0.01

    def test_unit_conversion_outstanding_sales(self) -> None:
        """50,000 MT ÷ 1000 = 50.0 (1000 MT)."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert abs(float(silver["outstanding_sales_1000mt"].iloc[0]) - 50.0) < 0.01

    def test_original_quantity_cols_dropped(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        for col in ("outstanding_sales", "weekly_exports", "gross_new_sales", "changes"):
            assert col not in silver.columns

    def test_unit_id_renamed_to_source_unit_id(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert "unit_id" not in silver.columns
        assert "source_unit_id" in silver.columns

    def test_1000mt_columns_have_their_declared_widths(self) -> None:
        """RE-ANCHORED 2026-09-04 (SILVER-F030 BF-W2). MEASURED FIRST: this test was GREEN at HEAD
        (`git archive HEAD` into a scratch tree -> 76 passed for this file, 17 for the bronze
        sibling), so the net-commitment lane is what turned it red and the re-anchor is deliberate,
        not an inherited failure.

        "every *_1000mt column is float32" stopped being true when the five net-commitment columns
        landed. The frozen ADR (reports/silver_readiness/R2_esr/F030_esr_adr.json,
        target_additive_schema_bf_w2) declares them Glue `double`, and a parquet FLOAT under a
        `double` catalog is the `HIVE_BAD_DATA: Malformed Parquet file ... type DOUBLE ...
        incompatible with type real` class the estate already ate on silver_food_cpi -- so they are
        float64 end to end. The incumbent four stay float32: widening THEM is the separate
        SILVER-F031 data rewrite already sitting in both contracts' drift_summary, deliberately not
        in this lane. The pin is kept as a per-column WIDTH assertion rather than deleted, and it
        is now stronger than the blanket version: it names which width each column owes."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        for col in ("outstanding_sales_1000mt", "weekly_exports_1000mt",
                    "gross_new_sales_1000mt", "changes_1000mt"):
            assert silver[col].dtype == "float32", f"{col} should be float32"
        for col in T._ADDITIVE_QUANTITY_COLS:
            assert silver[f"{col}_1000mt"].dtype == "float64", f"{col}_1000mt should be float64"
        # and no *_1000mt column escapes the two declared widths.
        for col in silver.columns:
            if col.endswith("_1000mt"):
                assert silver[col].dtype in ("float32", "float64"), col

    def test_output_column_order(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        cols = list(silver.columns)
        assert cols[0] == "commodity_code"
        assert cols[1] == "commodity_name"
        assert cols[2] == "market_year"
        assert cols[3] == "country_code"
        assert cols[4] == "week_ending_date"

    def test_metadata_cols_preserved(self) -> None:
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), MARKET_YEAR)
        assert silver["as_of_date"].iloc[0] == "20260524"
        assert silver["ingest_date"].iloc[0] == "2026-05-24"
        assert silver["source"].iloc[0] == "usda_esr"


# ---------------------------------------------------------------------------
# Commodity name mapping
# ---------------------------------------------------------------------------

class TestCommodityNameMapping:
    @pytest.mark.parametrize("code,expected_name", [
        (101, "hard_red_winter_wheat_kcbt"),
        (102, "soft_red_winter_wheat_cbot"),
        (103, "hard_red_spring_wheat_mgex"),
        (104, "white_wheat"),
        (107, "all_wheat"),
        (401, "corn_cbot"),
        (701, "grain_sorghum"),
        (801, "soybeans_cbot"),
        (901, "soybean_meal_cbot"),
        (902, "soybean_oil_cbot"),
    ])
    def test_known_code_maps_correctly(self, code: int, expected_name: str) -> None:
        bronze = _make_bronze_df(
            commodity_code=pd.array([code], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([1000.0], dtype="float32"),
            weekly_exports=pd.array([500.0], dtype="float32"),
            gross_new_sales=pd.array([600.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["commodity_name"].iloc[0] == expected_name

    def test_unknown_code_becomes_unknown(self) -> None:
        """Commodity code not in the mapping → 'unknown' (no raise)."""
        bronze = _make_bronze_df(
            commodity_code=pd.array([999], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([1000.0], dtype="float32"),
            weekly_exports=pd.array([500.0], dtype="float32"),
            gross_new_sales=pd.array([600.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["commodity_name"].iloc[0] == "unknown"


# ---------------------------------------------------------------------------
# Unit conversion edge cases
# ---------------------------------------------------------------------------

class TestUnitConversion:
    def test_known_unit_id_applies_factor(self) -> None:
        """1,000,000 MT × 0.001 = 1,000.0 (1000 MT)."""
        bronze = _make_bronze_df(
            weekly_exports=pd.array([1_000_000.0], dtype="float32"),
            commodity_code=pd.array([401], dtype="Int16"),
            country_code=pd.array([351], dtype="Int16"),
            week_ending_date=[datetime.date(2024, 9, 12)],
            outstanding_sales=pd.array([0.0], dtype="float32"),
            gross_new_sales=pd.array([0.0], dtype="float32"),
            changes=pd.array([0.0], dtype="float32"),
            unit_id=pd.array([1], dtype="Int16"),
            as_of_date=["20260524"],
            ingest_date=["2026-05-24"],
            source=["usda_esr"],
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert abs(float(silver["weekly_exports_1000mt"].iloc[0]) - 1000.0) < 0.1

    def test_unknown_unit_id_raises(self) -> None:
        """unit_id not in _UNIT_TO_1000MT_FACTOR must raise ValueError."""
        bronze = _make_bronze_df(
            unit_id=pd.array([99, 99], dtype="Int16"),
        )
        with pytest.raises(ValueError, match="unrecognised unit_id"):
            transform_esr_bronze_to_silver(bronze, MARKET_YEAR)


# ---------------------------------------------------------------------------
# Null / empty handling
# ---------------------------------------------------------------------------

class TestNullHandling:
    def test_null_week_ending_date_rows_dropped(self) -> None:
        bronze = _make_bronze_df()
        bronze.loc[0, "week_ending_date"] = None
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert len(silver) == 1

    def test_missing_required_column_raises(self) -> None:
        bronze = _make_bronze_df().drop(columns=["unit_id"])
        with pytest.raises(ValueError, match="missing required columns"):
            transform_esr_bronze_to_silver(bronze, MARKET_YEAR)


# ---------------------------------------------------------------------------
# SILVER-F030 ADR: changes_1000mt is deprecated + never synthesized (INV-4)
# ---------------------------------------------------------------------------

class TestChangesNeverSynthesized:
    def test_null_bronze_changes_stays_null_in_silver(self) -> None:
        """A null bronze 'changes' propagates to a null 'changes_1000mt' -- never 0.0 (INV-4)."""
        import numpy as np
        bronze = _make_bronze_df(
            changes=pd.array([np.nan, 500.0], dtype="float32"),
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["changes_1000mt"].isna().sum() == 1
        # the present revision survives its unit conversion (500 MT -> 0.5 kMT).
        assert abs(float(silver["changes_1000mt"].dropna().iloc[0]) - 0.5) < 1e-6

    def test_all_null_changes_stays_all_null(self) -> None:
        import numpy as np
        bronze = _make_bronze_df(
            changes=pd.array([np.nan, np.nan], dtype="float32"),
        )
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert silver["changes_1000mt"].isna().all()
        assert (silver["changes_1000mt"] == 0.0).sum() == 0


# ---------------------------------------------------------------------------
# SILVER-F030 ADR: ending-year market-year convention (stored = FAS start year)
# ---------------------------------------------------------------------------

class TestMarketYearConvention:
    def test_stored_market_year_is_the_start_year_param(self) -> None:
        """The stored market_year is the FAS START year passed in; the numbers layer derives the
        ending-year label as market_year+1 (period_offset:+1). The transform never fabricates a
        next marketing year."""
        silver = transform_esr_bronze_to_silver(_make_bronze_df(), 2023)
        assert (silver["market_year"] == 2023).all()
        # no next-MY (2024) row is synthesized from the 2023 bronze frame.
        assert set(silver["market_year"].unique()) == {2023}

    def test_usda_grouping_codes_stay_source_faithful(self) -> None:
        """USDA grouping codes (all_wheat=107, grain_sorghum=701, white_wheat=104) are NOT contract
        slugs but the canonical transform still maps them (source-faithful); the esr_exports slug
        boundary is enforced downstream, not by dropping rows here."""
        for code, name in ((107, "all_wheat"), (701, "grain_sorghum"), (104, "white_wheat")):
            bronze = _make_bronze_df(
                commodity_code=pd.array([code, code], dtype="Int16"),
            )
            silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
            assert (silver["commodity_name"] == name).all()


# ---------------------------------------------------------------------------
# D-EC (2026-08-20) -- THE 44-CODE UNIVERSE.
#
# The fetcher now requests all 44 measured source codes. `silver_esr_compact`
# partitions BY commodity_name, so an unmapped code does not read "unknown" in a
# column -- every unmapped code collapses into ONE `commodity=unknown` partition
# object. These tests pin the two halves of the disposition: 21 new mass codes
# map to a slug, and the 13 non-mass codes are skipped IN WRITING.
# ---------------------------------------------------------------------------

# The 21 new unit_id=1 codes and the slug each one now carries.
_NEW_MASS_CODE_TO_SLUG: dict[int, str] = {
    105: "durum_wheat",
    106: "mixed_wheat",
    201: "wheat_products",
    301: "barley",
    501: "rye",
    601: "oats",
    1001: "flaxseed",
    1101: "linseed_oil",
    1110: "sunflower_oil",
    1201: "cottonseed",
    1202: "cottonseed_meal",
    1203: "cottonseed_oil",
    1498: "rough_rice_cbot",
    1499: "medium_short_rough_rice",
    1501: "long_grain_brown_rice",
    1502: "medium_short_brown_rice",
    1503: "long_grain_milled_rice",
    1504: "medium_short_milled_rice",
    1505: "all_rice",
    1701: "cattle_beef",
    1702: "hogs",
}

# The 13 codes that publish bales or piece counts, with the unit that refuses them.
_NON_MASS_CODES: tuple[int, ...] = (
    1301, 1401, 1402, 1403, 1404,                    # cotton lint, running bales
    1601, 1602, 1603, 1604, 1605, 1606, 1607, 1608,  # hides / skins / wet blues, pieces
)

_TRANSFORM_LOGGER = "leviathan.transforms.bronze_to_silver.usda_esr"


def _rows_for(code: int, unit_id: int = 1, n: int = 2) -> pd.DataFrame:
    """A bronze frame of *n* rows for ONE commodity code -- the real per-code file shape."""
    return _make_bronze_df(
        commodity_code=pd.array([code] * n, dtype="Int16"),
        country_code=pd.array([(351, 1220)[i % 2] for i in range(n)], dtype="Int16"),
        week_ending_date=[datetime.date(2024, 9, 12 + i) for i in range(n)],
        outstanding_sales=pd.array([1000.0] * n, dtype="float32"),
        weekly_exports=pd.array([500.0] * n, dtype="float32"),
        gross_new_sales=pd.array([600.0] * n, dtype="float32"),
        changes=pd.array([0.0] * n, dtype="float32"),
        unit_id=pd.array([unit_id] * n, dtype="Int16"),
        as_of_date=["20260820"] * n,
        ingest_date=["2026-08-20"] * n,
        source=["usda_esr"] * n,
    )


class TestFortyFourCodeDisposition:
    def test_every_code_in_the_measured_universe_is_mapped_or_written_off(self) -> None:
        """No third bucket: a code is a slug or a written refusal. This is the assertion that
        makes `commodity=unknown` unreachable for the universe the fetcher actually requests."""
        universe = set(F._TARGET_COMMODITY_CODES)
        assert len(universe) == 44
        mapped = set(T._COMMODITY_CODE_TO_NAME)
        skipped = set(T._NON_MASS_UNIT_CODES)
        assert not (universe - (mapped | skipped)), universe - (mapped | skipped)
        assert not (mapped & skipped), "a code cannot be both mapped and refused"

    def test_the_two_halves_are_31_and_13(self) -> None:
        assert len(T._COMMODITY_CODE_TO_NAME) == 31
        assert set(T._NON_MASS_UNIT_CODES) == set(_NON_MASS_CODES)

    def test_no_two_codes_share_a_slug(self) -> None:
        """silver_esr_compact writes one object per commodity_name, so two codes on one name
        merge two different USDA series into a single partition file."""
        names = list(T._COMMODITY_CODE_TO_NAME.values())
        assert len(set(names)) == len(names)

    @pytest.mark.parametrize("code,expected", sorted(_NEW_MASS_CODE_TO_SLUG.items()))
    def test_each_new_mass_code_maps_to_its_slug(self, code: int, expected: str) -> None:
        silver = transform_esr_bronze_to_silver(_rows_for(code), MARKET_YEAR)
        assert len(silver) == 2
        assert (silver["commodity_name"] == expected).all()

    def test_the_whole_mass_universe_produces_no_unknown_partition(self) -> None:
        """THE PARTITION TEST: run every mass code through in one frame and assert that
        'unknown' appears nowhere -- the defect this fix exists to prevent."""
        mass_codes = sorted(set(F._TARGET_COMMODITY_CODES) - set(T._NON_MASS_UNIT_CODES))
        frames = [_rows_for(code, n=1) for code in mass_codes]
        silver = transform_esr_bronze_to_silver(
            pd.concat(frames, ignore_index=True), MARKET_YEAR
        )
        assert len(silver) == len(mass_codes)
        assert "unknown" not in set(silver["commodity_name"])
        assert silver["commodity_name"].nunique() == len(mass_codes)


class TestNonMassCodesAreSkippedInWriting:
    @pytest.mark.parametrize("code", _NON_MASS_CODES)
    def test_each_non_mass_code_is_skipped_with_one_log_line(
        self, code: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A SKIP, never an exception: the fetcher requests all 44 codes every Thursday, so a
        raise here would error-log 13 codes on the live weekly chain forever."""
        unit_id = 2 if code < 1500 else 3
        with caplog.at_level(logging.INFO, logger=_TRANSFORM_LOGGER):
            silver = transform_esr_bronze_to_silver(_rows_for(code, unit_id=unit_id), MARKET_YEAR)
        assert silver.empty
        skips = [r for r in caplog.records if "SKIPPING commodity_code=%d" % code in r.getMessage()]
        assert len(skips) == 1, [r.getMessage() for r in caplog.records]
        assert T._NON_MASS_UNIT_CODES[code] in skips[0].getMessage()

    def test_a_skipped_only_frame_returns_an_empty_but_well_formed_silver(self) -> None:
        """Files are partitioned by code, so a skipped code's file yields ZERO rows. The batch
        producer skips empty results (`not result.empty`), so this must not raise and must not
        return a shapeless frame.

        RE-ANCHORED 2026-09-04 (SILVER-F030 BF-W2), measured green at HEAD before the re-anchor.
        The exact-list assertion is the lane's INV-2 additive pin AND the is_schema_widen
        precondition, so it is extended rather than loosened."""
        silver = transform_esr_bronze_to_silver(_rows_for(1601, unit_id=3), MARKET_YEAR)
        assert silver.empty
        assert list(silver.columns) == [
            "commodity_code", "commodity_name", "market_year", "country_code",
            "week_ending_date", "outstanding_sales_1000mt", "weekly_exports_1000mt",
            "gross_new_sales_1000mt", "changes_1000mt", "source_unit_id",
            "as_of_date", "ingest_date", "source",
            # SILVER-F030 BF-W2 (2026-09-04): the five net-commitment columns, emitted
            # UNCONDITIONALLY and strictly at the TAIL. Both facts are load-bearing --
            # unconditional because the value census IGNORES files where a column is absent (an
            # absent column measures 1.000 non-null over nothing), and TAIL because
            # catalog.is_schema_widen admits ONLY a trailing append, which is what lets the
            # compact producer self-heal the registered partition descriptors after the Glue
            # ADD COLUMNS. Mid-list, every partition fails closed on the next canonical promote.
            "accumulated_exports_1000mt", "current_my_net_sales_1000mt",
            "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
            "next_my_net_sales_1000mt",
        ]

    def test_mass_rows_survive_a_mixed_frame(self) -> None:
        mixed = pd.concat([_rows_for(401, n=2), _rows_for(1404, unit_id=2, n=2)], ignore_index=True)
        silver = transform_esr_bronze_to_silver(mixed, MARKET_YEAR)
        assert set(silver["commodity_name"]) == {"corn_cbot"}
        assert len(silver) == 2

    def test_an_unknown_unit_still_raises(self) -> None:
        """The skip is NARROW. Unknown-unit drift on a KEPT code stays fatal, exactly as before."""
        with pytest.raises(ValueError, match="unrecognised unit_id"):
            transform_esr_bronze_to_silver(_rows_for(401, unit_id=7), MARKET_YEAR)

    def test_an_unknown_unit_on_an_unmapped_code_still_raises(self) -> None:
        """A code that is neither mapped nor written off must NOT ride the skip path."""
        with pytest.raises(ValueError, match="unrecognised unit_id"):
            transform_esr_bronze_to_silver(_rows_for(9999, unit_id=7), MARKET_YEAR)

    @pytest.mark.parametrize("code", [1301, 1404, 1601, 1608])
    def test_a_written_off_code_arriving_as_metric_tonnes_raises(self, code: int) -> None:
        """UNIVERSE-DRIFT DETECTION. unit_id=1 on a code recorded as bales/pieces means USDA
        re-based the series: the written refusal has stopped describing reality and must be
        re-decided, not silently re-applied to data this schema COULD now represent."""
        with pytest.raises(ValueError, match="arrived with unit_id=1"):
            transform_esr_bronze_to_silver(_rows_for(code, unit_id=1), MARKET_YEAR)
