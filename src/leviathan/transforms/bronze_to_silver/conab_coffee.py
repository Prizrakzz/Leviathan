"""CONAB coffee XLS bronze -> revision-aware silver."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

import pandas as pd

PARSER_VERSION = "conab_coffee_silver_v3"

OUTPUT_COLUMNS = [
    "commodity",
    "country",
    "safra_year",
    "survey_number",
    "region",
    "region_raw",
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
    "area_revision_ha",
    "yield_revision_bags_per_ha",
    "production_revision_thousand_bags",
    "production_revision_pct",
    "production_revision_streak",
    "is_repeated_survey",
    "repeated_from_survey_number",
    "survey_content_fingerprint",
    "source_raw_key",
    "source_file_etag",
    "worksheet",
    "parser_version",
    "source",
]

_ELEMENTS = {
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
}
_PRODUCTION_SHEET_MARKERS = {
    "arabica_coffee": ("arabica", "arabica"),
    "robusta_coffee": ("conilon", "robusta"),
}
_NON_PRODUCTION_SHEET_MARKERS = ("area", "cafeeiros", "colheita", "total")


def _snake(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    aliases = {
        "brasil": "brazil",
        "brazil": "brazil",
        "minas gerais": "minas_gerais",
        "espirito santo": "espirito_santo",
        "sao paulo": "sao_paulo",
        "rio de janeiro": "rio_de_janeiro",
        "bahia": "bahia",
        "parana": "parana",
        "rondonia": "rondonia",
        "mato grosso": "mato_grosso",
        "goias": "goias",
    }
    text = aliases.get(text, text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _is_production_sheet(commodity: str, worksheet: str) -> bool:
    """Return whether a CONAB worksheet is the accepted production estimate sheet.

    CONAB workbooks include total-coffee aggregates, area-only sheets, tree-count
    sheets, and harvest-progress sheets.  Silver keeps only the commodity-specific
    production-estimate sheets so one survey has one accepted table per commodity.
    """
    normalized = _snake(worksheet)
    if not normalized:
        return True
    if any(marker in normalized for marker in _NON_PRODUCTION_SHEET_MARKERS):
        return False
    return any(marker in normalized for marker in _PRODUCTION_SHEET_MARKERS.get(commodity, ()))


def _fingerprint(group: pd.DataFrame) -> str:
    cols = [
        "commodity",
        "safra_year",
        "region",
        "area_in_production_ha",
        "yield_bags_per_ha",
        "production_thousand_bags",
    ]
    payload = (
        group[cols]
        .sort_values(["commodity", "region"])
        .round(8)
        .to_dict(orient="records")
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _revision_streak(values: pd.Series) -> pd.Series:
    last_sign = 0
    streak = 0
    out: list[int] = []
    for value in values.fillna(0):
        sign = 1 if value > 0 else (-1 if value < 0 else 0)
        if sign and sign == last_sign:
            streak += 1
        elif sign:
            streak = 1
        else:
            streak = 0
        last_sign = sign if sign else last_sign
        out.append(streak)
    return pd.Series(out, index=values.index)


def _mark_repeated_surveys(wide: pd.DataFrame) -> pd.DataFrame:
    wide = wide.copy()
    wide["is_repeated_survey"] = False
    wide["repeated_from_survey_number"] = pd.Series(pd.NA, index=wide.index, dtype="Int64")

    group_cols = ["commodity", "safra_year"]
    fingerprints = (
        wide.groupby(group_cols + ["survey_number"], dropna=False)["survey_content_fingerprint"]
        .first()
        .reset_index()
        .sort_values(group_cols + ["survey_number"])
    )

    for _, group in fingerprints.groupby(group_cols, dropna=False):
        previous_fingerprint: str | None = None
        previous_survey: int | None = None
        seen: dict[str, int] = {}
        for row in group.itertuples(index=False):
            fingerprint = str(row.survey_content_fingerprint)
            survey_number = int(row.survey_number)
            if fingerprint == previous_fingerprint and previous_survey is not None:
                mask = (
                    (wide["commodity"] == row.commodity)
                    & (wide["safra_year"] == row.safra_year)
                    & (wide["survey_number"] == survey_number)
                )
                wide.loc[mask, "is_repeated_survey"] = True
                wide.loc[mask, "repeated_from_survey_number"] = previous_survey
            elif fingerprint in seen:
                raise ValueError(
                    "CONAB non-consecutive repeated survey table detected: "
                    f"commodity={row.commodity} safra_year={row.safra_year} "
                    f"survey_number={survey_number} repeated_from={seen[fingerprint]}"
                )
            seen[fingerprint] = survey_number
            previous_fingerprint = fingerprint
            previous_survey = survey_number
    return wide


def transform_conab_coffee_bronze_to_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    required = {"safra_year", "survey", "commodity", "region", "element", "value"}
    missing = required - set(bronze.columns)
    if missing:
        raise ValueError(f"CONAB bronze missing required columns: {sorted(missing)}")
    if bronze.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = bronze.copy()
    df["element"] = df["element"].astype(str)
    df = df[df["element"].isin(_ELEMENTS)]
    df = df[df["commodity"].isin(["arabica_coffee", "robusta_coffee"])]
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["survey_number"] = pd.to_numeric(df["survey"], errors="raise").astype(int)
    df["safra_year"] = pd.to_numeric(df["safra_year"], errors="raise").astype(int)
    df["region_raw"] = df["region"].astype(str)
    df["region"] = df["region"].map(_snake)
    df["worksheet"] = df.get("sheet_name", "").astype(str) if "sheet_name" in df.columns else ""
    df = df[
        df.apply(
            lambda row: _is_production_sheet(str(row["commodity"]), str(row["worksheet"])),
            axis=1,
        )
    ]
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df["source_raw_key"] = df.get("source_raw_key", pd.Series([None] * len(df))).astype("string")
    df["source_file_etag"] = df.get("source_file_etag", pd.Series([None] * len(df))).astype("string")

    index_cols = [
        "commodity",
        "safra_year",
        "survey_number",
        "region",
        "region_raw",
        "source_raw_key",
        "source_file_etag",
        "worksheet",
    ]
    conflicts = (
        df.groupby(index_cols + ["element"], dropna=False)["value"]
        .nunique(dropna=True)
        .reset_index(name="n_values")
    )
    conflicts = conflicts[conflicts["n_values"] > 1]
    if not conflicts.empty:
        raise ValueError(
            "CONAB conflicting duplicate values before pivot: "
            f"{conflicts.head(5).to_dict(orient='records')}"
        )

    wide = (
        df.pivot_table(
            index=index_cols,
            columns="element",
            values="value",
            aggfunc="last",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for col in _ELEMENTS:
        if col not in wide.columns:
            wide[col] = pd.NA

    wide["country"] = "brazil"
    wide["parser_version"] = PARSER_VERSION
    wide["source"] = "conab_xls"

    group_cols = ["commodity", "safra_year"]
    wide["survey_content_fingerprint"] = ""
    for _, group in wide.groupby(group_cols + ["survey_number"], dropna=False):
        wide.loc[group.index, "survey_content_fingerprint"] = _fingerprint(group)

    wide = _mark_repeated_surveys(wide)

    wide = wide.sort_values(["commodity", "region", "safra_year", "survey_number"])
    base_cols = [
        "area_in_production_ha",
        "yield_bags_per_ha",
        "production_thousand_bags",
    ]
    grouped = wide.groupby(["commodity", "region", "safra_year"], dropna=False)
    for col in base_cols:
        wide[f"_{col}_initial"] = grouped[col].transform("first")
    wide["area_revision_ha"] = wide["area_in_production_ha"] - wide["_area_in_production_ha_initial"]
    wide["yield_revision_bags_per_ha"] = wide["yield_bags_per_ha"] - wide["_yield_bags_per_ha_initial"]
    wide["production_revision_thousand_bags"] = (
        wide["production_thousand_bags"] - wide["_production_thousand_bags_initial"]
    )
    initial = wide["_production_thousand_bags_initial"].replace({0: pd.NA})
    wide["production_revision_pct"] = wide["production_revision_thousand_bags"] / initial
    wide["_adjacent_revision"] = grouped["production_thousand_bags"].diff()
    wide["production_revision_streak"] = (
        wide.groupby(["commodity", "region", "safra_year"], dropna=False)["_adjacent_revision"]
        .transform(_revision_streak)
        .astype(int)
    )

    return wide[OUTPUT_COLUMNS].reset_index(drop=True)
