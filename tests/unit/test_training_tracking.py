"""Unit tests for the MLflow reproducibility tracking helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from leviathan.training.cv import WalkForwardResult
from leviathan.training.tracking import (
    data_fingerprint,
    feature_set_sha,
    log_training_run,
)


def _train_df() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["br", "br", "us", "us"],
        "crop_year": [2010, 2011, 2010, 2011],
        "gdd_z_a": [0.1, 0.2, 0.3, 0.4],
        "psd_available": [1.0, 1.0, 1.0, 1.0],
        "label_production_quantity": [100.0, 110.0, 200.0, 210.0],
    })


# ---------------------------------------------------------------------------
# feature_set_sha
# ---------------------------------------------------------------------------

def test_feature_set_sha_is_deterministic_and_order_independent() -> None:
    a = feature_set_sha(["gdd_z_a", "psd_available"], "PH1")
    b = feature_set_sha(["psd_available", "gdd_z_a"], "PH1")  # reordered
    assert a == b
    # different params hash → different sha
    assert feature_set_sha(["gdd_z_a"], "PH1") != feature_set_sha(["gdd_z_a"], "PH2")
    # different column set → different sha
    assert feature_set_sha(["gdd_z_a"], "PH1") != feature_set_sha(["gdd_z_a", "x"], "PH1")


# ---------------------------------------------------------------------------
# data_fingerprint
# ---------------------------------------------------------------------------

def test_data_fingerprint_stable_under_reorder_changes_on_value() -> None:
    df = _train_df()
    cols = ["gdd_z_a", "psd_available"]
    fp = data_fingerprint(df, cols, "label_production_quantity")

    # Row + column reorder must not change the fingerprint.
    shuffled = df.iloc[[2, 0, 3, 1]][
        ["label_production_quantity", "psd_available", "crop_year", "gdd_z_a", "country"]
    ]
    assert data_fingerprint(shuffled, cols, "label_production_quantity") == fp

    # A single changed feature value must change it (revision detector).
    revised = df.copy()
    revised.loc[0, "gdd_z_a"] = 0.999
    assert data_fingerprint(revised, cols, "label_production_quantity") != fp

    # A changed LABEL value must change it too.
    revised_label = df.copy()
    revised_label.loc[0, "label_production_quantity"] = 999.0
    assert data_fingerprint(revised_label, cols, "label_production_quantity") != fp


# ---------------------------------------------------------------------------
# log_training_run with a stand-in mlflow
# ---------------------------------------------------------------------------

class _FakeMlflow:
    def __init__(self):
        self.tags: dict = {}
        self.params: dict = {}
        self.metrics: dict = {}

    def active_run(self):
        return None

    def set_tag(self, k, v):
        self.tags[k] = v

    def log_param(self, k, v):
        self.params[k] = v

    def log_metric(self, k, v):
        self.metrics[k] = v

    def log_metrics(self, d):
        self.metrics.update(d)


def test_log_training_run_records_identity_and_metrics() -> None:
    df = _train_df()
    cols = ["gdd_z_a", "psd_available"]
    result = WalkForwardResult(
        folds=[], predictions=pd.DataFrame(), rmse=0.1, mae=0.08,
        directional_accuracy=0.7, n_folds=2,
    )
    fake = _FakeMlflow()
    out = log_training_run(
        "corn_cbot", "climate", df, cols, result,
        target_col="label_production_quantity", params_hash="PH1",
        bucket=None, mlflow=fake, snapshot=False,
    )

    assert fake.tags["commodity"] == "corn_cbot"
    assert fake.tags["tier"] == "climate"
    assert fake.tags["feature_set_sha"] == feature_set_sha(cols, "PH1")
    assert fake.tags["data_fingerprint"] == out["data_fingerprint"]
    assert fake.params["n_features"] == 2
    assert fake.params["n_train_rows"] == 4
    assert fake.params["train_first_year"] == 2010
    assert fake.params["train_last_year"] == 2011
    # cv metrics flowed through
    assert fake.metrics["rmse"] == 0.1
    assert fake.metrics["directional_accuracy"] == 0.7
    # no snapshot requested → no snapshot_uri tag
    assert "snapshot_uri" not in fake.tags
