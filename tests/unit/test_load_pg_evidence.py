"""Unit tests for the P2 W0.3 --table forwarding on the pg evidence loader (pure, no DB, no S3).

Covers ONLY the new blue-green surface: --table lands in EVIDENCE_PG_TABLE (so pgstore's per-call resolver
targets the shadow table), the dry-run reports the resolved target, and an invalid --table is rejected up
front via pgstore.table_name(). The load loop itself (ThreadPool + upsert) is the already-tested pgstore
path; we stop at the dry-run boundary so no Postgres or S3 is touched.
"""
from __future__ import annotations

import pytest

from jobs.utils import load_pg_evidence as loader


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["load_pg_evidence.py"] + argv)
    return loader.main()


def test_table_flag_sets_env_and_reports_target(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    rc = _run(monkeypatch, ["--nodes", "coffee", "--table", "evidence_props_shadow", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "evidence_props_shadow" in out                       # dry-run names the resolved target
    assert loader.os.environ["EVIDENCE_PG_TABLE"] == "evidence_props_shadow"  # forwarded for the workers


def test_default_target_is_evidence_props(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    rc = _run(monkeypatch, ["--nodes", "coffee", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "evidence_props" in out


def test_env_table_used_when_no_flag(monkeypatch, capsys):
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props_shadow")
    rc = _run(monkeypatch, ["--nodes", "coffee", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "evidence_props_shadow" in out


def test_invalid_table_flag_rejected(monkeypatch):
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    with pytest.raises(ValueError):
        _run(monkeypatch, ["--nodes", "coffee", "--table", "evidence_props; DROP TABLE x", "--dry-run"])
