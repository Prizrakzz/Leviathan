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
  * derives ``is_official`` from the release's OWN flag legend (:data:`FLAG_SEMANTICS`) and refuses
    any flag the legend does not carry (fail-closed on a scheme change, FAO-6);
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

# ── FAOSTAT observation-status flags (FAO-6) ───────────────────────────────────────────────────────
# The descriptions are VERBATIM from the release's own legend, ``Production_Crops_Livestock_E_Flags.csv``,
# which ships INSIDE the same QCL ZIP this transform's bronze is cut from -- the legend and the data are
# one artefact, so the scheme can never be read from a stale doc.
#
# THIS REPLACES THE PRE-2022 SCHEME (``{"E","F","Fc","Im","*","A"}`` read as NON-official). FAOSTAT
# switched legends and the estate did not: MEASURED on the 2026-05-11 raw ZIP, all 4,209,110 rows carry
# exactly {A, E, X, I, M} and ZERO carry F / Fc / Im / ``*`` -- four dead keys, which is itself the proof
# the file changed schemes. Under the old set ``A`` (an OFFICIAL figure, 43.7% of the file) was marked
# UNOFFICIAL while ``I`` (imputed) and ``M`` (missing) were marked OFFICIAL, so ``is_official`` was
# inverted on the two ends that matter most. The ML label lane reads that column (`source_contracts.yaml`
# status: core), so this is a correctness fix, not a cosmetic one.
FLAG_SEMANTICS: dict[str, str] = {
    "A": "Official figure",
    "E": "Estimated value",
    "I": "Value imputed by a receiving agency",
    "M": "Missing value; data cannot exist",
    "X": "Figure from external organization",
}

# Officiality is ASSERTED, never inferred: only FAO's own "Official figure" marks a row official.
OFFICIAL_FLAGS = frozenset({"A"})

# ``M`` says the observation CANNOT EXIST. THIS IS A FORWARD GUARD, NOT A REPAIR: measured on the
# 2026-05-11 ZIP, all 94,355 M rows print an EMPTY Value cell, so pd.to_numeric has already made them
# NaN and this blanking moves zero rows on the current vintage (the Lane-4 review measured it to the
# row). It exists for the vintage where FAO does print a number beside M -- carrying that number
# forward would mint a measured-looking figure for a country-year FAO states cannot exist -- and it
# runs AFTER duplicate resolution so such a value still participates in conflict detection first
# (see _blank_no_value_flags). Neither official nor a value.
NO_VALUE_FLAGS = frozenset({"M"})

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


def _apply_flag_semantics(df: pd.DataFrame) -> pd.DataFrame:
    """Derive ``is_official`` from :data:`FLAG_SEMANTICS` and blank the value of a ``M`` row (FAO-6).

    FAIL-CLOSED IN BOTH DIRECTIONS, and they are different directions on purpose:

      * a PRESENT flag the legend does not carry is a legend change -- raise, because the alternative
        is publishing an ``is_official`` whose meaning nobody has read. The four dead pre-2022 keys
        (F / Fc / Im / ``*``) reach this branch if FAO ever reverts, which is exactly when a silent
        default would re-inject the inverted column this replaced;
      * an ABSENT flag is an absence of an OFFICIALITY ASSERTION, not a scheme change -- the row keeps
        its value and reads ``is_official=False``. Measured: the 2026-05-11 ZIP carries no blank flag
        at all, so this branch exists for a future vintage and for hand-built frames, and it leans the
        only way that cannot manufacture officialness."""
    flags = df["flag"].astype("string").str.strip()
    unknown = sorted(set(flags.dropna().unique()) - set(FLAG_SEMANTICS))
    if unknown:
        raise FaostatMappingError(
            f"FAOSTAT bronze carries observation flag(s) {unknown} absent from the release legend "
            f"{sorted(FLAG_SEMANTICS)}. The flag scheme changed: re-read "
            "Production_Crops_Livestock_E_Flags.csv inside the QCL ZIP and re-derive is_official "
            "before publishing (FAO-6)."
        )
    df["is_official"] = flags.isin(OFFICIAL_FLAGS).fillna(False).astype(bool)
    return df


def _blank_no_value_flags(df: pd.DataFrame) -> pd.DataFrame:
    """NULL the value of every :data:`NO_VALUE_FLAGS` row -- AFTER duplicate resolution, deliberately.

    Blanking before ``_resolve_duplicates_or_raise`` fails OPEN for exactly the future vintage this
    guard exists for: the conflict test drops NaN, so an M row carrying a printed number would vanish
    from conflict detection and ``keep="last"`` could silently publish the NaN M row over a real
    official figure -- the "never a silent last-wins" promise broken by ordering alone (Lane-4 review,
    minor 1). Run here, a numeric M cell first collides loudly with any sibling row, and only the
    survivor is blanked."""
    flags = df["flag"].astype("string").str.strip()
    # float NaN, not pd.NA: `value` is float64 by this point and the registry contract keeps it numeric.
    df.loc[flags.isin(NO_VALUE_FLAGS).fillna(False), "value"] = float("nan")
    return df


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
    df = _apply_flag_semantics(df)

    df = df.dropna(subset=["year", "metric", "country_key"]).copy()
    if df.empty:
        return []
    df["year"] = df["year"].astype(int)

    silver = df[CANONICAL_PHYSICAL_COLUMNS + ["year"]].copy()
    silver = _resolve_duplicates_or_raise(silver)
    silver = _blank_no_value_flags(silver)

    # Coverage warnings (unofficial-heavy sources). Under the FAO-6 scheme these carry signal: a
    # non-official row is E/I/X/M (estimated / imputed / external-org / missing), never an A.
    for (ckey, metric), group in silver.groupby(["country_key", "metric"]):
        if group["is_official"].sum() == 0:
            logger.warning(
                "No official rows for country_key=%s metric=%s -- every value is FAO-estimated, "
                "imputed or sourced from an external organization",
                ckey, metric,
            )
    non_official_pct = (~silver["is_official"]).mean() * 100
    if non_official_pct > 30:
        logger.warning(
            "%.1f%% of silver rows are non-official (FAO estimated/imputed/external). "
            "Review flag distribution before using in ML.",
            non_official_pct,
        )

    out: list[tuple[int, pd.DataFrame]] = []
    for year, year_df in silver.groupby("year"):
        body = year_df[CANONICAL_PHYSICAL_COLUMNS].reset_index(drop=True)
        out.append((int(year), body))
    return out
