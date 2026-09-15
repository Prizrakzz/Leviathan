"""THE PRELIMINARY STAMP AT GOLD -- the flag that nearly died one seam before it was used, and the
BYTE-IDENTITY PROOF that the whole 1981..2026-07 corpus is untouched by the lane that added it.

WHY A STAMP AT ALL.  ``drought_z`` may now be computed from CHIRPS v2.0 PRELIM days, about eighteen days
before the authoritative FINAL block lands; when the block lands the month is RECOMPUTED and the served
z CHANGES after it has been served.  ``state/analogs.state_history`` builds its knowledge axis from the
declared lag and ranks candidate crossings against a historical distribution, so a z that moves after
publication makes a banked analog ranking non-reproducible from today's bytes -- and nothing in the
estate recorded that a row was preliminary when it was read.  The stamp is that record.

IT IS AN OBSERVATION, NOT A PREDICTION, and that distinction is the reason it costs a row.  The cheap
alternative -- derive "preliminary" from (data month, today, the two declared lags) -- over-labels a
month preliminary between the final's real landing (+12..+16) and the declared horizon (25), which is
merely fail-CLOSED and safe; but past 25 it labels a PERMANENTLY-prelim month "final", which is a leak.
Only the observation cannot be wrong about a month the source never completed.

WHAT NEARLY KILLED IT (T-E1).  ``gold_weather_z_task._to_long`` returned ``ids + ["variable", "value"]``
for an already-long chirps frame and DROPPED EVERY OTHER COLUMN, so ``is_preliminary`` would have
vanished at the gold reader seam with no error, and the lane would have shipped a flag that reaches
nothing.

THE PROOF OBLIGATION, EXECUTED (THREAT_MODEL sec 2 close).  Two cases at the bottom of this file drive a
month whose every day is FINAL from fetch -> bronze rows -> silver long -> ``compute_weather_z`` and
compare against the PRE-LANE module loaded out of ``git show HEAD:...``: element-wise equality for the
pre-lane silver shape, and element-wise equality of every pre-lane row for the post-lane shape.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from leviathan.transforms.gold.weather_z import (
    _PRELIM_COL,
    CELLS_SUFFIX,
    METRIC_DROUGHT_PRELIM,
    METRIC_DROUGHT_PRELIM_SHARE,
    METRIC_DROUGHT_Z,
    METRIC_FROST_SHARE,
    TAIL_SHARE_SUFFIX,
    Z_METRICS,
    compute_weather_z,
    to_psd_surface,
)

_REPO = Path(__file__).resolve().parents[2]
_WIN, _MIN = 10, 5


@pytest.fixture(autouse=True)
def _no_retry_sleep():
    """Remove the BACKOFF, never the RETRY -- the fetcher's three-attempt ``wait_exponential`` costs a
    real 6 seconds per 404 and the whole-chain cases below fetch 31 of them."""
    from leviathan.ingestion.weather import chirps as _chirps_mod
    from tenacity import wait_none
    original = _chirps_mod._read_cog_values.retry.wait
    _chirps_mod._read_cog_values.retry.wait = wait_none()
    try:
        yield
    finally:
        _chirps_mod._read_cog_values.retry.wait = original


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------
def _chirps(years, *, prelim_years=(), country="brazil", region="r1", days=31,
            seed=0, prelim_days=None, with_column=True) -> pd.DataFrame:
    """A long silver_chirps frame: one January per year, ``days`` days, deterministic precip.

    ``with_column=False`` reproduces the PRE-LANE silver shape -- the 11-column layout every object
    written before 2026-09-15 carries, and which is never rewritten."""
    rng = np.random.default_rng(seed)
    rows = []
    for y in years:
        prelim_set = set(range(1, days + 1)) if y in prelim_years else set(prelim_days or ())
        for d in range(1, days + 1):
            row = {"country": country, "region": region, "year": y, "month": 1, "day": d,
                   "variable": "precipitation_mm", "value": float(rng.uniform(0, 10))}
            if with_column:
                row[_PRELIM_COL] = "1" if (y in prelim_years and d in prelim_set) or \
                                          (prelim_days and y == max(years) and d in prelim_days) else "0"
            rows.append(row)
    return pd.DataFrame(rows)


def _val(gold, metric, year, country=None):
    sub = gold[(gold["metric"] == metric) & (gold["year"] == year)]
    if country is not None:
        sub = sub[sub["country"] == country]
    return float(sub["value"].iloc[0])


# ---------------------------------------------------------------------------
# T-E1 -- the seam
# ---------------------------------------------------------------------------
class TestToLongCarriesTheColumn:
    def _seam(self):
        mod = importlib.import_module("jobs.batch.gold_weather_z_task")
        return mod._to_long

    def test_a_long_chirps_frame_CARRIES_the_provenance_column(self):
        out = self._seam()(pd.DataFrame({
            "country": ["br"], "region": ["r"], "year": [2026], "month": [8], "day": [1],
            "variable": ["precipitation_mm"], "value": [3.3], _PRELIM_COL: ["1"],
        }))
        assert _PRELIM_COL in out.columns
        assert list(out[_PRELIM_COL]) == ["1"]

    def test_a_pre_lane_long_frame_projects_EXACTLY_as_before(self):
        out = self._seam()(pd.DataFrame({
            "country": ["br"], "region": ["r"], "year": [2020], "month": [1], "day": [1],
            "variable": ["precipitation_mm"], "value": [3.3],
        }))
        assert list(out.columns) == ["country", "region", "year", "month", "day", "variable", "value"]

    def test_the_nasa_WIDE_melt_is_untouched(self):
        out = self._seam()(pd.DataFrame({
            "country": ["br"], "region": ["r"], "year": [2020], "month": [1], "day": [1],
            "temperature_2m_max_c": [30.0], "temperature_2m_min_c": [18.0],
        }))
        assert set(out["variable"]) == {"temperature_2m_max_c", "temperature_2m_min_c"}
        assert _PRELIM_COL not in out.columns


# ---------------------------------------------------------------------------
# The stamp at CELL grain
# ---------------------------------------------------------------------------
class TestCellGrainStamp:
    def test_an_ALL_PRELIM_month_stamps_1_beside_its_drought_z(self):
        frame = _chirps(range(2000, 2016), prelim_years=(2015,), days=31)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2015) == 1.0

    def test_an_ALL_FINAL_month_stamps_0_and_that_ZERO_IS_A_READING(self):
        """0.0 is kept for the same reason ``frost_event_flag`` keeps its zeros: an ABSENT row would
        mean both 'final' and 'no data' and 'pre-lane silver', and a renderer that read absence as
        'final' would be fail-OPEN on exactly the months this metric exists to mark."""
        frame = _chirps(range(2000, 2016), days=31)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2015) == 0.0

    def test_ONE_PRELIM_DAY_IN_THIRTY_ONE_makes_the_month_preliminary(self):
        """THE ASYMMETRY, at gold: any prelim day does it; only ALL final days make a month final. A
        mean over the month's days would have read 1/31 = 0.032 and rounded, in a reader's head, to
        'basically final' -- for a figure that WILL be revised."""
        frame = _chirps(range(2000, 2016), days=31, prelim_days=(17,))
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2015) == 1.0

    def test_there_is_EXACTLY_ONE_stamp_per_emitted_drought_z_row(self):
        frame = _chirps(range(2000, 2016), prelim_years=(2015,), days=31)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        cells = gold[gold["region"] == "r1"]
        z_keys = set(map(tuple, cells[cells["metric"] == METRIC_DROUGHT_Z]
                         [["country", "region", "year", "month"]].values))
        s_keys = set(map(tuple, cells[cells["metric"] == METRIC_DROUGHT_PRELIM]
                         [["country", "region", "year", "month"]].values))
        assert z_keys == s_keys and len(z_keys) > 0

    def test_a_year_with_too_thin_a_baseline_gets_NEITHER_a_z_NOR_a_stamp(self):
        """A stamp with no z would be a provenance claim about a figure that was never served."""
        frame = _chirps(range(2000, 2016), prelim_years=(2015,), days=31)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        early = gold[gold["year"] < 2000 + _MIN]
        assert early.empty

    def test_the_stamp_is_NOT_winsorized_and_NOT_a_z(self):
        from leviathan.transforms.gold.weather_z import Z_METRICS as ZM
        assert METRIC_DROUGHT_PRELIM not in ZM
        frame = _chirps(range(2000, 2016), prelim_years=(2015,), days=31)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        stamps = gold[gold["metric"] == METRIC_DROUGHT_PRELIM]["value"]
        assert set(stamps.unique()) <= {0.0, 1.0}

    def test_a_PRE_LANE_silver_frame_emits_NO_STAMP_AT_ALL(self):
        """The byte-identity hinge. A silver object written before this lane has no provenance column,
        is never rewritten, and must produce exactly the pre-lane gold rows -- so absence of the column
        means absence of the metric, not a fabricated '0'."""
        frame = _chirps(range(2000, 2016), days=31, with_column=False)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert (gold["metric"] == METRIC_DROUGHT_PRELIM).sum() == 0

    def test_a_NaN_flag_from_a_LEGACY_OBJECT_CONCATENATED_BESIDE_A_CURRENT_ONE_reads_as_FINAL(self):
        """This is not hypothetical: ``_read_long`` concatenates every parquet under the prefix, and an
        11-column legacy object beside a 12-column fresh one yields NaN for the legacy rows."""
        legacy = _chirps(range(2000, 2015), days=31, with_column=False)
        fresh = _chirps([2015], days=31, seed=7)
        gold = compute_weather_z("corn_cbot", chirps=pd.concat([legacy, fresh], ignore_index=True),
                                 window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2015) == 0.0


# ---------------------------------------------------------------------------
# T-E2 / T-E7 -- the aggregate grains
# ---------------------------------------------------------------------------
def _two_country_frame(prelim_countries=()):
    frames = []
    for i, country in enumerate(("cameroon", "ghana")):
        for region in (f"{country}_a", f"{country}_b"):
            frames.append(_chirps(range(2000, 2016), region=region, country=country, days=31,
                                  seed=i * 10 + len(region),
                                  prelim_years=(2015,) if country in prelim_countries else ()))
    return pd.concat(frames, ignore_index=True)


class TestAggregateGrains:
    def test_the_basin_row_is_a_SHARE_and_wears_a_DIFFERENT_NAME(self):
        """``_basin_rows`` MEANS every metric it finds, so at basin grain the 0/1 flag becomes a
        fraction of member cells. A fraction may never wear a flag's name -- the exact rule that made
        ``frost_event_flag`` into ``frost_event_share`` at this grain."""
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(prelim_countries=("ghana",)),
                                 window_years=_WIN, min_years=_MIN)
        basin = gold[(gold["region"] == "west_africa_basin") & (gold["year"] == 2015)]
        assert METRIC_DROUGHT_PRELIM not in set(basin["metric"]), \
            "a share of cells is riding under the flag's own name"
        share = float(basin[basin["metric"] == METRIC_DROUGHT_PRELIM_SHARE]["value"].iloc[0])
        assert share == pytest.approx(0.5)      # 2 of 4 member cells preliminary

    def test_the_basin_carries_its_CELLS_provenance_sibling(self):
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(prelim_countries=("ghana",)),
                                 window_years=_WIN, min_years=_MIN)
        basin = gold[(gold["region"] == "west_africa_basin") & (gold["year"] == 2015)]
        cells = float(basin[basin["metric"] == f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}"]["value"].iloc[0])
        assert cells == 4.0

    def test_the_member_country_tier_decomposes_the_share(self):
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(prelim_countries=("ghana",)),
                                 window_years=_WIN, min_years=_MIN)
        for country, want in (("Ghana", 1.0), ("Cameroon", 0.0)):
            row = gold[(gold["region"] == f"{country.lower()}_country")
                       & (gold["year"] == 2015)
                       & (gold["metric"] == METRIC_DROUGHT_PRELIM_SHARE)]
            assert float(row["value"].iloc[0]) == pytest.approx(want), country

    def test_the_stamp_gets_NO_tail_share_at_either_grain(self):
        """``_tail_share`` counts cells at or beyond +2 sigma; a 0/1 provenance flag has no sigma."""
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(prelim_countries=("ghana",)),
                                 window_years=_WIN, min_years=_MIN)
        assert f"{METRIC_DROUGHT_PRELIM}{TAIL_SHARE_SUFFIX}" not in set(gold["metric"])
        assert f"{METRIC_DROUGHT_PRELIM_SHARE}{TAIL_SHARE_SUFFIX}" not in set(gold["metric"])

    def test_an_ALL_FINAL_basin_still_emits_a_ZERO_share(self):
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(),
                                 window_years=_WIN, min_years=_MIN)
        basin = gold[(gold["region"] == "west_africa_basin") & (gold["year"] == 2015)]
        assert float(basin[basin["metric"] == METRIC_DROUGHT_PRELIM_SHARE]["value"].iloc[0]) == 0.0

    def test_the_frost_rename_is_untouched_by_the_new_one(self):
        from leviathan.transforms.gold.weather_z import AGGREGATE_RENAMES, METRIC_FROST_FLAG
        assert AGGREGATE_RENAMES[METRIC_FROST_FLAG] == METRIC_FROST_SHARE
        assert AGGREGATE_RENAMES[METRIC_DROUGHT_PRELIM] == METRIC_DROUGHT_PRELIM_SHARE
        assert len(AGGREGATE_RENAMES) == 2

    def test_the_z_metrics_still_ride_under_their_own_names_at_basin_grain(self):
        gold = compute_weather_z("cocoa", chirps=_two_country_frame(prelim_countries=("ghana",)),
                                 window_years=_WIN, min_years=_MIN)
        basin = gold[(gold["region"] == "west_africa_basin")]
        assert METRIC_DROUGHT_Z in set(basin["metric"])
        assert set(Z_METRICS) & set(basin["metric"]) == {METRIC_DROUGHT_Z}


# ---------------------------------------------------------------------------
# The card declares everything the transform can emit
# ---------------------------------------------------------------------------
class TestTheCardDeclaresTheStamp:
    def test_every_new_metric_is_on_the_card_with_an_EXPLICIT_lag(self):
        from leviathan.graphrag.numbers.registry import load_registry
        metrics = load_registry().get("gold_weather_z").metrics
        for name in (METRIC_DROUGHT_PRELIM, METRIC_DROUGHT_PRELIM_SHARE,
                     f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}"):
            assert name in metrics, name
            assert getattr(metrics[name], "ym_publication_lag_days", None) is not None, name

    def test_all_three_carry_DROUGHT_Z_S_OWN_LAG(self):
        """check_metric_lags clause 4: one source cannot print the reading and its own provenance on two
        different days. They move WITH the stem when the 25 -> 7 flip is taken, never before it."""
        from leviathan.graphrag.numbers.registry import load_registry
        metrics = load_registry().get("gold_weather_z").metrics
        stem = metrics[METRIC_DROUGHT_Z].ym_publication_lag_days
        for name in (METRIC_DROUGHT_PRELIM, METRIC_DROUGHT_PRELIM_SHARE,
                     f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}",
                     f"{METRIC_DROUGHT_Z}{TAIL_SHARE_SUFFIX}", f"{METRIC_DROUGHT_Z}{CELLS_SUFFIX}"):
            assert metrics[name].ym_publication_lag_days == stem, name

    def test_the_lag_lint_is_green_and_is_RUN_HERE(self):
        """``check_metric_lags`` is still NOT wired into ``graphrag.config_check.main`` (its own
        docstring says so, and wiring it is the orchestrator's post-S7b step), so CALLING it here is the
        point of this case rather than a courtesy: without it, a lag edit that violates a clause passes
        the build. The wiring is deliberately not ASSERTED on -- this deck must not go red on the day
        somebody does wire it in."""
        from leviathan.graphrag.numbers.registry import check_metric_lags
        assert check_metric_lags() == []


# ---------------------------------------------------------------------------
# THE BYTE-IDENTITY PROOF, EXECUTED -- fetch -> bronze -> silver -> gold
# ---------------------------------------------------------------------------
_PRE_LANE_REF = "HEAD:src/leviathan/transforms/gold/weather_z.py"


@pytest.fixture(scope="module")
def pre_lane_weather_z(tmp_path_factory):
    """``weather_z.py`` as it stands at HEAD, imported as a SECOND module beside the working tree's.

    This is the acceptance contract made executable rather than asserted: the pre-lane transform is run
    on the same frames as the current one and the two outputs are compared element-wise."""
    try:
        src = subprocess.run(["git", "show", _PRE_LANE_REF], cwd=_REPO, capture_output=True,
                             text=True, check=True).stdout
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"git show {_PRE_LANE_REF} unavailable: {exc}")
    path = tmp_path_factory.mktemp("prelane") / "weather_z_pre_lane.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("weather_z_pre_lane", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["weather_z_pre_lane"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["commodity", "country", "region", "year", "month", "metric"]) \
                .reset_index(drop=True)


class TestByteIdentityAgainstHead:
    """The HEAD module is the reference; the tree's output must reproduce it row for row."""

    def _frames(self, with_column: bool):
        chirps = pd.concat([
            _chirps(range(2000, 2016), region=r, country=c, days=31, seed=i, with_column=with_column)
            for i, (c, r) in enumerate((("brazil", "r1"), ("brazil", "r2"),
                                        ("cameroon", "c1"), ("ghana", "g1")))
        ], ignore_index=True)
        return chirps

    def test_a_PRE_LANE_SHAPED_silver_frame_yields_an_ELEMENT_WISE_IDENTICAL_gold_frame(
            self, pre_lane_weather_z):
        """No provenance column at all -- the shape of every silver object on S3 today. The tree and
        HEAD must be indistinguishable, which covers the z values, ``_complete_months_only``'s verdicts,
        ``_drought_runs``' thresholds, the winsorization and every ``_basin_rows`` aggregate."""
        frame = self._frames(with_column=False)
        got = _sorted(compute_weather_z("cocoa", chirps=frame, window_years=_WIN, min_years=_MIN))
        want = _sorted(pre_lane_weather_z.compute_weather_z(
            "cocoa", chirps=frame.copy(), window_years=_WIN, min_years=_MIN))
        assert len(got) == len(want) and len(got) > 0
        pd.testing.assert_frame_equal(got, want, check_exact=True)

    def test_an_ALL_FINAL_post_lane_frame_reproduces_EVERY_pre_lane_ROW_exactly(self, pre_lane_weather_z):
        """The same month with the column present and all-final. The z arithmetic is not merely close --
        every pre-lane row is reproduced element-wise -- and the ONLY difference is the added provenance
        rows, all of which read 0.0. That delta is the lane's entire content at gold, stated as a set."""
        frame = self._frames(with_column=True)
        got = compute_weather_z("cocoa", chirps=frame, window_years=_WIN, min_years=_MIN)
        want = pre_lane_weather_z.compute_weather_z(
            "cocoa", chirps=frame.drop(columns=[_PRELIM_COL]), window_years=_WIN, min_years=_MIN)
        stamp_names = {METRIC_DROUGHT_PRELIM, METRIC_DROUGHT_PRELIM_SHARE,
                       f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}"}
        added = got[got["metric"].isin(stamp_names)]
        kept = _sorted(got[~got["metric"].isin(stamp_names)])
        pd.testing.assert_frame_equal(kept, _sorted(want), check_exact=True)
        assert not added.empty
        assert set(added[added["metric"] == METRIC_DROUGHT_PRELIM]["value"].unique()) == {0.0}
        assert set(added[added["metric"] == METRIC_DROUGHT_PRELIM_SHARE]["value"].unique()) == {0.0}

    def test_A_PRELIM_MONTH_CHANGES_NO_OTHER_MONTH_S_Z(self, pre_lane_weather_z):
        """The recompute must be BOUNDED: reading a prelim month is a new row for THAT month, never a
        disturbance of a settled one. Pinned by running HEAD on the same values."""
        frame = self._frames(with_column=True)
        frame.loc[frame["year"] == 2015, _PRELIM_COL] = "1"
        got = compute_weather_z("cocoa", chirps=frame, window_years=_WIN, min_years=_MIN)
        want = pre_lane_weather_z.compute_weather_z(
            "cocoa", chirps=frame.drop(columns=[_PRELIM_COL]), window_years=_WIN, min_years=_MIN)
        stamp_names = {METRIC_DROUGHT_PRELIM, METRIC_DROUGHT_PRELIM_SHARE,
                       f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}"}
        kept = _sorted(got[~got["metric"].isin(stamp_names)])
        pd.testing.assert_frame_equal(kept, _sorted(want), check_exact=True)


# ---------------------------------------------------------------------------
# THE WHOLE CHAIN: fetch -> bronze rows -> silver long -> compute_weather_z
# ---------------------------------------------------------------------------
def _fixture_dataset(value: float):
    ds = MagicMock()
    ds.__enter__ = lambda s: s
    ds.__exit__ = MagicMock(return_value=False)
    ds.nodata = None
    ds.height, ds.width = 2000, 7200
    ds.index.return_value = (1259, 2479)
    ds.read.return_value = np.array([[value]], dtype=np.float32)
    return ds


def _drive_chain(year: int, month: int, *, product: str, today: date) -> pd.DataFrame:
    """fetch -> bronze rows -> ``chirps_bronze_to_silver`` -> a long silver frame, for one region."""
    from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values_with_product
    from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver

    loc = {"country": "brazil", "region": "r1", "latitude": -12.64, "longitude": -55.42}
    rng = np.random.default_rng(3)
    rows = []
    import calendar
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        value = float(np.float32(rng.uniform(0, 10)))

        def _open(url, *a, _v=value, **kw):
            if product == "prelim" and "prelim" not in url:
                raise __import__("rasterio").errors.RasterioIOError("HTTP response code: 404")
            return _fixture_dataset(_v)

        with patch("rasterio.open", side_effect=_open):
            values, got_product = fetch_chirps_daily_values_with_product(
                year, month, day, [loc], today=today)
        assert got_product == product
        rows.append({
            "commodity": "corn_cbot", "source": "chirps", "country": loc["country"],
            "region": loc["region"], "date": date(year, month, day).isoformat(),
            "year": year, "month": month, "day": day,
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "precipitation_mm": values.get(loc["region"]),
            "is_preliminary": got_product == "prelim",
            "ingest_date": "2026-09-15",
        })
    return chirps_bronze_to_silver(pd.DataFrame(rows))


class TestTheWholeChain:
    def test_an_ALL_FINAL_month_carries_a_0_STRING_through_silver_and_a_0_0_stamp_at_gold(self):
        silver = _drive_chain(2026, 7, product="final", today=date(2026, 9, 15))
        assert set(silver["is_preliminary"]) == {"0"}
        history = _chirps(range(2016, 2026), country="brazil", region="r1", days=31, seed=5)
        history = history[history["month"] == 1]
        july = silver.rename(columns={})
        frame = pd.concat([history.assign(month=7), july], ignore_index=True)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2026) == 0.0

    def test_THE_PROOF_OBLIGATION_an_all_final_month_through_the_WHOLE_CHAIN_equals_HEAD(
            self, pre_lane_weather_z):
        """THE ACCEPTANCE CONTRACT, EXECUTED RATHER THAN ASSERTED (THREAT_MODEL sec 2 close).

        One month whose every day is FINAL, driven fetch -> bronze rows -> ``chirps_bronze_to_silver``
        -> ``compute_weather_z``, against the SAME chain output with the provenance column dropped run
        through the module as it stands at ``git show HEAD:``. Every pre-lane row must be reproduced
        ELEMENT-WISE: the z values, ``_complete_months_only``'s verdicts, ``_drought_runs``' thresholds,
        the winsorization and the ``_basin_rows`` aggregates. The only difference permitted is the
        stamp rows, and for an all-final month every one of them must read 0.0.

        This single case is what covers byte-identity items 1-13 behaviourally: it exercises the real
        URL builder, the real reader stack, the real bronze row shape, the real melt-and-reattach at
        the b2s seam and the real gold transform, rather than a synthetic frame that resembles them."""
        silver = _drive_chain(2026, 7, product="final", today=date(2026, 9, 15))
        assert set(silver["is_preliminary"]) == {"0"}
        history = _chirps(range(2014, 2026), country="brazil", region="r1", days=31, seed=5)
        history = history[history["month"] == 1].assign(month=7)
        frame = pd.concat([history, silver], ignore_index=True)

        got = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        want = pre_lane_weather_z.compute_weather_z(
            "corn_cbot", chirps=frame.drop(columns=[_PRELIM_COL]),
            window_years=_WIN, min_years=_MIN)

        stamp_names = {METRIC_DROUGHT_PRELIM, METRIC_DROUGHT_PRELIM_SHARE,
                       f"{METRIC_DROUGHT_PRELIM}{CELLS_SUFFIX}"}
        kept = _sorted(got[~got["metric"].isin(stamp_names)])
        added = got[got["metric"].isin(stamp_names)]
        assert len(kept) > 0 and len(want) > 0
        pd.testing.assert_frame_equal(kept, _sorted(want), check_exact=True)
        assert not added.empty
        assert set(added["value"].unique()) == {0.0}

    def test_a_PRELIM_month_carries_a_1_STRING_through_silver_and_a_1_0_stamp_at_gold(self):
        """August 2026 is the live case: the 2026-08 FINAL block was absent at +11 days on 2026-09-11
        (it landed that evening at 21:10Z) while all 31 prelim days had been published since Sep 02."""
        silver = _drive_chain(2026, 8, product="prelim", today=date(2026, 9, 15))
        assert set(silver["is_preliminary"]) == {"1"}
        history = _chirps(range(2016, 2026), country="brazil", region="r1", days=31, seed=5)
        history = history[history["month"] == 1]
        frame = pd.concat([history.assign(month=8), silver], ignore_index=True)
        gold = compute_weather_z("corn_cbot", chirps=frame, window_years=_WIN, min_years=_MIN)
        assert _val(gold, METRIC_DROUGHT_PRELIM, 2026) == 1.0
        assert not gold[(gold["metric"] == METRIC_DROUGHT_Z) & (gold["year"] == 2026)].empty

    def test_a_2014_month_NEVER_reaches_prelim_through_the_chain(self):
        """T-A3 end to end: the fetcher refuses, so no bronze row, no silver row and no gold row of the
        historical corpus can be built from a preliminary raster."""
        import rasterio.errors
        from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values_with_product
        seen: list[str] = []

        def _open(url, *a, **kw):
            seen.append(url)
            raise rasterio.errors.RasterioIOError("HTTP response code: 404")

        with patch("rasterio.open", side_effect=_open):
            values, product = fetch_chirps_daily_values_with_product(
                2014, 3, 9, [{"country": "brazil", "region": "r1",
                              "latitude": -12.64, "longitude": -55.42}],
                today=date(2026, 9, 15))
        assert product == "absent" and values == {"r1": None}
        assert all("prelim" not in u for u in seen), seen


def test_to_psd_surface_is_the_key_the_stamp_and_the_z_share(self=None):
    """The stamp is keyed off the EMITTED z rows, which carry the PSD surface form, so the two can
    never be emitted for different country spellings."""
    assert to_psd_surface("cote_divoire") == "Cote Divoire"
    assert to_psd_surface("united_states") == "United States"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
