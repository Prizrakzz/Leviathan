"""Unit tests for the A-W3 [Reconcile] task (jobs/audit/advance_rolling_census).

Nothing here touches boto3/network, the live pg mirror, Athena, or a real census run: the census entry
point (_run_census) and the S3 client (_s3_client) are both stubbed. Covers the plan requirements:
  * upload happens ONLY on a clean census (rc == 0), to the right bucket/key with the census bytes;
  * a nonzero census rc PROPAGATES (fail closed) and NEVER uploads (a dirty census is not enshrined);
  * a raised census (env assert / pg outage / firewall trip) fails closed, no upload;
  * a full-ISO --asof is truncated to the date ([:10]) before the census runs;
  * a malformed dest-uri and an S3 upload error both fail closed;
  * ASCII-only stdout.
"""
from __future__ import annotations

import json

import pytest

from jobs.audit import advance_rolling_census as r


# --- a tiny boto3-S3 stand-in (put_object only) -----------------------------------------------------------
class _FakeS3:
    """Records put_object calls; optionally raises to simulate an S3 failure."""

    def __init__(self, exc=None):
        self._exc = exc
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803 -- boto3 kwarg names
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        if self._exc is not None:
            raise self._exc
        return {"ETag": '"stub"'}


_CENSUS = {"as_of_date": "2026-02-15", "legs": [], "banner": {"athena_calls": 0, "dark": 0}}

_URI = "s3://leviathan-dev-shahem-001/cascade_census/rolling/fx_macro_daily/census.json"


def _stub_census(rc=0, payload=_CENSUS, write=True):
    """Return a _run_census stand-in that (optionally) writes `payload` to out_path and returns `rc`."""
    def _fn(asof, out_path):
        _fn.seen_asof = asof
        if write:
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        return rc
    _fn.seen_asof = None
    return _fn


# ---------------------------------------------------------------------------
# (1) clean census (rc 0) -> uploads the census bytes to the right bucket/key
# ---------------------------------------------------------------------------
def test_upload_happens_on_rc0(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(r, "_s3_client", lambda: fake)
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=0))

    rc = r.reconcile("2026-02-15", _URI)

    assert rc == 0
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["Bucket"] == "leviathan-dev-shahem-001"
    assert put["Key"] == "cascade_census/rolling/fx_macro_daily/census.json"
    assert json.loads(put["Body"].decode("utf-8")) == _CENSUS   # the census bytes, verbatim
    assert put["ContentType"] == "application/json"


# ---------------------------------------------------------------------------
# (2) nonzero census rc PROPAGATES and NEVER uploads (fail closed)
# ---------------------------------------------------------------------------
def test_nonzero_census_rc_propagates_and_never_uploads(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(r, "_s3_client", lambda: fake)
    # census wrote a (dirty) artifact but returned rc=1 -- must NOT be rolled forward.
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=1))

    rc = r.reconcile("2026-02-15", _URI)

    assert rc == 1
    assert fake.puts == []          # dirty census is never enshrined as the baseline


def test_nonzero_census_rc_is_preserved(monkeypatch):
    monkeypatch.setattr(r, "_s3_client", lambda: _FakeS3())
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=3))
    assert r.reconcile("2026-02-15", _URI) == 3


# ---------------------------------------------------------------------------
# (3) a raised census fails closed (env assert / pg outage / Athena trip), no upload
# ---------------------------------------------------------------------------
def test_census_exception_fails_closed_no_upload(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(r, "_s3_client", lambda: fake)

    def _boom(asof, out_path):
        raise AssertionError("cascade_census requires EVIDENCE_PG_DSN")

    monkeypatch.setattr(r, "_run_census", _boom)

    rc = r.reconcile("2026-02-15", _URI)
    assert rc == 1
    assert fake.puts == []


def test_clean_rc_but_missing_artifact_fails_closed(monkeypatch):
    """Defensive: census claimed rc==0 but wrote no file -> fail closed, no upload."""
    fake = _FakeS3()
    monkeypatch.setattr(r, "_s3_client", lambda: fake)
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=0, write=False))

    rc = r.reconcile("2026-02-15", _URI)
    assert rc == 1
    assert fake.puts == []


# ---------------------------------------------------------------------------
# (4) full-ISO --asof is truncated to the date before the census runs
# ---------------------------------------------------------------------------
def test_iso_asof_truncated_to_date(monkeypatch):
    stub = _stub_census(rc=0)
    monkeypatch.setattr(r, "_run_census", stub)
    monkeypatch.setattr(r, "_s3_client", lambda: _FakeS3())

    rc = r.reconcile("2026-07-16T09:00:00Z", _URI)   # scheduler scheduled-time shape
    assert rc == 0
    assert stub.seen_asof == "2026-07-16"            # census saw the truncated date, not the timestamp


# ---------------------------------------------------------------------------
# (5) fail-closed dest / upload
# ---------------------------------------------------------------------------
def test_bad_dest_uri_fails_closed_before_census(monkeypatch):
    """A non-s3 dest fails closed BEFORE a census run is spent (and never uploads)."""
    ran = {"census": False}

    def _should_not_run(asof, out_path):
        ran["census"] = True
        return 0

    monkeypatch.setattr(r, "_run_census", _should_not_run)
    monkeypatch.setattr(r, "_s3_client",
                        lambda: (_ for _ in ()).throw(AssertionError("no S3 for a bad URI")))

    rc = r.reconcile("2026-02-15", "https://not-s3/census.json")
    assert rc == 1
    assert ran["census"] is False


def test_dest_uri_missing_key_fails_closed(monkeypatch):
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=0))
    monkeypatch.setattr(r, "_s3_client", lambda: _FakeS3())
    assert r.reconcile("2026-02-15", "s3://bucket-only") == 1


def test_upload_error_fails_closed(monkeypatch):
    fake = _FakeS3(exc=RuntimeError("AccessDenied: not authorized to PutObject"))
    monkeypatch.setattr(r, "_s3_client", lambda: fake)
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=0))

    rc = r.reconcile("2026-02-15", _URI)
    assert rc == 1
    assert len(fake.puts) == 1      # it was attempted, then failed closed


# ---------------------------------------------------------------------------
# (6) main() arg wiring + ASCII stdout
# ---------------------------------------------------------------------------
def test_main_threads_args_to_reconcile(monkeypatch):
    seen = {}

    def _capture(asof, dest_uri):
        seen["asof"] = asof
        seen["dest_uri"] = dest_uri
        return 0

    monkeypatch.setattr(r, "reconcile", _capture)
    rc = r.main(["--asof", "2026-07-16T00:00:00Z", "--dest-uri", _URI])
    assert rc == 0
    assert seen == {"asof": "2026-07-16T00:00:00Z", "dest_uri": _URI}   # main passes through raw; reconcile truncates


def test_main_requires_both_args(monkeypatch):
    with pytest.raises(SystemExit):
        r.main(["--asof", "2026-02-15"])          # missing --dest-uri
    with pytest.raises(SystemExit):
        r.main(["--dest-uri", _URI])              # missing --asof


def test_ok_and_fail_output_is_ascii(monkeypatch, capsys):
    monkeypatch.setattr(r, "_s3_client", lambda: _FakeS3())
    monkeypatch.setattr(r, "_run_census", _stub_census(rc=0))
    r.reconcile("2026-02-15", _URI)
    ok = capsys.readouterr().out
    assert "advance_rolling_census OK" in ok and ok.isascii()

    monkeypatch.setattr(r, "_run_census", _stub_census(rc=1))
    r.reconcile("2026-02-15", _URI)
    fail = capsys.readouterr().out
    assert "FAIL advance_rolling_census" in fail and fail.isascii()
