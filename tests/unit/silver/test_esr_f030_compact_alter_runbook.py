"""THE silver_esr_compact ADD COLUMNS, AND THE RUNBOOK THAT APPLIES IT (SILVER-F030 BF-W2).

WHAT THIS DECK IS FOR. ``sql/athena/migrations/silver/silver_esr_f030_additive.sql`` states the
migration and its refusal; ``scripts/ops/esr_netcommitment_runbook.py --step S5`` states the
sequence. This deck holds the EXECUTION: that
``scripts/ops/esr_f030_compact_alter_runbook.py`` plans exactly the five columns that file ALTERs,
in that order, at the tail; that it refuses every shape it was not measured against; that it never
touches ``silver_esr``; that its rollback actually restores; and that a failure between
``glue.update_table`` returning and the record being written is reported from the CATALOG rather
than from where the exception fired.

IT SURVIVES ITS OWN CLOSURE. The five are staged in the F010 contract as physical-only
(``glue_type: null``) today. After the ALTER and the step-4 registry regeneration they carry
``glue_type: double``, and ``five_from_registry`` reports ``REGISTERED`` instead of
``STAGED_HIDDEN``. Every test below reads that state rather than assuming the pre-flip one, so the
deck does not have to be rewritten by the commit that closes the migration -- and the one test that
DOES pin today's state says so in its own name.

AWS-FREE, no network: the tracked migration SQL, the tracked F010 registry, THE TRACKED MACHINE
MANIFEST ``sql/athena/migrations/silver/<UTC>_silver_esr_compact_additive_update.json`` (whose two
halves -- ``backup.table_input`` and ``plan.table_input`` -- carry their own catalog digests), the
estate's in-memory Glue/S3 fakes, and subprocess runs of the runbook in ``--offline`` mode.

IT READS NO GITIGNORED FILE AS A BASIS (2026-09-11). Until today this deck and the runbook both
called ``reports/silver_readiness/20260712_p65impl/tables/silver_esr_compact.json`` "the tracked R0
record". It was never tracked -- ``.gitignore`` carries a ``reports/silver_readiness/`` rule -- and
it is a LIVING file the runbook's own post-apply step [2] re-captures, so once the ALTER landed it
became the 17-column POST-ALTER shape under ``run_census`` recipe v2 and every offline mode refused.
The narrow basis is now the machine manifest, which git tracks and the mutation wrote once; the two
tests that still want the gitignored ``_raw`` sidecar SKIP with the reason stated when it is absent.

THE RULE IS NAMED, NEVER ITS LINE NUMBER. This deck's first form cited ``.gitignore:77`` in six
places and asserted that literal in the runbook's source and printed text, which made a rotting
figure load-bearing: MEASURED 2026-09-11, that rule was line 77 at HEAD and line 91 in the working
tree an hour later, because a concurrent lane inserted fourteen lines above it. The FACT is
measured instead, by ``git check-ignore``, in
``test_the_tracked_basis_is_a_file_git_can_track_and_the_r0_record_is_not``.

THREE THINGS THE STEP-4 FLIP TOOK AWAY FROM THE SUBPROCESS. Since the registry declares the five,
``assert_registry_not_ahead`` answers FIRST on every subprocess route to a printed plan: a narrow
offline source is "THE REGISTRY LEADS LIVE GLUE" and any ``--rollback`` is "the step-4 registry flip
has ALREADY LANDED" (exit 2 -- which is what the live ``--rollback --dry-run`` does today, and is
correct). The plan-printing code is unchanged and still has to be exercised, so the tests that read
a plan drive ``dry_run`` in process with the CONTRACT STATE -- and only that -- put back to its
pre-flip value, and the subprocess keeps pinning the fence that now answers.

THE ONE MEASUREMENT THIS DECK CANNOT MAKE is whether the objects still read under the widened
catalog. That is ``--verify-read``, it needs live Athena, and the authoring lane is read-only on
AWS -- so what is pinned here is that the probe is partition-filtered, names all five, and FAILS
CLOSED on zero rows.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# conftest: the allowlisted in-memory test surface (tests/unit/silver/conftest.py). NEVER the prod
# bucket or the prod database -- the round-trip tests below drive the real mutating code path.
from conftest import TEST_BUCKET, TEST_DB, FakeGlue  # noqa: E402
from leviathan.silver import catalog
from leviathan.silver.migrate import CatalogMigrator, UnsafeMigration
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[3]
_RUNBOOK = _REPO / "scripts" / "ops" / "esr_f030_compact_alter_runbook.py"
_MIGRATIONS = _REPO / "sql" / "athena" / "migrations" / "silver"
_MIGRATION_SQL = _MIGRATIONS / "silver_esr_f030_additive.sql"
_R0_RECORD = (_REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "tables"
              / "silver_esr_compact.json")
_R0_SIDECAR = (_REPO / "reports" / "silver_readiness" / "20260712_p65impl" / "_raw"
               / "silver_esr_compact.get-table.json")

TABLE = "silver_esr_compact"
REFUSED_TABLE = "silver_esr"


def _manifest_path() -> Path:
    """THE TRACKED RECORD of this ALTER, named by the deck independently of the runbook.

    ``CatalogMigrator`` writes ``<UTC>_<table>_<change_type>.json``; exactly one such file exists
    for this table, and it is the basis every test below builds on."""
    found = sorted(_MIGRATIONS.glob(f"*_{TABLE}_additive_update.json"))
    assert len(found) == 1, [p.name for p in found]
    return found[0]


def _manifest() -> dict:
    return json.loads(_manifest_path().read_text(encoding="utf-8"))


def _gitignored_json(path: Path, what: str) -> dict:
    """Read a file the repo does NOT track, or SKIP with the reason stated.

    ``reports/silver_readiness/`` is gitignored (that rule is in ``.gitignore``; the RULE is cited,
    never its line number, which moves) and ``git ls-files`` returns nothing under it, so a fresh
    clone has neither the R0 record nor the ``_raw`` sidecar. A deck
    that reads one unguarded fails at the read, for a reason that has nothing to do with the code
    under test -- which is exactly how the runbook came to call an untracked file 'tracked'."""
    if not path.exists():
        pytest.skip(f"{what} is not on disk ({path}); reports/silver_readiness/ is GITIGNORED "
                    "(the reports/silver_readiness/ rule in .gitignore), so a fresh clone carries "
                    "no copy. The runbook's tracked basis is the machine manifest, which this "
                    "deck pins directly.")
    return json.loads(path.read_text(encoding="utf-8"))

# The five, in the migration file's order. Written out here so the deck states the target
# independently of the module it is testing -- a runbook that agrees only with itself proves
# nothing.
FIVE = [
    ("accumulated_exports_1000mt", "double"),
    ("current_my_net_sales_1000mt", "double"),
    ("current_my_total_commitment_1000mt", "double"),
    ("next_my_outstanding_sales_1000mt", "double"),
    ("next_my_net_sales_1000mt", "double"),
]
FIVE_NAMES = [n for n, _ in FIVE]

# MEASURED 2026-09-10 by glue.get_table against leviathan_dev: VersionId 1, 12 non-partition
# columns, `source` last, two partition keys.
LIVE_COLUMNS = 12
LIVE_PARTITION_KEYS = [("commodity", "string"), ("as_of_date", "string")]


def _runbook_module():
    spec = importlib.util.spec_from_file_location("_esr_f030_alter_runbook", _RUNBOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _runbook_module()


@pytest.fixture()
def clean_globals(mod):
    """``_MUTATED`` / ``_VERDICTS`` are module state by design (the exit summary reads them). Keep
    one test's half-applied run out of the next test's verdict."""
    del mod._MUTATED[:]
    del mod._VERDICTS[:]
    yield
    del mod._MUTATED[:]
    del mod._VERDICTS[:]


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_RUNBOOK), *args],
                          cwd=str(_REPO), capture_output=True, timeout=300)


def _alter_body(half: str) -> list[tuple[str, str]]:
    """[(column, type)] from one ``ALTER TABLE leviathan_dev.<half> ADD COLUMNS (...)`` statement in
    the tracked migration file -- parsed, never assumed."""
    sql = _MIGRATION_SQL.read_text(encoding="utf-8")
    marker = f"ALTER TABLE leviathan_dev.{half} ADD COLUMNS ("
    assert marker in sql, f"{_MIGRATION_SQL.name} no longer carries the {half} statement"
    body = sql.split(marker, 1)[1].split(");", 1)[0]
    out = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        parts = line.split()
        out.append((parts[0], parts[1]))
    return out


# ---------------------------------------------------------------------------
# 1. THE RUNBOOK, THE MIGRATION FILE AND THE CONTRACT DESCRIBE THE SAME FIVE COLUMNS.
# ---------------------------------------------------------------------------
def test_the_runbook_plans_exactly_what_the_migration_file_alters(mod):
    """Same names, same Glue types, SAME ORDER. Order is load-bearing twice over: Glue's ADD
    COLUMNS appends at the tail, and catalog.is_schema_widen admits ONLY a pure trailing append --
    a reordered plan would strand every registered partition descriptor."""
    assert _alter_body(TABLE) == FIVE
    assert list(mod.FIVE) == [tuple(c) for c in FIVE]
    assert list(mod.FIVE_NAMES) == FIVE_NAMES


def test_the_runbook_re_derives_the_five_from_the_contract(mod):
    """``five_from_registry`` reads the F010 contract at every run, so the runbook and the registry
    cannot drift apart in silence. Today the contract stages them physical-only; after the step-4
    flip it declares them double, and BOTH are legal states of this function."""
    state, five = mod.five_from_registry()
    assert state in (mod.STAGED_HIDDEN, mod.REGISTERED)
    assert five == FIVE


def test_the_contract_registers_the_five_today(mod):
    """THE ONE TEST THAT PINS TODAY'S STATE. It was written asserting STAGED_HIDDEN and named so
    the flip would be a one-line edit and not a puzzle; the ALTER landed 2026-09-10 and step [4]
    regenerated the registry, so it now pins the post-ALTER state: the contract declares all five
    as double and nothing is left hidden.

    NOTE FOR THE NEXT READER: the runbook's printed step [4] named only the two tests in
    test_esr_contract_rebaseline.py and test_ddl_generation.py and missed this one, which goes red
    on the same regeneration. Corrected 2026-09-11 -- step [4] now names three, this one included,
    and test_the_post_apply_steps_name_every_file_the_commit_touches holds it there."""
    state, _five = mod.five_from_registry()
    contract = load_registry().table(TABLE)
    hidden = [c["name"] for c in contract["physical_columns"] if not c.get("glue_type")]
    assert state == mod.REGISTERED, (
        "the registry no longer declares the five -- the contract has regressed to the "
        "pre-ALTER staged-hidden form while live Glue carries 17 columns")
    assert hidden == []


def test_the_five_are_the_contracts_last_five_columns_after_source(mod):
    names = [c["name"] for c in load_registry().table(TABLE)["physical_columns"]]
    assert names[-5:] == FIVE_NAMES
    assert names[-6] == mod.ANCHOR_COLUMN == "source"


def test_the_pinned_narrow_shape_is_the_tracked_machine_manifest(mod):
    """The 12 columns the preflight demands are not a memory: they are the TRACKED machine
    manifest's own ``backup.table_input`` -- the pre-apply glue.get_table snapshot the mutation
    froze -- column for column, type for type, IN ORDER, plus its two partition keys.

    THIS TEST USED TO READ THE R0 RECORD. It cannot any more, and the reason is the whole point of
    the re-anchor: the runbook's own post-apply step [2] re-captures that record to the 17-column
    POST-ALTER shape, so a 12-column assertion against it went red the day the ALTER landed. The
    manifest is written ONCE, by the mutation, and never re-captured."""
    backup = _manifest()["backup"]["table_input"]
    assert [(c["Name"], c["Type"]) for c in backup["StorageDescriptor"]["Columns"]] == list(
        mod.NARROW_COLUMNS)
    assert len(mod.NARROW_COLUMNS) == LIVE_COLUMNS == len(backup["StorageDescriptor"]["Columns"])
    assert [(p["Name"], p["Type"]) for p in backup["PartitionKeys"]] == LIVE_PARTITION_KEYS
    assert list(mod.PARTITION_KEYS) == LIVE_PARTITION_KEYS
    assert mod.NARROW_NAMES[-1] == "source"


def test_the_tracked_basis_is_a_file_git_can_track_and_the_r0_record_is_not(mod):
    """THE DEFECT THIS DECK NOW GUARDS. A runbook may not call a file 'tracked' unless git can
    track it. ``git check-ignore`` is the measurement: exit 1 = not ignored (the manifest, which
    lives under ``sql/``), exit 0 = ignored (the R0 record, matched by the
    ``reports/silver_readiness/`` rule in ``.gitignore``). The precedence rule exists because of
    that asymmetry, so it is asserted here rather than believed.

    THE RULE, NOT ITS LINE. ``check-ignore -v`` names the rule that actually matched, so the fact
    stays measured while the line number is free to move -- and it does: MEASURED 2026-09-11 this
    rule was ``.gitignore`` line 77 at HEAD and line 91 in the working tree within the hour. The
    deck's first form asserted the literal ``.gitignore:77`` in the runbook's source and in its
    printed step [4], which is a stale figure made load-bearing -- the very class this lane
    exists to remove. What is asserted now is that the runbook cites the RULE and cites no line
    number for it at all."""
    def check_ignore(path: Path) -> tuple[bool, str]:
        proc = subprocess.run(["git", "check-ignore", "-v", str(path)],
                              cwd=str(_REPO), capture_output=True, timeout=60)
        assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
        return proc.returncode == 0, proc.stdout.decode("utf-8", "replace").strip()

    manifest_ignored, _ = check_ignore(_manifest_path())
    assert not manifest_ignored, "the narrow basis must be a file git can track"
    r0_ignored, why = check_ignore(_R0_RECORD)
    assert r0_ignored, (
        "the R0 record is no longer gitignored -- re-read NARROW_BASIS_PRECEDENCE, which justifies "
        "the manifest's precedence partly on that fact")
    # THE RULE that matched, named by git itself -- "<file>:<line>:<pattern>\t<path>".
    assert "reports/silver_readiness/" in why, why
    assert why.split(":")[0].endswith(".gitignore"), why

    # and the runbook no longer claims otherwise, nor pins a line number that moves.
    src = _RUNBOOK.read_text(encoding="utf-8")
    assert "tracked R0 record" not in src
    assert "reports/silver_readiness/ rule in .gitignore" in src
    assert not re.search(r"\.gitignore:\d+", src), (
        "the runbook cites a .gitignore LINE NUMBER again -- cite the rule; the line moved from 77 "
        "to 91 inside one hour on 2026-09-11")


def test_the_narrow_basis_prefers_the_tracked_manifest_over_the_r0_record(mod):
    """THE PRECEDENCE RULE, PINNED. With a manifest on disk the narrow basis is the manifest's
    ``backup.table_input``, certified by ``backup.catalog_hash`` re-computed with
    ``catalog.hash_table`` -- not the R0 record, whatever shape that happens to be in today."""
    table, cert = mod.narrow_basis()
    assert cert["basis"] == "machine manifest"
    assert _manifest_path().name in cert["source"] and _manifest_path().name in cert["record"]
    assert cert["verified"] and cert["expected"] == cert["got"]
    assert cert["got"] == catalog.hash_table(table) == mod.MEASURED["live_catalog_hash"]
    assert [(c["Name"], c["Type"]) for c in table["StorageDescriptor"]["Columns"]] == list(
        mod.NARROW_COLUMNS)
    assert mod.live_shape(table, FIVE) == mod.AT_SOURCE
    # the precedence is stated in the module, not only implied by the code path.
    assert "MACHINE MANIFEST" in mod.NARROW_BASIS_PRECEDENCE[0]
    assert "R0 record" in mod.NARROW_BASIS_PRECEDENCE[1]


def test_the_narrow_basis_falls_back_to_the_r0_record_when_no_manifest_exists(mod, tmp_path,
                                                                             monkeypatch):
    """THE OTHER HALF OF THE PRECEDENCE -- the PRE-apply world, where there is no manifest yet.

    Both files are synthesized here rather than read from the tree: the R0 record is gitignored, so
    a deck that needs one has to write it. The record carries a recipe-v2 stamp and a digest minted
    by ``run_census.hash_block`` itself, which is what a pre-ALTER capture looks like today."""
    empty = tmp_path / "migrations"
    empty.mkdir()
    record = tmp_path / f"{TABLE}.json"
    record.write_text(json.dumps(_synth_r0_record(mod, recipe=2), indent=2), encoding="utf-8")
    monkeypatch.setattr(mod, "R0_RECORD", record)
    monkeypatch.setattr(mod, "MIGRATIONS_DIR", empty)

    table, cert = mod.narrow_basis()
    assert cert["basis"] == "R0 record"
    assert cert["verified"] and cert["expected"] == cert["got"]
    assert "recipe v2" in cert["field"]
    assert mod.live_shape(table, FIVE) == mod.AT_SOURCE
    # and the offline READ falls back with it: pre-apply, the record IS the current catalog.
    offline, ocert = mod.offline_table()
    assert ocert["basis"] == "R0 record"
    assert mod.live_shape(offline, FIVE) == mod.AT_SOURCE


def test_the_r0_certification_recomputes_under_the_recipe_the_record_stamps(mod, tmp_path,
                                                                           monkeypatch):
    """THE SECOND HALF OF THE DEFECT, PINNED. ``run_census`` has two hash recipes and every record
    says which one minted its digest; ``run_census.check_one`` selects on exactly that stamp
    (``legacy = "hash_recipe" not in stored.get("glue", {})``, run_census.py:378). Recomputing a v2
    record under v1 is a FALSE ALARM, and it is the one that cascaded into 12 errors on 2026-09-10.

    A stamp this runbook has no recomputation for is a REFUSAL, never a guess."""
    # build every record from the REAL narrow basis first; only then take the manifest away.
    records = {r: _synth_r0_record(mod, recipe=r) for r in (None, 1, 2, 99)}
    empty = tmp_path / "migrations"
    empty.mkdir()
    monkeypatch.setattr(mod, "MIGRATIONS_DIR", empty)

    for recipe in (None, 1, 2):                       # None = the ghost tool's unstamped v1
        record = tmp_path / f"r{recipe}.json"
        record.write_text(json.dumps(records[recipe]), encoding="utf-8")
        monkeypatch.setattr(mod, "R0_RECORD", record)
        _table, cert = mod.r0_record_table()
        assert cert["verified"], (recipe, cert)
        assert f"recipe v{1 if recipe is None else recipe}" in cert["field"], (recipe, cert)

    # a recipe-2 record recomputed under v1 is exactly the false alarm: the digests differ.
    census = mod._census_module()
    block = records[2]["glue"]
    assert census.hash_block(block) != census.catalog_hash_v1(
        census._record_glue_to_raw_shape(block))

    bad = tmp_path / "r99.json"
    bad.write_text(json.dumps(records[99]), encoding="utf-8")
    monkeypatch.setattr(mod, "R0_RECORD", bad)
    with pytest.raises(mod.Refused) as exc:
        mod.r0_record_table()
    assert "hash_recipe 99" in str(exc.value)


def test_the_offline_source_certifies_itself(mod):
    """``--offline`` RE-COMPUTES the digest that certifies whatever source it resolved, and refuses
    a source that cannot prove it is the table it claims to be.

    POST-ALTER both halves of the manifest are in play: ``plan.table_input`` is the executable
    TableInput ``update_table`` was handed (the CURRENT catalog) and ``backup.table_input`` is what
    it overwrote. Each is checked against its own stored digest AND against the runbook's pinned
    live measurement of that side."""
    table, cert = mod.offline_table()
    assert cert["basis"] == "machine manifest"
    assert cert["verified"] and cert["expected"] == cert["got"]
    assert cert["got"] == catalog.hash_table(table) == mod.MEASURED["live_catalog_hash_post_alter"]
    assert len(table["StorageDescriptor"]["Columns"]) == LIVE_COLUMNS + len(FIVE)
    assert mod.live_shape(table, FIVE) == mod.AT_TARGET
    # a TableInput carries no VersionId/UpdateTime, so those are the pinned live measurement and
    # the source line says so rather than letting them read as if the file carried them.
    assert table["VersionId"] == mod.MEASURED["live_version_id_post_alter"]
    assert table["UpdateTime"] == mod.MEASURED["live_update_time_post_alter"]
    assert "MEASURED" in cert["version_source"] and "glue.get_table" in cert["version_source"]

    narrow, ncert = mod.narrow_basis()
    assert ncert["got"] == mod.MEASURED["live_catalog_hash"] != cert["got"]
    assert mod.live_shape(narrow, FIVE) == mod.AT_SOURCE


def test_a_manifest_that_does_not_certify_itself_may_not_back_a_plan(mod, tmp_path, monkeypatch):
    """The manifest earns its precedence by proving itself, not by being tracked. A hand-edited
    backup (or another migration's manifest) fails the self-certification, and a backup that
    certifies but hashes to something other than the runbook's pinned live measurement fails the
    second fence -- both REFUSE rather than plan from whichever file was read first."""
    good = _manifest()
    for mutate, expect in (
            (lambda m: m["backup"]["table_input"]["StorageDescriptor"]["Columns"].pop(),
             "does not certify its own backup"),
            (lambda m: m["backup"].__setitem__("catalog_hash", "0" * 64),
             "does not certify its own backup"),
            (lambda m: m.__setitem__("backup", {}), "no usable backup.table_input")):
        payload = json.loads(json.dumps(good))
        mutate(payload)
        out = tmp_path / f"20260910T170043Z_{TABLE}_additive_update.json"
        out.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(mod.Refused) as exc:
            mod.narrow_basis(tmp_path)
        assert expect in str(exc.value), str(exc.value)

    # the pinned-measurement fence: a manifest that is internally consistent but is not THIS table.
    payload = json.loads(json.dumps(good))
    monkeypatch.setitem(mod.MEASURED, "live_catalog_hash", "f" * 64)
    out = tmp_path / f"20260910T170043Z_{TABLE}_additive_update.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(mod.Refused) as exc:
        mod.narrow_basis(tmp_path)
    assert "measured against LIVE GLUE" in str(exc.value)


def _reconstructed_manifest(mod, tmp_path: Path, *, drop_post_apply: bool = False) -> Path:
    """The real manifest re-shaped the way ``--record-applied`` writes one: ``plan: null``, with a
    self-certifying ``post_apply`` half instead.

    NOT A HYPOTHETICAL SHAPE. ``write_applied_manifest`` stores ``"plan": plan.to_dict() if plan is
    not None else None`` and ``record_applied`` passes no plan, so this is what this runbook's own
    repair mode produces -- and the estate already carries one: MEASURED 2026-09-11,
    ``sql/athena/migrations/silver/20260910T060216Z_silver_fgis_additive_update.json`` has
    ``reconstructed: true``, ``plan: null``, and a ``post_apply`` whose stored ``catalog_hash``
    re-hashes exactly under ``catalog.hash_table``."""
    payload = _manifest()
    wide = payload["plan"]["table_input"]
    payload["plan"] = None
    payload["applied"] = True
    payload["reconstructed"] = True
    if not drop_post_apply:
        payload["post_apply"] = {
            "version_id": "2",
            "update_time": mod.MEASURED["live_update_time_post_alter"],
            "catalog_hash": catalog.hash_table(wide),
            "column_types": {c["Name"]: c["Type"] for c in wide["StorageDescriptor"]["Columns"]},
            "table_input": wide,
        }
    out = tmp_path / _manifest_path().name
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def test_a_reconstructed_manifest_has_no_plan_and_offline_reads_it_anyway(mod, tmp_path,
                                                                         monkeypatch):
    """THE REPAIR MODE MAY NOT DESTROY THE CAPABILITY IT REPAIRS.

    ``--record-applied`` exists for the 04:07Z hole -- the ALTER landed and the migrator's manifest
    was never written (a MEASURED incident class on the sibling runbook, 2026-09-10). What it can
    honestly freeze is the POST-apply re-read, not a plan it never cut, so the manifest it writes
    carries ``plan: null`` and a ``post_apply`` half. A reader that knows only ``plan.table_input``
    turns ``--offline`` into a PERMANENT exit 2 in exactly that world -- and with no fallback,
    because the manifest file has already claimed the precedence and the R0 rung is unreachable.
    MEASURED 2026-09-11 before the fix: ``narrow_basis`` fine (12 columns), ``offline_table``
    Refused "carries no usable plan.table_input".

    So the halves are tried in order and ABSENCE falls through. NON-certification still refuses --
    that fence is not relaxed here, and its own test still stands."""
    path = _reconstructed_manifest(mod, tmp_path)

    narrow, ncert = mod.narrow_basis(tmp_path)
    assert ncert["basis"] == "machine manifest" and ncert["verified"]
    assert mod.live_shape(narrow, FIVE) == mod.AT_SOURCE

    wide, cert = mod.offline_table(tmp_path)
    assert cert["basis"] == "machine manifest" and cert["verified"]
    assert "post_apply.table_input" in cert["source"], cert["source"]
    assert cert["field"].startswith("post_apply.catalog_hash")
    assert cert["got"] == catalog.hash_table(wide) == mod.MEASURED["live_catalog_hash_post_alter"]
    assert mod.live_shape(wide, FIVE) == mod.AT_TARGET
    # a reconstructed record DOES carry VersionId/UpdateTime, so they are read, not pinned.
    assert wide["VersionId"] == "2"
    assert "post_apply.version_id" in cert["version_source"], cert["version_source"]

    # AND THE FENCE IS STILL A FENCE: a post_apply that does not certify itself refuses.
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["post_apply"]["catalog_hash"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(mod.Refused) as exc:
        mod.offline_table(tmp_path)
    assert "does not certify its own post_apply" in str(exc.value)


def test_a_manifest_with_neither_half_falls_to_the_r0_record_and_names_both_failures(
        mod, tmp_path, monkeypatch):
    """THE LAST RUNG, AND THE REFUSAL THAT NAMES BOTH. A manifest with no ``plan`` and no
    ``post_apply`` describes the pre-apply table only, so the CURRENT catalog has to come from the
    R0 record -- which post-ALTER is the right answer, because step [2] re-captured it to the wide
    shape. When that file is absent too (a fresh clone), the refusal says what was missing on the
    manifest AND what was missing on disk, rather than reporting only whichever was read last."""
    _reconstructed_manifest(mod, tmp_path, drop_post_apply=True)
    record = tmp_path / f"{TABLE}.json"
    record.write_text(json.dumps(_synth_r0_record(mod, recipe=2)), encoding="utf-8")
    monkeypatch.setattr(mod, "R0_RECORD", record)

    table, cert = mod.offline_table(tmp_path)
    assert cert["basis"] == "R0 record" and cert["verified"]
    assert mod.live_shape(table, FIVE) == mod.AT_SOURCE   # the synthesized record is pre-ALTER

    monkeypatch.setattr(mod, "R0_RECORD", tmp_path / "nowhere.json")
    with pytest.raises(mod.Refused) as exc:
        mod.offline_table(tmp_path)
    message = str(exc.value)
    assert "plan.table_input" in message and "post_apply.table_input" in message
    assert "the R0 record is not on disk" in message


def test_record_applied_writes_a_manifest_its_own_offline_mode_can_read(
        mod, narrow_table, migrations_dir, capsys, clean_globals):
    """END TO END, THROUGH THE REAL WRITER. A catalog that IS wide with no record beside it (the
    04:07Z hole), reconstructed by ``--record-applied``, and then read back by ``offline_table``.
    The two sides of this runbook have to agree about the file one of them writes -- and until
    2026-09-11 they did not: the writer stored ``plan: null`` and the reader accepted only
    ``plan.table_input``."""
    glue = Boto3ShapedGlue()
    glue.seed(mod.widen_table_input(narrow_table, FIVE), version="2")
    capsys.readouterr()

    rc = mod.record_applied(region="us-east-1", database=TEST_DB, glue_client=glue,
                            migrations_dir=migrations_dir)
    out = capsys.readouterr().out
    assert rc == 0, out[-2000:]
    written = json.loads(next(migrations_dir.glob(
        f"*_{TABLE}_additive_update.json")).read_text(encoding="utf-8"))
    assert written["plan"] is None, "this is the shape the reader has to survive"
    assert written["post_apply"]["catalog_hash"] == catalog.hash_table(
        written["post_apply"]["table_input"])

    table, cert = mod.offline_table(migrations_dir)
    assert cert["basis"] == "machine manifest" and cert["verified"]
    assert "post_apply.table_input" in cert["source"], cert["source"]
    assert mod.live_shape(table, FIVE) == mod.AT_TARGET


def test_record_applied_without_any_narrow_basis_says_so_and_exits_3(
        mod, narrow_table, migrations_dir, tmp_path, capsys, clean_globals, monkeypatch):
    """THE WORLD WITH NO BASIS AT ALL -- a fresh clone where the ALTER landed, no manifest was ever
    written and the gitignored R0 record was never captured.

    ``pre_apply_basis`` resolves the REPOSITORY's migrations directory by design (the narrow basis
    is a fact about this TABLE's history, not about where a run files its record), so reaching this
    world takes taking BOTH sources away -- which is what this test does and what
    ``test_record_applied_reconstructs_the_manifest_for_an_alter_that_landed`` deliberately does
    not. The record is still written, the backup is absent rather than guessed, the reason is
    printed, and the exit code is 3 -- never 0."""
    empty = tmp_path / "no_migrations"
    empty.mkdir()
    monkeypatch.setattr(mod, "MIGRATIONS_DIR", empty)
    monkeypatch.setattr(mod, "R0_RECORD", tmp_path / "nowhere.json")
    glue = Boto3ShapedGlue()
    glue.seed(mod.widen_table_input(narrow_table, FIVE), version="2")
    capsys.readouterr()

    rc = mod.record_applied(region="us-east-1", database=TEST_DB, glue_client=glue,
                            migrations_dir=migrations_dir)
    out = capsys.readouterr().out
    assert rc == 3, out[-2000:]
    assert "certified        : NO" in out
    assert "the R0 record is not on disk" in out
    assert "EXIT 3" in out
    payload = json.loads(next(migrations_dir.glob(
        f"*_{TABLE}_additive_update.json")).read_text(encoding="utf-8"))
    assert payload["backup"]["table_input"] is None
    assert "R0 record is not on disk" in payload["backup"]["unavailable_reason"]


def _synth_r0_record(mod, *, recipe) -> dict:
    """A PRE-ALTER R0 record, built from the certified narrow basis and minted under ``recipe``.

    Synthesized, never read from ``reports/silver_readiness/`` -- that tree is gitignored, and the
    record that IS there is the post-ALTER re-capture. ``recipe=None`` is the ghost tool's unstamped
    v1 record; 1 and 2 stamp ``glue.hash_recipe`` explicitly."""
    census = mod._census_module()
    table, _cert = mod.narrow_basis()
    sd = table["StorageDescriptor"]
    block = {
        "nonpartition_columns": [{"name": c["Name"], "type": c["Type"]} for c in sd["Columns"]],
        "num_nonpartition_columns": len(sd["Columns"]),
        "partition_keys": [{"name": p["Name"], "type": p["Type"]}
                           for p in table.get("PartitionKeys") or []],
        "location": sd["Location"], "input_format": sd["InputFormat"],
        "output_format": sd["OutputFormat"],
        "serde": (sd.get("SerdeInfo") or {}).get("SerializationLibrary"),
        "table_type": table["TableType"], "parameters": table.get("Parameters") or {},
        "version_id": 1, "update_time": "2026-07-15T02:58:03+03:00",
        "create_time": "2026-07-04T17:39:11+03:00",
    }
    if recipe is not None:
        block["hash_recipe"] = recipe
    if recipe in (None, 1):
        block["catalog_hash_sha256"] = census.catalog_hash_v1(
            census._record_glue_to_raw_shape(block))
    else:
        block["catalog_hash_sha256"] = census.hash_block(block)
    return {"table": TABLE, "baseline_id": "20260712_p65impl", "glue": block}


def test_the_raw_sidecar_is_stale_and_the_runbook_says_so_instead_of_using_it(mod):
    """THE TRAP THIS RUNBOOK STEPS AROUND. The estate's usual AWS-free source for a catalog plan is
    the ``_raw/<table>.get-table.json`` sidecar. For THIS table it is the PRE-deprojection catalog:
    13 columns (``as_of_date`` still an in-file column) and ONE partition key. Planning from it
    would compute a diff against a table that has not existed since SILVER-F031 option-b.

    The sidecar is GITIGNORED, so this SKIPS with the reason stated where it is absent -- it is
    evidence about a trap, not a basis anything depends on."""
    snap = _gitignored_json(_R0_SIDECAR, "the R0 _raw sidecar")
    assert len(snap["StorageDescriptor"]["Columns"]) == 13
    assert [p["Name"] for p in snap["PartitionKeys"]] == ["commodity"]
    assert "as_of_date" in [c["Name"] for c in snap["StorageDescriptor"]["Columns"]]
    note = mod.sidecar_note()
    assert "13 columns" in note and "['commodity']" in note
    assert "NOT used" in note


# ---------------------------------------------------------------------------
# 2. THE DRY RUN: deterministic, AWS-free, ASCII, PowerShell-5.1-safe.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def offline_runs():
    """Two identical --offline invocations. --offline resolves the TRACKED machine manifest, so
    this makes no AWS call and no network call."""
    return _run("--offline"), _run("--offline")


@pytest.fixture()
def narrow_dir(tmp_path, mod):
    """A simulated PRE-apply catalog: the certified narrow basis, written where --offline-dir reads.

    This is how the deck reaches the WIDEN plan now that live Glue is 17 columns -- the same way an
    operator would preview it, through the flag the runbook already has."""
    narrow, _cert = mod.narrow_basis()
    snap = json.loads(json.dumps(narrow, default=str))
    (tmp_path / f"{TABLE}.get-table.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def pre_flip_contract(mod, monkeypatch):
    """The F010 contract as it stood BEFORE the step-4 registry flip: the five staged physical-only.

    WHY ANY TEST NEEDS THIS, MEASURED 2026-09-11: ``dry_run`` and ``apply`` both run
    ``assert_registry_not_ahead`` FIRST, and since the flip landed (2026-09-10) a REGISTERED
    contract over a NARROW catalog is "THE REGISTRY LEADS LIVE GLUE" -- exit 2 before a plan is
    cut, before a lease is taken, before update_table. That fence is CORRECT, and it is pinned by
    ``test_the_registry_may_never_lead_live_glue`` and by the live ``--rollback --dry-run`` (exit
    2). It also means every round-trip in this deck, each of which starts from a narrow fake
    catalog, would now refuse at the door for a reason that has nothing to do with what it tests.

    So the CONTRACT STATE -- and only that -- goes back to STAGED_HIDDEN. No code under test is
    patched, no fence is disabled: the runbook still runs the fence, it simply finds the contract
    in the state the migration was designed around."""
    monkeypatch.setattr(mod, "five_from_registry", lambda: (mod.STAGED_HIDDEN, FIVE))


def _pre_flip_dry_run(mod, monkeypatch, capsys, *, offline_dir, direction="ADD"):
    """``(exit code, stdout)`` for a dry-run as it printed BEFORE the step-4 registry flip landed.

    Same reason as ``pre_flip_contract`` (which this cannot use, being a helper rather than a
    test), plus one more: a --rollback of ANY shape now refuses at "the step-4 registry flip has
    ALREADY LANDED", so a reverse-plan preview is unreachable by subprocess too. Both refusals are
    pinned by their own tests; the plan-PRINTING code is untouched by the flip and still has to be
    exercised."""
    monkeypatch.setattr(mod, "five_from_registry", lambda: (mod.STAGED_HIDDEN, FIVE))
    rc = mod.dry_run(offline=True, region="us-east-1", database=TEST_DB, direction=direction,
                     offline_dir=offline_dir)
    return rc, capsys.readouterr().out


def test_the_dry_run_is_deterministic(offline_runs):
    """Byte-for-byte identical across runs: no clock, no uuid, no set iteration order in the
    output. An operator diffing two dry-runs sees only real catalog movement."""
    first, second = offline_runs
    assert first.returncode == second.returncode == 0, first.stdout.decode("ascii")[-2000:]
    assert first.stdout == second.stdout, "the dry-run output is not reproducible"
    assert first.stdout, "the dry-run printed nothing"


def test_offline_reports_the_same_state_live_does(offline_runs, mod):
    """THE CAPABILITY THE RE-ANCHOR GIVES BACK. ``--offline`` is the mid-incident preview: no AWS,
    no credentials, exit 0, and the SAME verdict a live read gives. It went to exit 2 the moment
    step [2] re-captured the R0 record it used to read, and it now resolves the tracked manifest
    instead -- which re-hashes to live Glue's own catalog hash (MEASURED 2026-09-11).

    The state block is byte-identical to the live one: only the ``source=`` line differs, and it
    names the manifest and says where VersionId/UpdateTime came from."""
    out = offline_runs[0].stdout.decode("ascii")
    assert offline_runs[0].returncode == 0, out[-2000:]
    assert "DONE AND RECORDED" in out
    assert f"VersionId {mod.MEASURED['live_version_id_post_alter']}  UpdateTime " \
           f"{mod.MEASURED['live_update_time_post_alter']}" in out
    assert _manifest_path().name in out
    assert mod.MEASURED["live_catalog_hash_post_alter"] in out
    assert "(AWS-free)" in out
    # the R0 record is not what backed it, and the output does not claim it was.
    assert "reports/silver_readiness" not in out


def test_the_dry_run_mutates_nothing_and_says_so(mod, narrow_dir, monkeypatch, capsys):
    rc, out = _pre_flip_dry_run(mod, monkeypatch, capsys, offline_dir=narrow_dir)
    assert rc == 0, out[-2000:]
    assert "DRY RUN -- NOTHING WAS MUTATED" in out
    assert "no glue.update_table was issued" in out.lower()
    assert "no lease was taken" in out.lower()
    assert "no S3 object was written" in out


def test_the_dry_run_prints_every_added_column_with_its_type(mod, narrow_dir, monkeypatch, capsys):
    """The deliverable of a dry-run: the column diff. Every one of the five, marked as added, with
    the type it lands as -- and the 12 -> 17 count."""
    rc, out = _pre_flip_dry_run(mod, monkeypatch, capsys, offline_dir=narrow_dir)
    assert rc == 0, out[-2000:]
    for name, glue_type in FIVE:
        line = [ln for ln in out.splitlines() if ln.strip().startswith("+ ") and name in ln]
        assert line, f"{name}: no added-column line in the dry-run output"
        assert glue_type in line[0], line[0]
    assert f"({LIVE_COLUMNS} -> {LIVE_COLUMNS + len(FIVE)} non-partition columns" in out
    assert "byte-identity (Parameters)   : PASS" in out
    assert "byte-identity (PartitionKeys): PASS" in out
    out.encode("ascii")                                   # the owner's console is cp1252
    assert "&&" not in out


def test_the_dry_run_names_the_partition_consequence(mod, narrow_dir, monkeypatch, capsys):
    """A registered-partition table's ADD COLUMNS is only half a migration, and the printed plan
    must say so: the 243 partition descriptors keep 12 columns until the next canonical promote.

    AND IT MUST NOT OVERSTATE IT. The plan used to close 'the five read NULL through Athena'.
    MEASURED 2026-09-11 by glue.get_partitions all 243 descriptors are indeed still 12-column, the
    probe partition included -- and MEASURED 2026-09-10 --verify-read returned 5 rows with all five
    NON-NULL over that very descriptor. The descriptor count is partition work owed, never a
    prediction about what a SELECT returns, and the corrected text says so."""
    rc, out = _pre_flip_dry_run(mod, monkeypatch, capsys, offline_dir=narrow_dir)
    assert rc == 0, out[-2000:]
    assert "registered_partition_audit.registered: True" in out
    assert "243 registered partitions" in out
    assert "reconcile_schema_widen=True" in out
    assert "NOT AS A PREDICTION OF NULLS" in out
    assert "NON-NULL over a 12-column partition descriptor" in out
    assert "read NULL through Athena" not in out, (
        "the falsified all-NULL prediction is back in the printed plan")


def test_the_dry_run_output_is_ascii_only(offline_runs):
    """The owner's console is cp1252; a non-ASCII byte is a UnicodeEncodeError at print time."""
    offline_runs[0].stdout.decode("ascii")     # raises on any non-ASCII byte


def test_the_runbook_hands_the_owner_no_powershell_51_parser_error(offline_runs, mod, capsys):
    """OWNER LAW: Windows PowerShell 5.1 has no ``&&``. Neither the printed plan NOR the post-apply
    / post-rollback steps (which only a mutating run prints, so they are exercised directly here)
    may hand the owner one. The only ``&&`` allowed anywhere in the file is the prose stating the
    ban."""
    assert b"&&" not in offline_runs[0].stdout

    mod.print_post_apply_steps()
    steps = capsys.readouterr().out
    mod.print_post_rollback_steps()
    rolled = capsys.readouterr().out
    for text in (steps, rolled):
        text.encode("ascii")                                # cp1252 console: ASCII only
        assert "&&" not in text
        for line in text.splitlines():
            if line.strip().startswith("python "):
                assert "&&" not in line and "|" not in line, line

    for line in _RUNBOOK.read_text(encoding="utf-8").splitlines():
        if "&&" in line:
            assert "parser error" in line or "never with" in line, (
                f"a literal '&&' outside the prose stating the ban: {line}")


def test_the_post_apply_steps_name_every_file_the_commit_touches(mod, capsys):
    """STEPS (2)-(4) OF S5, WITH THE EXACT FILES. An owner who runs the ALTER and stops has left
    the registry describing a catalog that has moved; these are the rest of that commit.

    FOUR NAMES IN HERE WERE WRONG UNTIL 2026-09-11 and each is now pinned by measurement: the
    generated DDL lives in ``sql/athena/ddl_generated/``, not ``sql/athena/ddl/silver/`` (which has
    never existed in this repo); THREE tests carry their post-ALTER form, not two; the flip RENAMED
    all three, so the two the step did name had ceased to exist; and the file step [2] writes is
    gitignored, so the step has to say so or the next reader will call it tracked -- which is
    precisely what this runbook did.

    A FIFTH NAME LANDED 2026-09-11. ``sql/athena/ddl/silver_esr_compact.sql`` -- the TRACKED
    hand-DDL tree ``config_check.check_numbers_schema_pins`` reads for card-vs-DDL drift -- is a
    different file from the generated one and was left at 12 columns by this migration. The step
    now says so, with the measurement that makes it latent rather than failing (no numbers card
    references any of the five today), because a step whose own test asserts it "names every file
    the commit touches" may not silently omit a file the commit has drifted.

    THE LAST LOOP IS THE ONE THAT MATTERS: every test the step names is RESOLVED in the deck it is
    named in. A runbook step that sends an owner to a test that no longer exists is a fence that
    has quietly stopped fencing."""
    mod.print_post_apply_steps()
    steps = capsys.readouterr().out
    for required in (
            "--verify-read",
            "python scripts/silver/run_census.py --table silver_esr_compact --check",
            "python scripts/silver/run_census.py --table silver_esr_compact",
            "reports/silver_readiness/20260712_p65impl/tables/silver_esr_compact.json",
            "GITIGNORED (the 'reports/silver_readiness/' rule in .gitignore",
            "DO NOT pass --raw",
            "scripts/silver/",
            "gen_registry_from_baseline.py, CURATION_OVERRIDES['silver_esr_compact']",
            "\"additive_columns_hidden\"",
            "\"additive_columns_registered\": True,",
            "python scripts/silver/gen_registry_from_baseline.py --check",
            "python scripts/silver/generate_ddls_from_registry.py --write",
            "sql/athena/ddl_generated/silver_esr_compact.sql",
            "THREE tests carry their post-ALTER form",
            "tests/unit/silver/test_ddl_generation.py",
            "test_the_five_are_registered_catalog_columns_since_the_gated_alter",
            "test_esr_compact_ddl_renders_the_five_since_the_gated_alter",
            "tests/unit/silver/test_esr_f030_compact_alter_runbook.py::",
            "test_the_contract_registers_the_five_today",
            # the pre-ALTER names are kept as history, so a reader of an old commit still lands.
            "was test_the_five_are_physical_only_until_the_gated_alter",
            "was test_esr_compact_ddl_does_not_yet_render_the_five",
            "was test_the_contract_stages_the_five_hidden_today",
            "aws glue get-partitions",
            "never hand that blob to glue.update_table",
            # the tracked hand DDL this migration drifted, named as owed rather than omitted.
            "sql/athena/ddl/silver_esr_compact.sql",
            "THE HAND DDL IS NOW DRIFTED",
            "--rollback"):
        assert required in steps, f"the post-apply steps do not print {required!r}"
    # the path that does not exist is gone, and the three named tests are real.
    assert "sql/athena/ddl/silver/silver_esr_compact.sql goes" not in steps
    assert (_REPO / "sql" / "athena" / "ddl_generated" / "silver_esr_compact.sql").exists()
    # BOTH DDL claims are MEASURED, not asserted from the step's own words: the generated file
    # carries the five and the hand DDL does not (which is exactly what "drifted" means here).
    generated = (_REPO / "sql" / "athena" / "ddl_generated"
                 / "silver_esr_compact.sql").read_text(encoding="utf-8")
    hand_ddl = _REPO / "sql" / "athena" / "ddl" / "silver_esr_compact.sql"
    assert hand_ddl.exists(), "step [4] names the hand DDL; it must be a file that exists"
    hand = hand_ddl.read_text(encoding="utf-8")
    for name, _type in FIVE:
        assert name in generated, f"the generated DDL does not render {name}"
        assert name not in hand, (
            f"the hand DDL now carries {name} -- the drift step [4] reports has been repaired, so "
            "that printed paragraph is stale and must be re-measured")
    for deck, name in (("test_esr_contract_rebaseline.py",
                        "test_the_five_are_registered_catalog_columns_since_the_gated_alter"),
                       ("test_ddl_generation.py",
                        "test_esr_compact_ddl_renders_the_five_since_the_gated_alter"),
                       ("test_esr_f030_compact_alter_runbook.py",
                        "test_the_contract_registers_the_five_today")):
        src = (Path(__file__).parent / deck).read_text(encoding="utf-8")
        assert f"def {name}(" in src, f"step [4] names a test that does not exist: {deck}::{name}"


def test_the_post_rollback_steps_are_the_opposite_of_the_post_apply_ones(mod, capsys):
    """After a rollback the catalog is NARROW again. Telling the owner to refresh R0 and flip
    additive_columns_hidden there would put the registry ahead of a catalog that has just been put
    back -- the exact failure the staging exists to prevent."""
    mod.print_post_rollback_steps()
    rolled = capsys.readouterr().out
    assert "POST-ROLLBACK STEPS" in rolled
    assert "POST-APPLY STEPS" not in rolled
    assert "do NOT rename additive_columns_hidden" in rolled
    assert "do NOT refresh the R0 record" in rolled
    assert "python scripts/ops/esr_f030_compact_alter_runbook.py --verify-read" in rolled


def test_an_offline_snapshot_can_never_back_a_mutation():
    """A snapshot is a dry-run source. Combining it with --apply is a REFUSAL (exit 2), not a silent
    live read."""
    for args in (("--offline", "--apply"), ("--offline", "--rollback")):
        proc = _run(*args)
        assert proc.returncode == 2, proc.stdout.decode("ascii")[-1500:]
        assert b"REFUSED" in proc.stdout


def test_apply_and_rollback_are_mutually_exclusive():
    proc = _run("--apply", "--rollback")
    assert proc.returncode == 2
    assert b"mutually exclusive" in proc.stdout


def test_the_reverse_plan_refuses_a_catalog_that_is_still_narrow(mod, narrow_table):
    """Asking for the REVERSE plan while the catalog has not been widened must refuse with the
    shape named, never narrow-then-widen blindly. This tests the PRECONDITION only -- the rollback
    never runs, which is why the tests below put it in front of a catalog that IS wide.

    TWO FENCES NOW STAND BETWEEN THE OWNER AND A REVERSE PLAN, and the outer one moved. Since the
    step-4 flip, ``--rollback --dry-run --offline`` refuses at the ORDER FENCE -- the registry
    declares the five, so rolling the CATALOG back would leave it ahead of live Glue -- and that is
    the runbook's live behaviour today (exit 2). The shape precondition it used to reach is still
    there and is exercised directly."""
    proc = _run("--rollback", "--dry-run", "--offline")
    out = proc.stdout.decode("ascii")
    assert proc.returncode == 2, out[-2000:]
    assert "REFUSED -- nothing was mutated by this runbook." in out
    assert "step-4 registry flip has ALREADY LANDED" in out

    with pytest.raises(mod.Refused) as exc:
        mod.narrow_table_input(narrow_table, FIVE)
    assert "not the measured POST-ALTER one" in str(exc.value)
    assert "a rollback that quietly no-ops" in str(exc.value)


@pytest.fixture()
def wide_dir(tmp_path, mod):
    """A simulated post-apply catalog: the certified NARROW BASIS with the five appended at the
    tail. The state the reverse plan has to be shown, and the only way to test it without AWS.

    Built from the manifest's ``backup.table_input`` now, not from the R0 record: the record is the
    post-ALTER re-capture, so appending the five to it would produce a 22-column table."""
    table, _cert = mod.narrow_basis()
    wide = json.loads(json.dumps(mod.widen_table_input(table, FIVE), default=str))
    wide["VersionId"] = "2"
    wide["Name"] = TABLE
    (tmp_path / f"{TABLE}.get-table.json").write_text(json.dumps(wide, indent=2), encoding="utf-8")
    return tmp_path


def test_the_reverse_plan_is_previewable_against_a_wide_catalog(mod, wide_dir, monkeypatch,
                                                                capsys):
    """The preview an owner gets mid-incident: exit 0 (the plan is real), the five shown dropped,
    the restore path named, and the closing line naming the flag that would EXECUTE it -- not
    --apply, which would run the ALTER again."""
    rc, out = _pre_flip_dry_run(mod, monkeypatch, capsys, offline_dir=wide_dir,
                                direction="ROLLBACK")
    assert rc == 0, out[-3000:]
    assert "CatalogMigrator.restore_table(" in out
    assert "Re-run with --rollback ALONE (drop --dry-run) to execute." in out
    assert "Re-run with --apply" not in out
    for name in FIVE_NAMES:
        line = [ln for ln in out.splitlines() if ln.strip().startswith("- ") and name in ln]
        assert line, f"{name}: no dropped-column line in the reverse plan"
    assert f"({LIVE_COLUMNS + len(FIVE)} -> {LIVE_COLUMNS} non-partition columns" in out
    # a rollback owes no partition work, and the plan must not tell the owner otherwise.
    assert "A rollback therefore needs NO partition work" in out
    out.encode("ascii")
    assert "&&" not in out


def test_the_reverse_plan_declares_its_drops_instead_of_hiding_them(mod, wide_dir, monkeypatch,
                                                                    capsys):
    """The five ``DROP column ...`` entries are what apply_table would refuse on. The preview must
    print them AS the bounded override they are -- an operator who sees `unsafe: [...]` with no
    explanation has been handed a plan that looks executable and is not."""
    rc, out = _pre_flip_dry_run(mod, monkeypatch, capsys, offline_dir=wide_dir,
                                direction="ROLLBACK")
    assert rc == 0, out[-3000:]
    for name in FIVE_NAMES:
        assert f"DROP column '{name}' (refused)" in out
    assert "does NOT go through apply_table" in out
    assert "bounded override" in out


def test_the_bounded_override_covers_only_the_five(mod):
    """The override is a LIST, not a mode. An unsafe entry outside the expected reverse set -- a
    sixth drop, a partition-key change, a narrowed incumbent -- must still refuse."""
    expected = mod.expected_reverse_unsafe(FIVE)
    assert expected == [f"DROP column '{n}' (refused)" for n in FIVE_NAMES]

    ok = mod.MigrationPlan(table=TABLE, database=TEST_DB,
                           change_type=mod.ChangeType.ADDITIVE_UPDATE, live_hash="a",
                           desired_hash="b", unsafe=list(expected))
    assert mod.check_unsafe(ok, FIVE, "ROLLBACK") == expected

    for extra in ("DROP column 'source' (refused)",
                  "NARROW column 'weekly_exports_1000mt' double -> float (refused)",
                  "partition-key change [('commodity', 'string')] -> [] (refused)"):
        bad = mod.MigrationPlan(table=TABLE, database=TEST_DB,
                                change_type=mod.ChangeType.ADDITIVE_UPDATE, live_hash="a",
                                desired_hash="b", unsafe=expected + [extra])
        with pytest.raises(mod.Refused) as exc:
            mod.check_unsafe(bad, FIVE, "ROLLBACK")
        assert "bounded expected one" in str(exc.value)

    # and the ADD direction still refuses on ANY unsafe entry -- the override is rollback-only.
    with pytest.raises(mod.Refused):
        mod.check_unsafe(ok, FIVE, "ADD")


# ---------------------------------------------------------------------------
# 3. silver_esr IS NEVER TOUCHED, IN ANY MODE.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("extra", [(), ("--apply",), ("--rollback",), ("--verify-read",),
                                   ("--record-applied",), ("--offline",)])
def test_silver_esr_is_a_hard_coded_refusal_in_every_mode(extra):
    """The migration file carries TWO ALTER statements and they do not share a fate. Naming the
    refused half here exits 2 BEFORE any client is built -- and prints the file's own reasons."""
    proc = _run("--table", REFUSED_TABLE, *extra)
    out = proc.stdout.decode("ascii")
    assert proc.returncode == 2, out[-2000:]
    assert "silver_esr is NEVER touched by this runbook." in out
    assert "nothing was mutated by this runbook." in out
    assert "no writer on any schedule" in out


def test_the_quoted_refusal_is_the_migration_files_own_words(mod):
    """Quoted, not paraphrased: if the refusal is ever lifted it is lifted in that file, and a copy
    inside this script would keep printing a decision that had been reversed."""
    sql = _MIGRATION_SQL.read_text(encoding="utf-8")
    quoted = mod.silver_esr_refusal_reasons()
    assert quoted, "the refusal quote is empty"
    for line in quoted:
        if line.strip():
            assert line.strip() in sql, f"quoted line is not in the migration file: {line!r}"
    body = "\n".join(quoted)
    for claim in ("all-NULL here forever", "370 registered partition StorageDescriptors",
                  "DELIBERATELY NOT SCHEDULED"):
        assert claim in body, f"the quoted refusal no longer carries {claim!r}"


def test_an_unknown_table_is_refused_too():
    proc = _run("--table", "silver_wasde")
    assert proc.returncode == 2
    assert b"is not a table this runbook knows" in proc.stdout


def test_the_runbook_never_names_the_refused_table_in_a_mutating_call(mod):
    """A belt-and-braces read of the source: no ``update_table``/``restore_table``/``apply_table``
    call site may be reachable with a table name that is not the compact one. The runbook has ONE
    table constant, and the mutating paths use it."""
    src = _RUNBOOK.read_text(encoding="utf-8")
    for call in ("apply_table(", "restore_table(", "update_table("):
        for m in re.finditer(re.escape(call) + r"([^\n]*)", src):
            assert "silver_esr'" not in m.group(1) and '"silver_esr"' not in m.group(1), m.group(0)
    assert src.count("REFUSED_TABLE = \"silver_esr\"") == 1


# ---------------------------------------------------------------------------
# 4. THE MUTATING PATHS, THROUGH A boto3-SHAPED IN-MEMORY CATALOG.
#
# The shared FakeGlue is seeded through json.dumps(default=str) and never carries a datetime, and
# its update_table does not move VersionId. Both of those hid a real defect on the sibling runbook
# (MEASURED 2026-09-10 04:07Z: the migration-manifest writer raised `TypeError: Object of type
# datetime is not JSON serializable` AFTER glue.update_table had returned, and the owner was told
# nothing was mutated while the catalog had moved). So every fake below returns boto3-SHAPED
# tables: real datetimes, and a VersionId that moves.
# ---------------------------------------------------------------------------
_APPLY_CLOCK = datetime(2026, 9, 10, 18, 30, 0, tzinfo=timezone.utc)


class Boto3ShapedGlue(FakeGlue):
    """FakeGlue plus the two behaviours the shared fake does not model.

    ``LastAccessTime`` is seeded deliberately even though live ``silver_esr_compact`` carries none
    today (measured 2026-09-10): ``raw_snapshot_to_table_input`` KEEPS that field on purpose -- a
    TableInput that omits it loses it -- and a table that gains one later must not break the
    manifest writer."""

    def __init__(self, clock=_APPLY_CLOCK):
        super().__init__()
        self.clock = clock

    def seed(self, table: dict, *, version: str = "0") -> dict:
        live = json.loads(json.dumps(table, default=str))
        live["Name"] = TABLE
        live["CreateTime"] = datetime(2026, 7, 4, 14, 39, 11, tzinfo=timezone.utc)
        live["UpdateTime"] = datetime(2026, 7, 14, 23, 58, 3, tzinfo=timezone.utc)
        live["LastAccessTime"] = datetime(2026, 9, 10, 11, 0, 0, tzinfo=timezone.utc)
        live["VersionId"] = version
        self.tables[TABLE] = live
        return live

    def update_table(self, DatabaseName, TableInput, **kw):
        name = TableInput["Name"]
        before = dict(self.tables.get(name) or {})
        super().update_table(DatabaseName=DatabaseName, TableInput=TableInput, **kw)
        now = self.tables[name]
        # Glue keeps the read-only fields a TableInput cannot carry, and bumps the version.
        now["VersionId"] = str(int(before.get("VersionId", "0")) + 1)
        now["CreateTime"] = before.get("CreateTime")
        now["UpdateTime"] = self.clock
        now.setdefault("LastAccessTime", before.get("LastAccessTime"))
        return {}


@pytest.fixture()
def narrow_table(mod):
    """The certified NARROW BASIS as a get_table-shaped Table: the pre-ALTER catalog, AWS-free.

    Post-apply that is the tracked machine manifest's ``backup.table_input`` -- the pre-apply
    snapshot the mutation froze, re-certified against its own ``backup.catalog_hash`` and against
    the runbook's pinned ``MEASURED['live_catalog_hash']``. It is a RAW get_table blob, so it still
    carries the nine read-only fields Glue rejects on input; every path below that turns it into a
    TableInput goes through ``migrate.raw_snapshot_to_table_input``."""
    table, _cert = mod.narrow_basis()
    return table


@pytest.fixture()
def migrations_dir(tmp_path):
    out = tmp_path / "migrations"
    out.mkdir()
    return out


def _apply_kw(glue, s3, migrations_dir, lease_id):
    return dict(region="us-east-1", database=TEST_DB, bucket=TEST_BUCKET, lease_prefix="silver/",
                lease_id=lease_id, glue_client=glue, s3_client=s3, migrations_dir=migrations_dir)


def _types(glue) -> dict:
    return {c["Name"]: c["Type"] for c in glue.tables[TABLE]["StorageDescriptor"]["Columns"]}


def _names(glue) -> list:
    return [c["Name"] for c in glue.tables[TABLE]["StorageDescriptor"]["Columns"]]


def test_the_happy_path_widens_a_boto3_shaped_catalog(
        mod, narrow_table, fake_s3, migrations_dir, capsys, clean_globals, pre_flip_contract):
    """12 -> 17 THROUGH THE REAL MUTATING CODE PATH: a real Lease over the fake S3, the real
    CatalogMigrator.apply_table with its live-hash re-check and fence, the real manifest writer.
    The manifest is not merely written -- it is RE-PARSED, which is the assertion that fails
    without ``default=str`` on a table carrying a datetime."""
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    before_hash = catalog.hash_table(glue.tables[TABLE])
    before_params = json.dumps(glue.tables[TABLE]["Parameters"], sort_keys=True)
    before_keys = json.dumps(glue.tables[TABLE]["PartitionKeys"], sort_keys=True)

    rc = mod.apply(direction="ADD", **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-happy"))
    out = capsys.readouterr().out
    assert rc == 0, out[-3000:]
    out.encode("ascii")                                   # the owner's console is cp1252
    assert "&&" not in out

    assert _names(glue) == list(mod.NARROW_NAMES) + FIVE_NAMES
    assert len(_names(glue)) == LIVE_COLUMNS + len(FIVE)
    for name, glue_type in FIVE:
        assert _types(glue)[name] == glue_type
    assert glue.tables[TABLE]["VersionId"] == "1", "VersionId did not move"
    assert "VersionId     : 0  ->  1" in out
    assert f"columns       : {LIVE_COLUMNS}  ->  {LIVE_COLUMNS + len(FIVE)}" in out
    assert "Parameters preserved (managed set)  : YES" in out
    assert "PartitionKeys preserved after apply : YES" in out
    assert "POST-APPLY VERIFICATION FAILED" not in out
    assert "POST-APPLY STEPS" in out

    # the incumbents did not move, and neither did the projection-shaped fields.
    assert json.dumps(glue.tables[TABLE]["Parameters"], sort_keys=True) == before_params
    assert json.dumps(glue.tables[TABLE]["PartitionKeys"], sort_keys=True) == before_keys
    for name, glue_type in mod.NARROW_COLUMNS:
        assert _types(glue)[name] == glue_type

    # THE MANIFEST -- written, and RE-PARSED.
    paths = list(migrations_dir.glob(f"*_{TABLE}_additive_update.json"))
    assert len(paths) == 1, [p.name for p in paths]
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["change_type"] == "additive_update"
    assert payload["guard_mode"] == "canonical"
    assert payload["plan"]["live_hash"] == before_hash
    assert payload["backup"]["catalog_hash"] == before_hash
    assert payload["backup"]["table_input"]["Name"] == TABLE
    # the datetime that fired on the sibling runbook, carried through as a string.
    last_access = payload["plan"]["table_input"]["LastAccessTime"]
    assert isinstance(last_access, str) and datetime.fromisoformat(last_access)
    # the executable backup a rollback would restore is the PRE-apply table, 12 columns.
    assert len(payload["backup"]["table_input"]["StorageDescriptor"]["Columns"]) == LIVE_COLUMNS
    assert mod._MUTATED == [TABLE]


def test_the_re_run_skips_an_already_wide_catalog(
        mod, narrow_table, fake_s3, migrations_dir, capsys, clean_globals, pre_flip_contract):
    """IDEMPOTENCE. A table already at the target is the work already DONE, not a precondition
    failure -- refusing it would make a half-finished run unfinishable by the same command. No
    lease is taken (a lease is a licence to mutate) and no second update_table is issued, and the
    rest of the commit is still printed because it is still owed."""
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    kw = _apply_kw(glue, fake_s3, migrations_dir, "deck-esr-rerun")
    assert mod.apply(direction="ADD", **kw) == 0
    capsys.readouterr()
    updates_after_first = [c for c in glue.calls if c[0] == "update_table"]

    assert mod.apply(direction="ADD", **kw) == 0
    out = capsys.readouterr().out
    assert "ALREADY WIDE: silver_esr_compact (VersionId 1, UpdateTime" in out
    assert "NOTHING TO DO" in out
    assert "No lease was taken" in out
    assert "POST-APPLY STEPS" in out
    assert [c for c in glue.calls if c[0] == "update_table"] == updates_after_first
    assert glue.tables[TABLE]["VersionId"] == "1"
    # the first run's record is found rather than a second one being written.
    assert "applied record already on disk" in out
    assert len(list(migrations_dir.glob(f"*_{TABLE}_additive_update.json"))) == 1


def test_preflight_refuses_a_thirteen_column_table(
        mod, fake_s3, migrations_dir, clean_globals, pre_flip_contract):
    """THE MIXED SHAPE IS THE ONLY REFUSAL, and this is the realest example of one: the tracked
    ``_raw`` sidecar, which is the PRE-deprojection table -- 13 columns, ``as_of_date`` still in
    the file. Planning an append onto it would be planning against a catalog that no longer
    exists. (The sidecar is gitignored, so this SKIPS with the reason stated where it is absent.)"""
    stale = _gitignored_json(_R0_SIDECAR, "the R0 _raw sidecar")
    glue = Boto3ShapedGlue()
    glue.seed(stale)
    with pytest.raises(mod.Refused) as exc:
        mod.apply(direction="ADD", **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-13col"))
    message = str(exc.value)
    assert "13 column(s)" in message
    assert "as_of_date" in message
    assert not [c for c in glue.calls if c[0] == "update_table"], "a refusal must mutate nothing"
    assert mod._MUTATED == []


def test_preflight_refuses_a_retyped_incumbent(
        mod, narrow_table, fake_s3, migrations_dir, clean_globals, pre_flip_contract):
    """An append must not become a cover for a retype. A catalog whose incumbent columns are not
    what this migration was measured against is MIXED, and MIXED is a refusal."""
    drifted = json.loads(json.dumps(narrow_table, default=str))
    for col in drifted["StorageDescriptor"]["Columns"]:
        if col["Name"] == "weekly_exports_1000mt":
            col["Type"] = "double"
    glue = Boto3ShapedGlue()
    glue.seed(drifted)
    with pytest.raises(mod.Refused) as exc:
        mod.apply(direction="ADD", **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-retype"))
    assert "weekly_exports_1000mt" in str(exc.value)
    assert not [c for c in glue.calls if c[0] == "update_table"]


def test_a_mid_run_failure_after_update_table_reports_the_truth(
        mod, narrow_table, fake_s3, migrations_dir, monkeypatch, capsys, clean_globals,
        pre_flip_contract):
    """THE 04:07Z INCIDENT, IN THIS RUNBOOK'S SHAPE. The manifest writer is made to raise the exact
    TypeError, which puts the failure in the one window that matters: AFTER glue.update_table
    returned and BEFORE the run recorded the mutation. The run must then say what the CATALOG says
    -- APPLIED -- write the record the failed writer owed, and never print 'nothing was mutated'."""
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)

    def _boom(self, plan, backup):
        raise TypeError("Object of type datetime is not JSON serializable")

    monkeypatch.setattr(CatalogMigrator, "_write_migration_manifest", _boom)
    with pytest.raises(TypeError):
        mod.apply(direction="ADD", **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-boom"))
    out = capsys.readouterr().out

    # the catalog DID move.
    assert glue.tables[TABLE]["VersionId"] == "1"
    assert _names(glue)[-5:] == FIVE_NAMES
    # and the run says so, from a fresh read, not from where the exception fired.
    assert "WHAT ACTUALLY HAPPENED" in out
    assert "APPLIED" in out
    assert "VersionId 0 -> 1" in out
    assert "MOVED      : silver_esr_compact" in out
    assert mod._MUTATED == [TABLE]
    # the missing manifest is written FROM THE RE-READ, with the pre-apply backup this run froze.
    paths = list(migrations_dir.glob(f"*_{TABLE}_additive_update.json"))
    assert len(paths) == 1
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["applied"] is True and payload["reconstructed"] is True
    assert "after glue.update_table had already returned" in payload["reconstructed_note"]
    assert len(payload["backup"]["table_input"]["StorageDescriptor"]["Columns"]) == LIVE_COLUMNS
    assert "manifest WRITTEN from the re-read" in out
    # and the exit summary can never claim otherwise.
    status = mod._mutation_status("ERROR")
    assert "WAS ALREADY MUTATED" in status and "nothing was mutated" not in status
    # the lease is released even on the failure path.
    assert "lease RELEASED" in out


def test_a_rollback_through_apply_table_would_be_a_dead_command(mod, narrow_table):
    """WHY --rollback DOES NOT USE apply_table, measured rather than asserted: the reverse plan's
    unsafe list is five DROPs, and apply_table raises UnsafeMigration on any unsafe entry. Routed
    that way the rollback would refuse, restore nothing, and still look like a command."""
    wide = mod.widen_table_input(narrow_table, FIVE)
    wide["VersionId"] = "1"
    narrow = mod.narrow_table_input(wide, FIVE)
    mig = CatalogMigrator(database=TEST_DB, auth=_canonical_auth(), glue_client=FakeGlue())
    unsafe = mig._unsafe_diffs(wide, narrow)
    assert sorted(unsafe) == sorted(mod.expected_reverse_unsafe(FIVE))
    plan = mod.build_plan(wide, narrow, mig, TEST_DB, "ROLLBACK")
    with pytest.raises(UnsafeMigration):
        mig.apply_table(plan)


def _canonical_auth():
    from conftest import canonical_authorization
    return canonical_authorization()


def test_the_rollback_actually_restores_the_narrow_catalog(
        mod, narrow_table, fake_s3, migrations_dir, capsys, clean_globals, pre_flip_contract):
    """THE ROUND TRIP, AWS-FREE: 12 -> --apply -> 17 -> --rollback -> 12, through a REAL Lease over
    the fake S3, so the fence, the live-hash re-check and restore_table's own post-restore hash
    verification all execute. This is the test that fails on a rollback routed through
    apply_table."""
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    narrow_types = dict(_types(glue))
    narrow_hash = catalog.hash_table(glue.tables[TABLE])
    shape_before = (json.dumps(glue.tables[TABLE]["Parameters"], sort_keys=True),
                    json.dumps(glue.tables[TABLE]["PartitionKeys"], sort_keys=True))
    kw = _apply_kw(glue, fake_s3, migrations_dir, "deck-esr-roundtrip")

    assert mod.apply(direction="ADD", **kw) == 0
    widened = capsys.readouterr().out
    assert _names(glue)[-5:] == FIVE_NAMES

    assert mod.apply(direction="ROLLBACK", **kw) == 0
    rolled = capsys.readouterr().out

    # THE ASSERTION THE WHOLE DETOUR EXISTS FOR: the five are gone and nothing else moved.
    assert _names(glue) == list(mod.NARROW_NAMES)
    assert _types(glue) == narrow_types
    assert catalog.hash_table(glue.tables[TABLE]) == narrow_hash
    assert (json.dumps(glue.tables[TABLE]["Parameters"], sort_keys=True),
            json.dumps(glue.tables[TABLE]["PartitionKeys"], sort_keys=True)) == shape_before
    assert "restored      : True" in rolled
    assert "OK (gone)" in rolled
    # two update_table calls: the widen and the restore.
    assert [c for c in glue.calls if c[0] == "update_table"] == [
        ("update_table", TABLE), ("update_table", TABLE)]

    # THE STEPS ARE DIRECTION-GATED.
    assert "POST-APPLY STEPS" in widened
    assert "POST-ROLLBACK STEPS" in rolled
    assert "POST-APPLY STEPS" not in rolled
    assert "do NOT rename additive_columns_hidden" in rolled
    for text in (widened, rolled):
        text.encode("ascii")
        assert "&&" not in text
    # a rollback leaves an audit record: restore_table writes no machine manifest of its own.
    assert sorted(p.name.split("_", 1)[1] for p in migrations_dir.iterdir()) == [
        f"{TABLE}_additive_update.json", f"{TABLE}_rollback_restore.json"]
    record = json.loads(next(migrations_dir.glob("*_rollback_restore.json")).read_text("utf-8"))
    assert record["mechanism"].startswith("leviathan.silver.migrate.CatalogMigrator.restore_table")
    assert len(record["backup"]["table_input"]["StorageDescriptor"]["Columns"]) == (
        LIVE_COLUMNS + len(FIVE)), "the rollback's backup must be the PRE-rollback (wide) table"


def test_the_registry_may_never_lead_live_glue(mod, narrow_table, fake_s3, migrations_dir,
                                               monkeypatch, clean_globals):
    """THE ORDER FENCE. Step [3] flips the contract to declare the five; step [1] applies the
    ALTER. Doing them the other way round puts the checked-in registry ahead of the catalog, which
    is what the whole hidden-staging exists to prevent -- so a run that finds a REGISTERED contract
    over a narrow catalog refuses and names both halves."""
    monkeypatch.setattr(mod, "five_from_registry", lambda: (mod.REGISTERED, FIVE))
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    with pytest.raises(mod.Refused) as exc:
        mod.apply(direction="ADD", **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-order"))
    assert "THE REGISTRY LEADS LIVE GLUE" in str(exc.value)
    assert not [c for c in glue.calls if c[0] == "update_table"]


def test_a_rollback_after_the_registry_flip_is_refused(
        mod, narrow_table, fake_s3, migrations_dir, monkeypatch, clean_globals):
    """THE ORDER FENCE, THE OTHER WAY ROUND -- and this is the half that would fail silently.
    Rolling the CATALOG back once the contract declares the five leaves the registry ahead of live
    Glue: the same illegal state, reached from the other side, with no test in the repo watching
    for it at that moment. The registry has to be reverted FIRST."""
    glue = Boto3ShapedGlue()
    glue.seed(mod.widen_table_input(narrow_table, FIVE), version="2")
    monkeypatch.setattr(mod, "five_from_registry", lambda: (mod.REGISTERED, FIVE))
    with pytest.raises(mod.Refused) as exc:
        mod.apply(direction="ROLLBACK",
                  **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-flipback"))
    message = str(exc.value)
    assert "step-4 registry flip has ALREADY LANDED" in message
    assert "additive_columns_hidden" in message
    assert not [c for c in glue.calls if c[0] == "update_table"]


def test_record_applied_reconstructs_the_manifest_for_an_alter_that_landed(
        mod, narrow_table, fake_s3, migrations_dir, capsys, clean_globals, pre_flip_contract):
    """The 04:07Z hole, closed by hand: the catalog moved and no machine record exists. This proves
    before it writes -- the live table must be the table this migration PLANNED, hash for hash --
    and it is read-only on AWS.

    WHAT THE DELETED tmp MANIFESTS DO AND DO NOT SIMULATE (stated because the name over-promises).
    Unlinking them makes ``record_applied``'s own "a record already exists" fence stand down, which
    is the world this test needs. It does NOT make the BACKUP come from nowhere: ``pre_apply_basis``
    deliberately ignores the caller's ``migrations_dir`` and always resolves the REPOSITORY's,
    because the narrow basis is a fact about this TABLE's history rather than about where a run
    files its record. So the ``source`` column asserted below is the REPO machine manifest's
    ``backup``, and that is the production behaviour being pinned -- it is asserted explicitly.
    In a world with no repo manifest either, the basis falls to the (today wide) R0 record and the
    backup comes back UNCERTIFIED -- MEASURED 2026-09-11, ``pre_apply_basis(five, empty_dir)``
    returns ``verified: False``, "the narrow basis is not the pre-ALTER shape" -- and
    ``test_record_applied_without_any_narrow_basis_says_so_and_exits_3`` is the test for that
    world."""
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    assert mod.apply(direction="ADD",
                     **_apply_kw(glue, fake_s3, migrations_dir, "deck-esr-record")) == 0
    capsys.readouterr()
    for path in migrations_dir.glob("*.json"):     # simulate the record never being written
        path.unlink()
    calls_before = len(glue.calls)

    rc = mod.record_applied(region="us-east-1", database=TEST_DB, glue_client=glue,
                            migrations_dir=migrations_dir)
    out = capsys.readouterr().out
    assert rc == 0, out[-2000:]
    assert "live == the planned post-ALTER table  : YES" in out
    assert "NOTHING WAS MUTATED IN AWS by this command" in out
    paths = list(migrations_dir.glob(f"*_{TABLE}_additive_update.json"))
    assert len(paths) == 1
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["applied"] is True and payload["reconstructed"] is True
    assert payload["backup"]["table_input"]["StorageDescriptor"]["Columns"][-1]["Name"] == "source"
    # THE BASIS THAT PRODUCED IT, NAMED: the repo manifest, not the tmp dir this run wrote into.
    assert _manifest_path().name in payload["backup"]["source"], payload["backup"]["source"]
    assert payload["backup"]["unavailable_reason"] is None
    # READ-ONLY ON AWS: every call this mode made after it started is a get_table.
    assert [c[0] for c in glue.calls[calls_before:]] == ["get_table"]

    # and it refuses to write a SECOND record of the same mutation.
    with pytest.raises(mod.Refused) as exc:
        mod.record_applied(region="us-east-1", database=TEST_DB, glue_client=glue,
                           migrations_dir=migrations_dir)
    assert "already exists" in str(exc.value)


def test_record_applied_refuses_a_table_that_is_not_wide(
        mod, narrow_table, migrations_dir, clean_globals):
    glue = Boto3ShapedGlue()
    glue.seed(narrow_table)
    with pytest.raises(mod.Refused) as exc:
        mod.record_applied(region="us-east-1", database=TEST_DB, glue_client=glue,
                           migrations_dir=migrations_dir)
    assert "no applied ALTER to record" in str(exc.value)
    assert not list(migrations_dir.glob("*.json"))


def test_a_half_applied_run_is_never_reported_as_no_mutation(mod, clean_globals):
    assert "nothing was mutated by this runbook." in mod._mutation_status("REFUSED")
    mod._MUTATED.append(TABLE)
    msg = mod._mutation_status("ERROR")
    assert TABLE in msg and "WAS ALREADY MUTATED" in msg
    assert "nothing was mutated" not in msg


# ---------------------------------------------------------------------------
# 5. THE READ PROBE.
# ---------------------------------------------------------------------------
class _WorkGroup:
    @staticmethod
    def get_work_group(WorkGroup):
        return {"WorkGroup": {"Configuration": {"EngineVersion": {
            "EffectiveEngineVersion": "Athena engine version 3",
            "SelectedEngineVersion": "AUTO"}}}}


def test_the_read_probe_is_bounded_and_names_all_five(mod):
    """One partition, one object, LIMIT 5, and every one of the five columns named -- a probe that
    selects nothing proves nothing, and a probe that scans the table is not a probe."""
    sql = mod.VERIFY_SQL
    for name in FIVE_NAMES:
        assert name in sql
    assert "commodity = 'white_wheat'" in sql and "as_of_date = '20260910'" in sql
    assert "LIMIT 5" in sql
    assert sql.count("FROM") == 1 and "JOIN" not in sql.upper()


def test_the_read_probe_never_reaches_for_ensure_catalog():
    """``jobs/utils/athena_utils.ensure_catalog`` DROPS AND RECREATES tables. The probe imports
    ``run_query`` and nothing else, and the file says why."""
    src = _RUNBOOK.read_text(encoding="utf-8")
    assert "from athena_utils import run_query" in src
    assert "import ensure_catalog" not in src
    assert "athena_utils.ensure_catalog()" in src and "must NEVER call" in src
    # every mention in the file is prose forbidding it -- never a call.
    mentions = [ln for ln in src.splitlines() if "ensure_catalog" in ln]
    assert mentions, "the file no longer says why ensure_catalog is forbidden"
    for line in mentions:
        assert ("NEVER" in line or "DROPS AND RECREATES" in line
                or "no ensure_catalog" in line), line


def test_the_read_probe_fails_closed_on_zero_rows(mod, capsys):
    """A filter that matches no registered partition returns zero rows without touching a parquet
    byte. An empty result therefore proves nothing about readability -- which is the one thing this
    probe exists to prove -- so 0 rows must be a FAILURE, not an 'OK -- 0 row(s)'."""
    rc = mod.verify_read(region="us-east-1", database=TEST_DB, client=_WorkGroup(),
                         runner=lambda client, sql, database=None: [])
    out = capsys.readouterr().out
    assert rc == 3
    assert "FAILED: 0 rows" in out
    assert "--rollback" in out


def test_the_read_probe_does_not_read_nulls_as_a_data_verdict(mod, capsys):
    """The probe proves the objects READ, and NOTHING about the values -- IN EITHER DIRECTION. An
    all-NULL sample must still be an OK, with the reason printed rather than swallowed.

    THE PRINTED REASON WAS A PREDICTION, AND IT WAS WRONG. This runbook said the five would read
    NULL until the canonical promote, because Athena resolves a registered partition's columns from
    the PARTITION descriptor. The descriptors ARE still narrow -- MEASURED 2026-09-11 by
    glue.get_partitions: 243 of 243 at 12 columns, this probe's partition (white_wheat/20260910)
    included. But MEASURED 2026-09-10 the probe returned 5 rows with ALL FIVE NON-NULL over that
    descriptor. So the corrected text has to hold BOTH the descriptor fact and the falsified
    prediction, and neither reading may be sold as a verdict on the data."""
    row = {"week_ending_date": "2026-09-04"}
    row.update({n: None for n in FIVE_NAMES})
    rc = mod.verify_read(region="us-east-1", database=TEST_DB, client=_WorkGroup(),
                         runner=lambda client, sql, database=None: [row])
    out = capsys.readouterr().out
    assert rc == 0
    assert "the existing objects read" in out
    assert "of the five, 0 read non-NULL" in out
    assert "NOT A VERDICT ON THE DATA, IN EITHER DIRECTION" in out
    assert "243 of 243" in out and "12 columns" in out
    assert "5 rows, and" in out and "read NON-NULL over that 12-column descriptor" in out
    assert "EXPECTED between the ALTER and that promote" not in out, (
        "the falsified all-NULL prediction is back in the probe's verdict")

    # and the measured case -- every one of the five populated -- is an OK for the same reason.
    populated = {"week_ending_date": "2026-09-04"}
    populated.update({n: "1.594" for n in FIVE_NAMES})
    rc = mod.verify_read(region="us-east-1", database=TEST_DB, client=_WorkGroup(),
                         runner=lambda client, sql, database=None: [populated])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"of the five, {len(FIVE_NAMES)} read non-NULL" in out
    assert "the partition repair is still owed" in out


def test_the_read_probe_reports_a_failed_query_as_a_failure(mod, capsys):
    def _boom(client, sql, database=None):
        raise RuntimeError("Athena FAILED: SYNTAX_ERROR")

    rc = mod.verify_read(region="us-east-1", database=TEST_DB, client=_WorkGroup(), runner=_boom)
    out = capsys.readouterr().out
    assert rc == 3
    assert "do NOT read under the current catalog" in out
