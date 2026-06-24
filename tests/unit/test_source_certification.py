from __future__ import annotations

from pathlib import Path

import pytest

from leviathan.certification.source_certification import (
    SourceCertificationError,
    SourceContract,
    SourceObservation,
    Waiver,
    certify_contract,
    load_source_contracts,
)


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
        "availability_columns": ("date",),
        "expected_min_rows": 1,
        "duplicate_check": "full",
    }
    values.update(overrides)
    return SourceContract(**values)


def observation(**overrides) -> SourceObservation:
    values = {
        "s3_prefix_exists": True,
        "glue_table_exists": True,
        "columns": ("id", "date", "value"),
        "partition_keys": (),
        "row_count": 10,
        "min_date": "2024-01-01",
        "max_date": "2024-12-31",
        "duplicate_key_count": 0,
    }
    values.update(overrides)
    return SourceObservation(**values)


def test_load_source_contracts_rejects_duplicate_source_key(tmp_path: Path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        """
sources:
  - source_key: one
    title: One
    glue_table: silver_one
    s3_prefix: s3://bucket/one/
    status: core
    grain: id
  - source_key: one
    title: Duplicate
    glue_table: silver_two
    s3_prefix: s3://bucket/two/
    status: core
    grain: id
""",
        encoding="utf-8",
    )
    with pytest.raises(SourceCertificationError, match="duplicate source_key"):
        load_source_contracts(path)


def test_certify_contract_passes_when_all_checks_are_clean() -> None:
    result = certify_contract(contract(), observation())

    assert result.status == "pass"
    assert result.checks["s3_prefix"] == "pass"
    assert result.checks["glue_table"] == "pass"
    assert result.checks["duplicate_keys"] == "pass"
    assert result.issues == ()


def test_certify_contract_blocks_missing_required_columns() -> None:
    result = certify_contract(
        contract(),
        observation(columns=("id", "date"), duplicate_key_count=0),
    )

    assert result.status == "blocked"
    assert result.checks["required_columns"] == "fail"
    assert result.issues[0]["code"] == "missing_required_columns"


def test_certify_contract_blocks_duplicate_natural_keys() -> None:
    result = certify_contract(contract(), observation(duplicate_key_count=2))

    assert result.status == "blocked"
    assert result.checks["duplicate_keys"] == "fail"
    assert result.issues[0]["code"] == "duplicate_keys"


def test_certify_contract_warns_when_duplicate_check_is_skipped() -> None:
    result = certify_contract(
        contract(duplicate_check="skip", duplicate_skip_reason="too large"),
        observation(duplicate_key_count=None),
    )

    assert result.status == "warn"
    assert result.checks["duplicate_keys"] == "skipped"
    assert any(item["code"] == "duplicate_check_skipped" for item in result.warnings)


def test_certify_contract_keeps_diagnostic_only_class() -> None:
    result = certify_contract(
        contract(status="diagnostic_only"),
        observation(),
    )

    assert result.status == "diagnostic_only"
    assert result.contract_status == "diagnostic_only"


def test_certify_contract_keeps_deferred_class_even_with_warnings() -> None:
    result = certify_contract(
        contract(status="deferred"),
        observation(row_count=None, duplicate_key_count=None),
    )

    assert result.status == "deferred"
    assert result.checks["row_count"] == "not_checked"


def test_certify_contract_applies_explicit_waiver() -> None:
    result = certify_contract(
        contract(),
        observation(columns=("id", "date")),
        waivers=(
            Waiver(
                source_key="example",
                issue_code="missing_required_columns",
                reason="known fixture gap",
            ),
        ),
    )

    assert result.status == "warn"
    assert result.issues == ()
    assert result.waivers[0]["issue_code"] == "missing_required_columns"
    assert result.warnings[0]["message"].startswith("WAIVED:")


def test_certify_contract_blocks_missing_s3_prefix() -> None:
    result = certify_contract(contract(), observation(s3_prefix_exists=False))

    assert result.status == "blocked"
    assert result.checks["s3_prefix"] == "fail"
    assert result.issues[0]["code"] == "missing_s3_prefix"
