"""CEC-W0 -- per-era failing goldens that PIN the SAGIS CEC scope/estimate defect.

Task #118, wave W0. These fixtures freeze the defect as executable, source-faithful
expectations BEFORE the era-aware parser exists (5ad4c0e6 discipline). There is NO
raw->bronze CEC parser in the tracked estate today (the on-S3 bronze was materialized
out-of-band by an untracked prototype -- CEC_PARSER_REPAIR_PLAN.md Section 0), so every
golden below currently RAISES ``ImportError`` on the not-yet-built entrypoint and is
marked ``xfail(strict=False)``. **W1 builds the parser and these flip to xpass** (strict
is False so a flipped golden never fails the suite mid-transition; W1 removes the marks).

Expected W1 entrypoint (Architecture D6=(a), raw->silver-direct):

    from leviathan.transforms.raw_to_bronze.sagis_cec import parse_cec_report
    obs: list[CecObservation] = parse_cec_report(raw_bytes, source_key)

emitting the existing ``CecObservation`` contract
(``leviathan.transforms.bronze_to_silver.sagis_cec.CecObservation``): production_year,
report_month, crop, scope, estimate_number, current_estimate_t, release_date, season_type,
area_planted_ha, source_format, source_key.

Ground truth provenance (all re-derived this session, W0):
  * PDF eras   -- extracted first-hand with pdfplumber (in-repo) from the committed fixture.
  * XLS era    -- extracted first-hand with xlrd/pandas (in-repo) from the committed fixture.
  * .doc eras  -- commercial figures extracted first-hand (olefile WordDocument text region,
                  8-bit cp1252) AND cross-checked against the report's own prose; developing
                  figures carried from the on-S3 bronze and cross-checked against the prose
                  hectare totals. Marked per assertion below.

The defect these goldens target (RATIFIED D1(c) / D2):
  * D1(c): keep {commercial, developing, total} with STRICT per-era vocabulary. The source
    prints the subsistence sector under DIFFERENT labels per era -- "Ontwikkelende landbou /
    Developing agriculture" (xls/old .doc) vs "Non-Commercial Maize / Nie-Kommersiele Mielies"
    (modern pdf/.doc) -- both canonicalize to scope=developing. The out-of-band bronze folded
    the whole subsistence sector into scope=commercial for 2007+ (developing rows = 0), and
    collapsed physically-distinct sector rows onto ONE natural key (61 conflict keys).
  * D2: estimate_number derived from release-date ordering; the printed ordinal ("FOURTH
    ESTIMATE", "eighth production forecast", "SECOND ESTIMATE") is parsed where present and
    cross-checked. The bronze's sentinel 99 (45.0% of rows) must be eliminated.
  * F3 (parse-time collapse invariant): physically-distinct sector rows must emit DISTINCT
    natural keys, never collapse.
  * F5 (release_date leakage): never impute a release_date EARLIER than true publication; the
    bronze imputed first-of-report-month (e.g. 2007-2024 all ``YYYY-MM-01``), an EARLY bound
    = PIT lookahead leak.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from leviathan.transforms.bronze_to_silver.sagis_cec import CecObservation

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sagis_cec"

# One representative REAL raw object per era signature (era census in the W0 handoff).
_PDF_MODERN = "CEC_2025-09.pdf"        # era D: PDF 2025-2026 (3-way maize collapse anchor)
_DOC_OLD = "CEC-2006-05-b-S.doc"       # era B: .doc 2005-2006, 8-bit (2-way maize collapse anchor)
_XLS = "CEC_2002_-_2005S.xls"          # era X: .xls 2002-2004 (developing-sector recovery)
_PDF_EARLY = "CEC-1999-10-20.pdf"      # era A: PDF 1999-2004 (winter cereals, total-only)

_W1 = "W1 builds leviathan.transforms.raw_to_bronze.sagis_cec.parse_cec_report; W0 pins the target"


def _parse(fixture: str) -> list[CecObservation]:
    """Call the W1 parser on a committed fixture. Raises ImportError until W1 lands (=> xfail)."""
    from leviathan.transforms.raw_to_bronze.sagis_cec import parse_cec_report  # noqa: PLC0415

    data = (_FIXTURES / fixture).read_bytes()
    return parse_cec_report(data, source_key=f"raw/production/source=sagis_cec/{fixture}")


def _one(obs: list[CecObservation], *, crop: str, scope: str) -> CecObservation:
    hits = [o for o in obs if o.crop == crop and o.scope == scope]
    assert len(hits) == 1, f"expected exactly one {crop}/{scope}, got {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------------------
# GREEN anchor: fixtures are present + intact (documents the era->format census).
# This is the only non-xfail test -- it proves the committed bytes are real raw
# objects of the claimed format, so every xfail below is attributable to the
# missing W1 parser, not a missing/corrupt fixture.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,magic", [
    (_PDF_MODERN, b"%PDF"),
    (_PDF_EARLY, b"%PDF"),
    (_DOC_OLD, b"\xd0\xcf\x11\xe0"),   # OLE compound file (.doc)
    (_XLS, b"\xd0\xcf\x11\xe0"),       # OLE compound file (.xls)
])
def test_era_fixtures_present_and_valid_magic(fixture: str, magic: bytes) -> None:
    data = (_FIXTURES / fixture).read_bytes()
    assert len(data) > 1024, f"{fixture} too small to be a real report"
    assert data.startswith(magic), f"{fixture} magic {data[:4]!r} != {magic!r}"


# ---------------------------------------------------------------------------
# W0 GOLDENS (xfail -> W1 flips). Each pins the CORRECT per-era parse.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason=_W1, strict=False)
def test_modern_pdf_maize_three_scopes_not_collapsed() -> None:
    """era D (CEC_2025-09.pdf): the 3-way collapse. Source prints THREE physical total_maize
    rows -- Commercial (16 178 500 t) / Non-Commercial (621 500 t) / RSA total (16 800 000 t) --
    which the bronze crammed onto ONE key (total_maize, commercial, est 8), n_distinct=3. The
    parser must emit THREE distinct scopes. All three values are source-hard (pdfplumber)."""
    obs = _parse(_PDF_MODERN)

    commercial = _one(obs, crop="total_maize", scope="commercial")
    developing = _one(obs, crop="total_maize", scope="developing")
    total = _one(obs, crop="total_maize", scope="total")

    assert commercial.current_estimate_t == 16_178_500
    assert developing.current_estimate_t == 621_500
    assert total.current_estimate_t == 16_800_000
    # structural invariant the source guarantees: total == commercial + developing.
    assert commercial.current_estimate_t + developing.current_estimate_t == total.current_estimate_t
    assert commercial.area_planted_ha == 2_596_700
    assert developing.area_planted_ha == 358_000

    # F3: three physical sector rows -> three DISTINCT emitted keys (no last-wins collapse).
    maize = [o for o in obs if o.crop == "total_maize"]
    assert {o.scope for o in maize} == {"commercial", "developing", "total"}

    # D2: real estimate number (8th forecast), NEVER the 99 sentinel.
    assert commercial.estimate_number == 8
    assert all(o.estimate_number != 99 for o in obs)

    # white/yellow commercial (source-hard cross-check).
    assert _one(obs, crop="white_maize", scope="commercial").current_estimate_t == 8_327_650
    assert _one(obs, crop="yellow_maize", scope="commercial").current_estimate_t == 7_850_850


@pytest.mark.xfail(reason=_W1, strict=False)
def test_old_doc_maize_two_scopes_not_collapsed() -> None:
    """era B (CEC-2006-05-b-S.doc): the 2-way collapse. White maize carries a Commercial row
    (3 615 650 t / 985 000 ha, ~3.67 t/ha) AND a Developing/subsistence row (238 426 t /
    345 881 ha, ~0.69 t/ha); the bronze tagged BOTH commercial+99 -> one key, n_distinct=2.
    Commercial figure is source-hard (olefile text region + prose 'white maize is 3,616 mill.
    tons'); developing figure is bronze-carried, cross-checked to the prose subsistence total
    (345 881 + 86 365 = 432 246 ha == prose 'subsistence agricultural sector ... 432 246 ha')."""
    obs = _parse(_DOC_OLD)

    commercial = _one(obs, crop="white_maize", scope="commercial")
    developing = _one(obs, crop="white_maize", scope="developing")

    assert commercial.current_estimate_t == 3_615_650   # source-hard
    assert commercial.area_planted_ha == 985_000         # source-hard
    assert developing.current_estimate_t == 238_426      # bronze-carried, prose-cross-checked
    assert developing.area_planted_ha == 345_881

    # the collapse-defeating invariant: two DISTINCT scopes, not two 'commercial' rows.
    assert commercial.scope != developing.scope

    # D2: 'FOURTH PRODUCTION ESTIMATE' -> 4, never sentinel 99.
    assert commercial.estimate_number == 4
    assert developing.estimate_number == 4
    assert all(o.estimate_number != 99 for o in obs)

    # yellow maize carries the same two-scope split (bronze-carried).
    assert _one(obs, crop="yellow_maize", scope="commercial").current_estimate_t == 2_387_275
    assert _one(obs, crop="yellow_maize", scope="developing").current_estimate_t == 78_630


@pytest.mark.xfail(reason=_W1, strict=False)
def test_xls_era_developing_sector_recovered() -> None:
    """era X (CEC_2002_-_2005S.xls): the developing sector the modern bronze dropped is EXPLICIT
    here under 'Ontwikkelende landbou / Developing agriculture'. All values source-hard (xlrd).
    total maize == commercial maize + developing maize (8 594 680 + 317 134 == 8 911 814)."""
    obs = _parse(_XLS)

    commercial = _one(obs, crop="total_maize", scope="commercial")
    developing = _one(obs, crop="total_maize", scope="developing")
    total = _one(obs, crop="total_maize", scope="total")

    assert commercial.current_estimate_t == 8_594_680
    assert developing.current_estimate_t == 317_134
    assert total.current_estimate_t == 8_911_814
    assert commercial.current_estimate_t + developing.current_estimate_t == total.current_estimate_t

    # per-crop developing recovery (source-hard).
    assert _one(obs, crop="white_maize", scope="commercial").current_estimate_t == 4_966_780
    assert _one(obs, crop="white_maize", scope="developing").current_estimate_t == 245_119

    # D2: 'FOURTH PRODUCTION ESTIMATE OF SUMMER CROPS: 2001/02' -> 4; season end-year -> 2002.
    assert commercial.estimate_number == 4
    assert commercial.production_year == 2002
    # F5: the source PRINTS '20 Mei/May 2002' -> exact, no imputation.
    assert commercial.release_date == "2002-05-20"


@pytest.mark.xfail(reason=_W1, strict=False)
def test_early_pdf_winter_cereals_total_only() -> None:
    """era A (CEC-1999-10-20.pdf): winter cereals (wheat/barley/canola) have NO developing
    sector -- the source prints only 'TOTAAL / TOTAL RSA'. Wheat total is source-hard
    (pdfplumber: 'TOTAAL / TOTAL RSA 718 000 1 581 000 ...'). scope must be 'total', and the
    winter block must NOT mint a spurious commercial/developing split."""
    obs = _parse(_PDF_EARLY)

    wheat = _one(obs, crop="wheat", scope="total")
    assert wheat.current_estimate_t == 1_581_000     # source-hard (2nd estimate)
    assert wheat.area_planted_ha == 718_000

    # winter cereal => only the 'total' scope exists for wheat (no developing sector).
    assert {o.scope for o in obs if o.crop == "wheat"} == {"total"}

    # D2: 'SECOND PRODUCTION ESTIMATE OF WINTER CROPS' -> 2, never sentinel 99.
    assert wheat.estimate_number == 2
    assert all(o.estimate_number != 99 for o in obs)
    # F5: the source PRINTS 'as at 20 October 1999' -> exact, no imputation.
    assert wheat.release_date == "1999-10-20"


@pytest.mark.xfail(reason=_W1, strict=False)
def test_only_canonical_scopes_emitted_strict_vocabulary() -> None:
    """D1(c): the parser canonicalizes every era's sector label into exactly
    {commercial, developing, total}. No raw Afrikaans/English source label
    ('Kommersieel', 'Ontwikkelende landbou', 'Non-Commercial', 'RSA') leaks through as a scope
    value. (An era signature or label outside the ratified set must fail-closed / quarantine in
    W1; here we assert the positive: only canonical scopes reach the observations.)"""
    allowed = {"commercial", "developing", "total"}
    for fixture in (_PDF_MODERN, _DOC_OLD, _XLS, _PDF_EARLY):
        obs = _parse(fixture)
        bad = {o.scope for o in obs} - allowed
        assert not bad, f"{fixture} leaked non-canonical scope labels: {bad}"


@pytest.mark.xfail(reason=_W1, strict=False)
def test_no_release_date_precedes_source_publication() -> None:
    """F5 / D2b: no imputed release_date precedes the source's true publication. For the two
    fixtures whose source PRINTS the meeting date, the parsed release_date equals it exactly.
    (The out-of-band bronze imputed first-of-report-month, e.g. 2007-2024 all 'YYYY-MM-01' --
    an EARLY bound and a PIT lookahead leak; W1/D2b must impute a conservative LATE bound
    (end-of-report-month class) or quarantine, never an early one.)"""
    early = _parse(_PDF_EARLY)
    assert all(o.release_date >= "1999-10-20" for o in early if o.release_date)
    assert _one(early, crop="wheat", scope="total").release_date == "1999-10-20"

    xls = _parse(_XLS)
    assert all(o.release_date >= "2002-05-20" for o in xls if o.release_date)
