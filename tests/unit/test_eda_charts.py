from __future__ import annotations

import warnings

import matplotlib
import pandas as pd

matplotlib.use("Agg")

from leviathan.eda.charts import (  # noqa: E402
    plot_correlation_heatmap,
    plot_missingness,
    plot_numeric_distribution,
    plot_temporal_coverage,
    plot_top_categories,
)
from leviathan.eda.models import Exactness, TableSpec  # noqa: E402
from leviathan.eda.profiling import profile_frame  # noqa: E402


def _profile_and_frame():
    contract = {
        "table_name": "silver_chart_test",
        "layer": "silver",
        "domain": "weather",
        "lifecycle_class": "source",
        "s3_root": "s3://leviathan-dev-shahem-001/silver/chart_test",
        "physical_columns": [
            {"name": "date", "target_arrow_type": "date32[day]", "nullable": False},
            {"name": "category", "target_arrow_type": "string", "nullable": False},
            {"name": "value", "target_arrow_type": "float64", "nullable": True},
            {"name": "aux", "target_arrow_type": "float64", "nullable": True},
        ],
        "partition_keys": [],
        "natural_key": ["date", "category"],
        "required_nonnull": ["date", "category"],
        "value_columns": ["value", "aux"],
        "min_nonnull_frac": 0.5,
        "knowledge_date_col": None,
        "knowledge_semantics": None,
        "publication_lag_days": 0,
        "freshness_sla": {"cadence": "monthly"},
    }
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=12, freq="MS").astype(str),
            "category": ["north", "south"] * 6,
            "value": [None] + [float(i) for i in range(1, 12)],
            "aux": [float(i * 2) for i in range(12)],
        }
    )
    return profile_frame(frame, TableSpec.from_contract(contract)), frame


def _all_text(figure):
    return " ".join(text.get_text() for axis in figure.axes for text in axis.texts)


def test_static_charts_label_scope_sample_size_and_exactness():
    profile, frame = _profile_and_frame()
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        warnings.simplefilter("error", PendingDeprecationWarning)
        figures = [
            plot_missingness(profile),
            plot_numeric_distribution(frame, "value", exactness=Exactness.EXACT),
            plot_temporal_coverage(frame, "date", exactness=Exactness.EXACT),
            plot_top_categories(frame, "category", exactness=Exactness.EXACT),
            plot_correlation_heatmap(profile, method="spearman"),
        ]

    try:
        assert all(figure.axes[0].get_title(loc="left") for figure in figures)
        assert all("exact" in _all_text(figure) for figure in figures)
    finally:
        import matplotlib.pyplot as plt

        for figure in figures:
            plt.close(figure)
