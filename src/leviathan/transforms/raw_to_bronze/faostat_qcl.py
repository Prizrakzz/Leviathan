from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)


# ── THE BRONZE ELEMENT GATE (FAO-2, Lane 5) ────────────────────────────────────────────────────────
# Matched against a lower-cased, stripped `element` column, so the members are lower-case; the
# CAPITALISATION-BEARING truth lives in `faostat_production.ELEMENT_TO_METRIC`, whose keys are the
# legend's own strings.
#
# THIS GATE IS WHERE ROWS DIE SILENTLY. `filter_by_fao_item` drops every non-member without a word,
# and the whole Lane-4/Lane-5 finding is that 93.85% of the file was discarded at exactly this line
# for years with nothing anywhere saying so. So the set is no longer "the three elements the crop
# half happened to need": it is THE COMPLETE LIVE ELEMENT UNIVERSE of the release, and the two
# legend members it does NOT carry are refused IN WRITING below rather than left as an absence.
#
# MEASURED on the tracked 2026-05-11 QCL ZIP (`data/raw/production/faostat/qcl/
# Production_Crops_Livestock_E_All_Data_(Normalized).zip`), one full stream of all 4,209,110 rows --
# banked at `data/dec_p0/faostat_livestock_census.json`, cut by
# `jobs/utils/faostat_element_item_census.py`:
#
#     Production                     1,643,611      Producing Animals/Slaughtered    313,081
#     Area harvested                   893,484      Yield/Carcass Weight             262,197
#     Yield                            839,819      Stocks                           180,294
#                                                   Milk Animals                      45,801
#                                                   Laying                            30,823
#
# The eight sum to 4,209,110 EXACTLY -- the whole file -- so this set is now provably the complete
# live universe and no element can be lost here again. The right-hand five are the LIVESTOCK half
# (832,196 rows), which is the plan's figure re-measured and confirmed to the row rather than quoted.
TARGET_ELEMENTS = {
    # the crop three (pre-Lane-5; byte-identical behaviour for every existing item)
    "area harvested",
    "production",
    "yield",
    # the livestock five (FAO-2). Admitted HERE, at the bronze gate, for a reason that outlives the
    # current item roster: THREE of the five carry rows under the four items Lane 5 admits (Stocks on
    # Cattle / Swine / pigs / Chickens; Milk Animals and Yield/Carcass Weight on Raw milk of cattle),
    # and the other two -- Producing Animals/Slaughtered and Laying -- are carried ONLY by the MEAT
    # and EGG items the map parks in writing. They are admitted anyway because a later item addition
    # would otherwise land HALF-BLIND: its slaughter and carcass-weight rows dropped here, silently,
    # with the item filter reporting success. An element that is admitted but unreached costs one set
    # member and mints no row; an element that is reached but unadmitted is the failure mode this
    # whole lane exists to close. The card is where the distinction has to be honest -- it serves only
    # the metrics that carry rows, and names the other two as unserved.
    "stocks",
    "milk animals",
    "laying",
    "producing animals/slaughtered",
    "yield/carcass weight",
}

# WRITTEN REFUSAL, not an oversight (the `_PSD_UNMAPPED_CODES` idiom on the element axis). The
# release's legend member `Production_Crops_Livestock_E_Elements.csv` declares TEN element names
# across 20 element codes; the eight above are every one that carries a row. These two carry ZERO
# rows in the 2026-05-11 data -- dead legend keys, the same tell the four dead pre-2022 FLAGS gave
# (`faostat_production.FLAG_SEMANTICS`), and they are named here so a future vintage that starts
# printing them fails the legend-equality test in tests/unit/test_transforms_faostat_raw.py instead
# of being admitted by a silent default.
_REFUSED_LEGEND_ELEMENTS: dict[str, str] = {
    "Extraction Rate": (
        "Element 5423. ZERO rows in the 2026-05-11 release. A processing RATIO with no unit this "
        "table can serve alongside tonnes -- the same class silver_psd refuses by leaving "
        "PERCENT/RATIO out of its unit-factor table. Reopen only with a rate-bearing metric, never "
        "by adding it to the set above."
    ),
    "Prod Popultn": (
        "Elements 5314 / 5319. ZERO rows in the 2026-05-11 release. A producing-population count "
        "whose relationship to `Producing Animals/Slaughtered` (5320/5321, 313,081 rows) is "
        "undocumented in the legend; admitting both would put two populations under one governed "
        "metric with no way to tell them apart. Reopen by measuring which items carry it first."
    ),
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


def filter_by_fao_item(df: pd.DataFrame, fao_item_name: str) -> pd.DataFrame:
    """Keep only rows matching the given FAO item name and production elements."""
    df = df.copy()

    required_columns = {"item", "element"}
    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(f"Missing required FAOSTAT columns after normalization: {missing}")

    item_normalized = df["item"].astype(str).str.strip().str.lower()
    element_normalized = df["element"].astype(str).str.strip().str.lower()

    mask = (
        (item_normalized == fao_item_name.strip().lower())
        & element_normalized.isin(TARGET_ELEMENTS)
    )

    return df.loc[mask].copy()


def add_bronze_metadata(
    df: pd.DataFrame,
    ingest_date: str,
    source_file_name: str,
    commodity: str,
) -> pd.DataFrame:
    df = df.copy()
    df["source"] = "faostat"
    df["dataset"] = "QCL"
    df["commodity"] = commodity
    df["ingest_date"] = ingest_date
    df["source_file_name"] = source_file_name
    return df


def transform_faostat_qcl_zip_to_bronze(
    zip_path: str | Path,
    output_dir: str | Path,
    ingest_date: str,
    commodity: str,
    fao_item_name: str,
    chunksize: int = 100_000,
) -> list[Path]:
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
                chunk = filter_by_fao_item(chunk, fao_item_name)

                if chunk.empty:
                    continue

                chunk = add_bronze_metadata(
                    chunk,
                    ingest_date=ingest_date,
                    source_file_name=zip_path.name,
                    commodity=commodity,
                )

                bronze_frames.append(chunk)

    if not bronze_frames:
        raise ValueError(f"No rows found for FAO item '{fao_item_name}' in FAOSTAT QCL file.")

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
            / f"commodity={commodity}"
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
