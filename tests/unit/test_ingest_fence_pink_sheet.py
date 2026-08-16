"""D-SG G2-1(c) -- World Bank Pink Sheet release-recency fence.

The release label is scraped from whatever ``CMO-Pink-Sheet-<Month>-<Year>.pdf``
href the commodity-markets page happens to show at fire time. The schedule fired
on the 4th while the WB publishes "around the first Tuesday", so in any month
where the WB posts later the fire re-downloaded the PRIOR month's workbook into
the SAME ``release=`` key, bronze skipped it, and the chain exited 0 having
landed nothing (2026-08-04: release=2026M07, raw/bronze still {2026M05, 2026M07}).

Month-1 is LEGAL and must stay green. Month-2 is the failure the fence exists for.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from jobs.ingest import fetch_world_bank_pink_sheet as fetcher
from leviathan.common.ingest_fence import bronze_is_current

BUCKET = "test-leviathan"
_RAW = "raw/production/source=world_bank_pink_sheet"
_BRONZE = "bronze/production/source=world_bank_pink_sheet"

_PAGE_TEMPLATE = (
    '<html><body>'
    '<a href="https://thedocs.worldbank.org/en/doc/abc-0050012026/related/'
    'CMO-Historical-Data-Monthly.xlsx">workbook</a>'
    '<a href="https://thedocs.worldbank.org/en/doc/abc-0050012026/related/'
    'CMO-Pink-Sheet-{month}-{year}.pdf">pink sheet</a>'
    '</body></html>'
)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, page_html: str):
        self.headers: dict[str, str] = {}
        self._page_html = page_html

    def update(self, _mapping):  # pragma: no cover -- headers.update shim
        return None

    def get(self, _url, **_kwargs):
        return _FakeResponse(self._page_html)


def _run_fetch(monkeypatch, *, month: str, year: str, argv: list[str]):
    """Drive main() as far as the fence; --dry-run stops before any S3/network write."""
    html = _PAGE_TEMPLATE.format(month=month, year=year)
    monkeypatch.setattr(fetcher.requests, "Session", lambda: _FakeSession(html))
    monkeypatch.setattr(sys, "argv", ["fetch_world_bank_pink_sheet.py", "--dry-run", *argv])
    fetcher.main()


# ---------------------------------------------------------------------------
# the fence
# ---------------------------------------------------------------------------

def test_month_minus_one_is_legal(monkeypatch, capsys):
    """THE EXACT 2026-08-04 CASE -- a legal month-1 lag must not go red."""
    _run_fetch(monkeypatch, month="July", year="2026", argv=["--asof", "2026-08-04"])
    assert "2026M07" in capsys.readouterr().out


def test_month_minus_two_fails(monkeypatch):
    """THE PREDICTED 2026-09-04 FAILURE."""
    with pytest.raises(SystemExit) as exc:
        _run_fetch(monkeypatch, month="July", year="2026", argv=["--asof", "2026-09-04"])

    msg = str(exc.value)
    assert msg.startswith("ZERO-ADVANCE")
    assert "2026M07" in msg


def test_same_month_is_legal(monkeypatch, capsys):
    _run_fetch(monkeypatch, month="August", year="2026", argv=["--asof", "2026-08-16"])
    assert "2026M08" in capsys.readouterr().out


def test_no_advance_fence_flag_stands_down(monkeypatch, capsys):
    _run_fetch(
        monkeypatch,
        month="July",
        year="2026",
        argv=["--asof", "2026-09-04", "--no-advance-fence"],
    )
    assert "2026M07" in capsys.readouterr().out


def test_year_boundary_lag_is_measured_in_months(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_fetch(monkeypatch, month="November", year="2026", argv=["--asof", "2027-01-08"])
    assert str(exc.value).startswith("ZERO-ADVANCE")


# ---------------------------------------------------------------------------
# release parsing -- the input the fence trusts
# ---------------------------------------------------------------------------

def test_parse_release_ym_from_page():
    html = _PAGE_TEMPLATE.format(month="July", year="2026")
    assert fetcher._parse_release_ym_from_page(html) == "2026M07"


def test_parse_release_ym_returns_none_without_a_pdf_href():
    """No PDF href -> None, which main() turns into the current-calendar-month fallback.

    Pinned because that fallback is silent: a page-structure change would mint a
    release label out of the clock and the fence would see lag=0 forever.
    """
    assert fetcher._parse_release_ym_from_page("<html><body>no pdf here</body></html>") is None


# ---------------------------------------------------------------------------
# the bronze fence, against the pink sheet key shape
# ---------------------------------------------------------------------------

def _raw_key(release: str) -> str:
    return f"{_RAW}/release={release}/CMO-Historical-Data-Monthly.xlsx"


def _bronze_key(release: str) -> str:
    return f"{_BRONZE}/release={release}/part-000.parquet"


class _StubS3:
    def __init__(self, mtimes):
        self._mtimes = mtimes

    def head_object(self, Bucket: str, Key: str):  # noqa: N803 -- boto3 kwarg names
        if Key not in self._mtimes:
            raise KeyError(Key)
        return {"LastModified": self._mtimes[Key]}


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_stale_bronze_rebuilt():
    """A bare fetch OVERWRITES the same release key, so raw outruns bronze every fire."""
    s3 = _StubS3(
        {
            _bronze_key("2026M07"): _utc("2026-08-04T16:02:00"),
            _raw_key("2026M07"): _utc("2026-09-04T16:01:00"),
        }
    )
    assert bronze_is_current(s3, BUCKET, _raw_key("2026M07"), _bronze_key("2026M07")) is False


def test_current_bronze_skipped():
    s3 = _StubS3(
        {
            _raw_key("2026M05"): _utc("2026-05-06T16:00:00"),
            _bronze_key("2026M05"): _utc("2026-05-06T16:01:00"),
        }
    )
    assert bronze_is_current(s3, BUCKET, _raw_key("2026M05"), _bronze_key("2026M05")) is True


@mock_aws
def test_missing_bronze_rebuilds():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=_raw_key("2026M08"), Body=b"xlsx")

    assert bronze_is_current(s3, BUCKET, _raw_key("2026M08"), _bronze_key("2026M08")) is False
