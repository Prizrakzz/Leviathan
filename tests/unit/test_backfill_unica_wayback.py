"""D-LD Track U -- the UNICA wayback CONTENT-REPAIR pins.

unica biweekly silver content stops at fortnight 2026-02-01 because the Apr..Aug 2026 bulletins
(season 2026/2027) were never captured, and the portal serves exactly ONE bulletin with no
archive -- so the only route back is CDX-pinned Wayback replay.  These tests pin the four things
that route can get wrong, all with mocked HTTP and no AWS:

  1. CDX PIN-AND-VERIFY  -- a wayback timestamp is a REQUEST: an unmatched one 200s with the
     NEAREST capture.  Drift must be REFUSED, never landed (the CEPEA nine-year hole).
  2. QUARANTINE RELABEL  -- idm=32820684 (published 2026/04, labelled 2025/2026) corrected at
     both layers the RCA named: fetch (manifest rows) and bronze (hive keys).
  3. PUBLICATION-MONTH LABELLING -- the published month decides the season.  Never the caller,
     never the loop variable, never the key the object happens to sit under.
  4. BRONZE SKIP BEHAVIOUR -- content-aware (staleness), never bare existence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest
from leviathan.common.unica_bulletins import (
    MIN_PDF_BYTES,
    PDF_MAGIC,
    SEASON_RELABELS,
    corrected_season,
    is_relabelled,
    parse_pdf_url,
    relabel_reason,
    season_for_publication,
)
from leviathan.common.wayback import capture_drift, replay_url, served_capture_ts

bf = pytest.importorskip("jobs.ingest.backfill_unica_wayback")


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------

_APRIL_HASH = "770db0dd8567be10a516943543a04df4"
_APRIL_URL = f"https://unicadata.com.br/arquivos/pdfs/2026/04/{_APRIL_HASH}.pdf"
_APRIL_TS = "20260521172419"


def _real_pdf(marker: bytes = b"april-2026") -> bytes:
    """A payload that clears both presence tests (%PDF magic + the 50 KB floor)."""
    return PDF_MAGIC + b"-1.7\n" + marker + b"0" * MIN_PDF_BYTES


class _Resp:
    """Duck-typed stand-in for requests.Response: only .url / .headers / .content are read."""

    def __init__(self, url: str, content: bytes = b"", headers: dict | None = None):
        self.url = url
        self.content = content
        self.headers = headers or {}


def _cdx_payload(rows: list[list[str]]) -> bytes:
    header = ["timestamp", "original", "digest", "statuscode", "mimetype"]
    return json.dumps([header, *rows]).encode()


def _pin(**overrides):
    info = parse_pdf_url(_APRIL_URL)
    pin = {
        **info,
        "timestamp": _APRIL_TS,
        "digest": "NCLO3EWDK6SQ7ZQ4YQ6DQ2E7YQ5J6ABC",
        "original": _APRIL_URL,
        "replay_url": replay_url(_APRIL_TS, _APRIL_URL),
        "s3_key": "raw/production/source=unica_biweekly/harvest_year=2026_2027/"
                  f"idm=pdf_{_APRIL_HASH}/report.pdf",
    }
    pin.update(overrides)
    return pin


# ===========================================================================
# 1. CDX PIN-AND-VERIFY
# ===========================================================================

class TestCdxPinAndVerify:
    def test_the_cdx_query_is_bounded_to_the_window_years(self, monkeypatch):
        """One bounded query per calendar year the PUBLICATION window spans -- never a wildcard."""
        seen: list[str] = []

        def fake_get(url, *, timeout):
            seen.append(url)
            return _Resp(url, _cdx_payload([]))

        monkeypatch.setattr(bf, "_http_get", fake_get)
        monkeypatch.setattr(bf.time, "sleep", lambda *_: None)
        bf.fetch_cdx_rows([2026])

        assert len(seen) == 1
        assert "arquivos/pdfs/2026/*" in seen[0]
        assert "filter=statuscode:200" in seen[0]
        assert "collapse=digest" in seen[0]
        assert "limit=" in seen[0]

    def test_pins_carry_the_exact_capture_timestamp_and_digest(self):
        rows = [{"timestamp": _APRIL_TS, "original": _APRIL_URL, "digest": "ABC123",
                 "statuscode": "200", "mimetype": "application/pdf"}]
        pins = bf.pin_captures(rows, dt.date(2026, 4, 1), dt.date(2026, 8, 18))

        assert len(pins) == 1
        pin = pins[0]
        assert pin["timestamp"] == _APRIL_TS          # pinned, not wished for
        assert pin["digest"] == "ABC123"
        assert pin["replay_url"] == f"https://web.archive.org/web/{_APRIL_TS}id_/{_APRIL_URL}"
        assert "id_/" in pin["replay_url"]            # raw bytes, no rewriting banner

    def test_the_window_bounds_publication_not_capture_date(self):
        """A Feb-2026 bulletin CAPTURED in April is out of an April.. window: publication rules."""
        rows = [
            {"timestamp": "20260410190820", "digest": "d1", "statuscode": "200",
             "original": "https://unicadata.com.br/arquivos/pdfs/2026/02/" + "a" * 32 + ".pdf"},
            {"timestamp": _APRIL_TS, "digest": "d2", "statuscode": "200", "original": _APRIL_URL},
        ]
        pins = bf.pin_captures(rows, dt.date(2026, 4, 1), dt.date(2026, 8, 18))

        assert [p["published_ym"] for p in pins] == ["2026/04"]

    def test_repeat_captures_of_one_url_pin_the_newest(self):
        rows = [
            {"timestamp": "20260501000000", "digest": "old", "statuscode": "200",
             "original": _APRIL_URL},
            {"timestamp": _APRIL_TS, "digest": "new", "statuscode": "200", "original": _APRIL_URL},
        ]
        pins = bf.pin_captures(rows, dt.date(2026, 4, 1), dt.date(2026, 8, 18))

        assert len(pins) == 1
        assert pins[0]["timestamp"] == _APRIL_TS and pins[0]["digest"] == "new"

    def test_a_nearest_capture_redirect_is_refused(self):
        """THE law: /web/{ts}id_/ does not 404 on an unmatched ts, it 200s with the NEAREST
        capture.  Those bytes must never wear the pinned key's provenance."""
        pin = _pin()
        served = "20170708153249"                      # wayback quietly served a different day
        why = bf.verify_payload(pin, _real_pdf(), served)

        assert why and "not the pinned" in why and "NEAREST" in why

    def test_a_response_that_names_no_capture_is_refused(self):
        why = bf.verify_payload(_pin(), _real_pdf(), None)
        assert why and "cannot be established" in why

    def test_the_served_capture_is_read_off_the_redirect_and_cross_checked(self):
        agreeing = _Resp(f"https://web.archive.org/web/{_APRIL_TS}id_/{_APRIL_URL}",
                         headers={"Memento-Datetime": "Thu, 21 May 2026 17:24:19 GMT"})
        assert served_capture_ts(agreeing) == _APRIL_TS
        assert served_capture_ts(_Resp(agreeing.url)) == _APRIL_TS          # URL alone suffices

        conflicted = _Resp(agreeing.url, headers={"Memento-Datetime": "Mon, 08 Jun 2026 14:39:48 GMT"})
        with pytest.raises(ValueError, match="disagrees with itself"):
            served_capture_ts(conflicted)

    def test_a_matching_capture_with_a_real_pdf_is_accepted(self):
        pin = _pin(digest=bf.cdx_digest(_real_pdf()))
        assert bf.verify_payload(pin, _real_pdf(), _APRIL_TS) is None

    def test_a_wayback_placeholder_page_is_refused_even_on_the_right_capture(self):
        why = bf.verify_payload(_pin(), b"<html>not archived</html>", _APRIL_TS)
        assert why and "not a PDF" in why

    def test_a_sub_minimum_stand_in_is_refused(self):
        why = bf.verify_payload(_pin(), PDF_MAGIC + b"-1.4\n" + b"0" * 100, _APRIL_TS)
        assert why and "too small" in why

    def test_digest_mismatch_warns_by_default_and_refuses_under_strict(self):
        """Soft by default ON PURPOSE: the base32-SHA1 equality has never been measured in this
        repo, and an unverified assumption must not block the repair's first ever run."""
        pin = _pin(digest="TOTALLYDIFFERENTDIGESTVALUE00000")
        assert bf.verify_payload(pin, _real_pdf(), _APRIL_TS) is None
        strict = bf.verify_payload(pin, _real_pdf(), _APRIL_TS, strict_digest=True)
        assert strict and "digest mismatch" in strict

    def test_cdx_digest_is_unpadded_base32_sha1(self):
        digest = bf.cdx_digest(b"payload")
        assert digest == digest.upper() and "=" not in digest and len(digest) == 32

    def test_download_verifies_against_the_response_wayback_actually_returned(self, monkeypatch):
        """End-to-end over mocked HTTP: the drift check reads the FINAL url, not the request."""
        pin = _pin()
        drifted = _Resp("https://web.archive.org/web/20170708153249id_/" + _APRIL_URL,
                        _real_pdf())
        monkeypatch.setattr(bf, "_http_get", lambda url, *, timeout: drifted)

        payload, served = bf.download_capture(pin)
        assert served == "20170708153249"
        assert bf.verify_payload(pin, payload, served) is not None

    def test_capture_drift_helper_passes_the_pinned_capture(self):
        assert capture_drift(_APRIL_TS, _APRIL_TS) is None


# ===========================================================================
# 2. QUARANTINE RELABEL (idm=32820684)
# ===========================================================================

class TestQuarantineRelabel:
    def test_the_map_names_the_bulletin_and_its_evidence(self):
        fix = SEASON_RELABELS["32820684"]
        assert fix["labelled"] == "2025/2026"
        assert fix["correct"] == "2026/2027"
        assert "2026/04" in fix["evidence"]
        assert is_relabelled("32820684") and not is_relabelled("99999999")

    def test_the_correction_matches_the_publication_month_rule(self):
        """The map is not a magic number: 2026/04 -> 2026/2027 is what the rule already says."""
        assert SEASON_RELABELS["32820684"]["correct"] == season_for_publication(2026, 4)

    def test_slash_and_underscore_shapes_are_both_preserved(self):
        # manifest rows are slash-shaped; S3 hive keys are underscore-shaped.
        assert corrected_season("32820684", "2025/2026") == "2026/2027"
        assert corrected_season("32820684", "2025_2026") == "2026_2027"

    def test_unmapped_bulletins_pass_through_untouched(self):
        assert corrected_season("pdf_abc", "2024/2025") == "2024/2025"
        assert relabel_reason("pdf_abc", "2024/2025") is None
        assert corrected_season(None, "2024/2025") == "2024/2025"

    def test_an_already_correct_label_is_not_reported_as_a_relabel(self):
        assert corrected_season("32820684", "2026/2027") == "2026/2027"
        assert relabel_reason("32820684", "2026/2027") is None

    def test_the_audit_line_names_both_seasons_and_the_defect(self):
        note = relabel_reason("32820684", "2025/2026")
        assert note and "2025/2026 -> 2026/2027" in note and "32820684" in note

    def test_fetch_layer_relabels_manifest_rows(self):
        """Layer 1 of 2: the manifest row the season-scoped download filter reads."""
        from jobs.ingest import fetch_unica_biweekly as fetch

        rows = [
            {"idm": "32820684", "harvest_year": "2025/2026", "published_ym": "2026/04"},
            {"idm": "pdf_deadbeef", "harvest_year": "2024/2025", "published_ym": "2024/10"},
        ]
        fixed, count = fetch._apply_season_relabels(rows)

        assert count == 1
        assert fixed[0]["harvest_year"] == "2026/2027"
        assert fixed[1]["harvest_year"] == "2024/2025"      # untouched
        assert rows[0]["harvest_year"] == "2025/2026"       # inputs not mutated

    def test_the_relabel_makes_the_season_scoped_filter_match(self):
        """The exact no-op being repaired: target_years == ['2026/2027'] matched ZERO rows."""
        from jobs.ingest import fetch_unica_biweekly as fetch

        rows = [{"idm": "32820684", "harvest_year": "2025/2026"}]
        target_years = ["2026/2027"]

        assert [r for r in rows if r["harvest_year"] in target_years] == []
        fixed, _ = fetch._apply_season_relabels(rows)
        assert len(([r for r in fixed if r["harvest_year"] in target_years])) == 1

    def test_bronze_layer_relabels_the_hive_key(self, monkeypatch):
        """Layer 2 of 2: the raw object is NOT moved (owner decision D22), so bronze corrects on
        read -- otherwise silver dates this April-2026 bulletin to April 2025."""
        task = pytest.importorskip("jobs.batch.unica_biweekly_task")

        raw_key = ("raw/production/source=unica_biweekly/harvest_year=2025_2026/"
                   "idm=32820684/report.pdf")
        written: list[str] = []

        class _S3:
            def head_object(self, **_kw):
                raise RuntimeError("no bronze yet")

            def put_object(self, **kw):
                written.append(kw["Key"])

        monkeypatch.setattr(task, "get_thread_local_s3_client", lambda _r: _S3())
        monkeypatch.setattr(task, "s3_download_with_retry", lambda *_a, **_k: b"%PDF-1.7 bytes")
        monkeypatch.setattr(
            task, "transform_pdf",
            lambda *_a, **_k: {"_classification": "biweekly_new_en",
                               "fortnight_production": _tiny_frame()},
        )

        status, _, _ = task._process(raw_key, "bkt", "us-east-1", False, False, "2026-08-18")

        assert status == "written"
        assert written and all("harvest_year=2026_2027" in k for k in written)
        assert not any("harvest_year=2025_2026" in k for k in written)


def _tiny_frame():
    pd = pytest.importorskip("pandas")
    return pd.DataFrame({"region": ["CS"], "value": [1.0]})


# ===========================================================================
# 3. PUBLICATION-MONTH LABELLING
# ===========================================================================

class TestPublicationMonthLabelling:
    @pytest.mark.parametrize(
        "pub_ym,season",
        [((2026, 4), "2026/2027"), ((2026, 8), "2026/2027"), ((2026, 12), "2026/2027"),
         ((2027, 1), "2026/2027"), ((2027, 3), "2026/2027"), ((2027, 4), "2027/2028"),
         ((2026, 3), "2025/2026")],
    )
    def test_april_opens_the_season_and_jan_to_mar_closes_the_prior_one(self, pub_ym, season):
        assert season_for_publication(*pub_ym) == season

    def test_the_url_is_the_evidence(self):
        info = parse_pdf_url(_APRIL_URL)
        assert info["published_ym"] == "2026/04"
        assert info["harvest_year"] == "2026/2027"
        assert info["idm"] == f"pdf_{_APRIL_HASH}"

    def test_a_non_bulletin_url_parses_to_nothing(self):
        assert parse_pdf_url("https://unicadata.com.br/listagem.php?idMn=63") is None
        assert parse_pdf_url("") is None

    def test_the_pinned_key_is_partitioned_by_the_published_season(self):
        pins = bf.pin_captures(
            [{"timestamp": _APRIL_TS, "original": _APRIL_URL, "digest": "d", "statuscode": "200"}],
            dt.date(2026, 4, 1), dt.date(2026, 8, 18),
        )
        assert "harvest_year=2026_2027" in pins[0]["s3_key"]
        assert pins[0]["s3_key"].endswith(f"idm=pdf_{_APRIL_HASH}/report.pdf")

    def test_the_backfill_rule_is_the_same_one_the_extractor_uses(self):
        """One rule, three call sites -- the extractor, the backfill, the as-of fence."""
        from leviathan.common.dates import current_harvest_season

        for year in (2025, 2026, 2027):
            for month in range(1, 13):
                assert (
                    season_for_publication(year, month)
                    == current_harvest_season(dt.date(year, month, 1))
                )


# ===========================================================================
# 4. SKIP BEHAVIOUR -- backfill (content-aware) and bronze (staleness-aware)
# ===========================================================================

class TestContentAwareSkip:
    def test_the_same_capture_already_landed_is_skipped_without_http(self):
        pin = _pin()
        meta = {"wayback_capture_ts": pin["timestamp"], "cdx_digest": pin["digest"]}
        assert bf.capture_already_landed(meta, pin) is True

    def test_a_replaced_bulletin_relands(self):
        """A NEW capture of the same URL means UNICA replaced the file -- must not skip."""
        pin = _pin(timestamp="20260701000000", digest="NEWDIGEST")
        stale = {"wayback_capture_ts": _APRIL_TS, "cdx_digest": "OLDDIGEST"}
        assert bf.capture_already_landed(stale, pin) is False

    def test_bare_existence_is_not_enough_to_skip(self):
        """The defect this wave repairs: an object that exists but proves nothing about WHICH
        capture it holds must be re-verified, not skipped."""
        assert bf.capture_already_landed({"sha256": "abc", "file_size_bytes": 12}, _pin()) is False
        assert bf.capture_already_landed(None, _pin()) is False
        assert bf.capture_already_landed({}, _pin()) is False

    def test_byte_identical_content_skips_the_put(self):
        """Re-uploading identical bytes bumps LastModified and would force a pointless bronze
        rebuild through the staleness fence."""
        payload = _real_pdf()
        meta = {"sha256": hashlib.sha256(payload).hexdigest()}
        assert bf.payload_unchanged(meta, payload) is True
        assert bf.payload_unchanged(meta, _real_pdf(b"different")) is False
        assert bf.payload_unchanged(None, payload) is False


class TestBronzeSkipBehaviour:
    """jobs/batch/unica_biweekly_task -- staleness, not existence."""

    @staticmethod
    def _task():
        return pytest.importorskip("jobs.batch.unica_biweekly_task")

    class _S3:
        """head_object over a {key: LastModified} table; absent keys raise like S3 does."""

        def __init__(self, table):
            self.table = table

        def head_object(self, Bucket=None, Key=None, **_kw):  # noqa: N803 -- boto3 kwarg casing
            if Key not in self.table:
                raise RuntimeError("404")
            return {"LastModified": self.table[Key]}

    def _table(self, raw_key, raw_at, bronze_at):
        task = self._task()
        table = {raw_key: raw_at}
        if bronze_at is not None:
            for name in task._OUTPUT_TABLES:
                key = task.bronze_unica_biweekly_key("2026_2027", "pdf_x", name)
                table[key] = bronze_at
        return table

    def test_fresh_bronze_over_untouched_raw_skips(self):
        task = self._task()
        raw = "raw/production/source=unica_biweekly/harvest_year=2026_2027/idm=pdf_x/report.pdf"
        s3 = self._S3(self._table(raw, dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
                                  dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc)))
        assert task._all_bronze_current(s3, "b", raw, "2026_2027", "pdf_x",
                                        task._OUTPUT_TABLES) is True

    def test_relanded_raw_forces_a_rebuild(self):
        """THE repair: the wayback backfill re-lands a PDF, bronze must NOT skip it."""
        task = self._task()
        raw = "raw/production/source=unica_biweekly/harvest_year=2026_2027/idm=pdf_x/report.pdf"
        s3 = self._S3(self._table(raw, dt.datetime(2026, 8, 18, tzinfo=dt.timezone.utc),
                                  dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc)))
        assert task._all_bronze_current(s3, "b", raw, "2026_2027", "pdf_x",
                                        task._OUTPUT_TABLES) is False

    def test_a_single_missing_output_table_rebuilds_all(self):
        task = self._task()
        raw = "raw/production/source=unica_biweekly/harvest_year=2026_2027/idm=pdf_x/report.pdf"
        table = self._table(raw, dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
                            dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc))
        del table[task.bronze_unica_biweekly_key("2026_2027", "pdf_x", task._OUTPUT_TABLES[-1])]
        assert task._all_bronze_current(self._S3(table), "b", raw, "2026_2027", "pdf_x",
                                        task._OUTPUT_TABLES) is False

    def test_the_harvest_year_filter_follows_the_relabel(self):
        """A "--harvest-year 2026_2027" backfill must still reach idm=32820684, whose raw object
        sits under 2025_2026 -- otherwise the scoped re-run silently drops the one bulletin the
        whole repair is about."""
        task = self._task()
        quarantined = ("raw/production/source=unica_biweekly/harvest_year=2025_2026/"
                       "idm=32820684/report.pdf")
        sibling = ("raw/production/source=unica_biweekly/harvest_year=2025_2026/"
                   "idm=pdf_other/report.pdf")

        def in_target(key, hy):
            recorded = task.parse_hive_key(key, "harvest_year")
            idm = task.parse_hive_key(key, "idm")
            return hy in {recorded, corrected_season(idm, recorded)}

        assert in_target(quarantined, "2026_2027") is True
        assert in_target(sibling, "2026_2027") is False
        assert in_target(sibling, "2025_2026") is True

    def test_an_unreadable_raw_mtime_fails_toward_rebuilding(self):
        """The fence must never fail toward the silent no-op it exists to kill."""
        task = self._task()
        raw = "raw/production/source=unica_biweekly/harvest_year=2026_2027/idm=pdf_x/report.pdf"
        table = self._table(raw, dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
                            dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc))
        del table[raw]
        assert task._all_bronze_current(self._S3(table), "b", raw, "2026_2027", "pdf_x",
                                        task._OUTPUT_TABLES) is False


# ===========================================================================
# 5. RUN GATING -- a backfill that achieves nothing must not exit 0
# ===========================================================================

class TestRunGating:
    def test_zero_candidates_refuses(self):
        reason = bf.exit_reason(0, 0, 0, 0, candidates=0)
        assert reason and reason.startswith("ZERO CANDIDATES")

    def test_zero_candidates_can_be_accepted_explicitly(self):
        assert bf.exit_reason(0, 0, 0, 0, candidates=0, allow_empty=True) is None

    def test_errors_fail_the_run(self):
        assert "2 capture(s) failed" in bf.exit_reason(1, 0, 0, 2, candidates=3)

    def test_all_refused_and_nothing_landed_fails(self):
        reason = bf.exit_reason(0, 0, 3, 0, candidates=3)
        assert reason and "REFUSED" in reason

    def test_a_refusal_alongside_real_progress_stays_green(self):
        assert bf.exit_reason(2, 0, 1, 0, candidates=3) is None

    def test_a_fully_skipped_rerun_stays_green(self):
        assert bf.exit_reason(0, 4, 0, 0, candidates=4) is None
