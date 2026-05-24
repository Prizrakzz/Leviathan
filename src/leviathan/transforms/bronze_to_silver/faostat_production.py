from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)


ELEMENT_TO_METRIC = {
    "Area harvested": "area_harvested",
    "Production": "production_quantity",
    "Yield": "yield",
}


def standardize_country_name(value: str) -> str:
    # Decompose accented chars (ô → o + combining circumflex) then strip non-ASCII.
    # "Côte d'Ivoire" → "cote_divoire", not "côte_divoire".
    s = unicodedata.normalize("NFKD", str(value).strip())
    s = s.encode("ascii", "ignore").decode("ascii")
    return (
        s.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("'", "")
        .replace("(", "")
        .replace(")", "")
    )


def load_bronze_faostat(bronze_root: str | Path) -> pd.DataFrame:
    bronze_root = Path(bronze_root)
    parquet_files = sorted(bronze_root.rglob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"No bronze FAOSTAT Parquet files found under {bronze_root}")

    frames = [pd.read_parquet(path) for path in parquet_files]
    return pd.concat(frames, ignore_index=True)


def transform_faostat_production_silver_df(
    df: pd.DataFrame,
    commodity: str,
) -> list[tuple[int, pd.DataFrame]]:
    """Apply silver cleaning rules to an already-loaded bronze FAOSTAT DataFrame.

    Returns a list of ``(year, silver_df)`` pairs ready for writing.

    Args:
        df: Bronze FAOSTAT DataFrame.
        commodity: Commodity label to stamp on every row.
    """
    required = {"area", "item", "element", "year", "unit", "value", "flag"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required FAOSTAT bronze columns: {missing}")

    df = df.copy()

    # Normalize element capitalization to match ELEMENT_TO_METRIC keys
    # (e.g. "area harvested" → "Area harvested", "PRODUCTION" → "Production")
    df["element"] = df["element"].astype(str).str.strip().str.capitalize()

    df = df[df["element"].isin(ELEMENT_TO_METRIC.keys())].copy()
    df["variable"] = df["element"].map(ELEMENT_TO_METRIC)

    # country: standardized key (e.g. "cote_divoire") — consistent with weather silver
    df["country"] = df["area"].astype(str).map(standardize_country_name)

    df["commodity"] = commodity
    df["source"] = "faostat"

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    NON_OFFICIAL_FLAGS = {"E", "F", "Fc", "Im", "*", "A"}
    df["flag"] = df["flag"].where(df["flag"].notna() & (df["flag"].astype(str).str.strip() != ""), other=None)
    df["is_official"] = ~df["flag"].astype(str).str.strip().isin(NON_OFFICIAL_FLAGS)

    silver = df[
        [
            "commodity",
            "source",
            "country",
            "variable",
            "year",
            "unit",
            "value",
            "flag",
            "is_official",
            "ingest_date",
        ]
    ].copy()

    silver = silver.dropna(subset=["year", "variable", "country"])
    silver["year"] = silver["year"].astype(int)

    silver = silver.drop_duplicates(
        subset=["country", "variable", "year", "source"],
        keep="last",
    )

    for (country, variable), group in silver.groupby(["country", "variable"]):
        if group["is_official"].sum() == 0:
            logger.warning(
                "No official rows for country=%s variable=%s — all values are FAO estimates",
                country,
                variable,
            )

    non_official_pct = (~silver["is_official"]).mean() * 100
    if non_official_pct > 30:
        logger.warning(
            "%.1f%% of silver rows are non-official (FAO estimated/imputed). "
            "Review flag distribution before using in ML.",
            non_official_pct,
        )

    return [(int(year), year_df) for year, year_df in silver.groupby("year")]
