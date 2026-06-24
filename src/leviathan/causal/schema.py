"""Causal ontology — the curated per-contract causal DAG (GRAPHRAG_PLAN §10 Phase 1).

The **brain** of the v2 system: for each futures contract, a hand-curated graph of
`target_metric ← driver{sign, mechanism, lag, silver_ref, parents}` + inter-commodity edges + a
**convergence** (fan-in / confluence) layer. Authored from domain knowledge + the harvested vocab +
web research — **not** extracted from documents. Drivers link to silver / `gold.feature_spine` by
**name** (`silver_ref` + `silver_status`), decoupled from whether that feature is built yet.

SIGN CONVENTION: `sign` is the driver's effect on the contract's `target_metric` (default `price`).
  e.g. coffee (target=price): `brazil_frost` sign=`+` (frost → price up). A driver may override its own
  `target_metric` (e.g. a yield driver). Convergence aggregates *aligned, same-sign* drivers into a signal.

The models encode STRUCTURE; the open node/edge vocabulary stays in config
(`configs/graphrag/{entity_vocabulary,commodity_hierarchy}.yaml`), validated softly by `validate.py`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.1.0"

Sign = Literal["+", "-", "0"]
SilverStatus = Literal["available", "planned", "none"]
Confidence = Literal["high", "medium", "low"]


class _Base(BaseModel):
    """Reject unknown fields — a typo'd key is a bug, not a silent drop."""
    model_config = {"extra": "forbid"}


class Driver(_Base):
    id: str                              # snake_case, unique within the contract (e.g. "brazil_frost")
    type: str                            # vocab node type: hazard|climate_driver|policy_event|instrument|macro|commodity|...
    sign: Sign                           # effect on the target_metric (+ up / - down / 0 ambiguous)
    mechanism: str                       # one-sentence causal explanation
    lag: str = ""                        # e.g. "0-2 quarters"; "" = contemporaneous/unspecified
    region: Optional[str] = None         # geography anchor (vocab region / country_origin)
    edge_type: str = "causes"            # curated edge type from the vocab taxonomy
    target_metric: Optional[str] = None  # override the contract default (e.g. a yield driver)
    silver_ref: Optional[str] = None     # the feature/metric NAME that measures this driver
    silver_status: SilverStatus = "none"
    parents: list[str] = Field(default_factory=list)   # driver ids that drive THIS driver (fan-in / multi-hop)
    evidence_query: str = ""             # query string for the evidence layer
    confidence: Confidence = "medium"

    @model_validator(mode="after")
    def _no_self_parent(self):
        if self.id in self.parents:
            raise ValueError(f"driver {self.id!r} lists itself as a parent")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError(f"driver {self.id!r} has duplicate parents")
        return self


class InterCommodityEdge(_Base):
    driver_commodity: str                # another node (e.g. "robusta_coffee")
    relation: str                        # substitutes_for|competes_with|crushed_into|feedstock_for|...
    sign: Sign
    mechanism: str = ""
    lag: str = ""


class Interaction(_Base):
    """A non-additive amplifier: when these drivers co-occur the effect is stronger than their sum."""
    when: list[str]                      # driver ids that must co-occur
    effect: Literal["amplifies", "dampens"] = "amplifies"
    note: str = ""


class ConvergenceSignal(_Base):
    """The fan-in / confluence layer: many aligned drivers → one signal."""
    name: str                            # e.g. "bullish_squeeze"
    direction: Literal["+", "-"]
    requires_any_n_of: int = Field(ge=1) # confluence threshold: N of `drivers` active + aligned
    drivers: list[str]                   # driver ids whose alignment constitutes the signal
    interactions: list[Interaction] = Field(default_factory=list)
    note: str = ""

    @model_validator(mode="after")
    def _n_within_drivers(self):
        if self.requires_any_n_of > len(self.drivers):
            raise ValueError(f"signal {self.name!r}: requires_any_n_of "
                             f"{self.requires_any_n_of} > {len(self.drivers)} drivers")
        return self


class CausalContract(_Base):
    schema_version: str = SCHEMA_VERSION
    contract: str                        # the node id (e.g. "arabica_coffee")
    aliases: list[str] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=lambda: ["price"])
    drivers: list[Driver] = Field(default_factory=list)
    inter_commodity: list[InterCommodityEdge] = Field(default_factory=list)
    convergence: list[ConvergenceSignal] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)   # {authored_by, date, sources: [...]}

    @model_validator(mode="after")
    def _refs_resolve(self):
        ids = [d.id for d in self.drivers]
        idset = set(ids)
        if len(idset) != len(ids):
            dup = [i for i in idset if ids.count(i) > 1]
            raise ValueError(f"duplicate driver ids: {dup}")
        for d in self.drivers:
            for p in d.parents:
                if p not in idset:
                    raise ValueError(f"driver {d.id!r} parent {p!r} is not a driver id")
        for s in self.convergence:
            for did in s.drivers:
                if did not in idset:
                    raise ValueError(f"signal {s.name!r} references unknown driver {did!r}")
            for inter in s.interactions:
                for did in inter.when:
                    if did not in idset:
                        raise ValueError(f"signal {s.name!r} interaction references unknown driver {did!r}")
        return self

    # convenience views
    def driver_ids(self) -> set[str]:
        return {d.id for d in self.drivers}

    def fan_in_drivers(self) -> list[Driver]:
        """Drivers that have parents — the multi-hop / convergence depth."""
        return [d for d in self.drivers if d.parents]


def load(path) -> CausalContract:
    return CausalContract.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def dump(contract: CausalContract, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = contract.model_dump(exclude_none=True, mode="json")
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
