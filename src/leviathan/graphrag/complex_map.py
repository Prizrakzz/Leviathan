"""The complex map (reroute v2 -- RV-W0): curated cross-commodity relative-value pairs.

The cross-COMMODITY analogue of ``cascade_map.yaml``. One gitignored config
(``configs/graphrag/numbers/complex_map.yaml``) carries pair identity so lint,
census and the firing gate each read ONE place. A pair is one event landing on
TWO commodities with opposing balance-sheet legs, quantified on a stocks-to-use
RATIO, World basis, each leg on its own marketing year.

``load_complex_map()`` mirrors ``cascade.load_map``: lru_cached, and it DROPS any
row whose ``materiality_tier != material`` so non-material rows are inert at serve
time (the ``deferred: true`` discipline) -- a candidate pair cannot fire until it
is ratified `material`. ``iter_all_pairs()`` returns EVERY authored row (material
or not) for the config lint, which validates shape on rows the loader hides.

``resolve_bare_commodity(name)`` bridges the vocabulary mismatch that blocks the
whole feature (engine F2 / adversarial C2): ``InterCommodityEdge.driver_commodity``
targets in the causal YAMLs are BARE commodity names (``palm_oil``,
``soybean_oil``, ``wheat``) with no contract YAML, while pair legs are exchange
contract SLUGS (``malaysian_crude_palm_oil_cme``). The resolver maps a bare name
to its curated loaded slug (or an already-loaded slug to itself), returning None
when the name is ambiguous/unknown -- an honest decline, never a guess.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

import yaml

from leviathan.graphrag import extract as ex  # ex._CFG = configs/graphrag (registry convention)

# ── bare-commodity -> contract-slug resolver (engine F2 / adversarial C2) ─────────────────────────────
# Curated, NOT auto-derived: several bare names are ambiguous across loaded slugs (wheat -> 4 classes;
# soybean_oil -> cbot|dce; palm_oil -> mcpo|palm_olein_dce) and the v1 curation picks ONE per RV-W0
# (rapeseed routes at the OIL level, not the seed; wheat -> the SRW/CBOT leg; soy* -> the CBOT legs).
# These mirror PSD_SLUG_ALIAS (corn/soybeans) and extend it to the veg-oil/crush edge targets.
_BARE_TO_SLUG: dict[str, str] = {
    "palm_oil":     "malaysian_crude_palm_oil_cme",
    "soybean_oil":  "soybean_oil_cbot",
    "soybean_meal": "soybean_meal_cbot",
    "rapeseed_oil": "rapeseed_oil_zce",
    "soybeans":     "soybeans_cbot",
    "corn":         "corn_cbot",
    "wheat":        "soft_red_winter_wheat_cbot",
    # Trade-shorthand forms (2026-07-19): the detector hands over NATURAL-LANGUAGE spans, and the trade
    # says "palm"/"soyoil"/"canola" far more often than the curated canonical names -- the clean-window
    # positive pin failed partly because bare "palm" resolved None. Only UNAMBIGUOUS shorthands are
    # listed ("maize" is NOT: corn_cbot vs the SAFEX white/yellow maize contracts; "soy" is NOT:
    # beans/meal/oil). "rapeseed"/"canola" route at the OIL level per the RV-W0 curation note above.
    "palm":         "malaysian_crude_palm_oil_cme",
    "soyoil":       "soybean_oil_cbot",
    "soy_oil":      "soybean_oil_cbot",
    "soymeal":      "soybean_meal_cbot",
    "soy_meal":     "soybean_meal_cbot",
    "soybean":      "soybeans_cbot",
    "rapeseed":     "rapeseed_oil_zce",
    "rapeoil":      "rapeseed_oil_zce",
    "rape_oil":     "rapeseed_oil_zce",
    "canola":       "rapeseed_oil_zce",
    "canola_oil":   "rapeseed_oil_zce",
}


@functools.lru_cache(maxsize=1)
def _loaded_contract_ids() -> frozenset[str]:
    """The loaded contract slugs (for slug pass-through in the resolver). lru_cached; fail-closed to an
    empty set if the graph cannot load, so the resolver degrades to the curated table only."""
    try:
        from leviathan.graphrag.graph import CausalGraph
        return frozenset(CausalGraph.load().contracts.keys())
    except Exception:  # noqa: BLE001
        return frozenset()


def resolve_bare_commodity(name: str, loaded: frozenset[str] | set[str] | None = None) -> str | None:
    """Map a cross_links edge target (a BARE commodity name OR an already-loaded slug) to a loaded
    contract slug, or None when ambiguous/unknown.

    Order: the curated bare-name table WINS (it disambiguates names that map to several loaded slugs),
    then an exact loaded-slug pass-through, else None. `loaded` may be supplied (the lint passes
    graph.contracts to avoid re-loading); when omitted the loaded set is resolved lazily + cached.
    """
    if not name:
        return None
    # Normalize separators: the detector captures NATURAL-LANGUAGE spans ("soybean oil", "read-across
    # to palm oil"), while the curated table and the causal-YAML edge targets are underscore forms.
    # Without this fold every multi-word named-target ask resolves None and the gate declines -- the
    # feature would only ever fire on single-word names (verify-wave finding, 2026-07-18). Possessive
    # markers are stripped too ("palm's" -> "palm"): no commodity name contains an apostrophe, and
    # carried-state / YAML spans may arrive possessive even though the detector now terminates before
    # the apostrophe (defense in depth, 2026-07-19).
    n = str(name).strip().lower()
    n = re.sub(r"['’]s\b", "", n).replace("'", "").replace("’", "")
    n = re.sub(r"[\s\-]+", "_", n)
    if n in _BARE_TO_SLUG:
        return _BARE_TO_SLUG[n]
    ids = loaded if loaded is not None else _loaded_contract_ids()
    if n in ids:
        return n
    return None


# ── schema ────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ComplexPair:
    """One curated ordered cross-commodity pair. `pair` is the (sideA, sideB) slug tuple; `side_a`/
    `side_b` carry {contract, ref, country_rule}. `complex_name` is the yaml `complex:` key (renamed to
    avoid the Python builtin). Attributes match the reroute-v2 interface contract exactly."""
    id: str
    pair: tuple[str, str]
    complex_name: str
    shared_event: str
    side_a: dict
    side_b: dict
    direction: str
    focus_rule: str
    materiality_tier: str
    relation: str = ""
    notes: str = ""
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ComplexMap:
    """The loaded map: `.pairs` is the list of `material` ComplexPair rows (non-material dropped)."""
    pairs: list[ComplexPair]

    def row(self, pair_id: str) -> ComplexPair | None:
        """The pair by stable id, or None (the lookup analogue of cascade.map_row)."""
        for p in self.pairs:
            if p.id == pair_id:
                return p
        return None

    def by_pair(self, a: str, b: str) -> ComplexPair | None:
        """Order-INSENSITIVE lookup by the two slugs (gating F1): pairs are authored ordered, but
        route()'s hit-count sort can yield either order, so (a,b) and (b,a) resolve to the same row."""
        want = frozenset((a, b))
        for p in self.pairs:
            if frozenset(p.pair) == want:
                return p
        return None


# ── loader ───────────────────────────────────────────────────────────────────────────────────────
def _cfg_path():
    return ex._CFG / "numbers" / "complex_map.yaml"


def _parse_pair(row: dict) -> ComplexPair:
    """Parse one raw yaml row into a ComplexPair, coercing `pair` to a 2-tuple and mapping the
    `complex` key to `complex_name`. Shape errors surface here (bad `pair` length) as ValueError so a
    malformed config fails loudly rather than half-loading."""
    pr = list(row.get("pair") or [])
    if len(pr) != 2:
        raise ValueError(f"complex_map pair {row.get('id')!r}: `pair` must have exactly 2 slugs, got {pr!r}")
    return ComplexPair(
        id=row.get("id") or "",
        pair=(pr[0], pr[1]),
        complex_name=row.get("complex") or "",
        shared_event=row.get("shared_event") or "",
        side_a=dict(row.get("sideA") or {}),
        side_b=dict(row.get("sideB") or {}),
        direction=row.get("direction") or "",
        focus_rule=row.get("focus_rule") or "",
        materiality_tier=row.get("materiality_tier") or "",
        relation=row.get("relation") or "",
        notes=row.get("notes") or "",
        provenance=dict(row.get("provenance") or {}),
    )


def iter_all_pairs() -> list[ComplexPair]:
    """EVERY authored pair (material or not) -- the config lint validates shape on rows load_complex_map()
    would drop. Not cached (lint calls it once per build); the loader below is the cached hot path."""
    p = _cfg_path()
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return [_parse_pair(r) for r in ((doc or {}).get("pairs") or [])]


@functools.lru_cache(maxsize=1)
def load_complex_map() -> ComplexMap:
    """{pairs: [ComplexPair, ...]} with ONLY `material` rows (the inert-by-default `deferred:true`
    discipline: a non-`material` row never loads, so a candidate pair cannot fire until ratified).
    lru_cached, mirroring cascade.load_map."""
    return ComplexMap([p for p in iter_all_pairs() if p.materiality_tier == "material"])


def complex_row(pair_id: str) -> ComplexPair | None:
    """The `material` pair by id, or None (module-level convenience over load_complex_map().row)."""
    return load_complex_map().row(pair_id)
