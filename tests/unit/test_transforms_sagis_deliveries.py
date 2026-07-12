"""SILVER-F042 -- SAGIS weekly producer-deliveries producer (two atomic fixes).

Covers the shared snapshot parser (filename -> season/week, publication-metadata ranking)
and the deliveries producer (authoritative selection, grade/total double-count guard,
prior-year/trailing comparisons after uniqueness with no future leakage, and the known
2011-12 x wheat x week 51 overlap).
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.transforms.bronze_to_silver.sagis_common import (
    build_snapshot,
    parse_season,
    parse_week_number,
    rank_snapshots,
    same_authority,
)
from leviathan.transforms.bronze_to_silver.sagis_deliveries import (
    DeliveryWeekRecord,
    SILVER_ARROW_SCHEMA,
    build_deliveries_silver,
    read_deliveries_xlsx,
    reconcile_grade_total,
    records_from_normalized,
    select_authoritative,
)


def _dt(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _snap(filename, published_at, crop="wheat"):
    return build_snapshot(
        s3_key=f"raw/production/source=sagis_weekly/dataset=producer_deliveries/crop={crop}/{filename}",
        filename=filename, dataset="producer_deliveries", crop=crop, published_at=published_at,
    )


def _rec(snap, week, total=None, grades=None):
    return DeliveryWeekRecord(
        snapshot=snap, season=snap.season, crop_label=snap.crop,
        week_number=week, prog_total_mt=total, grade_totals_mt=grades,
    )


# ---------------------------------------------------------------------------
# Shared parser
# ---------------------------------------------------------------------------

class TestSnapshotParser:
    @pytest.mark.parametrize("fn,exp", [
        ("ProdProgressive-Mielies_2026-2027_03.xlsx", "2026/27"),
        ("IMP-EXP_Progressive_Koring_2011_12_Week51.xls", "2011/12"),
        ("ProdProgressive_-_Sojabone_2015/16.xlsx", "2015/16"),
    ])
    def test_parse_season(self, fn, exp):
        assert parse_season(fn) == exp

    @pytest.mark.parametrize("fn,exp", [
        ("ProdProgressive-Mielies_2026-2027_03.xlsx", 3),
        ("Koring_2011_12_Week51.xls", 51),
        ("Koring_2011_12_Week_51.xls", 51),
        ("Koring_2011_12.xls", None),           # no week token
    ])
    def test_parse_week(self, fn, exp):
        assert parse_week_number(fn) == exp

    def test_ranking_by_publication_not_filename(self):
        # 'a_...' would sort first lexically, but it is published LATER -> ranks last.
        early = _snap("z_2011_12_Week10.xls", _dt(2012, 1, 1))
        late = _snap("a_2011_12_Week11.xls", _dt(2012, 1, 8))
        ranked = rank_snapshots([late, early])
        assert ranked[-1] is late   # highest authority is the later publication

    def test_missing_pub_ranks_below_real_pub(self):
        no_pub = _snap("x_2011_12_Week30.xls", None)
        with_pub = _snap("y_2011_12_Week05.xls", _dt(2012, 2, 1))
        assert rank_snapshots([with_pub, no_pub])[-1] is with_pub

    def test_same_authority(self):
        a = _snap("a_2011_12_Week51.xls", _dt(2012, 1, 1))
        b = _snap("b_2011_12_Week51.xls", _dt(2012, 1, 1))
        assert same_authority(a, b)


# ---------------------------------------------------------------------------
# Grade/total double-count guard
# ---------------------------------------------------------------------------

class TestGradeTotalGuard:
    def test_published_total_wins_and_reconciles(self):
        val, flag = reconcile_grade_total(1000.0, {"A": 600.0, "B": 405.0})
        assert val == 1000.0 and flag == "reconciled"

    def test_grade_mismatch_flagged_but_uses_total(self):
        val, flag = reconcile_grade_total(1000.0, {"A": 600.0, "B": 200.0})
        assert val == 1000.0 and flag.startswith("grade_total_mismatch")

    def test_grades_only_fallback(self):
        val, flag = reconcile_grade_total(None, {"A": 600.0, "B": 400.0})
        assert val == 1000.0 and flag == "grades_only"

    def test_never_sums_total_and_grades(self):
        # The guarantee: output is the total, NOT total + summed grades (=2005).
        val, _ = reconcile_grade_total(1005.0, {"A": 600.0, "B": 405.0})
        assert val == 1005.0

    def test_grade_record_does_not_create_separate_crop_row(self):
        # maize total + maize_grade breakdown -> ONE maize row using the published total.
        tot = _snap("ProdProgressive-Mielies_2020_21_Week10.xlsx", _dt(2021, 1, 1), crop="maize")
        grd = _snap("SWP_Grade_Per_Week_2020_21_Week10.xlsx", _dt(2021, 1, 1), crop="maize_grade")
        rows = select_authoritative([
            _rec(tot, 10, total=5000.0),
            _rec(grd, 10, grades={"B1": 3000.0, "B2": 2000.0}),
        ])
        assert len(rows) == 1
        assert rows[0]["crop"] == "maize"
        assert rows[0]["prog_total_mt"] == 5000.0   # NOT 5000 + 5000


# ---------------------------------------------------------------------------
# Authoritative selection + the 2011-12 wheat week 51 collision
# ---------------------------------------------------------------------------

class TestAuthoritativeSelection:
    def test_2011_12_wheat_week51_overlap_resolves_to_later(self):
        early = _snap("ProdProgressive-Koring_2011_12_Week51.xls", _dt(2012, 1, 1))
        revised = _snap("ProdProgressive-Koring_2011_12_Week51b.xls", _dt(2012, 1, 8))
        rows = select_authoritative([
            _rec(early, 51, total=1000.0),
            _rec(revised, 51, total=1050.0),   # a mid-season revision
        ])
        assert len(rows) == 1
        assert rows[0]["prog_total_mt"] == 1050.0   # the later-published snapshot wins

    def test_same_authority_conflict_fails_closed(self):
        a = _snap("A_2011_12_Week51.xls", _dt(2012, 1, 1))
        b = _snap("B_2011_12_Week51.xls", _dt(2012, 1, 1))   # identical authority
        with pytest.raises(ValueError, match="conflicting co-authoritative"):
            select_authoritative([_rec(a, 51, total=1000.0), _rec(b, 51, total=1050.0)])

    def test_no_natural_key_duplicates(self):
        s1 = _snap("wheat_2010_11_Week10.xls", _dt(2011, 1, 1))
        s2 = _snap("wheat_2010_11_Week11.xls", _dt(2011, 1, 8))
        df = build_deliveries_silver([_rec(s1, 10, 100.0), _rec(s2, 10, 110.0), _rec(s2, 11, 120.0)])
        assert not df.duplicated(subset=["season", "crop", "week_number"]).any()


# ---------------------------------------------------------------------------
# Comparisons after uniqueness (no future leakage)
# ---------------------------------------------------------------------------

class TestComparisons:
    def _multi_season(self):
        recs = []
        seasons = ["2010/11", "2011/12", "2012/13", "2013/14"]
        totals = {"2010/11": 100.0, "2011/12": 110.0, "2012/13": 120.0, "2013/14": 150.0}
        for i, season in enumerate(seasons):
            start = int(season.split("/")[0])
            snap = _snap(f"ProdProgressive-Koring_{start}_{str(start+1)[-2:]}_Week10.xls",
                         _dt(start + 1, 1, 1))
            recs.append(_rec(snap, 10, totals[season]))
        return recs

    def test_pct_of_prior_year(self):
        df = build_deliveries_silver(self._multi_season())
        row = df[df["season"] == "2011/12"].iloc[0]
        assert row["prior_prog_total_mt"] == pytest.approx(100.0)
        assert row["pct_of_prior_yr"] == pytest.approx(110.0)   # 110/100*100

    def test_first_season_has_null_comparisons(self):
        df = build_deliveries_silver(self._multi_season())
        row = df[df["season"] == "2010/11"].iloc[0]
        assert math.isnan(row["pct_of_prior_yr"])
        assert math.isnan(row["z_vs_3yr_avg"])

    def test_z_uses_only_prior_seasons_no_leakage(self):
        df = build_deliveries_silver(self._multi_season())
        # 2013/14 z uses prior seasons 2010/11,2011/12,2012/13 = mean 110, std ~8.165.
        row = df[df["season"] == "2013/14"].iloc[0]
        import numpy as np
        mu = np.mean([100.0, 110.0, 120.0])
        sd = np.std([100.0, 110.0, 120.0], ddof=0)
        assert row["z_vs_3yr_avg"] == pytest.approx((150.0 - mu) / sd, abs=1e-6)


# ---------------------------------------------------------------------------
# xlsx adapter + INV-2 schema
# ---------------------------------------------------------------------------

class TestXlsxAndSchema:
    def test_xlsx_roundtrip(self):
        raw = pd.DataFrame({
            "week_no": [10, 11, 12],
            "week_ending": ["2020-11-06", "2020-11-13", "2020-11-20"],
            "cumulative_tons": [1000.0, 1500.0, 2100.0],
        })
        buf = io.BytesIO()
        raw.to_excel(buf, index=False)
        snap = _snap("ProdProgressive-Koring_2020_21_Week12.xlsx", _dt(2021, 1, 1))
        recs = read_deliveries_xlsx(buf.getvalue(), snap)
        assert len(recs) == 3
        assert {r.week_number for r in recs} == {10, 11, 12}
        assert recs[0].prog_total_mt == 1000.0

    def test_records_from_normalized_skips_unkeyable(self):
        snap = _snap("ProdProgressive-Koring_2020_21_Week12.xlsx", _dt(2021, 1, 1))
        recs = records_from_normalized([{"week_number": None}, {"week_number": 5, "prog_total_mt": 9.0}], snap)
        assert len(recs) == 1 and recs[0].week_number == 5

    def test_silver_schema_matches_registry(self):
        from leviathan.silver.registry import load_registry
        target_to_pa = {"int64": pa.int64(), "float64": pa.float64(), "string": pa.string()}
        contract = load_registry().table("silver_sagis_weekly_deliveries")
        expected = {c["name"]: target_to_pa[c["target_arrow_type"]] for c in contract["physical_columns"]}
        actual = {f.name: f.type for f in SILVER_ARROW_SCHEMA}
        assert actual == expected

    def test_empty_records_returns_empty_contract(self):
        df = build_deliveries_silver([])
        assert list(df.columns) == [f.name for f in SILVER_ARROW_SCHEMA]
        assert len(df) == 0
