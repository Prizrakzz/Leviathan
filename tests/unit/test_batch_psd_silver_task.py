"""Unit tests for the USDA PSD silver Batch task (F2 guard + A-W4 CLASS-B retrofit).

The F2 fail-closed release_date guard is exercised directly (pure Python, no S3/AWS): it is the
belt-and-suspenders check that aborts the run if the silver transform's clamp is ever bypassed
and a future-dated row survives to the write.

The A-W4 retrofit routes the flat ``silver_psd`` write through the shadow-first publisher via
``build_flat_publish``; ``--publish-mode`` defaults to dry-run (nothing written). Those tests
exercise ``_publish_psd`` directly with injected guard verdicts, proving the three-mode INV-6
contract.

The D-SG G1-1b bounded-input rider (drop bronze partitions whose RAW vendor zip duplicates a
newer one) is exercised on synthetic ETag sets: the SELECTION is unit-testable here, while the
claim that the selection cannot change the silver output is the separate live-bronze proof
``jobs/utils/psd_dedup_proof.py``.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_psd_key
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_SLUGS,
    _SILVER_COLS,
)

from jobs.batch import psd_silver_task as task
from jobs.utils import psd_dedup_proof as proof
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_INGEST = "2026-05-20"

_CONTRACT = load_registry().table("silver_psd")
_BUCKET = _CONTRACT["s3_bucket"]          # where build_flat_publish writes (contract-pinned)
_SENTINEL = b"OLD-CANONICAL-PSD"


def _silver_df() -> pd.DataFrame:
    """One full 18-column canonical silver row -- every value column NON-NULL so the fixture clears
    every V001 floor. W0-2 (projection wave, 2026-08-25) promoted the four derived columns into
    value_columns with measured floors (su_ratio_yoy_delta 0.60; the three revisions 0.025); the old
    all-None tail read 0.0 non-null and failed the publish gate on a frame nobody meant to test."""
    return pd.DataFrame([{
        "leviathan_slug": "corn_cbot", "country": "united_states",
        "market_year": 2024, "wasde_release_month": 5, "release_date": "2026-05-10",
        "beginning_stocks_mt": 40.0, "production_mt": 380.0, "imports_mt": 1.0,
        "exports_mt": 60.0, "ending_stocks_mt": 45.0, "consumption_mt": 310.0,
        "area_harvested_1000ha": 33000.0, "yield_mt_ha": 11.5, "su_ratio": 0.145,
        "su_ratio_yoy_delta": -0.012, "production_mt_revision": 2.0,
        "ending_stocks_mt_revision": -1.0, "consumption_mt_revision": 0.5,
    }])


def _silver(release_dates: list[str]) -> pd.DataFrame:
    """Minimal silver frame carrying only the column the guard inspects."""
    return pd.DataFrame({
        "leviathan_slug": ["corn_cbot"] * len(release_dates),
        "release_date":   release_dates,
    })


def _bronze(release_date: str = _INGEST) -> pd.DataFrame:
    return pd.DataFrame({
        "commodity_code": [440000],
        "release_date":   [release_date],
    })


# ---------------------------------------------------------------------------
# TestSnapshotIngestDate
# ---------------------------------------------------------------------------

class TestSnapshotIngestDate:
    def test_single_partition(self) -> None:
        assert task._snapshot_ingest_date([_bronze("2026-05-20")]) == "2026-05-20"

    def test_newest_across_partitions(self) -> None:
        dfs = [_bronze("2026-01-15"), _bronze("2026-05-20"), _bronze("2025-11-01")]
        assert task._snapshot_ingest_date(dfs) == "2026-05-20"

    def test_no_release_dates_raises(self) -> None:
        with pytest.raises(ValueError, match="no bronze release_date"):
            task._snapshot_ingest_date([pd.DataFrame({"commodity_code": [440000]})])


# ---------------------------------------------------------------------------
# TestReleaseDateGuard
# ---------------------------------------------------------------------------

class TestReleaseDateGuard:
    def test_all_historical_passes(self) -> None:
        # Dates at/below the snapshot must not raise.
        task._assert_release_dates_not_future(
            _silver(["2001-01-10", "1990-01-01", _INGEST]), _INGEST
        )

    def test_equal_to_ingest_passes(self) -> None:
        # A row clamped exactly to the ingest date is allowed (not "future").
        task._assert_release_dates_not_future(_silver([_INGEST]), _INGEST)

    def test_future_row_raises(self) -> None:
        """A fabricated future date (clamp bypassed) must abort the producer."""
        fabricated = _silver(["2001-01-10", "2027-03-10"])
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(fabricated, _INGEST)

    def test_future_row_message_names_count_and_example(self) -> None:
        fabricated = _silver(["2027-03-10", "2027-01-10"])
        with pytest.raises(ValueError) as exc:
            task._assert_release_dates_not_future(fabricated, _INGEST)
        msg = str(exc.value)
        assert "2 release_date" in msg          # count reported
        assert "2027-01-10" in msg              # sorted example surfaced
        assert _INGEST in msg                   # the bound reported

    def test_empty_silver_is_noop(self) -> None:
        task._assert_release_dates_not_future(_silver([]), _INGEST)


# ---------------------------------------------------------------------------
# TestGuardEndToEnd
# ---------------------------------------------------------------------------

class TestGuardEndToEnd:
    def test_snapshot_bound_then_guard_flags_bypass(self) -> None:
        """Derive the bound from bronze, then a bypassed future row trips the guard."""
        ingest = task._snapshot_ingest_date([_bronze(_INGEST)])
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(_silver(["2027-03-10"]), ingest)


# ---------------------------------------------------------------------------
# TestShadowFirstPublish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

class TestShadowFirstPublish:
    def test_silver_columns_match_contract(self) -> None:
        contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
        assert _SILVER_COLS == contract_cols

    def test_dry_run_writes_nothing_but_validates(self) -> None:
        # main() passes s3_client=None in dry-run; the plan reaches VALIDATED with nothing written.
        state = task._publish_psd(_silver_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET,
                                  force_overwrite=True)
        assert state is ManifestState.VALIDATED

    def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_key()
        s3.store[(_BUCKET, canonical_key)] = _SENTINEL          # pre-seed a canonical sentinel
        etag_before = s3._etag(_SENTINEL)

        state = task._publish_psd(_silver_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

        assert state is ManifestState.VALIDATED
        assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL              # canonical untouched
        assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before  # etag identical
        assert any("_shadow" in k for k in s3.keys())                      # staged under _shadow/
        # every data object other than canonical + the control-plane manifest lives under _shadow/
        for _, key in s3.store:
            if key == canonical_key or "/_manifests/" in key:
                continue
            assert "/_shadow/" in key

    def test_canonical_overwrites_the_psd_silver_object(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_key()
        s3.store[(_BUCKET, canonical_key)] = _SENTINEL

        state = task._publish_psd(_silver_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

        assert state is ManifestState.CERTIFIED
        assert (_BUCKET, canonical_key) in s3.store
        assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL   # canonical overwritten


# ---------------------------------------------------------------------------
# TestBronzeEtagDedup (D-SG G1-1b bounded-input rider)
# ---------------------------------------------------------------------------

_RAW_KEY = task._RAW_BULK_PREFIX + "release_date=%s/psd_alldata.zip"

# The LIVE shape, 2026-08-16: 8 raw zips, 4 distinct ETags (08-08..08-11 identical,
# 08-12/08-13 identical). The newest label of each pair is the one the rider keeps.
_LIVE_ETAGS = {
    "2026-05-20": "a16b789ec80f27605e755418f7026a8b",
    "2026-07-17": "39762f232a748acf15cd3d28f5dd8287",
    "2026-08-08": "d085f3d1a6048cedcbc9b5df94e07b21",
    "2026-08-09": "d085f3d1a6048cedcbc9b5df94e07b21",
    "2026-08-10": "d085f3d1a6048cedcbc9b5df94e07b21",
    "2026-08-11": "d085f3d1a6048cedcbc9b5df94e07b21",
    "2026-08-12": "bd5be5458e069a6f8ccc260acfff4b4f",
    "2026-08-13": "bd5be5458e069a6f8ccc260acfff4b4f",
}


class _FakePaginator:
    """Two-page ListObjectsV2 so the rider's pagination is exercised, not assumed."""

    def __init__(self, contents: list[dict], raiser: Exception | None = None):
        self._contents = contents
        self._raiser = raiser

    def paginate(self, **kw):
        if self._raiser is not None:
            raise self._raiser
        half = (len(self._contents) + 1) // 2
        for page in (self._contents[:half], self._contents[half:]):
            yield {"Contents": page} if page else {}


class _FakeListS3:
    def __init__(self, etags: dict[str, str], raiser: Exception | None = None):
        self.contents = [
            # ETags come back from S3 quoted; the rider must strip the quotes.
            {"Key": _RAW_KEY % label, "ETag": '"%s"' % etag}
            for label, etag in sorted(etags.items())
        ]
        self._raiser = raiser

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _FakePaginator(self.contents, self._raiser)


def _bronze_keys(labels: list[str]) -> list[str]:
    return [
        "bronze/production/source=usda_psd/release_date=%s/part-000.parquet" % label
        for label in labels
    ]


class TestDistinctReleaseDates:
    def test_newest_label_wins_per_etag(self) -> None:
        keep, seen = task._distinct_release_dates(_FakeListS3(_LIVE_ETAGS), _BUCKET)
        assert keep == {"2026-05-20", "2026-07-17", "2026-08-11", "2026-08-13"}
        assert seen == set(_LIVE_ETAGS)

    def test_distinct_etags_are_all_kept(self) -> None:
        etags = {"2026-06-10": "aaa", "2026-07-10": "bbb", "2026-08-10": "ccc"}
        keep, seen = task._distinct_release_dates(_FakeListS3(etags), _BUCKET)
        assert keep == set(etags)
        assert seen == set(etags)

    def test_empty_prefix_returns_none(self) -> None:
        # Nothing to compare -> keep everything, which is what None means downstream.
        keep, seen = task._distinct_release_dates(_FakeListS3({}), _BUCKET)
        assert keep is None
        assert seen == set()

    def test_keys_without_a_release_date_are_ignored(self) -> None:
        fake = _FakeListS3({"2026-08-13": "aaa"})
        fake.contents.append({"Key": task._RAW_BULK_PREFIX + "manifest.json", "ETag": '"zzz"'})
        keep, _seen = task._distinct_release_dates(fake, _BUCKET)
        assert keep == {"2026-08-13"}

    def test_listing_failure_degrades_to_keep_everything(self) -> None:
        fake = _FakeListS3(_LIVE_ETAGS, raiser=RuntimeError("AccessDenied"))
        keep, seen = task._distinct_release_dates(fake, _BUCKET)
        assert keep is None
        assert seen == set()


class TestLoadBronzeDedup:
    @staticmethod
    def _patch(monkeypatch, labels: list[str]) -> list[str]:
        loaded: list[str] = []
        monkeypatch.setattr(task, "list_s3_keys", lambda *a, **kw: _bronze_keys(labels))
        monkeypatch.setattr(
            task, "_download_parquet",
            lambda _c, _b, key: loaded.append(key) or pd.DataFrame({"release_date": [key]}),
        )
        return loaded

    def test_eight_partitions_collapse_to_four(self, monkeypatch, caplog) -> None:
        loaded = self._patch(monkeypatch, sorted(_LIVE_ETAGS))
        with caplog.at_level("INFO", logger="psd_silver_task"):
            dfs = task._load_bronze(_BUCKET, "us-east-1", _FakeListS3(_LIVE_ETAGS))
        assert len(dfs) == 4
        assert [k.split("release_date=")[1][:10] for k in loaded] == [
            "2026-05-20", "2026-07-17", "2026-08-11", "2026-08-13"
        ]
        # The drop is loud, and it says how many and why.
        assert "bronze dedup by raw ETag: 4 of 8 partitions" in caplog.text
        assert "skipping 4 re-download(s)" in caplog.text

    def test_a_bronze_partition_with_no_raw_counterpart_is_kept(self, monkeypatch, caplog) -> None:
        """Review M-2: the dedup may only drop a partition raw PROVES is an older copy.

        A bronze partition whose raw zip is gone (raw lifecycle expiry, hand-delete,
        bronze-without-raw) has nothing to judge it a duplicate BY -- dropping it would
        silently truncate the input of a self-promoting canonical transform.
        """
        labels = sorted(_LIVE_ETAGS) + ["2026-04-15"]  # orphan: bronze exists, raw does not
        loaded = self._patch(monkeypatch, labels)
        with caplog.at_level("INFO", logger="psd_silver_task"):
            dfs = task._load_bronze(_BUCKET, "us-east-1", _FakeListS3(_LIVE_ETAGS))
        assert len(dfs) == 5  # the 4 distinct releases + the orphan, KEPT
        assert any("2026-04-15" in k for k in loaded)
        assert "no raw counterpart and are KEPT" in caplog.text
        assert "'2026-04-15'" in caplog.text or "2026-04-15" in caplog.text

    def test_distinct_etags_load_every_partition(self, monkeypatch, caplog) -> None:
        etags = {"2026-06-10": "aaa", "2026-07-10": "bbb", "2026-08-10": "ccc"}
        loaded = self._patch(monkeypatch, sorted(etags))
        with caplog.at_level("INFO", logger="psd_silver_task"):
            dfs = task._load_bronze(_BUCKET, "us-east-1", _FakeListS3(etags))
        assert len(dfs) == len(loaded) == 3
        # Behaviour is unchanged and the accounting line says so out loud.
        assert "bronze dedup by raw ETag: 3 of 3 partitions" in caplog.text
        assert "skipping 0 re-download(s)" in caplog.text

    def test_unreadable_raw_prefix_loads_every_partition(self, monkeypatch) -> None:
        loaded = self._patch(monkeypatch, sorted(_LIVE_ETAGS))
        fake = _FakeListS3(_LIVE_ETAGS, raiser=RuntimeError("AccessDenied"))
        assert len(task._load_bronze(_BUCKET, "us-east-1", fake)) == 8
        assert len(loaded) == 8

    def test_selection_that_matches_nothing_loads_every_partition(self, monkeypatch) -> None:
        """A raw prefix that shares no label with bronze must not empty the load."""
        loaded = self._patch(monkeypatch, ["2026-05-20", "2026-07-17"])
        fake = _FakeListS3({"2020-01-01": "aaa"})
        assert len(task._load_bronze(_BUCKET, "us-east-1", fake)) == 2
        assert len(loaded) == 2


class TestProofHarnessHash:
    """The live-bronze proof's verdict is only worth its hash: row-order blind, value-aware."""

    def test_row_order_does_not_change_the_hash(self) -> None:
        df = pd.concat([_silver_df(), _silver_df().assign(market_year=2025)], ignore_index=True)
        assert proof._frame_hash(df) == proof._frame_hash(df.iloc[::-1])

    def test_a_changed_value_changes_the_hash(self) -> None:
        df = _silver_df()
        assert proof._frame_hash(df) != proof._frame_hash(df.assign(production_mt=381.0))

    def test_a_dropped_row_changes_the_hash(self) -> None:
        df = pd.concat([_silver_df(), _silver_df().assign(market_year=2025)], ignore_index=True)
        assert proof._frame_hash(df) != proof._frame_hash(df.head(1))


# ---------------------------------------------------------------------------
# P19 / T14 -- THE CALENDAR IS READ FROM PARTITIONS, AND THE COUNTERS ARE LOGGED
# ---------------------------------------------------------------------------

class _FakeGlue:
    """A get_partitions paginator over a supplied release_date list."""

    def __init__(self, values: list[str]) -> None:
        self._values = values
        self.calls: list[dict] = []

    def get_paginator(self, name: str):
        assert name == "get_partitions", "the calendar must come from get_partitions"
        outer = self

        class _P:
            def paginate(self, **kwargs):
                outer.calls.append(kwargs)
                yield {"Partitions": [{"Values": [v]} for v in outer._values]}

        return _P()


class TestTheCalendarIsReadFromRegisteredPartitions:
    """F5's fence: the clock's calendar is LIVE, never baked into the worker image.

    silver_wasde's newest partition and the newest PSD stamp advance in LOCKSTEP
    every month and psd_monthly fires cron(0 18 8-13 * ? *), so a calendar frozen
    at image-build time would make the clock's fail-closed raise RED-STOP the DAG
    every month until a new image, a terraform digest bump and a jobdef
    re-register had landed. A one-time build step cannot be a monthly mechanism.
    """

    def test_it_reads_get_partitions_and_never_MSCK(self) -> None:
        glue = _FakeGlue(["2026-06-11", "2026-07-10", "2026-08-12"])
        cal = task.wasde_release_calendar("us-east-1", glue_client=glue)
        assert cal == {"2026-06": 11, "2026-07": 10, "2026-08": 12}
        assert glue.calls and glue.calls[0]["TableName"] == "silver_wasde"
        assert glue.calls[0]["DatabaseName"] == \
            load_registry().table("silver_wasde")["glue_database"]

    def test_an_empty_catalog_answer_RAISES(self) -> None:
        with pytest.raises(ValueError, match="NO registered partitions"):
            task.wasde_release_calendar("us-east-1", glue_client=_FakeGlue([]))

    def test_two_releases_in_one_month_take_the_LATER_day_and_say_so(self, caplog) -> None:
        glue = _FakeGlue(["2008-10-10", "2008-10-28"])
        with caplog.at_level("WARNING"):
            cal = task.wasde_release_calendar("us-east-1", glue_client=glue)
        assert cal == {"2008-10": 28}
        assert "TWO releases" in caplog.text

    def test_the_task_does_not_import_a_generated_calendar_module(self) -> None:
        """The generated calendar is a TEST FIXTURE and nothing else."""
        import inspect

        src = inspect.getsource(task)
        assert "gen_wasde_release_calendar" not in src
        assert "get_partitions" in src

    def test_every_declared_counter_reaches_the_structured_log(self, caplog) -> None:
        """A counter that lives only in a prose log line is not a gate reading."""
        import json as _json

        from leviathan.transforms.bronze_to_silver.usda_psd import _CLOCK_COUNTER_KEYS

        with caplog.at_level("INFO"):
            task.log_clock_counters({k: 1 for k in _CLOCK_COUNTER_KEYS})
        line = next(m for m in caplog.messages if m.startswith("PSD_CLOCK_COUNTERS "))
        payload = _json.loads(line[len("PSD_CLOCK_COUNTERS "):])
        assert set(payload) == set(_CLOCK_COUNTER_KEYS)

    def test_a_missing_counter_is_reported_as_absent_never_as_zero(self, caplog) -> None:
        """Absence is declared, not defaulted -- a 0 would read as a measurement."""
        import json as _json

        from leviathan.transforms.bronze_to_silver.usda_psd import _CLOCK_COUNTER_KEYS

        with caplog.at_level("INFO"):
            task.log_clock_counters({"n_clamped": 0})
        line = next(m for m in caplog.messages if m.startswith("PSD_CLOCK_COUNTERS "))
        payload = _json.loads(line[len("PSD_CLOCK_COUNTERS "):])
        assert payload["n_clamped"] == 0
        assert payload["n_reprints_under_shipped_key"] is None
        assert set(payload) == set(_CLOCK_COUNTER_KEYS)


# ---------------------------------------------------------------------------
# THE SAME-CRON RACE WITH wasde_monthly, AND ITS BOUNDED WAIT
#
# psd_monthly and wasde_monthly BOTH fire cron(0 18 8-13 * ? *) with NO ordering
# dependency, and the clock FAILS CLOSED on a stamp month newer than the newest
# REGISTERED silver_wasde partition. The vendor's PSD object flips content ON the
# WASDE day (this task's own ETag measurement: 08-08/09/10/11 share one ETag,
# 08-12/13 the next, with 2026-08-12 the registered day), so once a month the new
# PSD file can be in the bucket before the sibling chain has registered.
#
# The answer is a BOUNDED WAIT, not a weaker raise: 90 minutes, polled every 5,
# then fail closed exactly as before. These pins drive it with a FAKE partitions
# client and a FAKE sleep, so no wall-clock time and no AWS is involved.
# ---------------------------------------------------------------------------

class _GrowingGlue:
    """A get_partitions paginator whose answer GROWS on a named poll.

    The race, reproduced honestly: the first read misses today's partition, and a
    later read (the sibling chain having finished) carries it.
    """

    def __init__(self, values: list[str], later: list[str], appears_on_call: int) -> None:
        self._values, self._later = values, later
        self._appears_on = appears_on_call
        self.reads = 0

    def get_paginator(self, name: str):
        assert name == "get_partitions"
        outer = self

        class _P:
            def paginate(self, **kwargs):
                outer.reads += 1
                vals = (outer._values + outer._later
                        if outer.reads >= outer._appears_on else outer._values)
                yield {"Partitions": [{"Values": [v]} for v in vals]}

        return _P()


def _stamped_bronze(commodity_code: int, calendar_year: int, month_code: int):
    return pd.DataFrame([{
        "commodity_code": commodity_code,
        "calendar_year": calendar_year,
        "month_code": month_code,
        "market_year": 2026,
        "release_date": "2026-08-13",
    }])


class TestTheWasdePartitionRaceIsWaitedOutThenFailsClosed:
    def test_the_newest_in_scope_stamp_month_is_what_decides(self) -> None:
        """In-scope and STAMPED only -- a wait must never be invented.

        month_code 0 carries no publication month, and an out-of-scope code's rows
        never reach the clock, so neither may drive the decision to wait.
        """
        corn, refused = 440000, 11000
        assert refused not in _PSD_COMMODITY_TO_SLUGS
        assert task._newest_psd_stamp_month(
            [_stamped_bronze(corn, 2026, 8), _stamped_bronze(corn, 2026, 5)]) == "2026-08"
        # an out-of-scope code stamped LATER does not move it
        assert task._newest_psd_stamp_month(
            [_stamped_bronze(corn, 2026, 5), _stamped_bronze(refused, 2026, 12)]) == "2026-05"
        # month_code 0 is not a stamp
        assert task._newest_psd_stamp_month([_stamped_bronze(corn, 2026, 0)]) is None

    def test_a_covered_stamp_month_does_NOT_wait_and_makes_no_extra_glue_call(self) -> None:
        """Every day of the month except the one this exists for."""
        glue = _GrowingGlue(["2026-08-12"], [], appears_on_call=1)
        slept: list[int] = []
        cal = {"2026-07": 10, "2026-08": 12}
        out = task.wait_for_wasde_calendar(
            [_stamped_bronze(440000, 2026, 8)], cal, "us-east-1",
            glue_client=glue, sleep=slept.append,
        )
        assert out is cal
        assert slept == [] and glue.reads == 0

    def test_the_race_RESOLVES_and_the_run_continues(self) -> None:
        glue = _GrowingGlue(["2026-07-10"], ["2026-08-12"], appears_on_call=2)
        slept: list[int] = []
        out = task.wait_for_wasde_calendar(
            [_stamped_bronze(440000, 2026, 8)], {"2026-07": 10}, "us-east-1",
            glue_client=glue, sleep=slept.append,
        )
        assert out == {"2026-07": 10, "2026-08": 12}
        assert slept == [task._WASDE_WAIT_POLL_SECONDS] * 2
        assert glue.reads == 2

    def test_the_wait_is_BOUNDED_and_then_fails_closed(self, caplog) -> None:
        """Past the bound the sibling chain has genuinely failed, and psd_monthly SHOULD red.

        The bound is 90 minutes polled every 5 -- at most 18 get-partitions reads,
        no other call. The function returns the still-short calendar and the
        transform's own fail-closed raise then stops the run: publishing PSD rows
        dated by a convention nobody measured is the worse outcome.
        """
        glue = _GrowingGlue(["2026-07-10"], [], appears_on_call=99)
        slept: list[int] = []
        with caplog.at_level("ERROR"):
            out = task.wait_for_wasde_calendar(
                [_stamped_bronze(440000, 2026, 8)], {"2026-07": 10}, "us-east-1",
                glue_client=glue, sleep=slept.append,
            )
        assert out == {"2026-07": 10}
        expected_polls = task._WASDE_WAIT_MAX_SECONDS // task._WASDE_WAIT_POLL_SECONDS
        assert expected_polls == 18
        assert len(slept) == expected_polls and glue.reads == expected_polls
        assert sum(slept) == task._WASDE_WAIT_MAX_SECONDS == 90 * 60
        assert "Failing closed" in caplog.text

    def test_a_SHORTER_re_read_never_shrinks_the_calendar(self) -> None:
        """Post-fix re-review M2: wasde_release_calendar raises only on ZERO partitions, so a
        short-but-nonempty Glue listing used to REPLACE the calendar -- the new month satisfied
        `stamp <= max(calendar)` while every other month silently fell to month_end_fallback. A
        re-read may only ADD months."""

        class _OnlyNew:
            def __init__(self) -> None:
                self.reads = 0

            def get_paginator(self, name: str):
                outer = self

                class _P:
                    def paginate(self, **kwargs):
                        outer.reads += 1
                        yield {"Partitions": [{"Values": ["2026-08-12"]}]}     # 2026-07 is GONE

                return _P()

        glue = _OnlyNew()
        slept: list[int] = []
        out = task.wait_for_wasde_calendar(
            [_stamped_bronze(440000, 2026, 8)], {"2026-07": 10, "2026-06": 11}, "us-east-1",
            glue_client=glue, sleep=slept.append,
        )
        assert out == {"2026-06": 11, "2026-07": 10, "2026-08": 12}     # merged, nothing lost
        assert glue.reads == 1 and slept == [task._WASDE_WAIT_POLL_SECONDS]

    def test_a_failing_calendar_re_read_keeps_waiting_rather_than_crashing(self) -> None:
        """A transient Glue error inside the wait must not become the outage."""

        class _Flaky:
            def __init__(self) -> None:
                self.reads = 0

            def get_paginator(self, name: str):
                outer = self

                class _P:
                    def paginate(self, **kwargs):
                        outer.reads += 1
                        if outer.reads == 1:
                            raise RuntimeError("throttled")
                        yield {"Partitions": [{"Values": ["2026-07-10"]},
                                              {"Values": ["2026-08-12"]}]}

                return _P()

        glue = _Flaky()
        slept: list[int] = []
        out = task.wait_for_wasde_calendar(
            [_stamped_bronze(440000, 2026, 8)], {"2026-07": 10}, "us-east-1",
            glue_client=glue, sleep=slept.append,
        )
        assert out == {"2026-07": 10, "2026-08": 12}
        assert glue.reads == 2 and len(slept) == 2

    def test_the_wait_is_WIRED_into_main_between_the_calendar_read_and_the_transform(self) -> None:
        """A wait nothing calls is a comment."""
        import inspect

        src = inspect.getsource(task.main)
        i_cal = src.index("calendar = wasde_release_calendar(aws_region)")
        i_wait = src.index("wait_for_wasde_calendar(dfs, calendar, aws_region)")
        i_transform = src.index("transform_psd_bronze_to_silver(dfs, calendar=calendar")
        assert i_cal < i_wait < i_transform
