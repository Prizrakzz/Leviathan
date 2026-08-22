from pathlib import Path

from leviathan.eda.campaign import build_all_overlays
from leviathan.silver.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_campaign_inventory_is_every_silver_and_no_gold() -> None:
    registry = load_registry()
    overlays = build_all_overlays(registry, repo_root=REPO_ROOT)

    expected = {
        name for name, contract in registry.tables.items()
        if contract.get("layer") == "silver"
    }
    assert set(overlays) == expected
    assert len(overlays) == 42
    assert "gold_weather_z" not in overlays


def test_model_predictions_is_output_plane_only() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)
    spec = overlays["silver_model_predictions"]

    assert spec["feature_disposition"] == "excluded_leakage"
    assert spec["no_candidate_reason"]
    assert "generated_output" in spec["adapters"]


def test_semantic_overlay_columns_are_declared_by_contract() -> None:
    registry = load_registry()
    overlays = build_all_overlays(registry, repo_root=REPO_ROOT)

    for table_name, spec in overlays.items():
        declared = registry.columns(table_name)
        for field in (
            "observation_time_candidates",
            "entity_columns",
            "categorical_columns",
            "numeric_columns",
            "meaningful_groupings",
        ):
            assert set(spec[field]) <= declared, (table_name, field)
        assert set(spec["units"]) <= declared


def test_daily_weather_is_not_misclassified_as_annual_panel() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)

    for table_name in ("silver_chirps", "silver_cpc_soil", "silver_nasa_power"):
        assert "annual_seasonal_panel" not in overlays[table_name]["adapters"]


def test_existing_feature_coverage_is_source_mapped_not_invented() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)
    mapped = {name for name, spec in overlays.items() if spec["existing_feature_families"]}

    assert len(mapped) == 24
    assert "silver_model_predictions" not in mapped


def test_table_level_feature_use_does_not_claim_candidate_or_column_parity() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)
    spec = overlays["silver_wasde"]

    assert "wasde_direct_revisions" in spec["existing_table_feature_families"]
    assert spec["existing_feature_families"] == spec[
        "existing_table_feature_families"
    ]
    assert spec["existing_feature_family_scope"] == (
        "table_level_source_reference_only"
    )
    assert spec["existing_candidate_families"] == {}
    assert spec["extension_candidate_kinds"] == []
    coverage = spec["existing_feature_coverage"]
    assert coverage["status"] == "table_level_source_reference_only"
    assert coverage["verified_candidate_kind_to_family"] == {}
    assert coverage["verified_source_columns"] == []
    assert coverage["candidate_classification_verified"] is False


def test_weather_overlay_separates_configured_mapping_from_observed_coverage() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)
    mapping = overlays["silver_chirps"]["governed_mapping_status"]

    assert mapping["status"] == "configured_pending_observed_coverage"
    assert mapping["observed_frame_coverage_assessed"] is False
    assert mapping["source_only"] is True
    assert mapping["serving_gold_followed"] is False
    assert mapping["config_inventory"]["status"] == "complete"
    assert mapping["config_inventory"]["crop_calendar_commodity_count"] > 0
    assert mapping["config_inventory"]["geography_mapping_row_count"] > 0


def test_non_esr_derived_overlays_emit_lineage_repair_evidence() -> None:
    overlays = build_all_overlays(load_registry(), repo_root=REPO_ROOT)
    for table_name in (
        "silver_mpob_annual",
        "silver_unica_biweekly_release_series",
        "silver_unica_corn_ethanol",
        "silver_unica_monthly_ethanol_sales",
        "silver_wap_table01_revisions",
    ):
        lineage = overlays[table_name]["lineage_status"]
        assert lineage["status"] == "lineage_not_assessed", table_name
        assert lineage["parity_assessed"] is False, table_name
        assert lineage["parity_claimed"] is False, table_name
        assert lineage["repair_required"] is True, table_name
        assert lineage["work_orders"], table_name

    esr = overlays["silver_esr_compact"]["lineage_status"]
    assert esr["status"] == "governed_peer_declared_pending_parity"
    assert esr["peer_table"] == "silver_esr"
