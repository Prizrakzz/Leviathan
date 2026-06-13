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

from dataclasses import dataclass, field

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


@dataclass
class WalkForwardResult:
    """Aggregate results across all test folds."""
    folds: list[FoldResult]
    predictions: pd.DataFrame   # columns: country, crop_year, y_actual, y_pred
    rmse: float                 # root-mean-squared error across all folds
    mae: float                  # mean absolute error across all folds
    directional_accuracy: float | None  # fraction of folds with correct sign, or None
    n_folds: int

    def as_mlflow_metrics(self) -> dict[str, float]:
        """Flat dict suitable for mlflow.log_metrics()."""
        m: dict[str, float] = {"rmse": self.rmse, "mae": self.mae, "n_folds": self.n_folds}
        if self.directional_accuracy is not None:
            m["directional_accuracy"] = self.directional_accuracy
        return m


def walk_forward_cv(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list[str],
    model: object,
    min_train_years: int = 5,
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

    Returns:
        WalkForwardResult with per-fold metrics and a combined predictions
        DataFrame suitable for analysis and MLflow logging.

    Raises:
        ValueError: If fewer than min_train_years + 1 years are present, or
                    if no folds produce any predictions.
    """
    years = sorted(df["crop_year"].unique())
    if len(years) < min_train_years + 1:
        raise ValueError(
            f"walk_forward_cv needs at least {min_train_years + 1} unique crop_years; "
            f"got {len(years)} ({years[0]}–{years[-1]})."
        )

    # Pre-index by year for O(1) lookup of prior-year actuals.
    by_year: dict[int, pd.DataFrame] = {
        yr: grp.set_index("country") for yr, grp in df.groupby("crop_year")
    }

    all_pred_frames: list[pd.DataFrame] = []
    fold_results: list[FoldResult] = []

    for fold_idx, test_year in enumerate(years[min_train_years:], start=min_train_years):
        train_years = set(years[:fold_idx])
        train_df = df[df["crop_year"].isin(train_years)]
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

        fold_pred = pd.DataFrame({
            "country": test_df["country"].values,
            "crop_year": test_year,
            "y_actual": y_test.to_numpy(),
            "y_pred": y_pred,
        })
        all_pred_frames.append(fold_pred)

        fold_results.append(FoldResult(
            test_year=test_year,
            fold_end_train_year=years[fold_idx - 1],
            n_train_rows=len(train_df),
            n_test_rows=len(test_df),
            rmse=fold_rmse,
            mae=fold_mae,
            directional_accuracy=dir_acc,
        ))

    if not fold_results:
        raise ValueError(
            "walk_forward_cv produced no folds. "
            "Check that target_col has non-NaN values in enough crop years."
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
    )
