"""Canonical physical/product entity taxonomy for ML target semantics."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import yaml

from leviathan.common.types import CommodityName

_DEFAULT_DIR = Path(__file__).resolve().parents[3] / "configs" / "entities"
_COMMODITY_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "commodities"
_FAOSTAT_ITEM_MAP = Path(__file__).resolve().parents[3] / "configs" / "sources" / "faostat_item_map.yaml"

_VALID_ENTITY_TYPES = {"physical_commodity", "processed_product"}
_VALID_LABEL_POLICIES = {"direct", "proxy", "blocked"}


class TaxonomyError(ValueError):
    """The entity taxonomy is internally inconsistent or rejects a target."""


@dataclass(frozen=True)
class ContractMapping:
    contract_slug: str
    entity_type: str
    entity_id: str
    physical_commodity: str
    origin: str
    exchange: str
    crop_class: str
    balance_sheet_family: str


@dataclass(frozen=True)
class TargetSpec:
    name: str
    target_kind: str
    allowed_entity_types: tuple[str, ...]
    unit_family: str
    primary_label_policy: str


@dataclass(frozen=True)
class ProxyRule:
    rule_id: str
    policy: str
    contract_slugs: tuple[str, ...]
    target_names: tuple[str, ...]
    source_datasets: tuple[str, ...]
    reason: str

    def matches(self, contract_slug: str, target_name: str, source_dataset: str) -> bool:
        return (
            contract_slug in self.contract_slugs
            and target_name in self.target_names
            and ("*" in self.source_datasets or source_dataset in self.source_datasets)
        )


@dataclass(frozen=True)
class SourcePrecedenceRule:
    rule_id: str
    match: dict[str, Any]
    sources: tuple[str, ...]

    def matches(
        self,
        mapping: ContractMapping,
        target_name: str,
        *,
        origin: str | None = None,
    ) -> bool:
        effective_origin = origin or mapping.origin
        target_names = tuple(self.match.get("target_names", ()))
        if target_names and target_name not in target_names and "*" not in target_names:
            return False
        contract_slugs = tuple(self.match.get("contract_slugs", ()))
        if contract_slugs and mapping.contract_slug not in contract_slugs:
            return False
        entity_ids = tuple(self.match.get("entity_ids", ()))
        if entity_ids and mapping.entity_id not in entity_ids:
            return False
        physical = tuple(self.match.get("physical_commodities", ()))
        if physical and mapping.physical_commodity not in physical:
            return False
        entity_type = self.match.get("entity_type")
        if entity_type and mapping.entity_type != entity_type:
            return False
        rule_origin = self.match.get("origin")
        return not rule_origin or str(rule_origin) == effective_origin

    def specificity(self) -> int:
        score = 0
        for field in ("contract_slugs", "entity_ids", "physical_commodities"):
            if self.match.get(field):
                score += 4
        if self.match.get("origin"):
            score += 3
        if self.match.get("entity_type"):
            score += 2
        if self.match.get("target_names"):
            score += 1
        return score


@dataclass(frozen=True)
class LabelPolicyResult:
    contract_slug: str
    target_name: str
    source_dataset: str
    policy: str
    reason: str
    rule_id: str | None = None

    @property
    def is_direct(self) -> bool:
        return self.policy == "direct"


@dataclass(frozen=True)
class LegacyLabelIssue:
    contract_slug: str
    target_name: str
    source_dataset: str
    policy: str
    reason: str


@dataclass(frozen=True)
class DuplicateLabelGroup:
    source_dataset: str
    label_id: str
    contract_slugs: tuple[str, ...]


@dataclass(frozen=True)
class EntityTaxonomy:
    physical_commodities: dict[str, dict[str, Any]]
    processed_products: dict[str, dict[str, Any]]
    contracts: dict[str, ContractMapping]
    targets: dict[str, TargetSpec]
    proxy_rules: tuple[ProxyRule, ...]
    source_precedence_rules: tuple[SourcePrecedenceRule, ...]

    def validate(self) -> None:
        errors: list[str] = []
        expected_contracts = set(get_args(CommodityName))
        mapped_contracts = set(self.contracts)
        missing = expected_contracts - mapped_contracts
        extra = mapped_contracts - expected_contracts
        if missing:
            errors.append(f"missing contract mappings: {sorted(missing)}")
        if extra:
            errors.append(f"unknown contract mappings: {sorted(extra)}")

        for slug, mapping in self.contracts.items():
            if mapping.entity_type not in _VALID_ENTITY_TYPES:
                errors.append(f"{slug}: invalid entity_type {mapping.entity_type!r}")
            if mapping.entity_type == "physical_commodity":
                if mapping.entity_id not in self.physical_commodities:
                    errors.append(f"{slug}: physical entity {mapping.entity_id!r} is undefined")
            if mapping.entity_type == "processed_product":
                product = self.processed_products.get(mapping.entity_id)
                if product is None:
                    errors.append(f"{slug}: processed product {mapping.entity_id!r} is undefined")
                elif product.get("parent_physical_commodity") != mapping.physical_commodity:
                    errors.append(
                        f"{slug}: parent physical commodity mismatch for {mapping.entity_id!r}"
                    )
            if mapping.physical_commodity not in self.physical_commodities:
                errors.append(
                    f"{slug}: physical_commodity {mapping.physical_commodity!r} is undefined"
                )

        for target in self.targets.values():
            unknown_types = set(target.allowed_entity_types) - _VALID_ENTITY_TYPES
            if unknown_types:
                errors.append(f"{target.name}: unknown entity types {sorted(unknown_types)}")

        for rule in self.proxy_rules:
            if rule.policy not in {"proxy", "blocked"}:
                errors.append(f"{rule.rule_id}: invalid proxy policy {rule.policy!r}")
            errors.extend(
                f"{rule.rule_id}: unknown contract {slug!r}"
                for slug in rule.contract_slugs
                if slug not in self.contracts
            )
            errors.extend(
                f"{rule.rule_id}: unknown target {target!r}"
                for target in rule.target_names
                if target not in self.targets
            )

        known_entities = set(self.physical_commodities) | set(self.processed_products)
        for rule in self.source_precedence_rules:
            for slug in rule.match.get("contract_slugs", ()):
                if slug not in self.contracts:
                    errors.append(f"{rule.rule_id}: unknown contract {slug!r}")
            for entity_id in rule.match.get("entity_ids", ()):
                if entity_id not in known_entities:
                    errors.append(f"{rule.rule_id}: unknown entity_id {entity_id!r}")
            for physical in rule.match.get("physical_commodities", ()):
                if physical not in self.physical_commodities:
                    errors.append(f"{rule.rule_id}: unknown physical commodity {physical!r}")
            for target in rule.match.get("target_names", ()):
                if target != "*" and target not in self.targets:
                    errors.append(f"{rule.rule_id}: unknown target {target!r}")

        if errors:
            raise TaxonomyError("; ".join(errors))

    def resolve_contract(self, contract_slug: str) -> ContractMapping:
        try:
            return self.contracts[contract_slug]
        except KeyError as exc:
            raise TaxonomyError(f"unknown contract_slug {contract_slug!r}") from exc

    def target_spec(self, target_name: str) -> TargetSpec:
        try:
            return self.targets[target_name]
        except KeyError as exc:
            raise TaxonomyError(f"unknown target {target_name!r}") from exc

    def label_policy(
        self,
        contract_slug: str,
        target_name: str,
        source_dataset: str,
    ) -> LabelPolicyResult:
        mapping = self.resolve_contract(contract_slug)
        target = self.target_spec(target_name)
        if mapping.entity_type not in target.allowed_entity_types:
            return LabelPolicyResult(
                contract_slug=contract_slug,
                target_name=target_name,
                source_dataset=source_dataset,
                policy="blocked",
                reason=(
                    f"target {target_name!r} allows {target.allowed_entity_types}, "
                    f"not entity_type={mapping.entity_type!r}"
                ),
            )
        for rule in self.proxy_rules:
            if rule.matches(contract_slug, target_name, source_dataset):
                return LabelPolicyResult(
                    contract_slug=contract_slug,
                    target_name=target_name,
                    source_dataset=source_dataset,
                    policy=rule.policy,
                    reason=rule.reason,
                    rule_id=rule.rule_id,
                )
        return LabelPolicyResult(
            contract_slug=contract_slug,
            target_name=target_name,
            source_dataset=source_dataset,
            policy="direct",
            reason="target is allowed for this entity and source",
        )

    def require_direct_label(
        self,
        contract_slug: str,
        target_name: str,
        source_dataset: str,
    ) -> LabelPolicyResult:
        result = self.label_policy(contract_slug, target_name, source_dataset)
        if not result.is_direct:
            raise TaxonomyError(
                f"{contract_slug}/{target_name} from {source_dataset} is "
                f"{result.policy}: {result.reason}"
            )
        return result

    def authoritative_sources(
        self,
        contract_slug: str,
        target_name: str,
        *,
        origin: str | None = None,
    ) -> tuple[str, ...]:
        mapping = self.resolve_contract(contract_slug)
        self.target_spec(target_name)
        matches = [
            rule
            for rule in self.source_precedence_rules
            if rule.matches(mapping, target_name, origin=origin)
        ]
        if not matches:
            raise TaxonomyError(
                f"no source precedence rule for {contract_slug}/{target_name}"
            )
        selected = max(matches, key=lambda rule: rule.specificity())
        return selected.sources

    def duplicate_label_groups(
        self,
        path: str | Path | None = None,
    ) -> tuple[DuplicateLabelGroup, ...]:
        raw = yaml.safe_load(Path(path or _FAOSTAT_ITEM_MAP).read_text(encoding="utf-8")) or {}
        groups: dict[str, list[str]] = {}
        for slug, item in raw.items():
            if slug in self.contracts:
                groups.setdefault(str(item), []).append(str(slug))
        return tuple(
            DuplicateLabelGroup(
                source_dataset="silver_production",
                label_id=item,
                contract_slugs=tuple(sorted(slugs)),
            )
            for item, slugs in sorted(groups.items())
            if len(slugs) > 1
        )

    def audit_legacy_commodity_targets(
        self,
        commodities_dir: str | Path | None = None,
        *,
        source_dataset: str = "silver_production",
    ) -> tuple[LegacyLabelIssue, ...]:
        issues: list[LegacyLabelIssue] = []
        for path in sorted(Path(commodities_dir or _COMMODITY_CONFIG_DIR).glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            slug = str(raw.get("commodity", path.stem))
            if slug not in self.contracts:
                continue
            for target_name in raw.get("label_targets", []):
                result = self.label_policy(slug, str(target_name), source_dataset)
                if not result.is_direct:
                    issues.append(LegacyLabelIssue(
                        contract_slug=slug,
                        target_name=str(target_name),
                        source_dataset=source_dataset,
                        policy=result.policy,
                        reason=result.reason,
                    ))
        return tuple(issues)


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_contracts(path: Path) -> dict[str, ContractMapping]:
    raw = _load_yaml(path).get("contracts", {})
    return {
        slug: ContractMapping(
            contract_slug=slug,
            entity_type=str(item["entity_type"]),
            entity_id=str(item["entity_id"]),
            physical_commodity=str(item["physical_commodity"]),
            origin=str(item["origin"]),
            exchange=str(item["exchange"]),
            crop_class=str(item["crop_class"]),
            balance_sheet_family=str(item["balance_sheet_family"]),
        )
        for slug, item in raw.items()
    }


def _load_targets(path: Path) -> dict[str, TargetSpec]:
    raw = _load_yaml(path).get("targets", {})
    return {
        name: TargetSpec(
            name=name,
            target_kind=str(item["target_kind"]),
            allowed_entity_types=tuple(str(value) for value in item["allowed_entity_types"]),
            unit_family=str(item["unit_family"]),
            primary_label_policy=str(item["primary_label_policy"]),
        )
        for name, item in raw.items()
    }


def _load_proxy_rules(path: Path) -> tuple[ProxyRule, ...]:
    raw = _load_yaml(path).get("rules", [])
    return tuple(
        ProxyRule(
            rule_id=str(item["id"]),
            policy=str(item["policy"]),
            contract_slugs=tuple(str(value) for value in item["contract_slugs"]),
            target_names=tuple(str(value) for value in item["target_names"]),
            source_datasets=tuple(str(value) for value in item["source_datasets"]),
            reason=str(item["reason"]),
        )
        for item in raw
    )


def _load_source_rules(path: Path) -> tuple[SourcePrecedenceRule, ...]:
    raw = _load_yaml(path).get("rules", [])
    return tuple(
        SourcePrecedenceRule(
            rule_id=str(item["id"]),
            match=dict(item.get("match", {})),
            sources=tuple(str(value) for value in item["sources"]),
        )
        for item in raw
    )


def load_entity_taxonomy(path: str | Path | None = None) -> EntityTaxonomy:
    root = Path(path or _DEFAULT_DIR)
    taxonomy = EntityTaxonomy(
        physical_commodities=_load_yaml(root / "physical_commodities.yaml").get(
            "physical_commodities", {}
        ),
        processed_products=_load_yaml(root / "processed_products.yaml").get(
            "processed_products", {}
        ),
        contracts=_load_contracts(root / "contract_mappings.yaml"),
        targets=_load_targets(root / "target_dictionary.yaml"),
        proxy_rules=_load_proxy_rules(root / "proxy_label_rules.yaml"),
        source_precedence_rules=_load_source_rules(root / "source_precedence.yaml"),
    )
    taxonomy.validate()
    return taxonomy
