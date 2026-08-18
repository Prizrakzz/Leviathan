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

    DISCHARGED 2026-08-18 (D-LD Track 1), and the rule above KEEPS ITS TEXT because it is still the
    correct general rule -- what changed is that the axis is now closable without a NumberQuery field.
    A further axis no longer forces a refusal when the card can pin it in CODE: `Metric.row_filters`
    emits the fence into every compiled read (`vintage_type IN ('year')`), and `grain_cols` decides what
    a vintage collapse is allowed to collapse. See `_DISCHARGED` below and
    test_wap_revisions_free_axis_blocker_is_discharged_by_mechanism_not_by_assertion.

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

# The tranche-1a candidates the recon ranked and this wave did NOT card, with the measured reason.
# `guard` = the table cannot anchor an as-of guard at all (build_sql raises on every read).
#
# D-LD (2026-08-18) removed TWO entries from this dict. Removing an entry is the ONLY honest way to card
# one of these tables -- the blanket fence below reads this dict, so a card that lands without an edit
# here goes red -- and the removal is never silent: the reason moves to `_DISCHARGED` and, for the
# free-axis verdict, to a replacement test that pins the MECHANISM that closed it. The three that remain
# are untouched and the fence over them is exactly as strong as it was.
_SKIPPED = {
    "silver_sagis_weekly_deliveries": "guard",   # week_ending is 100% free text (0/2999 ISO), no date col
    "silver_mpoc_exports_by_country": "guard",   # year x country only, no knowledge column; content stops 2023
    "silver_ams_cotton_quality": "guard",        # commodity x geography x season, no knowledge column
}

# The verdicts D-LD DISCHARGED, kept here because this file is the record of why a table was refused --
# a discharged refusal that is merely deleted leaves the next reader re-deriving the argument.
_DISCHARGED = {
    # Was: "stale" -- guardable, but content stops 2023-12 behind a 21d-old object. RE-MEASURED 2026-08-18:
    # the object is 3 days old and CERTIFIED, and the 2023-12 ceiling is not staleness at all but a CLOSED
    # ARCHIVE (15 annual stat pages in configs/sources/mpoc_archive.yaml, none after 2023). A closed
    # archive is servable; the card carries the ceiling in its own notes AND in the router clause, so no
    # ask is routed here for a current print. Note this was the only one of the five whose blocker was a
    # judgement about FRESHNESS rather than a structural impossibility -- the other reasons cannot be
    # discharged this way, and the three above are not.
    "silver_mpoc_trade_stats_monthly": "stale -> closed-archive, re-measured (D-LD 2026-08-18)",
    # Was: "free_axis" -- vintage_type/row_label axis NumberQuery cannot express. Both halves of that
    # verdict were CORRECT and both are now closed by card mechanism rather than by assertion; see the
    # replacement test at the bottom of this file.
    "silver_wap_table01_revisions": "free_axis -> closed by row_filters + grain_cols (D-LD 2026-08-18)",
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
    """A blunt anti-regression fence over the whole refused set: none of them may acquire a card without
    this file being edited, which is where the measured reason lives. UNCHANGED by D-LD -- it still reads
    the live `_SKIPPED` and still refuses every table in it. What D-LD changed is the CONTENTS of that
    dict (two verdicts discharged, three untouched), which is the edit the fence exists to force."""
    served = set(nreg.visible_tables(_reg()))
    leaked = sorted(t for t in _SKIPPED if t in served)
    assert not leaked, (f"{leaked} was carded without discharging its recorded blocker "
                        f"(see _SKIPPED in this file and the D-PQ execution record)")


def test_a_discharged_verdict_names_a_table_that_really_is_served_now():
    """The other half of the fence above, and the reason a discharge is a MOVE rather than a delete. A
    table may sit in `_DISCHARGED` only if it is actually carded -- otherwise a future editor could
    silence the blanket refusal simply by relocating a name, and the file would record a discharge that
    never happened. The two dicts must also stay disjoint."""
    served = set(nreg.visible_tables(_reg()))
    unserved = sorted(t for t in _DISCHARGED if t not in served)
    assert not unserved, (f"{unserved} is recorded as DISCHARGED but is not served -- a discharge is not "
                          f"a way to leave _SKIPPED, it is what landing the card looks like")
    assert not (set(_SKIPPED) & set(_DISCHARGED))


def test_wap_revisions_free_axis_blocker_is_discharged_by_mechanism_not_by_assertion():
    """D-LD (2026-08-18) DISCHARGES the D-PQ refusal above. Both halves of the 2026-08-07 verdict were
    correct and both are now closed by CARD mechanism, so the reason stays here rather than being deleted:

      (a) THE AXIS. `vintage_type` really does put two different quantities in value_mmt, and NumberQuery
          still has no field to choose between them. The card does not need one: `row_filters` emits
          `vintage_type IN ('year')` on every read and the `vintage_tiebreak` role_order ranks 'year'
          first as defence in depth. Re-measured on the canonical parquet: the year rows are UNIQUE on
          (release_month, commodity, country, marketing_year) in ALL 49,188 groups.
      (b) THE SERIES. The vintage ROW_NUMBER really does apply to every agg -- but it collapses the GRAIN,
          and `grain_cols` puts release_month IN the grain (the silver_esr week idiom). The revision
          series across circulars is therefore reachable, which is what the refusal said it could not be.
    """
    from leviathan.silver import registry as SR
    T = "silver_wap_table01_revisions"
    c = SR.load_registry().table(T)
    assert "row_label" in c["natural_key"]                       # the axis is still physically there
    assert {"vintage_type", "row_label"} <= {pc["name"] for pc in c["physical_columns"]}
    ts = _reg().get(T)
    assert T in nreg.visible_tables(_reg())                      # ...and it is now SERVED
    assert "release_month" in ts.group_cols()                    # (b): the release is part of the identity
    assert ts.metrics["value_mmt"].row_filters["wheat"] == {"vintage_type": ["year"]}   # (a): the fence
