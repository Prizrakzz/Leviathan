"""SILVER-C001 unit tests for the silver_rebuild_gate DISPATCHER.

Everything AWS/pg is mocked or injected; nothing touches the mirror/Athena/Batch. Covers the three plan
requirements: (1) branch selection for ALL 43 F010 tables from the `consumers` field, (2) a Branch-B
feature-only table NEVER calls load_pg_numbers (the crash class Attack 3 #1 fixed), (3) fail-closed on any
red stage. Plus the census --diff new-dark detector and the offline (no-pg) skip posture."""
from __future__ import annotations

import types

import pytest

from jobs.audit import silver_rebuild_gate as g


# --- a tiny F010-silver-registry shim ---------------------------------------------------------------------
class _SilverReg:
    def __init__(self, tables):
        self.tables = tables            # {name: contract dict}

    def table(self, name):
        return self.tables[name]

    def value_columns(self, name):
        return list(self.tables[name].get("value_columns", []))


def _ctx(silver_reg, **kw):
    base = dict(numbers_reg=types.SimpleNamespace(get=lambda t: None), silver_reg=silver_reg,
                query_fn=None, conn=None, census_asof="2026-02-15", prior_census=None,
                eval_runner=None, value_census_fn=None)
    base.update(kw)
    return g.GateContext(**base)


# ---------------------------------------------------------------------------
# (1) branch selection for all 43 tables from the F010 consumers field
# ---------------------------------------------------------------------------
def test_branch_selection_all_43_tables():
    from leviathan.silver import registry as sreg
    silver = sreg.load_registry()
    names = silver.names()
    assert len(names) == 43, f"expected 43 F010 tables, got {len(names)}"

    branch_a = {t for t in names if g.select_branch(t, silver_reg=silver) == g.BRANCH_A}
    branch_b = {t for t in names if g.select_branch(t, silver_reg=silver) == g.BRANCH_B}

    # Branch A == exactly the 7 pg-mirror tables (== load_pg_numbers.P1_TABLES); every other table -> B.
    assert branch_a == g.PG_MIRROR_TABLES, branch_a
    assert len(branch_a) == 7
    assert branch_a | branch_b == set(names)          # partition: no table is UNKNOWN in the real registry
    assert not (branch_a & branch_b)


def test_nasa_power_is_branch_b_despite_numbers_consumer():
    """silver_nasa_power's F010 consumers == 'both', but it is a PROJECTION table excluded from the mirror
    (INV-3 + size) -> Branch B, never load_pg_numbers. This is the exact shape Attack 3 #1 mandates."""
    from leviathan.silver import registry as sreg
    silver = sreg.load_registry()
    assert silver.table("silver_nasa_power")["consumers"] == "both"
    assert "silver_nasa_power" not in g.PG_MIRROR_TABLES
    assert g.select_branch("silver_nasa_power", silver_reg=silver) == g.BRANCH_B


def test_unregistered_table_is_unknown_and_fails_closed():
    silver = _SilverReg({})
    assert g.select_branch("silver_nope", silver_reg=silver) == g.BRANCH_UNKNOWN
    res = g.run_table("silver_nope", _ctx(silver))
    assert not res.ok and res.branch == g.BRANCH_UNKNOWN


# ---------------------------------------------------------------------------
# (2) Branch-B on a feature-only table NEVER calls load_pg_numbers (the crash class)
# ---------------------------------------------------------------------------
def test_branch_b_never_calls_load_pg_numbers(monkeypatch):
    import leviathan.features.extractors as extractors

    from jobs.utils import load_pg_numbers

    called = {"load_table": 0}

    def _boom_load_table(*a, **k):
        called["load_table"] += 1
        raise AssertionError("load_pg_numbers.load_table MUST NOT run for a feature-only table")

    monkeypatch.setattr(load_pg_numbers, "load_table", _boom_load_table)
    # a healthy footer probe (no S3)
    monkeypatch.setattr(extractors, "probe_source",
                        lambda key, loc, **k: types.SimpleNamespace(
                            exists=True, num_files=3, num_rows=100,
                            columns=("commodity", "year", "value")))

    silver = _SilverReg({"silver_chirps": {
        "consumers": "feature_layer", "s3_root": "s3://leviathan-dev-shahem-001/silver/chirps",
        "natural_key": ["commodity", "year"], "value_columns": ["value"]}})
    ctx = _ctx(silver, value_census_fn=lambda t, reg: {"ok": True})

    res = g.run_table("silver_chirps", ctx)
    assert res.branch == g.BRANCH_B
    assert called["load_table"] == 0
    stage_names = {s.name for s in res.stages}
    assert stage_names == {"feature_probe", "value_census", "config_check"} or "config_check" in stage_names
    assert not any(s.name in ("pg_reload", "parity", "contract_check") for s in res.stages)


# ---------------------------------------------------------------------------
# (3) fail-closed on a red stage
# ---------------------------------------------------------------------------
def _green(name):
    return lambda t, ctx: g.StageResult(name, g.GREEN, "ok")


def _red(name):
    return lambda t, ctx: g.StageResult(name, g.RED, "boom")


def _skip(name):
    return lambda t, ctx: g.StageResult(name, g.SKIPPED, "deferred")


def test_red_stage_fails_the_table_and_run(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    ctx = _ctx(silver)
    bundle = g.run_gate(["silver_wasde"], ctx,
                        branch_a_stages=(_green("pg_reload"), _red("parity"), _green("config_check")))
    assert bundle["verdict"] == "FAIL"
    assert bundle["banner"]["red_tables"] == 1
    assert bundle["results"][0]["ok"] is False


def test_all_green_passes(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    ctx = _ctx(silver)
    bundle = g.run_gate(["silver_wasde"], ctx,
                        branch_a_stages=(_green("pg_reload"), _green("config_check"), _skip("eval_subset")))
    assert bundle["verdict"] == "PASS"
    assert bundle["banner"]["branch_a"] == 1
    assert "in_vpc_submit_command" in bundle and "silver_wasde" in bundle["in_vpc_submit_command"]


def test_all_skipped_is_not_a_pass():
    """Fail-closed: a table whose every stage skipped proved nothing -> NOT ok."""
    silver = _SilverReg({"silver_cot": {"consumers": "feature_layer"}})
    ctx = _ctx(silver)
    res = g.run_table("silver_cot", ctx,
                      branch_b_stages=(_skip("feature_probe"), _skip("value_census"), _skip("config_check")))
    assert not res.ok


# ---------------------------------------------------------------------------
# census --diff new-dark detector
# ---------------------------------------------------------------------------
def test_census_diff_flags_new_dark_only():
    prior = {"legs": [{"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON"}]}
    current = {
        "banner": {"athena_calls": 0},
        "legs": [
            {"contract": "cocoa", "node_id": "grind", "verdict": "DARK-WITH-REASON"},   # pre-existing
            {"contract": "corn_cbot", "node_id": "export", "verdict": "FIRES"},
            {"contract": "wheat_cbot", "node_id": "eu", "verdict": "DARK-WITH-REASON",  # NEW dark
             "table": "silver_psd", "metric": "exports", "reason": "country-not-a-psd-title"},
        ],
    }
    problems = g._census_diff(prior, current)
    assert len(problems) == 1 and "wheat_cbot/eu" in problems[0]


def test_census_diff_flags_nonzero_athena():
    problems = g._census_diff({"legs": []}, {"banner": {"athena_calls": 3}, "legs": []})
    assert any("ATHENA_CALLS" in p for p in problems)


# ---------------------------------------------------------------------------
# offline posture: a Branch-A table with no pg backend SKIPS pg stages (never crashes)
# ---------------------------------------------------------------------------
def test_branch_a_offline_skips_pg_stages(monkeypatch):
    silver = _SilverReg({"silver_wasde": {"consumers": "both"}})
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"silver_wasde"}))
    numbers_reg = types.SimpleNamespace(get=lambda t: types.SimpleNamespace(id=t))
    ctx = _ctx(silver, numbers_reg=numbers_reg, query_fn=None, conn=None)
    # real Branch-A stages, but no pg backend -> pg_reload/parity/contract_check/census skip, config_check
    # still runs. Assert no crash and the pg stages are skipped (not red).
    monkeypatch.setattr(g, "_run_config_check", lambda: [])
    res = g.run_table("silver_wasde", ctx)
    by = {s.name: s.status for s in res.stages}
    assert by["pg_reload"] == g.SKIPPED
    assert by["parity"] == g.SKIPPED
    assert by["contract_check"] == g.SKIPPED
    assert by["cascade_census_diff"] == g.SKIPPED
    assert by["config_check"] == g.GREEN
