"""Unit tests for the USDA AMS GTR freight family (fixture-pinned, network-free).

Every fixture under ``tests/fixtures/ams_gtr/`` is a VERBATIM live capture taken on
2026-08-20 while this producer was built:

    soda_{id}.json                 40 most recent rows, ``$order={period} DESC``
    meta_{id}.json                 the publisher's own /api/views/{id}.json
    soda_2n8s-739j_dup_2022q3.json the measured null-versus-value duplicate
    GTRTable1.xlsx                 the full 297,236-byte spreadsheet, unmodified

One later capture, taken 2026-08-20 while closing the build review:

    soda_7spn-fbua_zero_2025w49.json
        The family's ONLY literal zero, with the two weeks either side.  Captured
        verbatim from
        ``/resource/7spn-fbua.json?$where=river_system_location like 'La Crosse%' AND
        date between '2025-11-18' and '2025-12-16'&$order=date`` (683 B, 5 rows).  It
        pins the measurement behind the zero rule in
        ``raw_to_bronze/ams_gtr.py::_null_zero_sentinels``: the reach is quoted through
        2025-11-25, publishes ``price_per_ton: "0"`` on 2025-12-02, and is then a
        genuine ABSENCE with no key at all for the rest of its seasonal ice closure.

No test here touches the network.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.storage.paths import (
    AMS_GTR_DATASETS,
    ams_gtr_dataset_prefix,
    bronze_ams_gtr_key,
    raw_ams_gtr_backfill_key,
    raw_ams_gtr_weekly_key,
    silver_ams_gtr_key,
)
from leviathan.transforms.bronze_to_silver.ams_gtr import (
    BASIS_GTR_THURSDAY,
    BASIS_GTR_THURSDAY_MONTH_END,
    BASIS_OBSERVED,
    BASIS_UKRAINE_ANNUAL,
    NATURAL_KEY,
    OUTPUT_COLUMNS,
    _first_thursday_after,
    _month_end,
    derive_knowledge_date,
    transform_gtr_bronze_to_silver,
)
from leviathan.transforms.raw_to_bronze.ams_gtr import (
    GTR_DATASETS,
    KNOWN_UNITS,
    REFUSED_DATASETS,
    UNIT_PCT_OF_TARIFF,
    UNIT_USD_PER_METRIC_TON,
    UNIT_USD_PER_TON,
    assert_soda_unit_declaration,
    get_dataset,
    soda_metadata_url,
    soda_resource_url,
    transform_gtr_ocean_weekly_xlsx_to_bronze,
    transform_gtr_soda_json_to_bronze,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ams_gtr"

AS_OF = "20260820"
INGEST = "2026-08-20"

SODA_DATASETS = [slug for slug, spec in GTR_DATASETS.items() if spec.channel == "soda"]


def _rows_fixture(dataset: str) -> bytes:
    return (FIXTURES / f"soda_{get_dataset(dataset).endpoint}.json").read_bytes()


def _meta_fixture(dataset: str) -> bytes:
    return (FIXTURES / f"meta_{get_dataset(dataset).endpoint}.json").read_bytes()


def _bronze(dataset: str) -> pd.DataFrame:
    return transform_gtr_soda_json_to_bronze(_rows_fixture(dataset), dataset, AS_OF, INGEST)


def _silver(dataset: str) -> pd.DataFrame:
    return transform_gtr_bronze_to_silver(_bronze(dataset), dataset)


# ---------------------------------------------------------------------------
# The family table itself
# ---------------------------------------------------------------------------

def test_dataset_slug_sets_agree_between_paths_and_transform():
    """paths.py keeps its own copy of the slug set so it stays dependency-free.

    A divergence would produce S3 keys the transform cannot read back, so the two
    are pinned equal here rather than trusted to stay in step.
    """
    assert set(GTR_DATASETS) == set(AMS_GTR_DATASETS)


def test_every_dataset_declares_a_known_unit():
    assert KNOWN_UNITS == {UNIT_USD_PER_METRIC_TON, UNIT_USD_PER_TON, UNIT_PCT_OF_TARIFF}
    for slug, spec in GTR_DATASETS.items():
        assert spec.unit in KNOWN_UNITS, slug
        assert spec.unit_declaration, slug
        assert spec.period_grain in {"weekly", "monthly", "quarterly"}, slug
        assert spec.channel in {"soda", "xlsx"}, slug


def test_the_index_twin_is_refused_in_writing():
    """8uye-ieij must stay a written refusal, not an absence.

    Its own column metadata says "($/metric ton)" while its values are the 2017=100
    index; a future reader who only sees an absent dataset could easily re-add it.
    """
    assert "8uye-ieij" in REFUSED_DATASETS
    reason = REFUSED_DATASETS["8uye-ieij"]
    assert "index" in reason.lower()
    assert "184.9733028222731" in reason  # the measurement that settles it
    assert "8uye-ieij" not in {spec.endpoint for spec in GTR_DATASETS.values()}


def test_soda_urls_are_built_for_soda_datasets_only():
    for slug in SODA_DATASETS:
        assert soda_resource_url(slug).endswith(f"{get_dataset(slug).endpoint}.json")
        assert "/api/views/" in soda_metadata_url(slug)
    with pytest.raises(ValueError, match="not soda"):
        soda_resource_url("ocean_weekly")


# ---------------------------------------------------------------------------
# Units, asserted from the publisher's own metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dataset", SODA_DATASETS)
def test_unit_is_asserted_from_the_sources_own_column_metadata(dataset):
    description = assert_soda_unit_declaration(_meta_fixture(dataset), dataset)
    assert get_dataset(dataset).unit_declaration.lower() in description.lower()


def test_unit_drift_raises_rather_than_publishing_a_restated_number():
    meta = json.loads(_meta_fixture("ukraine_ocean_quarterly"))
    for column in meta["columns"]:
        column["description"] = "Freight rate in some other unit entirely"
    with pytest.raises(ValueError, match="no longer declares"):
        assert_soda_unit_declaration(
            json.dumps(meta).encode(), "ukraine_ocean_quarterly"
        )


def test_barge_per_ton_takes_its_unit_from_the_column_not_the_dataset_blurb():
    """The source contradicts itself; the column description is the authority.

    ``7spn-fbua``'s dataset description opens "Weekly barge rates (percent of tariff)"
    -- copied from ``deqi-uken`` -- while its column says "Price Per Ton". Magnitude
    decides: a percent-of-tariff runs 600-800, these run 14-17.
    """
    meta = json.loads(_meta_fixture("barge_per_ton"))
    assert "percent of tariff" in (meta.get("description") or "").lower()

    spec = get_dataset("barge_per_ton")
    assert spec.unit == UNIT_USD_PER_TON

    quoted = _silver("barge_per_ton")["rate"].dropna()
    assert not quoted.empty
    assert quoted.max() < 200, "a USD/ton barge rate cannot reach percent-of-tariff scale"

    pct = _silver("barge_pct_tariff")["rate"].dropna()
    assert pct.min() > 200, "a percent-of-tariff rate is an order of magnitude larger"


# ---------------------------------------------------------------------------
# SODA -> bronze -> silver
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dataset", SODA_DATASETS)
def test_soda_roundtrip_produces_the_contract_columns(dataset):
    silver = _silver(dataset)
    assert list(silver.columns) == OUTPUT_COLUMNS
    assert not silver.empty
    assert (silver["dataset"] == dataset).all()
    assert (silver["unit"] == get_dataset(dataset).unit).all()
    assert (silver["period_grain"] == get_dataset(dataset).period_grain).all()
    assert silver["period_date"].notna().all()
    assert silver["route_or_reach"].notna().all()
    assert (silver["as_of_date"] == AS_OF).all()


def test_forward_curves_carry_their_offset_and_the_month_they_apply_to():
    one = _silver("barge_fwd_1m")
    three = _silver("barge_fwd_3m")
    assert (one["forward_month_offset"] == 1).all()
    assert (three["forward_month_offset"] == 3).all()
    assert one["rate_month"].notna().all()
    assert three["rate_month"].notna().all()
    # The spot leg is offset 0 and carries no forward month.
    spot = _silver("barge_pct_tariff")
    assert (spot["forward_month_offset"] == 0).all()
    assert spot["rate_month"].isna().all()


def test_ukraine_leg_keeps_commodity_and_vessel_size_on_the_key():
    silver = _silver("ukraine_ocean_quarterly")
    assert silver["commodity"].notna().all()
    assert silver["vessel_size"].notna().all()
    assert set(silver["commodity"].unique()) <= {"Wheat", "Corn", "Soybeans"}
    # Other datasets leave both null -- they are not part of those keys.
    assert _silver("barge_pct_tariff")["commodity"].isna().all()


def test_ocean_monthly_melts_three_series_and_carries_the_vendor_attribution():
    silver = _silver("ocean_monthly")
    assert set(silver["series"].unique()) == {
        "gulf_to_japan", "pnw_to_japan", "gulf_pnw_spread"
    }
    assert silver["source_attribution"].str.contains("O'Neil").all()
    assert silver["source_attribution"].str.contains("U.S. Department of Agriculture").all()


def test_absent_rates_stay_null_and_are_never_zero():
    """INV-4. Socrata omits a null field entirely, so an absent rate arrives as a
    missing key rather than an explicit null -- the easiest kind to accidentally fill."""
    records = json.loads(_rows_fixture("ukraine_ocean_quarterly"))
    records[0].pop("rate", None)
    bronze = transform_gtr_soda_json_to_bronze(
        json.dumps(records).encode(), "ukraine_ocean_quarterly", AS_OF, INGEST
    )
    assert bronze["rate"].isna().any()
    silver = transform_gtr_bronze_to_silver(bronze, "ukraine_ocean_quarterly")
    assert silver["rate"].isna().any()
    assert not (silver["rate"].fillna(-1) == 0).any()


def test_a_source_side_literal_zero_is_refused_as_a_quote(caplog):
    """The one measured zero in the whole family, pinned from a verbatim live capture.

    ``7spn-fbua`` (2025-12-02, "La Crosse - Minneapolis") publishes ``price_per_ton: "0"``.
    The fixture holds the two weeks either side of it: the reach is quoted normally up to
    2025-11-25, carries the zero on 2025-12-02, and is then a genuine ABSENCE (no key at
    all) for the rest of its seasonal ice closure.  The zero is the same absence spelled
    with a digit, and unlike a NULL it would be silently averaged, min'd and plotted.
    """
    raw = (FIXTURES / "soda_7spn-fbua_zero_2025w49.json").read_bytes()
    records = json.loads(raw)
    assert len(records) == 5
    by_date = {r["date"][:10]: r for r in records}
    # the source really does say what this rule is written against
    assert by_date["2025-12-02"]["price_per_ton"] == "0"
    assert "price_per_ton" not in by_date["2025-12-09"]
    assert "price_per_ton" not in by_date["2025-12-16"]

    with caplog.at_level("WARNING"):
        bronze = transform_gtr_soda_json_to_bronze(raw, "barge_per_ton", AS_OF, INGEST)
    assert "literal ZERO" in caplog.text, "the refusal must be said out loud, not silent"

    zero_row = bronze.loc[bronze["period_date"] == datetime.date(2025, 12, 2)]
    assert len(zero_row) == 1
    assert pd.isna(zero_row["price_per_ton"].iloc[0]), "0 is not a freight quote"
    # ... and the real quotes either side are untouched
    quoted = bronze.loc[bronze["period_date"] == datetime.date(2025, 11, 25)]
    assert quoted["price_per_ton"].iloc[0] == pytest.approx(29.4025)

    silver = transform_gtr_bronze_to_silver(bronze, "barge_per_ton")
    assert not (silver["rate"].fillna(-1) == 0).any()
    assert silver["rate"].notna().sum() == 2


def test_a_zero_never_reaches_silver_on_any_rate_dataset():
    """The 'never 0.0' claim, enforced rather than asserted. Every non-exempt value column
    in the family is a price or a percent-of-tariff -- zero would mean it moved for free."""
    from leviathan.transforms.raw_to_bronze.ams_gtr import ZERO_IS_A_QUOTE_COLUMNS

    for dataset in SODA_DATASETS:
        spec = get_dataset(dataset)
        records = json.loads(_rows_fixture(dataset))
        for source_col in spec.value_cols:
            if source_col in ZERO_IS_A_QUOTE_COLUMNS:
                continue
            for record in records:
                record[source_col] = "0"
        bronze = transform_gtr_soda_json_to_bronze(
            json.dumps(records).encode(), dataset, AS_OF, INGEST
        )
        silver = transform_gtr_bronze_to_silver(bronze, dataset)
        rateable = [c for c in spec.value_cols if c not in ZERO_IS_A_QUOTE_COLUMNS]
        assert rateable, dataset
        assert not (silver["rate"].fillna(-1) == 0).any(), dataset


def test_a_spread_may_legitimately_be_zero_and_is_exempt_in_writing():
    """The exemption is principled, not observed: gulf_pnw_spread is a DIFFERENCE between
    two routes, so zero means they priced level -- an ordinary market state. It has not
    happened in the 367 months 1996-01..2026-07 (measured live: 0 rows), but nulling it
    would delete a real observation the day it does."""
    from leviathan.transforms.raw_to_bronze.ams_gtr import ZERO_IS_A_QUOTE_COLUMNS

    assert ZERO_IS_A_QUOTE_COLUMNS == frozenset({"gulf_pnw_spread"})

    records = json.loads(_rows_fixture("ocean_monthly"))
    records[0]["gulf_pnw_spread"] = "0"
    bronze = transform_gtr_soda_json_to_bronze(
        json.dumps(records).encode(), "ocean_monthly", AS_OF, INGEST
    )
    assert (bronze["gulf_pnw_spread"] == 0.0).sum() == 1
    silver = transform_gtr_bronze_to_silver(bronze, "ocean_monthly")
    spread = silver.loc[silver["series"] == "gulf_pnw_spread"]
    assert (spread["rate"] == 0.0).sum() == 1


def test_empty_and_malformed_payloads_fail_closed():
    with pytest.raises(ValueError, match="empty array"):
        transform_gtr_soda_json_to_bronze(b"[]", "barge_pct_tariff", AS_OF, INGEST)
    with pytest.raises(ValueError, match="not a JSON array"):
        transform_gtr_soda_json_to_bronze(b'{"a": 1}', "barge_pct_tariff", AS_OF, INGEST)
    with pytest.raises(ValueError, match="unknown ams_gtr dataset"):
        transform_gtr_soda_json_to_bronze(b"[]", "not_a_dataset", AS_OF, INGEST)


def test_a_mixed_dataset_frame_is_refused():
    """One frame per dataset. A mixed frame would melt several units into one column."""
    frame = _bronze("barge_pct_tariff")
    frame.loc[frame.index[0], "dataset"] = "barge_per_ton"
    with pytest.raises(ValueError, match="One frame per dataset"):
        transform_gtr_bronze_to_silver(frame, "barge_pct_tariff")


# ---------------------------------------------------------------------------
# The measured null-versus-value duplicate
# ---------------------------------------------------------------------------

def test_null_twin_is_dropped_and_the_quoted_value_kept():
    raw = (FIXTURES / "soda_2n8s-739j_dup_2022q3.json").read_bytes()
    records = json.loads(raw)
    assert len(records) == 3, "the pinned slice holds the duplicate"

    bronze = transform_gtr_soda_json_to_bronze(
        raw, "ukraine_ocean_quarterly", AS_OF, INGEST
    )
    silver = transform_gtr_bronze_to_silver(bronze, "ukraine_ocean_quarterly")

    assert len(silver) == 2
    kept = silver.loc[silver["route_or_reach"] == "Odesa-Southern ports, China"]
    assert len(kept) == 1
    assert kept["rate"].iloc[0] == pytest.approx(85.99)


def test_contradictory_rates_on_one_key_raise_rather_than_being_guessed():
    raw = (FIXTURES / "soda_2n8s-739j_dup_2022q3.json").read_bytes()
    records = json.loads(raw)
    for record in records:
        if record["route"] == "Odesa-Southern ports, China" and "rate" not in record:
            record["rate"] = "99.99"  # a second, DIFFERENT quote on the same key
    bronze = transform_gtr_soda_json_to_bronze(
        json.dumps(records).encode(), "ukraine_ocean_quarterly", AS_OF, INGEST
    )
    with pytest.raises(ValueError, match="DIFFERENT non-null rates"):
        transform_gtr_bronze_to_silver(bronze, "ukraine_ocean_quarterly")


@pytest.mark.parametrize("dataset", SODA_DATASETS)
def test_the_natural_key_is_unique_after_transform(dataset):
    silver = _silver(dataset)
    keys = silver[NATURAL_KEY].astype(object).where(silver[NATURAL_KEY].notna(), "\x00")
    assert not keys.duplicated().any()


# ---------------------------------------------------------------------------
# The spreadsheet leg
# ---------------------------------------------------------------------------

def test_ocean_weekly_xlsx_parses_the_full_measured_series():
    bronze = transform_gtr_ocean_weekly_xlsx_to_bronze(
        (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
    )
    # Measured live 2026-08-20: 1,253 weekly rows, 2002-08-21 .. 2026-08-19.
    assert len(bronze) == 1253
    assert bronze["period_date"].min() == datetime.date(2002, 8, 21)
    assert bronze["period_date"].max() == datetime.date(2026, 8, 19)
    # Every period date is a Wednesday -- the property the Thursday derivation rests on.
    assert {d.weekday() for d in bronze["period_date"]} == {2}
    # Source-faithful: Table 1's other columns survive into bronze even though silver
    # publishes only the ocean pair.
    for column in ("diesel_price_usd_per_gal", "rail_usd_per_car", "river_pct_of_tariff"):
        assert column in bronze.columns


def test_ocean_weekly_silver_pins_the_last_published_values():
    silver = transform_gtr_bronze_to_silver(
        transform_gtr_ocean_weekly_xlsx_to_bronze(
            (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
        ),
        "ocean_weekly",
    )
    assert len(silver) == 2506  # 1,253 weeks x 2 series
    assert set(silver["series"].unique()) == {"gulf_to_japan", "pnw_to_japan"}
    assert set(silver["route_or_reach"].unique()) == {"US Gulf-Japan", "PNW-Japan"}
    assert (silver["unit"] == UNIT_USD_PER_METRIC_TON).all()

    last = silver.loc[silver["period_date"] == datetime.date(2026, 8, 19)]
    by_series = dict(zip(last["series"], last["rate"]))
    assert by_series["gulf_to_japan"] == pytest.approx(72.75)
    assert by_series["pnw_to_japan"] == pytest.approx(36.50)
    # The 2026-08-19 report week was published Thursday 2026-08-20.
    assert (last["knowledge_date"] == datetime.date(2026, 8, 20)).all()


def test_na_cells_become_null_never_zero():
    """GTRTable1 writes 27 unquoted ocean weeks as the literal string 'n/a'."""
    bronze = transform_gtr_ocean_weekly_xlsx_to_bronze(
        (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
    )
    assert bronze["ocean_gulf_japan"].isna().sum() == 27
    assert bronze["ocean_pnw_japan"].isna().sum() == 27
    quoted = bronze["ocean_gulf_japan"].dropna()
    assert (quoted > 0).all(), "no unquoted week may have been filled with 0.0"


def test_an_unrecognised_annotation_becomes_null_and_is_warned(caplog):
    """Row 236 (period 2007-01-03) holds the string 'One week Lag' in a value cell.

    It must not be swallowed: an annotation that silently becomes NULL is a defect
    that only surfaces years later.
    """
    with caplog.at_level("WARNING"):
        bronze = transform_gtr_ocean_weekly_xlsx_to_bronze(
            (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
        )
    assert "One week Lag" in caplog.text
    row = bronze.loc[bronze["period_date"] == datetime.date(2007, 1, 3)]
    assert len(row) == 1
    assert pd.isna(row["ocean_gulf_japan"].iloc[0])


def test_a_relaid_sheet_raises_instead_of_reading_the_wrong_column():
    """The header positions are asserted before any value is read.

    Reading pinned positions against a re-laid sheet would publish the wrong series
    under the right name -- the failure mode a size check cannot see.
    """
    import io

    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO((FIXTURES / "GTRTable1.xlsx").read_bytes()))
    sheet = workbook["Data"]
    sheet.cell(7, 5).value = "Atlantic"  # was "Gulf"
    buffer = io.BytesIO()
    workbook.save(buffer)

    with pytest.raises(ValueError, match="no longer matches the pinned layout"):
        transform_gtr_ocean_weekly_xlsx_to_bronze(buffer.getvalue(), AS_OF, INGEST)


def test_weekly_and_monthly_ocean_legs_agree_which_is_how_the_unit_is_known():
    """GTRTable1 declares no unit anywhere; ``ehs5-yac3`` declares "dollar per metric
    ton" verbatim. The two are the same series, so the agreement below is what makes
    the weekly leg's unit an assertion rather than an assumption.

    Measured over the twelve most recent overlapping months: max relative difference
    2.79% (Gulf) and 2.04% (PNW).
    """
    weekly = transform_gtr_bronze_to_silver(
        transform_gtr_ocean_weekly_xlsx_to_bronze(
            (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
        ),
        "ocean_weekly",
    )
    monthly = _silver("ocean_monthly")

    weekly = weekly.loc[weekly["rate"].notna()].copy()
    weekly["ym"] = [(d.year, d.month) for d in weekly["period_date"]]
    weekly_mean = weekly.groupby(["ym", "series"])["rate"].mean()

    monthly = monthly.loc[monthly["series"].isin({"gulf_to_japan", "pnw_to_japan"})].copy()
    monthly["ym"] = [(d.year, d.month) for d in monthly["period_date"]]

    compared = 0
    for _, row in monthly.iterrows():
        key = (row["ym"], row["series"])
        if key not in weekly_mean.index or pd.isna(row["rate"]):
            continue
        assert abs(weekly_mean[key] - row["rate"]) / row["rate"] < 0.05, key
        compared += 1
    assert compared >= 20, "the fixtures must overlap enough months to mean anything"


# ---------------------------------------------------------------------------
# PIT -- the derived release date
# ---------------------------------------------------------------------------

def test_first_thursday_after_is_strictly_after():
    # A Wednesday period -> the next day's Thursday report.
    assert _first_thursday_after(datetime.date(2026, 8, 19)) == datetime.date(2026, 8, 20)
    # A Tuesday period (the barge convention) -> the same week's Thursday.
    assert _first_thursday_after(datetime.date(2026, 8, 18)) == datetime.date(2026, 8, 20)
    # A Thursday period -> the NEXT Thursday, never the same morning's report.
    assert _first_thursday_after(datetime.date(2026, 8, 20)) == datetime.date(2026, 8, 27)


def test_month_end_handles_the_december_boundary():
    assert _month_end(datetime.date(2026, 7, 1)) == datetime.date(2026, 7, 31)
    assert _month_end(datetime.date(2026, 12, 1)) == datetime.date(2026, 12, 31)
    assert _month_end(datetime.date(2024, 2, 1)) == datetime.date(2024, 2, 29)


def test_monthly_leg_derives_off_month_end_not_the_first():
    """Its period_date is the 1st. Deriving off that would claim a July figure was
    knowable on 2 July -- knowledge the publisher had not released."""
    knowledge, basis = derive_knowledge_date(
        datetime.date(2026, 7, 1), BASIS_GTR_THURSDAY_MONTH_END, datetime.date(2026, 8, 20)
    )
    assert basis == BASIS_GTR_THURSDAY_MONTH_END
    assert knowledge == datetime.date(2026, 8, 6)
    assert knowledge > datetime.date(2026, 7, 31)


def test_ukraine_leg_uses_the_annual_edition_not_a_thursday():
    """It is published yearly. A Thursday rule would claim a 2025Q4 figure was
    knowable on 2026-01-01, months before the edition that carries it."""
    knowledge, basis = derive_knowledge_date(
        datetime.date(2025, 12, 31), BASIS_UKRAINE_ANNUAL, datetime.date(2026, 8, 20)
    )
    assert basis == BASIS_UKRAINE_ANNUAL
    assert knowledge == datetime.date(2026, 7, 31)  # the July 2026 edition, month-end

    early, basis_early = derive_knowledge_date(
        datetime.date(2019, 9, 30), BASIS_UKRAINE_ANNUAL, datetime.date(2026, 8, 20)
    )
    assert basis_early == BASIS_UKRAINE_ANNUAL
    assert early == datetime.date(2020, 3, 31)  # the March 2020 edition


def test_a_quarter_with_no_edition_yet_falls_back_to_the_observed_snapshot():
    """The fallback is reported on the row, not papered over with a guess."""
    knowledge, basis = derive_knowledge_date(
        datetime.date(2099, 3, 31), BASIS_UKRAINE_ANNUAL, datetime.date(2026, 8, 20)
    )
    assert basis == BASIS_OBSERVED
    assert knowledge == datetime.date(2026, 8, 20)


@pytest.mark.parametrize("dataset", list(GTR_DATASETS))
def test_knowledge_date_never_exceeds_the_snapshot_that_contains_the_row(dataset):
    """The PIT invariant: a row in a snapshot taken at as_of was published by then."""
    if get_dataset(dataset).channel == "xlsx":
        silver = transform_gtr_bronze_to_silver(
            transform_gtr_ocean_weekly_xlsx_to_bronze(
                (FIXTURES / "GTRTable1.xlsx").read_bytes(), AS_OF, INGEST
            ),
            dataset,
        )
    else:
        silver = _silver(dataset)
    as_of = datetime.date(2026, 8, 20)
    assert all(k <= as_of for k in silver["knowledge_date"])
    assert silver["knowledge_date_basis"].notna().all()


def test_a_derivation_that_outruns_the_snapshot_raises():
    """If the rule ever produces a date after the snapshot it has stopped describing
    the publisher, and the transform must say so rather than publish the claim."""
    bronze = _bronze("barge_pct_tariff")
    bronze["as_of_date"] = "20260101"  # a snapshot BEFORE the rows it contains
    with pytest.raises(ValueError, match="knowledge_date AFTER the snapshot"):
        transform_gtr_bronze_to_silver(bronze, "barge_pct_tariff")


# ---------------------------------------------------------------------------
# S3 key layout
# ---------------------------------------------------------------------------

def test_raw_keys_carry_the_dataset_and_the_mode():
    assert raw_ams_gtr_backfill_key("barge_per_ton", "full.json") == (
        "raw/production/source=ams_gtr/dataset=barge_per_ton/backfill/full.json"
    )
    assert raw_ams_gtr_weekly_key("ocean_weekly", "2026-08-20", "GTRTable1.xlsx") == (
        "raw/production/source=ams_gtr/dataset=ocean_weekly/as_of=20260820/GTRTable1.xlsx"
    )
    assert raw_ams_gtr_weekly_key("ocean_weekly", "20260820", "GTRTable1.xlsx") == (
        raw_ams_gtr_weekly_key("ocean_weekly", "2026-08-20", "GTRTable1.xlsx")
    )
    assert bronze_ams_gtr_key("ocean_monthly", "20260820").startswith(
        "bronze/production/source=ams_gtr/dataset=ocean_monthly/as_of=20260820/"
    )
    assert silver_ams_gtr_key("barge_fwd_3m") == (
        "silver/ams_gtr/dataset=barge_fwd_3m/part-000.parquet"
    )
    assert ams_gtr_dataset_prefix("ocean_weekly").endswith("dataset=ocean_weekly/")


def test_an_unknown_dataset_is_never_turned_into_a_key():
    for builder in (
        lambda: raw_ams_gtr_backfill_key("made_up", "full.json"),
        lambda: raw_ams_gtr_weekly_key("made_up", "20260820", "full.json"),
        lambda: bronze_ams_gtr_key("made_up", "20260820"),
        lambda: silver_ams_gtr_key("made_up"),
        lambda: ams_gtr_dataset_prefix("made_up"),
    ):
        with pytest.raises(ValueError, match="not one of"):
            builder()


def test_a_malformed_as_of_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="not YYYY-MM-DD or YYYYMMDD"):
        raw_ams_gtr_weekly_key("ocean_weekly", "aug-20", "GTRTable1.xlsx")


# ---------------------------------------------------------------------------
# The registry contract
# ---------------------------------------------------------------------------

def test_registry_contract_matches_what_the_transform_emits():
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_ams_gtr")
    partitions = [p["name"] for p in contract["partition_keys"]]
    assert partitions == ["dataset"]

    declared = [c["name"] for c in contract["physical_columns"]]
    # `dataset` rides in the parquet body but is declared only as a partition key
    # (the silver_fgis convention), so it is the one output column not listed here.
    assert declared == [c for c in OUTPUT_COLUMNS if c != "dataset"]
    assert contract["natural_key"] == NATURAL_KEY
    assert contract["value_columns"] == ["rate"]
    assert contract["knowledge_date_col"] == "knowledge_date"


def test_the_declared_types_are_what_the_writer_actually_emits():
    """INV-2. The contract's arrow/parquet types must be the writer's own, measured -- not
    remembered. The first cut declared forward_month_offset int64 and rate_month int16 with
    glue `int` for both, which the estate's classifier scores as a glue_catalog_mismatch on
    a table whose DDL was about to create the catalog wrong on its very first run."""
    import pyarrow as pa
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_ams_gtr")
    declared = {c["name"]: c for c in contract["physical_columns"]}

    # a forward-curve dataset, so both integer columns carry real values
    silver = _silver("barge_fwd_1m")
    schema = pa.Table.from_pandas(silver, preserve_index=False).schema
    for name in ("forward_month_offset", "rate_month"):
        assert str(schema.field(name).type) == declared[name]["arrow_type"], name
        assert declared[name]["arrow_type"] == "int64", name
        assert declared[name]["parquet_physical_type"] == "INT64", name
        # int16 would only mint a widen_int drift entry at birth; INV-2's target IS int64.
        assert declared[name]["target_arrow_type"] == "int64", name


def test_the_glue_types_match_the_physical_bytes_and_drift_summary_is_true():
    """`drift_summary: []` is a CLAIM about this contract, and the estate has a classifier
    that can check it. Every int16 column elsewhere in the registry is declared smallint and
    every int64 bigint; `int` against int64 is the WASDE C-WRONG-6 mismatch, closed there by
    making glue bigint equal the physical int64 -- applied here before the table exists."""
    from leviathan.silver.registry import load_registry
    from leviathan.silver.types import classify_drift

    contract = load_registry().table("silver_ams_gtr")
    computed = {
        c["name"]: classify_drift(c.get("arrow_type"), c.get("glue_type"))
        for c in contract["physical_columns"]
    }
    offenders = {k: v for k, v in computed.items() if v}
    assert offenders == {}, offenders
    assert contract["drift_summary"] == []

    by = {c["name"]: c for c in contract["physical_columns"]}
    assert by["forward_month_offset"]["glue_type"] == "bigint"
    assert by["rate_month"]["glue_type"] == "bigint"

    # and the DDL that CREATES the catalog says the same thing, in both copies
    for path in (
        Path(__file__).resolve().parents[2] / "sql" / "athena" / "ddl" / "silver_ams_gtr.sql",
        Path(__file__).resolve().parents[2] / "sql" / "athena" / "ddl_generated"
        / "silver_ams_gtr.sql",
    ):
        text = path.read_text(encoding="utf-8")
        assert "forward_month_offset bigint" in " ".join(text.split()), path.name
        assert "rate_month bigint" in " ".join(text.split()), path.name


def test_the_pit_declaration_is_vintage_not_data_date():
    """The report-date-vs-observation-date inversion, caught in the CONTRACT.

    knowledge_date is the derived RELEASE date; the observation date is period_date. The
    estate reserves `data_date` for a column holding the OBSERVATION date, with the lag
    carrying the publication offset (silver_cot report_date +6, silver_fgis
    week_ending_date +13), and `vintage` for a column that already IS the release
    (silver_nass_annual release_date 0, silver_ams_cotton_quality release_date 0). The lag
    is consumed ADDITIVELY as as-of grace, so the original `data_date` + 1 would have added
    a further day on top of a date already advanced to the report."""
    from leviathan.silver.dag_catalog import effective_sla_lag_days
    from leviathan.silver.registry import load_registry

    reg = load_registry()
    contract = reg.table("silver_ams_gtr")
    assert contract["knowledge_semantics"] == "vintage"
    assert contract["knowledge_date_col"] == "knowledge_date"
    assert contract["publication_lag_days"] == 0

    # the estate's own convention, re-derived rather than quoted
    for name in ("silver_nass_annual", "silver_ams_cotton_quality", "silver_sagis_cec"):
        other = reg.table(name)
        assert other["knowledge_semantics"] == "vintage"
        assert other["publication_lag_days"] == 0

    # no phantom grace is added on top of a column that is already the release date
    lag, _basis = effective_sla_lag_days(contract)
    weekly, _ = effective_sla_lag_days(
        {"freshness_sla": {"cadence": "weekly", "max_lag_days": None},
         "publication_lag_days": 0}
    )
    assert lag == weekly


def test_a_knowledge_date_before_its_own_period_is_refused():
    """The inversion, caught in the DATA. Under vintage semantics knowledge_date IS the
    release date, and a release cannot precede the period it reports on. A derivation that
    produced one would have quietly turned the column back into an observation date."""
    import leviathan.transforms.bronze_to_silver.ams_gtr as B

    bronze = _bronze("barge_pct_tariff")
    # a rule that "publishes" a week BEFORE the week closes
    monkey = lambda period, basis, as_of: (period - datetime.timedelta(days=1), basis)  # noqa: E731
    original = B.derive_knowledge_date
    B.derive_knowledge_date = monkey
    try:
        with pytest.raises(ValueError, match="knowledge_date BEFORE the period"):
            B.transform_gtr_bronze_to_silver(bronze, "barge_pct_tariff")
    finally:
        B.derive_knowledge_date = original


def test_knowledge_date_is_on_or_after_every_period_it_describes():
    """The same bound, held against the real fixtures on every dataset."""
    for dataset in SODA_DATASETS:
        silver = _silver(dataset)
        assert (
            pd.to_datetime(silver["knowledge_date"]) >= pd.to_datetime(silver["period_date"])
        ).all(), dataset
