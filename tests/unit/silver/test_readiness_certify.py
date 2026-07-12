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
# ---------------------------------------------------------------------------
def test_runner_build_evidence_smoke(tmp_path):
    from jobs.audit import readiness_certify as rcert
    from leviathan.silver.registry import load_registry

    reg = load_registry()
    evidence = rcert.build_evidence(reg, evidence_dir=tmp_path)
    assert len(evidence) == 43
    cert = certify_all(evidence)

    # HONEST: today it must be RED (orphans unadopted, chirps all-NaN, ESR single-vintage).
    assert cert["verdict"] == "RED"
    assert cert["signed"] is False
    # the concrete work orders the assignment calls out are present
    wo = cert["work_orders"]
    assert "silver_chirps" in wo.get("BF-W1", [])
    assert "silver_esr_compact" in wo.get("BF-W2", [])
    # the R4 real run censused ALL 43 tables (scratch/R4_census_all.log), so the V001
    # missing-census order is gone; it must REAPPEAR if any table is ever added uncensused.
    assert r.WO_V001 not in wo
    # every orphan producer is BLOCKED (registry entrypoint still null)
    for orphan in ("silver_fred_fx", "silver_noaa_oni", "silver_icco_cocoa"):
        assert cert["tables"][orphan]["readiness_state"] == r.STATE_BLOCKED
    # the generated ML table is NEVER BACKFILL_READY; today it is honestly BLOCKED-BY the F018
    # placeholder-partition cleanup (8 placeholder partitions still on the registry fingerprint),
    # and its value track is NA -- it can only reach GENERATION_READY once F018 executes.
    mp = cert["tables"]["silver_model_predictions"]
    assert mp["readiness_state"] in (r.STATE_BLOCKED, r.GENERATION_READY)
    assert mp["tracks"]["current_data"]["verdict"] == r.NA
    assert mp["readiness_state"] != r.BACKFILL_READY
    if mp["readiness_state"] == r.STATE_BLOCKED:
        assert r.WO_F018 in cert["work_orders"]
