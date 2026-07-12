"""SILVER-F082: incident-runbook completeness lint.

The lint passes on the delivered runbook and fails (with a precise gap) when a DAG-catalog family
row, a required failure-mode section, or an alarm's runbook anchor is missing.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LINT = _REPO / "scripts" / "silver" / "f082_runbook_lint.py"
_RUNBOOK = _REPO / "reports" / "silver_readiness" / "R4_incident_runbooks.md"


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("f082_runbook_lint", _LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSlug:
    def test_github_style_slug(self, lint):
        assert lint.gh_slug("Batch job failed") == "batch-job-failed"
        assert lint.gh_slug("Freshness SLA breach") == "freshness-sla-breach"
        # a dropped '/' between spaces yields a double hyphen (GitHub behaviour).
        assert lint.gh_slug("Value-census failure (all-NaN / collapsed vintage)") == \
            "value-census-failure-all-nan--collapsed-vintage"


class TestDeliveredRunbook:
    def test_the_delivered_runbook_is_complete(self, lint):
        r = lint.lint(_RUNBOOK)
        assert r["complete"] is True, r
        assert r["missing_failure_modes"] == []
        assert r["missing_families"] == []
        assert r["dangling_alarm_anchors"] == []

    def test_every_dag_family_has_a_row(self, lint):
        from leviathan.silver.dag_catalog import build_catalog
        md = _RUNBOOK.read_text(encoding="utf-8")
        rows = lint.parse_family_rows(md)
        for key in build_catalog():
            assert key in rows, f"family {key} has no runbook row"


class TestGapDetection:
    def _write(self, tmp_path, body: str) -> Path:
        p = tmp_path / "rb.md"
        p.write_text(body, encoding="utf-8")
        return p

    def test_missing_family_row_fails(self, lint, tmp_path):
        # a runbook with every failure-mode heading but NO family rows.
        headings = "\n".join(f"## {t}\n\nbody\n" for t in lint.REQUIRED_FAILURE_MODES)
        r = lint.lint(self._write(tmp_path, headings))
        assert r["complete"] is False
        assert len(r["missing_families"]) == r["families_in_catalog"]

    def test_missing_failure_mode_section_fails(self, lint, tmp_path):
        from leviathan.silver.dag_catalog import build_catalog
        # all family rows, but drop one required failure-mode section.
        rows = "\n".join(f"| `{k}` | x | y | z | 3d | yes |" for k in build_catalog())
        headings = "\n".join(f"## {t}\n" for t in lint.REQUIRED_FAILURE_MODES[1:])  # drop the first
        r = lint.lint(self._write(tmp_path, rows + "\n" + headings))
        assert r["complete"] is False
        assert lint.REQUIRED_FAILURE_MODES[0] in r["missing_failure_modes"]

    def test_empty_runbook_fails(self, lint, tmp_path):
        r = lint.lint(self._write(tmp_path, "# nothing here\n"))
        assert r["complete"] is False
