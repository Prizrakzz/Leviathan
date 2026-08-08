"""CYCLE-7 (2026-08-08) identity-gate pins -- the three fixes gate-4 of the D-CW/D-PQ probe reduced to.

Gate-4 confirmed cycle-6's gate-3 defects healed (the gas unlock holds on BOTH passes via the verify
amendment; the covenant is in band at 31 strips) and found a NEW both-pass class that cycle-6's FIX A
introduced: the footer-completion mint matched by ABSOLUTE MAGNITUDE alone and shipped 11 wrong-attribution
rows on hybrid turns -- real served numbers, correctly rendered, attached to prose numerals that are
semantically not about them.

  FIX 1  the completion mint is IDENTITY-GATED: per established call, sign-exact, unclaimed numerals only,
         non-data numeral shapes excluded, a 0-dp numeral held to a magnitude-scaled ceiling, and units
         that must not contradict.
  FIX 2  the `[N]` value splice writes the READER-FORMATTED figure, exactly once, and never a figure the
         sentence already carries.
  FIX 3  (instrument) `eval._served_rows` projects every call that can produce a footer row on the hybrid
         lane, not just the numbers agent's own lookups.

EVERY FIXTURE IS REPLAYED FROM GATE-4 EVIDENCE. The 11 over-mints are quoted with their own prose context
from the five gate-4 runs (dcw pass1/pass2 `dcw_urea_zscore`, `dcw_nass_conditions_split`,
`dcw_iod_beside_oni`; covenant `ab_pt_soy`, `ab_mech_frost`, `ab_amb_elnino`), and the FIX-2 shapes from
dcw pass2 `dcw_gas_nitrogen_squeeze`'s shipped body.

THE POLARITY IS DECIDED AND IT IS NOT SYMMETRIC (gate-4's own words): a missing bonus row costs a reader
one line of context; a wrong-attribution row is a lie with a citation on it. So the negative pins here
carry more weight than the positive ones, and several of them pin a row cycle-6 minted and cycle-7 gives
up on purpose.
"""
from __future__ import annotations

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orc


def _gold_z(vals, commodity="CBOT corn", metric="drought_z", period=None) -> dict:
    """The GOLD WEATHER Z serve shape: `drought_z` rows in `z`, the table behind 8 of the 11 over-mints."""
    return {"query": {"table": "gold_weather_z", "metric": metric, "commodity": commodity,
                      "period": period, "asof": "2026-08-07"}, "status": "ok",
            "rows": [{"value": str(v), "unit": "z", "period": p, "knowledge_date": k}
                     for v, p, k in vals]}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 1 -- THE 11 GATE-4 OVER-MINTS, EACH IN ITS OWN PROSE CONTEXT. ALL MUST REFUSE.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _refuses(prose: str, calls: list, cited: set) -> list[str]:
    stated = orc._stated_values(prose)
    return [c.label for c in cit.prose_completion_citations(calls, stated, seen=set(), cited=cited)]


def test_overmint_1_urea_zscore_names_a_drought_row_and_is_refused():
    """dcw pass1 `dcw_urea_zscore` [N6b]/[N6d]. The prose numeral is the UREA z-score standing beside its
    OWN [N2] marker; cycle-6 gave it two drought_z rows, one of them sign-flipped."""
    call = _gold_z([("-0.19742", "2025-08-07..2026-08-07", "2026-06"),
                    ("0.202378", "2024-01-01..2024-12-31", "2024-12"),
                    ("0.83", "2001-01-01..2001-03-31", "2001-03")])
    prose = ("Urea at $453.1/mt [N1] is at the 65.9th percentile of its five-year distribution [N4] and "
             "just fractionally below the five-year mean, at −0.195 sigma [N2].")
    assert _refuses(prose, [call], {1, 2, 4}) == []
    assert _refuses(prose, [call], {1}) == []          # ...and call 1 is the WASDE read, not this one


def test_overmint_2_a_farm_price_never_names_a_zscore():
    """dcw pass1 [N6f] / pass2 [N4d]: `drought_z = 1.82179 z` minted from '$1.82/bu', a season-average
    FARM PRICE carrying its own [N20]. Two independent refusals -- the numeral is claimed, and a currency
    numeral is not a z-score."""
    call = _gold_z([("1.82179", "2025-08-07..2026-08-07", "2026-06")])
    claimed = ("In MY 1998/99 the season-average US corn farm price was $1.94/bu [N19]; it fell to "
               "$1.82/bu [N20] in MY 1999/00.")
    assert _refuses(claimed, [call], {1}) == []
    bare = "The season-average corn farm price fell to $1.82/bu that year."
    assert _refuses(bare, [call], {1}) == []           # the unit fence alone, with nothing claiming it


def test_overmint_3_a_lag_horizon_is_not_a_measurement():
    """dcw pass1 [N6g] / pass2 [N4e]: `drought_z = 1.0044 z` minted from the '1' of '(1-4 quarter)'."""
    call = _gold_z([("1.0044", "2025-08-07..2026-08-07", "2026-06")])
    prose = ("The model carries urea cost as a low-confidence, long-lagged (1-4 quarter) driver on corn "
             "price.")
    assert _refuses(prose, [call], {1}) == []


def test_overmint_4_a_list_marker_and_a_quarter_label_are_not_measurements():
    """dcw pass1 [N18b]: `drought_z_pace_streak = 2 months` minted from the '(2)' of an enumeration.
    dcw pass2 [N16b] is the same row off the '2' of '2013 Q2'. covenant `ab_amb_elnino` [N2b] is
    `el_nino_flag = 1` off the '1' of '2016 Q1'."""
    pace = _gold_z([("2.0", "2025-12-30..2026-08-07", "2026-06")], metric="drought_z_pace_streak")
    pace["rows"][0]["unit"] = "months"
    enum = ("The mechanism runs through two channels: (1) a high breakeven cost that trims applied "
            "nitrogen rates, and (2) in extreme cases, an acre-switching effect toward soybeans.")
    assert _refuses(enum, [pace], {1}) == []
    assert _refuses("The reading is consistent with what was documented globally (2013 Q2).",
                    [pace], {1}) == []
    flag = {"query": {"table": "noaa_oni", "metric": "el_nino_flag", "asof": "2026-08-07"},
            "status": "ok",
            "rows": [{"value": "1", "unit": "0/1", "knowledge_date": "2026-05"},
                     {"value": "0", "unit": "0/1", "knowledge_date": "2016-03"}]}
    assert _refuses("For cocoa the ONI anomaly was still 1.71 degC in early 2016 Q1 [N7].",
                    [flag], {1, 7}) == []


def test_overmint_5_a_range_endpoint_is_not_a_measurement():
    """dcw pass1 [N18b] / pass2 [N19b] on `dcw_iod_beside_oni`: `oni_anom_pace_streak = 5 months` minted
    from the '5' of the range '2-5 MMT'. BOTH ends of a range are refused, not just the one measured."""
    streak = {"query": {"table": "noaa_oni", "metric": "oni_anom_pace_streak", "asof": "2026-08-07"},
              "status": "ok",
              "rows": [{"value": "5", "unit": "months", "knowledge_date": "2026-06"},
                       {"value": "2", "unit": "months", "knowledge_date": "2025-12"}]}
    prose = ("A weaker El Niño influence could raise India's rice production by 2-5 MMT. That "
             "illustrates the countervailing channel.")
    assert _refuses(prose, [streak], {1}) == []


def test_overmint_6_an_ONI_temperature_never_names_a_drought_z_row():
    """dcw pass1 [N30b] / pass2 [N29b]: `drought_z = -0.628213 z` minted from '-0.63 degC', an ONI
    anomaly. Pass1's numeral is claimed by [N28]; pass2's is claimed ACROSS AN INTERVENING YEAR
    ('-0.63 degC in mid-2021 [N10]') and refused by the unit fence besides."""
    call = _gold_z([("-0.628213", "2012-01-01..2012-03-31", "2012-03"),
                    ("-0.60975", "2021-06-25..2021-09-23", "2021-09")])
    p1 = ("This is the opposite of the two La Niña analogue windows in the record (−0.46 degC "
          "[N27] and −0.63 degC [N28]), where the ENSO forcing was price-supportive.")
    assert _refuses(p1, [call], {1, 27, 28}) == []
    p2 = ("The two prior La Niña analog windows showed negative ONI: -0.46 degC in early 2012 [N9] "
          "and -0.63 degC in mid-2021 [N10].")
    assert _refuses(p2, [call], {1, 9, 10}) == []
    # ...and with NOTHING claiming it, the unit fence still refuses on its own
    assert _refuses("The two analogue windows showed -0.46 degC and -0.63 degC.", [call], {1}) == []


def test_overmint_7_the_nass_zscore_neighbourhood_is_refused_row_by_row():
    """dcw pass1 [N31b]/[N32b]/[N32c], pass2 [N30b]/[N31b]/[N31c]: three drought_z rows minted off two
    numerals that each already carry their own marker, two of them SIGN-FLIPPED."""
    call = _gold_z([("1.01225", "2025-08-07..2026-08-07", "2026-06"),
                    ("-1.00651", "2025-05-01..2025-08-06", "2025-08"),
                    ("-0.60975", "2021-06-25..2021-09-23", "2021-09")])
    prose = ("However, the drought z-score for the current window is 1.00594 z [N32], sitting between the "
             "2012 analogue (0.614177 z [N30]) and the drier 2021 analogue (1.75586 z [N31]).")
    assert _refuses(prose, [call], {1, 30, 31, 32}) == []


def test_overmint_8_a_psd_era_diff_never_reads_the_opposite_direction():
    """dcw pass1 [N22b] / pass2 [N21b]: `area_harvested_1000ha_era_diff = 0.031 M ha` minted from
    '−0.033 M ha' -- a claimed numeral AND the opposite sign."""
    era = {"query": {"table": "silver_psd", "metric": "area_harvested_1000ha_era_diff",
                     "commodity": "CBOT corn", "asof": "2026-08-07"}, "status": "ok",
           "rows": [{"value": "0.031", "unit": "M ha", "period": "MY1994->MY1998",
                     "knowledge_date": "1999-03-10"}]}
    prose = ("MY1997 was 29.409 M ha [N17] and MY1998 was 29.376 M ha [N18], a change of −0.033 M ha "
             "[N19], or −0.11% [N20].")
    assert _refuses(prose, [era], {1, 17, 18, 19, 20}) == []
    # the sign clause standing alone: strip the markers and it is STILL the wrong direction
    assert _refuses("Area moved by -0.033 M ha across the era.", [era], {1}) == []


def test_overmint_9_the_covenant_090_spray_is_refused_all_five_ways():
    """covenant `ab_pt_soy` [N19b]/[N19d]/[N20b]/[N20c]/[N20e] -- one claimed '0.90 z' minted FIVE
    distinct drought rows -- plus [N20f], the same numeral sign-flipped."""
    call = _gold_z([("0.90036", "2011-04-05..2011-07-04", "2011-07"),
                    ("0.902066", "2011-07-05..2011-10-03", "2011-10"),
                    ("0.897333", "2025-08-06..2026-08-06", "2026-06"),
                    ("0.90323", "2025-05-01..2025-08-05", "2025-08"),
                    ("0.896081", "2024-08-06..2025-08-05", "2025-08"),
                    ("-0.903891", "2023-08-06..2024-08-05", "2024-08")],
                   commodity="CBOT soybeans")
    prose = ("The drought intensity index for the United States anchor also rose from 0.90 z [N19] to "
             "1.81 z [N20] across that same window.")
    assert _refuses(prose, [call], {1, 19, 20}) == []


def test_overmint_10_and_11_the_frost_and_elnino_rows():
    """covenant `ab_mech_frost` [N17b]: `drought_z = -1.00019 z` off the '1' of '1-2 quarters' (a range
    endpoint AND a horizon AND the opposite sign). covenant `ab_amb_elnino` [N2b] is pinned above."""
    call = _gold_z([("-1.00019", "2020-08-01..2020-10-30", "2020-10")], commodity="ICE arabica coffee")
    prose = ("The result is a supply shock that lands 1–2 quarters ahead in the price signal but is "
             "visible in the weather record now.")
    assert _refuses(prose, [call], {1}) == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 1 -- THE SIX RULES, EACH ISOLATED
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _pink(metric: str, vals, unit=None) -> dict:
    return {"query": {"table": "silver_pink_sheet", "metric": metric, "asof": "2026-08-07"},
            "status": "ok",
            "rows": [{"value": str(v), "unit": unit, "knowledge_date": k} for v, k in vals]}


def test_rule1_an_uncited_call_mints_nothing_and_a_cited_one_mints_its_sibling():
    """RULE (1), the re-scope, in both directions on ONE serve. This is cycle-5's numbers_only scope --
    the lane that produced ZERO over-mints in all five gate-4 runs -- applied to the hybrid pass."""
    call = _pink("natural_gas_eu_usd_mmbtu", [("17.91", "2026-03-01"), ("15.17", "2026-06-01")],
                 unit="USD/mmbtu")
    prose = "EU gas last printed 15.17 USD/mmbtu and ran as high as 17.91 earlier in the year."
    assert _refuses(prose, [call], set()) == []                      # no marker -> no mint, at all
    got = _refuses(prose + " [N1]", [call], {1})
    assert len(got) == 1 and "17.91" in got[0], got                  # the headline's SIBLING, once


def test_rule2_sign_is_exact_for_minting_and_stays_insensitive_for_backing():
    """RULE (2). `verify._num_matches` is magnitude-insensitive ON PURPOSE and is UNTOUCHED (cycle-6's
    amendment is frozen); identity is a different question and gate-4 shipped four rows that read the
    opposite direction of the numeral that named them."""
    from leviathan.graphrag import verify as vf
    assert vf._num_matches([-0.60975], [0.614177], [6]) is True             # BACKING: unchanged, still true
    call = _gold_z([("1.75586", "2026", "2026-06"), ("-0.60975", "2021", "2021-09")])
    assert _refuses("The 2012 analogue read 0.614177 z. [N1]", [call], {1}) == []
    # CYCLE-8 (2026-08-08), rule (7): the POSITIVE control moved onto a numeral that is a CORRECT ROUNDING
    # of the row. Cycle-7 wrote it as the gate-4 prose "0.614177" against a 0.60975 row -- a pair that only
    # ever matched through the 2-dp EXACT BUCKET, which cycle-8 demoted to a candidate index (they differ
    # in the third decimal: 0.614177 is not 0.60975 written to any precision). The SIGN pin is what this
    # test exists for and it is now pinned on BOTH arms of a precision-legal pair.
    plus = _gold_z([("1.75586", "2026", "2026-06"), ("0.60975", "2021", "2021-09")])
    assert len(_refuses("The 2012 analogue read 0.61 z. [N1]", [plus], {1})) == 1
    assert _refuses("The 2012 analogue read 0.61 z. [N1]", [call], {1}) == []       # ...and the minus row


def test_rule3_a_claimed_numeral_never_mints_a_second_row():
    """RULE (3), and the two adjacencies it reads: a handle AFTER the numeral inside its own sentence
    (with no other surviving numeral between -- an intervening YEAR does not break the link), and a
    handle sitting immediately in FRONT of it."""
    # CYCLE-8 (2026-08-08), rule (7): the numeral is "1.01" throughout, not cycle-7's "1.006". 1.006 named
    # the 1.01225 row only through the 2-dp exact bucket, which cycle-8 demoted to a candidate index -- so
    # under cycle-7's spelling BOTH arms would now refuse and this test would stop discriminating the thing
    # it exists for (CLAIMED-ness). "1.01" is a correct 2-dp rounding of 1.01225, so the mint decision turns
    # on rule (3) alone, exactly as cycle-7 intended.
    call = _gold_z([("1.75586", "2026-08-07", "2026-06"),
                    ("1.01225", "2021-09-23", "2021-09")])
    assert _refuses("The current window is 1.01 z [N32]. [N1]", [call], {1, 32}) == []
    assert _refuses("It read -0.63 degC in mid-2021 [N10] and 1.01 z in 2026 [N9]. [N1]",
                    [call], {1, 9, 10}) == []
    assert _refuses("The window read [N9] 1.01 z. [N1]", [call], {1, 9}) == []
    # ...and an UNCLAIMED restatement of the same figure still mints
    assert len(_refuses("The current window is 1.01 z, which is elevated. [N1]", [call], {1})) == 1


def test_rule5_the_zero_dp_ceiling_separates_a_restatement_from_a_coincidence():
    """RULE (5). A 0-dp numeral has a +-0.5 window whatever its magnitude, so only the RELATIVE gap can
    bound it. '1' vs 1.0044 is 4.4e-3 and is a coincidence; '35,763' vs 35763.1 is 2.8e-6 and is the CONAB
    row cycle-6's reader-precision arm exists for. A flat 'd=0 never names a non-integer row' would have
    refused both."""
    small = _gold_z([("1.75586", "2026", "2026-06"), ("1.0044", "2021", "2021-09")])
    assert _refuses("A single quarter of stress is enough. 1 quarter, in fact. [N1]", [small], {1}) == []
    assert _refuses("The index sat at 1 through the window. [N1]", [small], {1}) == []
    big = {"query": {"table": "silver_conab_coffee", "metric": "production_thousand_bags",
                     "asof": "2026-08-07"}, "status": "ok",
           "rows": [{"value": "35763.1", "period": "2026", "knowledge_date": "2026-06-01"},
                    {"value": "38904.9", "period": "2024", "knowledge_date": "2026-06-01"}]}
    got = _refuses("The prior crop ran 38,905 thousand bags. [N1]", [big], {1})
    assert len(got) == 1 and "38,905" in got[0], got
    assert _refuses("Yield was about 26 bags. [N1]", [big], {1}) == []


def test_rule6_the_unit_fence_refuses_a_category_error_and_fails_OPEN():
    """RULE (6). A degC numeral does not name a z row and a currency numeral does not name a z-score --
    but a unit the table does not know refuses NOTHING, so the fence can only ever remove a row cycle-6
    would have minted."""
    z = _gold_z([("1.75586", "2026", "2026-06"), ("1.71", "2016", "2016-03")])
    assert _refuses("The cocoa-tracked anomaly was still 1.71 degC in that window. [N1]", [z], {1}) == []
    oni = {"query": {"table": "noaa_oni", "metric": "oni_anom", "asof": "2026-08-07"}, "status": "ok",
           "rows": [{"value": "0.98", "unit": "degC", "knowledge_date": "2026-05"},
                    {"value": "1.71", "unit": "degC", "knowledge_date": "2016-03"}]}
    assert len(_refuses("The cocoa-tracked anomaly was still 1.71 degC in that window. [N1]",
                        [oni], {1})) == 1
    # an unknown prose unit and an unknown row unit both fail open (the cycle-6 behaviour)
    assert len(_refuses("The anomaly was still 1.71 widgets in that window. [N1]", [oni], {1})) == 1


def test_the_numbers_only_extras_lane_is_byte_for_byte_untouched():
    """CYCLE-5's lane produced ZERO over-mints in five runs and is the model this re-scope copies. It
    reads `.percent`/`.percent_level` and the magnitude list, never `.mint`, so nothing above reaches it."""
    call = _pink("natural_gas_eu_usd_mmbtu", [("17.91", "2026-03-01"), ("15.17", "2026-06-01")],
                 unit="USD/mmbtu")
    stated = orc._stated_values("The range ran 15.17 to 17.91 USD/mmbtu.")
    assert [c.id for c in cit.extra_number_citations(call, 1, stated)] == ["N1b"]
    # ...and a PLAIN list (every legacy/fixture caller) still works on that lane and mints NOTHING on this
    assert [c.id for c in cit.extra_number_citations(call, 1, [15.17, 17.91])] == ["N1b"]
    assert cit.prose_completion_citations([call], [15.17, 17.91], seen=set(), cited={1}) == []


def test_the_stated_values_list_and_percent_annotations_are_unchanged():
    """The mint annotation is ADDITIVE. The caution banner's list, `.percent` and `.percent_level` are the
    cycle-6 values to the item -- the mint pass runs its OWN scrub precisely so this stays true."""
    sv = orc._stated_values("Holds 15.7% of open interest, down 2.1% on the week, at -0.195 sigma [N2] "
                            "on 2026-06-01 with a (1-4 quarter) lag.")
    assert list(sv) == [15.7, 2.1, 0.195, 1.0, 4.0]
    assert sv.percent == (15.7, 2.1) and sv.percent_level == (15.7,)
    # ...and the mint view of the SAME string keeps only what may name a row: signed, unclaimed, unshaped
    assert [(n.value, n.claimed) for n in sv.mint] == [(15.7, False), (2.1, False), (-0.195, True)]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 2 -- THE VALUE SPLICE
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

_GAS_Z = -0.3063197017144927


def _gas_pair() -> list[dict]:
    return [_pink("natural_gas_eu_usd_mmbtu", [("15.17", "2026-06-01")]),
            _pink("natural_gas_eu_usd_mmbtu_zscore_5yr", [(_GAS_Z, "2026-06-01")])]


def test_the_splice_renders_the_figure_the_footer_renders():
    """gate-4 dcw pass2 `dcw_gas_nitrogen_squeeze` shipped 17 digits of a z-score in the prose beside its
    own correctly-rounded `## Sources` line. ONE renderer, one rendering."""
    calls = _gas_pair()
    assert an._number_handle_value(calls[1], 2) == "-0.30632 sigma vs 5-yr mean"
    assert "-0.30632" in cit.from_number(calls[1], 2).label
    assert repr(_GAS_Z)[:8] not in an._number_handle_value(calls[1], 2)


def test_the_five_duplications_in_one_paragraph_are_all_refused():
    """The other half of the same defect, verbatim from the shipped body: the writer put the marker in
    FRONT of its figure, the backward-looking cue read it as a stand-in, and the splice wrote the number
    a second time -- five times in one paragraph, one of them with the raw repr."""
    st = {"tldr": "", "sources": [],
          "mechanism": ("European natural gas was at [N1] 15.17 USD/mmbtu as of the latest available "
                        "date, sitting at [N2] -0.31 sigma below its five-year mean.")}
    census = an._resolve_number_handles(st, _gas_pair())
    assert st["mechanism"].count("15.17") == 1 and st["mechanism"].count("-0.31") == 1
    assert "0.3063197" not in st["mechanism"] and "-0.30632" not in st["mechanism"]
    assert census == {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 0}


def test_a_genuine_standin_still_gets_its_figure():
    """POLARITY. covenant `ab_mech_frost` shipped 'Brazil's drought-z score in the 2020 window was
    -0.00851709 z [N17]' -- a REAL stand-in, correctly filled, and its digits are `_fmt`'s (the footer
    renders the same string), so it was never the raw-repr class. It must keep working."""
    frost = _gold_z([("-0.00851709", "2020-08-01..2020-10-30", "2020-10")],
                    commodity="ICE arabica coffee")
    st = {"tldr": "", "sources": [],
          "mechanism": "Brazil's drought-z score in the 2020 La Nina window was [N1]."}
    census = an._resolve_number_handles(st, [frost])
    assert "-0.00851709 z [N1]" in st["mechanism"]
    assert census["substituted"] == 1
    assert "= -0.00851709 z" in cit.from_number(frost, 1).label     # prose and footer agree exactly


def test_a_neighbouring_citations_figure_is_never_mistaken_for_this_one():
    """ADJACENT MEANS ADJACENT. A figure standing further along the sentence -- even the SAME figure,
    belonging to another row -- must not suppress a splice this handle owes: a bare "[N1]" facing the
    reader is exactly the D-PQ HANDLE-1 defect the splice exists to prevent."""
    calls = _gas_pair()
    st = {"tldr": "", "sources": [],
          "mechanism": "Gas was at [N1], while the z-score was at 15.17 sigma [N2]."}
    census = an._resolve_number_handles(st, calls)
    assert "at 15.17 USD/mmbtu [N1]" in st["mechanism"], st["mechanism"]
    assert census["substituted"] == 1                             # [N2] is beside a stated figure


def test_a_handle_with_no_cue_is_untouched_in_both_worlds():
    """The cue test still gates everything: a handle attached to a stated figure was never spliced and
    still is not, byte for byte."""
    st = {"tldr": "", "sources": [], "mechanism": "Gas settled at 15.17 USD/mmbtu [N1]."}
    before = st["mechanism"]
    census = an._resolve_number_handles(st, _gas_pair())
    assert st["mechanism"] == before and census["substituted"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 3 -- served_rows COMPLETENESS ON THE HYBRID LANE (instrument, additive)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_served_rows_projects_every_footer_row_producing_call():
    """gate-4: dcw pass1 `nass_conditions_split` = 23 footer rows / 0 served row values; pass2
    `urea_zscore` = 18 / 2. The cascade legs mint most of a hybrid footer's [N] indices and reached no
    artifact, because `number_calls` stops at the agent's own lookups."""
    agent = _pink("urea_usd_mt", [("453.1", "2026-06-01")], unit="USD/mt")
    cascade = [_gold_z([("1.01225", "2025-08-07..2026-08-07", "2026-06")]),
               {"query": {"table": "noaa_oni", "metric": "oni_anom_pace_streak"}, "status": "ok",
                "rows": [{"value": "5", "unit": "months", "knowledge_date": "2026-06"}]},
               {"query": {"table": "silver_psd", "metric": "area_harvested_1000ha_era_diff"},
                "status": "ok", "rows": [{"value": "0.031", "unit": "M ha",
                                          "knowledge_date": "1999-03-10"}]}]
    out = {"number_calls": [agent], "number_calls_full": [agent] + cascade}
    recs = ev._served_rows(out)
    assert [r["metric"] for r in recs] == ["urea_usd_mt", "drought_z", "oni_anom_pace_streak",
                                           "area_harvested_1000ha_era_diff"]
    assert all(r["rows"] and r["rows"][0]["value"] for r in recs), recs
    assert [r["row_count"] for r in recs] == [1, 1, 1, 1]


def test_served_rows_falls_back_to_the_old_source_byte_for_byte():
    """ADDITIVE ONLY: the numbers_only lane never sets the new key, and its projection is unchanged."""
    agent = _pink("urea_usd_mt", [("453.1", "2026-06-01")], unit="USD/mt")
    assert ev._served_rows({"number_calls": [agent]}) == ev._served_rows(
        {"number_calls": [agent], "number_calls_full": None})
    assert ev._served_rows({}) == []


def test_served_rows_keeps_its_caps():
    """The bounded projection is the whole reason this column is safe to append to every record; widening
    the SOURCE must not widen the BUDGET."""
    wide = [_pink(f"m{k}", [(str(100 + i), "2026-06-01") for i in range(60)]) for k in range(40)]
    recs = ev._served_rows({"number_calls_full": wide})
    assert all(len(r["rows"]) <= ev._ROWS_PER_CALL_CAP for r in recs)
    assert sum(len(r["rows"]) for r in recs) <= ev._ROWS_PER_RECORD_CAP


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# CYCLE-7-AMEND (2026-08-08) -- THE FOUR AMENDMENTS THE ADVERSARIAL REVIEW MANDATED BEFORE GATE 5.
#
# Findings 3, 5, 6 and 7 of the cycle-7 review. Each was reproduced against the shipped working tree
# before the fix; each pin below FAILED then and passes now. The review's other findings (rule (1) buys
# nothing when the colliding call is itself cited; rule (3) is per OCCURRENCE not per FIGURE; rule (6)
# reads only the token AFTER the numeral) are ACCEPTED WATCH ITEMS this cycle and are deliberately NOT
# pinned here.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_amend_sign_is_exact_in_the_near_zero_band_both_directions():
    """FINDING 3. `round(x, 2)` collapses every |x| < 0.005 to +-0.0 and `round(-0.0, 2) == round(0.0, 2)`
    is True, so the exact bucket hit SHORT-CIRCUITED before rule (2)'s sign test could run: prose
    '-0.0012 z' minted a '0.0041 z' row. The covenant serves exactly this band (`ab_mech_frost` drought_z
    = -0.00851709 z). Both directions, because the collapse is symmetric."""
    pos_row = _gold_z([("9.99", "2026-06", "2026-06"), ("0.0041", "2020-10", "2020-10")])
    assert _refuses("Weather z is tracked for this anchor [N1].\nThe 2020 window read -0.0012 z.",
                    [pos_row], {1}) == []
    neg_row = _gold_z([("9.99", "2026-06", "2026-06"), ("-0.0041", "2020-10", "2020-10")])
    assert _refuses("Weather z is tracked for this anchor [N1].\nThe 2020 window read 0.0012 z.",
                    [neg_row], {1}) == []
    # ...and a SAME-SIGN row in the band still mints, so the amendment removed a sign error and not the arm
    same = _gold_z([("9.99", "2026-06", "2026-06"), ("0.0012", "2020-10", "2020-10")])
    assert len(_refuses("Weather z is tracked for this anchor [N1].\nThe 2020 window read 0.0012 z.",
                        [same], {1})) == 1


def test_amend_the_bucket_key_is_sign_carrying_and_zero_stays_neutral():
    """The key itself. ZERO HAS NO DIRECTION: `-0.0 < 0` is False in Python, so a true zero and a negative
    zero share one bucket. OUTSIDE the band the key decides exactly what 2-dp equality decided."""
    assert cit._mint_bucket(0.0) == cit._mint_bucket(-0.0) == (False, 0.0)
    assert cit._mint_bucket(-0.0012) == (True, 0.0) != cit._mint_bucket(0.0041) == (False, 0.0)
    assert cit._mint_bucket(-0.00851709) == (True, 0.01)              # the covenant's own row
    for a, b in ((1.75586, 1.7536), (-0.60975, -0.61), (35763.1, 35763.099)):
        assert (cit._mint_bucket(a) == cit._mint_bucket(b)) is (round(a, 2) == round(b, 2))
    assert cit._mint_bucket(1.75586) != cit._mint_bucket(-1.75586)


def test_amend_the_adjacency_prefix_set_covers_the_decks_own_shapes():
    """FINDING 5. FIX 2's adjacency class was `[\\s(\\[*"']` only, so "Urea was at [N1] $453.1/mt" still
    duplicated to "...453.1 USD/mt [N1] $453.1/mt" -- and `$453.1/mt` is the shape this deck's writers
    produce (this very file quotes it in `test_overmint_1`). The widened set is ENUMERATED: currency
    glyphs, the approximation markers, separating punctuation, and a currency WORD."""
    urea = [_pink("urea_usd_mt", [("453.1", "2026-06")], unit="USD/mt")]
    for mech in ("Urea was at [N1] $453.1/mt in June.",              # the deck's own shape
                 "Urea was at [N1] €453.1 in June.",
                 "Urea was at [N1] USD 453.1 in June.",
                 "Urea was at [N1] ~453.1 USD/mt in June.",
                 "Urea was at [N1] ~= 453.1 USD/mt in June.",
                 "Urea was at [N1] c. 453.1 USD/mt in June.",
                 "Urea was at [N1] about 453.1 USD/mt in June.",
                 "Urea was at [N1] roughly 453.1 USD/mt in June.",
                 "Urea was at [N1]: 453.1 USD/mt in June.",
                 "Urea was at [N1], 453.1 USD/mt, in June.",
                 "Urea was at [N1];453.1 USD/mt in June.",
                 "Urea was at [N1] -- 453.1 USD/mt in June.",
                 "Urea was at [N1] — 453.1 USD/mt in June."):
        st = {"tldr": "", "sources": [], "mechanism": mech}
        census = an._resolve_number_handles(st, urea)
        assert st["mechanism"].count("453.1") == mech.count("453.1"), st["mechanism"]
        assert census == {"substituted": 0, "handles_dropped": 0,
                          "sentences_dropped": 0, "unresolvable": 0}


def test_amend_the_adjacency_stays_strict_and_the_sign_is_never_eaten():
    """THE NON-REGRESSION HALF. The widening is a BOUNDED window of ENUMERATED shapes, not a sentence
    scan: a figure that is merely further along must still leave the splice alone (D-PQ HANDLE-1), and a
    lone '-' is the numeral's own sign, never a prefix -- reading it as punctuation would make the
    comparison sign-blind and suppress a splice the reader needs."""
    urea = [_pink("urea_usd_mt", [("453.1", "2026-06")], unit="USD/mt")]
    for mech in ("Urea was at [N1], the same 453.1 it printed in June.",
                 "Urea was at [N1] and corn 453.1 USD/mt in June.",
                 "Urea was at [N1] in June; DAP was 453.1 USD/mt.",
                 # `; ` is a SENTENCE boundary (`_HANDLE_BOUND_RX`), and the adjacency read never leaves the
                 # handle's own sentence -- the older, stricter fence wins over the widened prefix set
                 "Urea was at [N1]; 453.1 USD/mt in June."):
        st = {"tldr": "", "sources": [], "mechanism": mech}
        assert an._resolve_number_handles(st, urea)["substituted"] == 1, st["mechanism"]
    gasz = [_pink("natural_gas_eu_usd_mmbtu_zscore_5yr", [(_GAS_Z, "2026-06-01")])]
    st = {"tldr": "", "sources": [], "mechanism": "Gas sat at [N1] -0.31 sigma below its mean."}
    assert an._resolve_number_handles(st, gasz)["substituted"] == 0        # the same figure -> no splice
    st = {"tldr": "", "sources": [], "mechanism": "Gas sat at [N1] 0.31 sigma below its mean."}
    assert an._resolve_number_handles(st, gasz)["substituted"] == 1        # opposite sign -> NOT the same


def test_amend_the_splice_keeps_every_digit_the_reader_needs():
    """FINDING 6 (latent). `cit._fmt`'s `,.0f` arm DROPS the decimals of every value at or above 1000 (a
    1052.25 settle would have reached the page as '1,052') and its `%g` arm goes SCIENTIFIC below 1e-4.
    The SPLICE gets its own precision-preserving renderer; the footer's `_fmt` is unchanged this cycle."""
    settle = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "CBOT soybeans",
                        "asof": "2026-08-07"}, "status": "ok",
              "rows": [{"value": "1052.25", "unit": "US cents/bu", "knowledge_date": "2026-06-01"}]}
    assert an._number_handle_value(settle, 1) == "1,052.25 US cents/bu"
    assert an._splice_fmt("1052.25") == "1,052.25" and cit._fmt("1052.25") == "1,052"
    tiny = _gold_z([("0.00001234", "2020-10", "2020-10")])
    assert an._number_handle_value(tiny, 1) == "0.00001234 z"
    assert "e-" not in an._splice_fmt("0.00001234") and cit._fmt("0.00001234") == "1.234e-05"
    # ...the gate-4 MEASURED shapes are byte-identical, which is what the cycle-7 fix bought
    assert an._splice_fmt("15.17") == "15.17"
    assert an._splice_fmt(str(_GAS_Z)) == "-0.30632"
    assert an._splice_fmt("35763.1") == "35,763.1" and an._splice_fmt("1486837.4") == "1,486,837"
    assert an._splice_fmt("not-a-number") == "not-a-number"            # `_fmt`'s own fall-through


def test_amend_number_calls_full_never_reaches_the_wire():
    """FINDING 7. INSTRUMENT-1 added an UNBOUNDED top-level key that /v1/respond returned raw, the SSE
    `result` event serialized, and the frontend posts whole to /v1/share (a PUBLIC read) and
    /v1/artifacts. It is an IN-PROCESS instrument: `eval._served_rows` still sees it because the harness
    calls `orchestrator.respond` directly; the service strips it at its boundary."""
    from fastapi.testclient import TestClient
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import server as sv

    full = [_pink("urea_usd_mt", [("453.1", "2026-06-01")], unit="USD/mt")]

    class _FakeGraph:
        contracts = {"corn": object()}
        version = "gtest12ab34cd"

    def fake_respond(query, *, graph, asof=None, session_id=None, **kw):
        return {"answer": "A", "intent": "reasoning", "number_calls": [],
                "number_calls_full": [dict(c) for c in full], "trace": {}}

    import pytest
    mp = pytest.MonkeyPatch()
    try:
        mp.setitem(sv._STATE, "graph", _FakeGraph())
        mp.setattr(orch, "respond", fake_respond)
        c = TestClient(sv.app)
        body = c.post("/v1/respond", json={"question": "urea"}).json()
        assert "number_calls_full" not in body and body["answer"] == "A"
        with c.stream("GET", "/v1/respond/stream", params={"question": "urea"}) as r:
            text = "".join(chunk for chunk in r.iter_text())
        assert "number_calls_full" not in text and "event: result" in text
    finally:
        mp.undo()
    # ...and the in-process consumer is untouched: the eval harness never goes through the server
    assert [r["metric"] for r in ev._served_rows(fake_respond("q", graph=None))] == ["urea_usd_mt"]
    assert sv._public_result({"a": 1}) == {"a": 1}                   # a result without the key is a no-op
