"""MINAGRO wayback history backfill. Hermetic: no network, no AWS, no browser.

The CDX fixture below is the REAL index response for the ministry's standing export slug, measured
2026-08-20 (32 rows: 16 x 200, 12 x 403, 3 x 301, 1 x 520). It is kept verbatim -- including the
five 2024-08-12 rows that share one digest, the archived Cloudflare interstitials, and the redirect
rows -- because every one of those shapes is a filtering decision this job has to make, and a
hand-cleaned fixture would test only the cases someone already thought of.

What these tests exist to pin is the class of failure that lands a WRONG WEEK rather than an error:

  * a capture whose body is a Cloudflare challenge or a redesign must be SKIPPED and COUNTED, never
    landed -- raw is immutable and an interstitial under an ``as_of=`` key is indistinguishable
    from the real table forever after;
  * the as-of key comes from the PAGE's own 'станом на' date, never from the capture timestamp;
  * FIRST CAPTURE WINS: two digests carrying the same as-of are the CMS re-publishing one release,
    and the earlier capture keeps the key -- so today's live 2026-08-14 capture can never be
    overwritten by an archived re-render;
  * a page whose own as-of LEADS its capture instant is not the page that was crawled.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests" / "fixtures" / "minagro" / "grain_exports_page_20260814.html"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("jobs/ingest/backfill_minagro_wayback.py", "backfill_minagro_wayback")


# ---------------------------------------------------------------------------
# The measured CDX response, verbatim (2026-08-20)
# ---------------------------------------------------------------------------

CDX_FIELDS = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]
_URLKEY = "ua,gov,minagro)/napryamki/eksport-do-krain-ies/eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna"
_ORIGINAL = (
    "https://minagro.gov.ua/napryamki/eksport-do-krain-ies/"
    "eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna"
)

_MEASURED_ROWS = [
    ("20240305120831", "200", "VEG4XHDZPTMMZHACLLN2NORAHJXNOPJV", "9835", "text/html"),
    ("20240316092944", "200", "EAWOTVD27USVGUO7DE34UTPXI3HUSTFR", "9561", "text/html"),
    ("20240319052419", "200", "HRHAL5P74ERZIZNN45BN346WE5N7C3FB", "7930", "text/html"),
    ("20240402081423", "301", "3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ", "733", "unk"),
    ("20240404230459", "200", "HCHZYXVPFFOEX5GFC32O2IIM62TVRZGJ", "9178", "text/html"),
    ("20240508153016", "403", "36TQXGA3VY4OW4YCWOJUKW2US6IIGLYX", "8743", "text/html"),
    ("20240530031807", "200", "MAQQTJABCIVVWVBVFJLP2UO7B2IRTTEK", "9302", "text/html"),
    ("20240614140932", "403", "CDTRPF7RV77BM4RBUYCBIQJUCY7PHZH6", "7936", "text/html"),
    ("20240625132710", "403", "VRMMVLSISKM5Q7NQ7OGW3AXIBOAZ4W37", "7938", "text/html"),
    ("20240711031650", "301", "OQ3OBNFR7DBCFQ4ANGEQW5P2FOXZZJRA", "425", "text/html"),
    # ONE page state, crawled five times inside four hours -- one digest, and therefore one fetch.
    ("20240812123829", "200", "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM", "9259", "text/html"),
    ("20240812123903", "200", "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM", "9259", "text/html"),
    ("20240812132646", "200", "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM", "9261", "text/html"),
    ("20240812140702", "200", "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM", "9256", "text/html"),
    ("20240812162323", "200", "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM", "9255", "text/html"),
    ("20240828102118", "200", "W7O4EK6MPMSDCFFX2EE6TAGBL2OJQDFQ", "9687", "text/html"),
    ("20240829175310", "301", "OM6ALWQTEGJ5NTY5RYSC2EXCKJOAHOVU", "849", "text/html"),
    ("20240927135253", "200", "SUHDGAK6TTPNBNYOBKB67HH3ZPZGM2XK", "9329", "text/html"),
    ("20241111104500", "200", "BJTTZPGZQJPNWWMC2ZPZ67JBZKC2SH5Z", "9410", "text/html"),
    ("20241125192248", "200", "2ZVH62ZZBVOC5IFOXZXLAMKW4QNR2L5Q", "9443", "text/html"),
    ("20241214114928", "403", "2SKBE2X4VYLW6LZQZASRHDMZTPFL4VR4", "7042", "text/html"),
    ("20241216073109", "403", "2GSSUWHGXLCRQ7DLXZOKCZORA7CVKEPE", "7458", "text/html"),
    ("20250105081959", "520", "ZCMIEDBLWSEAQT7VLEI5X4F4E32H776B", "2934", "text/html"),
    ("20250131140944", "200", "47MLYPYECQ4LHTXWBIV4O23B3CUMNIQV", "9437", "text/html"),
    ("20250214194541", "403", "LBHQFZRTWM6XMDNEPBFYPKVRV23LQGNN", "7043", "text/html"),
    ("20250528030818", "200", "ACRTTX4HUH4RIY6SE3SKUKXS55SXMUR4", "9940", "text/html"),
    ("20251001114741", "403", "DPKID3NKSLAJRPBU6KLCB7SDLKIXNH42", "6893", "text/html"),
    ("20251004224025", "403", "C357YA6QGX43NXWVKAZQDGO6ZTHUU6EG", "6486", "text/html"),
    ("20251108074454", "403", "K2GZKC26RGIYHXUFQZ4ZTBOJFQMAF2OS", "6538", "text/html"),
    ("20251202124539", "403", "COWABNNRKMREJ6IEFXOFWFC3RH7XDH6M", "6902", "text/html"),
    ("20260430131537", "403", "AMR7K6ZWK72C7O2GVE4CX6AXDWMX6BWA", "4826", "text/html"),
    ("20260525024552", "403", "GZFWUSPEA7RVEDUZ6KULUXXCPNCAZVRK", "4624", "text/html"),
]

# The number of DISTINCT page states behind those 16 successes -- the fetch budget, and the whole
# reason a re-crawl of an unchanged page must not cost a request.
_DISTINCT_200_DIGESTS = 12


def cdx_payload() -> list[list[str]]:
    """The CDX JSON body shape: a HEADER ROW followed by data rows (not objects)."""
    return [CDX_FIELDS] + [
        [_URLKEY, ts, _ORIGINAL, mime, status, digest, length]
        for ts, status, digest, length, mime in _MEASURED_ROWS
    ]


def page() -> str:
    """The real 2026-08-14 ``<main>`` capture -- the one shape a landed object ever has."""
    return _FIXTURE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CDX row filtering + dedupe
# ---------------------------------------------------------------------------

def test_parse_cdx_zips_the_header_row_onto_the_data_rows():
    rows = B.parse_cdx_rows(json.dumps(cdx_payload()))
    assert len(rows) == len(_MEASURED_ROWS)
    assert rows[0]["timestamp"] == "20240305120831"
    assert rows[0]["digest"] == "VEG4XHDZPTMMZHACLLN2NORAHJXNOPJV"
    assert rows[0]["statuscode"] == "200"


def test_parse_cdx_reads_an_empty_index_as_an_answer_not_an_error():
    # "the archive holds nothing" is a finding the caller must be able to report, not a crash.
    assert B.parse_cdx_rows("[]") == []
    assert B.parse_cdx_rows(json.dumps([CDX_FIELDS])) == []


def test_select_keeps_only_200s_and_one_per_digest():
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    assert len(caps) == _DISTINCT_200_DIGESTS
    assert {c["statuscode"] for c in caps} == {"200"}
    assert len({c["digest"] for c in caps}) == _DISTINCT_200_DIGESTS


def test_select_drops_the_archived_cloudflare_interstitials_and_redirects():
    """The 403s ARE archived, with 200-shaped bodies of their own. They are not the table."""
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    kept = {c["timestamp"] for c in caps}
    for ts, status, *_ in _MEASURED_ROWS:
        if status != "200":
            assert ts not in kept, f"{ts} is a {status} and must never become a replay request"


def test_select_collapses_the_five_2024_08_12_crawls_to_the_earliest():
    """Five crawls, one digest, ONE fetch -- and the EARLIEST is the closest witness."""
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    same = [c for c in caps if c["digest"] == "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM"]
    assert len(same) == 1
    assert same[0]["timestamp"] == "20240812123829"


def test_select_returns_captures_in_timestamp_order():
    """Order is load-bearing: first-capture-wins depends on the incumbent being the earlier one."""
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    stamps = [c["timestamp"] for c in caps]
    assert stamps == sorted(stamps)
    assert stamps[0] == "20240305120831"
    assert stamps[-1] == "20250528030818"


def test_select_refuses_an_unpinnable_timestamp():
    """A row that cannot be pinned must never become a replay request -- that IS the CEPEA defect."""
    rows = [{"timestamp": "2024", "statuscode": "200", "digest": "X", "original": _ORIGINAL}]
    assert B.select_captures(rows) == []


def test_select_refuses_a_row_with_no_digest():
    rows = [{"timestamp": "20240305120831", "statuscode": "200", "digest": "",
             "original": _ORIGINAL}]
    assert B.select_captures(rows) == []


def test_replay_url_is_the_raw_body_form():
    """``id_`` serves the STORED body: no wayback banner, no rewritten links inside the markup."""
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    url = caps[0]["replay_url"]
    assert url.startswith("https://web.archive.org/web/20240305120831id_/")
    assert url.endswith("eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna")


# ---------------------------------------------------------------------------
# The capture-drift law -- a wayback timestamp is a REQUEST, not a guarantee
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, url: str, memento: str | None = None):
        self.url = url
        self.headers = {"Memento-Datetime": memento} if memento else {}


def test_verify_accepts_the_pinned_capture():
    pin = {"timestamp": "20240530031807"}
    served = B.served_capture_ts(
        _Resp("https://web.archive.org/web/20240530031807id_/" + _ORIGINAL))
    assert B.verify_capture(pin, b"x" * 60_000, served) is None


def test_verify_refuses_a_nearest_capture_redirect():
    """The whole law in one test: an unmatched timestamp 200s with the NEAREST capture."""
    pin = {"timestamp": "20250301000000"}
    served = B.served_capture_ts(
        _Resp("https://web.archive.org/web/20250131140944id_/" + _ORIGINAL))
    reason = B.verify_capture(pin, b"x" * 60_000, served)
    assert reason and "20250131140944" in reason and "20250301000000" in reason


def test_verify_refuses_a_response_that_names_no_capture_at_all():
    assert B.verify_capture({"timestamp": "20240530031807"}, b"x" * 60_000, None)


def test_verify_refuses_the_not_archived_placeholder():
    """Wayback serves its placeholder with HTTP 200; the status code is not the presence test."""
    pin = {"timestamp": "20240530031807"}
    served = B.served_capture_ts(
        _Resp("https://web.archive.org/web/20240530031807id_/" + _ORIGINAL))
    reason = B.verify_capture(pin, b"<html>not archived</html>", served)
    assert reason and "placeholder" in reason


# ---------------------------------------------------------------------------
# The challenge / non-table skip path
# ---------------------------------------------------------------------------

CHALLENGE_BODY = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><main><div class='cf-browser-verification'>Checking your browser before accessing "
    "minagro.gov.ua. This process is automatic.</div></main></body></html>"
)


def test_a_challenge_body_is_refused_by_the_producers_own_sniff():
    """The gate is the TRANSFORM's, not a second opinion -- raw and bronze cannot disagree."""
    from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (
        looks_like_the_export_table,
    )
    main_html = B.extract_main(CHALLENGE_BODY)
    assert main_html is not None, "the challenge page does have a <main>; the SNIFF is the gate"
    assert looks_like_the_export_table(main_html) is not None


def test_the_real_capture_passes_the_same_sniff():
    from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (
        looks_like_the_export_table,
    )
    assert looks_like_the_export_table(page()) is None


def test_extract_main_refuses_a_page_with_no_main_element():
    """None, not a whole-page fallback: a second undeclared object shape in an immutable layer is
    worse than a capture the report names as skipped."""
    assert B.extract_main("<html><body><table><tr><td>x</td></tr></table></body></html>") is None


def test_extract_main_cuts_main_out_of_the_surrounding_page_chrome():
    archived = (
        "<html><body><header>NAV NAV NAV</header>"
        "<main><h1>tbl</h1><table><tr><td>1</td></tr></table></main>"
        "<footer>FOOT</footer></body></html>"
    )
    main_html = B.extract_main(archived)
    assert main_html.startswith("<main>") and main_html.endswith("</main>")
    assert "NAV" not in main_html and "FOOT" not in main_html


# ---------------------------------------------------------------------------
# The as-of key: derived from the PAGE, cross-checked against the capture instant
# ---------------------------------------------------------------------------

def test_as_of_comes_from_the_page_not_from_the_capture_timestamp():
    """The capture is 2026-08-19; the page says 2026-08-14; the key is the PAGE's date."""
    as_of = B.as_of_for_capture({"timestamp": "20260819120000"}, page())
    assert as_of == dt.date(2026, 8, 14)


def test_as_of_key_is_the_familys_normal_raw_key():
    from leviathan.storage.paths import raw_minagro_grain_exports_key
    as_of = B.as_of_for_capture({"timestamp": "20260819120000"}, page())
    assert raw_minagro_grain_exports_key(as_of.isoformat()) == (
        "raw/production/source=minagro_grain_exports/as_of=20260814/page.html"
    )


def test_an_as_of_that_leads_its_capture_is_refused():
    """Customs figures cannot be dated after the crawl that archived them -- these bytes are not
    the capture they claim to be."""
    with pytest.raises(ValueError, match="AFTER the crawl"):
        B.as_of_for_capture({"timestamp": "20260801120000"}, page())


def test_capture_date_reads_the_calendar_day_off_the_timestamp():
    assert B.capture_date("20240812123829") == dt.date(2024, 8, 12)


# ---------------------------------------------------------------------------
# FIRST CAPTURE WINS
# ---------------------------------------------------------------------------

def test_first_capture_wins_lets_an_unclaimed_as_of_through():
    assert B.first_capture_wins({}, dt.date(2024, 8, 12), "20240812123829") is None


def test_first_capture_wins_refuses_a_later_re_render_of_the_same_release():
    """Two digests, one as-of: the CMS re-published cosmetically. The earlier capture keeps it."""
    landed = {"2024-08-12": "20240812123829"}
    reason = B.first_capture_wins(landed, dt.date(2024, 8, 12), "20240815090000")
    assert reason and "20240812123829" in reason and "20240815090000" in reason


def test_first_capture_wins_protects_the_live_capture_already_in_s3():
    """The 2026-08-14 object is a live browser render of the origin. An archived re-render is not
    an improvement on it, and raw is immutable."""
    landed = {"2026-08-14": "(pre-existing)"}
    assert B.first_capture_wins(landed, dt.date(2026, 8, 14), "20260819120000") is not None


# ---------------------------------------------------------------------------
# The dry-run plan
# ---------------------------------------------------------------------------

def test_the_plan_covers_every_selected_capture_and_predicts_no_as_of():
    """A dry run may not fetch a body, and the as-of is a property OF THE BODY. Naming a key it
    cannot know would be exactly the wished-for-date habit the wayback law exists to break."""
    caps = B.select_captures(B.parse_cdx_rows(json.dumps(cdx_payload())))
    plan = B.plan_captures(caps)
    assert len(plan) == _DISTINCT_200_DIGESTS
    assert plan[0]["capture_date"] == "2024-03-05"
    assert plan[-1]["capture_date"] == "2025-05-28"
    for item in plan:
        assert "as_of" not in item
        assert "s3_key" not in item


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_cdx_digest_is_unpadded_base32_of_the_sha1():
    import base64
    import hashlib
    payload = b"the ministry's page"
    assert B.cdx_digest(payload) == base64.b32encode(
        hashlib.sha1(payload).digest()).decode().rstrip("=")


def test_capture_metadata_carries_everything_needed_to_reproduce_the_landing():
    archived = b"<html><body><main>x</main></body></html>"
    pin = {
        "timestamp": "20240812123829",
        "served_capture_ts": "20240812123829",
        "digest": "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM",
        "original": _ORIGINAL,
        "replay_url": "https://web.archive.org/web/20240812123829id_/" + _ORIGINAL,
    }
    meta = B.capture_metadata(pin, archived, page(), dt.date(2024, 8, 12))
    assert meta["wayback_capture_ts"] == "20240812123829"
    assert meta["wayback_served_capture_ts"] == "20240812123829"
    assert meta["cdx_digest"] == "OUEJE5ZK3IVZ3RFCL5FXYM5QNWMKT3BM"
    assert meta["cdx_payload_digest"] == B.cdx_digest(archived)
    assert meta["archived_page_sha256"] and meta["archived_page_bytes"] == len(archived)
    assert meta["replay_url"].endswith(_ORIGINAL)
    # DISTINCT from the live leg's 'rendered_main_outerhtml': a consumer must be able to tell a
    # browser render of the origin from a <main> cut out of an archived page.
    assert meta["capture_kind"] == "wayback_main_outerhtml"
    assert meta["source"] == "minagro_grain_exports"


def test_the_landed_payload_clears_the_familys_raw_size_floor():
    """``check_min_file_size`` returns SILENTLY for an unknown source -- so the floor being wired
    to THIS source key is part of the job, not decoration."""
    from leviathan.storage.raw_metadata import check_min_file_size
    check_min_file_size(page().encode("utf-8"), B.SOURCE, context="test")


# ---------------------------------------------------------------------------
# The existence probe FAILS CLOSED -- the overwrite it prevents is CROSS-SHAPE
# ---------------------------------------------------------------------------
class _ReplayResp:
    """A ``requests.Response`` carrying a BODY -- distinct from the URL-only ``_Resp``
    above, which the verify_capture tests use."""

    def __init__(self, content: bytes, url: str = "", headers=None):
        self.content = content
        self.url = url
        self.headers = headers or {}


class TestRawExistsFailsClosed:
    """``raw_exists`` is the only thing enforcing the sentence this module states in prose:
    *today's live 2026-08-14 capture is a real browser render of the origin; nothing from the
    archive may ever replace it.* The estate house idiom repeals it silently on any throttle.

    THE ARCHIVED BYTES ARE RE-DERIVABLE -- the capture is CDX-pinned, the archive is immutable and
    ``verify_capture`` refuses drift -- so this is NOT the EEX argument. The argument that bites is
    that the overwrite is CROSS-SHAPE: what gets destroyed is a ``rendered_main_outerhtml`` browser
    render OF THE ORIGIN, and what replaces it is a ``wayback_main_outerhtml`` cut from a crawl,
    filed under the same ``as_of=`` key and distinguished afterwards only by a ``capture_kind``
    field that nothing re-checks. The live capture is the better witness and is not re-derivable at
    all, so the loss runs one way only."""

    # Captures dated AFTER the fixture page's own 'stanom na' date: as_of_for_capture refuses a
    # page dated after the crawl that archived it, which is the guard, not the subject here.
    _TS = ("20260818120000", "20260819120000")
    # The fixture page's own "stanom na" date, which is what the raw key is dated by.
    _AS_OF = "2026-08-14"

    @staticmethod
    def _client_error(code, status):
        from botocore.exceptions import ClientError
        return ClientError(
            {"Error": {"Code": code, "Message": "x"},
             "ResponseMetadata": {"HTTPStatusCode": status}},
            "HeadObject",
        )

    @staticmethod
    def _cdx_body(timestamps) -> bytes:
        rows = [CDX_FIELDS]
        for i, ts in enumerate(timestamps):
            rows.append([_URLKEY, ts, _ORIGINAL, "text/html", "200", f"DIGEST{i}", "9999"])
        return json.dumps(rows).encode("utf-8")

    def test_a_landed_object_is_reported_present(self):
        class _S3:
            def head_object(self, **_kw):
                return {"ContentLength": 1}

        assert B.raw_exists(_S3(), "b", "k") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        outer = self

        class _S3:
            def head_object(self, **_kw):
                raise outer._client_error(code, status)

        assert B.raw_exists(_S3(), "b", "k") is False

    @pytest.mark.parametrize("code,status", [
        ("SlowDown", 503),
        ("InternalError", 500),
        ("ExpiredToken", 400),
        ("AccessDenied", 403),
        ("RequestTimeout", 400),
    ])
    def test_every_other_head_failure_RAISES_rather_than_fabricating_absence(self, code, status):
        """Fail closed. This is a one-shot repair: failing costs a re-run, and the archive is not
        going anywhere."""
        from botocore.exceptions import ClientError
        outer = self

        class _S3:
            def head_object(self, **_kw):
                raise outer._client_error(code, status)

        with pytest.raises(ClientError):
            B.raw_exists(_S3(), "b", "k")

    @staticmethod
    def _drive(monkeypatch, raiser, timestamps=None):
        """``main()`` through the REAL raw_exists over a stubbed head_object and a stubbed archive.
        Returns ``(exit_code, [uploaded keys])``."""
        import leviathan.storage.raw_metadata as META
        import leviathan.storage.s3 as S3MOD

        timestamps = timestamps or TestRawExistsFailsClosed._TS
        archived = (b"<html><body>" + page().encode("utf-8") + b"</body></html>")
        uploaded: list[str] = []

        class _S3:
            def head_object(self, **kw):
                exc = raiser(kw["Key"])
                if exc is not None:
                    raise exc
                return {"ContentLength": 1}

        def _http_get(url, *, timeout):
            if url.startswith(B.CDX_URL[:40]):
                return _ReplayResp(TestRawExistsFailsClosed._cdx_body(timestamps))
            return _ReplayResp(archived, url=url)

        monkeypatch.setattr(B, "_http_get", _http_get)
        monkeypatch.setattr(B, "load_env", lambda *a, **k: None)
        monkeypatch.setattr(B.time, "sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(S3MOD, "get_thread_local_s3_client", lambda region: _S3())
        monkeypatch.setattr(S3MOD, "upload_bytes_to_s3",
                            lambda data, bucket, key, region: uploaded.append(key))
        monkeypatch.setattr(META, "write_raw_s3_metadata",
                            lambda *a, **kw: None)
        rc = B.main(["--bucket", "test-bucket", "--aws-region", "us-east-1"])
        return rc, uploaded

    def test_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end through ``main()``: every probe throttles, so every capture is counted as an
        error, NOTHING is uploaded, and the run exits 1. The raise falls to the per-capture handler
        that already existed -- no new call-site machinery, and no exit-0 fall-through: `if errors:
        return 1` is the first verdict main() reaches."""
        rc, uploaded = self._drive(monkeypatch, lambda _k: self._client_error("SlowDown", 503))
        assert rc == 1
        assert uploaded == [], "a throttled head must never let an ARCHIVED render overwrite a LIVE one"

    def test_one_captures_unanswerable_probe_never_costs_the_others(self, monkeypatch):
        """The blocked capture is counted and skipped; the next one still lands. One dead capture
        must not sink the repair, and a repair that hit an S3 fault must not exit green."""
        from leviathan.storage.paths import raw_minagro_grain_exports_key

        key = raw_minagro_grain_exports_key(self._AS_OF)
        calls = {"n": 0}

        def _raiser(_key):
            calls["n"] += 1
            return (self._client_error("AccessDenied", 403) if calls["n"] == 1
                    else self._client_error("404", 404))

        rc, uploaded = self._drive(monkeypatch, _raiser)
        assert rc == 1
        assert uploaded == [key]

    def test_the_same_drive_lands_when_the_head_answers_404(self, monkeypatch):
        """The positive control, so the two tests above cannot pass vacuously. Both captures carry
        the same as-of, so the SECOND is refused by first-capture-wins rather than by the probe --
        which is the within-run half of the rule, still working."""
        rc, uploaded = self._drive(monkeypatch, lambda _k: self._client_error("404", 404))
        assert rc == 0
        from leviathan.storage.paths import raw_minagro_grain_exports_key

        assert uploaded == [raw_minagro_grain_exports_key(self._AS_OF)]

    def test_an_already_landed_as_of_still_short_circuits(self, monkeypatch):
        """The across-runs half of first-capture-wins is unchanged: a head that ANSWERS 'present'
        keeps the live browser render and uploads nothing."""
        rc, uploaded = self._drive(monkeypatch, lambda _k: None)
        assert rc == 0 and uploaded == []
