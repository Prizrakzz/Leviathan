"""Build the numbers-owned FAOSTAT area reference (D-EC projection wave FAO-3).

Deterministic curation: the QCL bulk ZIP's OWN legend member
``Production_Crops_Livestock_E_AreaCodes.csv``  ->  ``configs/graphrag/numbers/faostat_areas.yaml``
(the static reference consumed by the numbers query builder's name->area translation).  Re-runnable;
the YAML is the source of truth and this script is its provenance/regenerator, never a runtime
dependency.  No network and no AWS -- the ZIP is the raw object already on disk / in S3.

  python jobs/utils/build_faostat_areas.py [--zip <path>] [--out <yaml>] [--check]

THE ONE NORMALIZATION, AND IT IS MEASURED.  The legend CSVs print a SEMICOLON where the DATA column
prints a COMMA -- ``'China; mainland'`` in AreaCodes.csv, ``'China, mainland'`` in the Value rows.  The
data column is what ``silver_production.country`` carries and therefore what the SQL must match, so
every legend name is rewritten ``"; " -> ", "``.  Under that single substitution the legend reconciles
with the data column EXACTLY: 244 codes both sides, zero name disagreements, measured on the
2026-05-11 ZIP by a full scan of the 4,209,110-row normalized CSV.

CLASSIFICATION IS BY CODE, NOT BY READING THE NAME.  FAOSTAT reserves the 5000+ band for aggregates,
so ``code >= 5000`` IS the aggregate test and every such code must land in one of the enumerated
buckets below -- an unclassified 5000+ code RAISES rather than defaulting, because a new FAO aggregate
silently typed as a country is precisely the double-count this reference exists to prevent.  ONE
aggregate hides below the band and is declared by hand: area 351 ``'China'`` == mainland + Hong Kong
SAR + Macao SAR + Taiwan Province of, verified as a ROUNDING ROLL-UP, not an exact float identity:
across 13,771 comparable Production (Item, Year) cells the four members sum to the 351 row within
1e-6 relative on 13,738 (exact float equality on 13,001; max residual 0.02 t, i.e. FAO's own printed
rounding). Re-measured 2026-08-26 after the first pin ("exact on 13,724 of 13,724") failed
reproduce-to-count; the COMPOSITION stands, the exactness claim did not.

ALIASES.  Every area gets its own lowercased name as a self-alias; the curated map below adds the
estate's names, common short forms and demonyms.  A curated alias WINS a collision and the colliding
auto self-alias is dropped -- that is how ``china`` lands on ``'China, mainland'`` (the reporting
country) instead of on the bare four-way aggregate, which keeps only its explicit aggregate aliases.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_ZIP = _REPO / "data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
_DEFAULT_OUT = _REPO / "configs/graphrag/numbers/faostat_areas.yaml"
_AREA_CODES_MEMBER = "Production_Crops_Livestock_E_AreaCodes.csv"

# ── aggregate classification, by FAOSTAT area code ────────────────────────────────────────────────
_WORLD = {5000}
_CONTINENTS = {5100, 5200, 5300, 5400, 5500}
_BLOCS = {5707}                                              # European Union (27)
_GROUPS = {5801, 5802, 5803, 5815, 5817}                     # LDC / LLDC / SIDS / LIFDC / NFIDC
# Sub-regions are the remaining 5000+ codes; they are enumerated rather than inferred so a NEW
# FAO aggregate cannot be swept into the bucket by a range test that happens to cover it.
_SUBREGIONS = {
    5101, 5102, 5103, 5104, 5105,                            # Africa
    5203, 5204, 5206, 5207,                                  # Americas
    5301, 5302, 5303, 5304, 5305,                            # Asia
    5401, 5402, 5403, 5404,                                  # Europe
    5501, 5502, 5503, 5504,                                  # Oceania
}
# The one aggregate BELOW the 5000 band, with its measured composition.
_COUNTRY_AGGREGATES: dict[int, list[int]] = {351: [41, 96, 128, 214]}

# Dissolved reporting areas: real single areas (pseudo:false) that must never be summed with their
# successor states.  Typed apart from `country` for the same reason esr_destinations types `former`.
_FORMER = {
    15,    # Belgium-Luxembourg
    51,    # Czechoslovakia
    62,    # Ethiopia PDR
    186,   # Serbia and Montenegro
    206,   # Sudan (former)
    228,   # USSR
    248,   # Yugoslav SFR
}

# ── curated aliases: FAOSTAT area code -> the estate's names for it ───────────────────────────────
# Every entry is either (a) a FAOSTAT display string the estate would never type verbatim, or (b) a
# demonym / short form the model plausibly emits.  A country whose FAOSTAT name IS its common name
# needs no entry -- the auto self-alias already covers it.
_CURATED_ALIASES: dict[int, list[str]] = {
    # -- names the estate types differently from FAOSTAT ---------------------------------------
    231: ["united states", "the united states", "usa", "u.s.", "u.s.a.", "us", "america", "american"],
    185: ["russia", "russian"],
    237: ["vietnam", "vietnamese"],
    223: ["turkey", "turkiye", "turkish"],
    107: ["cote d'ivoire", "cote d ivoire", "cote divoire", "ivory coast", "ivorian"],
    150: ["netherlands", "the netherlands", "holland", "dutch"],
    229: ["united kingdom", "the united kingdom", "uk", "u.k.", "great britain", "britain", "british"],
    117: ["south korea", "korea", "korean"],
    116: ["north korea", "dprk"],
    102: ["iran", "iranian"],
    236: ["venezuela", "venezuelan"],
    19:  ["bolivia", "bolivian"],
    215: ["tanzania", "tanzanian"],
    250: ["dr congo", "drc", "democratic republic of congo", "congo-kinshasa"],
    46:  ["republic of the congo", "congo-brazzaville"],
    120: ["laos", "lao pdr"],
    212: ["syria", "syrian"],
    146: ["moldova"],
    154: ["macedonia"],
    209: ["swaziland"],
    35:  ["cape verde"],
    167: ["czech republic"],
    28:  ["burma"],
    299: ["palestinian territories", "west bank and gaza"],
    # -- the China surface: `china` is the mainland REPORTING COUNTRY, never the roll-up ---------
    41:  ["china", "mainland china", "china mainland", "chinese"],
    351: ["china (faostat aggregate)", "greater china", "china total"],
    214: ["taiwan", "chinese taipei"],
    96:  ["hong kong"],
    128: ["macao", "macau"],
    # -- demonyms for the estate's producer geography ------------------------------------------
    21:  ["brazilian"],
    9:   ["argentinian", "argentine"],
    230: ["ukrainian"],
    100: ["indian"],
    101: ["indonesian"],
    131: ["malaysian"],
    216: ["thai"],
    10:  ["australian"],
    33:  ["canadian"],
    68:  ["french"],
    79:  ["german"],
    159: ["nigerian"],
    81:  ["ghanaian"],
    44:  ["colombian"],
    238: ["ethiopian"],
    170: ["peruvian"],
    138: ["mexican"],
    59:  ["egyptian"],
    165: ["pakistani"],
    16:  ["bangladeshi"],
    202: ["south african"],
    108: ["kazakh"],
    183: ["romanian"],
    173: ["polish"],
    # -- the aggregate ladder, addressable BY NAME so a bloc ask is answerable AND caveatable ----
    5000: ["global", "worldwide", "the world"],
    5707: ["european union", "eu", "eu-27", "eu27", "the eu", "the european union"],
    5801: ["least developed countries", "ldcs", "ldc"],
    5802: ["land locked developing countries", "landlocked developing countries", "lldcs", "lldc"],
    5803: ["small island developing states", "sids"],
    5815: ["low income food deficit countries", "lifdcs", "lifdc"],
    5817: ["net food importing developing countries", "nfidcs", "nfidc"],
}


class AreaClassificationError(ValueError):
    """A FAOSTAT area code cannot be classified (fail-closed: never default an aggregate to country)."""


def _norm_legend_name(name: str) -> str:
    """The legend CSVs' semicolon separator -> the data column's comma. See the module docstring."""
    return name.replace("; ", ", ")


def _norm_alias(a: str) -> str:
    return re.sub(r"\s+", " ", a.strip().lower())


def read_area_codes(zip_path: Path) -> list[tuple[int, str, str]]:
    """[(area_code, m49, area_name)] from the ZIP's own legend, names normalized to the data column."""
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(_AREA_CODES_MEMBER).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    out: list[tuple[int, str, str]] = []
    for code, m49, name in (r for r in rows[1:] if len(r) >= 3):
        out.append((int(code), m49.lstrip("'"), _norm_legend_name(name)))
    return sorted(out)


def classify(code: int) -> tuple[bool, str]:
    """(pseudo, kind) for one area code. RAISES on an unclassified 5000+ code."""
    if code in _WORLD:
        return True, "world"
    if code in _CONTINENTS:
        return True, "continent"
    if code in _SUBREGIONS:
        return True, "subregion"
    if code in _BLOCS:
        return True, "bloc"
    if code in _GROUPS:
        return True, "group"
    if code in _COUNTRY_AGGREGATES:
        return True, "country_aggregate"
    if code >= 5000:
        raise AreaClassificationError(
            f"FAOSTAT area code {code} is in the 5000+ aggregate band but matches no declared "
            "aggregate bucket. Classify it in build_faostat_areas.py before regenerating -- an "
            "aggregate typed as a country double-counts every sum over the country axis."
        )
    if code in _FORMER:
        return False, "former"
    return False, "country"


def build_entries(areas: list[tuple[int, str, str]]) -> dict[int, dict]:
    """area code -> the reference entry, with curated aliases winning every self-alias collision."""
    curated_owner: dict[str, int] = {}
    for code, aliases in _CURATED_ALIASES.items():
        for a in aliases:
            na = _norm_alias(a)
            if na in curated_owner and curated_owner[na] != code:
                raise AreaClassificationError(
                    f"curated alias {a!r} is claimed by BOTH area {curated_owner[na]} and {code}"
                )
            curated_owner[na] = code

    entries: dict[int, dict] = {}
    for code, m49, name in areas:
        pseudo, kind = classify(code)
        aliases: list[str] = []
        self_alias = _norm_alias(name)
        # a curated alias WINS: drop the colliding self-alias rather than minting a second owner.
        if curated_owner.get(self_alias, code) == code:
            aliases.append(self_alias)
        aliases += [a for a in (_norm_alias(x) for x in _CURATED_ALIASES.get(code, []))
                    if a not in aliases]
        entry = {"name": name, "m49": m49, "aliases": aliases, "pseudo": pseudo, "kind": kind}
        if code in _COUNTRY_AGGREGATES:
            entry["members"] = list(_COUNTRY_AGGREGATES[code])
        entries[code] = entry
    unaddressable = [c for c, e in entries.items() if not e["aliases"]]
    if unaddressable:
        raise AreaClassificationError(
            f"areas {sorted(unaddressable)} carry NO alias and are unreachable by name; give each an "
            "explicit alias in _CURATED_ALIASES rather than shipping a dark row"
        )
    return entries


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(entries: dict[int, dict], zip_path: Path, fetched: str) -> str:
    head = f"""# GENERATED by jobs/utils/build_faostat_areas.py -- FAOSTAT QCL area code -> the RAW M49
# display string the silver_production `country` column carries.  Numbers-owned static reference
# (D-EC projection wave FAO-3), consumed by the numbers query builder's name->area translation via
# TableSpec.country_name_ref.  NO silver column, NO pg mirror.
#
# `name` is the join key ONLY because it is what the physical column stores; the STABLE identity is
# the area CODE this file keys on, which is what makes an unmapped probed area a rename tripwire
# rather than a mystery (faostat_areas.missing_areas).
#
# pseudo:true == a FAOSTAT AGGREGATE sharing the country column with its own members -- World, the
# five continents and their sub-regions, European Union (27), the five country groups, and the bare
# `China` row, which is mainland + Hong Kong SAR + Macao SAR + Taiwan Province of (MEASURED as a
# ROUNDING roll-up: 13,771 Production cells, within 1e-6 relative on 13,738, max residual 0.02 t).
# Summing this column without excluding them double-counts.  `china` therefore resolves to the
# mainland REPORTING COUNTRY; the roll-up is reachable only under an explicit aggregate alias.
version: 1
source: "faostat_qcl_bulk_zip"
source_file: {_yaml_str(zip_path.name)}
source_member: {_yaml_str(_AREA_CODES_MEMBER)}
fetched: {_yaml_str(fetched)}
reference_row_count: {len(entries)}
audit:
  probed_object: "data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
  distinct_areas_in_data: {len(entries)}
  data_areas_all_covered: true
  legend_separator_note: "the legend CSVs print '; ' where the data column prints ', '; every name here is normalized to the DATA form, and under that one substitution legend and data reconcile exactly (244/244 codes, zero name disagreements)"
  china_aggregate_members: {_COUNTRY_AGGREGATES[351]}
  china_aggregate_proof: "China(351) production == sum(41, 96, 128, 214) as a ROUNDING roll-up: 13,771 comparable (Item, Year) cells, within 1e-6 relative on 13,738, exact-float on 13,001, max residual 0.02 t (full scan, 2026-05-11 ZIP; re-measured 2026-08-26 -- the composition is the claim, exactness is not)"
  aggregate_codes: {sorted(_WORLD | _CONTINENTS | _SUBREGIONS | _BLOCS | _GROUPS | set(_COUNTRY_AGGREGATES))}
  former_area_codes: {sorted(_FORMER)}
areas:
"""
    lines = [head]
    for code in sorted(entries):
        e = entries[code]
        alias_list = ", ".join(_yaml_str(a) for a in e["aliases"])
        parts = [
            f"name: {_yaml_str(e['name'])}",
            f"m49: {_yaml_str(e['m49'])}",
            f"aliases: [{alias_list}]",
            f"pseudo: {'true' if e['pseudo'] else 'false'}",
            f"kind: {e['kind']}",
        ]
        if "members" in e:
            parts.append(f"members: {e['members']}")
        lines.append(f"  {code}: {{{', '.join(parts)}}}\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zip", default=str(_DEFAULT_ZIP), help="raw FAOSTAT QCL bulk ZIP")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="reference YAML to write")
    ap.add_argument("--fetched", default="2026-05-11", help="raw-object vintage recorded in the header")
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the rendered reference differs from --out")
    args = ap.parse_args()

    zip_path = Path(args.zip)
    entries = build_entries(read_area_codes(zip_path))
    body = render(entries, zip_path, args.fetched)
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != body:
            print(f"STALE: {out} differs from the rendered reference")
            return 1
        print(f"OK: {out} matches the rendered reference ({len(entries)} areas)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline='\n' pins LF regardless of platform: --check reads with universal newlines, so a CRLF
    # write on Windows would pass the gate while rewriting all 275 lines against an LF-landed copy --
    # full-file churn on a reference whose whole point is byte-stable provenance (no .gitattributes
    # exists to normalize it).
    out.write_text(body, encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({len(entries)} areas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
