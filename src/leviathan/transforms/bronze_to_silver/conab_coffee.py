"""Silver transform for CONAB Brazil coffee bulletin XLS bronze data."""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

COUNTRY = "brazil"
SOURCE = "conab_xls"

OUTPUT_COLUMNS = [
    "commodity",
    "country",
    "safra_year",
    "survey_number",
    "region",
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
    "production_revision_thousand_bags",
    "source",
]

_METRIC_ELEMENTS = {
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
}

_STATE_NAMES = {
    "AC": "acre",
    "AL": "alagoas",
    "AP": "amapa",
    "AM": "amazonas",
    "BA": "bahia",
    "CE": "ceara",
    "DF": "distrito_federal",
    "ES": "espirito_santo",
    "GO": "goias",
    "MA": "maranhao",
    "MT": "mato_grosso",
    "MS": "mato_grosso_do_sul",
    "MG": "minas_gerais",
    "PA": "para",
    "PB": "paraiba",
    "PR": "parana",
    "PE": "pernambuco",
    "PI": "piaui",
    "RJ": "rio_de_janeiro",
    "RN": "rio_grande_do_norte",
    "RS": "rio_grande_do_sul",
    "RO": "rondonia",
    "RR": "roraima",
    "SC": "santa_catarina",
    "SP": "sao_paulo",
    "SE": "sergipe",
    "TO": "tocantins",
}


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _canonical_region(value: object) -> str | None:
    raw = str(value).strip().upper()
    if raw == "BRASIL":
        return "brazil"
    return _STATE_NAMES.get(raw)


def _commodity_from_sheet(sheet_name: object) -> str | None:
    sheet = str(sheet_name).strip().lower()
    if sheet.startswith("2 "):
        return "arabica_coffee"
    if sheet.startswith("3 "):
        return "robusta_coffee"
    return None


def _dedupe_or_raise(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["safra_year", "survey_number", "commodity", "region", "element"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        if group["value"].dropna().nunique() > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(item) for item in conflicts[:5])
        raise ValueError(f"CONAB coffee bronze has conflicting duplicate metrics for {preview}")

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def transform_conab_coffee_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot CONAB long bronze into production/revision silver rows.

    Silver keeps national Brazil plus state rows only. CONAB macroregions and
    sub-state coffee zones remain in bronze but are excluded from this table.
    """
    required = {"safra_year", "survey", "sheet_name", "region", "element", "value"}
    if missing := required - set(df.columns):
        raise ValueError(f"CONAB coffee bronze is missing columns: {missing}")
    if df.empty:
        return _empty()

    work = df.copy()
    work["commodity"] = work["sheet_name"].map(_commodity_from_sheet)
    work["region"] = work["region"].map(_canonical_region)
    work["element"] = work["element"].astype(str)
    work = work.loc[
        work["commodity"].notna()
        & work["region"].notna()
        & work["element"].isin(_METRIC_ELEMENTS)
    ].copy()
    if work.empty:
        return _empty()

    work["safra_year"] = pd.to_numeric(work["safra_year"], errors="coerce")
    work["survey_number"] = pd.to_numeric(work["survey"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["safra_year", "survey_number"]).copy()
    work["safra_year"] = work["safra_year"].astype(int)
    work["survey_number"] = work["survey_number"].astype(int)

    work = _dedupe_or_raise(work)
    index_cols = ["commodity", "safra_year", "survey_number", "region"]
    silver = (
        work.pivot(index=index_cols, columns="element", values="value")
        .reset_index()
        .rename_axis(columns=None)
    )

    for metric in _METRIC_ELEMENTS:
        if metric not in silver.columns:
            silver[metric] = pd.NA
        silver[metric] = pd.to_numeric(silver[metric], errors="coerce").astype("Float64")

    silver = silver.sort_values(
        ["commodity", "safra_year", "region", "survey_number"],
        kind="stable",
    ).reset_index(drop=True)
    silver["production_revision_thousand_bags"] = silver.groupby(
        ["commodity", "safra_year", "region"],
        dropna=False,
    )["production_thousand_bags"].diff()
    silver["production_revision_thousand_bags"] = silver[
        "production_revision_thousand_bags"
    ].astype("Float64")
    silver["country"] = COUNTRY
    silver["source"] = SOURCE

    silver = silver[OUTPUT_COLUMNS].sort_values(
        ["safra_year", "survey_number", "commodity", "region"],
        kind="stable",
    )
    logger.info("CONAB coffee silver produced %d rows", len(silver))
    return silver.reset_index(drop=True)
