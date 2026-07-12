"""Shared pytest fixtures for the Leviathan unit test suite.

SILVER-F002 -- structural AWS test-isolation guard
==================================================
The suite is isolated *by convention* (per-author ``@mock_aws`` + fake buckets),
not structurally.  A future test that news up a real ``boto3.client`` against the
literal production bucket ``leviathan-dev-shahem-001`` / database ``leviathan_dev``
and calls ``put_object`` / ``start_query_execution`` would hit prod -- the $134
LIST-storm class had no tripwire in the harness.

This module installs a **default-deny** guard that FAILS CLOSED on any *real*
(un-mocked) AWS network call:

* An autouse fixture sets fake AWS credentials + ``AWS_EC2_METADATA_DISABLED`` for
  every non-integration test, and records whether the test carries the
  ``integration`` marker.
* ``botocore.httpsession.URLLib3Session.send`` -- the actual wire send -- is
  patched to consult the guard.  ``moto`` / ``@mock_aws`` short-circuit inside
  botocore's ``before-send`` event (verified against moto 5.2.1), so the real
  ``send`` is **never reached** under moto and the guard never fires for mocked
  tests.  It fires only when a test would truly hit the network.
* A real send is permitted ONLY when the test carries ``@pytest.mark.integration``
  AND the request targets an allowlisted TEST bucket/database.  The literal
  production names are denied UNCONDITIONALLY -- an integration test may never
  touch prod.

"Network disabled" is approximated structurally: the guard raises *before*
``URLLib3Session.send`` runs, so no socket is opened for a blocked call.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import botocore.httpsession
import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# SILVER-F002: default-deny AWS network guard
# ---------------------------------------------------------------------------

# Literal PRODUCTION surfaces -- denied for EVERY test, integration included.
PROD_NAMES = frozenset(
    {
        "leviathan-dev-shahem-001",  # prod S3 bucket (appears throughout src/ + submit scripts)
        "leviathan_dev",             # prod Glue / Athena database
    }
)

# Allowlisted TEST surfaces a *marked* integration test may reach on a real wire.
# Unit tests use moto and never reach this guard; this list exists only for the
# future, separately-approved integration role.  Extend it there, never with a
# prod name.
ALLOWLIST_NAMES = frozenset(
    {
        "test-leviathan",                 # moto bucket used across the current suite
        "leviathan-test",
        "leviathan-integration-test",
        "leviathan_test",                 # test database
        "leviathan_integration_test",
    }
)


class RealAWSCallBlocked(AssertionError):
    """Raised when the suite attempts a real (un-mocked) AWS network call.

    Subclasses ``AssertionError`` so it reports as a plain test failure and is
    never swallowed by botocore's retry policy.
    """


# Per-test state, set by the autouse fixture.  pytest runs serially in one
# process (xdist uses separate processes, each with its own copy), so a plain
# module dict is safe.
_STATE = {"allow_real": False, "node_id": None}
_ORIG_SEND = None
_INSTALLED = False


def _request_text(request) -> str:
    """URL + headers + decoded body as one searchable string.

    ``request.body`` may be a streaming/file-like object (e.g. botocore's
    ``AwsChunkedWrapper`` for S3 uploads), which is NOT subscriptable -- only
    inspect it when it is bytes/str, otherwise fall back to the URL (which
    carries the bucket for both virtual-hosted and path-style S3).  Headers are
    included so a prod name riding in a header (e.g. S3 CopySource's
    ``x-amz-copy-source``) also trips the tripwire.
    """
    url = getattr(request, "url", "") or ""
    body = getattr(request, "body", None)
    if isinstance(body, (bytes, bytearray)):
        body_s = bytes(body).decode("utf-8", "replace")
    elif isinstance(body, str):
        body_s = body
    else:
        body_s = ""
    try:
        headers_s = "\n".join(f"{k}: {v}" for k, v in dict(getattr(request, "headers", {}) or {}).items())
    except Exception:
        headers_s = ""
    return "\n".join((url, headers_s, body_s))


def _decide(text: str, allow_real: bool, node_id=None) -> None:
    """Pure decision core -- raises RealAWSCallBlocked, or returns None if allowed."""
    # 1. Production surfaces are denied unconditionally.
    for name in PROD_NAMES:
        if name in text:
            raise RealAWSCallBlocked(
                f"PROD AWS surface '{name}' targeted by a real call (test={node_id}). "
                f"Mock it (@mock_aws / patch the client). F002 default-deny; prod is "
                f"never a valid test target."
            )
    # 2. Default-deny: unit tests never make real calls.
    if not allow_real:
        raise RealAWSCallBlocked(
            f"Real (un-mocked) AWS call blocked (test={node_id}). Unit tests must mock "
            f"AWS (@mock_aws / patch boto3.client). To make a real call to an allowlisted "
            f"test resource, mark the test @pytest.mark.integration."
        )
    # 3. Integration path: the target must be an explicit allowlisted test resource.
    if not any(name in text for name in ALLOWLIST_NAMES):
        raise RealAWSCallBlocked(
            f"Integration AWS call to a non-allowlisted target (test={node_id}). "
            f"Add the test bucket/database to ALLOWLIST_NAMES in tests/conftest.py."
        )
    return None


def _guard_send(self, request):
    _decide(_request_text(request), _STATE["allow_real"], _STATE["node_id"])
    return _ORIG_SEND(self, request)  # allowed integration call -> real wire


def _install_guard() -> None:
    global _ORIG_SEND, _INSTALLED
    if _INSTALLED:
        return
    _ORIG_SEND = botocore.httpsession.URLLib3Session.send
    botocore.httpsession.URLLib3Session.send = _guard_send
    _INSTALLED = True


def _uninstall_guard() -> None:
    global _INSTALLED
    if _INSTALLED and _ORIG_SEND is not None:
        botocore.httpsession.URLLib3Session.send = _ORIG_SEND
    _INSTALLED = False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: test may make a REAL AWS call to an allowlisted test resource "
        "(needs the separately-approved integration role; never prod).",
    )
    _install_guard()


def pytest_unconfigure(config: pytest.Config) -> None:
    _uninstall_guard()


@pytest.fixture(autouse=True)
def _aws_isolation(request, monkeypatch):
    """Autouse: fake creds + metadata-off for unit tests; record integration state.

    Integration-marked tests keep the ambient environment (the CI integration
    role supplies real creds) and are permitted real calls to allowlisted targets.
    """
    is_integration = request.node.get_closest_marker("integration") is not None
    if not is_integration:
        # Deterministic fake static creds so botocore never resolves a real
        # profile or reaches IMDS.  monkeypatch auto-restores after the test.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
        monkeypatch.delenv("AWS_PROFILE", raising=False)
    _STATE["allow_real"] = is_integration
    _STATE["node_id"] = request.node.nodeid
    try:
        yield
    finally:
        _STATE["allow_real"] = False
        _STATE["node_id"] = None


@pytest.fixture()
def aws_guard():
    """Accessor to the F002 guard internals for the isolation regression tests.

    Exposed as a fixture so tests never depend on the (import-mode-fragile)
    ``tests`` package path.
    """
    return SimpleNamespace(
        RealAWSCallBlocked=RealAWSCallBlocked,
        PROD_NAMES=PROD_NAMES,
        ALLOWLIST_NAMES=ALLOWLIST_NAMES,
        decide=_decide,
        request_text=_request_text,
        set_state=lambda allow_real, node_id=None: _STATE.update(
            allow_real=allow_real, node_id=node_id
        ),
        state=_STATE,
    )


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def nasa_power_payload() -> dict:
    """Minimal valid NASA POWER API payload with all 7 required parameters × 3 dates."""
    return json.loads((FIXTURES_DIR / "nasa_power_payload.json").read_text())


@pytest.fixture()
def faostat_bronze_df() -> pd.DataFrame:
    """Bronze FAOSTAT DataFrame as produced by transform_faostat_qcl_zip_to_bronze().

    Represents cocoa production data for Ghana, 2020, with all three FAO elements.
    """
    return pd.DataFrame(
        {
            "area": ["Ghana", "Ghana", "Ghana"],
            "item": ["Cocoa beans", "Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Area harvested", "Yield"],
            "year": [2020, 2020, 2020],
            "unit": ["tonnes", "ha", "hg/ha"],
            "value": [900_000.0, 1_800_000.0, 5_000.0],
            "flag": ["A", "A", ""],
            "ingest_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
        }
    )


@pytest.fixture()
def weather_bronze_wide_df() -> pd.DataFrame:
    """Bronze NASA POWER DataFrame as produced by nasa_power_payload_to_daily_dataframe().

    Wide format with lowercased raw parameter names, 3 rows.
    """
    return pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "year": [2020, 2020, 2020],
            "month": [1, 1, 1],
            "day": [1, 2, 3],
            "source": ["nasa_power", "nasa_power", "nasa_power"],
            "commodity": ["cocoa", "cocoa", "cocoa"],
            "country": ["ghana", "ghana", "ghana"],
            "region": ["gh_main", "gh_main", "gh_main"],
            "ingest_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
            "source_file_name": ["sample.json", "sample.json", "sample.json"],
            "t2m": [25.5, 26.1, 24.8],
            "t2m_max": [30.2, 31.0, 29.5],
            "t2m_min": [20.1, 21.3, 19.8],
            "prectotcorr": [2.5, 0.0, 1.1],
            "rh2m": [75.0, 72.0, 78.0],
            "ws2m": [2.1, 1.8, 2.5],
            "allsky_sfc_sw_dwn": [18.5, 20.1, 15.3],
        }
    )
