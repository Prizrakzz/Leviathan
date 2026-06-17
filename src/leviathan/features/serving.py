"""The single legal path to inference-time features.

Training/serving skew is the classic production failure: features computed one
way for training and a slightly different way for live inference.  Leviathan
avoids it structurally — ``build_spine`` is the only place features are ever
computed, and the training matrix is its output.  Serving must use the *same*
path.  This module is that path; never reconstruct features ad hoc in an
inference script.

Two modes:
  * ``prefer="gold"`` (default) — read the spine's own wide output
    (``gold/feature_matrix/commodity={slug}``).  Zero skew: it is the exact
    artifact training consumed.
  * ``prefer="compute"`` — rebuild a single (commodity, crop_year) via
    ``build_spine`` + ``build_feature_matrix`` when an as-of isn't yet
    materialised in gold.  Identical feature logic to training by construction.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pyarrow.dataset as ds

from leviathan.common.logging import get_logger
from leviathan.features.calendar import load_crop_calendars
from leviathan.features.extractors import extract_all
from leviathan.features.pivot import build_feature_matrix
from leviathan.features.registry import load_registry
from leviathan.features.spine import build_spine, default_calendar, load_countries

logger = get_logger(__name__)


def _resolve_root(bucket: str | None, root: str | None) -> str:
    if root:
        return root.rstrip("/")
    if bucket:
        return f"s3://{bucket}"
    raise ValueError("load_inference_features requires either `bucket` or `root`.")


def _read_gold_matrix(root: str, commodity: str) -> pd.DataFrame:
    location = f"{root}/gold/feature_matrix/commodity={commodity}"
    dataset = ds.dataset(location, format="parquet")
    return dataset.to_table().to_pandas()


def _compute_matrix(
    root: str, commodity: str, crop_year: int, config_dir: str | None
) -> pd.DataFrame:
    registry = load_registry(config_dir)
    calendars = load_crop_calendars()
    countries = load_countries(commodity)
    if not countries:
        return pd.DataFrame(columns=["country", "crop_year"])
    inputs, _ = extract_all(root, commodity, registry.sources_for(commodity))
    calendar = calendars.get(commodity) or default_calendar(commodity)
    build = build_spine(
        commodity=commodity, crop_years=[crop_year], countries=countries,
        calendar=calendar, registry=registry, inputs=inputs,
    )
    return build_feature_matrix(build.df)


def load_inference_features(
    commodity: str,
    crop_year: int | None = None,
    *,
    bucket: str | None = None,
    root: str | None = None,
    prefer: str = "gold",
    config_dir: str | None = None,
) -> pd.DataFrame:
    """Inference-time feature rows for *commodity* — the only sanctioned source.

    Args:
        commodity:   Slug.
        crop_year:   Target crop year; defaults to the latest available
                     (gold mode) or the current calendar year (compute mode).
        bucket/root: ``root`` (e.g. ``s3://bucket`` or a local path) wins; else
                     ``s3://{bucket}``.
        prefer:      ``"gold"`` (read the spine output) or ``"compute"``
                     (rebuild via build_spine for a fresh as-of).
        config_dir:  Override registry/feature config dir (compute mode).

    Returns:
        Wide DataFrame (``country, crop_year, <feature cols>``) for the target
        crop year.  Empty frame when no data exists.
    """
    root = _resolve_root(bucket, root)

    if prefer == "gold":
        matrix = _read_gold_matrix(root, commodity)
        if matrix.empty:
            logger.warning("serving: no gold matrix for %s at %s", commodity, root)
            return matrix
        target = int(crop_year) if crop_year is not None else int(matrix["crop_year"].max())
        return matrix.loc[matrix["crop_year"] == target].reset_index(drop=True)

    if prefer == "compute":
        target = int(crop_year) if crop_year is not None else date.today().year
        matrix = _compute_matrix(root, commodity, target, config_dir)
        return matrix.loc[matrix["crop_year"] == target].reset_index(drop=True)

    raise ValueError(f"prefer must be 'gold' or 'compute', got {prefer!r}")
