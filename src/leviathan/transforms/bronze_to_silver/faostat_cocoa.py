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


def transform_faostat_cocoa_silver_df(
    df: pd.DataFrame,
    commodity: str = "cocoa",
) -> list[tuple[int, pd.DataFrame]]:
    """Apply silver cleaning rules to an already-loaded bronze FAOSTAT DataFrame.

    Returns a list of ``(year, silver_df)`` pairs ready for writing.
    ``transform_faostat_cocoa_to_silver`` calls this internally; Glue jobs that
    read bronze Parquet directly from S3 should call this instead.

    Args:
        df: Bronze FAOSTAT DataFrame.
        commodity: Commodity label to stamp on every row (default: "cocoa").
    """
    required = {"area", "item", "element", "year", "unit", "value", "flag"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required FAOSTAT bronze columns: {missing}")

    df = df.copy()

    df = df[df["element"].isin(ELEMENT_TO_METRIC.keys())].copy()
    df["metric"] = df["element"].map(ELEMENT_TO_METRIC)

    df["country"] = df["area"].astype(str)
    df["country_key"] = df["country"].map(standardize_country_name)

    df["commodity"] = commodity
    df["source"] = "faostat"
    df["dataset"] = "QCL"

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    NON_OFFICIAL_FLAGS = {"E", "F", "Fc", "Im", "*", "A"}
    df["flag"] = df["flag"].where(df["flag"].notna() & (df["flag"].astype(str).str.strip() != ""), other=None)
    df["is_official"] = ~df["flag"].astype(str).str.strip().isin(NON_OFFICIAL_FLAGS)

    note_col = ["note"] if "note" in df.columns else []

    silver = df[
        [
            "country",
            "country_key",
            "metric",
            "year",
            "unit",
            "value",
            "flag",
            "is_official",
            *note_col,
            "source",
            "dataset",
            "ingest_date",
            "source_file_name",
        ]
    ].copy()

    silver = silver.dropna(subset=["year", "metric", "country_key"])
    silver["year"] = silver["year"].astype(int)

    silver = silver.drop_duplicates(
        subset=["country_key", "metric", "year", "source"],
        keep="last",
    )

    for (country_key, metric), group in silver.groupby(["country_key", "metric"]):
        if group["is_official"].sum() == 0:
            logger.warning(
                "No official rows for country_key=%s metric=%s — all values are FAO estimates",
                country_key,
                metric,
            )

    non_official_pct = (~silver["is_official"]).mean() * 100
    if non_official_pct > 30:
        logger.warning(
            "%.1f%% of silver rows are non-official (FAO estimated/imputed). "
            "Review flag distribution before using in ML.",
            non_official_pct,
        )

    return [(int(year), year_df) for year, year_df in silver.groupby("year")]


def transform_faostat_cocoa_to_silver(
    bronze_root: str | Path,
    output_root: str | Path,
    commodity: str = "cocoa",
) -> list[Path]:
    df = load_bronze_faostat(bronze_root)
    year_frames = transform_faostat_cocoa_silver_df(df, commodity=commodity)

    written_files: list[Path] = []
    output_root = Path(output_root)

    for year, year_df in year_frames:
        year_dir = output_root / f"commodity={commodity}" / f"year={year}"
        year_dir.mkdir(parents=True, exist_ok=True)

        output_path = year_dir / "part-000.parquet"

        year_df.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        logger.info("Wrote silver FAOSTAT cocoa file: %s rows=%s", output_path, len(year_df))
        written_files.append(output_path)

    return written_files