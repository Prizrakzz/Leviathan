"""CEC W1 -- unit tests for the era-aware parser's classifiers, fail-closed paths, and D2 machinery.

Task #118, wave W1. The end-to-end golden parse of the real raw fixtures lives in
``test_transforms_sagis_cec_parser.py``; THIS file whiteboxes every discrete rule so a regression is
attributed to the exact classifier/guard, not a whole-report diff:

  * ``classify_sector`` -- D1(c) STRICT per-era vocabulary (Non-Commercial -> developing, not
    commercial; the combined "+" descriptor is not a header; an unknown label is not a scope).
  * ``classify_crop`` -- maize disambiguation (white/yellow before the subtotal; RSA / pre-2007
    "Totaal mielies" -> grand-total; modern "Total Maize" without RSA -> per-sector subtotal),
    winter cereals, the all-crop total skip, and the unknown-crop path.
  * estimate ordinal + release_date + season-year parsing (incl. the "8043/32" phone false positive
    and the D2b conservative-late month bound).
  * the fail-closed paths: unknown magic bytes (:class:`CecEraError`), the F3 parse-time collapse
    detector (:class:`CecCollapseError`), and the three quarantine reasons.
  * :func:`reconcile_estimate_numbers` -- D2 release-date derivation, printed cross-check
    (fail-closed on a release-date-vs-printed order mismatch), and the D2a deterministic tie-break.
  * ``extract_doc_text`` -- the cp1252 (old) and UTF-16LE-fast-save (modern) piece-table paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from leviathan.transforms.bronze_to_silver.sagis_cec import CecObservation
from leviathan.transforms.raw_to_bronze import sagis_cec as P

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sagis_cec"


# --------------------------------------------------------------------------- #
# classify_sector -- D1(c) strict per-era vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,era,expected", [
    ("Kommersieel / Commercial:", P.ERA_OLD_DOC, "commercial"),
    ("Bestaanslandbou / Subsistence agriculture:", P.ERA_OLD_DOC, "developing"),
    ("Ontwikkelende landbou / Developing agriculture :", P.ERA_XLS, "developing"),
    ("Commercial/Kommersie�l:", P.ERA_MODERN_PDF, "commercial"),
    # the critical ordering: "Non-Commercial" contains "Commercial" but must resolve to developing.
    ("Non-Commercial Maize/Nie-Kommersi�le Mielies", P.ERA_MODERN_PDF, "developing"),
    ("Nie-Kommersiele Mielies", P.ERA_MODERN_DOC, "developing"),
    # pre-2007 vocabulary does NOT recognise the modern "Non-Commercial" label (strict per-era set).
    ("Non-Commercial Maize", P.ERA_OLD_DOC, None),
    # the combined descriptor line is not a pure header.
    ("Maize/Mielies: Commercial + Non-Commercial", P.ERA_MODERN_PDF, None),
    ("White maize/Witmielies", P.ERA_MODERN_PDF, None),
    ("", P.ERA_XLS, None),
])
def test_classify_sector(label, era, expected):
    assert P.classify_sector(label, era) == expected


# --------------------------------------------------------------------------- #
# classify_crop -- maize disambiguation + winter cereals + total lines
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,era,crop,kind", [
    ("Witmielies / White Maize", P.ERA_XLS, "white_maize", P._CROP_ROW),
    ("White maize/Witmielies", P.ERA_MODERN_PDF, "white_maize", P._CROP_ROW),
    ("Geelmielies/Yellow maize", P.ERA_OLD_DOC, "yellow_maize", P._CROP_ROW),
    # per-sector subtotal
    ("Mielies / Maize", P.ERA_XLS, "total_maize", P._CROP_ROW),
    ("Total Maize/Totale Mielies", P.ERA_MODERN_PDF, "total_maize", P._CROP_ROW),  # modern, no RSA
    # grand totals
    ("Total Maize RSA/Totaal Mielies RSA", P.ERA_MODERN_PDF, "total_maize", P._CROP_GRAND),
    ("Totaal mielies / Total maize", P.ERA_XLS, "total_maize", P._CROP_GRAND),     # pre-2007 grand
    # winter cereals
    ("KORING", P.ERA_EARLY_PDF, "wheat", P._CROP_ROW),
    ("Barley/Gars", P.ERA_MODERN_DOC, "barley", P._CROP_ROW),
    ("Kanola/Canola", P.ERA_MODERN_DOC, "canola", P._CROP_ROW),
    # non-maize summer crops
    ("Sonneblomsaad/Sunflower seed", P.ERA_OLD_DOC, "sunflower_seed", P._CROP_ROW),
    ("Sojabone/Soya-beans", P.ERA_OLD_DOC, "soybeans", P._CROP_ROW),
    ("Dro�bone / Dry beans", P.ERA_OLD_DOC, "dry_beans", P._CROP_ROW),
    # the all-crop total is not a crop
    ("TOTAL/TOTAAL", P.ERA_MODERN_PDF, None, P._CROP_ALLCROP_TOTAL),
    # an unrecognised crop with data must be quarantined, not guessed
    ("Frobnicate seed/Frobbing", P.ERA_XLS, None, P._CROP_UNKNOWN),
])
def test_classify_crop(label, era, crop, kind):
    assert P.classify_crop(label, era) == (crop, kind)


def test_classify_crop_modern_total_maize_needs_rsa_for_grand():
    # The modern per-sector subtotal "Total Maize" (no RSA) must NOT be read as the grand total,
    # else the commercial and developing subtotals would both collapse onto scope=total.
    assert P.classify_crop("Total Maize", P.ERA_MODERN_PDF)[1] == P._CROP_ROW
    assert P.classify_crop("Total Maize RSA", P.ERA_MODERN_PDF)[1] == P._CROP_GRAND


# --------------------------------------------------------------------------- #
# estimate ordinal + release_date + season year
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("FOURTH PRODUCTION ESTIMATE OF SUMMER CROPS", 4),
    ("the eighth production forecast for summer crops", 8),
    ("SECOND PRODUCTION ESTIMATE OF WINTER CROPS", 2),
    ("VIERDE PRODUKSIESKATTING VAN SOMERGEWASSE", 4),
    ("AGTSTE PRODUKSIESKATTING", 8),
    # an ordinal NOT adjacent to an estimate keyword is ignored
    ("the second largest province by area planted", None),
    ("area planted report, no numbered estimate here", None),
])
def test_parse_estimate_ordinal(text, expected):
    assert P.parse_estimate_ordinal(text) == expected


def test_parse_estimate_ordinal_season_disambiguates_combined_report():
    # cec-w23: a COMBINED report prints a winter-final ordinal EARLIER in the text than the summer
    # title (e.g. the Feb release = winter crops' 5th/final + summer crops' 1st). With no season the
    # earliest estimate-adjacent ordinal wins (the winter 5) and bleeds onto the emitted summer rows;
    # with the emitted season passed, the season-NAMED title ordinal is preferred.
    txt = ("Fifth production estimate of winter crops for the 1999/2000 season, tons and area planted. "
           "First production estimate of summer crops: 1999/2000 season.")
    assert P.parse_estimate_ordinal(txt) == 5                     # legacy: earliest estimate-adjacent
    assert P.parse_estimate_ordinal(txt, season="summer") == 1    # summer-named title wins
    assert P.parse_estimate_ordinal(txt, season="winter") == 5    # winter-named title wins


def test_parse_estimate_ordinal_season_falls_back_when_no_season_word():
    # Modern single-season reports name no crop-season next to the ordinal ("EIGHTH PRODUCTION
    # FORECAST: 2025"); a season hint must NOT suppress them -- the fallback keeps the printed number.
    assert P.parse_estimate_ordinal("EIGHTH PRODUCTION FORECAST: 2025", season="summer") == 8
    assert P.parse_estimate_ordinal("EIGHTH PRODUCTION FORECAST: 2025", season=None) == 8


# --------------------------------------------------------------------------- #
# _resolve_estimate_ordinal -- title-anchored attribution + transition quarantine (cec-w23)
# --------------------------------------------------------------------------- #
def _resolve(text, season="summer", py=2020, era=P.ERA_MODERN_DOC):
    return P._resolve_estimate_ordinal(era, "k", text, season, py)


def test_resolve_prefers_season_named_year_matching_title():
    # the Feb combined release: winter-final "fifth" prints EARLIER than the summer "first".
    txt = ("Fifth production estimate of winter crops for the 1999/2000 season, tons. "
           "First production estimate of summer crops: 1999/2000 season.")
    assert _resolve(txt, "summer", 2000) == 1
    assert _resolve(txt, "winter", 2000) == 5


def test_resolve_quarantines_summer_title_year_conflict():
    # the October combined intentions+final matrix: the only summer title prints the CLOSING season
    # (2019) while the derived production_year is the intentions season (2020) -> quarantine, never
    # stamp the 9th-final ordinal onto next season's series (the printed-9-at-rank-1 signature).
    txt = "Ninth production forecast for summer crops for 2019 is hereby released."
    with pytest.raises(P.CecNotImplementedEra):
        _resolve(txt, "summer", 2020)
    assert _resolve(txt, "summer", 2019) == 9      # same title, right year -> clean


def test_resolve_quarantines_other_season_ordinal_only():
    # the Oct/Nov area-revision layout: emitted summer matrix has NO ordinal of its own; only the
    # winter-cereal data title is numbered. Inheriting the winter ordinal was the original defect.
    txt = ("Revised area planted of summer crops: 2020/21 season. "
           "Fourth production forecast for winter cereals for the 2020 season is hereby released.")
    with pytest.raises(P.CecNotImplementedEra):
        _resolve(txt, "summer", 2021)


def test_resolve_notice_never_rescues_transition_release():
    # a future-schedule NOTICE ("the first production forecast ... WILL BE RELEASED on ...") is not
    # a data title: the Jan area-revision doc must still quarantine, not borrow the notice's "1".
    txt = ("Revised area planted of summer crops: 2012/13 season. "
           "Sixth production forecast for winter cereals for the 2012 season is hereby released. "
           "The first production forecast for summer crops for 2013 will be released on 29 January.")
    with pytest.raises(P.CecNotImplementedEra):
        _resolve(txt, "summer", 2013)


def test_resolve_unnamed_pair_year_headers_rescue():
    # the Sep 2004/05-FINAL: cover title is the unnumbered "FINALE", but the matrix's own column
    # headers print "seventh estimate 2004/05" -- the PAIR-form year matching production_year is
    # positive evidence and beats the other-season quarantine.
    txt = ("Finale produksieskatting van somergewasse. "
           "Sewende skatting/ seventh estimate 2004/05 tons. "
           "Second production forecast of winter crops is hereby released.")
    assert _resolve(txt, "summer", 2005) == 7


def test_resolve_bare_year_headers_do_not_rescue():
    # a winter title's BARE calendar year ("second ... forecast: 2010 production season") collides
    # with the summer production_year -- bare-year evidence must NOT rescue (the Sep-2010 signature;
    # the un-season-named variant of the winter title must not be mistaken for summer evidence).
    txt = ("Revised area planted of summer crops. "
           "Second production forecast: 2010 production season, wheat and barley tables. "
           "Second production forecast of winter cereals for the 2010 season is hereby released.")
    with pytest.raises(P.CecNotImplementedEra):
        _resolve(txt, "summer", 2010)


def test_resolve_early_pdf_dual_summer_years_quarantines():
    # the January dual-summer layout under the EARLY-PDF reader (per-crop province tables): titles
    # for TWO summer season-years -- the reader cannot prove which season's table it walked.
    txt = ("Sixth production estimate of summer crops: 2007/08 season. "
           "First production forecast of summer crops: 2008/09 season.")
    with pytest.raises(P.CecNotImplementedEra):
        _resolve(txt, "summer", 2009, era=P.ERA_EARLY_PDF)
    # the modern readers take the FIRST summary matrix (the current-season release) -- no quarantine.
    assert _resolve(txt, "summer", 2009, era=P.ERA_MODERN_DOC) == 1


def test_crop_season_mismatch_guard():
    # a wheat row inside a summer-attributed matrix belongs to the OTHER season's section of a
    # transition release: quarantined per-row, never emitted under the summer meta.
    assert P._crop_season_mismatch("wheat", "summer")
    assert P._crop_season_mismatch("total_maize", "winter")
    assert not P._crop_season_mismatch("wheat", "winter")
    assert not P._crop_season_mismatch("total_maize", "summer")
    assert not P._crop_season_mismatch("wheat", None)


def test_emit_summary_rows_quarantines_cross_season_row():
    rows = [
        ("Kommersieel / Commercial:", []),
        ("Witmielies/White Maize", [985_000.0, 3_615_650.0]),
        ("Koring/Wheat", [700_000.0, 2_000_000.0]),   # winter cereal in a summer matrix
    ]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)      # _meta() is season_type="summer"
    assert [(o.crop, o.scope) for o in result.observations] == [("white_maize", "commercial")]
    assert [q.reason for q in result.quarantined] == ["crop_season_mismatch"]


@pytest.mark.parametrize("text,expected", [
    ("20 October 1999", "1999-10-20"),
    ("30 September 2025", "2025-09-30"),
    ("20 Mei/ May 2002", "2002-05-20"),          # bilingual, English resolves
    ("23 May / Mei 2006", "2006-05-23"),
    ("Estimates are based on conditions as at 20 May 2002.", "2002-05-20"),
    ("no date printed here", None),
])
def test_parse_release_date(text, expected):
    assert P.parse_release_date(text) == expected


def test_parse_release_date_prefers_as_at_meeting_date():
    # "as at / soos op" wins over a stray later date on the page.
    txt = "EMBARGO 14:30 on 05 May 2006. Estimates are based on conditions as at 23 May 2006."
    assert P.parse_release_date(txt) == "2006-05-23"


@pytest.mark.parametrize("text,expected", [
    ("SUMMER CROPS: 2001/02 SEASON", 2002),
    ("WINTER CROPS: 1999/2000 SEASON", 2000),
    ("SOMERGEWASSE: 2005/06-SEISOEN", 2006),
    ("EIGHTH PRODUCTION FORECAST: 2025", 2025),
    # the "012 319 8043/32" phone number must NOT be read as a 8043/32 season.
    ("Tel: 012 319 8043/32 E-mail", None),
])
def test_expand_season_end_year(text, expected):
    assert P._expand_season_end_year(text) == expected


def test_end_of_month_conservative_late_bound():
    # D2b: an un-dated report is bounded to the LAST day of its report month (defers PIT eligibility).
    assert P._end_of_month(2020, 2) == "2020-02-29"   # leap year
    assert P._end_of_month(2021, 2) == "2021-02-28"
    assert P._end_of_month(2025, 9) == "2025-09-30"


def test_is_province():
    assert P._is_province("Free State/Vrystaat")
    assert P._is_province("KwaZulu-Natal")
    assert P._is_province("North West/Noordwes")
    assert not P._is_province("White maize/Witmielies")
    assert not P._is_province("Total Maize RSA")


# --------------------------------------------------------------------------- #
# era detection -- fail closed on unknown bytes
# --------------------------------------------------------------------------- #
def test_detect_era_unknown_magic_fails_closed():
    with pytest.raises(P.CecEraError):
        P.detect_era(b"this is not a pdf or an ole file at all, just text", "k")


def test_detect_era_real_fixtures():
    cases = {
        "CEC_2025-09.pdf": P.ERA_MODERN_PDF,
        "CEC-1999-10-20.pdf": P.ERA_EARLY_PDF,
        "CEC-2006-05-b-S.doc": P.ERA_OLD_DOC,
        "CEC-2024-05-b.doc": P.ERA_MODERN_DOC,
        "CEC_2002_-_2005S.xls": P.ERA_XLS,
    }
    for fixture, era in cases.items():
        data = (_FIXTURES / fixture).read_bytes()
        assert P.detect_era(data, fixture) == era


# --------------------------------------------------------------------------- #
# _emit_summary_rows -- F3 collapse detector + quarantine reasons
# --------------------------------------------------------------------------- #
def _meta(era=P.ERA_OLD_DOC):
    return P._ReportMeta(
        era=era, source_key="raw/.../k", production_year=2006, report_month=5,
        estimate_number=4, release_date="2006-05-23", season_type="summer", source_format="doc")


def test_collapse_detector_raises_on_two_physical_rows_one_key():
    # F3: two physical "white maize" rows under one section collapse onto (white_maize, commercial).
    # This is the detector the transform's post-selection duplicated() guard structurally cannot be
    # (it always runs on the already-collapsed by_key.values()), and it fires even for UNEQUAL rank.
    rows = [
        ("Kommersieel / Commercial:", []),
        ("Witmielies/White Maize", [985_000.0, 3_615_650.0]),
        ("Witmielies/White Maize", [1.0, 2.0]),
    ]
    with pytest.raises(P.CecCollapseError):
        P._emit_summary_rows(rows, _meta(), P.CecParseResult())


def test_distinct_scopes_do_not_collapse():
    rows = [
        ("Kommersieel / Commercial:", []),
        ("Mielies/Maize", [100.0, 200.0]),
        ("Bestaanslandbou / Subsistence agriculture:", []),
        ("Mielies/Maize", [10.0, 20.0]),
    ]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)
    keys = {(o.crop, o.scope) for o in result.observations}
    assert keys == {("total_maize", "commercial"), ("total_maize", "developing")}


def test_grand_total_line_is_total_scope_and_resets_to_commercial():
    # The pre-2007 grand-total maize line emits scope=total; the trailing non-maize crops resume
    # the commercial sector (they follow the maize block in the pre-2007 layout).
    rows = [
        ("Kommersieel / Commercial:", []),
        ("Mielies/Maize", [100.0, 200.0]),
        ("Bestaanslandbou / Subsistence agriculture:", []),
        ("Mielies/Maize", [10.0, 20.0]),
        ("Totaal mielies / Total maize", [110.0, 220.0]),
        ("Sorghum", [5.0, 6.0]),
    ]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)
    by = {(o.crop, o.scope): o for o in result.observations}
    assert by[("total_maize", "total")].current_estimate_t == 220.0
    assert ("sorghum", "commercial") in by      # resumed commercial after the grand total


def test_quarantine_unknown_crop_with_data():
    rows = [("Kommersieel / Commercial:", []), ("Frobnicate/Frobbing", [1.0, 2.0])]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)
    assert not result.observations
    assert [q.reason for q in result.quarantined] == ["unknown_crop_with_data"]


def test_quarantine_unrecognised_sector_header_then_rows_without_scope():
    # An unrecognised colon-terminated sector header quarantines, and the rows beneath it are
    # quarantined per-row (never inherit / guess a scope) -- D1(c) fail-closed.
    rows = [
        ("Nuwe sektor landbou:", []),           # unknown sector, colon-terminated header shape
        ("Witmielies/White Maize", [1.0, 2.0]),
    ]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)
    assert not result.observations
    reasons = [q.reason for q in result.quarantined]
    assert "unrecognised_sector_header" in reasons
    assert "crop_row_without_scope" in reasons


def test_preamble_rows_before_any_section_are_skipped_not_quarantined():
    rows = [("CROP ESTIMATES COMMITTEE", [1.0]), ("Kommersieel / Commercial:", []),
            ("Witmielies/White Maize", [985_000.0, 3_615_650.0])]
    result = P.CecParseResult()
    P._emit_summary_rows(rows, _meta(), result)
    assert not result.quarantined
    assert result.observations[0].crop == "white_maize"


# --------------------------------------------------------------------------- #
# reconcile_estimate_numbers -- D2 / D2a
# --------------------------------------------------------------------------- #
def _obs(py, rel, sk, est, crop="total_maize", scope="total"):
    return CecObservation(production_year=py, report_month=5, crop=crop, scope=scope,
                          estimate_number=est, current_estimate_t=1.0, release_date=rel, source_key=sk)


def test_reconcile_fills_unresolved_from_release_date_rank():
    grp = [_obs(2020, "2020-08-20", "c", P.ESTIMATE_UNRESOLVED),
           _obs(2020, "2020-02-20", "a", P.ESTIMATE_UNRESOLVED),
           _obs(2020, "2020-05-20", "b", P.ESTIMATE_UNRESOLVED)]
    got = {o.source_key: o.estimate_number for o in P.reconcile_estimate_numbers(grp)}
    assert got == {"a": 1, "b": 2, "c": 3}


def test_reconcile_printed_monotonic_passes():
    grp = [_obs(2021, "2021-02-20", "a", 1), _obs(2021, "2021-05-20", "b", 2)]
    nums = sorted(o.estimate_number for o in P.reconcile_estimate_numbers(grp))
    assert nums == [1, 2]


def test_reconcile_printed_contradiction_fails_closed():
    # A strictly-later release carrying a strictly-lower printed estimate number is a D2 mismatch.
    grp = [_obs(2022, "2022-02-20", "a", 5), _obs(2022, "2022-05-20", "b", 3)]
    with pytest.raises(P.CecEstimateError):
        P.reconcile_estimate_numbers(grp)


def test_reconcile_reports_all_contradictions_not_just_first():
    # collect-and-report-all: two INDEPENDENT groups each invert; the single raised error must name
    # BOTH (so a corpus dry-run surfaces the full defect set in one pass), and still fail closed.
    grp = [
        _obs(2022, "2022-02-20", "a", 5, crop="white_maize"),
        _obs(2022, "2022-05-20", "b", 3, crop="white_maize"),
        _obs(2022, "2022-02-20", "c", 4, crop="yellow_maize"),
        _obs(2022, "2022-05-20", "d", 2, crop="yellow_maize"),
    ]
    with pytest.raises(P.CecEstimateError) as ei:
        P.reconcile_estimate_numbers(grp)
    msg = str(ei.value)
    assert "2 estimate_number contradiction" in msg
    assert "white_maize" in msg and "yellow_maize" in msg
    # deterministic order (sorted by group key) regardless of input order.
    with pytest.raises(P.CecEstimateError) as ei2:
        P.reconcile_estimate_numbers(list(reversed(grp)))
    assert str(ei2.value) == msg


def test_reconcile_tiebreak_is_deterministic_on_source_key():
    # D2a: equal release_date (renamed-duplicate raw) -> ordered by source_key, byte-identical on
    # re-runs regardless of input order.
    a = [_obs(2023, "2023-05-20", "z", P.ESTIMATE_UNRESOLVED),
         _obs(2023, "2023-05-20", "a", P.ESTIMATE_UNRESOLVED)]
    r1 = {o.source_key: o.estimate_number for o in P.reconcile_estimate_numbers(a)}
    r2 = {o.source_key: o.estimate_number for o in P.reconcile_estimate_numbers(list(reversed(a)))}
    assert r1 == r2 == {"a": 1, "z": 2}


def test_reconcile_groups_independently_by_crop_scope():
    grp = [_obs(2020, "2020-05-20", "a", P.ESTIMATE_UNRESOLVED, crop="white_maize", scope="commercial"),
           _obs(2020, "2020-05-20", "b", P.ESTIMATE_UNRESOLVED, crop="yellow_maize", scope="commercial")]
    got = P.reconcile_estimate_numbers(grp)
    # each (crop, scope) group is ranked on its own -> both are the 1st estimate of their series.
    assert all(o.estimate_number == 1 for o in got)


# --------------------------------------------------------------------------- #
# extract_doc_text -- cp1252 (old) and UTF-16LE fast-save (modern) piece-table paths
# --------------------------------------------------------------------------- #
def test_extract_doc_text_old_cp1252():
    text = P.extract_doc_text((_FIXTURES / "CEC-2006-05-b-S.doc").read_bytes())
    low = P._fold(text)
    assert "bestaanslandbou" in low and "witmielies" in low
    assert "\x07" in text          # table cells preserved for deterministic splitting


def test_extract_doc_text_modern_utf16_fastsave():
    # The mixed-encoding CLX (UTF-16 cover page + cp1252 tables) must yield the crop matrix; a naive
    # single-encoding FIB-region read drops the tables entirely.
    text = P.extract_doc_text((_FIXTURES / "CEC-2024-05-b.doc").read_bytes())
    low = P._fold(text)
    assert "kommersieel" in low or "commercial" in low
    assert "mielies" in low
    assert "\x07" in text


def test_looks_utf16le_discriminates_the_two_docs():
    import io as _io
    import struct as _struct

    import olefile

    def wd_ccp(fixture):
        data = (_FIXTURES / fixture).read_bytes()
        ole = olefile.OleFileIO(_io.BytesIO(data))
        wd = ole.openstream("WordDocument").read()
        ole.close()
        fc_min = _struct.unpack_from("<II", wd, 0x18)[0]
        ccp = _struct.unpack_from("<I", wd, 0x4C)[0]
        return wd, fc_min, ccp

    wd_old, fc_old, ccp_old = wd_ccp("CEC-2006-05-b-S.doc")
    wd_new, fc_new, ccp_new = wd_ccp("CEC-2024-05-b.doc")
    assert P._looks_utf16le(wd_old, fc_old, ccp_old) is False   # 8-bit cp1252
    assert P._looks_utf16le(wd_new, fc_new, ccp_new) is True    # UTF-16LE cover page
