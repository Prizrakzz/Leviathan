"""SILVER-F030: the ESR contract re-baseline is codified in the operational registry.

Asserts the frozen semantic ADR at the CONTRACT level (registry.py loads the YAML the generator
emits): the true physical natural key, changes_1000mt deprecated, publication-lag/PIT semantics
reconciled against the numbers TableSpec, the slug-coverage boundary, and the additive-migration
artifacts. AWS-free; pure registry + reconcile reads under the F002 isolation guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leviathan.silver.registry import load_registry
from leviathan.silver import reconcile as R

_REPO = Path(__file__).resolve().parents[3]
_ADR = _REPO / "reports" / "silver_readiness" / "R2_esr" / "F030_esr_adr.json"
_MIGRATION = _REPO / "sql" / "athena" / "migrations" / "silver" / "silver_esr_f030_additive.sql"

_ESR_KEY = ["commodity_code", "market_year", "as_of_date", "country_code", "week_ending_date"]

# SILVER-F030 BF-W2 additive five, in the ADR's frozen order.
_FIVE = [
    "accumulated_exports_1000mt",
    "current_my_net_sales_1000mt",
    "current_my_total_commitment_1000mt",
    "next_my_outstanding_sales_1000mt",
    "next_my_net_sales_1000mt",
]


@pytest.fixture(scope="module")
def reg():
    return load_registry()


class TestGrainAndNaturalKey:
    def test_silver_esr_natural_key_is_the_true_physical_key(self, reg):
        assert reg.table("silver_esr")["natural_key"] == _ESR_KEY

    def test_compact_natural_key_matches(self, reg):
        assert reg.table("silver_esr_compact")["natural_key"] == _ESR_KEY

    def test_required_nonnull_tracks_the_key(self, reg):
        assert reg.table("silver_esr")["required_nonnull"] == _ESR_KEY

    def test_partition_dims_are_registered_not_projected(self, reg):
        for name in ("silver_esr", "silver_esr_compact"):
            c = reg.table(name)
            assert c["partition_mode"] == "registered"
            assert c["projection"] == "forbidden"
            assert all(pk.get("projected") is False for pk in c["partition_keys"])


class TestChangesDeprecated:
    def test_changes_1000mt_is_deprecated_on_both(self, reg):
        for name in ("silver_esr", "silver_esr_compact"):
            col = next(c for c in reg.table(name)["physical_columns"]
                       if c["name"] == "changes_1000mt")
            assert col.get("deprecated") is True, name
            assert col["nullable"] is True, name

    def test_changes_is_a_schema_row_but_not_a_governed_value_column(self, reg):
        # deprecated != removed: the column stays DECLARED (a physical row, nullable, never
        # synthesized) but it is NOT a governed value column any more. The value census's all-NaN
        # rule is floor-independent by design (an all-null regression on a live column hard-fails
        # even under a 0.0 override), and the FAS API stopped publishing 'changes' in August 2026
        # (the schema-drift WARN names the five net-commitment fields that replaced it): with the
        # column still governed, every usda_esr gate went red on 2026-08-27 and 2026-09-03
        # ("'changes_1000mt' is 100% NaN/null across 225 sampled rows") and canonical promote was
        # skipped for the whole family. Governance belongs to the columns the source still writes;
        # an override may only name a value column, so the 0.0 override is gone with it.
        for name in ("silver_esr", "silver_esr_compact"):
            assert "changes_1000mt" not in reg.value_columns(name), name
            overrides = reg.table(name).get("min_nonnull_frac_overrides") or {}
            assert "changes_1000mt" not in overrides, name
            assert any(c["name"] == "changes_1000mt" for c in reg.table(name)["physical_columns"]), name


class TestAdditiveNetCommitmentColumns:
    """SILVER-F030 BF-W2 (2026-09-04): the five net-commitment columns enter the COMPACT contract.

    They are the ADR's frozen ``target_additive_schema_bf_w2`` set, they are produced by both ESR
    transforms as of this change, and they are declared here as PHYSICAL-ONLY until the gated Glue
    ALTER lands. Every assertion below is one of the three things that can silently go wrong:
    which table takes them, where they sit, and whether they are governed.
    """

    def test_compact_declares_all_five_nullable_at_the_float64_target(self, reg):
        """Declared on the SERVING surface, nullable, INV-2 target float64 (== Glue `double`, the
        ADR's own type). float64 rather than the incumbents' float32 because a parquet FLOAT under
        a `double` catalog is the silver_food_cpi HIVE_BAD_DATA class."""
        cols = {c["name"]: c for c in reg.table("silver_esr_compact")["physical_columns"]}
        for name in _FIVE:
            assert name in cols, name
            assert cols[name]["target_arrow_type"] == "float64", name
            assert cols[name]["nullable"] is True, name

    def test_the_five_are_the_last_five_physical_columns(self, reg):
        """TAIL placement is load-bearing, not cosmetic. catalog.is_schema_widen admits ONLY a
        pure trailing-column append at an identical location/format/SerDe (measured: the five at
        the tail -> True; the same five inserted at position 9 -> False). That narrow self-heal is
        what repairs the already-registered partition StorageDescriptors on the first canonical
        promote after the ALTER; mid-list, every partition fails closed and the whole family's
        promote dies. Glue's ADD COLUMNS appends at the tail, so this also keeps parquet order ==
        catalog order."""
        names = [c["name"] for c in reg.table("silver_esr_compact")["physical_columns"]]
        assert names[-5:] == _FIVE
        assert names[-6] == "source"

    def test_the_five_are_physical_only_until_the_gated_alter(self, reg):
        """THE REGISTRY NEVER LEADS LIVE GLUE. `glue_type: null` is the estate's own name for
        "the writer emits it, the catalog has not registered it" (ddl.py excludes such a column
        from the DDL; the F011 report records it as an R2 add). Live leviathan_dev
        .silver_esr_compact still carries 12 columns, so declaring 17 here before the ALTER puts
        the checked-in registry ahead of the catalog -- measured: the registered variant reds
        test_ddl_generation.test_generated_matches_live_glue_for_every_table with
        `columns extra: [the five]`.

        THE FLIP, in ONE commit at rollout step 5: apply the silver_esr_compact half of
        sql/athena/migrations/silver/silver_esr_f030_additive.sql under lease (only AFTER the image
        carrying reconcile_schema_widen=True is live on esr-bronze-to-silver AND
        silver-publisher-runner), refresh
        reports/silver_readiness/20260712_p65impl/tables/silver_esr_compact.json, rename
        `additive_columns_hidden` to `additive_columns` + `additive_columns_registered: True` in
        gen_registry_from_baseline.CURATION_OVERRIDES, and regenerate. This test then flips to
        asserting glue_type == "double"."""
        from leviathan.silver import ddl as D
        contract = reg.table("silver_esr_compact")
        assert D.physical_only_columns(contract) == _FIVE
        assert not (set(_FIVE) & {n for n, _ in D.catalog_columns(contract)})

    def test_the_five_are_not_governed_value_columns_yet(self, reg):
        """UNGOVERNED ON PURPOSE, and the exclusion is AUTOMATIC rather than a suppression list.

        build_contract derives value_columns from the numbers CARD's metric keys, so while
        configs/graphrag/numbers/tables.yaml#silver_esr omits the five they are simply not value
        columns -- there is no override to remember to undo, and adding a metric to the card will
        promote them on the next generator run.

        Measured reason to wait: at the provisional 0.5 floor, over the census sampler's real
        shape (3 files per commodity= group, first/mid/last as_of), one populated vintage reads
        nonnull_fraction=0.333 -> ['nonnull_below_floor'] and none populated reads 0.000
        all_nan=True -> ['all_nan']. The all-NaN rule is floor-INDEPENDENT by design, so no 0.0
        override could rescue it -- that is the identical mechanism that cost this family its
        2026-08-27 and 2026-09-03 canonical promotes on changes_1000mt. Two populated vintages of
        three sampled reads 0.667 and PASSES; the card flip IS the governance promotion and must
        wait for that measurement, never for a date."""
        for name in ("silver_esr", "silver_esr_compact"):
            assert not (set(_FIVE) & set(reg.value_columns(name))), name
            overrides = reg.table(name).get("min_nonnull_frac_overrides") or {}
            assert not (set(_FIVE) & set(overrides)), name

    def test_silver_esr_full_surface_does_not_declare_them(self, reg):
        """THE REFUSAL, pinned so a later "for symmetry" edit has to argue with a test.

        silver_esr has no writer on any schedule (its vintage_waiver, approved 2026-08-16 D-SG
        G1-6, says the surface "is read by nothing"; its only writer,
        jobs/ingest/backfill_silver_usda_esr.py, is on no DAG). So the five would be all-NULL there
        forever -- census nonnull_fraction=0.000, all_nan=True, the floor-independent red -- and
        the ALTER would strand its 370 registered partition StorageDescriptors with no producer
        run to self-heal them. Aligning it later means backfill first, THEN the ALTER, THEN the R0
        refresh."""
        names = {c["name"] for c in reg.table("silver_esr")["physical_columns"]}
        assert not (set(_FIVE) & names)
        notes = reg.table("silver_esr")["notes"]
        assert "SPECIFIED-NOT-APPLIED" in notes
        assert "no writer on any schedule" in notes

    def test_the_compact_notes_record_the_landing(self, reg):
        """The contract's own prose must say the five are EMITTED and NULL before the promotion,
        so a reader of the YAML alone is not misled by five columns full of nulls."""
        notes = reg.table("silver_esr_compact")["notes"]
        assert "EMIT" in notes
        for name in _FIVE:
            assert name in notes, name


class TestPublicationLagReconciled:
    def test_pit_semantics_match_numbers_tablespec(self, reg):
        divs = R.reconcile_numbers(reg)
        esr = [d for d in divs if d.table == "silver_esr"]
        assert esr == [], f"ESR publication_lag / PIT divergence vs the numbers TableSpec: {esr}"

    def test_lag_fields_are_frozen(self, reg):
        # BF-W2 SILVER-F031 supersedes the F030 v1 interim (data_date + 7d): per-week as_of vintages,
        # the as_of stamp IS the publication event -> vintage semantics, lag 0 (runbook ESR-R2/R4).
        c = reg.table("silver_esr")
        assert c["knowledge_date_col"] == "as_of_date"
        assert c["knowledge_semantics"] == "vintage"
        assert c["publication_lag_days"] == 0

    def test_whole_registry_reconciles_clean(self, reg):
        assert R.unallowed(R.reconcile_all(reg)) == []


class TestCoverageBoundaryAndAdrArtifacts:
    def test_notes_record_the_slug_coverage_boundary(self, reg):
        notes = reg.table("silver_esr")["notes"]
        assert "all_wheat" in notes and "grain_sorghum" in notes and "white_wheat" in notes
        assert "NOT contract" in notes

    def test_adr_record_exists_and_freezes_the_decisions(self):
        adr = json.loads(_ADR.read_text(encoding="utf-8"))
        assert adr["status"] == "frozen"
        assert adr["field_decisions"]["changes_1000mt"]["decision"].startswith("DEPRECATED")
        # the 5 target additive net-commitment columns are named for BF-W2.
        cols = {c["name"] for c in adr["target_additive_schema_bf_w2"]["columns"]}
        assert cols == {
            "accumulated_exports_1000mt", "current_my_net_sales_1000mt",
            "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
            "next_my_net_sales_1000mt",
        }

    def test_additive_migration_is_additive_only(self):
        sql = _MIGRATION.read_text(encoding="utf-8").lower()
        assert "add columns" in sql
        # additive-only: no destructive verbs.
        for banned in ("drop table", "drop column", "drop partition", "rename"):
            assert banned not in sql, banned
        assert "not applied" in sql  # the R2 gating note survives

    def test_the_migration_status_is_per_table(self):
        """RE-AIMED, not deleted (2026-09-04). The stub used to carry ONE status line for both
        halves; the halves no longer share a fate. silver_esr_compact is ready to apply (both
        transforms emit the five, the producer carries reconcile_schema_widen=True), while the
        silver_esr half is a written REFUSAL -- a surface with no writer would hold five all-NULL
        columns forever and the ALTER would strand its 370 partition descriptors. Both statements
        must be IN the artifact, so a future reader applying it does not apply the wrong half."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "STATUS IS PER TABLE" in sql
        assert "silver_esr_compact : SPECIFIED, NOT APPLIED" in sql
        assert "silver_esr         : SPECIFIED, NOT APPLIED, and DELIBERATELY NOT SCHEDULED" in sql

    def test_the_migration_records_the_reconcile_precondition(self):
        """THE REGRESSION PIN FOR THE ONE STEP THAT CAN TAKE THE FAMILY DOWN. The ALTER widens the
        TABLE StorageDescriptor from 12 to 17 columns, and PartitionPublisher.publish_one builds
        every partition's desired SD by copying the table's -- so every already-registered
        partition diffs. Without reconcile_schema_widen=True live on the publishing image FIRST,
        publish_one calls _fail, ShadowPublisher._catalog raises PublisherError, and the canonical
        promote exits 1 for the whole table. The ordering constraint has to live in the artifact
        the operator actually opens when applying it."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "reconcile_schema_widen=True" in sql
        assert "BEFORE this ALTER is applied" in sql
        assert "leviathan-dev-silver-publisher-runner" in sql

    def test_the_migration_forbids_a_shared_tree_image_build(self):
        """C-NEW-F2. scripts/build_push_worker.ps1 tars $RepoRoot -- the WORKING tree -- while
        stamping BUILD_GIT_COMMIT from `git rev-parse HEAD`, and it carries no dirty-tree guard.
        On this shared tree that bakes other lanes' uncommitted work into an image whose own
        IMAGE_MANIFEST asserts a commit it does not contain, and this rollout puts that image on
        the gate 26 rendered families share. The artifact the operator opens must name the clean-
        worktree path, not merely imply it."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "NEVER BUILT FROM THE SHARED WORKING TREE" in sql
        assert "git worktree add" in sql
        assert "scripts/ops/make_worker_context_tar.py --repo" in sql

    def test_the_migration_pins_the_jobdef_envelope_that_must_survive(self):
        """C-M2. Both silver jobdefs are hand-registered, and the estate's own submitter hardcodes
        MEMORY 4096 for one of them -- the exact jobdef bumped to 12,288 MiB after it OOM'd on
        2026-09-03. This lane makes the frame 13.1% wider (306.35 -> 346.35 B/row, measured on 80
        real bronze objects), so the envelope is load-bearing and the number belongs in the
        artifact, as an instruction with its measurement."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "repin_jobdef_digest.py" in sql
        assert "rev 8" in sql and "rev 36" in sql
        assert "2 vCPU / 12,288 MiB" in sql
        assert "MUST PRESERVE THOSE NUMBERS" in sql
        assert "346.35" in sql and "+40.00 B/row" in sql
        assert "DO NOT re-register through jobs/submit/submit_batch_b2s_esr.py" in sql

    def test_the_migration_carries_the_MEASURED_rebronze_bound(self):
        """C-M3. The bound and the verdict were going to be 20260813 and "0.0 on every earlier
        vintage" -- a sentence guaranteed by the re-bronze SCOPE rather than by the source, i.e.
        one that cannot fail. The raw census measured every one of the 12 vintages carrying all
        five keys (446/446), so the artifact carries 20260712 and a falsifiable verdict."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "--as-of-min 20260712" in sql
        assert "446/446" in sql
        assert "PIPELINE finding, never a source finding" in sql
        assert "--as-of-min 20260813" not in sql

    def test_the_migration_makes_the_GITIGNORED_OVERLAY_mandatory(self):
        """RE-REVIEW NEW-1. The clean-worktree remedy, written as `--repo <a fresh worktree>` and
        nothing else, reintroduces the estate's 'worktree builds bake ZERO gitignored configs'
        incident: make_worker_context_tar.py reads the configs/graphrag overlay from the --repo
        WORKING TREE, and `git worktree add` checks out TRACKED files only, so the overlay is
        empty BY CONSTRUCTION. Measured in the main tree 2026-09-04: 141 gitignored files,
        4,751,532 bytes, 69 causal DAGs -- and the image lands on leviathan-dev-silver-gate, whose
        jobs/audit/silver_rebuild_gate.py reads exactly that subtree at runtime. So the artifact
        must carry the COPY step and the overlay_files gate, and must no longer claim a clean
        checkout satisfies the bake law on its own."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "git ls-files --others --ignored --exclude-standard -- configs/graphrag" in sql
        assert "THIS STEP IS MANDATORY" in sql
        assert "overlay_files > 0" in sql
        assert "overlay_files: 0 IS A REFUSAL" in sql
        assert "141 files" in sql and "4,751,532 bytes" in sql
        assert "a clean checkout satisfies it too" not in sql

    def test_the_migration_recommends_only_LAW_ABIDING_writers(self):
        """RE-REVIEW NEW-2. The lane declared a law ("a bronze partition's as_of comes from the
        raw key or the raw_meta sidecar, never from today's date") and then, three paragraphs
        away, recommended by name a writer that stamped the run's date:
        jobs/ingest/backfill_silver_usda_esr.py defaulted --as-of-date to today. The Glue bronze
        writer's DEFAULT mode did the same thing to the bronze prefix. Both refuse now, and the
        artifact states the law and names each writer's mechanism where it names the writer."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "THE VINTAGE LAW" in sql
        assert "PER BRONZE VINTAGE" in sql
        assert "ALWAYS WITH AN EXPLICIT --as-of-date" in sql
        assert "jobs/glue/raw_to_bronze_usda_esr.py" in sql
        assert "REFUSES by name" in sql
        # VERIFY-2 V2-NEW-1: the artifact said the estate had THREE ESR writers while a FOURTH,
        # jobs/ingest/backfill_bronze_usda_esr.py, still stamped today onto undated keys with no
        # flags required. A pinned law statement that is false is the one thing this review chain
        # exists to stop, so the count, the fourth writer's mechanism and the law-abiding fifth
        # are all pinned here -- and the false count is pinned ABSENT.
        assert "has FOUR ESR writers and the law now holds in all four" in sql
        assert "THREE ESR writers" not in sql
        assert "jobs/ingest/backfill_bronze_usda_esr.py" in sql
        assert "the LOCAL TWIN of that Glue backfill mode" in sql
        assert "dags/airflow/esr_weekly_ingest_dag.py" in sql
        assert "THE COUNT IS A GREP, NOT A MEMORY" in sql

    def test_the_five_land_last_in_both_halves_of_the_migration(self):
        """Column ORDER inside the ALTER is the same load-bearing fact as the contract's tail
        placement: is_schema_widen admits only a pure trailing append, so a reordered ALTER would
        make the self-heal decline and every partition fail closed."""
        sql = _MIGRATION.read_text(encoding="utf-8")
        for half in ("leviathan_dev.silver_esr ADD COLUMNS",
                     "leviathan_dev.silver_esr_compact ADD COLUMNS"):
            body = sql.split(f"ALTER TABLE {half} (", 1)[1].split(");", 1)[0]
            names = [ln.split()[0] for ln in body.strip().splitlines() if ln.strip()]
            assert names == _FIVE, half
            assert all("double" in ln for ln in body.strip().splitlines() if ln.strip()), half
