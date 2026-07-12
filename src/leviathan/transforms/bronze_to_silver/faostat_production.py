"""FAOSTAT bronze -> canonical ``silver_production`` transform (SILVER-F022).

``silver_production`` (the FAOSTAT/PSD production spine feeding the training LABEL + 4 faostat
families) is a projected table resolved at ``silver/production/commodity=<c>/year=<y>/`` with the
12-column contract pinned by the SILVER-F010 registry
(``configs/silver/tables/silver_production.yaml``):

    country, country_key, metric, unit, value, flag, is_official, note, source, dataset,
    ingest_date, source_file_name

The pre-F022 producer emitted a DIFFERENT shape (``variable`` instead of ``metric``; a single
``country`` holding the governed KEY with no display column; no ``note`` / ``dataset`` /
``source_file_name``) and wrote it beneath ``silver/production/source=faostat/`` -- a prefix the
canonical projection does NOT resolve, so the objects were invisible to the served table. This
transform:

  * preserves the DISPLAY country and derives the governed ``country_key`` (was collapsed to one
    column holding only the key);
  * renames ``variable`` -> ``metric`` via an explicit element map (no silent metric invention);
  * retains provenance (``note``, ``dataset``, ``source_file_name``);
  * resolves only logically-exact duplicates automatically and FAILS on a conflicting natural-key
    value (never a silent last-wins);
  * emits exactly the 12 canonical physical columns -- ``commodity`` and ``year`` are the projected
    partition keys carried on the S3 path, never in the parquet body (INV-2 exact writer schema).

The batch/Glue writer enforces the INV-2 arrow schema from the registry contract, hard-guards the
canonical ``silver/production/commodity=/year=/`` layout (a ``source=faostat`` key is refused), and
routes through the shadow-first publisher.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# element (FAOSTAT) -> governed metric name (the explicit, validated variable->metric map).
ELEMENT_TO_METRIC = {
    "Area harvested": "area_harvested",
    "Production": "production_quantity",
    "Yield": "yield",
}

# The 12 canonical physical columns, in registry order. ``commodity`` / ``year`` are partition keys
# (path-carried, NOT in the parquet body). This is the exact INV-2 writer column set for the body.
CANONICAL_PHYSICAL_COLUMNS = [
    "country",
    "country_key",
    "metric",
    "unit",
    "value",
    "flag",
    "is_official",
    "note",
    "source",
    "dataset",
    "ingest_date",
    "source_file_name",
]

SOURCE = "faostat"
DEFAULT_DATASET = "QCL"  # FAOSTAT Production_Crops_Livestock (QCL); overridden by a bronze `dataset`.

NON_OFFICIAL_FLAGS = {"E", "F", "Fc", "Im", "*", "A"}

# Natural key for silver_production (commodity is fixed per call; year is the partition tuple key).
_NATURAL_KEY = ["country_key", "metric", "year"]


class FaostatMappingError(ValueError):
    """A FAOSTAT bronze row cannot be mapped onto the governed silver contract (fail-closed)."""


class SilverProductionLayoutError(ValueError):
    """A silver_production write key is not the canonical projected layout (fail-closed)."""


def assert_canonical_production_key(key: str) -> str:
    """Hard-guard the canonical ``silver/production/commodity=<c>/year=<y>/`` layout (SILVER-F022).

    Refuses the legacy ``silver/production/source=faostat/`` prefix (which the projection does NOT
    resolve, so its objects are invisible to the served table) -- and any ``source=`` segment, or a
    key outside ``silver/production/``. Called before every write so the wrong-prefix regression can
    never recur."""
    k = (key or "").lstrip("/")
    if not k.startswith("silver/production/"):
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} is not under silver/production/"
        )
    if "source=" in k:
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} carries a 'source=' segment -- the canonical layout is "
            "silver/production/commodity=<c>/year=<y>/ (SILVER-F022 forbids the source=faostat prefix)"
        )
    if "commodity=" not in k or "year=" not in k:
        raise SilverProductionLayoutError(
            f"silver_production key {key!r} is missing the commodity=/year= partition segments"
        )
    return key


def standardize_country_name(value: str) -> str:
    """Governed country KEY: NFKD-fold accents, drop non-ASCII, snake_case.

    "Cote d'Ivoire" -> "cote_divoire" (consistent with the weather-silver country key)."""
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


def _resolve_duplicates_or_raise(silver: pd.DataFrame) -> pd.DataFrame:
    """Drop logically-exact duplicate rows; FAIL on a conflicting natural-key value.

    Two rows with the same ``(country_key, metric, year)`` may be collapsed automatically ONLY when
    their ``value`` agrees (byte/logically exact). A genuine value conflict is a data defect that
    must be triaged (documented flag precedence / quarantine), never silently last-wins."""
    dup_mask = silver.duplicated(subset=_NATURAL_KEY, keep=False)
    if dup_mask.any():
        conflicts = []
        for key, group in silver.loc[dup_mask].groupby(_NATURAL_KEY, dropna=False):
            if group["value"].dropna().round(9).nunique() > 1:
                conflicts.append(key)
        if conflicts:
            preview = ", ".join(str(c) for c in conflicts[:5])
            raise FaostatMappingError(
                f"FAOSTAT silver has conflicting duplicate values for natural key(s) {preview}. "
                "Resolve via flag precedence or quarantine before publishing."
            )
    return silver.drop_duplicates(subset=_NATURAL_KEY, keep="last")


def transform_faostat_production_silver_df(
    df: pd.DataFrame,
    commodity: str,
) -> list[tuple[int, pd.DataFrame]]:
    """Clean an already-loaded bronze FAOSTAT DataFrame into the canonical ``silver_production`` shape.

    Returns a list of ``(year, silver_df)`` pairs. Each ``silver_df`` has EXACTLY the 12 canonical
    physical columns (:data:`CANONICAL_PHYSICAL_COLUMNS`); ``commodity`` (this call's arg) and
    ``year`` (the tuple key) are the projected partition keys, carried on the path, not in the body.
    """
    required = {"area", "item", "element", "year", "unit", "value", "flag"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required FAOSTAT bronze columns: {missing}")

    df = df.copy()

    # Normalize element capitalization to the governed keys ("area harvested"->"Area harvested").
    df["element"] = df["element"].astype(str).str.strip().str.capitalize()
    df = df[df["element"].isin(ELEMENT_TO_METRIC)].copy()
    if df.empty:
        return []

    # metric (was `variable`): explicit, validated map -- unmapped elements are already filtered out.
    df["metric"] = df["element"].map(ELEMENT_TO_METRIC)

    # display country (preserved) + governed country key.
    df["country"] = df["area"].astype(str).str.strip()
    df["country_key"] = df["area"].astype(str).map(standardize_country_name)

    df["source"] = SOURCE
    df["dataset"] = df["dataset"].astype(str) if "dataset" in df.columns else DEFAULT_DATASET
    df["note"] = df["note"] if "note" in df.columns else None
    df["source_file_name"] = df["source_file_name"] if "source_file_name" in df.columns else None
    if "ingest_date" not in df.columns:
        df["ingest_date"] = None

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df["flag"] = df["flag"].where(
        df["flag"].notna() & (df["flag"].astype(str).str.strip() != ""), other=None
    )
    df["is_official"] = ~df["flag"].astype(str).str.strip().isin(NON_OFFICIAL_FLAGS)

    df = df.dropna(subset=["year", "metric", "country_key"]).copy()
    if df.empty:
        return []
    df["year"] = df["year"].astype(int)

    silver = df[CANONICAL_PHYSICAL_COLUMNS + ["year"]].copy()
    silver = _resolve_duplicates_or_raise(silver)

    # Coverage warnings (unofficial-heavy sources).
    for (ckey, metric), group in silver.groupby(["country_key", "metric"]):
        if group["is_official"].sum() == 0:
            logger.warning(
                "No official rows for country_key=%s metric=%s -- all values are FAO estimates",
                ckey, metric,
            )
    non_official_pct = (~silver["is_official"]).mean() * 100
    if non_official_pct > 30:
        logger.warning(
            "%.1f%% of silver rows are non-official (FAO estimated/imputed). "
            "Review flag distribution before using in ML.",
            non_official_pct,
        )

    out: list[tuple[int, pd.DataFrame]] = []
    for year, year_df in silver.groupby("year"):
        body = year_df[CANONICAL_PHYSICAL_COLUMNS].reset_index(drop=True)
        out.append((int(year), body))
    return out
