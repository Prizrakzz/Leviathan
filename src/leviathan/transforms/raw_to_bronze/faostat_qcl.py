from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger


logger = get_logger(__name__)


TARGET_ITEMS = {
    "cocoa beans",
}

TARGET_ELEMENTS = {
    "area harvested",
    "production quantity",
    "yield",
}


def snake_case(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def find_csv_inside_zip(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path, "r") as archive:
        csv_files = [
            name for name in archive.namelist()
            if name.lower().endswith(".csv")
        ]

    if not csv_files:
        raise FileNotFoundError(f"No CSV file found inside ZIP: {zip_path}")

    if len(csv_files) > 1:
        logger.warning("Multiple CSV files found inside ZIP. Using first: %s", csv_files[0])

    return csv_files[0]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [snake_case(col) for col in df.columns]
    return df


def clean_basic_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df


def filter_cocoa_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    required_columns = {"item", "element"}
    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(f"Missing required FAOSTAT columns after normalization: {missing}")

    item_normalized = df["item"].astype(str).str.strip().str.lower()
    element_normalized = df["element"].astype(str).str.strip().str.lower()

    mask = (
        item_normalized.isin(TARGET_ITEMS)
        & element_normalized.isin(TARGET_ELEMENTS)
    )

    return df.loc[mask].copy()


def add_bronze_metadata(
    df: pd.DataFrame,
    ingest_date: str,
    source_file_name: str,
) -> pd.DataFrame:
    df = df.copy()
    df["source"] = "faostat"
    df["dataset"] = "QCL"
    df["commodity"] = "cocoa"
    df["ingest_date"] = ingest_date
    df["source_file_name"] = source_file_name
    return df


def transform_faostat_qcl_zip_to_bronze(
    zip_path: str | Path,
    output_dir: str | Path,
    ingest_date: str,
    chunksize: int = 100_000,
) -> list[Path]:
    """
    Convert raw FAOSTAT QCL ZIP into bronze Parquet files.

    Bronze rules:
    - preserve source-shaped rows
    - normalize column names
    - keep source identifiers
    - filter to cocoa only for MVP
    - partition by year
    """

    zip_path = Path(zip_path)
    output_dir = Path(output_dir)

    if not zip_path.exists():
        raise FileNotFoundError(f"Raw FAOSTAT ZIP not found: {zip_path}")

    csv_name = find_csv_inside_zip(zip_path)
    logger.info("Reading CSV inside ZIP: %s", csv_name)

    bronze_frames: list[pd.DataFrame] = []

    with zipfile.ZipFile(zip_path, "r") as archive:
        with archive.open(csv_name) as file:
            reader = pd.read_csv(file, chunksize=chunksize, low_memory=False)

            for chunk_number, chunk in enumerate(reader, start=1):
                logger.info("Processing FAOSTAT chunk %s", chunk_number)

                chunk = normalize_columns(chunk)
                chunk = clean_basic_types(chunk)
                chunk = filter_cocoa_rows(chunk)

                if chunk.empty:
                    continue

                chunk = add_bronze_metadata(
                    chunk,
                    ingest_date=ingest_date,
                    source_file_name=zip_path.name,
                )

                bronze_frames.append(chunk)

    if not bronze_frames:
        raise ValueError("No cocoa rows found in FAOSTAT QCL file.")

    bronze_df = pd.concat(bronze_frames, ignore_index=True)

    if "year" not in bronze_df.columns:
        raise ValueError("Column 'year' not found. Cannot partition bronze data by year.")

    written_files: list[Path] = []

    for year, year_df in bronze_df.groupby("year", dropna=True):
        year_int = int(year)

        year_dir = (
            output_dir
            / "source=faostat"
            / "dataset=QCL"
            / "commodity=cocoa"
            / f"year={year_int}"
        )

        year_dir.mkdir(parents=True, exist_ok=True)

        output_path = year_dir / "part-000.parquet"

        year_df.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        written_files.append(output_path)
        logger.info("Wrote bronze Parquet: %s rows=%s", output_path, len(year_df))

    logger.info("Bronze transform complete. Files written: %s", len(written_files))

    return written_files