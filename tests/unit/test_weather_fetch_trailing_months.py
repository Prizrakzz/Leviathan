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
import io
import json
import re
import sys
import types
from pathlib import Path

import pytest
import requests

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "tests" / "fixtures" / "cpc_soil"


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
#
# CORRECTED 2026-09-11. The 2026-08-22 cpc fix above closed the partial-month trap but expected
# ``today.day - 1`` days of the current month -- a ONE-day publication lag. CPC publishes day D at
# about 17:53Z on D+1 (MEASURED: GeoTIFF/w.20260909.tif carries Last-Modified "Thu, 10 Sep 2026
# 17:53:44 GMT", and w.20260910.tif was still 404 at 09:30Z on 09-11), which is AFTER the 08:00Z
# fire -- so the real lag is TWO days. Every run therefore invented a one-day hole and reached for
# clim/w.2026.tif.tar.gz to heal it: a file that does not exist, because clim/ carries CLOSED years
# only (w.2000..w.2025 plus w.40ym). HTTPError 404, tenacity exhausted, exit 1, every run since
# about 2026-08-28 -- while raw was in fact COMPLETE through every published day.
# Capture evidence: tests/fixtures/cpc_soil/capture_notes.md.

def _cpc():
    return _load("cpc_task_t", "jobs/batch/cpc_soil_to_raw_task.py")


def _days(start: datetime.date, end: datetime.date) -> set[str]:
    out: set[str] = set()
    d = start
    while d <= end:
        out.add(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out


def test_cpc_a_day_cpc_has_not_published_is_a_decline_never_a_hole():
    """THE REGRESSION, named. Raw complete through the publication tip must report NO deficit."""
    m = _cpc()
    today = datetime.date(2026, 9, 11)
    published = _days(datetime.date(2026, 8, 1), datetime.date(2026, 9, 9))   # tip = T-2
    # the previous December is inspected ALL YEAR (see the year-boundary section below), so a
    # complete one rides along in the present set and the dict equality still reads cleanly
    present = set(published) | _days(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
    holes = m._trailing_month_holes(present, published, today=today)
    assert holes == {
        "2026-09": (9, 9, m._BASIS_PUBLISHED),
        "2026-08": (31, 31, m._BASIS_PUBLISHED),
        # the 2026 listing says nothing about a 2025 month, so the CALENDAR is its honest yardstick
        "2025-12": (31, 31, m._BASIS_CALENDAR_FULL),
    }
    assert [ym for ym, (p, e, _b) in holes.items() if p < e] == []
    # the pre-fix expectation, stated so the phantom is visible in the deck itself
    assert max(0, today.day - 1) == 10 and holes["2026-09"][1] == 9


def test_cpc_trailing_month_holes_counts_days_and_spans_the_year_boundary():
    """The January case is unchanged in substance: December is CLOSED, its tarball exists, and the
    CALENDAR is the honest expectation for a month the current year's listing does not cover."""
    m = _cpc()
    today = datetime.date(2027, 1, 10)
    published = _days(datetime.date(2027, 1, 1), datetime.date(2027, 1, 8))   # the 2027 listing
    present = _days(datetime.date(2026, 12, 1), datetime.date(2026, 12, 15)) | published
    holes = m._trailing_month_holes(present, published, today=today)
    assert holes["2026-12"] == (15, 31, m._BASIS_CALENDAR_FULL)    # the hole, visible
    assert holes["2027-01"] == (8, 8, m._BASIS_PUBLISHED)          # published basis, not today-1
    # and the fallback derives the TARBALL year from the hole's own year, not the run year
    hole_years = sorted({int(ym.split("-")[0]) for ym, (p, e, _b) in holes.items() if p < e})
    assert hole_years == [2026]


def test_cpc_without_a_listing_the_current_month_carries_the_measured_two_day_lag():
    """When the live index cannot be read the calendar stands in -- but with the MEASURED lag.
    Under the old one-day assumption this expectation was 9, and that 9 is the whole defect."""
    m = _cpc()
    assert m._PUBLICATION_LAG_DAYS == 2
    holes = m._trailing_month_holes(set(), None, today=datetime.date(2027, 1, 10))
    assert holes["2027-01"] == (0, 8, m._BASIS_CALENDAR_LAGGED)
    assert holes["2026-12"] == (0, 31, m._BASIS_CALENDAR_FULL)
    # MINOR (b), the reason the basis is a RETURNED fact. The hole line used to end with
    # "expected = days CPC has PUBLISHED, not calendar days" on every branch -- a sentence that is
    # flatly false here, on the blind run, which is exactly when an operator reads it hardest.
    assert "CALENDAR" in m._BASIS_PHRASE[m._BASIS_CALENDAR_LAGGED]
    assert "PUBLISHED" in m._BASIS_PHRASE[m._BASIS_PUBLISHED]
    assert set(m._BASIS_PHRASE) == {
        m._BASIS_PUBLISHED, m._BASIS_CALENDAR_LAGGED, m._BASIS_CALENDAR_FULL,
    }


def test_cpc_an_upstream_publication_gap_is_reported_on_its_own_line_not_as_our_hole():
    """Fences CORRECT or COMPUTE, never delete: moving the expectation off the calendar must not
    make the calendar fact disappear."""
    m = _cpc()
    today = datetime.date(2026, 9, 11)
    published = _days(datetime.date(2026, 8, 1), datetime.date(2026, 9, 9)) - {"20260815"}
    holes = m._trailing_month_holes(set(published), published, today=today)
    # not OUR hole: we hold every published day
    assert holes["2026-08"] == (30, 30, m._BASIS_PUBLISHED)
    short = m._upstream_short_months(published, today=today)
    assert short == {"2026-08": (30, 31)}
    assert "2026-09" not in short                         # still inside the lag: short by construction


def test_cpc_a_current_year_hole_never_requests_the_current_year_tarball(monkeypatch):
    """PIN (a). The exact production state on 2026-09-11, with a genuine current-year hole on top:
    the leg must complete without ever asking for clim/w.2026.tif.tar.gz."""
    m = _cpc()

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 11)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    published = sorted(_days(datetime.date(2026, 8, 1), datetime.date(2026, 9, 9)))
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda year, variable: (published, True))

    # a GENUINE current-year hole: 2026-09-03 is published but absent from raw. The previous
    # December is complete, so the ONLY hole in play is the current year's.
    def _present(bucket, region, variable, y):
        if y == 2026:
            return set(published) - {"20260903"}
        return _days(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))

    monkeypatch.setattr(m, "_list_present_raw_days", _present)
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball",
                        lambda **kw: pytest.fail(f"current-year tarball requested: {kw}"))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()                                              # pre-fix: HTTPError 404, exit 1


def _current_year_hole_main(monkeypatch, m, today, tarball):
    """A run with a GENUINE current-year hole -- the 3rd of the CURRENT month, published and absent
    from raw, so the hole lands in a month ``_inspected_months`` actually looks at -- and a complete
    previous December, so the only hole in play is the current year's."""
    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(*today)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    tip = datetime.date(*today) - datetime.timedelta(days=m._PUBLICATION_LAG_DAYS)
    published = sorted(_days(datetime.date(today[0], 1, 1), tip))
    missing = f"{today[0]}{today[1]:02d}03"
    assert missing in published                           # the hole must be a PUBLISHED day
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda y, variable: (published, True))
    monkeypatch.setattr(
        m, "_list_present_raw_days",
        lambda b, r, v, y: set(published) - {missing} if y == today[0]
        else _days(datetime.date(today[0] - 1, 12, 1), datetime.date(today[0] - 1, 12, 31)),
    )
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball", tarball)
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()


@pytest.mark.parametrize("today", [(2026, 9, 11), (2026, 2, 15)])
def test_cpc_the_current_year_guard_is_isolated_by_its_own_line(monkeypatch, caplog, today):
    """PIN (a), ISOLATED -- MINOR (c), review round 2. The headline pin above only asserts that no
    tarball is requested, and at 2026-09-11 that holds even with the guard GONE: an unguarded 2026
    falls through to the ARCHIVE-SEASON guard (month 9 > 3) and is declined there instead. Mutating
    ``if hy >= current_year:`` to ``if False:`` therefore SURVIVED it.

    Two facts kill it. The line is WRONG for the operator -- YEAR-BOUNDARY HOLE names the remedy
    ``--year 2026``, a year whose tarball is a measured 404 (clim/ carries w.2000..w.2025 only), so
    the guard's disappearance would hand out a command that cannot work. And in FEBRUARY the season
    guard does not catch the fall-through at all: the leg reaches for clim/w.2026.tif.tar.gz and
    the September defect returns, three months early."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _current_year_hole_main(
            monkeypatch, m, today,
            lambda **kw: pytest.fail(f"current-year tarball requested: {kw}"),
        )
    text = "\n".join(caplog.messages)
    assert f"CURRENT-YEAR HOLE {today[0]}" in text        # the guard's OWN line, by name
    assert "the daily GeoTIFF path is the remedy" in text
    assert f"YEAR-BOUNDARY HOLE {today[0]}" not in text   # never the closed-year line
    assert f"--year {today[0]}" not in text               # never that impossible operator command


def test_cpc_fallback_is_still_wired_per_hole_year_for_a_CLOSED_year(monkeypatch):
    """The self-heal 0b16421b added is kept, not deleted -- only its year is guarded. A December
    hole seen from January still pulls YEAR-1's tarball, and it is the hole's year, not the run's."""
    m = _cpc()

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 10)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    published = sorted(_days(datetime.date(2027, 1, 1), datetime.date(2027, 1, 8)))
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda year, variable: (published, True))
    present = {
        2027: set(published),
        2026: _days(datetime.date(2026, 12, 1), datetime.date(2026, 12, 15)),
    }
    monkeypatch.setattr(m, "_list_present_raw_days", lambda b, r, v, y: set(present[y]))
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    seen: list[dict] = []
    monkeypatch.setattr(m, "_process_year_via_tarball", lambda **kw: seen.append(kw) or (16, 0))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()
    assert [kw["year"] for kw in seen] == [2026]
    assert seen[0]["force_overwrite"] is False


def _january_main(monkeypatch, m, tarball):
    """A 2027-01-10 run with a half-full previous December -- the case that legitimately reaches
    a closed year's tarball."""
    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 10)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    published = sorted(_days(datetime.date(2027, 1, 1), datetime.date(2027, 1, 8)))
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda year, variable: (published, True))
    present = {
        2027: set(published),
        2026: _days(datetime.date(2026, 12, 1), datetime.date(2026, 12, 15)),
    }
    monkeypatch.setattr(m, "_list_present_raw_days", lambda b, r, v, y: set(present[y]))
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball", tarball)
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()


def test_cpc_a_tarball_not_yet_published_declines_the_self_heal_instead_of_failing_the_leg(
    monkeypatch,
):
    """THE JANUARY EDGE -- the same 404, three months later. A year closing does not make its
    archive exist: clim/w.2025.tif.tar.gz carries Last-Modified "Tue, 03 Mar 2026 23:03:20 GMT",
    about two months after 2025 ended. From January to roughly March a December hole finds no
    tarball, and an OPPORTUNISTIC remedy must never fail a leg whose real work already succeeded."""
    m = _cpc()

    def _not_published(**kw):
        resp = requests.Response()
        resp.status_code = 404
        raise requests.HTTPError("404 Client Error: Not Found", response=resp)

    _january_main(monkeypatch, m, _not_published)     # must NOT raise


def test_cpc_a_non_4xx_tarball_failure_still_fails_the_leg(monkeypatch):
    """The other half: a 503 is an anomaly worth an alarm, not a stated absence."""
    m = _cpc()

    def _server_error(**kw):
        resp = requests.Response()
        resp.status_code = 503
        raise requests.HTTPError("503 Server Error", response=resp)

    with pytest.raises(requests.HTTPError):
        _january_main(monkeypatch, m, _server_error)


def test_cpc_the_loud_instrument_lines_survive():
    src = (_REPO / "jobs" / "batch" / "cpc_soil_to_raw_task.py").read_text(encoding="utf-8")
    assert "_trailing_month_holes(present_days, published_days, today=today)" in src
    assert re.search(r"for hy in hole_years:.*\n(?:.*\n)*?.*_process_year_via_tarball\(\n\s*year=hy",
                     src)
    assert "TRAILING-MONTH HOLE" in src                   # the loud line a silent skip never had
    assert "CURRENT-YEAR HOLE" in src                     # the distinct line for the guarded case
    assert "UPSTREAM SHORT" in src                        # the calendar fact, not deleted
    assert "UPSTREAM SHORT BLIND" in src                  # and its stated decline when index-less
    assert "TARBALL NOT PUBLISHED" in src                 # the January edge, stated not swallowed
    assert "YEAR-BOUNDARY HOLE" in src                    # Dec 30/31, visible past the archive season
    assert "SINGLE-DAY DECLINE" in src                    # the one-day window, warned not reddened
    assert "UPSTREAM STALL" in src                        # the calendar-side alarm's stated reason
    assert "PUBLISHER STALL BLIND" in src                 # and ITS decline when there is no tip
    # THE ALARMS. A warning is not an instrument here -- the exit code is the only one that fires,
    # so both raises and both re-raises in main() are pinned by source.
    assert "raise DailyWindowOutage(" in src
    assert re.search(r"if outage is not None:\n\s*#(?:.*\n)*?\s*raise outage", src)
    assert "stall = PublisherStall(reason)" in src
    assert re.search(r"if stall is not None:\n\s*#(?:.*\n)*?\s*raise stall", src)
    # and the floor the outage is measured against is a NAMED constant, never an inline literal
    assert "if len(targets) >= _OUTAGE_MIN_WINDOW_DAYS:" in src
    assert "days_behind >= _PUBLISHER_STALL_RED_DAYS" in src
    assert "days_behind >= _PUBLISHER_STALL_WARN_DAYS" in src


# ── cpc: the daily window is BOUNDED by the listing and by what raw already holds ───────────────
def _daily_window(m, monkeypatch, published, present, force_overwrite=False, downloader=None):
    fetched: list[str] = []

    def _default(ds, v):
        fetched.append(ds)
        return b"TIF"

    monkeypatch.setattr(m, "download_cpc_daily_tif", downloader or _default)
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    monkeypatch.setattr(m, "_put_tif", lambda *a, **k: True)
    written, skipped = m._process_year_via_daily_files(
        year=2026, variable="w", bucket="B", aws_region="R", ingest_date="2026-01-12",
        force_overwrite=force_overwrite, published_days=list(published), present_days=set(present),
    )
    return fetched, written, skipped


def test_cpc_daily_window_is_the_published_days_raw_does_not_already_hold(monkeypatch):
    """PIN (c). Never a day beyond the listing, never a day already ingested -- and an INTERIOR gap
    stays in the window, because a strict high-water mark would reopen the permanence trap."""
    m = _cpc()
    published = sorted(_days(datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)))
    present = {"20260101", "20260102", "20260103", "20260105", "20260106", "20260107"}
    fetched, written, skipped = _daily_window(m, monkeypatch, published, present)
    assert sorted(fetched) == ["20260104", "20260108", "20260109", "20260110"]
    assert "20260104" in fetched                          # the interior gap heals
    assert "20260111" not in fetched                      # nothing beyond the listing
    assert not (set(fetched) & present)                   # nothing already ingested
    assert (written, skipped) == (4, 6)


def test_cpc_a_run_with_nothing_new_fetches_nothing(monkeypatch):
    m = _cpc()
    published = sorted(_days(datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)))
    fetched, written, skipped = _daily_window(m, monkeypatch, published, set(published))
    assert fetched == [] and written == 0 and skipped == 10


def test_cpc_force_overwrite_refetches_every_published_day(monkeypatch):
    m = _cpc()
    published = sorted(_days(datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)))
    fetched, written, _ = _daily_window(
        m, monkeypatch, published, set(published), force_overwrite=True,
    )
    assert sorted(fetched) == published and written == 10


def test_cpc_a_404_on_one_daily_is_a_per_day_decline_not_a_leg_failure(monkeypatch):
    """PIN (d). The leg's job is to carry forward every day it can reach; the hole report is what
    makes the unreachable one visible."""
    m = _cpc()

    def _one_404(ds, v):
        if ds == "20260908":
            raise requests.HTTPError("404 Client Error: Not Found")
        return b"TIF"

    fetched, written, skipped = _daily_window(
        m, monkeypatch, ["20260907", "20260908", "20260909"], set(), downloader=_one_404,
    )
    assert (written, skipped) == (2, 1)


# ── cpc: THE OUTAGE FLOOR -- reaching NOTHING is not a decline (added 2026-09-11, review MAJOR) ──
#
# The repair above turned every per-day failure into a decline, which left a hole in the contract:
# a leg that fetched NOTHING from a non-empty window exited 0 and Batch reported SUCCEEDED. That
# matters because the exit code is the ONLY instrument on this leg -- MEASURED 2026-09-11,
# ``aws logs describe-metric-filters --log-group-name /aws/batch/job`` returns nothing, and both
# weather alarms (leviathan-dev-freshness-sla-breach-weather, FreshnessLagDays > 3d, and
# leviathan-dev-freshness-breach-count-weather) read OK on 09-07 and 09-08 while silver_cpc_soil
# was frozen at 2026-09-05 and gold_weather_z at 2026-07. So a vanished source directory, an egress
# break or a cert change would have yielded SUCCEEDED forever behind one WARNING line -- the exact
# "every scheduled run succeeded while the data froze" class this wave exists to close.

def test_cpc_a_total_outage_raises_instead_of_returning_zero(monkeypatch):
    """THE MAJOR, named. Every day of a non-empty window unreachable is an OUTAGE, not 52 declines."""
    m = _cpc()

    def _all_404(ds, v):
        raise requests.HTTPError("404 Client Error: Not Found")

    with pytest.raises(m.DailyWindowOutage) as exc:
        _daily_window(
            m, monkeypatch, ["20260907", "20260908", "20260909"], set(), downloader=_all_404,
        )
    assert "to_fetch=3 declined=3" in str(exc.value)
    assert "first=20260907 last=20260909" in str(exc.value)


def test_cpc_a_partial_outage_is_still_green_and_still_writes_what_it_reached(monkeypatch):
    """The other side of the floor: one day through is work carried forward, and the hole report --
    not a red leg -- is what makes the unreachable days visible."""
    m = _cpc()

    def _only_one_works(ds, v):
        if ds != "20260909":
            raise requests.HTTPError("404 Client Error: Not Found")
        return b"TIF"

    fetched, written, skipped = _daily_window(
        m, monkeypatch, ["20260907", "20260908", "20260909"], set(), downloader=_only_one_works,
    )
    assert (written, skipped) == (1, 2)


def test_cpc_an_empty_window_is_never_an_outage(monkeypatch):
    """The guard the MAJOR fix must not overreach past: the STEADY STATE is written=0, and a
    zero-of-zero window must stay green forever."""
    m = _cpc()
    published = sorted(_days(datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)))
    fetched, written, skipped = _daily_window(m, monkeypatch, published, set(published))
    assert (fetched, written, skipped) == ([], 0, 10)


def test_cpc_a_day_s3_turned_out_to_hold_is_not_an_outage(monkeypatch):
    """PRECISION. ``written == 0`` alone would be the wrong test: a day the raw LIST missed but
    ``_put_tif`` found present is not an unreachable SOURCE. Only a declined DOWNLOAD counts."""
    m = _cpc()
    monkeypatch.setattr(m, "_put_tif", lambda *a, **k: False)      # every target already in S3
    monkeypatch.setattr(m, "download_cpc_daily_tif", lambda ds, v: b"TIF")
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    written, skipped = m._process_year_via_daily_files(
        year=2026, variable="w", bucket="B", aws_region="R", ingest_date="2026-09-11",
        force_overwrite=False, published_days=["20260907", "20260908"], present_days=set(),
    )
    assert (written, skipped) == (0, 2)                            # green: the source was reachable


def test_cpc_the_daily_window_line_adds_up(monkeypatch, caplog):
    """MINOR. The operator-facing triple is quoted verbatim in runbook step R3, so it must be
    arithmetic: published = already_raw + to_fetch. It used to print ``len(present_days)`` in the
    already_raw slot, which disagrees whenever raw holds a day the listing does not."""
    m = _cpc()
    published = sorted(_days(datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)))
    present = set(published[:6]) | {"20251231"}        # a raw day the 2026 listing does not carry
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _daily_window(m, monkeypatch, published, present)
    line = next(r for r in caplog.messages if r.startswith("Daily window"))
    assert "published=10 already_raw=6 to_fetch=4  raw_day_keys=7" in line
    assert 10 == 6 + 4                                 # the triple, stated


def test_cpc_main_reads_every_instrument_before_it_fails_on_an_outage(monkeypatch, caplog):
    """THE MEASURED SCENARIO from the review: index GET raises ConnectionError, every daily 404s,
    raw holding Jan 1 .. Jul 19. HEAD exits nonzero on this state; the un-repaired fix exited 0 with
    'written=0 declined=52'. The leg must fail -- AND the hole report must still be in the log,
    because an outage run is the one where WHAT is missing matters most."""
    m = _cpc()

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 11)

    def _no_network(url, timeout=None):
        raise requests.ConnectionError("egress break")

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m.requests, "get", _no_network)            # the live index is unreadable
    monkeypatch.setattr(m, "download_cpc_daily_tif",
                        lambda ds, v: (_ for _ in ()).throw(requests.HTTPError("404")))
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    raw_2026 = _days(datetime.date(2026, 1, 1), datetime.date(2026, 7, 19))
    monkeypatch.setattr(
        m, "_list_present_raw_days",
        lambda b, r, v, y: set(raw_2026) if y == 2026
        else _days(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31)),
    )
    monkeypatch.setattr(m, "_process_year_via_tarball",
                        lambda **kw: pytest.fail(f"self-heal against a dead source: {kw}"))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])

    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        with pytest.raises(m.DailyWindowOutage):
            m.main()

    text = "\n".join(caplog.messages)
    assert "DAILY WINDOW OUTAGE" in text
    assert "TRAILING-MONTH HOLE 2026-09" in text                   # the instruments, still read
    assert "TRAILING-MONTH HOLE 2026-08" in text
    assert "UPSTREAM SHORT BLIND" in text                          # the fence with no statement
    assert "SELF-HEAL DECLINED for 2026" in text                   # no remedy against a dead source
    assert "Done  written=0  skipped=0" in text                    # reported, THEN failed


def test_cpc_the_upstream_short_fence_says_so_when_it_is_blind(monkeypatch, caplog):
    """MINOR. ``_upstream_short_months`` returns {} whenever the live index could not be read --
    i.e. exactly when an upstream problem is likeliest. An empty dict reads like 'nothing is
    short'; the fence must DECLINE out loud instead. Fences correct or compute, never delete."""
    m = _cpc()
    assert m._upstream_short_months(None, today=datetime.date(2026, 9, 11)) == {}

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 11)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda year, variable: ([], False))
    monkeypatch.setattr(m, "_list_present_raw_days", lambda b, r, v, y: set())
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball", lambda **kw: (0, 0))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        m.main()
    assert any(msg.startswith("UPSTREAM SHORT BLIND") for msg in caplog.messages)


def test_cpc_a_one_day_window_that_wholly_declined_is_a_warning_not_red(monkeypatch, caplog):
    """MINOR (a), review round 2. The STEADY-STATE window here is exactly ONE day -- the single day
    CPC published since the last run -- so "every day of a non-empty window declined" put the whole
    leg's exit code on one 875KB GET. It is a stated WARNING instead, and two facts make that
    honest rather than a softening: a source that has STOPPED is caught against the CALENDAR by the
    PUBLISHER STALL alarm (no fetch window required), and a break that survives into the next run
    makes the window two days -- the floor below."""
    m = _cpc()
    assert m._OUTAGE_MIN_WINDOW_DAYS == 2

    def _all_404(ds, v):
        raise requests.HTTPError("404 Client Error: Not Found")

    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        fetched, written, skipped = _daily_window(
            m, monkeypatch, ["20260909"], set(), downloader=_all_404,   # window = 1 day
        )
    assert (written, skipped) == (0, 1)                   # green: no raise
    text = "\n".join(caplog.messages)
    assert "SINGLE-DAY DECLINE w 20260909" in text
    assert "window=1 day" in text and "below the 2-day outage floor" in text


def test_cpc_a_two_day_window_that_wholly_declined_is_still_red(monkeypatch):
    """The other side of the floor, measured at the boundary: the SECOND day is where red begins.
    A one-day break that lasts into the next run arrives here."""
    m = _cpc()

    def _all_404(ds, v):
        raise requests.HTTPError("404 Client Error: Not Found")

    with pytest.raises(m.DailyWindowOutage) as exc:
        _daily_window(m, monkeypatch, ["20260908", "20260909"], set(), downloader=_all_404)
    assert "to_fetch=2 declined=2" in str(exc.value)
    assert "window 2 days >= the 2-day outage floor" in str(exc.value)


# ── cpc: THE PUBLISHER-STALL ALARM -- can this leg see CPC STOP? (added 2026-09-11, round 2) ────
#
# THE MAJOR the round-1 repair left open. Moving the current year's expectation off the calendar
# and onto CPC's published SET is what killed the phantom hole -- and it is also what made a
# stopped publisher invisible. Drive the round-1 code with the index frozen at tip 20260909 and raw
# complete to that tip: 2026-09-12 exits 0 with ZERO warnings; 2026-09-20, eleven days stale, exits
# 0 with ZERO warnings. The hole report finds no deficit (we hold every published day) and the
# UPSTREAM SHORT fence skips September until it is settled past the lag, so its first word would
# come only on 2026-10-05. Three weeks of a frozen source, reported SUCCEEDED -- the same class as
# the freeze this whole wave exists to close, re-entered through the front door.
#
# So the calendar is not deleted, it is put where it belongs: the published SET remains the
# expectation for what raw must HOLD; the published TIP is measured against the CALENDAR for
# whether the source is still alive.

def _frozen_index_main(monkeypatch, m, today, tip, tarball=None):
    """A run whose raw is COMPLETE to a FROZEN publication tip -- a perfect leg, a dead source."""
    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(*today)

    published = sorted(_days(datetime.date(tip[0], 1, 1), datetime.date(*tip)))
    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda y, variable: (published, True))
    monkeypatch.setattr(
        m, "_list_present_raw_days",
        lambda b, r, v, y: set(published) if y == tip[0]
        else _days(datetime.date(tip[0] - 1, 12, 1), datetime.date(tip[0] - 1, 12, 31)),
    )
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball",
                        tarball or (lambda **kw: pytest.fail(f"no hole, no tarball: {kw}")))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()


def test_cpc_publisher_stall_is_the_tip_measured_against_the_calendar():
    """The predicate, driven at every threshold. days_behind = (today - lag) - newest_published."""
    m = _cpc()
    assert (m._PUBLISHER_STALL_WARN_DAYS, m._PUBLISHER_STALL_RED_DAYS) == (3, 7)
    tip = {"20260909"}
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 11)) == ("20260909", 0, "quiet")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 12)) == ("20260909", 1, "quiet")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 13)) == ("20260909", 2, "quiet")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 14)) == ("20260909", 3, "warning")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 17)) == ("20260909", 6, "warning")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 18)) == ("20260909", 7, "red")
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 20)) == ("20260909", 9, "red")
    # A publisher AHEAD of the measured lag is kept negative, not clamped: that is the reading that
    # would justify re-measuring _PUBLICATION_LAG_DAYS downward, and a clamp would hide it.
    assert m._publisher_stall(tip, today=datetime.date(2026, 9, 10)) == ("20260909", -1, "quiet")
    # BLIND is not QUIET: no statement to measure is its own answer, and the caller must say so.
    assert m._publisher_stall(None, today=datetime.date(2026, 9, 18)) is None
    assert m._publisher_stall(set(), today=datetime.date(2026, 9, 18)) is None


def test_cpc_publisher_stall_ignores_a_future_dated_tip_and_names_it():
    """The one-entry off switch (review 2026-09-11): a listed day after today must not become the
    tip.  With the index frozen at 20260909 and ONE poisoned entry 20261231, the alarm at 2026-10-15
    still reads RED on the real tip, the poisoned entry is NAMED, and a set that is ALL future is BLIND
    (None), never quiet."""
    m = _cpc()
    poisoned = {"20260909", "20261231"}
    assert m._publisher_stall(poisoned, today=datetime.date(2026, 10, 15)) == ("20260909", 34, "red")
    assert m._publisher_stall(poisoned, today=datetime.date(2026, 11, 30)) == ("20260909", 80, "red")
    assert m._future_dated(poisoned, today=datetime.date(2026, 10, 15)) == ["20261231"]
    # a day published TODAY is not future-dated: it is CPC ahead of its lag, kept negative
    assert m._publisher_stall({"20261015"}, today=datetime.date(2026, 10, 15)) == ("20261015", -2, "quiet")
    assert m._future_dated({"20261015"}, today=datetime.date(2026, 10, 15)) == []
    # an all-future set is BLIND
    assert m._publisher_stall({"20261231"}, today=datetime.date(2026, 10, 15)) is None
    assert m._future_dated(None, today=datetime.date(2026, 10, 15)) == []
    src = (_REPO / "jobs" / "batch" / "cpc_soil_to_raw_task.py").read_text(encoding="utf-8")
    assert "PUBLISHER TIP DISCARDED" in src                  # the caller names the discard out loud
    assert "usable = {d for d in published_days if d <= cutoff}" in src


def test_cpc_the_steady_state_day_is_quiet():
    """tip = today - the measured lag, every day of a year: days_behind 0, never a word."""
    m = _cpc()
    for offset in (0, 40, 120, 300):
        today = datetime.date(2026, 1, 1) + datetime.timedelta(days=offset + 10)
        tip = today - datetime.timedelta(days=m._PUBLICATION_LAG_DAYS)
        assert m._publisher_stall({tip.strftime("%Y%m%d")}, today=today)[1:] == (0, "quiet")


def test_cpc_a_frozen_index_three_days_past_the_lag_warns(monkeypatch, caplog):
    """THE DRIVE the round-1 code was silent on. 2026-09-14, tip 20260909, raw complete: the leg
    still exits 0 -- correctly, there is nothing for it to fetch -- but it is no longer QUIET."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _frozen_index_main(monkeypatch, m, (2026, 9, 14), (2026, 9, 9))
    warnings = [r.message for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    text = "\n".join(warnings)
    assert "UPSTREAM STALL: newest published w.20260909 is 3 days behind the lag" in text
    assert "warn at 3, red at 7" in text
    assert "-- WARNING" in text
    assert not any("RED" in w for w in warnings)


def test_cpc_a_frozen_index_a_week_past_the_lag_is_RED_with_the_reason(monkeypatch, caplog):
    """THE MAJOR, closed. A PERFECT run -- raw holds every published day, nothing declined,
    written=0 -- and the source has not moved in a week. The exit code is the only instrument that
    can say so, so it says so."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        with pytest.raises(m.PublisherStall) as exc:
            _frozen_index_main(monkeypatch, m, (2026, 9, 18), (2026, 9, 9))
    assert "UPSTREAM STALL: newest published w.20260909 is 7 days behind the lag" in str(exc.value)
    assert "measured publication lag 2 days" in str(exc.value)
    text = "\n".join(caplog.messages)
    assert "Done  written=0  skipped=0" in text           # every instrument read, THEN the failure
    assert "TRAILING-MONTH HOLE" not in text              # and no invented hole: raw IS complete


def test_cpc_a_frozen_index_inside_the_threshold_stays_quiet(monkeypatch, caplog):
    """The guard the alarm must not overreach past: 2026-09-12 with tip 20260909 is ONE day behind
    the measured lag -- ordinary upstream lateness, and the leg must not cry about it."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _frozen_index_main(monkeypatch, m, (2026, 9, 12), (2026, 9, 9))
    warnings = [r.message for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert warnings == []                                 # zero warnings, and correctly so
    assert any("Publisher tip w.20260909 is 1 days behind" in msg for msg in caplog.messages)


def test_cpc_the_steady_state_run_end_to_end_is_quiet(monkeypatch, caplog):
    """tip = today - 2, raw complete: the shape of every healthy morning. Nothing must fire."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _frozen_index_main(monkeypatch, m, (2026, 9, 11), (2026, 9, 9))
    assert [r.message for r in caplog.records if r.levelname in ("WARNING", "ERROR")] == []


def test_cpc_without_the_stall_alarm_the_first_word_would_be_weeks_late(monkeypatch, caplog):
    """THE MEASUREMENT THAT SIZES THE DEFECT, kept in the deck. With the index frozen at 20260909,
    the only OTHER fence that can speak is _upstream_short_months, and it skips September until the
    month is settled past the lag. MEASURED HERE: its first word lands 2026-10-02 -- 23 days after
    the tip, and 11 days after an eleven-day-stale run had already reported SUCCEEDED in silence.
    (The round-2 review estimated 10-05; the boundary is 10-02, because September's last day clears
    ``today - _PUBLICATION_LAG_DAYS`` on that date. The figure is the code's, not the estimate's.)
    The stall alarm speaks on 09-14 and is red on 09-18."""
    m = _cpc()
    published = _days(datetime.date(2026, 1, 1), datetime.date(2026, 9, 9))
    assert m._upstream_short_months(published, today=datetime.date(2026, 9, 20)) == {}
    assert m._upstream_short_months(published, today=datetime.date(2026, 10, 1)) == {}
    assert m._upstream_short_months(published, today=datetime.date(2026, 10, 2)) == {
        "2026-09": (9, 30),
    }
    assert (datetime.date(2026, 10, 2) - datetime.date(2026, 9, 9)).days == 23
    # and on that same 09-20 the stall alarm has been RED for two days
    assert m._publisher_stall(published, today=datetime.date(2026, 9, 20))[2] == "red"


def test_cpc_the_stall_alarm_declines_out_loud_when_it_is_blind(monkeypatch, caplog):
    """Same doctrine as UPSTREAM SHORT BLIND: an instrument with nothing to measure must never be
    mistaken for a healthy one. No published tip, no verdict -- said out loud."""
    m = _cpc()

    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 11)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda year, variable: ([], False))
    monkeypatch.setattr(m, "_list_present_raw_days", lambda b, r, v, y: set())
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball", lambda **kw: (0, 0))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        m.main()
    text = "\n".join(caplog.messages)
    assert "PUBLISHER STALL BLIND" in text
    # and the hole lines on that same blind run PRINT the calendar basis they actually used --
    # MINOR (b): the old line asserted "days CPC has PUBLISHED" even here, which is false.
    assert "expected basis = CALENDAR days minus the measured 2-day publication lag" in text
    assert "the days CPC has PUBLISHED" not in text


# ── cpc: THE YEAR-BOUNDARY FENCE -- Dec 30/31 reach no path (added 2026-09-11, review MINOR) ────
#
# CPC publishes day D at about 17:53Z on D+1, so Dec 30 lands on Dec 31 and Dec 31 lands on Jan 1 --
# both AFTER the last 08:00Z fire that asks for that year. Neither day ever reaches the daily path.
# MEASURED IN THIS ESTATE: raw date=20251230 and date=20251231 exist but carry LastModified
# 2026-05-24 -- five months late, rescued by a hand `--year 2025` tarball backfill, never by the
# scheduled leg. The January self-heal correctly declines (clim/w.2025.tif.tar.gz was published
# 2026-03-03, two months after the year closed) -- but before this fix the report looked back only
# ONE month, so from February 1 the December hole stopped being reported at all, months before the
# archive that could heal it even exists.

def test_cpc_the_previous_december_is_inspected_every_month_of_the_year():
    m = _cpc()
    for month in range(1, 13):
        months = m._inspected_months(datetime.date(2026, month, 15))
        assert (2025, 12) in months, f"December fell out of view in month {month}"
        assert (2026, month) in months                  # the current month, always
    # no duplicate in January, where "previous month" IS the previous December
    assert m._inspected_months(datetime.date(2026, 1, 15)) == [(2026, 1), (2025, 12)]
    # and in December the PREVIOUS December is the prior year's, not this month
    assert m._inspected_months(datetime.date(2026, 12, 3)) == [(2026, 12), (2026, 11), (2025, 12)]


def test_cpc_a_july_run_still_reports_the_previous_december_hole():
    """THE DEFECT, dated. Under the one-month lookback this dict had no 2025-12 key at all in July."""
    m = _cpc()
    today = datetime.date(2026, 7, 15)
    published = _days(datetime.date(2026, 6, 1), datetime.date(2026, 7, 13))
    present = set(published) | _days(datetime.date(2025, 12, 1), datetime.date(2025, 12, 29))
    holes = m._trailing_month_holes(present, published, today=today)
    # the two year-boundary days, visible
    assert holes["2025-12"] == (29, 31, m._BASIS_CALENDAR_FULL)
    assert [ym for ym, (p, e, _b) in holes.items() if p < e] == ["2025-12"]


def _main_with_december_hole(monkeypatch, m, today, tarball):
    """A run whose previous December is two days short -- the Dec 30/31 shape, exactly."""
    class _D(datetime.date):
        @classmethod
        def today(cls):
            return cls(*today)

    monkeypatch.setattr(m, "date", _D)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setattr(m, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    year = today[0]
    tip = datetime.date(*today) - datetime.timedelta(days=m._PUBLICATION_LAG_DAYS)
    published = sorted(_days(datetime.date(year, 1, 1), tip))   # a healthy current year
    monkeypatch.setattr(m, "_list_available_daily_dates", lambda y, variable: (published, True))
    monkeypatch.setattr(
        m, "_list_present_raw_days",
        lambda b, r, v, y: set(published) if y == year
        else _days(datetime.date(year - 1, 12, 1), datetime.date(year - 1, 12, 29)),
    )
    monkeypatch.setattr(m, "_process_year_via_daily_files", lambda **kw: (0, 0))
    monkeypatch.setattr(m, "_process_year_via_tarball", tarball)
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    m.main()


def test_cpc_an_in_season_december_hole_still_reaches_the_archive(monkeypatch):
    """January through March: the archive may have published, so the self-heal still tries."""
    m = _cpc()
    seen: list[dict] = []
    _main_with_december_hole(monkeypatch, m, (2027, 3, 20),
                             lambda **kw: seen.append(kw) or (2, 0))
    assert [kw["year"] for kw in seen] == [2026]


def test_cpc_an_out_of_season_december_hole_names_the_operator_backfill(monkeypatch, caplog):
    """From April the archive has either healed it or is itself short, so an 86MB retry a day buys
    nothing. The hole stays REPORTED and the remedy is named -- never silently dropped."""
    m = _cpc()
    with caplog.at_level("INFO", logger="cpc_soil_to_raw_task"):
        _main_with_december_hole(
            monkeypatch, m, (2027, 7, 15),
            lambda **kw: pytest.fail(f"out-of-season archive retry: {kw}"),
        )
    text = "\n".join(caplog.messages)
    assert "TRAILING-MONTH HOLE 2026-12: 29/31" in text        # still visible in July
    assert "YEAR-BOUNDARY HOLE 2026 STANDS" in text
    assert "--year 2026" in text                                # the operator's exact command
    assert m._ARCHIVE_SELF_HEAL_THROUGH_MONTH == 3              # measured: w.2025 landed 2026-03-03


# ── cpc: the CLOSED-year tarball path is untouched ──────────────────────────────────────────────
_CLIM_YEAR = re.compile(r'href="w\.(\d{4})\.tif\.tar\.gz"')


def test_cpc_clim_carries_closed_years_only_and_the_fixture_assertion_bites():
    """PIN (b), premise half. The captured clim/ index is the evidence that there is no current-year
    tarball to fall back TO. The mutation proves the assertion reads the capture rather than merely
    restating a constant."""
    html = (_FIXTURES / "clim_index.sample.html").read_text(encoding="utf-8")
    years = {int(y) for y in _CLIM_YEAR.findall(html)}
    assert years == set(range(2000, 2026))                # captured 2026-09-11: w.2000..w.2025
    assert 2026 not in years                              # HEAD clim/w.2026.tif.tar.gz = 404
    mutated = html.replace(
        '<tr><td><a href="w.2025.tif.tar.gz">',
        '<tr><td><a href="w.2026.tif.tar.gz">w.2026.tif.tar.gz</a></td></tr>\n'
        '<tr><td><a href="w.2025.tif.tar.gz">',
    )
    assert 2026 in {int(y) for y in _CLIM_YEAR.findall(mutated)}


def test_cpc_closed_year_path_still_goes_through_the_unchanged_clim_tarball(monkeypatch):
    """PIN (b). Same URL, same members, uploaded unchanged."""
    m = _cpc()
    seen: dict = {}
    monkeypatch.setattr(m, "download_cpc_annual_tarball",
                        lambda year, variable: seen.update(year=year, variable=variable) or b"TAR")
    monkeypatch.setattr(m, "extract_tifs_from_tarball",
                        lambda tar, variable: {"20251230": b"A", "20251231": b"B"})
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    uploaded: dict = {}
    monkeypatch.setattr(
        m, "_put_tif",
        lambda c, b, v, ds, body, url, ts, fo: uploaded.update({ds: (body, url)}) or True,
    )
    written, skipped = m._process_year_via_tarball(
        year=2025, variable="w", bucket="B", aws_region="R",
        ingest_date="2026-09-11", force_overwrite=False,
    )
    assert seen == {"year": 2025, "variable": "w"}
    assert (written, skipped) == (2, 0)
    assert uploaded["20251231"][0] == b"B"                # member bytes uploaded unchanged
    assert uploaded["20251231"][1].endswith("/clim/w.2025.tif.tar.gz")


def test_cpc_retry_and_timeout_shape_is_unchanged():
    """PIN (e). The repair changed WHICH url is requested and WHEN, never the request shape."""
    from leviathan.ingestion.weather import cpc_soil_moisture as cpc

    daily = cpc.download_cpc_daily_tif.retry
    assert daily.stop.max_attempt_number == 3
    assert (daily.wait.multiplier, daily.wait.min, daily.wait.max) == (2, 2.0, 30.0)
    assert daily.retry.exception_types is requests.RequestException
    assert daily.reraise is True

    tarball = cpc.download_cpc_annual_tarball.retry
    assert tarball.stop.max_attempt_number == 3
    assert (tarball.wait.multiplier, tarball.wait.min, tarball.wait.max) == (2, 10.0, 60.0)
    assert tarball.retry.exception_types is requests.RequestException
    assert tarball.reraise is True

    assert (cpc._REQUEST_TIMEOUT, cpc._TARBALL_TIMEOUT) == (60, 300)


# ── cpc raw->bronze: THE SAME DEFECT CLASS, one layer further down (measured 2026-09-11) ────────
#
# The 404 above cost no data -- raw was complete through every published day. The fifteen missing
# silver days (2026-08-21..08-31 and 2026-09-06..09-09) came from here: _write_bronze_partition
# skipped any existing month object on EXISTENCE alone. MEASURED on
# corn_cbot/us_corn_south_dakota/year=2026: month=08 held 20 of 31 days with access_timestamp
# 2026-08-22T11:31:43Z and month=09 held Sep 1..5 with 2026-09-07T08:55:12Z, while the job
# SUCCEEDED on 09-08 and 09-09, read all 252 raw days, and declined to rewrite either. Silver
# carried the freeze faithfully: max(date) 2026-09-05 over 101,254 rows, 30 of 31 commodities at
# August=20 / September=5. The bronze->silver leg above it was already freshness-aware
# (base_jobs.select_partitions_to_write); this is that same rule, one layer down.

_T_BRONZE = datetime.datetime(2026, 9, 7, 8, 55, 12, tzinfo=datetime.timezone.utc)   # frozen bronze
_T_RAW = datetime.datetime(2026, 9, 11, 8, 47, 11, tzinfo=datetime.timezone.utc)     # newest raw


def _cpc_r2b():
    return _load("cpc_r2b_t", "jobs/batch/cpc_raw_to_bronze_task.py")


class _ClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3:
    class exceptions:
        ClientError = _ClientError

    def __init__(self, bronze_mtime, prior_meta=...) -> None:
        self._bronze_mtime = bronze_mtime
        # ``...`` = no companion meta at all (the pre-layout partition); None = a meta whose body
        # is unreadable JSON. Anything else is the meta dict itself.
        self._prior_meta = prior_meta
        self.puts: list[str] = []
        self.gets: list[str] = []

    def head_object(self, Bucket, Key):
        if self._bronze_mtime is None:
            raise _ClientError("404")
        return {"LastModified": self._bronze_mtime, "ContentLength": 1}

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        if self._prior_meta is ...:
            raise _ClientError("NoSuchKey")
        body = b"<not json>" if self._prior_meta is None else json.dumps(self._prior_meta).encode()
        return {"Body": io.BytesIO(body)}

    def put_object(self, **kw):
        self.puts.append(kw["Key"])


def _write(m, s3, raw_max_mtime, force_overwrite=False, n_rows=1):
    return m._write_bronze_partition(
        s3_client=s3, bucket="B", commodity="corn_cbot", variable="w",
        country="us", region="us_corn_south_dakota", year=2026, month=9,
        rows=[{"soil_moisture_mm": 1.0}] * n_rows, ingest_date="2026-09-11",
        access_timestamp="2026-09-11T09:00:00Z", force_overwrite=force_overwrite,
        raw_max_mtime=raw_max_mtime,
    )


def test_cpc_bronze_month_is_rewritten_when_its_raw_is_newer():
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_BRONZE)
    assert _write(m, s3, _T_RAW) == "written"
    assert any(k.endswith("part-000.parquet") for k in s3.puts)


def test_cpc_bronze_month_is_skipped_while_it_is_still_fresh():
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_RAW)
    assert _write(m, s3, _T_BRONZE) == "skipped"
    assert s3.puts == []                                  # a no-op rerun stays a no-op (AV-12)
    assert s3.gets == []                                  # and a fresh skip costs no meta GET


def test_cpc_bronze_month_is_written_when_absent():
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=None)
    assert _write(m, s3, _T_RAW) == "written"


# ── cpc raw->bronze: THE SHRINK FLOOR -- a rewrite REPLACES (added 2026-09-11, review round 2) ──
#
# The freshness rule above is what brings the fifteen days back, and it is also what made shrinking
# reachable: before it, a month partition was written once and never touched again; after it, every
# run may REPLACE it with whatever ``rows_by_partition`` collected THIS run. A run that reads 5 of
# 30 raw days -- S3 throttling, a truncated LIST, a raw prefix half deleted -- would have written a
# 5-row partition over a 30-row one and logged "Wrote bronze". Silver would have carried the loss
# faithfully, exactly as it carried the freeze. So the floor ships with the rule that opened it.

def test_cpc_bronze_rewrite_that_would_shrink_a_partition_declines_by_name(caplog):
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_BRONZE, prior_meta={"row_count": 30})
    with caplog.at_level("INFO", logger="cpc_raw_to_bronze_task"):
        result = _write(m, s3, _T_RAW, n_rows=5)          # stale AND smaller
    assert result == "declined"
    assert s3.puts == []                                  # the 30-row partition is LEFT AS IT IS
    text = "\n".join(caplog.messages)
    assert "BRONZE REWRITE DECLINED (shrink floor)" in text      # declined BY NAME
    assert m._SHRINK_FLOOR_RULE in text                          # with the rule stated, not implied
    assert "collected 5 rows" in text and "holds 30" in text     # both figures, in analyst units


def test_cpc_bronze_shrink_floor_is_the_rule_stated_as_a_pure_predicate():
    m = _cpc_r2b()
    assert m._rewrite_would_shrink(30, 5) is True
    assert m._rewrite_would_shrink(30, 31) is False       # GROWING is the whole point of the repair
    assert m._rewrite_would_shrink(30, 30) is False       # equal: the ordinary same-day rerun
    assert m._rewrite_would_shrink(None, 5) is False      # unknown is never grounds to act (AV-12)
    assert "FEWER rows" in m._SHRINK_FLOOR_RULE


def test_cpc_bronze_a_growing_rewrite_is_exactly_what_must_still_happen():
    """THE REGRESSION THE FLOOR MUST NOT CAUSE. August 2026 held 20 of 31 days; the repair's whole
    job is to replace it with 31. A floor that blocked that would re-freeze the estate."""
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_BRONZE, prior_meta={"row_count": 20})
    assert _write(m, s3, _T_RAW, n_rows=31) == "written"
    assert any(k.endswith("part-000.parquet") for k in s3.puts)


@pytest.mark.parametrize("prior_meta", [..., None, {}, {"row_count": "30"}, {"row_count": True}])
def test_cpc_bronze_an_unknown_prior_count_stands_the_floor_down(prior_meta):
    """No meta, unreadable meta, no row_count, a STRING row_count, a bool masquerading as an int:
    none of them is a measured prior size, and declining on an unknown would refuse exactly the
    partitions whose meta predates this layout. Symmetric with ``_bronze_is_stale``'s own rule."""
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_BRONZE, prior_meta=prior_meta)
    assert _write(m, s3, _T_RAW, n_rows=1) == "written"
    assert m._prior_bronze_row_count(s3, "B", "k/part-000.parquet") is None


def test_cpc_bronze_force_overwrite_names_the_overwrite_and_steps_past_the_floor():
    """The flag exists to repair a partition that is wrong, and some of those repairs are smaller.
    It must reach the write without ever consulting head_object or the meta."""
    m = _cpc_r2b()
    s3 = _FakeS3(bronze_mtime=_T_BRONZE, prior_meta={"row_count": 30})
    assert _write(m, s3, _T_RAW, force_overwrite=True, n_rows=5) == "written"
    assert s3.gets == []


def test_cpc_bronze_a_declined_rewrite_is_not_counted_as_a_skip(monkeypatch, caplog):
    """A skip means the partition was already correct; a decline means this run tried to change it
    and was stopped. Folding one into the other is the miniature of the defect this wave closes --
    a summary line that reads like nothing needed doing."""
    m = _cpc_r2b()
    monkeypatch.setattr(m, "list_s3_keys_with_mtime", lambda *a, **k: {
        "raw/weather/source=cpc_soil/variable=w/date=20260901/w.20260901.tif": _T_RAW,
    })
    monkeypatch.setattr(m, "_fetch_tif", lambda region, bucket, variable, ds: (ds, b"TIF"))
    monkeypatch.setattr(m, "extract_region_values",
                        lambda body, locs: {loc["region"]: 1.0 for loc in locs})
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    monkeypatch.setattr(m, "_write_bronze_partition", lambda **kw: "declined")
    with caplog.at_level("INFO", logger="cpc_raw_to_bronze_task"):
        m._process_year(
            aws_region="R", bucket="B",
            all_commodity_locations={"corn_cbot": [
                {"country": "us", "region": "us_corn_south_dakota",
                 "latitude": 44.0, "longitude": -100.0},
            ]},
            variable="w", year=2026, ingest_date="2026-09-11", force_overwrite=False,
        )
    text = "\n".join(caplog.messages)
    assert "written=0 skipped=0 declined=1" in text
    assert "BRONZE SHRINK FLOOR HELD on 1 partition(s)" in text


def test_cpc_bronze_freshness_rule_matches_silver_v002():
    m = _cpc_r2b()
    assert m._bronze_is_stale(_T_BRONZE, _T_RAW) is True
    assert m._bronze_is_stale(_T_RAW, _T_BRONZE) is False
    assert m._bronze_is_stale(_T_RAW, _T_RAW) is False    # equal: not stale
    assert m._bronze_is_stale(None, _T_RAW) is False      # unknown is never grounds for a rewrite
    assert m._bronze_is_stale(_T_BRONZE, None) is False


def test_cpc_process_year_hands_each_month_its_newest_raw_mtime(monkeypatch):
    """The wiring: September's yardstick is 09-09's object, not 09-01's."""
    m = _cpc_r2b()
    keys = {
        "raw/weather/source=cpc_soil/variable=w/date=20260831/w.20260831.tif": _T_BRONZE,
        "raw/weather/source=cpc_soil/variable=w/date=20260901/w.20260901.tif": _T_BRONZE,
        "raw/weather/source=cpc_soil/variable=w/date=20260909/w.20260909.tif": _T_RAW,
    }
    monkeypatch.setattr(m, "list_s3_keys_with_mtime", lambda *a, **k: dict(keys))
    monkeypatch.setattr(m, "_fetch_tif", lambda region, bucket, variable, ds: (ds, b"TIF"))
    monkeypatch.setattr(m, "extract_region_values",
                        lambda body, locs: {loc["region"]: 1.0 for loc in locs})
    monkeypatch.setattr(m, "get_thread_local_s3_client", lambda region: object())
    seen: dict = {}
    monkeypatch.setattr(
        m, "_write_bronze_partition",
        lambda **kw: seen.update({(kw["year"], kw["month"]): kw["raw_max_mtime"]}) or "written",
    )
    m._process_year(
        aws_region="R", bucket="B",
        all_commodity_locations={"corn_cbot": [
            {"country": "us", "region": "us_corn_south_dakota",
             "latitude": 44.0, "longitude": -100.0},
        ]},
        variable="w", year=2026, ingest_date="2026-09-11", force_overwrite=False,
    )
    assert seen == {(2026, 8): _T_BRONZE, (2026, 9): _T_RAW}


def test_cpc_bronze_existence_alone_no_longer_skips_a_month():
    """Source pin, the jobdef-fence idiom: a refactor that drops the freshness read silently
    refreezes the current month, and the job keeps reporting SUCCEEDED while it does."""
    src = (_REPO / "jobs" / "batch" / "cpc_raw_to_bronze_task.py").read_text(encoding="utf-8")
    assert "list_s3_keys_with_mtime" in src
    assert "_bronze_is_stale(bronze_mtime, raw_max_mtime)" in src
    assert "raw_max_mtime=raw_max_mtime_by_month.get((yr, month))" in src
    # and the floor that rule opened: a rewrite REPLACES, so it may never shrink a partition
    assert "_rewrite_would_shrink(prior_rows, len(rows))" in src
    assert "BRONZE REWRITE DECLINED (shrink floor)" in src
    assert 'return "declined"' in src                     # a decline is not a skip, and is counted
