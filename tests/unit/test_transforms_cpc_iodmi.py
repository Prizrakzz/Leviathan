"""ADR_IOD_SOURCE_SWITCH -- CPC IODMI (ERSSTv5) ingest + bronze parser.

The ratified re-baseline (Option B) repoints ``silver_noaa_iod`` from the frozen NOAA PSL
HadISST DMI onto the live NOAA CPC IODMI record. These tests pin the LANE-1 half of that
switch -- the fetcher and the raw->bronze parser:

  * the two golden identities from the ADR are parsed exactly:
    1950-01  DMI 0.08 = -0.85 - (-0.93)   and   2026-06  DMI -0.58 = 0.24 - 0.82;
  * the ``Year Month WTIO SETIO DMI`` column header -- which splits into exactly the same
    5 tokens as a real data row -- is never admitted as data (the SILVER-F041 lesson,
    carried over from the HadISST ``1870 2025`` header bug);
  * sentinel / out-of-range / non-numeric cells become NaN, never a synthesized number;
  * structurally malformed rows (wrong token count, month 13, pre-1950 year) are rejected;
  * ``DMI == WTIO - SETIO`` is asserted within the published rounding tolerance, and a
    real one-ULP rounding miss (the live file's worst case) is still admitted;
  * a climatology other than the ratified 1991-2020 basis fails closed;
  * the bronze frame satisfies the basis-agnostic ``build_iod_silver`` contract unchanged;
  * the batch entrypoint runs the new source behind ``--source cpc_iodmi`` (truthful raw /
    bronze keys + truthful silver ``source`` stamp) and its DEFAULT is still HadISST.
"""
from __future__ import annotations

import math
import sys

import pandas as pd
import pytest
import requests

from leviathan.storage.paths import (
    bronze_cpc_iodmi_key,
    bronze_iod_key,
    raw_cpc_iodmi_key,
    raw_iod_key,
)
from leviathan.transforms.bronze_to_silver.noaa_iod import SILVER_COLUMNS, build_iod_silver
from leviathan.transforms.raw_to_bronze.cpc_iodmi import (
    BRONZE_COLUMNS,
    EXPECTED_CLIMATOLOGY,
    extract_cpc_iodmi_bronze,
    parse_climatology,
)
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
)

# ---------------------------------------------------------------------------
# Golden micro-fixture -- the real file shape, trimmed to the ADR's anchor rows.
#
# The degree signs in the box definitions are built via chr(0xB0) so this test file stays
# pure ASCII while the fixture bytes still exercise the parser's UTF-8 decode path.
# ---------------------------------------------------------------------------

_DEG = chr(0xB0)    # the preamble's degree signs, built so this file stays ASCII

_PREAMBLE = (
    "Data sources for indices:\n"
    "ERSST.V5 : Huang, B., Peter W. Thorne, et. al, 2017: Extended Reconstructed Sea "
    "Surface Temperature version 5 (ERSSTv5), Upgrades, validations, and "
    "intercomparisons. J. Climate\n"
    "Climatology : 1991-2020\n"
    "\n"
    f"WTIO  : SSTA averaged in [50{_DEG}E-70{_DEG}E, 10{_DEG}S-10{_DEG}N]\n"
    f"SETIO : SSTA averaged in [90{_DEG}E-110{_DEG}E, 10{_DEG}S-0]\n"
    "DMI  = WTIO - SETIO\n"
    "\n"
)

# 5 whitespace tokens -- structurally indistinguishable from a data row by token count.
_COLUMN_HEADER = "  Year   Month     WTIO      SETIO       DMI"

_ROW_1950_01 = "  1950     1      -0.85      -0.93       0.08"   # ADR identity #1
_ROW_1950_02 = "  1950     2      -0.93      -0.50      -0.44"
_ROW_1997_11 = "  1997    11       0.48      -1.07       1.55"   # the +IOD analogue peak
_ROW_2026_06 = "  2026     6       0.24       0.82      -0.58"   # ADR identity #2 (latest)

_GOLDEN = _PREAMBLE + "\n".join([
    _COLUMN_HEADER, _ROW_1950_01, _ROW_1950_02, _ROW_1997_11, _ROW_2026_06,
]) + "\n"


def _bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _file(*rows: str) -> bytes:
    """Golden preamble + column header + the given data rows."""
    return _bytes(_PREAMBLE + "\n".join([_COLUMN_HEADER, *rows]) + "\n")


def _row(year: int, month: int, wtio: str, setio: str, dmi: str) -> str:
    return f"  {year}  {month:>4}  {wtio:>9}  {setio:>9}  {dmi:>9}"


# ---------------------------------------------------------------------------
# Climatology preamble
# ---------------------------------------------------------------------------

class TestClimatology:
    def test_parses_declared_climatology(self):
        assert parse_climatology(_GOLDEN.splitlines()) == EXPECTED_CLIMATOLOGY

    def test_absent_climatology_returns_none(self):
        assert parse_climatology([_COLUMN_HEADER, _ROW_1950_01]) is None

    def test_absent_climatology_still_parses(self):
        # Missing preamble is a warning, not a failure -- the values are still readable.
        df = extract_cpc_iodmi_bronze(_bytes(f"{_COLUMN_HEADER}\n{_ROW_1950_01}\n"))
        assert len(df) == 1

    def test_different_climatology_fails_closed(self):
        # A silent upstream re-anomalization restates every historical value.
        text = _GOLDEN.replace("Climatology : 1991-2020", "Climatology : 2001-2030")
        with pytest.raises(ValueError, match="climatology"):
            extract_cpc_iodmi_bronze(_bytes(text))


# ---------------------------------------------------------------------------
# The ADR golden identities
# ---------------------------------------------------------------------------

class TestGoldenIdentities:
    def _df(self) -> pd.DataFrame:
        return extract_cpc_iodmi_bronze(_bytes(_GOLDEN))

    def test_columns_and_row_count(self):
        df = self._df()
        assert list(df.columns) == BRONZE_COLUMNS
        assert len(df) == 4                      # the column header is NOT a 5th row
        assert (df["source"] == "cpc_iodmi").all()

    def test_first_record_month_1950_01(self):
        r = self._df().iloc[0]
        assert (int(r["year"]), int(r["month"])) == (1950, 1)
        assert r["wtio_value"] == pytest.approx(-0.85)
        assert r["setio_value"] == pytest.approx(-0.93)
        assert r["dmi_value"] == pytest.approx(0.08)
        assert r["dmi_value"] == pytest.approx(r["wtio_value"] - r["setio_value"], abs=1e-9)

    def test_latest_record_month_2026_06(self):
        r = self._df().iloc[-1]
        assert (int(r["year"]), int(r["month"])) == (2026, 6)
        assert r["wtio_value"] == pytest.approx(0.24)
        assert r["setio_value"] == pytest.approx(0.82)
        assert r["dmi_value"] == pytest.approx(-0.58)
        assert r["dmi_value"] == pytest.approx(r["wtio_value"] - r["setio_value"], abs=1e-9)

    def test_1997_analogue_peak_is_the_ersst_magnitude(self):
        # ADR Section 3.1: the 1997-11 Ethiopia lag-4 anchor is 1.279 on HadISST but 1.55
        # on ERSSTv5 -- the re-baseline restates the analogue, and bronze must carry it.
        r = self._df()
        nov97 = r[(r["year"] == 1997) & (r["month"] == 11)].iloc[0]
        assert nov97["dmi_value"] == pytest.approx(1.55)

    def test_date_column_is_month_start(self):
        df = self._df()
        assert df["date"].iloc[0] == pd.Timestamp("1950-01-01")
        assert df["date"].iloc[-1] == pd.Timestamp("2026-06-01")

    def test_measures_are_float64(self):
        df = self._df()
        for col in ("wtio_value", "setio_value", "dmi_value"):
            assert str(df[col].dtype) == "float64", col

    def test_deterministic(self):
        pd.testing.assert_frame_equal(self._df(), self._df())


# ---------------------------------------------------------------------------
# The column header is shaped like a data row (SILVER-F041 carry-over)
# ---------------------------------------------------------------------------

class TestColumnHeaderNotAdmittedAsData:
    def test_header_has_data_row_token_count(self):
        # Proves the trap is real: a token-count rule alone would admit the header.
        assert len(_COLUMN_HEADER.split()) == 5

    def test_header_never_becomes_a_record(self):
        df = extract_cpc_iodmi_bronze(_bytes(_GOLDEN))
        assert df["year"].notna().all()
        assert sorted(df["year"].unique().tolist()) == [1950, 1997, 2026]

    def test_no_duplicate_year_month(self):
        df = extract_cpc_iodmi_bronze(_bytes(_GOLDEN))
        assert not df.duplicated(subset=["year", "month"]).any()

    def test_duplicate_key_fails_closed(self):
        with pytest.raises(ValueError, match="duplicate"):
            extract_cpc_iodmi_bronze(_file(_ROW_1950_01, _ROW_1950_01))


# ---------------------------------------------------------------------------
# Cell coercion: sentinels, out-of-range, non-numeric
# ---------------------------------------------------------------------------

class TestCellCoercion:
    def test_sentinel_becomes_nan(self):
        df = extract_cpc_iodmi_bronze(_file(_row(2026, 7, "-999.9", "-999.9", "-999.9")))
        r = df.iloc[0]
        for col in ("wtio_value", "setio_value", "dmi_value"):
            assert math.isnan(r[col]), col

    def test_sentinel_row_is_kept_source_faithfully(self):
        # INV-4: an absent measure stays null; the KEY is still published.
        df = extract_cpc_iodmi_bronze(_file(_ROW_1950_01, _row(1950, 2, "-9999.0", "-9999.0", "-9999.0")))
        assert len(df) == 2
        assert (int(df.iloc[1]["year"]), int(df.iloc[1]["month"])) == (1950, 2)

    def test_out_of_range_value_becomes_nan(self):
        df = extract_cpc_iodmi_bronze(_file(_row(1990, 1, "2026.0", "0.10", "0.05")))
        assert math.isnan(df.iloc[0]["wtio_value"])
        assert df.iloc[0]["setio_value"] == pytest.approx(0.10)

    def test_non_numeric_cell_becomes_nan(self):
        df = extract_cpc_iodmi_bronze(_file(_row(1990, 1, "x", "0.10", "0.05")))
        assert math.isnan(df.iloc[0]["wtio_value"])

    def test_partially_null_row_skips_the_identity_check(self):
        # A missing box makes the identity UNCHECKABLE, not violated -- must not raise.
        df = extract_cpc_iodmi_bronze(_file(_row(1990, 1, "-999.9", "0.10", "0.05")))
        assert df.iloc[0]["dmi_value"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Structural row rules: token count + bounds
# ---------------------------------------------------------------------------

class TestRowStructure:
    def test_short_row_rejected(self):
        short = "  1955     1      -0.10      -0.20"
        df = extract_cpc_iodmi_bronze(_file(_ROW_1950_01, short))
        assert 1955 not in set(df["year"].tolist())

    def test_long_row_rejected(self):
        long_row = "  1955     1      -0.10      -0.20       0.10       0.10"
        df = extract_cpc_iodmi_bronze(_file(_ROW_1950_01, long_row))
        assert 1955 not in set(df["year"].tolist())

    def test_month_out_of_range_rejected(self):
        df = extract_cpc_iodmi_bronze(_file(_ROW_1950_01, _row(1955, 13, "-0.10", "-0.20", "0.10")))
        assert 1955 not in set(df["year"].tolist())

    def test_year_before_record_start_rejected(self):
        # CPC starts 1950-01; the ADR accepted the loss of 1870-1949 (no named analogue).
        df = extract_cpc_iodmi_bronze(_file(_ROW_1950_01, _row(1949, 12, "-0.10", "-0.20", "0.10")))
        assert 1949 not in set(df["year"].tolist())

    def test_preamble_only_file_raises(self):
        with pytest.raises(ValueError, match="no parseable data rows"):
            extract_cpc_iodmi_bronze(_bytes(_PREAMBLE + _COLUMN_HEADER + "\n"))


# ---------------------------------------------------------------------------
# DMI = WTIO - SETIO
# ---------------------------------------------------------------------------

class TestDmiIdentity:
    def test_one_ulp_rounding_miss_is_admitted(self):
        # The live file's worst residual: 1958-07 publishes -0.85 where the rounded boxes
        # give -0.68 - 0.18 = -0.86. Independent 2-dp rounding, not a broken file.
        df = extract_cpc_iodmi_bronze(_file(_row(1958, 7, "-0.68", "0.18", "-0.85")))
        assert df.iloc[0]["dmi_value"] == pytest.approx(-0.85)

    def test_violation_fails_closed(self):
        with pytest.raises(ValueError, match="DMI = WTIO - SETIO"):
            extract_cpc_iodmi_bronze(_file(_row(1990, 1, "0.50", "0.10", "0.90")))

    def test_swapped_columns_fail_closed(self):
        # A column-order change upstream (DMI first) is exactly what this assertion buys.
        with pytest.raises(ValueError, match="DMI = WTIO - SETIO"):
            extract_cpc_iodmi_bronze(_file(_row(2026, 6, "-0.58", "0.24", "0.82")))

    def test_violation_message_names_the_offending_month(self):
        with pytest.raises(ValueError, match=r"\(1990, 1,"):
            extract_cpc_iodmi_bronze(_file(_row(1990, 1, "0.50", "0.10", "0.90")))


# ---------------------------------------------------------------------------
# The bronze frame satisfies the basis-agnostic silver transform, UNCHANGED
# (ADR Section 5: build_iod_silver is reused as-is; only the source stamp moves)
# ---------------------------------------------------------------------------

class TestSilverReuse:
    def test_build_iod_silver_accepts_cpc_bronze(self):
        s = build_iod_silver(extract_cpc_iodmi_bronze(_bytes(_GOLDEN)))
        assert list(s.columns) == SILVER_COLUMNS
        assert len(s) == 4
        assert s["dmi_value"].tolist() == pytest.approx([0.08, -0.44, 1.55, -0.58])

    def test_phase_thresholds_hold_on_the_new_basis(self):
        s = build_iod_silver(extract_cpc_iodmi_bronze(_bytes(_GOLDEN)))
        phases = dict(zip(zip(s["year"], s["month"]), s["iod_phase"]))
        assert phases[(1997, 11)] == "positive"     # 1.55 > +0.4
        assert phases[(2026, 6)] == "negative"      # -0.58 < -0.4
        assert phases[(1950, 1)] == "neutral"       # 0.08


# ---------------------------------------------------------------------------
# Fetcher: URL pin + bounded retry (no network, no S3)
# ---------------------------------------------------------------------------

class _FakeResp:
    """Minimal requests.Response stand-in (never hits the network)."""

    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestFetcher:
    def _mod(self, monkeypatch):
        from jobs.ingest import fetch_cpc_iodmi as mod
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)     # no real backoff waits
        return mod

    def test_url_is_the_ratified_adr_pin(self, monkeypatch):
        mod = self._mod(monkeypatch)
        assert mod._IODMI_URL == (
            "https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/IODMI/"
            "mnth.ersstv5.clim19912020.dmi_current.txt"
        )

    def test_returns_bytes_on_first_success(self, monkeypatch):
        mod = self._mod(monkeypatch)
        calls: list[str] = []

        def _get(url, timeout=None):
            calls.append(url)
            return _FakeResp(_bytes(_GOLDEN))

        monkeypatch.setattr(mod.requests, "get", _get)
        assert mod.fetch_with_retry() == _bytes(_GOLDEN)
        assert len(calls) == 1

    def test_retries_a_connection_error_then_succeeds(self, monkeypatch):
        mod = self._mod(monkeypatch)
        attempts = {"n": 0}

        def _get(url, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise requests.ConnectionError("reset by peer")
            return _FakeResp(_bytes(_GOLDEN))

        monkeypatch.setattr(mod.requests, "get", _get)
        assert mod.fetch_with_retry() == _bytes(_GOLDEN)
        assert attempts["n"] == 2

    def test_retries_a_retryable_status_then_succeeds(self, monkeypatch):
        mod = self._mod(monkeypatch)
        responses = [_FakeResp(b"", 503), _FakeResp(_bytes(_GOLDEN))]

        monkeypatch.setattr(mod.requests, "get", lambda url, timeout=None: responses.pop(0))
        assert mod.fetch_with_retry() == _bytes(_GOLDEN)
        assert responses == []

    def test_raises_after_the_attempt_budget(self, monkeypatch):
        mod = self._mod(monkeypatch)
        attempts = {"n": 0}

        def _get(url, timeout=None):
            attempts["n"] += 1
            raise requests.ConnectionError("down")

        monkeypatch.setattr(mod.requests, "get", _get)
        with pytest.raises(requests.RequestException):
            mod.fetch_with_retry()
        assert attempts["n"] == mod._MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Batch entrypoint: --source cpc_iodmi runs the new basis end to end; the DEFAULT
# (HadISST) path is unchanged and stays runnable for the _hadisst_frozen snapshot.
# ---------------------------------------------------------------------------

# A minimal HadISST-shaped file for the default-source path (year-range header + 1 row).
_HADISST_FILE = (
    "1870 1870\n"
    "1870    -0.438    -0.336     0.177    -0.048     0.120     0.234"
    "    -0.100     0.050     0.300     0.210     0.190     0.020\n"
)


class _FakeManifest:
    class _State:
        value = "VALIDATED"

    state = _State()


def _passing_silver(start: str, n: int) -> pd.DataFrame:
    """A silver frame that clears both sources' row / non-null floors so main() runs end
    to end (the raw/bronze/source-stamp behaviour under test sits before validation)."""
    dates = pd.date_range(start, periods=n, freq="MS")
    df = pd.DataFrame({
        "year": dates.year,
        "month": dates.month,
        "date": dates,
        "dmi_value": 0.1,
        "iod_dmi_3month_avg": 0.1,
        "iod_phase": "neutral",
        "iod_dmi_ethiopia_lag4": 0.1,
        "source": "noaa_iod",          # the stamp build_iod_silver hardcodes
    })
    df.loc[df["date"] == "1997-11-01", "iod_dmi_3month_avg"] = 1.05
    return df


class TestTaskSourceArg:
    def _run_main(self, monkeypatch, argv, *, payload: bytes, silver: pd.DataFrame,
                  auth=None):
        from jobs.batch import noaa_iod_task as task

        s3 = FakeS3()
        published: dict = {}

        def _fake_upload(body, bucket, key, region):
            s3.store[(bucket, key)] = bytes(body)

        def _fake_publish(**kwargs):
            published.update(kwargs)
            return _FakeManifest()

        monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: s3)
        monkeypatch.setattr(task, "upload_bytes_to_s3", _fake_upload)
        monkeypatch.setattr(task, "_caller_identity",
                            lambda region: ("111111111111", "arn:aws:sts::x:assumed-role/r/s"))
        monkeypatch.setattr(task, "authorize_publish",
                            lambda *a, **k: auth or canonical_authorization())
        monkeypatch.setattr(task.requests, "get",
                            lambda url, timeout=None: _FakeResp(payload))
        monkeypatch.setattr(task, "build_iod_silver", lambda df: silver)
        monkeypatch.setattr(task, "publish_flat_silver", _fake_publish)
        monkeypatch.setenv("LEVIATHAN_BUCKET", "leviathan-test")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setattr(sys, "argv", ["noaa_iod_task.py", *argv])

        task.main()
        return s3, published

    def test_cpc_source_writes_the_truthful_raw_and_bronze_keys(self, monkeypatch):
        s3, _ = self._run_main(
            monkeypatch,
            ["--source", "cpc_iodmi", "--publish-mode", "canonical", "--force-overwrite"],
            payload=_bytes(_GOLDEN), silver=_passing_silver("1950-01-01", 918),
        )
        keys = s3.keys()
        assert raw_cpc_iodmi_key() in keys
        assert bronze_cpc_iodmi_key() in keys
        assert raw_iod_key() not in keys          # the HadISST capture is untouched
        assert bronze_iod_key() not in keys

    def test_cpc_source_stamps_the_silver_source_column(self, monkeypatch):
        # ADR-003 rule 2: the served source column must name the TRUE provider of the rows.
        _, published = self._run_main(
            monkeypatch,
            ["--source", "cpc_iodmi", "--publish-mode", "canonical", "--force-overwrite"],
            payload=_bytes(_GOLDEN), silver=_passing_silver("1950-01-01", 918),
        )
        assert published["table_name"] == "silver_noaa_iod"          # legacy served identity
        assert set(published["df"]["source"].unique()) == {"cpc_iodmi"}

    def test_cpc_source_writes_the_legacy_silver_key(self, monkeypatch):
        from leviathan.storage.paths import silver_iod_key

        _, published = self._run_main(
            monkeypatch,
            ["--source", "cpc_iodmi", "--publish-mode", "canonical", "--force-overwrite"],
            payload=_bytes(_GOLDEN), silver=_passing_silver("1950-01-01", 918),
        )
        assert published["canonical_key"] == silver_iod_key()

    def test_default_source_is_unchanged_hadisst(self, monkeypatch):
        s3, published = self._run_main(
            monkeypatch, ["--publish-mode", "canonical", "--force-overwrite"],
            payload=_bytes(_HADISST_FILE), silver=_passing_silver("1870-01-01", 1900),
        )
        keys = s3.keys()
        assert raw_iod_key() in keys
        assert bronze_iod_key() in keys
        assert raw_cpc_iodmi_key() not in keys
        assert set(published["df"]["source"].unique()) == {"noaa_iod"}

    def test_cpc_source_writes_nothing_under_a_dry_run_authorization(self, monkeypatch):
        s3, _ = self._run_main(
            monkeypatch, ["--source", "cpc_iodmi", "--force-overwrite"],
            payload=_bytes(_GOLDEN), silver=_passing_silver("1950-01-01", 918),
            auth=dryrun_authorization(),
        )
        assert s3.keys() == []

    def test_unknown_source_is_rejected(self, monkeypatch):
        from jobs.batch import noaa_iod_task as task

        monkeypatch.setenv("LEVIATHAN_BUCKET", "leviathan-test")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setattr(sys, "argv", ["noaa_iod_task.py", "--source", "bom_weekly"])
        with pytest.raises(SystemExit) as exc:
            task.main()
        assert exc.value.code == 2

    def test_cpc_row_floor_rejects_a_short_series(self, monkeypatch):
        # The CPC record is 918 months; a 100-row frame must fail the floor, not publish.
        with pytest.raises(SystemExit) as exc:
            self._run_main(
                monkeypatch,
                ["--source", "cpc_iodmi", "--publish-mode", "canonical", "--force-overwrite"],
                payload=_bytes(_GOLDEN), silver=_passing_silver("1950-01-01", 100),
            )
        assert exc.value.code == 1
