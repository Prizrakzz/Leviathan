"""Point-in-time availability rules for gold_v2 feature sources.

Each silver source arrives with its own date vocabulary: release dates,
week-ending dates, month-end statistics, position dates, and trade dates.  The
gold_v2 builder uses this adapter as the single place where those dates become
``feature_available_at`` timestamps.
"""
from __future__ import annotations

import pandas as pd

AVAILABILITY_COLUMNS = [
    "observation_date",
    "release_date",
    "feature_window_start",
    "feature_window_end",
    "feature_available_at",
    "source_vintage",
]


class AvailabilityError(ValueError):
    """A source does not expose enough date information for PIT use."""


def _dt(value: pd.Series | object) -> pd.Series:
    return pd.to_datetime(value, errors="coerce").dt.normalize()


def _first_date(df: pd.DataFrame, columns: list[str]) -> pd.Series | None:
    for column in columns:
        if column in df.columns:
            return _dt(df[column])
    return None


def _month_end_from_year_month(df: pd.DataFrame) -> pd.Series | None:
    if {"year", "month"} <= set(df.columns):
        year = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        month = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
        text = year.astype(str).str.zfill(4) + "-" + month.astype(str).str.zfill(2) + "-01"
        return _dt(pd.to_datetime(text, errors="coerce") + pd.offsets.MonthEnd(0))
    return None


def _month_end_from_year_text(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series.astype(str).str.slice(0, 7) + "-01", errors="coerce")
    return _dt(parsed + pd.offsets.MonthEnd(0))


def _coalesce(*series: pd.Series | None) -> pd.Series | None:
    usable = [value for value in series if value is not None]
    if not usable:
        return None
    result = usable[0].copy()
    for value in usable[1:]:
        result = result.fillna(value)
    return result


def _ensure(series: pd.Series | None, source_key: str, detail: str) -> pd.Series:
    if series is None or series.isna().all():
        raise AvailabilityError(f"{source_key}: cannot derive {detail}")
    return series


def _source_vintage(source_key: str, df: pd.DataFrame, release: pd.Series) -> pd.Series:
    if "source_vintage" in df.columns:
        existing = df["source_vintage"].astype("string")
        return existing.fillna(source_key)
    return source_key + ":" + release.dt.strftime("%Y-%m-%d").fillna("unknown")


def _fallback_window_dates(df: pd.DataFrame, observation: pd.Series) -> tuple[pd.Series, pd.Series]:
    start = _coalesce(
        _first_date(df, ["feature_window_start", "window_start", "period_start"]),
        observation,
    )
    end = _coalesce(
        _first_date(df, ["feature_window_end", "window_end", "period_end"]),
        observation,
    )
    return _ensure(start, "availability", "feature_window_start"), _ensure(
        end, "availability", "feature_window_end"
    )


def normalize_availability(source_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Return *df* with normalized PIT availability columns.

    Rules are source-level, not feature-level.  Unknown sources fail fast so a
    future feature cannot silently choose a convenient date policy.
    """
    out = df.copy()
    if out.empty:
        for column in AVAILABILITY_COLUMNS:
            out[column] = pd.Series(dtype="datetime64[ns]" if column != "source_vintage" else "string")
        return out

    key = source_key.lower().replace("-", "_")
    observation: pd.Series | None = None
    release: pd.Series | None = None
    available: pd.Series | None = None

    if key.startswith("weather:"):
        observation = _first_date(out, ["date", "period_start", "window_end"])
        observation = _ensure(observation, key, "observation_date")
        release = _coalesce(_first_date(out, ["release_date"]), observation + pd.Timedelta(days=7))
        available = release

    elif key == "production:faostat":
        if "year" not in out.columns:
            raise AvailabilityError(f"{source_key}: cannot derive annual observation date")
        years = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
        observation = _dt(pd.to_datetime(years.astype(str) + "-12-31", errors="coerce"))
        release = _coalesce(_first_date(out, ["release_date"]), observation + pd.Timedelta(days=365))
        available = release

    elif key == "psd":
        release = _first_date(out, ["release_date"])
        observation = _coalesce(_first_date(out, ["observation_date", "date"]), release)
        available = release

    elif key == "cot":
        observation = _first_date(out, ["report_date", "date"])
        release = _coalesce(_first_date(out, ["release_date"]), observation)
        available = release

    elif key in {"wasde", "wap_revisions", "sagis_cec"}:
        release = _coalesce(
            _first_date(out, ["release_date"]),
            _month_end_from_year_text(out["release_month"]) if "release_month" in out.columns else None,
        )
        observation = _coalesce(
            _first_date(out, ["observation_date", "date", "release_date"]),
            release,
        )
        available = release

    elif key == "nass_crop_progress":
        observation = _first_date(out, ["date", "week_ending"])
        release = observation
        available = observation

    elif key == "esr":
        observation = _first_date(out, ["week_ending_date", "week_ending", "date"])
        release = _coalesce(
            _first_date(out, ["as_of_date", "release_date"]),
            observation,
        )
        available = release

    elif key in {"fgis", "sagis_deliveries", "sagis_weekly"}:
        observation = _first_date(out, ["week_ending_date", "week_ending", "date"])
        release = _first_date(out, ["release_date"])
        available = release if release is not None else (
            observation + pd.Timedelta(days=7) if observation is not None else None
        )
        release = _coalesce(release, available)

    elif key == "pink_sheet":
        observation = _coalesce(_first_date(out, ["date"]), _month_end_from_year_month(out))
        observation = _ensure(observation, key, "month-end observation date")
        release = observation + pd.Timedelta(days=15)
        available = release

    elif key in {"oni", "iod"}:
        observation = _coalesce(_first_date(out, ["date"]), _month_end_from_year_month(out))
        observation = _ensure(observation, key, "month-end observation date")
        release = _coalesce(_first_date(out, ["release_date"]), observation + pd.Timedelta(days=15))
        available = release

    elif key == "fred_fx":
        observation = _first_date(out, ["date"])
        observation = _ensure(observation, key, "observation_date")
        release = _coalesce(_first_date(out, ["release_date"]), observation + pd.Timedelta(days=1))
        available = release

    elif key == "futures_prices":
        observation = _first_date(out, ["trade_date", "date"])
        available = observation + pd.Timedelta(days=1) if observation is not None else None
        release = available

    elif key in {"mpob", "mpoc", "mpoc_trade_stats_monthly", "mpoc_exports_by_country"}:
        observation = _coalesce(_first_date(out, ["date"]), _month_end_from_year_month(out))
        observation = _ensure(observation, key, "month-end observation date")
        release = observation + pd.Timedelta(days=15)
        available = release

    elif key == "unica":
        observation = _first_date(out, ["fortnight_date", "position_date", "date"])
        release = _coalesce(
            _first_date(out, ["source_position_date", "position_date", "release_date"]),
            observation,
        )
        available = release

    elif key == "conab":
        survey = (
            pd.to_numeric(out["survey_number"], errors="coerce")
            if "survey_number" in out.columns
            else pd.Series([1] * len(out), index=out.index)
        )
        release = _coalesce(
            _first_date(out, ["release_date", "report_date", "date"]),
            (
                _dt(
                    pd.to_datetime(
                        pd.to_numeric(out["safra_year"], errors="coerce").astype("Int64").astype(str)
                        + "-"
                        + survey.fillna(1).astype(int).astype(str).str.zfill(2)
                        + "-01",
                        errors="coerce",
                    )
                )
                if "safra_year" in out.columns
                else None
            ),
        )
        observation = _coalesce(_first_date(out, ["observation_date", "date"]), release)
        available = release

    elif key in {"nass_citrus", "ams_cotton_quality"}:
        release = _coalesce(
            _first_date(out, ["release_date", "report_date", "date"]),
            _month_end_from_year_month(out),
        )
        observation = _coalesce(_first_date(out, ["observation_date", "date"]), release)
        available = release

    else:
        raise AvailabilityError(f"{source_key}: unsupported availability source")

    observation = _ensure(observation, source_key, "observation_date")
    release = _ensure(release, source_key, "release_date")
    available = _ensure(available, source_key, "feature_available_at")
    window_start, window_end = _fallback_window_dates(out, observation)

    out["observation_date"] = observation
    out["release_date"] = release
    out["feature_window_start"] = window_start
    out["feature_window_end"] = window_end
    out["feature_available_at"] = available
    out["source_vintage"] = _source_vintage(source_key, out, release)
    return out
