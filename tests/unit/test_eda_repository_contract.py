from __future__ import annotations

import json
from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import nbformat
import yaml

from leviathan.eda.notebooks import SILVER_SECTIONS, validate_silver_notebook
from leviathan.silver.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
EDA_ROOT = REPO_ROOT / "eda"


def test_repository_has_exactly_one_dossier_per_current_silver() -> None:
    registry = load_registry()
    expected = {
        name for name in registry.names() if registry.table(name).get("layer") == "silver"
    }
    actual = {
        path.name
        for path in EDA_ROOT.iterdir()
        if path.is_dir() and path.name.startswith("silver_")
    }
    assert len(expected) == 42
    assert actual == expected
    assert "gold_weather_z" not in actual
    assert not any(path.name.startswith("gold_") for path in EDA_ROOT.iterdir())

    for table in sorted(expected):
        directory = EDA_ROOT / table
        required = {
            "spec.yaml",
            f"{table}_eda.ipynb",
            "summary.json",
            "manifest.json",
            "feature_candidates.yaml",
        }
        assert required <= {path.name for path in directory.iterdir() if path.is_file()}
        spec = yaml.safe_load((directory / "spec.yaml").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert spec["table_name"] == table
        assert manifest["table_name"] == table
        assert manifest["source_layer"] == "silver"
        notebook = nbformat.read(directory / f"{table}_eda.ipynb", as_version=4)
        validate_silver_notebook(
            notebook, table_name=table, require_executed=False
        )
        ids = {cell.id for cell in notebook.cells}
        assert {cell_id for cell_id, _ in SILVER_SECTIONS} <= ids


def test_scaffold_model_predictions_is_quarantined() -> None:
    summary = json.loads(
        (EDA_ROOT / "silver_model_predictions" / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    candidates = yaml.safe_load(
        (EDA_ROOT / "silver_model_predictions" / "feature_candidates.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert summary["profile"]["disposition"] == "excluded_leakage"
    assert candidates["candidate_count"] == 0


def test_icco_reference_sidecars_match_the_embedded_exact_frame() -> None:
    directory = EDA_ROOT / "silver_icco_cocoa"
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    candidates = yaml.safe_load(
        (directory / "feature_candidates.yaml").read_text(encoding="utf-8")
    )
    spec = yaml.safe_load((directory / "spec.yaml").read_text(encoding="utf-8"))

    assert summary["decision_capsule"]["row_count"]["value"] == 15
    assert summary["reader"]["source_shape"]["source_shape"] == [15, 10]
    assert summary["reader"]["display_policy"]["mode"] == "full_dataframe"
    assert len(summary["reader"]["reader_insights"]) >= 3
    assert candidates["candidate_count"] == 5
    assert len(summary["feature_candidates"]) == candidates["candidate_count"]
    assert manifest["status"] == "executed_reference_not_campaign"
    assert manifest["analysis_complete"] is False
    assert spec["archetype"] == "annual_geographic_production"
