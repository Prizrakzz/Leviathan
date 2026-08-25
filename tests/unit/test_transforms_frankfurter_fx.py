"""SILVER-F040 -- Frankfurter FX producer (the FROM-SCRATCH ``silver_fred_fx`` producer).

Per ADR-003 the source of record is Frankfurter (not FRED); ``source`` is stamped
truthfully. These tests pin: the series mapping + direction, base=USD enforcement, the
fail-closed conflict rule, the wide pivot + date grain, the 90-day CALENDAR-day
percent-change semantics, INV-4 (an absent currency stays a null column), determinism,
the INV-2 registry-reconciled schema, and the shadow-first publish path.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.transforms.bronze_to_silver.frankfurter_fx import (
    SILVER_ARROW_SCHEMA,
    SILVER_COLUMNS,
    build_fx_silver,
)
from leviathan.transforms.raw_to_bronze.frankfurter_fx import (
    BRONZE_COLUMNS,
    SOURCE,
    extract_fx_bronze,
)


def _json(rates: dict, base: str = "USD") -> bytes:
    return json.dumps({"amount": 1.0, "base": base,
                       "start_date": min(rates), "end_date": max(rates),
                       "rates": rates}).encode("utf-8")


# ---------------------------------------------------------------------------
# Bronze
# ---------------------------------------------------------------------------

class TestBronze:
    def test_maps_series_and_stamps_source(self):
        df = extract_fx_bronze(_json({
            "2004-12-31": {"BRL": 2.6577, "ARS": 2.9733, "CNY": 8.277},
        }))
        assert list(df.columns) == BRONZE_COLUMNS
        assert set(df["currency"]) == {"BRL", "ARS", "CNY"}
        assert (df["source"] == SOURCE).all()
        brl = df[df["currency"] == "BRL"].iloc[0]
        assert brl["rate_local_per_usd"] == pytest.approx(2.6577)

    def test_base_must_be_usd(self):
        with pytest.raises(ValueError, match="base must be USD"):
            extract_fx_bronze(_json({"2020-01-01": {"BRL": 4.0}}, base="EUR"))

    def test_empty_rates_raises(self):
        with pytest.raises(ValueError, match="no 'rates'"):
            extract_fx_bronze(json.dumps({"base": "USD", "rates": {}}).encode())

    def test_absent_currency_simply_missing(self):
        df = extract_fx_bronze(_json({"2020-01-01": {"BRL": 4.0, "CNY": 6.9}}))
        assert set(df["currency"]) == {"BRL", "CNY"}
        assert "ARS" not in set(df["currency"])

    def test_null_rate_skipped(self):
        # A null cell for a currency on a date is skipped (not coerced to 0).
        df = extract_fx_bronze(_json({"2020-01-01": {"BRL": 4.0, "ARS": None, "CNY": 6.9}}))
        assert set(df["currency"]) == {"BRL", "CNY"}


# ---------------------------------------------------------------------------
# Silver: pivot + grain + source
# ---------------------------------------------------------------------------

class TestSilverShape:
    def test_wide_columns_and_order(self):
        s = build_fx_silver(extract_fx_bronze(_json({
            "2020-01-01": {"BRL": 4.0, "ARS": 60.0, "CNY": 6.9},
        })))
        assert list(s.columns) == SILVER_COLUMNS

    def test_date_grain_unique(self):
        s = build_fx_silver(extract_fx_bronze(_json({
            "2020-01-01": {"BRL": 4.0}, "2020-01-02": {"BRL": 4.1},
        })))
        assert len(s) == s["date"].nunique() == 2

    def test_source_stamped(self):
        s = build_fx_silver(extract_fx_bronze(_json({"2020-01-01": {"BRL": 4.0}})))
        assert (s["source"] == SOURCE).all()

    def test_absent_currency_is_null_column(self):
        # ARS never returned -> ars_usd + its pct column present but all-null (INV-4).
        s = build_fx_silver(extract_fx_bronze(_json({
            "2020-01-01": {"BRL": 4.0, "CNY": 6.9},
            "2020-01-02": {"BRL": 4.1, "CNY": 6.95},
        })))
        assert "ars_usd" in s.columns and "ars_usd_pct_change_90d" in s.columns
        assert s["ars_usd"].isna().all()
        assert s["ars_usd_pct_change_90d"].isna().all()

    def test_weekends_not_synthesized(self):
        # Only the dates the source returns exist -- no gap-filling.
        s = build_fx_silver(extract_fx_bronze(_json({
            "2020-01-03": {"BRL": 4.0}, "2020-01-06": {"BRL": 4.1},  # skips the weekend
        })))
        assert sorted(s["date"]) == ["2020-01-03", "2020-01-06"]

    def test_pivot_rejects_conflicting_duplicate(self):
        # Feed a long bronze with a conflicting duplicate (date, currency) straight to silver.
        bad = pd.DataFrame({
            "date": ["2020-01-01", "2020-01-01"],
            "currency": ["BRL", "BRL"],
            "rate_local_per_usd": [4.0, 4.5],
            "source": [SOURCE, SOURCE],
        })
        with pytest.raises(ValueError):
            build_fx_silver(bad)


# ---------------------------------------------------------------------------
# Silver: the 90-day CALENDAR-day percent change
# ---------------------------------------------------------------------------

class TestPctChange90d:
    def _rates(self):
        return {
            "2020-01-01": {"BRL": 4.00},
            "2020-01-15": {"BRL": 4.10},
            "2020-04-01": {"BRL": 5.00},   # target 2020-01-02 -> last obs <= = 2020-01-01 (4.00)
            "2020-04-15": {"BRL": 5.20},   # target 2020-01-16 -> last obs <= = 2020-01-15 (4.10)
        }

    def test_early_dates_have_null_pct(self):
        s = build_fx_silver(extract_fx_bronze(_json(self._rates())))
        for d in ("2020-01-01", "2020-01-15"):
            v = s[s["date"] == d]["brl_usd_pct_change_90d"].iloc[0]
            assert math.isnan(v)

    def test_uses_last_obs_at_or_before_90d(self):
        s = build_fx_silver(extract_fx_bronze(_json(self._rates())))
        apr1 = s[s["date"] == "2020-04-01"]["brl_usd_pct_change_90d"].iloc[0]
        assert apr1 == pytest.approx(25.0)   # (5.00-4.00)/4.00*100
        apr15 = s[s["date"] == "2020-04-15"]["brl_usd_pct_change_90d"].iloc[0]
        assert apr15 == pytest.approx((5.20 - 4.10) / 4.10 * 100.0, abs=1e-4)

    def test_is_calendar_lag_not_obs_count(self):
        # Only 4 observations total; an obs-count(90) lag would yield ALL null. The
        # calendar-day lag yields non-null for the two April dates, proving it is calendar.
        s = build_fx_silver(extract_fx_bronze(_json(self._rates())))
        nonnull = s["brl_usd_pct_change_90d"].notna().sum()
        assert nonnull == 2

    def test_deterministic(self):
        raw = _json(self._rates())
        s1 = build_fx_silver(extract_fx_bronze(raw))
        s2 = build_fx_silver(extract_fx_bronze(raw))
        pd.testing.assert_frame_equal(s1, s2)


# ---------------------------------------------------------------------------
# INV-2 schema + shadow publish
# ---------------------------------------------------------------------------

_TARGET_TO_PA = {
    "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(),
    "bool": pa.bool_(), "date32[day]": pa.date32(), "timestamp[us]": pa.timestamp("us"),
}


def test_silver_schema_matches_registry():
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_fred_fx")
    expected = {c["name"]: _TARGET_TO_PA[c["target_arrow_type"]]
                for c in contract["physical_columns"]}
    actual = {f.name: f.type for f in SILVER_ARROW_SCHEMA}
    assert actual == expected


def _dense_rates(n_days: int = 500) -> dict:
    d0 = date(2020, 1, 1)
    rates = {}
    for i in range(n_days):
        d = (d0 + timedelta(days=i)).isoformat()
        rates[d] = {"BRL": 4.0 + i * 0.001, "ARS": 60.0 + i * 0.05, "CNY": 6.9 + i * 0.0005}
    return rates


class _MiniS3:
    """Minimal in-memory S3 (put/copy/keys) -- the shadow-first publisher's flat path only
    calls put_object (shadow object + manifest) and copy_object (canonical promotion)."""

    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body, "utf-8")
        return {"ETag": '"x"'}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        self.store[(Bucket, Key)] = self.store[(CopySource["Bucket"], CopySource["Key"])]
        return {}

    def keys(self):
        return sorted(k for _, k in self.store)


class TestPublish:
    def _fake_s3(self):
        return _MiniS3()

    def test_count_equals_distinct_dates(self):
        s = build_fx_silver(extract_fx_bronze(_json(_dense_rates(120))))
        assert len(s) == s["date"].nunique()

    def test_dryrun_and_shadow_publish(self):
        from jobs.batch._sb_producer_publish import publish_flat_silver

        s = build_fx_silver(extract_fx_bronze(_json(_dense_rates(500))))
        # All 6 value columns must clear the 0.5 non-null floor on a dense 500-day series.
        for c in ("brl_usd", "ars_usd", "cny_usd",
                  "brl_usd_pct_change_90d", "ars_usd_pct_change_90d", "cny_usd_pct_change_90d"):
            assert s[c].notna().mean() > 0.5, c

        for argv, expect_keys in [(["p"], 1), (["p", "--publish-mode", "shadow"], 2)]:
            fs = self._fake_s3()
            m = publish_flat_silver(
                table_name="silver_fred_fx", df=s, job="t",
                canonical_key="silver/fred_fx/part-000.parquet",
                bucket="leviathan-test", s3_client=fs, argv=argv,
            )
            assert m.validation_result["ok"] is True
            assert m.state.value == "VALIDATED"
            assert len(fs.keys()) == expect_keys


class TestPublishIdentityResolution:
    """publish_flat_silver resolves a blank caller identity via STS (BF-W3 FX live-caught:
    the guard's canonical environment check fails closed on empty account/role, and dry-run/
    shadow never reach it, so T1-T5 cannot expose the gap)."""

    def test_blank_identity_resolved_via_sts(self, monkeypatch):
        import boto3

        import jobs.batch._sb_producer_publish as sbp

        class _Sts:
            def get_caller_identity(self):
                return {"Account": "668891723125",
                        "Arn": "arn:aws:sts::668891723125:assumed-role/"
                               "leviathan-dev-batch-job-role/job"}

        monkeypatch.setattr(boto3, "client", lambda *a, **k: _Sts())
        captured = {}

        def fake_authorize(target, **kw):
            captured["target"] = target
            raise RuntimeError("stop-here")  # surgical: identity plumbing only

        monkeypatch.setattr(sbp, "authorize_publish", fake_authorize)
        # FX-1 (2026-08-25): build the fixture off SILVER_COLUMNS so the frame tracks the currency
        # roster instead of hand-listing three of thirteen (the exact drift the widening exposed).
        from leviathan.transforms.bronze_to_silver.frankfurter_fx import SILVER_COLUMNS
        row = {c: [float("nan")] for c in SILVER_COLUMNS}
        row.update({"date": ["2026-01-02"], "brl_usd": [5.0], "cny_usd": [7.0],
                    "source": ["frankfurter"]})
        df = pd.DataFrame(row)
        with pytest.raises(RuntimeError, match="stop-here"):
            sbp.publish_flat_silver(table_name="silver_fred_fx", df=df, job="t",
                                    canonical_key="silver/fred_fx/part-000.parquet",
                                    bucket="b", s3_client=None, argv=["prog"])
        assert captured["target"].account_id == "668891723125"
        assert "leviathan-dev-batch-job-role" in captured["target"].role_arn


# ---------------------------------------------------------------------------
# D-SG G1-4 -- the bounded backoff in front of the one GET this leg makes
# ---------------------------------------------------------------------------

class TestFrankfurterRetry:
    """Two Cloudflare 5xx in four days each burned a whole daily fire (2026-08-08, 2026-08-11).

    The contract pinned here: three tries, 30 s then 120 s, on 5xx (Cloudflare's 520/522 included)
    and on transport faults -- and NEVER on a 4xx, which is the vendor saying the request is wrong.
    ``sleep`` is injected, so the schedule is asserted without the suite waiting 150 seconds."""

    @staticmethod
    def _task():
        from jobs.batch import frankfurter_fx_task
        return frankfurter_fx_task

    @staticmethod
    def _response(task, code: int, reason: str = "x", content: bytes = b"{}"):
        class R:
            def __init__(self):
                self.status_code, self.reason, self.content = code, reason, content

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise task.requests.HTTPError(str(self.status_code), response=self)
        return R()

    def test_a_cloudflare_520_is_retried_then_succeeds(self, monkeypatch):
        T = self._task()
        calls, sleeps = [], []
        seq = [self._response(T, 520), self._response(T, 522), self._response(T, 200)]
        monkeypatch.setattr(T.requests, "get",
                            lambda url, timeout: (calls.append(url), seq.pop(0))[1])
        resp = T._get_with_retry("https://x", sleep=sleeps.append)
        assert resp.status_code == 200
        assert len(calls) == 3 and sleeps == [30, 120]

    def test_a_404_is_never_retried(self, monkeypatch):
        T = self._task()
        calls, sleeps = [], []
        monkeypatch.setattr(T.requests, "get",
                            lambda url, timeout: (calls.append(url),
                                                  self._response(T, 404, "Not Found", b""))[1])
        with pytest.raises(T.requests.HTTPError):
            T._get_with_retry("https://x", sleep=sleeps.append)
        assert len(calls) == 1 and sleeps == []

    def test_three_consecutive_5xx_reraise_the_last(self, monkeypatch):
        T = self._task()
        sleeps = []
        monkeypatch.setattr(T.requests, "get",
                            lambda url, timeout: self._response(T, 522, "Origin Down", b""))
        with pytest.raises(T.requests.HTTPError):
            T._get_with_retry("https://x", sleep=sleeps.append)
        assert sleeps == [30, 120]

    def test_a_connection_fault_is_retried(self, monkeypatch):
        T = self._task()
        sleeps, calls = [], []

        def _boom(url, timeout):
            calls.append(url)
            if len(calls) < 3:
                raise T.requests.ConnectionError("reset by peer")
            return self._response(T, 200)

        monkeypatch.setattr(T.requests, "get", _boom)
        assert T._get_with_retry("https://x", sleep=sleeps.append).status_code == 200
        assert sleeps == [30, 120]
