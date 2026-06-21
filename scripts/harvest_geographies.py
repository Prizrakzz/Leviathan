"""Harvest curated producing regions from configs/geographies/*_regions.yaml into the GraphRAG
region canonicalization set (configs/graphrag/regions.yaml, git-ignored IP).

Ends the per-run "discover a new region" whack-a-mole: every region the geographies already curate
(São Paulo, Bahia, Free State, Sabah, …) is pre-loaded so extraction's region mentions canonicalize
deterministically downstream (extract._canon_region), instead of landing in unmapped_entities.

    python scripts/harvest_geographies.py
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
_GEO = _REPO / "configs" / "geographies"
_OUT = _REPO / "configs" / "graphrag" / "regions.yaml"


def _region_name(slug: str, commodity_tokens: set[str]) -> str:
    """`za_white_maize_free_state` (commodity south_african_white_maize_jse) → `Free_State`.
    Drop the leading country-code token + any token that's part of the commodity slug."""
    toks = slug.split("_")
    kept = [t for i, t in enumerate(toks) if i != 0 and t not in commodity_tokens]
    return "_".join(t.capitalize() for t in kept) if kept else slug


def harvest() -> dict:
    regions: dict[str, dict] = {}
    for f in sorted(_GEO.glob("*_regions.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        commodity = data.get("commodity", "")
        ctoks = set(commodity.split("_"))
        for blk in data.get("regions", []):
            country = blk.get("country_name") or blk.get("country", "")
            for loc in blk.get("locations", []):
                slug = loc.get("region", "")
                name = _region_name(slug, ctoks)
                if not name:
                    continue
                spaced = name.replace("_", " ")
                entry = regions.setdefault(name, {"country": country, "aliases": set()})
                entry["aliases"].update({slug, spaced.lower(), name.lower()})
    # set → sorted list for YAML
    return {k: {"country": v["country"], "aliases": sorted(v["aliases"])}
            for k, v in sorted(regions.items())}


def main() -> None:
    regions = harvest()
    _OUT.write_text(
        "# Harvested from configs/geographies/ by scripts/harvest_geographies.py. PRIVATE (git-ignored).\n"
        "# Full producing-region set for post-extraction region canonicalization (extract._canon_region).\n"
        + yaml.safe_dump({"regions": regions}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    countries = sorted({v["country"] for v in regions.values()})
    print(f"harvested {len(regions)} regions across {len(countries)} countries -> {_OUT}")
    print("countries:", ", ".join(countries))


if __name__ == "__main__":
    main()
