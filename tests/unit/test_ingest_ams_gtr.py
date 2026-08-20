"""Unit tests for jobs/ingest/fetch_ams_gtr.py -- network-free.

Every HTTP call is monkeypatched to serve the pinned fixtures captured live on
2026-08-20.  Nothing here reaches the network or AWS.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ams_gtr"

from leviathan.transforms.raw_to_bronze.ams_gtr import GTR_DATASETS, get_dataset  # noqa: E402


def _load_module():
    """Import the fetcher by path -- jobs/ are scripts, not an installed package."""
    path = REPO_ROOT / "jobs" / "ingest" / "fetch_ams_gtr.py"
    spec = importlib.util.spec_from_file_location("fetch_ams_gtr", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_ams_gtr"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gtr():
    return _load_module()


def _fixture_for(url: str) -> bytes:
    """Serve the pinned capture that corresponds to *url*."""
    if url.endswith("GTRTable1.xlsx"):
        return (FIXTURES / "GTRTable1.xlsx").read_bytes()
    if "/api/views/" in url:
        dataset_id = url.rsplit("/", 1)[-1].removesuffix(".json")
        return (FIXTURES / f"meta_{dataset_id}.json").read_bytes()
    dataset_id = url.split("/resource/", 1)[1].split(".json", 1)[0]
    return (FIXTURES / f"soda_{dataset_id}.json").read_bytes()


@pytest.fixture
def offline(gtr, monkeypatch):
    """Replace the module's only network seam with the fixtures."""
    calls: list[str] = []

    def fake_get(_session, url: str) -> bytes:
        calls.append(url)
        return _fixture_for(url)

    monkeypatch.setattr(gtr, "_get", fake_get)
    monkeypatch.setattr(gtr.time, "sleep", lambda _s: None)
    return calls


# ---------------------------------------------------------------------------
# The user agent -- the estate's standing rule, pinned
# ---------------------------------------------------------------------------

def test_no_fake_browser_user_agent_is_sent(gtr):
    """Measured 2026-08-20: ams.usda.gov answers 200 to a short honest token and to
    python-requests' default; only the long parenthetical-with-contact shape drew a
    403.  There is no access problem here that a browser string would solve, so
    claiming to be Chrome would be evasion rather than access.
    """
    assert "Mozilla" not in gtr._UA
    assert "Chrome" not in gtr._UA
    assert "Safari" not in gtr._UA
    assert "AppleWebKit" not in gtr._UA
    assert gtr._UA == "leviathan-gtr/1.0"
    # The shape that DID draw the 403 must not creep back in.
    assert "(" not in gtr._UA and "@" not in gtr._UA


def test_session_sends_the_honest_token(gtr):
    assert gtr._session().headers["User-Agent"] == gtr._UA


def test_requests_are_sequential_and_polite(gtr):
    assert gtr._SLEEP >= 1.0, "government servers, not CDNs"
    # No thread pool anywhere in the producer.
    source = (REPO_ROOT / "jobs" / "ingest" / "fetch_ams_gtr.py").read_text(encoding="utf-8")
    assert "ThreadPool" not in source
    assert "concurrent.futures" not in source


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def test_dry_run_prints_every_key_and_makes_no_call(gtr, monkeypatch, capsys):
    def explode(*_a, **_k):  # pragma: no cover - the point is that it never runs
        raise AssertionError("dry-run must not touch the network")

    monkeypatch.setattr(gtr, "_get", explode)
    gtr.run(
        datasets=sorted(GTR_DATASETS),
        mode="weekly",
        as_of_date="20260820",
        bucket="BUCKET",
        region="us-east-1",
        skip_existing=False,
        dry_run=True,
    )
    printed = capsys.readouterr().out.splitlines()

    # One key per SODA payload + one per SODA metadata sidecar + the spreadsheet.
    soda = [s for s in GTR_DATASETS.values() if s.channel == "soda"]
    assert len(printed) == 2 * len(soda) + 1
    assert all(line.startswith("[dry-run] s3://BUCKET/") for line in printed)
    assert any("dataset=ocean_weekly/as_of=20260820/GTRTable1.xlsx" in s for s in printed)
    assert any("dataset=barge_per_ton/as_of=20260820/meta.json" in s for s in printed)


def test_backfill_mode_uses_the_static_prefix(gtr, capsys):
    gtr.run(
        datasets=["ukraine_ocean_quarterly"],
        mode="backfill",
        as_of_date="20260820",
        bucket="BUCKET",
        region="us-east-1",
        skip_existing=False,
        dry_run=True,
    )
    printed = capsys.readouterr().out
    assert "dataset=ukraine_ocean_quarterly/backfill/full.json" in printed
    assert "as_of=" not in printed


# ---------------------------------------------------------------------------
# Fetch + validate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dataset", [s for s, spec in GTR_DATASETS.items() if spec.channel == "soda"]
)
def test_soda_fetch_captures_rows_and_the_publishers_metadata(gtr, offline, dataset):
    payloads = gtr._fetch_dataset(gtr._session(), dataset, "20260820")
    names = [name for name, _b, _u, _c in payloads]
    assert names == ["full.json", "meta.json"]

    # The metadata is requested BEFORE the rows: the unit is asserted before any
    # number is accepted, not after it has been written.
    assert "/api/views/" in offline[0]
    assert "/resource/" in offline[1]

    rows_bytes = payloads[0][1]
    assert isinstance(json.loads(rows_bytes), list)
    # Single-page pulls keep the publisher's exact bytes.
    assert rows_bytes == _fixture_for(gtr.soda_resource_url(dataset))


def test_xlsx_fetch_needs_no_metadata_sidecar(gtr, offline):
    payloads = gtr._fetch_dataset(gtr._session(), "ocean_weekly", "20260820")
    assert [name for name, *_ in payloads] == ["GTRTable1.xlsx"]
    assert payloads[0][3].endswith("spreadsheetml.sheet")


def test_a_drifted_unit_declaration_stops_the_dataset_before_any_row_lands(
    gtr, monkeypatch
):
    meta = json.loads((FIXTURES / "meta_deqi-uken.json").read_bytes())
    for column in meta["columns"]:
        column["description"] = "rate, unit unspecified"
    restated = json.dumps(meta).encode()

    def fake_get(_session, url: str) -> bytes:
        if "/api/views/" in url:
            return restated
        raise AssertionError("rows must not be fetched once the unit has drifted")

    monkeypatch.setattr(gtr, "_get", fake_get)
    with pytest.raises(ValueError, match="no longer declares"):
        gtr._fetch_dataset(gtr._session(), "barge_pct_tariff", "20260820")


def test_an_html_error_page_served_as_200_is_refused(gtr, monkeypatch):
    monkeypatch.setattr(
        gtr, "_get", lambda _s, _u: b"<!DOCTYPE html><html>Service Unavailable</html>"
    )
    with pytest.raises(RuntimeError, match="not a ZIP/xlsx container"):
        gtr._fetch_dataset(gtr._session(), "ocean_weekly", "20260820")


def test_validation_parses_rather_than_measuring_bytes(gtr):
    """A byte floor cannot tell a thin week from an error page, and this estate has
    already been bitten by a floor refusing legitimately thin data.  Parsing is the
    stronger check, so the producer runs the real transform before uploading."""
    source = (REPO_ROOT / "jobs" / "ingest" / "fetch_ams_gtr.py").read_text(encoding="utf-8")
    assert "_MIN_SIZE_BYTES" not in source
    assert "transform_gtr_soda_json_to_bronze" in source
    assert "transform_gtr_ocean_weekly_xlsx_to_bronze" in source


def test_an_empty_soda_payload_is_never_accepted(gtr, monkeypatch):
    def fake_get(_session, url: str) -> bytes:
        if "/api/views/" in url:
            return (FIXTURES / "meta_deqi-uken.json").read_bytes()
        return b"[]"

    monkeypatch.setattr(gtr, "_get", fake_get)
    monkeypatch.setattr(gtr.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="zero rows"):
        gtr._fetch_dataset(gtr._session(), "barge_pct_tariff", "20260820")


def test_paging_stops_on_a_short_page_and_orders_deterministically(gtr, offline):
    gtr._fetch_soda_rows(gtr._session(), "barge_pct_tariff")
    row_calls = [u for u in offline if "/resource/" in u]
    assert len(row_calls) == 1, "a 40-row fixture is a short page -- one request only"
    assert "%24order=%3Aid" in row_calls[0] or "$order=:id" in row_calls[0]
    assert "%24limit=50000" in row_calls[0] or "$limit=50000" in row_calls[0]


def test_a_full_page_triggers_a_second_request(gtr, monkeypatch):
    """The loop exists so a growing dataset is not silently truncated at the cap."""
    monkeypatch.setattr(gtr, "_SODA_PAGE", 2)
    monkeypatch.setattr(gtr.time, "sleep", lambda _s: None)
    records = json.loads((FIXTURES / "soda_deqi-uken.json").read_bytes())
    served: list[str] = []

    def fake_get(_session, url: str) -> bytes:
        served.append(url)
        offset = int(url.split("offset=")[1].split("&")[0])
        return json.dumps(records[offset:offset + 2]).encode()

    monkeypatch.setattr(gtr, "_get", fake_get)
    merged = json.loads(gtr._fetch_soda_rows(gtr._session(), "barge_pct_tariff"))
    assert merged == records
    assert len(served) == len(records) // 2 + 1


# ---------------------------------------------------------------------------
# Metadata that travels with the bytes
# ---------------------------------------------------------------------------

def test_raw_metadata_carries_the_licence_unit_and_attribution(gtr, offline, monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(gtr, "upload_bytes_to_s3", lambda *a, **k: None)
    monkeypatch.setattr(gtr, "s3_object_exists", lambda *a, **k: False)
    monkeypatch.setattr(
        gtr, "write_raw_s3_metadata",
        lambda bucket, key, data, url, ctype, region, extra=None: written.append(
            {"key": key, "extra": extra}
        ),
    )

    gtr.run(
        datasets=["ocean_monthly"],
        mode="weekly",
        as_of_date="20260820",
        bucket="BUCKET",
        region="us-east-1",
        skip_existing=False,
        dry_run=False,
    )

    assert len(written) == 2  # rows + metadata sidecar
    extra = written[0]["extra"]
    assert "non-copyrighted" in extra["license"]
    assert extra["attribution"] == get_dataset("ocean_monthly").attribution
    assert "O'Neil" in extra["attribution"], "the vendor credit travels with the bytes"
    assert extra["unit"] == "USD_per_metric_ton"
    assert extra["cadence"] == "monthly"


def test_skip_existing_avoids_the_network_entirely(gtr, monkeypatch):
    monkeypatch.setattr(gtr, "s3_object_exists", lambda *a, **k: True)
    monkeypatch.setattr(
        gtr, "_get",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not fetch an existing key")),
    )
    gtr.run(
        datasets=sorted(GTR_DATASETS),
        mode="weekly",
        as_of_date="20260820",
        bucket="BUCKET",
        region="us-east-1",
        skip_existing=True,
        dry_run=False,
    )


def test_a_failed_dataset_fails_the_run(gtr, monkeypatch):
    monkeypatch.setattr(gtr, "s3_object_exists", lambda *a, **k: False)
    monkeypatch.setattr(gtr, "upload_bytes_to_s3", lambda *a, **k: None)
    monkeypatch.setattr(gtr, "write_raw_s3_metadata", lambda *a, **k: None)
    monkeypatch.setattr(gtr.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        gtr, "_get", lambda *a: (_ for _ in ()).throw(RuntimeError("upstream 503"))
    )
    with pytest.raises(SystemExit, match="1 dataset\\(s\\) failed"):
        gtr.run(
            datasets=["ocean_weekly"],
            mode="weekly",
            as_of_date="20260820",
            bucket="BUCKET",
            region="us-east-1",
            skip_existing=False,
            dry_run=False,
        )
