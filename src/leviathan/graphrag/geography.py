"""Geography ROUTING index (Phase 5.8) — country -> {contracts, drivers} for query routing.

Geography is routing metadata, NOT a causal node: a country has no mechanism, so the causal DAGs stay
commodity-anchored (design decision 2026-07-06). This module lets the orchestrator answer geography-led
questions that name no tradeable contract ("news on India", "Black Sea wheat") by resolving a country to
the contracts + drivers it materially moves — the ~13 majors are curated in ``configs/graphrag/
geography.yaml`` and every country's HOME contracts are additionally derived from
``commodity_hierarchy.yaml`` ``origin`` (so a curation omission can never drop them).

Public code; reads the git-ignored ``configs/graphrag/`` IP at runtime (same pattern as ``hierarchy`` /
``config_check``). Entirely deterministic + hermetic — no network, no model.

    python -m leviathan.graphrag.geography      # prints check_geography result
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import yaml

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"


@functools.lru_cache(maxsize=1)
def _geo() -> dict:
    return yaml.safe_load((_CFG / "geography.yaml").read_text(encoding="utf-8")) or {}


@functools.lru_cache(maxsize=1)
def _origin_index() -> dict[str, list[str]]:
    """origin_token -> [contract slugs] from commodity_hierarchy.yaml (the auto-derived HOME contracts)."""
    from leviathan.graphrag import hierarchy as hy
    out: dict[str, list[str]] = {}
    for slug, spec in (hy._hierarchy().get("contracts", {})).items():
        origin = spec.get("origin")
        if origin and origin != "global":
            out.setdefault(origin, []).append(slug)
    return out


def _countries() -> dict[str, dict]:
    return _geo().get("countries", {})


@functools.lru_cache(maxsize=1)
def _matcher():
    """Accent/case-insensitive, WORD-BOUNDARY matcher over every country's aliases -> the alias->country
    map. Word-boundary (via harvest.build_matcher) means 'india' never matches inside 'indiana'."""
    from leviathan.graphrag import harvest as hv
    alias_to_id: dict[str, str] = {}
    forms: list[str] = []
    for cid, spec in _countries().items():
        for a in (spec.get("aliases") or []):
            alias_to_id[a.lower()] = cid
            forms.append(a)
    return hv.build_matcher(forms), alias_to_id


def all_country_ids() -> list[str]:
    return list(_countries().keys())


def resolve_country(text: str) -> str | None:
    """The country a query names, or None. First lexical hit wins (queries name one country in practice)."""
    if not text:
        return None
    matcher, alias_to_id = _matcher()
    hits = matcher.findall(text) if matcher else []
    for h in hits:
        cid = alias_to_id.get(str(h).lower())
        if cid:
            return cid
    return None


def contracts_for(country: str, graph=None) -> list[str]:
    """The tracked contracts a country moves = curated ∪ origin-derived HOME contracts, order-preserving,
    de-duplicated. Filtered to real ``graph.contracts`` when a graph is given (routing must never emit an
    id the graph doesn't have)."""
    spec = _countries().get(country) or {}
    out: list[str] = list(spec.get("contracts") or [])
    for slug in _origin_index().get(spec.get("origin_token", ""), []):
        if slug not in out:
            out.append(slug)
    if graph is not None:
        valid = set(getattr(graph, "contracts", {}) or {})
        out = [c for c in out if c in valid]
    return out


def drivers_for(country: str) -> list[str]:
    return list((_countries().get(country) or {}).get("drivers") or [])


def check_geography() -> list[str]:
    """Every curated contract is a real graph contract (causal DAG stem); every driver exists in
    driver_slices.yaml; every region is an entity_vocabulary region; every origin_token is a hierarchy
    origin. Offline — reads the causal dir + configs, no graph load."""
    errs: list[str] = []
    contracts = {p.stem for p in (_CFG / "causal").glob("*.yaml")}
    ds = yaml.safe_load((_CFG / "driver_slices.yaml").read_text(encoding="utf-8")) or {}
    drivers = set((ds.get("drivers") or {}).keys()) | set((ds.get("dag_alias") or {}).keys())
    vocab_nodes = (yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8")) or {}).get("nodes", {})
    regions = set(vocab_nodes.get("region") or [])
    origins = set(vocab_nodes.get("country_origin") or [])   # the 44 canonical country tokens (a country
    # with no HOME contract — India, Russia, Ukraine — is still a valid origin_token; origin-derive yields [])

    if not contracts:
        errs.append("no causal DAG stems found — cannot validate geography contracts")
    for cid, spec in _countries().items():
        if not (spec.get("aliases") or []):
            errs.append(f"country {cid}: no aliases (undetectable)")
        for c in (spec.get("contracts") or []):
            if c not in contracts:
                errs.append(f"country {cid}: contract {c!r} is not a real graph contract")
        for d in (spec.get("drivers") or []):
            if d not in drivers:
                errs.append(f"country {cid}: driver {d!r} not in driver_slices.yaml")
        for r in (spec.get("regions") or []):
            if r not in regions:
                errs.append(f"country {cid}: region {r!r} not an entity_vocabulary region")
        ot = spec.get("origin_token")
        if ot and ot not in origins:
            errs.append(f"country {cid}: origin_token {ot!r} not a hierarchy origin")
    return errs


# ── THE COUNTRY-AXIS NAMESPACE DIFF (B1 recon R4, ratified 2026-08-21) ───────────────────────────────────
# SIX ROSTERS SPELL A COUNTRY IN THIS ESTATE AND NO LINT COMPARED ANY ADJACENT PAIR:
#   esr_destinations.yaml `codes`         the FAS destination code table (data-derived; the reference)
#   numbers.agent._ESR_DESTINATIONS       the buyer-directional scope guard's detection roster
#   geo_lexicon._COUNTRIES                the binding verifier's ONE geography vocabulary (lives in src/)
#   entity_vocabulary.nodes.country_origin the CANONICAL country namespace the graph is keyed on
#   cascade_map.region_map.resolve[].country the cascade's country labels
#   geography.yaml `countries`            this module's router
# Five of the six live in gitignored configs; geo_lexicon deliberately lives in src/ so a worktree image
# cannot import it empty. The B1 recon's R-7 states the consequence exactly: "adding destinations to some and
# not others makes the drift worse, not better", which is why R4 was ratified as a PRECONDITION of the
# router/vocabulary extensions rather than as a follow-on.
#
# THE MEASURED HEADLINE THIS EXISTS TO STOP DRIFTING: 113 destinations carry measured US-export volume and
# 3 resolve through the router -- 27.4% of actual traded tonnage. The recon's corrected sentence, which this
# lint's output must not be read as contradicting: the buyer side EXISTS in the numbers lane (93.5% of
# tonnage) and in the vocabulary (84.2%); it is absent from evidence ADDRESSING and from the router.
#
# ADVISORY, CONFIG-ONLY, TONNAGE-OPTIONAL. Roster membership is a config fact and is checked unconditionally;
# the tonnage WEIGHTING that makes "27.4%" meaningful needs an ESR aggregation that only Athena can produce,
# so it is an OPTIONAL argument and never a network call. A lint that needs a warehouse to run is a lint that
# gets switched off.
_COUNTRY_AXIS_SYNONYMS = {                                   # measured, not guessed -- see each note
    # esr_destinations code 1 declares BOTH surfaces for the same bloc ("European Union", aliases incl "eu"),
    # so the canonical token `EU` and the lexicon/cascade display "European Union" are one entity, not drift.
    "eu": "european union",
}
_COUNTRY_AXIS_BENIGN = frozenset({
    # THE REPORTER, not a destination. numbers/agent.py states it verbatim: "The United States is the
    # REPORTER in ESR and is deliberately absent from the destination vocabulary." Its absence from the FAS
    # destination code table is the schema being right, and flagging it forever would train the reader to
    # skim this lint.
    "united states",
})


def _ca_norm(s: object) -> str:
    """One normalization for all six rosters: lowercase, drop everything but [a-z ] (so "Cote d'Ivoire" and
    "South Africa, Republic Of" fold toward comparable surfaces), collapse whitespace, then apply the
    declared synonym fold. Underscored ids are spaced by the caller."""
    import re
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", str(s or "").lower())).strip()
    return _COUNTRY_AXIS_SYNONYMS.get(t, t)


def country_axis_rosters() -> dict[str, set[str]]:
    """The six rosters, normalized, each as a set of surface forms. A roster that cannot be read (no private
    configs, or the numbers agent's dependency tree unavailable) comes back EMPTY rather than raising -- this
    is a lint, and a lint that cannot load its input must report nothing, never a false gap."""
    out: dict[str, set[str]] = {k: set() for k in
                               ("esr_destinations", "agent", "geo_lexicon", "country_origin",
                                "region_map", "geography")}
    try:
        codes = (yaml.safe_load((_CFG / "numbers" / "esr_destinations.yaml").read_text(encoding="utf-8"))
                 or {}).get("codes") or {}
        for m in codes.values():
            out["esr_destinations"].add(_ca_norm((m or {}).get("name")))
            for a in ((m or {}).get("aliases") or []):
                out["esr_destinations"].add(_ca_norm(a))
    except Exception:                                          # noqa: BLE001
        pass
    try:
        from leviathan.graphrag.numbers import agent as _ag
        out["agent"] = {_ca_norm(str(disp).replace("the ", "")) for disp, _n, _d in _ag._ESR_DESTINATIONS}
    except Exception:                                          # noqa: BLE001 -- serving deps absent: vacuous
        pass
    try:
        from leviathan.graphrag import geo_lexicon as _gl
        out["geo_lexicon"] = {_ca_norm(spec.get("display")) for spec in _gl._COUNTRIES.values()}
    except Exception:                                          # noqa: BLE001
        pass
    try:
        nodes = (yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
                 or {}).get("nodes") or {}
        out["country_origin"] = {_ca_norm(str(c).replace("_", " ")) for c in (nodes.get("country_origin") or [])}
    except Exception:                                          # noqa: BLE001
        pass
    try:
        cm = yaml.safe_load((_CFG / "numbers" / "cascade_map.yaml").read_text(encoding="utf-8")) or {}
        resolve = ((cm.get("region_map") or {}).get("resolve") or {})
        out["region_map"] = {_ca_norm((v or {}).get("country")) for v in resolve.values()}
    except Exception:                                          # noqa: BLE001
        pass
    out["geography"] = {_ca_norm(str(k).replace("_", " ")) for k in _countries()}
    for k in out:
        out[k] = {s for s in out[k] if s}
    return out


def country_axis_warnings(tonnage: dict | None = None) -> list[str]:
    """ADVISORY (non-fatal) six-roster country-axis namespace diff -- B1 recon R4, ratified 2026-08-21 as a
    PRECONDITION of the destination router/vocabulary extensions rather than a follow-on to them.

    FIVE LEGS, each an ADJACENT pair in the direction the data actually flows. Adjacency is the whole design:
    a 211-vs-13 raw diff is noise, and a lint whose output nobody reads is worse than no lint.

      (1) agent -> esr_destinations   a buyer the ESR scope guard DETECTS but the FAS code table cannot name.
                                      That combination stamps a national total as if it answered a
                                      destination-scoped ask, which is the exact failure agent.py's guard
                                      exists to prevent.
      (2) geo_lexicon -> esr_destinations  the verifier spells a country the destination table does not.
      (3) country_origin -> esr_destinations  the CANONICAL namespace spells a country the destination table
                                      does not. Legs 2 and 3 are how "Russia" vs "Russian Federation" and
                                      "South Africa" vs "South Africa, Republic Of" surface as findings
                                      instead of as a silent zero-row join.
      (4) {geo_lexicon, region_map, geography} -> country_origin  any roster spelling a country the canonical
                                      namespace lacks. This is the drift that makes a graph key unjoinable.
      (5) THE B1 HEADLINE, count-only: real (non-pseudo, kind=country) ESR destinations with no
                                      country_origin node, and with no router entry.

    TONNAGE IS OPTIONAL AND THAT IS DELIBERATE. Pass `tonnage` = {ESR code -> kt} (the aggregation
    b1_namespace_diff.py built from silver_esr) and leg 5 additionally reports the tonnage-weighted coverage
    -- the only form of the number that means anything, because 191 unmapped destinations and 27.4% unmapped
    FLOW are very different statements. Without it the leg reports counts and says so. No network, ever.

    REPORTS ONLY. Extending the router changes `resolve_country`'s first-lexical-hit arbitration on a live
    flagged-on path (B1 recon R-3), so it is a ratified behaviour change, never a lint's to make."""
    r = country_axis_rosters()
    if not r["esr_destinations"] and not r["country_origin"]:
        return []                                              # no private configs: vacuous, not "all drift"
    out = ["country-axis namespace diff (B1 R4): " + " / ".join(
        f"{k} {len(r[k])}" for k in ("esr_destinations", "agent", "geo_lexicon", "country_origin",
                                     "region_map", "geography"))]

    def _leg(label: str, left: set[str], right_key: str, why: str) -> None:
        gap = sorted((left - r[right_key]) - _COUNTRY_AXIS_BENIGN)
        if gap:
            out.append(f"country-axis {label}: {len(gap)} spelled here and absent from {right_key} "
                       f"-- {', '.join(gap)} ({why})")

    if r["agent"] and r["esr_destinations"]:
        _leg("agent->esr_destinations", r["agent"], "esr_destinations",
             "the ESR scope guard would detect a buyer the code table cannot resolve")
    if r["esr_destinations"]:
        _leg("geo_lexicon->esr_destinations", r["geo_lexicon"], "esr_destinations",
             "the verifier's spelling does not join the destination table")
        _leg("country_origin->esr_destinations", r["country_origin"], "esr_destinations",
             "the canonical namespace's spelling does not join the destination table")
    for label in ("geo_lexicon", "region_map", "geography"):
        if r[label] and r["country_origin"]:
            _leg(f"{label}->country_origin", r[label], "country_origin",
                 "a country spelled outside the canonical namespace cannot key the graph")

    try:
        codes = (yaml.safe_load((_CFG / "numbers" / "esr_destinations.yaml").read_text(encoding="utf-8"))
                 or {}).get("codes") or {}
    except Exception:                                          # noqa: BLE001
        codes = {}
    real = {int(c): m for c, m in codes.items()
            if (m or {}).get("kind") == "country" and not (m or {}).get("pseudo")}
    if real:
        def _surfaces(m: dict) -> set[str]:
            return {_ca_norm(m.get("name"))} | {_ca_norm(a) for a in (m.get("aliases") or [])}
        no_vocab = [c for c, m in real.items() if not (_surfaces(m) & r["country_origin"])]
        no_route = [c for c, m in real.items() if not (_surfaces(m) & r["geography"])]
        line = (f"country-axis B1 headline: of {len(real)} real ESR destination countries, {len(no_vocab)} "
                f"have no entity_vocabulary country_origin node and {len(no_route)} have no geography.yaml "
                f"router entry")
        if tonnage:
            tot = sum(float(v) for v in tonnage.values() if float(v) > 0) or 1.0
            def _cov(missing: list[int]) -> float:
                miss = sum(float(tonnage.get(c, tonnage.get(str(c), 0)) or 0) for c in missing)
                return 100.0 * (tot - max(miss, 0.0)) / tot
            line += (f"; TONNAGE-WEIGHTED coverage: country_origin {_cov(no_vocab):.1f}%, "
                     f"router {_cov(no_route):.1f}%")
        else:
            line += " (counts only -- pass tonnage={ESR code: kt} for the weighted coverage that matters)"
        out.append(line)
    return out


def main() -> int:
    errs = check_geography()
    if errs:
        print("FAIL geography:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"PASS geography ({len(_countries())} countries; contracts/drivers/regions resolve)")
    for w in country_axis_warnings():
        print(f"NOTE {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
