from __future__ import annotations

import pandas as pd
import pytest

from leviathan.eda.models import Exactness, TableSpec
from leviathan.eda.pit import PITBoundaryError, truncate_at_knowledge_time
from leviathan.eda.profiling import profile_frame
from leviathan.silver.registry import load_registry


def test_future_rows_cannot_change_prior_cutoff_profile() -> None:
    spec = TableSpec.from_contract(load_registry().table("silver_wasde"))
    columns = list(spec.declared_columns)
    base = pd.DataFrame([{column: None for column in columns} for _ in range(3)])
    base[spec.knowledge_date_col] = ["2024-01-12", "2024-02-08", "2024-03-08"]
    value = spec.value_columns[0]
    base[value] = [10.0, 11.0, 12.0]
    future = base.iloc[[0]].copy()
    future[spec.knowledge_date_col] = "2025-01-10"
    future[value] = 999999.0
    cutoff = "2024-12-31"

    expected = truncate_at_knowledge_time(base, spec, cutoff)
    actual = truncate_at_knowledge_time(pd.concat([base, future], ignore_index=True), spec, cutoff)
    pd.testing.assert_frame_equal(actual, expected)
    expected_profile = profile_frame(expected, spec, exactness=Exactness.EXACT)
    actual_profile = profile_frame(actual, spec, exactness=Exactness.EXACT)
    assert actual_profile.to_dict() == expected_profile.to_dict()


def test_truncation_refuses_observation_time_substitution() -> None:
    spec = TableSpec.from_contract(load_registry().table("silver_unica_biweekly_season_history"))
    with pytest.raises(PITBoundaryError, match="knowledge-time"):
        truncate_at_knowledge_time(
            pd.DataFrame({"fortnight_date": ["2024-01-01"]}), spec, "2024-02-01"
        )

