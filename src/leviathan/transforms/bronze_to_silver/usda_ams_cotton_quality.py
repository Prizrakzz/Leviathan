"""USDA AMS Cotton Annual Quality bronze -> silver."""
from __future__ import annotations

import pandas as pd

OUTPUT_COLUMNS = [
    "commodity",
    "season",
    "geography",
    "percent_tenderable",
    "samples_classed",
    "avg_staple",
    "avg_micronaire",
    "avg_strength",
    "source_pages",
    "source_raw_key",
    "source_file_etag",
    "source",
]

_METRICS = [
    "percent_tenderable",
    "samples_classed",
    "avg_staple",
    "avg_micronaire",
    "avg_strength",
]
_NATIONAL_SCOPES = {"national_summary", "national_narrative"}


def _derive_national_rows_from_legacy_bronze(df: pd.DataFrame) -> pd.DataFrame:
    percent_pages = df.loc[df["metric"] == "percent_tenderable", "source_page"]
    if percent_pages.empty:
        return df.iloc[0:0].copy()

    summary_page = int(percent_pages.min())
    summary_metrics = set(df.loc[df["source_page"] == summary_page, "metric"].astype(str))
    accepted = (
        (df["source_page"] == summary_page)
        | (
            (df["source_page"] < summary_page)
            & df["metric"].astype(str).str.startswith("avg_")
            & ~df["metric"].astype(str).isin(summary_metrics)
        )
    )
    out = df.loc[accepted].copy()
    out["geography"] = "us_total"
    return out


def _accepted_national_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "extraction_scope" not in df.columns:
        frames = [
            _derive_national_rows_from_legacy_bronze(group)
            for _, group in df.groupby("season", dropna=False)
        ]
        if not frames:
            return df.iloc[0:0].copy()
        return pd.concat(frames, ignore_index=True)
    return df[
        (df["geography"].astype(str) == "us_total")
        & df["extraction_scope"].astype(str).isin(_NATIONAL_SCOPES)
    ].copy()


def transform_ams_cotton_quality_bronze_to_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    required = {"season", "geography", "metric", "value", "source_page"}
    missing = required - set(bronze.columns)
    if missing:
        raise ValueError(f"AMS cotton bronze missing required columns: {sorted(missing)}")
    if bronze.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = bronze.copy()
    df = df[df["metric"].isin(_METRICS)]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = _accepted_national_rows(df)
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    conflicts = (
        df.groupby(["season", "geography", "metric"], dropna=False)["value"]
        .nunique(dropna=True)
        .reset_index(name="n_values")
    )
    conflicts = conflicts[conflicts["n_values"] > 1]
    if not conflicts.empty:
        raise ValueError(
            "AMS cotton conflicting duplicate metric values: "
            f"{conflicts.head(5).to_dict(orient='records')}"
        )

    wide = (
        df.pivot_table(
            index=["season", "geography"],
            columns="metric",
            values="value",
            aggfunc="last",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for metric in _METRICS:
        if metric not in wide.columns:
            wide[metric] = pd.NA

    pages = (
        df.groupby(["season", "geography"], dropna=False)["source_page"]
        .apply(lambda values: ",".join(str(int(v)) for v in sorted(set(values))))
        .reset_index(name="source_pages")
    )
    provenance = (
        df.sort_values(["season", "geography", "source_page"])
        .drop_duplicates(["season", "geography"], keep="last")
        [["season", "geography", "source_raw_key", "source_file_etag"]]
        if {"source_raw_key", "source_file_etag"}.issubset(df.columns)
        else None
    )
    wide = wide.merge(pages, on=["season", "geography"], how="left")
    if provenance is not None:
        wide = wide.merge(provenance, on=["season", "geography"], how="left")
    else:
        wide["source_raw_key"] = pd.NA
        wide["source_file_etag"] = pd.NA
    wide["commodity"] = "cotton"
    wide["source"] = "usda_ams_cotton_classing_annual"

    return wide[OUTPUT_COLUMNS].reset_index(drop=True)
