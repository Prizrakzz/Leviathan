"""The entity-vocabulary slug seam -- the ONE vocabulary surface with no tripwire until 2026-08-05.

During the MATIF arming verification, a break-it probe renamed `french_rapeseed_matif` inside
configs/graphrag/entity_vocabulary.yaml and NOTHING went red: the token silently stopped being a
contract-slug reference and became an inert surface form. Every sibling seam (CONTRACT_MAP,
tables.yaml unit_overrides, cftc_cot.yaml not_covered, futures_roll delivery cycles, ...) already
pins its slug vocabulary; this file pins the last one, in the same yaml==frozenset idiom as the
COT fence tests.

THE GUARDED PROPERTY is the INTERSECTION of alias tokens with the canonical contract universe
(leviathan.common.constants.ALL_COMMODITIES). Alias lists deliberately mix quoted surface forms
("blé tendre") with bare contract slugs (french_wheat_matif); only the slugs are load-bearing --
they are what lets extraction resolve a surface mention onto a tradeable contract. A rename in
EITHER direction moves the intersection and reds the pin:
  - slug renamed/deleted in the yaml  -> intersection loses a member (the probe's exact shape);
  - universe renames a contract       -> intersection loses a member from the other side.
Growing the universe (a new contract) is a DELIBERATE edit here too: add the slug to the alias
map and to the pin in the same change, or the absence stays visible.

configs/graphrag/entity_vocabulary.yaml is GITIGNORED (private IP) -- absent in worktree builds
per feedback_worktree_builds_miss_gitignored_configs -- so the graphrag half SKIPS loudly when
the file is not present rather than passing vacuously.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from leviathan.common.constants import ALL_COMMODITIES

_REPO = Path(__file__).resolve().parents[2]
_GRAPHRAG_VOCAB = _REPO / "configs" / "graphrag" / "entity_vocabulary.yaml"
_SOURCES_VOCAB = _REPO / "configs" / "sources" / "entity_vocabulary.yaml"

# The pinned intersection: every contract slug the graphrag alias map is expected to reference.
# 24 of the 31-contract universe as of 2026-08-05 (the 7 absent ones -- e.g. sugar_no_11,
# arabica_coffee, cotton_no_2_ice -- are aliased through NON-slug surface forms by design; their
# nodes exist, the slug string just does not appear in an alias list). If you add a contract or
# re-alias one, move this pin IN THE SAME COMMIT and say why in the message.
_EXPECTED_GRAPHRAG_SLUG_REFS = frozenset({
    "brazilian_arabica_coffee",
    "campinas_corn_reference_bmf",
    "canola_ice",
    "corn_cbot",
    "french_maize_matif",
    "french_rapeseed_matif",
    "french_wheat_matif",
    "hard_red_spring_wheat_mgex",
    "hard_red_winter_wheat_kcbt",
    "malaysian_crude_palm_oil_cme",
    "palm_olein_dce",
    "rapeseed_meal_zce",
    "rapeseed_oil_zce",
    "rough_rice_cbot",
    "soft_red_winter_wheat_cbot",
    "south_african_white_maize_jse",
    "south_african_yellow_maize_jse",
    "soybean_meal_cbot",
    "soybean_meal_dce",
    "soybean_oil_cbot",
    "soybean_oil_dce",
    "soybeans_cbot",
    "soybeans_no_1_dce",
    "soybeans_no_2_dce",
})


def _universe() -> frozenset[str]:
    u = frozenset(ALL_COMMODITIES)
    # the pin only means something while it is a subset of the universe
    assert _EXPECTED_GRAPHRAG_SLUG_REFS <= u, (
        "the pinned slug refs are no longer a subset of ALL_COMMODITIES -- a contract was renamed "
        f"or removed: {sorted(_EXPECTED_GRAPHRAG_SLUG_REFS - u)}"
    )
    return u


def test_graphrag_alias_slug_refs_match_the_pin() -> None:
    if not _GRAPHRAG_VOCAB.exists():
        pytest.skip("configs/graphrag/entity_vocabulary.yaml is gitignored and absent here")
    vocab = yaml.safe_load(_GRAPHRAG_VOCAB.read_text(encoding="utf-8"))
    aliases = vocab.get("aliases") or {}
    u = _universe()
    refs = frozenset(
        tok
        for toks in aliases.values()
        if isinstance(toks, list)
        for tok in toks
        if isinstance(tok, str) and tok in u
    )
    missing = _EXPECTED_GRAPHRAG_SLUG_REFS - refs
    unexpected = refs - _EXPECTED_GRAPHRAG_SLUG_REFS
    assert refs == _EXPECTED_GRAPHRAG_SLUG_REFS, (
        "the graphrag alias map's contract-slug references moved. "
        f"missing (renamed/deleted in the yaml?): {sorted(missing)}; "
        f"new (move the pin deliberately): {sorted(unexpected)}"
    )


def test_sources_vocab_canonicals_are_all_in_the_universe() -> None:
    # the LEGACY (frozen) extractor vocabulary: every commodities.*.canonical must be a real slug.
    # No pin needed -- the file is frozen; membership is the whole contract.
    src = yaml.safe_load(_SOURCES_VOCAB.read_text(encoding="utf-8"))
    u = _universe()
    bad = sorted(
        entry["canonical"]
        for entry in (src.get("commodities") or {}).values()
        if isinstance(entry, dict) and entry.get("canonical") and entry["canonical"] not in u
    )
    assert not bad, f"legacy vocab canonicals not in ALL_COMMODITIES (renamed slug?): {bad}"
