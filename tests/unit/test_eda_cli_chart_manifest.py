from __future__ import annotations

from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import nbformat
import pytest

from leviathan.eda.cli import (
    CampaignError,
    _bind_runtime_chart_manifest,
    _extract_runtime_chart_manifest,
)

MIME = "application/vnd.leviathan.chart-manifest+json"


def _row(
    *,
    chart_id: str = "history",
    status: str = "ready",
    exactness: str = "exact",
    plotted_rows: int = 8,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "aggregation": "median within duplicate positions" if status == "ready" else None,
        "analysis_rows": 100,
        "chart_id": chart_id,
        "exactness": exactness,
        "plotted_rows": plotted_rows,
        "reason": reason,
        "scope": "complete semantic series; no pooling",
        "source_rows": 120,
        "status": status,
        "title": "History",
        "unit": "metric tonnes" if status == "ready" else None,
    }


def _write_notebook(path: Path, rows: list[dict[str, object]]) -> Path:
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "pass",
                outputs=[
                    nbformat.v4.new_output(
                        "display_data",
                        data={MIME: rows, "text/plain": "runtime chart manifest"},
                    )
                ],
                execution_count=1,
            )
        ]
    )
    nbformat.write(notebook, path)
    return path


@pytest.mark.parametrize("exactness", ["exact", "exact full-source aggregate"])
def test_runtime_manifest_binds_actual_frame_and_aggregate_counts(
    tmp_path: Path,
    exactness: str,
) -> None:
    rows = [
        _row(exactness=exactness, plotted_rows=12),
        _row(
            chart_id="underpowered",
            status="omitted",
            exactness=exactness,
            plotted_rows=0,
            reason="No complete series.",
        ),
    ]
    path = _write_notebook(tmp_path / "executed.ipynb", rows)
    summary = {
        "table_name": "silver_wasde",
        "reader": {
            "display_policy": {"plotted_rows": None},
            "source_shape": {"plotted_rows": None},
        },
    }

    manifest = _bind_runtime_chart_manifest(summary, path)

    assert manifest == rows
    reader = summary["reader"]
    assert reader["chart_manifest"] == rows
    assert reader["ready_chart_count"] == 1
    assert reader["omitted_chart_count"] == 1
    assert reader["chart_omission_reasons"] == ["No complete series."]
    assert reader["plotted_rows"] == 12
    assert reader["source_shape"]["plotted_rows"] == 12
    assert reader["display_policy"]["plotted_rows"] == 12
    assert reader["chart_execution"]["status"] == "complete"


def test_model_output_quarantine_accepts_only_omitted_runtime_payload(
    tmp_path: Path,
) -> None:
    omitted = _row(
        chart_id="output_quarantine",
        status="omitted",
        plotted_rows=0,
        reason="Generated-output leakage quarantine.",
    )
    path = _write_notebook(tmp_path / "quarantined.ipynb", [omitted])
    summary = {"table_name": "silver_model_predictions", "reader": {}}
    _bind_runtime_chart_manifest(summary, path)
    assert summary["reader"]["ready_chart_count"] == 0
    assert summary["reader"]["plotted_rows"] == 0

    ready_path = _write_notebook(tmp_path / "unsafe.ipynb", [_row()])
    with pytest.raises(CampaignError, match="prohibited ready chart"):
        _bind_runtime_chart_manifest(
            {"table_name": "silver_model_predictions", "reader": {}},
            ready_path,
        )


def test_runtime_manifest_rejects_missing_or_inconsistent_payloads(
    tmp_path: Path,
) -> None:
    missing_field = _row()
    missing_field.pop("unit")
    path = _write_notebook(tmp_path / "missing.ipynb", [missing_field])
    with pytest.raises(CampaignError, match="missing=.*unit"):
        _extract_runtime_chart_manifest(path)

    inconsistent = _row(status="omitted", plotted_rows=3, reason="omitted")
    path = _write_notebook(tmp_path / "inconsistent.ipynb", [inconsistent])
    with pytest.raises(CampaignError, match="reports plotted rows"):
        _extract_runtime_chart_manifest(path)
