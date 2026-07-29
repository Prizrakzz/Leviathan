"""PRICE_AND_PLAYBOOKS W1a -- the CZCE leg + the shared --source host. Hermetic: no network, no AWS.

The fixtures below are built from the VERBATIM payload shape of two real sessions (2026-07-27,
37,747 B / 269 lines / 26 roots, and 2015-10-08, 21,982 B / 155 lines / 17 roots), reduced to the
rows a test can reason about. Every trap this file pins is one that produces a plausible WRONG
number rather than an error:

  * the header is Chinese and its wording DRIFTS across the history, so a name-based map dies
    silently at the 2015 boundary -- the parse is positional and this file proves it survives a
    header rewrite;
  * ``OI`` is rapeseed OIL. Reading it as cotton would land a 10,000 CNY/t oil price under a cotton
    slug that does not exist in this estate at all;
  * the 3-digit ``YMM`` code needs a decade anchor, and the only correct one is the file's own date;
  * the row floor is a COUNT of silver rows, never a count of raw lines (269 vs 13) and never a
    substring match (the plan's F-C GRADE-2 defect).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import czce_year_prefix, raw_czce_key
from leviathan.transforms.bronze_to_silver import czce_eod as S
from leviathan.transforms.raw_to_bronze import czce_eod as T

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task")
FETCH = _load("jobs/ingest/fetch_czce_eod.py", "fetch_czce_eod")

# The real title line: five tabs, the exchange name, then the session date in ASCII parentheses.
_TITLE = "\t\t\t\t\t\u90d1\u5dde\u5546\u54c1\u4ea4\u6613\u6240\u671f\u8d27\u6bcf\u65e5\u884c\u60c5\u8868({date})"
# The real 2026 column line. The 2015 file's first column header is a DIFFERENT word for the same
# column -- which is the whole reason nothing here is ever looked up by name.
_HEADER_2026 = ("\u5408\u7ea6\u4ee3\u7801|\u6628\u7ed3\u7b97    |\u4eca\u5f00\u76d8    |"
                "\u6700\u9ad8\u4ef7    |\u6700\u4f4e\u4ef7    |\u4eca\u6536\u76d8    |"
                "\u4eca\u7ed3\u7b97    |\u6da8\u8dcc1    |\u6da8\u8dcc2    |"
                "\u6210\u4ea4\u91cf(\u624b)|\u6301\u4ed3\u91cf    |\u589e\u51cf\u91cf    |"
                "\u6210\u4ea4\u989d(\u4e07\u5143)|\u4ea4\u5272\u7ed3\u7b97\u4ef7")
# Subtotal + grand total. Their first field is a label, not a contract code -- a looser row filter
# would ingest the grand total as a contract with 13.9M lots of volume.
_TRAILERS = [
    "\u5c0f\u8ba1    |          |          |          |          |          |          |"
    "         |         |552       |4,686     |196       |1,919.17    |",
    "\u603b\u8ba1    |          |          |          |          |          |          |"
    "         |         |13,888,569|17,183,130|-253,706  |49,804,032.57|",
]

# Verbatim row shapes from the live 2026-07-27 file. cols:
# code, prev_settle, open, high, low, close, SETTLE, chg1, chg2, volume, OI, oi_chg, turnover, ''
_ROWS_2026 = [
    "AP610 |7,715.00  |7,820.00  |7,910.00  |7,653.00  |7,727.00  |7,760.00  |12.00    |45.00    "
    "|166,584   |124,403   |4,722     |1,292,719.98|",
    # CF = COTTON. Kept out by the exact 2-character root match, not by luck.
    "CF611 |12,450.00 |12,515.00 |12,515.00 |12,440.00 |12,440.00 |12,455.00 |-10.00   |5.00     "
    "|62        |236       |-6        |386.15      |",
    "CY611 |18,000.00 |18,100.00 |18,120.00 |17,990.00 |18,010.00 |18,050.00 |50.00    |40.00    "
    "|10        |40        |1         |180.50      |",
    "OI609 |10,206.00 |10,240.00 |10,240.00 |9,966.00  |9,991.00  |10,083.00 |-215.00  |-123.00  "
    "|331,667   |324,754   |-47,444   |3,344,117.66|",
    "OI701 |10,132.00 |10,170.00 |10,170.00 |9,892.00  |9,919.00  |10,002.00 |-213.00  |-130.00  "
    "|66,579    |116,459   |-2,422    |665,956.42  |",
    "RM609 |2,405.00  |2,426.00  |2,426.00  |2,368.00  |2,387.00  |2,406.00  |-30.00   |-21.00   "
    "|1,282,015 |552,745   |-18,000   |1,862.18    |",
    "RM701 |2,349.00  |2,360.00  |2,362.00  |2,330.00  |2,339.00  |2,349.00  |-10.00   |0.00     "
    "|256,008   |331,045   |-1,000    |6,012.55    |",
    # A no-session row: 0.00 across OHLC while the settlement is real. The sentinel case.
    "ZC707 |801.40    |0.00      |0.00      |0.00      |0.00      |801.40    |0.00     |0.00     "
    "|0         |0         |0         |0.00        |",
]


def session_file(date: str = "2026-07-27", rows=None, header: str = _HEADER_2026,
                 encoding: str = "utf-8") -> bytes:
    lines = [_TITLE.format(date=date), header] + list(_ROWS_2026 if rows is None else rows)
    lines += _TRAILERS
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


# ---------------------------------------------------------------------------
class TestPositionalParse:
    def test_keeps_exactly_the_two_roots(self):
        bronze, stats = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        assert sorted(set(bronze["root"])) == ["OI", "RM"]
        assert sorted(set(bronze["leviathan_slug"])) == ["rapeseed_meal_zce", "rapeseed_oil_zce"]
        assert stats["rows_kept"] == 4 and stats["data_rows"] == len(_ROWS_2026)
        assert stats["roots_seen"] == 6

    def test_oi_is_rapeseed_oil_and_cotton_is_not_ingested_at_all(self):
        """The corrected defect. CZCE cotton is CF (yarn is CY) and there is NO cotton_zce slug in
        this estate -- so a root filter that took OI for cotton would land a 10,000 CNY/t oil price
        under a contract that does not exist."""
        bronze, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        oil = bronze[bronze["raw_symbol"] == "OI609"].iloc[0]
        assert oil["leviathan_slug"] == "rapeseed_oil_zce"
        assert oil["settle"] == pytest.approx(10083.0)      # an oil price level, not a meal one
        meal = bronze[bronze["raw_symbol"] == "RM609"].iloc[0]
        assert meal["leviathan_slug"] == "rapeseed_meal_zce"
        assert meal["settle"] == pytest.approx(2406.0)
        assert "CF611" not in set(bronze["raw_symbol"])
        assert "cotton_zce" not in FC.CONTRACT_MAP

    def test_settle_is_the_seventh_field_and_never_the_close(self):
        bronze, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        row = bronze[bronze["raw_symbol"] == "OI609"].iloc[0]
        assert row["settle"] == pytest.approx(10083.0)      # the SETTLE column
        assert row["close"] == pytest.approx(9991.0)        # the close, carried separately
        assert row["prev_settle"] == pytest.approx(10206.0)
        assert row["open"] == pytest.approx(10240.0)
        assert row["high"] == pytest.approx(10240.0)
        assert row["low"] == pytest.approx(9966.0)
        assert int(row["volume"]) == 331667
        assert int(row["open_interest"]) == 324754

    def test_raw_symbol_is_verbatim(self):
        bronze, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        assert set(bronze["raw_symbol"]) == {"OI609", "OI701", "RM609", "RM701"}

    def test_the_trailer_rows_are_not_contracts(self):
        """The grand-total row carries 13.9M lots. A row filter that admitted it would publish that
        as a contract."""
        bronze, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        assert int(bronze["volume"].max()) == 1282015

    def test_the_parse_survives_a_total_header_rewrite(self):
        """THE POSITIONAL PROPERTY. The 2015 file's column header words differ from the 2026 file's
        for the same columns; a name-based map would have died silently at that boundary."""
        want, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        for header in ("A|B|C|D|E|F|G|H|I|J|K|L|M|N",
                       "\u54c1\u79cd\u6708\u4efd|x|x|x|x|x|x|x|x|x|x|x|x|x",
                       "",
                       "completely different words in a different order"):
            got, _ = T.build_czce_bronze(session_file(header=header), trade_date="2026-07-27")
            pd.testing.assert_frame_equal(got, want)

    def test_gb18030_bytes_decode(self):
        """The 2015 files are GB18030 while the server labels every session charset=utf-8."""
        payload = session_file(date="2015-10-08", encoding="gb18030")
        with pytest.raises(UnicodeDecodeError):
            payload.decode("utf-8")
        bronze, stats = T.build_czce_bronze(payload, trade_date="2015-10-08")
        assert stats["encoding"] == "gb18030"
        assert stats["rows_kept"] == 4

    def test_the_no_session_zero_is_a_sentinel_not_a_price(self):
        rows = [_ROWS_2026[3], _ROWS_2026[7].replace("ZC707", "OI707")]
        bronze, stats = T.build_czce_bronze(session_file(rows=rows), trade_date="2026-07-27")
        idle = bronze[bronze["raw_symbol"] == "OI707"].iloc[0]
        assert stats["zero_ohlc_rows"] == 1
        for col in ("open", "high", "low", "close"):
            assert pd.isna(idle[col]), f"{col} of a no-session row must be NULL, never 0.0"
        assert idle["settle"] == pytest.approx(801.40)      # the settlement is REAL and is kept
        assert int(idle["volume"]) == 0                     # a true count, not a sentinel

    def test_a_misfiled_object_is_a_hard_error(self):
        """The path segment is the trade date AND the decade anchor, so a file landed under the
        wrong day would re-date every contract code in it."""
        with pytest.raises(ValueError, match="misfiled"):
            T.build_czce_bronze(session_file(date="2026-07-27"), trade_date="2026-07-24")

    def test_a_short_row_is_refused_rather_than_mis_mapped(self):
        short = "RM609 |2,405.00  |2,426.00  |2,426.00  |2,368.00  |2,387.00  |2,406.00  |-30.00 |"
        with pytest.raises(ValueError, match="field"):
            T.build_czce_bronze(session_file(rows=[short] + _ROWS_2026), trade_date="2026-07-27")

    def test_the_root_map_is_bound_to_the_contract_map_both_ways(self):
        assert T._lint_root_map() == []
        assert set(T.CZCE_ROOT_MAP.values()) == {
            s for s, r in FC.CONTRACT_MAP.items() if r["source"] == "czce"}


# ---------------------------------------------------------------------------
class TestDecadeAnchor:
    """The 3-digit YMM code carries ONE year digit. datetime.now() would re-date history."""

    def test_the_anchor_is_the_file_date(self):
        assert T.contract_month_str("609", "2026-07-27") == "2026-09"
        assert T.contract_month_str("609", "2015-10-08") == "2016-09"
        assert T.contract_month_str("701", "2026-07-27") == "2027-01"
        assert T.contract_month_str("511", "2015-10-08") == "2015-11"

    def test_a_backfill_rerun_decades_later_decodes_identically(self):
        """The whole point: the anchor is a path segment, so the answer does not move."""
        for anchor in ("2016-07-27", "2016-01-02", "2016-12-30"):
            assert T.contract_month_str("609", anchor) == "2016-09"

    def test_the_decade_boundary_forward(self):
        assert T.contract_month_str("001", "2029-12-20") == "2030-01"
        assert T.contract_month_str("003", "2029-11-01") == "2030-03"

    def test_the_decade_boundary_backward(self):
        assert T.contract_month_str("912", "2030-01-05") == "2029-12"
        assert T.resolve_contract_year(9, "2030-01-05") == 2029

    def test_a_bad_month_fails_closed(self):
        with pytest.raises(ValueError, match="delivery month"):
            T.contract_month_str("613", "2026-07-27")
        with pytest.raises(ValueError, match="3-digit"):
            T.contract_month_str("60", "2026-07-27")


# ---------------------------------------------------------------------------
class TestSilverProjection:
    @staticmethod
    def _silver(date: str = "2026-07-27"):
        bronze, _ = T.build_czce_bronze(session_file(date=date), trade_date=date)
        return S.build_czce_eod_silver(bronze)

    def test_shape_and_labels(self):
        df = self._silver()
        assert list(df.columns) == FC.SILVER_COLUMNS
        assert set(df["instrument_kind"]) == {"futures"}
        assert set(df["settle_kind"]) == {"settlement"}
        assert set(df["source"]) == {"czce"}
        assert set(df["unit"]) == {"CNY/t"}
        assert set(df["currency"]) == {"CNY"}
        assert df["contract_month"].notna().all()
        assert df["expiry_date"].isna().all(), "expiry is NEVER derived from the delivery month"
        assert df["dataset"].isna().all(), "dataset is the VENDOR id; source already names czce"
        assert set(df["trade_year"]) == {2026} and df["trade_year"].dtype == "int64"

    def test_the_labels_come_from_the_map_not_from_here(self):
        assert FC.lint_frame(self._silver()) == []

    def test_an_alien_slug_is_refused(self):
        bronze, _ = T.build_czce_bronze(session_file(), trade_date="2026-07-27")
        bronze.loc[0, "leviathan_slug"] = "corn_cbot"
        with pytest.raises(ValueError, match="not CZCE contracts"):
            S.build_czce_eod_silver(bronze)

    def test_the_publish_route_passes_the_row_validator(self):
        """Gate 8's wiring, proven rather than grepped: the CZCE frame goes through
        build_partitioned_publish with row_validator=FC.lint_frame, in dry-run, no S3."""
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        df = self._silver()
        contract = load_registry().table("silver_futures_eod")
        plan = build_partitioned_publish(
            df=df, contract=contract,
            auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
            job="futures_eod_czce", partition_cols=TASK._PARTITION_COLS,
            s3_client=None, row_validator=FC.lint_frame)
        assert plan.row_count == len(df)
        assert plan.partition_count == 2          # one per (slug, 2026)

    def test_a_mislabeled_row_cannot_reach_the_publisher(self):
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        df = self._silver()
        df.loc[0, "unit"] = "USD/metric ton"
        contract = load_registry().table("silver_futures_eod")
        with pytest.raises(Exception, match="unit|lint|valid"):
            build_partitioned_publish(
                df=df, contract=contract,
                auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
                job="futures_eod_czce", partition_cols=TASK._PARTITION_COLS,
                s3_client=None, row_validator=FC.lint_frame)


# ---------------------------------------------------------------------------
class FakeS3:
    """get_object / list_objects_v2 over an in-memory ``{key: bytes}`` map."""

    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})

    def get_object(self, *, Bucket, Key):  # noqa: N803 -- boto3 kwarg casing
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, **kw):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


class TestHostDispatch:
    """The shared host. The Databento leg's own suite (tests/unit/test_futures_eod_task.py) is the
    proof it stayed byte-compatible; these are the new seams."""

    def test_every_declared_source_has_a_spec_and_a_floor_story(self):
        assert set(TASK._SOURCE_SPECS) == {"databento", "czce", "jse", "cepea", "miax"}
        assert TASK._SOURCE_SPECS["czce"].rows_per_day == 10
        assert TASK._SOURCE_SPECS["jse"].rows_per_day == 14
        assert TASK._SOURCE_SPECS["cepea"].rows_per_day == 2
        assert TASK._SOURCE_SPECS["cepea"].rows_per_day_exact is True
        assert TASK._SOURCE_SPECS["miax"].rows_per_day == 6
        # The Databento unit floor is a DIFFERENT measurement and must not have leaked across.
        assert TASK._SOURCE_SPECS["databento"].rows_per_day == 0
        assert TASK._SOURCE_SPECS["databento"].min_rows_per_unit == TASK._MIN_ROWS_PER_UNIT == 25
        assert TASK._SOURCE_SPECS["czce"].min_rows_per_unit == 0

    def test_the_databento_preflight_is_source_conditional(self):
        """A CZCE run must not fail on a vendor package it never calls -- the reason the module
        entry preflight had to move behind the dispatch."""
        assert TASK._SOURCE_SPECS["databento"].preflight_imports == ("databento",)
        assert TASK._SOURCE_SPECS["czce"].preflight_imports == ()
        assert TASK.preflight(TASK._SOURCE_SPECS["czce"]) is True
        broken = TASK._SOURCE_SPECS["czce"]._replace(
            preflight_imports=("a_package_that_does_not_exist",))
        assert TASK.preflight(broken) is False

    def test_per_source_job_labels(self):
        assert TASK._SOURCE_SPECS["databento"].job == "futures_eod_databento" == TASK._JOB
        assert TASK._SOURCE_SPECS["czce"].job == "futures_eod_czce"

    def test_the_silver_builder_dispatches(self):
        assert TASK._silver_builder("czce") is S.build_czce_eod_silver
        from leviathan.transforms.bronze_to_silver.databento_eod import build_databento_eod_silver
        assert TASK._silver_builder("databento") is build_databento_eod_silver

    def test_all_five_declared_legs_are_now_implemented(self):
        """jse / cepea / miax were declared-but-unimplemented when the CZCE leg landed and are
        implemented now (W1a + W1b). Their parse suites are tests/unit/test_{jse_safex,cepea,
        miax}_eod.py; what this pins is that the DISPATCH has no declared-only holes left."""
        for source in sorted(TASK._SOURCE_SPECS):
            assert TASK._SOURCE_SPECS[source].implemented is True, source
            assert TASK._silver_builder(source) is not None

    def test_an_undeclared_leg_names_what_is_missing(self):
        """The declared-but-unimplemented path still exists for the next leg (bursa is W1c-bound
        behind a Cloudflare JS challenge), so the error that names the missing module is exercised
        against a synthetic spec rather than left untested until someone needs it."""
        with pytest.raises(ValueError, match="unknown --source"):
            TASK.source_spec("bursa")
        pending = TASK._SOURCE_SPECS["czce"]._replace(
            name="bursa", job="futures_eod_bursa", implemented=False,
            todo="a browser producer on Fargate -- the zone is behind a Cloudflare JS challenge")
        try:
            TASK._SOURCE_SPECS["bursa"] = pending
            with pytest.raises(NotImplementedError, match="not implemented|Still needed"):
                TASK._silver_builder("bursa")
        finally:
            TASK._SOURCE_SPECS.pop("bursa", None)

    def test_build_silver_still_defaults_to_databento(self):
        """--source's default keeps every landed W2 invocation byte-identical."""
        empty = TASK.build_silver([])
        assert list(empty.columns) == FC.SILVER_COLUMNS

    def test_czce_units_are_sessions_from_the_landed_prefix(self):
        keys = {raw_czce_key(d): b"" for d in ("2015-10-08", "2016-03-01", "2026-07-27")}
        s3 = FakeS3(keys)
        got = TASK.czce_units(s3, "b", since="2015-01-01")
        assert got == sorted(keys)
        assert [TASK._czce_key_date(k) for k in got] == ["2015-10-08", "2016-03-01", "2026-07-27"]
        assert TASK.czce_units(s3, "b", since="2026-01-01") == [raw_czce_key("2026-07-27")]
        assert TASK.czce_units(s3, "b", years=[2016]) == [raw_czce_key("2016-03-01")]

    def test_a_session_with_no_landed_object_is_absence_not_error(self):
        """A holiday is a 404 at fetch time, so no object exists, so the unit is simply not
        selected -- there is no failure to swallow and no curated calendar to drift."""
        s3 = FakeS3({raw_czce_key("2026-07-27"): session_file()})
        assert TASK.czce_units(s3, "b", since="2026-07-01") == [raw_czce_key("2026-07-27")]
        bronze, stats = TASK.load_czce_session(s3, "b", raw_czce_key("2026-07-27"))
        assert stats["trade_date"] == "2026-07-27" and len(bronze) == 4
        with pytest.raises(FileNotFoundError):
            TASK.load_czce_session(s3, "b", raw_czce_key("2026-07-28"))

    def test_the_prefix_is_year_bounded(self):
        assert czce_year_prefix(2015) == "raw/production/source=czce/year=2015/"
        assert raw_czce_key("2026-07-27").startswith(czce_year_prefix(2026))


class TestRowFloor:
    """PLAN GATE 5. Exact silver row COUNTS per day -- never raw lines, never a substring."""

    @staticmethod
    def _day(date: str, rows: int) -> pd.DataFrame:
        base = pd.DataFrame({
            "trade_date": [pd.Timestamp(date)] * rows,
            "source": ["czce"] * rows,
            "leviathan_slug": ["rapeseed_meal_zce"] * rows,
        })
        return base

    def test_a_full_session_passes(self):
        czce = TASK._SOURCE_SPECS["czce"]
        assert TASK.assert_row_floor(self._day("2026-07-27", 13), czce) == []
        assert TASK.assert_row_floor(self._day("2026-07-27", 10), czce) == []

    def test_a_thin_session_fires_and_names_the_day(self):
        czce = TASK._SOURCE_SPECS["czce"]
        bad = TASK.assert_row_floor(self._day("2026-07-27", 9), czce)
        assert len(bad) == 1 and "2026-07-27" in bad[0] and ">= 10" in bad[0]

    def test_the_floor_is_per_day_not_per_run(self):
        czce = TASK._SOURCE_SPECS["czce"]
        df = pd.concat([self._day("2026-07-27", 13), self._day("2026-07-28", 3)],
                       ignore_index=True)
        bad = TASK.assert_row_floor(df, czce)
        assert len(bad) == 1 and "2026-07-28" in bad[0]

    def test_the_cepea_floor_is_an_equality(self):
        cepea = TASK._SOURCE_SPECS["cepea"]
        df = self._day("2026-07-27", 3)
        df["source"] = "cepea"
        bad = TASK.assert_row_floor(df, cepea)
        assert len(bad) == 1 and "== 2" in bad[0]
        two = self._day("2026-07-27", 2)
        two["source"] = "cepea"
        assert TASK.assert_row_floor(two, cepea) == []

    def test_the_floor_counts_silver_rows_not_raw_lines(self):
        """The 2026-07-27 file is 269 LINES across 26 roots and yields 13 silver rows. A floor read
        against lines would pass a leg that wrote nothing at all."""
        payload = session_file()
        assert len(payload.decode("utf-8").splitlines()) == len(_ROWS_2026) + 4
        bronze, _ = T.build_czce_bronze(payload, trade_date="2026-07-27")
        df = S.build_czce_eod_silver(bronze)
        czce = TASK._SOURCE_SPECS["czce"]
        assert len(df) == 4
        assert TASK.assert_row_floor(df, czce), "4 kept rows must be BELOW the 10-row floor"

    def test_a_foreign_publication_source_is_rejected_by_equality(self):
        """Rows are scoped by source EQUALITY. The plan's F-C defect is a substring match that
        merges a second deliverable contract into the slug and lands a plausible wrong number."""
        czce = TASK._SOURCE_SPECS["czce"]
        df = self._day("2026-07-27", 13)
        df.loc[0, "source"] = "czce_grade_2"      # a substring test would still call this czce
        bad = TASK.assert_row_floor(df, czce)
        assert len(bad) == 1 and "foreign publication source" in bad[0]

    def test_databento_has_no_daily_floor(self):
        assert TASK.assert_row_floor(self._day("2026-07-27", 1),
                                     TASK._SOURCE_SPECS["databento"]) == []


# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status: int, content: bytes = b""):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestProducer:
    def test_the_url_mirrors_the_raw_key(self):
        import datetime as dt

        day = dt.date(2026, 7, 27)
        assert FETCH.czce_url(day) == ("https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/"
                                       "20260727/FutureDataDaily.txt")
        assert raw_czce_key(day.isoformat()).endswith("trade_date=20260727/FutureDataDaily.txt")

    def test_a_404_day_is_an_absence_not_an_error(self, monkeypatch):
        """Weekends, Golden Week and every other closure. The venue decides the calendar."""
        import datetime as dt

        monkeypatch.setattr(FETCH.requests, "get", lambda url, timeout=None: _Resp(404))
        assert FETCH.fetch_day(dt.date(2026, 7, 26)) is None

    def test_a_412_is_the_waf_and_is_never_treated_as_a_closed_session(self, monkeypatch):
        import datetime as dt

        monkeypatch.setattr(FETCH.requests, "get", lambda url, timeout=None: _Resp(412, b"js"))
        monkeypatch.setattr(FETCH.time, "sleep", lambda *_a, **_k: None)
        with pytest.raises(RuntimeError, match="412"):
            FETCH.fetch_day(dt.date(2026, 7, 27))

    def test_a_200_session_file_is_landed_verbatim(self, monkeypatch):
        import datetime as dt

        payload = session_file(rows=_ROWS_2026 * 8)   # a real session carries >= 100 rows
        monkeypatch.setattr(FETCH.requests, "get", lambda url, timeout=None: _Resp(200, payload))
        got = FETCH.fetch_day(dt.date(2026, 7, 27))
        assert got is payload
        assert FETCH.looks_like_a_session_file(payload, dt.date(2026, 7, 27)) is None

    def test_a_challenge_page_is_not_a_session_file(self):
        import datetime as dt

        junk = b"<html><title>Just a moment...</title></html>" * 200
        why = FETCH.looks_like_a_session_file(junk, dt.date(2026, 7, 27))
        assert why and "not a session file" in why

    def test_the_venue_serving_another_day_is_caught(self):
        import datetime as dt

        why = FETCH.looks_like_a_session_file(session_file(date="2026-07-24",
                                                           rows=_ROWS_2026 * 8),
                                              dt.date(2026, 7, 27))
        assert why and "header date" in why

    def test_before_the_first_session_is_a_permanent_absence(self):
        ns = FETCH.argparse.Namespace(mode="backfill", start="2015-09-07", end=None,
                                      lookback_days=5)
        with pytest.raises(SystemExit, match="PERMANENT absence"):
            FETCH.resolve_window(ns)

    def test_the_backfill_window_defaults_to_the_first_session(self):
        ns = FETCH.argparse.Namespace(mode="backfill", start=None, end="2015-10-10",
                                      lookback_days=5)
        start, end = FETCH.resolve_window(ns)
        assert start.isoformat() == T.CZCE_FIRST_TRADE_DATE
        assert len(list(FETCH.daterange(start, end))) == 3

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["czce"] == 5_000, (
            "check_min_file_size returns SILENTLY for an unknown source -- a missing entry is a "
            "DISABLED floor, not an error")


# ---------------------------------------------------------------------------
_RM_MONTHS = ("608", "609", "611", "701", "703", "705", "707")
_OI_MONTHS = ("609", "611", "701", "703", "705", "707")


def full_session(date: str = "2026-07-27") -> bytes:
    """A whole session: 7 RM + 6 OI expiries, the shape measured on 2015-10-08 and 2026-07-24/27."""
    rows = [_ROWS_2026[5].replace("RM609", "RM" + m) for m in _RM_MONTHS]
    rows += [_ROWS_2026[3].replace("OI609", "OI" + m) for m in _OI_MONTHS]
    rows += [_ROWS_2026[0], _ROWS_2026[1], _ROWS_2026[7]]     # AP / CF / ZC, all discarded
    return session_file(date=date, rows=rows)


class TestHostEndToEnd:
    """main() over a fake S3: units -> bronze -> silver -> gate 5 -> the dry-run publish."""

    @staticmethod
    def _run(monkeypatch, objects, *extra):
        monkeypatch.setattr(TASK, "get_thread_local_s3_client",
                            lambda region: FakeS3(objects))
        return TASK.main(["--source", "czce", "--mode", "backfill", "--bucket", "b",
                          "--aws-region", "us-east-1", *extra])

    def test_a_full_backfill_dry_run_is_green(self, monkeypatch):
        objects = {raw_czce_key(d): full_session(d)
                   for d in ("2026-07-24", "2026-07-27", "2026-07-28")}
        assert self._run(monkeypatch, objects) == 0

    def test_a_thin_session_fails_the_run(self, monkeypatch):
        """Gate 5, end to end: below the floor is exit 1, never a quiet short publish."""
        objects = {raw_czce_key("2026-07-27"): full_session("2026-07-27"),
                   raw_czce_key("2026-07-28"): session_file(date="2026-07-28")}   # 4 kept rows
        assert self._run(monkeypatch, objects) == 1

    def test_row_floor_report_is_probe_p10(self, monkeypatch):
        """P10 derives the venue holiday calendar from the backfill BEFORE the gate is armed."""
        objects = {raw_czce_key("2026-07-27"): full_session("2026-07-27"),
                   raw_czce_key("2026-07-28"): session_file(date="2026-07-28")}
        assert self._run(monkeypatch, objects, "--row-floor", "report") == 0

    def test_no_landed_session_is_an_honest_failure_not_an_empty_publish(self, monkeypatch):
        assert self._run(monkeypatch, {}) == 1

    def test_an_unimplemented_leg_refuses_before_any_aws_call(self, monkeypatch):
        """All five declared legs are implemented now, so the guard is exercised against a
        synthetic declared-only spec -- it still has to fire for the NEXT leg (bursa, W1c)."""
        def _boom(region):
            raise AssertionError("must not build an S3 client for an unimplemented leg")

        monkeypatch.setattr(TASK, "get_thread_local_s3_client", _boom)
        pending = TASK._SOURCE_SPECS["czce"]._replace(
            name="bursa", job="futures_eod_bursa", publication_sources=("bursa",),
            implemented=False, todo="a browser producer on Fargate (W1c)")
        try:
            TASK._SOURCE_SPECS["bursa"] = pending
            assert TASK.main(["--source", "bursa", "--bucket", "b",
                              "--aws-region", "us-east-1"]) == 1
        finally:
            TASK._SOURCE_SPECS.pop("bursa", None)
