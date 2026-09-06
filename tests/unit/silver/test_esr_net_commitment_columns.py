"""SILVER-F030 BF-W2: the five FAS net-commitment columns, bronze and silver.

The FAS ``allCountries`` payload replaced the dead ``changes`` field with five net-commitment
fields in August 2026 -- the exact set the bronze schema-drift WARN had been naming on every
(commodity, market_year) partition. This suite pins the promotion of those five through both ESR
transforms: the names, the widths, INV-4 nullability, the unconditional 18-column emission, and
the TAIL placement that the registered-partition self-heal depends on.

Every test's docstring names the measured fact it pins, because several of these look like style
choices and are not: float64 vs float32, tail vs mid-list, and "create the column as NaN" vs
"omit the column" each have a specific incident behind them.

Pure Python -- no S3/AWS. (These pins live in tests/unit/silver/ rather than beside the incumbent
transform suites because the two files tests/unit/test_transforms_esr_{raw,silver}.py are outside
this lane's write allowlist; two re-aims they still need are handed to the operator as diffs.)
"""
from __future__ import annotations

import datetime
import json
import logging
import pathlib

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver import usda_esr as S
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver
from leviathan.transforms.raw_to_bronze import usda_esr as B
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

COMMODITY_CODE = 401
MARKET_YEAR = 2025
AS_OF_DATE = "20260903"
INGEST_DATE = "2026-09-03"

_RAW_LOGGER = "leviathan.transforms.raw_to_bronze.usda_esr"

# The ADR's frozen order (reports/silver_readiness/R2_esr/F030_esr_adr.json,
# target_additive_schema_bf_w2). Both transforms and the contract must agree with it.
API_TO_BRONZE = [
    ("accumulatedExports", "accumulated_exports"),
    ("currentMYNetSales", "current_my_net_sales"),
    ("currentMYTotalCommitment", "current_my_total_commitment"),
    ("nextMYOutstandingSales", "next_my_outstanding_sales"),
    ("nextMYNetSales", "next_my_net_sales"),
]
FIVE_API = [a for a, _ in API_TO_BRONZE]
FIVE_BRONZE = [b for _, b in API_TO_BRONZE]
FIVE_SILVER = [f"{b}_1000mt" for b in FIVE_BRONZE]

# The 13 columns the silver transform emitted before this lane, in order.
INCUMBENT_SILVER_COLS = [
    "commodity_code", "commodity_name", "market_year", "country_code", "week_ending_date",
    "outstanding_sales_1000mt", "weekly_exports_1000mt", "gross_new_sales_1000mt",
    "changes_1000mt", "source_unit_id", "as_of_date", "ingest_date", "source",
]

# A pre-promotion record: everything the old adapter saw, none of the five.
_OLD_RECORD = {
    "commodityCode": 401, "countryCode": 351, "marketYear": 2025,
    "weekEndingDate": "2025-10-02", "netSales": 125000.5, "outstandingSales": 3200000.0,
    "weeklyExports": 85000.25, "cumulativeExports": 250000.0, "grossNewSales": 140000.5,
    "cancelations": 15000.0, "changes": 500.0, "unitId": 1,
}
# A post-2026-08 record: the same payload plus the five, at distinguishable values.
_NEW_VALUES = {
    "accumulatedExports": 250000.0,
    "currentMYNetSales": 125000.5,
    "currentMYTotalCommitment": 1250000.0,
    "nextMYOutstandingSales": 40000.0,
    "nextMYNetSales": 15000.0,
}
_NEW_RECORD = {**_OLD_RECORD, **_NEW_VALUES}


def _bronze(records: list[dict]) -> pd.DataFrame:
    return transform_esr_json_to_bronze(
        json.dumps(records).encode(), COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
    )


def _bronze_frame(with_five: bool, as_of: str = AS_OF_DATE) -> pd.DataFrame:
    """A two-row bronze frame in the shape the parquet loader returns.

    ``with_five=False`` is the HISTORICAL vintage: a bronze object written by the pre-promotion
    transform, which is what every as_of before the re-bronze actually holds.
    """
    data = {
        "commodity_code": pd.array([401, 401], dtype="Int16"),
        "country_code": pd.array([1220, 351], dtype="Int16"),
        "week_ending_date": [datetime.date(2024, 9, 12), datetime.date(2024, 9, 19)],
        "outstanding_sales": pd.array([50000.0, 120000.0], dtype="float32"),
        "weekly_exports": pd.array([25000.0, 60000.0], dtype="float32"),
        "gross_new_sales": pd.array([30000.0, 80000.0], dtype="float32"),
        "changes": pd.array([0.0, 500.0], dtype="float32"),
        "unit_id": pd.array([1, 1], dtype="Int16"),
        "as_of_date": [as_of, as_of],
        "ingest_date": ["2026-09-03", "2026-09-03"],
        "source": ["usda_esr", "usda_esr"],
    }
    if with_five:
        for col in FIVE_BRONZE:
            # row 0 populated, row 1 NULL -- so null-propagation is measured in the same frame.
            data[col] = pd.array([1_250_000.0, float("nan")], dtype="float64")
    return pd.DataFrame(data)


# ===========================================================================
# BRONZE
# ===========================================================================
class TestBronzeNetCommitmentFields:
    def test_all_five_present_are_typed_and_named(self):
        """The five camelCase API keys become the five snake_case bronze columns at float64,
        carrying the payload's MT values UNCONVERTED (bronze stores the API's native units; the
        /1000 is silver's job)."""
        df = _bronze([_NEW_RECORD])
        for api, bronze in API_TO_BRONZE:
            assert bronze in df.columns, bronze
            assert str(df[bronze].dtype) == "float64", bronze
            assert float(df[bronze].iloc[0]) == _NEW_VALUES[api], bronze

    def test_the_five_are_float64_while_the_incumbents_stay_float32(self):
        """Measured incident, not taste: a parquet FLOAT under a Glue `double` is the
        HIVE_BAD_DATA "type DOUBLE ... incompatible with type real" class the estate ate on
        silver_food_cpi. The ADR declares these five `double`, so they are born float64. Widening
        the incumbent four is the separate SILVER-F031 rewrite and is NOT in this lane."""
        df = _bronze([_NEW_RECORD])
        assert {str(df[c].dtype) for c in FIVE_BRONZE} == {"float64"}
        for col in ("outstanding_sales", "weekly_exports", "gross_new_sales", "changes"):
            assert str(df[col].dtype) == "float32", col

    def test_absent_fields_stay_null_never_zero(self):
        """INV-4, five more times. A payload with NONE of the five still yields all five columns,
        all-NaN. Absent must never become 0.0: a synthesized zero commitment is indistinguishable
        from a real one. The column must EXIST because the value census IGNORES files where a
        column is missing -- an absent column measures 1.000 non-null over nothing."""
        df = _bronze([_OLD_RECORD])
        for col in FIVE_BRONZE:
            assert col in df.columns, col
            assert bool(df[col].isna().all()), col
            assert int((df[col] == 0.0).sum()) == 0, col

    def test_mixed_presence_preserves_the_null(self):
        """One record with the fields and one without: exactly one NaN per column, and the
        present value survives intact."""
        df = _bronze([_NEW_RECORD, _OLD_RECORD])
        for api, bronze in API_TO_BRONZE:
            assert int(df[bronze].isna().sum()) == 1, bronze
            assert float(df[bronze].dropna().iloc[0]) == _NEW_VALUES[api], bronze

    def test_explicit_json_null_stays_null(self):
        """An explicit `"currentMYNetSales": null` in the payload is a reported absence, not a
        zero -- pd.to_numeric must leave it NaN."""
        df = _bronze([{**_NEW_RECORD, "currentMYNetSales": None}])
        assert bool(df["current_my_net_sales"].isna().all())
        assert int((df["current_my_net_sales"] == 0.0).sum()) == 0

    def test_the_field_map_appends_the_five_at_the_tail(self):
        """The map diff is a pure tail append after `unitId`, so no incumbent bronze column
        changes position and the `expected` projection order is unchanged for them."""
        names = list(B._FIELD_MAP)
        assert names[-5:] == FIVE_API
        assert names.index("unitId") == len(names) - 6

    def test_every_nullable_measure_rides_one_implementation(self):
        """INV-4 has ONE implementation (_ensure_nullable) and six call sites, so the law cannot
        drift between `changes` and the five."""
        assert B._NULLABLE_MEASURE_COLS == ("changes", *FIVE_BRONZE)
        assert set(B._FLOAT64_COLS) == set(FIVE_BRONZE)
        assert not (set(B._FLOAT64_COLS) & set(B._FLOAT_COLS))


class TestBronzeSchemaDriftContract:
    def test_the_five_no_longer_drift(self, caplog):
        """The point of promoting them into _FIELD_MAP: the WARN is
        `sorted(set(df.columns) - set(_FIELD_MAP))`, so a payload carrying all five and no other
        unknown key now emits ZERO schema-drift warnings. This WARN has been firing on every ESR
        partition since 2026-08."""
        with caplog.at_level(logging.WARNING, logger=_RAW_LOGGER):
            _bronze([_NEW_RECORD])
        drift = [r for r in caplog.records if "schema drift" in r.getMessage().lower()]
        assert drift == [], [r.getMessage() for r in drift]

    def test_a_sixth_unknown_field_still_warns_and_names_it(self, caplog):
        """The INV-1 contract for any FUTURE unknown field is untouched. Without this pin, the
        test above could be satisfied by simply breaking the WARN."""
        with caplog.at_level(logging.WARNING, logger=_RAW_LOGGER):
            df = _bronze([{**_NEW_RECORD, "someNewSixthField": 42.0}])
        assert "someNewSixthField" not in df.columns  # unknowns are still not promoted
        drift = [r.getMessage() for r in caplog.records
                 if "schema drift" in r.getMessage().lower()]
        assert len(drift) == 1, drift
        assert "someNewSixthField" in drift[0]


# ===========================================================================
# SILVER
# ===========================================================================
class TestSilverNetCommitmentDerivation:
    def test_divided_by_1000_at_float64(self):
        """1,250,000 MT -> 1250.0 in the *_1000mt column, float64 end to end."""
        silver = transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR)
        for col in FIVE_SILVER:
            assert str(silver[col].dtype) == "float64", col
            assert abs(float(silver[col].iloc[0]) - 1250.0) < 1e-9, col

    def test_null_bronze_stays_null_silver(self):
        """NaN * 0.001 = NaN, so a null bronze value propagates with no special case -- the same
        mechanism `changes` -> `changes_1000mt` already uses. Never 0.0."""
        silver = transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR)
        for col in FIVE_SILVER:
            assert bool(pd.isna(silver[col].iloc[1])), col
            assert int((silver[col] == 0.0).sum()) == 0, col

    def test_absent_bronze_columns_still_emit_all_five_as_null(self):
        """THE HISTORICAL-VINTAGE CASE. A pre-promotion 12-column bronze frame must still yield an
        18-column silver frame with the five all-NaN.

        Measured reason: value_census.census_column keeps only files where the column is present
        (`present = [s for s in file_stats if s is not None]`). A column ABSENT from old-vintage
        files reads nonnull_fraction=1.000 over the sample -- a gate that passes because it is
        looking at nothing. Emitting NULL is what makes the measurement real."""
        silver = transform_esr_bronze_to_silver(_bronze_frame(False, "20260806"), MARKET_YEAR)
        assert len(silver.columns) == 18
        for col in FIVE_SILVER:
            assert col in silver.columns, col
            assert bool(silver[col].isna().all()), col
            assert int((silver[col] == 0.0).sum()) == 0, col

    def test_the_emitted_column_list_is_the_same_18_for_every_vintage(self):
        """The schema must not depend on which bronze vintage produced the frame: the producer
        pd.concats per-file frames in as_completed() order, so a vintage-dependent column set would
        make the union's column ORDER depend on which S3 read finished first (measured unstable
        under mid-list emission). A fixed list removes the hazard."""
        new_cols = list(transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR).columns)
        old = transform_esr_bronze_to_silver(_bronze_frame(False, "20260806"), MARKET_YEAR)
        assert list(old.columns) == new_cols
        forward = pd.concat(
            [old, transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR)],
            ignore_index=True)
        backward = pd.concat(
            [transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR), old],
            ignore_index=True)
        assert list(forward.columns) == list(backward.columns) == new_cols

    def test_the_exact_18_column_order(self):
        """THE INV-2 ADDITIVE PIN AND THE is_schema_widen PRECONDITION IN ONE ASSERTION.

        The 13 incumbent names in their incumbent positions, then the five in ADR order. No
        existing reader's column index, name or type moves; and the catalog widen that follows is
        a pure TRAILING append, which is the only shape catalog.is_schema_widen admits."""
        silver = transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR)
        assert list(silver.columns) == INCUMBENT_SILVER_COLS + FIVE_SILVER

    def test_the_five_are_strictly_after_source(self):
        """Measured: is_schema_widen(live -> five appended at the TAIL) = True, while
        is_schema_widen(live -> the same five INSERTED at position 9) = False. Mid-list, the
        narrow self-heal declines and EVERY already-registered partition fails closed on the next
        canonical promote -- for the whole family, not just the new columns. Glue's ADD COLUMNS
        appends at the tail, so tail is also the only placement that keeps parquet order ==
        catalog order."""
        cols = list(transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR).columns)
        assert max(cols.index(c) for c in INCUMBENT_SILVER_COLS) < min(
            cols.index(c) for c in FIVE_SILVER)
        assert cols.index("source") < min(cols.index(c) for c in FIVE_SILVER)

    def test_a_skipped_only_frame_is_empty_but_carries_all_18(self):
        """A per-code bronze object for one of the 13 non-mass codes transforms to ZERO rows. The
        producer skips empty results, but the frame must still be well-formed at the full width --
        otherwise the shape depends on which codes a run happened to see."""
        frame = _bronze_frame(True)
        frame["commodity_code"] = pd.array([1601, 1601], dtype="Int16")
        frame["unit_id"] = pd.array([3, 3], dtype="Int16")
        silver = transform_esr_bronze_to_silver(frame, MARKET_YEAR)
        assert silver.empty
        assert list(silver.columns) == INCUMBENT_SILVER_COLS + FIVE_SILVER

    def test_the_additive_set_is_kept_separate_from_the_incumbent_quantities(self):
        """Same /1000 derivation, different ORDER and different width -- so the two lists must
        stay disjoint module constants rather than one merged list."""
        assert S._ADDITIVE_QUANTITY_COLS == FIVE_BRONZE
        assert not (set(S._ADDITIVE_QUANTITY_COLS) & set(S._QUANTITY_COLS))

    def test_the_incumbent_four_keep_their_float32_width(self):
        """INV-2 additive means the five are ADDED, not that anything existing is re-typed. The
        float32 -> float64 widen of the incumbent quantities is SILVER-F031, a data rewrite that
        is deliberately not in this change."""
        silver = transform_esr_bronze_to_silver(_bronze_frame(True), MARKET_YEAR)
        for col in ("outstanding_sales_1000mt", "weekly_exports_1000mt",
                    "gross_new_sales_1000mt", "changes_1000mt"):
            assert str(silver[col].dtype) == "float32", col


@pytest.mark.parametrize("bronze_col,silver_col", list(zip(FIVE_BRONZE, FIVE_SILVER)))
def test_every_bronze_name_maps_to_its_adr_silver_name(bronze_col, silver_col):
    """The silver names are the frozen ADR's, not this lane's: the bronze name plus `_1000mt`."""
    assert f"{bronze_col}_1000mt" == silver_col
    assert bronze_col in B._FIELD_MAP.values()


# ===========================================================================
# The two fixtures, side by side: the pre- and post-2026-08 payload shapes.
# ===========================================================================
_FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures"


class TestBothPayloadShapesAreFixtureBacked:
    """esr_sample_netcommitment.json is a POST-2026-08 payload; esr_sample.json is the pre-2026-08
    one and is deliberately left byte-for-byte untouched, so the "before" and "after" cases are
    both backed by a file on disk rather than by two dict literals that could drift apart.
    """

    def test_the_incumbent_fixture_is_untouched_and_carries_no_new_field(self):
        """The old fixture must keep describing the OLD world. If this file ever gains the five,
        the pre-promotion regression cases stop testing anything -- including
        tests/unit/test_transforms_esr_raw.py::test_changes_null_in_fixture_stays_null, which
        expects exactly 3 NaN over 5 rows."""
        old = json.loads((_FIXTURES / "esr_sample.json").read_text(encoding="utf-8"))
        assert len(old) == 5
        assert all(not (set(FIVE_API) & set(rec)) for rec in old)
        df = transform_esr_json_to_bronze(
            (_FIXTURES / "esr_sample.json").read_bytes(),
            COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE)
        assert int(df["changes"].isna().sum()) == 3          # unchanged by this lane
        for col in FIVE_BRONZE:                              # ...and all five exist, all-NULL
            assert bool(df[col].isna().all()), col
            assert int((df[col] == 0.0).sum()) == 0, col

    def test_the_new_fixture_has_the_post_2026_08_shape(self):
        """MEASURED SOURCE SHAPE, not an invention: after August 2026 the allCountries payload
        carries the five and carries NO `changes` key at all (immutable-raw proof: 0/6863 records
        of as_of=20260712+ for commodity_code=101 hold a changes-like key). So the fixture holds
        no `changes`, and `changes` must read all-NULL through the transform -- which is exactly
        why changes_1000mt left the governed value set on 2026-09-04."""
        recs = json.loads((_FIXTURES / "esr_sample_netcommitment.json").read_text(encoding="utf-8"))
        assert len(recs) == 5
        assert all("changes" not in rec for rec in recs)
        df = transform_esr_json_to_bronze(
            (_FIXTURES / "esr_sample_netcommitment.json").read_bytes(),
            COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE)
        assert bool(df["changes"].isna().all())
        # row 2 omits all five (a country/week the API did not report them for -- the TAIL case,
        # written down per row rather than averaged); row 4 sends currentMYNetSales as an explicit
        # JSON null. Both stay NULL, neither becomes 0.0.
        assert int(df["accumulated_exports"].isna().sum()) == 1
        assert int(df["current_my_net_sales"].isna().sum()) == 2
        # THE OTHER HALF OF INV-4, which an "all nulls" test alone would miss: a REAL reported
        # zero must survive AS a zero. The fixture sends nextMYOutstandingSales/nextMYNetSales as
        # 0.0 on two rows (a marketing year with no new-crop business yet), and those two zeros
        # must still be there -- the law is "never SYNTHESIZE a zero", not "never hold one".
        for col in ("next_my_outstanding_sales", "next_my_net_sales"):
            assert int((df[col] == 0.0).sum()) == 2, col
        for col in ("accumulated_exports", "current_my_net_sales", "current_my_total_commitment"):
            assert int((df[col] == 0.0).sum()) == 0, col

    def test_the_new_fixture_emits_zero_schema_drift(self, caplog):
        """The end-to-end statement of the whole bronze half: a REAL post-promotion payload now
        passes through with no unknown-field WARN at all."""
        with caplog.at_level(logging.WARNING, logger=_RAW_LOGGER):
            transform_esr_json_to_bronze(
                (_FIXTURES / "esr_sample_netcommitment.json").read_bytes(),
                COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE)
        assert [r.getMessage() for r in caplog.records
                if "schema drift" in r.getMessage().lower()] == []

    def test_the_new_fixture_carries_through_to_18_silver_columns(self):
        """Fixture -> bronze -> silver in one pass, so the two halves are pinned together and not
        only against hand-built frames."""
        bronze = transform_esr_json_to_bronze(
            (_FIXTURES / "esr_sample_netcommitment.json").read_bytes(),
            COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE)
        silver = transform_esr_bronze_to_silver(bronze, MARKET_YEAR)
        assert list(silver.columns) == INCUMBENT_SILVER_COLS + FIVE_SILVER
        # 1,250,000 MT -> 1250.0, and the omitted row stays NULL rather than 0.0.
        assert abs(float(silver["current_my_total_commitment_1000mt"].iloc[0]) - 1250.0) < 1e-9
        assert int(silver["current_my_total_commitment_1000mt"].isna().sum()) == 1
