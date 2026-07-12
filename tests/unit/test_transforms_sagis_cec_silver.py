"""SILVER-F058: SAGIS CEC bronze -> silver producer (authoritative selection + revision math).

Pure Python -- no S3/AWS.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.sagis_cec import (
    CecObservation,
    NATURAL_KEY,
    OUTPUT_COLUMNS,
    SagisConflictError,
    select_authoritative,
    transform_sagis_cec,
)


def _obs(**kw) -> CecObservation:
    base = dict(production_year=2024, report_month=10, crop="maize", scope="commercial",
                estimate_number=1, current_estimate_t=1000.0, release_date="2024-02-01")
    base.update(kw)
    return CecObservation(**base)


def _season(year: int, values: list[float], release_prefix: str) -> list[CecObservation]:
    """One production year's numbered estimates (estimate_number 1..n)."""
    return [
        _obs(production_year=year, report_month=10 + i, estimate_number=i + 1,
             current_estimate_t=v, release_date=f"{release_prefix}-{i:02d}")
        for i, v in enumerate(values)
    ]


class TestAuthoritativeSelection:
    def test_latest_release_wins(self):
        obs = [
            _obs(estimate_number=2, current_estimate_t=1100, release_date="2024-03-01"),
            _obs(estimate_number=2, current_estimate_t=9999, release_date="2024-01-01"),
        ]
        chosen = select_authoritative(obs)
        assert len(chosen) == 1 and chosen[0].current_estimate_t == 1100

    def test_format_priority_breaks_release_tie(self):
        obs = [
            _obs(estimate_number=2, current_estimate_t=1100, release_date="2024-03-01", source_format="pdf"),
            _obs(estimate_number=2, current_estimate_t=1200, release_date="2024-03-01", source_format="doc"),
        ]
        chosen = select_authoritative(obs)
        assert chosen[0].current_estimate_t == 1100   # pdf > doc

    def test_true_tie_disagreement_fails_closed(self):
        obs = [
            _obs(estimate_number=2, current_estimate_t=1100, release_date="2024-03-01",
                 source_format="pdf", source_key="a"),
            _obs(estimate_number=2, current_estimate_t=1200, release_date="2024-03-01",
                 source_format="pdf", source_key="a"),
        ]
        with pytest.raises(SagisConflictError):
            select_authoritative(obs)


class TestRevisionMath:
    @pytest.fixture()
    def silver(self) -> pd.DataFrame:
        obs = _season(2023, [900, 950, 1000], "2023") + _season(2024, [1100, 1210], "2024")
        return transform_sagis_cec(obs)

    def test_schema(self, silver):
        assert list(silver.columns) == OUTPUT_COLUMNS

    def test_natural_key_unique(self, silver):
        assert not silver.duplicated(subset=NATURAL_KEY).any()

    def test_prior_estimate_no_lookahead(self, silver):
        r = silver[(silver.production_year == 2024) & (silver.estimate_number == 2)].iloc[0]
        assert r.prior_estimate_t == 1100        # estimate 1, never a later estimate
        assert r.revision_t == 110 and r.revision_pct == pytest.approx(10.0)

    def test_first_estimate_has_null_revision(self, silver):
        r = silver[(silver.production_year == 2024) & (silver.estimate_number == 1)].iloc[0]
        assert pd.isna(r.prior_estimate_t) and pd.isna(r.revision_t) and pd.isna(r.revision_pct)

    def test_prior_year_final(self, silver):
        r = silver[(silver.production_year == 2024) & (silver.estimate_number == 1)].iloc[0]
        assert r.prior_year_final_t == 1000       # 2023's highest estimate_number (3rd)
        assert r.revision_surprise == pytest.approx(10.0)   # (1100-1000)/1000*100

    def test_prior_year_final_absent_for_first_season(self):
        obs = _season(2023, [900, 950, 1000], "2023")
        df = transform_sagis_cec(obs)
        assert df["prior_year_final_t"].isna().all()   # no 2022 -> honest null


class TestZeroDenominator:
    def test_zero_prior_estimate_gives_null_pct(self):
        obs = [
            _obs(production_year=2024, estimate_number=1, current_estimate_t=0.0, release_date="2024-02-01"),
            _obs(production_year=2024, report_month=11, estimate_number=2, current_estimate_t=500.0,
                 release_date="2024-03-01"),
        ]
        df = transform_sagis_cec(obs)
        r = df[df.estimate_number == 2].iloc[0]
        assert r.revision_t == 500 and pd.isna(r.revision_pct)   # /0 -> null, not inf


def test_empty_input_returns_empty_schema():
    df = transform_sagis_cec([])
    assert df.empty and list(df.columns) == OUTPUT_COLUMNS
