"""BF-W2 step 2 -- the WASDE bronze-read runner (jobs/batch/wasde_silver_task.run_from_bronze).

Sibling of ``test_wasde_publish.py`` (same fakes, same contract re-homing). Proves the runner
wiring the wave depends on:

  * bounded release selection reads bronze release partitions and fails closed on an empty /
    unresolvable selection (F032-style ordering guard);
  * ``prior_series_state`` is seeded from bronze HISTORY, so a bounded catch-up's revision fields
    (prior_estimate / revision / release_sequence / revision_gap_days) depend on the PRIOR release
    even though only the newer release is published (F034);
  * the F033 region-cleanliness floor REFUSES the run before anything is staged, in every mode;
  * publish-mode routing: dry-run stages nothing; shadow stays outside canonical; canonical
    registers exactly the selected release_date partitions; and canonical AUTHORITY requires the
    signed ``LEVIATHAN_APPROVAL_JSON`` artifact through the guard main() wires.
"""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
import pytest
from leviathan.common import publish_guard as PG
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry

from jobs.batch import wasde_silver_task as T
from tests.unit.silver.conftest import (  # shared fakes + auth helpers (imported, never modified)
    TEST_BUCKET,
    TEST_DB,
    FakeGlue,
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)
from tests.unit.silver.test_wasde_publish import _mem_manifest_store, _seed_table

_BR = "bronze/production/source=usda_wasde"


@pytest.fixture()
def contract():
    """The real registry contract re-homed onto the allow-listed TEST surfaces (schema unchanged)."""
    c = dict(load_registry().table("silver_wasde"))
    c["s3_bucket"] = TEST_BUCKET
    c["s3_root"] = f"s3://{TEST_BUCKET}/silver/wasde"
    c["glue_database"] = TEST_DB
    return c


def _bronze_row(region, attribute, my, value, release_date, status="Proj."):
    return dict(release_date=release_date,
                table_name="World Wheat Supply and Use 1/ (Million Metric Tons)",
                region=region, market_year=my, status=status, projection_month="",
                attribute=attribute, value=value, unit="Million Metric Tons")


def _put_bronze(s3: FakeS3, release_date: str, rows: list[dict]) -> str:
    """Write a bronze release partition into the fake exactly as wasde_bronze_modern_task lays it
    out (one parquet under release_date=<d>/), so the runner's read path is exercised for real."""
    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    key = f"{_BR}/release_date={release_date}/part-000.parquet"
    s3.put_object(Bucket=TEST_BUCKET, Key=key, Body=buf.getvalue())
    return key


# ---------------------------------------------------------------------------
# Bounded selection -- fail-closed ordering guard.
# ---------------------------------------------------------------------------
def test_selection_fails_closed_on_empty_or_missing():
    with pytest.raises(T.WasdeBronzeNotReadyError):
        T.select_bronze_keys([])                                        # no bronze at all
    keys = [f"{_BR}/release_date=2024-05-10/part-000.parquet"]
    with pytest.raises(T.WasdeBronzeNotReadyError):
        T.select_bronze_keys(keys, from_date="2024-06-01")              # empty window
    with pytest.raises(T.WasdeBronzeNotReadyError):
        T.select_bronze_keys(keys, release_dates=["2024-06-12"])        # requested but absent


def test_selection_splits_publish_window_from_history():
    keys = [f"{_BR}/release_date={d}/part-000.parquet"
            for d in ("2024-04-11", "2024-05-10", "2024-06-12", "2024-07-12")]
    publish, history = T.select_bronze_keys(keys, from_date="2024-06-01", to_date="2024-06-30")
    assert sorted(publish) == ["2024-06-12"]
    assert sorted(history) == ["2024-04-11", "2024-05-10"]              # strictly-before releases
    # explicit --release-date selection overrides the window; seed_from bounds the history read.
    publish, history = T.select_bronze_keys(keys, release_dates=["2024-07-12"],
                                            seed_from="2024-05-01")
    assert sorted(publish) == ["2024-07-12"]
    assert sorted(history) == ["2024-05-10", "2024-06-12"]


# ---------------------------------------------------------------------------
# F034 QUARANTINE (D-SG G1-2) -- excluded from BOTH legs, never silently.
# ---------------------------------------------------------------------------
def test_quarantine_excludes_from_publish_window_and_history_seed():
    keys = [f"{_BR}/release_date={d}/part-000.parquet"
            for d in ("2024-04-11", "2024-05-10", "2024-06-12", "2024-07-12")]
    publish, history = T.select_bronze_keys(
        keys, from_date="2024-06-01", quarantined=["2024-05-10", "2024-06-12"])
    assert sorted(publish) == ["2024-07-12"]      # quarantined release never publishes
    assert sorted(history) == ["2024-04-11"]      # ... and never seeds the revision series,
                                                  # which is the half a publish-only filter misses
    # the live conflict release is pinned WITH its evidence, so the parse fix has a target.
    assert "1985-06-10" in T.QUARANTINED_RELEASES
    reason = T.QUARANTINE_REASONS["1985-06-10"]
    assert "2.5" in reason and "1.67" in reason and "avg_farm_price_bu" in reason


def test_quarantine_refuses_an_explicitly_named_release():
    keys = [f"{_BR}/release_date={d}/part-000.parquet" for d in ("2024-05-10", "2024-06-12")]
    with pytest.raises(T.WasdeQuarantineError):
        T.select_bronze_keys(keys, release_dates=["2024-05-10"], quarantined=["2024-05-10"])
    # named-but-absent-from-bronze still reports QUARANTINE, not the misleading "missing".
    with pytest.raises(T.WasdeQuarantineError):
        T.select_bronze_keys(keys, release_dates=["1985-06-10"], quarantined=["1985-06-10"])


def test_since_days_resolves_the_incremental_window():
    assert T._resolve_from_date(T._parse_args(["--since-days", "75"]),
                                today=date(2026, 8, 16)) == "2026-06-02"
    assert T._resolve_from_date(T._parse_args(["--from", "2026-01-01"]),
                                today=date(2026, 8, 16)) == "2026-01-01"
    assert T._resolve_from_date(T._parse_args([]), today=date(2026, 8, 16)) is None
    with pytest.raises(SystemExit):     # both knobs = fail closed
        T._resolve_from_date(T._parse_args(["--from", "2026-01-01", "--since-days", "75"]),
                             today=date(2026, 8, 16))


# ---------------------------------------------------------------------------
# F034 -- prior_series_state seeded from bronze HISTORY.
# ---------------------------------------------------------------------------
def test_runner_seeds_revision_series_from_bronze_history(contract):
    s3, glue = FakeS3(), FakeGlue()
    k1 = _put_bronze(s3, "2024-05-10",
                     [_bronze_row("World", "Ending Stocks", "2024/25", 100.0, "2024-05-10")])
    k2 = _put_bronze(s3, "2024-06-12",
                     [_bronze_row("World", "Ending Stocks", "2024/25", 105.0, "2024-06-12")])
    _store, put = _mem_manifest_store()
    manifest, results = T.run_from_bronze(
        contract=contract, auth=dryrun_authorization(), s3_client=s3, glue_client=glue,
        bronze_keys=[k1, k2], bucket=TEST_BUCKET,
        from_date="2024-06-01", to_date="2024-06-30",
        manifest_store=put, run_id="wasde-seed")
    # only release 2 is planned; release 1 participated purely as the HISTORY seed.
    assert [r.release_date for r in results] == ["2024-06-12"]
    assert [i["values"] for i in manifest.inputs] == [["2024-06-12"]]
    row = results[0].rows[0]
    assert row["is_first_estimate"] is False                            # depends on release 1
    assert row["prior_release_date"] == "2024-05-10"
    assert row["prior_estimate"] == 100.0
    assert row["revision"] == 5.0 and row["revision_direction"] == "up"
    assert row["release_sequence"] == 2
    assert row["revision_gap_days"] == 33


def test_without_history_seed_the_same_release_is_a_first_estimate(contract):
    """The negative control: identical bronze, seeding disabled -> no revision linkage. Proves the
    threading in the test above flows from the seed, not from anything else in the runner."""
    s3 = FakeS3()
    k1 = _put_bronze(s3, "2024-05-10",
                     [_bronze_row("World", "Ending Stocks", "2024/25", 100.0, "2024-05-10")])
    k2 = _put_bronze(s3, "2024-06-12",
                     [_bronze_row("World", "Ending Stocks", "2024/25", 105.0, "2024-06-12")])
    _store, put = _mem_manifest_store()
    _manifest, results = T.run_from_bronze(
        contract=contract, auth=dryrun_authorization(), s3_client=s3, glue_client=FakeGlue(),
        bronze_keys=[k1, k2], bucket=TEST_BUCKET,
        from_date="2024-06-01", seed_history=False,
        manifest_store=put, run_id="wasde-noseed")
    row = results[0].rows[0]
    assert row["is_first_estimate"] is True
    assert row["revision"] is None and row["release_sequence"] == 1


# ---------------------------------------------------------------------------
# F033 -- region-junk floor refusal (before ANY staging, any mode).
# ---------------------------------------------------------------------------
def test_region_junk_floor_refuses_before_any_write(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    # '#5' survives the bronze-row quarantine (classify_region('#5') is clean) but its NORMALIZED
    # published token is '5' -- pure-numeric -> the PUBLISHED-axis gate trips (1/2 distinct = 50%
    # >> the 2% floor). This is the escape class the gate exists to catch.
    key = _put_bronze(s3, "2024-06-12", [
        _bronze_row("World", "Production", "2024/25", 800.0, "2024-06-12"),
        _bronze_row("#5", "Production", "2024/25", 9.0, "2024-06-12"),
    ])
    before = set(s3.keys())
    _store, put = _mem_manifest_store()
    with pytest.raises(T.WasdeRegionGateError):
        T.run_from_bronze(
            contract=contract, auth=canonical_authorization(), s3_client=s3, glue_client=glue,
            bronze_keys=[key], bucket=TEST_BUCKET, from_date="2024-06-01",
            manifest_store=put, run_id="wasde-gate")
    assert set(s3.keys()) == before                                     # nothing staged, shadow incl.
    assert glue.partitions == {}                                        # nothing cataloged


# ---------------------------------------------------------------------------
# Publish-mode routing through the runner.
# ---------------------------------------------------------------------------
def test_dry_run_stages_nothing(contract):
    s3, glue = FakeS3(), FakeGlue()
    key = _put_bronze(s3, "2024-06-12",
                      [_bronze_row("World", "Production", "2024/25", 800.0, "2024-06-12")])
    _store, put = _mem_manifest_store()
    manifest, _results = T.run_from_bronze(
        contract=contract, auth=dryrun_authorization(), s3_client=s3, glue_client=glue,
        bronze_keys=[key], bucket=TEST_BUCKET, from_date="2024-06-01",
        manifest_store=put, run_id="wasde-dry")
    assert manifest.state is ManifestState.VALIDATED                    # halted before canonical
    assert s3.keys() == [key]                                           # bronze fixture only
    assert glue.partitions == {}


def test_shadow_stays_outside_canonical(contract):
    s3, glue = FakeS3(), FakeGlue()
    key = _put_bronze(s3, "2024-06-12",
                      [_bronze_row("World", "Production", "2024/25", 800.0, "2024-06-12")])
    _store, put = _mem_manifest_store()
    manifest, _results = T.run_from_bronze(
        contract=contract, auth=shadow_authorization(), s3_client=s3, glue_client=glue,
        bronze_keys=[key], bucket=TEST_BUCKET, from_date="2024-06-01",
        shadow_prefix="silver/_shadow/wasde",                            # outside partition locations
        manifest_store=put, run_id="wasde-shadow")
    assert manifest.state is ManifestState.VALIDATED
    new_keys = [k for k in s3.keys() if k != key]
    assert new_keys and all(k.startswith("silver/_shadow/wasde/") for k in new_keys)
    assert not any(k.startswith("silver/wasde/release_date=") for k in new_keys)
    assert glue.partitions == {}                                        # never cataloged in shadow


def test_canonical_registers_selected_partitions_with_history_linkage(contract):
    s3, glue = FakeS3(), FakeGlue()
    _seed_table(glue, contract)
    _put_bronze(s3, "2024-05-10",
                [_bronze_row("World", "Ending Stocks", "2024/25", 100.0, "2024-05-10")])
    _put_bronze(s3, "2024-06-12",
                [_bronze_row("World", "Ending Stocks", "2024/25", 105.0, "2024-06-12")])
    _put_bronze(s3, "2024-07-12",
                [_bronze_row("World", "Ending Stocks", "2024/25", 103.0, "2024-07-12")])
    bronze_keys = [k for k in s3.keys()]
    _store, put = _mem_manifest_store()
    manifest, results = T.run_from_bronze(
        contract=contract, auth=canonical_authorization(), s3_client=s3, glue_client=glue,
        bronze_keys=bronze_keys, bucket=TEST_BUCKET, from_date="2024-06-01",
        shadow_prefix="silver/_shadow/wasde", manifest_store=put, run_id="wasde-canon")
    assert manifest.state is ManifestState.CERTIFIED
    # exactly the 2 in-window release_date partitions registered; the history release is NOT.
    assert sorted(v for (_t, v) in glue.partitions) == [("2024-06-12",), ("2024-07-12",)]
    # revision series thread across the window AND from the seeded history release.
    june, july = results[0].rows[0], results[1].rows[0]
    assert (june["prior_release_date"], june["release_sequence"]) == ("2024-05-10", 2)
    assert (july["prior_release_date"], july["release_sequence"]) == ("2024-06-12", 3)
    assert july["revision"] == -2.0 and july["revision_direction"] == "down"


def test_canonical_authority_requires_signed_approval_artifact(monkeypatch):
    """The guard seam main() wires: canonical without LEVIATHAN_APPROVAL_JSON fails closed; the
    SAME call with the signed artifact (+ secret) authorizes canonical mutation."""
    target = T._publish_target(
        PG.PROD_ACCOUNT_ID,
        f"arn:aws:sts::{PG.PROD_ACCOUNT_ID}:assumed-role/leviathan-dev-batch-job-role/task",
        "leviathan-dev-shahem-001", "leviathan_dev")
    monkeypatch.delenv(PG.ENV_APPROVAL_JSON, raising=False)
    monkeypatch.delenv(PG.ENV_APPROVAL_SECRET, raising=False)
    monkeypatch.delenv(PG.ENV_READINESS, raising=False)
    monkeypatch.delenv(PG.ENV_ROLE_ARN, raising=False)
    with pytest.raises(PG.ApprovalError):
        PG.authorize_publish(target, argv=["--publish-mode", "canonical"])
    expiry = "2099-01-01T00:00:00Z"
    sig = PG.sign_approval(environment="leviathan_dev", table="silver_wasde",
                           registry_hash="rh", git_sha="sha", expiry=expiry, secret="s3cret")
    monkeypatch.setenv(PG.ENV_APPROVAL_SECRET, "s3cret")
    monkeypatch.setenv(PG.ENV_APPROVAL_JSON, json.dumps(dict(
        environment="leviathan_dev", table="silver_wasde", registry_hash="rh",
        git_sha="sha", expiry=expiry, signature=sig)))
    auth = PG.authorize_publish(target, argv=["--publish-mode", "canonical"])
    assert auth.may_mutate_canonical is True
