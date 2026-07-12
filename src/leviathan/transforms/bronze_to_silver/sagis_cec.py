"""SILVER-F058: SAGIS Crop Estimates Committee (CEC) producer (silver_sagis_cec).

Grain / natural key: ``production_year x report_month x crop x scope x estimate_number``.

The SA CEC issues a numbered sequence of production estimates per (production_year, crop, scope)
across the season (1st estimate, 2nd estimate, ...). Multiple physical source files (pdf/doc/xls,
or a re-release) can carry the SAME numbered estimate; :func:`select_authoritative` picks ONE
deterministically (latest release_date, then a format priority, then lexical source key) and keeps
release/source provenance. Revision metrics are computed ONLY after the natural key is unique, with
STRICT no-lookahead (a later estimate can never inform an earlier one):

  * ``prior_estimate_t``    -- the current estimate's immediate predecessor
                               (max estimate_number < this one, same production_year/crop/scope).
  * ``prior_year_final_t``  -- the FINAL (highest estimate_number) estimate of the prior
                               production_year for the same crop/scope.
  * ``revision_t``          -- current_estimate_t - prior_estimate_t (None on the first estimate).
  * ``revision_pct``        -- 100 * revision_t / prior_estimate_t (None if prior is None/0).
  * ``revision_surprise``   -- 100 * (current_estimate_t - prior_year_final_t) / prior_year_final_t
                               (None if prior_year_final is None/0): this season vs last year's final.

Pure + AWS-free. The batch task parses the governed bronze workbook records; this module is the
transform over those records.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "production_year", "report_month", "release_date", "season_type", "crop", "scope",
    "estimate_number", "area_planted_ha", "current_estimate_t", "prior_estimate_t",
    "prior_year_final_t", "revision_t", "revision_pct", "revision_surprise", "source",
]

NATURAL_KEY = ["production_year", "report_month", "crop", "scope", "estimate_number"]

# Deterministic tie-break when two files carry the same numbered estimate (higher = authoritative).
SOURCE_FORMAT_PRIORITY: dict[str, int] = {"pdf": 3, "doc": 2, "xls": 1}


class SagisConflictError(ValueError):
    """A natural key survived selection with two different current_estimate_t values (fail closed)."""


@dataclass(frozen=True)
class CecObservation:
    """One parsed CEC estimate observation from governed bronze (before authoritative selection)."""

    production_year: int
    report_month: int
    crop: str
    scope: str
    estimate_number: int
    current_estimate_t: Optional[float]
    release_date: Optional[str] = None        # ISO YYYY-MM-DD
    season_type: Optional[str] = None
    area_planted_ha: Optional[float] = None
    source_format: str = "pdf"
    source_key: str = ""
    source: str = "sagis_cec"


def _selection_rank(obs: CecObservation) -> tuple:
    """Higher tuple = more authoritative: latest release_date, then format priority, then key."""
    return (
        obs.release_date or "",
        SOURCE_FORMAT_PRIORITY.get((obs.source_format or "").lower(), 0),
        obs.source_key or "",
    )


def select_authoritative(observations: list[CecObservation]) -> list[CecObservation]:
    """Collapse to ONE observation per natural key, deterministically (the F058 selector).

    Keeps the highest :func:`_selection_rank`. Raises :class:`SagisConflictError` if the winner is
    ambiguous only when two winners tie on the full rank AND disagree on the estimate value."""
    by_key: dict[tuple, CecObservation] = {}
    for obs in observations:
        key = (obs.production_year, obs.report_month, obs.crop, obs.scope, obs.estimate_number)
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = obs
            continue
        rank_new, rank_cur = _selection_rank(obs), _selection_rank(cur)
        if rank_new > rank_cur:
            by_key[key] = obs
        elif rank_new == rank_cur and obs.current_estimate_t != cur.current_estimate_t:
            raise SagisConflictError(
                f"ambiguous authoritative estimate for {key}: "
                f"{cur.current_estimate_t} vs {obs.current_estimate_t} at equal rank"
            )
    return list(by_key.values())


def _prior_estimate(df: pd.DataFrame, row) -> Optional[float]:
    """Immediate predecessor estimate (strict no-lookahead) in the same year/crop/scope."""
    mask = (
        (df["production_year"] == row["production_year"])
        & (df["crop"] == row["crop"])
        & (df["scope"] == row["scope"])
        & (df["estimate_number"] < row["estimate_number"])
    )
    prior = df[mask]
    if prior.empty:
        return None
    best = prior.loc[prior["estimate_number"].idxmax()]
    val = best["current_estimate_t"]
    return None if pd.isna(val) else float(val)


def _prior_year_final(df: pd.DataFrame, row) -> Optional[float]:
    """Final (highest estimate_number) estimate of the prior production_year, same crop/scope."""
    mask = (
        (df["production_year"] == row["production_year"] - 1)
        & (df["crop"] == row["crop"])
        & (df["scope"] == row["scope"])
    )
    prior = df[mask]
    if prior.empty:
        return None
    best = prior.loc[prior["estimate_number"].idxmax()]
    val = best["current_estimate_t"]
    return None if pd.isna(val) else float(val)


def _safe_pct(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    if numer is None or denom is None or denom == 0:
        return None
    return 100.0 * numer / denom


def transform_sagis_cec(observations: list[CecObservation]) -> pd.DataFrame:
    """Transform governed CEC bronze observations into the silver CEC table with revision metrics."""
    chosen = select_authoritative(observations)
    if not chosen:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    base = pd.DataFrame.from_records([{
        "production_year": int(o.production_year),
        "report_month": int(o.report_month),
        "release_date": o.release_date,
        "season_type": o.season_type,
        "crop": o.crop,
        "scope": o.scope,
        "estimate_number": int(o.estimate_number),
        "area_planted_ha": o.area_planted_ha,
        "current_estimate_t": o.current_estimate_t,
        "source": o.source,
    } for o in chosen])

    # Uniqueness precondition (defensive: selector already enforced it).
    if base.duplicated(subset=NATURAL_KEY).any():
        raise SagisConflictError("natural key not unique after authoritative selection")

    priors_e: list[Optional[float]] = []
    priors_pyf: list[Optional[float]] = []
    for _, row in base.iterrows():
        priors_e.append(_prior_estimate(base, row))
        priors_pyf.append(_prior_year_final(base, row))
    base["prior_estimate_t"] = priors_e
    base["prior_year_final_t"] = priors_pyf

    def _rev(row):
        cur, prev = row["current_estimate_t"], row["prior_estimate_t"]
        if pd.isna(cur) or prev is None or pd.isna(prev):
            return None
        return float(cur) - float(prev)

    base["revision_t"] = base.apply(_rev, axis=1)
    base["revision_pct"] = base.apply(
        lambda r: _safe_pct(r["revision_t"], r["prior_estimate_t"]), axis=1)
    base["revision_surprise"] = base.apply(
        lambda r: _safe_pct(
            (None if pd.isna(r["current_estimate_t"]) or r["prior_year_final_t"] is None
             else float(r["current_estimate_t"]) - float(r["prior_year_final_t"])),
            r["prior_year_final_t"]),
        axis=1)

    base = base.sort_values(NATURAL_KEY).reset_index(drop=True)
    return base[OUTPUT_COLUMNS]
