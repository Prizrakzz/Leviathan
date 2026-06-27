from __future__ import annotations

import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from leviathan.training.cv import (
    available_cv_policies,
    resolve_cv_policy,
    walk_forward_cv,
)


def _panel(start: int = 1980, end: int = 2010) -> pd.DataFrame:
    rows = []
    for year in range(start, end + 1):
        rows.append({
            "country": "united_states",
            "crop_year": year,
            "feature_a": float(year - start),
            "target_value": float(year - start) / 10.0,
        })
    return pd.DataFrame(rows)


def test_available_cv_policies_include_named_windows() -> None:
    assert set(available_cv_policies()) >= {
        "expanding_full_history",
        "expanding_post_1990",
        "expanding_post_2000",
        "rolling_25y",
        "rolling_30y",
    }


def test_resolve_cv_policy_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="unknown cv_policy"):
        resolve_cv_policy("not_a_policy")


def test_expanding_policy_preserves_legacy_prior_year_training() -> None:
    result = walk_forward_cv(
        _panel(2000, 2006),
        "target_value",
        ["feature_a"],
        LinearRegression(),
        min_train_years=3,
        cv_policy="expanding_full_history",
    )

    assert result.cv_policy == "expanding_full_history"
    assert [fold.test_year for fold in result.folds] == [2003, 2004, 2005, 2006]
    assert [fold.fold_start_train_year for fold in result.folds] == [2000, 2000, 2000, 2000]
    assert [fold.fold_end_train_year for fold in result.folds] == [2002, 2003, 2004, 2005]
    assert [fold.train_year_count for fold in result.folds] == [3, 4, 5, 6]


def test_post_2000_policy_excludes_older_history() -> None:
    result = walk_forward_cv(
        _panel(1995, 2006),
        "target_value",
        ["feature_a"],
        LinearRegression(),
        min_train_years=3,
        cv_policy="expanding_post_2000",
    )

    assert result.train_start_year == 2000
    assert min(fold.fold_start_train_year for fold in result.folds if fold.fold_start_train_year) >= 2000
    assert result.folds[0].test_year == 2003


def test_rolling_policy_limits_training_window() -> None:
    result = walk_forward_cv(
        _panel(1970, 2010),
        "target_value",
        ["feature_a"],
        LinearRegression(),
        min_train_years=5,
        cv_policy="rolling_25y",
    )

    assert result.rolling_window_years == 25
    assert max(fold.train_year_count or 0 for fold in result.folds) == 25
    last = result.folds[-1]
    assert last.test_year == 2010
    assert last.fold_start_train_year == 1985
    assert last.fold_end_train_year == 2009
