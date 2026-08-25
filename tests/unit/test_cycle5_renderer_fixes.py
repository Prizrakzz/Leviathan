"""CYCLE-5 (2026-08-07) renderer/instrument pins -- the four deterministic fixes gate-2 of the D-CW/D-PQ
probe reduced to.

Every fixture in this file is REPLAYED FROM GATE-2 EVIDENCE, not invented: the farm-price shape from
`dcw_farm_price_vintage` (both passes), the un-stamped families from `dcw_macro_on_soy` /
`dcw_iod_beside_oni`, and the orphaned fragments quoted verbatim out of the two report bodies. The
polarity pins (byte-identical output when the defect is absent) matter as much as the positive ones:
gate-3 must stay comparable to gate-2 on every metric that already existed.
"""
from __future__ import annotations

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag import verify as vf
from leviathan.graphrag.numbers import cascade as cq


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 1 -- FOOTER COMPLETENESS FOR MULTI-ROW SERVES
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _wasde_farm_price_call() -> dict:
    """The `dcw_farm_price_vintage` serve, reconstructed to its measured shape: ONE silver_wasde
    avg_farm_price lookup returning 35 marketing-year rows off the 2026-07-10 release, including the two
    the prose stated (4.24 MY2024/25 actual, 4.15 MY2025/26 estimate) and the one the footer headlined
    (4.4 MY2026/27 projection -- the newest period, hence `_row_order_key`'s max)."""
    rows = []
    for i in range(32):                                   # 32 filler MYs + the 3 real ones = 35 rows
        y = 1992 + i
        rows.append({"value": round(2.0 + i * 0.05, 2), "unit": "$/bu", "period": f"{y}/{str(y + 1)[2:]}",
                     "knowledge_date": "2026-07-10", "revision_stamp": "actual"})
    rows += [
        {"value": 4.24, "unit": "$/bu", "period": "2024/25", "knowledge_date": "2026-07-10",
         "revision_stamp": "actual"},
        {"value": 4.15, "unit": "$/bu", "period": "2025/26", "knowledge_date": "2026-07-10",
         "revision_stamp": "estimate"},
        {"value": 4.4, "unit": "$/bu", "period": "2026/27", "knowledge_date": "2026-07-10",
         "revision_stamp": "projection"},
    ]
    return {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "corn",
                      "country": "united_states", "asof": "2026-08-07"},
            "rows": rows, "status": "ok"}


# the answer body gate-2 actually shipped for this row
_FARM_PRICE_PROSE = (
    "The USDA is carrying **$4.15 per bushel** for US corn in the 2025/26 marketing year, as an "
    "**estimate** (projection) published on 2026-07-10.\n\n"
    "For the completed 2024/25 season, the actual figure is **$4.24 per bushel**, published 2026-07-10.")


def test_multi_row_serve_footnotes_every_stated_row():
    call = _wasde_farm_price_call()
    cits = cit.unify(None, [call], stated=orc._stated_values(_FARM_PRICE_PROSE))
    body = cit.render(cits)
    lines = body.split("\n")
    # the headline row is FIRST and unchanged in SUBSTANCE -- PA-8(a)/PA-10(a) (2026-08-25) rebuilt the two
    # halves this very serve indicted: the metric speaks the card's analyst label ("average farm price", the
    # `_metric_display` path) instead of the raw slug, and the line now STATES that 35 rows were served with
    # one shown -- the abundance marker this incident is the motivating case for.
    assert lines[0].startswith("[N1] USDA WASDE average farm price corn united_states = 4.4 $/bu")
    assert "35 rows served" in lines[0] and "newest shown" in lines[0]
    assert "[known 2026-07-10]" in lines[0]
    # ...and BOTH stated sibling-period values now have a row of their own, vintage-stamped
    assert any(x.startswith("[N1b]") and "4.24" in x and "MY2024/25" in x and "(actual)" in x
               and "[known 2026-07-10]" in x for x in lines), body
    assert any(x.startswith("[N1c]") and "4.15" in x and "MY2025/26" in x and "(estimate)" in x
               and "[known 2026-07-10]" in x for x in lines), body


def test_headline_only_prose_renders_todays_footer_byte_for_byte():
    """THE POLARITY PIN. An answer that states only the headline figure must produce the pre-CYCLE-5
    footer exactly -- no extra rows, no reordering, not one byte of difference."""
    call = _wasde_farm_price_call()
    prose = "The USDA is carrying 4.4 $/bu for US corn."
    before = cit.render(cit.unify(None, [call]))
    after = cit.render(cit.unify(None, [call], stated=orc._stated_values(prose)))
    assert after == before
    assert after.count("\n") == 0                          # exactly one footer line


def test_extra_rows_do_not_consume_an_n_index():
    """A grouped footer must never renumber the answer: the model's prose cites [N2] for the SECOND call,
    so the extras of call 1 have to ride a letter suffix, not the next integer."""
    call = _wasde_farm_price_call()
    other = {"query": {"table": "silver_psd", "metric": "production_mt", "commodity": "corn",
                       "country": "United States", "period": 2025, "asof": "2026-08-07"},
             "rows": [{"value": 380.0, "unit": "MMT", "knowledge_date": "2026-03-10"}], "status": "ok"}
    cits = cit.unify(None, [call, other], stated=orc._stated_values(_FARM_PRICE_PROSE))
    ids = [c.id for c in cits]
    assert ids == ["N1", "N1b", "N1c", "N2"], ids
    assert vf._HANDLE.match("[N1b]")                        # the suffix shape the verifier already parses


def test_extra_rows_are_capped_and_deduped():
    """<=6 extras per call, and the same (value, period) on two vintages is ONE reader-facing fact."""
    rows = [{"value": 10.0 + i, "unit": "MMT", "period": f"20{10 + i}/{11 + i}",
             "knowledge_date": "2026-07-10"} for i in range(12)]
    rows += [{"value": 12.0, "unit": "MMT", "period": "2012/13", "knowledge_date": "2026-06-10"}]  # dup
    call = {"query": {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "corn",
                      "asof": "2026-08-07"}, "rows": rows, "status": "ok"}
    stated = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0]
    extras = cit.extra_number_citations(call, 1, stated)
    assert len(extras) == 6
    assert len({(c.value, c.label) for c in extras}) == 6


def test_extra_row_locator_reruns_the_same_call_scoped_to_the_row_period():
    call = _wasde_farm_price_call()
    extras = cit.extra_number_citations(call, 1, orc._stated_values(_FARM_PRICE_PROSE))
    for c in extras:
        assert c.locator["table"] == "silver_wasde" and c.locator["metric"] == "avg_farm_price"
        assert c.locator["commodity"] == "corn" and c.locator["asof"] == "2026-08-07"
        assert c.locator["period"] in ("2024/25", "2025/26")   # the ROW's period, not the query's (None)
        assert c.payload["query"]["period"] == c.locator["period"]
        assert len(c.payload["rows"]) == 1


def test_empty_and_single_row_and_zero_aggregate_serves_never_grow_extras():
    """Three classes that must stay silent: nothing served, one row served (the headline IS the serve),
    and the collapsed-zero ESR aggregate whose whole point is that it asserts no value."""
    q = {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "corn", "asof": "2026-08-07"}
    assert cit.extra_number_citations({"query": q, "rows": [], "status": "no_rows"}, 1, [4.15]) == []
    assert cit.extra_number_citations({"query": q, "rows": [{"value": 4.15}], "status": "ok"},
                                      1, [4.15]) == []
    # the EMPTY-2 collapsed-zero ESR aggregate: single-row by definition, so the `len(rows) < 2` fence is
    # what keeps the class that asserts NO value out of the footer -- pinned here so a later widening of
    # that fence has to answer for this row too.
    esr = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn",
                     "country": "China", "agg": "sum", "asof": "2026-08-07"},
           "rows": [{"value": 0.0, "unit": "1000 MT"}], "status": "ok"}
    assert cit._zero_aggregate(esr) is True
    assert cit.extra_number_citations(esr, 1, [0.0]) == []


def test_stated_values_is_the_verifiers_own_extractor():
    """FIX 1 leans on `_stated_values`; the verifier's mismatch count leans on the same call. If they ever
    fork, the caution banner and the footer start disagreeing about what the prose said."""
    prose = ("As of June 1, 2025 the 60-kg bag price was 453.1 USD/mt [N1], up from 2024/25 and more "
             "than 14 months old.\n1. first item")
    assert orc._stated_values(prose) == [453.1]
    nv = orc._verify_numbers_answer(prose, [{"query": {"metric": "x"},
                                             "rows": [{"value": "453.1"}]}])
    assert nv["stated"] == 1 and nv["mismatched"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 2 -- VINTAGE STAMPS ON PERIOD-SCOPED AND DERIVED ROWS
#
# Gate-2 measured 29/74 (pass 1) and 35/86 (pass 2) footer [N] rows with no `[known ...]` tail, the same
# families both passes. Two mint classes, both pinned below:
#   SYNTHETIC (cascade `_delta_call` / `_pace_synth` / `_price_call`) -- the source row's date existed and
#       was simply not copied onto the derived row.
#   YEAR_MONTH (silver_noaa_oni, silver_noaa_iod, gold_weather_z) -- the card declares no date column at
#       all, so the row's (year, month) IS its as-known identity and renders as 'YYYY-MM'.
# NO EXEMPTIONS REMAIN in the measured families: every gate-2 shape below now stamps.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_year_month_rows_stamp_from_their_own_year_and_month():
    """NOAA ONI / NOAA IOD / GOLD WEATHER Z -- the gate-2 `dcw_iod_beside_oni` shapes, verbatim."""
    for table, metric, unit in (("silver_noaa_iod", "dmi_value", "degC"),
                                ("silver_noaa_iod", "iod_dmi_3month_avg", "degC"),
                                ("silver_noaa_oni", "oni_anom", "degC"),
                                ("gold_weather_z", "drought_z", "z")):
        call = {"query": {"table": table, "metric": metric, "asof": "2026-08-07"},
                "rows": [{"value": -0.58, "unit": unit, "year": 2026, "month": 6}], "status": "ok"}
        c = cit.from_number(call, 1)
        assert c.date == "2026-06", (table, metric, c.date)
        assert "[known 2026-06]" in cit.render([c])


def test_year_month_fallback_never_fires_when_a_real_date_exists_or_the_row_is_not_a_month():
    assert cit._row_known_date({"knowledge_date": "2026-07-10", "year": 2026, "month": 6}) == "2026-07-10"
    assert cit._row_known_date({"data_date": "2026-07-10", "year": 2026, "month": 6}) == "2026-07-10"
    assert cit._row_known_date({"year": 2026}) is None            # a year alone is not an observation date
    assert cit._row_known_date({"year": 2026, "month": 13}) is None
    assert cit._row_known_date({"year": "nope", "month": "6"}) is None
    assert cit._row_known_date({}) is None


def test_year_month_stamp_does_not_mint_a_staleness_clause():
    """'YYYY-MM' is deliberately not parseable as a date, so the `(latest available X; as-of Y)` clause
    stays OFF for these rows -- a missed warning, never a false one."""
    call = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "asof": "2026-08-07"},
            "rows": [{"value": 0.98, "unit": "degC", "year": 2025, "month": 1}], "status": "ok"}
    assert "latest available" not in cit.from_number(call, 1).label


def test_psd_derived_legs_inherit_the_source_rows_vintage():
    """`dcw_macro_on_soy`: [N15] ending_stocks_mt_delta and [N16] _pct rendered with no stamp directly
    under [N14] ending_stocks_mt [known 2025-03-10]."""
    rec = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "soybeans",
                     "country": "United States", "period": 2024, "asof": "2026-08-07"},
           "rows": [{"value": 8.84, "unit": "MMT", "knowledge_date": "2025-03-10",
                     "release_date": "2025-03-10"}], "status": "ok"}
    row = {"metric": "ending_stocks_mt", "narrate_unit": "MMT"}
    for kind in ("delta", "pct", "era_diff"):
        call = cq._delta_call(rec, row, -0.479, 2, kind=kind)
        assert call["rows"][0]["knowledge_date"] == "2025-03-10"
        assert "[known 2025-03-10]" in cit.render([cit.from_number(call, 1)])


def test_pace_legs_inherit_the_source_rows_vintage():
    rec = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "asof": "2026-08-07"},
           "rows": [{"value": 0.51, "year": 2026, "month": 5}, {"value": 0.98, "year": 2026, "month": 6}],
           "status": "ok"}
    row = {"metric": "oni_anom", "narrate_unit": "degC"}
    call = cq._pace_synth(rec, row, 0.47, 1, kind="pace_change", unit="degC")
    assert (call["rows"][0]["year"], call["rows"][0]["month"]) == (2026, 6)     # the LATEST point
    assert cit.from_number(call, 1).date == "2026-06"


def test_farm_price_pair_legs_inherit_the_wasde_release_date():
    """`_price_call` mints a synthetic silver_wasde row; WASDE is a vintage table, so a pair rendering it
    with no `[known ...]` was the sharpest form of the defect (gate-2 [N24]/[N25], [N19]/[N20])."""
    src = {"value": 5.18, "unit": "$/bu", "knowledge_date": "2011-09-12"}
    call = cq._price_call("corn", "united_states", 5.18, "2010/11", "2013-06-01", unit="$/bu", src_row=src)
    assert call["rows"][0]["knowledge_date"] == "2011-09-12"
    assert "[known 2011-09-12]" in cit.render([cit.from_number(call, 1)])
    # ...and a caller that passes no source row keeps the pre-CYCLE-5 record byte for byte
    bare = cq._price_call("corn", "united_states", 5.18, "2010/11", "2013-06-01", unit="$/bu")
    assert bare["rows"] == [{"value": 5.18, "unit": "$/bu"}]


def test_gate2_iod_and_macro_call_shapes_render_zero_unstamped_number_rows():
    """The FIX-2 acceptance, run as the gate would read it: replay the two rows' call shapes and count
    footer lines with no `[known ...]` tail. Zero, no exemptions."""
    psd = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "soybeans",
                     "country": "United States", "period": 2024, "asof": "2026-08-07"},
           "rows": [{"value": 8.84, "unit": "MMT", "knowledge_date": "2025-03-10"}], "status": "ok"}
    calls = [
        psd,
        cq._delta_call(psd, {"metric": "ending_stocks_mt", "narrate_unit": "MMT"}, -0.479, 2, kind="delta"),
        cq._delta_call(psd, {"metric": "ending_stocks_mt", "narrate_unit": "MMT"}, -5.14, 2, kind="pct"),
        cq._delta_call(psd, {"metric": "ending_stocks_mt", "narrate_unit": "MMT"}, 0.138, 2,
                       kind="era_diff", period="MY2024->MY2025"),
        cq._price_call("soybeans", "united_states", 12.4, "2023/24", "2026-08-07", unit="$/bu",
                       src_row={"value": 12.4, "unit": "$/bu", "knowledge_date": "2026-07-10"}),
        {"query": {"table": "silver_noaa_iod", "metric": "dmi_value", "asof": "2026-08-07"},
         "rows": [{"value": -0.58, "unit": "degC", "year": 2026, "month": 6}], "status": "ok"},
        {"query": {"table": "silver_noaa_iod", "metric": "iod_dmi_3month_avg", "asof": "2026-08-07"},
         "rows": [{"value": -0.2133, "unit": "degC", "year": 2026, "month": 6}], "status": "ok"},
        {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "asof": "2026-08-07"},
         "rows": [{"value": 0.98, "unit": "degC", "year": 2026, "month": 6}], "status": "ok"},
        {"query": {"table": "gold_weather_z", "metric": "drought_z", "commodity": "corn",
                   "country": "United States", "asof": "2026-08-07"},
         "rows": [{"value": 1.00594, "unit": "z", "year": 2026, "month": 6}], "status": "ok"},
    ]
    lines = cit.render(cit.unify(None, calls)).split("\n")
    unstamped = [x for x in lines if "[known " not in x]
    assert unstamped == [], unstamped


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 3 -- ARTIFACT TRANSPARENCY (additive only)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _turn(calls: list, nv: dict | None = None) -> dict:
    return {"q": {"id": "dcw_farm_price_vintage"}, "secs": 1.0,
            "rubric": {"intent_ok": True, "cascade_asserts": None},
            "out": {"answer": _FARM_PRICE_PROSE, "intent": "numbers_only", "structured": None,
                    "evidence": [], "citations": [], "number_calls": calls,
                    "trace": ({"numbers_verifier": nv} if nv else {})}}


def test_served_rows_ride_the_per_answer_record():
    nv = {"stated": 2, "rows": 35, "mismatched": 0, "mismatch_values": []}
    rec = ev._per_answer_record(_turn([_wasde_farm_price_call()], nv), "single")
    sr = rec["served_rows"]
    assert len(sr) == 1
    assert sr[0]["table"] == "silver_wasde" and sr[0]["metric"] == "avg_farm_price"
    assert sr[0]["row_count"] == 35
    got = {(r["period"], r["estimate_role"], r["value"]) for r in sr[0]["rows"]}
    assert ("2024/25", "actual", 4.24) in got and ("2025/26", "estimate", 4.15) in got
    # D-HP-25 TIGHTENING T2 (2026-08-15, plan 10.30.11(B)): `country` joins the per-ROW projection, and
    # `country` (from the query) joins the per-CALL one. ARTIFACT-ONLY -- no behaviour reads either, and
    # both caps are unchanged (the next test pins `_ROWS_PER_CALL_CAP` and still passes). Without them an
    # offline reader cannot reconstruct what the geo verifier compared against, so M-1's replay and M-3's
    # per-injection labelling would be unfalsifiable from stored artifacts.
    assert all(set(r) == {"period", "estimate_role", "value", "unit", "knowledge_date", "country"}
               for r in sr[0]["rows"])
    assert "country" in sr[0]
    assert rec["numbers_verifier"] == nv


def test_served_rows_are_capped_per_call():
    big = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn"},
           "rows": [{"value": i, "unit": "c/bu", "knowledge_date": "2026-08-06"} for i in range(500)],
           "status": "ok"}
    sr = ev._per_answer_record(_turn([big]), "single")["served_rows"]
    assert sr[0]["row_count"] == 500 and len(sr[0]["rows"]) == ev._ROWS_PER_CALL_CAP == 40


def test_new_artifact_fields_are_strictly_additive():
    """Remove the two CYCLE-5 columns and the record must be the pre-CYCLE-5 record, byte for byte --
    that is the gate-3-comparable-to-gate-2 contract, and it is what makes this instrument safe to add
    mid-wave."""
    import json
    _NEW = ("served_rows", "numbers_verifier")
    rich = ev._per_answer_record(_turn([_wasde_farm_price_call()], {"stated": 2, "rows": 35}), "single")
    bare = ev._per_answer_record(_turn([]), "single")
    # the two new columns are the ONLY difference between a turn with served rows and one without, and
    # every pre-existing column is identical in value, not merely in name
    assert {k: v for k, v in rich.items() if k not in _NEW} == {k: v for k, v in bare.items()
                                                                if k not in _NEW}
    # APPENDED: no pre-existing column moved. The pin is "nothing BEFORE these two moved", never "nothing
    # may ever follow them" -- later waves append their own columns after (D-GD-1 `closure_cited`,
    # 2026-08-08), which is the same additive contract, one wave further along. Extend _LATER, never
    # re-order.
    # D-HP-17/19 (2026-08-13): `dhp_successor` appends after `closure_cited` -- the successor strip-class
    # family, derived per row from `by_rule` beside the OLD family, which is what makes the bridge run a
    # readout rather than a second billed run. Same additive contract, one wave further along.
    # D-HP-21 CLAUSE (2b) (H2, 2026-08-13): `bare_handle_escapes` appends after THAT -- the clause named a
    # number no module produced, so a pre-registered clause of G1 was unreadable from any artifact. Same
    # additive contract, same one-line re-anchor the comment above licenses ("Extend _LATER, never
    # re-order"); nothing before it moved, which is what the second assertion checks.
    _LATER = ("closure_cited", "dhp_successor", "bare_handle_escapes")
    _tail = len(_NEW) + len(_LATER)
    assert list(rich)[-_tail:] == list(_NEW) + list(_LATER)
    assert list(rich)[:-_tail] == list(bare)[:-_tail]
    json.dumps(rich)                                       # the record must still serialize


def test_served_rows_survive_a_malformed_call_record():
    rec = ev._per_answer_record(_turn(["not-a-dict", {"query": None, "rows": None}]), "single")
    assert isinstance(rec["served_rows"], list)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 4 -- STRIP-SPLICE TIDY
#
# The four fragments below are quoted from the gate-2 report bodies (ASCII-folded). Each was left standing
# by a CORRECT whole-sentence strip that removed the sentence in front of it.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

_FRAG_THAT = ("That sits in El Nino territory, not La Nina. The model assigns El Nino a medium-confidence "
              "price-pressuring sign for CBOT corn.")
_FRAG_IF = ("if the ONI crosses into strong El Nino territory (above ~1.5 degC), the drought mechanism "
            "accelerates toward the kharif window.")
_FRAG_WITHIN = "within recent range (five-year low 9.48, five-year high 17.91)."
_FRAG_THE_MODEL = ("The model tags El Nino (positive ONI) as price-pressuring at medium confidence. That "
                   "is the opposite of the La Nina forcing.")


def _seams(*frags) -> dict:
    return {"strip_seams": [{"field": "mechanism", "after": " " + f} for f in frags]}


def test_anaphoric_orphan_sentence_is_removed_and_the_rest_of_the_paragraph_survives():
    d = {"mechanism": "**August specifically.** August governs grain fill.\n\n " + _FRAG_THAT}
    assert an._tidy_strip_orphans(d, _seams(_FRAG_THAT)) == 1
    assert "That sits in El Nino territory" not in d["mechanism"]
    assert "The model assigns El Nino a medium-confidence" in d["mechanism"]
    assert "\n " not in d["mechanism"]                     # the seam's leading space is gone too


def test_lowercase_headless_fragment_carrying_a_claim_numeral_keeps_its_words():
    """SUPERSEDES the builder's `..._bullet_remainder_is_removed_whole` (fix-cycle-2, review major 5).
    `_FRAG_IF` states a figure ('above ~1.5 degC'). A headless opener is evidence about GRAMMAR, never
    about backing, so a fragment carrying a claim numeral is repaired at the seam and KEPT -- deleting it
    would destroy a stated figure the verifier left standing."""
    d = {"mechanism": "## What to watch\n\n " + _FRAG_IF + "\n- **IOD DMI trend**: a negative IOD."}
    assert an._tidy_strip_orphans(d, _seams(_FRAG_IF)) == 1
    assert "if the ONI crosses" in d["mechanism"]           # the words survive...
    assert "\n " + _FRAG_IF not in d["mechanism"]           # ...un-indented: the seam IS repaired
    assert "**IOD DMI trend**" in d["mechanism"]
    assert "\n\n\n" not in d["mechanism"]


def test_a_lazy_list_continuation_is_never_touched():
    """SUPERSEDES the builder's `..._list_continuation_is_removed` (fix-cycle-2, review major 6). A wrapped
    bullet indented 1-3 spaces and opening lower-case is byte-identical to the orphan shape; the only
    discriminator is the preceding line. Removing it left the bullet ending on a colon with nothing under
    it -- the cycle-3 over-removal class in markdown form. INERT is the required answer: `changed == 0`."""
    body = "- Pakistan's urea application fell 8%.\n " + _FRAG_WITHIN + "\n- DAP in June."
    d = {"mechanism": body}
    assert an._tidy_strip_orphans(d, _seams(_FRAG_WITHIN)) == 0
    assert d["mechanism"] == body
    # ...and the colon lead-in form of the same defect, which carries no list marker at all
    body2 = "The balance sheet tightened materially:\n stocks fell hard.\nNext."
    d2 = {"mechanism": body2}
    assert an._tidy_strip_orphans(d2, _seams("stocks fell hard.")) == 0
    assert d2["mechanism"] == body2


def test_forward_referring_prose_keeps_its_sentence_and_only_loses_the_seam_space():
    """RECORDED DEVIATION from the fix brief. The brief lists this gate-2 fragment among those to remove;
    it is not removed. The sentence is complete, forward-referring, grounded and cited -- it lost only its
    bold lead-in to a correct strip on the sentence BEFORE it. Deleting verified content because a
    NEIGHBOUR was convicted is precisely the over-removal class cycle-3's reviewer caught on the "U.S."
    sentence split. The seam is repaired (leading whitespace) and the prose stays."""
    d = {"mechanism": "**The convexity point.** The buffer is thin.\n\n " + _FRAG_THE_MODEL}
    assert an._tidy_strip_orphans(d, _seams(_FRAG_THE_MODEL)) == 1
    assert "The model tags El Nino" in d["mechanism"]
    assert "\n " + _FRAG_THE_MODEL not in d["mechanism"]   # ...but no longer indented
    assert d["mechanism"].endswith(_FRAG_THE_MODEL)


def test_an_identical_fragment_with_no_adjacent_strip_survives_untouched():
    """THE CONSERVATISM PIN: without a recorded seam this pass is a prose editor, so it must do nothing."""
    body = "**August specifically.** August governs grain fill.\n\n " + _FRAG_THAT
    d = {"mechanism": body}
    assert an._tidy_strip_orphans(d, {"strip_seams": []}) == 0
    assert d["mechanism"] == body
    d2 = {"mechanism": body}
    assert an._tidy_strip_orphans(d2, _seams("A completely different sentence about soybean crush.")) == 0
    assert d2["mechanism"] == body


def test_abbreviations_quotes_bullets_and_code_are_never_touched():
    cases = {
        # an initialism inside the orphan: the sentence walk must not cut after "U." or "S."
        "abbrev": " that U.S. corn stocks tightened. The next sentence stands.",
        # a nested list marker is a list, not an orphan
        "nested": "  - a nested bullet that starts lowercase",
        # 4+ leading spaces is an indented code block
        "indent": "    that_looks_like_code(x)",
    }
    d = {"mechanism": "Lead sentence.\n\n" + "\n\n".join(cases.values())}
    before = d["mechanism"]
    an._tidy_strip_orphans(d, _seams(cases["nested"].strip(), cases["indent"].strip()))
    assert cases["nested"] in d["mechanism"] and cases["indent"] in d["mechanism"]
    # the abbreviation case, on its own, with a real seam: only the FIRST sentence goes and "U.S." is
    # never split mid-token
    d2 = {"mechanism": "Lead sentence.\n\n" + cases["abbrev"]}
    an._tidy_strip_orphans(d2, _seams(cases["abbrev"].strip()))
    assert "The next sentence stands." in d2["mechanism"]
    assert "U." not in d2["mechanism"].replace("U.S.", "")
    assert before  # (the multi-case body above is asserted through `d`)


def test_a_quoted_sentence_orphan_keeps_its_quote_intact():
    frag = '"that number is the whole story," the attache wrote. The report also flagged rain.'
    d = {"mechanism": "Lead sentence.\n\n " + frag}
    an._tidy_strip_orphans(d, _seams(frag))
    assert d["mechanism"].count('"') % 2 == 0             # never an unbalanced quote


def test_fenced_code_is_never_edited():
    body = "Lead.\n\n```mermaid\n flowchart LR\n a --> b\n```"
    d = {"mechanism": body}
    an._tidy_strip_orphans(d, _seams("flowchart LR"))
    assert d["mechanism"] == body


def test_the_tidy_cannot_create_or_destroy_a_strip():
    """`_tidy_strip_orphans` reads the report and writes the prose. It must never move a counter."""
    report = {"enabled": True, "stripped": 3, "by_rule": {"number_mismatch": 3}, "checked": 9,
              "claim_count": 20, **_seams(_FRAG_THAT)}
    snapshot = {k: (dict(v) if isinstance(v, dict) else v) for k, v in report.items()}
    d = {"mechanism": "Lead.\n\n " + _FRAG_THAT}
    an._tidy_strip_orphans(d, report)
    assert report["stripped"] == snapshot["stripped"] and report["by_rule"] == snapshot["by_rule"]
    assert report["checked"] == snapshot["checked"] and report["claim_count"] == snapshot["claim_count"]


def test_tidy_is_inert_without_a_report_or_a_structured_dict():
    d = {"mechanism": "Lead.\n\n " + _FRAG_THAT}
    assert an._tidy_strip_orphans(d, None) == 0
    assert an._tidy_strip_orphans(d, {}) == 0
    assert an._tidy_strip_orphans(None, _seams(_FRAG_THAT)) == 0
    assert d["mechanism"].startswith("Lead.")


def test_verify_records_the_seam_after_a_whole_sentence_drop():
    """The producer half: `verify` must record the seam that follows each removal, and record NOTHING when
    it removed nothing.

    SUPERSEDED SHAPE (fix-cycle-2, review major 7): the seam rides the INTERNAL, non-serialized carrier
    `report.strip_seams`, and what it carries is a normalized 40-char KEY, never the raw prose."""
    calls = [{"query": {"table": "silver_noaa_oni", "metric": "oni_anom"},
              "rows": [{"value": 0.98, "unit": "degC"}]}]
    # TWO mismatched numerals in one sentence -> `_num_repair` cannot pick a rewrite, so the whole
    # sentence is dropped (the fail-closed remedy) and the seam this fix reads is created.
    st = {"tldr": "", "mechanism": "The ONI reads 5.55 [N1] against 7.77 today. "
                                   "That sits in El Nino territory.", "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert rep["stripped"] >= 1
    seams = rep.strip_seams
    assert any(s["field"] == "mechanism" and s["key"].startswith("that sits in el nino") for s in seams), \
        seams
    clean = {"tldr": "", "mechanism": "The ONI reads 0.98 [N1] today.", "sources": []}
    assert not vf.verify_citations(clean, [], calls).strip_seams


def test_verify_seam_counters_are_unchanged_by_the_new_field():
    """The FROZEN-SEMANTICS pin: adding `strip_seams` must not move `stripped` / `by_rule` / `claim_count`
    on a body that exercises the whole-sentence-drop path."""
    calls = [{"query": {"table": "silver_noaa_oni", "metric": "oni_anom"},
              "rows": [{"value": 0.98, "unit": "degC"}]}]
    # TWO mismatched numerals in one sentence -> `_num_repair` cannot pick a rewrite, so the whole
    # sentence is dropped (the fail-closed remedy) and the seam this fix reads is created.
    st = {"tldr": "", "mechanism": "The ONI reads 5.55 [N1] against 7.77 today. "
                                   "That sits in El Nino territory.", "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["stripped"] == 1
    assert rep["claim_count"] == 2            # unchanged denominator: _SENT_SPLIT over the ORIGINAL prose


def test_empty_tldr_header_is_dropped_rather_than_rendered_bare():
    """Gate-2 pass 1, `dcw_urea_zscore`: the verifier convicted the only TL;DR sentence and the body
    shipped the literal line '**TL;DR.** ' with nothing under it."""
    md = an.render({"tldr": "   ", "mechanism": "## Mechanism\n\nThe key distinction is level vs z-score."})
    assert "TL;DR" not in md
    assert md.startswith("**Why.**")
    # ...and a TL;DR with content renders exactly as before
    md2 = an.render({"tldr": "Urea is not expensive.", "mechanism": "Body."})
    assert md2 == "**TL;DR.** Urea is not expensive.\n\n**Why.** Body."


def test_orphan_tidy_trace_key_is_registered_as_an_artifact_column():
    assert "prose_orphans_tidied" in tk.TRACE_RECORD_KEYS


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# FIX-CYCLE-2 (2026-08-07) -- one pin per finding the adversarial review closed.
#
# Every scenario below is the reviewer's, re-stated against the corrected semantics. Where the probe and
# the fix disagreed about which CONFIGURATION was being asserted (adv-1, the A2b headline kill-switch) the
# pin here is the stricter one: it asserts BOTH flag states rather than the default.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

# -- BLOCKER 1: the cap must rank NEWEST-first --------------------------------------------------------

def _wasde_with_clustered_history(extra: list) -> dict:
    """The 35-row serve plus older marketing years whose prints CLUSTER near the stated figures -- the
    ordinary shape of a 35-marketing-year price history, and the shape that filled the 6-row cap first."""
    call = _wasde_farm_price_call()
    call["rows"] = [{"value": v, "unit": "$/bu", "period": p, "knowledge_date": "2026-07-10",
                     "revision_stamp": "actual"} for p, v in extra] + call["rows"]
    return call


def test_the_extra_row_cap_ranks_newest_first_and_never_evicts_the_stated_rows():
    call = _wasde_with_clustered_history([("1997/98", 4.13), ("1998/99", 4.17), ("2007/08", 4.20),
                                          ("2008/09", 4.26), ("2009/10", 4.22), ("2011/12", 4.14)])
    labels = [c.label for c in cit.unify(None, [call], stated=orc._stated_values(_FARM_PRICE_PROSE))]
    assert any("MY2025/26" in x for x in labels), labels
    assert any("MY2024/25" in x for x in labels), labels


def test_the_cap_survivors_still_render_in_ascending_period_order():
    """Ranking is newest-first; RENDER order stays chronological, so the footer still reads as a series."""
    call = _wasde_with_clustered_history([("2019/20", 4.15), ("2020/21", 4.24), ("2021/22", 4.15)])
    cits = cit.unify(None, [call], stated=orc._stated_values(_FARM_PRICE_PROSE))
    periods = [c.label.split(" MY")[1].split(" ")[0] for c in cits if c.id != "N1" and " MY" in c.label]
    assert periods == sorted(periods), periods
    ids = [c.id for c in cits]
    assert ids[0] == "N1" and ids[1:] == [f"N1{s}" for s in cit._EXTRA_SUFFIXES[:len(ids) - 1]]


# -- BLOCKER 2: an extra row is a claim of IDENTITY, not of backing ------------------------------------

def test_a_stated_percentage_never_mints_a_price_footer_row():
    prose = _FARM_PRICE_PROSE + "\n\nThat is down 2.1% year on year."
    cits = cit.unify(None, [_wasde_farm_price_call()], stated=orc._stated_values(prose))
    assert not [c.label for c in cits if c.id != "N1" and " 2.1 " in c.label]
    # ...and the extraction still HANDS the banner that magnitude: only the footer's narrower reader drops it
    assert 2.1 in orc._stated_values(prose) and 2.1 in orc._stated_values(prose).percent


def test_a_rescaled_magnitude_never_mints_a_footer_row():
    """'250 cents per bushel' is the same FACT as $2.50 and `_num_matches` says so -- correctly, for the
    caution banner. It is not evidence that the MY2002/03 row is the row the prose named."""
    cits = cit.unify(None, [_wasde_farm_price_call()],
                     stated=orc._stated_values("US corn is near 250 cents per bushel on the old crop."))
    assert [c.id for c in cits] == ["N1"]


def test_extras_match_at_scale_one_to_two_decimals_only():
    assert cit._row_matches_value(4.15, [4.15]) and cit._row_matches_value("4.150", [4.15])
    assert cit._row_matches_value(-0.479, [0.479])          # magnitude only, the estate-wide convention
    assert not cit._row_matches_value(4.15, [415.0])        # no x100 arm
    assert not cit._row_matches_value(4.15, [4.1])          # no 1% band


def test_an_extra_row_never_duplicates_the_headline_line():
    """A vintage table legitimately serves one (period, value) on two releases; the de-dup set is seeded
    with the HEADLINE's own key so the twin cannot re-render the line already on the page."""
    call = {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": "corn",
                      "country": "united_states", "asof": "2026-08-07"},
            "rows": [{"value": 4.4, "unit": "$/bu", "period": "2026/27", "knowledge_date": "2026-06-11",
                      "revision_stamp": "projection"},
                     {"value": 4.4, "unit": "$/bu", "period": "2026/27", "knowledge_date": "2026-07-10",
                      "revision_stamp": "projection"}],
            "status": "ok"}
    assert [c.id for c in cit.unify(None, [call], stated=[4.4])] == ["N1"]


# -- BLOCKER 3: the two synthetic mint sites agree, and both stamp the LATER endpoint ------------------

def _oni_era_leg() -> dict:
    """A year_month ERA leg in the shape `_headline_row`'s own A2b RCA documents: agg='series', six
    ascending monthly rows, Jan..Jun 2012. rows[0] is the OLDEST print."""
    return {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "corn",
                      "period": "2012-01-01..2012-06-01", "asof": "2013-01-01"},
            "rows": [{"value": v, "unit": "degC", "year": 2012, "month": m}
                     for m, v in zip(range(1, 7), (-0.72, -0.60, -0.45, -0.30, -0.10, 0.06))],
            "status": "ok"}


def test_a_derived_delta_row_is_stamped_at_the_LATER_endpoint():
    """The Jun-minus-Jan delta could not have been known in January. Asserted under BOTH states of the A2b
    headline kill-switch: `_headline_row` returns rows[0] when the switch is off (its default, and every
    production configuration shipped to date), so routing the mint site through it would have left the
    false January stamp exactly where it was."""
    for flag in (False, True):
        cq._set_headline(flag)
        try:
            call = cq._delta_call(_oni_era_leg(), {"metric": "oni_anom", "narrate_unit": "degC",
                                                   "scale": 1}, 0.78, 5, kind="delta")
            assert cit.from_number(call, 5).date == "2012-06", flag
        finally:
            cq._set_headline(False)


def test_the_delta_and_pace_mint_sites_use_ONE_endpoint_rule():
    rec = _oni_era_leg()
    assert cq._endpoint_row(rec) is rec["rows"][-1]          # the freshest print, by `_row_order_key`
    d = cq._delta_call(rec, {"metric": "oni_anom", "narrate_unit": "degC"}, 0.78, 5, kind="delta")
    p = cq._pace_synth(rec, {"metric": "oni_anom"}, 5, 5, kind="pace_streak", unit="months")
    assert d["rows"][0]["year"] == p["rows"][0]["year"] == 2012
    assert d["rows"][0]["month"] == p["rows"][0]["month"] == 6


def test_an_unkeyed_ascending_series_still_resolves_the_pace_endpoint_to_the_LAST_row():
    """`_row_order_key` spans no `week_ending_date`, so every ESR pace leg ties on all of it. Bare max()
    would return rows[0]; row POSITION is the documented final tiebreaker and keeps the pace twin's
    pre-CYCLE-5 answer byte-identical."""
    rec = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
           "rows": [{"value": i, "week_ending_date": f"2026-0{i}-01"} for i in (1, 2, 3)], "status": "ok"}
    assert cq._endpoint_row(rec) is rec["rows"][-1]


def test_a_rowless_record_mints_no_vintage_at_all():
    assert cq._endpoint_row({"rows": []}) == {} and cq._endpoint_row(None) == {}


# -- BLOCKER 4: `n_cascade_rows` keeps its pre-CYCLE-5 meaning -----------------------------------------

def test_footer_extras_do_not_move_the_n_cascade_rows_baseline_column():
    """PRE == POST on the motivating row: the column counts CALLS, and a letter-suffixed sibling row is
    not a call."""
    call = _wasde_farm_price_call()
    pre = [c.model_dump() for c in cit.unify(None, [call])]
    post = [c.model_dump() for c in cit.unify(None, [call],
                                              stated=orc._stated_values(_FARM_PRICE_PROSE))]
    assert len(pre) == 1 and len(post) == 3                  # the extras DO reach the reader...
    out_pre = {"citations": pre, "structured": None, "trace": {}}
    out_post = {"citations": post, "structured": None, "trace": {}}
    assert ev._cascade_stats(out_pre)["n_rows"] == ev._cascade_stats(out_post)["n_rows"] == 1
    # ...and the un-narrowed list is still what the row-surface readers (eod/PIT) see
    assert len(ev._num_citations(out_post)) == 3


def test_call_grained_filter_keeps_integer_ids_and_drops_suffixed_ones():
    out = {"citations": [{"kind": "number", "id": "N1"}, {"kind": "number", "id": "N1b"},
                         {"kind": "number", "id": "N12"}, {"kind": "number", "id": "N12c"},
                         {"kind": "evidence", "id": "E1"}]}
    assert [c["id"] for c in ev._call_grained_citations(out)] == ["N1", "N12"]


# -- MAJOR 5 / 6: the tidy pass deletes only genuinely contentless continuations -----------------------

def test_tidy_keeps_a_backed_cited_orphan_sentence():
    seam = " it fell to 1.32 billion bushels [N3], the tightest carryout since 2013. Basis firmed."
    d = {"tldr": "", "mechanism": "Old crop cleared.\n\n" + seam}
    an._tidy_strip_orphans(d, {"strip_seams": [{"field": "mechanism", "after": seam}]})
    assert "1.32 billion bushels [N3]" in d["mechanism"] and "Basis firmed." in d["mechanism"]


def test_tidy_still_removes_a_genuinely_contentless_continuation():
    """The polarity check on major 5's fence: no handle, no claim numeral -> still deleted, so the fix is
    a NARROWING, not a disabling."""
    d = {"mechanism": "**August specifically.** August governs grain fill.\n\n " + _FRAG_THAT}
    assert an._tidy_strip_orphans(d, _seams(_FRAG_THAT)) == 1
    assert "That sits in El Nino territory" not in d["mechanism"]
    assert "The model assigns El Nino a medium-confidence" in d["mechanism"]


def test_a_handle_alone_is_enough_content_to_spare_a_fragment():
    seam = " that one [N2] carried the whole move."
    d = {"mechanism": "Lead sentence here.\n\n" + seam}
    an._tidy_strip_orphans(d, {"strip_seams": [{"field": "mechanism", "after": seam}]})
    assert "[N2]" in d["mechanism"]


# -- MAJOR 7: no raw prose on the wire, and the tidy join still works with the gate OFF ----------------

def test_strip_seams_ships_nothing_to_the_client_unless_audited(monkeypatch):
    import json
    monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    calls = [{"query": {"table": "silver_noaa_oni", "metric": "oni_anom"},
              "rows": [{"value": 0.98, "unit": "degC"}]}]
    st = {"tldr": "", "mechanism": "The ONI reads 5.55 [N1] against 7.77 today. Our internal desk view "
                                   "is that this is cheap and you should be long.", "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert rep["stripped"] > 0
    assert "strip_audit" not in rep and "strip_seams" not in rep
    assert "desk view" not in json.dumps(rep)               # nothing reaches trace.citation_verifier
    assert rep.strip_seams                                  # ...while the internal join carrier is live


def test_the_audited_seam_record_is_a_normalized_key_not_prose(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    calls = [{"query": {"table": "silver_noaa_oni", "metric": "oni_anom"},
              "rows": [{"value": 0.98, "unit": "degC"}]}]
    st = {"tldr": "", "mechanism": "The ONI reads 5.55 [N1] against 7.77 today. "
                                   "That sits in El Nino territory, and it is a long way from over.",
          "sources": []}
    seams = vf.verify_citations(st, [], calls)["strip_seams"]
    # H1 FOLD ROUND 3 (FIX X2): the record gained a PRODUCER TAG. The point of this pin is unchanged and
    # is asserted on the line below -- the seam carries a bounded, normalized KEY and never raw prose --
    # and the shape is still CLOSED, so a fourth key cannot appear unnoticed. `src` is an enumerated
    # producer name, so it leaks nothing either (`answer._SEAM_SRC_*`).
    assert seams and all(set(s) == {"field", "key", "src"} for s in seams)
    assert all(s["src"] == "verify" for s in seams)         # the only producer inside verify itself
    assert all(len(s["key"]) <= vf._SEAM_KEY_CHARS and s["key"] == s["key"].lower() for s in seams)


def test_the_tidy_join_still_fires_off_the_internal_carrier_with_the_gate_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    calls = [{"query": {"table": "silver_noaa_oni", "metric": "oni_anom"},
              "rows": [{"value": 0.98, "unit": "degC"}]}]
    st = {"tldr": "", "mechanism": "Lead sentence stands.\n\nThe ONI reads 5.55 [N1] against 7.77 today. "
                                   "That sits in El Nino territory, not La Nina.", "sources": []}
    rep = vf.verify_citations(st, [], calls)
    assert an._report_seams(rep), "the internal carrier is what the renderer joins on"
    an._tidy_strip_orphans(st, rep)                          # reads the carrier; never raises


def test_the_report_is_still_a_plain_dict_to_every_consumer():
    import json
    rep = vf.verify_citations({"tldr": "", "mechanism": "Nothing cited here.", "sources": []}, [], [])
    assert isinstance(rep, dict) and json.dumps(rep)
    assert "strip_seams" not in dict(rep)


# -- MINOR 11 / 12: the artifact projection's bounds and its alias fallback ----------------------------

def test_served_rows_are_capped_per_RECORD_not_only_per_call():
    big = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn"},
           "rows": [{"value": i, "unit": "c/bu"} for i in range(500)], "status": "ok"}
    sr = ev._per_answer_record(_turn([dict(big) for _ in range(20)]), "single")["served_rows"]
    assert len(sr) == 20                                     # every call still records its header...
    assert sum(len(r["rows"]) for r in sr) == ev._ROWS_PER_RECORD_CAP == 400
    assert all(r["row_count"] == 500 for r in sr)            # ...and row_count carries the hidden truth


def test_a_present_but_None_alias_falls_back_to_the_raw_column():
    call = {"query": {"table": "silver_wasde", "metric": "avg_farm_price"},
            "rows": [{"value": 4.15, "period": "2025/26", "revision_stamp": None,
                      "estimate_role": "estimate", "knowledge_date": None, "data_date": "2026-07-10"}],
            "status": "ok"}
    row = ev._per_answer_record(_turn([call]), "single")["served_rows"][0]["rows"][0]
    assert row["estimate_role"] == "estimate" and row["knowledge_date"] == "2026-07-10"
