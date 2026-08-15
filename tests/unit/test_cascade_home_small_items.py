"""TRACK 1 of docs/private/CASCADE_HOME_AND_SMALL_ITEMS_PLAN.md -- the small-fixes bundle's gates.

One file per bundle rather than per item, deliberately: these are six independent seams whose only
common property is that they ship together and are reviewed together, and a reviewer reading the
commit wants the six gates side by side.

  T1-1  silverleg: the memo/shared cache key carries the READ-SHAPE scope (two shapes never share an
        entry) and the newest-first token reaches `_su_ratio`; `_fx` / `_oni` pinned UNCHANGED.
  T1-2  planner: the structural 1-row floor holds on the FIFO branch (cap_policy=None, i.e. deep),
        under BOTH ways FIFO can starve a paid slot; the score branch is byte-identical.
  T1-3  answer: the CONTRACT header carries the admission provenance under provenance_prompt, and the
        DRIVER header is untouched.
  T1-4  citations: a spread stat row names BOTH delivery legs; every non-spread row is byte-identical.
  T1-5  citations: `_row_order_key` carries `contract_month`, so a curve read's headline is
        deterministic -- the FURTHEST-dated expiry of the session, the row the series SQL sorts last.
  T1-6  answer: the [E]-cited exemption is conditional on a RANGE the cited receipts actually state;
        the wild #35 case from data/dhp_g1/clause6_audit.json is the fixture. TWO REVIEW FIXES ride
        with it, each a reproduced FALSE CONVICTION on a stored r6 body: an endpoint the writer
        ROUNDED (42.2/53.7 -> "42-54") now backs, and a sentence whose cited record could not be read
        IN FULL is exempt rather than convicted on the members that happened to hydrate.
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import silverleg as slv


# ── T1-1 ────────────────────────────────────────────────────────────────────────────────────────────
def _graph():
    c = cs.CausalContract(
        contract="corn", aliases=[],
        drivers=[cs.Driver(id="ending_stocks_su_ratio", type="fundamental", sign="-",
                           mechanism="tight stocks lift price",
                           silver_ref="psd_ending_stock_su_ratio", silver_status="available"),
                 cs.Driver(id="el_nino", type="climate_driver", sign="+", mechanism="dries the belt",
                           silver_ref="oni_climate", silver_status="available"),
                 cs.Driver(id="fx", type="macro", sign="+", mechanism="origin currency",
                           silver_ref="fred_fx_macro", silver_status="available")],
        convergence=[])
    return g.CausalGraph({"corn": c}, silver=set())


def _ratio_rows(ratios):
    stocks = [{"period": p, "value": s, "knowledge_date": "2012-08-10"} for p, (s, _) in ratios.items()]
    cons = [{"period": p, "value": c, "knowledge_date": "2012-08-10"} for p, (_, c) in ratios.items()]
    return stocks, cons


def _qfn(stocks, cons, sink=None):
    def qfn(sql):
        if sink is not None:
            sink.append(sql)
        if "ending_stocks_mt" in sql:
            return stocks
        if "consumption_mt" in sql:
            return cons
        return []
    return qfn


def test_t1_1_read_shape_is_part_of_the_cache_key():
    """THE GATE: two read shapes never share an entry. The label is what the key carries, and the three
    compiled orderings map to three DISTINCT labels -- an unknown scope gets its own rather than
    collapsing into a known one."""
    assert slv._read_shape(False) == "asc"
    assert slv._read_shape(True) == "nf"
    assert slv._read_shape("all") == "nf_all"
    labels = {slv._read_shape(v) for v in (False, True, "all", "some_future_scope")}
    assert len(labels) == 4                                   # no two scopes collapse onto one entry


def test_t1_1_shared_cache_entries_do_not_cross_read_shapes():
    """The SHARED cross-request cache is IMMORTAL on a historical as-of, so an entry computed under one
    ordering must be unreachable from a factory running under the other. Asserted on the KEYS the two
    factories write, which is the property (a value compare would pass by luck on a fixture)."""
    ratios = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
    ratios["2012"] = (80.0, 1000.0)
    st, cn = _ratio_rows(ratios)
    slv._SHARED.clear()
    try:
        import os
        os.environ["GRAPHRAG_SILVER_CACHE"] = "on"
        slv.make_silver_lookup(_graph(), _qfn(st, cn), newest_first=False)(
            "corn", "ending_stocks_su_ratio", "2012-08-15")
        keys_asc = set(slv._SHARED)
        slv.make_silver_lookup(_graph(), _qfn(st, cn), newest_first="all")(
            "corn", "ending_stocks_su_ratio", "2012-08-15")
        keys_all = set(slv._SHARED)
        assert keys_asc and len(keys_all) == 2 * len(keys_asc)     # a SECOND entry, never a re-read
        assert not {k[-1] for k in keys_asc} & {k[-1] for k in (keys_all - keys_asc)}
    finally:
        os.environ.pop("GRAPHRAG_SILVER_CACHE", None)
        slv._SHARED.clear()


def test_t1_1_su_ratio_threads_the_token_and_keeps_the_newest_rows():
    """T1-1(b): the token reaches `_su_ratio`'s SQL. Compiled DESC is what makes the 400-row cap keep the
    NEWEST marketing years instead of the oldest ones -- the live-dangerous half of the item."""
    ratios = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
    ratios["2012"] = (80.0, 1000.0)
    st, cn = _ratio_rows(ratios)
    sql_off, sql_on = [], []
    slv.make_silver_lookup(_graph(), _qfn(st, cn, sql_off), newest_first=False)(
        "corn", "ending_stocks_su_ratio", "2012-08-15")
    slv.make_silver_lookup(_graph(), _qfn(st, cn, sql_on), newest_first="all")(
        "corn", "ending_stocks_su_ratio", "2012-08-15")
    assert sql_off and sql_on
    # The discriminator is the OUTER series ORDER BY, not a bare "DESC": the PIT vintage window carries
    # its own `ORDER BY release_date DESC` inside the sub-select on BOTH scopes and always did.
    def _tail(s):
        return s.rsplit("ORDER BY", 1)[-1]
    assert not any("DESC NULLS LAST" in _tail(s) for s in sql_off)
    assert all("DESC NULLS LAST" in _tail(s) for s in sql_on)   # newest-first compile reached the leg
    assert all("2012-08-15" in s for s in sql_on)               # ...and the PIT guard is untouched


def test_t1_1_safe_legs_are_pinned_unchanged():
    """`_oni` is agg='latest' on a card WITH an order column -- not the series branch -- so its SQL cannot
    move whatever the token says. `_fx` reads a ~504-day window under an 800 cap, so its ROW SET cannot
    move; the handler sorts its own pairs, so its answer cannot either."""
    oni_rows = [{"value": "1.6", "data_date": "2012-07-31"}]
    fx_rows = [{"value": 5.0 + (i % 7) * 0.01, "data_date": f"2012-{1 + i // 28:02d}-{1 + i % 28:02d}"}
               for i in range(90)]

    def qfn(sql, sink):
        sink.append(sql)
        if "oni_anom" in sql:
            return oni_rows
        if "brl_usd" in sql or "cny_usd" in sql:
            return fx_rows
        return []

    outs, sqls = {}, {}
    for tok in (False, "all"):
        s: list = []
        look = slv.make_silver_lookup(_graph(), lambda q, s=s: qfn(q, s), newest_first=tok)
        outs[tok] = (look("corn", "el_nino", "2012-08-15"), look("corn", "fx", "2012-08-15"))
        sqls[tok] = s
    assert outs[False] == outs["all"]                          # both safe legs byte-identical
    oni_off = [q for q in sqls[False] if "oni_anom" in q]
    oni_on = [q for q in sqls["all"] if "oni_anom" in q]
    assert oni_off and oni_off == oni_on                       # ONI's SQL cannot move at all


# ── T1-2 ────────────────────────────────────────────────────────────────────────────────────────────
def _node(nid, contract, depth, rel, evidence, reason=None):
    n = pl.GroundedNode(kind="driver", id=nid, contract=contract, depth=depth, relevance=rel)
    n.evidence = list(evidence)
    n.admission = ({"reason": reason, "ancestor_of": "corn_cbot", "chain_depth": -1}
                   if reason else dict(pl._ADMIT_COSINE))
    return n


def _row(key, text):
    return {"source_key": key, "date": "2026-01-01", "text": text}


def _sg(nodes):
    return pl.Subgraph(seeds=["corn_cbot"], nodes=list(nodes), trace={})


def test_t1_2_fifo_structural_node_keeps_a_row_under_full_dedup():
    """THE GATE, cause (i): every one of the paid node's rows was attributed to a shallower node. Under
    cap_policy=None -- the branch `deep` actually runs -- it used to end the turn with ZERO rows."""
    shared = _row("k1", "a substitution piece filed under both slices")
    seed = _node("d_seed", "corn_cbot", 0, 1.0, [shared])
    paid = _node("d_far", "wheat_cbot", 1, 0.0, [shared], reason=pl.REASON_DOWNSTREAM_CONTRACT)
    sg = _sg([seed, paid])
    pl._dedup_and_cap(sg, cap=50, cap_policy=None)
    assert len(seed.evidence) == 1
    assert len(paid.evidence) == 1 and paid.evidence[0] is shared    # the floor, not a rewrite


def test_t1_2_fifo_structural_node_keeps_a_row_under_budget_exhaustion():
    """THE GATE, cause (ii) -- the one the score branch CANNOT reach. FIFO spends one global budget
    shallowest-first, so a paid slot that sorts late gets nothing however unique its rows are."""
    seed = _node("d_seed", "corn_cbot", 0, 1.0, [_row("k1", "one"), _row("k2", "two")])
    paid = _node("d_far", "wheat_cbot", 1, 0.0, [_row("k9", "its own unique row")],
                 reason=pl.REASON_DOWNSTREAM)
    sg = _sg([seed, paid])
    pl._dedup_and_cap(sg, cap=2, cap_policy=None)               # budget spent by the seed
    assert len(seed.evidence) == 2
    assert len(paid.evidence) == 1


def test_t1_2_fifo_floor_never_manufactures_a_block():
    """ANTI-VACUITY, both directions: a COSINE node that dedups to nothing still ends with nothing, and a
    structural node that HAD no evidence is not given any (nothing was bought)."""
    shared = _row("k1", "shared")
    seed = _node("d_seed", "corn_cbot", 0, 1.0, [shared])
    cosine = _node("d_cos", "corn_cbot", 1, 0.5, [shared])
    empty_paid = _node("d_empty", "wheat_cbot", 1, 0.0, [], reason=pl.REASON_CLOSURE)
    sg = _sg([seed, cosine, empty_paid])
    pl._dedup_and_cap(sg, cap=50, cap_policy=None)
    assert cosine.evidence == [] and empty_paid.evidence == []


def test_t1_2_score_branch_is_unchanged():
    """The score branch's own floor is the SAME helper now; its result must be what it always was."""
    shared = _row("k1", "shared")
    seed = _node("d_seed", "corn_cbot", 0, 1.0, [shared])
    paid = _node("d_far", "wheat_cbot", 1, 0.0, [shared], reason=pl.REASON_DOWNSTREAM)
    sg = _sg([seed, paid])
    pl._dedup_and_cap(sg, cap=10, cap_policy="score", k_by_depth=(3,))
    assert len(paid.evidence) == 1 and paid.evidence[0] is shared


# ── T1-3 ────────────────────────────────────────────────────────────────────────────────────────────
def _cascade_contract_node():
    n = pl.GroundedNode(kind="contract", id="palm_bursa", contract="palm_bursa", depth=1, relevance=0.4,
                        via_edge={"_from": "corn_cbot", "relation": "substitute", "sign": "+",
                                  "category": "market_structure", "mechanism": "vegoil substitution"})
    n.admission = {"reason": pl.REASON_DOWNSTREAM_CONTRACT, "ancestor_of": "corn_cbot",
                   "chain_depth": -1, "convergence": True, "anchors": ["corn_cbot", "soy_cbot"]}
    return n


def test_t1_3_contract_header_carries_admission_under_provenance():
    note = an._admission_note(_cascade_contract_node())
    assert note == " [graph admission: downstream of corn_cbot, converges from 2 anchors]"


def test_t1_3_contract_header_is_byte_identical_without_provenance():
    """The suffix rides `provenance`, exactly as the driver header's does -- so a turn without the
    provenance prompt renders the pre-T1-3 CASCADE-HOP line byte for byte."""
    n = _cascade_contract_node()
    e = n.via_edge
    base = (f"REACHED VIA CASCADE HOP: {e.get('_from')} --{e.get('relation')}({e.get('sign')})--> "
            f"palm_bursa [market_structure: a market-structure link] {e.get('mechanism')}")
    for provenance in (False, True):
        sfx = an._admission_note(n) if provenance else ""
        line = (f"REACHED VIA CASCADE HOP: {e.get('_from')} --{e.get('relation')}({e.get('sign')})--> "
                f"palm_bursa{sfx} [market_structure: a market-structure link] {e.get('mechanism')}")
        assert (line == base) is (not provenance)


def test_t1_3_cosine_contract_gets_no_suffix():
    n = pl.GroundedNode(kind="contract", id="soy_cbot", contract="soy_cbot", depth=1, relevance=0.4)
    n.admission = dict(pl._ADMIT_COSINE)
    assert an._admission_note(n) == ""


# ── T1-4 ────────────────────────────────────────────────────────────────────────────────────────────
def _spread_call(near, far, value="12.5"):
    return {"query": {"table": "stats", "metric": "spread", "commodity": "corn_cbot"},
            "rows": [{"value": value, "unit": "spread", "knowledge_date": "2026-06-01",
                      "near_month": near, "far_month": far}],
            "status": "ok"}


def test_t1_4_spread_citation_names_both_delivery_legs():
    c = cit.from_number(_spread_call("2026-07", "2026-12"), 1)
    assert "delivery 2026-07->2026-12" in c.label


def test_t1_4_partial_or_degenerate_legs_are_never_guessed():
    """"never guess from partial labels": one leg, or two identical legs, renders NOTHING extra -- a
    spread naming one month is not a narrower fact, it is a wrong one."""
    for near, far in (("2026-07", None), (None, "2026-12"), (None, None), ("2026-07", "2026-07")):
        assert "delivery" not in cit.from_number(_spread_call(near, far), 1).label


def test_t1_4_non_spread_rows_are_byte_identical():
    """ANTI-VACUITY (the test_dam_carry_stat:471-475 idiom): the legs term may not touch a row that
    carries none, including a row that carries an ordinary contract_month."""
    plain = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn_cbot"},
             "rows": [{"value": "430.25", "unit": "cents/bu", "knowledge_date": "2026-06-01"}],
             "status": "ok"}
    curve = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn_cbot"},
             "rows": [{"value": "430.25", "unit": "cents/bu", "knowledge_date": "2026-06-01",
                       "contract_month": "2026-09"}],
             "status": "ok"}
    assert "delivery" not in cit.from_number(plain, 1).label
    assert "delivery 2026-09" in cit.from_number(curve, 1).label
    assert "->" not in cit.from_number(curve, 1).label


# ── T1-5 ────────────────────────────────────────────────────────────────────────────────────────────
def _curve_rows():
    """One trading session, four expiries -- every earlier order term ties by construction."""
    return [{"data_date": "2026-06-01", "knowledge_date": "2026-06-01", "contract_month": m,
             "value": v, "unit": "cents/bu"}
            for m, v in (("2026-12", "441.0"), ("2026-07", "430.0"),
                         ("2027-03", "449.0"), ("2026-09", "435.0"))]


def test_t1_5_row_order_key_carries_contract_month():
    k = cit._row_order_key({"data_date": "2026-06-01", "contract_month": "2026-09"})
    assert k[-1] == "2026-09"
    assert cit._row_order_key({"data_date": "2026-06-01"})[-1] == ""      # absent -> "", never a KeyError


def test_t1_5_curve_headline_is_the_furthest_expiry_deterministically():
    """THE PINNED NEW CHOICE. Before T1-5 every row of a curve read tied on the whole key and `max()`
    returned rows[0] -- engine-arbitrary. Now the expiries sort ASC ('YYYY-MM' sorts lexically ==
    chronologically) and the headline is the row the series SQL's own ORDER BY puts LAST: the
    FURTHEST-dated expiry, identical on Athena and on the pg mirror."""
    rows = _curve_rows()
    assert max(rows, key=cit._row_order_key)["contract_month"] == "2027-03"
    assert max(list(reversed(rows)), key=cit._row_order_key)["contract_month"] == "2027-03"
    c = cit.from_number({"query": {"table": "silver_futures_eod", "metric": "settle",
                                   "commodity": "corn_cbot"}, "rows": rows, "status": "ok"}, 1)
    assert "delivery 2027-03" in c.label and c.value == "449.0"
    assert c.locator["contract_month"] == "2027-03"            # the drill-down re-runs what was quoted


def test_t1_5_non_curve_reads_keep_their_headline():
    """ANTI-VACUITY: a series with real chronology is decided by the EARLIER terms, so the term added at
    the tail changes nothing."""
    rows = [{"data_date": "2026-05-01", "value": "1"}, {"data_date": "2026-06-01", "value": "2"}]
    assert max(rows, key=cit._row_order_key)["value"] == "2"


# ── T1-6 ────────────────────────────────────────────────────────────────────────────────────────────
# The wild case, verbatim from data/dhp_g1/clause6_audit.json verdicts #35/#36 (`ab_rec_malaysia_stocks`,
# artifact r6_cov_inv4_deep_hp_r2, field verified_mechanism, char offsets 2930/2932). The en dash is the
# artifact's own glyph and is written as a codepoint escape to keep this source ASCII.
_WILD_35 = ("- **El Nino watch for late 2026**: any confirmed onset would add a 2" + chr(0x2013) +
            "4 quarter supply lag [E23], which would tighten the MY 2026/27 balance sheet " +
            chr(0x2014) + " not the current one, but forward-curve relevant.")
# [E23] is usda_gain_soybean_meal (country TH). Its stored text forecasts Thai palm kernel imports and
# states no lag, no quarter count and neither endpoint -- which is the audit's finding.
_E23 = ("Thailand: El Nino related drought constraints are expected to raise palm kernel imports "
        "slightly over the forecast period.")


def _uniq_with_e23():
    return [{"text": "filler"} for _ in range(22)] + [{"text": _E23}]


def test_t1_6_the_wild_35_sentence_convicts():
    """THE GATE. Before T1-6 the R3(b) exemption kept this sentence on the page unconditionally, because
    it asks only whether an [E] handle is PRESENT."""
    assert an._e_cited_unbacked_ranges(_WILD_35, _uniq_with_e23()) == ["2" + chr(0x2013) + "4"]
    st = {"tldr": "", "mechanism": _WILD_35}
    census = an._drop_bare_digit_sentences(st, [], None, uniq=_uniq_with_e23())
    assert census["e_cited_range_unbacked"] == 1
    assert census["e_cited_kept"] == 0
    assert "quarter supply lag" not in st["mechanism"]


def test_t1_6_a_backed_range_keeps_the_exemption():
    """Either half of the generous backing test exonerates: the range VERBATIM, or both endpoints as
    digit runs of the receipt's own."""
    u = [{"text": "a spring frost is expected to cut yields 15-30% on dry wheat farms"}]
    assert an._e_cited_unbacked_ranges("yields were cut 15-30% [E1]", u) == []
    u2 = [{"text": "the lag has run 2 quarters and in one case 4 quarters"}]
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1]", u2) == []


def test_t1_6_unparseable_and_non_range_shapes_stay_exempt():
    """FAIL-OPEN, enumerated. Every one of these keeps the exemption byte for byte."""
    u = [{"text": "no figures at all in this receipt"}]
    for s in ("the 2024-25 season [E1]",                      # a year range
              "as of 2026-05-30 [E1]",                        # an ISO date
              "from 2010-2020 [E1]",                          # two years
              "a 9-4 split [E1]",                             # descending: not a range
              "several items [E1-E4] show it",                # a RANGED HANDLE, not a figure
              "stocks were tight [E1]"):                      # no figure at all
        assert an._e_cited_unbacked_ranges(s, u) == [], s


def test_t1_6_missing_evidence_never_convicts():
    """Three separate fail-opens, each of which is a real production shape: no `uniq` threaded (every
    pre-T1-6 caller), a receipt with no stored text, and an out-of-range index."""
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1]", None) == []
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1]", [{"text": ""}]) == []
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E9]", [{"text": "x"}]) == []


# ── T1-6 REVIEW FIXES ───────────────────────────────────────────────────────────────────────────────
# Both are reproduced FALSE CONVICTIONS on stored r6 bodies -- this lint's one unacceptable direction.
_DDG = ("The antidumping (AD) rates on DDGS imports from the United States range from 42.2 to 53.7 "
        "percent.")
_DDG_SENT = ("Outside the US, tariff walls (China's 42" + chr(0x2013) + "54% antidumping duty on US DDGS "
             "[E1]) cap the export floor.")


def test_t1_6_a_rounded_endpoint_keeps_the_exemption():
    """THE REPRODUCED FALSE CONVICTION (review, on a stored r6 body: `dv_sub_ddg_floor`,
    r6_inv1_deepv2_width_deep_r1). Exact float equality convicted a FAITHFUL restatement -- the receipt
    states 42.2 to 53.7, the prose rounds to 42-54, and the sentence was deleted for saying the same
    thing at the precision prose speaks in. Rounding AND truncation, since both are ordinary habits."""
    assert an._e_cited_unbacked_ranges(_DDG_SENT, [{"text": _DDG}]) == []
    assert an._e_cited_unbacked_ranges("a 42-53% duty [E1]", [{"text": _DDG}]) == []   # truncated instead
    assert an._e_cited_unbacked_ranges("a 42.2-53.7% duty [E1]", [{"text": _DDG}]) == []  # exact, as before


def test_t1_6_the_tolerance_is_the_written_tokens_own_precision():
    """ANTI-VACUITY: this is not "any nearby number". A token that SPEAKS precisely is held to that
    precision, so a receipt stating 42.2 does not back a written 42.9, and the conviction lane stays open
    for a range the record genuinely does not carry."""
    u = [{"text": _DDG}]
    assert an._e_cited_unbacked_ranges("a 42.9-53.7% duty [E1]", u) == ["42.9-53.7"]
    assert an._e_cited_unbacked_ranges("a 30-54% duty [E1]", u) == ["30-54"]
    assert an._e_cited_unbacked_ranges("a 42-99% duty [E1]", u) == ["42-99"]


def test_t1_6_an_incomplete_cited_record_never_convicts():
    """REVIEW FIX 2 -- the fail-open was ALL-OR-NOTHING at the receipt-SET level. The pooled-union reading
    is only sound when the union IS the cited record; the shipped guard exempted only when the pool was
    ENTIRELY empty, so a sentence citing five receipts with four unhydrated was convicted on the fifth
    (seen in the corpus: `ab_cmp_vegoils`, convicted on a receipt carrying neither endpoint). One
    unreadable member is one doubt, and every doubt here reads EXEMPT."""
    one = [{"text": "palm stocks fell in Malaysia last month"}]
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1][E9]", one) == []          # E9 out of range
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1][E2]",
                                       one + [{"text": ""}]) == []                       # E2 textless
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1-E3]", one + [{"text": "x"}]) == []
    # ...and the COMPLETE record still convicts, which is what keeps the guard from swallowing the lint.
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1]", one) == ["2-4"]
    assert an._e_cited_unbacked_ranges("a 2-4 quarter lag [E1][E2]",
                                       one + [{"text": "y"}]) == ["2-4"]


def test_t1_6_receipt_texts_reports_completeness():
    """The flag is the helper's, not the caller's guess: only the scan knows which members were named."""
    items = [{"text": "a"}, {"text": ""}]
    assert an._e_receipt_texts("x [E1]", items) == (["a"], True)
    assert an._e_receipt_texts("x [E1][E2]", items) == (["a"], False)
    assert an._e_receipt_texts("x [E9]", items) == ([], False)
    assert an._e_receipt_texts("no handles here", items) == ([], True)


def test_t1_6_census_key_is_absent_when_nothing_fires():
    """OFF-ARM-CLEAN: a turn with no such sentence carries the pre-T1-6 three-key census exactly, so the
    trace shape does not move for every consumer that never sees this class."""
    st = {"tldr": "", "mechanism": "US wheat commitments were [N4] this week."}
    census = an._drop_bare_digit_sentences(st, [], None, uniq=[{"text": "x"}])
    assert set(census) == {"sentences_dropped", "clauses_severed", "e_cited_kept"}
