"""Honest, bounded chart payloads for reader-first Silver EDA notebooks.

The module deliberately separates computation from Matplotlib rendering.  A
payload is small, JSON-compatible evidence with an explicit aggregation and
scope; figures are a presentation of that payload, never a second analytical
calculation.  Unsupported or underpowered plans return an omission payload
instead of silently falling back to a different question.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

MAX_SERIES = 12
MAX_DISTRIBUTION_POINTS = 5_000
MAX_DISTRIBUTION_SERIES = 4
MAX_HEATMAP_CELLS = 600
MAX_AXIS_TICKS = 8
MIN_LINE_POINTS = 8

UNIT_SENSITIVE_CHART_TYPES = frozenset(
    {
        "anomaly_heatmap",
        "calendar_heatmap",
        "change_distribution",
        "composition",
        "distribution",
        "dual_axis",
        "first_latest",
        "increment",
        "line",
        "milestone",
        "ranked_bar",
        "revision_distribution",
        "season_curve",
        "seasonal_profile",
        "signed_bar",
        "vintage_line",
        "year_over_year",
    }
)
FACET_CHART_TYPES = frozenset(
    {
        "change_distribution",
        "distribution",
        "increment",
        "line",
        "ranked_bar",
        "release_depth",
        "revision_distribution",
        "season_curve",
        "seasonal_profile",
        "vintage_line",
        "year_over_year",
    }
)

SUPPORTED_CHART_TYPES = frozenset(
    {
        "anomaly_heatmap",
        "calendar_heatmap",
        "change_distribution",
        "composition",
        "coverage_heatmap",
        "distribution",
        "dual_axis",
        "first_latest",
        "increment",
        "line",
        "milestone",
        "missingness_bar",
        "parity",
        "ranked_bar",
        "release_depth",
        "revision_distribution",
        "season_curve",
        "seasonal_profile",
        "signed_bar",
        "vintage_line",
        "year_over_year",
    }
)

_TIME_PRIORITY = (
    "release_date",
    "as_of_date",
    "week_ending_date",
    "report_date",
    "date",
    "position_date",
    "projection_month",
    "cocoa_year",
    "year",
)
_SEASON_PRIORITY = (
    "market_year",
    "marketing_year",
    "harvest_year",
    "crop_year",
    "season",
    "year",
)
_ENTITY_PRIORITY = (
    "commodity",
    "leviathan_slug",
    "commodity_name",
    "commodity_code",
    "country",
    "country_code",
    "country_name",
    "geography",
    "state",
    "state_region",
    "region",
    "department",
    "destination_country",
    "port",
    "coffee_type",
    "oil_type",
    "attribute",
    "row_label",
    "variable",
    "metric",
    "crop",
    "scope",
    "contract",
)
_REVISION_PRIORITY = (
    "revision",
    "revision_value",
    "revision_mmt",
    "change",
    "changes_1000mt",
)
_VINTAGE_DIMENSION_PRIORITY = (
    "marketing_year",
    "market_year",
    "crop_year",
    "harvest_year",
    "production_year",
    "season",
    "commodity",
    "crop",
    "country",
    "region",
    "state",
    "attribute",
    "row_label",
    "unit",
    "estimate_role",
    "projection_month",
    "table_type",
    "scope",
    "source_table_id",
)


class ChartOmission(ValueError):
    """A plan cannot be rendered honestly from the available evidence."""


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        timestamp = pd.Timestamp(value)
        return None if pd.isna(timestamp) else timestamp.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _chart_type(plan: Mapping[str, Any]) -> str:
    raw = str(plan.get("chart_type") or plan.get("type") or plan.get("kind") or "")
    aliases = {
        "histogram": "distribution",
        "missingness": "missingness_bar",
        "trend": "line",
        "timeseries": "line",
        "time_series": "line",
    }
    return aliases.get(raw.lower(), raw.lower())


def _plan_columns(plan: Mapping[str, Any], frame: pd.DataFrame) -> list[str]:
    raw: list[Any] = []
    for key in (
        "x",
        "y",
        "column",
        "value",
        "series",
        "group",
        "facet",
        "unit_column",
    ):
        if plan.get(key) is not None:
            raw.append(plan[key])
    for key in (
        "columns",
        "measures",
        "measure_columns",
        "series_dimensions",
        "split_by",
        "time_components",
    ):
        value = plan.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            raw.extend(value)
    return list(dict.fromkeys(str(value) for value in raw if str(value) in frame.columns))


def _is_time_name(name: str) -> bool:
    lower = name.lower()
    return any(
        token in lower
        for token in (
            "date",
            "year",
            "month",
            "week",
            "season",
            "period",
            "as_of",
            "survey",
        )
    )


def _time_column(frame: pd.DataFrame, columns: Sequence[str]) -> str | None:
    direct = next(
        (
            name
            for name in columns
            if name in frame.columns
            and (
                name.lower() == "date"
                or name.lower().endswith("_date")
                or name.lower()
                in {"as_of", "fortnight_date", "month_date", "week_ending"}
            )
        ),
        None,
    )
    if direct:
        return direct
    for name in (*columns, *_TIME_PRIORITY):
        if name in frame.columns and _is_time_name(name):
            return name
    datetime_columns = [
        str(name)
        for name in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[name])
    ]
    return datetime_columns[0] if datetime_columns else None


def _release_time_column(frame: pd.DataFrame, columns: Sequence[str]) -> str | None:
    """Prefer actual publication/vintage axes over marketing-year dimensions."""
    priority = (
        "release_date",
        "as_of_date",
        "report_date",
        "publication_date",
        "published_at",
        "release_time",
        "snapshot_date",
    )
    for name in priority:
        if name in frame.columns:
            return name
    for name in columns:
        lower = name.lower()
        if name in frame.columns and any(
            token in lower for token in ("release", "as_of", "publish", "report_date")
        ):
            return name
    return _time_column(frame, columns)


def _time_values(series: pd.Series, name: str) -> pd.Series:
    """Parse governed time shapes explicitly, without dateutil inference."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    if pd.api.types.is_numeric_dtype(series) and "year" in name.lower():
        years = pd.to_numeric(series, errors="coerce")
        text = years.round().astype("Int64").astype("string")
        return pd.to_datetime(text, format="%Y", errors="coerce")

    text = series.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    formats = (
        (text.str.match(r"^\d{4}-\d{2}-\d{2}(?:[ T].*)?$", na=False), "%Y-%m-%d", 10),
        (text.str.match(r"^\d{4}/\d{2}/\d{2}(?:[ T].*)?$", na=False), "%Y/%m/%d", 10),
        (text.str.match(r"^\d{8}$", na=False), "%Y%m%d", None),
        (text.str.match(r"^\d{4}-\d{2}$", na=False), "%Y-%m", None),
    )
    for mask, date_format, width in formats:
        if not mask.any():
            continue
        values = text.loc[mask].str.slice(0, width) if width else text.loc[mask]
        parsed.loc[mask] = pd.to_datetime(values, format=date_format, errors="coerce")

    remaining = parsed.isna()
    years = text.loc[remaining].str.extract(r"((?:19|20)\d{2})", expand=False)
    parsed.loc[remaining] = pd.to_datetime(years, format="%Y", errors="coerce")
    return parsed


def _ordered_values(series: pd.Series, name: str) -> pd.Series:
    parsed = _time_values(series, name)
    if parsed.notna().mean() >= 0.8:
        return parsed
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        return numeric.astype(float)
    return parsed


def _route_values(base: Mapping[str, Any], key: str) -> list[str]:
    route = base.get("_route") or {}
    value = route.get(key) if isinstance(route, Mapping) else None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _route_value(base: Mapping[str, Any], key: str) -> str | None:
    route = base.get("_route") or {}
    value = route.get(key) if isinstance(route, Mapping) else None
    return str(value) if value is not None and str(value) else None


def _route_max_series(base: Mapping[str, Any]) -> int:
    raw = _route_value(base, "max_series")
    try:
        value = int(raw) if raw is not None else MAX_SERIES
    except ValueError:
        value = MAX_SERIES
    return max(1, min(MAX_SERIES, value))


def _is_year_component(name: str) -> bool:
    lower = name.lower()
    return lower in {"calendar_year", "observation_year", "report_year", "year"}


def _is_month_component(name: str) -> bool:
    lower = name.lower()
    return lower in {
        "calendar_month",
        "month",
        "month_number",
        "observation_month",
        "report_month",
    }


def _composite_month_axis(
    frame: pd.DataFrame,
    year_column: str,
    month_column: str,
) -> pd.Series:
    years = pd.to_numeric(frame[year_column], errors="coerce")
    missing_years = years.isna()
    if missing_years.any():
        extracted = frame.loc[missing_years, year_column].astype("string").str.extract(
            r"((?:19|20)\d{2})",
            expand=False,
        )
        years.loc[missing_years] = pd.to_numeric(extracted, errors="coerce")

    month_text = frame[month_column].astype("string").str.strip().str.lower()
    months = pd.to_numeric(month_text, errors="coerce")
    month_names = {
        name: index
        for index, names in enumerate(
            (
                ("jan", "january"),
                ("feb", "february"),
                ("mar", "march"),
                ("apr", "april"),
                ("may",),
                ("jun", "june"),
                ("jul", "july"),
                ("aug", "august"),
                ("sep", "sept", "september"),
                ("oct", "october"),
                ("nov", "november"),
                ("dec", "december"),
            ),
            start=1,
        )
        for name in names
    }
    months = months.fillna(month_text.map(month_names))
    valid_month = months.between(1, 12) & months.eq(months.round())
    valid_year = years.between(1900, 2200) & years.eq(years.round())
    year_text = years.where(valid_year).round().astype("Int64").astype("string")
    month_text = (
        months.where(valid_month)
        .round()
        .astype("Int64")
        .astype("string")
        .str.zfill(2)
    )
    values = year_text + "-" + month_text + "-01"
    return pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")


def _materialize_time_axis(
    base: Mapping[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    release: bool = False,
) -> tuple[pd.DataFrame, str, str]:
    if release:
        time = _release_time_column(frame, columns)
        if time is None:
            raise ChartOmission("A release/as-of time column is required.")
        return frame, time, time

    configured = _route_values(base, "time_components")
    components = configured
    if not components:
        has_full_date = any(
            name.lower() == "date"
            or name.lower().endswith("_date")
            or name.lower() in {"as_of", "published_at", "timestamp"}
            for name in columns
        )
        if not has_full_date:
            year = next((name for name in columns if _is_year_component(name)), None)
            month = next((name for name in columns if _is_month_component(name)), None)
            if year and month:
                components = [year, month]
    if components:
        if len(components) == 1:
            component = components[0]
            if component not in frame.columns:
                raise ChartOmission(
                    f"Configured ordered-axis component {component!r} is missing."
                )
            return frame, component, component
        if len(components) != 2:
            raise ChartOmission(
                "time_components requires one ordered component or [year, month]."
            )
        missing = [name for name in components if name not in frame.columns]
        if missing:
            raise ChartOmission(
                "Composite monthly time is missing component columns: " + ", ".join(missing)
            )
        year = next((name for name in components if _is_year_component(name)), components[0])
        month = next(
            (name for name in components if _is_month_component(name)),
            components[1],
        )
        values = _composite_month_axis(frame, year, month)
        if values.notna().mean() < 0.8:
            raise ChartOmission(
                f"Composite {year}+{month} time is invalid for more than 20% of rows."
            )
        materialized = frame.copy()
        materialized["__reader_time_axis"] = values
        return materialized, "__reader_time_axis", f"{year}+{month}"

    time = _time_column(frame, columns)
    if time is None:
        raise ChartOmission("A governed time axis is required.")
    return frame, time, time


def _measure_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    configured: Sequence[str] = (),
) -> list[str]:
    configured = tuple(dict.fromkeys(map(str, configured)))
    if configured:
        missing = [name for name in configured if name not in frame.columns]
        nonnumeric = [
            name
            for name in configured
            if name in frame.columns and not pd.api.types.is_numeric_dtype(frame[name])
        ]
        if missing or nonnumeric:
            raise ChartOmission(
                "Configured measure columns are unavailable or nonnumeric: "
                + ", ".join([*missing, *nonnumeric])
            )
        return list(configured)

    def is_control(name: str) -> bool:
        lower = name.lower()
        return (
            _is_time_name(name)
            or lower.endswith(("_id", "_code", "_seq", "_number", "_num"))
            or lower.startswith("week_")
        )

    preferred = []
    for name in columns:
        if name not in frame or not pd.api.types.is_numeric_dtype(frame[name]):
            continue
        if is_control(name):
            continue
        preferred.append(name)
    fallback = []
    for name in map(str, frame.select_dtypes(include=[np.number]).columns):
        if is_control(name):
            continue
        fallback.append(name)
    return list(dict.fromkeys(preferred or fallback))


def _measure_scale_class(measure: str) -> str:
    lower = measure.lower()
    if "return" in lower or "change" in lower or "delta" in lower:
        return "change"
    if "ratio" in lower or "share" in lower or "percent" in lower or "pct" in lower:
        return "ratio"
    if "z_score" in lower or lower.endswith("_z") or "standardized" in lower:
        return "standardized"
    if "volatility" in lower or lower.startswith("vol_") or "_vol_" in lower:
        return "volatility"
    return "level"


def _normalized_governed_unit(value: Any) -> str:
    unit = str(value or "").strip().casefold()
    if not unit or "verify" in unit or "source-native" in unit:
        return ""
    return unit


def _overlay_compatibility(
    measures: Sequence[str],
    units: Mapping[str, Any],
) -> tuple[bool, str]:
    if len(measures) <= 1:
        return True, "one measure"
    governed_units = [_normalized_governed_unit(units.get(measure)) for measure in measures]
    if any(not unit for unit in governed_units):
        return False, "at least one measure has no governed unit"
    if len(set(governed_units)) != 1:
        return False, "measure units differ"
    scale_classes = {_measure_scale_class(measure) for measure in measures}
    if len(scale_classes) != 1:
        return False, "measure scale semantics differ"
    return True, "governed units and scale semantics match"


def _plan_units(
    plan: Mapping[str, Any],
    units: Mapping[str, Any] | None,
) -> dict[str, Any]:
    mapping = dict(units or {})
    configured = plan.get("measure_units")
    if isinstance(configured, Mapping):
        mapping.update({str(key): value for key, value in configured.items()})
    return mapping


def _split_measure_plans(
    frame: pd.DataFrame,
    plan: Mapping[str, Any],
    units: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return one plan per compatible governed-unit/scale group.

    A price level and a return, for example, are separate analytical questions
    even when their registry units are both incomplete.  The first split keeps
    the approved chart ID so existing evidence references remain stable.
    """
    kind = _chart_type(plan)
    if (
        kind not in {"change_distribution", "distribution", "line", "vintage_line"}
        or str(plan.get("status") or "ready").lower()
        not in {"ready", "supported", "pass", "available"}
    ):
        return [dict(plan)]
    columns = _plan_columns(plan, frame)
    measures = _measure_columns(frame, columns, plan.get("measure_columns") or ())[:3]
    if len(measures) <= 1:
        return [dict(plan)]

    grouped: dict[tuple[str, ...], list[str]] = {}
    for measure in measures:
        governed_unit = _normalized_governed_unit(units.get(measure))
        # An undeclared unit is never evidence that two measures are compatible.
        key = (
            ("governed", governed_unit, _measure_scale_class(measure))
            if governed_unit
            else ("undeclared", measure)
        )
        grouped.setdefault(key, []).append(measure)
    if len(grouped) == 1:
        return [dict(plan)]

    plans: list[dict[str, Any]] = []
    original_id = str(plan.get("chart_id") or plan.get("id") or "chart")
    original_title = str(plan.get("title") or original_id)
    for index, measure_group in enumerate(grouped.values()):
        split = dict(plan)
        for key in ("columns", "measures"):
            values = split.get(key)
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                split[key] = [
                    value
                    for value in values
                    if str(value) not in measures or str(value) in measure_group
                ]
        for key in ("column", "value", "y"):
            if str(split.get(key)) in measures:
                split[key] = measure_group[0]
        split["chart_id"] = (
            original_id
            if index == 0
            else f"{original_id}__{_safe_suffix(measure_group[0])}"
        )
        split["title"] = (
            f"{original_title} — "
            + ", ".join(measure.replace("_", " ") for measure in measure_group)
        )
        split["reader_measure_group"] = list(measure_group)
        plans.append(split)
    return plans


def _safe_suffix(value: Any) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_").lower()
    return suffix or "missing"


def _split_row_unit_plans(
    frame: pd.DataFrame,
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Split a unit-sensitive plan before any unit compatibility guard runs."""

    if _chart_type(plan) not in UNIT_SENSITIVE_CHART_TYPES:
        return [dict(plan)]
    unit_column = str(plan.get("unit_column") or "").strip()
    if not unit_column or unit_column not in frame.columns:
        return [dict(plan)]
    string_units = frame[unit_column].astype("string")
    stripped_units = string_units.str.strip()
    try:
        measures = _measure_columns(
            frame,
            _plan_columns(plan, frame),
            plan.get("measure_columns") or (),
        )
    except ChartOmission:
        measures = []
    contributing = (
        frame[measures].notna().any(axis=1)
        if measures
        else pd.Series(True, index=frame.index)
    )
    unit_counts = stripped_units.loc[
        stripped_units.notna() & stripped_units.ne("") & contributing
    ].value_counts(dropna=False)
    # The unsuffixed chart is the representative split.  Make that choice from
    # evidence (contributing rows), not lexical order: malformed rare labels
    # such as WASDE ``Con't`` must not displace the dominant reporting basis.
    values = sorted(
        (str(value) for value in unit_counts.index),
        key=lambda value: (
            -int(unit_counts.get(value, 0)),
            value.casefold(),
            value,
        ),
    )
    has_missing = bool(
        (contributing & string_units.isna()).any()
        or (contributing & string_units.str.strip().eq("").fillna(False)).any()
    )
    if len(values) <= 1 and not (values and has_missing):
        return [dict(plan)]

    original_id = str(plan.get("chart_id") or plan.get("id") or "chart")
    original_title = str(plan.get("title") or original_id)
    splits: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        split = dict(plan)
        split["reader_unit_value"] = value
        split["chart_id"] = (
            original_id
            if index == 0
            else f"{original_id}__unit_{_safe_suffix(value)}"
        )
        split["title"] = f"{original_title} — {unit_column}={value}"
        splits.append(split)
    if has_missing:
        split = dict(plan)
        split["reader_unit_missing"] = True
        split["chart_id"] = f"{original_id}__unit_missing"
        split["title"] = f"{original_title} — {unit_column}=<missing>"
        splits.append(split)
    return splits or [dict(plan)]


def _series_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    exclude: Iterable[str] = (),
    include_season: bool = False,
    include_vintage_dimensions: bool = False,
    configured: Sequence[str] = (),
    unit_column: str | None = None,
) -> list[str]:
    excluded = set(exclude)
    candidates: list[str] = []
    configured = tuple(dict.fromkeys(configured))
    missing = [name for name in configured if name not in frame.columns]
    if unit_column and unit_column not in frame.columns:
        missing.append(unit_column)
    if missing:
        raise ChartOmission(
            "Configured semantic series dimensions are missing: " + ", ".join(missing)
        )
    if configured:
        candidates.extend(configured)
    elif include_vintage_dimensions:
        candidates.extend(
            name for name in _VINTAGE_DIMENSION_PRIORITY if name in frame.columns
        )
    elif include_season:
        candidates.extend(name for name in _SEASON_PRIORITY if name in frame.columns)
    if not configured:
        candidates.extend(name for name in columns if name in _ENTITY_PRIORITY)
        candidates.extend(name for name in _ENTITY_PRIORITY if name in frame.columns)
    if unit_column and unit_column in frame.columns:
        candidates.append(unit_column)
    selected: list[str] = []
    for name in candidates:
        if name in excluded or name in selected:
            continue
        distinct = int(frame[name].nunique(dropna=True))
        if distinct > 1 or (configured and distinct > 0):
            selected.append(name)
        if not configured and not include_vintage_dimensions and len(selected) == 3:
            break
    return selected


def _routed_series_columns(
    base: Mapping[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    exclude: Iterable[str] = (),
    include_season: bool = False,
    vintage: bool = False,
) -> tuple[list[str], bool]:
    configured = list(
        dict.fromkeys(
            [
                *_route_values(base, "series_dimensions"),
                *_route_values(base, "split_by"),
            ]
        )
    )
    series = _series_columns(
        frame,
        columns,
        exclude=exclude,
        include_season=include_season,
        include_vintage_dimensions=vintage,
        configured=configured,
        unit_column=_route_value(base, "unit_column"),
    )
    return series, bool(configured or vintage)


def _apply_series(
    frame: pd.DataFrame,
    series_columns: Sequence[str],
    *,
    max_series: int | None = MAX_SERIES,
    strict: bool = False,
) -> tuple[pd.DataFrame, str]:
    work = frame.copy()
    if series_columns:
        labels = work[list(series_columns)].astype("string").fillna("<missing>")
        work["series"] = labels.apply(
            lambda row: " | ".join(
                f"{column}={row[column]}" for column in series_columns
            ),
            axis=1,
        )
    else:
        work["series"] = "all observations"
    counts = work["series"].value_counts(dropna=False)
    total = len(counts)
    if strict and max_series is not None and total > max_series:
        raise ChartOmission(
            f"The configured semantic grain produces {total:,} series, above the "
            f"{max_series}-series readability cap; no dimensions were dropped or pooled."
        )
    selected = sorted(
        counts.index.tolist(),
        key=lambda value: (-int(counts[value]), str(value)),
    )
    if max_series is not None:
        selected = selected[:max_series]
    work = work.loc[work["series"].isin(selected)].copy()
    dimensions = ", ".join(series_columns) if series_columns else "none"
    scope = (
        f"all {total} semantic series; label dimensions={dimensions}"
        if max_series is None or total <= max_series
        else (
            f"top {max_series} of {total} semantic series by contributing-row count; "
            f"excluded series={total - max_series}; label dimensions={dimensions}; no pooling"
        )
    )
    return work, scope


def _select_complete_series(
    frame: pd.DataFrame,
    *,
    base: Mapping[str, Any],
    position: str,
    required_positions: int,
    series_columns: Sequence[str],
    measure: str | None = None,
) -> tuple[pd.DataFrame, str]:
    total_series = int(frame["series"].nunique(dropna=False))
    if measure:
        by_measure = frame.groupby(["series", measure], dropna=False)[position].nunique()
        distinct_positions = by_measure.groupby("series").min()
    else:
        distinct_positions = frame.groupby("series", dropna=False)[position].nunique()
    complete = distinct_positions[distinct_positions >= required_positions]
    contributing = frame.groupby("series", dropna=False).size()
    ranked = pd.DataFrame(
        {
            "distinct_positions": complete,
            "contributing_rows": contributing.reindex(complete.index).fillna(0),
        }
    ).reset_index()
    ranked["series_sort"] = ranked["series"].astype(str)
    ranked = ranked.sort_values(
        ["distinct_positions", "contributing_rows", "series_sort"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    max_series = _route_max_series(base)
    selected = ranked["series"].head(max_series).tolist()
    result = frame.loc[frame["series"].isin(selected)].copy()
    complete_count = len(complete)
    underpowered_count = total_series - complete_count
    complete_excluded = max(0, complete_count - len(selected))
    dimensions = ", ".join(series_columns) if series_columns else "none"
    scope = (
        f"selected {len(selected):,} of {complete_count:,} complete semantic series by "
        "distinct-position count, contributing rows, then label; "
        f"excluded series={total_series - len(selected):,} "
        f"(complete but outside cap={complete_excluded:,}, "
        f"underpowered={underpowered_count:,}); "
        f"label dimensions={dimensions}; no pooling"
    )
    return result, scope


def _unit(measure: str | None, units: Mapping[str, Any]) -> str:
    if measure is None:
        return "rows"
    raw = str(units.get(measure) or "").strip()
    return raw if _normalized_governed_unit(raw) else "unit not declared"


def _base_payload(
    plan: Mapping[str, Any],
    provenance: Mapping[str, Any],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    source_rows = int(
        provenance.get("source_rows")
        or provenance.get("source_total_rows")
        or len(frame)
    )
    analysis_rows = int(provenance.get("analysis_rows") or len(frame))
    return {
        "_route": {
            "coverage_grain": plan.get("coverage_grain"),
            "intentional_points": bool(plan.get("intentional_points")),
            "max_series": plan.get("max_series"),
            "max_x_gap": plan.get("max_x_gap"),
            "measure_columns": list(plan.get("measure_columns") or []),
            "measure_units": dict(plan.get("measure_units") or {}),
            "minimum_rows": plan.get("minimum_rows"),
            "series_selection": plan.get("series_selection"),
            "series_dimensions": list(plan.get("series_dimensions") or []),
            "split_by": list(plan.get("split_by") or []),
            "time_components": list(plan.get("time_components") or []),
            "cutoff_mode": plan.get("cutoff_mode"),
            "unit_column": plan.get("unit_column"),
            "unit_filter": plan.get("reader_unit_value"),
            "unit_filter_missing": bool(plan.get("reader_unit_missing")),
        },
        "aggregation": "not computed",
        "analysis_rows": analysis_rows,
        "chart_id": str(plan.get("chart_id") or plan.get("id") or "chart"),
        "chart_type": _chart_type(plan),
        "exactness": str(provenance.get("exactness") or plan.get("exactness") or "exact"),
        "omission_reason": None,
        "plotted_rows": 0,
        "records": [],
        "scope": str(plan.get("scope") or "frozen analysis frame"),
        "source_rows": source_rows,
        "status": "omitted",
        "title": str(plan.get("title") or plan.get("chart_id") or "Chart"),
        "unit": "not applicable",
    }


def _omit(base: dict[str, Any], reason: str) -> dict[str, Any]:
    public = {key: value for key, value in base.items() if not key.startswith("_")}
    return {**public, "omission_reason": reason, "status": "omitted"}


def _ready(
    base: dict[str, Any],
    data: pd.DataFrame,
    *,
    aggregation: str,
    unit: str,
    scope: str,
    encoding: Mapping[str, Any],
) -> dict[str, Any]:
    if data.empty:
        raise ChartOmission("The supported transformation produced no finite chart values.")
    data = data.copy()
    encoding = dict(encoding)
    route = base.get("_route") or {}
    semantic_series = (
        data["semantic_series"]
        if "semantic_series" in data.columns
        else data["series"] if "series" in data.columns else pd.Series(dtype="string")
    )
    selected_series = sorted(
        {str(value) for value in semantic_series.dropna().unique()},
        key=str,
    )
    identify_selected_scope = (
        base.get("chart_type") in {"revision_distribution", "vintage_line"}
        and int(route.get("max_series") or MAX_SERIES) == 1
        and len(selected_series) == 1
        and selected_series[0] != "all observations"
    )
    if identify_selected_scope:
        scope = f"{scope}; selected semantic series={selected_series[0]}"
    split_dimensions = (
        list(route.get("split_by") or []) if isinstance(route, Mapping) else []
    )
    if (
        base.get("chart_type") in FACET_CHART_TYPES
        and "series" in data.columns
        and split_dimensions
    ):
        def display_parts(value: Any) -> tuple[str, str]:
            parts = str(value).split(" | ")
            facet_parts = [
                part
                for part in parts
                if any(part.startswith(f"{dimension}=") for dimension in split_dimensions)
            ]
            series_parts = [part for part in parts if part not in facet_parts]
            return (
                " | ".join(facet_parts) or "all scope",
                " | ".join(series_parts) or "all observations",
            )

        labels = data["series"].map(display_parts)
        data["semantic_series"] = data["series"]
        data["facet"] = labels.map(lambda value: value[0])
        data["series"] = labels.map(lambda value: value[1])
        encoding["facet"] = "facet"
    public = {key: value for key, value in base.items() if not key.startswith("_")}
    unit_filter = route.get("unit_filter") if isinstance(route, Mapping) else None
    if unit_filter is not None:
        unit_column = route.get("unit_column") or "unit"
        scope = f"{scope}; row filter {unit_column}={unit_filter}; no cross-unit pooling"
    return {
        **public,
        "aggregation": aggregation,
        "encoding": encoding,
        "omission_reason": None,
        "plotted_rows": int(len(data)),
        "records": _records(data),
        "selected_series": selected_series,
        "scope": scope,
        "status": "ready",
        "unit": unit,
    }


def _line_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    vintage: bool = False,
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(
        base,
        frame,
        columns,
        release=vintage,
    )
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:3]
    if not measures:
        raise ChartOmission("A time axis and at least one numeric measure are required.")
    series_columns, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, *measures),
        include_season=vintage,
        vintage=vintage,
    )
    work, series_scope = _apply_series(
        frame[[time, *measures, *series_columns]],
        series_columns,
        max_series=None,
    )
    work["__time"] = _ordered_values(work[time], time_label)
    long = work.melt(
        id_vars=["__time", "series"],
        value_vars=measures,
        var_name="measure",
        value_name="__value",
    ).rename(columns={"__value": "value"})
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["__time", "value"])
    configured_minimum = _route_value(base, "minimum_rows")
    try:
        reviewed_minimum = int(configured_minimum) if configured_minimum else None
    except ValueError:
        reviewed_minimum = None
    route = base.get("_route") or {}
    intentional_points = bool(
        route.get("intentional_points") if isinstance(route, Mapping) else False
    )
    if vintage:
        required = max(2, reviewed_minimum or 2)
    elif intentional_points:
        required = max(2, reviewed_minimum or 2)
    else:
        required = max(MIN_LINE_POINTS, reviewed_minimum or MIN_LINE_POINTS)
    long, series_scope = _select_complete_series(
        long,
        base=base,
        position="__time",
        required_positions=required,
        series_columns=series_columns,
        measure="measure",
    )
    if long.empty:
        raise ChartOmission(
            f"No preserved series has at least {required} distinct ordered observations."
        )
    grouped = (
        long.groupby(["__time", "series", "measure"], as_index=False)["value"]
        .median()
        .sort_values(["series", "measure", "__time"], kind="mergesort")
    )
    grouped = grouped.rename(columns={"__time": "x"})
    if grouped["series"].nunique(dropna=False) > 1 and any(
        str(units.get(measure) or "").strip()
        and not _normalized_governed_unit(units.get(measure))
        for measure in measures
    ):
        raise ChartOmission(
            "Multiple semantic series cannot share a raw overlay until the measure unit "
            "is governed; use unit-specific or normalized views."
        )
    aggregation = "median only within duplicate x/series/measure rows"
    if series_columns:
        aggregation += "; semantic series remain separate"
    max_x_gap = _route_value(base, "max_x_gap")
    scope = f"{series_scope}; time={time_label}; measures={', '.join(measures)}"
    encoding = {
        "measure": "measure",
        "series": "series",
        "x": "x",
        "x_label": time_label,
        "y": "value",
    }
    if max_x_gap is not None:
        threshold = float(max_x_gap)
        if not np.isfinite(threshold) or threshold <= 0:
            raise ChartOmission("max_x_gap must be a finite positive number.")
        encoding["max_x_gap"] = threshold
        scope += f"; line breaks where the x-axis gap exceeds {threshold:g}"
    return _ready(
        base,
        grouped,
        aggregation=aggregation,
        unit=_unit(measures[0], units),
        scope=scope,
        encoding=encoding,
    )


def _distribution_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    changes: bool = False,
    revisions: bool = False,
) -> dict[str, Any]:
    time: str | None = None
    time_label: str | None = None
    if changes or revisions:
        frame, time, time_label = _materialize_time_axis(
            base,
            frame,
            columns,
            release=revisions,
        )
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )
    if revisions:
        explicit = next((name for name in _REVISION_PRIORITY if name in frame.columns), None)
        measures = [explicit] if explicit else measures[:1]
    else:
        measures = measures[:3]
    if not measures:
        raise ChartOmission("No numeric measure is available for a distribution.")
    series_columns, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=measures,
        vintage=revisions,
    )
    selected = list(dict.fromkeys([*(series_columns or []), *( [time] if time else []), *measures]))
    work, series_scope = _apply_series(
        frame[selected],
        series_columns,
        max_series=min(MAX_DISTRIBUTION_SERIES, _route_max_series(base)),
        strict=False,
    )
    rows: list[pd.DataFrame] = []
    for measure in measures:
        part = work[[measure, "series"] + ([time] if time else [])].copy()
        part["value"] = pd.to_numeric(part[measure], errors="coerce")
        if changes or (revisions and measure not in _REVISION_PRIORITY and time):
            if time is None:
                raise ChartOmission("Changes require an ordered time column.")
            part["__time"] = _ordered_values(part[time], time_label or time)
            part = part.sort_values(["series", "__time"], kind="mergesort")
            part["value"] = part.groupby("series", dropna=False)["value"].diff()
        part = part.dropna(subset=["value"])
        part["measure"] = measure
        rows.append(part[["series", "measure", "value"]])
    long = pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan).dropna()
    if len(long) > MAX_DISTRIBUTION_POINTS:
        hashes = pd.util.hash_pandas_object(long, index=False)
        long = long.loc[hashes.sort_values(kind="mergesort").index[:MAX_DISTRIBUTION_POINTS]]
        plot_scope = f"deterministic {MAX_DISTRIBUTION_POINTS:,}-point plotting cap"
    else:
        plot_scope = "all finite values"
    label = "first differences within preserved series" if changes else "raw finite observations"
    if revisions:
        label = (
            "stored revision values"
            if measures[0] in _REVISION_PRIORITY
            else "first release-to-release differences within preserved vintage series"
        )
    return _ready(
        base,
        long,
        aggregation=f"{label}; no cross-series pooling; {plot_scope}",
        unit=(f"change in {_unit(measures[0], units)}" if changes else _unit(measures[0], units)),
        scope=(
            f"{series_scope}; measures={', '.join(measures)}"
            + (f"; time={time_label}" if time_label else "")
        ),
        encoding={"x": "value", "series": "series", "measure": "measure"},
    )


def _coverage_payload(
    base: dict[str, Any], frame: pd.DataFrame, columns: Sequence[str]
) -> dict[str, Any]:
    vintage_coverage = "vintage" in str(base.get("chart_id", "")).lower()
    frame, time, time_label = _materialize_time_axis(
        base,
        frame,
        columns,
        release=vintage_coverage,
    )
    entities, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time,),
        vintage=vintage_coverage,
    )
    work, series_scope = _apply_series(
        frame[[time, *entities]],
        entities,
        max_series=_route_max_series(base),
        strict=False,
    )
    parsed = _ordered_values(work[time], time_label)
    work = work.loc[parsed.notna()].copy()
    parsed = parsed.loc[parsed.notna()]
    configured_grain = (_route_value(base, "coverage_grain") or "").lower()
    series_count = max(1, int(work["series"].nunique(dropna=False)))
    max_time_buckets = max(1, MAX_HEATMAP_CELLS // series_count)
    if pd.api.types.is_datetime64_any_dtype(parsed):
        span_days = (parsed.max() - parsed.min()).days if not parsed.empty else 0
        use_month = configured_grain == "month" or (
            not configured_grain and span_days < 730
        )
        if use_month:
            work["x"] = parsed.dt.to_period("M").astype("string")
            bucket_policy = "calendar-month buckets"
        else:
            work["x"] = parsed.dt.year
            bucket_policy = "calendar-year buckets"
    else:
        work["x"] = parsed
        bucket_policy = "original ordered positions"
    work["y"] = work["series"]
    data = work.groupby(["y", "x"], as_index=False).size().rename(columns={"size": "value"})
    if len(data) > MAX_HEATMAP_CELLS:
        if pd.api.types.is_datetime64_any_dtype(parsed):
            years = parsed.dt.year
            unique_years = sorted(int(value) for value in years.dropna().unique())
            if len(unique_years) <= max_time_buckets:
                work["x"] = years
                bucket_policy = "calendar-year buckets selected to satisfy the cell cap"
            else:
                year_groups = {
                    year: min(
                        max_time_buckets - 1,
                        index * max_time_buckets // len(unique_years),
                    )
                    for index, year in enumerate(unique_years)
                }
                group_ranges: dict[int, tuple[int, int]] = {}
                for year, group in year_groups.items():
                    lower, upper = group_ranges.get(group, (year, year))
                    group_ranges[group] = (min(lower, year), max(upper, year))
                labels = {
                    group: str(lower) if lower == upper else f"{lower}–{upper}"
                    for group, (lower, upper) in group_ranges.items()
                }
                work["x"] = years.map(lambda value: labels[year_groups[int(value)]])
                bucket_policy = (
                    f"deterministic {len(group_ranges)}-bucket calendar-year ranges "
                    f"for the {MAX_HEATMAP_CELLS}-cell cap"
                )
        else:
            unique_positions = sorted(work["x"].dropna().unique(), key=str)
            position_groups = {
                value: min(
                    max_time_buckets - 1,
                    index * max_time_buckets // len(unique_positions),
                )
                for index, value in enumerate(unique_positions)
            }
            group_values: dict[int, list[Any]] = {}
            for value, group in position_groups.items():
                group_values.setdefault(group, []).append(value)
            labels = {
                group: (
                    str(values[0])
                    if len(values) == 1
                    else f"{values[0]}–{values[-1]}"
                )
                for group, values in group_values.items()
            }
            work["x"] = work["x"].map(
                lambda value: labels[position_groups[value]]
            )
            bucket_policy = (
                f"deterministic {len(group_values)}-bucket ordered ranges "
                f"for the {MAX_HEATMAP_CELLS}-cell cap"
            )
        data = (
            work.groupby(["y", "x"], as_index=False)
            .size()
            .rename(columns={"size": "value"})
        )
    return _ready(
        base,
        data,
        aggregation="exact contributing-row count by displayed time bucket and entity",
        unit="rows",
        scope=(
            f"{series_scope}; time={time_label}; "
            f"{bucket_policy}; {len(data):,} populated cells"
        ),
        encoding={
            "value": "value",
            "x": "x",
            "x_label": f"{time_label} bucket",
            "y": "y",
            "y_label": "+".join(entities) if entities else "all rows",
        },
    )


def _seasonal_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    if not measures:
        raise ChartOmission("Seasonal profiles require time and one numeric measure.")
    measure = measures[0]
    series_columns, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, measure),
    )
    work, series_scope = _apply_series(
        frame[[time, measure, *series_columns]],
        series_columns,
        max_series=None,
    )
    parsed = _time_values(work[time], time)
    work["x"] = parsed.dt.month
    work["value"] = pd.to_numeric(work[measure], errors="coerce")
    work = work.dropna(subset=["x", "value"])
    data = work.groupby(["series", "x"], as_index=False)["value"].mean()
    data, series_scope = _select_complete_series(
        data,
        base=base,
        position="x",
        required_positions=4,
        series_columns=series_columns,
    )
    if data.empty:
        raise ChartOmission(
            "No preserved series has at least four distinct seasonal positions."
        )
    return _ready(
        base,
        data,
        aggregation="mean by calendar month within each preserved entity series",
        unit=_unit(measure, units),
        scope=(
            f"{series_scope}; time={time_label}; measure={measure}; "
            f"contributing source rows={len(work):,}"
        ),
        encoding={
            "series": "series",
            "x": "x",
            "x_label": "calendar month",
            "y": "value",
        },
    )


def _heatmap_measure_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    anomaly: bool,
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    if not measures:
        raise ChartOmission("The heatmap requires time and one numeric measure.")
    measure = measures[0]
    entities = _series_columns(frame, columns, exclude=(time, measure))
    entity = entities[0] if entities else None
    work = frame[[time, measure] + ([entity] if entity else [])].copy()
    parsed = _time_values(work[time], time)
    work["value"] = pd.to_numeric(work[measure], errors="coerce")
    work["entity"] = work[entity].astype("string") if entity else "all observations"
    work["year"] = parsed.dt.year
    work["month"] = parsed.dt.month
    work["period"] = parsed.dt.to_period("M").astype("string")
    work = work.dropna(subset=["value", "year", "month"])
    if anomaly:
        baseline = work.groupby(["entity", "month"])["value"].transform("mean")
        work["value"] = work["value"] - baseline
        data = work.groupby(["entity", "period"], as_index=False)["value"].mean()
        data = data.rename(columns={"period": "x", "entity": "y"})
        aggregation = "monthly mean minus entity-specific calendar-month baseline"
    else:
        data = work.groupby(["entity", "year", "month"], as_index=False)["value"].mean()
        data["series"] = data.pop("entity")
        data = data.rename(columns={"month": "x", "year": "y"})
        aggregation = "mean by calendar year/month within each preserved entity series"
    if len(data) > MAX_HEATMAP_CELLS:
        raise ChartOmission(
            f"The requested heatmap has {len(data):,} populated cells; narrow its scope."
        )
    encoding = (
        {
            "value": "value",
            "x": "x",
            "x_label": "calendar period",
            "y": "y",
            "y_label": entity or "all observations",
        }
        if anomaly
        else {
            "series": "series",
            "value": "value",
            "x": "x",
            "x_label": "calendar month",
            "y": "y",
            "y_label": "calendar year",
        }
    )
    return _ready(
        base,
        data,
        aggregation=aggregation,
        unit=_unit(measure, units),
        scope=(
            f"time={time_label}; entity={entity or 'all observations'}; "
            f"measure={measure}"
        ),
        encoding=encoding,
    )


def _ranked_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    if not measures:
        raise ChartOmission("Latest ranking requires time and one numeric measure.")
    measure = measures[0]
    entities, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, measure),
    )
    if not entities:
        raise ChartOmission("Latest ranking requires an entity column.")
    work, series_scope = _apply_series(
        frame[[time, measure, *entities]],
        entities,
        max_series=_route_max_series(base),
        strict=False,
    )
    work["__time"] = _ordered_values(work[time], time_label)
    work["value"] = pd.to_numeric(work[measure], errors="coerce")
    work = work.dropna(subset=["__time", "value"])
    counts = work.groupby("__time")["series"].nunique()
    comparable = counts[counts >= 2]
    if comparable.empty:
        raise ChartOmission("No period contains at least two comparable entities.")
    latest = comparable.index.max()
    selected = work.loc[work["__time"].eq(latest)]
    data = (
        selected.groupby("series", as_index=False)["value"].median()
        .sort_values("value", kind="mergesort")
        .tail(15)
    )
    data["period"] = latest
    latest_label = (
        str(latest.date()) if isinstance(latest, pd.Timestamp) else str(latest)
    )
    return _ready(
        base,
        data,
        aggregation="latest comparable period only; median only within duplicate entity-period rows",
        unit=_unit(measure, units),
        scope=(
            f"{series_scope}; time={time_label}; latest comparable period={latest_label}; "
            f"measure={measure}"
        ),
        encoding={"x": "value", "y": "series", "period": "period"},
    )


def _year_over_year_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    if not measures:
        raise ChartOmission("Year-over-year movement requires monthly time and one measure.")
    measure = measures[0]
    series_columns, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, measure),
    )
    work, series_scope = _apply_series(
        frame[[time, measure, *series_columns]],
        series_columns,
        max_series=None,
    )
    work["period"] = _time_values(work[time], time).dt.to_period("M")
    work["value"] = pd.to_numeric(work[measure], errors="coerce")
    monthly = work.dropna(subset=["period", "value"]).groupby(
        ["series", "period"], as_index=False
    )["value"].median()
    prior = monthly.copy()
    prior["period"] = prior["period"] + 12
    prior = prior.rename(columns={"value": "prior_value"})
    joined = monthly.merge(prior, on=["series", "period"], how="inner")
    joined = joined.loc[joined["prior_value"].ne(0)].copy()
    joined["value"] = 100.0 * (joined["value"] / joined["prior_value"] - 1.0)
    joined["x"] = joined["period"].dt.to_timestamp()
    data = joined[["x", "series", "value"]].replace([np.inf, -np.inf], np.nan).dropna()
    data, series_scope = _select_complete_series(
        data,
        base=base,
        position="x",
        required_positions=MIN_LINE_POINTS,
        series_columns=series_columns,
    )
    if data.empty:
        raise ChartOmission(
            f"No preserved series has at least {MIN_LINE_POINTS} distinct YoY observations."
        )
    return _ready(
        base,
        data,
        aggregation="monthly median within preserved series; percent change versus exactly 12 months earlier",
        unit="percent year over year",
        scope=f"{series_scope}; time={time_label}; measure={measure}",
        encoding={
            "series": "series",
            "x": "x",
            "x_label": time_label,
            "y": "value",
        },
    )


def _composition_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:4]
    if not measures:
        raise ChartOmission("Composition requires at least one numeric measure.")
    compatible, reason = _overlay_compatibility(measures, units)
    if len(measures) > 1 and not compatible:
        raise ChartOmission(
            "Composition is unsafe because its component measures are incompatible: "
            + reason
            + "."
        )
    series_columns, strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, *measures),
    )
    selected_columns = [time, *measures, *series_columns]
    work, series_scope = _apply_series(
        frame[selected_columns],
        series_columns,
        strict=strict_series,
    )
    period_text = "all periods"
    work["__time"] = _ordered_values(work[time], time_label)
    usable = work.dropna(subset=["__time"])
    if usable.empty:
        raise ChartOmission("Composition has no parseable comparison period.")
    latest = usable["__time"].max()
    work = usable.loc[usable["__time"].eq(latest)].copy()
    period_text = (
        str(latest.date()) if isinstance(latest, pd.Timestamp) else str(latest)
    )
    if len(measures) > 1:
        long = work.melt(
            id_vars="series",
            value_vars=measures,
            var_name="component",
            value_name="__value",
        ).rename(columns={"__value": "value"})
        long["value"] = pd.to_numeric(long["value"], errors="coerce")
        data = long.groupby(["series", "component"], as_index=False)["value"].sum(min_count=1)
    else:
        data = work.groupby("series", as_index=False)[measures[0]].sum(min_count=1)
        data = data.rename(columns={"series": "component", measures[0]: "value"})
        data["series"] = "all observations"
    data = data.dropna(subset=["value"])
    totals = data.groupby("series")["value"].transform("sum")
    data = data.loc[totals.ne(0)].copy()
    data["share"] = data["value"] / totals[totals.ne(0)]
    data["period"] = period_text
    return _ready(
        base,
        data,
        aggregation="component sums and shares at the latest observed period; totals remain in payload",
        unit=_unit(measures[0], units),
        scope=(
            f"{series_scope}; time={time_label}; period={period_text}; "
            f"components={', '.join(measures)}"
        ),
        encoding={"x": "series", "y": "share", "component": "component", "total": "value"},
    )


def _season_curve_base(
    base: Mapping[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> tuple[pd.DataFrame, str, str, str, int]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    if not measures:
        raise ChartOmission("Season analysis requires time and one numeric measure.")
    measure = measures[0]
    season = next(
        (name for name in _SEASON_PRIORITY if name in frame.columns and name != time), None
    )
    series_columns, strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, measure),
        include_season=True,
    )
    if season and season not in series_columns:
        series_columns.insert(0, season)
    selected = list(dict.fromkeys([time, measure, *series_columns]))
    work, series_scope = _apply_series(
        frame[selected],
        series_columns,
        max_series=None,
    )
    parsed = _ordered_values(work[time], time_label)
    cutoff_mode = (_route_value(base, "cutoff_mode") or "").lower()
    if cutoff_mode == "within_series_ordinal" or (
        not cutoff_mode and pd.api.types.is_datetime64_any_dtype(parsed)
    ):
        work["__cutoff_order"] = parsed
        work["cutoff"] = work.groupby("series", dropna=False)[
            "__cutoff_order"
        ].rank(method="dense")
        cutoff_label = (
            "ordered report week within preserved market-year series "
            "(derived; not ISO week)"
        )
    elif pd.api.types.is_datetime64_any_dtype(parsed):
        raise ChartOmission(
            "A calendar date cannot be substituted for a governed within-season cutoff; "
            "configure within_series_ordinal or a declared numeric cutoff."
        )
    else:
        work["cutoff"] = pd.to_numeric(parsed, errors="coerce")
        cutoff_label = time_label
    work["value"] = pd.to_numeric(work[measure], errors="coerce")
    work = work.dropna(subset=["cutoff", "value"])
    data = work.groupby(["series", "cutoff"], as_index=False)["value"].median()
    data, series_scope = _select_complete_series(
        data,
        base=base,
        position="cutoff",
        required_positions=MIN_LINE_POINTS,
        series_columns=series_columns,
    )
    if data.empty:
        raise ChartOmission(
            f"No preserved series has at least {MIN_LINE_POINTS} distinct season cutoffs."
        )
    return data, measure, cutoff_label, series_scope, len(work)


def _season_curve_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    data, measure, time, series_scope, contributing = _season_curve_base(
        base,
        frame,
        columns,
    )
    if mode == "increment":
        data = data.sort_values(["series", "cutoff"], kind="mergesort")
        data["reset"] = data.groupby("series")["value"].diff().lt(0)
        data["value"] = data.groupby("series")["value"].diff()
        data = data.dropna(subset=["value"])
        aggregation = "first difference between consecutive cutoffs within each preserved season/entity series"
        unit = f"change in {_unit(measure, units)}"
    elif mode == "milestone":
        maximum = float(data["value"].max()) if not data.empty else np.nan
        thresholds = [25.0, 50.0, 75.0, 90.0] if maximum <= 110 else [
            maximum * 0.25,
            maximum * 0.5,
            maximum * 0.75,
        ]
        rows = []
        for series, group in data.groupby("series", sort=True):
            ordered = group.sort_values("cutoff", kind="mergesort")
            for threshold in thresholds:
                reached = ordered.loc[ordered["value"].ge(threshold)]
                if not reached.empty:
                    rows.append(
                        {"series": series, "threshold": threshold, "cutoff": reached.iloc[0]["cutoff"]}
                    )
        data = pd.DataFrame(rows)
        aggregation = "earliest within-series cutoff reaching each stated threshold"
        unit = "season cutoff"
    else:
        aggregation = "median only within duplicate season/entity/cutoff rows; series remain separate"
        unit = _unit(measure, units)
    encoding = (
        {
            "series": "series",
            "x": "threshold",
            "x_label": "milestone threshold",
            "y": "cutoff",
        }
        if mode == "milestone"
        else {
            "series": "series",
            "x": "cutoff",
            "x_label": time,
            "y": "value",
        }
    )
    return _ready(
        base,
        data,
        aggregation=aggregation,
        unit=unit,
        scope=(
            f"{series_scope}; time={time}; measure={measure}; "
            f"contributing source rows={contributing:,}"
        ),
        encoding=encoding,
    )


def _release_summary_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(
        base,
        frame,
        columns,
        release=True,
    )
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[:1]
    measure = measures[0] if measures else None
    series_columns, _strict_series = _routed_series_columns(
        base,
        frame,
        columns,
        exclude=(time, *measures),
        include_season=True,
        vintage=True,
    )
    selected = [time, *([measure] if measure else []), *series_columns]
    work, series_scope = _apply_series(
        frame[selected],
        series_columns,
        max_series=None,
    )
    work["__time"] = _time_values(work[time], time_label)
    work = work.dropna(subset=["__time"])
    work, series_scope = _select_complete_series(
        work,
        base=base,
        position="__time",
        required_positions=1 if mode == "release_depth" else 2,
        series_columns=series_columns,
    )
    if mode == "release_depth":
        data = work.groupby("series", as_index=False)["__time"].nunique()
        data = data.rename(columns={"__time": "value"}).sort_values("value").tail(20)
        aggregation = "distinct release/as-of count within each preserved season/entity series"
        unit = "releases"
        encoding = {"x": "value", "y": "series"}
    else:
        if measure is None:
            raise ChartOmission("First-to-latest movement requires a numeric estimate.")
        work["value"] = pd.to_numeric(work[measure], errors="coerce")
        work = work.dropna(subset=["value"]).sort_values(["series", "__time"])
        grouped = work.groupby("series", sort=True)["value"]
        data = grouped.agg(first="first", latest="last", release_count="size").reset_index()
        data = data.loc[data["release_count"].ge(2)].copy()
        data["delta"] = data["latest"] - data["first"]
        data = data.sort_values("delta", kind="mergesort").tail(20)
        aggregation = "first and latest finite estimates within each preserved vintage series"
        unit = _unit(measure, units)
        encoding = {"y": "series", "first": "first", "latest": "latest", "delta": "delta"}
    return _ready(
        base,
        data,
        aggregation=aggregation,
        unit=unit,
        scope=(
            f"{series_scope}; release_time={time_label}; "
            f"contributing source rows={len(work):,}"
        ),
        encoding=encoding,
    )


def _parity_payload(
    base: dict[str, Any], relationship_evidence: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    evidence = next(
        (
            item
            for item in relationship_evidence
            if item.get("relationship") == "silver_esr_to_silver_esr_compact"
        ),
        None,
    )
    if not evidence:
        raise ChartOmission("Bound raw/compact ESR relationship evidence is not attached.")
    if evidence.get("status") != "complete":
        raise ChartOmission(
            "Bound ESR parity evidence is incomplete: " + str(evidence.get("status"))
        )
    matched = int(evidence.get("matched_keys") or 0)
    raw_only = int(evidence.get("raw_only_keys") or 0)
    compact_only = int(evidence.get("compact_only_keys") or 0)
    raw_rows = int(evidence.get("raw_rows") or matched + raw_only)
    compact_rows = int(evidence.get("compact_rows") or matched + compact_only)
    parity = evidence.get("value_parity") or {}
    extension = evidence.get("compact_coverage_extension") or {}
    extension_note = str(extension.get("interpretation") or "").strip()
    if not extension_note:
        extension_note = (
            "No compact-only coverage extension is present."
            if compact_only == 0
            else (
                "Compact-only keys extend compact coverage beyond the raw frame and do not "
                "contradict shared-key parity."
                if not raw_only
                else "Compact-only keys are outside the shared-key value comparison."
            )
        )
    rows = [
        {"panel": "key coverage", "measure": "raw rows", "value": raw_rows},
        {"panel": "key coverage", "measure": "compact rows", "value": compact_rows},
        {"panel": "key coverage", "measure": "matched keys", "value": matched},
        {"panel": "key coverage", "measure": "raw-only keys", "value": raw_only},
        {
            "panel": "key coverage",
            "measure": "compact-only keys",
            "value": compact_only,
        },
    ]
    rows.extend(
        {
            "panel": "value parity",
            "measure": measure,
            "value": values.get("mismatch_rate"),
            "comparable_rows": values.get("comparable_rows"),
            "mismatch_rows": values.get("mismatch_rows"),
        }
        for measure, values in sorted(parity.items())
        if values.get("mismatch_rate") is not None
    )
    data = pd.DataFrame(rows)
    return _ready(
        base,
        data,
        aggregation="bound raw/compact key coverage plus governed value mismatch rates",
        unit="key counts; value parity is a rate",
        scope=(
            f"raw rows={raw_rows:,}; compact rows={compact_rows:,}; matched keys={matched:,}; "
            f"raw-only={raw_only:,}; compact-only={compact_only:,}; {extension_note}"
        ),
        encoding={"category": "measure", "panel": "panel", "value": "value"},
    )


def _missingness_payload(base: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        raise ChartOmission("Missingness has no positive row denominator.")
    data = pd.DataFrame(
        {
            "column": list(map(str, frame.columns)),
            "value": [float(frame[name].isna().mean()) for name in frame.columns],
        }
    )
    data = data.loc[data["value"].gt(0)].sort_values(["value", "column"]).tail(30)
    if data.empty:
        raise ChartOmission(
            "All assessed columns are complete; an all-zero missingness chart adds no information."
        )
    return _ready(
        base,
        data,
        aggregation="null rows divided by all analyzed rows for each displayed column",
        unit="null rate",
        scope=(
            f"top {len(data)} columns with non-zero null rate; "
            f"denominator={len(frame):,} rows"
        ),
        encoding={"x": "value", "y": "column"},
    )


def _signed_or_dual_payload(
    base: dict[str, Any],
    frame: pd.DataFrame,
    columns: Sequence[str],
    units: Mapping[str, Any],
    *,
    dual: bool,
) -> dict[str, Any]:
    frame, time, time_label = _materialize_time_axis(base, frame, columns)
    measures = _measure_columns(
        frame, columns, _route_values(base, "measure_columns")
    )[: (2 if dual else 1)]
    if len(measures) < (2 if dual else 1):
        raise ChartOmission("The chart requires an ordered axis and the planned numeric measure(s).")
    selected = frame[[time, *measures]].copy()
    selected["x"] = _ordered_values(selected[time], time_label)
    for measure in measures:
        selected[measure] = pd.to_numeric(selected[measure], errors="coerce")
    selected = selected.dropna(subset=["x", *measures])
    data = selected.groupby("x", as_index=False)[measures].median()
    if dual:
        data = data.rename(columns={measures[0]: "value_left", measures[1]: "value_right"})
        encoding = {
            "x": "x",
            "x_label": time_label,
            "left": "value_left",
            "right": "value_right",
        }
        unit = f"left={_unit(measures[0], units)}; right={_unit(measures[1], units)}"
    else:
        data = data.rename(columns={measures[0]: "value"})
        data["sign"] = np.where(data["value"].ge(0), "non-negative", "negative")
        encoding = {
            "x": "x",
            "x_label": time_label,
            "y": "value",
            "sign": "sign",
        }
        unit = _unit(measures[0], units)
    return _ready(
        base,
        data,
        aggregation="median only within duplicate time rows; no across-time aggregation",
        unit=unit,
        scope=f"time={time_label}; measures={', '.join(measures)}",
        encoding=encoding,
    )


def compute_chart_payload(
    frame: pd.DataFrame,
    plan: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    units: Mapping[str, Any] | None = None,
    relationship_evidence: Sequence[Mapping[str, Any]] = (),
    quarantine: bool = False,
) -> dict[str, Any]:
    """Compute one bounded chart payload or an explicit omission."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    base = _base_payload(plan, provenance, frame)
    kind = base["chart_type"]
    if quarantine:
        return _omit(base, "Generated-output values are quarantined from reader charts.")
    if str(plan.get("status") or "ready").lower() not in {
        "ready",
        "supported",
        "pass",
        "available",
    }:
        return _omit(base, str(plan.get("reason") or "The assessed plan is not ready."))
    if kind not in SUPPORTED_CHART_TYPES:
        return _omit(base, f"Unsupported approved chart type: {kind!r}.")
    unit_column = _route_value(base, "unit_column")
    unit_filter = (base.get("_route") or {}).get("unit_filter")
    unit_filter_missing = bool((base.get("_route") or {}).get("unit_filter_missing"))
    if unit_filter_missing:
        return _omit(
            base,
            f"Rows with missing {unit_column or 'unit'} cannot be assigned a compatible chart unit.",
        )
    if unit_filter is not None:
        if not unit_column or unit_column not in frame.columns:
            return _omit(base, "The configured row-unit filter column is missing.")
        normalized_units = frame[unit_column].astype("string").str.strip()
        frame = frame.loc[normalized_units.eq(str(unit_filter))].copy()
        if frame.empty:
            return _omit(
                base,
                f"No rows match the configured {unit_column}={unit_filter} unit filter.",
            )
    columns = _plan_columns(plan, frame)
    mapping = _plan_units(plan, units)
    if not plan.get("reader_measure_group") and len(
        _split_measure_plans(frame, plan, mapping)
    ) > 1:
        return _omit(
            base,
            "Multiple numeric measures require compute_chart_payloads so each scale "
            "is rendered separately.",
        )
    if unit_column and kind in UNIT_SENSITIVE_CHART_TYPES:
        if unit_column not in frame.columns:
            return _omit(base, f"Configured row-level unit column {unit_column!r} is missing.")
        row_units = sorted(
            {
                str(value).strip()
                for value in frame[unit_column].dropna().unique()
                if str(value).strip()
            }
        )
        if len(row_units) > 1:
            return _omit(
                base,
                f"The planned chart spans {len(row_units)} row-level units in "
                f"{unit_column!r}; incompatible units were not overlaid.",
            )
        if row_units:
            for measure in _measure_columns(
                frame,
                columns,
                _route_values(base, "measure_columns"),
            ):
                mapping.setdefault(measure, row_units[0])
    try:
        if kind == "line":
            return _line_payload(base, frame, columns, mapping)
        if kind == "vintage_line":
            return _line_payload(base, frame, columns, mapping, vintage=True)
        if kind == "distribution":
            return _distribution_payload(base, frame, columns, mapping)
        if kind == "change_distribution":
            return _distribution_payload(base, frame, columns, mapping, changes=True)
        if kind == "revision_distribution":
            return _distribution_payload(base, frame, columns, mapping, revisions=True)
        if kind == "coverage_heatmap":
            return _coverage_payload(base, frame, columns)
        if kind == "seasonal_profile":
            return _seasonal_payload(base, frame, columns, mapping)
        if kind == "anomaly_heatmap":
            return _heatmap_measure_payload(base, frame, columns, mapping, anomaly=True)
        if kind == "calendar_heatmap":
            return _heatmap_measure_payload(base, frame, columns, mapping, anomaly=False)
        if kind == "ranked_bar":
            return _ranked_payload(base, frame, columns, mapping)
        if kind == "year_over_year":
            return _year_over_year_payload(base, frame, columns)
        if kind == "composition":
            return _composition_payload(base, frame, columns, mapping)
        if kind in {"season_curve", "increment", "milestone"}:
            return _season_curve_payload(
                base, frame, columns, mapping, mode=kind
            )
        if kind in {"release_depth", "first_latest"}:
            return _release_summary_payload(
                base, frame, columns, mapping, mode=kind
            )
        if kind == "parity":
            return _parity_payload(base, relationship_evidence)
        if kind == "missingness_bar":
            return _missingness_payload(base, frame)
        if kind in {"signed_bar", "dual_axis"}:
            return _signed_or_dual_payload(
                base, frame, columns, mapping, dual=kind == "dual_axis"
            )
    except ChartOmission as exc:
        return _omit(base, str(exc))
    raise AssertionError(f"unrouted supported chart type: {kind}")


def compute_chart_payloads(
    frame: pd.DataFrame,
    plans: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    *,
    units: Mapping[str, Any] | None = None,
    relationship_evidence: Sequence[Mapping[str, Any]] = (),
    quarantine: bool = False,
    max_charts: int = 6,
) -> list[dict[str, Any]]:
    """Compute plans in stable order, including honest omission payloads.

    Each approved plan gets its primary measure first.  Additional measures are
    considered afterward, so scale separation cannot crowd out a distinct
    analytical question under the notebook chart cap.
    """
    payloads: list[dict[str, Any]] = []
    groups = []
    for plan in plans:
        if quarantine:
            groups.append([dict(plan)])
            continue
        measure_plans = _split_measure_plans(
            frame,
            plan,
            _plan_units(plan, units),
        )
        groups.append(
            [
                unit_plan
                for measure_plan in measure_plans
                for unit_plan in _split_row_unit_plans(frame, measure_plan)
            ]
        )
    ordered_plans = [group[0] for group in groups]
    ordered_plans.extend(split for group in groups for split in group[1:])
    ready_count = 0
    for plan in ordered_plans:
        payload = compute_chart_payload(
            frame,
            plan,
            provenance,
            units=units,
            relationship_evidence=relationship_evidence,
            quarantine=quarantine,
        )
        if payload["status"] == "ready":
            if ready_count >= max_charts:
                base = _base_payload(plan, provenance, frame)
                payload = _omit(
                    base,
                    f"Chart exceeds the {max_charts}-ready-chart notebook cap.",
                )
            else:
                ready_count += 1
        payloads.append(payload)
    return payloads


def chart_scope_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact scope register row shown below notebook figures."""
    return {
        "aggregation": payload.get("aggregation"),
        "chart": payload.get("chart_id"),
        "exactness": payload.get("exactness"),
        "plotted_rows": payload.get("plotted_rows"),
        "scope": payload.get("scope"),
        "source_rows": payload.get("source_rows"),
        "unit": payload.get("unit"),
    }


def _heatmap(
    ax: Any,
    frame: pd.DataFrame,
    encoding: Mapping[str, Any],
    unit: str,
    *,
    diverging: bool = False,
    limits: tuple[float, float] | None = None,
) -> None:
    x, y, value = encoding["x"], encoding["y"], encoding["value"]
    matrix = frame.pivot_table(index=y, columns=x, values=value, aggfunc="first")
    kwargs: dict[str, Any] = {}
    if limits is not None:
        kwargs.update(vmin=limits[0], vmax=limits[1])
    if diverging:
        maximum = float(np.nanmax(np.abs(matrix.values))) if matrix.size else 1.0
        kwargs.update(vmin=-maximum, vmax=maximum)
    image = ax.imshow(
        matrix.values,
        aspect="auto",
        cmap="RdBu_r" if diverging else "Blues",
        **kwargs,
    )
    x_indices = np.unique(
        np.linspace(
            0,
            max(0, len(matrix.columns) - 1),
            min(MAX_AXIS_TICKS, len(matrix.columns)),
        ).astype(int)
    )
    y_indices = np.unique(
        np.linspace(
            0,
            max(0, len(matrix.index) - 1),
            min(MAX_AXIS_TICKS, len(matrix.index)),
        ).astype(int)
    )
    ax.set_xticks(
        x_indices,
        [matrix.columns[index] for index in x_indices],
        rotation=45,
        ha="right",
    )
    ax.set_yticks(y_indices, [matrix.index[index] for index in y_indices])
    ax.figure.colorbar(image, ax=ax, label=unit)


def _bound_ordered_x_axis(ax: Any, *, temporal: bool) -> None:
    if temporal:
        locator = mdates.AutoDateLocator(
            minticks=3,
            maxticks=MAX_AXIS_TICKS,
            interval_multiples=True,
        )
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    else:
        ax.xaxis.set_major_locator(
            mticker.MaxNLocator(nbins=MAX_AXIS_TICKS, min_n_ticks=3)
        )


def _legend_label(labels: Any, group_names: Sequence[str]) -> str:
    values = labels if isinstance(labels, tuple) else (labels,)
    parts = []
    for name, value in zip(group_names, values):
        text = str(value)
        if name == "series" and text in {"all observations", "all scope"}:
            continue
        parts.append(text.replace("_", " ") if name == "measure" else text)
    return " | ".join(parts) or "all observations"


def _plot_ordered_line(
    ax: Any,
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    label: str,
    max_x_gap: Any = None,
) -> None:
    """Plot an ordered series without interpolating across declared x-axis gaps."""
    ordered = frame.sort_values(x, kind="mergesort")
    try:
        threshold = float(max_x_gap) if max_x_gap is not None else None
    except (TypeError, ValueError):
        threshold = None
    if threshold is None or not np.isfinite(threshold) or threshold <= 0:
        ax.plot(ordered[x], ordered[y], marker="o", markersize=2.5, label=label)
        return

    if pd.api.types.is_datetime64_any_dtype(ordered[x]):
        positions = pd.to_datetime(ordered[x], errors="coerce")
        gaps = positions.diff().dt.total_seconds().div(86_400)
    else:
        positions = pd.to_numeric(ordered[x], errors="coerce")
        gaps = positions.diff()
    segment_ids = gaps.gt(threshold).fillna(False).cumsum()
    for index, (_, segment) in enumerate(ordered.groupby(segment_ids, sort=False)):
        ax.plot(
            segment[x],
            segment[y],
            marker="o",
            markersize=2.5,
            label=label if index == 0 else "_nolegend_",
        )


def render_chart_payload(payload: Mapping[str, Any]) -> Figure | None:
    """Render one ready payload without recomputing its analytical values."""
    if payload.get("status") != "ready":
        return None
    frame = pd.DataFrame(payload.get("records") or [])
    if frame.empty:
        return None
    kind = str(payload["chart_type"])
    encoding = payload.get("encoding") or {}
    temporal_x_chart_types = {
        "dual_axis",
        "line",
        "signed_bar",
        "vintage_line",
        "year_over_year",
    }
    time_columns: set[str] = set()
    x_column = encoding.get("x")
    if kind in temporal_x_chart_types and x_column in frame.columns:
        column = str(x_column)
        label = str(encoding.get("x_label") or column)
        parsed = _time_values(frame[column], label)
        if parsed.notna().mean() >= 0.8:
            frame[column] = parsed
            time_columns.add(column)
    facet_column = encoding.get("facet")
    facets = (
        sorted(frame[facet_column].dropna().unique(), key=str)
        if facet_column in frame.columns and kind in FACET_CHART_TYPES
        else []
    )
    handled_facets = bool(facets)
    facet_axes: list[Any] = []
    if handled_facets:
        column_count = 1 if len(facets) == 1 else min(3, len(facets))
        row_count = int(np.ceil(len(facets) / column_count))
        fig, axes = plt.subplots(
            row_count,
            column_count,
            figsize=(5.2 * column_count, 3.2 * row_count + 1.2),
            squeeze=False,
        )
        flat_axes = list(axes.ravel())
        for facet, facet_ax in zip(facets, flat_axes):
            selected = frame.loc[frame[facet_column].eq(facet)]
            if kind in {
                "increment",
                "line",
                "season_curve",
                "seasonal_profile",
                "vintage_line",
                "year_over_year",
            }:
                x, y = encoding["x"], encoding["y"]
                groups = [
                    name
                    for name in (encoding.get("series"), encoding.get("measure"))
                    if name
                ]
                for labels, group in selected.groupby(groups, dropna=False, sort=True):
                    _plot_ordered_line(
                        facet_ax,
                        group,
                        x=x,
                        y=y,
                        label=_legend_label(labels, groups),
                        max_x_gap=encoding.get("max_x_gap"),
                    )
                if selected.groupby(groups, dropna=False).ngroups > 1:
                    facet_ax.legend(frameon=False, fontsize=7)
                facet_ax.set_xlabel(str(encoding.get("x_label") or x))
                facet_ax.set_ylabel(str(payload["unit"]))
            elif kind in {
                "change_distribution",
                "distribution",
                "revision_distribution",
            }:
                groups = ["series", "measure"]
                for labels, group in selected.groupby(groups, sort=True):
                    facet_ax.hist(
                        group["value"],
                        bins="auto",
                        histtype="step",
                        linewidth=1.5,
                        label=_legend_label(labels, groups),
                    )
                if selected.groupby(groups).ngroups > 1:
                    facet_ax.legend(frameon=False, fontsize=7)
                facet_ax.set_xlabel(str(payload["unit"]))
                facet_ax.set_ylabel("Rows")
            else:
                x, y = encoding["x"], encoding["y"]
                ordered = selected.sort_values(x, kind="mergesort")
                facet_ax.barh(ordered[y].astype(str), ordered[x], color="#356AA0")
                facet_ax.set_xlabel(str(payload["unit"]))
                facet_ax.set_ylabel(str(y))
            facet_ax.set_title(str(facet), fontsize=10)
            facet_axes.append(facet_ax)
        for unused in flat_axes[len(facets) :]:
            unused.set_visible(False)
        primary_ax = facet_axes[0]
    elif kind == "calendar_heatmap" and "series" in frame and frame["series"].nunique() > 1:
        series_values = sorted(frame["series"].dropna().unique(), key=str)[:4]
        fig, axes = plt.subplots(
            len(series_values),
            1,
            figsize=(10, 3.2 * len(series_values) + 1.2),
            squeeze=False,
        )
        limits = (float(frame[encoding["value"]].min()), float(frame[encoding["value"]].max()))
        for ax, series in zip(axes[:, 0], series_values):
            _heatmap(
                ax,
                frame.loc[frame["series"].eq(series)],
                encoding,
                str(payload["unit"]),
                limits=limits,
            )
            ax.set_title(str(series), fontsize=10)
        primary_ax = axes[0, 0]
    else:
        fig, primary_ax = plt.subplots(figsize=(9.5, 5.2))

    ax = primary_ax
    if handled_facets:
        pass
    elif kind in {"line", "vintage_line", "seasonal_profile", "year_over_year", "season_curve", "increment"}:
        x, y = encoding["x"], encoding["y"]
        groups = [name for name in (encoding.get("series"), encoding.get("measure")) if name]
        for labels, group in frame.groupby(groups, dropna=False, sort=True):
            label = _legend_label(labels, groups)
            _plot_ordered_line(
                ax,
                group,
                x=x,
                y=y,
                label=label,
                max_x_gap=encoding.get("max_x_gap"),
            )
        if frame.groupby(groups, dropna=False).ngroups > 1:
            ax.legend(frameon=False, fontsize=8, ncol=2)
        ax.set_xlabel(str(encoding.get("x_label") or x))
        ax.set_ylabel(str(payload["unit"]))
    elif kind in {"distribution", "change_distribution", "revision_distribution"}:
        for labels, group in frame.groupby(["series", "measure"], sort=True):
            ax.hist(group["value"], bins="auto", histtype="step", linewidth=1.5, label=" | ".join(map(str, labels)))
        if frame.groupby(["series", "measure"]).ngroups > 1:
            ax.legend(frameon=False, fontsize=7, ncol=2)
        ax.set_xlabel(str(payload["unit"])); ax.set_ylabel("Rows")
    elif kind in {"coverage_heatmap", "anomaly_heatmap"}:
        _heatmap(
            ax,
            frame,
            encoding,
            str(payload["unit"]),
            diverging=kind == "anomaly_heatmap",
        )
        ax.set_xlabel(str(encoding.get("x_label") or encoding["x"]))
        ax.set_ylabel(str(encoding.get("y_label") or encoding["y"]))
    elif kind == "calendar_heatmap":
        if frame["series"].nunique() == 1:
            _heatmap(ax, frame, encoding, str(payload["unit"]))
            ax.set_xlabel(str(encoding.get("x_label") or encoding["x"]))
            ax.set_ylabel(str(encoding.get("y_label") or encoding["y"]))
    elif kind in {"ranked_bar", "release_depth", "missingness_bar"}:
        x, y = encoding["x"], encoding["y"]
        ordered = frame.sort_values(x, kind="mergesort")
        ax.barh(ordered[y].astype(str), ordered[x], color="#356AA0")
        ax.set_xlabel(str(payload["unit"])); ax.set_ylabel(y)
    elif kind == "composition":
        pivot = frame.pivot_table(index="series", columns="component", values="share", aggfunc="first")
        pivot.plot.bar(stacked=True, ax=ax, colormap="tab20")
        ax.set_ylabel("Share of displayed total"); ax.legend(frameon=False, fontsize=8)
    elif kind == "milestone":
        for series, group in frame.groupby("series", sort=True):
            ax.scatter(group["threshold"], group["cutoff"], label=str(series))
        if frame["series"].nunique() > 1:
            ax.legend(frameon=False, fontsize=8)
        ax.set_xlabel("Threshold"); ax.set_ylabel("Earliest season cutoff")
    elif kind == "first_latest":
        ordered = frame.sort_values("delta", kind="mergesort").tail(20).reset_index(drop=True)
        positions = np.arange(len(ordered))
        ax.hlines(positions, ordered["first"], ordered["latest"], color="#9aa5b1")
        ax.scatter(ordered["first"], positions, label="first", color="#356AA0")
        ax.scatter(ordered["latest"], positions, label="latest", color="#D1495B")
        ax.set_yticks(positions, ordered["series"]); ax.legend(frameon=False)
        ax.set_xlabel(str(payload["unit"]))
    elif kind == "parity":
        coverage = frame.loc[frame["panel"].eq("key coverage")].copy()
        parity = frame.loc[frame["panel"].eq("value parity")].copy()
        bars = ax.barh(
            coverage["measure"].astype(str),
            pd.to_numeric(coverage["value"], errors="coerce"),
            color="#356AA0",
        )
        ax.set_xlabel("Rows / keys")
        ax.set_ylabel("Raw–compact coverage")
        for bar, value in zip(bars, coverage["value"]):
            ax.text(
                bar.get_width(),
                bar.get_y() + bar.get_height() / 2,
                f" {int(value):,}",
                va="center",
                fontsize=8,
            )
        if not parity.empty:
            parity_lines = [
                f"{row.measure}: mismatch {float(row.value):.2%} "
                f"(n={int(row.comparable_rows or 0):,})"
                for row in parity.itertuples()
            ]
            ax.text(
                0.99,
                0.02,
                "Value parity\n" + "\n".join(parity_lines),
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "alpha": 0.9},
            )
    elif kind == "signed_bar":
        colors = np.where(frame["value"].ge(0), "#356AA0", "#D1495B")
        ax.bar(frame["x"], frame["value"], color=colors)
        ax.axhline(0, color="#52606d", linewidth=0.8); ax.set_ylabel(str(payload["unit"]))
    elif kind == "dual_axis":
        ax.plot(frame["x"], frame["value_left"], color="#356AA0", marker="o", label="left")
        other = ax.twinx()
        other.plot(frame["x"], frame["value_right"], color="#D1495B", marker="s", label="right")
        ax.set_ylabel("left measure"); other.set_ylabel("right measure")
    else:  # pragma: no cover - SUPPORTED_CHART_TYPES and routing guard this.
        raise ValueError(f"No renderer for ready chart type {kind!r}")

    if kind in {
        "dual_axis",
        "increment",
        "line",
        "season_curve",
        "seasonal_profile",
        "signed_bar",
        "vintage_line",
        "year_over_year",
    }:
        for ordered_ax in facet_axes or [ax]:
            _bound_ordered_x_axis(ordered_ax, temporal=bool(time_columns))
    if time_columns:
        fig.autofmt_xdate(rotation=30, ha="right")
    title = str(payload["title"])
    selected_series = [str(value) for value in payload.get("selected_series") or []]
    if (
        kind in {"revision_distribution", "vintage_line"}
        and len(selected_series) == 1
        and selected_series[0] != "all observations"
    ):
        title += "\n" + selected_series[0]
    fig.suptitle(title, fontsize=13, y=0.985)
    # Keep the image itself readable.  Unit, aggregation, and detailed scope
    # remain available in the adjacent chart scope register and manifest.
    footer = (
        f"source n={int(payload['source_rows']):,}; analyzed n={int(payload['analysis_rows']):,}; "
        f"plotted n={int(payload['plotted_rows']):,}; exactness={payload['exactness']}"
    )
    fig.text(
        0.01,
        0.012,
        footer,
        fontsize=7.2,
        color="#52606d",
    )
    fig.tight_layout(rect=(0.015, 0.17, 0.99, 0.94))
    setattr(fig, "_leviathan_chart_payload", dict(payload))
    return fig


__all__ = [
    "SUPPORTED_CHART_TYPES",
    "chart_scope_record",
    "compute_chart_payload",
    "compute_chart_payloads",
    "render_chart_payload",
]
