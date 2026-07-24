"""IOD SOURCE SWITCH (ADR_IOD_SOURCE_SWITCH, RATIFIED 2026-07-24, Option B) -- the silver half.

The re-baseline moves `silver_noaa_iod` from the FROZEN NOAA PSL HadISST1.1 file to the LIVE
NOAA CPC ERSSTv5 IODMI record. The ADR's binding constraint on this layer is that NOTHING
analytical moves with it: the 3-month mean, the +/-0.4 phase band, the Ethiopia lag-4 and the
trailing-tail trim are pure functions of the ordered `dmi_value` series, so `build_iod_silver`
is reused UNCHANGED and only the `source` stamp differs (ADR Section 5). These tests prove:

  * the CPC path stamps the TRUE provider (`cpc_iodmi`, ADR-003 rule 2) while the served
    object stays on the LEGACY `source=noaa_iod` root (decision 6.4) -- the two identities
    are deliberately different and neither may drift onto the other;
  * the same dmi series produces a BYTE-IDENTICAL silver frame on either basis apart from
    that stamp (the "reused unchanged" claim, made falsifiable);
  * the stamp resolution is total: explicit argument > the bronze's own stamp > the legacy
    default, with a blank/mixed bronze stamp falling back rather than publishing ambiguity;
  * the CPC bronze's extra box columns (wtio_value / setio_value) never widen the served
    8-column schema;
  * the full raw -> bronze -> silver path joins end to end on a CPC-format file.

AWS-free; no network.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest
from leviathan.storage.paths import (
    bronze_cpc_iodmi_key,
    raw_cpc_iodmi_key,
    silver_iod_key,
)
from leviathan.transforms.bronze_to_silver.cpc_iodmi import (
    SOURCE,
    build_cpc_iodmi_silver,
    silver_key,
)
from leviathan.transforms.bronze_to_silver.noaa_iod import (
    SILVER_ARROW_SCHEMA,
    SILVER_COLUMNS,
    build_iod_silver,
)
from leviathan.transforms.raw_to_bronze.cpc_iodmi import extract_cpc_iodmi_bronze

_LEGACY_SOURCE = "noaa_iod"


# ---------------------------------------------------------------------------
# Fixtures: bronze frames in each parser's shape, over the SAME dmi series.
# ---------------------------------------------------------------------------

def _dmi_series() -> list[tuple[int, int, float]]:
    """(year, month, dmi) covering both phase thresholds and enough months for lag-4."""
    vals = [0.08, 0.15, -0.22, -0.51, -0.44, 0.03,       # 1950-01..06 (negative phase inside)
            0.31, 0.55, 0.92, 1.10, 0.48, 0.12,          # 1950-07..12 (positive phase inside)
            -0.05, -0.18, 0.02, 0.21, 0.33, -0.61]       # 1951-01..06
    out: list[tuple[int, int, float]] = []
    for i, v in enumerate(vals):
        year, month = (1950, i + 1) if i < 12 else (1951, i - 11)
        out.append((year, month, v))
    return out


def _cpc_bronze() -> pd.DataFrame:
    """CPC-parser shape: the two box columns ride along beside dmi_value, stamped cpc_iodmi."""
    rows = [{"year": y, "month": m, "wtio_value": round(v / 2, 2),
             "setio_value": round(v / 2 - v, 2), "dmi_value": v} for (y, m, v) in _dmi_series()]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = SOURCE
    return df[["year", "month", "date", "wtio_value", "setio_value", "dmi_value", "source"]]


def _hadisst_bronze() -> pd.DataFrame:
    """HadISST-parser shape over the SAME dmi values (the basis-agnostic comparison arm)."""
    rows = [{"year": y, "month": m, "dmi_value": v} for (y, m, v) in _dmi_series()]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = _LEGACY_SOURCE
    return df[["year", "month", "date", "dmi_value", "source"]]


# ---------------------------------------------------------------------------
# The two identities: provider stamp vs served path (ADR decision 6.4)
# ---------------------------------------------------------------------------

class TestSourceIdentityVsServedPath:
    def test_cpc_silver_is_stamped_with_the_true_provider(self):
        s = build_cpc_iodmi_silver(_cpc_bronze())
        assert set(s["source"].unique()) == {"cpc_iodmi"}          # ADR-003 rule 2, never the table name

    def test_served_path_stays_on_the_legacy_root(self):
        # The re-baseline is an atomic overwrite of the SAME object, not a path migration: consumers
        # (15 DAGs, Card A, features, pg mirror) are not repointed. The path is a legacy misnomer.
        assert silver_key() == silver_iod_key()
        assert silver_key() == "silver/weather/source=noaa_iod/part-000.parquet"
        assert "source=cpc_iodmi" not in silver_key()

    def test_raw_and_bronze_capture_under_the_truthful_prefix(self):
        # Only the per-provider CAPTURE layers move; the served identity does not.
        assert "source=cpc_iodmi" in raw_cpc_iodmi_key()
        assert "source=cpc_iodmi" in bronze_cpc_iodmi_key()

    def test_stamp_and_path_disagree_on_purpose(self):
        assert SOURCE != _LEGACY_SOURCE and _LEGACY_SOURCE in silver_key()


# ---------------------------------------------------------------------------
# "build_iod_silver is REUSED UNCHANGED" -- made falsifiable
# ---------------------------------------------------------------------------

class TestBasisAgnosticReuse:
    def test_same_series_gives_identical_frames_apart_from_the_stamp(self):
        cpc = build_cpc_iodmi_silver(_cpc_bronze())
        had = build_iod_silver(_hadisst_bronze())
        assert list(cpc.columns) == SILVER_COLUMNS == list(had.columns)
        pd.testing.assert_frame_equal(cpc.drop(columns=["source"]), had.drop(columns=["source"]))
        assert set(cpc["source"].unique()) == {"cpc_iodmi"}
        assert set(had["source"].unique()) == {_LEGACY_SOURCE}

    def test_derived_features_hold_on_the_new_basis(self):
        s = build_cpc_iodmi_silver(_cpc_bronze())
        by_ym = {(int(r.year), int(r.month)): r for r in s.itertuples(index=False)}
        # 3-month mean, min_periods=2: 1950-03 = mean(0.08, 0.15, -0.22).
        assert by_ym[(1950, 3)].iod_dmi_3month_avg == pytest.approx(0.0033, abs=1e-3)
        # WINDOW WIDTH pinned where 3 and 4 actually diverge. Inside the first three rows a
        # rolling(4) mean collapses onto rolling(3) (min_periods=2 averages what is there), so
        # the 1950-03 assertion above cannot see a widened window; 1950-05 can --
        # mean(-0.22, -0.51, -0.44) = -0.39 at width 3 vs -0.255 at width 4 (ADR decision 6).
        assert by_ym[(1950, 5)].iod_dmi_3month_avg == pytest.approx(-0.39, abs=1e-4)
        # +/-0.4 JMA band on the RAW dmi, unchanged by the basis switch.
        assert by_ym[(1950, 9)].iod_phase == "positive"             # 0.92
        assert by_ym[(1950, 4)].iod_phase == "negative"             # -0.51
        assert by_ym[(1950, 6)].iod_phase == "neutral"              # 0.03
        # BAND EDGES pinned: the three rows above sit far from +/-0.4, so widening the band to
        # +/-0.5 would leave them all classified the same. These two are the only fixture months
        # between 0.4 and 0.5, so they are what makes the ratified JMA threshold falsifiable.
        assert by_ym[(1950, 11)].iod_phase == "positive"            # 0.48 -- just outside +0.4
        assert by_ym[(1950, 5)].iod_phase == "negative"             # -0.44 -- just outside -0.4
        # Ethiopia lag-4: the smoothed value from four months earlier.
        assert by_ym[(1950, 7)].iod_dmi_ethiopia_lag4 == pytest.approx(
            by_ym[(1950, 3)].iod_dmi_3month_avg)
        # the first 4 months have no lag-4 antecedent
        assert math.isnan(by_ym[(1950, 1)].iod_dmi_ethiopia_lag4)

    def test_box_columns_do_not_widen_the_served_schema(self):
        # INV-2: the CPC bronze carries wtio_value/setio_value; silver stays the SAME 8 columns,
        # so the Glue DDL and the pinned writer schema are untouched by the switch.
        s = build_cpc_iodmi_silver(_cpc_bronze())
        assert list(s.columns) == SILVER_COLUMNS
        assert "wtio_value" not in s.columns and "setio_value" not in s.columns
        assert [f.name for f in SILVER_ARROW_SCHEMA] == SILVER_COLUMNS

    def test_trailing_placeholder_trim_still_applies_on_the_new_basis(self):
        # CPC publishes only completed months, so the trim is normally a no-op -- it must still fire
        # if a sentinel tail ever appears, or agg=latest would serve NaN (the IOD-FRESHNESS invariant).
        b = _cpc_bronze()
        nan = float("nan")
        tail = pd.DataFrame([{"year": 1951, "month": m, "wtio_value": nan, "setio_value": nan,
                              "dmi_value": nan,
                              "date": pd.Timestamp(1951, m, 1), "source": SOURCE}
                             for m in (7, 8)])
        s = build_cpc_iodmi_silver(pd.concat([b, tail], ignore_index=True))
        assert (s["year"] * 100 + s["month"]).max() == 195106
        assert not math.isnan(s.iloc[-1]["dmi_value"])


# ---------------------------------------------------------------------------
# Stamp resolution: explicit > bronze's own > legacy default
# ---------------------------------------------------------------------------

class TestSourceStampResolution:
    def test_legacy_default_survives_for_a_stampless_bronze(self):
        # Back-compat: the HadISST path (and the frozen-snapshot rebuild) must keep stamping noaa_iod
        # even when the caller passes nothing and the bronze carries no source column.
        b = _hadisst_bronze().drop(columns=["source"])
        assert set(build_iod_silver(b)["source"].unique()) == {_LEGACY_SOURCE}

    def test_bronze_stamp_carries_through_when_no_argument_is_given(self):
        # A caller that just hands a CPC bronze frame to the shared builder must NOT silently
        # re-label CPC rows as noaa_iod.
        assert set(build_iod_silver(_cpc_bronze())["source"].unique()) == {"cpc_iodmi"}

    def test_explicit_argument_wins_over_the_bronze_stamp(self):
        s = build_iod_silver(_cpc_bronze(), source=_LEGACY_SOURCE)
        assert set(s["source"].unique()) == {_LEGACY_SOURCE}

    @pytest.mark.parametrize("stamps", [["cpc_iodmi", "noaa_iod"], ["", ""], [None, None]])
    def test_ambiguous_bronze_stamp_falls_back_to_the_default(self, stamps):
        # A published frame's stamp must be ONE unambiguous provider; a mixed or blank bronze stamp
        # is not evidence, so it falls back rather than propagating ambiguity into silver.
        b = _hadisst_bronze()
        b["source"] = [stamps[i % len(stamps)] for i in range(len(b))]
        assert set(build_iod_silver(b)["source"].unique()) == {_LEGACY_SOURCE}


# ---------------------------------------------------------------------------
# End to end: the CPC file shape -> bronze -> silver (the two lanes join)
# ---------------------------------------------------------------------------

_CPC_PREAMBLE = (
    "Data sources for indices:\n"
    "ERSST.V5 : Huang, B., Peter W. Thorne, et. al, 2017: Extended Reconstructed Sea Surface\n"
    "Climatology : 1991-2020\n"
    "\n"
    "WTIO  : SSTA averaged in [50E-70E, 10S-10N]\n"
    "SETIO : SSTA averaged in [90E-110E, 10S-0]\n"
    "DMI  = WTIO - SETIO\n"
    "\n"
    "  Year   Month     WTIO      SETIO       DMI\n"
)


def _cpc_file_bytes() -> bytes:
    lines = [_CPC_PREAMBLE]
    for (y, m, v) in _dmi_series():
        wtio = round(v / 2, 2)
        setio = round(wtio - v, 2)                      # keeps the published DMI = WTIO - SETIO identity
        lines.append(f"  {y:4d}  {m:4d}   {wtio:8.2f}   {setio:8.2f}   {round(wtio - setio, 2):8.2f}\n")
    return "".join(lines).encode("utf-8")


def test_raw_to_bronze_to_silver_joins_end_to_end():
    bronze = extract_cpc_iodmi_bronze(_cpc_file_bytes())
    silver = build_cpc_iodmi_silver(bronze)
    assert list(silver.columns) == SILVER_COLUMNS
    assert len(silver) == len(_dmi_series())
    assert set(silver["source"].unique()) == {"cpc_iodmi"}
    last = silver.sort_values(["year", "month"]).iloc[-1]
    assert (int(last["year"]), int(last["month"])) == (1951, 6)
    assert not math.isnan(last["dmi_value"])            # agg=latest serves a real reading
    assert int(silver["year"].min()) == 1950            # the CPC record starts 1950, not 1870
