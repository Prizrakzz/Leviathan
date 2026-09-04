"""G-B6, AS A STRUCTURAL PIN: the archive backfill cannot reach the served chain.

THE WHOLE SERVED-SET SAFETY ARGUMENT OF LANE (b) IS THIS FILE.  The backfill lands historical
vintages that the served latest-only table has never seen.  If one of them reached
``jobs/batch/pink_sheet_task.py``'s relist, the 8th-of-month cron would bronze it UNGATED and the
served table could gain cells it currently holds NULL -- a widening nobody decided.

The remedy is NOT a runtime flag (a cron does not pass one) and NOT a gate inside a six-worker
thread pool (racy, and it reds the newest release by construction because its newer-set is empty).
It is a PREFIX: the two scheduled jobs each relist exactly ONE hard-coded prefix, and the archive
keys are string-disjoint from both.  The trailing slash is what makes that true --
``source=world_bank_pink_sheet/`` is not a prefix of ``source=world_bank_pink_sheet_archive/`` --
and this file asserts exactly that, plus the source-text pin that neither scheduled job has acquired
an archive symbol.

AWS-free: source text and pure key functions only.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from leviathan.storage import paths

_REPO = Path(__file__).resolve().parents[2]
_SCHEDULED_RAW_JOB = _REPO / "jobs" / "batch" / "pink_sheet_task.py"
_SCHEDULED_SILVER_JOB = _REPO / "jobs" / "batch" / "pink_sheet_silver_task.py"
_VINTAGES_JOB = _REPO / "jobs" / "batch" / "pink_sheet_vintages_task.py"
_ARCHIVE_JOB = _REPO / "jobs" / "batch" / "pink_sheet_archive_task.py"

_ARCHIVE_TOKEN = "world_bank_pink_sheet_archive"
_RELEASES = ["1960M01", "1998M07", "2016M03", "2025M01", "2026M01", "2026M09"]


@pytest.fixture(scope="module")
def scheduled_raw_prefix():
    import jobs.batch.pink_sheet_task as t
    return t._RAW_PREFIX


@pytest.fixture(scope="module")
def scheduled_bronze_prefix():
    import jobs.batch.pink_sheet_silver_task as t
    return t._BRONZE_PREFIX


class TestPrefixesAreDisjoint:
    def test_the_scheduled_prefixes_are_what_this_fence_assumes(
            self, scheduled_raw_prefix, scheduled_bronze_prefix):
        # Pinned literally: if either job's prefix ever moves, this fence's reasoning has to be
        # re-derived, and a silently-changed prefix must not slip through as "still disjoint".
        assert scheduled_raw_prefix == "raw/production/source=world_bank_pink_sheet/"
        assert scheduled_bronze_prefix == "bronze/production/source=world_bank_pink_sheet/"

    @pytest.mark.parametrize("release", _RELEASES)
    def test_an_archive_raw_key_is_not_under_the_scheduled_raw_prefix(
            self, release, scheduled_raw_prefix):
        key = paths.raw_pink_sheet_archive_key(release, "CMO-Historical-Data-Monthly.xlsx")
        assert not key.startswith(scheduled_raw_prefix)
        assert _ARCHIVE_TOKEN in key

    @pytest.mark.parametrize("release", _RELEASES)
    def test_an_archive_bronze_key_is_not_under_the_scheduled_bronze_prefix(
            self, release, scheduled_bronze_prefix):
        key = paths.bronze_pink_sheet_archive_key(release)
        assert not key.startswith(scheduled_bronze_prefix)
        assert _ARCHIVE_TOKEN in key

    def test_the_trailing_slash_is_load_bearing(self, scheduled_raw_prefix):
        """WITHOUT the trailing slash the two prefixes are NOT disjoint -- 'source=
        world_bank_pink_sheet' IS a prefix of 'source=world_bank_pink_sheet_archive'. This states
        the mechanism rather than leaving it implicit in a passing assertion above."""
        naked = scheduled_raw_prefix.rstrip("/")
        key = paths.raw_pink_sheet_archive_key("2025M01", "x.xlsx")
        assert key.startswith(naked)          # the trap, demonstrated
        assert not key.startswith(naked + "/")  # the slash is the fence

    def test_the_scheduled_and_archive_silver_objects_are_SIBLINGS_never_nested(self):
        """A flat table's recovery strategy is a bounded full relist under its own root, so a
        nested object would be swallowed by the parent's relist (the silver/psd vs
        silver/psd_attributes law)."""
        served = paths.silver_pink_sheet_key()
        vintages = paths.silver_pink_sheet_vintages_key()
        assert served == "silver/pink_sheet/part-000.parquet"
        assert vintages == "silver/pink_sheet_vintages/part-000.parquet"
        assert not vintages.startswith("silver/pink_sheet/")


class TestScheduledJobsCarryNoArchiveSymbol:
    @pytest.mark.parametrize("path", [_SCHEDULED_RAW_JOB, _SCHEDULED_SILVER_JOB])
    def test_no_archive_token_in_the_scheduled_job_source(self, path):
        """The source-text half. A scheduled job that so much as IMPORTS an archive helper is one
        edit away from relisting it, and this pin is what makes that edit loud."""
        text = path.read_text(encoding="utf-8")
        assert _ARCHIVE_TOKEN not in text, (
            f"{path.name} has acquired an archive symbol -- the backfill is now one line from "
            f"reaching the served chain, and the widen decision would be made by accident")
        assert "pink_sheet_archive_key" not in text

    def test_the_vintages_task_is_the_ONE_place_the_two_prefixes_meet(self):
        text = _VINTAGES_JOB.read_text(encoding="utf-8")
        assert "bronze/production/source=world_bank_pink_sheet/" in text
        assert "bronze/production/source=world_bank_pink_sheet_archive/" in text

    def test_the_task_declares_the_ORIGIN_of_every_frame_it_reads(self):
        """The cross-prefix collision is adjudicated by ORIGIN, and the row cannot supply it: the
        archive bronze is written by the SAME shipped extractor, so every row of BOTH prefixes
        carries source == 'world_bank_pink_sheet'. Only this task knows, because only this task
        listed the two prefixes apart -- so the origins list is built here or nowhere."""
        import jobs.batch.pink_sheet_vintages_task as v
        from leviathan.transforms.bronze_to_silver import pink_sheet as P
        text = _VINTAGES_JOB.read_text(encoding="utf-8")
        assert "origins=origins" in text
        assert f"[{'ORIGIN_SCHEDULED'}] * len(scheduled_keys)" in text
        assert f"[{'ORIGIN_ARCHIVE'}] * len(archive_keys)" in text
        assert (v.ORIGIN_SCHEDULED, v.ORIGIN_ARCHIVE) == (P.ORIGIN_SCHEDULED, P.ORIGIN_ARCHIVE)


class TestTheClockSidecarRead:
    """Rung 1 of the release-clock ladder is reachable ONLY from here.

    The origin's HTTP Last-Modified is recorded AT CAPTURE into raw_meta and exists nowhere else --
    bronze carries no clock column. Before this read the producer called release_clock with no
    header at all, so release_date_source was the constant 'derived_month_first' on every row of
    every vintage and the ladder's origin/archive distinction was unmeasurable.
    """

    @staticmethod
    def _fake_s3(records):
        class _Body:
            def __init__(self, raw):
                self._raw = raw

            def read(self):
                return self._raw

        class _S3:
            def get_object(self, Bucket, Key):  # noqa: N803 -- boto3's own casing
                import json as _json
                return {"Body": _Body(_json.dumps(records[Key]).encode())}
        return _S3()

    def test_the_sidecar_prefixes_are_the_raw_prefixes_under_raw_meta(self):
        import jobs.batch.pink_sheet_vintages_task as v
        assert v._RAW_META_PREFIX == "raw_meta/raw/production/source=world_bank_pink_sheet/"
        assert v._RAW_META_ARCHIVE_PREFIX == (
            "raw_meta/raw/production/source=world_bank_pink_sheet_archive/")
        assert v._RAW_META_PREFIX == "raw_meta/" + paths.raw_pink_sheet_key("X", "y").split(
            "release=")[0]

    def test_the_scheduled_header_reaches_rung_1_and_the_archive_uses_the_ORIGIN_field(
            self, monkeypatch):
        import jobs.batch.pink_sheet_vintages_task as v
        sched = paths.raw_pink_sheet_key("2026M09", "cmo.xlsx")
        arch = paths.raw_pink_sheet_archive_key("2019M04", "cmo.xlsx")
        records = {
            f"raw_meta/{sched}_meta.json": {"http_last_modified": "Tue, 02 Sep 2026 11:00:00 GMT"},
            # LAW 4: the archive record's own `http_last_modified` is the ARCHIVE's clock and must
            # never reach rung 1; only `origin_last_modified` may.
            f"raw_meta/{arch}_meta.json": {"http_last_modified": "Fri, 01 Mar 2024 00:00:00 GMT",
                                           "origin_last_modified": "Mon, 08 Apr 2019 06:00:00 GMT"},
        }
        monkeypatch.setattr(v, "list_s3_keys", lambda bucket, prefix, **kw: [
            k for k in records if k.startswith(prefix)])
        clocks = v.read_release_clocks(self._fake_s3(records), "B", "us-east-1")
        assert clocks["2026M09"] == {
            "http_last_modified": "Tue, 02 Sep 2026 11:00:00 GMT", "archive": False,
            "raw_meta_key": f"raw_meta/{sched}_meta.json"}
        assert clocks["2019M04"]["http_last_modified"] == "Mon, 08 Apr 2019 06:00:00 GMT"
        assert clocks["2019M04"]["archive"] is True

    def test_an_ORIGIN_PHASE_archive_capture_reaches_rung_1_through_origin_last_modified(
            self, monkeypatch):
        """THE RE-REVIEW MAJOR (2026-09-04): the backfill's PHASE 0 (retired document-ID epochs) is
        a real origin fetch, but it recorded the header only as `http_last_modified`, which LAW 4
        deliberately ignores on the archive prefix -- so every pre-Wayback vintage silently took
        rung 2 while its own sidecar said `origin_last_modified`. The origin phase now writes the
        header under BOTH keys; this pins the origin-phase sidecar SHAPE, not only the Wayback one."""
        import jobs.batch.pink_sheet_vintages_task as v
        arch = paths.raw_pink_sheet_archive_key("2016M08", "cmo.xlsx")
        records = {
            f"raw_meta/{arch}_meta.json": {
                "capture_kind": "origin_retired_epoch", "backfill_phase": "origin",
                "http_last_modified": "Thu, 04 Aug 2016 14:22:00 GMT",
                "origin_last_modified": "Thu, 04 Aug 2016 14:22:00 GMT",
                "release_date_source": "origin_last_modified"},
        }
        monkeypatch.setattr(v, "list_s3_keys", lambda bucket, prefix, **kw: [
            k for k in records if k.startswith(prefix)])
        clocks = v.read_release_clocks(self._fake_s3(records), "B", "us-east-1")
        assert clocks["2016M08"]["archive"] is True
        assert clocks["2016M08"]["http_last_modified"] == "Thu, 04 Aug 2016 14:22:00 GMT"
        # and the producer takes rung 1 from it, never the archive fallback
        from leviathan.transforms.bronze_to_silver import pink_sheet as ps
        from leviathan.common import pink_sheet_release as R
        assert R.release_clock("2016M08", http_last_modified=clocks["2016M08"]["http_last_modified"],
                               archive=True) == ("2016-08-04", R.SOURCE_ORIGIN_LAST_MODIFIED)

    def test_the_SCHEDULED_sidecar_wins_when_both_prefixes_describe_one_release(
            self, monkeypatch):
        import jobs.batch.pink_sheet_vintages_task as v
        sched = paths.raw_pink_sheet_key("2026M05", "cmo.xlsx")
        arch = paths.raw_pink_sheet_archive_key("2026M05", "cmo.xlsx")
        records = {
            f"raw_meta/{sched}_meta.json": {"http_last_modified": "Mon, 04 May 2026 09:00:00 GMT"},
            f"raw_meta/{arch}_meta.json": {"origin_last_modified": "Tue, 05 May 2026 09:00:00 GMT"},
        }
        monkeypatch.setattr(v, "list_s3_keys", lambda bucket, prefix, **kw: [
            k for k in records if k.startswith(prefix)])
        clocks = v.read_release_clocks(self._fake_s3(records), "B", "us-east-1")
        assert clocks["2026M05"]["archive"] is False
        assert clocks["2026M05"]["http_last_modified"] == "Mon, 04 May 2026 09:00:00 GMT"

    def test_an_UNREADABLE_sidecar_is_an_absence_and_never_a_crash(self, monkeypatch):
        """write_raw_s3_metadata is best-effort and never re-raises, so a correctly landed object
        can legitimately have no sidecar. That release takes rung 2 -- declared by being absent
        from the mapping, never guessed at."""
        import jobs.batch.pink_sheet_vintages_task as v
        key = f"raw_meta/{paths.raw_pink_sheet_key('2026M09', 'cmo.xlsx')}_meta.json"

        class _Broken:
            def get_object(self, Bucket, Key):  # noqa: N803
                raise RuntimeError("NoSuchKey")

        monkeypatch.setattr(v, "list_s3_keys", lambda bucket, prefix, **kw: (
            [key] if prefix == v._RAW_META_PREFIX else []))
        assert v.read_release_clocks(_Broken(), "B", "us-east-1") == {}

    def test_a_failed_LISTING_is_an_absence_too(self, monkeypatch):
        import jobs.batch.pink_sheet_vintages_task as v

        def _boom(bucket, prefix, **kw):
            raise RuntimeError("AccessDenied")

        monkeypatch.setattr(v, "list_s3_keys", _boom)
        assert v.read_release_clocks(None, "B", "us-east-1") == {}

    def test_the_archive_task_writes_only_under_the_archive_bronze_prefix(self):
        import jobs.batch.pink_sheet_archive_task as a
        assert a._RAW_PREFIX == "raw/production/source=world_bank_pink_sheet_archive/"
        assert a._BRONZE_PREFIX == "bronze/production/source=world_bank_pink_sheet_archive/"
        # it READS the scheduled bronze -- as the census's comparison set only -- and never writes
        # a key derived from it.
        assert a._SCHEDULED_BRONZE_PREFIX == "bronze/production/source=world_bank_pink_sheet/"
        text = _ARCHIVE_JOB.read_text(encoding="utf-8")
        assert "bronze_pink_sheet_key" not in text, (
            "the archive task must key bronze through bronze_pink_sheet_ARCHIVE_key only")

    def test_the_shipped_key_helpers_were_not_parameterized(self):
        """Parameterizing raw_pink_sheet_key / bronze_pink_sheet_key / silver_pink_sheet_key would
        change a call signature on the SERVED path. The archive gets its OWN three helpers instead;
        the shipped three still take exactly what they always took."""
        import inspect
        assert list(inspect.signature(paths.raw_pink_sheet_key).parameters) == [
            "release_ym", "filename"]
        assert list(inspect.signature(paths.bronze_pink_sheet_key).parameters) == ["release_ym"]
        assert list(inspect.signature(paths.silver_pink_sheet_key).parameters) == []
        assert list(inspect.signature(paths.silver_pink_sheet_vintages_key).parameters) == []


class TestServedSetCensus:
    """The counted half of G-B6. A report, never a runtime refusal -- under the prefix fence an
    archived vintage cannot reach the served table at all, so what the census produces is the
    OWNER's widen-or-refuse input."""

    @staticmethod
    def _frame(release, keys):
        import pandas as pd
        return pd.DataFrame([{"release_ym": release, "date": d, "series_name": s,
                              "value_usd": 1.0} for d, s in keys])

    def test_zero_extras_when_every_key_survives_into_a_newer_release(self):
        from jobs.batch.pink_sheet_archive_task import served_set_census
        keys = [("1998-01-01", "urea_usd_mt"), ("1998-02-01", "urea_usd_mt")]
        report = served_set_census(
            {"1998M03": self._frame("1998M03", keys)},
            {"2026M09": self._frame("2026M09", keys)},
        )
        assert report["total_extra_keys"] == 0
        assert report["releases"][0]["extra_governed_keys"] == 0
        assert "declined" not in report["releases"][0]

    def test_a_dropped_series_is_reported_with_its_month_RANGE(self):
        """A bare count does not name a finding. The range does."""
        from jobs.batch.pink_sheet_archive_task import served_set_census
        old = [("1998-01-01", "urea_usd_mt"), ("1998-02-01", "urea_usd_mt"),
               ("1998-01-01", "lamb_usd_t"), ("1998-06-01", "lamb_usd_t")]
        new = [("1998-01-01", "urea_usd_mt"), ("1998-02-01", "urea_usd_mt")]
        report = served_set_census(
            {"1998M07": self._frame("1998M07", old)},
            {"2026M09": self._frame("2026M09", new)},
        )
        assert report["total_extra_keys"] == 2
        extras = report["releases"][0]["extras_by_series"]
        assert extras["lamb_usd_t"] == {"n": 2, "first": "1998-01-01", "last": "1998-06-01"}

    def test_a_release_with_no_newer_scheduled_release_DECLARES_rather_than_reporting_zero(self):
        """ABSENT IS NEVER ZERO. An empty comparison set makes '0 extras' an unmeasured claim, not
        a finding, so the census says so in words."""
        from jobs.batch.pink_sheet_archive_task import served_set_census
        keys = [("2026-08-01", "urea_usd_mt")]
        report = served_set_census(
            {"2026M09": self._frame("2026M09", keys)},
            {"2026M05": self._frame("2026M05", keys)},
        )
        entry = report["releases"][0]
        assert entry["compared_against_newer_scheduled"] == []
        assert entry["extra_governed_keys"] == 0
        assert "UNMEASURED" in entry["declined"]
