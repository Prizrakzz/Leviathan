from __future__ import annotations

from pathlib import Path

import pytest
# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import yaml

from leviathan.eda.config import eda_threshold_section, load_eda_thresholds
from leviathan.eda.inventory import DEFAULT_FRAGMENT_CAP
from leviathan.eda.notebooks import NOTEBOOK_SIZE_LIMIT_BYTES
from leviathan.eda.reader import (
    DEFAULT_ANALYSIS_ROW_LIMIT,
    DEFAULT_FULL_COMPRESSED_BYTE_LIMIT,
    DEFAULT_FULL_ROW_LIMIT,
)


def test_repository_thresholds_drive_runtime_limits() -> None:
    inventory = eda_threshold_section("inventory")
    notebook = eda_threshold_section("notebook")
    reader = eda_threshold_section("reader")

    assert DEFAULT_FRAGMENT_CAP == inventory["fragment_cap"] == 25_000
    assert DEFAULT_FULL_ROW_LIMIT == inventory["full_frame_max_rows"] == 5_000_000
    assert (
        DEFAULT_FULL_COMPRESSED_BYTE_LIMIT
        == inventory["full_frame_max_compressed_bytes"]
        == 2 * 1024**3
    )
    assert DEFAULT_ANALYSIS_ROW_LIMIT == inventory["sample_max_rows"] == 1_000_000
    assert NOTEBOOK_SIZE_LIMIT_BYTES == notebook["max_bytes"] == 8 * 1024**2
    assert reader == {
        "full_dataframe_max_rows": 200,
        "preview_max_rows": 40,
        "max_charts": 4,
        "min_trend_points": 8,
        "min_scatter_points": 20,
        "min_insights": 3,
        "max_insights": 10,
        "embedded_replica_max_bytes": 512 * 1024,
    }


def test_invalid_threshold_schema_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 999, "inventory": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported thresholds schema_version"):
        load_eda_thresholds(str(path))
