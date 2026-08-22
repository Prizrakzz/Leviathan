from __future__ import annotations

from pathlib import Path

import pandas as pd

from leviathan.eda.models import TableSpec
from leviathan.eda.relations import (
    consumer_view_delta,
    esr_raw_compact_parity,
    lineage_status,
    spatial_weather_readiness,
)
from leviathan.silver.registry import load_registry


def test_consumer_view_delta_preserves_raw_duplicate_evidence() -> None:
    spec = TableSpec.from_contract(load_registry().table("silver_fred_fx"))
    frame = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-01", "2024-02-01"],
            "brl_usd": [5.0, 5.1, 5.2],
            "brl_usd_pct_change_90d": [0.0, 0.1, 0.2],
            "ars_usd": [1.0, 1.0, 1.0],
            "ars_usd_pct_change_90d": [0.0, 0.0, 0.0],
            "cny_usd": [7.0, 7.0, 7.0],
            "cny_usd_pct_change_90d": [0.0, 0.0, 0.0],
            "source": ["a", "b", "c"],
        }
    )
    result = consumer_view_delta(frame, spec)
    assert result["raw_rows"] == 3
    assert result["consumer_rows"] == 2
    assert result["removed_rows"] == 1
    assert result["raw_profile_preserved"] is True


def test_esr_parity_reports_mismatch_and_never_expands_rows() -> None:
    keys = {
        "commodity_code": ["101", "101"],
        "market_year": ["2024", "2024"],
        "as_of_date": ["2024-01-01", "2024-01-08"],
        "country_code": ["MX", "MX"],
        "week_ending_date": ["2023-12-28", "2024-01-04"],
    }
    values = {
        "weekly_exports_1000mt": [1.0, 2.0],
        "outstanding_sales_1000mt": [3.0, 4.0],
        "gross_new_sales_1000mt": [5.0, 6.0],
        "changes_1000mt": [7.0, 8.0],
    }
    raw = pd.DataFrame({**keys, **values})
    compact = raw.copy()
    compact.loc[1, "changes_1000mt"] = 99.0
    result = esr_raw_compact_parity(raw, compact, exactness="exact")
    assert result["row_expansion"] is False
    assert result["matched_keys"] == 2
    assert result["value_parity"]["changes_1000mt"]["mismatch_rows"] == 1
    assert result["shared_key_parity_status"] == "fail"


def test_esr_parity_classifies_later_compact_keys_as_coverage_extension() -> None:
    raw = pd.DataFrame(
        {
            "commodity_code": ["101", "101"],
            "market_year": ["2024", "2024"],
            "as_of_date": ["2026-05-24", "2026-05-24"],
            "country_code": ["MX", "JP"],
            "week_ending_date": ["2026-05-21", "2026-05-21"],
            "weekly_exports_1000mt": [1.0, 2.0],
            "outstanding_sales_1000mt": [3.0, 4.0],
            "gross_new_sales_1000mt": [5.0, 6.0],
            "changes_1000mt": [7.0, None],
        }
    )
    compact = pd.concat(
        [
            raw,
            raw.assign(
                as_of_date="2026-07-12",
                week_ending_date="2026-07-09",
            ),
        ],
        ignore_index=True,
    )

    result = esr_raw_compact_parity(raw, compact, exactness="exact")

    assert result["matched_keys"] == 2
    assert result["raw_only_keys"] == 0
    assert result["compact_only_keys"] == 2
    assert result["shared_key_parity_status"] == "pass"
    assert result["raw_coverage_status"] == "fully_preserved_in_compact"
    assert result["coverage_relationship"] == "compact_superset"
    extension = result["compact_coverage_extension"]
    assert extension["classification"] == "later_snapshot_extension"
    assert extension["entirely_after_raw_latest_as_of"] is True
    assert extension["earliest_as_of_date"] == "2026-07-12"
    assert "do not contradict shared-key parity" in extension["interpretation"]


def test_weather_readiness_never_follows_gold() -> None:
    frame = pd.DataFrame(
        {
            "latitude": [1.0, 95.0],
            "longitude": [10.0, 11.0],
            "commodity": ["corn", "corn"],
            "region": ["r1", "r2"],
            "date": ["2024-01-01", "2024-01-02"],
        }
    )
    result = spatial_weather_readiness(
        frame, table_name="silver_chirps", exactness="sampled"
    )
    assert result["coordinates"]["latitude_invalid_count"] == 1
    assert result["serving_gold_followed"] is False
    assert result["crop_stage_join_required"] is True


def _write_weather_mapping_configs(repo_root: Path) -> None:
    calendar = repo_root / "configs" / "features" / "crop_calendars.yaml"
    calendar.parent.mkdir(parents=True)
    calendar.write_text(
        """corn_cbot:
  crop_year_start_month: 5
  stages:
    planting: [5, 5]
""",
        encoding="utf-8",
    )
    geography = repo_root / "configs" / "geographies"
    geography.mkdir(parents=True)
    payload = """commodity: corn_cbot
regions:
  - country: united_states
    locations:
      - region: us_corn_iowa
        latitude: 42.03
        longitude: -93.64
"""
    (geography / "corn_cbot_regions.yaml").write_text(payload, encoding="utf-8")
    # A second governed record with the same key proves that the EDA reports
    # expansion risk rather than silently selecting one mapping row.
    (geography / "corn_cbot_duplicate_regions.yaml").write_text(
        payload, encoding="utf-8"
    )


def test_weather_mapping_reports_coverage_unmapped_ids_and_expansion(
    tmp_path: Path,
) -> None:
    _write_weather_mapping_configs(tmp_path)
    frame = pd.DataFrame(
        {
            "commodity": ["corn_cbot", "soybeans_cbot", "corn_cbot"],
            "country": ["united_states", "united_states", "canada"],
            "region": ["us_corn_iowa", "us_soy_iowa", "ca_unknown"],
            "date": ["2024-05-01", "2024-05-02", "2024-05-03"],
        }
    )

    result = spatial_weather_readiness(
        frame,
        table_name="silver_chirps",
        exactness="exact",
        repo_root=tmp_path,
    )

    commodity = result["commodity_mapping_coverage"]
    assert commodity["raw_distinct_count"] == 2
    assert commodity["crop_calendar_mapped_distinct_count"] == 1
    assert commodity["crop_calendar_unmapped_ids"] == ["soybeans_cbot"]

    geography = result["geography_mapping_coverage"]
    assert geography["raw_distinct_key_count"] == 3
    assert geography["mapped_distinct_key_count"] == 1
    assert geography["unmapped_distinct_key_count"] == 2
    assert geography["mapping_key_unique"] is False
    assert geography["projected_row_expansion"] == 1
    assert geography["row_expansion_risk"] == "present_for_observed_keys"
    assert result["governed_mapping_status"]["readiness"] == "row_expansion_blocked"
    assert result["source_overlap_window"]["fully_governed_overlap_window"] == {
        "start": "2024-05-01T00:00:00+00:00",
        "end": "2024-05-01T00:00:00+00:00",
        "row_count": 1,
    }
    assert result["serving_gold_followed"] is False
    assert all(
        "gold" not in path.casefold()
        for path in result["governed_config_inventory"][
            "geography_config_paths"
        ]
    )


def test_weather_mapping_is_explicitly_not_assessed_when_impossible(
    tmp_path: Path,
) -> None:
    result = spatial_weather_readiness(
        pd.DataFrame({"date": ["2024-01-01"]}),
        table_name="silver_nasa_power",
        exactness="exact",
        repo_root=tmp_path,
    )

    assert result["status"] == "not_assessed"
    assert result["governed_mapping_status"]["status"] == "not_assessed"
    assert result["commodity_mapping_coverage"]["status"] == "not_assessed"
    assert result["geography_mapping_coverage"]["status"] == "not_assessed"
    assert result["governed_config_inventory"]["serving_gold_followed"] is False


def test_non_esr_derived_lineage_never_claims_unverified_parity() -> None:
    derived = lineage_status("silver_mpob_annual", "derived")
    assert derived["status"] == "lineage_not_assessed"
    assert derived["parity_assessed"] is False
    assert derived["parity_claimed"] is False
    assert derived["repair_required"] is True
    assert derived["work_orders"]

    esr = lineage_status("silver_esr_compact", "serving_copy")
    assert esr["status"] == "governed_peer_declared_pending_parity"
    assert esr["peer_table"] == "silver_esr"
    assert esr["parity_claimed"] is False
