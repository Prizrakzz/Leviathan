from __future__ import annotations

import pytest

from leviathan.training.feature_policy import (
    FeaturePolicyError,
    FeaturePolicyRegistry,
    FeaturePolicyRule,
    apply_feature_policy,
)


def _registry() -> FeaturePolicyRegistry:
    return FeaturePolicyRegistry(
        default_policy="fundamental_physical",
        rules=(
            FeaturePolicyRule(
                pattern="crush_margin_z",
                policy="allowed_economic_driver",
                mechanism="soy_crush",
                eligible_targets=("production_quantity",),
                reason="processing profitability",
            ),
            FeaturePolicyRule(
                pattern="cot_",
                policy="diagnostic_only",
                mechanism="positioning",
                eligible_targets=(),
                reason="market behavior",
            ),
            FeaturePolicyRule(
                pattern="calendar_spread",
                policy="excluded_market_signal",
                mechanism="term_structure",
                eligible_targets=(),
                reason="market signal",
            ),
        ),
    )


def test_apply_feature_policy_keeps_fundamentals_and_allowed_drivers() -> None:
    kept, report = apply_feature_policy(
        ["gdd_z_us", "crush_margin_z"],
        target="production_quantity",
        registry=_registry(),
    )
    assert kept == ["gdd_z_us", "crush_margin_z"]
    assert report["allowed_economic_drivers"][0]["feature"] == "crush_margin_z"


def test_apply_feature_policy_drops_diagnostic_features() -> None:
    kept, report = apply_feature_policy(
        ["gdd_z_us", "cot_mm_net_z"],
        target="production_quantity",
        registry=_registry(),
    )
    assert kept == ["gdd_z_us"]
    assert report["dropped_diagnostic_features"] == ["cot_mm_net_z"]


def test_apply_feature_policy_rejects_excluded_market_signal() -> None:
    with pytest.raises(FeaturePolicyError, match="excluded_market_signal"):
        apply_feature_policy(
            ["calendar_spread_front_second"],
            target="production_quantity",
            registry=_registry(),
        )


def test_apply_feature_policy_rejects_driver_for_wrong_target() -> None:
    with pytest.raises(FeaturePolicyError, match="not target"):
        apply_feature_policy(
            ["crush_margin_z"],
            target="yield",
            registry=_registry(),
        )
