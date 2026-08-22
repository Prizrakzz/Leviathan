"""The PARTIAL-MONTH PERMANENCE fences (2026-08-22).

The defect class: all three weather fetchers write month-granular raw state and skip work when
that state EXISTS -- so a month first touched mid-month keeps its hole forever. July 2026 measured
12/31 days (nasa_power), 0/31 (chirps), 16/31 (cpc_soil) across every commodity while the daily
scheduled runs kept succeeding; gold_weather_z's _complete_months_only guard then (correctly)
excluded July, freezing the z layer at June with no alarm. These tests pin the fix per fetcher:
the CURRENT and PREVIOUS calendar months are never skippable on existence alone.
"""
from __future__ import annotations

import datetime
import importlib.util
import re
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── nasa_power: the trailing-window predicate + both skip sites carry it ────────────────────────
def test_nasa_trailing_window_covers_current_and_previous_month(monkeypatch):
    m = _load("fetch_nasa_power_t", "jobs/ingest/fetch_nasa_power.py")

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 22)

    monkeypatch.setattr(m.datetime, "date", _D)
    assert m._is_trailing_window(2026, 8) is True         # current
    assert m._is_trailing_window(2026, 7) is True         # previous -- THE July hole
    assert m._is_trailing_window(2026, 6) is False        # M-2: immutable-complete again
    assert m._is_trailing_window(2025, 8) is False


def test_nasa_trailing_window_january_rolls_to_december_prior_year(monkeypatch):
    m = _load("fetch_nasa_power_t2", "jobs/ingest/fetch_nasa_power.py")

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 5)

    monkeypatch.setattr(m.datetime, "date", _D)
    assert m._is_trailing_window(2027, 1) is True
    assert m._is_trailing_window(2026, 12) is True        # the year-rollover edge
    assert m._is_trailing_window(2026, 11) is False


def test_nasa_both_existence_skips_are_gated_on_the_trailing_flag():
    """Source pin: the fix is only real while BOTH skip sites consult it. A refactor that drops
    either guard silently reopens the hole -- the jobdef-fence test idiom."""
    src = (_REPO / "jobs" / "ingest" / "fetch_nasa_power.py").read_text(encoding="utf-8")
    assert re.search(r"if local_path\.exists\(\) and not refetch_trailing:", src)
    assert re.search(r"if args\.skip_existing_s3 and args\.upload and not refetch_trailing:", src)
    assert "_is_trailing_window(window.year, window.month)" in src


# ── chirps: the month selector is parameter-pure -- test it directly ────────────────────────────
class _HeadOK:
    """Fake s3: every sentinel exists -- the pre-fix trap state."""

    def head_object(self, Bucket, Key):
        return {"ContentLength": 1}


def _chirps():
    return _load("chirps_task_t", "jobs/batch/chirps_to_bronze_task.py")


_LOCS = [{"country": "cote_divoire", "region": "abengourou"}]


def test_chirps_previous_month_is_always_redownloaded_even_with_sentinel_present():
    m = _chirps()
    months = m._months_to_process(_HeadOK(), "bkt", "cocoa", _LOCS, 2026,
                                  force_overwrite=False, today=datetime.date(2026, 8, 22))
    assert 8 in months and 7 in months                    # current AND previous, sentinel or not
    assert 6 not in months                                # M-2 with sentinel present: trusted


def test_chirps_older_month_still_self_heals_when_sentinel_absent():
    class _Head404:
        def head_object(self, Bucket, Key):
            raise RuntimeError("404")

    m = _chirps()
    months = m._months_to_process(_Head404(), "bkt", "cocoa", _LOCS, 2026,
                                  force_overwrite=False, today=datetime.date(2026, 8, 22))
    assert months == list(range(1, 9))                    # every elapsed month: all sentinels absent


def test_chirps_january_top_up_fetches_only_december_of_prior_year():
    m = _chirps()
    months = m._months_to_process(_HeadOK(), "bkt", "cocoa", _LOCS, 2026,
                                  force_overwrite=False, today=datetime.date(2027, 1, 5))
    assert months == [12]                                 # never the 12-month backfill download


# ── cpc: trailing-hole detection + the per-year tarball fallback derivation ─────────────────────
def test_cpc_trailing_month_holes_counts_days_and_spans_the_year_boundary(monkeypatch):
    m = _load("cpc_task_t", "jobs/batch/cpc_soil_to_raw_task.py")

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 10)

    monkeypatch.setattr(m, "date", _D)

    present: set[str] = {f"202612{d:02d}" for d in range(1, 16)}     # December half-full

    class _S3:
        def head_object(self, Bucket, Key):
            stamp = Key.split(".")[-2]
            if stamp not in present:
                raise RuntimeError("404")
            return {}

    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: _S3())
    holes = m._trailing_month_holes("bkt", "us-east-1", "w")
    assert holes["2026-12"] == (15, 31)                   # the hole, visible
    assert holes["2027-01"][1] == 9                       # current month expects today-1 days
    # and the fallback derives the TARBALL year from the hole's own year, not the run year
    hole_years = sorted({int(ym.split("-")[0]) for ym, (p, e) in holes.items() if p < e})
    assert 2026 in hole_years


def test_cpc_fallback_is_wired_per_hole_year_in_main():
    src = (_REPO / "jobs" / "batch" / "cpc_soil_to_raw_task.py").read_text(encoding="utf-8")
    assert "_trailing_month_holes(bucket, aws_region, args.variable)" in src
    assert re.search(r"for hy in hole_years:.*\n.*_process_year_via_tarball\(\n\s*year=hy", src)
    assert "TRAILING-MONTH HOLE" in src                   # the loud line a silent skip never had
