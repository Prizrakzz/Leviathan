"""PINK SHEET VINTAGES lane (a): the bitemporal producer and its contract, pinned.

Seven properties, each of which the served surface (or a future one) actually depends on:

  1. FULL RESTATEMENT -- every release's month set is the complete hole-free 1960-01..R-1 run and
     ``len(months) == expected_month_count(R)``. The one-clock guarantee rests on it.
  2. ONE CLOCK PER RELEASE -- ``release_date`` and ``release_date_source`` are constant within a
     release, so ``mixed_release_stamp`` stays structurally unreachable on a point-in-time read.
  3. release_date DTYPE IS STRING, matching ``^\\d{4}-\\d{2}-\\d{2}$``, and the contract's
     ``partition_keys`` is EMPTY while ``release_date`` IS a frame column (the stage_feature_probe
     pin: a required column that is not a declared partition key must genuinely be in the footer).
  4. NEVER MONTH-END -- no ``release_date`` is the last day of its own release month.
  5. ROUND TRIP -- ``derived_release_ym(workbook) == release_ym`` on the row.
  6. PER-VINTAGE Z -- where two vintages disagree on a level, their z-scores differ too. If the
     held range has no revised month, the test DECLARES that rather than passing vacuously.
  7. ``latest_release_ym`` is ABSENT from ``SILVER_VINTAGE_COLUMNS`` -- on a vintage row it and
     ``release_ym`` are one fact in two renderings.

And three the STEP-12 review and the refute added, each of which was a live hazard rather than a
tidiness point:

  8. G-A1 IS IN THE PRODUCER, not in prose. A release that is not a complete hole-free
     1960M01..R-1 run -- a hole, a duplicate, or a TRAILING PARTIAL MONTH -- is QUARANTINED under a
     name from a closed vocabulary, and every other release still builds.
  9. THE CROSS-PREFIX COLLISION cannot abort the table. Scheduled and archive bronze can both hold
     one release; the union dedups on (release_ym, date, series_name) preferring the SCHEDULED
     frame, counts the drop, and counts a value disagreement apart from an exact re-capture.
 10. THE CLOCK LADDER IS LIVE. rung 1 is reachable from the caller's raw_meta read, so an
     origin-clocked vintage and an archive-clocked one are distinguishable on the row -- which is
     what pink_sheet_release's ladder docstring claims and could not previously deliver.

AWS-free. Bronze frames are built here in the long shape the shipped extractor emits.
"""
from __future__ import annotations

import calendar

import pandas as pd
import pytest
import yaml
from leviathan.common import pink_sheet_release as R
from leviathan.transforms.bronze_to_silver import pink_sheet as P
from leviathan.transforms.bronze_to_silver.pink_sheet import (
    SILVER_COLUMNS,
    SILVER_VINTAGE_COLUMNS,
    build_silver,
    build_silver_vintages,
)

_REPO_CONTRACT = "configs/silver/tables/silver_pink_sheet_vintages.yaml"

# The governed series names the extractor emits (post-_SERIES_RENAME they are the silver columns).
_SERIES = ["soybean_oil_usd_t", "palm_oil_cpo_usd_t", "urea_usd_mt", "brent_crude_usd_bbl"]


def _bronze(release: str, *, months: list[str] | None = None,
            bump: dict[tuple[str, str], float] | None = None) -> pd.DataFrame:
    """One release's LONG bronze frame: (date, series_name, value_usd, release_ym, source).

    ``bump`` restates individual (month, series) cells so a later vintage can legitimately DISAGREE
    with an earlier one -- which is the whole subject of a bitemporal table.
    """
    months = months if months is not None else R.expected_months(release)
    bump = bump or {}
    rows = []
    for i, month in enumerate(months):
        date = pd.Timestamp(int(month[:4]), int(month[5:7]), 1).date()
        for j, series in enumerate(_SERIES):
            base = 100.0 + j * 10 + (i % 37)
            rows.append({
                "release_ym": release,
                "date": date,
                "series_name": series,
                "value_usd": base + bump.get((month, series), 0.0),
                "source": "world_bank_pink_sheet",
            })
    return pd.DataFrame(rows)


def _short(release: str, n: int = 90) -> pd.DataFrame:
    """A SHORT release -- the last ``n`` months of the real run. Deliberately NOT hole-free.

    IT IS NO LONGER A CHEAP STAND-IN FOR THE VINTAGE BUILDER, and that is the point of the G-A1 fix:
    build_silver_vintages now QUARANTINES a release that is not a complete 1960M01..R-1 run, so a
    short frame handed to it produces an EMPTY table -- and a test written against a short frame
    would pass vacuously rather than assert anything. So this helper survives for exactly two jobs:
    driving the sibling ``build_silver`` (which collapses releases and has no such premise), and
    DRIVING THE QUARANTINE ITSELF."""
    return _bronze(release, months=R.expected_months(release)[-n:])


_FULL_CACHE: dict[str, pd.DataFrame] = {}


def _full(release: str) -> pd.DataFrame:
    """A release's COMPLETE ``1960M01..R-1`` bronze history -- the only shape the vintage builder
    will build. Memoised: the suite below needs the same four releases a dozen times, and rebuilding
    a 3,200-row frame each time buys nothing."""
    if release not in _FULL_CACHE:
        _FULL_CACHE[release] = _bronze(release)
    return _FULL_CACHE[release].copy()


class TestColumnContract:
    def test_latest_release_ym_is_dropped_on_purpose(self):
        assert "latest_release_ym" in SILVER_COLUMNS
        assert "latest_release_ym" not in SILVER_VINTAGE_COLUMNS

    def test_the_three_vintage_columns_are_appended_and_nothing_else_moves(self):
        assert SILVER_VINTAGE_COLUMNS[-3:] == ["release_ym", "release_date", "release_date_source"]
        assert SILVER_VINTAGE_COLUMNS[:-3] == [c for c in SILVER_COLUMNS
                                               if c != "latest_release_ym"]
        assert len(SILVER_VINTAGE_COLUMNS) == len(SILVER_COLUMNS) + 2

    def test_the_sibling_builder_is_untouched(self):
        """build_silver still emits the latest-only contract, exactly. The vintage lane's whole
        safety argument is that it never changes the served table's producer."""
        frame = build_silver([_short("2026M05"), _short("2026M07")])
        assert list(frame.columns) == SILVER_COLUMNS
        assert "release_ym" not in frame.columns


class TestEmptyInputs:
    @pytest.mark.parametrize("dfs", [[], [pd.DataFrame()], [pd.DataFrame(), pd.DataFrame()]])
    def test_empty_in_empty_out_with_the_full_column_contract(self, dfs):
        out = build_silver_vintages(dfs)
        assert list(out.columns) == SILVER_VINTAGE_COLUMNS
        assert len(out) == 0


class TestFullRestatementInvariant:
    """G-A1, on the BUILT frame."""

    def test_every_release_is_a_hole_free_1960_to_R_minus_one_history(self):
        releases = ["2026M05", "2026M07", "2026M08", "2026M09"]
        frame = build_silver_vintages([_bronze(r) for r in releases])
        assert sorted(frame["release_ym"].unique()) == releases
        for release in releases:
            got = frame.loc[frame["release_ym"] == release, "date"]
            months = ["%04dM%02d" % (d.year, d.month) for d in got]
            assert len(months) == R.expected_month_count(release)
            assert R.is_full_restatement(months), release
        # ~3,193 rows for the four banked vintages (796+798+799+800)
        assert len(frame) == 796 + 798 + 799 + 800 == 3193

    def test_a_release_that_restates_a_month_twice_is_DEDUPED_not_raised(self):
        """RE-ANCHORED. This used to assert a ValueError, which was the defect: one release with a
        doubled month aborted the WHOLE table, and this builder is a publishes:true leg of the live
        pink_sheet_monthly chain. Exact duplicates are what the dedup is for -- they carry no
        disagreement, so the release builds and the drop is COUNTED."""
        doubled = pd.concat([_full("2026M05"), _full("2026M05")], ignore_index=True)
        counters: dict = {}
        declines: dict = {}
        frame = build_silver_vintages([doubled], counters=counters, declines=declines)
        assert declines == {}
        assert len(frame) == R.expected_month_count("2026M05") == 796
        assert counters["duplicate_rows_dropped"] == 796 * len(_SERIES)
        assert counters["duplicate_rows_dropped_value_conflict"] == 0

    def test_a_HOLED_release_is_QUARANTINED_by_name_and_the_others_still_build(self):
        """G-A1 IN THE PRODUCER. The fetch lands a holed release deliberately (raw is the asset) and
        says the vintage builder refuses it. Before this fix no such gate existed and a 3-row release
        built cleanly into the served bitemporal table."""
        good = _full("2026M09")
        holed = _bronze("2026M05", months=[m for m in R.expected_months("2026M05")
                                           if m != "1971M04"])
        declines: dict = {}
        counters: dict = {}
        frame = build_silver_vintages([good, holed], declines=declines, counters=counters)
        assert declines == {"2026M05": P.VINTAGE_QUARANTINE_NOT_FULL_RESTATEMENT}
        assert sorted(frame["release_ym"].unique()) == ["2026M09"]
        assert counters["releases_seen"] == 2
        assert counters["releases_built"] == 1
        assert counters["releases_quarantined"] == 1

    def test_a_TRAILING_PARTIAL_MONTH_is_quarantined_too(self):
        """The shape the fetch's own check cannot see: a labelled-but-blank last monthly row files
        the release one month HIGH, so the rows filed under 2026M09 run one month LONG. Measured
        against the DECLARED release rather than against the run's own max, it fails."""
        rows = _bronze("2026M09", months=R.expected_months("2026M09") + ["2026M09"])
        declines: dict = {}
        assert build_silver_vintages([rows], declines=declines).empty
        assert declines == {"2026M09": P.VINTAGE_QUARANTINE_NOT_FULL_RESTATEMENT}

    def test_an_ALIAS_COLLAPSE_inside_one_release_is_quarantined_not_raised(self):
        """The one duplicate class the cross-prefix dedup CANNOT fix: two different source spellings
        that _SERIES_RENAME maps onto one governed name, inside a single release. It still must not
        abort the table."""
        alias = next((k for k, v in P._SERIES_RENAME.items()
                      if v == "soybean_oil_usd_t" and k != "soybean_oil_usd_t"), None)
        if alias is None:
            pytest.skip("no cross-convention alias for soybean_oil_usd_t in _SERIES_RENAME")
        clashing = _full("2026M05")
        extra = clashing.loc[clashing["series_name"] == "soybean_oil_usd_t"].copy()
        extra["series_name"] = alias
        extra["value_usd"] = extra["value_usd"] + 1.0
        declines: dict = {}
        frame = build_silver_vintages(
            [pd.concat([clashing, extra], ignore_index=True), _full("2026M09")],
            declines=declines)
        assert declines == {"2026M05": P.VINTAGE_QUARANTINE_DUPLICATE_RESTATEMENT}
        assert sorted(frame["release_ym"].unique()) == ["2026M09"]

    def test_a_NULL_release_stamp_is_dropped_and_counted_never_coerced(self):
        """`astype(str)` on the release column would turn NaN into the STRING 'nan' and file those
        rows under a release called "nan" -- a fabricated vintage key, which is precisely what the
        content key exists to prevent. They are dropped, counted, and the good release still
        builds."""
        good = _full("2026M05")
        orphan = _full("2026M05")
        orphan["release_ym"] = float("nan")
        counters: dict = {}
        frame = build_silver_vintages([good, orphan], counters=counters)
        assert sorted(frame["release_ym"].unique()) == ["2026M05"]
        assert "nan" not in set(frame["release_ym"])
        assert counters["rows_dropped_null_release_ym"] == 796 * len(_SERIES)

    def test_the_quarantine_vocabulary_is_closed(self):
        assert P.VINTAGE_QUARANTINE_REASONS == {
            "not_full_restatement", "duplicate_restatement", "pivot_duplicate_columns"}


class TestCrossPrefixCollision:
    """THE FATAL, REPRODUCED AND CLOSED.

    Nothing stops the Wayback harvest landing a release the scheduled chain already holds: the
    capture selection is not year-bounded and ``_land`` only checks the ARCHIVE key. Unioned, that
    release restates every ``(date, series_name)`` twice -- and before this fix the union raised a
    ValueError that took every OTHER release down with it.
    """

    def test_the_refuters_shape_no_longer_aborts_the_table(self):
        """``build_silver_vintages([sched_2026M05, archive_2026M05])`` -- verbatim."""
        counters: dict = {}
        declines: dict = {}
        frame = build_silver_vintages(
            [_full("2026M05"), _full("2026M05")],
            origins=[P.ORIGIN_SCHEDULED, P.ORIGIN_ARCHIVE],
            counters=counters, declines=declines)
        assert declines == {}
        assert sorted(frame["release_ym"].unique()) == ["2026M05"]
        assert len(frame) == 796
        assert counters["releases_in_both_prefixes"] == 1

    def test_a_good_release_beside_the_collision_SURVIVES(self):
        """The refuter's second half: 'adding a good release does not save it -- the entire table
        fails, not that release'. It does now."""
        frame = build_silver_vintages(
            [_full("2026M05"), _full("2026M09"), _full("2026M05")],
            origins=[P.ORIGIN_SCHEDULED, P.ORIGIN_SCHEDULED, P.ORIGIN_ARCHIVE])
        assert sorted(frame["release_ym"].unique()) == ["2026M05", "2026M09"]
        assert len(frame) == 796 + 800

    def test_the_SCHEDULED_frame_wins_a_value_disagreement_and_it_is_COUNTED(self):
        """A World Bank re-render can differ from the archived replay. The scheduled object came
        from the origin directly, so it wins by rule -- and the disagreement is reported rather than
        resolved in silence."""
        scheduled = _full("2026M05")
        archived = _full("2026M05")
        archived["value_usd"] = archived["value_usd"] + 7.0
        counters: dict = {}
        frame = build_silver_vintages([scheduled, archived],
                                      origins=[P.ORIGIN_SCHEDULED, P.ORIGIN_ARCHIVE],
                                      counters=counters)
        merged = frame.set_index("date")["soybean_oil_usd_t"]
        expected = scheduled.loc[scheduled["series_name"] == "soybean_oil_usd_t"]
        expected = expected.set_index(pd.to_datetime(expected["date"]))["value_usd"]
        assert merged.equals(expected.astype(float).rename("soybean_oil_usd_t"))
        assert counters["duplicate_rows_dropped"] == 796 * len(_SERIES)
        assert counters["duplicate_rows_dropped_value_conflict"] == 796 * len(_SERIES)

    def test_the_ARCHIVE_frame_wins_nothing_by_being_listed_first(self):
        """Preference is by ORIGIN, not by input order -- the task lists scheduled keys first today,
        and a builder that depended on that would break the day the listing order changed."""
        scheduled = _full("2026M05")
        archived = _full("2026M05")
        archived["value_usd"] = archived["value_usd"] + 7.0
        frame = build_silver_vintages([archived, scheduled],
                                      origins=[P.ORIGIN_ARCHIVE, P.ORIGIN_SCHEDULED])
        expected = scheduled.loc[scheduled["series_name"] == "soybean_oil_usd_t"]
        expected = expected.set_index(pd.to_datetime(expected["date"]))["value_usd"]
        assert frame.set_index("date")["soybean_oil_usd_t"].equals(
            expected.astype(float).rename("soybean_oil_usd_t"))

    def test_an_unknown_origin_is_a_REFUSAL_never_a_guess(self):
        with pytest.raises(ValueError, match="may not be guessed"):
            build_silver_vintages([_full("2026M05")], origins=["somewhere_else"])


class TestTheClockLadderIsLIVEInTheProducer:
    """THE MAJOR: rung 1 was unreachable. release_clock was called with no header and no archive
    flag, so release_date_source was the constant 'derived_month_first' on EVERY row and the
    capture-time Last-Modified recorded by the fetch was read by nothing."""

    def test_an_ORIGIN_clocked_release_carries_the_origin_token_and_the_origin_DAY(self):
        frame = build_silver_vintages(
            [_full("2026M05")],
            clocks={"2026M05": {"http_last_modified": "Mon, 04 May 2026 09:12:00 GMT",
                                "archive": False}})
        assert set(frame["release_date"]) == {"2026-05-04"}
        assert set(frame["release_date_source"]) == {R.SOURCE_ORIGIN_LAST_MODIFIED}

    def test_an_ARCHIVE_release_with_no_origin_header_carries_the_ARCHIVE_token(self):
        frame = build_silver_vintages(
            [_full("2026M05")],
            clocks={"2026M05": {"http_last_modified": None, "archive": True}})
        assert set(frame["release_date"]) == {"2026-05-01"}
        assert set(frame["release_date_source"]) == {R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE}

    def test_a_release_with_NO_sidecar_takes_rung_2_and_is_counted_there(self):
        counters: dict = {}
        frame = build_silver_vintages([_full("2026M05")], clocks={}, counters=counters)
        assert set(frame["release_date_source"]) == {R.SOURCE_DERIVED_MONTH_FIRST}
        assert counters["clock_rung_1"] == 0 and counters["clock_rung_2"] == 1

    def test_two_releases_can_take_DIFFERENT_rungs_in_one_build(self):
        """The whole point of counting the rung per row: the corpus must be able to tell an
        origin-clocked vintage from an archive-clocked one."""
        counters: dict = {}
        frame = build_silver_vintages(
            [_full("2026M05"), _full("2026M09")],
            clocks={"2026M05": {"http_last_modified": "Mon, 04 May 2026 09:12:00 GMT",
                                "archive": False},
                    "2026M09": {"http_last_modified": None, "archive": True}})
        by_release = frame.groupby("release_ym")["release_date_source"].first()
        assert by_release["2026M05"] == R.SOURCE_ORIGIN_LAST_MODIFIED
        assert by_release["2026M09"] == R.SOURCE_DERIVED_MONTH_FIRST_ARCHIVE
        # one clock per release still holds, per release, with two different rungs in one table
        assert (frame.groupby("release_ym")["release_date"].nunique() == 1).all()


class TestOneClockPerRelease:
    """G-A2."""

    def test_release_date_and_its_source_are_constant_within_a_release(self):
        frame = build_silver_vintages([_full(r) for r in ("2026M05", "2026M07", "2026M09")])
        assert (frame.groupby("release_ym")["release_date"].nunique() == 1).all()
        assert (frame.groupby("release_ym")["release_date_source"].nunique() == 1).all()

    def test_release_ym_and_release_date_agree_row_by_row(self):
        frame = build_silver_vintages([_full(r) for r in ("2026M05", "2026M09")])
        for _, row in frame.iterrows():
            assert row["release_date"][:4] == row["release_ym"][:4]
            assert row["release_date"][5:7] == row["release_ym"][5:7]

    def test_no_release_date_is_the_last_day_of_its_own_month(self):
        """G-A2's month-end clause. A month-end knowledge date makes a vintage UNSELECTABLE for its
        own month under the lexical as-of guard, and a PIT read inside the release month then
        silently serves the PREVIOUS vintage while a one-clock gate still passes."""
        frame = build_silver_vintages([_full(r) for r in
                                       ("2025M01", "2026M01", "2026M05", "2026M09")])
        for release, date in frame.groupby("release_ym")["release_date"].first().items():
            year, month = int(release[:4]), int(release[5:7])
            assert date != "%04d-%02d-%02d" % (year, month, calendar.monthrange(year, month)[1])

    def test_the_banked_objects_all_take_the_derived_fallback_and_it_is_counted(self):
        """MEASURED FACT OF THE CORPUS: the four already-banked raw objects carry no recorded
        Last-Modified, so all four take derived_month_first. That is written down per row rather
        than silenced -- absent is never zero."""
        frame = build_silver_vintages([_full(r) for r in
                                       ("2026M05", "2026M07", "2026M08", "2026M09")])
        assert set(frame["release_date_source"]) == {R.SOURCE_DERIVED_MONTH_FIRST}


class TestReleaseDatePhysicalType:
    """G-A2b. The DP-5 trap, both halves."""

    def test_release_date_is_a_python_STRING_not_a_timestamp(self):
        frame = build_silver_vintages([_full("2026M05")])
        assert frame["release_date"].dtype == object
        assert all(isinstance(v, str) for v in frame["release_date"])
        assert frame["release_date"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()
        # and it is NOT a datetime-like: a pandas datetime would render
        # 'YYYY-MM-DD HH:MM:...' through the as-of guard and silently exclude a release published
        # ON the asof, plus stamp '[known ... 00:00:00.000]' into every citation footer.
        assert not pd.api.types.is_datetime64_any_dtype(frame["release_date"])

    def test_release_ym_and_source_are_strings_too(self):
        frame = build_silver_vintages([_full("2026M05")])
        for col in ("release_ym", "release_date_source"):
            assert frame[col].dtype == object
            assert all(isinstance(v, str) for v in frame[col])

    def test_the_contract_declares_no_partition_keys_and_release_date_is_in_file(self, contract):
        """stage_feature_probe forgives a missing required column ONLY when it is a declared
        partition key. release_date is NOT one, so it must genuinely be in the parquet footer --
        which is exactly what makes the silver_wasde 'release_date=' false-RED impossible here."""
        assert contract["partition_keys"] == []
        assert contract["layout"] == "flat"
        assert contract["partition_mode"] == "flat"
        frame = build_silver_vintages([_full("2026M05")])
        required = set(contract["value_columns"]) | set(contract["natural_key"])
        assert required - set(frame.columns) == set()


class TestRoundTrip:
    def test_the_release_ym_on_the_row_is_the_month_the_workbook_derives(self):
        """The producer never invents a release: bronze carries release_ym, which the fetch derived
        from the workbook's own last monthly row. Driven end to end through a real xlsx."""
        for release in ("2026M05", "2026M09"):
            body = _xlsx(R.expected_months(release))
            assert R.derived_release_ym(body) == release
            frame = build_silver_vintages([_bronze(release)])
            assert set(frame["release_ym"]) == {release}


class TestPerVintageZScores:
    """G-A1's companion: the z-scores are RE-COMPUTED per release over that release's own restated
    history. Copying the current z onto an older vintage's rows would put a number derived from
    POST-ASOF revisions on a row stamped with a PAST release -- a leak on the one metric the table
    advertises point-in-time clean."""

    def test_a_revised_level_moves_that_vintage_s_z_too(self):
        months = R.expected_months("2026M09")
        target = months[-13]                      # inside the 60-month window of the recent tail
        old = _bronze("2026M05", months=R.expected_months("2026M05"))
        new = _bronze("2026M09", months=months,
                      bump={(target, "soybean_oil_usd_t"): 250.0})
        frame = build_silver_vintages([old, new])
        stamp = pd.Timestamp(int(target[:4]), int(target[5:7]), 1)
        rows = frame.loc[frame["date"] == stamp].set_index("release_ym")
        levels = rows["soybean_oil_usd_t"]
        zs = rows["soybean_oil_usd_t_zscore_5yr"]
        if levels.nunique() <= 1:
            pytest.fail("no revised month in the held range -- the fixture must restate a level "
                        "for this pin to mean anything (absent is never zero)")
        assert levels["2026M09"] - levels["2026M05"] == pytest.approx(250.0)
        assert zs.notna().all(), "both vintages must carry a z at this month"
        assert zs["2026M09"] != zs["2026M05"], (
            "the z-scores are identical across two vintages that DISAGREE on the level -- the z "
            "was copied rather than re-computed per release, which is the PIT leak this pin exists "
            "to catch")

    def test_the_zscore_floor_and_the_epsilon_still_apply_per_vintage(self):
        """Option A: a window with NO dispersion has no z-score. A constant series must render
        NULL, not 0.0 -- a z of 0.0 asserts 'exactly at the 5-year mean', which constant data
        cannot support."""
        months = R.expected_months("2026M05")
        flat = _bronze("2026M05", months=months)
        flat.loc[flat["series_name"] == "urea_usd_mt", "value_usd"] = 44.0
        frame = build_silver_vintages([flat])
        tail = frame.loc[frame["date"] >= pd.Timestamp(2020, 1, 1), "urea_usd_mt_zscore_5yr"]
        assert tail.isna().all(), "a flat 60-month window must yield NULL, never 0.0"


class TestSortAndShape:
    def test_rows_are_ordered_by_release_then_date(self):
        frame = build_silver_vintages([_full("2026M09"), _full("2026M05")])
        assert frame[["release_ym", "date"]].equals(
            frame[["release_ym", "date"]].sort_values(["release_ym", "date"]).reset_index(drop=True))

    def test_column_order_is_the_declared_contract_exactly(self):
        frame = build_silver_vintages([_full("2026M05")])
        assert list(frame.columns) == SILVER_VINTAGE_COLUMNS

    def test_a_missing_series_is_NaN_filled_not_dropped(self):
        """A pre-F063 bronze release carries only 15 of the 37 governed series. The vintage builder
        must widen it to the full contract, exactly as build_silver does."""
        narrow = _full("2026M05")
        narrow = narrow.loc[narrow["series_name"] != "urea_usd_mt"]
        frame = build_silver_vintages([narrow])
        assert "urea_usd_mt" in frame.columns
        assert frame["urea_usd_mt"].isna().all()


class TestSeriesRenameStaysArmed:
    def test_a_cross_convention_alias_is_normalised_before_the_pivot(self):
        """_SERIES_RENAME exists because two World Bank naming conventions pivot to the SAME
        governed column, and the ARCHIVE widens that convention set. If the vintage builder skipped
        the rename, the post-pivot duplicate-column tripwire would fire -- or worse, one governed
        series would silently vanish."""
        alias = next((k for k, v in P._SERIES_RENAME.items()
                      if v == "soybean_oil_usd_t" and k != "soybean_oil_usd_t"), None)
        if alias is None:
            pytest.skip("no cross-convention alias for soybean_oil_usd_t in _SERIES_RENAME")
        frame_bronze = _full("2026M05")
        frame_bronze.loc[frame_bronze["series_name"] == "soybean_oil_usd_t",
                         "series_name"] = alias
        frame = build_silver_vintages([frame_bronze])
        assert frame["soybean_oil_usd_t"].notna().any()


@pytest.fixture(scope="module")
def contract():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    return yaml.safe_load((repo / _REPO_CONTRACT).read_text(encoding="utf-8"))


def _xlsx(months: list[str]) -> bytes:
    import io as _io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = R.SHEET_NAME
    sheet.append(["World Bank Commodity Price Data (The Pink Sheet)"])
    sheet.append(["Updated as of: September 2, 2026"])
    sheet.append([None])
    sheet.append([None])
    sheet.append(["Month", "Soybean oil"])
    for i, month in enumerate(months):
        sheet.append([month, 900.0 + i])
    buf = _io.BytesIO()
    book.save(buf)
    return buf.getvalue()
