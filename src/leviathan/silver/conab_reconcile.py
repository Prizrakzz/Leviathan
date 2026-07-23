"""SILVER-F024: reconcile the legacy CONAB orphan EAV against the canonical wide silver_conab_coffee.

OP-4 found a SECOND, catalog-less CONAB coffee representation at
``silver/production/source=conab/`` (26 objects / ~3,434 rows) with a 9-column EAV shape -- distinct
from the ``silver_conab_coffee`` table (the wide canonical; 22 F024 cols + the WIRING_WAVE1
survey_release_date additive = 23 -- reconciliation compares only the measured CANONICAL_METRICS, so
the vintage-anchor additive does not affect it). Before the orphan can be
classified/quarantined (deferred to F060), F024 requires a row/cell reconciliation between the two so
we KNOW the canonical reproduces the orphan's facts, with an ``unexplained_difference_count`` of zero
or an explicitly approved exception ledger.

This utility is a pure DataFrame-vs-DataFrame comparator (no AWS/IO). It projects the wide canonical
into the same (commodity, safra_year, survey_number, region, metric) -> value EAV grain as the orphan
and diffs cell by cell with a float tolerance, returning a structured report + a bounded exception
allow-list.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# The measurement metrics both representations carry (the wide canonical columns melted to EAV rows).
CANONICAL_METRICS = (
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
)

EAV_KEY = ["commodity", "safra_year", "survey_number", "region", "metric"]


@dataclass(frozen=True)
class ReconciliationReport:
    """Row/cell reconciliation of the orphan EAV against the canonical wide representation."""

    matched: int = 0
    value_mismatch: tuple[tuple, ...] = field(default=())     # (key..., orphan_value, canonical_value)
    orphan_only: tuple[tuple, ...] = field(default=())        # keys present only in the orphan
    canonical_only: tuple[tuple, ...] = field(default=())     # keys present only in the canonical
    exceptions_applied: int = 0

    @property
    def unexplained_difference_count(self) -> int:
        return len(self.value_mismatch) + len(self.orphan_only) + len(self.canonical_only)

    @property
    def reconciled(self) -> bool:
        return self.unexplained_difference_count == 0

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "value_mismatch": [list(x) for x in self.value_mismatch],
            "orphan_only": [list(x) for x in self.orphan_only],
            "canonical_only": [list(x) for x in self.canonical_only],
            "exceptions_applied": self.exceptions_applied,
            "unexplained_difference_count": self.unexplained_difference_count,
            "reconciled": self.reconciled,
        }


def canonical_to_eav(wide: pd.DataFrame, metrics=CANONICAL_METRICS) -> pd.DataFrame:
    """Melt the wide canonical silver into the orphan's (key..., metric, value) EAV grain."""
    present = [m for m in metrics if m in wide.columns]
    id_cols = ["commodity", "safra_year", "survey_number", "region"]
    long = wide.melt(
        id_vars=id_cols, value_vars=present, var_name="metric", value_name="value"
    )
    return long.dropna(subset=["value"]).reset_index(drop=True)


def _key_tuple(row: pd.Series) -> tuple:
    return (
        str(row["commodity"]), int(row["safra_year"]), int(row["survey_number"]),
        str(row["region"]), str(row["metric"]),
    )


def reconcile_conab_eav(
    orphan_eav: pd.DataFrame,
    canonical: pd.DataFrame,
    *,
    canonical_is_wide: bool = True,
    metrics=CANONICAL_METRICS,
    tol: float = 1e-6,
    exceptions=(),
) -> ReconciliationReport:
    """Reconcile the orphan EAV against the canonical representation.

    ``orphan_eav`` must carry columns ``commodity, safra_year, survey_number, region, metric,
    value``. ``canonical`` is the wide silver (melted here) when ``canonical_is_wide`` else an EAV
    frame with the same columns. ``exceptions`` is an allow-list of key tuples whose difference is
    approved (excluded from every difference bucket). Float values compare within ``tol``."""
    canon_eav = canonical_to_eav(canonical, metrics) if canonical_is_wide else canonical.copy()

    def _index(df: pd.DataFrame) -> dict[tuple, float]:
        out: dict[tuple, float] = {}
        for _, r in df.iterrows():
            if pd.isna(r["value"]):
                continue
            out[_key_tuple(r)] = float(r["value"])
        return out

    o = _index(orphan_eav)
    c = _index(canon_eav)
    exc = {tuple(e) for e in exceptions}

    matched = 0
    mismatches: list[tuple] = []
    for key in sorted(set(o) & set(c)):
        if key in exc:
            continue
        if np.isclose(o[key], c[key], rtol=0.0, atol=tol):
            matched += 1
        else:
            mismatches.append((*key, o[key], c[key]))

    orphan_only = tuple(sorted(k for k in (set(o) - set(c)) if k not in exc))
    canon_only = tuple(sorted(k for k in (set(c) - set(o)) if k not in exc))
    exceptions_applied = len(exc & (set(o) | set(c)))

    return ReconciliationReport(
        matched=matched,
        value_mismatch=tuple(mismatches),
        orphan_only=orphan_only,
        canonical_only=canon_only,
        exceptions_applied=exceptions_applied,
    )
