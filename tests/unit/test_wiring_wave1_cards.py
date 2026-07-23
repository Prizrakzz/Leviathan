"""WIRING WAVE-1 -- Card A (silver_noaa_iod) + Card B (silver_conab_coffee) wired into the numbers agent.

AWS-free: registry membership, build_sql shape (PIT guard + vintage collapse), and the apply_pit_filter
oracle over local fixtures. Card C (silver_sagis_weekly_exports) is BLOCKED this wave (the pre-step left
the served-table DDL/migration incomplete) and is deliberately NOT in the registry -- pinned here so a
future accidental wiring without the DDL is caught.
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
    # SKEPTIC fold (Finding 2): the producer trims the NaN tail so agg=latest returns the LAST REAL month --
    # which for a lagging SST reconstruction can sit many months before a live as-of (e.g. 2025-04 read at
    # 2026-07 is ~15 months old). The IOD system-prompt bullet must carry a hard staleness-visible clause
    # (mirroring the silver_cot positioning bullet) so a months-old 'latest DMI' is never narrated as 'current'.
    sp = system_prompt(load_registry())
    assert "silver_noaa_iod is the Indian Ocean Dipole" in sp
    iod = sp.split("silver_noaa_iod is the Indian Ocean Dipole", 1)[1].split("\n", 1)[0]
    assert "staleness must be visible" in iod                      # the hard clause, same voice as the COT bullet
    assert "current DMI" in iod                                    # explicit no-stale-as-current guard


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


# ── Card C: silver_sagis_weekly_exports is BLOCKED (NOT wired) ─────────────────────────────────────────
def test_sagis_weekly_exports_not_registered_this_wave():
    assert "silver_sagis_weekly_exports" not in load_registry().tables
