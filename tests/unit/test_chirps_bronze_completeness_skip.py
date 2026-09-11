"""THE COMPLETENESS-AWARE BRONZE WRITE SKIP for both CHIRPS tasks (2026-09-11).

THE DEFECT, MEASURED. Both tasks skipped an existing bronze month on EXISTENCE alone
(``chirps_to_bronze_task.py:156-160``, ``chirps_year_to_bronze_task.py:168-175``: ``head_object`` ->
"Skipping existing" -> ``continue``). The 2026-08-22 all-null August skeleton therefore survived every
subsequent daily run -- twenty of them, all green, all writing zero CHIRPS bronze bytes -- and
``gold_weather_z``, a SERVED numbers card, stayed frozen at data month 2026-07.

WHY NOT THE cpc LANE'S MTIME RULE. ``cpc_raw_to_bronze_task._bronze_is_stale(bronze_mtime,
raw_max_mtime)`` needs a RAW object whose mtime can prove the bronze stale. CHIRPS HAS NO RAW TIER
(configs/sources/chirps.yaml: "HTTP range-read via rasterio/vsicurl -- no raw S3 tier"), so there is no
such timestamp anywhere. The yardstick here is what both sides can state: how many days of the month
carry an OBSERVATION. That rule is strictly monotone, so the anti-shrink floor the cpc lane had to ship
as a separate rule (``_rewrite_would_shrink``) is built into this one.

The helper trio is DUPLICATED across the two Batch entrypoints -- they are invoked by path, so a
cross-task import would resolve at runtime and not in this deck -- and every case below runs through
BOTH modules, which is the drift pin.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
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
BOTH = pytest.mark.parametrize("mod", [daily, yearly], ids=["daily", "yearly"])


# ---------------------------------------------------------------------------
# _rewrite_admitted -- the whole decision, in one pure function
# ---------------------------------------------------------------------------
@BOTH
class TestRewriteAdmitted:
    def test_MORE_observed_days_is_admitted(self, mod):
        """THE REPAIR ITSELF: the August case once the source publishes. 31 > 0 -> write."""
        assert mod._rewrite_admitted(31, 0) is True
        assert mod._rewrite_admitted(31, 22) is True

    def test_EQUAL_is_not_an_improvement_and_stays_a_no_op(self, mod):
        """The ordinary same-day rerun (AV-12): nothing new arrived, nothing is rewritten."""
        assert mod._rewrite_admitted(22, 22) is False
        assert mod._rewrite_admitted(0, 0) is False

    def test_FEWER_is_the_SHRINK_the_floor_exists_to_refuse(self, mod):
        """A run that reached 19 of 31 days because UCSB was throttling must never replace a 22-day
        partition and call it a refresh. Monotonicity IS the anti-shrink floor here."""
        assert mod._rewrite_admitted(19, 22) is False
        assert mod._rewrite_admitted(1, 31) is False

    def test_UNKNOWN_is_never_grounds_to_act(self, mod):
        """``_bronze_is_stale`` and ``_rewrite_would_shrink`` both read an unknown this way: a rewrite
        REPLACES, and a run that cannot see what it is replacing cannot prove it would not shrink."""
        assert mod._rewrite_admitted(31, None) is False
        assert mod._rewrite_admitted(0, None) is False


# ---------------------------------------------------------------------------
# _stored_nonnull_days -- meta first, the partition as fallback, unknown on failure
# ---------------------------------------------------------------------------
class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _S3:
    def __init__(self, objects: dict):
        self.objects = objects
        self.gets: list[str] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        self.gets.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(self.objects[Key])}


_PART = "bronze/weather/source=chirps/commodity=c/country=x/region=r/year=2026/month=08/part-000.parquet"
_META = _PART.replace("part-000.parquet", "_meta.json")


def _parquet_bytes(values: list) -> bytes:
    import io
    buf = io.BytesIO()
    pd.DataFrame({"precipitation_mm": values, "day": range(1, len(values) + 1)}).to_parquet(
        buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


@BOTH
class TestStoredNonNullDays:
    def test_the_companion_meta_answers_in_ONE_small_get(self, mod):
        s3 = _S3({_META: json.dumps({"row_count": 31, "nonnull_count": 22}).encode()})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 22
        assert s3.gets == [_META], "the parquet must not be read when the meta already says so"

    def test_a_pre_2026_09_11_meta_has_no_nonnull_count_so_the_PARTITION_is_read(self, mod):
        """Every object minted before this wave carries row_count only -- and the 2026-08-22 all-null
        August skeletons are exactly those. MEASURED: 31 rows, 0 observations, 7.4 KB."""
        s3 = _S3({_META: json.dumps({"row_count": 31}).encode(),
                  _PART: _parquet_bytes([None] * 31)})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 0
        assert s3.gets == [_META, _PART]

    def test_row_count_is_NOT_mistaken_for_the_observation_count(self, mod):
        """The whole defect in one assertion: a 31-row all-null month must read as ZERO, not 31."""
        s3 = _S3({_PART: _parquet_bytes([None] * 31)})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 0

    def test_a_partly_published_month_reads_its_real_observation_count(self, mod):
        s3 = _S3({_PART: _parquet_bytes([1.0] * 22 + [None] * 9)})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 22

    def test_an_unreadable_partition_is_UNKNOWN_not_zero(self, mod):
        """None, never 0 -- reading it as 0 would admit ANY rewrite over an object nobody could see."""
        s3 = _S3({})
        assert mod._stored_nonnull_days(s3, "b", _PART) is None

    def test_a_non_integer_nonnull_count_falls_through_rather_than_being_trusted(self, mod):
        s3 = _S3({_META: json.dumps({"nonnull_count": "22"}).encode(),
                  _PART: _parquet_bytes([1.0] * 5 + [None] * 26)})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 5

    def test_a_boolean_is_not_an_integer_count(self, mod):
        """``isinstance(True, int)`` is True in Python; a bool in that field is corrupt, not a count."""
        s3 = _S3({_META: json.dumps({"nonnull_count": True}).encode(),
                  _PART: _parquet_bytes([1.0] * 3 + [None] * 28)})
        assert mod._stored_nonnull_days(s3, "b", _PART) == 3


# ---------------------------------------------------------------------------
# the three cases the fix plan names, end to end through the decision
# ---------------------------------------------------------------------------
@BOTH
@pytest.mark.parametrize(
    "new, stored, admitted, why",
    [
        (31, 22, True, "31 > 22 writes -- the published month replaces the partial one"),
        (22, 22, False, "22 == 22 skips -- nothing new arrived"),
        (19, 22, False, "19 < 22 DECLINES -- the anti-shrink floor"),
        (31, 0, True, "the measured August repair: 31 observations over an all-null skeleton"),
        (31, None, False, "unknown stored count declines; --force_overwrite names the overwrite"),
    ],
)
def test_the_named_decision_table(mod, new, stored, admitted, why):
    assert mod._rewrite_admitted(new, stored) is admitted, why


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
