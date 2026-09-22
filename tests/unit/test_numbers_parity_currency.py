"""THE PARITY GATE LEARNS CURRENCY -- the pins for census B1/P2 (2026-09-22).

THE DEFECT THESE PIN. At 2026-09-22T09:27Z the blocking parity gate printed
``## verdict: 108/108 exact-match`` and PASSED while the pg mirror it certifies had last been
loaded in full on 2026-09-10 and was missing the whole September WASDE and PSD release. It passed
HONESTLY: every leg asked one of three FIXED HISTORICAL as-ofs, and a twelve-day-old mirror answers
all three exactly right. The gate proved ARITHMETIC and said nothing about VINTAGE -- and
``leviathan-dev-serving:133`` serves every number out of that mirror.

EVERY TEST HERE FAILS ON HEAD, because ``run_asofs``, ``tip_sql``, ``tip_value`` and
``tip_mismatch`` do not exist there. That is the point: the gate had no instrument for the
question, so the pin is that the instrument exists AND decides correctly.

AWS-free: the registry is a config read, ``build_sql``/``_dcmp`` are string compilers, and the
verdict is a pure function of two row lists.
"""
from __future__ import annotations

import importlib
from datetime import date

import pytest
from leviathan.graphrag.numbers.registry import load_registry

parity = importlib.import_module("jobs.utils.numbers_parity")
loader = importlib.import_module("jobs.utils.load_pg_numbers")


# --- (a) the three historical legs are PINNED and stay byte-identical (threat model T4) ------

def test_the_three_historical_asofs_are_unchanged():
    """T4's byte-identical set, stated as a test. The currency change is ADDITIVE: a leg at one of
    these three as-ofs must compile the same SQL and return the same rows after it as before it, so
    the list itself may not move. If someone needs a different historical as-of, that is a separate,
    argued change -- not a side effect of adding a today leg."""
    assert parity.ASOFS == ["2021-08-15", "2024-06-01", "2026-07-01"]


def test_run_asofs_appends_today_and_never_mutates_the_pinned_list():
    before = list(parity.ASOFS)
    got = parity.run_asofs()
    assert got[:3] == before, "the pinned history must lead, unchanged"
    assert got[3] == date.today().isoformat(), "the fourth leg is TODAY -- the currency question"
    assert len(got) == 4
    assert parity.ASOFS == before, "run_asofs must not mutate the module constant"
    # ...and it takes an injected clock, so a deck can pin a date without pinning a day.
    assert parity.run_asofs("2030-01-01")[3] == "2030-01-01"


def test_today_asof_is_the_wall_clock():
    """The silver gate's ``_freshness_clock`` records what a currency instrument reading a PINNED
    baseline does: with the frozen ``--asof 2026-02-15`` default it published ``months_behind = -6``
    and would have certified a 42-day-stale table as fresh. A currency leg's clock is the wall
    clock."""
    assert parity.today_asof() == date.today().isoformat()


# --- (b) the tip statement: one aggregate, in a spelling BOTH backends read the same way ------

def test_tip_sql_is_schema_qualified_for_every_mirrored_table():
    """``leviathan_dev.<physical>`` and never a bare relation. The pg mirror does not put its tables
    on the default search_path (load_pg_numbers creates them as ``"leviathan_dev"."<physical>"`` and
    pgnumbers connects with an ``options`` string that replaces whatever the DSN carried), so a bare
    name raises UndefinedTable on pg ONLY -- which reads as a broken mirror rather than a broken
    instrument. That exact defect was repaired in silver_rebuild_gate on 2026-09-11."""
    reg = load_registry()
    seen = 0
    for tid in loader.P1_TABLES:
        ts = reg.tables.get(tid)
        if ts is None:
            continue
        sql = parity.tip_sql(ts)
        if sql is None:
            continue
        seen += 1
        physical = ts.athena_table or ts.id
        assert f"FROM leviathan_dev.{physical}" in sql, sql
    assert seen >= 35, "nearly every mirrored table must have a measurable tip"


def test_tip_sql_normalises_a_timestamp_column_through_the_compilers_own_expression():
    """MEASURED, not argued (read-only Athena, 2026-09-22): ``SELECT MAX(date) FROM
    leviathan_dev.silver_pink_sheet`` returns '2026-08-01 00:00:00.000' while the normalised form
    returns '2026-08-01' -- and the pg mirror stores ``str(datetime)`` as '2026-08-01 00:00:00'. A
    naive MAX() would therefore report a FALSE STALE on every run for ever, and a fence that cries
    wolf daily stops being read.

    The expression is borrowed from ``query._dcmp`` rather than re-spelled, so the tip leg and every
    as-of predicate in the estate can never drift apart. This test is also the rename detector: if
    ``_dcmp`` moves, this goes red in CI rather than at 12:00Z inside a gate."""
    reg = load_registry()
    for tid in ("silver_pink_sheet", "silver_futures_prices"):
        ts = reg.get(tid)
        assert ts.date_col_type == "timestamp", f"{tid} is the DP-5 shape this test exists for"
        sql = parity.tip_sql(ts)
        assert f"substr(CAST({ts.date_col} AS varchar), 1, 10)" in sql, sql
    # ...and a plain string/date column keeps the type-agnostic CAST, never the substr.
    psd = parity.tip_sql(reg.get("silver_psd"))
    assert psd == "SELECT MAX(CAST(release_date AS varchar)) AS tip FROM leviathan_dev.silver_psd"


def test_tip_sql_reads_the_year_month_class_instead_of_skipping_it():
    """``knowledge_col()`` returns None for a card guarded on ``year*100+month``, and a
    ``if not col: skip`` would have silently exempted those cards -- the same shape as the sampler
    holes this wave closes. They get the year-month aggregate, which is byte-identical in shape to
    the gate's own ``_tip_ym_sql``."""
    reg = load_registry()
    ts = reg.get("silver_mpoc_stock_comparison")
    assert ts.knowledge_semantics == "year_month" and ts.knowledge_col() is None
    assert parity.tip_sql(ts) == ("SELECT MAX((year * 100) + month) AS tip "
                                  "FROM leviathan_dev.silver_mpoc_stock_comparison")


def test_every_mirrored_table_has_a_measurable_tip_today():
    """A TIP-SKIP is legal and is reported by name, but it must never become the normal case. If a
    future card lands with no knowledge axis at all, this goes red and somebody decides deliberately
    whether that card should be mirrored at all."""
    reg = load_registry()
    skipped = [t for t in loader.P1_TABLES
               if reg.tables.get(t) is not None and parity.tip_sql(reg.get(t)) is None]
    assert skipped == [], f"these mirrored cards declare no knowledge axis: {skipped}"


# --- (c) the verdict: a pure decision, pinned on the REAL 2026-09-22 numbers -----------------

def test_tip_mismatch_flags_the_measured_stale_mirror():
    """The concrete case. On 2026-09-22 canonical silver_psd_attributes read release_date 2026-08-12
    while silver_psd -- the same USDA bulk object -- read 2026-09-11; the mirror was a month behind
    on the first. Feed the leg those two tips and it must say so."""
    msg = parity.tip_mismatch("silver_psd", [{"tip": "2026-09-11"}], [{"tip": "2026-08-12"}])
    assert msg is not None
    assert "TIP-STALE silver_psd" in msg
    assert "2026-09-11" in msg and "2026-08-12" in msg


def test_tip_mismatch_is_silent_when_the_mirror_is_current():
    assert parity.tip_mismatch("silver_psd", [{"tip": "2026-09-11"}], [{"tip": "2026-09-11"}]) is None


def test_tip_value_normalises_the_two_backends_renders():
    """Athena returns a year-month as the STRING '202606'; psycopg returns the INT 202606. The same
    normaliser that already makes the grid's values comparable makes these comparable, so a
    cross-engine render difference can never masquerade as a stale mirror."""
    assert parity.tip_value([{"tip": "202606"}]) == parity.tip_value([{"tip": 202606}])
    assert parity.tip_value([]) == ""
    assert parity.tip_value([{"tip": None}]) == ""
    # empty on both backends is a MATCH -- vacuity is the grid's EMPTY-PANEL guard's job, not this
    # leg's, and a table that is empty everywhere is not a currency defect.
    assert parity.tip_mismatch("t", [], []) is None


# --- (d) the fence defaults to BLOCKING ------------------------------------------------------

def test_the_tip_leg_blocks_by_default_and_the_override_is_explicit(monkeypatch):
    """T4 asks for one day of report-only reading before the leg is trusted. That is an OPERATIONAL
    step, so it is an env opt-out -- and the DEFAULT IS BLOCKING, because a currency fence that
    defaults to advisory is fail-open, and the 108/108 PASS is exactly what an advisory currency
    instrument looks like once everybody has stopped reading it."""
    monkeypatch.delenv("PARITY_TIP_REPORT_ONLY", raising=False)
    assert parity.tip_report_only() is False
    for lit in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("PARITY_TIP_REPORT_ONLY", lit)
        assert parity.tip_report_only() is True, lit
    monkeypatch.setenv("PARITY_TIP_REPORT_ONLY", "0")
    assert parity.tip_report_only() is False


@pytest.mark.parametrize("tid", ["silver_psd", "silver_wasde", "silver_fgis"])
def test_the_today_leg_actually_compiles_for_the_flagship_tables(tid):
    """The currency as-of has to reach the compiler, not just the list. A card whose guard rejected a
    present-day as-of would make the whole leg decorative."""
    from leviathan.graphrag.numbers import query as Q
    reg = load_registry()
    ts = reg.get(tid)
    metric = parity.metric_plan(ts.shape, ts.metrics)[0][0]
    sql = Q.build_sql(Q.NumberQuery(table=tid, metric=metric, asof=parity.run_asofs()[-1],
                                    commodity=parity.SAMPLE_COMMODITY[tid], agg="latest", limit=50))
    assert sql.strip().upper().startswith("SELECT")
