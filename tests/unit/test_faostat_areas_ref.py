"""FAOSTAT area reference (D-EC projection wave FAO-3) -- loader, lint, generator round-trip, and the
query-side name->area translation it unlocks.

AWS-free. The reference is generated from a TRACKED repo artifact -- the QCL bulk ZIP's own legend
member ``Production_Crops_Livestock_E_AreaCodes.csv`` -- so the census this file pins is reproducible
here rather than quoted from a plan: ``python jobs/utils/build_faostat_areas.py --check``.

WHAT THE LITERALS BELOW ARE. They are the MEASURED area strings, taken from the 2026-05-11 raw object
``data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip`` (244 areas,
4,209,110 rows; the same object the in-repo bronze partitions under
``data/bronze/production/faostat/qcl/`` were cut from). They are pinned as literals on purpose: the
failure this reference exists to close is a ``country='United States'`` ask compiling clean SQL
against a column holding ``'United States of America'`` and returning ZERO rows, silently, so the
exact bytes ARE the contract.
"""
from __future__ import annotations

import csv
import io
import textwrap
import zipfile
from pathlib import Path

import pytest
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.faostat_areas import (
    lint_reference,
    load_faostat_areas,
    missing_areas,
)
from leviathan.graphrag.numbers.registry import load_registry

_REPO = Path(__file__).resolve().parents[2]
_QCL_ZIP = _REPO / "data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
_AREA_CODES_MEMBER = "Production_Crops_Livestock_E_AreaCodes.csv"
_needs_zip = pytest.mark.skipif(not _QCL_ZIP.exists(), reason=f"raw QCL ZIP not checked out: {_QCL_ZIP}")


def _prod():
    return load_registry().get("silver_production")


# ─────────────────────────────── the committed reference ───────────────────────────────

def test_committed_reference_loads_and_is_lint_clean():
    assert lint_reference() == []                       # alias uniqueness + pseudo/kind + member resolution
    ref = load_faostat_areas()
    assert len(ref.area_to_display) == 244              # every area the 2026-05-11 ZIP carries
    assert len(ref.pseudo_areas) == 35                  # the aggregate ladder + the bare 'China' roll-up


@pytest.mark.parametrize("name,area", [
    ("United States", "United States of America"),      # the ask that returned 0 rows, silently, before FAO-3
    ("usa", "United States of America"),
    ("US", "United States of America"),
    ("Russia", "Russian Federation"),
    ("Vietnam", "Viet Nam"),                            # FAOSTAT spells it as two words
    ("Turkey", "Türkiye"),                         # renamed 2022; the estate still types the old name
    ("Ivory Coast", "Côte d'Ivoire"),
    ("cote d'ivoire", "Côte d'Ivoire"),            # unaccented, apostrophe kept
    ("Cote d Ivoire", "Côte d'Ivoire"),            # unaccented, apostrophe dropped
    ("South Korea", "Republic of Korea"),
    ("Iran", "Iran (Islamic Republic of)"),
    ("Netherlands", "Netherlands (Kingdom of the)"),
    ("United Kingdom", "United Kingdom of Great Britain and Northern Ireland"),
    ("Tanzania", "United Republic of Tanzania"),
    ("the EU", "European Union (27)"),
    ("World", "World"),
])
def test_resolve_hits_the_measured_area_string(name, area):
    assert load_faostat_areas().resolve_codes(name) == [area]


def test_china_resolves_to_the_mainland_reporting_country_not_the_rollup():
    """THE TRAP THIS REFERENCE EXISTS FOR. FAOSTAT carries a bare ``'China'`` row BESIDE its four
    members, and it is a four-way ROUNDING roll-up (mainland + Hong Kong SAR + Macao SAR + Taiwan
    Province of) -- measured on the full-file scan: 13,771 comparable Production cells, members sum
    within 1e-6 relative on 13,738, max residual 0.02 t. So ``china`` must land on the reporting
    COUNTRY, and the roll-up must be reachable only when a reader asks for it."""
    ref = load_faostat_areas()
    assert ref.resolve_codes("China") == ["China, mainland"]
    assert ref.resolve_codes("greater china") == ["China"]
    assert ref.is_pseudo("China") and not ref.is_pseudo("China, mainland")
    assert ref.kind("China") == "country_aggregate"
    assert ref.members("China") == (
        "China, mainland", "China, Hong Kong SAR", "China, Macao SAR", "China, Taiwan Province of",
    )
    assert ref.members("China, mainland") == ()         # not declared == no claim, never "no members"


def test_the_aggregate_ladder_is_declared_and_typed():
    """Members must never be silently summed with the aggregates that sit in the SAME column."""
    ref = load_faostat_areas()
    assert ref.kind("World") == "world"
    for continent in ("Africa", "Americas", "Asia", "Europe", "Oceania"):
        assert ref.kind(continent) == "continent", continent
    for sub in ("Eastern Africa", "Northern America", "South-eastern Asia", "Western Europe", "Polynesia"):
        assert ref.kind(sub) == "subregion", sub
    assert ref.kind("European Union (27)") == "bloc"
    for group in ("Least Developed Countries (LDCs)",
                  "Land Locked Developing Countries (LLDCs)",
                  "Small Island Developing States (SIDS)",
                  "Low Income Food Deficit Countries (LIFDCs)",
                  "Net Food Importing Developing Countries (NFIDCs)"):
        assert ref.kind(group) == "group", group
        assert ref.is_pseudo(group), group
    # dissolved reporting areas are NOT aggregates -- real single areas, never summed with successors
    for former in ("USSR", "Czechoslovakia", "Yugoslav SFR", "Sudan (former)", "Belgium-Luxembourg"):
        assert ref.kind(former) == "former" and not ref.is_pseudo(former), former
    assert not ref.is_pseudo("Brazil")


def test_resolve_fail_closed_and_unscoped_path():
    ref = load_faostat_areas()
    assert ref.resolve_codes("Narnia") == []            # unresolved -> caller fails CLOSED, never the world row
    assert ref.resolve_codes("") == []                  # unscoped path (no country filter)
    assert ref.resolve_codes(None) == []


def test_display_is_identity_with_a_bare_fallback():
    """FAOSTAT's own area string IS the honest label; rewriting it to an estate name would put a word
    on the row the source never printed. An unmapped value falls back to itself and never raises."""
    ref = load_faostat_areas()
    assert ref.display("Viet Nam") == "Viet Nam"
    assert ref.display("Atlantis") == "Atlantis"


def test_area_code_is_the_stable_identity():
    """The join key is the DISPLAY STRING only because that is what the physical column stores; the
    source's stable id is the area CODE, which is what makes a rename detectable rather than silent."""
    ref = load_faostat_areas()
    assert ref.code("United States of America") == 231
    assert ref.code("China, mainland") == 41 and ref.code("China") == 351
    assert ref.code("Atlantis") is None


# ─────────────────────── the census: reference vs the raw object it came from ───────────────────────

def _measured_areas() -> set[str]:
    """The area universe as the DATA column spells it, from the ZIP's own legend member. The legend
    prints a SEMICOLON where the data column prints a COMMA ('China; mainland' vs 'China, mainland');
    under that one substitution the two reconcile EXACTLY -- 244/244 codes, zero name disagreements,
    measured by a full scan of the 4,209,110-row normalized CSV on 2026-05-11."""
    with zipfile.ZipFile(_QCL_ZIP) as z:
        raw = z.read(_AREA_CODES_MEMBER).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw)))
    return {r[2].replace("; ", ", ") for r in rows[1:] if len(r) >= 3}


@_needs_zip
def test_every_measured_area_is_covered():
    """A probed-present-but-unmapped area is a HARD failure, not a fallback: it is unreachable by name
    AND it is how a FAOSTAT rename announces itself (the string moves, the code does not)."""
    measured = _measured_areas()
    assert len(measured) == 244
    assert missing_areas(measured) == []
    assert missing_areas([*measured, "Atlantis"]) == ["Atlantis"]


@_needs_zip
def test_generator_round_trip_is_clean():
    """The reference is GENERATED; --check re-renders it from the raw object and fails on any drift, so
    a hand-edit or a new FAO vintage cannot leave the committed file and its source disagreeing."""
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, str(_REPO / "jobs/utils/build_faostat_areas.py"), "--check"],
        capture_output=True, text=True, cwd=str(_REPO),
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_generator_refuses_an_unclassified_aggregate_code():
    """FAOSTAT reserves 5000+ for aggregates. An unclassified one RAISES rather than defaulting to
    country -- an aggregate typed as a country double-counts every sum over this axis."""
    from jobs.utils.build_faostat_areas import AreaClassificationError, classify
    assert classify(231) == (False, "country")
    assert classify(5000) == (True, "world")
    with pytest.raises(AreaClassificationError, match="5000\\+ aggregate band"):
        classify(5999)


# ─────────────────── the governed key: why the ask goes through the DISPLAY column ───────────────────

def test_country_key_still_carries_the_comma():
    """DOCUMENTATION WITH A TEST, and a deliberate NON-fix. ``standardize_country_name`` strips accents,
    spaces, hyphens, apostrophes and parens but NOT commas, so the governed key for the mainland row
    ships as 'china,_mainland'. FAO-3 routes the ask through the DISPLAY column instead of touching
    this, because changing the key re-writes the join surface every ML-label consumer already reads.
    Pinned so the state is recorded rather than rediscovered."""
    from leviathan.transforms.bronze_to_silver.faostat_production import standardize_country_name
    assert standardize_country_name("China, mainland") == "china,_mainland"
    assert standardize_country_name("Cote d'Ivoire") == "cote_divoire"
    assert standardize_country_name("Türkiye") == "turkiye"       # NFKD-folded, ASCII-only


# ─────────────────────────── query-side: name -> area IN filter ───────────────────────────

def test_named_country_emits_the_area_in_filter():
    sql = Q.build_sql(Q.NumberQuery(table="silver_production", metric="production_quantity",
                                    asof="2026-05-20", commodity="corn_cbot", country="United States",
                                    agg="latest"), _prod())
    assert "CAST(country AS varchar) IN ('United States of America')" in sql
    assert "country = 'United States'" not in sql       # never the string-mismatch plain equality


def test_apostrophe_area_is_quote_escaped():
    sql = Q.build_sql(Q.NumberQuery(table="silver_production", metric="production_quantity",
                                    asof="2026-05-20", commodity="cocoa", country="Ivory Coast",
                                    agg="latest"), _prod())
    assert "IN ('Côte d''Ivoire')" in sql          # doubled quote, the _q contract


def test_unresolved_country_fails_closed():
    sql = Q.build_sql(Q.NumberQuery(table="silver_production", metric="production_quantity",
                                    asof="2026-05-20", commodity="corn_cbot", country="Narnia",
                                    agg="sum"), _prod())
    assert "CAST(country AS varchar) IN ('__unresolved_destination__')" in sql   # zero rows, not the world


def test_unscoped_read_emits_no_country_filter():
    sql = Q.build_sql(Q.NumberQuery(table="silver_production", metric="production_quantity",
                                    asof="2026-05-20", commodity="corn_cbot", agg="latest"), _prod())
    assert "CAST(country AS varchar) IN" not in sql


_ROWS = [
    {"commodity": "corn_cbot", "country": "United States of America", "year": "2023",
     "metric": "production_quantity", "value": "389.7", "ingest_date": "2026-05-13"},
    {"commodity": "corn_cbot", "country": "China, mainland", "year": "2023",
     "metric": "production_quantity", "value": "288.8", "ingest_date": "2026-05-13"},
    {"commodity": "corn_cbot", "country": "World", "year": "2023",
     "metric": "production_quantity", "value": "1230.0", "ingest_date": "2026-05-13"},
]


def test_oracle_keeps_only_the_scoped_area():
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_production",
                                                   metric="production_quantity", asof="2026-05-20",
                                                   commodity="corn_cbot", country="United States"), _prod())
    assert [r["country"] for r in kept] == ["United States of America"]


def test_oracle_china_never_borrows_the_world_or_the_rollup():
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_production",
                                                   metric="production_quantity", asof="2026-05-20",
                                                   commodity="corn_cbot", country="China"), _prod())
    assert [r["country"] for r in kept] == ["China, mainland"]


def test_oracle_unresolved_keeps_none():
    kept = Q.apply_pit_filter(_ROWS, Q.NumberQuery(table="silver_production",
                                                   metric="production_quantity", asof="2026-05-20",
                                                   commodity="corn_cbot", country="Narnia"), _prod())
    assert kept == []                                   # fail-closed, never the World row


def test_post_fetch_render_leaves_the_faostat_string_alone():
    rows = [{"value": "389.7", "country": "United States of America"}]
    out = Q._apply_country_names(rows, Q.NumberQuery(table="silver_production",
                                                     metric="production_quantity", asof="2026-05-20"),
                                 _prod())
    assert out[0]["country"] == "United States of America"


# ─────────────────── the ref dispatch, and the semantic it stopped overloading ───────────────────

def test_unknown_country_name_ref_raises_rather_than_falling_back():
    """A card that declares a reference and silently gets the plain-equality path back is the exact
    zero-rows-narrated-as-a-figure failure the mechanism closes, so an unknown ref must be loud."""
    ts = _prod().model_copy(update={"country_name_ref": "numbers/not_a_reference.yaml"})
    with pytest.raises(ValueError, match="no loader in query._COUNTRY_REF_LOADERS serves"):
        Q._country_ref(ts)


def test_destination_coded_is_declared_not_inferred():
    """silver_esr's country axis enumerates BUYERS of one national flow; silver_production's enumerates
    REPORTING COUNTRIES of a world crop surface. Both now carry a country_name_ref, so the label rule
    can no longer read that key as the semantic."""
    reg = load_registry()
    assert reg.get("silver_esr").destination_coded() is True
    assert reg.get("silver_production").destination_coded() is False
    assert reg.get("silver_psd").destination_coded() is False       # no ref, no declaration -> free axis


def test_undeclared_card_with_a_ref_falls_back_to_the_silent_direction():
    """The None fallback is byte-identical to the pre-FAO-3 reading, so a card that gains a ref without
    declaring the semantic goes SILENT rather than mislabelling."""
    ts = _prod().model_copy(update={"country_axis_is_destination": None})
    assert ts.destination_coded() is True


# ─────────────────────────────── lint negative controls ───────────────────────────────

def _write(tmp_path, body, name="ref.yaml"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    load_faostat_areas.cache_clear()
    return str(p)


def test_lint_flags_duplicate_alias(tmp_path):
    path = _write(tmp_path, """
        version: 1
        areas:
          41: {name: "China, mainland", aliases: [china], pseudo: false, kind: country}
          351: {name: "China", aliases: [china], pseudo: true, kind: country_aggregate}
    """)
    assert any("maps to BOTH" in p for p in lint_reference(path))
    load_faostat_areas.cache_clear()


def test_lint_flags_pseudo_kind_inconsistency(tmp_path):
    path = _write(tmp_path, """
        version: 1
        areas:
          5000: {name: "World", aliases: [world], pseudo: false, kind: world}
    """)
    assert any("implies pseudo=true" in p for p in lint_reference(path))
    load_faostat_areas.cache_clear()


def test_lint_flags_unresolvable_member(tmp_path):
    path = _write(tmp_path, """
        version: 1
        areas:
          351: {name: "China", aliases: [china], pseudo: true, kind: country_aggregate, members: [41]}
    """)
    assert any("declares member 41" in p for p in lint_reference(path))
    load_faostat_areas.cache_clear()


def test_lint_flags_strict_schema_violation(tmp_path):
    # extra="forbid": a typoed/extra key must fail the load, not be silently dropped.
    path = _write(tmp_path, """
        version: 1
        areas:
          231: {name: "United States of America", aliases: [usa], pseudo: false, kind: country, typo: oops}
    """)
    probs = lint_reference(path)
    assert probs and "strict-schema parse" in probs[0]
    load_faostat_areas.cache_clear()                 # avoid leaking the tmp path to later tests
