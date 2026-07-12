"""SILVER-V002 -- value-nonnull + freshness + producer-coverage certification tests.

Value-nonnull (registry value_columns + min_nonnull_frac), freshness
(silver.ingest_date >= bronze.ingest_date, no misfire on a benign re-ingest -- AV-12),
and the producer-coverage contract test (flags exactly the six orphan families
until R3 builds them).
"""
from __future__ import annotations

from pathlib import Path

from leviathan.certification.source_certification import (
    EXPECTED_PRODUCER_GAPS,
    SourceContract,
    SourceObservation,
    certify_contract,
    load_source_contracts,
    producer_coverage_gaps,
    producer_status_from_registry,
)
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[2]
CONTRACTS = _REPO / "configs" / "datasets" / "source_contracts.yaml"


def contract(**overrides) -> SourceContract:
    values = {
        "source_key": "example",
        "title": "Example",
        "glue_table": "silver_example",
        "s3_prefix": "s3://bucket/silver/example/",
        "status": "core",
        "grain": "id x date",
        "required_columns": ("id", "date", "value"),
        "natural_key": ("id", "date"),
        "date_columns": ("date",),
    }
    values.update(overrides)
    return SourceContract(**values)


def observation(**overrides) -> SourceObservation:
    values = {
        "s3_prefix_exists": True,
        "glue_table_exists": True,
        "columns": ("id", "date", "value"),
        "row_count": 10,
        "duplicate_key_count": 0,
    }
    values.update(overrides)
    return SourceObservation(**values)


# ---------------------------------------------------------------------------
# value_nonnull check
# ---------------------------------------------------------------------------
def test_all_nan_value_column_fails_value_nonnull():
    result = certify_contract(
        contract(),
        observation(value_nonnull_fractions={"value": 0.0}, min_nonnull_frac=0.5),
    )
    assert result.checks["value_nonnull"] == "fail"
    assert result.status == "blocked"
    assert any(i["code"] == "value_nonnull_below_floor" for i in result.issues)


def test_healthy_value_column_passes_value_nonnull():
    result = certify_contract(
        contract(),
        observation(value_nonnull_fractions={"value": 0.92}, min_nonnull_frac=0.5),
    )
    assert result.checks["value_nonnull"] == "pass"


def test_value_nonnull_not_checked_when_no_fractions():
    result = certify_contract(contract(), observation())
    assert result.checks["value_nonnull"] == "not_checked"
    # a not_checked value gate is a warning, never a silent hard pass
    assert any(w["code"] == "value_nonnull_not_checked" for w in result.warnings)


# ---------------------------------------------------------------------------
# freshness contract
# ---------------------------------------------------------------------------
def test_stale_silver_fails_freshness():
    # the CHIRPS class: silver 2026-05-16 predates bronze 2026-06-16.
    result = certify_contract(
        contract(),
        observation(silver_ingest_date="2026-05-16", bronze_ingest_date="2026-06-16"),
    )
    assert result.checks["freshness"] == "fail"
    assert result.status == "blocked"
    assert any(i["code"] == "stale_silver" for i in result.issues)


def test_benign_reingest_does_not_misfire_freshness():
    # AV-12: bronze re-ingested but silver rebuilt the same day -> silver >= bronze.
    result = certify_contract(
        contract(),
        observation(silver_ingest_date="2026-06-16", bronze_ingest_date="2026-06-16"),
    )
    assert result.checks["freshness"] == "pass"


def test_fresh_silver_newer_than_bronze_passes():
    result = certify_contract(
        contract(),
        observation(silver_ingest_date="2026-06-20", bronze_ingest_date="2026-06-16"),
    )
    assert result.checks["freshness"] == "pass"


# ---------------------------------------------------------------------------
# producer-coverage contract
# ---------------------------------------------------------------------------
def test_producer_coverage_flags_core_orphan():
    contracts = (
        contract(source_key="fred_fx", glue_table="silver_fred_fx", status="certified_driver"),
        contract(source_key="psd", glue_table="silver_psd", status="core"),
    )
    status_by_table = {"silver_fred_fx": "orphan", "silver_psd": "producer"}
    gaps = producer_coverage_gaps(contracts, status_by_table)
    assert [g["source_key"] for g in gaps] == ["fred_fx"]
    assert gaps[0]["r3_package"] == "SILVER-F040"


def test_producer_coverage_live_gap_equals_expected_orphan_set():
    """xfail-style: the LIVE producer-coverage gap must equal the six-orphan set
    pinned to R3 packages -- red until R3 builds each producer, green only when a
    package removes its row from EXPECTED_PRODUCER_GAPS."""
    contracts = load_source_contracts(CONTRACTS)
    reg = load_registry()
    status_by_table = producer_status_from_registry(reg)
    gaps = producer_coverage_gaps(contracts, status_by_table)
    gap_keys = sorted(g["source_key"] for g in gaps)
    assert gap_keys == sorted(EXPECTED_PRODUCER_GAPS)
    # every gap carries its owning R3 package and a non-"producer" status
    for g in gaps:
        assert g["r3_package"] is not None
        assert g["producer_status"] != "producer"


def test_expected_producer_gaps_covers_six_families():
    families = {k.split("_")[0] for k in EXPECTED_PRODUCER_GAPS}
    # fred, oni, ams, icco, nass(citrus), sagis
    assert {"fred", "oni", "ams", "icco", "nass", "sagis"} <= families
