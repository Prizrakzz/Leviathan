"""Unit tests for the UNICA biweekly bronze-to-silver transforms.

All tests are pure in-memory — no S3 or AWS dependencies.

The fixtures in ``TestBronzeDefectRepairs`` are miniature reproductions of the
four measured bronze defects (page-window shift, comma-thousands separator,
season-calendar year, mixed-format cover stamps) plus the release-series
column-role and duplicate-stamp defects, using the real digits from the
bulletins the defects were measured on.
"""
from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.unica_biweekly import (
    CORN_ETHANOL_COLUMNS,
    MONTHLY_ETHANOL_SALES_COLUMNS,
    RELEASE_SERIES_COLUMNS,
    SEASON_HISTORY_COLUMNS,
    _repair_separator_scale,
    _resolve_fortnight_date,
    _resolve_position_date,
    transform_corn_ethanol,
    transform_monthly_ethanol_sales,
    transform_release_series,
    transform_season_history,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp_row(**kw) -> dict[str, Any]:
    """Minimal fortnight_production bronze row."""
    base: dict[str, Any] = {
        "harvest_year":    "2023_2024",
        "idm":             "100",
        "doc_type":        "biweekly_new_pt",
        "position_date":   "16/04/2023",
        "fortnight_label": "16/04",
        "fortnight_seq":   1,
        "region":          "centro_sul",
        "variable":        "cane_crushed",
        "period":          "current",
        "value":           1000.0,
        "unit":            "t",
        "ingest_date":     "2023-04-17",
    }
    base.update(kw)
    return base


def _fp_slot(seq: int = 1, region: str = "centro_sul", *, cane: float,
             sugar: float, total: float, anhydrous: float, hydrous: float,
             **kw) -> list[dict[str, Any]]:
    """A complete five-variable bronze slot (one bulletin, one region)."""
    label = {1: "16/04", 2: "01/05", 3: "16/05", 24: "01/04"}.get(seq, "16/04")
    pairs = [
        ("cane_crushed", cane), ("sugar_produced", sugar),
        ("ethanol_total", total), ("ethanol_anhydrous", anhydrous),
        ("ethanol_hydrous", hydrous),
    ]
    return [
        _fp_row(fortnight_seq=seq, fortnight_label=label, region=region,
                variable=var, value=val, **kw)
        for var, val in pairs
    ]


def _fp_region_set(seq: int = 1, *, cs: tuple, sp: tuple, **kw) -> list[dict[str, Any]]:
    """Three additive regions for one slot; ``de`` is derived as ``cs - sp``."""
    de = tuple(c - s for c, s in zip(cs, sp))
    keys = ("cane", "sugar", "total", "anhydrous", "hydrous")
    rows: list[dict[str, Any]] = []
    for region, vals in (("centro_sul", cs), ("sao_paulo", sp),
                         ("demais_estados", de)):
        rows += _fp_slot(seq=seq, region=region, **dict(zip(keys, vals)), **kw)
    return rows


def _ss_row(**kw) -> dict[str, Any]:
    """Minimal summary_snapshot bronze row."""
    base: dict[str, Any] = {
        "harvest_year":   "2023_2024",
        "idm":            "100",
        "doc_type":       "biweekly_new_pt",
        "position_date":  "16/04/2023",
        "period_type":    "accumulated",
        "region":         "centro_sul",
        "variable":       "cane_crushed",
        "current_value":  1000.0,
        "prior_value":    900.0,
        "var_pct":        11.1,
        "unit":           "t",
        "ingest_date":    "2023-04-17",
    }
    base.update(kw)
    return base


def _ss_reading(values: dict[str, tuple[float, float]], **kw) -> list[dict[str, Any]]:
    """One Tabela 1 reading: ``{variable: (current, prior)}``."""
    return [
        _ss_row(variable=var, current_value=cur, prior_value=pri, **kw)
        for var, (cur, pri) in values.items()
    ]


# A well-formed Tabela 1 reading (values in the PDF's published thousands).
_GOOD_SNAPSHOT = {
    "cane_crushed":      (16598.0, 16117.0),
    "sugar_produced":    (731.0, 722.0),
    "ethanol_anhydrous": (179.0, 145.0),
    "ethanol_hydrous":   (739.0, 679.0),
    "ethanol_total":     (918.0, 824.0),
}

# The SAME reading as the bronze extractor emits it when Tabela 1 carries an
# extra header row: every figure lands one variable further down the list and
# ethanol_total is pushed off the end.  Digits are from pdf_1ccd91c7bb852ef4.
_SHIFTED_SNAPSHOT = {
    "cane_crushed":      (float("nan"), float("nan")),
    "sugar_produced":    (524957.0, 539980.0),
    "ethanol_anhydrous": (36016.0, 35698.0),
    "ethanol_hydrous":   (9412.0, 9819.0),
    "ethanol_total":     (15623.0, 17463.0),
}


def _scaled_snapshot(frac: float) -> dict[str, tuple[float, float]]:
    """A share of the good reading, kept whole and internally consistent.

    UNICA never prints fractions, so a fractional figure is itself the
    mis-read-separator tell; and ``total`` is recomputed from the rounded legs
    so the reading still satisfies the identity it is published under.
    """
    out = {k: (float(round(v[0] * frac)), float(round(v[1] * frac)))
           for k, v in _GOOD_SNAPSHOT.items()}
    out["ethanol_total"] = tuple(
        out["ethanol_anhydrous"][i] + out["ethanol_hydrous"][i] for i in (0, 1)
    )
    return out


def _ce_row(**kw) -> dict[str, Any]:
    """Minimal corn_ethanol bronze row."""
    base: dict[str, Any] = {
        "harvest_year":          "2023_2024",
        "idm":                   "100",
        "doc_type":              "biweekly_new_pt",
        "position_date":         "16/04/2023",
        "fortnight_label":       "16/04",
        "fortnight_seq":         1,
        "anhydrous_quinzenal_kl": 50.0,
        "hydrous_quinzenal_kl":   30.0,
        "total_quinzenal_kl":     80.0,
        "anhydrous_accum_kl":    50.0,
        "hydrous_accum_kl":      30.0,
        "total_accum_kl":        80.0,
        "ingest_date":           "2023-04-17",
    }
    base.update(kw)
    return base


def _me_row(**kw) -> dict[str, Any]:
    """Minimal monthly_ethanol_sales bronze row."""
    base: dict[str, Any] = {
        "harvest_year":       "2023_2024",
        "idm":                "100",
        "doc_type":           "biweekly_new_pt",
        "position_date":      "16/04/2023",
        "month_label":        "April",
        "month_num":          4,
        "is_partial":         True,
        "total_current_m3":   1000.0,
        "total_prior_m3":     900.0,
        "external_current_m3": 400.0,
        "external_prior_m3":   360.0,
        "internal_current_m3": 600.0,
        "internal_prior_m3":   540.0,
        "ingest_date":        "2023-04-17",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# TestResolveFortnight
# ---------------------------------------------------------------------------

class TestResolveFortnight:
    def test_april_16_maps_to_year_start(self):
        assert _resolve_fortnight_date("16/04", "2023_2024") == datetime.date(2023, 4, 16)

    def test_january_maps_to_year_end(self):
        assert _resolve_fortnight_date("16/01", "2023_2024") == datetime.date(2024, 1, 16)

    def test_none_label_returns_none(self):
        assert _resolve_fortnight_date(None, "2023_2024") is None

    def test_invalid_harvest_year_returns_none(self):
        assert _resolve_fortnight_date("16/04", "invalid") is None

    def test_december_maps_to_year_start(self):
        assert _resolve_fortnight_date("16/12", "2023_2024") == datetime.date(2023, 12, 16)

    def test_march_maps_to_year_end(self):
        assert _resolve_fortnight_date("16/03", "2023_2024") == datetime.date(2024, 3, 16)

    def test_closing_april_maps_to_year_end(self):
        """DEFECT 3: 01/04 CLOSES the season and belongs to the end year.

        Resolving by month alone stamps it with the start year, placing the
        season's last position a year before its first.
        """
        assert _resolve_fortnight_date("01/04", "2024_2025") == datetime.date(2025, 4, 1)

    def test_both_aprils_disambiguated(self):
        opening = _resolve_fortnight_date("16/04", "2024_2025")
        closing = _resolve_fortnight_date("01/04", "2024_2025")
        assert opening == datetime.date(2024, 4, 16)
        assert closing == datetime.date(2025, 4, 1)
        assert opening < closing

    def test_sequence_resolves_without_label(self):
        assert _resolve_fortnight_date(None, "2024_2025", 24) == datetime.date(2025, 4, 1)
        assert _resolve_fortnight_date(None, "2024_2025", 1) == datetime.date(2024, 4, 16)

    def test_label_contradicting_sequence_is_refused(self):
        assert _resolve_fortnight_date("16/04", "2024_2025", 24) is None

    def test_whole_season_calendar_is_strictly_increasing(self):
        dates = [_resolve_fortnight_date(None, "2024_2025", s) for s in range(1, 25)]
        assert all(d is not None for d in dates)
        assert dates == sorted(dates)
        assert len(set(dates)) == 24


class TestResolvePositionDate:
    def test_valid_ddmmyyyy(self):
        assert _resolve_position_date("16/04/2023") == datetime.date(2023, 4, 16)

    def test_none_returns_none(self):
        assert _resolve_position_date(None) is None

    def test_invalid_returns_none(self):
        assert _resolve_position_date("not-a-date") is None

    def test_unambiguous_mmddyyyy_resolves_structurally(self):
        """DEFECT 4: '10/16/2025' has no 16th month -- only MM/DD reads."""
        assert _resolve_position_date("10/16/2025") == datetime.date(2025, 10, 16)

    def test_ambiguous_stamp_uses_document_language(self):
        assert _resolve_position_date("05/01/2024", "biweekly_new_en") == datetime.date(2024, 5, 1)
        assert _resolve_position_date("05/01/2024", "biweekly_new_pt") == datetime.date(2024, 1, 5)

    def test_iso_input_round_trips(self):
        assert _resolve_position_date("2025-10-16") == datetime.date(2025, 10, 16)


class TestSeparatorScaleRepair:
    """DEFECT 2: pt-BR parsing of an English comma-thousands number."""

    def test_three_decimals_restored(self):
        assert _repair_separator_scale(12.151) == 12151.0
        assert _repair_separator_scale(394.383) == 394383.0

    def test_whole_numbers_untouched(self):
        assert _repair_separator_scale(233958078.0) == 233958078.0
        assert _repair_separator_scale(123.0) == 123.0

    def test_none_and_nan_pass_through(self):
        assert _repair_separator_scale(None) is None
        assert pd.isna(_repair_separator_scale(float("nan")))

    def test_identity_survives_the_repair(self):
        anh, hyd, tot = (_repair_separator_scale(v) for v in (12.151, 382.232, 394.383))
        assert anh + hyd == tot


# ---------------------------------------------------------------------------
# TestTransformSeasonHistory
# ---------------------------------------------------------------------------

class TestTransformSeasonHistory:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_dedup_keeps_latest_position_date(self):
        """When two bulletins report the same slot, latest position_date wins."""
        rows = (
            _fp_slot(idm="100", position_date="16/04/2023",
                     cane=1000.0, sugar=100.0, total=80.0, anhydrous=30.0, hydrous=50.0)
            + _fp_slot(idm="200", position_date="01/05/2023",
                       cane=2000.0, sugar=200.0, total=160.0, anhydrous=60.0, hydrous=100.0)
        )
        df = transform_season_history(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["cane_crushed_t"] == 2000.0
        assert df.iloc[0]["source_idm"] == "200"

    def test_prior_rows_excluded(self):
        """Rows with period='prior' must not appear in the output."""
        rows = _fp_slot(cane=1000.0, sugar=100.0, total=80.0,
                        anhydrous=30.0, hydrous=50.0)
        rows += [_fp_row(period="prior", value=999.0)]
        df = transform_season_history(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["cane_crushed_t"] == 1000.0

    def test_pivot_column_names_with_units(self):
        """Output must have unit-suffixed column names."""
        rows = _fp_slot(cane=1000.0, sugar=100.0, total=80.0,
                        anhydrous=30.0, hydrous=50.0)
        df = transform_season_history(self._build_df(rows))
        for col in ["cane_crushed_t", "sugar_produced_t", "ethanol_total_m3",
                    "ethanol_anhydrous_m3", "ethanol_hydrous_m3"]:
            assert col in df.columns, f"Expected column '{col}' not found"

    def test_fortnight_date_populated(self):
        rows = _fp_slot(cane=1000.0, sugar=100.0, total=80.0,
                        anhydrous=30.0, hydrous=50.0)
        df = transform_season_history(self._build_df(rows))
        assert df.iloc[0]["fortnight_date"] == datetime.date(2023, 4, 16)

    def test_output_columns_match_schema(self):
        rows = _fp_slot(cane=1000.0, sugar=100.0, total=80.0,
                        anhydrous=30.0, hydrous=50.0)
        df = transform_season_history(self._build_df(rows))
        assert list(df.columns) == SEASON_HISTORY_COLUMNS

    def test_sort_order(self):
        """Output is sorted by (harvest_year, region, fortnight_seq)."""
        rows: list[dict[str, Any]] = []
        for hy, seq in (("2022_2023", 2), ("2022_2023", 1), ("2023_2024", 1)):
            rows += _fp_slot(seq=seq, harvest_year=hy, cane=1000.0 * seq,
                             sugar=100.0, total=80.0, anhydrous=30.0, hydrous=50.0)
        df = transform_season_history(self._build_df(rows))
        tuples = list(zip(df["harvest_year"], df["region"], df["fortnight_seq"]))
        assert tuples == sorted(tuples)

    def test_source_position_date_is_iso(self):
        rows = _fp_slot(position_date="16/04/2023", cane=1000.0, sugar=100.0,
                        total=80.0, anhydrous=30.0, hydrous=50.0)
        df = transform_season_history(self._build_df(rows))
        assert df.iloc[0]["source_position_date"] == "2023-04-16"

    def test_a_row_never_mixes_bulletins(self):
        """A slot's five metrics all come from ONE bulletin.

        The old per-variable dedup let a revised cane figure sit beside an
        older ethanol split, breaking the identity and making source_idm a
        claim the row could not support.
        """
        rows = (
            _fp_slot(idm="old", position_date="16/04/2023",
                     cane=1000.0, sugar=100.0, total=80.0, anhydrous=30.0, hydrous=50.0)
            + _fp_slot(idm="new", position_date="01/05/2023",
                       cane=1100.0, sugar=110.0, total=90.0, anhydrous=35.0, hydrous=55.0)
        )
        df = transform_season_history(self._build_df(rows))
        assert len(df) == 1
        row = df.iloc[0]
        assert row["source_idm"] == "new"
        assert (row["cane_crushed_t"], row["ethanol_anhydrous_m3"]) == (1100.0, 35.0)
        assert row["ethanol_anhydrous_m3"] + row["ethanol_hydrous_m3"] == row["ethanol_total_m3"]


class TestBronzeDefectRepairs:
    """The four measured bronze defects, reproduced and repaired."""

    def _shifted_bulletin(self) -> list[dict[str, Any]]:
        """DEFECT 1: a one-page history-window shift (pdf_ee049e5f1f5e08d0).

        Every metric is bound to the NEXT variable name: the sugar column holds
        cane, the total column holds sugar, and so on, while cane collects a
        stray fragment and the real hydrous figure is pushed out of the window.
        """
        rows: list[dict[str, Any]] = []
        # centro_sul, seq 1-2 are the real 2022/23 digits; 3-7 continue the
        # accumulation so the stray fragment is the minority it is in the PDF.
        truth = {
            1: (5287706.0, 131347.0, 394383.0, 12151.0, 382232.0),
            2: (29302034.0, 1065621.0, 1495450.0, 242907.0, 1252543.0),
            3: (55000000.0, 2100000.0, 2600000.0, 420000.0, 2180000.0),
            4: (82000000.0, 3300000.0, 3900000.0, 640000.0, 3260000.0),
            5: (110000000.0, 4600000.0, 5300000.0, 880000.0, 4420000.0),
            6: (140000000.0, 6000000.0, 6800000.0, 1140000.0, 5660000.0),
            7: (233958078.0, 12660513.0, 11250416.0, 4167730.0, 7082686.0),
        }
        order = ["cane_crushed", "sugar_produced", "ethanol_total",
                 "ethanol_anhydrous", "ethanol_hydrous"]
        labels = {1: "16/04", 2: "01/05", 3: "16/05"}
        for seq, vals in truth.items():
            # shift: truth[i] is published under order[i + 1]
            for i, v in enumerate(vals[:-1]):
                rows.append(_fp_row(
                    harvest_year="2022_2023", idm="pdf_shift1",
                    position_date="16/07/2022", fortnight_seq=seq,
                    fortnight_label=labels.get(seq), variable=order[i + 1], value=v,
                ))
        # the stray fragment the window picked up before the real block
        rows.append(_fp_row(
            harvest_year="2022_2023", idm="pdf_shift1", position_date="16/07/2022",
            fortnight_seq=1, fortnight_label="16/04",
            variable="cane_crushed", value=233958.0,
        ))
        return rows

    def test_defect1_page_shift_is_detected_and_relabelled(self):
        df = transform_season_history(pd.DataFrame(self._shifted_bulletin()))
        assert len(df) == 7
        first = df[df.fortnight_seq == 1].iloc[0]
        assert first["cane_crushed_t"] == 5287706.0
        assert first["sugar_produced_t"] == 131347.0
        assert first["ethanol_total_m3"] == 394383.0
        assert first["ethanol_anhydrous_m3"] == 12151.0

    def test_defect1_truncated_hydrous_is_derived_from_the_identity(self):
        df = transform_season_history(pd.DataFrame(self._shifted_bulletin()))
        first = df[df.fortnight_seq == 1].iloc[0]
        # UNICA defines total = anhydrous + hydrous, so the lost leg is exact.
        assert first["ethanol_hydrous_m3"] == 382232.0
        assert (first["ethanol_anhydrous_m3"] + first["ethanol_hydrous_m3"]
                == first["ethanol_total_m3"])

    def test_defect1_stray_fragment_is_discarded(self):
        """The value the shifted window collected under 'cane_crushed' is not
        a measurement and must not survive as one."""
        df = transform_season_history(pd.DataFrame(self._shifted_bulletin()))
        assert 233958.0 not in set(df["cane_crushed_t"])

    def test_defect1_two_page_shift_leaves_the_ethanol_split_null(self):
        """A two-page shift truncates BOTH ethanol legs -- they are not
        recoverable and must be published as null, never guessed."""
        order = ["cane_crushed", "sugar_produced", "ethanol_total",
                 "ethanol_anhydrous", "ethanol_hydrous"]
        truth = [(18078715.0, 874723.0, 617662.0), (40950372.0, 2243638.0, 1374393.0)]
        rows: list[dict[str, Any]] = []
        for seq, vals in enumerate(truth, start=1):
            for i, v in enumerate(vals):
                rows.append(_fp_row(
                    harvest_year="2012_2013", idm="pdf_shift2", doc_type="biweekly_old_pt",
                    position_date="01/02/2013", fortnight_seq=seq,
                    fortnight_label={1: "16/04", 2: "01/05"}[seq],
                    region="sao_paulo", variable=order[i + 2], value=v,
                ))
        df = transform_season_history(pd.DataFrame(rows))
        assert len(df) == 2
        first = df[df.fortnight_seq == 1].iloc[0]
        assert first["cane_crushed_t"] == 18078715.0
        assert first["sugar_produced_t"] == 874723.0
        # The published aggregate survives; only the split is unrecoverable.
        assert first["ethanol_total_m3"] == 617662.0
        assert pd.isna(first["ethanol_anhydrous_m3"])
        assert pd.isna(first["ethanol_hydrous_m3"])

    def test_defect2_thousands_separator_repaired_in_season_history(self):
        rows = _fp_slot(harvest_year="2022_2023", idm="pdf_en", region="sao_paulo",
                        cane=5287.706, sugar=131.347, total=394.383,
                        anhydrous=12.151, hydrous=382.232)
        df = transform_season_history(pd.DataFrame(rows))
        row = df.iloc[0]
        assert row["cane_crushed_t"] == 5287706.0
        assert row["ethanol_anhydrous_m3"] == 12151.0
        assert row["ethanol_hydrous_m3"] == 382232.0

    def test_defect2_thousands_separator_repaired_in_corn(self):
        """21 of 86 corn rows were exactly 1000x too small."""
        rows = [_ce_row(idm="pdf_ccb21ce8c5241dfc", doc_type="biweekly_new_en",
                        position_date="09/01/2022", fortnight_seq=3,
                        fortnight_label="16/05",
                        anhydrous_quinzenal_kl=43.833, hydrous_quinzenal_kl=114.766,
                        total_quinzenal_kl=158.599, anhydrous_accum_kl=87.048,
                        hydrous_accum_kl=352.542, total_accum_kl=439.590)]
        df = transform_corn_ethanol(pd.DataFrame(rows))
        row = df.iloc[0]
        assert row["anhydrous_quinzenal_kl"] == 43833.0
        assert row["hydrous_quinzenal_kl"] == 114766.0
        assert row["total_quinzenal_kl"] == 158599.0
        assert (row["anhydrous_quinzenal_kl"] + row["hydrous_quinzenal_kl"]
                == row["total_quinzenal_kl"])

    def test_defect3_season_closing_april_not_stamped_a_year_early(self):
        rows = [_ce_row(harvest_year="2024_2025", fortnight_seq=24,
                        fortnight_label="01/04", position_date="31/03/2025")]
        df = transform_corn_ethanol(pd.DataFrame(rows))
        assert df.iloc[0]["fortnight_date"] == datetime.date(2025, 4, 1)

    def test_defect3_positions_strictly_increase_across_the_season(self):
        rows = [
            _ce_row(harvest_year="2024_2025", fortnight_seq=s,
                    fortnight_label=lbl, position_date="31/03/2025")
            for s, lbl in ((1, "16/04"), (23, "16/03"), (24, "01/04"))
        ]
        df = transform_corn_ethanol(pd.DataFrame(rows)).sort_values("fortnight_seq")
        dates = list(df["fortnight_date"])
        assert dates == sorted(dates)
        assert len(set(dates)) == len(dates)

    def test_defect4_mixed_format_stamps_all_normalise_to_iso(self):
        rows = [
            _ce_row(idm="a", doc_type="biweekly_new_pt", position_date="16/10/2025",
                    harvest_year="2025_2026", fortnight_seq=1),
            _ce_row(idm="b", doc_type="biweekly_new_en", position_date="10/16/2025",
                    harvest_year="2025_2026", fortnight_seq=2, fortnight_label="01/05"),
            _ce_row(idm="c", doc_type="biweekly_new_en", position_date="04/16/2014",
                    harvest_year="2014_2015", fortnight_seq=1),
        ]
        df = transform_corn_ethanol(pd.DataFrame(rows))
        stamps = set(df["source_position_date"])
        assert stamps == {"2025-10-16", "2014-04-16"}
        assert all(datetime.date.fromisoformat(s) for s in stamps)

    def test_negative_production_voids_the_ethanol_triple(self):
        """Accumulated production cannot run negative; the reading is refused
        rather than published, and the cane/sugar legs survive."""
        rows = _fp_region_set(cs=(5287706.0, 131347.0, 394383.0, 12151.0, 382232.0),
                              sp=(1645300.0, 38221.0, 69113.0, 37733.0, 31380.0))
        df = transform_season_history(pd.DataFrame(rows))
        assert len(df) == 3
        assert df["cane_crushed_t"].notna().all()
        assert df["ethanol_anhydrous_m3"].isna().all()
        assert (df[["cane_crushed_t", "sugar_produced_t"]] >= 0).all().all()

    def test_unverifiable_orphan_reading_is_refused(self):
        """A lone metric on a lone region exercises no invariant, so there is
        no way to tell a measurement from a mis-read fragment -- refuse it."""
        rows = [_fp_row(harvest_year="2014_2015", idm="pdf_orphan",
                        doc_type="biweekly_new_en", position_date="04/16/2014",
                        region="demais_estados", variable="cane_crushed", value=368.0)]
        df = transform_season_history(pd.DataFrame(rows))
        assert df.empty

    def test_a_complete_clean_bulletin_beats_a_repaired_one(self):
        """Ranking is (measured metrics desc, vintage desc): a derived leg
        never displaces a measured one."""
        clean = _fp_slot(idm="clean", position_date="16/04/2023",
                         cane=1000.0, sugar=100.0, total=80.0,
                         anhydrous=30.0, hydrous=50.0)
        shifted: list[dict[str, Any]] = []
        order = ["cane_crushed", "sugar_produced", "ethanol_total",
                 "ethanol_anhydrous", "ethanol_hydrous"]
        for i, v in enumerate([1000.0, 100.0, 80.0, 30.0]):
            shifted.append(_fp_row(idm="shifted", position_date="01/05/2023",
                                   variable=order[i + 1], value=v))
        df = transform_season_history(pd.DataFrame(clean + shifted))
        assert len(df) == 1
        assert df.iloc[0]["source_idm"] == "clean"


class TestSeasonHistoryInvariants:
    """The acceptance identities, asserted on transform output."""

    def _multi_season_frame(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for seq, (cs, sp) in enumerate([
            ((5287706.0, 131347.0, 394383.0, 12151.0, 382232.0),
             (3000000.0, 80000.0, 200000.0, 6000.0, 194000.0)),
            ((29302034.0, 1065621.0, 1495450.0, 242907.0, 1252543.0),
             (16000000.0, 600000.0, 800000.0, 130000.0, 670000.0)),
        ], start=1):
            rows += _fp_region_set(seq=seq, cs=cs, sp=sp,
                                   harvest_year="2022_2023", idm="b1",
                                   position_date="01/05/2022")
        return pd.DataFrame(rows)

    def test_ethanol_identity_holds_on_every_row(self):
        df = transform_season_history(self._multi_season_frame())
        a, h, t = (df.ethanol_anhydrous_m3, df.ethanol_hydrous_m3, df.ethanol_total_m3)
        assert (a + h == t).all()

    def test_regional_additivity_holds(self):
        df = transform_season_history(self._multi_season_frame())
        piv = df.pivot_table(index="fortnight_seq", columns="region",
                             values="cane_crushed_t", aggfunc="first")
        assert (piv["centro_sul"] == piv["sao_paulo"] + piv["demais_estados"]).all()

    def test_no_negative_metric_values(self):
        df = transform_season_history(self._multi_season_frame())
        metrics = ["cane_crushed_t", "sugar_produced_t", "ethanol_total_m3",
                   "ethanol_anhydrous_m3", "ethanol_hydrous_m3"]
        assert not (df[metrics] < 0).any().any()

    def test_ethanol_triple_is_never_partial(self):
        df = transform_season_history(self._multi_season_frame())
        triple = df[["ethanol_total_m3", "ethanol_anhydrous_m3", "ethanol_hydrous_m3"]]
        assert not (triple.notna().any(axis=1) & triple.isna().any(axis=1)).any()

    def test_fortnight_dates_lie_inside_the_season_window(self):
        df = transform_season_history(self._multi_season_frame())
        for _, r in df.iterrows():
            y0, y1 = (int(x) for x in r["harvest_year"].split("_"))
            assert datetime.date(y0, 4, 1) <= r["fortnight_date"] <= datetime.date(y1, 4, 30)


# ---------------------------------------------------------------------------
# TestTransformReleaseSeries
# ---------------------------------------------------------------------------

class TestTransformReleaseSeries:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_accumulated_filter(self):
        """Only 'accumulated' period_type rows are included."""
        rows = (_ss_reading(_GOOD_SNAPSHOT, period_type="accumulated")
                + _ss_reading(_GOOD_SNAPSHOT, period_type="fortnightly"))
        df = transform_release_series(self._build_df(rows))
        assert len(df) == 1

    def test_double_ingestion_dedup(self):
        """Duplicate (harvest_year, position_date, region) kept once."""
        rows = _ss_reading(_GOOD_SNAPSHOT) + _ss_reading(_GOOD_SNAPSHOT)
        df = transform_release_series(self._build_df(rows))
        assert len(df) == 1

    def test_both_current_and_prior_in_output(self):
        df = transform_release_series(self._build_df(_ss_reading(_GOOD_SNAPSHOT)))
        assert "cane_crushed_current_t" in df.columns
        assert "cane_crushed_prior_t" in df.columns

    def test_output_columns_match_schema(self):
        df = transform_release_series(self._build_df(_ss_reading(_GOOD_SNAPSHOT)))
        assert list(df.columns) == RELEASE_SERIES_COLUMNS

    def test_sort_order(self):
        rows = (_ss_reading(_GOOD_SNAPSHOT, position_date="01/05/2023", idm="b")
                + _ss_reading(_GOOD_SNAPSHOT, position_date="16/04/2023", idm="a"))
        df = transform_release_series(self._build_df(rows))
        assert list(df["position_date"]) == sorted(df["position_date"])

    def test_values_scaled_to_the_units_the_columns_name(self):
        """Tabela 1 publishes THOUSANDS of tonnes; the columns are named for
        whole tonnes."""
        df = transform_release_series(self._build_df(_ss_reading(_GOOD_SNAPSHOT)))
        assert df.iloc[0]["cane_crushed_current_t"] == 16598000.0
        assert df.iloc[0]["cane_crushed_prior_t"] == 16117000.0

    def test_position_date_is_a_resolved_iso_date(self):
        """The stamp is resolved to a real calendar date and rendered ISO, so
        the as-of comparison this column feeds is chronological."""
        df = transform_release_series(self._build_df(_ss_reading(_GOOD_SNAPSHOT)))
        assert df.iloc[0]["position_date"] == "2023-04-16"
        assert datetime.date.fromisoformat(df.iloc[0]["position_date"])

    def test_row_binding_shift_is_detected_and_repaired(self):
        """The shifted reading must land on the same figures the season
        history reports for that bulletin (pdf_1ccd91c7bb852ef4, 16/10/2025)."""
        rows = _ss_reading(_SHIFTED_SNAPSHOT, harvest_year="2025_2026",
                           position_date="16/10/2025")
        df = transform_release_series(self._build_df(rows))
        row = df.iloc[0]
        assert row["cane_crushed_current_t"] == 524957000.0
        assert row["sugar_produced_current_t"] == 36016000.0
        assert row["ethanol_anhydrous_current_m3"] == 9412000.0
        assert row["ethanol_hydrous_current_m3"] == 15623000.0
        # ethanol_total was pushed off the end -- recovered from the identity.
        assert row["ethanol_total_current_m3"] == 25035000.0

    def test_day_month_swapped_duplicate_collapses_to_one_row(self):
        """DEFECT 4/5: the same release ingested twice -- once under a pt
        DD/MM cover stamp and once under its English MM/DD twin at a
        thousandth of the scale -- is one release, not two."""
        pt = _ss_reading(_SHIFTED_SNAPSHOT, harvest_year="2025_2026",
                         idm="pt", doc_type="biweekly_new_pt",
                         position_date="16/10/2025")
        en = _ss_reading(
            {k: (v[0] / 1000.0, v[1] / 1000.0) for k, v in _SHIFTED_SNAPSHOT.items()},
            harvest_year="2025_2026", idm="en", doc_type="biweekly_new_en",
            position_date="10/16/2025",
        )
        df = transform_release_series(self._build_df(pt + en))
        assert len(df) == 1
        assert df.iloc[0]["position_date"] == "2025-10-16"
        assert df.iloc[0]["cane_crushed_current_t"] == 524957000.0

    def test_lexicographic_ordering_no_longer_misreads_the_series(self):
        """Under the old free-text stamps '05/01/2024' sorted before
        '16/04/2023'; as real dates the order is chronological."""
        rows = (_ss_reading(_GOOD_SNAPSHOT, idm="a", position_date="16/04/2023")
                + _ss_reading(_GOOD_SNAPSHOT, idm="b", doc_type="biweekly_new_en",
                              position_date="05/01/2024"))
        df = transform_release_series(self._build_df(rows)).sort_values("position_date")
        # ISO text sorts identically to the underlying dates -- which the raw
        # DD/MM/YYYY stamps did not ('05/01/2024' sorted before '16/04/2023').
        assert list(df["position_date"]) == ["2023-04-16", "2024-05-01"]

    def test_identity_holds_on_every_published_row(self):
        rows = (_ss_reading(_GOOD_SNAPSHOT, idm="a")
                + _ss_reading(_SHIFTED_SNAPSHOT, idm="b", harvest_year="2025_2026",
                              position_date="16/10/2025"))
        df = transform_release_series(self._build_df(rows))
        assert len(df) == 2
        a, h, t = (df.ethanol_anhydrous_current_m3, df.ethanol_hydrous_current_m3,
                   df.ethanol_total_current_m3)
        assert (a + h == t).all()

    def test_unreconcilable_reading_is_refused(self):
        """Neither well-formed nor a recognisable shift -- not published."""
        broken = dict(_GOOD_SNAPSHOT)
        broken["ethanol_total"] = (99999.0, 99999.0)   # identity fails
        broken["cane_crushed"] = (float("nan"), float("nan"))
        df = transform_release_series(self._build_df(_ss_reading(broken)))
        assert df.empty

    def test_regional_split_that_does_not_reconcile_is_dropped(self):
        """centro_sul survives alone; a split that does not add up is not
        published as if it did."""
        rows = _ss_reading(_GOOD_SNAPSHOT, region="centro_sul")
        rows += _ss_reading(_scaled_snapshot(0.4), region="sao_paulo")
        rows += _ss_reading(_scaled_snapshot(0.9), region="demais_estados")
        df = transform_release_series(self._build_df(rows))
        assert list(df["region"]) == ["centro_sul"]

    def test_reconciling_regional_split_is_kept(self):
        rows = _ss_reading(_GOOD_SNAPSHOT, region="centro_sul")
        rows += _ss_reading(_scaled_snapshot(0.6), region="sao_paulo")
        rows += _ss_reading(_scaled_snapshot(0.4), region="demais_estados")
        df = transform_release_series(self._build_df(rows))
        assert set(df["region"]) == {"centro_sul", "sao_paulo", "demais_estados"}


# ---------------------------------------------------------------------------
# TestTransformCornEthanol
# ---------------------------------------------------------------------------

class TestTransformCornEthanol:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_dedup_keeps_latest_position_date(self):
        rows = [
            _ce_row(idm="100", position_date="16/04/2023", total_quinzenal_kl=80.0),
            _ce_row(idm="200", position_date="01/05/2023", anhydrous_quinzenal_kl=60.0,
                    hydrous_quinzenal_kl=30.0, total_quinzenal_kl=90.0),
        ]
        df = transform_corn_ethanol(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_quinzenal_kl"] == 90.0

    def test_fortnight_date_populated(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        assert df.iloc[0]["fortnight_date"] == datetime.date(2023, 4, 16)

    def test_all_six_value_cols_preserved(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        for col in ["anhydrous_quinzenal_kl", "hydrous_quinzenal_kl", "total_quinzenal_kl",
                    "anhydrous_accum_kl", "hydrous_accum_kl", "total_accum_kl"]:
            assert col in df.columns

    def test_output_columns_match_schema(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        assert list(df.columns) == CORN_ETHANOL_COLUMNS

    def test_more_complete_reading_wins_over_a_later_partial_one(self):
        rows = [
            _ce_row(idm="full", position_date="16/04/2023"),
            _ce_row(idm="partial", position_date="01/05/2023",
                    anhydrous_accum_kl=None, hydrous_accum_kl=None,
                    total_accum_kl=None),
        ]
        df = transform_corn_ethanol(self._build_df(rows))
        assert df.iloc[0]["source_idm"] == "full"

    def test_identity_holds_on_output(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        row = df.iloc[0]
        assert (row["anhydrous_quinzenal_kl"] + row["hydrous_quinzenal_kl"]
                == row["total_quinzenal_kl"])
        assert (row["anhydrous_accum_kl"] + row["hydrous_accum_kl"]
                == row["total_accum_kl"])

    def test_negative_value_voids_its_triple(self):
        df = transform_corn_ethanol(self._build_df([
            _ce_row(anhydrous_quinzenal_kl=-5.0)
        ]))
        assert df[["anhydrous_quinzenal_kl", "hydrous_quinzenal_kl",
                   "total_quinzenal_kl"]].isna().all().all()
        # The accumulated triple is untouched.
        assert df.iloc[0]["total_accum_kl"] == 80.0


# ---------------------------------------------------------------------------
# TestTransformMonthlyEthanol
# ---------------------------------------------------------------------------

class TestTransformMonthlyEthanol:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_is_partial_false_preferred(self):
        """A final reading (is_partial=False) beats an earlier partial one."""
        rows = [
            _me_row(idm="100", position_date="16/04/2023", is_partial=True,
                    total_current_m3=500.0),
            _me_row(idm="200", position_date="01/05/2023", is_partial=False,
                    total_current_m3=1000.0),
        ]
        df = transform_monthly_ethanol_sales(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_current_m3"] == 1000.0

    def test_partial_preferred_over_older_final_when_same_month(self):
        """Later partial beats older final in same month."""
        rows = [
            _me_row(idm="100", position_date="01/04/2023", is_partial=False,
                    total_current_m3=800.0),
            _me_row(idm="200", position_date="30/04/2023", is_partial=False,
                    total_current_m3=900.0),
        ]
        df = transform_monthly_ethanol_sales(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_current_m3"] == 900.0

    def test_month_date_april_uses_year_start(self):
        df = transform_monthly_ethanol_sales(self._build_df([
            _me_row(harvest_year="2023_2024", month_num=4)
        ]))
        assert df.iloc[0]["month_date"] == "2023-04-01"

    def test_month_date_january_uses_year_end(self):
        df = transform_monthly_ethanol_sales(self._build_df([
            _me_row(harvest_year="2023_2024", month_num=1)
        ]))
        assert df.iloc[0]["month_date"] == "2024-01-01"

    def test_prior_values_preserved(self):
        row = _me_row(total_current_m3=1000.0, total_prior_m3=900.0)
        df = transform_monthly_ethanol_sales(self._build_df([row]))
        assert df.iloc[0]["total_prior_m3"] == 900.0

    def test_empty_input_returns_empty_with_correct_columns(self):
        df = transform_monthly_ethanol_sales(pd.DataFrame(columns=[
            "harvest_year", "idm", "month_num", "month_label",
            "is_partial", "position_date", "ingest_date",
            "total_current_m3", "total_prior_m3",
            "external_current_m3", "external_prior_m3",
            "internal_current_m3", "internal_prior_m3",
        ]))
        assert len(df) == 0
        for col in MONTHLY_ETHANOL_SALES_COLUMNS:
            assert col in df.columns

    def test_output_columns_match_schema(self):
        df = transform_monthly_ethanol_sales(self._build_df([_me_row()]))
        assert list(df.columns) == MONTHLY_ETHANOL_SALES_COLUMNS

    def test_source_position_date_is_iso(self):
        df = transform_monthly_ethanol_sales(self._build_df([
            _me_row(doc_type="biweekly_new_en", position_date="10/16/2025")
        ]))
        assert df.iloc[0]["source_position_date"] == "2025-10-16"


class TestMonthlySalesSkeletonRows:
    """DEFECT 5: an unreported month arrives as a labelled row with no figures.

    Every bulletin lists all twelve months of the season, so a month UNICA has
    not published yet still produces a bronze row.  Ranking on recency alone
    handed whole seasons (all of 2025, May-Nov 2022) to whichever empty
    skeleton happened to be stamped latest.
    """

    def _empty(self, **kw) -> dict[str, Any]:
        blank = {c: None for c in ["total_current_m3", "total_prior_m3",
                                   "external_current_m3", "external_prior_m3",
                                   "internal_current_m3", "internal_prior_m3"]}
        return _me_row(**blank, **kw)

    def test_empty_skeleton_never_beats_a_populated_reading(self):
        rows = [
            _me_row(idm="early", position_date="16/04/2025", harvest_year="2025_2026",
                    month_num=9, is_partial=False, total_current_m3=3101370.0,
                    internal_current_m3=2949844.0),
            self._empty(idm="later", position_date="01/02/2026",
                        harvest_year="2025_2026", month_num=9, is_partial=False),
        ]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        assert len(df) == 1
        assert df.iloc[0]["source_idm"] == "early"
        assert df.iloc[0]["total_current_m3"] == 3101370.0

    def test_latest_still_wins_between_two_populated_readings(self):
        rows = [
            _me_row(idm="early", position_date="16/04/2025", harvest_year="2025_2026",
                    month_num=4, total_current_m3=1379158.0),
            _me_row(idm="later", position_date="01/02/2026", harvest_year="2025_2026",
                    month_num=4, total_current_m3=2787817.0),
        ]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        assert df.iloc[0]["source_idm"] == "later"
        assert df.iloc[0]["total_current_m3"] == 2787817.0

    def test_month_with_no_figures_anywhere_stays_null(self):
        """Content truth, not a parse gap -- it must not be invented."""
        rows = [self._empty(idm="a", harvest_year="2022_2023", month_num=6),
                self._empty(idm="b", harvest_year="2022_2023", month_num=6,
                            position_date="01/09/2022")]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        assert len(df) == 1
        assert pd.isna(df.iloc[0]["total_current_m3"])

    def test_export_leg_is_derived_from_the_published_identity(self):
        """Tabela 9's export column is not captured for the newer layout, but
        total = external + internal is exact wherever all three survive.
        Digits are pdf_d202463da8b96630, Abr 2025/26."""
        rows = [_me_row(harvest_year="2025_2026", month_num=4,
                        position_date="01/02/2026",
                        total_current_m3=2787817.0, internal_current_m3=2728805.0,
                        external_current_m3=None,
                        total_prior_m3=2873120.0, internal_prior_m3=2782525.0,
                        external_prior_m3=None)]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        row = df.iloc[0]
        assert row["external_current_m3"] == 59012.0    # PDF prints 59.012
        assert row["external_prior_m3"] == 90595.0      # PDF prints 90.595
        assert (row["external_current_m3"] + row["internal_current_m3"]
                == row["total_current_m3"])

    def test_export_leg_not_derived_when_it_would_go_negative(self):
        rows = [_me_row(month_num=4, total_current_m3=100.0,
                        internal_current_m3=150.0, external_current_m3=None)]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        assert pd.isna(df.iloc[0]["external_current_m3"])

    def test_measured_export_leg_is_not_overwritten(self):
        rows = [_me_row(month_num=4, total_current_m3=1000.0,
                        internal_current_m3=900.0, external_current_m3=100.0)]
        df = transform_monthly_ethanol_sales(pd.DataFrame(rows))
        assert df.iloc[0]["external_current_m3"] == 100.0


# ---------------------------------------------------------------------------
# Required-column contracts
# ---------------------------------------------------------------------------

class TestRequiredColumns:

    @pytest.mark.parametrize("fn,cols", [
        (transform_season_history, ["harvest_year"]),
        (transform_release_series, ["harvest_year"]),
        (transform_corn_ethanol, ["harvest_year"]),
        (transform_monthly_ethanol_sales, ["harvest_year"]),
    ])
    def test_missing_columns_raise(self, fn, cols):
        with pytest.raises(ValueError, match="missing columns"):
            fn(pd.DataFrame(columns=cols))
