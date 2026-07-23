"""Unit tests for the CONAB coffee silver Batch task helpers (SILVER-F024).

The task publishes the 23-column canonical (22 F024 + the WIRING_WAVE1 survey_release_date additive)
through the shadow-first publisher; ``--publish-mode`` defaults to dry-run (nothing written). These
tests exercise the helpers directly.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_conab_coffee_key
from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    PARSER_VERSION,
    _survey_release_date,
)

from jobs.batch import conab_coffee_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_CONTRACT = load_registry().table("silver_conab_coffee")
_BUCKET = "leviathan-test"


def _silver_row(
    commodity: str = "arabica_coffee",
    safra_year: int = 2025,
    survey_number: int = 1,
    region: str = "minas_gerais",
    production_revision: float | None = None,
) -> dict[str, object]:
    """A full 23-column canonical silver row (22 F024 + the survey_release_date additive)."""
    return {
        "commodity": commodity, "country": "brazil", "safra_year": safra_year,
        "survey_number": survey_number, "region": region,
        "area_in_production_ha": 10.0, "yield_bags_per_ha": 20.0,
        "production_thousand_bags": 200.0, "production_revision_thousand_bags": production_revision,
        "source": "conab_xls", "region_raw": "MG", "area_revision_ha": None,
        "yield_revision_bags_per_ha": None, "production_revision_pct": None,
        "production_revision_streak": 0, "is_repeated_survey": False,
        "repeated_from_survey_number": None, "survey_content_fingerprint": "abc123",
        "source_raw_key": None, "source_file_etag": None, "worksheet": "2 Cafe Arabica",
        "parser_version": PARSER_VERSION,
        "survey_release_date": _survey_release_date(safra_year, survey_number),
    }


def _group_df() -> pd.DataFrame:
    """One (commodity, safra_year) group: survey 1 (null rev) + survey 2 (rev populated) so the
    value column clears the provisional non-null floor (0.5)."""
    df = pd.DataFrame([
        _silver_row(survey_number=1),
        _silver_row(survey_number=2, production_revision=25.0),
    ])[OUTPUT_COLUMNS]
    df["production_revision_streak"] = df["production_revision_streak"].astype("Int64")
    df["repeated_from_survey_number"] = df["repeated_from_survey_number"].astype("Int64")
    return df


def _silver_df(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)[OUTPUT_COLUMNS]
    df["production_revision_streak"] = df["production_revision_streak"].astype("Int64")
    df["repeated_from_survey_number"] = df["repeated_from_survey_number"].astype("Int64")
    return df


def test_list_bronze_keys_filters_by_safra_year(monkeypatch) -> None:
    keys = [
        "bronze/production/source=conab_xls/safra_year=2024/survey=02/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=01/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=02/part-000.parquet",
        "bronze/production/source=conab_xls/safra_year=2025/survey=02/_SUCCESS",
    ]

    def fake_list_s3_keys(_bucket, _prefix, aws_region):
        assert aws_region == "us-east-1"
        return keys

    monkeypatch.setattr(task, "list_s3_keys", fake_list_s3_keys)
    assert task._list_bronze_keys("bucket", "us-east-1", {2025}) == keys[1:3]


def test_dry_run_publishes_nothing_but_validates() -> None:
    s3 = FakeS3()
    published, skipped = task._publish_grouped(
        _group_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET, force_overwrite=True
    )
    assert published == 1 and skipped == 0     # 1 (commodity, safra_year) group, planned
    assert s3.keys() == []                      # nothing written anywhere in dry-run


def test_shadow_stages_to_shadow_prefix_only() -> None:
    s3 = FakeS3()
    published, _ = task._publish_grouped(
        _group_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET, force_overwrite=True
    )
    assert published == 1
    keys = s3.keys()
    canonical = silver_conab_coffee_key(2025, "arabica_coffee")
    assert canonical not in keys                        # canonical NEVER touched in shadow
    assert any("_shadow" in k for k in keys)            # staged under the shadow prefix


def test_canonical_promotes_to_the_conab_silver_path() -> None:
    s3 = FakeS3()
    published, _ = task._publish_grouped(
        _group_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET, force_overwrite=True
    )
    assert published == 1
    assert silver_conab_coffee_key(2025, "arabica_coffee") in s3.keys()


def test_validate_uniqueness_raises_on_duplicate_output_rows() -> None:
    df = _silver_df([_silver_row(), _silver_row()])
    with pytest.raises(ValueError, match="duplicate output rows"):
        task._validate_uniqueness(df)


def test_conab_silver_path_does_not_overlap_other_prefixes() -> None:
    key = silver_conab_coffee_key(2025, "robusta_coffee")
    assert key == "silver/conab_coffee/commodity=robusta_coffee/safra_year=2025/part-000.parquet"
    assert not key.startswith("silver/production/")
    assert not key.startswith("silver/nass_annual/")
