"""SILVER-F011: registry-driven DDL generation.

Covers the assignment's test contract:
  * the generator is deterministic (render twice / regenerate == byte-identical);
  * the generated DDL for 3 sampled tables (one per partition mode) PARSES -- sqlglot if the
    dependency is present, else structural assertions;
  * the R1_F011 diff report exists and every drift row carries a valid disposition.

Plus the F011 acceptance guards: NASS crop-progress + registered ESR/WASDE cannot be flattened or
re-projected, and the generated DDLs are byte-faithful to the live Glue catalog.

AWS-free, no network -- pure file reads + registry load under the F002 isolation guard.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from leviathan.silver import ddl as D
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[3]
_GEN_SCRIPT = _REPO / "scripts" / "silver" / "generate_ddls_from_registry.py"
_REPORT_SCRIPT = _REPO / "scripts" / "silver" / "f011_ddl_diff_report.py"
_LEGACY_SCRIPT = _REPO / "jobs" / "utils" / "generate_silver_ddls.py"
_GENERATED_DIR = _REPO / "sql" / "athena" / "ddl_generated"
_BASELINE_TABLES = _REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "tables"
_REPORT_MD = _REPO / "reports" / "silver_readiness" / "R1_F011_ddl_diff.md"

# One deterministically-sampled table per partition mode (the F011 modes under guard).
_SAMPLE = {"flat": "silver_cot", "projected": "silver_nasa_power", "registered": "silver_wasde"}
# The F024 migration artifact is the single consistency authority for the CONAB registry flip.
_F024_ARTIFACT = _REPO / "reports" / "silver_readiness" / "R2_SA" / "F024_conab_additive_migration.json"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses need the module registered to resolve annotations
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def reg():
    return load_registry()


@pytest.fixture(scope="module")
def gen_mod():
    return _load_script(_GEN_SCRIPT, "generate_ddls_from_registry")


@pytest.fixture(scope="module")
def report_mod():
    return _load_script(_REPORT_SCRIPT, "f011_ddl_diff_report")


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------
def test_render_ddl_is_deterministic(reg):
    for name in reg.names():
        a = D.render_ddl(reg.table(name))
        b = D.render_ddl(reg.table(name))
        assert a == b, name


def test_render_all_is_deterministic(gen_mod):
    first = gen_mod.render_all()
    second = gen_mod.render_all()
    assert first == second
    assert len(first) == 46  # 43 R0 + gold_pattern_records (T2B) + silver_futures_eod (W1.0)
    #                          + gold_board_crush (D-EC DK-13)


def test_generated_dir_is_byte_identical_to_a_fresh_render(gen_mod):
    """The F011 idempotency gate: the checked-in ddl_generated/ tree == a fresh render."""
    rendered = gen_mod.render_all()
    drift = []
    for name, text in rendered.items():
        path = _GENERATED_DIR / f"{name}.sql"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            drift.append(name)
    assert drift == [], f"stale generated DDLs; re-run --write: {drift}"


def test_all_43_tables_covered(gen_mod):
    rendered = set(gen_mod.render_all())
    on_disk = {p.stem for p in _GENERATED_DIR.glob("*.sql")}
    assert len(rendered) == 46  # 43 R0 + gold_pattern_records (T2B) + silver_futures_eod (W1.0)
    #                             + gold_board_crush (D-EC DK-13)
    assert rendered == on_disk


# ---------------------------------------------------------------------------
# The 3 sampled generated DDLs parse (sqlglot if available, else structural).
# ---------------------------------------------------------------------------
def _assert_parses(name: str, sql: str) -> None:
    try:
        import sqlglot
    except ImportError:
        sqlglot = None
    if sqlglot is not None:
        parsed = None
        for dialect in ("athena", "hive", "spark", "trino"):
            try:
                parsed = sqlglot.parse_one(sql, read=dialect)
                break
            except Exception:
                continue
        assert parsed is not None, f"{name}: sqlglot failed to parse in any SQL dialect"
        assert parsed.key == "create", f"{name}: not parsed as a CREATE statement"
        return
    # Structural fallback (no sqlglot dependency in this env).
    assert sql.startswith("--"), f"{name}: missing documented header"
    assert f"CREATE EXTERNAL TABLE IF NOT EXISTS {name} (" in sql, f"{name}: missing idempotent CREATE"
    assert sql.count("(") == sql.count(")"), f"{name}: unbalanced parentheses"
    assert "STORED AS PARQUET" in sql
    assert "LOCATION '" in sql
    assert "TBLPROPERTIES (" in sql
    assert sql.rstrip().endswith(");"), f"{name}: statement not terminated"
    # the parser round-trips to the same semantic content.
    assert D.parse_ddl(sql).columns  # non-empty column list survives a parse


@pytest.mark.parametrize("mode,name", sorted(_SAMPLE.items()))
def test_sampled_generated_ddl_parses(reg, mode, name):
    sql = D.render_ddl(reg.table(name))
    _assert_parses(name, sql)


# ---------------------------------------------------------------------------
# Registry fidelity + parse round-trip.
# ---------------------------------------------------------------------------
def test_generated_matches_live_glue_for_every_table(reg):
    """Generated DDL (from the registry) == the live Glue catalog for ALL 43 tables.

    Encodes the model_predictions column-order fix (no accidental drift). BF-W2 retired the one
    sanctioned exception: the F024 CONAB additive migration (step 5) and the F036 WASDE 29-column
    migration (step 17, m2mye int->bigint + F013 461-partition SD repair) are both APPLIED, the
    snapshots under 20260712_p65impl/tables/ refreshed to the post-migration live state
    (2026-07-15), and the registry regenerates to exactly that state. ANY divergence is drift.
    """
    drift = {}
    for name in reg.names():
        R = D.structured_from_contract(reg.table(name))
        glue = json.loads((_BASELINE_TABLES / f"{name}.json").read_text(encoding="utf-8"))["glue"]
        G = D.structured_from_glue(glue)
        d = D.diff_structured(G, R)
        if d:
            drift[name] = d
    assert drift == {}, f"registry diverges from live Glue: {drift}"


def test_model_predictions_snapshot_columns_at_catalog_positions(reg):
    """The fixed table: snapshot_stage/snapshot_policy sit at columns 2-3 (catalog order)."""
    cols = [n for n, _ in D.catalog_columns(reg.table("silver_model_predictions"))]
    assert cols[:4] == ["country", "crop_year", "snapshot_stage", "snapshot_policy"]
    assert cols[-1] == "prediction_as_of_date"


def test_parse_round_trip_is_semantically_identity(reg):
    for name in reg.names():
        c = reg.table(name)
        want = D.structured_from_contract(c)
        got = D.parse_ddl(D.render_ddl(c))
        # parse_ddl does not carry physical_only (registry-only metadata); compare the rest.
        assert list(want.columns) == list(got.columns), name
        assert list(want.partition_keys) == list(got.partition_keys), name
        assert want.partition_mode == got.partition_mode, name
        assert list(want.projection) == list(got.projection), name
        assert want.location == got.location, name


# ---------------------------------------------------------------------------
# Partition-mode behaviour is preserved (F011 acceptance: no flatten / re-project).
# ---------------------------------------------------------------------------
def test_projected_ddls_keep_projection(reg):
    # SILVER-F047 catch-up (2026-07-28): the weather storm-trio left this list -- BF-W1
    # (2026-07-21) deprojected them live to REGISTERED [commodity, year]; they are asserted in
    # test_registered_ddls_partitioned_without_projection below. nass_crop_progress remains
    # live-projected (verified projection.enabled='true' in Glue, 2026-07-28).
    for name in ("silver_nass_crop_progress",):
        sql = D.render_ddl(reg.table(name))
        assert "PARTITIONED BY (" in sql, name
        assert "'projection.enabled' = 'true'" in sql, name
        assert "'storage.location.template'" in sql, name


def test_registered_ddls_partitioned_without_projection(reg):
    for name in ("silver_esr", "silver_esr_compact", "silver_wasde",
                 "silver_model_predictions",
                 # SILVER-F047 catch-up: the deprojected weather trio renders registered.
                 "silver_chirps", "silver_nasa_power", "silver_cpc_soil"):
        sql = D.render_ddl(reg.table(name))
        assert "PARTITIONED BY (" in sql, name
        # no projection TBLPROPERTY / storage template (the word "projection" appears only in the
        # safety comment "DO NOT re-add partition projection").
        assert "'projection." not in sql, name
        assert "storage.location.template" not in sql, name
        assert "REGISTERED partitions" in sql, name  # the S3-LIST-storm safety note


def test_flat_ddls_have_no_partitioning(reg):
    for name in ("silver_cot", "silver_conab_coffee", "gold_weather_z"):
        sql = D.render_ddl(reg.table(name))
        assert "PARTITIONED BY" not in sql, name
        assert "projection." not in sql, name


def test_legacy_generator_refuses_to_flatten_non_flat_tables():
    """The constrained legacy generator can never emit a flat DDL for a projected/registered table."""
    legacy = _load_script(_LEGACY_SCRIPT, "legacy_generate_silver_ddls")
    protected = legacy._protected_tables()
    # every registered/projected table is protected...
    for name in ("silver_nass_crop_progress", "silver_esr", "silver_wasde",
                 "silver_nasa_power", "silver_model_predictions"):
        assert name in protected, name
    # ...and the one projected table still listed in the legacy _SOURCES is refused.
    assert "silver_nass_crop_progress" in legacy._SOURCES
    assert "silver_nass_crop_progress" in protected


# ---------------------------------------------------------------------------
# The diff report exists and every drift row carries a disposition.
# ---------------------------------------------------------------------------
def test_diff_report_exists():
    assert _REPORT_MD.exists(), "reports/silver_readiness/R1_F011_ddl_diff.md is missing"
    text = _REPORT_MD.read_text(encoding="utf-8")
    assert "SILVER-F011" in text


def test_every_diff_row_has_a_valid_disposition(report_mod):
    rows = report_mod.build_diff()
    assert rows, "diff report produced no rows"
    for r in rows:
        assert r.disposition in report_mod.DISPOSITIONS, (r.table, r.disposition)
        assert r.detail, (r.table, r.dimension)


def test_diff_report_covers_the_known_findings(report_mod):
    rows = report_mod.build_diff()
    by_disp = {}
    for r in rows:
        by_disp.setdefault(r.disposition, []).append(r)
    # POST-F024 (BF-W2 step 5 APPLIED): the CONAB migration landed and the snapshot was re-captured,
    # so NO migration-pending row may remain -- a reappearing one means live Glue regressed. The
    # WIRING_WAVE1 survey_release_date additive follows the same apply-then-refresh discipline (registry
    # + R0 snapshot + hand DDL all carry the 23rd column together), so it too leaves no pending row.
    reg_wins = by_disp.get(report_mod.REGISTRY_WINS, [])
    assert not any(r.table == "silver_conab_coffee" and r.dimension == "catalog-migration-pending"
                   for r in reg_wins)
    assert not any(r.table == "silver_conab_coffee" and r.dimension == "physical-only-columns"
                   for r in rows)
    assert not any(r.table == "silver_conab_coffee" and r.dimension == "registry-vs-liveGlue"
                   for r in rows)
    # the model_predictions order bug is recorded as fixed.
    hand_wins = by_disp.get(report_mod.HAND_WINS_FIXED, [])
    assert any(r.table == "silver_model_predictions" for r in hand_wins)
    # every table either carries at least one classified row OR is FULLY CLEAN (generated DDL
    # byte-identical to the hand DDL) -- the BF-W3 wasde hand-DDL sync produced the first fully
    # clean table, which is the goal state, not a coverage gap.
    reg = load_registry()
    covered = {r.table for r in rows}
    for name in sorted(set(reg.names()) - covered):
        gen_text = D.render_ddl(reg.table(name))
        hand_text = (report_mod.HAND_DDL_DIR / f"{name}.sql").read_text(encoding="utf-8")
        assert gen_text == hand_text, f"{name} has no drift row but generated != hand DDL"
