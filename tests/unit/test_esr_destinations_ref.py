"""ESR destination code<->name reference (ESR_DESTINATION_PLAN W0) — loader, lint, and the folded
skeptic findings (S2 str-key reconciliation; W2.2 double-count verdict pinned in the YAML audit block).

AWS-free: exercises the committed configs/graphrag/numbers/esr_destinations.yaml + the standalone loader.
The double-count audit itself (jobs/utils/esr_double_count_audit.py) reads S3 and is run as a gate, not
here; this file pins the VERDICT it produced into the reference so a regeneration cannot silently flip it.
"""
from __future__ import annotations

import textwrap

import pytest
from leviathan.graphrag.numbers.esr_destinations import (
    lint_reference,
    load_esr_destinations,
    missing_codes,
)

# ─────────────────────────────── the committed reference ───────────────────────────────

def test_committed_reference_loads_and_is_lint_clean():
    assert lint_reference() == []                       # guard cross-seed + alias uniqueness + pseudo/kind
    d = load_esr_destinations()
    assert len(d.code_to_name) == 211                   # full FAS reference, superset of the 178 data codes
    assert len(d.pseudo_codes) == 6


def test_every_guard_destination_resolves():
    """§5.1 lint core: every display name in agent._ESR_DESTINATIONS must map to a code."""
    from leviathan.graphrag.numbers.agent import _ESR_DESTINATIONS
    d = load_esr_destinations()
    for disp, names, dems in _ESR_DESTINATIONS:
        forms = [disp, *names, *dems]
        assert any(d.resolve_codes(f) for f in forms), f"{disp!r} resolves to nothing"


@pytest.mark.parametrize("name,code", [
    ("China", "5700"), ("chinese", "5700"), ("  SOUTH KOREA ", "5800"), ("korean", "5800"),
    ("Vietnam", "5520"),          # modern, NOT the former-South 5510
    ("the Netherlands", "4210"),  # NOT Netherlands Antilles 2770
    ("India", "5330"),            # NOT British Indian Ocean Territory 7810
    ("Germany", "4280"),          # NOT the former German DR 4290
    ("the EU", "1"),
])
def test_resolve_hits_the_modern_code(name, code):
    assert load_esr_destinations().resolve_codes(name) == [code]


def test_resolve_fail_closed_and_national_path():
    d = load_esr_destinations()
    assert d.resolve_codes("Narnia") == []              # unresolved -> caller fails CLOSED (never national)
    assert d.resolve_codes("") == []                    # national path (no destination filter)
    assert d.resolve_codes(None) == []


# ─────────────────────────── S2: int-key YAML / string-value row ───────────────────────────

def test_display_str_normalizes_the_row_code():
    """Folded S2: the row's country_code is a STRING on both backends; the YAML keys ints. display()
    must resolve the STRING '1220' off the int-keyed reference (parity can't see this label)."""
    d = load_esr_destinations()
    assert d.display("1220") == "Canada"                # VarCharValue / _stringify contract
    assert d.display(1220) == "Canada"                  # int also works (symmetry)
    assert d.display("5700") == "China"
    assert d.display(9990) == "Unknown"


def test_display_unmapped_code_falls_back_to_bare_string():
    assert load_esr_destinations().display(99999) == "99999"   # never raises; lint makes real gaps hard-fail


# ─────────────────────────────── pseudo / aggregate honesty ───────────────────────────────

def test_pseudo_classification():
    d = load_esr_destinations()
    assert {c for c in d.pseudo_codes} == {"1", "4461", "5680", "6860", "7640", "9990"}
    assert d.is_pseudo(9990) and d.is_pseudo("4461")
    assert not d.is_pseudo(5700) and not d.is_pseudo("2010")
    assert d.kind("1") == "bloc" and d.kind("9990") == "unknown" and d.kind("5680") == "region_nec"
    assert d.kind("5700") == "country"


def test_double_count_verdict_pinned_none():
    """W2.2 verdict pinned into the YAML audit block: national agg=sum does NOT double-count, so no
    exclusion codes today; the two blocs are the watch list only."""
    d = load_esr_destinations()
    assert d.national_exclusion_codes == ()             # W2.4 NOT triggered
    assert d.bloc_watch_codes == ("1", "4461")


def test_missing_codes_coverage():
    d = load_esr_destinations()
    present = list(d.code_to_name)[:5]
    assert missing_codes(present) == []                 # all mapped
    assert missing_codes([*present, 424242]) == ["424242"]   # a probe code absent from the reference


# ─────────────────────────────── lint negative controls ───────────────────────────────

def _write(tmp_path, body, name="ref.yaml"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    load_esr_destinations.cache_clear()
    return str(p)


def test_lint_flags_duplicate_alias(tmp_path):
    path = _write(tmp_path, """
        version: 1
        codes:
          5700: {name: China, aliases: [china], pseudo: false, kind: country}
          2010: {name: Mexico, aliases: [china], pseudo: false, kind: country}
    """)
    probs = lint_reference(path)
    assert any("maps to BOTH" in p for p in probs)


def test_lint_flags_unresolved_guard_destination(tmp_path):
    # a reference missing China (and everything else) -> the guard cross-seed check fires.
    path = _write(tmp_path, """
        version: 1
        codes:
          9990: {name: Unknown, aliases: [unknown], pseudo: true, kind: unknown}
    """)
    probs = lint_reference(path)
    assert any("China" in p and "resolves to NO code" in p for p in probs)


def test_lint_flags_pseudo_kind_inconsistency(tmp_path):
    path = _write(tmp_path, """
        version: 1
        codes:
          5700: {name: China, aliases: [china], pseudo: true, kind: country}
    """)
    probs = lint_reference(path)
    assert any("pseudo=true but kind='country'" in p for p in probs)


def test_lint_flags_strict_schema_violation(tmp_path):
    # extra="forbid": a typoed/extra key must fail the load, not be silently dropped.
    path = _write(tmp_path, """
        version: 1
        codes:
          5700: {name: China, aliases: [china], pseudo: false, kind: country, typo_key: oops}
    """)
    probs = lint_reference(path)
    assert probs and "strict-schema parse" in probs[0]
    load_esr_destinations.cache_clear()                 # avoid leaking the tmp path to later tests


# ─────────────────────────── producers: fetch + audit modules import cleanly ───────────────────────────

def test_fetch_module_raw_key_shape():
    from jobs.ingest.fetch_usda_esr_countries import raw_countries_key
    assert raw_countries_key("20260723") == "raw/reference/source=usda_esr/countries/as_of=20260723/countries.json"


def test_audit_region_member_grouping():
    from jobs.utils.esr_double_count_audit import _region_members
    rows = [{"countryCode": 4461, "regionId": 4}, {"countryCode": 4621, "regionId": 4},
            {"countryCode": 5700, "regionId": 9}]
    m = _region_members(rows)
    assert m[4] == {4461, 4621} and m[9] == {5700}
