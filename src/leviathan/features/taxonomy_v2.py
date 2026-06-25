"""Feature taxonomy helpers for the point-in-time gold_v2 layer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_ROOT = Path(__file__).resolve().parents[3] / "configs" / "features"
_DEFAULT_TAXONOMY_PATH = _CONFIG_ROOT / "feature_taxonomy_v2.yaml"
_DEFAULT_GROUPS_PATH = _CONFIG_ROOT / "feature_groups_v2.yaml"

VALID_SEMANTIC_SCOPES = {"global", "group", "physical_commodity", "origin", "contract"}
VALID_POLICIES = {
    "fundamental_physical",
    "certified_economic_driver",
    "diagnostic_only",
    "excluded_market_signal",
}
LEGACY_POLICY_ALIASES = {"allowed_economic_driver": "certified_economic_driver"}


class FeatureTaxonomyError(ValueError):
    """The gold_v2 feature taxonomy configuration is invalid."""


@dataclass(frozen=True)
class FeatureTaxonomyRule:
    pattern: str
    semantic_scope: str
    mechanism: str
    policy: str
    sources: tuple[str, ...]
    groups: tuple[str, ...]

    def matches(self, feature: str) -> bool:
        return feature == self.pattern or feature.startswith(self.pattern)


@dataclass(frozen=True)
class FeatureClassification:
    feature: str
    semantic_scope: str
    mechanism: str
    policy: str
    sources: tuple[str, ...]
    groups: tuple[str, ...]


@dataclass(frozen=True)
class FeatureGroupRegistry:
    groups: dict[str, tuple[str, ...]]

    def groups_for_commodity(self, commodity: str) -> tuple[str, ...]:
        return tuple(
            group
            for group, commodities in sorted(self.groups.items())
            if commodity in commodities
        )

    def groups_for_commodities(self, commodities: set[str]) -> tuple[str, ...]:
        found: set[str] = set()
        for commodity in commodities:
            found.update(self.groups_for_commodity(commodity))
        return tuple(sorted(found))


@dataclass(frozen=True)
class FeatureTaxonomyRegistry:
    default: FeatureTaxonomyRule
    rules: tuple[FeatureTaxonomyRule, ...]
    groups: FeatureGroupRegistry

    def rule_for(self, feature: str) -> FeatureTaxonomyRule:
        matches = [rule for rule in self.rules if rule.matches(feature)]
        if not matches:
            return self.default
        return max(matches, key=lambda rule: len(rule.pattern))

    def classify_feature(self, feature: str) -> FeatureClassification:
        rule = self.rule_for(feature)
        return FeatureClassification(
            feature=feature,
            semantic_scope=rule.semantic_scope,
            mechanism=rule.mechanism,
            policy=rule.policy,
            sources=rule.sources,
            groups=rule.groups,
        )


def _canonical_policy(value: str) -> str:
    return LEGACY_POLICY_ALIASES.get(value, value)


def _as_str_tuple(value: Any, *, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise FeatureTaxonomyError(f"{context} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_rule(raw: dict[str, Any], *, context: str, pattern_required: bool) -> FeatureTaxonomyRule:
    pattern = str(raw.get("pattern", "")).strip()
    if pattern_required and not pattern:
        raise FeatureTaxonomyError(f"{context} missing pattern")
    semantic_scope = str(raw.get("semantic_scope", "")).strip()
    policy = _canonical_policy(str(raw.get("policy", "")).strip())
    mechanism = str(raw.get("mechanism", "")).strip()
    if semantic_scope not in VALID_SEMANTIC_SCOPES:
        raise FeatureTaxonomyError(f"{context} invalid semantic_scope {semantic_scope!r}")
    if policy not in VALID_POLICIES:
        raise FeatureTaxonomyError(f"{context} invalid policy {policy!r}")
    if not mechanism:
        raise FeatureTaxonomyError(f"{context} missing mechanism")
    return FeatureTaxonomyRule(
        pattern=pattern,
        semantic_scope=semantic_scope,
        mechanism=mechanism,
        policy=policy,
        sources=_as_str_tuple(raw.get("sources", []), context=f"{context}.sources"),
        groups=_as_str_tuple(raw.get("groups", []), context=f"{context}.groups"),
    )


def load_feature_groups_v2(path: str | Path | None = None) -> FeatureGroupRegistry:
    raw = yaml.safe_load(Path(path or _DEFAULT_GROUPS_PATH).read_text(encoding="utf-8")) or {}
    groups_raw = raw.get("groups") or {}
    if not isinstance(groups_raw, dict) or not groups_raw:
        raise FeatureTaxonomyError("feature_groups_v2 must define non-empty groups")
    groups: dict[str, tuple[str, ...]] = {}
    for name, item in groups_raw.items():
        commodities = _as_str_tuple(
            (item or {}).get("commodities", []),
            context=f"groups.{name}.commodities",
        )
        if not commodities:
            raise FeatureTaxonomyError(f"groups.{name} has no commodities")
        groups[str(name)] = commodities
    return FeatureGroupRegistry(groups=groups)


def load_feature_taxonomy_v2(
    taxonomy_path: str | Path | None = None,
    groups_path: str | Path | None = None,
) -> FeatureTaxonomyRegistry:
    raw = yaml.safe_load(Path(taxonomy_path or _DEFAULT_TAXONOMY_PATH).read_text(encoding="utf-8")) or {}
    groups = load_feature_groups_v2(groups_path)
    default = _parse_rule(raw.get("default") or {}, context="default", pattern_required=False)
    rules = tuple(
        _parse_rule(item, context=f"rules[{index}]", pattern_required=True)
        for index, item in enumerate(raw.get("rules", []))
    )
    for rule in rules:
        unknown_groups = set(rule.groups) - set(groups.groups)
        if unknown_groups:
            raise FeatureTaxonomyError(
                f"rule {rule.pattern!r} references unknown groups {sorted(unknown_groups)}"
            )
    return FeatureTaxonomyRegistry(default=default, rules=rules, groups=groups)


def classify_feature_v2(feature: str) -> FeatureClassification:
    return load_feature_taxonomy_v2().classify_feature(feature)
