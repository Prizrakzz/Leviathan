"""Regression tests for the SILVER-F002 AWS test-isolation guard (tests/conftest.py).

Proves the harness FAILS CLOSED on any real (un-mocked) AWS call and, critically,
that ``moto`` / ``@mock_aws`` still work underneath the guard.  None of these
tests open a socket: the end-to-end cases raise *before* the wire send, and the
decision cases exercise the pure core directly.
"""
from __future__ import annotations

import boto3
import botocore.httpsession
import pytest
from moto import mock_aws

REGION = "us-east-1"
PROD_BUCKET = "leviathan-dev-shahem-001"
PROD_DB = "leviathan_dev"


# ---------------------------------------------------------------------------
# End-to-end: a real client hitting prod / any un-mocked target fails closed
# (the guard raises before URLLib3Session.send, so no network is touched).
# ---------------------------------------------------------------------------


def test_prod_bucket_read_fails_closed(aws_guard):
    """A synthetic test that news up a real S3 client against the prod bucket
    is stopped before the wire -- the $134 LIST-storm class."""
    s3 = boto3.client("s3", region_name=REGION)
    with pytest.raises(aws_guard.RealAWSCallBlocked, match=PROD_BUCKET):
        s3.list_objects_v2(Bucket=PROD_BUCKET, Prefix="silver/")


def test_prod_bucket_write_fails_closed(aws_guard):
    s3 = boto3.client("s3", region_name=REGION)
    with pytest.raises(aws_guard.RealAWSCallBlocked, match=PROD_BUCKET):
        s3.put_object(Bucket=PROD_BUCKET, Key="silver/partition/x.parquet", Body=b"data")


def test_glue_write_to_prod_db_fails_closed(aws_guard):
    """The historical live-partition pollution class: a real Glue partition
    mutation against leviathan_dev cannot reach the catalog."""
    glue = boto3.client("glue", region_name=REGION)
    with pytest.raises(aws_guard.RealAWSCallBlocked, match=PROD_DB):
        glue.create_partition(
            DatabaseName=PROD_DB,
            TableName="silver_esr",
            PartitionInput={"Values": ["2026-07-12"]},
        )


def test_athena_start_query_against_prod_fails_closed(aws_guard):
    """start_query_execution is the exact LIST-storm trigger; it must fail closed."""
    ath = boto3.client("athena", region_name=REGION)
    with pytest.raises(aws_guard.RealAWSCallBlocked):
        ath.start_query_execution(
            QueryString="SELECT * FROM silver_esr",
            QueryExecutionContext={"Database": PROD_DB},
            ResultConfiguration={"OutputLocation": f"s3://{PROD_BUCKET}/athena/"},
        )


def test_default_deny_even_for_nonprod_target(aws_guard):
    """Default-deny: a real call to a NON-prod, non-allowlisted bucket also fails
    closed (fail-closed does not depend on recognising a prod name)."""
    s3 = boto3.client("s3", region_name=REGION)
    with pytest.raises(aws_guard.RealAWSCallBlocked):
        s3.list_objects_v2(Bucket="some-unknown-scratch-bucket-xyz")


# ---------------------------------------------------------------------------
# moto coexistence -- the load-bearing compatibility guarantee
# ---------------------------------------------------------------------------


@mock_aws
def test_moto_still_works_under_the_guard():
    """@mock_aws short-circuits inside botocore's before-send, so the guard's
    patched send is never reached and mocked tests run normally."""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="test-leviathan")
    s3.put_object(Bucket="test-leviathan", Key="k", Body=b"hello")
    body = s3.get_object(Bucket="test-leviathan", Key="k")["Body"].read()
    assert body == b"hello"
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="test-leviathan").get("Contents", [])]
    assert keys == ["k"]


def test_guard_is_installed():
    """Meta-check: the send patch is actually active during the run."""
    assert botocore.httpsession.URLLib3Session.send.__name__ == "_guard_send"


# ---------------------------------------------------------------------------
# Pure decision core -- exercises the integration/allowlist branches without
# any client or network.
# ---------------------------------------------------------------------------


def test_decide_denies_unit_call_by_default(aws_guard):
    with pytest.raises(aws_guard.RealAWSCallBlocked):
        aws_guard.decide("https://leviathan-test.s3.amazonaws.com/k", allow_real=False)


def test_decide_allows_integration_allowlisted_target(aws_guard):
    # allow_real=True (integration marker) + allowlisted bucket -> permitted.
    assert (
        aws_guard.decide(
            "https://leviathan-test.s3.amazonaws.com/k", allow_real=True, node_id="itg"
        )
        is None
    )


def test_decide_denies_prod_even_with_integration_marker(aws_guard):
    """Prod is denied UNCONDITIONALLY, marker or not."""
    body = '{"DatabaseName": "leviathan_dev", "TableName": "silver_esr"}'
    with pytest.raises(aws_guard.RealAWSCallBlocked, match="leviathan_dev"):
        aws_guard.decide(
            "https://glue.us-east-1.amazonaws.com/\n" + body, allow_real=True
        )


def test_decide_denies_integration_call_to_nonallowlisted_target(aws_guard):
    with pytest.raises(aws_guard.RealAWSCallBlocked):
        aws_guard.decide(
            "https://random-bucket.s3.amazonaws.com/k", allow_real=True
        )


def test_prod_db_matches_in_json_body(aws_guard):
    """The db name arrives in the request body for Glue/Athena (JSON protocol);
    the guard scans body, not just URL."""
    text = 'https://athena.us-east-1.amazonaws.com/\n{"Database":"leviathan_dev"}'
    with pytest.raises(aws_guard.RealAWSCallBlocked, match="leviathan_dev"):
        aws_guard.decide(text, allow_real=False)


# ---------------------------------------------------------------------------
# request_text robustness -- a streaming body must not crash the guard
# (botocore wraps S3 upload bodies in a non-subscriptable AwsChunkedWrapper).
# ---------------------------------------------------------------------------


def test_request_text_handles_streaming_body(aws_guard):
    class _NotSubscriptable:
        def __getitem__(self, k):  # pragma: no cover - must never be called
            raise TypeError("streaming body is not subscriptable")

    req = type(
        "R",
        (),
        {"url": "https://leviathan-test.s3.amazonaws.com/k", "body": _NotSubscriptable()},
    )()
    text = aws_guard.request_text(req)
    assert text.startswith("https://leviathan-test.s3.amazonaws.com/k")


def test_request_text_reads_bytes_body(aws_guard):
    req = type("R", (), {"url": "https://x/", "body": b'{"Database":"leviathan_dev"}'})()
    assert "leviathan_dev" in aws_guard.request_text(req)
