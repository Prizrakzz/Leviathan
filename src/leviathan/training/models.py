"""Shared model factories for training and certification jobs."""
from __future__ import annotations


def make_tree_model(name: str, **hp):
    """Build the tree models used by Leviathan training jobs.

    Defaults intentionally match the historical trainer defaults.  Certification
    jobs import this factory so diagnostics replay the same candidate class
    instead of drifting into a subtly different estimator.
    """
    common = dict(
        n_estimators=hp.get("n_estimators", 400),
        max_depth=hp.get("max_depth", 4),
        learning_rate=hp.get("learning_rate", 0.03),
        subsample=hp.get("subsample", 0.8),
        reg_lambda=hp.get("reg_lambda", 1.0),
        min_child_weight=hp.get("min_child_weight", 1),
    )
    if name == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(
            **common,
            colsample_bytree=hp.get("colsample_bytree", 0.8),
            reg_alpha=hp.get("reg_alpha", hp.get("lambda_l1", 0.0)),
            n_jobs=-1,
        )
    if name == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            **common,
            num_leaves=hp.get("num_leaves", 31),
            min_data_in_leaf=hp.get("min_data_in_leaf", hp.get("min_child_samples", 20)),
            colsample_bytree=hp.get("colsample_bytree", 0.8),
            feature_fraction=hp.get("feature_fraction", hp.get("colsample_bytree", 0.8)),
            lambda_l1=hp.get("lambda_l1", hp.get("reg_alpha", 0.0)),
            lambda_l2=hp.get("lambda_l2", hp.get("reg_lambda", 1.0)),
            n_jobs=-1,
            verbose=-1,
        )
    raise ValueError(f"unknown model {name!r} (xgboost|lightgbm)")
