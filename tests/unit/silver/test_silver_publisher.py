"""SILVER-F015: the common shadow-first publisher + run manifest.

Covers: manifest state machine (legal/illegal transitions), dry-run (nothing written), shadow (staged
to shadow prefix, never promoted/cataloged), canonical happy path (shadow->promote->catalog->certify),
validation gate blocks promotion, failure injection at all four seams leaves canonical untouched,
identical rerun is an identical replacement, lease-fencing blocks a stale writer, and -- end to end
through the real publish_guard -- a canonical publish WITHOUT an approval is denied. In-memory fakes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver.lease import Lease
from leviathan.silver.publisher import (
    FailurePoint,
    ManifestState,
    PublishStrategy,
    PublisherError,
    RunManifest,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
    build_lease_for,
)
from leviathan.silver.partition_publish import RepairAuthorization

from tests.unit.silver.conftest import (
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

BUCKET = "leviathan-test"
ROOT = "s3://leviathan-test/silver/production/source=usda_esr"
FLAT_ROOT = "s3://leviathan-test/silver/fred_fx"


def _reg_table_sd():
    return {
        "Columns": [{"Name": "commodity_name", "Type": "string"}],
        "Location": ROOT,
        "InputFormat": "if", "OutputFormat": "of",
        "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {}},
        "Parameters": {},
    }


def _obj(key="silver/fred_fx/part-000.parquet", rows=10, values=None, metrics=None):
    return StagedObject(canonical_key=key, body=b"PAR1data" + key.encode(),
                        partition_values=values, row_count=rows, null_metrics=metrics)


# --------------------------------------------------------------------------- manifest state machine
def test_manifest_legal_full_path():
    m = RunManifest(run_id="r", job="j", table="t", database="d", publish_mode="canonical",
                    strategy="flat")
    for st in (ManifestState.DISCOVERED, ManifestState.STAGED, ManifestState.VALIDATED,
               ManifestState.PUBLISHED, ManifestState.CATALOGED, ManifestState.CERTIFIED):
        m.advance(st)
    assert m.state is ManifestState.CERTIFIED
    assert len(m.transitions) == 6


def test_manifest_illegal_transition_rejected():
    m = RunManifest(run_id="r", job="j", table="t", database="d", publish_mode="c", strategy="flat")
    with pytest.raises(PublisherError):
        m.advance(ManifestState.PUBLISHED)  # skipped DISCOVERED/STAGED/VALIDATED


def test_manifest_fail_from_any_state_then_terminal():
    m = RunManifest(run_id="r", job="j", table="t", database="d", publish_mode="c", strategy="flat")
    m.advance(ManifestState.DISCOVERED)
    m.fail("boom")
    assert m.state is ManifestState.FAILED
    with pytest.raises(PublisherError):
        m.advance(ManifestState.STAGED)


# --------------------------------------------------------------------------- dry-run / shadow
def test_dryrun_writes_nothing(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_fred_fx", database="leviathan_test", bucket=BUCKET,
                          canonical_root=FLAT_ROOT, auth=dryrun_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.FLAT, manifest_store=lambda k, b: None)
    m = pub.run([_obj()])
    assert m.state is ManifestState.VALIDATED       # stops before touching canonical
    assert fake_s3.store == {}                        # nothing written anywhere
    assert m.outputs == []


def test_shadow_stages_to_shadow_prefix_only(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_fred_fx", database="leviathan_test", bucket=BUCKET,
                          canonical_root=FLAT_ROOT, auth=shadow_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.FLAT, shadow_prefix="silver/_shadow/fred_fx",
                          manifest_store=lambda k, b: None)
    m = pub.run([_obj()])
    assert m.state is ManifestState.VALIDATED
    keys = fake_s3.keys()
    # object landed under the shadow prefix, and the CANONICAL key is NOT present.
    assert any(k.startswith("silver/_shadow/fred_fx/") for k in keys)
    assert "silver/fred_fx/part-000.parquet" not in keys


# --------------------------------------------------------------------------- canonical happy path
def test_canonical_flat_promote_and_certify(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_fred_fx", database="leviathan_test", bucket=BUCKET,
                          canonical_root=FLAT_ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.FLAT, manifest_store=lambda k, b: None)
    m = pub.run([_obj()])
    assert m.state is ManifestState.CERTIFIED
    assert "silver/fred_fx/part-000.parquet" in fake_s3.keys()   # promoted to canonical
    assert len(m.outputs) == 1


def test_canonical_registered_catalogs_partition(fake_s3, fake_glue):
    fake_glue.tables["silver_esr"] = {"Name": "silver_esr", "StorageDescriptor": _reg_table_sd()}
    key = "silver/production/source=usda_esr/commodity_code=101/market_year=2000/as_of=20260524/part.parquet"
    obj = StagedObject(canonical_key=key, body=b"PAR1x", partition_values=["101", "2000", "20260524"],
                       row_count=5)
    pub = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                          canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                          manifest_store=lambda k, b: None)
    m = pub.run([obj])
    assert m.state is ManifestState.CERTIFIED
    assert ("silver_esr", ("101", "2000", "20260524")) in fake_glue.partitions


# --------------------------------------------------------------------------- validation gate
def test_validation_failure_blocks_promotion(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_fred_fx", database="leviathan_test", bucket=BUCKET,
                          canonical_root=FLAT_ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.FLAT, validation=ValidationHooks(min_rows=100),
                          manifest_store=lambda k, b: None)
    with pytest.raises(PublisherError):
        pub.run([_obj(rows=1)])
    assert pub.manifest.state is ManifestState.FAILED
    # nothing promoted to canonical.
    assert "silver/fred_fx/part-000.parquet" not in fake_s3.keys()


def test_value_nonnull_hook_v001_style(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_chirps", database="leviathan_test", bucket=BUCKET,
                          canonical_root="s3://leviathan-test/silver/chirps", auth=canonical_authorization(),
                          s3_client=fake_s3, strategy=PublishStrategy.FLAT,
                          validation=ValidationHooks(min_nonnull_frac=0.5),
                          manifest_store=lambda k, b: None)
    with pytest.raises(PublisherError):
        pub.run([_obj(key="silver/chirps/part.parquet", metrics={"value": 0.0})])  # all-NaN -> fail
    assert pub.manifest.state is ManifestState.FAILED


# --------------------------------------------------------------------------- failure injection
@pytest.mark.parametrize("point", [
    FailurePoint.BEFORE_OBJECT_WRITE, FailurePoint.AFTER_OBJECT_WRITE, FailurePoint.BEFORE_CATALOG,
])
def test_failure_before_catalog_leaves_no_registered_partition(fake_s3, fake_glue, point):
    """A failure at or before the catalog step never registers the partition -- so unvalidated /
    unpublished data is never made query-visible through Glue, and the manifest is FAILED."""
    fake_glue.tables["silver_esr"] = {"Name": "silver_esr", "StorageDescriptor": _reg_table_sd()}
    key = "silver/production/source=usda_esr/commodity_code=101/market_year=2000/as_of=20260524/part.parquet"
    obj = StagedObject(canonical_key=key, body=b"PAR1x",
                       partition_values=["101", "2000", "20260524"], row_count=5)
    pub = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                          canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                          inject_failure=point, manifest_store=lambda k, b: None)
    with pytest.raises(PublisherError):
        pub.run([obj])
    assert pub.manifest.state is ManifestState.FAILED
    assert ("silver_esr", ("101", "2000", "20260524")) not in fake_glue.partitions


def test_failure_after_catalog_is_consistent_and_idempotent_on_rerun(fake_s3, fake_glue):
    """A failure AFTER the catalog step (only the final CERTIFY transition is lost) leaves a
    CONSISTENT state: the new partition is registered pointing at the promoted, validated object. The
    manifest is FAILED, and an identical re-run is an idempotent no-op (existing), never a corruption."""
    fake_glue.tables["silver_esr"] = {"Name": "silver_esr", "StorageDescriptor": _reg_table_sd()}
    key = "silver/production/source=usda_esr/commodity_code=101/market_year=2000/as_of=20260524/part.parquet"
    obj = StagedObject(canonical_key=key, body=b"PAR1x",
                       partition_values=["101", "2000", "20260524"], row_count=5)
    pub = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                          canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                          inject_failure=FailurePoint.AFTER_CATALOG, manifest_store=lambda k, b: None)
    with pytest.raises(PublisherError):
        pub.run([obj])
    assert pub.manifest.state is ManifestState.FAILED
    part = fake_glue.partitions[("silver_esr", ("101", "2000", "20260524"))]
    assert part["StorageDescriptor"]["Location"].endswith("/as_of=20260524/")  # consistent pointer
    # re-run without the injected failure -> idempotent existing, certifies.
    obj2 = StagedObject(canonical_key=key, body=b"PAR1x",
                        partition_values=["101", "2000", "20260524"], row_count=5)
    pub2 = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                           canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                           glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                           manifest_store=lambda k, b: None)
    m2 = pub2.run([obj2])
    assert m2.state is ManifestState.CERTIFIED
    assert m2.partition_actions[0]["outcome"] == "existing"


def test_manifest_persisted_even_on_failure(fake_s3):
    saved = {}
    pub = ShadowPublisher(job="j", table="silver_fred_fx", database="leviathan_test", bucket=BUCKET,
                          canonical_root=FLAT_ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.FLAT, inject_failure=FailurePoint.BEFORE_OBJECT_WRITE,
                          manifest_store=lambda k, b: saved.update({k: b}))
    with pytest.raises(PublisherError):
        pub.run([_obj()])
    assert saved  # manifest written despite the failure
    assert b'"state": "FAILED"' in next(iter(saved.values()))


# --------------------------------------------------------------------------- identical rerun
def test_identical_rerun_is_identical_replacement(fake_s3, fake_glue):
    fake_glue.tables["silver_esr"] = {"Name": "silver_esr", "StorageDescriptor": _reg_table_sd()}
    key = "silver/production/source=usda_esr/commodity_code=101/market_year=2000/as_of=20260524/part.parquet"

    def _run():
        obj = StagedObject(canonical_key=key, body=b"PAR1x",
                           partition_values=["101", "2000", "20260524"], row_count=5)
        p = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                            canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                            glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                            manifest_store=lambda k, b: None)
        return p.run([obj])

    m1 = _run()
    m2 = _run()  # second identical run: partition already registered at the SAME location -> existing
    assert m1.state is ManifestState.CERTIFIED and m2.state is ManifestState.CERTIFIED
    actions = m2.partition_actions
    assert actions and actions[0]["outcome"] == "existing"


# --------------------------------------------------------------------------- lease fencing
def test_stale_lease_cannot_promote(fake_s3, fake_glue):
    fake_glue.tables["silver_esr"] = {"Name": "silver_esr", "StorageDescriptor": _reg_table_sd()}
    base = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    lease = build_lease_for("silver_esr", [["101", "2000", "20260524"]], BUCKET, "silver/", fake_s3,
                            owner="op-a", run_id="r1", ttl_seconds=100)
    granted = lease.acquire(now=base)
    thief = build_lease_for("silver_esr", [["101", "2000", "20260524"]], BUCKET, "silver/", fake_s3,
                            owner="op-b", run_id="r2", ttl_seconds=100)
    thief.acquire(now=base + timedelta(seconds=200))  # steals; op-a fenced out
    key = "silver/production/source=usda_esr/commodity_code=101/market_year=2000/as_of=20260524/part.parquet"
    obj = StagedObject(canonical_key=key, body=b"PAR1x", partition_values=["101", "2000", "20260524"],
                       row_count=5)
    pub = ShadowPublisher(job="j", table="silver_esr", database="leviathan_test", bucket=BUCKET,
                          canonical_root=ROOT, auth=canonical_authorization(), s3_client=fake_s3,
                          glue_client=fake_glue, strategy=PublishStrategy.REGISTERED,
                          lease=lease, fencing_token=granted.fencing_token,
                          manifest_store=lambda k, b: None)
    with pytest.raises(PublisherError):
        pub.run([obj])  # promote's _fence() recheck raises LeaseLost
    assert ("silver_esr", ("101", "2000", "20260524")) not in fake_glue.partitions


# --------------------------------------------------------------------------- END-TO-END guard denial
def test_canonical_publish_without_approval_denied_end_to_end(fake_s3, monkeypatch):
    """A canonical publish attempted through the REAL publish_guard, with the true prod environment
    but no signed approval, is denied before any write -- proving the publisher cannot mint canonical
    data without the approval artifact."""
    from leviathan.common import publish_guard as PG

    # Build a target that matches the real prod environment on every field EXCEPT it carries no
    # approval -> authorize_publish must raise ApprovalError (never returns may_mutate_canonical).
    target = PG.PublishTarget(
        account_id=PG.PROD_ACCOUNT_ID, bucket="leviathan-dev-shahem-001", database="leviathan_dev",
        prefix="silver/production/source=usda_esr/",
        role_arn=f"arn:aws:iam::{PG.PROD_ACCOUNT_ID}:role/leviathan-dev-silver-publisher",
        table="silver_esr",
    )
    with pytest.raises(PG.ApprovalError):
        PG.authorize_publish(target, argv=["--publish-mode", "canonical"], env={})
    # And with a readiness identity it is denied even earlier (ReadinessPublishDenied).
    with pytest.raises(PG.ReadinessPublishDenied):
        PG.authorize_publish(target, argv=["--publish-mode", "canonical"],
                             env={PG.ENV_READINESS: "1"})


# --------------------------------------------------------------- shadow placement (BF-W1 rehearsal find)
WEATHER_ROOT = "s3://leviathan-test/silver/weather/source=chirps"


def test_shadow_key_stays_outside_partition_locations(fake_s3):
    # Per-directory shadow put staged objects INSIDE the future registered-partition
    # locations (commodity=<c>/year=<y>/_shadow/...), which the feature extractor's raw
    # year= LIST would double-read after promote. Shadow must stage at the TABLE root.
    pub = ShadowPublisher(job="j", table="silver_chirps", database="leviathan_test", bucket=BUCKET,
                          canonical_root=WEATHER_ROOT, auth=shadow_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.REGISTERED, manifest_store=lambda k, b: None)
    canonical = "silver/weather/source=chirps/commodity=cocoa/year=1981/part-000.parquet"
    shadow = pub._shadow_key(canonical)
    assert shadow == "silver/weather/source=chirps/_shadow/commodity=cocoa/year=1981/part-000.parquet"
    # the year= segment must come AFTER the _shadow marker, never before it
    assert shadow.index("/_shadow/") < shadow.index("year=")


def test_shadow_run_never_writes_inside_year_dirs(fake_s3):
    pub = ShadowPublisher(job="j", table="silver_chirps", database="leviathan_test", bucket=BUCKET,
                          canonical_root=WEATHER_ROOT, auth=shadow_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.REGISTERED, manifest_store=lambda k, b: None)
    key = "silver/weather/source=chirps/commodity=cocoa/year=1981/part-000.parquet"
    m = pub.run([StagedObject(canonical_key=key, body=b"PAR1x", partition_values=["cocoa", "1981"],
                              row_count=3)])
    assert m.state is ManifestState.VALIDATED
    for written in fake_s3.keys():
        if "year=" in written:
            # anything under a year= dir must not be shadow scrap
            assert "/_shadow/" not in written.split("year=", 1)[1], written


def test_manifest_key_is_a_bucket_key_not_a_url(fake_s3):
    seen = {}
    pub = ShadowPublisher(job="j", table="silver_chirps", database="leviathan_test", bucket=BUCKET,
                          canonical_root=WEATHER_ROOT, auth=dryrun_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.REGISTERED,
                          manifest_store=lambda k, b: seen.setdefault("key", k))
    pub.run([_obj(key="silver/weather/source=chirps/commodity=cocoa/year=1981/part-000.parquet",
                  values=["cocoa", "1981"])])
    # the URL form once minted literal "s3://<bucket>/..." OBJECT KEYS in the bucket
    assert seen["key"].startswith("silver/weather/source=chirps/_manifests/")
    assert not seen["key"].startswith("s3:")


def test_plain_key_canonical_root_unchanged(fake_s3):
    # canonical_root given as a plain key prefix (no scheme) must behave identically
    pub = ShadowPublisher(job="j", table="silver_chirps", database="leviathan_test", bucket=BUCKET,
                          canonical_root="silver/weather/source=chirps",
                          auth=shadow_authorization(), s3_client=fake_s3,
                          strategy=PublishStrategy.REGISTERED, manifest_store=lambda k, b: None)
    shadow = pub._shadow_key("silver/weather/source=chirps/commodity=cocoa/year=2020/part-000.parquet")
    assert shadow == "silver/weather/source=chirps/_shadow/commodity=cocoa/year=2020/part-000.parquet"


def test_validation_hooks_floor_override_calibrates_one_column():
    # OP-8 (BF-W3 cotton): the override floor applies to its column only; others keep the base.
    hooks = ValidationHooks(min_nonnull_frac=0.5, floor_overrides={"sparse": 0.25})
    ok_obj = _obj(metrics={"sparse": 0.296, "dense": 1.0})
    assert hooks.run(ok_obj) == []
    # below even the calibrated floor still fails, and the message names the effective floor.
    bad = hooks.run(_obj(metrics={"sparse": 0.1, "dense": 1.0}))
    assert len(bad) == 1 and "sparse" in bad[0] and "0.25" in bad[0]
    # a non-overridden column keeps the base 0.5.
    bad2 = hooks.run(_obj(metrics={"sparse": 0.296, "dense": 0.4}))
    assert len(bad2) == 1 and "dense" in bad2[0]
