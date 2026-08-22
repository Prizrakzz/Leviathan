from __future__ import annotations

import asyncio
import warnings
from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import nbformat
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.eda.campaign import build_table_overlay
from leviathan.eda.candidates import generate_feature_candidates
from leviathan.eda.models import Exactness, TableSpec
from leviathan.eda.notebooks import (
    SILVER_SECTIONS,
    NotebookContractError,
    build_silver_notebook,
    execute_notebook,
    read_and_validate_notebook,
    validate_silver_notebook,
)
from leviathan.eda.profiling import profile_frame
from leviathan.eda.render import render_summary
from leviathan.silver.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _payload(tmp_path: Path, *, row_count: int = 24):
    contract = load_registry().table("silver_fred_fx")
    spec = TableSpec.from_contract(contract)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=row_count, freq="MS"),
            "brl_usd": [5.0 + index / 20 for index in range(row_count)],
            "brl_usd_pct_change_90d": [index / 100 for index in range(row_count)],
            "ars_usd": [800.0 + index for index in range(row_count)],
            "ars_usd_pct_change_90d": [index / 80 for index in range(row_count)],
            "cny_usd": [7.0 + index / 100 for index in range(row_count)],
            "cny_usd_pct_change_90d": [index / 120 for index in range(row_count)],
            "source": ["FRED"] * row_count,
        }
    )
    profile = profile_frame(frame, spec, exactness=Exactness.EXACT)
    candidates = generate_feature_candidates(frame, profile, spec)
    summary = render_summary(profile, candidates, {"campaign_id": "unit"})
    overlay = build_table_overlay(contract, repo_root=REPO_ROOT)
    parquet = tmp_path / "frame.parquet"
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), parquet)
    return contract, overlay, summary, parquet


def _rendered_text(notebook: nbformat.NotebookNode) -> str:
    chunks: list[str] = []
    for cell in notebook.cells:
        if cell.cell_type == "markdown":
            chunks.append(str(cell.source))
        for output in cell.get("outputs", []):
            data = output.get("data", {})
            chunks.extend(
                str(data[mime])
                for mime in ("text/plain", "text/markdown", "text/html")
                if mime in data
            )
    return "\n".join(chunks)


def test_silver_notebook_has_stable_mandatory_sections(tmp_path: Path) -> None:
    contract, overlay, summary, parquet = _payload(tmp_path)
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit"},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    ids = {cell.id for cell in notebook.cells}
    assert {cell_id for cell_id, _ in SILVER_SECTIONS} <= ids
    assert len(ids) == len(notebook.cells)
    assert notebook.metadata.leviathan_eda.source_only is True
    assert notebook.metadata.leviathan_eda.reader_contract_version == 1
    chart_cells = [
        cell.source
        for cell in notebook.cells
        if cell.cell_type == "code" and "plt.show()" in cell.source
    ]
    assert chart_cells
    assert all(
        "EXACTNESS" in source or "— exact" in source
        for source in chart_cells
    )
    setup = next(cell for cell in notebook.cells if cell.id == "parameters-and-setup")
    assert '"figure.dpi": 120' in setup.source
    assert "FULL_DISPLAY_MAX_ROWS = 200" in setup.source
    assert "BOUNDED_PREVIEW_MAX_ROWS = 40" in setup.source
    assert "MAX_READER_CHARTS = 4" in setup.source
    assert "MIN_SCATTER_POINTS = 20" in setup.source
    assert "def deterministic_preview" in setup.source
    assert "def column_dictionary" in setup.source
    assert "def rate_display" in setup.source
    assert 'READER.get("source_aggregates"' in setup.source
    assert "exact full-source aggregate" in setup.source
    decision = next(cell for cell in notebook.cells if cell.id == "decision-capsule-output")
    assert "severe_findings" in decision.source
    assert "Feature-readiness disposition" in decision.source
    candidates = next(cell for cell in notebook.cells if cell.id == "feature-opportunity-output")
    assert "seen_surfaces" in candidates.source
    coverage = next(cell for cell in notebook.cells if cell.id == "entity-vocabulary-output")
    assert "configured_entity_columns" in coverage.source
    missingness = next(cell for cell in notebook.cells if cell.id == "missingness-validity-output")
    assert "numeric output-value validity is quarantined" in missingness.source
    pit = next(cell for cell in notebook.cells if cell.id == "pit-leakage-output")
    assert "must not be read as historical availability" in pit.source
    rendered_source = _rendered_text(notebook)
    assert "TL;DR and readiness dashboard" in rendered_source
    assert "The data: row meaning, shape, and columns" in rendered_source
    assert "Ordinary descriptive statistics" in rendered_source
    assert "What the data says" in rendered_source
    assert "PIT and leakage" in rendered_source
    assert "Feature opportunities and anti-features" in rendered_source
    assert "Compact provenance" in rendered_source


def test_notebook_rejects_candidate_reference_to_missing_cell(tmp_path: Path) -> None:
    contract, overlay, summary, parquet = _payload(tmp_path)
    assert summary["feature_candidates"]
    summary["feature_candidates"][0]["evidence"].append("cell:does-not-exist")

    with pytest.raises(NotebookContractError, match="missing notebook cell"):
        build_silver_notebook(
            summary=summary,
            overlay=overlay,
            contract=contract,
            provenance={"campaign_id": "unit"},
            frame_uri=str(parquet),
            manifest_uri=None,
        )


def test_output_plane_rejects_value_distribution_or_correlation_payload(
    tmp_path: Path,
) -> None:
    _contract, _overlay, summary, _parquet = _payload(tmp_path)
    output_contract = load_registry().table("silver_model_predictions")
    output_overlay = build_table_overlay(output_contract, repo_root=REPO_ROOT)
    summary["table_name"] = "silver_model_predictions"
    summary["profile"]["table_name"] = "silver_model_predictions"
    summary["profile"]["disposition"] = "excluded_leakage"
    summary["feature_candidates"] = []
    summary["profile"]["sections"]["distributions"]["metrics"][
        "numeric_distributions"
    ]["value"] = {"y_actual": {"count": 10, "mean": 1.0}}

    with pytest.raises(NotebookContractError, match="prohibited value"):
        build_silver_notebook(
            summary=summary,
            overlay=output_overlay,
            contract=output_contract,
            provenance={"campaign_id": "unit"},
            frame_uri=None,
            manifest_uri=None,
        )


def test_sparse_notebook_accepts_visible_no_chart_rationale(tmp_path: Path) -> None:
    contract, overlay, summary, _parquet = _payload(tmp_path)
    summary["decision_capsule"]["row_count"]["value"] = 0
    sections = summary["profile"]["sections"]
    sections["schema_contract"]["metrics"]["row_count"]["value"] = 0
    sections["distributions"]["metrics"]["numeric_distributions"]["value"] = {}
    sections["temporal_structure"]["metrics"]["temporal_columns"]["value"] = {}
    sections["entity_vocabulary_coverage"]["metrics"]["vocabularies"]["value"] = {}
    sections["missingness_validity"]["metrics"]["column_missingness"]["value"] = {}
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit"},
        frame_uri=None,
        manifest_uri=None,
    )
    for index, cell in enumerate(notebook.cells, start=1):
        if cell.cell_type == "code":
            cell.execution_count = index
    chart_cell = next(
        cell for cell in notebook.cells if cell.id == "temporal-structure-output"
    )
    chart_cell.outputs = [
        nbformat.v4.new_output(
            "display_data",
            data={"text/markdown": "**No chart shown:** no analyzed rows."},
        )
    ]
    validate_silver_notebook(
        notebook,
        table_name="silver_fred_fx",
        campaign_id="unit",
        require_executed=True,
    )
    chart_cell.outputs = []
    with pytest.raises(NotebookContractError, match="no visible no-chart rationale"):
        validate_silver_notebook(
            notebook,
            table_name="silver_fred_fx",
            campaign_id="unit",
            require_executed=True,
        )


def test_nonblocked_nonempty_notebook_cannot_replace_chart_with_generic_rationale(
    tmp_path: Path,
) -> None:
    contract, overlay, summary, parquet = _payload(tmp_path)
    summary["profile"]["blockers"] = []
    summary["profile"]["disposition"] = "ready_for_feature_ideation"
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit"},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    for index, cell in enumerate(notebook.cells, start=1):
        if cell.cell_type == "code":
            cell.execution_count = index
    chart_cell = next(
        cell for cell in notebook.cells if cell.id == "temporal-structure-output"
    )
    chart_cell.outputs = [
        nbformat.v4.new_output(
            "display_data",
            data={"text/markdown": "**No chart shown:** generic omission."},
        )
    ]
    with pytest.raises(NotebookContractError, match="lacks a data-supported chart"):
        validate_silver_notebook(
            notebook,
            table_name="silver_fred_fx",
            campaign_id="unit",
            require_executed=True,
        )


def test_silver_notebook_executes_top_to_bottom(
    tmp_path: Path, monkeypatch,
) -> None:
    # Match the dedicated Batch job definition. The notebook must explicitly
    # switch the headless kernel to the inline capture backend.
    monkeypatch.setenv("MPLBACKEND", "Agg")
    contract, overlay, summary, parquet = _payload(tmp_path)
    summary["reader"] = {
        "source_rows": 24,
        "analysis_rows": 24,
        "source_shape": {
            "source_shape": [24, 8],
            "analysis_shape": [24, 8],
            "column_count": 8,
        },
        "df_info_text": "reader-provided df.info evidence",
        "column_dictionary": [
            {
                "column": "brl_usd",
                "declared_type": "float64",
                "observed_dtype": "float64",
                "unit": "BRL per USD",
                "example": 5.0,
                "null_rate": 0.0,
                "distinct_count": 24,
                "meaning": "Brazilian real exchange rate.",
                "why_it_matters": "Affects Brazilian commodity pricing incentives.",
            }
        ],
        "ordinary_statistics": {
            "status": "ready",
            "numeric": {
                "records": [{"column": "brl_usd", "count": 24, "mean": 5.575}]
            },
        },
        "quality_scorecard": {
            "overall_status": "pass",
            "checks": [
                {
                    "check_id": "grain",
                    "check": "Declared grain",
                    "status": "pass",
                    "summary": "All 24 dates are unique.",
                }
            ],
        },
        "reader_insights": [
            {
                "insight_id": "reader-test",
                "title": "Coverage",
                "statement": "Reader evidence covers all 24 monthly observations.",
                "evidence": ["source_shape"],
            }
        ],
        "notable_rows": {
            "status": "ready",
            "records": [
                {
                    "reasons": ["latest row"],
                    "row": {"date": "2025-12-01", "brl_usd": 6.15},
                }
            ],
        },
        "chart_plan": {
            "ready_chart_count": 1,
            "charts": [
                {
                    "chart_id": "fx-levels",
                    "chart_type": "line",
                    "title": "BRL/USD over time",
                    "columns": ["date", "brl_usd"],
                    "status": "ready",
                    "minimum_rows": 8,
                }
            ],
        },
        "pit_summary": {
            "status": "blocked",
            "explanation": "Publication lag is not governed.",
            "use_rule": "Do not use without a cutoff rule.",
        },
    }
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit", "object_count": 1},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    event_loop_policy = asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        output = execute_notebook(notebook, tmp_path / "executed.ipynb", cwd=tmp_path)
    assert asyncio.get_event_loop_policy() is event_loop_policy
    checked = read_and_validate_notebook(
        output,
        table_name="silver_fred_fx",
        campaign_id="unit",
        require_executed=True,
    )
    with pytest.raises(NotebookContractError, match="campaign mismatch"):
        read_and_validate_notebook(
            output,
            table_name="silver_fred_fx",
            campaign_id="another-campaign",
            require_executed=True,
        )
    assert output.stat().st_size < 8 * 1024 * 1024
    assert not any(
        result.get("output_type") == "error"
        for cell in checked.cells
        if cell.cell_type == "code"
        for result in cell.get("outputs", [])
    )
    assert all(
        cell.execution_count is not None
        for cell in checked.cells
        if cell.cell_type == "code"
    )
    embedded_charts = [
        output
        for cell in checked.cells
        if cell.cell_type == "code"
        for output in cell.get("outputs", [])
        if {"image/png", "image/svg+xml", "image/jpeg"}.intersection(
            output.get("data", {})
        )
    ]
    assert 1 <= len(embedded_charts) <= 6
    runtime_manifests = [
        result["data"]["application/vnd.leviathan.chart-manifest+json"]
        for cell in checked.cells
        if cell.cell_type == "code"
        for result in cell.get("outputs", [])
        if "application/vnd.leviathan.chart-manifest+json" in result.get("data", {})
    ]
    assert len(runtime_manifests) == 1
    assert runtime_manifests[0]
    assert all(
        {
            "aggregation",
            "analysis_rows",
            "chart_id",
            "exactness",
            "plotted_rows",
            "reason",
            "scope",
            "source_rows",
            "status",
            "title",
            "unit",
        }
        <= set(item)
        for item in runtime_manifests[0]
    )
    assert any(item["status"] == "ready" for item in runtime_manifests[0])
    rendered = _rendered_text(checked)
    assert "Full DataFrame: all 24 analyzed rows are shown." in rendered
    assert "24 x 8" in rendered
    assert "plain_English_meaning" in rendered
    assert "performs no target analysis" in rendered.lower()
    assert "reader-provided df.info evidence" in rendered
    assert "Reader evidence covers all 24 monthly observations." in rendered
    assert "All 24 dates are unique." in rendered
    # The notebook remains a valid v4 artifact after execution and serialization.
    nbformat.validate(checked)


def test_exact_small_dataframe_renders_all_113_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    contract, overlay, summary, parquet = _payload(tmp_path, row_count=113)
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit", "object_count": 1},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    output = execute_notebook(
        notebook,
        tmp_path / "executed-113.ipynb",
        cwd=tmp_path,
    )
    checked = read_and_validate_notebook(
        output,
        table_name="silver_fred_fx",
        campaign_id="unit",
        require_executed=True,
    )
    data_cell = next(
        cell for cell in checked.cells if cell.id == "contract-row-meaning-output"
    )
    html_tables = [
        str(result["data"]["text/html"])
        for result in data_cell.get("outputs", [])
        if "text/html" in result.get("data", {})
    ]
    preview_html = next(table for table in html_tables if "<th>112</th>" in table)
    assert preview_html.count("<tr") == 114
    assert "Full DataFrame: all 113 analyzed rows are shown." in _rendered_text(checked)


def test_high_cardinality_nass_plan_selects_complete_series_without_generic_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    contract = load_registry().table("silver_nass_annual")
    spec = TableSpec.from_contract(contract)
    rows = []
    for state_index in range(14):
        for year in range(2016, 2024):
            rows.append(
                {
                    "area_harvested_cv_pct": 1.5,
                    "area_harvested_ha": 900 + state_index * 10,
                    "area_planted_cv_pct": 1.4,
                    "area_planted_ha": 1_000 + state_index * 10,
                    "commodity": "corn",
                    "country": "United States",
                    "leviathan_slug": "corn",
                    "marketing_year": year,
                    "production_cv_pct": 2.0,
                    "production_mt": 5_000 + state_index * 100 + year,
                    "source": "synthetic fixture",
                    "state": f"S{state_index:02d}",
                    "year": year,
                    "yield_cv_pct": 1.2,
                    "yield_t_ha": 5.0 + state_index / 10,
                }
            )
    frame = pd.DataFrame(rows)
    profile = profile_frame(frame, spec, exactness=Exactness.EXACT)
    candidates = generate_feature_candidates(frame, profile, spec)
    summary = render_summary(profile, candidates, {"campaign_id": "unit"})
    summary["reader"] = {
        "analysis_rows": len(frame),
        "chart_plan": {
            "ready_chart_count": 1,
            "charts": [
                {
                    "chart_id": "history",
                    "chart_type": "line",
                    "columns": ["year", "production_mt", "commodity", "state"],
                    "measure_units": {"production_mt": "metric tonnes"},
                    "series_dimensions": ["commodity", "state"],
                    "status": "ready",
                    "title": "Production history by state",
                }
            ],
        },
        "primary_measures": ["production_mt"],
        "source_rows": len(frame),
        "source_shape": {
            "analysis_shape": list(frame.shape),
            "column_count": frame.shape[1],
            "source_shape": list(frame.shape),
        },
    }
    overlay = build_table_overlay(contract, repo_root=REPO_ROOT)
    parquet = tmp_path / "nass-frame.parquet"
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), parquet)
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit", "object_count": 1},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    output = execute_notebook(
        notebook,
        tmp_path / "executed-nass.ipynb",
        cwd=tmp_path,
    )
    checked = read_and_validate_notebook(
        output,
        table_name="silver_nass_annual",
        campaign_id="unit",
        require_executed=True,
    )
    rendered = _rendered_text(checked)
    assert "No chart shown:" not in rendered
    assert "selected 12 of 14 complete semantic series" in rendered
    assert "excluded series=2" in rendered
    assert "no pooling" in rendered
    assert "Chart execution manifest" in rendered
    assert "Selected measures over year" not in rendered
    assert "Distribution of production_mt" not in rendered


def test_tiny_exact_mpob_annual_executes_with_reviewed_history_chart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    contract = load_registry().table("silver_mpob_annual")
    spec = TableSpec.from_contract(contract)
    frame = pd.DataFrame(
        {
            "closing_stocks_palm_oil_mt": np.arange(6) * 20_000 + 1_500_000,
            "commodity": ["palm_oil"] * 6,
            "exports_palm_oil_mt": np.arange(6) * 40_000 + 15_000_000,
            "ffb_price_myr_per_mt": np.arange(6) * 20 + 500,
            "imports_palm_oil_mt": np.arange(6) * 10_000 + 1_000_000,
            "production_cpo_mt": np.arange(6) * 100_000 + 17_000_000,
            "source": ["synthetic fixture"] * 6,
            "su_ratio": np.arange(6) / 100 + 0.08,
            "year": np.arange(2018, 2024),
        }
    )
    profile = profile_frame(frame, spec, exactness=Exactness.EXACT)
    candidates = generate_feature_candidates(frame, profile, spec)
    summary = render_summary(profile, candidates, {"campaign_id": "unit"})
    summary["reader"] = {
        "analysis_rows": 6,
        "chart_plan": {
            "ready_chart_count": 1,
            "charts": [
                {
                    "chart_id": "measure_history",
                    "chart_type": "line",
                    "columns": ["year", "production_cpo_mt", "commodity"],
                    "intentional_points": True,
                    "measure_units": {"production_cpo_mt": "metric tonnes"},
                    "minimum_rows": 2,
                    "series_dimensions": ["commodity"],
                    "status": "ready",
                    "title": "Annual crude palm-oil production",
                }
            ],
        },
        "primary_measures": ["production_cpo_mt"],
        "source_rows": 6,
        "source_shape": {
            "analysis_shape": list(frame.shape),
            "column_count": frame.shape[1],
            "source_shape": list(frame.shape),
        },
    }
    overlay = build_table_overlay(contract, repo_root=REPO_ROOT)
    parquet = tmp_path / "mpob-annual-frame.parquet"
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), parquet)
    notebook = build_silver_notebook(
        summary=summary,
        overlay=overlay,
        contract=contract,
        provenance={"campaign_id": "unit", "object_count": 1},
        frame_uri=str(parquet),
        manifest_uri=None,
    )
    output = execute_notebook(
        notebook,
        tmp_path / "executed-mpob-annual.ipynb",
        cwd=tmp_path,
    )
    checked = read_and_validate_notebook(
        output,
        table_name="silver_mpob_annual",
        campaign_id="unit",
        require_executed=True,
    )
    embedded_charts = [
        result
        for cell in checked.cells
        if cell.cell_type == "code"
        for result in cell.get("outputs", [])
        if {"image/png", "image/svg+xml", "image/jpeg"}.intersection(
            result.get("data", {})
        )
    ]
    assert len(embedded_charts) == 1
    assert "No chart shown:" not in _rendered_text(checked)
