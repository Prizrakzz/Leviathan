"""Slice-based evaluation for commodity forecast models.

Aggregate RMSE averages away the failures that matter for a mispricing system:
a model can be excellent on data-rich annual crops and random on data-sparse
tree crops or in stress years, and the overall number looks fine.  This module
breaks a walk-forward ``predictions`` frame (``country, crop_year, y_actual,
y_pred``) into the slices defined in ``configs/training/slices.yaml`` and scores
each independently, then checks the pre-registered gaps in
``configs/training/acceptable_gaps.yaml``.

Scopes
------
One model is trained per commodity, so:
  * ``country`` and ``year_type`` are *within-run* slices — pass a single
    commodity's predictions; the flattened metrics go to that run's MLflow log.
  * ``crop_type`` / ``group`` / ``data_richness`` are *cross-run* rollup slices
    — concatenate every commodity's predictions (``rollup_cross_commodity``) to
    expose, e.g., tree crops failing while annuals look fine.

Anti-leakage: ``classify_stress_years`` labels test-year *actuals* for
evaluation only.  It is never a model input, so fitting the trend on the full
actual series is correct, not leakage.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "training"

_PRED_COLS = ("country", "crop_year", "y_actual", "y_pred")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_taxonomy(config_dir: str | Path | None = None) -> dict:
    """Load slices.yaml and invert the lists into lookups.

    Returns a dict with ``commodity_crop_type``, ``commodity_group`` (slug ->
    label), ``data_rich_countries`` (set), and ``stress`` (params).
    """
    cfg_dir = Path(config_dir) if config_dir is not None else _CONFIG_DIR
    raw = yaml.safe_load((cfg_dir / "slices.yaml").read_text(encoding="utf-8"))

    def _invert(section: dict) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, slugs in (section or {}).items():
            for slug in slugs or []:
                out[slug] = label
        return out

    return {
        "commodity_crop_type": _invert(raw.get("crop_type", {})),
        "commodity_group": _invert(raw.get("group", {})),
        "data_rich_countries": set(raw.get("data_rich_countries", []) or []),
        "stress": raw.get("stress", {}) or {},
    }


def load_gap_rules(config_dir: str | Path | None = None) -> list[dict]:
    cfg_dir = Path(config_dir) if config_dir is not None else _CONFIG_DIR
    raw = yaml.safe_load((cfg_dir / "acceptable_gaps.yaml").read_text(encoding="utf-8"))
    return raw.get("rules", []) or []


# ---------------------------------------------------------------------------
# Stress-year labelling (on actuals — evaluation only)
# ---------------------------------------------------------------------------

def classify_stress_years(predictions: pd.DataFrame, stress_cfg: dict) -> pd.DataFrame:
    """Add a ``year_type`` column (``stress`` / ``normal``) to *predictions*.

    Per (commodity, country) a linear trend is fit to ``y_actual`` over
    ``crop_year``; a year is ``stress`` when |residual| >= sigma_threshold * the
    residual std, or when it is one of ``named_shock_years``.  Series with fewer
    than ``min_years`` points fall back to the named shock years only.
    """
    sigma = float(stress_cfg.get("sigma_threshold", 1.5))
    min_years = int(stress_cfg.get("min_years", 10))
    shock = set(stress_cfg.get("named_shock_years", []) or [])

    df = predictions.copy()
    if "commodity" not in df.columns:
        df["commodity"] = "_single"

    stress_flag = pd.Series(False, index=df.index)
    for _, grp in df.groupby(["commodity", "country"]):
        y = pd.to_numeric(grp["y_actual"], errors="coerce")
        years = pd.to_numeric(grp["crop_year"], errors="coerce")
        valid = y.notna() & years.notna()
        if int(valid.sum()) >= min_years:
            coeffs = np.polyfit(years[valid], y[valid], 1)
            resid = y - np.polyval(coeffs, years)
            std = float(resid[valid].std(ddof=1))
            if std > 0:
                stress_flag.loc[grp.index] = (resid.abs() >= sigma * std).fillna(False)
    # Named macro shock years always count.
    stress_flag |= df["crop_year"].isin(shock)

    df["year_type"] = np.where(stress_flag, "stress", "normal")
    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _augment(predictions: pd.DataFrame) -> pd.DataFrame:
    """Attach residual + prior-year directional correctness for slicing.

    ``dir_correct`` compares sign(pred - prior_actual) with
    sign(actual - prior_actual) using the prior crop year's actual for the same
    (commodity, country) — NaN when no prior year exists.
    """
    df = predictions.copy()
    if "commodity" not in df.columns:
        df["commodity"] = "_single"
    df["y_actual"] = pd.to_numeric(df["y_actual"], errors="coerce")
    df["y_pred"] = pd.to_numeric(df["y_pred"], errors="coerce")
    df["residual"] = df["y_actual"] - df["y_pred"]

    prior = df[["commodity", "country", "crop_year", "y_actual"]].copy()
    prior["crop_year"] = prior["crop_year"] + 1
    prior = prior.rename(columns={"y_actual": "prior_actual"})
    df = df.merge(prior, on=["commodity", "country", "crop_year"], how="left")

    actual_chg = df["y_actual"] - df["prior_actual"]
    pred_chg = df["y_pred"] - df["prior_actual"]
    valid = actual_chg.notna() & pred_chg.notna()
    df["dir_correct"] = np.where(
        valid, np.sign(actual_chg) == np.sign(pred_chg), np.nan
    )
    return df


def _metrics(df: pd.DataFrame) -> dict[str, float]:
    """rmse / mae / directional_accuracy / n_obs for an augmented slice."""
    resid = df["residual"].dropna()
    dir_vals = pd.to_numeric(df["dir_correct"], errors="coerce").dropna()
    return {
        "n_obs": int(len(resid)),
        "rmse": float(np.sqrt((resid ** 2).mean())) if len(resid) else float("nan"),
        "mae": float(resid.abs().mean()) if len(resid) else float("nan"),
        "directional_accuracy": float(dir_vals.mean()) if len(dir_vals) else float("nan"),
    }


def compute_slice_metrics(
    predictions: pd.DataFrame,
    taxonomy: dict,
    commodity: str | None = None,
) -> pd.DataFrame:
    """Per-slice metrics as a tidy frame.

    Columns: ``slice_dim, slice_value, n_obs, rmse, mae, directional_accuracy``.

    Dimensions computed depend on what's present: ``overall``, ``country`` and
    ``year_type`` always; ``crop_type`` / ``group`` / ``data_richness`` whenever
    the rows span the taxonomy (i.e. a cross-commodity rollup, or a single
    commodity for its own crop_type/group).
    """
    if predictions.empty:
        return pd.DataFrame(columns=[
            "slice_dim", "slice_value", "n_obs", "rmse", "mae", "directional_accuracy",
        ])

    df = predictions.copy()
    if "commodity" not in df.columns:
        df["commodity"] = commodity or "_single"

    df = classify_stress_years(df, taxonomy.get("stress", {}))
    df = _augment(df)

    rich = taxonomy["data_rich_countries"]
    df["crop_type"] = df["commodity"].map(taxonomy["commodity_crop_type"])
    df["group"] = df["commodity"].map(taxonomy["commodity_group"])
    df["data_richness"] = np.where(df["country"].isin(rich), "rich", "sparse")

    rows: list[dict] = []
    rows.append({"slice_dim": "overall", "slice_value": "all", **_metrics(df)})
    for dim in ("crop_type", "group", "data_richness", "country", "year_type"):
        if dim not in df.columns:
            continue
        for value, grp in df.groupby(dim):
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            rows.append({"slice_dim": dim, "slice_value": str(value), **_metrics(grp)})

    return pd.DataFrame(rows, columns=[
        "slice_dim", "slice_value", "n_obs", "rmse", "mae", "directional_accuracy",
    ])


def flatten_for_mlflow(slice_df: pd.DataFrame) -> dict[str, float]:
    """Flat ``{metric_dim_value: float}`` dict for ``mlflow.log_metrics``."""
    out: dict[str, float] = {}
    for _, r in slice_df.iterrows():
        if r["slice_dim"] == "overall":
            tag = ""
        else:
            tag = f"_{r['slice_dim']}_{r['slice_value']}"
        for metric in ("rmse", "mae", "directional_accuracy"):
            val = r[metric]
            if pd.notna(val):
                out[f"{metric}{tag}"] = float(val)
    return out


# ---------------------------------------------------------------------------
# Governance: acceptable gaps
# ---------------------------------------------------------------------------

def evaluate_gaps(slice_df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """Check each pre-registered gap rule against the slice metrics.

    Columns: ``rule, kind, status (pass|warn|fail|skip), hard, observed,
    threshold, detail``.  Any ``hard`` rule with status ``fail`` disqualifies the
    model.
    """
    def _val(dim: str, value: str, metric: str) -> float:
        m = slice_df[(slice_df["slice_dim"] == dim) & (slice_df["slice_value"] == value)]
        return float(m[metric].iloc[0]) if len(m) else float("nan")

    rows: list[dict] = []
    for rule in rules:
        kind = rule["kind"]
        metric = rule["metric"]
        status, observed, threshold, detail = "skip", float("nan"), None, ""

        if kind == "ratio":
            worse = _val(rule["worse"]["dim"], rule["worse"]["value"], metric)
            base = _val(rule["baseline"]["dim"], rule["baseline"]["value"], metric)
            threshold = rule["max_ratio"]
            if np.isfinite(worse) and np.isfinite(base) and base > 0:
                observed = worse / base - 1.0
                status = "pass" if observed <= threshold else "fail"
                detail = f"{rule['worse']['value']}={worse:.4g} vs {rule['baseline']['value']}={base:.4g}"

        elif kind == "order":
            left = _val(rule["left"]["dim"], rule["left"]["value"], metric)
            right = _val(rule["right"]["dim"], rule["right"]["value"], metric)
            if np.isfinite(left) and np.isfinite(right):
                observed = left - right
                ok = left >= right if rule["must_be"] == ">=" else left <= right
                status = "pass" if ok else "fail"
                detail = f"{rule['left']['value']}={left:.4g} {rule['must_be']} {rule['right']['value']}={right:.4g}"

        elif kind == "floor":
            sub = slice_df[slice_df["slice_dim"] == rule["dim"]]
            vals = pd.to_numeric(sub[metric], errors="coerce").dropna()
            threshold = rule["min_value"]
            if len(vals):
                below = sub.loc[vals.index][vals < threshold]
                observed = float(vals.min())
                status = "pass" if below.empty else "fail"
                if not below.empty:
                    detail = "below floor: " + ", ".join(
                        f"{r.slice_value}={r[metric]:.3g}" for _, r in below.iterrows()
                    )

        rows.append({
            "rule": rule["name"], "kind": kind, "status": status,
            "hard": bool(rule.get("hard", False)), "observed": observed,
            "threshold": threshold, "detail": detail,
        })

    return pd.DataFrame(rows, columns=[
        "rule", "kind", "status", "hard", "observed", "threshold", "detail",
    ])


def gaps_passed(gap_df: pd.DataFrame) -> bool:
    """True unless any hard-rule failed."""
    hard_fail = gap_df[(gap_df["hard"]) & (gap_df["status"] == "fail")]
    return hard_fail.empty


# ---------------------------------------------------------------------------
# Cross-commodity rollup
# ---------------------------------------------------------------------------

def rollup_cross_commodity(
    predictions_by_commodity: dict[str, pd.DataFrame],
    taxonomy: dict,
) -> pd.DataFrame:
    """Concatenate per-commodity predictions (tagged) and slice across them.

    This is where tree-vs-annual / group / data-richness become visible — a
    single commodity run cannot slice itself by crop_type.
    """
    frames = []
    for commodity, preds in predictions_by_commodity.items():
        if preds is None or preds.empty:
            continue
        tagged = preds.copy()
        tagged["commodity"] = commodity
        frames.append(tagged)
    if not frames:
        return compute_slice_metrics(pd.DataFrame(columns=list(_PRED_COLS)), taxonomy)
    return compute_slice_metrics(pd.concat(frames, ignore_index=True), taxonomy)
