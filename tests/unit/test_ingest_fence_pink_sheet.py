"""D-SG G2-1(c) -- World Bank Pink Sheet release-recency fence.

The schedule fired on the 4th while the WB publishes "around the first Tuesday", so in any month
where the WB posts later the fire re-downloaded the PRIOR month's workbook into the SAME ``release=``
key, bronze skipped it, and the chain exited 0 having landed nothing (2026-08-04: release=2026M07,
raw/bronze still {2026M05, 2026M07}).

Month-1 is LEGAL and must stay green. Month-2 is the failure the fence exists for. Both properties
are unchanged.

RE-ANCHORED 2026-09-03 (PINK SHEET VINTAGES lane (a)) -- THE FENCE MOVED, IT DID NOT LOOSEN
-------------------------------------------------------------------------------------------
The fence used to key on the PAGE LABEL and run ABOVE the download, so a ``--dry-run`` reached it
and these tests could drive it with a page and no workbook. It now keys on the month the WORKBOOK
DERIVES and runs BELOW the download, because the label measured PAGE FRESHNESS rather than ADVANCE:
a correctly-advancing workbook behind a stale label went hard-RED, and a stale workbook behind a
fresh label passed. A ``--dry-run`` therefore no longer reaches the fence at all -- it cannot, since
the fence's subject is a property of bytes a dry run does not fetch.

So every fence test below now drives the LIVE path with the network and S3 doubled, and the month it
names is the month the WORKBOOK derives. The fence is STRICTER than it was (it also refuses a
FUTURE derived month), and two properties are pinned here that the old shape could not express: the
stale-label case that used to go red now LANDS, and the dry run says out loud that it has not
derived a key.
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timezone

import boto3
import pytest
from leviathan.common import pink_sheet_release as psr
from leviathan.common.ingest_fence import bronze_is_current
from moto import mock_aws

from jobs.ingest import fetch_world_bank_pink_sheet as fetcher

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
    def __init__(self, text: str = "", content: bytes = b"", headers=None):
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class _FakeSession:
    """Serves the page for the entry URL and the WORKBOOK for the .xlsx URL, and records both."""

    def __init__(self, page_html: str, workbook: bytes):
        self.headers: dict[str, str] = {}
        self._page_html = page_html
        self._workbook = workbook
        self.gets: list[str] = []

    def update(self, _mapping):  # pragma: no cover -- headers.update shim
        return None

    def get(self, url, **_kwargs):
        self.gets.append(url)
        if str(url).endswith(".xlsx"):
            return _FakeResponse(content=self._workbook,
                                 headers={"Content-Length": str(len(self._workbook))})
        return _FakeResponse(text=self._page_html)


def _workbook(release: str) -> bytes:
    """A REAL xlsx whose last monthly row derives *release* -- the fence's actual subject now."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = psr.SHEET_NAME
    sheet.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    sheet.append(["Updated as of: whatever"])
    sheet.append([None])
    sheet.append([None])
    sheet.append(["Month", "Soybean oil"])
    for i, month in enumerate(psr.expected_months(release)):
        sheet.append([month, 900.0 + i])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _run_fetch(monkeypatch, *, month: str, year: str, argv: list[str],
               derives: str | None = None, dry_run: bool = False):
    """Drive main() through the fence.

    *month*/*year* set the PAGE LABEL (a log field now); *derives* sets the month the WORKBOOK's own
    last row implies, which is what the fence measures. They default to the same month so the
    existing cases read exactly as they did.
    """
    html = _PAGE_TEMPLATE.format(month=month, year=year)
    if derives is None:
        derives = "%sM%02d" % (year, datetime.strptime(month, "%B").month)
    session = _FakeSession(html, _workbook(derives))
    monkeypatch.setattr(fetcher.requests, "Session", lambda: session)
    monkeypatch.setattr(fetcher, "load_env", lambda: None)
    monkeypatch.setattr(fetcher, "get_required_env",
                        lambda n: {"LEVIATHAN_BUCKET": "b", "AWS_REGION": "r"}[n])
    monkeypatch.setattr(fetcher, "s3_object_exists", lambda *a, **k: False)
    landed: dict[str, bytes] = {}
    monkeypatch.setattr(fetcher, "upload_bytes_to_s3",
                        lambda data, bucket, key, region: landed.__setitem__(key, data))
    monkeypatch.setattr(fetcher, "write_raw_s3_metadata", lambda *a, **k: None)
    # The 500 KB MIN_RAW_FILE_SIZES floor is real in production; a synthetic 800-row workbook is
    # ~16 KB and padding one would test the padding. Nothing here is about file size.
    monkeypatch.setattr(fetcher, "check_min_file_size", lambda *a, **k: None)
    argv = ["fetch_world_bank_pink_sheet.py", *(["--dry-run"] if dry_run else []), *argv]
    monkeypatch.setattr(sys, "argv", argv)
    fetcher.main()
    return session, landed


# ---------------------------------------------------------------------------
# the fence -- now on the DERIVED month, below the download
# ---------------------------------------------------------------------------

def test_month_minus_one_is_legal(monkeypatch):
    """THE EXACT 2026-08-04 CASE -- a legal month-1 lag must not go red."""
    _session, landed = _run_fetch(monkeypatch, month="July", year="2026",
                                  argv=["--asof", "2026-08-04"])
    assert [k for k in landed if "release=2026M07/" in k]


def test_month_minus_two_fails(monkeypatch):
    """THE PREDICTED 2026-09-04 FAILURE."""
    with pytest.raises(SystemExit) as exc:
        _run_fetch(monkeypatch, month="July", year="2026", argv=["--asof", "2026-09-04"])

    msg = str(exc.value)
    assert msg.startswith("ZERO-ADVANCE")
    assert "2026M07" in msg


def test_same_month_is_legal(monkeypatch):
    _session, landed = _run_fetch(monkeypatch, month="August", year="2026",
                                  argv=["--asof", "2026-08-16"])
    assert [k for k in landed if "release=2026M08/" in k]


def test_no_advance_fence_flag_stands_down(monkeypatch):
    _session, landed = _run_fetch(
        monkeypatch,
        month="July",
        year="2026",
        argv=["--asof", "2026-09-04", "--no-advance-fence"],
    )
    assert [k for k in landed if "release=2026M07/" in k]


def test_year_boundary_lag_is_measured_in_months(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_fetch(monkeypatch, month="November", year="2026", argv=["--asof", "2027-01-08"])
    assert str(exc.value).startswith("ZERO-ADVANCE")


def test_the_fence_now_measures_ADVANCE_not_PAGE_FRESHNESS(monkeypatch):
    """THE CASE THE OLD SHAPE COULD NOT EXPRESS, and the reason the fence moved.

    The page still advertises July while the workbook already holds data through August, i.e. it
    DERIVES 2026M09 -- a perfectly current release behind a stale label. Under the old label-keyed
    fence this went hard-RED at a 2026-09-08 asof (lag 2 on the label). It must now LAND, under the
    DERIVED month."""
    _session, landed = _run_fetch(monkeypatch, month="July", year="2026", derives="2026M09",
                                  argv=["--asof", "2026-09-08"])
    assert [k for k in landed if "release=2026M09/" in k]
    assert not [k for k in landed if "release=2026M07/" in k]


def test_a_FUTURE_derived_month_is_its_own_refusal(monkeypatch):
    """A workbook cannot have been published after the moment it was fetched. Not expressible on
    the label either -- a label is whatever the page says."""
    with pytest.raises(SystemExit, match="FUTURE RELEASE"):
        _run_fetch(monkeypatch, month="August", year="2026", derives="2026M11",
                   argv=["--asof", "2026-09-08"])


def test_the_dry_run_no_longer_reaches_the_fence_AND_SAYS_SO(monkeypatch, capsys):
    """The honest consequence of moving the fence below the download: a dry run cannot judge
    advance, cannot know the release month, and must not print an S3 key it has not derived."""
    session, landed = _run_fetch(monkeypatch, month="July", year="2026", derives="2026M09",
                                 argv=["--asof", "2026-09-04"], dry_run=True)
    out = capsys.readouterr().out
    assert [u for u in session.gets if u.endswith(".xlsx")] == [], "a dry run must not download"
    assert landed == {}
    assert "Page label : 2026M07" in out
    assert "--dry-run does not download" in out
    assert "release=" not in out


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
