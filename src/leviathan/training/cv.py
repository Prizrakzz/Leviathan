"""Walk-forward cross-validation for commodity ML models.

The critical anti-leakage invariant: for any test year T, the model is fitted
exclusively on data from years strictly before T, and any transformation
(scaler, expanding baseline) is fitted on that same training window only.
Fitting a scaler on the full dataset before splitting is the most common CV
mistake in time-series ML and is what this function prevents.

Usage
-----
    from leviathan.training.cv import walk_forward_cv
    import xgboost as xgb

    df = pd.read_parquet("s3://.../gold/feature_matrix/commodity=corn_cbot/")
    result = walk_forward_cv(
        df=df,
        target_col="label_production_quantity",
        feature_cols=selected_features,
        model=xgb.XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05),
    )
    print(result.rmse, result.directional_accuracy)
    mlflow.log_metrics(result.as_mlflow_metrics())
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone


@dataclass
class FoldResult:
    """Metrics for a single test year."""
    test_year: int
    fold_end_train_year: int
    n_train_rows: int
    n_test_rows: int
    rmse: float
    mae: float
    directional_accuracy: float | None  # None when prior-year actuals are unavailable
    fold_start_train_year: int | None = None
    train_year_count: int | None = None
    cv_policy: str = "expanding_full_history"


@dataclass
class WalkForwardResult:
    """Aggregate results across all test folds."""
    folds: list[FoldResult]
    predictions: pd.DataFrame   # columns: country, crop_year, y_actual, y_pred
    rmse: float                 # root-mean-squared error across all folds
    mae: float                  # mean absolute error across all folds
    directional_accuracy: float | None  # fraction of folds with correct sign, or None
    n_folds: int
    sliced_metrics: "pd.DataFrame | None" = None  # populated by with_slices()
    cv_policy: str = "expanding_full_history"
    min_train_years: int = 5
    train_start_year: int | None = None
    rolling_window_years: int | None = None

    def with_slices(self, commodity: str, config_dir: str | None = None) -> "WalkForwardResult":
        """Attach per-slice metrics (country, year_type, plus this commodity's
        crop_type/group) computed from ``predictions``.  Returns self for
        chaining.  Aggregate metrics are unchanged — slices are additive.

        Cross-commodity slices (tree-vs-annual) come from
        ``leviathan.training.slices.rollup_cross_commodity`` after all runs.
        """
        from leviathan.training.slices import compute_slice_metrics, load_taxonomy
        taxonomy = load_taxonomy(config_dir)
        self.sliced_metrics = compute_slice_metrics(self.predictions, taxonomy, commodity)
        return self

    def as_mlflow_metrics(self) -> dict[str, float]:
        """Flat dict suitable for mlflow.log_metrics().

        Always includes the aggregate rmse/mae/directional_accuracy; when
        ``with_slices()`` has run, the flattened per-slice metrics
        (e.g. ``rmse_year_type_stress``, ``directional_accuracy_country_vietnam``)
        are merged in.
        """
        m: dict[str, float] = {"rmse": self.rmse, "mae": self.mae, "n_folds": self.n_folds}
        if self.directional_accuracy is not None:
            m["directional_accuracy"] = self.directional_accuracy
        if self.sliced_metrics is not None and not self.sliced_metrics.empty:
            from leviathan.training.slices import flatten_for_mlflow
            for key, val in flatten_for_mlflow(self.sliced_metrics).items():
                # don't clobber the canonical aggregate keys
                if key not in m:
                    m[key] = val
        return m


_CV_POLICIES: dict[str, dict[str, int | None]] = {
    "expanding_full_history": {"train_start_year": None, "rolling_window_years": None},
    "expanding_post_1990": {"train_start_year": 1990, "rolling_window_years": None},
    "expanding_post_2000": {"train_start_year": 2000, "rolling_window_years": None},
    "rolling_25y": {"train_start_year": None, "rolling_window_years": 25},
    "rolling_30y": {"train_start_year": None, "rolling_window_years": 30},
}


def _prediction_identity_columns(df: pd.DataFrame) -> list[str]:
    cols = ["country", "crop_year"]
    for col in ("snapshot_stage", "as_of_date"):
        if col in df.columns:
            cols.append(col)
    return cols


def resolve_cv_policy(
    cv_policy: str,
    *,
    train_start_year: int | None = None,
    rolling_window_years: int | None = None,
) -> tuple[str, int | None, int | None]:
    """Resolve a named CV policy plus optional explicit overrides."""
    name = (cv_policy or "expanding_full_history").strip()
    if name not in _CV_POLICIES:
        raise ValueError(
            f"unknown cv_policy {name!r}; expected one of {sorted(_CV_POLICIES)}"
        )
    spec = _CV_POLICIES[name]
    resolved_start = train_start_year if train_start_year is not None else spec["train_start_year"]
    resolved_window = (
        rolling_window_years
        if rolling_window_years is not None else spec["rolling_window_years"]
    )
    if resolved_window is not None and int(resolved_window) <= 0:
        raise ValueError("rolling_window_years must be positive")
    return name, resolved_start, resolved_window


def available_cv_policies() -> tuple[str, ...]:
    """Return supported CV policy names for CLIs/tests."""
    return tuple(sorted(_CV_POLICIES))


def walk_forward_cv(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list[str],
    model: object,
    min_train_years: int = 5,
    cv_policy: str = "expanding_full_history",
    train_start_year: int | None = None,
    rolling_window_years: int | None = None,
) -> WalkForwardResult:
    """Walk-forward cross-validation with anti-leakage guarantees.

    For each test year T (starting after ``min_train_years`` of history):
      1. Train on all rows where crop_year < T.
      2. Predict rows where crop_year == T.
      3. The model is cloned fresh each fold — no weight carry-over.

    No scaler is applied by default because the current model lineup
    (XGBoost, LightGBM, Random Forest) are tree-based and invariant to
    monotonic feature transforms.  If you add a distance- or gradient-based
    model (e.g. the planned tabular autoencoder), add a fold-local scaler
    inside your training script before calling this function.

    NaN values in features are passed through unchanged.  XGBoost and
    LightGBM learn the optimal split direction for NaN at each node; this is
    the intended behaviour for our missingness-as-signal design.  Rows where
    the TARGET is NaN are dropped from both train and test.

    Args:
        df:               Wide feature matrix — one row per (country, crop_year).
                          Must contain columns "country", "crop_year",
                          all ``feature_cols``, and ``target_col``.
        target_col:       Label column name (e.g. "label_production_quantity").
        feature_cols:     Feature columns to use.  Select from the feature
                          catalog by scope to control what the model sees.
        model:            Any sklearn-compatible estimator (fit / predict).
                          Must support sklearn.base.clone().
        min_train_years:  Minimum number of unique crop years required before
                          the first test fold is created.  Default 5.
        cv_policy:        Named training-window policy.  Default preserves the
                          historical expanding-window behavior.
        train_start_year: Optional lower bound for training years.
        rolling_window_years:
                          Optional rolling lookback window, e.g. 25 means
                          train on years T-25 through T-1.

    Returns:
        WalkForwardResult with per-fold metrics and a combined predictions
        DataFrame suitable for analysis and MLflow logging.

    Raises:
        ValueError: If fewer than min_train_years + 1 years are present, or
                    if no folds produce any predictions.
    """
    policy_name, resolved_start, resolved_window = resolve_cv_policy(
        cv_policy,
        train_start_year=train_start_year,
        rolling_window_years=rolling_window_years,
    )
    years = sorted(int(y) for y in df["crop_year"].dropna().unique())
    if len(years) < min_train_years + 1:
        raise ValueError(
            f"walk_forward_cv needs at least {min_train_years + 1} unique crop_years; "
            f"got {len(years)} ({years[0]}–{years[-1]})."
        )

    identity_cols = _prediction_identity_columns(df)
    # Pre-index by year for O(1) lookup of prior-year actuals. Snapshot-stage
    # datasets repeat annual labels across stages, so the prior-year reference
    # must collapse to one value per country.
    by_year: dict[int, pd.DataFrame] = {
        yr: grp.sort_values(identity_cols)
        .drop_duplicates("country", keep="first")
        .set_index("country")
        for yr, grp in df.groupby("crop_year")
    }

    all_pred_frames: list[pd.DataFrame] = []
    fold_results: list[FoldResult] = []

    for test_year in years:
        train_years = [year for year in years if year < test_year]
        if resolved_start is not None:
            train_years = [year for year in train_years if year >= int(resolved_start)]
        if resolved_window is not None:
            lower_bound = test_year - int(resolved_window)
            train_years = [year for year in train_years if year >= lower_bound]
        if len(train_years) < min_train_years:
            continue
        train_df = df[df["crop_year"].isin(set(train_years))]
        test_df = df[df["crop_year"] == test_year]

        # Drop rows where the target is NaN — a NaN label is not a training
        # signal and cannot be evaluated.
        train_df = train_df[train_df[target_col].notna()]
        test_df = test_df[test_df[target_col].notna()]

        if train_df.empty or test_df.empty:
            continue

        X_train = train_df[feature_cols]
        y_train = train_df[target_col].astype(float)
        X_test = test_df[feature_cols]
        y_test = test_df[target_col].astype(float)

        # Clone so each fold starts from the same untrained state.
        m = clone(model)
        m.fit(X_train, y_train)
        y_pred = m.predict(X_test)

        residuals = y_test.to_numpy() - y_pred
        fold_rmse = float(np.sqrt((residuals ** 2).mean()))
        fold_mae = float(np.abs(residuals).mean())

        # Directional accuracy: did we predict whether production went up or
        # down relative to the prior year?  Uses test_year - 1 actuals joined
        # on country.  None when prior-year data is absent.
        dir_acc: float | None = None
        prior_year = test_year - 1
        if prior_year in by_year:
            prior = by_year[prior_year][target_col].reindex(test_df["country"].values)
            prior_vals = prior.to_numpy(dtype=float)
            actual_change = y_test.to_numpy() - prior_vals
            pred_change = y_pred - prior_vals
            valid = np.isfinite(actual_change) & np.isfinite(pred_change)
            if valid.sum() > 0:
                dir_acc = float(
                    (np.sign(actual_change[valid]) == np.sign(pred_change[valid])).mean()
                )

        fold_pred = test_df[identity_cols].copy()
        fold_pred["y_actual"] = y_test.to_numpy()
        fold_pred["y_pred"] = y_pred
        all_pred_frames.append(fold_pred)

        fold_results.append(FoldResult(
            test_year=test_year,
            fold_end_train_year=max(train_years),
            n_train_rows=len(train_df),
            n_test_rows=len(test_df),
            rmse=fold_rmse,
            mae=fold_mae,
            directional_accuracy=dir_acc,
            fold_start_train_year=min(train_years),
            train_year_count=len(train_years),
            cv_policy=policy_name,
        ))

    if not fold_results:
        raise ValueError(
            "walk_forward_cv produced no folds. "
            "Check that target_col has non-NaN values in enough crop years "
            "after applying the CV policy."
        )

    predictions = pd.concat(all_pred_frames, ignore_index=True)

    all_residuals = predictions["y_actual"] - predictions["y_pred"]
    agg_rmse = float(np.sqrt((all_residuals ** 2).mean()))
    agg_mae = float(all_residuals.abs().mean())

    dir_accs = [f.directional_accuracy for f in fold_results if f.directional_accuracy is not None]
    agg_dir_acc = float(np.mean(dir_accs)) if dir_accs else None

    return WalkForwardResult(
        folds=fold_results,
        predictions=predictions,
        rmse=agg_rmse,
        mae=agg_mae,
        directional_accuracy=agg_dir_acc,
        n_folds=len(fold_results),
        cv_policy=policy_name,
        min_train_years=min_train_years,
        train_start_year=resolved_start,
        rolling_window_years=resolved_window,
    )
