"""WIRING WAVE-1 -- Card A (silver_noaa_iod) + Card B (silver_conab_coffee) + Card C
(silver_sagis_weekly_exports) wired into the numbers agent.

AWS-free: registry membership, build_sql shape (PIT guard + vintage/data-date collapse), and the
apply_pit_filter oracle over local fixtures. Card C landed once the catalog ALTER registered the derived
week_ending_date (DATE): it is a WIDE data_date card on that column with a conservative +5d publication lag.
"""
from __future__ import annotations

from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.agent import system_prompt
from leviathan.graphrag.numbers.registry import load_registry


# ── Card A: silver_noaa_iod (year_month, global; dmi_value + 3mo avg only) ─────────────────────────────
def test_iod_registered_year_month_metric_set():
    ts = load_registry().get("silver_noaa_iod")
    assert ts.knowledge_semantics == "year_month" and ts.year_col == "year" and ts.month_col == "month"
    assert set(ts.metrics) == {"dmi_value", "iod_dmi_3month_avg"}    # the observed index + its 3-mo mean
    assert "iod_phase" not in ts.metrics                            # string categorical -> excluded
    assert "iod_dmi_ethiopia_lag4" not in ts.metrics               # engineered feature -> excluded
    assert ts.commodity_col is None and ts.country_col is None      # global climate state


def test_iod_build_sql_year_month_guard():
    sql = Q.build_sql(Q.NumberQuery(table="silver_noaa_iod", metric="dmi_value", asof="1998-06-01",
                                    agg="latest"))
    assert "(year * 100 + month) <= 199806" in sql                 # year_month PIT guard (no CAST, no date col)
    assert "dmi_value AS value" in sql and sql.strip().endswith("LIMIT 1")


def test_iod_pit_year_month_no_leakage():
    ts = load_registry().get("silver_noaa_iod")
    rows = [{"year": 2025, "month": m, "dmi_value": 0.1 * m} for m in range(1, 13)]
    kept = Q.apply_pit_filter(rows, Q.NumberQuery(table="silver_noaa_iod", metric="dmi_value",
                                                  asof="2025-04-15"), ts)
    assert {r["month"] for r in kept} == {1, 2, 3, 4}              # May+ not yet known at mid-April


def test_iod_bullet_carries_staleness_clause():
    # SKEPTIC fold (Finding 2): the producer trims the NaN tail so agg=latest returns the LAST REAL month,
    # which can sit before a live as-of. The IOD system-prompt bullet must carry a hard staleness-visible
    # clause (mirroring the silver_cot positioning bullet) so a dated 'latest DMI' is never narrated as
    # 'current'. IOD SOURCE SWITCH (ADR_IOD_SOURCE_SWITCH, 2026-07-24): the clause SURVIVES the re-baseline
    # but its justification changes -- the old text described a DEAD HadISST reconstruction trailing "many
    # months"; the live CPC ERSSTv5 record trails by ~one publication cycle instead. The date-honesty
    # invariant is unchanged; the dead-source framing is gone (see the live-cadence test below).
    sp = system_prompt(load_registry())
    assert "silver_noaa_iod is the Indian Ocean Dipole" in sp
    iod = sp.split("silver_noaa_iod is the Indian Ocean Dipole", 1)[1].split("\n", 1)[0]
    assert "staleness must be visible" in iod                      # the hard clause, same voice as the COT bullet
    assert "current DMI" in iod                                    # explicit no-stale-as-current guard
    assert "many months" not in iod                                # the retired dead-source framing is gone


def test_iod_bullet_states_live_cadence_not_a_dead_source():
    # The re-baselined source is LIVE and monthly with a ~30-45d publication lag under a 45d SLA. The bullet
    # must say so, because the failure mode flips: with a dead source the risk was narrating a 15-month-old
    # reading as current; with a live one it is reporting the normal one-cycle lag as missing data (the
    # fabricated-unavailability class). Both guards therefore ship in the same bullet.
    sp = system_prompt(load_registry())
    iod = sp.split("silver_noaa_iod is the Indian Ocean Dipole", 1)[1].split("\n", 1)[0]
    assert "LIVE" in iod and "30-45 days" in iod                   # live cadence + the publication lag
    assert "45-day freshness SLA" in iod                           # the ratified staleness ceiling
    assert "1991-2020" in iod                                      # the anomaly basis the values are quoted on
    assert "never report a month as unavailable" in iod            # no invented unpublished-month story


def test_iod_card_text_carries_the_rebaselined_basis():
    # Card A's own description/notes (what the model reads per table) must state the new basis, the live
    # cadence + lag, the 45d SLA and the fixed climatology -- and must NOT still claim a month is "known at
    # month end", which is false under a 30-45d publication lag.
    ts = load_registry().get("silver_noaa_iod")
    text = f"{ts.description} {ts.notes}"
    assert "ERSSTv5" in text and "NOAA CPC" in text                # the new source of record
    assert "1991-2020" in text                                     # fixed climatology (ADR decision 5)
    assert "30-45" in text                                         # publication lag (EDA-PIT-002 governance)
    assert "45-day freshness SLA" in text                          # the ratified ceiling
    assert "1.55" in text and "1.28" in text                       # magnitudes RESTATED, both bases named
    assert "known at month end" not in text                        # the retired (and now false) PIT claim


# ── Card B: silver_conab_coffee (survey-vintage on the DERIVED survey_release_date) ───────────────────
def test_conab_registered_vintage_shape():
    ts = load_registry().get("silver_conab_coffee")
    assert ts.knowledge_semantics == "vintage" and ts.knowledge_date_col == "survey_release_date"
    assert ts.commodity_col == "commodity" and ts.country_col == "region"   # region repurposed as the geo axis
    assert set(ts.metrics) == {"production_thousand_bags", "area_in_production_ha", "yield_bags_per_ha"}
    assert "production_revision_thousand_bags" not in ts.metrics    # cross-survey DELTA -> excluded (D4)
    assert [t.col for t in ts.vintage_tiebreak] == ["survey_number"]
    assert ts.vintage_tiebreak[0].dir == "desc"                    # later survey wins the tie


def test_conab_build_sql_vintage_collapse_and_region_scope():
    sql = Q.build_sql(Q.NumberQuery(table="silver_conab_coffee", metric="production_thousand_bags",
                                    asof="2025-06-01", commodity="arabica_coffee", country="brazil",
                                    period="2024"))
    assert "CAST(survey_release_date AS varchar) <= '2025-06-01'" in sql   # PIT guard on the derived date
    assert "commodity = 'arabica_coffee'" in sql and "region = 'brazil'" in sql   # variety + national scope
    assert "safra_year = 2024" in sql                              # int period
    assert "ROW_NUMBER() OVER" in sql and "survey_release_date DESC" in sql   # latest-survey collapse
    assert "survey_number DESC" in sql                             # deterministic tiebreak


def test_conab_pit_latest_survey_wins():
    ts = load_registry().get("silver_conab_coffee")
    base = dict(commodity="arabica_coffee", region="brazil", safra_year=2024)
    rows = [{**base, "survey_number": n, "survey_release_date": d, "production_thousand_bags": v}
            for n, d, v in ((1, "2024-03-01", 40000.0), (2, "2024-06-01", 41000.0),
                            (3, "2024-10-01", 42000.0), (4, "2025-02-01", 42500.0))]
    q = dict(table="silver_conab_coffee", metric="production_thousand_bags", commodity="arabica_coffee",
             country="brazil", period="2024")
    mid = Q.apply_pit_filter(rows, Q.NumberQuery(asof="2024-07-01", **q), ts)
    assert len(mid) == 1 and mid[0]["survey_number"] == 2          # only S1+S2 released by Jul 2024
    late = Q.apply_pit_filter(rows, Q.NumberQuery(asof="2025-06-01", **q), ts)
    assert len(late) == 1 and late[0]["survey_number"] == 4        # all four released -> latest survey wins


# ── Card C: silver_sagis_weekly_exports (data_date on the DERIVED week_ending_date; +5d pub lag) ───────
def test_sagis_weekly_registered_data_date_shape():
    ts = load_registry().get("silver_sagis_weekly_exports")
    assert ts.knowledge_semantics == "data_date"
    assert ts.date_col == "week_ending_date" and ts.knowledge_date_col == "week_ending_date"
    assert ts.publication_lag_days == 5                             # cumulative file posts a few days after week-end
    assert ts.commodity_col == "crop" and ts.country_col is None    # national crop total -- no geo axis
    assert set(ts.metrics) == {"prog_exports_mt", "pct_of_prior_yr", "z_vs_3yr_avg"}
    assert ts.group_cols() == ["crop"]                             # agg=latest collapses per crop -> newest week


def test_sagis_weekly_build_sql_data_date_guard_and_pub_lag():
    sql = Q.build_sql(Q.NumberQuery(table="silver_sagis_weekly_exports", metric="prog_exports_mt",
                                    asof="2023-09-01", commodity="maize", agg="latest"))
    assert "CAST(week_ending_date AS varchar) <= '2023-08-27'" in sql   # data_date PIT guard, +5d lag shifts RHS back
    assert "crop = 'maize'" in sql                                 # SAGIS crop label (not a contract slug)
    assert "prog_exports_mt AS value" in sql and sql.strip().endswith("LIMIT 1")   # newest week on/before asof


def test_sagis_weekly_pit_data_date_no_leakage():
    ts = load_registry().get("silver_sagis_weekly_exports")
    rows = [{"crop": "maize", "week_number": n, "week_ending_date": d, "prog_exports_mt": v}
            for n, d, v in ((15, "2023-08-11", 194079.0), (16, "2023-08-18", 220245.0),
                            (17, "2023-08-25", 249861.0), (18, "2023-09-01", 280000.0))]
    q = dict(table="silver_sagis_weekly_exports", metric="prog_exports_mt", commodity="maize")
    kept = Q.apply_pit_filter(rows, Q.NumberQuery(asof="2023-09-01", agg="latest", **q), ts)
    # asof 2023-09-01 minus the +5d lag = 2023-08-27, so wk18 (2023-09-01) is NOT yet published; wk15-17 are.
    assert {r["week_number"] for r in kept} == {15, 16, 17}
    assert max(kept, key=lambda r: r["week_ending_date"])["week_number"] == 17   # newest published week is wk17


def test_sagis_weekly_bullet_carries_cadence_and_national_only():
    sp = system_prompt(load_registry())
    assert "silver_sagis_weekly_exports is SAGIS South-African WEEKLY cumulative grain export" in sp
    sagis = sp.split("silver_sagis_weekly_exports is SAGIS", 1)[1].split("\n", 1)[0]
    assert "staleness must be visible" in sagis                    # the COT/IOD-house cadence clause
    assert "national crop total" in sagis                          # no per-destination/grade cut
    assert "CUMULATIVE" in sagis                                   # never delta the running total vs a weekly ESR flow
