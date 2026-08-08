"""CYCLE-6 (2026-08-08) prose-authority pins -- the three deterministic fixes gate-3 of the D-CW/D-PQ probe
reduced to, plus the RCA arithmetic that produced FIX B.

Every fixture here is REPLAYED FROM GATE-3 EVIDENCE, never invented: the pink-sheet gas/urea z-score serve
and its two stripped sentences from `dcw_gas_nitrogen_squeeze` (dcw pass1 strip_audit + served_rows), the
uncited COT/pink-sheet values from `dcw_macro_on_soy` (pass1), the CONAB rows from covenant `ab_cmp_coffee`,
the duplicated FUTURES EOD 446 settle row from `dpq_probe` (both passes), and the el-nino streak/threshold
strips the RCA FALSIFIED as a rounding class.

The three fixes:
  FIX B  verify._num_matches / _num_backed gain a reader-precision arm (the ONE sanctioned strip-rule
         amendment) -- a correct rounding at the precision the prose wrote is a match.
  FIX A  the hybrid lane's `## Sources` completes itself off the FINAL prose: a SERVED value the reader can
         see, with no footer row, gets one.
  FIX C  a full-identity duplicate footer row is dropped and its prose markers re-pointed to the survivor.

The POLARITY pins (byte-identical output when the defect is absent) carry as much weight as the positive
ones: gate-4 must stay comparable to gate-3 on every metric that already existed.

CYCLE-7 (2026-08-08) AMENDS SIX FIX-A PINS IN THIS FILE, and every amendment is in ONE direction: fewer
rows minted. Gate-4 measured 11 both-pass wrong-attribution rows off FIX A's magnitude-only match, and the
completion pass is now identity-gated and scoped to calls the prose actually cites
(`citations.prose_completion_citations`, pinned in `test_cycle7_identity_gate.py`). FIX B -- the sanctioned
verify amendment -- is FROZEN as shipped and nothing in this file's FIX-B section moved. The three FIX-A
shapes that lose their rows (gas pass2, macro pass1, the coffee covenant serve as the covenant actually
cited it) are pinned here as REFUSALS, with the cost stated in each docstring rather than deleted.
"""
from __future__ import annotations

import re

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag import verify as vf


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# THE GATE-3 SERVE, verbatim from `dcw_gas_nitrogen_squeeze` pass1 served_rows
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

_GAS_Z = -0.3063197017144927
_UREA_Z = -0.19515863509764528


def _ps(metric: str, value, rows=None) -> dict:
    return {"query": {"table": "silver_pink_sheet", "metric": metric, "asof": "2026-08-07"},
            "status": "ok",
            "rows": rows if rows is not None else [{"value": str(value), "knowledge_date": "2026-06-01"}]}


def _gas_calls() -> list[dict]:
    """[N1..N4] = the four `latest` reads the answer cited; [N5]/[N6] = the 30-row windows behind them."""
    win = [{"value": v, "knowledge_date": f"2026-{m:02d}-01"}
           for m, v in ((3, "17.91"), (4, "15.41"), (5, "16.17"), (6, "15.17"))]
    return [_ps("natural_gas_eu_usd_mmbtu", "15.17"),
            _ps("natural_gas_eu_usd_mmbtu_zscore_5yr", _GAS_Z),
            _ps("urea_usd_mt", "453.1"),
            _ps("urea_usd_mt_zscore_5yr", _UREA_Z),
            _ps("natural_gas_eu_usd_mmbtu", None, rows=win),
            _ps("urea_usd_mt", None, rows=[{"value": "453.1", "knowledge_date": "2026-06-01"}])]


# the two sentences gate-3 stripped, quoted from the pass1 strip_audit
_MECH_GAS = ("The most recent observed read on EU gas is 15.17 USD/mmbtu [N1] [N5], sitting at "
             "-0.31 sigma versus its five-year mean [N2] -- below average, not elevated.")
_MECH_UREA = ("Urea is 453.1 USD/mt [N3] [N6], likewise at -0.20 sigma versus its five-year mean [N4].")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX B -- THE RCA, AND THE SANCTIONED AMENDMENT
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_rca_the_1pct_tolerance_really_does_reject_a_correct_2dp_rounding():
    """The measured arithmetic, pinned so the defect can never be re-argued as anything else. The prose
    wrote a CORRECT 2-dp rounding of the served z-score and BOTH 1% arms rejected it, in both directions,
    because at |x| ~ 0.3 a 2-dp restatement is worth up to 0.005 absolute and 1% of 0.3 is only 0.003."""
    a, b = 0.31, abs(_GAS_Z)
    assert round(_GAS_Z, 2) == -0.31                      # the prose was RIGHT
    assert abs(a - b) > 0.01 * b and abs(a - b) > 0.01 * a  # ...and both 1% arms said no
    assert vf._num_matches([a], [_GAS_Z]) is False        # the pre-CYCLE-6 predicate, unarmed
    assert vf._num_matches([a], [_GAS_Z], [2]) is True    # ...and armed with the prose's own precision
    # the urea leg of the same answer, same shape, larger margin of error
    assert round(_UREA_Z, 2) == -0.2
    assert vf._num_matches([0.2], [_UREA_Z]) is False
    assert vf._num_matches([0.2], [_UREA_Z], [2]) is True


def test_the_reader_precision_arm_rounds_and_never_bins():
    m = vf._num_matches
    assert m([0.31], [_GAS_Z], [2]) is True               # -0.31 IS -0.30632 to 2 places
    assert m([0.32], [_GAS_Z], [2]) is False              # -0.32 is NOT
    assert m([4.2], [4.24], [1]) is True                  # a 1-dp restatement of a 2-dp figure: allowed
    assert m([4.3], [4.24], [1]) is False
    assert m([446.0], [445.6], [0]) is True               # d=0 rounding: allowed
    assert m([400.0], [446.0], [0]) is False              # d=0 BINNING: refused
    assert m([446.0], [446.0], [0]) is True
    # the arm is SCALE-1 only: a rescale bridge stacked on a rounding window is not sanctioned
    assert m([0.31], [30.632], [2]) is False


def test_written_precision_is_read_off_the_token_not_the_float():
    """'-0.20' commits to two places; float('0.20') cannot remember that, so the decimals come from the
    matched token. The pair extractor stays positionally parallel to the historical values extractor."""
    assert vf._token_decimals("0.20") == 2 and vf._token_decimals("0.2") == 1
    assert vf._token_decimals("446") == 0 and vf._token_decimals("1,486,837") == 0
    assert vf._token_decimals("30.") == 0                 # trailing sentence punctuation is not precision
    nums, decs = vf._claim_numbers_with_decimals("gas 15.17 at -0.31 sigma, urea 453.1 at -0.20")
    assert nums == vf._claim_numbers_in("gas 15.17 at -0.31 sigma, urea 453.1 at -0.20")
    assert (nums, decs) == ([15.17, 0.31, 453.1, 0.2], [2, 2, 1, 2])


def test_the_zero_policy_is_untouched():
    """0 matches only 0, before and after. A prose '0' may never round-rescue a 0.4 row -- the guard runs
    first and the arm never sees the pair."""
    assert vf._num_matches([0.0], [0.0], [0]) is True
    assert vf._num_matches([0.0], [0.4], [0]) is False
    assert vf._num_matches([0.4], [0.0], [1]) is False
    assert vf._num_backed(0.0, [0.0], dec=0) is True
    assert vf._num_backed(0.0, [0.4], dec=0) is False


def test_omitting_the_decimals_is_byte_for_byte_the_old_predicate():
    """The polarity pin for every caller that does not thread precision (orchestrator's caution banner,
    every fixture, every legacy call site)."""
    for a, pool in ((0.31, [_GAS_Z]), (2.0, [2.75]), (31.4, [31400000.0]), (0.3636, [36.4]), (5.0, [5.0])):
        assert vf._num_matches([a], pool) == vf._num_matches([a], pool, None)
    assert vf._num_backed(0.31, [_GAS_Z]) is False and vf._num_backed(0.31, [_GAS_Z], dec=None) is False


def test_the_gate3_gas_answer_stops_stripping_entirely():
    """END TO END on the real call set: gate-3 charged 10 number-rule strips across these three sentences
    (4 on the tldr, 4 number_unbacked + 2 number_mismatch on the two mechanism sentences). All 10 clear."""
    calls = _gas_calls()
    tldr = ("EU natural gas as of June 2026 stands at 15.17 USD/mmbtu [N1], roughly in line with its "
            "five-year mean (z-score of -0.31 sigma [N2]), and urea is at 453.1 USD/mt [N3], also near "
            "its five-year mean (-0.20 sigma [N4]).")
    for sent, idxs in ((tldr, (1, 2, 3, 4)), (_MECH_GAS, (1, 5, 2)), (_MECH_UREA, (3, 6, 4))):
        assert [vf._check_number_handle(sent, i, calls) for i in idxs] == [None] * len(idxs), sent


def test_number_unbacked_needed_the_same_arm_or_the_fix_would_be_inert():
    """The gas sentence was charged TWICE by two different predicates: number_mismatch on [N2]
    (`_num_matches`) and number_unbacked on [N1]/[N5] (`_num_backed`, against the merged all-rows pool).
    Arming only the first leaves the sentence stripped by the second."""
    allv = vf._all_row_vals(_gas_calls())
    assert vf._num_backed(0.31, allv) is False            # the pre-CYCLE-6 backstop
    assert vf._num_backed(0.31, allv, dec=2) is True      # ...and the same rule, armed


def test_the_elnino_strips_are_NOT_a_rounding_class_and_stay_stripped():
    """RCA FALSIFICATION, pinned. The covenant `ab_amb_elnino` strips have two OTHER causes and the
    amendment must not touch either:
      (a) a handle cited for a QUALITATIVE clause -- [N9]/[N11] are `pace_streak` rows whose value is the
          run length 5, while the prose wrote 'five' as a WORD, so 0.98/0.47 are checked against 5 and
          mismatch. That is the co-cited-handle class, not a precision class (task #46 territory).
      (b) a genuinely INVENTED threshold: '2.0+ degC' against a served 2.75 is not a rounding of anything
          (round(2.75, 1) = 2.8), and it must keep stripping."""
    assert vf._num_matches([0.98, 0.47], [5.0], [2, 2]) is False
    assert vf._num_matches([2.0], [2.75], [1]) is False
    assert vf._num_backed(2.0, [2.75], dec=1) is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX A -- FINAL-PROSE FOOTER COMPLETION (hybrid lane)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

_VR = {"enabled": True, "resolved": {}}


def _rows(block: str) -> list[str]:
    return [ln for ln in block.split("\n") if ln.startswith("[N")]


def test_gas_pass2_shape_is_GIVEN_UP_by_the_cycle7_per_call_scope():
    """CYCLE-7 AMENDMENT, AND THE HONEST RESIDUAL. (i) THE MODEL STATES IT WITH NO MARKER -- gate-3 dcw
    pass2: 'European natural gas as of June 2026 stood at 15.17 USD/mmbtu, with a 5-year z-score of
    -0.30632 sigma', no [N] anywhere on either call. Cycle-6 minted [N1b]/[N2b] here; gate-4 measured what
    minting off an UNESTABLISHED call costs (11 both-pass wrong-attribution rows) and cycle-7 rule (1)
    gives this shape up: a call the reader sees no marker for mints nothing.

    THE CLASS IS COVERED FROM THE OTHER SIDE and that is why the trade is affordable -- what actually
    healed the gas unlock at gate-4 was cycle-6's verify amendment keeping the marker-bearing sentences
    alive (pinned directly by `test_the_gate3_gas_answer_stops_stripping_entirely`), not this pass."""
    st = {"tldr": "Urea is close to its recent average [N3].", "sources": [],
          "mechanism": ("European natural gas as of June 2026 stood at 15.17 USD/mmbtu, with a 5-year "
                        "z-score of -0.30632 sigma.")}
    rows = _rows(an._cited_sources_block(st, _VR, _gas_calls()))
    assert rows == [r for r in rows if r.startswith("[N3] PINK SHEET urea_usd_mt")], rows
    assert not any(r.startswith("[N1b]") or r.startswith("[N2b]") for r in rows), rows


def test_the_same_print_served_twice_is_footed_once():
    """The de-dup horizon is the WHOLE footer, not one call: the deck routinely serves a `latest` read
    beside the 30-row window it came from, and 15.17 appears in both. One fact, one row.
    CYCLE-7: both calls now carry a marker (rule (1)), which is also the shape the deck actually ships."""
    st = {"tldr": "", "sources": [],
          "mechanism": ("EU gas last printed 15.17 USD/mmbtu [N1]. The five-year window [N5] ran as high "
                        "as 17.91.")}
    rows = _rows(an._cited_sources_block(st, _VR, _gas_calls()))
    mints = [r for r in rows if re.match(r"\[N\d+[a-z]\]", r)]
    # 15.17 is [N1]'s headline AND [N5]'s; the shared horizon means the COMPLETION pass re-mints neither
    assert not any("15.17" in r for r in mints), rows
    assert mints == [r for r in mints if r.startswith("[N5b]") and "17.91" in r], rows


def test_macro_pass1_shape_is_GIVEN_UP_the_same_way():
    """gate-3 dcw pass1 `dcw_macro_on_soy`: mm_net 160,479 / mm_pct_oi 15.7% / soybean_oil 1,765 /
    soybean_meal 425 were all SERVED and all faced the reader uncited. CYCLE-7 rule (1) refuses the whole
    shape for the same reason as the gas one -- and gate-4's own `dcw_macro_on_soy` completion row
    (`cny_usd_pct_change_90d = -0.763022` off call 11, which the prose never marks) goes with it."""
    def _c(table, metric, value, kd):
        return {"query": {"table": table, "metric": metric, "asof": "2026-08-07"}, "status": "ok",
                "rows": [{"value": value, "knowledge_date": kd}]}
    calls = [_c("silver_cot", "mm_net", "160479", "2026-07-28"),
             _c("silver_cot", "mm_pct_oi", "15.7316", "2026-07-28"),
             _c("silver_pink_sheet", "soybean_oil_usd_t", "1765.0", "2026-06-01"),
             _c("silver_pink_sheet", "soybean_meal_usd_t", "425.0", "2026-06-01")]
    st = {"tldr": "", "sources": [],
          "mechanism": ("Managed money is net long 160,479 contracts, 15.7% of open interest. Soyoil sits "
                        "at 1,765 USD/t and soymeal at 425 USD/t.")}
    assert an._cited_sources_block(st, _VR, calls) == ""


def test_a_percent_numeral_still_cannot_mint_a_PRICE_row():
    """The un-fence above is per CALL and reads only card-declared facts, so cycle-5 correction (B)'s
    motivating fabrication is still refused: 'down 2.1% year on year' must never mint an avg_farm_price
    row of 2.1 $/bu."""
    call = {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "corn"},
            "status": "ok", "rows": [{"value": "2.1", "period": "1994/95", "knowledge_date": "2026-07-10"},
                                     {"value": "4.4", "period": "2026/27", "knowledge_date": "2026-07-10"}]}
    st = {"tldr": "", "sources": [], "mechanism": "The farm price is down 2.1% year on year."}
    assert an._cited_sources_block(st, _VR, [call]) == ""


def test_coffee_covenant_shape_needs_the_reader_precision_arm():
    """gate-3 covenant `ab_cmp_coffee`: the prose wrote '35,763' for a served 35763.1 -- a correct 0-dp
    rounding that 2-dp equality alone cannot see."""
    def _conab(metric, vals):
        return {"query": {"table": "silver_conab_coffee", "metric": metric, "asof": "2026-08-07"},
                "status": "ok",
                "rows": [{"value": v, "period": p, "knowledge_date": "2026-06-01"} for v, p in vals]}
    calls = [_conab("production_thousand_bags", [("38904.9", "2024"), ("35763.1", "2026")]),
             _conab("area_in_production_ha", [("1508744.0", "2025"), ("1486837.0", "2026")]),
             _conab("yield_bags_per_ha", [("26.24593701781084", "2025"),
                                          ("24.05314099662572", "2026")])]
    # CYCLE-7, AND THE COST STATED PLAINLY. The covenant answer this fixture is copied from cites [N4]..
    # [N13] and NEVER [N1]/[N2]/[N3] -- so under rule (1) the real shape mints NOTHING, and the three rows
    # gate-4 shipped for it are given up with the gas and macro shapes. That refusal is pinned first; the
    # reader-precision arm is then pinned on the SAME serve with the calls established, which is the shape
    # that keeps the arm reachable (and is what `dcw_us_ethanol_margin`-style turns actually look like).
    _bare = {"tldr": "", "sources": [],
             "mechanism": ("Brazil arabica production is 35,763 thousand bags on 1,486,837 ha, a yield of "
                           "24.0531 bags/ha.")}
    assert an._cited_sources_block(_bare, _VR, calls) == ""
    _cite = "The CONAB survey reports production [N1], area [N2] and yield [N3]. "
    st = {"tldr": "", "sources": [],
          "mechanism": (_cite + "The prior crop ran 38,905 thousand bags on 1,508,744 ha, a yield of "
                        "26.2459 bags/ha.")}
    rows = [r for r in _rows(an._cited_sources_block(st, _VR, calls)) if re.match(r"\[N\d+[a-z]\]", r)]
    assert len(rows) == 3, rows
    # "38,905" for 38904.9 is a 0-dp round the 2-dp bucket alone cannot see -- the arm is what mints it,
    # and CYCLE-7's 0-dp relative ceiling admits it at 2.6e-6 while refusing "about 26" at 9.4e-3.
    assert "MY2024 = 38,905" in rows[0] and "1,508,744" in rows[1] and "26.2459" in rows[2], rows
    # ...and the binning refusal on the same fixture: a 2-significant-digit numeral names nothing
    st2 = {"tldr": "", "sources": [], "mechanism": _cite + "Yield was about 26 bags/ha."}
    assert not [r for r in _rows(an._cited_sources_block(st2, _VR, calls))
                if re.match(r"\[N\d+[a-z]\]", r)]


def test_only_the_final_prose_counts():
    """A value the verifier stripped away must not summon a row -- the footer follows SURVIVING prose."""
    st = {"tldr": "", "sources": [], "mechanism": "EU gas is below its five-year average."}
    assert an._cited_sources_block(st, _VR, _gas_calls()) == ""


def test_a_declined_call_and_a_zero_aggregate_refusal_never_mint():
    """The two classes whose whole purpose is to assert the ABSENCE of a figure."""
    dead = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"}, "status": "no_rows",
            "rows": [{"value": "0.0", "knowledge_date": "2026-07-30"}]}
    st = {"tldr": "", "sources": [], "mechanism": "Weekly exports printed 0.0."}
    assert an._cited_sources_block(st, _VR, [dead]) == ""
    # the EMPTY-2 collapsed-zero ESR aggregate: `from_number` renders NO REPORTED FIGURE for it, so a
    # value-keyed row asserting 0 would contradict the very line beside it
    zero = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "sum",
                      "commodity": "soybeans", "country": "china", "asof": "2026-08-07"}, "status": "ok",
            "rows": [{"value": "0.0", "knowledge_date": "2026-07-30", "period": "2026"}]}
    assert cit._zero_aggregate(zero) is True                    # the fixture really IS that class
    assert "NO REPORTED FIGURE" in cit.from_number(zero, 1).label
    stated = orc._stated_values("Weekly exports summed to 0.0 for the window.")
    assert cit.prose_completion_citations([zero], stated, seen=set(), cited=set()) == []


def test_the_whole_footer_is_capped_and_the_cap_takes_the_newest():
    """A hybrid turn carries many calls where the numbers_only lane carries one, so the per-call cap of 6
    is not a ceiling on its own -- a 30-call turn minted 91 rows without this. The cap is applied to a
    GLOBAL newest-first ranking, so the freshest evidence is what survives it."""
    calls, prose = [], []
    for k in range(20):
        v = f"{100 + k}.50"
        # CYCLE-7: two rows per call -- the headline (already on the page under its own marker) and the
        # older sibling the prose restates. Rule (1) needs the call cited; the CAP is what this pins.
        calls.append({"query": {"table": "silver_pink_sheet", "metric": f"m{k}", "asof": "2026-08-07"},
                      "status": "ok",
                      "rows": [{"value": v, "knowledge_date": f"2026-06-{k + 1:02d}"},
                               {"value": f"{200 + k}.50", "knowledge_date": f"2026-07-{k + 1:02d}"}]})
        prose.append(v)
    st = {"tldr": "", "sources": [],
          "mechanism": ("Reads " + " ".join(f"[N{k}]" for k in range(1, 21)) + ".\n"
                        "Prints: " + ", ".join(prose) + ".")}
    rows = [r for r in _rows(an._cited_sources_block(st, _VR, calls)) if re.match(r"\[N\d+[a-z]\]", r)]
    assert len(rows) == cit._MAX_COMPLETION_ROWS == 12
    # the survivors are the twelve NEWEST knowledge dates on the page (calls 9..20), and the ids are still
    # ascending by call index
    assert rows == sorted(rows, key=lambda r: int(re.match(r"\[N(\d+)", r).group(1)))
    assert [int(re.match(r"\[N(\d+)", r).group(1)) for r in rows] == list(range(9, 21))


def test_headline_already_on_the_page_is_never_minted_twice():
    """Polarity: prose states exactly the value its own [N] headline already renders -> no extra row."""
    st = {"tldr": "", "sources": [], "mechanism": "EU gas last printed 15.17 USD/mmbtu [N1]."}
    rows = _rows(an._cited_sources_block(st, _VR, _gas_calls()[:1]))
    assert rows == [r for r in rows if r.startswith("[N1] ")] and len(rows) == 1


def test_the_numbers_only_lane_is_untouched_and_the_two_passes_are_idempotent():
    """LANE IDEMPOTENCY, pinned. `run_numbers_only` mints through `unify(stated=...)`; the hybrid bodies
    mint through `_cited_sources_block`. Neither calls the other. And because both seed the same
    (value, period) horizon, running the hybrid pass OVER a footer the extras pass already built adds
    nothing -- the overlap is empty by measurement, not by assumption."""
    call = _gas_calls()[4]                                # a 4-row window: the extras pass's entry shape
    prose = "The range ran 15.17 to 17.91 USD/mmbtu."
    stated = orc._stated_values(prose)
    extras = cit.extra_number_citations(call, 1, stated)
    assert [c.id for c in extras] == ["N1b"]              # 17.91 is the headline; 15.17 is the extra
    seen = {cit.row_key(call, cit.headline_row(call))} | {cit.row_key(call, c.payload["rows"][0])
                                                          for c in extras}
    assert cit.prose_completion_citations([call], stated, seen=seen, cited={1}) == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX C -- FOOTER DE-DUP (full identity only, prose re-pointed)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _settle(value="446", kd="2026-06-05", month="2026-12") -> dict:
    """The dpq row that shipped twice: `FUTURES EOD settle CBOT corn delivery 2026-12 = 446 US
    cents/bushel (exchange settlement, USD)  [known 2026-06-05]`."""
    return {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "CBOT corn",
                      "asof": "2026-08-07"}, "status": "ok",
            "rows": [{"value": value, "unit": "US cents/bushel", "contract_month": month,
                      "currency": "USD", "print_kind": "exchange settlement", "knowledge_date": kd}]}


def test_dpq_p1_footer_shape_dedups_and_the_prose_is_repointed():
    """gate-3 dpq pass1: [N10] and [N12] rendered the identical settle row. The clone leaves the prose
    FIRST (so body and footer cannot disagree) and the footer follows."""
    calls = [_settle() for _ in range(12)]
    st = {"tldr": "", "sources": [],
          "mechanism": "It settled at 446 cents [N10] and the same print appears again [N12]."}
    # the clone map is scoped to the indices the PROSE carries (a call nobody cites has no footer row to
    # duplicate), so this is one re-point onto the LOWEST cited index -- 'keep the first'
    assert an._dedup_number_handles(st, calls) == 1
    assert "[N12]" not in st["mechanism"] and st["mechanism"].count("[N10]") == 2
    rows = _rows(an._cited_sources_block(st, _VR, calls))
    assert len(rows) == 1 and rows[0].startswith("[N10] FUTURES EOD settle")


def test_two_rows_differing_in_ANY_field_both_stay():
    """ONLY full identity drops. Value, unit, delivery month and known-stamp are each sufficient to keep
    both -- these are the fields `from_number` writes into the one line the de-dup keys on."""
    for other in (_settle(value="447"), _settle(kd="2026-06-06"), _settle(month="2027-03")):
        calls = [_settle(), other]
        st = {"tldr": "", "sources": [], "mechanism": "Two prints [N1] and [N2]."}
        assert an._dedup_number_handles(st, calls) == 0
        assert an._number_row_clones([1, 2], calls) == {}
        assert len(_rows(an._cited_sources_block(st, _VR, calls))) == 2


def test_a_grouped_token_collapses_to_one_marker():
    """`[N1, N2]` where N2 clones N1 is one receipt written twice; the collapse folds it and the adjacent
    repeat it can create."""
    calls = [_settle(), _settle()]
    st = {"tldr": "", "sources": [], "mechanism": "The settle [N1, N2] held. Again [N2] [N1]."}
    assert an._dedup_number_handles(st, calls) == 1
    assert st["mechanism"] == "The settle [N1] held. Again [N1]."


def test_a_non_clone_token_keeps_its_exact_bytes():
    """Polarity, and it matters: a turn that re-points ONE index must not silently re-canonicalize every
    other grouped token on the page."""
    calls = [_settle(), _settle(), _settle(value="447")]
    st = {"tldr": "", "sources": [], "mechanism": "A [N1] B [N2] C [N3;N1] D."}
    an._dedup_number_handles(st, calls)
    assert "[N3;N1]" in st["mechanism"] and "[N2]" not in st["mechanism"]


def test_no_clone_means_byte_identical_prose():
    calls = [_settle(), _settle(value="447")]
    st = {"tldr": "T [N1].", "sources": [], "mechanism": "M [N2] and [N1;N2]."}
    before = dict(st)
    assert an._dedup_number_handles(st, calls) == 0
    assert st == before


def test_the_dedup_is_a_no_op_without_number_calls():
    st = {"tldr": "", "sources": [], "mechanism": "Nothing here [N1]."}
    assert an._dedup_number_handles(st, None) == 0
    assert an._dedup_number_handles(None, [_settle()]) == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# CROSS-FIX POLARITY: a clean turn renders exactly today's footer
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_a_turn_with_no_defect_renders_the_pre_cycle6_footer():
    """The whole-page polarity pin: prose cites its handles, states only their headline values, and no two
    rows are clones -> the block is what gate-3 would have rendered, byte for byte."""
    calls = _gas_calls()[:4]
    st = {"tldr": "Gas is 15.17 USD/mmbtu [N1] at -0.30632 sigma [N2].", "sources": [],
          "mechanism": "Urea is 453.1 USD/mt [N3] at -0.19515863509764528 sigma [N4]."}
    block = an._cited_sources_block(st, _VR, calls)
    assert [r.split()[0] for r in _rows(block)] == ["[N1]", "[N2]", "[N3]", "[N4]"]
    assert not re.search(r"^\[N\d+[a-z]\]", block, re.M)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# CYCLE-6 ADVERSARIAL REVIEW (2026-08-08) -- the five findings the reviewer BLOCKED on, pinned
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _num(vals, table="silver_futures_eod", metric="settle", commodity="corn",
         period=None, unit=None, status=None) -> dict:
    return {"query": {"table": table, "metric": metric, "commodity": commodity,
                      "period": period, "asof": "2026-06-05"},
            "rows": [{"value": v, "period": period, "known_date": "2026-06-05", "unit": unit}
                     for v in vals],
            "status": status}


# -- BLOCKERS 1+2: every citation-handle FORM is masked before magnitude extraction ---------------------

def test_an_E_handle_index_is_not_a_stated_magnitude():
    """BLOCKER 1. The D-DT scaffold (LIVE, serving rev 78) splices `[E<k>]` episode handles into
    `mechanism` AFTER the dedup pass and BEFORE the footer build, so on the hybrid lane `_stated_values`
    read every episode index as a figure the reader stated -- and the completion pass minted a footer row
    for any served value that happened to BE that integer. Indices 1..30 collide with real row values
    (MMT, $/bu, stocks-to-use, pct-of-OI) constantly."""
    body = ("## Episodes\n"
            "- Jun 2012 -- us_corn_belt: the dated item [E7] recorded 2012-06-14\n"
            "- Sep 2008 -- macro_shock: the dated item [E12] recorded 2008-09-15\n\n"
            "CBOT corn settled at 446 US cents [N1].")
    assert list(orc._stated_values(body)) == [446.0]
    st = {"tldr": "Crush margins are compressing.", "mechanism": body, "sources": []}
    blk = an._cited_sources_block(st, _VR, [
        _num([446.0]),
        _num([12.0, 88.5], "silver_psd", "exports_mmt", "soybeans", "MY2026", "MMT"),
        _num([7.0], "silver_wasde", "avg_farm_price", "corn", "MY2026", "USD/bu")])
    assert "exports_mmt" not in blk and "avg_farm_price" not in blk


def test_a_grouped_or_ranged_N_token_leaks_no_member_index():
    """BLOCKER 2, same root and the same one-token fix. Models write `[N1, N2]` and `[N1-N6]` despite the
    prompt ban -- `answer._N_HANDLE_RX`, D-PQ HANDLE-2 and open task #46 all exist because they do -- and
    the old solitary-only scrub shed their MEMBER indices as magnitudes."""
    assert list(orc._stated_values("Corn settled at 446 US cents [N1, N2].")) == [446.0]
    assert list(orc._stated_values("Balances tightened across the board [N1-N4].")) == []
    assert list(orc._stated_values("Stocks fell to 1.42 [N1-N6] on the month.")) == [1.42]
    assert list(orc._stated_values("A [N3b] B [E12c] C [n7] D [12].")) == []
    st = {"tldr": "", "mechanism": "Corn at 446 and beans at 1520 US cents [N1, N2].", "sources": []}
    blk = an._cited_sources_block(st, _VR, [
        _num([446.0]), _num([1520.0], commodity="soybeans"),
        _num([2.0, 87.4], "silver_wasde", "stocks_to_use", "corn", "MY2026")])
    assert "stocks_to_use" not in blk


def test_the_handle_mask_leaves_real_figures_and_the_old_scrubs_alone():
    """Polarity for BLOCKERS 1+2: widening the handle token must not eat prose the extractor was already
    reading correctly, and every pre-existing scrub class still fires."""
    assert list(orc._stated_values("Gas printed 15.17 USD/mmbtu [N1] on 2026-06-01, up from 14.9 [N2].")) \
        == [15.17, 14.9]
    assert list(orc._stated_values("Published June 1, 2025; MY2024/25; 60-kg bags; 14 months old.")) == []


# -- BLOCKER 3 + MAJOR 4: the reader-precision arm carries a RELATIVE CEILING ---------------------------

def test_the_reader_precision_arm_refuses_a_far_off_row():
    """BLOCKER 3. `d=0` opened a FLAT +-0.5 window with no relative floor, so at the magnitudes this estate
    actually serves the verifier certified tens-of-percent-wrong numbers -- and `_num_backed` is the MERGED
    ALL-ROWS backstop, so a 1-dp claim became backed by anything within +-0.05 anywhere in the turn.
    'strip -> keep only' is no defence when the keep is a WRONG number."""
    stu = {"query": {"table": "silver_wasde", "metric": "stocks_to_use", "commodity": "corn"},
           "rows": [{"value": 1.49}], "status": None}
    assert vf._check_number_handle("The stocks-to-use ratio stands at 1 [N1].", 1, [stu]) \
        == "number_mismatch"
    assert not vf._num_backed(1.0, [0.51], dec=0)          # 96% relative error
    assert not vf._num_backed(1.0, [1.49], dec=0)          # 33%
    assert not vf._num_matches([2.0], [2.49], [0])         # 25%
    assert not vf._num_backed(0.3, [0.34], dec=1)          # 12%, and vs the merged all-rows pool


def test_the_relative_ceiling_still_admits_both_real_gate3_rows():
    """The ceiling is SIZED against the defect the arm exists for: the two measured gate-3 pink-sheet
    z-scores are a 1.2% and a 2.4% relative gap, and both must stay admitted or FIX B is inert."""
    assert vf._reader_precision_match(0.31, abs(_GAS_Z), 2)     # 1.19%
    assert vf._reader_precision_match(0.20, abs(_UREA_Z), 2)    # 2.42%
    assert abs(abs(_GAS_Z) - 0.31) / 0.31 < vf._READER_REL_CEILING
    assert abs(abs(_UREA_Z) - 0.20) / 0.20 < vf._READER_REL_CEILING


def test_the_precision_incentive_is_symmetric():
    """MAJOR 4. '1' and '1.0' are the SAME claim. Pre-fix the vaguer spelling was certified and the precise
    one stripped against the identical row -- an instrument that rewards writing fewer significant figures.
    Both must now strip."""
    stu = {"query": {"table": "silver_wasde", "metric": "stocks_to_use", "commodity": "corn"},
           "rows": [{"value": 1.49}], "status": None}
    a = vf._check_number_handle("The ratio stands at 1 [N1].", 1, [stu])
    b = vf._check_number_handle("The ratio stands at 1.0 [N1].", 1, [stu])
    assert a == b == "number_mismatch"
    assert not vf._num_matches([1.0], [1.49], [0]) and not vf._num_matches([1.0], [1.49], [1])


def test_the_ceiling_leaves_every_cycle6_rounding_pin_standing():
    """Polarity for BLOCKER 3: every pair the arm was built to accept is inside 3%, so the ceiling removes
    the d=0 flat-window class and nothing else."""
    assert vf._reader_precision_match(4.2, 4.24, 1)      # 0.9%
    assert not vf._reader_precision_match(4.3, 4.24, 1)  # outside the window, as before
    assert vf._reader_precision_match(446.0, 445.6, 0)   # 0.09%
    assert not vf._reader_precision_match(400.0, 446.0, 0)


# -- MAJOR 5: the percent fence reads the NUMERAL's syntax, not the CALL's type -------------------------

def test_a_percent_CHANGE_never_names_a_percent_LEVEL_row():
    """MAJOR 5. The un-fence was per CALL, so one percent-denominated call made EVERY percent numeral in
    the answer a candidate name for its rows -- and 'down 2.1% on the week' minted `mm_pct_oi = 2.1` off a
    week-on-week CHANGE. Percent-change-vs-percent-level is the densest category error in this domain."""
    # CYCLE-7: three rows (so the headline is neither of the two under test) and the call is marked in the
    # prose, which rule (1) now requires; the percent question itself is unchanged.
    cot = _num([99.0, 15.7316, 2.1], "silver_cot", "mm_pct_oi", "corn", "2026-06-01",
               "pct of OI (signed)")
    sv = orc._stated_values("Per the COT [N1], managed money holds 15.7% of open interest, "
                            "down 2.1% on the week.")
    assert sv.percent == (15.7, 2.1) and sv.percent_level == (15.7,)
    labels = [c.label for c in cit.prose_completion_citations([cot], sv, seen=set(), cited={1})]
    assert any("= 15.7316 " in x for x in labels)          # the LEVEL still mints
    assert not any("= 2.1 " in x for x in labels)          # the CHANGE never does
    # the same two clauses in the reviewer's own spelling, each standing alone
    mint = lambda p: [c.label for c in cit.prose_completion_citations(                # noqa: E731
        [cot], orc._stated_values(p), seen=set(), cited={1})]
    assert mint("Per the COT [N1], managed money holds 15.7 percent of open interest.") == \
        ["COT mm_pct_oi corn MY2026-06-01 = 15.7316 pct of OI (signed)"]
    assert mint("Per the COT [N1], positioning fell, down 2.1 percent on the week.") == []


def test_the_change_cue_reads_only_the_numerals_own_context():
    """The fence is per numeral and cue-adjacent: a level verb keeps its numeral, a change verb (with the
    hedges models write between the two) drops only its own."""
    lvl = orc._stated_values("Share stands at 15.7 percent; it holds 12.0% of OI; at 9.5%.")
    assert lvl.percent_level == (15.7, 12.0, 9.5)
    chg = orc._stated_values("rose 4.1%, fell by 2.2 percent, up another 1.3%, versus 8.8%.")
    assert chg.percent_level == ()


def test_the_numbers_only_lane_percent_delta_is_refusal_side_only():
    """The same fence rides `extra_number_citations` (the cycle-5 lane). `.percent_level` is a SUBSET of
    `.percent`, so that lane can only ever mint fewer extra rows than it did -- never more -- and the
    cycle-5 motivating fabrication stays refused by both conditions."""
    cot = _num([15.7316, 2.1], "silver_cot", "mm_pct_oi", "corn", "2026-06-01", "pct of OI (signed)")
    sv = orc._stated_values("Managed money holds 15.7% of open interest, down 2.1% on the week.")
    vals = [c.value for c in cit.extra_number_citations(cot, 1, sv)]
    assert "2.1" not in vals
    price = _num([2.1, 4.4], "silver_wasde", "avg_farm_price", "corn", "MY1994/95", "USD/bu")
    assert cit.extra_number_citations(price, 1, orc._stated_values("down 2.1% year on year")) == []


# -- MEDIUM 6: the clone drop lives on the prose side, and ONLY there -----------------------------------

def test_cited_sources_block_alone_never_dangles_a_marker():
    """MEDIUM 6. The footer-side skip dropped a clone's row on this function's OWN authority -- but every
    index it could call a clone is an index the PROSE still carries (`prose_n` is where the map comes
    from), so the skip re-minted exactly the dangling-marker defect D-PQ HANDLE-4 abolishes. Latent on the
    two production call sites because the prose pass runs first; a loaded gun for any other caller. The
    drop is now the prose pass's alone."""
    st = {"tldr": "Corn settled at 446 [N1].",
          "mechanism": "The December board printed 446 US cents [N2].", "sources": []}
    blk = an._cited_sources_block(st, _VR, [_settle(), _settle()])
    assert {int(x) for x in re.findall(r"^\[N(\d+)\] ", blk, re.M)} == {1, 2}


def test_the_prose_pass_is_still_the_single_mechanism_end_to_end():
    """Polarity for MEDIUM 6: run the passes in production order and the clone still leaves BOTH the prose
    and the footer -- the fix removes a second, wrong mechanism, not the de-dup itself."""
    calls = [_settle(), _settle()]
    st = {"tldr": "Corn settled at 446 [N1].",
          "mechanism": "The December board printed 446 US cents [N2].", "sources": []}
    assert an._dedup_number_handles(st, calls) == 1
    assert "[N2]" not in st["mechanism"] and "[N1]" in st["mechanism"]
    blk = an._cited_sources_block(st, _VR, calls)
    assert {int(x) for x in re.findall(r"^\[N(\d+)\] ", blk, re.M)} == {1}


# -- LOW 9: the compiled predicate production actually runs is pinned equivalent to the named one -------

def test_the_compiled_matcher_is_equivalent_to_the_named_predicate():
    """LOW 9. `_match_candidates` runs `_matcher`, not `_row_matches_value` -- so the cycle-5 pins were
    pinning a function the estate no longer executes. Pin the two forms equal across the grid that spans
    both arms (2-dp bucket, reader-precision window, the relative fence, and the refusals)."""
    mags = [4.0, 0.3, 35763.0, 446.0, 15.17, 1.0]
    hit = cit._matcher(mags)
    grid = [4.0, 4.15, 4.24, 4.4, 3.999, 0.3, 0.34, 0.30632, 35763.0, 35763.1, 35763.9,
            446.0, 445.6, 447.0, 15.17, 15.1712, 1.0, 1.49, 0.51, 0.0, -4.0, -35763.1,
            "35,763.1", "not a number", None]
    for v in grid:
        assert hit(v) is cit._row_matches_value(v, mags), f"divergence on {v!r}"
    assert hit(35763.1) and not hit(4.4) and not hit(1.49)
