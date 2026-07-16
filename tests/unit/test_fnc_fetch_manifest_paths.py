"""Manifest-path resolution guard for the FNC Colombia fetch scripts.

Both ``jobs/ingest/fetch_fnc_excel.py`` and ``jobs/ingest/fetch_fnc_pdf.py``
derive ``_MANIFEST_PATH`` from ``Path(__file__)`` relative to the repo root.
The scripts live two directories deep (``jobs/ingest/<script>.py``), so reaching
the top-level ``configs/`` tree needs THREE ``.parent`` hops -- one short and the
path silently resolves to a non-existent ``jobs/configs/...`` and the fetch dies
with a deterministic FileNotFoundError (the fnc_colombia Wave-1 canary break).

These tests load each script by file path and assert the *real* module constant
resolves to an existing file directly under ``<repo>/configs/sources/``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# tests/unit/<this file> -> tests/unit -> tests -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

# (module name, script path relative to repo root, expected manifest filename)
_FNC_FETCHERS = [
    ("fetch_fnc_excel", "jobs/ingest/fetch_fnc_excel.py", "fnc_excel_sources.yaml"),
    ("fetch_fnc_pdf", "jobs/ingest/fetch_fnc_pdf.py", "fnc_reports.yaml"),
]


def _load_manifest_path(module_name: str, script_rel: str) -> Path:
    """Exec the fetch script by file path and return its ``_MANIFEST_PATH``."""
    spec = importlib.util.spec_from_file_location(module_name, _REPO_ROOT / script_rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # not registered in sys.modules -- no pollution
    return module._MANIFEST_PATH


@pytest.mark.parametrize(
    "module_name,script_rel,manifest_name",
    _FNC_FETCHERS,
    ids=[m for m, _, _ in _FNC_FETCHERS],
)
def test_fnc_manifest_path_resolves_under_repo_configs(
    module_name: str, script_rel: str, manifest_name: str
) -> None:
    manifest = _load_manifest_path(module_name, script_rel).resolve()

    # The file the fetcher reads must actually exist ...
    assert manifest.exists(), f"{module_name}._MANIFEST_PATH does not exist: {manifest}"
    # ... at the canonical top-level configs/sources location ...
    assert manifest == (_REPO_ROOT / "configs" / "sources" / manifest_name).resolve()
    # ... and never under jobs/ (the one-hop-short regression signature).
    assert (_REPO_ROOT / "jobs") not in manifest.parents
