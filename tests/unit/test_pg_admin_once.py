"""The one-off Postgres administrative file runs exactly two NAMED actions, and the drop refuses unless every
pre-check holds (owner word 2026-09-29, after the pg audit)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jobs.utils import pg_admin_once as P  # noqa: E402

GOOD = {"live": "evidence_props", "old": "evidence_props_old", "live_exists": True, "old_exists": True,
        "live_rows": 2_748_672, "old_rows": 2_748_112, "live_vector_indexes": 29, "dependents": 0}


def test_the_file_runs_exactly_two_named_actions_and_no_free_sql():
    assert P.ACTIONS == ("create-pg-stat-statements", "drop-evidence-props-old")
    with pytest.raises(SystemExit):
        P.main(["--action", "run-sql", "--dry-run"])


def test_the_drop_holds_when_every_precheck_holds():
    assert P.drop_refusal(dict(GOOD), "evidence_props_old") == ""


@pytest.mark.parametrize("change, confirm, needle", [
    ({}, "", "--confirm must name"),
    ({}, "evidence_props", "--confirm must name"),
    ({"old": "evidence_props"}, "evidence_props", "IS the live table"),
    ({"old_exists": False}, "evidence_props_old", "does not exist"),
    ({"live_exists": False}, "evidence_props_old", "live table"),
    ({"live_rows": 10}, "evidence_props_old", "fewer rows"),
    ({"live_vector_indexes": 0}, "evidence_props_old", "no vector index"),
    ({"dependents": 1}, "evidence_props_old", "depend"),
])
def test_the_drop_refuses_on_any_failed_precheck(change, confirm, needle):
    why = P.drop_refusal({**GOOD, **change}, confirm)
    assert needle in why, why


def test_the_live_table_name_is_a_bare_identifier(monkeypatch):
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props; DROP TABLE x")
    with pytest.raises(SystemExit):
        P.live_table()
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props_shadow")
    assert P.live_table() == "evidence_props_shadow" and P.old_table() == "evidence_props_shadow_old"


def test_a_dry_run_connects_to_nothing(monkeypatch, capsys):
    monkeypatch.delenv("EVIDENCE_PG_DSN", raising=False)
    monkeypatch.delenv("EVIDENCE_PG_TABLE", raising=False)
    assert P.main(["--action", "drop-evidence-props-old", "--dry-run"]) == 0
    assert "evidence_props_old" in capsys.readouterr().out
