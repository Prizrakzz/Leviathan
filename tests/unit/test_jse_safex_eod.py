"""PRICE_AND_PLAYBOOKS W1a -- the JSE/SAFEX leg. Hermetic: no network, no AWS, no .xls writer.

The fixtures are CELL GRIDS rather than workbook bytes, and that is not a shortcut: no library in
this estate can WRITE a legacy OLE .xls, and everything this leg can get wrong is grid logic. The
transform is split at the OLE boundary (``read_grid`` / ``build_jse_bronze_from_grid``) precisely so
the interesting half is testable.

The grid below reproduces the real sheet's shape: a two-row title carrying the session date, a
TWO-ROW column header carrying the upstream typo ``Cloisng Bid``, and section rows interleaved with
expiry rows -- including all FOUR sections whose text contains "MAIZE", which is the whole point.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import jse_safex_year_prefix, raw_jse_safex_key
from leviathan.transforms.bronze_to_silver import jse_safex as S
from leviathan.transforms.raw_to_bronze import jse_safex as T

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_jse")
FETCH = _load("jobs/ingest/fetch_jse_safex_daily.py", "fetch_jse_safex_daily")

# The two header rows. Column 2 carries the upstream typo VERBATIM -- "Cloisng", not "Closing".
_HEADER_TOP = ["Expiry", "Change", "Cloisng", "Closing", "MTM", "VWAP", "High", "Low",
               "Volume", "OI", "Option"]
_HEADER_BOTTOM = ["", "", "Bid", "Offer", "", "", "", "", "", "", "Volume"]

# cols: expiry | change | bid | offer | MTM | VWAP | high | low | volume | OI | option volume
_WHITE = [
    ["Aug-2026", -127, 3471, 3483, 3478, 3477, 3540, 3460, 713, 927, ""],
    ["Sep-2026", -125, 3520, 3531, 3527, 3526, 3590, 3510, 900, 4100, 12.5],
    ["Dec-2026", -123, 3656, 3659, 3658, 3657, 3731, 3638, 4142, 22942, 24.75],
    ["Mar-2027", -120, 3800, 3812, 3806, 3805, 3860, 3790, 300, 5100, ""],
    ["May-2027", -118, 3860, 3872, 3866, 3865, 3920, 3850, 120, 1800, ""],
    ["Jul-2027", -115, 3900, 3912, 3906, 3905, 3960, 3890, 60, 900, ""],
    ["Sep-2027", -112, 3950, 3962, 3956, 3955, 4010, 3940, 30, 400, ""],
    ["Dec-2027", -110, 4000, 4012, 4006, 4005, 4060, 3990, 10, 200, ""],
    # THE NO-TRADE ROW. 0 is not a ZAR/t price -- every price cell here must land NULL.
    ["Mar-2028", 0, 0, 0, 0, 0, 4027, 3900, 0, 0, ""],
]
# The same shape at a yellow-maize level. The zeros are PRESERVED rather than shifted -- the
# no-trade row has to stay a no-trade row on both slugs.
_YELLOW = [[e[0], e[1]] + [(v + 100 if v else v) for v in e[2:8]] + [e[8], e[9], e[10]]
           for e in _WHITE]
# The GRADE 2 sections. A DIFFERENT deliverable with its OWN mark -- Sep-2026 at 3098 against
# grade-1's 3527. A substring section test merges these in and lands a plausible wrong number.
_GRADE2 = [
    ["Sep-2026", -80, 3090, 3105, 3098, 3097, 3150, 3080, 40, 300, ""],
    ["Dec-2026", -78, 3200, 3215, 3208, 3207, 3260, 3190, 20, 150, ""],
]
# A section this leg does not read at all, to prove the non-maize path is a quiet skip.
_OTHER = [["Sep-2026", -5, 6100, 6120, 6110, 6109, 6200, 6050, 500, 3000, ""]]


def grid(date: str = "2026-07-27", *, sections=None) -> list[list]:
    """The sheet as a cell grid. ``sections`` is ``[(label, rows), ...]`` in sheet order."""
    if sections is None:
        sections = [
            ("WHITE MAIZE FUTURE", _WHITE),
            ("WHITE MAIZE GRADE 2 FUTURE", _GRADE2),
            ("YELLOW MAIZE FUTURE", _YELLOW),
            ("SOYA BEANS FUTURE", _OTHER),
            ("YELLOW MAIZE GRADE 2 FUTURE", _GRADE2),
        ]
    width = len(_HEADER_TOP)
    out: list[list] = [
        ["COMMODITY DERIVATIVES MARKET"] + [""] * (width - 1),
        [f"DOMESTIC FUTURES PRICES {_stamp(date)}"] + [""] * (width - 1),
        list(_HEADER_TOP),
        list(_HEADER_BOTTOM),
    ]
    for label, rows in sections:
        out.append([label] + [""] * (width - 1))
        out.extend([list(r) for r in rows])
        out.append([""] * width)
    return out


def _stamp(iso: str) -> str:
    ts = pd.Timestamp(iso)
    return f"{ts.day:02d}-{ts.strftime('%b')}-{ts.year}"


# ---------------------------------------------------------------------------
class TestSectionDiscrimination:
    """The highest-value defect in the whole wave: it produces plausible WRONG numbers."""

    def test_the_two_grade_2_sections_are_rejected_by_exact_match(self):
        bronze, stats = T.build_jse_bronze_from_grid(grid())
        assert sorted(set(bronze["section"])) == ["WHITE MAIZE FUTURE", "YELLOW MAIZE FUTURE"]
        # 9 + 9 = the measured 18/day. The GRADE-2-merged parse is 22, and the plan's ORIGINAL
        # floor of 20 sat BETWEEN them -- which is what would have pushed an implementer INTO
        # the bug while chasing a red gate.
        assert stats["rows_kept"] == 18
        assert 3098 not in set(bronze["mtm"]), "the grade-2 Sep-2026 MTM must not be in the frame"
        assert 3527 in set(bronze["mtm"]), "the grade-1 Sep-2026 MTM must be"

    def test_a_substring_test_would_have_taken_four_sections(self):
        """States the counterfactual so the exact match cannot be 'simplified' later."""
        labels = [row[0] for row in grid() if isinstance(row[0], str) and "MAIZE" in row[0]]
        assert len(labels) == 4
        assert len([lb for lb in labels if lb in T.JSE_SECTION_MAP]) == 2

    def test_an_unrecognised_maize_section_is_a_hard_error(self):
        bad = grid(sections=[("WHITE MAIZE FUTURE", _WHITE),
                             ("WHITE MAIZE GRADE 3 FUTURE", _GRADE2),
                             ("YELLOW MAIZE FUTURE", _YELLOW)])
        with pytest.raises(ValueError, match="unrecognised maize section"):
            T.build_jse_bronze_from_grid(bad)

    def test_a_non_maize_section_is_a_quiet_skip_not_an_error(self):
        """The fail-closed rule is SCOPED. The sheet carries 31 sections and an upstream rename in
        one this leg never reads must not take the leg down."""
        bronze, stats = T.build_jse_bronze_from_grid(
            grid(sections=[("WHITE MAIZE FUTURE", _WHITE),
                           ("COFFEE QUANTO", _OTHER),
                           ("MAIZE US NO 2 YELLOW GULF CBOT", _OTHER),
                           ("YELLOW MAIZE FUTURE", _YELLOW)]))
        assert stats["rows_kept"] == 18
        assert "COFFEE QUANTO" in stats["sections_seen"]

    def test_a_renamed_kept_section_is_a_hard_error_not_an_empty_leg(self):
        """Two independent detectors, and the test pins both. An upstream rename that still starts
        with a guarded prefix trips the unrecognised-section rule; one that does not (or a section
        that simply vanishes) trips the ABSENT check at the end of the pass. Neither path can yield
        a quiet short day."""
        with pytest.raises(ValueError, match="unrecognised maize section"):
            T.build_jse_bronze_from_grid(
                grid(sections=[("WHITE MAIZE FUTURES", _WHITE),
                               ("YELLOW MAIZE FUTURE", _YELLOW)]))
        with pytest.raises(ValueError, match="ABSENT"):
            T.build_jse_bronze_from_grid(
                grid(sections=[("WHITE MAIZE FUTURE", _WHITE),
                               ("MAIZE YELLOW FUTURE", _YELLOW)]))

    def test_the_section_map_is_bound_to_the_contract_map_both_ways(self):
        assert T._lint_section_map() == []
        assert set(T.JSE_SECTION_MAP.values()) == {
            s for s, r in FC.CONTRACT_MAP.items() if r["source"] == "jse_safex"}


class TestHeaderResolve:
    def test_the_upstream_typo_resolves_verbatim(self):
        first, cols = T.resolve_columns(grid())
        assert first == 4
        assert cols["mtm"] == 4 and cols["high"] == 6 and cols["low"] == 7
        assert cols["volume"] == 8 and cols["open_interest"] == 9
        assert cols["bid"] == 2, "'Cloisng Bid' is the real spelling and must resolve as-is"
        assert "cloisng bid" in T._FIELD_TOKENS["bid"]

    def test_the_two_header_rows_are_merged_per_column(self):
        _first, cols = T.resolve_columns(grid())
        assert cols["offer"] == 3 and cols["option_volume"] == 10

    def test_a_missing_required_column_fails_closed_and_names_what_it_saw(self):
        g = grid()
        g[2][9] = "Interesse"          # the OI header, renamed upstream
        g[3][9] = ""
        with pytest.raises(ValueError, match="open_interest"):
            T.resolve_columns(g)

    def test_no_mtm_column_refuses_to_guess_positionally(self):
        g = grid()
        g[2][4] = "Preco"
        with pytest.raises(ValueError, match="no MTM column"):
            T.resolve_columns(g)

    def test_the_trade_date_comes_from_the_sheet_not_the_key(self):
        assert T.header_trade_date(grid("2026-07-27")) == "2026-07-27"
        assert T.header_trade_date(grid("2026-03-02")) == "2026-03-02"

    def test_a_sheet_with_no_header_date_is_a_hard_error(self):
        g = grid()
        g[1][0] = "DOMESTIC FUTURES PRICES"
        with pytest.raises(ValueError, match="no 'DD-Mon-YYYY' header date"):
            T.build_jse_bronze_from_grid(g)


class TestSentinelAndDecode:
    def test_zero_is_no_trade_and_maps_to_null(self):
        bronze, stats = T.build_jse_bronze_from_grid(grid())
        idle = bronze[(bronze["raw_symbol"] == "Mar-2028")
                      & (bronze["leviathan_slug"] == "south_african_white_maize_jse")].iloc[0]
        for col in ("mtm", "bid", "offer", "vwap"):
            assert pd.isna(idle[col]), f"{col} of a no-trade row must be NULL, never 0"
        assert idle["high"] == pytest.approx(4027.0)   # the row still carries a real high/low
        assert idle["low"] == pytest.approx(3900.0)
        assert int(idle["volume"]) == 0, "a zero VOLUME is a true count, not a sentinel"
        assert int(idle["open_interest"]) == 0
        assert stats["zero_price_cells"] >= 4

    def test_the_delivery_month_decode(self):
        assert T.contract_month_str("Aug-2026") == "2026-08"
        assert T.contract_month_str("Mar-2028") == "2028-03"
        with pytest.raises(ValueError, match="MMM-YYYY"):
            T.contract_month_str("2026-08")

    def test_raw_symbol_is_the_expiry_verbatim(self):
        bronze, _ = T.build_jse_bronze_from_grid(grid())
        assert "Dec-2026" in set(bronze["raw_symbol"])


# ---------------------------------------------------------------------------
class TestSilverProjection:
    @staticmethod
    def _silver(date: str = "2026-07-27"):
        bronze, _ = T.build_jse_bronze_from_grid(grid(date))
        return S.build_jse_safex_silver(bronze)

    def test_shape_and_labels(self):
        df = self._silver()
        assert list(df.columns) == FC.SILVER_COLUMNS
        assert set(df["instrument_kind"]) == {"futures"}
        assert set(df["settle_kind"]) == {"mark_to_market"}, "the JSE number is a MARK, not a settle"
        assert set(df["source"]) == {"jse_safex"}
        assert set(df["unit"]) == {"ZAR/t"} and set(df["currency"]) == {"ZAR"}
        assert df["contract_month"].notna().all()
        assert df["expiry_date"].isna().all()
        assert df["dataset"].isna().all()
        assert set(df["trade_year"]) == {2026}

    def test_open_and_close_are_null_by_source(self):
        """F-N, undeclared upstream data loss: the sheet publishes bid/offer/MTM/VWAP/high/low and
        has NO open and NO close. Filling close from the MTM would launder a mark into a trade."""
        df = self._silver()
        assert df["open"].isna().all()
        assert df["close"].isna().all()
        assert df["settle"].notna().sum() == 16      # 18 rows less the two no-trade rows

    def test_open_interest_is_written(self):
        """futures_roll routes jse_safex -> open_interest and front_month fills a missing metric
        with -1.0, so a dropped OI column would silently demote the roll rule with no error."""
        from leviathan.silver import futures_roll as FR

        df = self._silver()
        assert FR.roll_method_for("south_african_white_maize_jse") == FR.METHOD_OPEN_INTEREST
        assert df["open_interest"].notna().all()
        assert int(df["open_interest"].max()) == 22942

    def test_the_labels_come_from_the_map_not_from_here(self):
        assert FC.lint_frame(self._silver()) == []

    def test_an_alien_slug_is_refused(self):
        bronze, _ = T.build_jse_bronze_from_grid(grid())
        bronze.loc[0, "leviathan_slug"] = "corn_cbot"
        with pytest.raises(ValueError, match="not JSE contracts"):
            S.build_jse_safex_silver(bronze)

    def test_a_re_captured_session_collapses_instead_of_false_failing_the_F2_ASSERTION(self):
        """THE OVERWRITTEN-OBJECT TRAP. The portal serves one object it overwrites in place, so the
        CAPTURE axis (the raw key's as_of_date) is not the SESSION axis (the sheet's header date).
        On any day the sheet is not refreshed -- a South African public holiday, a late publish, a
        portal stall -- two consecutive captures carry the SAME header date and the same 18 rows,
        and the nightly 5-day window reads both. Before the collapse this produced 18 duplicate
        NATURAL KEYS and `assert_no_duplicates` hard-failed the whole leg while reporting it as
        "the F2 double bar survived the ICE_BAR_RULE dedupe" -- an ICE diagnosis on a maize frame.
        """
        first, _ = T.build_jse_bronze_from_grid(grid(), as_of_date="2026-07-28")
        again, _ = T.build_jse_bronze_from_grid(grid(), as_of_date="2026-07-29")
        df = TASK.build_silver([first, again], source="jse")
        assert len(df) == 18, "the identical re-capture must collapse, not stack"
        TASK.assert_no_duplicates(df)
        assert TASK.assert_row_floor(df, TASK._SOURCE_SPECS["jse"]) == []

    def test_a_CONFLICTING_re_capture_still_fails_loudly(self):
        """The collapse is deliberately the NARROW form: EXACT duplicates only. Two rows sharing a
        natural key but carrying a DIFFERENT mark are a real conflict, not a re-read, and must
        still reach the uniqueness assertion."""
        first, _ = T.build_jse_bronze_from_grid(grid(), as_of_date="2026-07-28")
        again, _ = T.build_jse_bronze_from_grid(grid(), as_of_date="2026-07-29")
        again.loc[again.index[0], "mtm"] = 9999.0
        df = TASK.build_silver([first, again], source="jse")
        assert len(df) == 19
        with pytest.raises(ValueError, match="duplicate natural key"):
            TASK.assert_no_duplicates(df)

    def test_the_publish_route_passes_the_row_validator(self):
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        df = self._silver()
        contract = load_registry().table("silver_futures_eod")
        plan = build_partitioned_publish(
            df=df, contract=contract,
            auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
            job="futures_eod_jse", partition_cols=TASK._PARTITION_COLS,
            s3_client=None, row_validator=FC.lint_frame)
        assert plan.row_count == len(df) and plan.partition_count == 2


# ---------------------------------------------------------------------------
class TestRowFloorAndDispatch:
    def test_the_measured_shape_clears_the_armed_floor(self):
        bronze, _ = T.build_jse_bronze_from_grid(grid())
        df = S.build_jse_safex_silver(bronze)
        spec = TASK._SOURCE_SPECS["jse"]
        assert len(df) == 18 and spec.rows_per_day == 14
        assert TASK.assert_row_floor(df, spec) == []

    def test_a_short_day_fires(self):
        bronze, _ = T.build_jse_bronze_from_grid(
            grid(sections=[("WHITE MAIZE FUTURE", _WHITE[:5]),
                           ("YELLOW MAIZE FUTURE", _YELLOW[:5])]))
        df = S.build_jse_safex_silver(bronze)
        spec = TASK._SOURCE_SPECS["jse"]
        assert len(df) == 10
        bad = TASK.assert_row_floor(df, spec)
        assert len(bad) == 1 and ">= 14" in bad[0]

    def test_the_leg_is_wired_into_the_host(self):
        assert TASK._SOURCE_SPECS["jse"].implemented is True
        assert TASK._silver_builder("jse") is S.build_jse_safex_silver
        assert TASK._SOURCE_SPECS["jse"].job == "futures_eod_jse"
        assert TASK._SOURCE_SPECS["jse"].preflight_imports == ("xlrd",)


# ---------------------------------------------------------------------------
class TestProducer:
    def test_a_backfill_request_is_refused_by_code_not_by_policy(self):
        """PLAN GATE 8. An empty result would be indistinguishable from a public holiday."""
        with pytest.raises(NotImplementedError, match="no history; series starts at first run"):
            FETCH.refuse_backfill()
        with pytest.raises(NotImplementedError):
            FETCH.main(["--mode", "backfill"])

    def test_a_non_ole_response_is_not_a_workbook(self):
        why = FETCH.looks_like_the_agri_workbook(b"<html><body>Error</body></html>")
        assert why and "not a legacy OLE workbook" in why
        assert FETCH.looks_like_the_agri_workbook(FETCH._OLE_MAGIC + b"rest") is None

    def test_the_url_is_the_amdmtm_node(self):
        """/Safex/Mtm -- the node the public site links to -- is EMPTY, and /Safex/mtmdata is
        financial derivatives stale at 2019-04-25. The agri file is under /Safex/amdmtm."""
        assert "/Safex/amdmtm/NEW%20DAYAGR.xls" in FETCH.JSE_URL
        assert "/Safex/Mtm" not in FETCH.JSE_URL

    def test_the_key_is_keyed_on_the_fetch_date(self):
        key = raw_jse_safex_key("2026-07-28")
        assert key.endswith("as_of_date=2026-07-28/NEW_DAYAGR.xls")
        assert key.startswith(jse_safex_year_prefix(2026))
        assert " " not in key, "a space forces URL-encoding through every LIST/GET for no upside"

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["jse_safex"] == 40_000
