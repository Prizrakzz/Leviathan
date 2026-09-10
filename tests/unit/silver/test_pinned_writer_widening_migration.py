"""THE TWO CATALOG WIDENINGS THAT PAY THE PINNED-WRITER DEBT, and the runbook that applies them.

WHAT THIS DECK IS FOR. ``tests/unit/silver/test_pinned_writer_catalog_debt.py`` names the debt:
eleven columns across ``silver_fgis`` and ``silver_modis_ndvi`` whose pinned writer emits a type the
Glue catalog does not declare, on two families whose promote is autonomous. That deck holds the
LIST. This deck holds the PAYMENT: it pins that the migration manifests describe exactly that list,
column for column and type for type, that they describe the catalog as it actually stands, and that
the runbook's dry-run is a deterministic, AWS-free function of tracked bytes.

IT SURVIVES ITS OWN CLOSURE. Every assertion is keyed off each manifest's ``applied`` flag:

  * ``applied: false``  -- the manifest's ``widened_columns`` must equal the debt deck's
    ``EXPECTED_DEBT`` entry for that table, and each ``from_glue_type`` must equal what the tracked
    R0 ``_raw`` sidecar (measured 2026-09-09 to be byte-equal to live Glue) declares today.
  * ``applied: true``   -- the debt is paid: the table must be GONE from ``EXPECTED_DEBT``, and the
    regenerated contract must carry the widened ``glue_type`` with no F062 widen left in its
    ``drift_summary``.

So flipping ``applied`` to true without doing the R0 re-capture, the registry regeneration and the
``EXPECTED_DEBT`` emptying fails here -- and emptying ``EXPECTED_DEBT`` without flipping ``applied``
fails here too. The two halves of the closure cannot drift apart.

AWS-free, no network: the tracked migration manifests, the tracked registry YAMLs, the tracked R0
sidecars, and one subprocess run of the runbook in ``--offline`` mode.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from leviathan.silver.migrate import CatalogMigrator
from leviathan.silver.registry import load_registry

# The allowlisted in-memory test surface (tests/unit/silver/conftest.py). NEVER the prod bucket or
# the prod database: the round-trip test below drives the real mutating code path.
from conftest import FakeGlue, TEST_BUCKET, TEST_DB  # noqa: E402

_REPO = Path(__file__).resolve().parents[3]
_MIGRATIONS = _REPO / "sql" / "athena" / "migrations" / "silver"
_R0_RAW = _REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "_raw"
_RUNBOOK = _REPO / "scripts" / "ops" / "pinned_writer_widening_runbook.py"
_DEBT_DECK = _REPO / "tests" / "unit" / "silver" / "test_pinned_writer_catalog_debt.py"

# The two manifests this deck governs, and the table each one widens.
MIGRATION_FILES = {
    "silver_fgis": "20260909T000000Z_silver_fgis_type_widening_additive.json",
    "silver_modis_ndvi": "20260909T000000Z_silver_modis_ndvi_type_widening_additive.json",
}

# The manifest shape, taken from the WIDENING precedent
# 20260820T000000Z_silver_pink_sheet_series_widening_additive.json. Keys that precedent carries and
# a type widening still needs; plus the four this change adds because a retype has questions a
# column-add does not (does the projection survive, does the stored parquet still read, what does
# the planner refuse to do, and what are the frozen hashes).
_PRECEDENT_KEYS = {
    "package", "table", "database", "change_type", "risk", "gated", "applied", "status",
    "generated_at", "guard_mode", "blocker_measured", "mechanism", "apply_sql", "glue_call",
    "sequencing_note", "arm_vs_flip_note", "known_limitation", "rollback_note", "reconciliation",
    "applied_at",
}
_WIDENING_KEYS = {
    "widened_columns", "widened_columns_note", "plan_hashes", "the_planner_cannot_plan_this",
    "partition_projection_note", "partition_key_note", "coercion_note",
}
_COLUMN_KEYS = {
    "name", "ordinal", "from_glue_type", "to_glue_type", "current_parquet_physical",
    "current_arrow_type", "target_arrow_type", "drift_kind", "owner_package",
}

# INV-2 target arrow type -> its Glue spelling. Deliberately two entries: an unmapped target must
# fail this deck rather than be assumed safe (the debt deck's own fail-closed convention).
_ARROW_TO_GLUE = {"int64": "bigint", "float64": "double"}


def _manifest(table: str) -> dict:
    return json.loads((_MIGRATIONS / MIGRATION_FILES[table]).read_text(encoding="utf-8"))


def _r0_types(table: str) -> dict:
    raw = json.loads((_R0_RAW / f"{table}.get-table.json").read_text(encoding="utf-8"))
    return {c["Name"]: c["Type"] for c in raw["StorageDescriptor"]["Columns"]}


def _expected_debt() -> dict:
    """The debt deck's EXPECTED_DEBT literal, read TEXTUALLY (no import, no fixtures, no pytest
    collection side effects) so this deck pins the source of truth exactly as it is written."""
    tree = ast.parse(_DEBT_DECK.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EXPECTED_DEBT" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("EXPECTED_DEBT not found in test_pinned_writer_catalog_debt.py")


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture(scope="module")
def debt():
    return _expected_debt()


# ---------------------------------------------------------------------------
# 1. The files exist, parse, and are shaped like the precedent.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_the_migration_file_parses_and_carries_the_precedent_shape(table):
    path = _MIGRATIONS / MIGRATION_FILES[table]
    assert path.exists(), f"missing migration manifest: {path}"
    m = json.loads(path.read_text(encoding="utf-8"))          # the parse IS the assertion
    missing = (_PRECEDENT_KEYS | _WIDENING_KEYS) - set(m)
    assert not missing, f"{path.name}: missing keys {sorted(missing)}"
    assert m["table"] == table
    assert m["database"] == "leviathan_dev"
    # ChangeType.ADDITIVE_UPDATE is what CatalogMigrator classifies a same-length retype as, and it
    # is what the machine-written silver_noaa_oni widen manifest recorded on 2026-07-15.
    assert m["change_type"] == "additive_update"
    assert m["gated"] is True
    assert isinstance(m["applied"], bool)
    assert (m["applied_at"] is None) == (not m["applied"]), (
        f"{path.name}: applied={m['applied']} but applied_at={m['applied_at']!r}")


@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_every_widened_column_entry_is_complete_and_is_a_widen(table):
    for col in _manifest(table)["widened_columns"]:
        assert set(col) == _COLUMN_KEYS, f"{table}.{col.get('name')}: {sorted(col)}"
        assert col["owner_package"] == "SILVER-F062"
        assert col["drift_kind"] in ("widen_int", "widen_float")
        assert col["target_arrow_type"] in _ARROW_TO_GLUE
        assert col["to_glue_type"] == _ARROW_TO_GLUE[col["target_arrow_type"]]
        assert col["from_glue_type"] != col["to_glue_type"]


# ---------------------------------------------------------------------------
# 2. The payment matches the debt, COLUMN FOR COLUMN -- until it is paid.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_the_manifest_matches_expected_debt_column_for_column(table, debt):
    """THE CENTRAL PIN. While the migration is unapplied, its column list must BE the debt deck's
    entry for that table -- same names, same from-type, same to-type. A column added to or dropped
    from either side fails here."""
    m = _manifest(table)
    if m["applied"]:
        pytest.skip(f"{table} widen is applied; the paid-debt pins cover it")
    assert table in debt, f"{table} is unapplied but carries no EXPECTED_DEBT entry"
    got = {c["name"]: (c["from_glue_type"], c["to_glue_type"]) for c in m["widened_columns"]}
    want = {name: (glue, _ARROW_TO_GLUE[target]) for name, (glue, target) in debt[table].items()}
    assert got == want
    assert len(m["widened_columns"]) == len(debt[table]), "duplicate column entry"


@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_the_manifest_describes_the_catalog_as_it_actually_stands(table):
    """``from_glue_type`` is a REFUSAL PRECONDITION, not decoration: the runbook re-reads live Glue
    and refuses unless each column holds exactly that type. Here it is checked against the tracked
    R0 ``_raw`` sidecar, whose managed-subset hash was measured equal to live Glue on 2026-09-09.
    Column ORDINALS are pinned too -- a retype must never move a column."""
    m = _manifest(table)
    if m["applied"]:
        pytest.skip(f"{table} widen is applied; the R0 sidecar is re-captured wide by then")
    live = _r0_types(table)
    order = list(live)
    for col in m["widened_columns"]:
        assert col["name"] in live, f"{table}: {col['name']} absent from the catalog"
        assert live[col["name"]] == col["from_glue_type"], (
            f"{table}.{col['name']}: catalog says {live[col['name']]!r}, "
            f"manifest says {col['from_glue_type']!r}")
        assert order.index(col["name"]) == col["ordinal"]
    ordinals = [c["ordinal"] for c in m["widened_columns"]]
    assert ordinals == sorted(ordinals), "widened_columns must be listed in catalog order"


@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_the_manifest_matches_the_contract_the_writer_is_pinned_to(table, registry):
    """The debt exists because the writer is pinned to the contract. So the manifest's target types
    must be the contract's ``target_arrow_type`` for exactly the columns whose ``glue_type`` differs
    from it -- the same derivation the runbook re-runs at every invocation."""
    m = _manifest(table)
    if m["applied"]:
        pytest.skip(f"{table} widen is applied; the contract is regenerated wide by then")
    contract = registry.table(table)
    assert contract.get("writer_schema_pinned") is True
    derived = {}
    for col in contract.get("physical_columns") or []:
        glue = str(col.get("glue_type") or "").strip().lower()
        target = str(col.get("target_arrow_type") or "").strip().lower()
        if glue and target in _ARROW_TO_GLUE and _ARROW_TO_GLUE[target] != glue:
            derived[col["name"]] = (glue, _ARROW_TO_GLUE[target])
    got = {c["name"]: (c["from_glue_type"], c["to_glue_type"]) for c in m["widened_columns"]}
    assert got == derived


# ---------------------------------------------------------------------------
# 3. The closure: what must be true once a manifest says applied.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", sorted(MIGRATION_FILES))
def test_an_applied_widen_has_actually_been_reconciled(table, registry, debt):
    """THE OTHER HALF OF THE CLOSURE. ``applied: true`` is a claim about the estate, and these are
    the three things that make it true: the debt entry is gone, the regenerated contract declares
    the WIDE glue_type, and no SILVER-F062 widen survives in its drift_summary. Flipping the flag
    without re-capturing R0 and regenerating the registry fails right here."""
    m = _manifest(table)
    if not m["applied"]:
        pytest.skip(f"{table} widen is not applied yet")
    assert table not in debt, (
        f"{table}: the widen is applied but EXPECTED_DEBT still lists it -- empty it "
        "(post-apply step 6) after the R0 re-capture and registry regeneration")
    contract = registry.table(table)
    by_name = {c["name"]: c for c in contract.get("physical_columns") or []}
    for col in m["widened_columns"]:
        c = by_name[col["name"]]
        assert str(c.get("glue_type")).lower() == col["to_glue_type"], (
            f"{table}.{col['name']}: contract still says {c.get('glue_type')!r}; re-capture R0 "
            "AFTER the canonical rewrite, then regenerate the registry")
        assert str(c.get("target_arrow_type")).lower() == col["target_arrow_type"]
    widens = [e for e in (contract.get("drift_summary") or [])
              if str(e.get("kind", "")).startswith("widen")]
    assert widens == [], f"{table}: F062 widens still declared after an applied widen: {widens}"


def test_the_debt_deck_and_these_manifests_cover_the_same_tables(debt):
    """No third table may owe a widen without a manifest, and no manifest may exist for a table that
    never owed one. (A paid table leaves EXPECTED_DEBT but keeps its manifest, so the check is one
    directional plus an applied-flag escape.)"""
    for table in debt:
        assert table in MIGRATION_FILES, (
            f"{table} owes a catalog widen with no migration manifest in {_MIGRATIONS}")
    for table in MIGRATION_FILES:
        assert table in debt or _manifest(table)["applied"], (
            f"{table} has a migration manifest but owes nothing and is not marked applied")


# ---------------------------------------------------------------------------
# 4. The runbook: deterministic, AWS-free, PowerShell-5.1-safe.
# ---------------------------------------------------------------------------
def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_RUNBOOK), *args],
        cwd=str(_REPO), capture_output=True, timeout=300)


@pytest.fixture(scope="module")
def offline_runs():
    """Two identical --offline invocations. --offline reads the tracked R0 sidecars, so this makes
    no AWS call and no network call."""
    return _run("--offline"), _run("--offline")


def test_the_dry_run_is_deterministic(offline_runs):
    """Byte-for-byte identical across runs: no clock, no uuid, no set iteration order in the plan
    output. An operator diffing two dry-runs sees only real catalog movement."""
    first, second = offline_runs
    assert first.returncode == second.returncode
    assert first.stdout == second.stdout, "the dry-run output is not reproducible"
    assert first.stdout, "the dry-run printed nothing"


def test_the_dry_run_mutates_nothing_and_says_so(offline_runs):
    out = offline_runs[0].stdout.decode("ascii")
    assert offline_runs[0].returncode == 0, out[-2000:]
    assert "DRY RUN -- NOTHING WAS MUTATED" in out
    assert "no glue.update_table was issued" in out.lower()
    for table in MIGRATION_FILES:
        assert table in out


def test_the_dry_run_prints_the_before_and_after_type_of_every_debt_column(offline_runs, debt):
    """The deliverable of a dry-run: the diff of column types. Every debt column, both types."""
    out = offline_runs[0].stdout.decode("ascii")
    for table, cols in debt.items():
        for name, (glue, target) in cols.items():
            wide = _ARROW_TO_GLUE[target]
            line = [ln for ln in out.splitlines() if ln.strip().startswith(("* " + name, "*  " + name))]
            assert line, f"{table}.{name}: no changed-column line in the dry-run output"
            assert glue in line[0] and wide in line[0], line[0]


def test_the_dry_run_output_is_ascii_only(offline_runs):
    """The owner's console is cp1252; a non-ASCII byte is a UnicodeEncodeError at print time."""
    offline_runs[0].stdout.decode("ascii")     # raises on any non-ASCII byte


def _runbook_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_pw_widening_runbook", _RUNBOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_runbook_hands_the_owner_no_powershell_51_parser_error(offline_runs, capsys):
    """OWNER LAW: Windows PowerShell 5.1 has no ``&&``. Neither the printed plan NOR the post-apply
    steps (which only ``--apply`` prints, so they are exercised directly here) may hand the owner
    one. The only ``&&`` allowed anywhere in the file is the prose stating the ban."""
    assert b"&&" not in offline_runs[0].stdout

    mod = _runbook_module()
    mod.print_post_apply_steps(sorted(MIGRATION_FILES))
    steps = capsys.readouterr().out
    steps.encode("ascii")                                   # cp1252 console: ASCII only
    assert "&&" not in steps
    for required in ("--verify-read",
                     "python scripts/silver/run_census.py",
                     "gen_registry_from_baseline.py --check",
                     "f011_ddl_diff_report.py",
                     "EXPECTED_DEBT = {}",
                     "python -m pytest tests/unit/silver"):
        assert required in steps, f"post-apply steps do not print {required!r}"
    # every command line is a single PowerShell statement, chained with ';' if at all.
    for line in steps.splitlines():
        if line.strip().startswith("python "):
            assert "&&" not in line and "|" not in line, line

    for line in _RUNBOOK.read_text(encoding="utf-8").splitlines():
        if "&&" in line:
            assert "parser error" in line or "never with" in line, (
                f"a literal '&&' outside the prose stating the ban: {line}")


def test_offline_can_never_back_a_mutation():
    """The snapshot source is a dry-run source. Combining it with --apply is a REFUSAL (exit 2), not
    a silent live read."""
    proc = _run("--offline", "--apply")
    assert proc.returncode == 2
    assert b"REFUSED" in proc.stdout


def test_the_type_precondition_refuses_a_catalog_that_is_not_in_the_measured_state():
    """THE TYPE PRECONDITION, exercised -- and NOTE WHAT THIS IS NOT. Asking for the REVERSE plan
    while the catalog still holds the NARROW types must refuse with the column named, never
    widen-then-narrow blindly. This is a test of the precondition ONLY: it says nothing about
    whether the rollback works, because the rollback never runs. The tests below put the reverse
    plan in front of a catalog that IS wide -- which is the only way to test it."""
    proc = _run("--table", "silver_fgis", "--rollback", "--dry-run", "--offline")
    assert proc.returncode == 2
    out = proc.stdout.decode("ascii")
    assert "REFUSED -- nothing was mutated by this runbook." in out
    assert "week_of_marketing_year" in out and "expected exactly 'bigint'" in out


# ---------------------------------------------------------------------------
# 5. THE ROLLBACK, IN FRONT OF A WIDE CATALOG.
#
# A reverse plan is a NARROWING, and CatalogMigrator.apply_table refuses every narrowing
# (UnsafeMigration). A --rollback routed through apply_table is therefore a DEAD command -- it
# cannot be caught by a test that only ever shows it a NARROW catalog, because the type
# precondition fires first and the exit code looks the same. Every test below seeds a catalog that
# is already WIDE.
# ---------------------------------------------------------------------------
_WIDE = {
    "silver_fgis": {"week_of_marketing_year": "bigint"},
    "silver_modis_ndvi": {"year": "bigint", "period": "bigint", "pixel_reliability": "bigint",
                          "latitude": "double", "longitude": "double", "ndvi_raw": "double",
                          "ndvi": "double", "ndvi_z_score": "double", "baseline_mean": "double",
                          "baseline_std": "double"},
}


def _wide_snapshot(table: str) -> dict:
    """The tracked R0 sidecar with exactly the debt columns retyped wide: the catalog as it stands
    the moment after a successful --apply. Datetimes are stringified the way a JSON round trip
    through a real get_table response leaves them."""
    snap = json.loads((_R0_RAW / f"{table}.get-table.json").read_text(encoding="utf-8"))
    changed = 0
    for col in snap["StorageDescriptor"]["Columns"]:
        if col["Name"] in _WIDE[table]:
            col["Type"] = _WIDE[table][col["Name"]]
            changed += 1
    assert changed == len(_WIDE[table]), f"{table}: seeded {changed} of {len(_WIDE[table])}"
    return snap


@pytest.fixture()
def wide_dir(tmp_path):
    for table in MIGRATION_FILES:
        (tmp_path / f"{table}.get-table.json").write_text(
            json.dumps(_wide_snapshot(table), indent=2), encoding="utf-8")
    return tmp_path


def test_the_reverse_plan_is_previewable_against_a_wide_catalog(wide_dir, debt):
    """The preview an owner gets mid-incident. Exit 0 (the plan is real), every debt column shown
    wide -> narrow, the restore path named, and the closing line naming the flag that would EXECUTE
    it -- not --apply, which would run the widen again."""
    proc = _run("--rollback", "--dry-run", "--offline", "--offline-dir", str(wide_dir))
    out = proc.stdout.decode("ascii")
    assert proc.returncode == 0, out[-3000:]
    assert "CatalogMigrator.restore_table(" in out
    assert "Re-run with --rollback ALONE (drop --dry-run) to execute." in out
    assert "Re-run with --apply" not in out
    for table, cols in debt.items():
        for name, (narrow, target) in cols.items():
            wide = _ARROW_TO_GLUE[target]
            line = [ln for ln in out.splitlines()
                    if ln.strip().startswith(("* " + name, "*  " + name))]
            assert line, f"{table}.{name}: no changed-column line in the reverse plan"
            assert wide in line[0] and narrow in line[0], line[0]


def test_the_reverse_plan_declares_its_narrowing_instead_of_hiding_it(wide_dir):
    """The eleven ``NARROW column ...`` entries are what apply_table would refuse on. The preview
    must print them AS the bounded override they are -- an operator who sees `unsafe: [...]` and no
    explanation has been handed a plan that looks executable and is not."""
    proc = _run("--rollback", "--dry-run", "--offline", "--offline-dir", str(wide_dir))
    out = proc.stdout.decode("ascii")
    assert proc.returncode == 0
    assert "NARROW column 'week_of_marketing_year' bigint -> int (refused)" in out
    assert "does NOT go through apply_table" in out
    assert "bounded override" in out


def test_the_bounded_override_covers_only_the_debt_columns():
    """The override is a LIST, not a mode. An unsafe entry outside the expected reverse set -- a
    DROP, a partition-key change, some third column narrowed -- must still refuse."""
    mod = _runbook_module()
    changes = [("week_of_marketing_year", "bigint", "int")]
    expected = mod.expected_reverse_unsafe(changes)
    assert expected == ["NARROW column 'week_of_marketing_year' bigint -> int (refused)"]

    ok = mod.MigrationPlan(table="silver_fgis", database="leviathan_test",
                           change_type=mod.ChangeType.ADDITIVE_UPDATE, live_hash="a",
                           desired_hash="b", unsafe=list(expected))
    assert mod.check_unsafe("silver_fgis", ok, changes, "ROLLBACK") == expected

    for extra in ("DROP column 'source' (refused)",
                  "NARROW column 'exports_mt_weekly' double -> float (refused)",
                  "partition-key change [('marketing_year', 'int')] -> [] (refused)"):
        bad = mod.MigrationPlan(table="silver_fgis", database="leviathan_test",
                                change_type=mod.ChangeType.ADDITIVE_UPDATE, live_hash="a",
                                desired_hash="b", unsafe=expected + [extra])
        with pytest.raises(mod.Refused) as exc:
            mod.check_unsafe("silver_fgis", bad, changes, "ROLLBACK")
        assert "bounded expected one" in str(exc.value)

    # and a WIDEN still refuses on ANY unsafe entry -- the override is rollback-only.
    with pytest.raises(mod.Refused):
        mod.check_unsafe("silver_fgis", ok, changes, "WIDEN")


def test_the_rollback_actually_restores_a_wide_catalog(fake_glue, fake_s3, tmp_path, capsys):
    """THE ROUND TRIP, AWS-FREE: narrow -> --apply -> wide -> --rollback -> narrow.

    Uses the estate's own in-memory Glue/S3 fakes and a REAL leviathan.silver.lease.Lease over the
    fake S3, so the fence, the live-hash re-check and restore_table's own post-restore hash
    verification all execute. This is the test that would have failed on a rollback routed through
    apply_table: it raises UnsafeMigration and nothing is restored."""
    mod = _runbook_module()
    tables = sorted(MIGRATION_FILES)

    def seed():
        for table in tables:
            snap = json.loads((_R0_RAW / f"{table}.get-table.json").read_text(encoding="utf-8"))
            fake_glue.tables[table] = json.loads(json.dumps(snap, default=str))

    def types(table):
        return {c["Name"]: c["Type"] for c in fake_glue.tables[table]["StorageDescriptor"]["Columns"]}

    def shape(table):
        t = fake_glue.tables[table]
        return (json.dumps(t.get("Parameters"), sort_keys=True),
                json.dumps(t.get("PartitionKeys"), sort_keys=True))

    seed()
    narrow = {t: types(t) for t in tables}
    shape_before = {t: shape(t) for t in tables}

    kw = dict(region="us-east-1", database=TEST_DB, bucket=TEST_BUCKET, lease_prefix="silver/",
              lease_id="pinned-writer-widening-deck", glue_client=fake_glue, s3_client=fake_s3,
              migrations_dir=tmp_path)
    assert mod.apply(tables, direction="WIDEN", **kw) == 0
    widened = capsys.readouterr().out
    for table, cols in _WIDE.items():
        for name, wide_type in cols.items():
            assert types(table)[name] == wide_type, f"{table}.{name} did not widen"

    assert mod.apply(tables, direction="ROLLBACK", **kw) == 0
    rolled = capsys.readouterr().out

    # THE ASSERTION THE WHOLE FIX EXISTS FOR: every one of the eleven columns is narrow again.
    for table in tables:
        assert types(table) == narrow[table], f"{table}: rollback did not restore the narrow types"
        assert shape(table) == shape_before[table], f"{table}: Parameters/PartitionKeys moved"
    assert "restored      : True" in rolled
    # four update_table calls: two widens, two restores.
    assert [c for c in fake_glue.calls if c[0] == "update_table"] == [
        ("update_table", "silver_fgis"), ("update_table", "silver_modis_ndvi"),
        ("update_table", "silver_fgis"), ("update_table", "silver_modis_ndvi")]
    # the projection grid survived both mutations.
    params = fake_glue.tables["silver_fgis"]["Parameters"]
    assert sorted(k for k in params if k.startswith("projection.")) == [
        "projection.enabled", "projection.leviathan_slug.type", "projection.leviathan_slug.values",
        "projection.marketing_year.range", "projection.marketing_year.type"]
    assert params["storage.location.template"]

    # AND THE STEPS ARE DIRECTION-GATED. After a rollback the catalog is NARROW: telling the owner
    # to fire the canonical rewrite, or to empty the debt map, would produce exactly the state the
    # whole package exists to prevent -- wide parquet under a narrow catalog with the tripwire gone.
    assert "POST-APPLY STEPS" in widened
    assert "LET THE CANONICAL REWRITE HAPPEN" in widened
    assert "POST-ROLLBACK STEPS" in rolled
    assert "POST-APPLY STEPS" not in rolled
    assert "LET THE CANONICAL REWRITE HAPPEN" not in rolled
    assert "EXPECTED_DEBT = {}" not in rolled
    assert "do NOT empty EXPECTED_DEBT" in rolled
    for text in (widened, rolled):
        text.encode("ascii")
        assert "&&" not in text
    # a rollback leaves an audit record: restore_table writes no machine manifest of its own.
    assert sorted(p.name.split("_", 1)[1] for p in tmp_path.iterdir()) == [
        "silver_fgis_additive_update.json", "silver_fgis_rollback_restore.json",
        "silver_modis_ndvi_additive_update.json", "silver_modis_ndvi_rollback_restore.json"]


def test_a_half_applied_run_is_never_reported_as_no_mutation():
    """``--table all`` mutates two tables under one lease. If the second fails, the exit-4 handler
    must name the first -- an owner told 'nothing was mutated' would leave a half-moved catalog."""
    mod = _runbook_module()
    assert "nothing was mutated by this runbook." in mod._mutation_status("REFUSED")
    mod._MUTATED.append("silver_fgis")
    try:
        msg = mod._mutation_status("ERROR")
        assert "silver_fgis" in msg and "HALF-MOVED" in msg
        assert "nothing was mutated" not in msg
    finally:
        del mod._MUTATED[:]


def test_the_read_probe_fails_closed_on_zero_rows():
    """Under partition projection a MISSING partition returns zero rows without touching a parquet
    byte. An empty result therefore proves nothing about readability -- which is the one thing this
    probe exists to prove -- so 0 rows must be a FAILURE, not an 'OK -- 0 row(s)'."""
    mod = _runbook_module()

    class _WG:
        @staticmethod
        def get_work_group(WorkGroup):
            return {"WorkGroup": {"Configuration": {"EngineVersion": {
                "EffectiveEngineVersion": "Athena engine version 3",
                "SelectedEngineVersion": "AUTO"}}}}

    rc = mod.verify_read(["silver_fgis"], region="us-east-1", database=TEST_DB, client=_WG(),
                         runner=lambda client, sql, database=None: [])
    assert rc == 3
    rc_ok = mod.verify_read(["silver_fgis"], region="us-east-1", database=TEST_DB, client=_WG(),
                            runner=lambda client, sql, database=None: [{"n": 1}])
    assert rc_ok == 0


# ---------------------------------------------------------------------------
# 6. THE 2026-09-10 04:07Z FAILURE, AND THE THREE DEFECTS IT EXPOSED.
#
# MEASURED, on the owner's console: `--apply` passed preflight on both tables (VersionId 0 each),
# took the lease, widened silver_fgis in Glue -- and then died inside
# CatalogMigrator._write_migration_manifest with `TypeError: Object of type datetime is not JSON
# serializable`. The handler printed "ERROR -- nothing was mutated by this runbook." A read-only
# get_table at 04:15Z: silver_fgis VersionId 1, week_of_marketing_year bigint, all nine Parameters
# and both PartitionKeys intact; silver_modis_ndvi VersionId 0, all ten columns still narrow.
#
# Three defects, one incident:
#   (a) the manifest writer had no default=str, and plan.table_input IS the LIVE table with the
#       read-only fields dropped -- a drop set that deliberately KEEPS LastAccessTime, which boto3
#       returns as a datetime;
#   (b) the accounting inferred what moved from WHERE the exception fired, and this exception fired
#       after glue.update_table had already returned;
#   (c) the type precondition treated "already wide" as a refusal, so the same command could not
#       finish the half-done job.
#
# Every fake below returns boto3-SHAPED tables -- real datetimes, and a VersionId that moves --
# because the shared FakeGlue is seeded through json.dumps(default=str) and therefore never carried
# the datetime that fired. That is why the happy path was green while broken.
# ---------------------------------------------------------------------------
_APPLY_CLOCK = datetime(2026, 9, 10, 4, 7, 46, tzinfo=timezone.utc)


class Boto3ShapedGlue(FakeGlue):
    """FakeGlue plus the two behaviours the shared fake does not model -- the two that hid the bug.

    * ``get_table`` hands back ``CreateTime`` / ``UpdateTime`` / ``LastAccessTime`` as ``datetime``
      objects, the way boto3 does.
    * ``update_table`` BUMPS ``VersionId`` and moves ``UpdateTime``, so "VersionId 0 -> 1" is a
      measurement rather than a claim -- and the APPLIED / NOT APPLIED verdict, which is keyed off
      VersionId movement, is exercised for real.
    """

    def __init__(self, clock=_APPLY_CLOCK):
        super().__init__()
        self.clock = clock

    def seed(self, table: str, *, wide: bool = False, version: str = "0") -> dict:
        snap = _wide_snapshot(table) if wide else json.loads(
            (_R0_RAW / f"{table}.get-table.json").read_text(encoding="utf-8"))
        live = json.loads(json.dumps(snap, default=str))
        for key in ("CreateTime", "UpdateTime", "LastAccessTime"):
            if isinstance(live.get(key), str):
                live[key] = datetime.fromisoformat(live[key])
        live["VersionId"] = version
        self.tables[table] = live
        return live

    def update_table(self, DatabaseName, TableInput, **kw):
        name = TableInput["Name"]
        before = dict(self.tables.get(name) or {})
        super().update_table(DatabaseName=DatabaseName, TableInput=TableInput, **kw)
        now = self.tables[name]
        # Glue keeps the read-only fields the TableInput cannot carry, and bumps the version.
        now["VersionId"] = str(int(before.get("VersionId", "0")) + 1)
        now["CreateTime"] = before.get("CreateTime")
        now["UpdateTime"] = self.clock
        now.setdefault("LastAccessTime", before.get("LastAccessTime"))
        return {}


@pytest.fixture()
def migrations_dir(tmp_path):
    """A tmp migrations directory carrying the two HAND-AUTHORED manifests -- the reconstruction
    path reads its pre-apply backup basis out of them, so an empty directory would test a
    degraded branch instead of the real one."""
    out = tmp_path / "migrations"
    out.mkdir()
    for name in MIGRATION_FILES.values():
        shutil.copy(_MIGRATIONS / name, out / name)
    return out


def _apply_kw(glue, s3, migrations_dir, lease_id):
    return dict(region="us-east-1", database=TEST_DB, bucket=TEST_BUCKET, lease_prefix="silver/",
                lease_id=lease_id, glue_client=glue, s3_client=s3, migrations_dir=migrations_dir)


def _verdict_line(out: str, table: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip().startswith(table + " ")]
    assert lines, f"no re-read verdict line for {table}"
    return lines[0]


def test_the_happy_path_applies_both_tables_through_a_boto3_shaped_catalog(
        fake_s3, migrations_dir, capsys):
    """THE PATH THAT WAS NEVER EXERCISED END TO END. Both tables, from a catalog whose get_table
    returns datetimes, all the way to a manifest that parses. Before the datetime fix this run
    widened silver_fgis and then raised."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    tables = sorted(MIGRATION_FILES)
    for table in tables:
        glue.seed(table)

    assert mod.apply(tables, direction="WIDEN",
                     **_apply_kw(glue, fake_s3, migrations_dir, "deck-happy")) == 0
    out = capsys.readouterr().out
    out.encode("ascii")                                  # the owner's console is cp1252
    assert "&&" not in out

    for table, cols in _WIDE.items():
        live = glue.tables[table]
        assert live["VersionId"] == "1", f"{table}: VersionId did not move"
        types = {c["Name"]: c["Type"] for c in live["StorageDescriptor"]["Columns"]}
        for name, wide in cols.items():
            assert types[name] == wide, f"{table}.{name} did not widen"
    assert out.count("VersionId     : 0  ->  1") == 2

    # THE MANIFESTS -- written, and RE-PARSED. This is the assertion that fails without default=str.
    for table in MIGRATION_FILES:
        paths = list(migrations_dir.glob(f"*_{table}_additive_update.json"))
        assert len(paths) == 1, f"{table}: {[p.name for p in paths]}"
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        assert payload["change_type"] == "additive_update"
        assert payload["guard_mode"] == "canonical"
        # the datetime that fired, carried through as a string -- on the PLAN half, which is the
        # half that raised (the backup half was already datetime-safe via migrate._serializable).
        last_access = payload["plan"]["table_input"]["LastAccessTime"]
        assert isinstance(last_access, str) and datetime.fromisoformat(last_access)
        assert payload["backup"]["table_input"]["Name"] == table
    assert "POST-APPLY STEPS" in out


def test_a_mid_run_failure_after_update_table_reports_the_truth_per_table(
        fake_s3, migrations_dir, monkeypatch, capsys):
    """THE 04:07Z INCIDENT ITSELF -- reproduced, and accounted for.

    The manifest writer is made to raise the exact TypeError the owner saw, which puts the failure
    in the one window that matters: AFTER glue.update_table returned on the first table and BEFORE
    the loop recorded it. The run must then say what the CATALOG says -- silver_fgis APPLIED,
    silver_modis_ndvi NOT APPLIED -- write the record the failed writer owed, and never print
    'nothing was mutated'."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    tables = sorted(MIGRATION_FILES)                     # fgis first, modis second
    for table in tables:
        glue.seed(table)

    def _raise_like_the_owners_console(self, plan, backup):
        raise TypeError("Object of type datetime is not JSON serializable")

    monkeypatch.setattr(CatalogMigrator, "_write_migration_manifest",
                        _raise_like_the_owners_console)

    with pytest.raises(TypeError):
        mod.apply(tables, direction="WIDEN",
                  **_apply_kw(glue, fake_s3, migrations_dir, "deck-midrun"))
    out = capsys.readouterr().out
    out.encode("ascii")

    # THE CATALOG: the first table moved, the second never was attempted.
    assert glue.tables["silver_fgis"]["VersionId"] == "1"
    assert glue.tables["silver_modis_ndvi"]["VersionId"] == "0"
    assert [c for c in glue.calls if c[0] == "update_table"] == [("update_table", "silver_fgis")]

    # 1. THE REPORT, from a re-read -- not from where the exception fired.
    assert "WHAT ACTUALLY HAPPENED -- every table RE-READ from live Glue" in out
    fgis = _verdict_line(out, "silver_fgis")
    assert "APPLIED" in fgis and "NOT APPLIED" not in fgis
    assert "VersionId 0 -> 1" in fgis
    assert "NOT APPLIED" in _verdict_line(out, "silver_modis_ndvi")
    assert "MOVED      : silver_fgis" in out
    assert "NOT MOVED  : silver_modis_ndvi" in out
    assert "UNKNOWN    : (none)" in out

    # 2. THE EXIT LINE the handler prints can no longer say nothing moved.
    assert mod._MUTATED == ["silver_fgis"]
    status = mod._mutation_status("ERROR")
    assert "silver_fgis" in status and "HALF-MOVED" in status
    assert "nothing was mutated" not in status
    assert "nothing was mutated by this runbook." not in out

    # 3. THE RECORD the failed writer owed, written from the re-read.
    paths = list(migrations_dir.glob("*_silver_fgis_additive_update.json"))
    assert len(paths) == 1, [p.name for p in paths]
    m = json.loads(paths[0].read_text(encoding="utf-8"))
    assert m["applied"] is True and m["reconstructed"] is True
    assert m["applied_at"] == _APPLY_CLOCK.isoformat(), "applied_at must be the LIVE UpdateTime"
    assert m["post_apply"]["version_id"] == "1"
    assert m["post_apply"]["column_types"]["week_of_marketing_year"] == "bigint"
    # the BACKUP is the PRE-apply TableInput this run froze: what a rollback would restore.
    assert m["backup"]["version_id"] == "0"
    backup_types = {c["Name"]: c["Type"] for c in
                    m["backup"]["table_input"]["StorageDescriptor"]["Columns"]}
    assert backup_types["week_of_marketing_year"] == "int"
    # nothing is written for the table that never moved.
    assert list(migrations_dir.glob("*_silver_modis_ndvi_additive_update.json")) == []

    # 4. AND THE WAY OUT is the same command, because the re-run is now idempotent.
    assert "TO FINISH THE JOB, re-run the SAME command" in out


def test_the_re_run_skips_the_already_wide_table_and_applies_the_rest(
        fake_s3, migrations_dir, capsys):
    """(c) IDEMPOTENCE, AGAINST THE STATE THE ESTATE IS ACTUALLY IN. Live Glue at 04:15Z:
    silver_fgis VersionId 1 and wide, silver_modis_ndvi VersionId 0 and narrow. The SAME --apply
    must finish the job -- skip the first, apply the second, exit 0."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    glue.seed("silver_fgis", wide=True, version="1")
    glue.seed("silver_modis_ndvi")

    assert mod.apply(sorted(MIGRATION_FILES), direction="WIDEN",
                     **_apply_kw(glue, fake_s3, migrations_dir, "deck-rerun")) == 0
    out = capsys.readouterr().out
    out.encode("ascii")

    assert "ALREADY WIDE: silver_fgis (VersionId 1, UpdateTime" in out
    assert "-- skipping." in out
    assert "preflight OK: silver_modis_ndvi" in out
    # exactly ONE update_table: the skipped table was never written to.
    assert [c for c in glue.calls if c[0] == "update_table"] == [
        ("update_table", "silver_modis_ndvi")]
    assert glue.tables["silver_fgis"]["VersionId"] == "1"
    assert glue.tables["silver_modis_ndvi"]["VersionId"] == "1"

    # the skipped table carried no applied record, so one is RECONSTRUCTED from the live read plus
    # the pre-apply basis the hand-authored manifest certifies.
    recon = json.loads(next(migrations_dir.glob("*_silver_fgis_additive_update.json"))
                       .read_text(encoding="utf-8"))
    assert recon["applied"] is True and recon["reconstructed"] is True
    assert recon["backup"]["certifying_field"] == "plan_hashes.live_hash_at_authoring"
    assert recon["backup"]["table_input"] is not None
    assert recon["backup"]["unavailable_reason"] is None

    # the post-apply sequence covers BOTH tables: a skipped table still owes the read probe, the
    # canonical rewrite, the R0 re-capture and its EXPECTED_DEBT line.
    steps = out.split("POST-APPLY STEPS", 1)[1]
    for table in MIGRATION_FILES:
        assert f"--table {table} --verify-read" in steps


def test_a_fully_applied_estate_takes_no_lease_and_exits_zero(fake_s3, migrations_dir, capsys):
    """Both tables already wide. There is nothing to mutate, so no lease is taken -- a lease is a
    licence to mutate, not a formality."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    for table in sorted(MIGRATION_FILES):
        glue.seed(table, wide=True, version="1")

    assert mod.apply(sorted(MIGRATION_FILES), direction="WIDEN",
                     **_apply_kw(glue, fake_s3, migrations_dir, "deck-done")) == 0
    out = capsys.readouterr().out
    out.encode("ascii")
    assert "NOTHING TO DO -- all 2 table(s) are ALREADY WIDE" in out
    assert [c for c in glue.calls if c[0] == "update_table"] == []
    assert fake_s3.store == {}, "no lease object should exist: nothing was mutated"


def test_preflight_still_refuses_a_table_that_is_neither_narrow_nor_wide(fake_s3, migrations_dir):
    """THE SKIP IS NOT A RELAXATION. A table in a THIRD state -- one debt column widened, the other
    nine narrow -- is neither 'already done' nor 'still to do'. It is a catalog nobody measured,
    and it still refuses, naming the column."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    live = glue.seed("silver_modis_ndvi")
    for col in live["StorageDescriptor"]["Columns"]:
        if col["Name"] == "year":
            col["Type"] = "bigint"                       # one of ten
    assert mod.live_shape(live, mod.EXPECTED_WIDENING["silver_modis_ndvi"]) == mod.MIXED

    with pytest.raises(mod.Refused) as exc:
        mod.apply(["silver_modis_ndvi"], direction="WIDEN",
                  **_apply_kw(glue, fake_s3, migrations_dir, "deck-mixed"))
    assert "year" in str(exc.value) and "expected exactly 'smallint'" in str(exc.value)
    assert [c for c in glue.calls if c[0] == "update_table"] == []
    assert list(migrations_dir.glob("*_additive_update.json")) == []


def test_record_applied_reconstructs_the_manifest_for_a_widen_that_landed(
        migrations_dir, capsys):
    """(d) THE FGIS RECORD, as a mechanism. Read-only on AWS: one get_table, no update_table, no
    lease. It proves the catalog is at the PLANNED wide state before it claims anything, and the
    record it writes carries the executable pre-apply TableInput a rollback would restore."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    glue.seed("silver_fgis", wide=True, version="1")

    rc = mod.record_applied("silver_fgis", region="us-east-1", database=TEST_DB,
                            glue_client=glue, migrations_dir=migrations_dir)
    out = capsys.readouterr().out
    assert rc == 0, out[-3000:]
    out.encode("ascii")
    assert [c for c in glue.calls if c[0] != "get_table"] == [], "this mode must not mutate"
    assert "NOTHING WAS MUTATED IN AWS by this command" in out

    m = json.loads(next(migrations_dir.glob("*_silver_fgis_additive_update.json"))
                   .read_text(encoding="utf-8"))
    assert m["applied"] is True and m["reconstructed"] is True
    assert m["applied_at"] == glue.tables["silver_fgis"]["UpdateTime"].isoformat()
    assert m["post_apply"]["column_types"]["week_of_marketing_year"] == "bigint"
    assert m["backup"]["certifying_field"] == "plan_hashes.live_hash_at_authoring"
    assert {c["Name"]: c["Type"] for c in
            m["backup"]["table_input"]["StorageDescriptor"]["Columns"]}[
                "week_of_marketing_year"] == "int"
    assert "TypeError" in m["reconstructed_note"]

    # a SECOND run refuses: one mutation, one record.
    with pytest.raises(mod.Refused) as exc:
        mod.record_applied("silver_fgis", region="us-east-1", database=TEST_DB,
                           glue_client=glue, migrations_dir=migrations_dir)
    assert "already exists" in str(exc.value)


def test_record_applied_refuses_a_table_that_is_not_wide(migrations_dir):
    """The record is a CLAIM about the catalog, so it is gated on the catalog. A narrow table gets
    no record, whatever anyone believes happened to it."""
    mod = _runbook_module()
    glue = Boto3ShapedGlue()
    glue.seed("silver_modis_ndvi")
    with pytest.raises(mod.Refused) as exc:
        mod.record_applied("silver_modis_ndvi", region="us-east-1", database=TEST_DB,
                           glue_client=glue, migrations_dir=migrations_dir)
    assert "not at the target types" in str(exc.value)
    assert list(migrations_dir.glob("*_additive_update.json")) == []


def test_the_dry_run_reports_an_already_wide_table_instead_of_refusing(wide_dir):
    """Post-apply step 1 tells the owner to CONFIRM the widen with a bare dry-run. A dry-run that
    refuses because the widen SUCCEEDED reads like a fault -- and the printed remedy for a fault
    here is a rollback."""
    proc = _run("--offline", "--offline-dir", str(wide_dir))
    out = proc.stdout.decode("ascii")
    assert proc.returncode == 0, out[-3000:]
    assert "ALREADY WIDE (VersionId" in out
    assert "-- skipping." in out
    assert "ALREADY WIDE (skipped, nothing to plan): silver_fgis, silver_modis_ndvi" in out
    assert "DRY RUN -- NOTHING WAS MUTATED" in out


def test_the_runbook_pins_the_same_eleven_columns_as_the_manifests():
    """The runbook's EXPECTED_WIDENING is a third copy of the same list. It re-derives it from the
    registry at runtime, but the literal itself is pinned here against the manifests so a reader of
    either file sees the same eleven columns."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_pw_widening_runbook", _RUNBOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.EXPECTED_WIDENING) == set(MIGRATION_FILES)
    assert mod.MIGRATION_FILES == MIGRATION_FILES
    for table, triples in mod.EXPECTED_WIDENING.items():
        m = _manifest(table)
        assert triples == [(c["name"], c["from_glue_type"], c["to_glue_type"])
                           for c in m["widened_columns"]], table
    total = sum(len(v) for v in mod.EXPECTED_WIDENING.values())
    assert total == 11, f"the measured debt is eleven columns, got {total}"
