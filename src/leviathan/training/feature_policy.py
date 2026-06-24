"""Feature policy preflight for the fundamental ML experiment track."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "features" / "feature_policies.yaml"
)

VALID_POLICIES = {
    "fundamental_physical",
    "certified_economic_driver",
    "diagnostic_only",
    "excluded_market_signal",
}

LEGACY_POLICY_ALIASES = {
    "allowed_economic_driver": "certified_economic_driver",
}


class FeaturePolicyError(ValueError):
    """A feature set violates the fundamental experiment policy."""


@dataclass(frozen=True)
class FeaturePolicyRule:
    pattern: str
    policy: str
    mechanism: str
    eligible_targets: tuple[str, ...]
    reason: str

    def matches(self, feature_name: str) -> bool:
        return feature_name == self.pattern or feature_name.startswith(self.pattern)


@dataclass(frozen=True)
class FeaturePolicyRegistry:
    default_policy: str
    rules: tuple[FeaturePolicyRule, ...]

    def rule_for(self, feature_name: str) -> FeaturePolicyRule | None:
        matches = [rule for rule in self.rules if rule.matches(feature_name)]
        if not matches:
            return None
        return max(matches, key=lambda rule: len(rule.pattern))


def _canonical_policy(value: str) -> str:
    return LEGACY_POLICY_ALIASES.get(value, value)


def load_feature_policy(path: str | Path | None = None) -> FeaturePolicyRegistry:
    raw = yaml.safe_load(Path(path or _DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    default = _canonical_policy(str(raw.get("default_policy", "fundamental_physical")))
    if default not in VALID_POLICIES:
        raise FeaturePolicyError(f"invalid default feature policy {default!r}")
    rules: list[FeaturePolicyRule] = []
    for index, item in enumerate(raw.get("policies", [])):
        policy = _canonical_policy(str(item["policy"]))
        if policy not in VALID_POLICIES:
            raise FeaturePolicyError(f"policy[{index}] invalid policy {policy!r}")
        pattern = str(item["pattern"]).strip()
        if not pattern:
            raise FeaturePolicyError(f"policy[{index}] missing pattern")
        rules.append(FeaturePolicyRule(
            pattern=pattern,
            policy=policy,
            mechanism=str(item.get("mechanism", "")),
            eligible_targets=tuple(str(value) for value in item.get("eligible_targets", [])),
            reason=str(item.get("reason", "")),
        ))
    return FeaturePolicyRegistry(default_policy=default, rules=tuple(rules))


def apply_feature_policy(
    feature_cols: list[str],
    *,
    target: str,
    registry: FeaturePolicyRegistry | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Filter/validate selected columns before training.

    Diagnostic features are removed from fitting. Excluded market-signal
    features fail the run. Certified economic drivers are admitted only for
    declared eligible physical targets and are reported for MLflow logging.
    """
    registry = registry or load_feature_policy()
    kept: list[str] = []
    diagnostic: list[str] = []
    allowed_drivers: list[dict[str, str]] = []
    violations: list[str] = []

    for feature in feature_cols:
        rule = registry.rule_for(feature)
        policy = _canonical_policy(rule.policy if rule else registry.default_policy)
        if policy == "fundamental_physical":
            kept.append(feature)
            continue
        if policy == "diagnostic_only":
            diagnostic.append(feature)
            continue
        if policy == "excluded_market_signal":
            reason = f": {rule.reason}" if rule and rule.reason else ""
            violations.append(f"{feature} is excluded_market_signal{reason}")
            continue
        if policy == "certified_economic_driver":
            eligible = set(rule.eligible_targets if rule else ())
            if eligible and target not in eligible:
                violations.append(
                    f"{feature} is certified_economic_driver only for "
                    f"{sorted(eligible)}, not target={target!r}"
                )
                continue
            kept.append(feature)
            allowed_drivers.append({
                "feature": feature,
                "mechanism": rule.mechanism if rule else "",
                "reason": rule.reason if rule else "",
            })
            continue
        violations.append(f"{feature} has unknown policy {policy!r}")

    if violations:
        raise FeaturePolicyError("; ".join(violations))

    return kept, {
        "kept_count": len(kept),
        "dropped_diagnostic_features": diagnostic,
        "certified_economic_drivers": allowed_drivers,
        # Backward-compatible alias for existing training scripts and older
        # MLflow dashboards. New code should read certified_economic_drivers.
        "allowed_economic_drivers": allowed_drivers,
    }
