"""Build the numbers-owned FAS ESR destination code->name reference (ESR_DESTINATION_PLAN W0).

Deterministic curation: FAS ``/api/esr/countries`` raw JSON  ->
``configs/graphrag/numbers/esr_destinations.yaml`` (the committed static reference consumed by the
numbers query builder's name<->code translation).  Re-runnable; the YAML is the source of truth and
this script is its provenance/regenerator (never a runtime dependency).

  python jobs/utils/build_esr_destinations.py --raw <countries.json> [--out <yaml>] [--check]

Curation rules (ESR_DESTINATION_PLAN section 2.3):
  * aliases REUSE the existing destination vocabulary in ``agent.py:_ESR_DESTINATIONS`` as the seed
    (do NOT invent a second, divergent vocabulary) -- every guard display name + name form + demonym
    is attached to its FAS code so the section-5.1 lint (guard name -> code) passes by construction.
  * aliases are globally UNIQUE (a curated guard alias wins; auto self-aliases that would collide are
    dropped -- the fuller distinct description still serves as that code's own alias).
  * ``pseudo: true`` marks codes that are NOT a legitimate single-COUNTRY name target and that drive
    the double-count audit: blocs (EU-27, Former Soviet Union), region residual buckets (``... NEC`` /
    Southern Asia) and Unknown.  ``kind`` records the sub-class (country|territory|former|bloc|
    region_nec|unknown).  Only ``kind: bloc`` is a *potential* double-count class -- W2.2 verified none
    is additive in the live data (see jobs/utils/esr_double_count_audit.py / the YAML ``audit:`` block).

The ``audit:`` block values are passed in via --audit-json (produced by the W2.2 audit) or default to
the ratified 2026-07-23 verdict.  Values are documentation only; the loader ignores them.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# ── curated guard-display -> FAS code (this module's curation; verified against the reference
#    countryDescription 2026-07-23).  The alias FORMS/demonyms come from agent.py:_ESR_DESTINATIONS
#    so the two vocabularies never drift; this map only pins which code each guard name lands on
#    (resolving the reference ambiguities: Vietnam 5520 not the former-South 5510, Netherlands 4210
#    not Antilles 2770, India 5330 not the British Indian Ocean Territory 7810). ──────────────────
_GUARD_DISPLAY_TO_CODE: dict[str, int] = {
    "China": 5700, "Mexico": 2010, "Japan": 5880, "South Korea": 5800, "Taiwan": 5830,
    "Egypt": 7290, "the Philippines": 5650, "Vietnam": 5520, "Indonesia": 5600, "Colombia": 3010,
    "Nigeria": 7530, "Bangladesh": 5380, "Pakistan": 5350, "Thailand": 5490, "Turkey": 4890,
    "Canada": 1220, "the European Union": 1, "Spain": 4700, "Italy": 4750, "the Netherlands": 4210,
    "Germany": 4280, "the United Kingdom": 4120, "Saudi Arabia": 5170, "Iraq": 5050, "Algeria": 7210,
    "Morocco": 7140, "India": 5330, "Malaysia": 5570, "Guatemala": 2050, "Honduras": 2150,
    "the Dominican Republic": 2470, "Peru": 3330, "Chile": 3370, "Venezuela": 3070, "Cuba": 2390,
    "Brazil": 3510, "Argentina": 3570, "unknown destinations": 9990,
}

# Clean article-free display names for the render (r["country"]); article-bearing forms stay in aliases.
_DISPLAY_OVERRIDE: dict[int, str] = {
    5700: "China", 5650: "Philippines", 1: "European Union", 4210: "Netherlands",
    4120: "United Kingdom", 2470: "Dominican Republic", 9990: "Unknown", 5800: "South Korea",
}

# pseudo classification (ESR_DESTINATION_PLAN 2.3 / 4.3).  kind drives the audit; pseudo drives the
# named-read exclusion + the aggregate caveat.
_BLOC: dict[int, str] = {1: "European Union", 4461: "Former Soviet Union"}       # double-count-RISK class
_REGION_NEC: dict[int, str] = {5680: "Southern Asia", 6860: "Other Pacific Islands (NEC)",
                               7640: "Western Africa (NEC)"}                     # residual buckets, no risk
_UNKNOWN: dict[int, str] = {9990: "Unknown"}
# former political entities: real historical single destinations -- pseudo:false, but must NOT be
# aliased by the modern successor's name (the fuller distinct description is their only alias).
_FORMER: set[int] = {4290, 4350, 4799, 5510, 5220}   # German DR, Czechoslovakia, Yugoslavia, S.Vietnam, S.Yemen

_DEFAULT_AUDIT = {
    "probed_table": "silver_esr_compact",
    "probed_source": "s3://leviathan-dev-shahem-001/silver/esr (S3-direct parquet, no Athena)",
    "probed_vintage": "as_of=20260717 full-history republish, 10 commodities",
    "distinct_codes_in_data": 178,
    "data_codes_all_covered": True,
    "double_count_verdict": "none",
    "double_count_note": ("national agg=sum across all country_code does NOT double-count: EU-27 (1) is "
                          "absent from the data; FSU-12 (4461) is never additively equal to its region "
                          "members (0/322 cells) -- a distinct residual/reallocation bucket; region-NEC "
                          "codes are residual by construction. W2.4 national exclusion NOT triggered."),
    "aggregate_codes_present": [4461, 5680, 6860, 7640],
    "national_exclusion_required": [],       # empty: no NOT IN needed on the national sum path
    "bloc_watch_codes": [1, 4461],           # exclude from the national sum ONLY if a future vintage makes a bloc additive
}


def _clean(desc: str) -> str:
    """Title-case a padded FAS description into a readable display name."""
    d = re.sub(r"\s+", " ", desc.strip())
    # keep parenthetical/comma structure; title-case word-wise, preserving apostrophes.
    out = " ".join(w.capitalize() if w.isupper() or w.islower() else w for w in d.split(" "))
    return out


def _norm_alias(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def build(raw_rows: list[dict], audit: dict) -> dict:
    guard = _load_guard_forms()                          # code -> set(alias forms) from _ESR_DESTINATIONS
    by_code = {r["countryCode"]: r for r in raw_rows}
    codes = sorted(by_code)
    claimed: dict[str, int] = {}                          # alias -> code (global uniqueness)
    out_codes: dict[int, dict] = {}

    def display_for(code: int) -> str:
        if code in _DISPLAY_OVERRIDE:
            return _DISPLAY_OVERRIDE[code]
        if code in _BLOC:
            return _BLOC[code]
        if code in _REGION_NEC:
            return _REGION_NEC[code]
        return _clean(by_code[code]["countryDescription"])

    def kind_pseudo(code: int) -> tuple[str, bool]:
        if code in _UNKNOWN:
            return "unknown", True
        if code in _BLOC:
            return "bloc", True
        if code in _REGION_NEC:
            return "region_nec", True
        if code in _FORMER:
            return "former", False
        return "country", False

    # PASS 1 -- curated guard aliases first (authoritative; they win every collision).
    for code in codes:
        for a in sorted(guard.get(code, ()), key=len, reverse=True):
            a = _norm_alias(a)
            if a and claimed.get(a, code) == code:
                claimed[a] = code
    # PASS 2 -- auto self-alias per code = the clean display name only, collision-dropped. (The raw
    # padded FAS countryName abbreviations -- "kor rep", "guin-bis", "n antil" -- are deliberately NOT
    # aliased: they are not surface forms the model emits, and "guin-bis" on Western-Africa-NEC would
    # mis-resolve. Guard forms (PASS 1) + the clean display cover the real vocabulary.)
    for code in codes:
        a = _norm_alias(display_for(code))
        if a and a not in claimed:
            claimed[a] = code

    # assemble
    alias_by_code: dict[int, list[str]] = {c: [] for c in codes}
    for a, c in claimed.items():
        alias_by_code[c].append(a)
    for code in codes:
        kind, pseudo = kind_pseudo(code)
        out_codes[code] = {
            "name": display_for(code),
            "aliases": sorted(set(alias_by_code[code])),
            "pseudo": pseudo,
            "kind": kind,
        }
    return {
        "version": 1,
        "source": "fas_api_esr_countries",
        "source_endpoint": "https://api.fas.usda.gov/api/esr/countries",
        "fetched": audit.get("fetched", "2026-07-23"),
        "reference_row_count": len(raw_rows),
        "audit": {k: v for k, v in audit.items() if k != "fetched"},
        "codes": out_codes,
    }


def _load_guard_forms() -> dict[int, set[str]]:
    """code -> alias forms, cross-seeded from agent.py:_ESR_DESTINATIONS (single source of truth)."""
    from leviathan.graphrag.numbers.agent import _ESR_DESTINATIONS
    out: dict[int, set[str]] = {}
    disp_to_code = _GUARD_DISPLAY_TO_CODE
    for disp, names, dems in _ESR_DESTINATIONS:
        code = disp_to_code.get(disp)
        if code is None:
            raise SystemExit(f"guard destination {disp!r} has no curated FAS code -- update _GUARD_DISPLAY_TO_CODE")
        out.setdefault(code, set()).update(names)
        out.setdefault(code, set()).update(dems)
    return out


def _dump_yaml(doc: dict) -> str:
    """Hand-rolled compact YAML so ``codes`` render one-line per code with INTEGER keys (stable, diffable)."""
    import io
    b = io.StringIO()
    b.write("# GENERATED by jobs/utils/build_esr_destinations.py -- FAS ESR destination code -> canonical\n")
    b.write("# name. Numbers-owned static reference (ESR_DESTINATION_PLAN W0). Consumed by the numbers\n")
    b.write("# query builder's name<->code translation; NO silver column, NO pg mirror. Aliases are\n")
    b.write("# cross-seeded from agent.py:_ESR_DESTINATIONS. pseudo:true = not a single-country name\n")
    b.write("# target (bloc / region-NEC residual / unknown); see the audit: block for the W2.2 verdict.\n")
    for k in ("version", "source", "source_endpoint", "fetched", "reference_row_count"):
        b.write(f"{k}: {json.dumps(doc[k])}\n")
    b.write("audit:\n")
    for k, v in doc["audit"].items():
        b.write(f"  {k}: {json.dumps(v)}\n")
    b.write("codes:\n")
    for code in sorted(doc["codes"]):
        e = doc["codes"][code]
        b.write(f"  {code}: {{name: {json.dumps(e['name'])}, aliases: {json.dumps(e['aliases'])}, "
                f"pseudo: {str(e['pseudo']).lower()}, kind: {e['kind']}}}\n")
    return b.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", required=True, help="FAS /api/esr/countries raw JSON")
    ap.add_argument("--out", default=None, help="output YAML (default: configs/graphrag/numbers/esr_destinations.yaml)")
    ap.add_argument("--audit-json", default=None, help="W2.2 audit summary JSON (else the ratified default)")
    ap.add_argument("--fetched", default="2026-07-23")
    ap.add_argument("--check", action="store_true", help="build in-memory and print stats; do not write")
    args = ap.parse_args()

    raw_rows = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    audit = dict(_DEFAULT_AUDIT)
    if args.audit_json:
        audit.update(json.loads(Path(args.audit_json).read_text(encoding="utf-8")))
    audit["fetched"] = args.fetched
    doc = build(raw_rows, audit)
    text = _dump_yaml(doc)

    n_pseudo = sum(1 for e in doc["codes"].values() if e["pseudo"])
    print(f"codes={len(doc['codes'])} pseudo={n_pseudo} aliases={sum(len(e['aliases']) for e in doc['codes'].values())}")
    if args.check:
        print(text[:400])
        return
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "configs" / "graphrag" / "numbers" / "esr_destinations.yaml")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
