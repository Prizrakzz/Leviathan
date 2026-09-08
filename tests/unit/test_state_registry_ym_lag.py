"""``TableSpec.ym_publication_lag_days`` -- landed, declared, and READ BY NOTHING at S0.

STATE ENGINE DESIGN sec 1.4 (D21, D23), sitting S0. The field exists because ``TableSpec`` is
``extra="forbid"``: the key on the card and the field on the model must land in ONE commit or every
registry load raises. Nothing consumes it until the threaded ``ym_lag`` kwarg arrives at S1, so the
whole deck below is one claim said several ways -- **every compiled SQL string and every oracle verdict
is byte-identical with the field present**.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter, build_sql
from leviathan.graphrag.numbers.registry import TableSpec, load_registry

#: silver_noaa_oni was 15 at the first S0 landing -- a DECLARATION, corrected to 36 at the S0 review
#: against the design's own publisher read. The arithmetic and its falsifier are one test down.
YM_BOARD_CARDS = {"silver_noaa_oni": 36, "silver_noaa_iod": 45, "gold_weather_z": 7}


def test_the_field_defaults_to_none_not_zero():
    ts = TableSpec(id="x", description="d", shape="wide")
    assert ts.ym_publication_lag_days is None, \
        "None is UNDECLARED; 0 would be a positive claim that the source prints on the data month's " \
        "last day, which no card in this estate has measured"


def test_the_three_board_cards_declare_their_lag():
    cards = load_registry().tables
    for tid, want in YM_BOARD_CARDS.items():
        assert cards[tid].ym_publication_lag_days == want, tid
        assert cards[tid].knowledge_semantics == "year_month", tid


def test_no_other_card_declares_one_and_the_two_that_could_are_named():
    cards = load_registry().tables
    declared = {t for t, ts in cards.items() if ts.ym_publication_lag_days is not None}
    assert declared == set(YM_BOARD_CARDS)
    ym = {t for t, ts in cards.items() if ts.knowledge_semantics == "year_month"}
    assert ym - declared == {"silver_mpoc_stock_comparison", "silver_mpoc_trade_stats_monthly"}, \
        "the estate's year_month roster moved; state/lint.py's warning clause names the undeclared ones"


def test_the_oni_lag_is_the_center_month_arithmetic_and_not_the_publishers_bare_print_lag():
    """36 is the PRODUCT of two measured facts, and this is where either one breaking is caught.

    (1) THE PUBLISHER: CPC posts the ONI table "by the 5th of each month" (design APPENDIX B DELTA
        PASS 1 item B4.1, cpc.ncep.noaa.gov/.../enso/oni/v6/, read 2026-09-08).
    (2) THE ROW KEY: a row's ``month`` is the 3-month season's CENTER month, so the row for month M
        rides the print that lands by the 5th of M+2 -- 33 to 36 days after M's own month-end.

    The same read is the falsifier: on 2026-09-08 the newest published row was JJA 2026 = (2026, 7)
    and JAS = (2026, 8) was blank. Any lag that admits (2026, 8) that day is serving a month the
    publisher had not printed -- which is exactly what a bare 5 and the first landing's 15 both do.
    """
    from leviathan.transforms.raw_to_bronze.noaa_oni import SEASON_TO_MONTH
    assert SEASON_TO_MONTH["JJA"] == 7, "the CENTER-month stamp is half of this arithmetic"

    lag = load_registry().get("silver_noaa_oni").ym_publication_lag_days

    def admitted_from(year: int, month: int, days: int) -> date:
        return date(year, month, monthrange(year, month)[1]) + timedelta(days=days)

    read_day = date(2026, 9, 8)
    printed_month_8 = date(2026, 10, 5)       # the 5th of M+2, in the publisher's own words
    assert admitted_from(2026, 7, lag) <= read_day, "JJA 2026 WAS on the publisher's page that day"
    assert admitted_from(2026, 8, lag) > read_day, "JAS 2026 was NOT, and the lag must withhold it"
    assert admitted_from(2026, 8, lag) >= printed_month_8,         "and it must stay withheld until the print that carries it"
    # The two values this deck would previously have accepted, each shown serving (2026, 8) before the
    # print that carries it. A bare 5 -- the delta pass's own headline, which is the PRINT lag and not
    # this row's lag -- serves it before the seat had even watched it not exist.
    for leaky, first_served in ((5, date(2026, 9, 5)), (15, date(2026, 9, 15))):
        assert admitted_from(2026, 8, leaky) == first_served
        assert first_served < printed_month_8
    assert admitted_from(2026, 8, 5) <= read_day

    # a lag is a WITHHOLDING, so being a few days long is safe and being short is not; 36 is the long
    # end of the 33-36 day span (33 falls in a non-leap February).
    spans = {admitted_from(2025, m, lag).day for m in range(1, 13)}
    assert lag >= 33 and max(spans) <= 8, spans


def _specs():
    return [
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="latest"),
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series", limit=120),
        NumberQuery(table="silver_noaa_iod", metric="dmi_value", asof="2026-03-15", agg="latest"),
        NumberQuery(table="gold_weather_z", metric="drought_z", asof="2026-06-30", agg="series",
                    commodity="soybeans_cbot", country="United States", limit=120),
    ]


def test_the_compiled_sql_is_byte_identical_with_the_field_stripped():
    """The direct proof that nothing reads the field: compile each query against the card as loaded,
    and again against a copy whose lag is None. Any difference would be a live SQL change riding a
    data edit -- the thing D23 exists to prevent."""
    reg = load_registry()
    for spec in _specs():
        ts = reg.get(spec.table)
        stripped = ts.model_copy(update={"ym_publication_lag_days": None})
        assert build_sql(spec, ts) == build_sql(spec, stripped), spec.table


def test_the_oracle_agrees_with_itself_too():
    """``apply_pit_filter`` is build_sql's pure-Python twin (the test oracle and client fallback); the
    year_month branch is the ONE branch S1 moves, so it is pinned here at S0 in its unmoved form."""
    reg = load_registry()
    rows = [
        {"year": 2026, "month": 7, "value": 1.0},
        {"year": 2026, "month": 8, "value": 2.0},
        {"year": 2026, "month": 9, "value": 3.0},
        {"year": 2026, "month": 10, "value": 4.0},
    ]
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series")
    ts = reg.get("silver_noaa_oni")
    stripped = ts.model_copy(update={"ym_publication_lag_days": None})
    kept = apply_pit_filter(rows, spec, ts)
    assert kept == apply_pit_filter(rows, spec, stripped)
    # the UNMOVED semantics: a data month is admitted from its FIRST DAY, so 2026-09 is already in at
    # an as-of of the 8th -- three months ahead of the print that will carry it. That is exactly what
    # the declared 36-day lag shifts once `ym_lag` arms (2026-09 would drop out here, and 2026-08 with
    # it), and pinning the unmoved form makes S1's change visible as a diff rather than a surprise.
    assert [(r["year"], r["month"]) for r in kept] == [(2026, 7), (2026, 8), (2026, 9)]
