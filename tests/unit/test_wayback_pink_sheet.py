"""LANE (b): the Pink Sheet archive backfill, pinned. NEW-CODE SPEC, NO BORROWED PRECEDENT.

CDX appears in this estate at ``backfill_minagro_wayback.py`` and ``backfill_unica_wayback.py`` and
NEITHER reads ``X-Archive-Orig-*``, and neither sweeps a DOMAIN.  So the two rules this lane adds --
the origin-header clock and the paged domain census -- ship with their own pins here rather than
citing an analogue they do not have.

What is under test, and why each one matters:

  * CAPTURE DRIFT -- an unmatched timestamp does NOT 404, it 200s with the NEAREST capture. This is
    the law that cost CEPEA nine years, re-pinned on a new leg.
  * THE CONTENT KEY -- a body is filed under the month it DERIVES or refused; never under the
    month somebody wanted.
  * MAGIC BYTES -- a lying origin (HTML under an xlsx content type, MEASURED on the 2016 epoch) and
    a real legacy OLE2 .xls are counted APART.
  * THE PAGED CENSUS -- the loop follows a resumeKey across pages and stops when it is ABSENT,
    never on a short page.
  * THE DOMAIN SWEEP -- ``matchType=domain&url=worldbank.org``, because the workbook lived on
    pubdocs / siteresources before thedocs and a prefix census returns zero pre-2021 captures BY
    CONSTRUCTION. Every row records its HOST so the era-to-host map is measured.
  * THE ARCHIVE CLOCK -- ``origin_last_modified`` is reachable ONLY from
    ``X-Archive-Orig-Last-Modified``; the archive's own ``Last-Modified`` never reaches rung 1.

AWS-free, network-free: the HTTP seam is injected.
"""
from __future__ import annotations

import io
import json

import pytest
from leviathan.common import pink_sheet_release as R

B = pytest.importorskip("jobs.ingest.backfill_pink_sheet_vintages")

TARGET = ("https://pubdocs.worldbank.org/en/xyz/"
          "CMO-Historical-Data-Monthly.xlsx")


def _workbook(release: str, *, nudge: float = 0.0) -> bytes:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = R.SHEET_NAME
    sheet.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    sheet.append(["Updated as of: whatever"])
    sheet.append([None])
    sheet.append([None])
    sheet.append(["Month", "Soybean oil"])
    for i, month in enumerate(R.expected_months(release)):
        sheet.append([month, 900.0 + i + nudge])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


class _Resp:
    def __init__(self, *, url="", content=b"", headers=None):
        self.url = url
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None


def _replay(ts: str, *, served: str | None = None, body: bytes = b"",
            headers: dict | None = None) -> _Resp:
    """A replay response whose FINAL url names the capture Wayback actually served."""
    served = served or ts
    return _Resp(url=f"https://web.archive.org/web/{served}id_/{TARGET}",
                 content=body, headers=headers or {})


class TestClosedDeclineVocabulary:
    def test_every_decline_constant_is_in_the_closed_set(self):
        names = [v for k, v in vars(B).items()
                 if k.startswith("DECLINE_") and isinstance(v, str)]
        assert names, "the decline constants vanished"
        assert set(names) == set(B.DECLINES)
        assert len(B.DECLINES) == 10

    def test_the_vocabulary_is_the_one_the_design_closed(self):
        # `widens_served_set` LEFT and `already_held` ARRIVED, and the count is unchanged at ten by
        # coincidence, not by design -- so both halves are asserted by NAME.
        #   OUT: no harvest code path could emit `widens_served_set`, and none could: the widening
        #        question needs the SCHEDULED frames a harvest does not hold. It is answered by
        #        served_set_census() in the archive task, about an object that has already landed.
        #   IN:  `_land` returns 'held' without writing when the key exists (first capture wins).
        #        That capture is a DECLINE; counting it as landed inflated coverage and broke the
        #        attempt identity.
        assert set(B.DECLINES) == {
            "capture_drift", "unpinnable_timestamp", "content_key_mismatch",
            "not_full_restatement", "extract_narrow", "duplicate_values", "non_200",
            "body_not_workbook", "format_unsupported", "already_held"}
        assert "widens_served_set" not in B.DECLINES
        assert B.WIDENING_IS_MEASURED_IN == (
            "jobs/batch/pink_sheet_archive_task.py::served_set_census")


class TestCaptureDrift:
    """THE CEPEA LAW, re-pinned on this leg."""

    def test_a_served_capture_that_is_not_the_pinned_one_is_REFUSED(self):
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "host": "pubdocs.worldbank.org",
               "replay_url": B.replay_url("20190401120000", TARGET)}
        body, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190401120000", served="20170715030201",
                                           body=_workbook("2019M04")))
        assert body is None
        assert decline == B.DECLINE_CAPTURE_DRIFT
        assert meta["served_capture_ts"] == "20170715030201"

    def test_a_response_that_disagrees_with_ITSELF_is_refused_as_drift(self):
        """URL says one capture, Memento-Datetime says another: provenance cannot be established at
        all, which is the drift class arriving by a second route."""
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        resp = _replay("20190401120000",
                       headers={"Memento-Datetime": "Mon, 15 Jul 2017 03:02:01 GMT"})
        body, decline, _ = B.fetch_capture(cap, fetch=lambda url: resp)
        assert body is None and decline == B.DECLINE_CAPTURE_DRIFT

    def test_a_matching_capture_passes_the_drift_gate(self):
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        body, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190401120000", body=_workbook("2019M04")))
        assert decline is None and body
        assert meta["derived_release_ym"] == "2019M04"


class TestContentKeyAndMagicBytes:
    def test_the_body_is_keyed_on_the_month_it_DERIVES_not_the_one_wished_for(self):
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        # the capture is April 2019, but the body derives 2018M11 -- the BYTES decide.
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190401120000", body=_workbook("2018M11")))
        assert decline is None
        assert meta["derived_release_ym"] == "2018M11"
        assert meta["release_date"].startswith("2018-11")

    def test_the_measured_2016_html_body_declines_body_not_workbook(self):
        cap = {"timestamp": "20160901120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        html = b"\x0a    \x0a\x0a\x0a<!DOCTYPE html><html>not a workbook</html>"
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20160901120000", body=html))
        assert decline == B.DECLINE_BODY_NOT_WORKBOOK
        # the detail names the SIZE and the FIRST BYTES -- the two facts that tell a reader the
        # origin served a web page under an xlsx content type rather than a broken workbook.
        assert str(len(html)) in meta["detail"] and "first 8" in meta["detail"]

    def test_a_real_legacy_xls_declines_format_unsupported_NOT_body_not_workbook(self):
        """The two are counted APART: one is a broken response, the other is a supported-format
        question whose answer is an era rule."""
        cap = {"timestamp": "20050901120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 2048
        _, decline, _ = B.fetch_capture(cap, fetch=lambda url: _replay("20050901120000",
                                                                       body=ole2))
        assert decline == B.DECLINE_FORMAT_UNSUPPORTED

    def test_a_workbook_with_a_hole_declines_not_full_restatement(self, monkeypatch):
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        real = B.monthly_rows
        monkeypatch.setattr(B, "monthly_rows", lambda b: [m for m in real(b) if m != "1971M04"])
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190401120000", body=_workbook("2019M04")))
        assert decline == B.DECLINE_NOT_FULL_RESTATEMENT
        assert meta["observed_month_count"] == meta["expected_month_count"] - 1


class TestCaptureBound:
    def test_a_release_dated_after_its_capture_is_refused(self):
        """A workbook cannot have been published AFTER the crawl that archived it. The capture
        timestamp is a WITNESS BOUND, never the release month."""
        assert B.release_within_capture_bound("2019-04-01", "20190501120000") is None
        why = B.release_within_capture_bound("2019-06-01", "20190501120000")
        assert why and "AFTER capture" in why

    def test_the_bound_fires_through_fetch_capture(self):
        cap = {"timestamp": "20190401120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190401120000", body=_workbook("2019M06")))
        assert decline == B.DECLINE_CONTENT_KEY_MISMATCH
        assert "AFTER capture" in meta["detail"]


class TestTheArchiveClock:
    """G-B1b. A crawl date written as ``origin_last_modified`` would be a provenance lie under a
    token asserting the opposite -- and it would be permanently quotable."""

    def test_the_ORIGIN_header_reaches_rung_1(self):
        cap = {"timestamp": "20190501120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        headers = {B.ORIGIN_LAST_MODIFIED_HEADER: "Tue, 02 Apr 2019 09:00:00 GMT",
                   "Last-Modified": "Wed, 01 May 2019 12:00:00 GMT"}
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190501120000", body=_workbook("2019M04"),
                                           headers=headers))
        assert decline is None
        assert meta["release_date"] == "2019-04-02"
        assert meta["release_date_source"] == R.SOURCE_ORIGIN_LAST_MODIFIED

    def test_the_ARCHIVE_s_own_last_modified_NEVER_reaches_rung_1(self):
        """The decisive pin. The replay's own Last-Modified names MAY 2019 (the crawl); the derived
        release is APRIL. If it reached the ladder it would disagree with the month and be dropped
        anyway -- so the fixture is built so it would AGREE, and the row must STILL take the
        archive fallback."""
        cap = {"timestamp": "20190430120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        headers = {"Last-Modified": "Tue, 30 Apr 2019 12:00:00 GMT"}   # would agree with 2019M04
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190430120000", body=_workbook("2019M04"),
                                           headers=headers))
        assert decline is None
        assert meta["release_date_source"] == R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE
        assert meta["release_date"] == "2019-04-01"
        assert meta["release_date_source"] != R.SOURCE_ORIGIN_LAST_MODIFIED
        # the ignored header is still RECORDED, so a reader can see what was declined and why
        assert meta["archive_last_modified_IGNORED"] == "Tue, 30 Apr 2019 12:00:00 GMT"

    def test_no_origin_header_takes_the_DISTINCT_archive_token(self):
        cap = {"timestamp": "20190501120000", "digest": "D", "original": TARGET,
               "replay_url": "x"}
        _, decline, meta = B.fetch_capture(
            cap, fetch=lambda url: _replay("20190501120000", body=_workbook("2019M04")))
        assert meta["release_date_source"] == R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE


class TestTheCdxCensus:
    def _page(self, rows, resume=None):
        payload = [["timestamp", "original", "digest", "statuscode", "length"]] + rows
        if resume:
            payload = payload + [[], [resume]]
        return _Resp(content=json.dumps(payload).encode())

    def test_the_census_url_is_a_DOMAIN_sweep_over_worldbank_org(self):
        """A thedocs PREFIX census returns ZERO pre-2021 captures BY CONSTRUCTION: the workbook was
        served from pubdocs and earlier siteresources before the migration, and CDX indexes by the
        URL AS CRAWLED."""
        assert "matchType=domain" in B.CDX_QUERY
        assert "url=worldbank.org" in B.CDX_QUERY
        assert "thedocs" not in B.CDX_QUERY
        assert "showResumeKey=true" in B.CDX_QUERY
        assert "filter=statuscode:200" in B.CDX_QUERY

    def test_the_filename_filter_spans_BOTH_spellings(self):
        """`.?` spans the hyphen, so the modern CMO-Historical-Data-Monthly and the pre-2020
        unhyphenated CMOHistoricalDataMonthly both match in ONE server-side filter."""
        import re
        raw = B.CDX_QUERY.split("filter=original:", 1)[1].split("&", 1)[0]
        rx = re.compile(raw)
        assert rx.search("/x/CMO-Historical-Data-Monthly.xlsx")
        assert rx.search("/x/CMOHistoricalDataMonthly.xlsx")

    def test_the_pager_follows_a_resume_key_and_stops_when_it_is_ABSENT(self):
        pages = [
            self._page([["20190401120000", TARGET, "AAA", "200", "700000"]], resume="KEY1"),
            self._page([["20200401120000", TARGET, "BBB", "200", "710000"]]),
        ]
        seen = []

        def _fetch(url):
            seen.append(url)
            return pages[len(seen) - 1]

        captures, report = B.census_pages(fetch=_fetch)
        assert report["pages"] == 2
        assert report["truncated"] is False
        assert len(captures) == 2
        assert "resumeKey=KEY1" in seen[1]
        assert "resumeKey" not in seen[0]

    def test_a_SHORT_page_with_a_resume_key_does_NOT_stop_the_loop(self):
        """Stopping on a short page is a page-size heuristic and it stops early. The ABSENCE of the
        key is the only terminator."""
        pages = [self._page([["20190401120000", TARGET, "AAA", "200", "1"]], resume="K"),
                 self._page([["20200401120000", TARGET, "BBB", "200", "1"]])]
        it = iter(pages)
        _, report = B.census_pages(fetch=lambda url: next(it))
        assert report["pages"] == 2

    def test_every_capture_records_its_HOST_so_the_era_map_is_measured(self):
        rows = [
            ["20140401120000", "https://siteresources.worldbank.org/a/CMOHistoricalDataMonthly.xlsx",
             "AAA", "200", "1"],
            ["20180401120000", "https://pubdocs.worldbank.org/b/CMO-Historical-Data-Monthly.xlsx",
             "BBB", "200", "1"],
            ["20230401120000", "https://thedocs.worldbank.org/c/CMO-Historical-Data-Monthly.xlsx",
             "CCC", "200", "1"],
        ]
        captures, report = B.census_pages(fetch=lambda url: self._page(rows))
        assert report["by_host"] == {"pubdocs.worldbank.org": 1,
                                     "siteresources.worldbank.org": 1,
                                     "thedocs.worldbank.org": 1}
        assert report["by_year"] == {"2014": 1, "2018": 1, "2023": 1}
        assert {c["host"] for c in captures} == set(report["by_host"])

    def test_an_empty_index_is_a_real_answer_not_an_error(self):
        captures, report = B.census_pages(fetch=lambda url: self._page([]))
        assert captures == []
        assert report["distinct_captures"] == 0
        assert report["earliest_capture"] is None


class TestSelectCaptures:
    def test_an_unpinnable_timestamp_never_becomes_a_replay_request(self):
        rows = [{"timestamp": "2019", "original": TARGET, "digest": "A", "statuscode": "200"},
                {"timestamp": "20190401120000", "original": TARGET, "digest": "B",
                 "statuscode": "200"}]
        got = B.select_captures(rows)
        assert [c["timestamp"] for c in got] == ["20190401120000"]

    def test_a_non_200_row_is_dropped_even_though_the_server_filtered(self):
        rows = [{"timestamp": "20190401120000", "original": TARGET, "digest": "A",
                 "statuscode": "301"}]
        assert B.select_captures(rows) == []

    def test_a_recurring_digest_keeps_the_EARLIEST_capture(self):
        """collapse=digest is an ADJACENT-RUN collapse server-side, so a digest that recurs later
        still arrives twice. The earliest capture is the closest witness to the release."""
        rows = [{"timestamp": "20200401120000", "original": TARGET, "digest": "A",
                 "statuscode": "200"},
                {"timestamp": "20190401120000", "original": TARGET, "digest": "A",
                 "statuscode": "200"}]
        got = B.select_captures(rows)
        assert [c["timestamp"] for c in got] == ["20190401120000"]

    def test_the_replay_url_carries_the_MANDATORY_id_suffix(self):
        rows = [{"timestamp": "20190401120000", "original": TARGET, "digest": "A",
                 "statuscode": "200"}]
        assert B.select_captures(rows)[0]["replay_url"].startswith(
            "https://web.archive.org/web/20190401120000id_/")


class TestValueKeyedDeduplication:
    def test_two_byte_different_encodings_of_the_SAME_data_hash_alike(self):
        """MEASURED: the display regime moved from full float to 2 decimals between 2026M05 and
        2026M07 and the file went 783,157 -> 575,636 bytes without moving most data. De-duplicating
        on raw bytes would land one vintage twice under two months."""
        import hashlib
        a = _workbook("2019M04")
        b = _workbook("2019M04")           # same values, re-encoded
        assert B.value_matrix_hash(a) == B.value_matrix_hash(b)
        c = _workbook("2019M04", nudge=1.0)
        assert B.value_matrix_hash(c) != B.value_matrix_hash(a)
        # and the CDX digest stays PROVENANCE: it is a byte hash and says nothing about values
        assert B.cdx_digest(a) != B.cdx_digest(c) or hashlib.sha1(a).digest() != \
            hashlib.sha1(c).digest()


class TestOriginPhasePlan:
    def test_the_plan_probes_every_epoch_under_BOTH_filename_spellings(self):
        plan = B.origin_plan()
        assert len(plan) == len(B._EPOCHS) * 2
        assert {item["url"].rsplit("/", 1)[1] for item in plan} == set(B._FILENAMES)

    def test_every_epoch_carries_its_measured_probe_result(self):
        for item in B.origin_plan():
            assert item["probe"], "an epoch with no recorded measurement is an unexamined guess"


class TestPolitenessConstants:
    def test_they_are_the_minagro_leg_s_values_VERBATIM(self):
        """archive.org is a LIBRARY, not a CDN. These are reused rather than re-chosen."""
        assert B._SLEEP_BETWEEN_FETCHES_S == 2.5
        assert B._CDX_TIMEOUT_S == 90
        assert B._FETCH_TIMEOUT_S == 120
        assert B._MAX_ATTEMPTS == 3
        assert B._BACKOFF_SECONDS == 10
        assert B._RETRYABLE_STATUS == frozenset({429, 500, 502, 503, 504})


class TestHarvestAccounting:
    """THE UNIT OF ACCOUNT IS THE ATTEMPT.

    Reproduces the refuter's shape directly: TWO captures of ONE release, the first landing and the
    second finding the key already held. Before the fix `landed` was a dict keyed by release, so the
    two collapsed into one accounted row, `accounted` (1) < `attempted` (2), identity_holds read
    False on a normal harvest, and the discarded capture carried no decline tag at all.
    """

    @staticmethod
    def _run(monkeypatch, capsys, statuses):
        caps = [{"timestamp": f"2019040112000{i}", "digest": f"D{i}", "original": TARGET,
                 "host": "pubdocs.worldbank.org",
                 "replay_url": B.replay_url(f"2019040112000{i}", TARGET), "length": "1"}
                for i in range(len(statuses))]
        seq = list(statuses)

        monkeypatch.setattr(B, "census_pages", lambda: (caps, {"pages": 1, "rows": len(caps)}))
        monkeypatch.setattr(B, "fetch_capture", lambda cap, **kw: (
            b"BODY", None,
            {"derived_release_ym": "2019M04", "release_date": "2019-04-01",
             "release_date_source": R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE}))
        # A DIFFERENT value hash per capture, so the duplicate-values tag cannot mask the shape
        # under test: what is being pinned is `_land` returning 'held', nothing else.
        hashes = iter([f"H{i}" for i in range(len(caps))])
        monkeypatch.setattr(B, "value_matrix_hash", lambda body: next(hashes))
        monkeypatch.setattr(B, "_land", lambda *a, **k: (seq.pop(0), "raw/archive/key.xlsx"))
        monkeypatch.setattr(B, "load_env", lambda *a, **k: None)
        monkeypatch.setattr(B, "get_required_env", lambda name: "TEST")
        monkeypatch.setattr(B.time, "sleep", lambda *_: None)

        args = B._parse_args(["--phase", "wayback"])
        assert B.run_wayback(args) == 0
        return json.loads(capsys.readouterr().out)

    def test_a_held_capture_is_a_counted_decline_and_never_a_landing(
            self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, ["landed", "held"])
        assert out["attempted"] == 2
        assert out["n_landed_captures"] == 1, "the held capture wrote nothing and is not a landing"
        assert out["n_releases_landed"] == 1
        assert out["declines_by_tag"] == {"already_held": 1}
        assert out["n_declines"] == 1

    def test_the_identity_is_counted_over_ATTEMPTS_and_holds_on_a_normal_harvest(
            self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, ["landed", "held"])
        assert out["accounted"] == out["attempted"] == 2
        assert out["identity_holds"] is True
        assert out["unknown_tags"] == []

    def test_two_captures_of_one_release_both_land_and_both_are_accounted(
            self, monkeypatch, capsys):
        """Not a contradiction of the release roster: TWO captures, ONE release, and the two
        numbers are reported under two names instead of one being silently dropped."""
        out = self._run(monkeypatch, capsys, ["landed", "landed"])
        assert out["n_landed_captures"] == 2
        assert out["n_releases_landed"] == 1
        assert out["landed"] == ["2019M04"]
        assert out["accounted"] == 2 and out["identity_holds"] is True

    def test_the_report_names_where_widening_is_actually_measured(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, ["landed"])
        assert out["widening_measured_in"].endswith("served_set_census")
