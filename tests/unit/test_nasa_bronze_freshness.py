"""FRESHNESS-AWARE raw->bronze for NASA POWER -- ``jobs/glue/raw_to_bronze_nasa_power.py`` (2026-09-11).

THE FREEZE, MEASURED. ``BaseRawToBronzeJob.run`` (``src/leviathan/storage/base_jobs.py:311-316``)
lists existing bronze and ``_process_one`` (:348-350) returns "skipped" on MERE EXISTENCE -- no mtime
comparison anywhere, unlike the bronze->silver seam one layer down, which has had SILVER-V002
(``select_partitions_to_write``) since the CHIRPS stale-silver hazard.

MEASURED on ``corn_cbot/united_states/us_corn_ohio/year=2026``: the raw August payload was refetched
2026-09-11T08:04:59Z and carries 31 of 31 real T2M_MAX / T2M_MIN days, while bronze month=08 still held
the 22 rows it was given on 2026-08-22T11:30:14Z. Twenty days of green daily runs read the fresh raw
and declined to rewrite the bronze; silver carried the freeze faithfully, and ``gold_weather_z`` -- a
SERVED numbers card -- tipped at data month 2026-07 while its card promised 2026-08.

The repair is a ``run()`` override in the nasa_power subclass -- the precedent being
``jobs/glue/bronze_to_silver_nasa_power.py``, which already carries its own ``run()`` for SILVER-V002
while the shared base class stays untouched. ``_process_one`` is NOT modified: a stale bronze key is
simply absent from the ``existing_bronze`` set handed to it, so it takes the ordinary write path.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_glue_module():
    """Load the Glue script without running its bootstrap or its bottom-of-file thin-contract entry."""
    boot = types.ModuleType("bootstrap")
    boot.run_bootstrap = lambda *a, **k: None            # type: ignore[attr-defined]
    saved_boot = sys.modules.get("bootstrap")
    sys.modules["bootstrap"] = boot

    from leviathan.storage.base_jobs import BaseRawToBronzeJob
    original = BaseRawToBronzeJob.__dict__["run_thin_contract"]
    BaseRawToBronzeJob.run_thin_contract = classmethod(lambda cls, argv=None: None)  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(
            "raw_to_bronze_nasa_power", _REPO / "jobs" / "glue" / "raw_to_bronze_nasa_power.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["raw_to_bronze_nasa_power"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        BaseRawToBronzeJob.run_thin_contract = original  # type: ignore[assignment]
        if saved_boot is None:
            sys.modules.pop("bootstrap", None)
        else:
            sys.modules["bootstrap"] = saved_boot


nasa = _load_glue_module()

_T0 = datetime(2026, 8, 22, 11, 30, 14, tzinfo=timezone.utc)     # the MEASURED bronze mtime
_T1 = datetime(2026, 9, 11, 8, 4, 59, tzinfo=timezone.utc)       # the MEASURED raw mtime


def _raw(month: int, region: str = "us_corn_ohio") -> str:
    return (f"raw/weather/source=nasa_power/commodity=corn_cbot/country=united_states/"
            f"region={region}/year=2026/month={month:02d}/nasa_power.json")


def _bronze_of(raw_key: str) -> str:
    return raw_key.replace("raw/", "bronze/").replace(".json", ".parquet")


# ---------------------------------------------------------------------------
# fresh_bronze_keys -- the whole decision, pure
# ---------------------------------------------------------------------------
class TestFreshBronzeKeys:
    def test_bronze_OLDER_than_its_own_raw_is_rewritten(self):
        """THE MEASURED AUGUST: raw refetched 2026-09-11T08:04:59Z over a bronze from
        2026-08-22T11:30:14Z. Before this fix that bronze was 'skipped' on existence and stayed at 22
        of 31 days for twenty days."""
        raw = {_raw(8): _T1}
        bronze = {_bronze_of(_raw(8)): _T0}
        fresh, stale = nasa.fresh_bronze_keys(raw, bronze, _bronze_of)
        assert stale == [_bronze_of(_raw(8))]
        assert fresh == set(), "a stale key must be ABSENT from existing_bronze so _process_one writes it"

    def test_bronze_NEWER_than_its_raw_is_skipped(self):
        raw = {_raw(7): _T0}
        bronze = {_bronze_of(_raw(7)): _T1}
        fresh, stale = nasa.fresh_bronze_keys(raw, bronze, _bronze_of)
        assert stale == []
        assert fresh == {_bronze_of(_raw(7))}

    def test_EQUAL_timestamps_are_fresh_so_a_benign_rerun_stays_a_no_op(self):
        """AV-12: the strict ``<`` is what keeps an ordinary same-second rerun from rewriting the layer."""
        raw = {_raw(6): _T0}
        bronze = {_bronze_of(_raw(6)): _T0}
        fresh, stale = nasa.fresh_bronze_keys(raw, bronze, _bronze_of)
        assert stale == [] and fresh == {_bronze_of(_raw(6))}

    def test_the_yardstick_is_PER_FILE_not_a_prefix_max(self):
        """A prefix-wide max(raw_mtime) -- the shape select_partitions_to_write uses one layer down,
        where a silver partition is assembled from MANY bronze files -- would mark all 3,843 of a
        commodity's 2026 bronze objects stale the moment ANY one raw file was refetched, i.e. a full
        rewrite of the layer every single day. A nasa_power bronze key is 1:1 with its raw key."""
        raw = {_raw(7): _T0, _raw(8): _T1}                    # only August was refetched
        bronze = {_bronze_of(_raw(7)): _T0, _bronze_of(_raw(8)): _T0}
        fresh, stale = nasa.fresh_bronze_keys(raw, bronze, _bronze_of)
        assert stale == [_bronze_of(_raw(8))], stale
        assert fresh == {_bronze_of(_raw(7))}, "July must not be dragged into August's rewrite"

    def test_a_MISSING_bronze_is_not_stale_it_is_simply_absent(self):
        """Never in the fresh set, never in the stale list: _process_one's existing behaviour writes it."""
        fresh, stale = nasa.fresh_bronze_keys({_raw(9): _T1}, {}, _bronze_of)
        assert fresh == set() and stale == []

    def test_a_MISSING_timestamp_on_either_side_is_FRESH(self):
        """An unknown is never grounds for a rewrite -- the reading select_partitions_to_write takes of
        a null bronze_max_mtime and _bronze_is_stale takes of a missing mtime."""
        bkey = _bronze_of(_raw(8))
        assert nasa.fresh_bronze_keys({_raw(8): None}, {bkey: _T0}, _bronze_of) == ({bkey}, [])
        assert nasa.fresh_bronze_keys({_raw(8): _T1}, {bkey: None}, _bronze_of) == ({bkey}, [])

    def test_an_ORPHAN_bronze_whose_raw_is_gone_is_left_alone(self):
        """This function decides what to REWRITE, never what to delete."""
        orphan = _bronze_of(_raw(3, region="retired_region"))
        fresh, stale = nasa.fresh_bronze_keys({_raw(8): _T1}, {orphan: _T0}, _bronze_of)
        assert fresh == {orphan} and stale == []

    def test_an_UNMAPPABLE_raw_key_does_not_abort_the_whole_commodity(self):
        """``bronze_key`` parses Hive segments and throws on a malformed key. Before this override
        that throw happened inside ``_process_one`` and became ONE dead-letter entry while the batch
        continued; letting it escape from the selector would abort every file of the commodity on one
        bad key -- strictly worse than the behaviour being repaired."""
        def _explodes(raw_key):
            if "garbage" in raw_key:
                raise ValueError("no year= segment")
            return _bronze_of(raw_key)

        fresh, stale = nasa.fresh_bronze_keys(
            {"raw/garbage.json": _T1, _raw(8): _T1}, {_bronze_of(_raw(8)): _T0}, _explodes)
        assert stale == [_bronze_of(_raw(8))], "the good key is still judged"
        assert fresh == set()

    def test_the_stale_list_is_ordered_so_two_runs_log_the_same_thing(self):
        raw = {_raw(m): _T1 for m in (9, 7, 8)}
        bronze = {_bronze_of(_raw(m)): _T0 for m in (9, 7, 8)}
        _, stale = nasa.fresh_bronze_keys(raw, bronze, _bronze_of)
        assert stale == sorted(stale)


# ---------------------------------------------------------------------------
# the run() override -- the wiring, with _process_one stubbed
# ---------------------------------------------------------------------------
def _job(monkeypatch, raw_objects: dict, bronze_objects: dict, *, force: bool = False):
    job = object.__new__(nasa.NasaPowerRawToBronze)
    job.commodity = "corn_cbot"
    job.bucket = "b"
    job.aws_region = "us-east-1"
    job.force_overwrite = force
    job.year_window = None

    calls: list[tuple[str, bool]] = []

    def _process_one(raw_key, existing_bronze):
        bkey = job.bronze_key(raw_key)
        skipped = bkey in existing_bronze
        calls.append((raw_key, skipped))
        return ("skipped", bkey) if skipped else ("success", bkey)

    job._process_one = _process_one  # type: ignore[method-assign]

    def _list(bucket, prefix, suffix="", aws_region=""):
        return dict(raw_objects) if prefix.startswith("raw/") else dict(bronze_objects)

    monkeypatch.setattr(nasa, "list_s3_keys_with_mtime", _list)
    return job, calls


class TestRunOverride:
    def test_a_stale_bronze_reaches_process_one_as_NOT_existing_and_is_written(self, monkeypatch):
        job, calls = _job(monkeypatch, {_raw(8): _T1}, {_bronze_of(_raw(8)): _T0})
        job.run()
        assert calls == [(_raw(8), False)], calls

    def test_a_fresh_bronze_is_still_skipped(self, monkeypatch):
        job, calls = _job(monkeypatch, {_raw(7): _T0}, {_bronze_of(_raw(7)): _T1})
        job.run()
        assert calls == [(_raw(7), True)], calls

    def test_force_overwrite_reprocesses_everything_exactly_as_before(self, monkeypatch):
        job, calls = _job(monkeypatch, {_raw(7): _T0}, {_bronze_of(_raw(7)): _T1}, force=True)
        job.run()
        assert calls == [(_raw(7), False)], calls

    def test_a_failure_still_raises_so_the_job_cannot_exit_green_on_a_dead_letter(self, monkeypatch):
        job, _ = _job(monkeypatch, {_raw(8): _T1}, {})
        job._process_one = lambda k, e: ("failed", f"{k}: boom")  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="failed during raw->bronze"):
            job.run()

    def test_the_year_window_still_bounds_the_daily_run(self, monkeypatch):
        old = _raw(8).replace("year=2026", "year=2019")
        job, calls = _job(monkeypatch, {_raw(8): _T1, old: _T1}, {})
        job.year_window = 2026
        job.run()
        assert [k for k, _ in calls] == [_raw(8)], calls


class TestNoShrinkFloorIsADecision:
    def test_the_shrink_floor_is_absent_BY_ARGUMENT_not_by_oversight(self):
        """The cpc lane's ``_rewrite_would_shrink`` guards a partition ASSEMBLED from many raw days,
        where one failed fetch silently shrinks the rewrite. A nasa_power bronze object is 1:1 with
        exactly one raw object and is a total function of it, so a smaller bronze can only mean a
        smaller RAW -- a fact of the raw layer that bronze must carry, not hide. Pinned so a future
        reader finds the argument rather than assuming an omission."""
        src = (_REPO / "jobs" / "glue" / "raw_to_bronze_nasa_power.py").read_text(encoding="utf-8")
        assert "NO SHRINK FLOOR HERE, AND THAT IS A DECISION" in src
        assert not hasattr(nasa, "_rewrite_would_shrink")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
