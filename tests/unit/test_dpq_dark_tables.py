"""D-PQ PART 2 (dark-table resurrection) tranche 1a -- the numbers cards that survived a data-shape check.

Born from docs/private/recon/dark-table-resurrection-matrix.md: 22 silver tables are built, scheduled,
fire on time and are never reachable from serving. The matrix ranked SIX of them as "tranche 1a: pure
config, zero pipeline risk, all canonical-current". Measuring the actual PARQUET (not just the object
age and the registry contract) cut that six to ONE, and the reasons are pinned in this file because each
is a reusable acceptance rule rather than a fact about MPOC:

  * THE GUARD RULE. ``query._guard`` raises ``ValueError`` for any table whose ``knowledge_col()`` is
    None and whose semantics are not ``year_month``. A card on a table with no date and no year+month
    pair is therefore not "PIT-optimistic" -- it is a served card that REFUSES every read. Three of the
    six (silver_mpoc_exports_by_country, silver_ams_cotton_quality, silver_sagis_weekly_deliveries) are
    in exactly that state, and ``test_tranche_1a_skips_have_no_anchorable_as_of_guard`` holds the
    verdict so a future card cannot land on one without the test going red first.
  * THE FREE-AXIS RULE. NumberQuery can express commodity / country / period and nothing else. A table
    whose physical grain carries a further axis serves an arbitrary row per read. That is what excluded
    silver_wap_table01_revisions (a vintage_type/row_label axis putting a MARKETING-YEAR projection and
    a MONTHLY value in the same value_mmt column, 1-3 rows per (release, commodity, country, MY)), and
    it is why the card that DID land states its two axes in the imperative.

AWS-free: everything here reads the checked-in configs and compiles SQL; no query is executed.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as nreg

MPOC = "silver_mpoc_stock_comparison"

# The five tranche-1a candidates the recon ranked and this wave did NOT card, with the measured reason.
# `guard` = the table cannot anchor an as-of guard at all (build_sql raises on every read).
_SKIPPED = {
    "silver_sagis_weekly_deliveries": "guard",   # week_ending is 100% free text (0/2999 ISO), no date col
    "silver_mpoc_exports_by_country": "guard",   # year x country only, no knowledge column; content stops 2023
    "silver_ams_cotton_quality": "guard",        # commodity x geography x season, no knowledge column
    "silver_mpoc_trade_stats_monthly": "stale",  # guardable, but content stops 2023-12 behind a 21d-old object
    "silver_wap_table01_revisions": "free_axis",  # vintage_type/row_label axis NumberQuery cannot express
}


def _reg():
    return nreg.load_registry()


def _mpoc():
    return _reg().get(MPOC)


def _props() -> dict:
    return na.tool_schema(_reg())["input_schema"]["properties"]


# ====================================================================================================
# The card that landed.
# ====================================================================================================
def test_mpoc_card_is_served_and_in_the_tool_enum():
    assert MPOC in nreg.visible_tables(_reg())
    assert MPOC in _props()["table"]["enum"]


def test_mpoc_card_pit_shape():
    """year_month on year+month -- the ONI/IOD idiom. publication_lag_days is deliberately 0/unset: the
    year_month branch of _guard RETURNS BEFORE the publication-lag shift is applied, so a lag declared
    here would be inert decoration that the F010 reconcile would then carry as a real number."""
    ts = _mpoc()
    assert ts.knowledge_semantics == "year_month"
    assert (ts.year_col, ts.month_col) == ("year", "month")
    assert ts.knowledge_date_col is None and ts.date_col is None
    assert ts.publication_lag_days == 0
    assert ts.shape == "wide"
    assert ts.commodity_col == "oil_type" and ts.country_col == "country"
    assert set(ts.metrics) == {"ending_stocks_mt"}
    assert not ts.levels_only and not ts.quarantined


def test_mpoc_card_declares_no_partition_cols():
    """SARGABLE PARTITION DISCIPLINE, in its NEGATIVE form. The table is flat / projection-forbidden, so
    there is no projected grid to prune -- and a partition_col that is not a real Glue partition key is a
    hard reconcile_numbers failure (SILVER-F047). The bare `year <= <asof year>` bound the year_month
    guard already emits is the whole pruning story here."""
    from leviathan.silver import registry as SR
    assert _mpoc().partition_cols == []
    c = SR.load_registry().table(MPOC)
    assert c["partition_mode"] == "flat" and c["partition_keys"] == [] and c["projection"] == "forbidden"


def test_mpoc_card_notes_state_the_stateless_read_trap_and_the_scope_fence():
    """TWO free axes, neither with a default: a read that pins neither serves a Pakistani sunflower
    number wearing an Indian palm label. The card must say so in the imperative (the NASS 'ALWAYS PASS A
    STATE' precedent), must fence the vocabularies, and must not inherit the recon deck's wrong subject
    line -- there is no Malaysia row and no Indonesia row in this table."""
    ts = _mpoc()
    blob = (ts.description + " " + ts.notes).lower()
    for token in ("always pass both a country and an oil", "palm_oil", "sunflower_oil",
                  "bangladesh", "decline rather than substituting"):
        assert token in blob, token
    assert "silver_mpob" in blob                       # where origin-side Malaysian stocks actually live
    assert "never call a dated reading 'current'" in blob
    assert "2025-01" in blob                           # coverage honesty: no multi-year z is available


def test_mpoc_latest_read_guards_the_as_of_and_pins_both_axes():
    spec = Q.NumberQuery(table=MPOC, metric="ending_stocks_mt", asof="2026-08-07",
                         commodity="palm_oil", country="india")
    sql = Q.build_sql(spec)
    assert "oil_type = 'palm_oil'" in sql
    assert "country = 'india'" in sql
    assert "(year * 100 + month) <= 202608" in sql     # the year_month leakage guard
    assert "year <= 2026" in sql                       # the bare-column bound that rides beside it
    assert "ORDER BY (year * 100 + month) DESC" in sql and sql.endswith("LIMIT 1")


def test_mpoc_window_read_carries_both_ym_bounds():
    spec = Q.NumberQuery(table=MPOC, metric="ending_stocks_mt", asof="2026-08-07", commodity="palm_oil",
                         country="india", agg="series", period_start="2025-01", period_end="2026-06")
    sql = Q.build_sql(spec)
    assert "(year * 100 + month) >= 202501" in sql and "(year * 100 + month) <= 202606" in sql
    assert "(year * 100 + month) <= 202608" in sql     # the guard still rides over the window


def test_mpoc_card_states_the_year_month_leak_instead_of_denying_it():
    """D-PQ FIX-4 (tranche review, CONFIRMED-DEFECT 1). The first draft of this card asserted that "a
    month that has not been published yet cannot be reached at all" and, four lines later, that the
    honesty gap was "~2 weeks". Both were wrong and they contradicted each other. `_guard` emits
    `(year*100+month) <= asof_ym`, which admits the CURRENT, INCOMPLETE month -- at asof 2026-06-01 the
    2026-06 row passes, and MPOC prints June around 2026-07-15. The real window is the data month plus
    the print lag, up to ~45 days, and it is unclosable on this card because the year_month branch
    returns before `_pub_lagged_asof` runs.

    Pinned as TEXT because that is where the claim lived and where a future editor would restore it, and
    pinned NEGATIVELY as well: a card may not say the thing that was false."""
    ts = _mpoc()
    blob = (ts.description + " " + ts.notes).lower()
    assert "admits the current, incomplete month" in blob
    assert "not yet published" in blob
    assert "sees only complete months" not in blob and "sees only completed months" not in blob

    # ANTI-VACUITY, and the measurement the text is describing: the current month IS admitted.
    ts_ = _mpoc()
    rows = [{"country": "india", "oil_type": "palm_oil", "year": 2026, "month": 6,
             "ending_stocks_mt": 1.0}]
    spec = Q.NumberQuery(table=MPOC, metric="ending_stocks_mt", asof="2026-06-01",
                         commodity="palm_oil", country="india")
    assert Q.apply_pit_filter(rows, spec, ts_), "the incomplete current month is withheld after all -- " \
                                                "the card's leak paragraph is now overstated, re-measure it"
    assert "(year * 100 + month) <= 202606" in Q.build_sql(spec, ts_)


def test_mpoc_oracle_agrees_with_the_guard():
    """apply_pit_filter is the pure-Python twin of the SQL guard: a month whose LABEL is later than the
    as-of's is withheld on both sides, and the two free axes filter identically. (Label, not publication:
    the row above pins that the current month is admitted, which is the card's stated leak.)"""
    ts = _mpoc()
    rows = [
        {"country": "india", "oil_type": "palm_oil", "year": 2026, "month": 6, "ending_stocks_mt": 1.0},
        {"country": "india", "oil_type": "palm_oil", "year": 2026, "month": 9, "ending_stocks_mt": 2.0},
        {"country": "india", "oil_type": "soybean_oil", "year": 2026, "month": 6, "ending_stocks_mt": 3.0},
        {"country": "china", "oil_type": "palm_oil", "year": 2026, "month": 6, "ending_stocks_mt": 4.0},
    ]
    spec = Q.NumberQuery(table=MPOC, metric="ending_stocks_mt", asof="2026-08-07",
                         commodity="palm_oil", country="india")
    assert [r["ending_stocks_mt"] for r in Q.apply_pit_filter(rows, spec, ts)] == [1.0]


def test_mpoc_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit: reconcile_numbers binds the card's PIT fields to the
    silver contract and requires the numbers_ref back-pointer, and the drift test requires
    NUMBERS_TABLES to enumerate every tables.yaml id (an unenumerated table is STRUCTURALLY UNCHECKED)."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert MPOC in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == MPOC] == []
    c = reg.table(MPOC)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           (None, "year_month", None)
    assert c["value_columns"] == ["ending_stocks_mt"]


def test_mpoc_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert MPOC in P1_TABLES


def test_mpoc_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


def test_mpoc_is_advertised_to_the_router():
    """The D-CW coverage property is the general fence; this is the specific clause it forces. A served
    table the purpose string does not name is a table the router keeps routing away from forever."""
    purpose = next(t.purpose for t in dp.REGISTRY if t.name == "numbers").lower()
    assert "mpoc" in purpose
    assert MPOC.removeprefix("silver_") in dp.family_names()


# ====================================================================================================
# The five the recon ranked into tranche 1a and this wave REFUSED -- each verdict held as a test so the
# next card cannot land on one silently.
# ====================================================================================================
@pytest.mark.parametrize("table", sorted(t for t, why in _SKIPPED.items() if why == "guard"))
def test_tranche_1a_skips_have_no_anchorable_as_of_guard(table):
    """These three carry no vintage/ingest/data date AND no year+month pair, so build_sql RAISES on every
    read. Carding one would ship a served table that refuses 100% of its lookups -- the failure is loud
    rather than a leak, which is why the fence is in the compiler, but it is still a dead card.

    The fix is NOT a card: silver_sagis_weekly_deliveries needs the SILVER-F059 pre-step its EXPORTS
    sibling already got (a producer-derived week_ending_date DATE column plus the Glue ADD COLUMNS
    migration -- its `week_ending` is free text, measured 0 of 2,999 rows ISO, bilingual '1 - 7 Oct/Okt'
    with no year in it at all), and the other two need a publication/ingest stamp their producers do not
    currently emit. All three are LOADER/SCHEMA class, not CARD-ONLY."""
    from leviathan.silver import registry as SR
    c = SR.load_registry().table(table)
    assert c["knowledge_date_col"] is None and c["knowledge_semantics"] is None
    assert table not in nreg.visible_tables(_reg())          # not served -- the point of the test
    cols = {pc["name"] for pc in c["physical_columns"]}
    assert not ({"year", "month"} <= cols), (
        f"{table} now carries year+month, so year_month semantics ARE expressible -- re-open the card")


def test_the_skipped_tables_are_absent_from_the_numbers_registry():
    """A blunt anti-regression fence over the whole refused set (including the two whose blocker is not
    the guard): none of the five may acquire a card without this file being edited, which is where the
    measured reason lives."""
    served = set(nreg.visible_tables(_reg()))
    leaked = sorted(t for t in _SKIPPED if t in served)
    assert not leaked, (f"{leaked} was carded without discharging its recorded blocker "
                        f"(see _SKIPPED in this file and the D-PQ execution record)")


def test_wap_revisions_stays_uncarded_while_its_free_axis_is_inexpressible():
    """silver_wap_table01_revisions is the recon's #2 and its contract IS complete -- but its natural key
    carries row_label, and vintage_type splits value_mmt into two DIFFERENT quantities (a marketing-year
    projection and a monthly value) that NumberQuery has no field to choose between. Measured: up to 3
    rows per (release_month, commodity, country, marketing_year), e.g. wheat/argentina/2024-25 at release
    2024-09 returns 15.9 (the MY projection) or 18.0 (the September monthly) with nothing to pick.

    Nor does `vintage` semantics rescue it: the vintage branch of build_sql applies its ROW_NUMBER
    collapse to EVERY agg, so a revision SERIES across release months -- the entire desk story for this
    table -- is structurally unreachable under the semantics that would deduplicate the axis. The fix is
    a producer-side split or a new dimension, i.e. a design decision, not a card."""
    from leviathan.silver import registry as SR
    c = SR.load_registry().table("silver_wap_table01_revisions")
    assert "row_label" in c["natural_key"]
    assert {"vintage_type", "row_label"} <= {pc["name"] for pc in c["physical_columns"]}
    assert "silver_wap_table01_revisions" not in nreg.visible_tables(_reg())
