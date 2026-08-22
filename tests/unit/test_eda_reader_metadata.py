from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import pandas as pd
import pytest
import yaml
from jsonschema import Draft202012Validator

from leviathan.eda.models import TableSpec
from leviathan.eda.profiling import profile_frame
from leviathan.eda.reader_analytics import build_reader_evidence
from leviathan.eda.reader_metadata import (
    ARCHETYPE_TABLES,
    SUPPORTED_SILVER_TABLES,
    ReaderArchetype,
    ReaderMetadataError,
    archetype_for_table,
    build_all_reader_metadata,
    build_reader_metadata,
)
from leviathan.silver.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
EDA_ROOT = REPO_ROOT / "eda"
SCHEMA_ROOT = EDA_ROOT / "_config" / "schemas"


def _overlays() -> dict[str, dict]:
    return {
        path.parent.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(EDA_ROOT.glob("silver_*/spec.yaml"))
    }


def _declared_columns(contract: dict) -> set[str]:
    return {
        str(item["name"])
        for item in (*contract.get("physical_columns", ()), *contract.get("partition_keys", ()))
    }


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def test_archetype_routing_is_complete_unique_and_matches_registry() -> None:
    registry = load_registry()
    current = {
        name for name in registry.names() if registry.table(name).get("layer") == "silver"
    }

    assert len(SUPPORTED_SILVER_TABLES) == 42
    assert set(SUPPORTED_SILVER_TABLES) == current
    assert sum(len(names) for names in ARCHETYPE_TABLES.values()) == 42
    assert Counter(
        name for names in ARCHETYPE_TABLES.values() for name in names
    ).most_common(1)[0][1] == 1
    assert {archetype_for_table(name) for name in current} == set(ReaderArchetype)
    assert archetype_for_table("silver_icco_cocoa") == (
        ReaderArchetype.ANNUAL_GEOGRAPHIC_PRODUCTION
    )

    with pytest.raises(ReaderMetadataError, match="No reader archetype"):
        archetype_for_table("silver_not_registered")


def test_all_reader_metadata_is_complete_deterministic_and_schema_valid() -> None:
    registry = load_registry()
    overlays = _overlays()
    first = build_all_reader_metadata(registry, overlays=overlays)
    second = build_all_reader_metadata(registry, overlays=overlays)
    validator = Draft202012Validator(_schema("reader_metadata.schema.json"))

    assert tuple(first) == tuple(sorted(first))
    assert len(first) == 42
    for name in first:
        metadata = first[name]
        payload = metadata.to_dict()
        contract = registry.table(name)
        declared = _declared_columns(contract)

        assert payload == second[name].to_dict()
        assert metadata.fingerprint == second[name].fingerprint
        assert json.loads(json.dumps(payload, sort_keys=True)) == payload
        assert set(payload["column_descriptions"]) == declared
        assert set(payload["why_it_matters"]) == declared
        assert all(payload["column_descriptions"].values())
        assert set(payload["primary_measures"]) <= declared
        assert 4 <= len(payload["dashboard_kpis"]) <= 8
        assert 1 <= len(payload["chart_plan"]) <= 6
        assert 3 <= len(payload["insight_rules"]) <= 10
        assert all(
            rule["unsupported_result"] == "not_assessed"
            for rule in payload["quality_rules"]
        )
        errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
        assert not errors, f"{name}: {[error.message for error in errors]}"


def test_all_42_descriptions_measures_and_chart_roles_are_reader_safe() -> None:
    registry = load_registry()
    catalog = build_all_reader_metadata(registry, overlays=_overlays())
    approved_chart_types = {
        "line",
        "distribution",
        "coverage_heatmap",
        "seasonal_profile",
        "anomaly_heatmap",
        "change_distribution",
        "calendar_heatmap",
        "ranked_bar",
        "year_over_year",
        "composition",
        "season_curve",
        "increment",
        "milestone",
        "vintage_line",
        "revision_distribution",
        "release_depth",
        "first_latest",
        "parity",
        "missingness_bar",
        "signed_bar",
        "dual_axis",
    }
    measure_chart_types = approved_chart_types - {"coverage_heatmap", "release_depth", "missingness_bar"}
    non_measure_name = re.compile(
        r"(^|_)(available|code|count|date|day|flag|id|key|latitude|longitude|month|"
        r"num|number|period|regime|role|samples|seq|sequence|status|type|version|week|year)(_|$)",
        re.I,
    )

    for table_name, metadata in catalog.items():
        contract = registry.table(table_name)
        physical_types = {
            str(item["name"]): str(item.get("target_arrow_type") or item.get("glue_type") or "")
            for item in (*contract.get("physical_columns", ()), *contract.get("partition_keys", ()))
        }
        excluded = set(contract.get("natural_key", ())) | {
            str(item["name"]) for item in contract.get("partition_keys", ())
        }
        for column, meaning in metadata.column_descriptions.items():
            assert not re.search(
                r"source field for|source column for|retained as explanatory source context|"
                r"attribute used to distinguish records",
                meaning,
                re.I,
            ), f"{table_name}.{column}: {meaning}"
            assert len(meaning.split()) >= 4, f"{table_name}.{column}: {meaning}"
        for measure in metadata.primary_measures:
            assert measure not in excluded, f"{table_name}: key/partition routed as measure: {measure}"
            assert not non_measure_name.search(measure), f"{table_name}: counter/time routed as measure: {measure}"
            assert re.search(r"int|float|double|decimal", physical_types[measure], re.I), (
                f"{table_name}: nonnumeric primary measure: {measure} ({physical_types[measure]})"
            )
        for chart in metadata.chart_plan:
            assert chart["chart_type"] in approved_chart_types
            if chart["chart_type"] in measure_chart_types and not metadata.feature_quarantined:
                assert set(chart["columns"]) & set(metadata.primary_measures), (
                    f"{table_name}.{chart['chart_id']} has no reviewed primary measure"
                )

    assert catalog["silver_nass_crop_progress"].primary_measures == (
        "pct_planted",
        "pct_emerged",
        "pct_harvested",
        "pct_good_excellent",
    )
    assert catalog["silver_esr"].primary_measures == (
        "weekly_exports_1000mt",
        "outstanding_sales_1000mt",
    )
    assert catalog["silver_wasde"].primary_measures == ("estimate",)
    assert catalog["silver_model_predictions"].primary_measures == ()


def test_pilot_table_chart_routes_preserve_measure_semantics_and_units() -> None:
    registry = load_registry()
    catalog = build_all_reader_metadata(registry, overlays=_overlays())

    futures = catalog["silver_futures_prices"]
    assert all(
        not {"close", "log_return"}.issubset(set(chart["columns"]))
        for chart in futures.chart_plan
    )
    assert next(chart for chart in futures.chart_plan if chart["chart_id"] == "history")[
        "columns"
    ] == ["date", "close", "leviathan_slug"]

    wasde = catalog["silver_wasde"]
    for chart in wasde.chart_plan:
        assert chart["columns"][0] == "release_date"
        assert "marketing_year" in chart["columns"]
    assert "estimate" in next(
        chart for chart in wasde.chart_plan if chart["chart_id"] == "revision_distribution"
    )["columns"]

    esr = {
        chart["chart_id"]: chart for chart in catalog["silver_esr_compact"].chart_plan
    }
    assert esr["weekly_flow"]["columns"][:2] == [
        "week_ending_date",
        "weekly_exports_1000mt",
    ]
    assert esr["outstanding"]["columns"][:2] == [
        "week_ending_date",
        "outstanding_sales_1000mt",
    ]
    assert all("ingest_date" not in chart["columns"] for chart in esr.values())

    crop_progress = catalog["silver_nass_crop_progress"]
    condition = next(
        chart for chart in crop_progress.chart_plan if chart["chart_id"] == "crop_condition"
    )
    assert condition["chart_type"] == "line"
    assert "pct_good_excellent" in condition["columns"]
    assert all(
        "pct_good_excellent" not in chart["columns"]
        for chart in crop_progress.chart_plan
        if chart["chart_type"] in {"increment", "milestone"}
    )

    mpob = catalog["silver_mpob"]
    assert all(chart["chart_type"] != "composition" for chart in mpob.chart_plan)
    assert next(chart for chart in mpob.chart_plan if chart["chart_id"] == "production")[
        "columns"
    ][:2] == ["date", "production_cpo_mt"]
    assert next(chart for chart in mpob.chart_plan if chart["chart_id"] == "stocks")[
        "columns"
    ][:2] == ["date", "closing_stocks_palm_oil_mt"]
    assert {"exports_palm_oil_mt", "imports_palm_oil_mt"}.issubset(
        next(chart for chart in mpob.chart_plan if chart["chart_id"] == "trade_flows")[
            "columns"
        ]
    )
    assert mpob.units["ffb_price_myr_per_mt"] == "Malaysian ringgit per metric tonne"
    assert catalog["silver_mpob_annual"].units["ffb_price_myr_per_mt"] == (
        "Malaysian ringgit per metric tonne"
    )
    annual_charts = catalog["silver_mpob_annual"].chart_plan
    assert {chart["chart_id"] for chart in annual_charts} == {
        "annual_production",
        "annual_stocks",
        "annual_trade",
    }
    assert all(
        chart["chart_type"] == "line"
        and chart["minimum_rows"] == 2
        and chart["intentional_points"] is True
        for chart in annual_charts
    )


def test_catalog_wide_chart_interfaces_and_semantic_bans() -> None:
    catalog = build_all_reader_metadata(load_registry(), overlays=_overlays())

    for table_name, metadata in catalog.items():
        assert all(chart["chart_type"] != "composition" for chart in metadata.chart_plan)
        prohibited_measure = re.compile(r"(^|_)(available|flag|period)(_|$)")
        assert not any(prohibited_measure.search(measure) for measure in metadata.primary_measures), table_name
        if table_name != "silver_sagis_cec":
            assert not any(
                re.search(r"(^|_)revision(_|$)", measure)
                for measure in metadata.primary_measures
            ), table_name
        for chart in metadata.chart_plan:
            columns = set(chart["columns"])
            assert {
                "coverage_grain",
                "cutoff_mode",
                "max_series",
                "measure_columns",
                "series_selection",
                "split_by",
                "time_components",
                "series_dimensions",
                "unit_column",
                "measure_units",
            } <= set(chart)
            assert set(chart["time_components"]) <= columns
            assert set(chart["series_dimensions"]) <= columns
            assert set(chart["measure_units"]) <= columns
            assert set(chart["measure_columns"]) <= set(metadata.primary_measures)
            assert set(chart["measure_columns"]) <= columns
            assert 1 <= chart["max_series"] <= 12
            assert chart["series_selection"] == "most_complete"
            assert set(chart["split_by"]) <= columns
            if chart["unit_column"]:
                assert chart["unit_column"] in columns
                assert chart["unit_column"] in chart["split_by"]

    fgis = {chart["chart_id"]: chart for chart in catalog["silver_fgis"].chart_plan}
    assert "exports_mt_ctd" in fgis["cumulative_increment"]["columns"]
    assert "exports_mt_weekly" not in fgis["cumulative_increment"]["columns"]
    assert all(
        chart["columns"][0] == "week_of_marketing_year"
        and chart["time_components"] == ["week_of_marketing_year"]
        and chart["cutoff_mode"] == "governed_axis"
        for chart in fgis.values()
    )

    for table_name, cumulative in {
        "silver_sagis_weekly_deliveries": "prog_total_mt",
        "silver_sagis_weekly_exports": "prog_exports_mt",
    }.items():
        charts = catalog[table_name].chart_plan
        for chart in charts:
            assert chart["columns"][0] == "week_number"
            assert chart["time_components"] == ["week_number"]
            assert chart["cutoff_mode"] == "governed_axis"
            assert "week_ending" not in chart["columns"]
            if chart["chart_type"] in {"increment", "milestone"}:
                assert cumulative in chart["columns"]
                assert "pct_of_prior_yr" not in chart["columns"]
                assert "z_vs_3yr_avg" not in chart["columns"]

    corn = {chart["chart_id"]: chart for chart in catalog["silver_unica_corn_ethanol"].chart_plan}
    assert "total_quinzenal_kl" not in corn["cumulative_increment"]["columns"]
    assert "total_accum_kl" in corn["cumulative_increment"]["columns"]
    assert all(
        chart["columns"][0] == "position_date"
        for chart in catalog["silver_unica_biweekly_release_series"].chart_plan
    )
    for table_name in {
        "silver_unica_biweekly_season_history",
        "silver_unica_corn_ethanol",
    }:
        assert all(
            chart["columns"][0] == "fortnight_seq"
            and chart["time_components"] == ["fortnight_seq"]
            and chart["cutoff_mode"] == "governed_axis"
            and "fortnight_date" not in chart["columns"]
            for chart in catalog[table_name].chart_plan
        )

    for table_name in {
        "silver_mpoc_stock_comparison",
        "silver_mpoc_trade_stats_monthly",
        "silver_noaa_oni",
    }:
        assert any(
            chart["time_components"] == ["year", "month"]
            for chart in catalog[table_name].chart_plan
        )
        assert not any(
            chart["columns"] == ["year"] for chart in catalog[table_name].chart_plan
        )

    assert all(
        chart["chart_type"]
        not in {"vintage_line", "revision_distribution", "release_depth", "first_latest"}
        for chart in catalog["silver_conab_coffee"].chart_plan
    )
    conab_sequence = next(
        chart
        for chart in catalog["silver_conab_coffee"].chart_plan
        if chart["chart_id"] == "survey_sequence"
    )
    assert conab_sequence["time_components"] == ["survey_number"]

    for table_name in {"silver_wasde", "silver_wap_table01", "silver_wap_table01_revisions"}:
        for chart in catalog[table_name].chart_plan:
            if chart["chart_type"] in {
                "first_latest",
                "release_depth",
                "revision_distribution",
                "vintage_line",
            }:
                assert chart["columns"][0] in {"release_date", "release_month"}
            assert "marketing_year" in chart["series_dimensions"]
    assert "attribute" in catalog["silver_wasde"].chart_plan[0]["series_dimensions"]
    assert all(
        chart["unit_column"] is None
        and chart["split_by"] == []
        and chart["max_series"] <= 4
        for chart in catalog["silver_wasde"].chart_plan
    )
    assert next(
        chart
        for chart in catalog["silver_wasde"].chart_plan
        if chart["chart_id"] == "release_depth"
    )["max_series"] == 4
    assert all(
        chart["max_series"] == 1
        for chart in catalog["silver_wasde"].chart_plan
        if chart["chart_id"] != "release_depth"
    )
    assert all(
        "estimate_role" not in chart["series_dimensions"]
        for chart in catalog["silver_wasde"].chart_plan
    )
    assert {rule["insight_id"] for rule in catalog["silver_wasde"].insight_rules} >= {
        "release_coverage_span",
        "outcome_season_coverage",
    }
    wap = {chart["chart_id"]: chart for chart in catalog["silver_wap_table01"].chart_plan}
    assert {"value_distribution", "bounded_coverage"} <= set(wap)
    assert all(chart["max_series"] <= 12 for chart in wap.values())
    assert wap["bounded_coverage"]["coverage_grain"] == "year"
    assert "row_label" in catalog["silver_wap_table01_revisions"].chart_plan[0][
        "series_dimensions"
    ]

    assert catalog["silver_psd"].units["yield_mt_ha"] == "metric tonnes per hectare"
    assert catalog["silver_fred_fx"].units["brl_usd"] == (
        "Brazilian real per U.S. dollar"
    )
    production = catalog["silver_production"].chart_plan[0]
    assert production["columns"][0] == "year"
    assert production["unit_column"] == "unit"
    assert {"metric", "unit"} <= set(production["series_dimensions"])
    assert "ingest_date" not in production["columns"]
    assert all(
        chart["split_by"] == ["metric", "unit"]
        for chart in catalog["silver_production"].chart_plan
    )
    production_coverage = next(
        chart
        for chart in catalog["silver_production"].chart_plan
        if chart["chart_id"] == "coverage"
    )
    assert production_coverage["coverage_grain"] == "year"
    assert production_coverage["max_series"] == 8

    cec = {chart["chart_id"]: chart for chart in catalog["silver_sagis_cec"].chart_plan}
    assert catalog["silver_sagis_cec"].primary_measures == (
        "current_estimate_t",
        "revision_t",
        "revision_surprise",
    )
    assert all(
        "estimate_number" not in chart["series_dimensions"]
        for chart in cec.values()
    )
    assert cec["degraded_estimate_sequence"]["time_components"] == ["estimate_number"]
    assert cec["degraded_coverage"]["coverage_grain"] == "ordered"
    assert cec["degraded_estimate_sequence"]["measure_columns"] == [
        "current_estimate_t"
    ]
    assert "estimate_number" not in {
        measure
        for chart in cec.values()
        for measure in chart["measure_columns"]
    }

    assert catalog["silver_unica_biweekly_season_history"].primary_measures == (
        "cane_crushed_t",
        "sugar_produced_t",
        "ethanol_total_m3",
    )
    for table_name in {
        "silver_unica_biweekly_season_history",
        "silver_unica_corn_ethanol",
    }:
        assert "fortnight_seq" not in catalog[table_name].primary_measures
        assert all(
            "fortnight_seq" not in chart["measure_columns"]
            for chart in catalog[table_name].chart_plan
        )

    food_cpi = catalog["silver_food_cpi"].chart_plan
    assert all(
        {"country_iso", "country_name"} <= set(chart["series_dimensions"])
        for chart in food_cpi
    )

    oni = {chart["chart_id"]: chart for chart in catalog["silver_noaa_oni"].chart_plan}
    assert "season" not in oni["seasonality"]["series_dimensions"]
    assert oni["seasonality"]["time_components"] == ["year", "month"]

    tiny_tables = {
        "silver_mpoc_stock_comparison": "stock_observations",
        "silver_mpoc_trade_stats_monthly": "trade_observations",
        "silver_unica_monthly_ethanol_sales": "total_sales",
    }
    for table_name, chart_id in tiny_tables.items():
        chart = next(
            item for item in catalog[table_name].chart_plan if item["chart_id"] == chart_id
        )
        assert chart["intentional_points"] is True
        assert chart["minimum_rows"] == 2

    futures = {chart["chart_id"]: chart for chart in catalog["silver_futures_prices"].chart_plan}
    assert futures["history"]["split_by"] == ["leviathan_slug"]
    assert futures["history"]["max_series"] == 1
    assert futures["volatility"]["max_series"] == 4
    assert futures["standardized_price"]["max_series"] == 4
    assert "close" not in futures["seasonality"]["columns"]
    assert "log_return" in futures["seasonality"]["columns"]
    assert catalog["silver_futures_prices"].units["close"] == (
        "contract-native quote unit (varies by contract)"
    )
    assert any(
        "quote/unit regime break" in value
        for value in catalog["silver_futures_prices"].anti_features
    )

    nass_annual = catalog["silver_nass_annual"].chart_plan
    assert all(chart["series_dimensions"] == ["state"] for chart in nass_annual)
    assert all(chart["split_by"] == ["commodity", "country"] for chart in nass_annual)
    crop_progress = catalog["silver_nass_crop_progress"].chart_plan
    assert all(chart["columns"][0] == "week_of_year" for chart in crop_progress)
    assert all(chart["series_dimensions"] == ["year"] for chart in crop_progress)
    assert all(chart["split_by"] == ["commodity", "state"] for chart in crop_progress)
    assert all(chart["max_series"] == 4 for chart in crop_progress)
    assert all("calendar" in chart["title"].lower() for chart in crop_progress)
    crop_progress_lines = [
        chart for chart in crop_progress if chart["chart_type"] == "line"
    ]
    assert len(crop_progress_lines) == 4
    assert all(chart["max_x_gap"] == 1.0 for chart in crop_progress_lines)
    assert all(
        "lines stop at missing calendar weeks" in chart["purpose"]
        for chart in crop_progress_lines
    )
    assert catalog["silver_nass_crop_progress"].units["pct_planted"] == "percent"
    assert catalog["silver_nass_crop_progress"].units["pct_emerged"] == "percent"
    assert "same_cutoff_pace" not in {
        rule["insight_id"]
        for rule in catalog["silver_nass_crop_progress"].insight_rules
    }
    assert any(
        "crop-specific season key" in value
        for value in catalog["silver_nass_crop_progress"].anti_features
    )

    esr_raw = {chart["chart_id"]: chart for chart in catalog["silver_esr"].chart_plan}
    assert "Synthetic-backfill" in esr_raw["vintage_coverage"]["title"]
    assert "compact-only" in esr_raw["paired_parity"]["purpose"]
    assert esr_raw["weekly_flow"]["cutoff_mode"] == "within_series_ordinal"
    assert esr_raw["outstanding"]["cutoff_mode"] == "within_series_ordinal"
    for table_name, commodity_axis in {
        "silver_esr": "commodity_code",
        "silver_esr_compact": "commodity",
    }.items():
        metadata = catalog[table_name]
        charts = {chart["chart_id"]: chart for chart in metadata.chart_plan}
        for chart_id in {"weekly_flow", "outstanding"}:
            assert charts[chart_id]["series_dimensions"] == ["market_year"]
            assert charts[chart_id]["split_by"] == [
                commodity_axis,
                "country_code",
                "as_of_date",
            ]
            assert charts[chart_id]["max_series"] == 4
        assert "same_cutoff_pace" not in {
            rule["insight_id"] for rule in metadata.insight_rules
        }
        assert "categorical identifier" in metadata.column_descriptions["commodity_code"]
        assert "categorical entity identifier" in metadata.column_descriptions["country_code"]

    wasde = catalog["silver_wasde"]
    assert wasde.units["estimate"] == "attribute-specific numeric unit / verify"
    assert "not a governed numeric measurement unit" in wasde.column_descriptions["unit"]
    assert any("unit field contains page basis" in value for value in wasde.anti_features)

    assert catalog["silver_mpob"].units["exports_palm_oil_mt"] == "metric tonnes"
    assert catalog["silver_mpob"].units["imports_palm_oil_mt"] == "metric tonnes"
    for table_name in {
        "silver_sagis_weekly_deliveries",
        "silver_sagis_weekly_exports",
    }:
        assert catalog[table_name].units["pct_of_prior_yr"] == (
            "ratio to prior year (1.0 = 100%)"
        )
        pace = next(
            chart
            for chart in catalog[table_name].chart_plan
            if chart["chart_id"] == "prior_year_pace"
        )
        assert pace["title"] == "Ratio to prior-year pace"
        assert "1.10 means 110%" in pace["purpose"]

    required_series_axes = {
        "silver_fnc_colombia_exports_port_type": {"port", "coffee_type"},
        "silver_fnc_colombia_area_department": {"department"},
        "silver_unica_annual_state": {"state_region"},
        "silver_chirps": {"variable", "region"},
        "silver_cpc_soil": {"variable", "region"},
        "silver_sagis_cec": {"scope", "production_year"},
    }
    for table_name, expected in required_series_axes.items():
        observed = {
            axis
            for chart in catalog[table_name].chart_plan
            for axis in chart["series_dimensions"]
        }
        assert expected <= observed, (table_name, observed)


def test_all_42_configured_kpis_insights_and_charts_are_honestly_assessed() -> None:
    registry = load_registry()
    catalog = build_all_reader_metadata(registry, overlays=_overlays())

    for table_name, metadata in catalog.items():
        contract = registry.table(table_name)
        frame = pd.DataFrame(
            {
                item["name"]: pd.Series(dtype="object")
                for item in [
                    *(contract.get("physical_columns") or []),
                    *(contract.get("partition_keys") or []),
                ]
            }
        )
        spec = TableSpec.from_contract(contract)
        evidence = build_reader_evidence(
            frame,
            profile_frame(frame, spec),
            spec,
            metadata,
        )

        assert [item["kpi_id"] for item in evidence["dashboard_kpis"]] == [
            item["kpi_id"] for item in metadata.dashboard_kpis
        ]
        assert all(
            item["status"] in {"evaluated", "not_assessed"}
            and item["detail"]
            and item["scope"]
            for item in evidence["dashboard_kpis"]
        )
        assert [item["insight_id"] for item in evidence["reader_insights"]] == [
            item["insight_id"] for item in metadata.insight_rules
        ]
        assert all(
            item["status"] in {"evaluated", "not_assessed"}
            and item["statement"]
            and item["caveat"]
            and set(item["references"]) == {"charts", "statistics"}
            for item in evidence["reader_insights"]
        )
        assert [item["chart_id"] for item in evidence["chart_plan"]["charts"]] == [
            item["chart_id"] for item in metadata.chart_plan
        ]
        assert all(
            item["status"] in {"ready", "skipped", "not_assessed"}
            for item in evidence["chart_plan"]["charts"]
        )


def test_reader_fields_can_be_merged_into_every_table_spec() -> None:
    registry = load_registry()
    overlays = _overlays()
    validator = Draft202012Validator(_schema("table_spec.schema.json"))

    for name, overlay in overlays.items():
        metadata = build_reader_metadata(registry.table(name), overlay=overlay)
        enriched = {**overlay, **metadata.to_spec_fields()}
        errors = sorted(validator.iter_errors(enriched), key=lambda item: list(item.path))
        assert not errors, f"{name}: {[error.message for error in errors]}"


def test_table_specific_hazards_and_contract_blockers_are_preserved() -> None:
    registry = load_registry()
    overlays = _overlays()
    catalog = build_all_reader_metadata(registry, overlays=overlays)
    required_phrases = {
        "silver_chirps": "canonical silver",
        "silver_nasa_power": "canonical silver",
        "silver_esr": "2026-05-24",
        "silver_esr_compact": "feature surface",
        "silver_fred_fx": "consumer-view",
        "silver_futures_prices": "consumer-view",
        "silver_noaa_iod": "consumer-view",
        "silver_sagis_weekly_deliveries": "consumer-view",
        "silver_production": "first-partition-key",
        "silver_sagis_cec": "degraded",
        "silver_unica_biweekly_season_history": "preseason",
        "silver_mpob_annual": "inferred grain",
        "silver_wap_table01": "inferred grain",
    }
    for table_name, phrase in required_phrases.items():
        combined = " ".join(catalog[table_name].known_hazards).lower()
        assert phrase.lower() in combined

    icco = catalog["silver_icco_cocoa"]
    assert "published market balance" in icco.column_descriptions["surplus_deficit_kt"]
    assert any("do not reconstruct" in value.lower() for value in icco.anti_features)


def test_model_predictions_is_structurally_quarantined() -> None:
    registry = load_registry()
    metadata = build_reader_metadata(
        registry.table("silver_model_predictions"),
        overlay=_overlays()["silver_model_predictions"],
    )
    payload = metadata.to_dict()
    prohibited = {
        "y_actual",
        "y_pred",
        "zero_anomaly_baseline",
        "prior_year_anomaly_baseline",
        "trailing_mean_anomaly_baseline",
        "trailing_trend_anomaly_baseline",
    }
    referenced = {
        column
        for section in ("dashboard_kpis", "chart_plan", "insight_rules")
        for item in payload[section]
        for column in item["columns"]
    }

    assert metadata.archetype == ReaderArchetype.GENERATED_OUTPUT_QUARANTINE
    assert metadata.feature_quarantined is True
    assert metadata.primary_measures == ()
    assert prohibited.isdisjoint(referenced)
    assert any("prohibited" in value.lower() for value in metadata.anti_features)
    assert any("excluded_leakage" in value for value in metadata.known_hazards)


def test_summary_and_manifest_schemas_accept_reader_evidence() -> None:
    registry = load_registry()
    contract = registry.table("silver_icco_cocoa")
    metadata = build_reader_metadata(
        contract,
        overlay=_overlays()["silver_icco_cocoa"],
    )
    frame = pd.DataFrame(
        {
            item["name"]: pd.Series(dtype="object")
            for item in [
                *(contract.get("physical_columns") or []),
                *(contract.get("partition_keys") or []),
            ]
        }
    )
    spec = TableSpec.from_contract(contract)
    reader = build_reader_evidence(
        frame,
        profile_frame(frame, spec),
        spec,
        metadata,
    )
    summary = {
        "schema_version": "leviathan.silver-eda-summary/v1",
        "table_name": "silver_icco_cocoa",
        "analysis_scope": {
            "source_layer": "silver",
            "legacy_gold_read": False,
            "model_ready_read": False,
            "target_aware_analysis": False,
            "production_feature_config_mutated": False,
        },
        "decision_capsule": {},
        "profile": {
            "table_name": "silver_icco_cocoa",
            "analysis_exactness": "exact",
            "disposition": "ready_for_feature_ideation",
            "sections": {},
            "findings": [],
            "blockers": [],
        },
        "feature_candidates": [],
        "feature_opportunity_map": {},
        "provenance": {},
        "reader": reader,
    }
    summary_errors = list(
        Draft202012Validator(_schema("summary.schema.json")).iter_errors(summary)
    )
    assert not summary_errors, [error.message for error in summary_errors]

    base_uri = (
        "s3://bucket/eda/silver/campaign_id=20260718T000000Z_deadbeef/"
        "table=silver_icco_cocoa/"
    )

    def artifact(relative_key: str) -> dict:
        return {
            "relative_key": relative_key,
            "uri": base_uri + relative_key,
            "bytes": 1,
            "sha256": "f" * 64,
        }

    manifest = {
        "schema_version": "leviathan.silver-eda-campaign/v2",
        "campaign_id": None,
        "table_name": "silver_icco_cocoa",
        "source_layer": "silver",
        "analysis_complete": False,
        "contract_sha256": "1" * 64,
        "spec_sha256": "2" * 64,
        "detailed_evidence": {
            "source_inventory": artifact("_machine/source_inventory.json"),
            "coverage_catalog": artifact("_machine/coverage_catalog.json"),
            "sampling_evidence": artifact("_machine/sampling_evidence.json"),
            "reader_evidence": artifact("_machine/reader_evidence.json"),
        },
    }
    manifest_errors = list(
        Draft202012Validator(_schema("manifest.schema.json")).iter_errors(manifest)
    )
    assert not manifest_errors, [error.message for error in manifest_errors]
