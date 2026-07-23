"""SILVER-F041 -- NOAA IOD header parsing + invalid-value fix.

The historical bug: the ``1870 2025`` year-range header matched the data-row regex
``^\\s*(\\d{4})\\s+`` and was parsed as ``year=1870, month=1, dmi_value=2025``, minting
the impossible ``dmi_value=2025`` and colliding with the real ``(1870, 1) = -0.438``
observation. These tests prove the fix:

  * the header is parsed as bounds, never admitted as data;
  * ``(1870, 1)`` occurs exactly once and no ``2025.0`` value survives;
  * a data row must carry 12 monthly cells (missing/extra-column rows are rejected);
  * sentinel / out-of-plausible-range / non-numeric cells become NaN;
  * ``(year, month)`` uniqueness is asserted in both bronze and silver;
  * derived rolling/lag fields are float64 (INV-2) and deterministic across reruns;
  * the explicit silver writer schema reconciles with the registry contract.
"""
from __future__ import annotations

import math
import sys

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.transforms.bronze_to_silver.noaa_iod import (
    SILVER_ARROW_SCHEMA,
    build_iod_silver,
)
from leviathan.transforms.raw_to_bronze.noaa_iod import (
    extract_iod_bronze,
    parse_header_bounds,
)
from leviathan.storage.paths import bronze_iod_key, raw_iod_key
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# The exact bug shape: header "1870 2025" plus real 1870/1871 rows and a padded
# current-year (2025) row with -9999 sentinels for unpublished months.
_ROW_1870 = ("1870    -0.438    -0.336     0.177    -0.048     0.120     0.234"
             "    -0.100     0.050     0.300     0.210     0.190     0.020")
_ROW_1871 = ("1871    -0.273    -0.170    -0.212    -0.148     0.010     0.020"
             "     0.030     0.040     0.050     0.060     0.070     0.080")
_ROW_2025 = ("2025     0.100     0.110     0.120     0.130  -9999.000  -9999.000"
             "  -9999.000  -9999.000  -9999.000  -9999.000  -9999.000  -9999.000")
_FOOTER = (
    "Created Mon Jun 16 09:50:15 MDT 2025\n"
    "using SST anomaly 10S:10N,50E-70E minus 10S:0,90E-110E area averaged\n"
    "Timeseries output created at NOAA PSL\n"
    "https://psl.noaa.gov/gcos_wgsp/timeseries/DMI"
)

_IOD_FILE = f"1870 2025\n{_ROW_1870}\n{_ROW_1871}\n{_ROW_2025}\n{_FOOTER}\n"


def _bytes(text: str) -> bytes:
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Header bounds
# ---------------------------------------------------------------------------

class TestHeaderBounds:
    def test_parses_two_year_header(self):
        assert parse_header_bounds(["1870 2025", _ROW_1870]) == (1870, 2025)

    def test_header_with_leading_ws(self):
        assert parse_header_bounds(["   1870   2025  "]) == (1870, 2025)

    def test_no_header_returns_none(self):
        assert parse_header_bounds([_ROW_1870, _FOOTER]) is None

    def test_data_row_is_not_a_header(self):
        # A 13-token data row must never be mistaken for the 2-year header.
        assert parse_header_bounds([_ROW_1870]) is None


# ---------------------------------------------------------------------------
# The header/observation collision (the marquee fix)
# ---------------------------------------------------------------------------

class TestHeaderNotAdmittedAsData:
    def test_1870_jan_occurs_exactly_once(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        jan_1870 = df[(df["year"] == 1870) & (df["month"] == 1)]
        assert len(jan_1870) == 1
        assert jan_1870.iloc[0]["dmi_value"] == pytest.approx(-0.438)

    def test_no_2025_value_survives(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        # The header's "2025" token must never reach a dmi_value.
        assert not (df["dmi_value"].dropna() > 3.0).any()
        assert 2025.0 not in set(df["dmi_value"].dropna().tolist())

    def test_unique_year_month(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        assert not df.duplicated(subset=["year", "month"]).any()

    def test_all_three_years_present(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        assert sorted(df["year"].unique()) == [1870, 1871, 2025]
        assert len(df) == 36  # 3 years x 12 months


# ---------------------------------------------------------------------------
# Cell coercion: sentinels, out-of-range, non-numeric
# ---------------------------------------------------------------------------

class TestCellCoercion:
    def test_sentinel_becomes_nan(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        # 2025 months 5-12 are -9999 sentinels -> NaN.
        may_2025 = df[(df["year"] == 2025) & (df["month"] == 5)].iloc[0]
        assert math.isnan(may_2025["dmi_value"])

    def test_real_values_preserved(self):
        df = extract_iod_bronze(_bytes(_IOD_FILE))
        apr_2025 = df[(df["year"] == 2025) & (df["month"] == 4)].iloc[0]
        assert apr_2025["dmi_value"] == pytest.approx(0.130)

    def test_out_of_range_value_becomes_nan(self):
        # A stray in-bounds-year row whose month-1 cell is an implausible 2025.0.
        bad = "1990  2025.000  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1"
        text = f"1870 2025\n{bad}\n"
        df = extract_iod_bronze(_bytes(text))
        r = df[(df["year"] == 1990) & (df["month"] == 1)].iloc[0]
        assert math.isnan(r["dmi_value"])

    def test_non_numeric_cell_becomes_nan(self):
        bad = "1990  x  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1"
        text = f"1870 2025\n{bad}\n"
        df = extract_iod_bronze(_bytes(text))
        r = df[(df["year"] == 1990) & (df["month"] == 1)].iloc[0]
        assert math.isnan(r["dmi_value"])


# ---------------------------------------------------------------------------
# Structural row rules: column count + bounds
# ---------------------------------------------------------------------------

class TestRowStructure:
    def test_missing_column_row_rejected(self):
        # 11 monthly cells (one short) -> not a valid data row -> skipped.
        short = "1955  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1  0.1"
        text = f"1870 2025\n{_ROW_1870}\n{short}\n"
        df = extract_iod_bronze(_bytes(text))
        assert 1955 not in set(df["year"].tolist())

    def test_extra_column_row_rejected(self):
        # 13 monthly cells (one extra) -> skipped.
        long = "1955  " + "  ".join(["0.1"] * 13)
        text = f"1870 2025\n{_ROW_1870}\n{long}\n"
        df = extract_iod_bronze(_bytes(text))
        assert 1955 not in set(df["year"].tolist())

    def test_year_outside_bounds_rejected(self):
        # A data row for 2050 with a header ending at 2025 must be rejected.
        future = "2050  " + "  ".join(["0.1"] * 12)
        text = f"1870 2025\n{_ROW_1870}\n{future}\n"
        df = extract_iod_bronze(_bytes(text))
        assert 2050 not in set(df["year"].tolist())

    def test_empty_file_raises(self):
        with pytest.raises(ValueError):
            extract_iod_bronze(_bytes("1870 2025\n"))


# ---------------------------------------------------------------------------
# Silver: uniqueness guard + INV-2 float64 + determinism
# ---------------------------------------------------------------------------

class TestSilver:
    def _bronze(self) -> pd.DataFrame:
        return extract_iod_bronze(_bytes(_IOD_FILE))

    def test_silver_rejects_duplicate_key(self):
        b = self._bronze()
        dup = pd.concat([b, b.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            build_iod_silver(dup)

    def test_measures_are_float64(self):
        s = build_iod_silver(self._bronze())
        for col in ("dmi_value", "iod_dmi_3month_avg", "iod_dmi_ethiopia_lag4"):
            assert str(s[col].dtype) == "float64", col

    def test_rolling_and_lag_deterministic(self):
        s1 = build_iod_silver(self._bronze())
        s2 = build_iod_silver(self._bronze())
        pd.testing.assert_frame_equal(s1, s2)

    def test_three_month_avg_value(self):
        s = build_iod_silver(self._bronze())
        # month 3 of 1870: mean(-0.438, -0.336, 0.177) = -0.199
        mar = s[(s["year"] == 1870) & (s["month"] == 3)].iloc[0]
        assert mar["iod_dmi_3month_avg"] == pytest.approx(-0.199, abs=1e-3)

    def test_phase_classification(self):
        s = build_iod_silver(self._bronze())
        # 1870-09 raw dmi = 0.300 (> 0.4? no) -> neutral; 1871 has none > 0.4.
        sep = s[(s["year"] == 1870) & (s["month"] == 9)].iloc[0]
        assert sep["iod_phase"] == "neutral"


# ---------------------------------------------------------------------------
# IOD-FRESHNESS (SKEPTIC-2): trailing placeholder-tail trim so agg=latest is honest
#
# The NOAA source pads the current year with -9999 sentinels (-> dmi_value NaN) and
# lags the calendar; the silver transform must drop that trailing all-placeholder
# block so the last (year, month) present is the last REAL observation. Otherwise the
# numbers-agent agg=latest (LIMIT-1, no IS NOT NULL guard) serves the NaN sentinel row.
# ---------------------------------------------------------------------------


def _bronze_frame(records: list[tuple[int, int, float | None]]) -> pd.DataFrame:
    """Build a minimal bronze frame (year, month, date, dmi_value) for silver tests.

    ``records`` is a list of ``(year, month, dmi_value_or_None)`` in any order; None
    stands for the -9999 sentinel the parser already coerced to NaN.
    """
    rows = [{"year": y, "month": m, "dmi_value": (float("nan") if v is None else v)}
            for (y, m, v) in records]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = "noaa_iod"
    return df[["year", "month", "date", "dmi_value", "source"]]


class TestTrailingTailTrim:
    def _padded(self) -> pd.DataFrame:
        # Two full real years + a current year with real months 1-3 then a NaN tail 4-12
        # (exactly the source shape: current-year sentinel pad).
        recs: list[tuple[int, int, float | None]] = []
        for m in range(1, 13):
            recs.append((2000, m, 0.10 + 0.01 * m))
        for m in range(1, 13):
            recs.append((2001, m, -0.10 + 0.01 * m))
        recs.append((2002, 1, 0.20))
        recs.append((2002, 2, 0.21))
        recs.append((2002, 3, 0.22))
        for m in range(4, 13):
            recs.append((2002, m, None))          # trailing placeholder tail
        return _bronze_frame(recs)

    def test_trailing_nan_months_are_dropped(self):
        s = build_iod_silver(self._padded())
        # last real dmi is 2002-03; nothing after it survives.
        assert (s["year"] * 100 + s["month"]).max() == 200203
        assert s[(s["year"] == 2002) & (s["month"] >= 4)].empty
        # 24 full + 3 real = 27 rows (9 placeholder months trimmed).
        assert len(s) == 27

    def test_latest_row_has_both_served_metrics_nonnull(self):
        # The money invariant: agg=latest (max ym) must serve a REAL dmi_value AND a
        # real iod_dmi_3month_avg -- never the NaN sentinel row.
        s = build_iod_silver(self._padded())
        last = s.sort_values(["year", "month"]).iloc[-1]
        assert last["year"] == 2002 and last["month"] == 3
        assert not math.isnan(last["dmi_value"])
        assert not math.isnan(last["iod_dmi_3month_avg"])

    def test_interior_gap_is_preserved(self):
        # A NaN month BEFORE the last real observation is interior, not trailing:
        # it must NOT be trimmed (only the contiguous trailing block goes).
        recs: list[tuple[int, int, float | None]] = [(y, m, 0.1) for y in (2000, 2001)
                                                      for m in range(1, 13)]
        recs.append((2002, 1, 0.2))
        recs.append((2002, 2, None))    # interior gap
        recs.append((2002, 3, 0.2))     # real obs after the gap
        recs.append((2002, 4, None))    # trailing tail
        recs.append((2002, 5, None))
        s = build_iod_silver(_bronze_frame(recs))
        assert (s["year"] * 100 + s["month"]).max() == 200203       # trailing tail gone
        interior = s[(s["year"] == 2002) & (s["month"] == 2)]
        assert len(interior) == 1                                   # interior row kept
        assert math.isnan(interior.iloc[0]["dmi_value"])            # still NaN, just present

    def test_all_nan_dmi_fails_closed(self):
        recs = [(2000, m, None) for m in range(1, 13)]
        with pytest.raises(ValueError, match="no non-null dmi_value"):
            build_iod_silver(_bronze_frame(recs))

    def test_no_trim_when_last_month_is_real(self):
        # A frame that ends on a real observation is returned unchanged in length.
        recs = [(y, m, 0.1) for y in (2000, 2001) for m in range(1, 13)]
        s = build_iod_silver(_bronze_frame(recs))
        assert len(s) == 24
        assert (s["year"] * 100 + s["month"]).max() == 200112

    def test_golden_source_shape_trims_to_last_real_month(self):
        # The real fixture (_IOD_FILE): 2025 has real months 1-4 then -9999 for 5-12.
        # Silver must end at 2025-04, both served metrics real.
        s = build_iod_silver(extract_iod_bronze(_bytes(_IOD_FILE)))
        last = s.sort_values(["year", "month"]).iloc[-1]
        assert last["year"] == 2025 and last["month"] == 4
        assert not math.isnan(last["dmi_value"])
        assert not math.isnan(last["iod_dmi_3month_avg"])
        # 1870 (12) + 1871 (12) + 2025 (4 real) = 28 rows; the 8-month tail is gone.
        assert len(s) == 28
        assert s[(s["year"] == 2025) & (s["month"] >= 5)].empty


# ---------------------------------------------------------------------------
# INV-2: explicit writer schema reconciles with the registry contract
# ---------------------------------------------------------------------------

_TARGET_TO_PA = {
    "int64": pa.int64(),
    "float64": pa.float64(),
    "string": pa.string(),
    "bool": pa.bool_(),
    "date32[day]": pa.date32(),
    "timestamp[us]": pa.timestamp("us"),
}


def test_silver_schema_matches_registry():
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_noaa_iod")
    expected = {c["name"]: _TARGET_TO_PA[c["target_arrow_type"]]
                for c in contract["physical_columns"]}
    actual = {f.name: f.type for f in SILVER_ARROW_SCHEMA}
    assert actual == expected


# ---------------------------------------------------------------------------
# Task-level publish authorization (SILVER-F004): --publish-mode is accepted and the
# raw + bronze S3 writes touch the canonical surface ONLY under a canonical (may_mutate_
# canonical) authorization -- a dry-run / shadow run must write NOTHING. Mirrors the
# noaa_oni_task gate; previously the raw/bronze writes were gated only on --dry-run and
# --publish-mode was undeclared (argparse SystemExit(2) before any publish decision).
# ---------------------------------------------------------------------------


class _FakeResp:
    """Minimal requests.Response stand-in for the IOD fetch (never hits the network)."""

    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeManifest:
    class _State:
        value = "VALIDATED"

    state = _State()


def _passing_silver() -> pd.DataFrame:
    """A silver frame large enough to clear the task's row / non-null validation floors so
    main() runs end to end (the raw/bronze gate under test fires BEFORE validation)."""
    n = 1900  # >= _MIN_ROWS (1860) and non-null 3mo >= _MIN_3MO_NON_NULL (1800)
    dates = pd.date_range("1870-01-01", periods=n, freq="MS")
    return pd.DataFrame({
        "date": dates,
        "dmi_value": 0.1,
        "iod_dmi_3month_avg": 0.1,
        "iod_phase": "neutral",
        "iod_dmi_ethiopia_lag4": 0.1,
    })


class TestTaskPublishGating:
    def _run_main(self, monkeypatch, auth, argv):
        """Drive noaa_iod_task.main() fully mocked: FakeS3 for canonical writes, a stubbed
        authorization verdict (the bit under test), a golden fetch, and a validation-passing
        silver. Returns the FakeS3 so the caller can assert what (if anything) was written."""
        from jobs.batch import noaa_iod_task as task

        s3 = FakeS3()

        def _fake_upload(body, bucket, key, region):
            # the raw path writes via upload_bytes_to_s3 (not s3.put_object); record it in the
            # same store so raw + bronze are asserted uniformly.
            s3.store[(bucket, key)] = bytes(body)

        monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: s3)
        monkeypatch.setattr(task, "upload_bytes_to_s3", _fake_upload)
        monkeypatch.setattr(task, "_caller_identity",
                            lambda region: ("111111111111", "arn:aws:sts::x:assumed-role/r/s"))
        monkeypatch.setattr(task, "authorize_publish", lambda *a, **k: auth)
        monkeypatch.setattr(task.requests, "get",
                            lambda url, timeout=None: _FakeResp(_bytes(_IOD_FILE)))
        monkeypatch.setattr(task, "build_iod_silver", lambda df: _passing_silver())
        # the silver publisher's own gating is covered by the flat-producer tests; stub it here so
        # this test isolates the raw/bronze gate.
        monkeypatch.setattr(task, "publish_flat_silver", lambda **k: _FakeManifest())
        monkeypatch.setenv("LEVIATHAN_BUCKET", "leviathan-test")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setattr(sys, "argv", ["noaa_iod_task.py", *argv])

        task.main()
        return s3

    def test_argparse_accepts_publish_mode_canonical(self, monkeypatch):
        # The marquee argparse fix: --publish-mode canonical must parse (no SystemExit(2)).
        try:
            self._run_main(monkeypatch, canonical_authorization(),
                           ["--publish-mode", "canonical", "--force-overwrite"])
        except SystemExit as exc:  # pragma: no cover - fail with a clear message
            pytest.fail(f"argparse rejected --publish-mode (SystemExit {exc.code})")

    @pytest.mark.parametrize("auth_factory", [dryrun_authorization, shadow_authorization])
    def test_non_canonical_auth_writes_no_raw_or_bronze(self, monkeypatch, auth_factory):
        s3 = self._run_main(monkeypatch, auth_factory(), ["--force-overwrite"])
        keys = s3.keys()
        assert raw_iod_key() not in keys
        assert bronze_iod_key() not in keys
        assert keys == []                       # nothing canonical touched in dry-run / shadow

    def test_canonical_auth_with_force_overwrite_writes_raw_and_bronze(self, monkeypatch):
        s3 = self._run_main(monkeypatch, canonical_authorization(),
                            ["--publish-mode", "canonical", "--force-overwrite"])
        keys = s3.keys()
        assert raw_iod_key() in keys
        assert bronze_iod_key() in keys
