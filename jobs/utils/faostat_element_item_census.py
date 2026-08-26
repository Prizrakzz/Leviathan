"""FAO-2 (Lane 5): the FAOSTAT QCL element x item x unit census -- ONE stream, AWS-free, $0.

The Lane-5 claims (which elements exist, what they cost, which items carry them, which units they
print) are measured HERE and banked at ``data/dec_p0/faostat_livestock_census.json`` so that the
literals pinned in ``configs/sources/faostat_item_map.yaml``,
``transforms/raw_to_bronze/faostat_qcl.py``, ``transforms/bronze_to_silver/faostat_production.py``
and the Lane-5 test suite all cite ONE artifact rather than each other. It is the
``jobs/utils/nass_value_axis_census.py`` shape (Lane 6, C-2): a committed tool beside its committed
output, so the number can be re-derived without asking anyone what was run.

It reads the TRACKED release ZIP -- ``data/raw/production/faostat/qcl/
Production_Crops_Livestock_E_All_Data_(Normalized).zip``, the same 2026-05-11 object the crop-half
backfill runs off -- with the stdlib csv module in one pass, never pandas: the data member is 545 MB
and the point is a tally, not a frame.

THE UNIT SETS ARE THE REASON THIS EXISTS. A (item, element) pair printing TWO units cannot be served
under silver_production's (country_key, metric, year) natural key, and the file contains exactly one
such pair in the livestock neighbourhood. That is discoverable only by counting.

Usage:
    python jobs/utils/faostat_element_item_census.py
    python jobs/utils/faostat_element_item_census.py --zip <path> --out <path>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

DEFAULT_ZIP = (
    _REPO / "data" / "raw" / "production" / "faostat" / "qcl"
    / "Production_Crops_Livestock_E_All_Data_(Normalized).zip"
)
DEFAULT_OUT = _REPO / "data" / "dec_p0" / "faostat_livestock_census.json"

DATA_MEMBER = "Production_Crops_Livestock_E_All_Data_(Normalized).csv"
ELEMENT_LEGEND_MEMBER = "Production_Crops_Livestock_E_Elements.csv"
ITEM_LEGEND_MEMBER = "Production_Crops_Livestock_E_ItemCodes.csv"

# The items Lane 5 reports on: the four ADMITTED, plus every item its written refusals name. A
# reader checking a park needs its number in the same artifact as the admissions' numbers.
CENSUS_ITEMS: tuple[str, ...] = (
    # admitted
    "Cattle",
    "Swine / pigs",
    "Chickens",
    "Raw milk of cattle",
    # parked -- no hierarchy node and no PSD slug
    "Sheep",
    "Goats",
    # parked -- the multi-unit natural-key collision + one item per slug
    "Hen eggs in shell, fresh",
    # parked -- the slaughter axis, no slug left under one-item-per-slug
    "Meat of cattle with the bone, fresh or chilled",
    "Meat of chickens, fresh or chilled",
    "Meat of pig with the bone, fresh or chilled",
)


def _legend_items(z: zipfile.ZipFile) -> set[str]:
    """Legend Item strings, normalized ``"; " -> ", "`` (the legend prints a semicolon where the
    data column prints a comma -- measured, and the item map's header records it)."""
    raw = z.read(ITEM_LEGEND_MEMBER).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    return {r[2].replace("; ", ", ") for r in rows[1:] if len(r) >= 3}


def _legend_elements(z: zipfile.ZipFile) -> dict[str, list[str]]:
    """Element name -> the element codes the legend files under it (several names carry two)."""
    raw = z.read(ELEMENT_LEGEND_MEMBER).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    out: dict[str, list[str]] = defaultdict(list)
    for r in rows[1:]:
        if len(r) >= 2:
            out[r[1].strip()].append(r[0].strip())
    return dict(out)


def census(zip_path: Path, items: tuple[str, ...] = CENSUS_ITEMS) -> dict:
    z = zipfile.ZipFile(zip_path)
    legend_elements = _legend_elements(z)
    legend_items = _legend_items(z)

    element_rows: Counter = Counter()
    element_units: dict[str, Counter] = defaultdict(Counter)
    per_item: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"rows": 0, "areas": set(), "ymin": None, "ymax": None,
                 "units": Counter(), "flags": Counter()}
    )
    # the multi-unit-per-(item, element) proof: how many (area, year) keys carry more than one unit
    unit_keys: dict[tuple[str, str], dict[tuple[str, str], set]] = defaultdict(
        lambda: defaultdict(set)
    )
    # EVERY (item, element) pair's unit set, file-wide. The one-unit-per-(item, element) assumption
    # silver_production's (country_key, metric, year) natural key rests on has never been checked;
    # this is the check, over all 301 items rather than over the ones Lane 5 happens to look at.
    all_pair_units: dict[tuple[str, str], set] = defaultdict(set)
    wanted = set(items)
    total = 0

    with z.open(DATA_MEMBER) as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""))
        for row in reader:
            total += 1
            element, unit, item = row["Element"], row["Unit"], row["Item"]
            element_rows[element] += 1
            element_units[element][unit] += 1
            all_pair_units[(item, element)].add(unit)
            if item not in wanted:
                continue
            key = (item, element)
            rec = per_item[key]
            rec["rows"] += 1
            rec["areas"].add(row["Area"])
            year = int(row["Year"])
            rec["ymin"] = year if rec["ymin"] is None else min(rec["ymin"], year)
            rec["ymax"] = year if rec["ymax"] is None else max(rec["ymax"], year)
            rec["units"][unit] += 1
            rec["flags"][row["Flag"]] += 1
            unit_keys[key][(row["Area"], row["Year"])].add(unit)

    live = set(element_rows)
    return {
        "source_zip": zip_path.name,
        "total_rows": total,
        "legend_element_names": sorted(legend_elements),
        "legend_element_codes": {k: sorted(v) for k, v in sorted(legend_elements.items())},
        "legend_item_count": len(legend_items),
        # the two legend element names that carry ZERO rows -- dead keys, the tell that made the
        # four dead pre-2022 FLAGS legible, and the reason the bronze gate can be the whole universe
        "legend_elements_with_zero_rows": sorted(set(legend_elements) - live),
        "element_rows": dict(element_rows.most_common()),
        "element_units": {k: dict(v.most_common()) for k, v in sorted(element_units.items())},
        "distinct_item_element_pairs": len(all_pair_units),
        # The whole-file answer to "can a governed metric receive two units for one item?" -- the
        # exceptions, named. Anything listed here is unservable under the current natural key.
        "item_element_pairs_with_multiple_units": {
            f"{i} || {e}": sorted(u)
            for (i, e), u in sorted(all_pair_units.items()) if len(u) > 1
        },
        "items": {
            f"{item} || {element}": {
                "rows": rec["rows"],
                "areas": len(rec["areas"]),
                "year_min": rec["ymin"],
                "year_max": rec["ymax"],
                "units": dict(rec["units"].most_common()),
                "flags": dict(rec["flags"].most_common()),
                "area_year_keys": len(unit_keys[(item, element)]),
                "area_year_keys_with_multiple_units": sum(
                    1 for v in unit_keys[(item, element)].values() if len(v) > 1
                ),
                "in_legend": item in legend_items,
            }
            for (item, element), rec in sorted(per_item.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zip", dest="zip_path", default=str(DEFAULT_ZIP))
    ap.add_argument("--out", dest="out_path", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"ERROR: release ZIP not found: {zip_path}")
        return 2

    doc = census(zip_path)
    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"rows read      : {doc['total_rows']}")
    print(f"live elements  : {len(doc['element_rows'])} of {len(doc['legend_element_names'])} legend names")
    print(f"dead legend els: {doc['legend_elements_with_zero_rows']}")
    print(f"items censused : {len(doc['items'])} (item, element) pairs")
    print(f"written        : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
