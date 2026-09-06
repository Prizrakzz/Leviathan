"""scripts/ops/esr_netcommitment_runbook.py -- the ROLLOUT DOC, pinned.

A runbook is only worth having if the things it must never say are asserted rather than reviewed.
Hermetic: printing is pure, and no test here calls AWS.

WHAT IT PINS, and which finding each pin closes:

  C-NEW-F2  the image build goes through a CLEAN worktree + make_worker_context_tar.py, and the
            runbook explicitly forbids scripts/build_push_worker.ps1 on the shared tree;
            re-registration goes ONLY through scripts/ops/repin_jobdef_digest.py.
  C-M2      the two silver jobdefs' live envelope (2 vCPU / 12,288 MiB, rev 8 and rev 36) is
            stated as an --expect-* assertion on every repin line, and the widened frame's
            measured memory rides in the step the operator reads before promoting.
  C-M3      the re-bronze bound is the MEASURED first vintage, and the verdict sentence is
            restated so it can fail.
  house law every handed command is PowerShell 5.1 and no chain operator appears anywhere.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "scripts" / "ops" / "esr_netcommitment_runbook.py"


@pytest.fixture(scope="module")
def book():
    spec = importlib.util.spec_from_file_location("esr_netcommitment_runbook", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rendered(book, capsysbinary=None):
    lines = []
    for _title, cmds in book.steps("20260904T1200"):
        lines.extend(cmds)
    return lines


class TestHouseLaws:
    def test_no_chain_operator_anywhere(self, rendered):
        """Windows PowerShell 5.1: the pipeline-chain operators are a parser error. Owner law."""
        offenders = [ln for ln in rendered if "&" + "&" in ln or "||" in ln]
        assert offenders == []

    def test_every_line_is_ascii(self, book, rendered):
        for line in rendered:
            line.encode("ascii")
        for name in ("PRINT",):
            assert name

    def test_it_is_dry_run_by_construction(self, book):
        """No code path submits, registers, uploads or applies. The steps are strings."""
        src = _TOOL.read_text(encoding="utf-8")
        assert "import boto3" not in src
        assert "--run" not in [a for a in src.split() if a == "--run"]
        for forbidden in ("register_job_definition(", "submit_job(", "put_object(", "start_query"):
            assert forbidden not in src, forbidden


class TestImageBuildProvenance:
    def test_it_forbids_the_shared_tree_build_script_by_name(self, rendered):
        text = "\n".join(rendered)
        assert "DO NOT RUN build_push_worker.ps1 HERE" in text

    def test_the_build_goes_through_the_committed_tree_tar(self, rendered):
        text = "\n".join(rendered)
        assert "scripts/ops/make_worker_context_tar.py --repo" in text
        assert "worktree add --detach" in text
        assert "worktree remove" in text

    def test_the_gitignored_overlay_is_COPIED_INTO_the_worktree_BEFORE_the_tar(self, book):
        """RE-REVIEW NEW-1 -- the half of the recipe the C-NEW-F2 remedy left out.

        ``make_worker_context_tar.py`` takes TRACKED bytes from ``git archive <ref>`` but reads the
        gitignored ``configs/graphrag`` overlay from the ``--repo`` WORKING TREE (overlay_files()
        runs ``git ls-files --others --ignored`` in *repo*). ``git worktree add`` checks out
        TRACKED files only, so ``--repo <a fresh worktree>`` makes that overlay EMPTY BY
        CONSTRUCTION -- an image with ZERO gitignored configs on the jobdef 26 rendered families
        share, which is the estate's recorded 'worktree builds bake ZERO gitignored configs'
        incident and strictly worse than the dirty bake the step was written to prevent.

        MEASURED in the main tree 2026-09-04: 141 files, 4,751,532 bytes (69 causal DAGs). So S1
        must LIST them in the main tree, COPY them into the worktree, and only THEN tar -- in that
        order, which is what this pin asserts."""
        s1 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S1")))
        listed = s1.index("ls-files --others --ignored --exclude-standard -- configs/graphrag")
        copied = s1.index("Copy-Item -LiteralPath")
        tarred = s1.index("make_worker_context_tar.py --repo")
        assert listed < copied < tarred, "the overlay must be copied BEFORE the context tar"
        assert book.OVERLAY_FILES_MEASURED == 141
        assert book.OVERLAY_BYTES_MEASURED == 4751532
        assert "141" in s1 and "4,751,532" in s1

    def test_a_zero_overlay_is_a_WRITTEN_REFUSAL_not_a_note(self, book):
        """The tool prints ``overlay_files`` in its summary and nothing reads it. An operator who
        is not told the number is a gate will read a successful-looking build. So S1 states the
        expected value, and states that 0 stops the rollout."""
        s1 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S1")))
        assert "overlay_files   MUST be > 0" in s1
        assert "overlay_files: 0 IS A REFUSAL" in s1
        assert "MUST NOT be uploaded, built or deployed" in s1

    def test_CHECK_greps_S1_for_every_clause_of_the_image_recipe(self, book):
        """The recipe is only durable if something asserts it stayed written. ``--step CHECK``
        greps S1 for each clause; the second half of this test proves that grep is not vacuous."""
        assert book.s1_overlay_missing() == []
        original = book.S1_OVERLAY_CLAUSES
        book.S1_OVERLAY_CLAUSES = original + ("a clause no runbook contains",)
        try:
            assert book.s1_overlay_missing() == ["a clause no runbook contains"]
        finally:
            book.S1_OVERLAY_CLAUSES = original

    def test_the_digest_is_read_never_inferred(self, rendered):
        text = "\n".join(rendered)
        assert "READ THE PUSHED DIGEST OFF THE KANIKO LOG" in text
        assert "aws ecr describe-images" in text


class TestJobdefEnvelope:
    def test_the_measured_live_envelope_is_the_one_the_helper_asserts(self, book):
        """The numbers here were read off AWS on 2026-09-04. If a jobdef moves, the repin refuses
        rather than copying a descriptor nobody re-read."""
        assert dict((n, (r, v, m)) for n, r, v, m in book.JOBDEFS) == {
            "leviathan-dev-usda-esr-bronze": (20, "2", "4096"),
            "leviathan-dev-esr-bronze-to-silver": (8, "2", "12288"),
            "leviathan-dev-silver-publisher-runner": (36, "2", "12288"),
            "leviathan-dev-silver-gate": (34, "2", "8192"),
        }

    def test_every_repin_line_states_the_envelope(self, rendered):
        repins = [ln for ln in rendered if "repin_jobdef_digest.py" in ln and "--job-definition" in ln]
        assert len(repins) == 4
        for line in repins:
            assert "--expect-vcpu" in line and "--expect-memory" in line

    def test_the_two_silver_jobdefs_are_pinned_at_12288(self, rendered):
        for name in ("leviathan-dev-esr-bronze-to-silver",
                     "leviathan-dev-silver-publisher-runner"):
            line = next(ln for ln in rendered
                        if "repin_jobdef_digest.py" in ln and name in ln)
            assert "--expect-memory 12288" in line, name

    def test_the_4096_hardcoding_submitter_is_forbidden_by_name(self, rendered):
        text = "\n".join(rendered)
        assert "DO NOT USE jobs/submit/submit_batch_b2s_esr.py" in text

    def test_no_step_hands_a_bare_register_job_definition(self, rendered):
        assert not [ln for ln in rendered if "aws batch register-job-definition" in ln]


class TestMeasurements:
    def test_the_widened_frame_number_is_stated_where_it_is_read(self, book, rendered):
        """C-M2: measured on 80 real bronze objects through both transforms."""
        assert book.MEASURED["silver_bytes_per_row_delta"] == 40.00
        assert (round(book.MEASURED["silver_bytes_per_row_widened"]
                      - book.MEASURED["silver_bytes_per_row_head"], 2) == 40.00)
        shadow = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S4")))
        assert "346.35 B/row deep" in shadow
        assert "12.0 GiB envelope" in shadow
        assert "137" in shadow, "the OOM signature must be named where it would be seen"

    def test_the_rebronze_bound_is_the_measured_first_vintage(self, book, rendered):
        assert book.REBRONZE_BOUND == book.MEASURED["raw_first_vintage"] == "20260712"
        s3 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S3")))
        assert "--as-of-min', '20260712'" in s3
        assert "20260813" not in s3

    def test_the_census_runs_before_the_bound_is_used(self, book):
        titles = [t.split()[0] for t, _ in book.steps("x")]
        assert titles.index("S0") < titles.index("S3")
        s0 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S0")))
        assert "esr_netcommitment_raw_census.py" in s0
        assert "IF THE CENSUS DISAGREES" in s0

    def test_the_verdict_can_fail(self, book):
        """C-M3: the old sentence ('0.0 before 20260813') was guaranteed by the re-bronze scope.
        The restated one names a zero as a PIPELINE finding, which is falsifiable."""
        s4 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S4")))
        assert "a 0.0 anywhere is a PIPELINE finding, never a source finding" in s4
        assert "PER" in s4 and "COMMODITY" in s4

    def test_the_fabricated_vintage_residual_is_named_with_its_number(self, book):
        assert book.MEASURED["bronze_objects"] == 8920
        assert (book.MEASURED["bronze_objects"] - book.MEASURED["bronze_from_dated_raw"]
                == book.MEASURED["bronze_fabricated_vintages"] == 8474)
        s9 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S9")))
        assert "8474" in s9 or "8,474" in s9


class TestMinorFindings:
    def test_the_pg_mirror_is_reloaded_AFTER_the_promote(self, book):
        """C-m1: the S6 gate reload runs before the canonical objects exist, so it is expected to
        show all-NULL. S8 reloads again."""
        titles = [t.split()[0] for t, _ in book.steps("x")]
        assert titles.index("S6") < titles.index("S7") < titles.index("S8")
        s6 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S6")))
        s8 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S8")))
        assert "C-m1" in s6 and "all-NULL in pg here" in s6
        assert "Reload again now" in s8

    def test_partition_actions_are_read_against_a_denominator(self, book):
        """C-m6: the publisher only walks the partitions the run STAGES, so an outcome set with no
        count says nothing about orphan partitions."""
        s7 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S7")))
        assert "READ THE COUNT, NOT THE OUTCOME SET" in s7
        assert "aws glue get-partitions" in s7
        assert "ORPHAN" in s7

    def test_the_stale_glue_bronze_writer_is_named(self, rendered):
        """C-m4: jobs/glue/raw_to_bronze_usda_esr.py shares the transform but ships its own wheel."""
        text = "\n".join(rendered)
        assert "jobs/glue/raw_to_bronze_usda_esr.py" in text
        assert "manual-only" in text


class TestVintageLawAcrossWriters:
    def test_the_law_is_stated_for_all_FOUR_ESR_writers(self, book, rendered):
        """RE-REVIEW NEW-2, corrected by VERIFY-2 V2-NEW-1. The lane declared a law about BRONZE
        PARTITIONS -- "the as_of comes from the raw key or the raw_meta sidecar, never from
        today's date" -- and then shipped the closure as holding in "all THREE ESR writers" while
        a FOURTH sat outside it: jobs/ingest/backfill_bronze_usda_esr.py, the LOCAL twin of the
        Glue backfill mode, still stamped today onto undated keys and needed no flags to do it.
        Four writers now obey, the runbook says which mechanism each one uses, and it names the
        law-abiding fifth (the Airflow DAG) so the census is not re-discovered a third time."""
        text = (book.__doc__ or "") + "\n" + "\n".join(rendered)
        for writer in ("jobs/batch/esr_task.py",
                       "jobs/glue/raw_to_bronze_usda_esr.py",
                       "jobs/ingest/backfill_bronze_usda_esr.py",
                       "jobs/ingest/backfill_silver_usda_esr.py",
                       "dags/airflow/esr_weekly_ingest_dag.py"):
            assert writer in text, writer
        assert "ALL FOUR ESR WRITERS" in text
        assert "all THREE ESR" not in text, "the false closure must not survive anywhere"
        assert "REFUSES by name" in text or "REFUSES BY NAME" in text
        assert "--as-of-date is REQUIRED" in text
        assert "REQUIRES an explicit --as-of-date" in text

    def test_the_residual_says_what_actually_stops_the_growth(self, book):
        """C-F1's residual R1 is 8,474 pre-existing fabricated BRONZE objects. Saying "the vintage
        law stops it growing" was true of the Batch path only while the other writers were
        unguarded -- and the first correction over-reached the other way, charging a SILVER writer
        with stopping bronze growth it cannot cause. S9 now charges the bronze writers, names all
        four, and files the silver one under R3."""
        s9 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S9")))
        assert "ALL FOUR ESR writers" in s9
        assert "every BRONZE writer in the estate" in s9
        assert "raw_to_bronze_usda_esr.py REFUSES backfill mode" in s9
        assert "backfill_bronze_usda_esr.py, its LOCAL TWIN, REFUSES the undated" in s9
        r3 = s9.split("#   R3 ", 1)[1]
        assert "backfill_silver_usda_esr.py is the writer" in r3, (
            "the SILVER writer belongs under R3: it cannot add one of R1's bronze objects")
        assert "REQUIRES an explicit --as-of-date" in r3

    def test_a_ZERO_overlay_is_now_an_EXIT_STATUS_not_only_a_sentence(self, book, rendered):
        """VERIFY-2 V2-NEW-2. Every gate NEW-1 shipped was prose plus a grep that the prose
        exists; make_worker_context_tar.py returned 0 whatever the overlay count was. S1 now
        carries a PowerShell 5.1 throw, and the tool itself refuses."""
        text = "\n".join(rendered)
        s1 = "\n".join(next(c for t, c in book.steps("x") if t.startswith("S1")))
        assert "if ($overlay.Count -lt 1)" in s1 and "throw" in s1
        assert "--allow-empty-overlay" in s1
        assert "&&" not in text and "||" not in text, "PowerShell 5.1 has no chain operators"


class TestRollback:
    def test_rollback_is_layered_on_the_ALTER(self, book, capsys):
        assert book.rollback() == 0
        out = capsys.readouterr().out
        assert "BEFORE S5" in out and "AFTER S5" in out
        assert "ROLL FORWARD, never back" in out
        assert "repin_jobdef_digest.py" in out, "the rollback must copy the envelope too"
