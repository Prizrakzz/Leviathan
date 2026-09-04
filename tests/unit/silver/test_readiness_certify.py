"""SILVER-F080 + SILVER-F083 unit tests -- the four-track readiness certification core.

Everything is a synthetic :class:`TableEvidence`; nothing touches AWS/registry/reports (the
pure core has no I/O). Covers:
  * each of the FOUR tracks passing AND failing to the correct verdict + blocking work order,
  * the rollup states (CERTIFIED / BACKFILL_READY / GENERATION_READY / BLOCKED),
  * the honesty invariant: a table with a planned/waived defect renders BLOCKED-BY, never green,
  * generator determinism (same evidence -> byte-identical certificate),
  * the global R4 certificate is RED (not signed) while any table is BLOCKED, and its
    work_orders map is the B-wave backlog.
The runner's artifact-assembly (build_evidence) is smoke-checked against the live registry +
report artifacts in one test that reads only local files (no AWS).
"""
from __future__ import annotations

import json

import pytest

from leviathan.silver import readiness as r
from leviathan.silver.readiness import (
    TableEvidence,
    certify_all,
    certify_table,
    evaluate_catalog,
    evaluate_current_data,
    evaluate_freshness,
    evaluate_producer,
)


# ---------------------------------------------------------------------------
# a clean, fully-ready evidence baseline the tests perturb one track at a time
# ---------------------------------------------------------------------------
def _clean(**kw) -> TableEvidence:
    base = dict(
        table="silver_demo",
        producer_status="producer",
        transform="src/leviathan/transforms/bronze_to_silver/demo.py",
        batch_task="jobs/batch/demo_task.py",
        shadow_cert_ok=None,
        census_present=True,
        census_passed=True,
        # freshness PASS via a probe (silver >= bronze, within SLA)
        freshness_probe={"silver_ingest_date": "2026-06-16", "bronze_ingest_date": "2026-06-16",
                         "newest_age_days": 3},
        max_lag_days=30,
    )
    base.update(kw)
    return TableEvidence(**base)


# ---------------------------------------------------------------------------
# (1) PRODUCER track
# ---------------------------------------------------------------------------
def test_producer_pass_when_discoverable():
    tr = evaluate_producer(_clean())
    assert tr.verdict == r.PASS and not tr.blocking


def test_producer_orphan_blocked_to_r3_and_bf_w3():
    ev = _clean(producer_status="orphan", transform=None, batch_task=None,
                producer_package="SILVER-F040")
    tr = evaluate_producer(ev)
    assert tr.verdict == r.BLOCKED
    assert "SILVER-F040" in tr.blocking and r.WO_BF_W3 in tr.blocking


def test_producer_half_orphan_with_green_shadow_still_blocked_until_registry_repointed():
    ev = _clean(producer_status="half-orphan", transform=None, batch_task=None,
                producer_package="SILVER-F051", shadow_cert_ok=True)
    tr = evaluate_producer(ev)
    assert tr.verdict == r.BLOCKED
    assert any("not yet repointed" in x for x in tr.reasons)


def test_producer_shadow_cert_regression_blocks():
    tr = evaluate_producer(_clean(shadow_cert_ok=False))
    assert tr.verdict == r.BLOCKED


def test_producer_ml_null_batch_task_is_fine():
    tr = evaluate_producer(_clean(is_ml=True, batch_task=None))
    assert tr.verdict == r.PASS


# ---------------------------------------------------------------------------
# (2) CATALOG track
# ---------------------------------------------------------------------------
def test_catalog_pass_when_only_cosmetic_diff():
    ev = _clean(catalog_drift_rows=({"dimension": "formatting", "disposition": "cosmetic",
                                     "detail": "header rewrite"},))
    assert evaluate_catalog(ev).verdict == r.PASS


def test_catalog_hidden_schema_blocks_to_parsed_package():
    ev = _clean(catalog_drift_rows=(
        {"dimension": "physical-only-columns", "disposition": "registry-wins (R2 fix)",
         "detail": "catalog missing 12 physical column(s); add in R2 (SILVER-F024 / SILVER-F016)"},))
    tr = evaluate_catalog(ev)
    assert tr.verdict == r.BLOCKED and "SILVER-F024" in tr.blocking


def test_catalog_already_fixed_registry_bug_is_not_blocking():
    ev = _clean(catalog_drift_rows=(
        {"dimension": "column-order", "disposition": "hand-DDL-wins (registry bug, FIXED)",
         "detail": "order drift already fixed"},))
    assert evaluate_catalog(ev).verdict == r.PASS


def test_catalog_reconcile_divergence_blocks():
    ev = _clean(reconcile_divergences=(
        {"check": "numbers", "kind": "publication_lag_days", "detail": "registry != tablespec"},))
    tr = evaluate_catalog(ev)
    assert tr.verdict == r.BLOCKED and r.WO_RECONCILE in tr.blocking


def test_catalog_placeholder_partitions_block_to_f018():
    tr = evaluate_catalog(_clean(placeholder_partition_count=5))
    assert tr.verdict == r.BLOCKED and r.WO_F018 in tr.blocking


# ---------------------------------------------------------------------------
# (3) CURRENT-DATA track (value census)
# ---------------------------------------------------------------------------
def test_current_data_pass_when_census_green():
    assert evaluate_current_data(_clean()).verdict == r.PASS


def test_current_data_missing_census_blocked_to_v001():
    tr = evaluate_current_data(_clean(census_present=False, census_passed=None))
    assert tr.verdict == r.BLOCKED and r.WO_V001 in tr.blocking


def test_current_data_all_nan_maps_to_bf_w1():
    tr = evaluate_current_data(_clean(census_passed=False, census_gate_kinds=("all_nan",)))
    assert tr.verdict == r.BLOCKED and r.WO_BF_W1 in tr.blocking


def test_current_data_single_vintage_maps_to_bf_w2():
    tr = evaluate_current_data(_clean(census_passed=False, census_gate_kinds=("single_vintage",)))
    assert tr.verdict == r.BLOCKED and r.WO_BF_W2 in tr.blocking


def test_current_data_na_for_ml_table():
    assert evaluate_current_data(_clean(is_ml=True, census_present=False)).verdict == r.NA


# ---------------------------------------------------------------------------
# (4) FRESHNESS track
# ---------------------------------------------------------------------------
def test_freshness_pass_when_probe_fresh():
    assert evaluate_freshness(_clean()).verdict == r.PASS


def test_freshness_deferred_when_no_probe():
    tr = evaluate_freshness(_clean(freshness_probe=None))
    assert tr.verdict == r.DEFERRED and not tr.blocking


def test_freshness_known_stale_blocks_to_wave():
    tr = evaluate_freshness(_clean(freshness_probe=None, staleness_package="BF-W1"))
    assert tr.verdict == r.BLOCKED and "BF-W1" in tr.blocking


def test_freshness_silver_older_than_bronze_blocks():
    ev = _clean(freshness_probe={"silver_ingest_date": "2026-05-16",
                                 "bronze_ingest_date": "2026-06-16", "newest_age_days": 3})
    tr = evaluate_freshness(ev)
    assert tr.verdict == r.BLOCKED


def test_freshness_past_sla_blocks():
    ev = _clean(freshness_probe={"silver_ingest_date": "2026-06-16",
                                 "bronze_ingest_date": "2026-06-16", "newest_age_days": 400},
                max_lag_days=30)
    assert evaluate_freshness(ev).verdict == r.BLOCKED


# ---------------------------------------------------------------------------
# rollup states
# ---------------------------------------------------------------------------
def test_all_pass_is_certified():
    c = certify_table(_clean())
    assert c.readiness_state == r.CERTIFIED and not c.blocking


def test_backfill_ready_when_freshness_only_deferred():
    """Producer+catalog+value certified; freshness deferred to the B-waves -> the plan's R4
    green target BACKFILL_READY (ready to backfill, not yet current)."""
    c = certify_table(_clean(freshness_probe=None))
    assert c.readiness_state == r.BACKFILL_READY and not c.blocking


def test_generation_ready_for_ml_table():
    c = certify_table(_clean(table="silver_model_predictions", is_ml=True,
                             batch_task=None, census_present=False, freshness_probe=None))
    assert c.readiness_state == r.GENERATION_READY


def test_planned_defect_renders_blocked_by_never_green():
    """The honesty invariant: a table with a waived/planned defect (here a not-yet-run census)
    renders BLOCKED-BY:<pkg> and is never a silent green."""
    c = certify_table(_clean(census_present=False, census_passed=None))
    assert c.readiness_state == r.STATE_BLOCKED
    assert c.label.startswith("BLOCKED-BY:") and r.WO_V001 in c.label
    assert r.WO_V001 in c.blocking


def test_pre_publish_table_blocks_on_its_publishing_wave_not_v001():
    """PRICE_AND_PLAYBOOKS W1.0: a table REGISTERED AHEAD OF ITS PRODUCERS (the F010 contract lands
    first so the schema is ratified, generated, DDL'd and linted before a byte is written) has zero
    canonical objects, so a value census is not merely missing but IMPOSSIBLE. It stays BLOCKED and
    is never silently green -- but the work order that closes it is the wave that PUBLISHES the
    table, not SILVER-V001 ('census the data that exists'). Fabricating a {"passed": true} census
    entry for a table with no objects is the alternative this branch exists to make unnecessary."""
    c = certify_table(_clean(table="silver_futures_eod", census_present=False, census_passed=None,
                             current_data_package="PRICE-PLAYBOOKS-W1A"))
    assert c.readiness_state == r.STATE_BLOCKED
    assert "PRICE-PLAYBOOKS-W1A" in c.blocking
    assert r.WO_V001 not in c.blocking
    # an ordinary uncensused table is unaffected -- it still lands on V001.
    assert r.WO_V001 in certify_table(_clean(census_present=False, census_passed=None)).blocking


def test_pre_publish_map_is_wired_into_the_runner():
    from jobs.audit import readiness_certify as rcert
    assert rcert.PRE_PUBLISH_PACKAGE["silver_futures_eod"] == "PRICE-PLAYBOOKS-W1A"


def test_chirps_shape_blocks_on_three_tracks():
    """CHIRPS today: all-NaN value + stale silver + a projection catalog it repairs in BF-W1."""
    c = certify_table(_clean(
        table="silver_chirps", census_passed=False, census_gate_kinds=("all_nan",),
        freshness_probe=None, staleness_package="BF-W1"))
    assert c.readiness_state == r.STATE_BLOCKED
    assert r.WO_BF_W1 in c.blocking


# ---------------------------------------------------------------------------
# global certificate + determinism
# ---------------------------------------------------------------------------
def _mixed_population():
    return [
        _clean(table="silver_ok"),                                           # CERTIFIED
        _clean(table="silver_defer", freshness_probe=None),                  # BACKFILL_READY
        _clean(table="silver_model_predictions", is_ml=True, batch_task=None,
               census_present=False, freshness_probe=None),                  # GENERATION_READY
        _clean(table="silver_chirps", census_passed=False,
               census_gate_kinds=("all_nan",), freshness_probe=None,
               staleness_package="BF-W1"),                                   # BLOCKED BF-W1
        _clean(table="silver_esr_compact", census_passed=False,
               census_gate_kinds=("single_vintage",), freshness_probe=None,
               staleness_package="BF-W2"),                                   # BLOCKED BF-W2
        _clean(table="silver_fred_fx", producer_status="orphan", transform=None,
               batch_task=None, producer_package="SILVER-F040",
               freshness_probe=None),                                        # BLOCKED F040/BF-W3
    ]


def test_global_certificate_is_red_and_unsigned_while_blocked():
    cert = certify_all(_mixed_population())
    assert cert["verdict"] == "RED"
    assert cert["signed"] is False
    assert set(cert["blocked_tables"]) == {"silver_chirps", "silver_esr_compact", "silver_fred_fx"}
    # the work-orders map is the B-wave backlog
    assert "silver_chirps" in cert["work_orders"]["BF-W1"]
    assert "silver_esr_compact" in cert["work_orders"]["BF-W2"]
    assert "silver_fred_fx" in cert["work_orders"]["SILVER-F040"]
    assert "silver_fred_fx" in cert["work_orders"]["BF-W3"]
    # five correctness dimensions surfaced
    dims = cert["correctness_dimensions"]
    assert set(dims) == {"producer", "catalog", "value_current_data", "freshness"}
    assert dims["value_current_data"].get("NA") == 1        # the ML table


def test_global_certificate_green_only_when_zero_blocked():
    cert = certify_all([_clean(table="silver_a"), _clean(table="silver_b")])
    assert cert["verdict"] == "GREEN" and not cert["blocked_tables"]
    # even GREEN never self-signs
    assert cert["signed"] is False


def test_certificate_generator_is_deterministic():
    pop = _mixed_population()
    a = json.dumps(certify_all(pop), sort_keys=True)
    b = json.dumps(certify_all(list(reversed(pop))), sort_keys=True)
    assert a == b  # order-independent + no clock in the pure core


def test_work_orders_and_blocking_are_sorted_deterministic():
    ev = _clean(table="silver_multi", producer_status="orphan", transform=None,
                batch_task=None, producer_package="SILVER-F051",
                census_passed=False, census_gate_kinds=("all_nan",),
                freshness_probe=None, staleness_package="BF-W1",
                catalog_drift_rows=(
                    {"dimension": "physical-only-columns", "disposition": "registry-wins",
                     "detail": "hidden schema SILVER-F024"},))
    c = certify_table(ev)
    assert list(c.blocking) == sorted(set(c.blocking))  # deduped + sorted


# ---------------------------------------------------------------------------
# runner smoke: build_evidence over the LIVE registry + report artifacts (local files only)
#
# RE-SCOPED 2026-08-16 (suite-debt sweep). This was ONE test and it was BADLY SCOPED: half of it
# exercises the runner against the in-repo registry (deterministic, tracked, correct to assert), and
# the other half asserted per-table VERDICTS that are computed entirely from
# reports/silver_readiness/ -- a tree that is GITIGNORED (.gitignore:77) and 0-files-tracked. Two
# consequences, both measured rather than assumed:
#
#   * on a fresh clone the tree does not exist at all, so those assertions never described anything
#     reproducible;
#   * on this machine the tree is the ORIGINAL R1 snapshot (every file mtime 2026-07-12 20:00), in
#     which R1_V001_value_census/value_census_summary.json still records
#     silver_chirps -> {"passed": false, "kinds": ["all_nan"]}. The certifier reads that faithfully
#     and returns BLOCKED. The assertion pinned BACKFILL_READY, which is the state AFTER the BF-W1
#     backfill + a census re-run + a summary regeneration -- work the artifact tree never received.
#
# So the red was neither a code regression nor a stale constant: the test was asserting a
# point-in-time snapshot of an untracked artifact as if it were a repo invariant. The fix is to say
# so out loud. The registry half runs always; the verdict half declares its precondition and SKIPS
# with the precise reason when the artifacts do not meet it. Deliberately NOT done: fabricating a
# passing census summary, or checking in a synthetic 45-table artifact corpus that would make the
# "runner smoke over the LIVE report artifacts" test stop smoking the live report artifacts.
# ---------------------------------------------------------------------------
def _local_report_tree_state() -> str | None:
    """None when the local report tree can support the verdict assertions; else the skip reason.

    Pinned to the ONE dependency those assertions actually rest on -- the V001 value-census summary
    -- and it reports which of the two ways it is unusable, so the skip is diagnostic, not a shrug."""
    import json

    from jobs.audit import readiness_certify as rcert

    summary = rcert.V001_SUMMARY
    if not summary.exists():
        return (f"reports/silver_readiness/ is gitignored and absent here ({summary} not found). "
                f"The per-table verdicts below are computed FROM that tree, so there is nothing to "
                f"assert. Regenerate it with the R1 value-census run to exercise this.")
    try:
        tables = (json.loads(summary.read_text(encoding="utf-8")) or {}).get("tables") or {}
    except (OSError, ValueError) as exc:
        return f"{summary} is present but unreadable ({exc}); refusing to guess its contents"
    chirps = tables.get("silver_chirps") or {}
    if chirps.get("passed") is not True:
        return (f"the local V001 census summary is a PRE-BF-W1 snapshot: silver_chirps records "
                f"passed={chirps.get('passed')!r} kinds={chirps.get('kinds')!r}, so the certifier "
                f"correctly returns BLOCKED. These assertions describe the POST-backfill tree. "
                f"Re-run the BF-W1 backfill + the value census and regenerate {summary.name} to "
                f"exercise them -- do NOT relax the assertions to match a stale artifact.")
    return None


def test_runner_build_evidence_smoke(tmp_path):
    """The REGISTRY half: hermetic, because the F010 registry is tracked in-repo."""
    from jobs.audit import readiness_certify as rcert
    from leviathan.silver.registry import load_registry

    reg = load_registry()
    evidence = rcert.build_evidence(reg, evidence_dir=tmp_path)
    # 43 R0 tables + the T2B gold_pattern_records ledger (generation-only, census-exempt like
    # model_predictions -- an engine-replay output, not a value-census measurement source) +
    # silver_futures_eod (PRICE_AND_PLAYBOOKS W1.0, registered ahead of its producers).
    # D-EC DK-13: + gold_board_crush; MINAGRO: + silver_minagro_grain_exports.
    # THE FOUR-FAMILY WAVE CLOSE (2026-08-20): 47 -> 50. The evidence set is one row per REGISTRY
    # table by construction (the next assert is the real invariant), so each new contract adds a row
    # whether or not its producer has ever run: + silver_moex_agro_indices, + silver_ams_gtr,
    # + silver_eex_freight. All three land BLOCKED with no census, which is the honest state --
    # silver_moex_agro_indices and silver_ams_gtr name their work order via PRE_PUBLISH_PACKAGE.
    # 50 -> 51: + gold_futures_spreads (GN-2 W2.3; pin caught up 2026-08-25)
    # 51 -> 52: + silver_psd_attributes (PROJECTION WAVE Lane 3, 2026-08-25). It lands BLOCKED with
    # no census and that is the honest state -- the transform has a full-object proof but no batch
    # task and no canonical publish yet, so there is nothing on S3 for the value census to read.
    # 52 -> 53: + silver_pink_sheet_vintages (PINK SHEET VINTAGES lane (a), 2026-09-03). It
    # lands BLOCKED with no census and that is the honest state -- the transform and the batch
    # task both exist, but no canonical publish has run, so there is nothing on S3 for the
    # value census to read.
    assert len(evidence) == 53
    assert {e.table for e in evidence} == set(reg.names())    # one row per registry table, no dups
    cert = certify_all(evidence)
    # Structural, and true whatever the artifact tree says: a certificate covers every table and
    # NEVER self-signs.
    assert set(cert["tables"]) == set(reg.names())
    assert cert["signed"] is False
    assert cert["verdict"] in ("RED", "GREEN")


def test_runner_certificate_verdicts_over_the_local_report_tree(tmp_path):
    """The ARTIFACT half: asserts the POST-BF-W3 verdicts, and skips (loudly, naming the gap) when
    the gitignored report tree cannot support them. See the block comment above."""
    from jobs.audit import readiness_certify as rcert
    from leviathan.silver.registry import load_registry

    reason = _local_report_tree_state()
    if reason:
        pytest.skip(reason)

    reg = load_registry()
    evidence = rcert.build_evidence(reg, evidence_dir=tmp_path)
    cert = certify_all(evidence)

    # HONEST: today it must be RED (orphans unadopted, chirps all-NaN, ESR single-vintage).
    assert cert["verdict"] == "RED"
    assert cert["signed"] is False
    # POST-B1/B2 close (KNOWN_STALENESS emptied at the BF-W3 close): the weather trio and the
    # ESR compact table are no longer known-stale -- they evaluate BACKFILL_READY, not a wave
    # work order.
    wo = cert["work_orders"]
    assert cert["tables"]["silver_chirps"]["readiness_state"] == r.BACKFILL_READY
    assert cert["tables"]["silver_esr_compact"]["readiness_state"] == r.BACKFILL_READY
    # the R4 real run censused ALL 43 tables (scratch/R4_census_all.log), so the V001
    # missing-census order is gone; it must REAPPEAR if any table is ever added uncensused.
    assert r.WO_V001 not in wo
    # BF-W3 step 0.5: the producer-repoint cleared the producer track for the core orphan
    # families -- they now evaluate BACKFILL_READY (the wave's whole point; GATE-02).
    for orphan in ("silver_fred_fx", "silver_noaa_oni", "silver_icco_cocoa"):
        assert cert["tables"][orphan]["readiness_state"] == r.BACKFILL_READY
    # the generated ML table is NEVER BACKFILL_READY; today it is honestly BLOCKED-BY the F018
    # placeholder-partition cleanup (8 placeholder partitions still on the registry fingerprint),
    # and its value track is NA -- it can only reach GENERATION_READY once F018 executes.
    mp = cert["tables"]["silver_model_predictions"]
    assert mp["readiness_state"] in (r.STATE_BLOCKED, r.GENERATION_READY)
    assert mp["tracks"]["current_data"]["verdict"] == r.NA
    assert mp["readiness_state"] != r.BACKFILL_READY
    if mp["readiness_state"] == r.STATE_BLOCKED:
        assert r.WO_F018 in cert["work_orders"]
