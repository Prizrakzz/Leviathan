"""THE ALL-NULL WRITE GATE on the DAILY CHIRPS bronze task (2026-09-11).

THE DEFECT, MEASURED. ``fetch_chirps_daily_values`` returns ``{region: None}`` on a 404
(``src/leviathan/ingestion/weather/chirps.py:59-63``) -- a TRUTHY dict -- so
``chirps_to_bronze_task._process_month`` built a row for every day of a month the source had not
published, with ``precipitation_mm=None``, and wrote it. The live object
``bronze/weather/source=chirps/commodity=corn_cbot/country=united_states/region=us_corn_.../year=2026/
month=08/part-000.parquet`` held 31 rows and ZERO precipitation observations with LastModified
2026-08-22T09:04:3xZ, and the F044 null-drop at silver turned that into NO August partition at all --
so ``gold_weather_z`` froze at data month 2026-07 while its served card promised 2026-08.

The SIBLING backfill task (``chirps_year_to_bronze_task.py:177-188``) has refused exactly this since
BF-W1; the daily task only ``logger.warning``-ed and wrote the skeleton anyway. This deck pins the
ported gate, and pins that it is UNCONDITIONAL -- ``--force_overwrite`` may not replace a real month
with an empty one either, which is the sibling's doctrine verbatim.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / "jobs" / "batch" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


daily = _load("chirps_to_bronze_task")
yearly = _load("chirps_year_to_bronze_task")


def _rows(values: list) -> list[dict]:
    """One bronze row per day; ``values[i]`` is that day's precipitation_mm (None == unpublished)."""
    return [{"precipitation_mm": v, "day": i + 1} for i, v in enumerate(values)]


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3:
    """The narrow surface ``_process_month``'s write block uses. Records every put_object."""

    class exceptions:                      # noqa: N801 -- mirrors botocore's client.exceptions shape
        ClientError = _FakeClientError

    def __init__(self, existing: dict | None = None) -> None:
        self.existing = dict(existing or {})     # key -> body bytes (or a sentinel)
        self.puts: list[str] = []

    def head_object(self, Bucket: str, Key: str):   # noqa: N803 -- boto3 kwarg casing
        if Key not in self.existing:
            raise _FakeClientError("404")
        return {"ContentLength": 1}

    def get_object(self, Bucket: str, Key: str):    # noqa: N803
        if Key not in self.existing:
            raise _FakeClientError("404")
        return {"Body": _Body(self.existing[Key])}

    def put_object(self, Bucket: str, Key: str, Body=None, **kw):  # noqa: N803
        self.puts.append(Key)
        self.existing[Key] = Body


class _Body:
    def __init__(self, data) -> None:
        self._data = data

    def read(self):
        return self._data


# ---------------------------------------------------------------------------
# the pure counter the gate is built on
# ---------------------------------------------------------------------------
class TestNonNullDayCount:
    def test_a_wholly_unpublished_month_counts_zero_observations_not_31_rows(self):
        """THE MEASURED AUGUST: 31 rows, 0 observations. Row count is not a measurement."""
        rows = _rows([None] * 31)
        assert len(rows) == 31
        assert daily._nonnull_day_count(rows) == 0

    def test_one_published_day_is_one_observation(self):
        assert daily._nonnull_day_count(_rows([None] * 30 + [3.5])) == 1

    def test_zero_millimetres_is_an_observation_not_an_absence(self):
        """A dry day is DATA. 0.0 is the value the drought family exists to count."""
        assert daily._nonnull_day_count(_rows([0.0] * 31)) == 31

    def test_nan_is_absent_for_the_same_reason_parquet_excludes_it_from_min_max(self):
        assert daily._nonnull_day_count(_rows([float("nan")] * 31)) == 0
        assert daily._nonnull_day_count(_rows([float("nan"), 1.0, None])) == 1

    def test_the_two_tasks_agree_digit_for_digit(self):
        """The helper is DUPLICATED across the two Batch entrypoints (they are invoked by path, so a
        cross-task import would resolve at runtime and not in this deck). This is the drift pin."""
        for case in ([None] * 31, [0.0] * 31, [float("nan"), 1.0, None], [1.0, 2.0], []):
            rows = _rows(case)
            assert daily._nonnull_day_count(rows) == yearly._nonnull_day_count(rows), case


# ---------------------------------------------------------------------------
# the gate itself, through _process_month
# ---------------------------------------------------------------------------
def _run_month(monkeypatch, s3: _FakeS3, day_values: dict, *, force: bool = False,
               year: int = 2026, month: int = 8):
    """Drive ``daily._process_month`` with a stubbed fetcher. ``day_values`` maps day -> precip|None."""
    locations = [{"country": "united_states", "region": "us_corn_ohio",
                  "latitude": 40.0, "longitude": -83.0}]

    def _fetch(y, m, d, locs):
        return {loc["region"]: day_values.get(d) for loc in locs}

    monkeypatch.setattr(daily, "fetch_chirps_daily_values", _fetch)
    monkeypatch.setattr(daily, "get_thread_local_s3_client", lambda region: s3)
    daily._process_month(
        aws_region="us-east-1", bucket="b", commodity="corn_cbot", year=year, month=month,
        locations=locations, ingest_date="2026-09-11", force_overwrite=force,
    )
    return s3


class TestAllNullWriteGate:
    def test_a_wholly_unpublished_month_writes_NO_object_at_all(self, monkeypatch):
        """THE REGRESSION PIN. Before the fix this wrote a 31-row all-null parquet AND its meta."""
        s3 = _run_month(monkeypatch, _FakeS3(), {})          # every day 404s -> {region: None}
        assert s3.puts == [], f"an all-null month minted {s3.puts}"

    def test_one_observed_day_in_thirty_one_DOES_write(self, monkeypatch):
        """The gate refuses ABSENCE, never thinness. A single real day is a real partition."""
        s3 = _run_month(monkeypatch, _FakeS3(), {12: 4.25})
        assert len(s3.puts) == 2, s3.puts                     # parquet + companion meta
        assert any(k.endswith("part-000.parquet") for k in s3.puts)
        assert any(k.endswith("_meta.json") for k in s3.puts)

    def test_force_overwrite_may_NOT_replace_a_real_month_with_an_empty_one(self, monkeypatch):
        """UNCONDITIONAL, exactly as chirps_year_to_bronze_task.py:177-188 has it: the write gate sits
        OUTSIDE the force_overwrite branch, so the flag that names an overwrite cannot name a deletion."""
        s3 = _run_month(monkeypatch, _FakeS3(), {}, force=True)
        assert s3.puts == [], f"--force_overwrite wrote an all-null partition: {s3.puts}"

    def test_the_meta_records_the_observation_count_not_only_the_row_count(self, monkeypatch):
        """``nonnull_count`` is the yardstick the NEXT run measures against (_stored_nonnull_days).
        row_count is the calendar length of the month whether 31 days arrived or one."""
        import json
        s3 = _run_month(monkeypatch, _FakeS3(), {5: 1.0, 6: 2.0})
        meta_key = next(k for k in s3.puts if k.endswith("_meta.json"))
        meta = json.loads(s3.existing[meta_key])
        assert meta["row_count"] == 31
        assert meta["nonnull_count"] == 2


class TestSiblingGateUnchanged:
    def test_the_year_task_still_refuses_an_all_null_region_month(self):
        """BF-W1's gate is untouched by this wave -- only the skip beside it moved."""
        assert yearly._nonnull_day_count(_rows([None] * 31)) == 0
        src = (_REPO / "jobs" / "batch" / "chirps_year_to_bronze_task.py").read_text(encoding="utf-8")
        assert "SKIP all-null precipitation (no partition written)" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
